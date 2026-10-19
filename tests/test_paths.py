from pathlib import Path

from claude_cleaner.paths import ClaudePaths

HOME = Path("/h")


def test_defaults():
    p = ClaudePaths.detect(home=HOME, env={}, platform="linux")
    assert p.config_dir == HOME / ".claude"
    assert p.global_config == HOME / ".claude.json"
    assert p.plugins_dir == HOME / ".claude" / "plugins"
    assert p.cache_dirs == (HOME / ".cache" / "claude-cli-nodejs",)
    assert p.backup_dir == HOME / ".claude-cleaner" / "backups"


def test_config_dir_override_moves_global_config_inside():
    p = ClaudePaths.detect(home=HOME, env={"CLAUDE_CONFIG_DIR": "/cfg"}, platform="linux")
    assert p.config_dir == Path("/cfg")
    assert p.global_config == Path("/cfg/.claude.json")
    assert p.plugins_dir == Path("/cfg/plugins")


def test_plugin_cache_override():
    p = ClaudePaths.detect(home=HOME, env={"CLAUDE_CODE_PLUGIN_CACHE_DIR": "/pc"}, platform="linux")
    assert p.plugins_dir == Path("/pc")


def test_cache_dir_per_platform():
    mac = ClaudePaths.detect(home=HOME, env={}, platform="darwin")
    assert mac.cache_dirs == (HOME / "Library" / "Caches" / "claude-cli-nodejs",)
    win = ClaudePaths.detect(home=HOME, env={"LOCALAPPDATA": "/la"}, platform="win32")
    assert win.cache_dirs == (Path("/la") / "claude-cli-nodejs",)
    xdg = ClaudePaths.detect(home=HOME, env={"XDG_CACHE_HOME": "/xc"}, platform="linux")
    assert xdg.cache_dirs == (Path("/xc") / "claude-cli-nodejs",)
