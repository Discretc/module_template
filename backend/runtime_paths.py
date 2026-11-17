"""Read-only bundle resources and optional desktop writable storage.

Without the desktop launcher all defaults retain the web deployment's paths.
"""
import os
from pathlib import Path
import sys


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def writable_path(default: Path, *parts: str) -> Path:
    setting = os.environ.get("MODULE_OUTLINE_DATA_DIR")
    if not setting:
        return default
    root = Path(setting)
    if not root.is_absolute():
        raise ValueError("MODULE_OUTLINE_DATA_DIR must be absolute")
    return root.joinpath(*parts)
