"""Command-line entry point. With no subcommand it opens the interactive picker."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, backup
from .inventory import Inventory, logged_in, scan
from .paths import ClaudePaths
from .procs import claude_running
from .reset import ResetPlan, Selection, UnknownSelection, apply_reset, plan_reset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-cleaner",
        description="Reset Claude Code to factory defaults, keeping your login and the "
                    "MCP servers, plugins and skills you pick.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", help="pick what to keep in a terminal UI (the default)")

    p = sub.add_parser("scan", help="list installed MCP servers, plugins and skills")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser("reset", help="reset without the UI")
    p.add_argument("--keep-mcp", action="append", default=[], metavar="NAME",
                   help="MCP server to keep (repeatable); local-scope servers are "
                        "NAME@/project/path, as shown by 'scan'")
    p.add_argument("--keep-plugin", action="append", default=[], metavar="NAME@MARKETPLACE",
                   help="plugin to keep (repeatable)")
    p.add_argument("--keep-skill", action="append", default=[], metavar="NAME",
                   help="skill folder to keep (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="show the plan and change nothing")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    sub.add_parser("backups", help="list backups")

    p = sub.add_parser("restore", help="put a backup back in place")
    p.add_argument("archive", nargs="?", type=Path, help="backup to restore (default: latest)")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    return parser


def main(argv: list[str] | None = None, paths: ClaudePaths | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = paths or ClaudePaths.detect()
    command = args.command or "tui"
    if command == "tui":
        from .tui import run
        return run(paths)
    if command == "scan":
        return cmd_scan(paths, args.json)
    if command == "reset":
        return cmd_reset(paths, args)
    if command == "backups":
        return cmd_backups(paths)
    return cmd_restore(paths, args)


def cmd_scan(paths: ClaudePaths, as_json: bool) -> int:
    inv = scan(paths)
    if as_json:
        print(json.dumps(inv.to_dict(), indent=2))
        return 0
    print(f"Config folder: {paths.config_dir}")
    print(f"Logged in:     {'yes' if logged_in(paths, inv.global_config) else 'not detected'}")
    print(f"\nMCP servers ({len(inv.mcp_servers)})")
    for s in inv.mcp_servers:
        print(f"  {s.key}  [{s.scope}]  {s.summary}")
    print(f"\nPlugins ({len(inv.plugins)})")
    for p in inv.plugins:
        state = "enabled" if p.enabled else "disabled"
        print(f"  {p.key}  {p.version}  [{state}]  {p.description}")
    print(f"\nSkills ({len(inv.skills)})")
    for s in inv.skills:
        print(f"  {s.name}  {s.description}")
    return 0


def describe_plan(plan: ResetPlan) -> str:
    inv = plan.inventory
    lines = ["Keeping:", "  your login (credentials and account entry)"]
    lines += [f"  MCP server  {s.key}" for s in plan.kept_mcp]
    lines += [f"  plugin      {p.key}" for p in plan.kept_plugins]
    lines += [f"  skill       {s.name}" for s in plan.kept_skills]
    lines.append("")
    lines.append(f"Deleting ({len(plan.delete)}):")
    lines += [f"  {display(p, inv.paths)}" for p in plan.delete]
    lines.append("")
    lines.append(f"Rewriting ({len(plan.write)}):")
    lines += [f"  {display(p, inv.paths)}" for p in plan.write]
    return "\n".join(lines)


def display(path: Path, paths: ClaudePaths) -> str:
    try:
        return "~/" + path.relative_to(paths.home).as_posix()
    except ValueError:
        return str(path)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def progress_printer():
    """A progress callback that redraws one line per step on a terminal, and stays silent
    when stderr is not one (so logs do not fill up with carriage returns)."""
    if not sys.stderr.isatty():
        return None
    last = {"step": None, "time": 0.0}

    def show(step: str, done: int, total: int) -> None:
        now = time.monotonic()
        if step == last["step"] and now - last["time"] < 0.1 and done < total:
            return
        if last["step"] not in (None, step):
            print(file=sys.stderr)
        last.update(step=step, time=now)
        if step == "backup":
            text = f"Backing up  {human_bytes(done)} of {human_bytes(total)}"
        else:
            text = f"Deleting    {done} of {total} items"
        percent = done * 100 // max(total, 1)
        print(f"\r{text}  {percent:3d}%\033[K", end="", file=sys.stderr, flush=True)
        if done >= total:
            print(file=sys.stderr)
            last["step"] = None

    return show


def cmd_reset(paths: ClaudePaths, args: argparse.Namespace) -> int:
    inv: Inventory = scan(paths)
    selection = Selection(set(args.keep_mcp), set(args.keep_plugin), set(args.keep_skill))
    try:
        plan = plan_reset(inv, selection)
    except UnknownSelection as exc:
        print(f"error: {exc}. Run 'claude-cleaner scan' to see what is installed.",
              file=sys.stderr)
        return 2
    print(describe_plan(plan))
    if args.dry_run:
        print("\nDry run: nothing was changed.")
        return 0
    if not logged_in(paths, inv.global_config) and sys.platform != "darwin":
        print("\nwarning: no login found; you will need to sign in again afterwards.")
    if claude_running():
        print("\nwarning: Claude Code is running. Quit every Claude Code session first.")
    if not args.yes and not confirm("\nBack up and reset now?"):
        print("Cancelled.")
        return 1
    print()
    archive = apply_reset(plan, progress=progress_printer())
    print(f"Done. Backup: {archive}")
    print("Undo with: claude-cleaner restore")
    return 0


def cmd_backups(paths: ClaudePaths) -> int:
    found = backup.list_backups(paths)
    if not found:
        print(f"No backups in {paths.backup_dir}")
    for archive in found:
        print(archive)
    return 0


def cmd_restore(paths: ClaudePaths, args: argparse.Namespace) -> int:
    archive = args.archive
    if archive is None:
        found = backup.list_backups(paths)
        if not found:
            print(f"error: no backups in {paths.backup_dir}", file=sys.stderr)
            return 2
        archive = found[-1]
    try:
        manifest = backup.read_manifest(archive)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: cannot read {archive}: {exc}", file=sys.stderr)
        return 2
    print(f"Restoring {archive} (made {manifest.get('created', '?')}).")
    print("This replaces your current Claude Code settings; they are backed up first.")
    if claude_running():
        print("warning: Claude Code is running. Quit every Claude Code session first.")
    if not args.yes and not confirm("Restore now?"):
        print("Cancelled.")
        return 1
    show = progress_printer()
    safety = backup.restore(archive, paths,
                            progress=(lambda done, total: show("backup", done, total)) if show else None)
    print(f"Restored. Your state from just before is in {safety}")
    return 0


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False
