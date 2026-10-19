"""Best-effort check for a running Claude Code process."""

from __future__ import annotations

import os
import subprocess


def claude_running() -> bool:
    """True if a process named ``claude`` is running. npm installs run as ``node`` and
    are not detected, so callers still warn the user to quit Claude Code first."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=10).stdout
            names = [line.split(",")[0].strip('"').lower() for line in out.splitlines()]
            return "claude.exe" in names
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True,
                             timeout=10).stdout
        return any(os.path.basename(line.strip()) == "claude" for line in out.splitlines())
    except (OSError, subprocess.SubprocessError):
        return False
