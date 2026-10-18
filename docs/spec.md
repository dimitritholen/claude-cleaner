# What a reset keeps and deletes

This is the map of Claude Code's user-level state that `claude-cleaner` works from. It was
checked against the Claude Code docs (code.claude.com/docs: settings, claude-directory,
authentication, mcp, plugins, skills, setup) and against what Claude Code 2.1 actually
writes on disk.

## Locations

| What | Where |
| --- | --- |
| Config folder | `~/.claude/`, or `$CLAUDE_CONFIG_DIR` when set |
| Global config | `~/.claude.json`, or `$CLAUDE_CONFIG_DIR/.claude.json` when set (verified: Claude Code writes it inside the override folder) |
| Legacy global config | `<config folder>/.config.json` (read only when the main file is missing) |
| Plugins | `<config folder>/plugins/`, or `$CLAUDE_CODE_PLUGIN_CACHE_DIR` when set |
| Log cache | `~/.cache/claude-cli-nodejs` (Linux, honours `XDG_CACHE_HOME`), `~/Library/Caches/claude-cli-nodejs` (macOS), `%LOCALAPPDATA%\claude-cli-nodejs` (Windows) |
| Backups made by this tool | `~/.claude-cleaner/backups/claude-backup-<timestamp>.tar.gz` |

## Kept

- **Login.** `<config folder>/.credentials.json` (Linux, Windows, and macOS when the
  Keychain is unavailable). On macOS the token normally lives in the login Keychain, which
  this tool never touches.
- **Account entries in the global config:** `oauthAccount`, `primaryApiKey`,
  `customApiKeyResponses`, `userID`, `hasCompletedOnboarding`, `lastOnboardingVersion`,
  `installMethod`. The onboarding flags are kept on purpose so Claude Code does not run its
  first-launch setup (which includes the login step) again.
- **The claude binary.** `<config folder>/local/` (legacy per-user install) is never touched,
  and nothing outside the folders above is touched either, so `~/.local/bin/claude` and
  `~/.local/share/claude/` (native installer) are safe.
- **Selected MCP servers.** User scope: top-level `mcpServers` in the global config. Local
  scope: `projects["<path>"].mcpServers`; a kept local server keeps a project entry holding
  only its `mcpServers`.
- **Selected plugins** (`name@marketplace`):
  - their records in `plugins/installed_plugins.json`;
  - their marketplace in `plugins/known_marketplaces.json`, and the clone in
    `plugins/marketplaces/<marketplace>/` if there is one;
  - their install folder `plugins/cache/<marketplace>/<name>/`;
  - their data folder `plugins/data/<name>-<marketplace>/`;
  - their `enabledPlugins` value (enabled or disabled), `pluginConfigs`, and
    `extraKnownMarketplaces` entry in `settings.json`.
  MCP servers and skills that come with a plugin stay with the plugin.
- **Selected skills:** folders in `<config folder>/skills/` that hold a `SKILL.md`, or a
  plugin folder (`.claude-plugin/plugin.json`). A symlinked skill stays a symlink.

## Deleted

Everything else in the config folder (and the separate plugins folder, if overridden),
plus the log cache. That includes `settings.json` content (permissions, hooks, env, model,
status line), `CLAUDE.md`, `rules/`, `commands/`, `agents/`, `output-styles/`, `themes/`,
`keybindings.json`, `projects/` (chat history and auto memory), `history.jsonl`, `todos/`,
`plans/`, `file-history/`, `shell-snapshots/`, `session-env/`, `statsig/`, `backups/`,
`remote-settings.json`, `policy-limits.json`, and every other key in the global config
(theme, UI toggles, per-project trust and allowed tools, tips, caches). Plugins synced from
claude.ai (`plugins/synced/`) are deleted locally and come back on the next sync.

Symlinks are removed, never followed, so a linked skill's real folder is left alone.

## Not touched

- Project-level files: `.claude/` folders, `CLAUDE.md` and `.mcp.json` inside repositories.
- Managed (admin) settings: `/Library/Application Support/ClaudeCode/`, `/etc/claude-code/`,
  `C:\Program Files\ClaudeCode\`.
- Anthropic Console profiles in `~/.config/anthropic` or `%APPDATA%\Anthropic`.
- claude.ai connectors, which live in your claude.ai account, not on disk.
