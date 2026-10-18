"""Terminal UI: pick the MCP servers, plugins and skills to keep, review, then reset."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)

from .cli import display
from .inventory import Inventory, logged_in, scan
from .paths import ClaudePaths
from .procs import claude_running
from .reset import ResetPlan, Selection, apply_reset, plan_reset


def _row(title: str, *details: str) -> Text:
    text = Text(title, style="bold")
    for detail in details:
        if detail:
            text.append("  ")
            text.append(detail, style="dim")
    return text


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class PickScreen(Screen):
    BINDINGS = [
        Binding("a", "select_all", "Keep all in tab"),
        Binding("n", "select_none", "Keep none in tab"),
        Binding("r", "review", "Review"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, inventory: Inventory) -> None:
        super().__init__()
        self.inventory = inventory

    def compose(self) -> ComposeResult:
        inv = self.inventory
        yield Header()
        login = "found" if logged_in(inv.paths, inv.global_config) else (
            "kept in the macOS Keychain" if sys.platform == "darwin" else "not found")
        yield Static(
            Text.assemble(
                "Tick what to keep. Everything else in ",
                (display(inv.paths.config_dir, inv.paths), "bold"),
                " is deleted (after a backup). Your login is ", (login, "bold"), " and is kept.",
            ),
            id="intro",
        )
        with TabbedContent():
            with TabPane(f"MCP servers ({len(inv.mcp_servers)})", id="tab-mcp"):
                yield self._list("mcp", [
                    (_row(s.name, f"[{s.scope}]", s.project or "", s.summary), s.key)
                    for s in inv.mcp_servers
                ], "No MCP servers configured at user or local scope.")
            with TabPane(f"Plugins ({len(inv.plugins)})", id="tab-plugins"):
                yield self._list("plugins", [
                    (_row(p.key, p.version, "" if p.enabled else "(disabled)", p.description,
                          ", ".join(filter(None, [
                              _plural(len(p.skills), "skill") if p.skills else "",
                              _plural(len(p.mcp_servers), "MCP server") if p.mcp_servers else "",
                          ]))), p.key)
                    for p in inv.plugins
                ], "No plugins installed.")
            with TabPane(f"Skills ({len(inv.skills)})", id="tab-skills"):
                yield self._list("skills", [
                    (_row(s.name, "(link)" if s.is_symlink else "", s.description), s.name)
                    for s in inv.skills
                ], "No personal skills installed.")
        with Horizontal(id="actions"):
            yield Button("Review", id="review", variant="primary")
            yield Button("Quit", id="quit")
        yield Footer()

    def _list(self, name: str, options: list[tuple[Text, str]], empty: str):
        if not options:
            return Static(empty, classes="empty")
        return SelectionList[str](*options, id=f"list-{name}")

    def selection(self) -> Selection:
        def chosen(name: str) -> set[str]:
            found = self.query(f"#list-{name}")
            return set(found.first(SelectionList).selected) if found else set()
        return Selection(chosen("mcp"), chosen("plugins"), chosen("skills"))

    def on_mount(self) -> None:
        self._focus_active_list()

    @on(TabbedContent.TabActivated)
    def _focus_active_list(self) -> None:
        if lst := self._active_list():
            lst.focus()

    def _active_list(self) -> SelectionList | None:
        pane = self.query_one(TabbedContent).active_pane
        found = pane.query(SelectionList) if pane else None
        return found.first() if found else None

    def action_select_all(self) -> None:
        if lst := self._active_list():
            lst.select_all()

    def action_select_none(self) -> None:
        if lst := self._active_list():
            lst.deselect_all()

    def action_review(self) -> None:
        plan = plan_reset(self.inventory, self.selection())
        self.app.push_screen(ReviewScreen(plan))

    @on(Button.Pressed, "#review")
    def _review(self) -> None:
        self.action_review()

    @on(Button.Pressed, "#quit")
    def _quit(self) -> None:
        self.app.exit()


class ReviewScreen(Screen):
    BINDINGS = [Binding("escape,b", "app.pop_screen", "Back")]

    def __init__(self, plan: ResetPlan) -> None:
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        plan, paths = self.plan, self.plan.inventory.paths
        yield Header()
        with VerticalScroll(id="summary"):
            keep = Text()
            keep.append("Keeping\n", style="bold green")
            keep.append("  your login\n")
            for s in plan.kept_mcp:
                keep.append(f"  MCP server  {s.key}\n")
            for p in plan.kept_plugins:
                keep.append(f"  plugin      {p.key}\n")
            for s in plan.kept_skills:
                keep.append(f"  skill       {s.name}\n")
            yield Static(keep)

            gone = Text()
            gone.append(f"Deleting {_plural(len(plan.delete), 'item')}\n", style="bold red")
            for path in plan.delete:
                gone.append(f"  {display(path, paths)}\n")
            gone.append(f"\nRewriting {_plural(len(plan.write), 'file')}\n", style="bold yellow")
            for path in plan.write:
                gone.append(f"  {display(path, paths)}\n")
            yield Static(gone)

            note = Text(f"A backup goes to {display(paths.backup_dir, paths)} first. "
                        "Undo with: claude-cleaner restore")
            if claude_running():
                note.append("\n\nClaude Code is running. Quit every session before resetting.",
                            style="bold red")
            else:
                note.append("\n\nQuit every Claude Code session before resetting.")
            yield Static(note, id="note")
        with Horizontal(id="actions"):
            yield Button("Back", id="back")
            yield Button("Back up and reset", id="reset", variant="error")
        yield Footer()

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#reset")
    def _reset(self) -> None:
        try:
            archive = apply_reset(self.plan)
        except Exception as exc:  # show it rather than crash with a traceback
            self.app.push_screen(DoneScreen(None, error=str(exc)))
            return
        self.app.push_screen(DoneScreen(archive))


class DoneScreen(Screen):
    BINDINGS = [Binding("q,enter,escape", "app.quit", "Quit")]

    def __init__(self, archive: Path | None, error: str | None = None) -> None:
        super().__init__()
        self.archive = archive
        self.error = error

    def compose(self) -> ComposeResult:
        yield Header()
        if self.error:
            message = Text()
            message.append("The reset stopped with an error:\n\n", style="bold red")
            message.append(self.error + "\n\n")
            message.append("If a backup was made, 'claude-cleaner restore' puts it back.")
        else:
            message = Text()
            message.append("Claude Code has been reset.\n\n", style="bold green")
            message.append(f"Backup: {self.archive}\n")
            message.append("Undo with: claude-cleaner restore")
        yield Static(message, id="done")
        with Horizontal(id="actions"):
            yield Button("Quit", id="quit", variant="primary")
        yield Footer()

    @on(Button.Pressed, "#quit")
    def _quit(self) -> None:
        self.app.exit(1 if self.error else 0)


class CleanerApp(App):
    TITLE = "Claude Cleaner"
    SUB_TITLE = "Reset Claude Code, keep your login"
    CSS = """
    #intro { padding: 1 2; }
    .empty { padding: 1 2; color: $text-muted; }
    SelectionList { height: 1fr; }
    TabbedContent, TabPane { height: 1fr; }
    #summary { padding: 1 2; height: 1fr; }
    #summary Static { margin-bottom: 1; }
    #done { padding: 1 2; height: 1fr; }
    #actions { height: auto; padding: 0 2 1 2; }
    #actions Button { margin-right: 2; }
    """

    def __init__(self, paths: ClaudePaths) -> None:
        super().__init__()
        self.paths = paths

    def on_mount(self) -> None:
        self.push_screen(PickScreen(scan(self.paths)))


def run(paths: ClaudePaths) -> int:
    result = CleanerApp(paths).run()
    return result if isinstance(result, int) else 0
