"""Desktop boundaries: resources, credentials, loopback lifecycle, persistence."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from desktop_auth import AdministratorCredentials
import desktop_runtime as desktop
import runtime_paths


class DesktopStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Desktop 測試 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_frozen_and_source_resource_discovery_independent_of_cwd(self):
        self.assertEqual(ROOT, desktop.resource_root())
        self.assertEqual(ROOT / "backend/schema.sql", runtime_paths.resource_path("backend", "schema.sql"))
        with patch.object(sys, "_MEIPASS", str(self.root), create=True):
            self.assertEqual(self.root, desktop.resource_root())
            self.assertEqual(self.root / "frontend/index.html", runtime_paths.resource_path("frontend", "index.html"))

    def test_complete_bundle_validates_and_missing_or_damaged_resources_fail(self):
        desktop.validate_resources(ROOT)
        bundled = self.root / "_internal"
        (bundled / "frontend").mkdir(parents=True)
        (bundled / "backend/templates").mkdir(parents=True)
        for name in ("frontend/index.html", "backend/schema.sql", "backend/seed.sql",
                     *(f"backend/templates/template_{lang}.docx" for lang in ("en", "zh", "pt"))):
            shutil.copyfile(ROOT / name, bundled / name)
        desktop.validate_resources(bundled)
        (bundled / "backend/templates/template_pt.docx").write_bytes(b"damaged")
        with self.assertRaisesRegex(RuntimeError, "damaged"):
            desktop.validate_resources(bundled)
        (bundled / "frontend/index.html").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            desktop.validate_resources(bundled)

    def test_writable_layout_and_explicit_local_appdata(self):
        desktop.prepare_storage(self.root)
        for name in ("data", "templates", ".template-backups", "output", "logs"):
            self.assertTrue((self.root / name).is_dir())
        with patch.dict(os.environ, LOCALAPPDATA=str(self.root)):
            self.assertEqual((self.root / "ModuleOutlineGenerator").resolve(), desktop.data_directory())
        with patch.dict(os.environ, MODULE_OUTLINE_DATA_DIR=str(self.root)):
            self.assertEqual(self.root / "data/test.db", runtime_paths.writable_path(Path("unused"), "data", "test.db"))
        with patch.dict(os.environ, MODULE_OUTLINE_DATA_DIR="relative"):
            with self.assertRaises(ValueError):
                runtime_paths.writable_path(Path("unused"), "data")

    def test_frozen_data_directory_cannot_write_inside_distribution(self):
        executable = self.root / "Program" / "ModuleOutlineGenerator.exe"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            with self.assertRaisesRegex(RuntimeError, "outside"):
                desktop.data_directory(str(executable.parent / "_internal" / "data"))

    def test_first_run_seeds_once_and_preserves_deliberately_empty_database(self):
        # Fresh processes prove real importer/generator paths are configured
        # before Flask's import-time initialization, including a different cwd.
        code = '''
from pathlib import Path
import sys
from desktop_auth import AdministratorCredentials
from desktop_runtime import create_application, prepare_storage
root = Path(sys.argv[1]).resolve()
prepare_storage(root)
app = create_application(root, AdministratorCredentials(root/'data/administrator.json'))
import database, generator, import_excel
assert database.DB_PATH == import_excel.DB_PATH == root/'data/module_outlines.db'
assert generator.OUTPUT_DIR == root/'output'
assert generator.TEMPLATE_DIR == root/'templates'
assert app.static_folder.endswith('frontend')
with database.get_connection() as conn:
    count = conn.execute('SELECT COUNT(*) FROM classes').fetchone()[0]
    if sys.argv[2] == 'first':
        assert count > 0
        conn.execute('DELETE FROM classes')
        conn.execute('DELETE FROM programmes')
        conn.execute('DELETE FROM faculties')
    else:
        assert count == 0, 'An existing empty DB was silently re-seeded'
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / "backend"))))
        for mode in ("first", "again"):
            result = subprocess.run([sys.executable, "-c", code, str(self.root), mode], cwd=self.root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_lock_rejects_duplicate_and_releases_for_next_launch(self):
        first, second = desktop.InstanceLock(self.root), desktop.InstanceLock(self.root)
        self.assertTrue(first.acquire())
        try:
            self.assertFalse(second.acquire())
            second.release()  # A duplicate must never remove the owner's state.
            (self.root / "instance.json").write_text("{}")
        finally:
            first.release()
        self.assertFalse((self.root / "instance.json").exists())
        self.assertTrue(second.acquire())
        second.release()

    def test_untrusted_or_stale_instance_address_is_never_opened(self):
        (self.root / "instance.json").write_text(json.dumps({"url": "https://untrusted.example", "nonce": "a" * 64}))
        with patch.object(desktop, "healthy") as probe:
            self.assertIsNone(desktop.existing_instance(self.root, timeout=0.01))
            probe.assert_not_called()


class DesktopAdministratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.credentials = AdministratorCredentials(self.root / "administrator.json")
        self.password = "Only my local secret 測試"

    def header(self, password=None):
        return "Desktop " + quote(password or self.password, safe="")

    def test_first_run_salted_hash_unicode_authentication_and_explicit_reset(self):
        self.assertFalse(self.credentials.exists())
        with self.assertRaises(ValueError):
            self.credentials.establish("short")
        self.credentials.establish(self.password)
        saved = self.credentials.path.read_text(encoding="utf-8")
        self.assertNotIn(self.password, saved)
        self.assertTrue(self.credentials.authenticate(self.header()))
        self.assertFalse(self.credentials.authenticate("Bearer " + self.password))
        self.assertFalse(self.credentials.authenticate(self.header("a different password")))
        with self.assertRaises(RuntimeError):
            self.credentials.establish("replacement password")
        self.credentials.establish("replacement password", reset=True)
        self.assertFalse(self.credentials.authenticate(self.header()))
        self.assertTrue(self.credentials.authenticate(self.header("replacement password")))
        other = AdministratorCredentials(self.root / "other.json")
        other.establish("replacement password")
        self.assertNotEqual(other.path.read_bytes(), self.credentials.path.read_bytes())

    def test_corrupt_or_missing_verifier_never_authenticates(self):
        self.assertFalse(self.credentials.authenticate(self.header()))
        for content in ("not json", '{"version": 2}', '{"version": 1, "password_hash": "plaintext"}'):
            self.credentials.path.write_text(content)
            with self.assertRaises(RuntimeError):
                self.credentials.exists()
            self.assertFalse(self.credentials.authenticate(self.header()))
        self.credentials.establish(self.password, reset=True)
        self.assertTrue(self.credentials.authenticate(self.header()))

    def test_failed_attempts_have_a_cooldown(self):
        self.credentials.establish(self.password)
        with patch("desktop_auth.time.monotonic", return_value=100):
            for _ in range(5):
                self.assertFalse(self.credentials.authenticate(self.header("wrong password")))
            self.assertFalse(self.credentials.authenticate(self.header()))
        with patch("desktop_auth.time.monotonic", return_value=131):
            self.assertTrue(self.credentials.authenticate(self.header()))

    def test_failed_password_reset_preserves_existing_verifier(self):
        self.credentials.establish(self.password)
        original = self.credentials.path.read_bytes()
        with patch("desktop_auth.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.credentials.establish("replacement password", reset=True)
        self.assertEqual(original, self.credentials.path.read_bytes())
        self.assertEqual([self.credentials.path], list(self.root.iterdir()))

    def test_masked_first_run_prompt_confirms_password(self):
        from desktop_launcher import ask_password
        with patch("tkinter.simpledialog.askstring", side_effect=[self.password, "mismatch", self.password, self.password]) as prompt, patch("tkinter.messagebox.showerror") as error:
            self.assertTrue(ask_password(None, self.credentials))
            error.assert_called_once()
            self.assertTrue(all(call.kwargs["show"] == "*" for call in prompt.call_args_list))
        self.assertTrue(self.credentials.authenticate(self.header()))

    def test_cancelled_explicit_reset_keeps_password(self):
        from desktop_launcher import ask_password
        self.credentials.establish(self.password)
        original = self.credentials.path.read_bytes()
        with patch("tkinter.messagebox.askyesno", return_value=False), patch("tkinter.simpledialog.askstring") as prompt:
            self.assertFalse(ask_password(None, self.credentials, reset=True))
            prompt.assert_not_called()
        self.assertEqual(original, self.credentials.path.read_bytes())
        with patch("tkinter.messagebox.askyesno", return_value=True), patch("tkinter.simpledialog.askstring", return_value=None):
            self.assertFalse(ask_password(None, self.credentials, reset=True))
        self.assertEqual(original, self.credentials.path.read_bytes())

    def test_headless_mode_cannot_bypass_first_run_setup(self):
        from argparse import Namespace
        from desktop_launcher import run_headless
        with self.assertRaisesRegex(RuntimeError, "existing administrator verifier"):
            run_headless(self.root, self.credentials, Namespace(reset_admin=False))

    def test_template_endpoint_requires_local_password_without_exposing_it(self):
        import app
        self.credentials.establish(self.password)
        with patch.dict(app.app.config, DESKTOP_ADMIN_AUTHENTICATOR=self.credentials.authenticate,
                        TEMPLATE_ADMIN_TOKEN="hosted-token", TEMPLATE_STORAGE_CONFIGURED=True), patch.object(app, "update_templates", return_value="backup") as update:
            client = app.app.test_client()
            for header in ("", "Bearer hosted-token", self.header("incorrect password")):
                response = client.post("/api/templates/convert", headers={"Authorization": header})
                self.assertEqual(401, response.status_code)
            update.assert_not_called()
            response = client.post("/api/templates/convert", headers={"Authorization": self.header()})
            self.assertEqual(200, response.status_code)
            update.assert_called_once()
            for path in ("/", "/api/runtime"):
                with client.get(path) as response:
                    self.assertNotIn(self.password, response.get_data(as_text=True))
                    self.assertNotIn("password_hash", response.get_data(as_text=True))
            with patch.object(app, "DATABASE_STARTUP_ERROR", "Review required"):
                self.assertEqual({"desktop": True}, client.get("/api/runtime").json)


class DesktopServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def application(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"Application"]

    def test_port_conflict_falls_back_to_a_free_loopback_port(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with desktop.bind_loopback(occupied.getsockname()[1]) as chosen:
                self.assertEqual("127.0.0.1", chosen.getsockname()[0])
                self.assertNotEqual(occupied.getsockname()[1], chosen.getsockname()[1])

    def test_no_available_port_fails_with_friendly_message(self):
        with patch.object(socket.socket, "bind", side_effect=OSError("permission denied")):
            with self.assertRaisesRegex(RuntimeError, "Cannot open a local port"):
                desktop.bind_loopback()

    def test_browser_opens_after_readiness_and_duplicate_uses_verified_server(self):
        server = desktop.DesktopServer(self.application, self.root, preferred_port=0)
        self.addCleanup(server.stop)
        def open_browser(url):
            self.assertTrue(desktop.healthy(url, server.nonce))
            return True
        with patch.object(desktop, "launch_browser", side_effect=open_browser) as browser:
            url = server.start()
            browser.assert_called_once_with(url)
        self.assertEqual(url, desktop.existing_instance(self.root))
        server.stop()
        self.assertFalse(desktop.healthy(url, server.nonce))
        self.assertFalse((self.root / "instance.json").exists())

    def test_readiness_failure_does_not_open_browser_and_releases_sockets(self):
        server = desktop.DesktopServer(self.application, self.root, preferred_port=0)
        with patch.object(desktop, "healthy", return_value=False), patch.object(desktop, "launch_browser") as browser:
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                server.start(timeout=0.01)
            browser.assert_not_called()
        self.assertIsNone(server.server)

    def test_browser_failure_keeps_the_application_running(self):
        with patch("desktop_runtime.webbrowser.open", side_effect=OSError("No browser")):
            self.assertFalse(desktop.launch_browser("http://127.0.0.1:5001"))

    def test_foreign_host_origin_and_cross_site_upload_are_blocked(self):
        from werkzeug.test import Client
        gate = desktop.LocalRequests(self.application, "127.0.0.1:5001", "nonce")
        client = Client(gate)
        self.assertEqual(200, client.get("/", base_url="http://127.0.0.1:5001").status_code)
        self.assertEqual(403, client.get("/", base_url="http://attacker.example:5001").status_code)
        self.assertEqual(403, client.post("/", base_url="http://127.0.0.1:5001", headers={"Origin": "https://attacker.example"}).status_code)
        self.assertEqual(403, client.post("/", base_url="http://127.0.0.1:5001", headers={"Sec-Fetch-Site": "cross-site"}).status_code)
        self.assertEqual(200, client.post("/", base_url="http://127.0.0.1:5001", headers={"Origin": "http://127.0.0.1:5001"}).status_code)

    def test_shutdown_waits_for_active_file_operations(self):
        from werkzeug.test import Client
        entered, finish, drained = threading.Event(), threading.Event(), threading.Event()
        def operation(environ, start_response):
            entered.set()
            finish.wait(timeout=5)
            return self.application(environ, start_response)
        gate = desktop.LocalRequests(operation, "127.0.0.1:5001", "nonce")
        worker = threading.Thread(target=lambda: Client(gate).post("/api/generate", base_url="http://127.0.0.1:5001"))
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        stopper = threading.Thread(target=lambda: (gate.drain(), drained.set()))
        stopper.start()
        try:
            self.assertFalse(drained.wait(timeout=0.05))
        finally:
            finish.set()
            worker.join(timeout=5)
            stopper.join(timeout=5)
        self.assertTrue(drained.is_set())
        self.assertEqual(503, Client(gate).post("/", base_url="http://127.0.0.1:5001").status_code)


if __name__ == "__main__":
    unittest.main()
