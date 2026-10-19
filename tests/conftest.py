"""A fake home folder laid out the way Claude Code 2.x leaves it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_cleaner.paths import ClaudePaths

ACCOUNT = {"accountUuid": "acc-1", "emailAddress": "me@example.com", "organizationUuid": "org-1"}


def write(path: Path, content: str | dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, indent=2) if isinstance(content, dict) else content
    path.write_text(text, encoding="utf-8")
    return path


def skill_md(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n"


def build_home(home: Path, config_dir: Path | None = None) -> ClaudePaths:
    env = {"CLAUDE_CONFIG_DIR": str(config_dir)} if config_dir else {}
    paths = ClaudePaths.detect(home=home, env=env, platform="linux")
    cfg = paths.config_dir
    project = str(home / "code" / "app")

    write(paths.global_config, {
        "oauthAccount": ACCOUNT,
        "userID": "user-hash",
        "hasCompletedOnboarding": True,
        "lastOnboardingVersion": "2.1.0",
        "theme": "dark",
        "numStartups": 42,
        "tipsHistory": {"x": 1},
        "mcpServers": {
            "github": {"type": "http", "url": "https://api.example.com/mcp"},
            "fs": {"type": "stdio", "command": "npx", "args": ["fs-server"], "env": {}},
        },
        "projects": {
            project: {
                "allowedTools": ["Bash"],
                "hasTrustDialogAccepted": True,
                "mcpServers": {"db": {"type": "stdio", "command": "db-mcp", "args": []}},
            },
            str(home / "code" / "other"): {"allowedTools": []},
        },
    })
    write(cfg / ".credentials.json", {"claudeAiOauth": {"accessToken": "secret"}})
    write(cfg / "settings.json", {
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
        "permissions": {"allow": ["Bash(ls)"]},
        "enabledPlugins": {"demo@local-mkt": True, "other@gh-mkt": False},
        "extraKnownMarketplaces": {
            "local-mkt": {"source": {"source": "directory", "path": "/src/mkt"}},
            "gh-mkt": {"source": {"source": "github", "repo": "acme/plugins"}},
        },
        "pluginConfigs": {"demo@local-mkt": {"opt": 1}},
    })
    write(cfg / "CLAUDE.md", "# my memory\n")
    write(cfg / "keybindings.json", {"bindings": []})
    write(cfg / "history.jsonl", '{"display": "hi"}\n')
    write(cfg / "projects" / "-code-app" / "session.jsonl", "{}\n")
    write(cfg / "projects" / "-code-app" / "memory" / "MEMORY.md", "notes\n")
    write(cfg / "commands" / "deploy.md", "deploy\n")
    write(cfg / "agents" / "reviewer.md", "agent\n")
    write(cfg / "todos" / "t.json", "[]")
    write(cfg / "local" / "claude", "#!/bin/sh\n")

    write(cfg / "skills" / "keepme" / "SKILL.md", skill_md("keepme", "A skill to keep"))
    write(cfg / "skills" / "dropme" / "SKILL.md", skill_md("dropme", "A skill to drop"))
    write(cfg / "skills" / "bundle" / ".claude-plugin" / "plugin.json",
          {"name": "bundle", "description": "Plugin folder in skills"})

    plugins = paths.plugins_dir
    demo = plugins / "cache" / "local-mkt" / "demo" / "1.0.0"
    write(demo / ".claude-plugin" / "plugin.json", {
        "name": "demo", "version": "1.0.0", "description": "Demo plugin",
        "mcpServers": {"demo-srv": {"command": "echo"}},
    })
    write(demo / "skills" / "hello" / "SKILL.md", skill_md("hello", "say hi"))
    other = plugins / "cache" / "gh-mkt" / "other" / "abc123"
    write(other / ".claude-plugin" / "plugin.json", {"name": "other", "description": "Other"})
    write(other / ".mcp.json", {"mcpServers": {"o1": {"command": "x"}}})
    write(plugins / "marketplaces" / "gh-mkt" / ".claude-plugin" / "marketplace.json", {"name": "gh-mkt"})
    write(plugins / "data" / "demo-local-mkt" / "state.json", {"n": 1})
    write(plugins / "data" / "other-gh-mkt" / "state.json", {"n": 2})
    write(plugins / "installed_plugins.json", {
        "version": 2,
        "plugins": {
            "demo@local-mkt": [{"scope": "user", "installPath": str(demo), "version": "1.0.0"}],
            "other@gh-mkt": [{"scope": "user", "installPath": str(other), "version": "abc123"}],
        },
    })
    write(plugins / "known_marketplaces.json", {
        "local-mkt": {"source": {"source": "directory", "path": "/src/mkt"},
                      "installLocation": "/src/mkt"},
        "gh-mkt": {"source": {"source": "github", "repo": "acme/plugins"},
                   "installLocation": str(plugins / "marketplaces" / "gh-mkt")},
    })
    for cache in paths.cache_dirs:
        write(cache / "mcp-logs-fs" / "log.txt", "log\n")
    return paths


@pytest.fixture
def home(tmp_path: Path) -> ClaudePaths:
    return build_home(tmp_path / "home")
