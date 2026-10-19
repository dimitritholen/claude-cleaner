"""Where Claude Code keeps its user-level state."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClaudePaths:
    """Resolved locations of Claude Code's user-level files.

    ``config_dir`` is ``~/.claude`` unless ``CLAUDE_CONFIG_DIR`` is set.
    ``global_config`` is ``~/.claude.json``, or ``$CLAUDE_CONFIG_DIR/.claude.json``
    when the config dir is overridden. ``plugins_dir`` is ``<config_dir>/plugins`` unless
    ``CLAUDE_CODE_PLUGIN_CACHE_DIR`` is set.
    """

    home: Path
    config_dir: Path
    plugins_dir: Path
    global_config: Path
    legacy_global_config: Path
    cache_dirs: tuple[Path, ...]
    backup_dir: Path

    @classmethod
    def detect(cls, home: Path | None = None, env: dict[str, str] | None = None,
               platform: str | None = None) -> "ClaudePaths":
        env = dict(os.environ) if env is None else env
        home = Path(home) if home is not None else Path.home()
        platform = platform or sys.platform

        override = env.get("CLAUDE_CONFIG_DIR")
        if override:
            config_dir = Path(override).expanduser()
            global_config = config_dir / ".claude.json"
        else:
            config_dir = home / ".claude"
            global_config = home / ".claude.json"

        plugins_override = env.get("CLAUDE_CODE_PLUGIN_CACHE_DIR")
        return cls(
            home=home,
            config_dir=config_dir,
            plugins_dir=Path(plugins_override).expanduser() if plugins_override
            else config_dir / "plugins",
            global_config=global_config,
            legacy_global_config=config_dir / ".config.json",
            cache_dirs=_cache_dirs(home, env, platform),
            backup_dir=home / ".claude-cleaner" / "backups",
        )


def _cache_dirs(home: Path, env: dict[str, str], platform: str) -> tuple[Path, ...]:
    """Claude Code's log cache (MCP server logs, debug logs), per OS."""
    name = "claude-cli-nodejs"
    if platform == "darwin":
        return (home / "Library" / "Caches" / name,)
    if platform.startswith("win"):
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return (base / name,)
    xdg = env.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else home / ".cache"
    return (base / name,)
