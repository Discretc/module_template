"""Coordinate template readers and all-or-nothing activation across workers.

The journal restores an interrupted transaction before any cooperating reader
can see the templates. Backups are retained independently of staging cleanup.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from uuid import uuid4

LANGUAGES = ("en", "zh", "pt")
_MUTEX = threading.RLock()
_LOCAL = threading.local()


def _sync_directory(directory: Path) -> None:
    """Persist rename/unlink ordering on the Linux filesystems used by hosting."""
    if os.name != "nt":
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_copy(source: Path, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(prefix=".template-copy-", dir=destination.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, destination)
        _sync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _recover(directory: Path) -> None:
    journal = directory.parent / ".template-transaction.json"
    if journal.exists():
        backup_id = json.loads(journal.read_text())["backup_id"]
        if len(backup_id) != 32 or any(c not in "0123456789abcdef" for c in backup_id):
            raise ValueError("Invalid template recovery journal")
        backup = directory.parent / ".template-backups" / backup_id
        # Never start restoring an incomplete backup. Keep the journal on any
        # error so readers fail closed and a later recovery can retry.
        if not all((backup / f"template_{lang}.docx").is_file() for lang in LANGUAGES):
            raise RuntimeError("Template recovery backup is incomplete")
        for lang in LANGUAGES:
            name = f"template_{lang}.docx"
            _atomic_copy(backup / name, directory / name)
        journal.unlink()
        _sync_directory(directory.parent)


@contextmanager
def template_lock(directory: Path):
    """Serialize readers/activation, with crash recovery and reentrant locking."""
    directory = Path(directory).resolve()
    with _MUTEX:
        held = getattr(_LOCAL, "held", set())
        if directory in held:
            yield
            return
        directory.parent.mkdir(parents=True, exist_ok=True)
        with (directory.parent / ".template-update.lock").open("a+b") as stream:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            _LOCAL.held = held | {directory}
            try:
                _recover(directory)
                _cleanup_temporary_files(directory)
                yield
            finally:
                _LOCAL.held = held
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def activate_templates(staged: Path, directory: Path) -> str:
    """Back up all three files, then commit or restore the complete set."""
    directory = Path(directory).resolve()
    with template_lock(directory):
        backup_id = uuid4().hex
        backup = directory.parent / ".template-backups" / backup_id
        backup.mkdir(parents=True)
        _sync_directory(backup.parent)
        _sync_directory(directory.parent)
        for lang in LANGUAGES:
            name = f"template_{lang}.docx"
            _atomic_copy(directory / name, backup / name)
        journal = directory.parent / ".template-transaction.json"
        journal_source = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", prefix=".template-journal-", dir=directory.parent, delete=False) as tmp:
                journal_source = Path(tmp.name)
                json.dump({"backup_id": backup_id}, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(journal_source, journal)
            _sync_directory(directory.parent)
        finally:
            if journal_source is not None:
                journal_source.unlink(missing_ok=True)
        try:
            for lang in LANGUAGES:
                name = f"template_{lang}.docx"
                _atomic_copy(staged / name, directory / name)
            journal.unlink()  # Commit. Backups remain available for administrators.
            _sync_directory(directory.parent)
        except BaseException:
            _recover(directory)
            raise
        return backup_id


def _cleanup_temporary_files(directory: Path) -> None:
    """Called under the shared lock; no cooperating upload can still be staging."""
    root = directory.parent
    for staging in root.glob(".template-stage-*"):
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
    for parent in (root, directory, *root.glob(".template-backups/*")):
        for pattern in (".template-copy-*", ".template-journal-*"):
            for temporary in parent.glob(pattern):
                temporary.unlink(missing_ok=True)


def configured_template_directory(bundled: Path) -> Path:
    """Seed a dedicated persistent store once; never replace an existing set.

    The operator must mount persistent storage here. A directory name alone
    cannot establish durability across container replacement.
    """
    setting = os.environ.get("TEMPLATE_STORAGE_DIR", "")
    if not setting:
        return bundled
    root = Path(setting)
    if not root.is_absolute():
        raise ValueError("TEMPLATE_STORAGE_DIR must be an absolute persistent-storage path")
    root = root.resolve()
    frontend = bundled.parent.parent / "frontend"
    for forbidden in (frontend.resolve(), bundled.resolve()):
        if root == forbidden or forbidden in root.parents or root in forbidden.parents:
            raise ValueError("TEMPLATE_STORAGE_DIR must be a dedicated directory outside static and bundled templates")
    directory = root / "templates"
    if directory.resolve() != directory:
        raise ValueError("Persistent templates directory must not be a symbolic link")
    with template_lock(directory):
        directory.mkdir(exist_ok=True)
        paths = [directory / f"template_{lang}.docx" for lang in LANGUAGES]
        if all(path.is_file() and not path.is_symlink() for path in paths):
            return directory
        if any(directory.iterdir()):
            raise RuntimeError("Persistent template set is incomplete; restore it from backup before starting")
        # An interruption during initial seeding leaves a partial set that must
        # be repaired explicitly, rather than silently mixing template versions.
        for path in paths:
            _atomic_copy(bundled / path.name, path)
        _sync_directory(root)
    return directory
