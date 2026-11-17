"""Desktop lifecycle, storage, single-instance coordination and loopback WSGI."""
import errno
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler, Request
import webbrowser
import zipfile

from desktop_auth import AdministratorCredentials


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def validate_resources(root: Path) -> None:
    for relative in ("frontend/index.html", "backend/schema.sql", "backend/seed.sql"):
        path = root / relative
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise RuntimeError(f"Application resource is missing or empty: {relative}. Extract the complete application ZIP again.")
    for language in ("en", "zh", "pt"):
        relative = f"backend/templates/template_{language}.docx"
        try:
            with zipfile.ZipFile(root / relative) as archive:
                if archive.testzip() or "word/document.xml" not in archive.namelist():
                    raise ValueError()
        except (OSError, ValueError, zipfile.BadZipFile):
            raise RuntimeError(f"Application template is missing or damaged: {relative}. Extract the complete application ZIP again.") from None


def data_directory(override: str | None = None) -> Path:
    if override:
        root = Path(override).expanduser().resolve()
    else:
        local = os.environ.get("LOCALAPPDATA")
        if os.name == "nt" and not local:
            raise RuntimeError("Windows local application data is unavailable. Sign in to your Windows account and try again.")
        root = ((Path(local) if local else Path.home() / ".local" / "share") / "ModuleOutlineGenerator").resolve()
    if getattr(sys, "frozen", False):
        distribution = Path(sys.executable).resolve().parent
        if root == distribution or distribution in root.parents:
            raise RuntimeError("Application data must be stored outside the extracted program folder.")
    return root


