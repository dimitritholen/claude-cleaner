# claude-cleaner

Reset Claude Code to factory defaults while staying logged in. A terminal UI lists your
MCP servers, plugins and skills; tick the ones to keep and everything else goes: memory,
chat history, projects, settings, hooks, commands, agents, other skills and plugins.
A backup is made first, and one command puts it back.

## Install

Needs Python 3.10 or newer.

```sh
pipx install git+https://github.com/dimitritholen/claude-cleaner
# or
uv tool install git+https://github.com/dimitritholen/claude-cleaner
```

## Use

Quit every Claude Code session first, then:

```sh
claude-cleaner
```

1. Tick what to keep in the **MCP servers**, **Plugins** and **Skills** tabs
   (`space` toggles, `a` keeps all in the tab, `n` none, `r` reviews).
2. The review screen lists every file and folder that will be deleted or rewritten.
3. **Back up and reset** writes the backup, then resets.

Without the UI:

```sh
claude-cleaner scan                      # what is installed (add --json for JSON)
claude-cleaner reset --dry-run \
  --keep-mcp github --keep-plugin demo@my-marketplace --keep-skill my-skill
claude-cleaner reset --keep-mcp github --yes
claude-cleaner backups                   # list backups
claude-cleaner restore                   # restore the latest backup (or pass a path)
```

Local-scope MCP servers are named `NAME@/path/to/project`, as `scan` shows them.

## What it touches

In short: it keeps your login, the claude binary and what you tick, and empties the rest of
`~/.claude/` (or `$CLAUDE_CONFIG_DIR`) and `~/.claude.json`, plus Claude Code's log cache.
Project folders in your repositories are left alone. The full list is in
[docs/spec.md](docs/spec.md).

Backups go to `~/.claude-cleaner/backups/` and contain your login token, so they are
readable by you only. `restore` backs up the current state before it replaces it.

## Develop

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```
