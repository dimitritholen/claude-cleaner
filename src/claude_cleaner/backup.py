"""Timestamped tar.gz backups of Claude Code's user-level state, and restoring them."""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from . import __version__
from .fsutil import is_within, remove
from .paths import ClaudePaths

PREFIX = "claude-backup-"
# Never archived or deleted: the legacy per-user install of the claude binary.
SKIP_DIRS = ("local",)


def _roots(paths: ClaudePaths) -> dict[str, Path]:
    roots = {"config_dir": paths.config_dir}
    if not is_within(paths.plugins_dir, paths.config_dir):
        roots["plugins_dir"] = paths.plugins_dir
    return roots


def _files(paths: ClaudePaths) -> dict[str, Path]:
    files = {}
    if not is_within(paths.global_config, paths.config_dir):
        files["global_config.json"] = paths.global_config
    return files


def create(paths: ClaudePaths, now: datetime | None = None) -> Path:
    """Write a backup archive and return its path. The archive holds login tokens, so it
    is readable by the current user only."""
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(paths.backup_dir, 0o700)
    except OSError:
        pass
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    archive = paths.backup_dir / f"{PREFIX}{stamp}.tar.gz"
    n = 1
    while archive.exists():
        n += 1
        archive = paths.backup_dir / f"{PREFIX}{stamp}-{n}.tar.gz"

    manifest = {
        "tool": "claude-cleaner",
        "version": __version__,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "roots": {k: str(v) for k, v in _roots(paths).items()},
        "files": {k: str(v) for k, v in _files(paths).items()},
    }
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
        data = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        info.mtime = int(datetime.now().timestamp())
        tar.addfile(info, io.BytesIO(data))
        for name, root in _roots(paths).items():
            if root.is_dir():
                for child in sorted(root.iterdir()):
                    if name == "config_dir" and child.name in SKIP_DIRS:
                        continue
                    if is_within(paths.backup_dir, child):
                        continue
                    tar.add(child, arcname=f"{name}/{child.name}", recursive=True)
        for name, path in _files(paths).items():
            if path.exists():
                tar.add(path, arcname=name)
    return archive


def list_backups(paths: ClaudePaths) -> list[Path]:
    if not paths.backup_dir.is_dir():
        return []
    return sorted(paths.backup_dir.glob(f"{PREFIX}*.tar.gz"), key=lambda p: p.stat().st_mtime)


def read_manifest(archive: Path) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile("manifest.json")
        if member is None:
            raise ValueError(f"{archive} is not a claude-cleaner backup")
        return json.load(member)


def restore(archive: Path, paths: ClaudePaths) -> Path:
    """Replace the current state with the archive's contents.

    The current state is backed up first; that safety backup's path is returned.
    """
    read_manifest(archive)  # fail early on a foreign archive
    safety = create(paths)

    roots = _roots(paths)
    for name, root in roots.items():
        if root.is_dir():
            for child in root.iterdir():
                if name == "config_dir" and child.name in SKIP_DIRS:
                    continue
                if is_within(paths.backup_dir, child):
                    continue
                remove(child)
    for path in _files(paths).values():
        if path.exists() or path.is_symlink():
            remove(path)

    # Unpack next to the backups first, then move into place, so links inside the
    # archive resolve the same way they did when it was written.
    staging = Path(tempfile.mkdtemp(prefix="restore-", dir=paths.backup_dir))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            if hasattr(tarfile, "tar_filter"):
                # "tar" keeps absolute symlinks (skills are often linked in from elsewhere)
                # while still refusing members that would land outside the staging folder.
                tar.extractall(staging, filter="tar")
            else:  # Python without extraction filters
                tar.extractall(staging)
        for name, root in roots.items():
            src = staging / name
            if src.is_dir():
                root.mkdir(parents=True, exist_ok=True)
                for child in src.iterdir():
                    shutil.move(str(child), str(root / child.name))
        for name, path in _files(paths).items():
            src = staging / name
            if src.exists() or src.is_symlink():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(path))
    finally:
        remove(staging)
    return safety
