import json

from claude_cleaner.cli import main


def test_scan_json(home, capsys):
    assert main(["scan", "--json"], paths=home) == 0
    data = json.loads(capsys.readouterr().out)
    assert [p["key"] for p in data["plugins"]] == ["demo@local-mkt", "other@gh-mkt"]
    assert data["logged_in"] is True


def test_scan_text(home, capsys):
    assert main(["scan"], paths=home) == 0
    assert "demo@local-mkt" in capsys.readouterr().out


def test_dry_run_changes_nothing(home, capsys):
    assert main(["reset", "--keep-mcp", "fs", "--dry-run"], paths=home) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "~/.claude/CLAUDE.md" in out
    assert (home.config_dir / "CLAUDE.md").exists()


def test_reset_and_restore(home, capsys):
    assert main(["reset", "--keep-skill", "keepme", "--yes"], paths=home) == 0
    assert not (home.config_dir / "CLAUDE.md").exists()
    assert (home.config_dir / "skills" / "keepme").is_dir()
    assert main(["restore", "--yes"], paths=home) == 0
    assert (home.config_dir / "CLAUDE.md").exists()


def test_reset_asks_first(home, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["reset"], paths=home) == 1
    assert (home.config_dir / "CLAUDE.md").exists()


def test_unknown_keep_is_an_error(home, capsys):
    assert main(["reset", "--keep-plugin", "missing@x", "--yes"], paths=home) == 2
    assert "missing@x" in capsys.readouterr().err


def test_restore_without_backups(home, capsys):
    assert main(["restore", "--yes"], paths=home) == 2
