import json
import os

import pytest

from claude_cleaner.inventory import scan
from claude_cleaner.reset import Selection, UnknownSelection, apply_reset, plan_reset
from conftest import ACCOUNT, build_home


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def listing(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_keep_nothing_leaves_only_the_login(home):
    archive = apply_reset(plan_reset(scan(home), Selection()))

    assert archive.exists()
    assert sorted(p.name for p in home.config_dir.iterdir()) == [".credentials.json", "local"]
    assert load(home.config_dir / ".credentials.json") == {"claudeAiOauth": {"accessToken": "secret"}}
    assert load(home.global_config) == {
        "oauthAccount": ACCOUNT,
        "userID": "user-hash",
        "hasCompletedOnboarding": True,
        "lastOnboardingVersion": "2.1.0",
    }
    assert not any(d.exists() for d in home.cache_dirs)


def test_keeps_selected_items(home):
    project = str(home.home / "code" / "app")
    selection = Selection(
        mcp_servers={"github", f"db@{project}"},
        plugins={"demo@local-mkt"},
        skills={"keepme", "bundle"},
    )
    apply_reset(plan_reset(scan(home), selection))

    config = load(home.global_config)
    assert config["mcpServers"] == {"github": {"type": "http", "url": "https://api.example.com/mcp"}}
    assert config["projects"] == {
        project: {"mcpServers": {"db": {"type": "stdio", "command": "db-mcp", "args": []}}}
    }
    assert "theme" not in config

    assert load(home.config_dir / "settings.json") == {
        "enabledPlugins": {"demo@local-mkt": True},
        "extraKnownMarketplaces": {
            "local-mkt": {"source": {"source": "directory", "path": "/src/mkt"}},
        },
        "pluginConfigs": {"demo@local-mkt": {"opt": 1}},
    }
    plugins = home.plugins_dir
    assert list(load(plugins / "installed_plugins.json")["plugins"]) == ["demo@local-mkt"]
    assert load(plugins / "installed_plugins.json")["version"] == 2
    assert list(load(plugins / "known_marketplaces.json")) == ["local-mkt"]
    assert listing(plugins) == [
        "cache", "cache/local-mkt", "cache/local-mkt/demo", "cache/local-mkt/demo/1.0.0",
        "cache/local-mkt/demo/1.0.0/.claude-plugin",
        "cache/local-mkt/demo/1.0.0/.claude-plugin/plugin.json",
        "cache/local-mkt/demo/1.0.0/skills", "cache/local-mkt/demo/1.0.0/skills/hello",
        "cache/local-mkt/demo/1.0.0/skills/hello/SKILL.md",
        "data", "data/demo-local-mkt", "data/demo-local-mkt/state.json",
        "installed_plugins.json", "known_marketplaces.json",
    ]
    assert sorted(p.name for p in (home.config_dir / "skills").iterdir()) == ["bundle", "keepme"]
    assert sorted(p.name for p in home.config_dir.iterdir()) == [
        ".credentials.json", "local", "plugins", "settings.json", "skills",
    ]


def test_keeping_a_github_marketplace_plugin_keeps_its_clone(home):
    apply_reset(plan_reset(scan(home), Selection(plugins={"other@gh-mkt"})))
    assert (home.plugins_dir / "marketplaces" / "gh-mkt" / ".claude-plugin").is_dir()
    assert load(home.config_dir / "settings.json")["enabledPlugins"] == {"other@gh-mkt": False}


def test_unknown_selection_is_rejected(home):
    with pytest.raises(UnknownSelection, match="nope"):
        plan_reset(scan(home), Selection(plugins={"nope@x"}))


def test_planning_changes_nothing(home):
    before = listing(home.home)
    plan = plan_reset(scan(home), Selection())
    assert listing(home.home) == before
    assert home.config_dir / "CLAUDE.md" in plan.delete
    assert home.config_dir / ".credentials.json" not in plan.delete


def test_symlinked_skill_is_unlinked_not_followed(home, tmp_path):
    target = tmp_path / "elsewhere" / "linked"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("---\nname: linked\n---\n", encoding="utf-8")
    try:
        os.symlink(target, home.config_dir / "skills" / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted here")
    apply_reset(plan_reset(scan(home), Selection()))
    assert (target / "SKILL.md").exists()
    assert not (home.config_dir / "skills").exists()


def test_custom_config_dir(tmp_path):
    paths = build_home(tmp_path / "home", config_dir=tmp_path / "cfg")
    apply_reset(plan_reset(scan(paths), Selection(mcp_servers={"fs"})))
    assert sorted(p.name for p in paths.config_dir.iterdir()) == [
        ".claude.json", ".credentials.json", "local",
    ]
    assert list(load(paths.global_config)["mcpServers"]) == ["fs"]


def test_reset_without_account_removes_global_config(tmp_path):
    from claude_cleaner.paths import ClaudePaths
    from conftest import write
    paths = ClaudePaths.detect(home=tmp_path, env={}, platform="linux")
    write(paths.global_config, {"theme": "dark"})
    apply_reset(plan_reset(scan(paths), Selection()), make_backup=False)
    assert not paths.global_config.exists()
