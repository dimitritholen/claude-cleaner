"""Read-only scan of the MCP servers, plugins and skills Claude Code has installed."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import ClaudePaths


@dataclass(frozen=True)
class McpServer:
    name: str
    scope: str  # "user" or "local"
    config: dict[str, Any]
    project: str | None = None  # project path, for local scope

    @property
    def key(self) -> str:
        """Stable id: ``name`` for user scope, ``name@<project path>`` for local scope."""
        return self.name if self.scope == "user" else f"{self.name}@{self.project}"

    @property
    def summary(self) -> str:
        cfg = self.config
        kind = cfg.get("type", "stdio")
        if "url" in cfg:
            return f"{kind} {cfg['url']}"
        cmd = " ".join([str(cfg.get("command", ""))] + [str(a) for a in cfg.get("args", [])])
        return f"{kind} {cmd}".strip()


@dataclass(frozen=True)
class Plugin:
    key: str  # "<name>@<marketplace>"
    name: str
    marketplace: str
    version: str
    enabled: bool
    description: str
    install_paths: tuple[Path, ...]
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    description: str
    is_symlink: bool


@dataclass
class Inventory:
    paths: ClaudePaths
    global_config: dict[str, Any]
    settings: dict[str, Any]
    installed_plugins: dict[str, Any]
    known_marketplaces: dict[str, Any]
    mcp_servers: list[McpServer] = field(default_factory=list)
    plugins: list[Plugin] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_dir": str(self.paths.config_dir),
            "global_config": str(self.paths.global_config),
            "logged_in": logged_in(self.paths, self.global_config),
            "mcp_servers": [
                {"key": s.key, "name": s.name, "scope": s.scope, "project": s.project,
                 "summary": s.summary}
                for s in self.mcp_servers
            ],
            "plugins": [
                {"key": p.key, "version": p.version, "enabled": p.enabled,
                 "description": p.description, "skills": list(p.skills),
                 "mcp_servers": list(p.mcp_servers)}
                for p in self.plugins
            ],
            "skills": [
                {"name": s.name, "path": str(s.path), "description": s.description}
                for s in self.skills
            ],
        }


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, returning ``{}`` for a missing or unreadable file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_global_config(paths: ClaudePaths) -> dict[str, Any]:
    if paths.global_config.exists():
        return read_json(paths.global_config)
    return read_json(paths.legacy_global_config)


def logged_in(paths: ClaudePaths, global_config: dict[str, Any]) -> bool:
    """Best-effort: is there an account to keep? (macOS keeps tokens in the Keychain.)"""
    return bool(
        global_config.get("oauthAccount")
        or global_config.get("primaryApiKey")
        or (paths.config_dir / ".credentials.json").exists()
    )


def scan(paths: ClaudePaths) -> Inventory:
    global_config = load_global_config(paths)
    plugins_dir = paths.plugins_dir
    inv = Inventory(
        paths=paths,
        global_config=global_config,
        settings=read_json(paths.config_dir / "settings.json"),
        installed_plugins=read_json(plugins_dir / "installed_plugins.json"),
        known_marketplaces=read_json(plugins_dir / "known_marketplaces.json"),
    )
    inv.mcp_servers = _scan_mcp(global_config)
    inv.plugins = _scan_plugins(inv)
    inv.skills = _scan_skills(paths.config_dir / "skills")
    return inv


def _scan_mcp(global_config: dict[str, Any]) -> list[McpServer]:
    servers = [
        McpServer(name, "user", cfg if isinstance(cfg, dict) else {})
        for name, cfg in (global_config.get("mcpServers") or {}).items()
    ]
    for project, entry in (global_config.get("projects") or {}).items():
        if not isinstance(entry, dict):
            continue
        for name, cfg in (entry.get("mcpServers") or {}).items():
            servers.append(McpServer(name, "local", cfg if isinstance(cfg, dict) else {}, project))
    return sorted(servers, key=lambda s: (s.scope != "user", s.name.lower(), s.project or ""))


def split_plugin_key(key: str) -> tuple[str, str]:
    name, _, marketplace = key.rpartition("@")
    return (name, marketplace) if name else (key, "")


def _scan_plugins(inv: Inventory) -> list[Plugin]:
    installed = inv.installed_plugins.get("plugins")
    if not isinstance(installed, dict):
        installed = {}
    enabled = inv.settings.get("enabledPlugins") or {}

    plugins = []
    for key in sorted(set(installed) | set(enabled), key=str.lower):
        name, marketplace = split_plugin_key(key)
        entries = installed.get(key) or []
        if isinstance(entries, dict):  # installed_plugins.json version 1
            entries = [entries]
        install_paths = tuple(
            Path(e["installPath"]) for e in entries if isinstance(e, dict) and e.get("installPath")
        )
        version = next((str(e.get("version")) for e in entries
                        if isinstance(e, dict) and e.get("version")), "")
        manifest: dict[str, Any] = {}
        skills: list[str] = []
        mcp: list[str] = []
        for root in install_paths:
            manifest = manifest or read_json(root / ".claude-plugin" / "plugin.json")
            skills += _skill_names(root / "skills")
            mcp += _plugin_mcp_names(root, manifest)
        plugins.append(Plugin(
            key=key,
            name=name,
            marketplace=marketplace,
            version=version or str(manifest.get("version", "")),
            enabled=bool(enabled.get(key, False)),
            description=str(manifest.get("description", "")),
            install_paths=install_paths,
            skills=tuple(sorted(set(skills))),
            mcp_servers=tuple(sorted(set(mcp))),
        ))
    return plugins


def _plugin_mcp_names(root: Path, manifest: dict[str, Any]) -> list[str]:
    servers = manifest.get("mcpServers")
    if isinstance(servers, str):
        servers = read_json(root / servers)
    if not isinstance(servers, dict):
        servers = read_json(root / ".mcp.json")
    servers = servers.get("mcpServers", servers)
    return list(servers) if isinstance(servers, dict) else []


def _skill_names(skills_dir: Path) -> list[str]:
    try:
        return [p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()]
    except OSError:
        return []


def _scan_skills(skills_dir: Path) -> list[Skill]:
    try:
        entries = sorted(skills_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    skills = []
    for entry in entries:
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            description = _frontmatter(skill_md).get("description", "")
        elif (entry / ".claude-plugin" / "plugin.json").is_file():
            # A plugin folder dropped into skills/ (loaded as "<name>@skills-dir").
            manifest = read_json(entry / ".claude-plugin" / "plugin.json")
            description = str(manifest.get("description", "")) or "plugin folder"
        else:
            continue
        skills.append(Skill(entry.name, entry, description, entry.is_symlink()))
    return skills


def _frontmatter(path: Path) -> dict[str, str]:
    """Parse the simple ``key: value`` lines of a SKILL.md frontmatter block."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and not key.startswith((" ", "\t")):
            meta[key.strip()] = value.strip().strip("\"'")
    return meta
