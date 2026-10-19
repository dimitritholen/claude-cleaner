"""Small filesystem helpers that never follow symlinks when deleting."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


def norm(path: Path | str) -> str:
    """A comparable form of a path (absolute, case-folded on Windows, symlinks kept)."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_within(path: Path | str, parent: Path | str) -> bool:
    p, root = norm(path), norm(parent)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def remove(path: Path) -> None:
    """Delete a file, symlink or directory tree. A symlink is unlinked, never followed."""
    if path.is_symlink() or not path.is_dir():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
        return
    if os.name == "nt" and _is_junction(path):
        os.rmdir(path)
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:
        shutil.rmtree(path, onerror=_clear_readonly)


def tree_size(path: Path) -> int:
    """Bytes of regular files under ``path`` (what tar counts), without following links."""
    try:
        if path.is_symlink() or not path.is_dir():
            return path.stat().st_size if path.is_file() and not path.is_symlink() else 0
    except OSError:
        return 0
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total


def _is_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _clear_readonly(func: Any, path: str, _exc: Any) -> None:
    # Windows refuses to delete read-only files; clear the flag and retry once.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace ``path`` with ``data`` as indented JSON, keeping its permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
