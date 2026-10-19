from claude_cleaner.inventory import scan


def test_scan_finds_everything(home):
    inv = scan(home)
    assert [s.key for s in inv.mcp_servers] == [
        "fs", "github", f"db@{home.home / 'code' / 'app'}",
    ]
    assert inv.mcp_servers[1].summary == "http https://api.example.com/mcp"

    demo, other = inv.plugins
    assert (demo.key, demo.version, demo.enabled) == ("demo@local-mkt", "1.0.0", True)
    assert demo.skills == ("hello",) and demo.mcp_servers == ("demo-srv",)
    assert (other.key, other.enabled, other.mcp_servers) == ("other@gh-mkt", False, ("o1",))

    assert [(s.name, s.description) for s in inv.skills] == [
        ("bundle", "Plugin folder in skills"),
        ("dropme", "A skill to drop"),
        ("keepme", "A skill to keep"),
    ]


def test_scan_of_empty_home(tmp_path):
    from claude_cleaner.paths import ClaudePaths
    inv = scan(ClaudePaths.detect(home=tmp_path, env={}, platform="linux"))
    assert (inv.mcp_servers, inv.plugins, inv.skills) == ([], [], [])


def test_corrupt_json_is_treated_as_empty(home):
    home.global_config.write_text("{not json", encoding="utf-8")
    assert scan(home).mcp_servers == []
