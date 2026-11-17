"""Local administrator verifier. No shared secret, plaintext or browser session."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import unquote

from werkzeug.security import check_password_hash, generate_password_hash


class AdministratorCredentials:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._failures = 0
        self._blocked_until = 0.0

    def exists(self) -> bool:
        if self.path.exists():
            self._read()  # Corruption must fail closed, never trigger setup.
            return True
        return False

    def _read(self) -> str:
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            value = record["password_hash"]
            if record["version"] != 1 or not isinstance(value, str) or not value.startswith("scrypt:32768:8:1$"):
                raise ValueError()
            if len(value.split("$")) != 3 or not value.split("$")[1] or len(value.split("$")[2]) != 128:
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError("Administrator credentials cannot be read. Use Reset Administrator to establish a new password.") from None

    def establish(self, password: str, *, reset: bool = False) -> None:
        if not 12 <= len(password) <= 256:
            raise ValueError("Choose a password or passphrase between 12 and 256 characters.")
        if self.path.exists() and not reset:
            raise RuntimeError("Administrator is already configured.")
        record = {"version": 1, "password_hash": generate_password_hash(password, method="scrypt:32768:8:1")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def authenticate(self, authorization: str) -> bool:
        # A distinct scheme preserves the hosted Bearer-token contract. Percent
        # encoding transports Unicode passphrases through ASCII HTTP headers.
        with self._lock:
            if time.monotonic() < self._blocked_until:
                return False
            if not authorization.startswith("Desktop ") or len(authorization) > 3200:
                return False
            try:
                password = unquote(authorization[8:], errors="strict")
                valid = 12 <= len(password) <= 256 and check_password_hash(self._read(), password)
            except (UnicodeError, ValueError, RuntimeError):
                valid = False
            if valid:
                self._failures = 0
            else:
                self._failures += 1
                if self._failures >= 5:
                    self._blocked_until = time.monotonic() + 30
                    self._failures = 0
            return bool(valid)
