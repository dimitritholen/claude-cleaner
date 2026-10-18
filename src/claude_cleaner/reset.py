"""Work out what a reset keeps and deletes, then carry it out."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import backup
from .fsutil import is_within, norm, remove, write_json
from .inventory import Inventory, split_plugin_key

# Keys in ~/.claude.json that belong to the signed-in account. Everything else in that
# file (theme, UI toggles, project history, trust decisions, caches) is dropped.
# The onboarding flags are kept so Claude Code does not walk through first-run setup
# (and its login step) again; installMethod tells the auto-updater how it was installed.
ACCOUNT_KEYS = (
    "oauthAccount",
    "primaryApiKey",
    "customApiKeyResponses",
    "userID",
    "hasCompletedOnboarding",
    "lastOnboardingVersion",
    "installMethod",
)

# Entries directly inside the config dir that a reset never touches.
ALWAYS_KEEP = (
    ".credentials.json",  # login tokens on Linux and Windows (macOS uses the Keychain)
    "local",  # legacy per-user install of the claude binary
)


@dataclass
class Selection:
    """What the user chose to keep. MCP servers use ``McpServer.key``, plugins use
    ``name@marketplace`` and skills use their folder name."""

    mcp_servers: set[str] = field(default_factory=set)
    plugins: set[str] = field(default_factory=set)
    skills: set[str] = field(default_factory=set)


@dataclass
class ResetPlan:
    inventory: Inventory
    selection: Selection
    delete: list[Path] = field(default_factory=list)
    write: dict[Path, dict[str, Any]] = field(default_factory=dict)
    keep: list[Path] = field(default_factory=list)

    @property
    def kept_mcp(self):
        return [s for s in self.inventory.mcp_servers if s.key in self.selection.mcp_servers]

    @property
    def kept_plugins(self):
        return [p for p in self.inventory.plugins if p.key in self.selection.plugins]

    @property
    def kept_skills(self):
        return [s for s in self.inventory.skills if s.name in self.selection.skills]


class UnknownSelection(ValueError):
    pass


def plan_reset(inv: Inventory, selection: Selection) -> ResetPlan:
    _check_selection(inv, selection)
    paths = inv.paths
    plan = ResetPlan(inv, selection)

    plan.write.update(_plugin_files(plan))
    settings = _settings(plan)
    if settings:
        plan.write[paths.config_dir / "settings.json"] = settings

    global_config = _global_config(plan)
    target = paths.global_config
    if not target.exists() and paths.legacy_global_config.exists():
        target = paths.legacy_global_config
    if global_config:
        plan.write[target] = global_config
    elif target.exists():
        plan.delete.append(target)

    protected = [paths.config_dir / name for name in ALWAYS_KEEP]
    protected += [s.path for s in plan.kept_skills]
    protected += _kept_plugin_dirs(plan)
    plan.keep = [p for p in protected if p.exists() or p.is_symlink()]

    keep_set = {norm(p) for p in plan.keep} | {norm(p) for p in plan.write}
    for root in _clean_roots(paths):
        if root.is_dir():
            plan.delete += _walk(root, keep_set)
    plan.delete += [d for d in paths.cache_dirs if d.exists() or d.is_symlink()]
    return plan


def _check_selection(inv: Inventory, selection: Selection) -> None:
    unknown = []
    unknown += [f"MCP server {k!r}" for k in selection.mcp_servers - {s.key for s in inv.mcp_servers}]
    unknown += [f"plugin {k!r}" for k in selection.plugins - {p.key for p in inv.plugins}]
    unknown += [f"skill {k!r}" for k in selection.skills - {s.name for s in inv.skills}]
    if unknown:
        raise UnknownSelection("Not installed: " + ", ".join(sorted(unknown)))


def _walk(directory: Path, keep: set[str]) -> list[Path]:
    """Everything under ``directory`` that is not kept and has no kept path inside it."""
    doomed = []
    for child in sorted(directory.iterdir()):
        key = norm(child)
        if key in keep:
            continue
        holds_kept = any(is_within(k, child) for k in keep)
        if holds_kept and child.is_dir() and not child.is_symlink():
            doomed += _walk(child, keep)
        else:
            doomed.append(child)
    return doomed


def _global_config(plan: ResetPlan) -> dict[str, Any]:
    old = plan.inventory.global_config
    new = {k: copy.deepcopy(old[k]) for k in ACCOUNT_KEYS if k in old}
    user = {s.name: s.config for s in plan.kept_mcp if s.scope == "user"}
    if user:
        new["mcpServers"] = copy.deepcopy(user)
    projects: dict[str, Any] = {}
    for s in plan.kept_mcp:
        if s.scope == "local":
            entry = projects.setdefault(s.project, {"mcpServers": {}})
            entry["mcpServers"][s.name] = copy.deepcopy(s.config)
    if projects:
        new["projects"] = projects
    return new


def _settings(plan: ResetPlan) -> dict[str, Any]:
    old = plan.inventory.settings
    kept = plan.kept_plugins
    if not kept:
        return {}
    marketplaces = {p.marketplace for p in kept}
    enabled = old.get("enabledPlugins") or {}
    new: dict[str, Any] = {"enabledPlugins": {p.key: enabled.get(p.key, True) for p in kept}}
    extra = {k: v for k, v in (old.get("extraKnownMarketplaces") or {}).items() if k in marketplaces}
    if extra:
        new["extraKnownMarketplaces"] = copy.deepcopy(extra)
    configs = {k: v for k, v in (old.get("pluginConfigs") or {}).items()
               if k in {p.key for p in kept}}
    if configs:
        new["pluginConfigs"] = copy.deepcopy(configs)
    return new


def _plugin_files(plan: ResetPlan) -> dict[Path, dict[str, Any]]:
    kept = plan.kept_plugins
    if not kept:
        return {}
    inv = plan.inventory
    root = inv.paths.plugins_dir
    keys = {p.key for p in kept}
    marketplaces = {p.marketplace for p in kept}
    installed = inv.installed_plugins
    files = {
        root / "installed_plugins.json": {
            "version": installed.get("version", 2),
            "plugins": {k: copy.deepcopy(v) for k, v in (installed.get("plugins") or {}).items()
                        if k in keys},
        },
    }
    known = {k: copy.deepcopy(v) for k, v in inv.known_marketplaces.items() if k in marketplaces}
    if known:
        files[root / "known_marketplaces.json"] = known
    return files


def _data_dir_name(plugin_key: str) -> str:
    name, marketplace = split_plugin_key(plugin_key)
    return re.sub(r"[^A-Za-z0-9_-]", "-", f"{name}-{marketplace}" if marketplace else name)


def _kept_plugin_dirs(plan: ResetPlan) -> list[Path]:
    root = plan.inventory.paths.plugins_dir
    dirs: list[Path] = []
    for p in plan.kept_plugins:
        dirs += list(p.install_paths)
        dirs.append(root / "cache" / p.marketplace / p.name)
        dirs.append(root / "data" / _data_dir_name(p.key))
        dirs.append(root / "marketplaces" / p.marketplace)
        location = (plan.inventory.known_marketplaces.get(p.marketplace) or {}).get("installLocation")
        if location:
            dirs.append(Path(location))
    # Only paths inside the folders we clean matter; anything outside is never touched.
    roots = _clean_roots(plan.inventory.paths)
    return [d for d in dirs if any(is_within(d, r) for r in roots)]


def _clean_roots(paths) -> list[Path]:
    """The folders a reset empties out (except for what is kept)."""
    roots = [paths.config_dir]
    if not is_within(paths.plugins_dir, paths.config_dir):
        roots.append(paths.plugins_dir)
    return roots


def apply_reset(plan: ResetPlan, *, make_backup: bool = True) -> Path | None:
    """Back up, delete, then write the rebuilt files. Returns the backup archive path."""
    archive = backup.create(plan.inventory.paths) if make_backup else None
    for path in plan.delete:
        remove(path)
    for path, data in plan.write.items():
        write_json(path, data)
    return archive