def prepare_storage(root: Path) -> None:
    for name in ("data", "templates", ".template-backups", "output", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    # Verify permissions early, without opening or replacing the user's DB.
    import tempfile
    for directory in (root, *(root / name for name in ("data", "templates", ".template-backups", "output", "logs"))):
        with tempfile.TemporaryFile(dir=directory):
            pass


def configure_logging(root: Path) -> None:
    handler = RotatingFileHandler(root / "logs" / "desktop.log", maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


class InstanceLock:
    """The OS releases this lock after crashes; stale state cannot lock users out."""
    def __init__(self, root: Path):
        self.root = root
        self.stream = None

    def acquire(self) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        stream = (self.root / ".desktop.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        self.stream = stream
        # We own the lock: discard a previous process's stale address.
        (self.root / "instance.json").unlink(missing_ok=True)
        return True

    def release(self) -> None:
        if self.stream is not None:
            (self.root / "instance.json").unlink(missing_ok=True)
            self.stream.close()
            self.stream = None


_HTTP = build_opener(ProxyHandler({}))


def healthy(url: str, nonce: str, timeout: float = 0.5) -> bool:
    try:
        req = Request(url + "/_desktop/health", headers={"X-Desktop-Instance": nonce})
        with _HTTP.open(req, timeout=timeout) as response:
            return response.status == 200 and json.load(response) == {"ready": True}
    except (OSError, ValueError):
        return False


def existing_instance(root: Path, timeout: float = 3.0) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads((root / "instance.json").read_text(encoding="utf-8"))
            url, nonce = state["url"], state["nonce"]
            if (re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", url)
                    and re.fullmatch(r"[0-9a-f]{64}", nonce) and healthy(url, nonce)):
                return url
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(0.1)
    return None


def create_application(root: Path, credentials: AdministratorCredentials):
    # These are launcher-owned, so inherited web deployment settings cannot
    # redirect desktop writes into the distribution or enable a shared token.
    os.environ["MODULE_OUTLINE_DESKTOP"] = "1"
    os.environ["MODULE_OUTLINE_DATA_DIR"] = str(root)
    os.environ["TEMPLATE_STORAGE_DIR"] = str(root)
    import app as application
    application.app.config.update(
        DESKTOP_ADMIN_AUTHENTICATOR=credentials.authenticate,
        TEMPLATE_ADMIN_TOKEN="", DEBUG=False, TESTING=False,
    )
    return application.app


class LocalRequests:
    """Reject foreign origins/hosts and serialize Windows SQLite replacement.

    The same lock lets shutdown wait for any active import/update/generation.
    """
    def __init__(self, application, host: str, nonce: str):
        self.application, self.host, self.nonce = application, host, nonce
        self.lock = threading.RLock()
        self.accepting = True

    def __call__(self, environ, start_response):
        with self.lock:
            host = environ.get("HTTP_HOST", "")
            origin = environ.get("HTTP_ORIGIN")
            foreign = origin is not None and origin != "http://" + self.host
            cross_write = (environ.get("HTTP_SEC_FETCH_SITE") == "cross-site"
                           and environ.get("REQUEST_METHOD") not in ("GET", "HEAD", "OPTIONS"))
            if host != self.host or foreign or cross_write:
                start_response("403 Forbidden", [("Content-Type", "text/plain")])
                yield b"Use the local application browser window."
            elif not self.accepting:
                start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
                yield b"Application is stopping."
            elif environ.get("PATH_INFO") == "/_desktop/health":
                authenticated = secrets.compare_digest(environ.get("HTTP_X_DESKTOP_INSTANCE", "").encode(), self.nonce.encode())
                start_response("200 OK" if authenticated else "403 Forbidden", [("Content-Type", "application/json"), ("Cache-Control", "no-store")])
                yield b'{"ready": true}' if authenticated else b'{}'
            else:
                iterable = self.application(environ, start_response)
                try:
                    yield from iterable
                finally:
                    if hasattr(iterable, "close"):
                        iterable.close()

    def drain(self):
        with self.lock:
            self.accepting = False


def bind_loopback(preferred_port: int = 5001) -> socket.socket:
    for port in (preferred_port, 0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
            return sock
        except OSError:
            sock.close()
            if port == 0:
                raise RuntimeError("Cannot open a local port. Check local security settings and try again.") from None
    raise RuntimeError("Cannot open a local port.")


class DesktopServer:
    def __init__(self, application, root: Path, preferred_port: int = 5001):
        self.root, self.application, self.preferred_port = root, application, preferred_port
        self.nonce = secrets.token_hex(32)
        self.server = self.thread = self.gate = None
        self.url = None

    def start(self, *, open_browser: bool = True, timeout: float = 30.0) -> str:
        from waitress import create_server
        sock = bind_loopback(self.preferred_port)
        self.url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        self.gate = LocalRequests(self.application, self.url[7:], self.nonce)
        try:
            self.server = create_server(self.gate, sockets=[sock], threads=4,
                                        asyncore_loop_timeout=0.1)
            self.thread = threading.Thread(target=self.server.run, name="local-wsgi", daemon=True)
            self.thread.start()
            deadline = time.monotonic() + timeout
            while not healthy(self.url, self.nonce):
                if not self.thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("The local server did not become ready. Please restart the application.")
                time.sleep(0.05)
            state = {"url": self.url, "nonce": self.nonce}
            temporary = self.root / ".instance.tmp"
            temporary.write_text(json.dumps(state), encoding="utf-8")
            os.replace(temporary, self.root / "instance.json")
            logging.info("Local server ready at %s", self.url)
            if open_browser:
                launch_browser(self.url)
            return self.url
        except BaseException:
            self.stop()
            sock.close()
            raise

    def stop(self) -> None:
        if self.server is None:
            return
        # Wait for file transactions before tearing down workers or sockets.
        self.gate.drain()
        self.server.task_dispatcher.shutdown(timeout=10)
        self.server.close()
        from waitress import wasyncore
        wasyncore.close_all(self.server._map)
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.server = None
        (self.root / "instance.json").unlink(missing_ok=True)
        logging.info("Local server stopped")


def launch_browser(url: str) -> bool:
    try:
        opened = bool(webbrowser.open(url))
    except Exception:
        opened = False
    if not opened:
        logging.warning("Browser could not be opened automatically; use Open Browser or the displayed local address")
    return opened
