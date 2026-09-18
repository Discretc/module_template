"""Focused persistence, process-interruption and cross-worker regressions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_generator import ROOT
import template_storage as storage


class PersistentTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bundled = self.root / "application" / "backend" / "templates"
        self.bundled.mkdir(parents=True)
        self.store = self.root / "persistent"
        self.active = self.store / "templates"
        self.env = patch.dict(os.environ, TEMPLATE_STORAGE_DIR=str(self.store))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.write_set(self.bundled, b"original")

    def write_set(self, directory, content):
        directory.mkdir(parents=True, exist_ok=True)
        for lang in storage.LANGUAGES:
            (directory / f"template_{lang}.docx").write_bytes(content)

    def snapshot(self):
        return [p.read_bytes() for p in sorted(self.active.glob("*.docx"))]

    def process(self, code, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))
        return subprocess.run([sys.executable, "-c", code, *map(str, args)], env=env,
                              capture_output=True, text=True, timeout=20)

    def test_unconfigured_uses_bundled_without_creating_store(self):
        with patch.dict(os.environ, TEMPLATE_STORAGE_DIR=""):
            self.assertEqual(self.bundled, storage.configured_template_directory(self.bundled))
        self.assertFalse(self.store.exists())

    def test_seed_once_and_preserve_updates_across_restart_and_new_release(self):
        self.assertEqual(self.active, storage.configured_template_directory(self.bundled))
        staged = self.root / "staged"
        self.write_set(staged, b"faculty update")
        backup_id = storage.activate_templates(staged, self.active)
        # A different application release has different bundled templates.
        self.write_set(self.bundled, b"new release defaults")
        for _ in range(2):
            result = self.process('''import sys
from pathlib import Path
from template_storage import configured_template_directory
active = configured_template_directory(Path(sys.argv[1]))
assert all(p.read_bytes() == b"faculty update" for p in active.glob("*.docx"))
''', self.bundled)
            self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"original", (self.store / ".template-backups" / backup_id / "template_en.docx").read_bytes())

    def test_generator_uses_external_templates_after_fresh_process(self):
        # Use real DOCX files to check the reader path as well as storage setup.
        for lang in storage.LANGUAGES:
            shutil.copyfile(ROOT / "backend/templates" / f"template_{lang}.docx",
                            self.bundled / f"template_{lang}.docx")
        storage.configured_template_directory(self.bundled)
        result = self.process('''import generator
from pathlib import Path
import os
assert generator.TEMPLATE_DIR == Path(os.environ["TEMPLATE_STORAGE_DIR"]) / "templates"
assert all(path.parent == generator.TEMPLATE_DIR for path in generator.TEMPLATES.values())
assert generator._render_one({"rule_code": 1}, "en").startswith(b"PK")
''')
        self.assertEqual(0, result.returncode, result.stderr)

    def test_admin_token_loaded_from_environment_without_default(self):
        for value in ("", "environment-only-test-secret"):
            with patch.dict(os.environ, TEMPLATE_ADMIN_TOKEN=value, TEMPLATE_STORAGE_DIR=""):
                result = self.process('''import app, os
assert app.app.config["TEMPLATE_ADMIN_TOKEN"] == os.environ["TEMPLATE_ADMIN_TOKEN"]
response = app.app.test_client().post("/api/templates/convert")
assert response.status_code == (503 if not os.environ["TEMPLATE_ADMIN_TOKEN"] else 401)
assert "environment-only-test-secret" not in response.get_data(as_text=True)
''')
            self.assertEqual(0, result.returncode, result.stderr)

    def test_relative_and_public_storage_paths_rejected(self):
        for path in ("relative", self.bundled, self.bundled.parent.parent / "frontend/store", self.bundled.parent.parent):
            with self.subTest(path=path), patch.dict(os.environ, TEMPLATE_STORAGE_DIR=str(path)):
                with self.assertRaises(ValueError):
                    storage.configured_template_directory(self.bundled)

    def test_symlink_cannot_redirect_active_templates_to_public_directory(self):
        public = self.bundled.parent.parent / "frontend"
        public.mkdir()
        self.store.mkdir()
        self.active.symlink_to(public, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            storage.configured_template_directory(self.bundled)
        self.assertEqual([], list(public.iterdir()))

    def test_partial_existing_store_is_not_silently_reseeded(self):
        self.active.mkdir(parents=True)
        (self.active / "template_en.docx").write_bytes(b"important update")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            storage.configured_template_directory(self.bundled)
        self.assertEqual(b"important update", (self.active / "template_en.docx").read_bytes())
        self.assertFalse((self.active / "template_zh.docx").exists())

    def test_backup_failure_does_not_modify_active_set(self):
        storage.configured_template_directory(self.bundled)
        staged = self.root / "staged"
        self.write_set(staged, b"new")
        real = storage._atomic_copy
        def fail(source, destination):
            if ".template-backups" in str(destination) and destination.name == "template_zh.docx":
                raise OSError("disk failure")
            return real(source, destination)
        with patch.object(storage, "_atomic_copy", side_effect=fail):
            with self.assertRaises(OSError):
                storage.activate_templates(staged, self.active)
        self.assertEqual([b"original"] * 3, self.snapshot())
        self.assertFalse((self.store / ".template-transaction.json").exists())

    def test_actual_process_death_and_interrupted_recovery_can_retry(self):
        storage.configured_template_directory(self.bundled)
        staged = self.root / "staged"
        self.write_set(staged, b"new")
        result = self.process('''import os, sys
from pathlib import Path
import template_storage as s
active, staged = map(Path, sys.argv[1:])
real = s._atomic_copy
def crash(source, destination):
    real(source, destination)
    if source.parent == staged and destination.name == "template_en.docx":
        os._exit(77)
s._atomic_copy = crash
s.activate_templates(staged, active)
''', self.active, staged)
        self.assertEqual(77, result.returncode, result.stderr)
        self.assertTrue((self.store / ".template-transaction.json").exists())
        self.assertIn(b"new", self.snapshot())
        # Kill recovery itself after restoring its first file.
        result = self.process('''import os, sys
from pathlib import Path
import template_storage as s
active = Path(sys.argv[1])
real = s._atomic_copy
def crash(source, destination):
    real(source, destination)
    os._exit(78)
s._atomic_copy = crash
with s.template_lock(active):
    pass
''', self.active)
        self.assertEqual(78, result.returncode, result.stderr)
        result = self.process('''import sys
from pathlib import Path
from template_storage import template_lock
active = Path(sys.argv[1])
with template_lock(active):
    assert all(p.read_bytes() == b"original" for p in active.glob("*.docx"))
''', self.active)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.store / ".template-transaction.json").exists())

    def test_missing_recovery_backup_blocks_readers_and_retains_journal(self):
        storage.configured_template_directory(self.bundled)
        journal = self.store / ".template-transaction.json"
        journal.write_text(json.dumps({"backup_id": "a" * 32}))
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            with storage.template_lock(self.active):
                self.fail("Readers must not see an unrecovered set")
        self.assertTrue(journal.exists())
        self.assertEqual([b"original"] * 3, self.snapshot())

    def test_orphan_staging_and_atomic_files_cleaned_on_restart(self):
        storage.configured_template_directory(self.bundled)
        orphan = self.store / ".template-stage-orphan"
        orphan.mkdir()
        (orphan / "official_en.docx").write_bytes(b"private upload")
        for directory in (self.store, self.active):
            (directory / ".template-copy-orphan").write_bytes(b"private temporary")
        (self.store / ".template-journal-orphan").write_bytes(b"unfinished journal")
        storage.configured_template_directory(self.bundled)
        self.assertFalse(orphan.exists())
        self.assertFalse(list(self.store.rglob(".template-copy-*")))
        self.assertFalse(list(self.store.glob(".template-journal-*")))

    @unittest.skipIf(os.name == "nt", "POSIX process locking used by cloud deployment")
    def test_two_process_updates_are_serialized_as_complete_sets(self):
        storage.configured_template_directory(self.bundled)
        stages = [self.root / "stage-a", self.root / "stage-b"]
        for stage, content in zip(stages, (b"A", b"B")):
            self.write_set(stage, content)
        code = '''import sys, time
from pathlib import Path
import template_storage as s
active, staged = map(Path, sys.argv[1:])
real = s._atomic_copy
def slow(source, destination):
    real(source, destination)
    if source.parent == staged:
        time.sleep(0.1)
s._atomic_copy = slow
with s.template_lock(active):
    s.activate_templates(staged, active)
    assert len({p.read_bytes() for p in active.glob("*.docx")}) == 1
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))
        processes = [subprocess.Popen([sys.executable, "-c", code, str(self.active), str(stage)],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for stage in stages]
        try:
            for process in processes:
                _, error = process.communicate(timeout=20)
                self.assertEqual(0, process.returncode, error)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        backups = list((self.store / ".template-backups").iterdir())
        self.assertEqual(2, len(backups))
        for backup in backups:
            self.assertEqual(1, len({p.read_bytes() for p in backup.glob("*.docx")}))
        self.assertEqual(1, len(set(self.snapshot())))

    def test_runtime_and_recovery_artifacts_are_git_ignored(self):
        names = ["template-storage/templates/template_en.docx", "custom/.template-backups/id/template_en.docx",
                 "custom/.template-stage-id/official_en.docx", "custom/.template-transaction.json",
                 "custom/.template-update.lock", "custom/templates/.template-copy-id", "custom/.template-journal-id"]
        result = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(names) + "\n",
                                cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(names, result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
