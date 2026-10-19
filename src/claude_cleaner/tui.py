"""Terminal UI: pick the MCP servers, plugins and skills to keep, review, then reset."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    ProgressBar,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.worker import Worker, WorkerState

from .cli import display, human_bytes
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
        if logged_in(inv.paths, inv.global_config):
            login = ("Your login stays.", "green")
        elif sys.platform == "darwin":
            login = ("Your login stays (it is in the macOS Keychain).", "green")
        else:
            login = ("No login found: you will have to sign in again.", "bold yellow")
        yield Static(
            Text.assemble(
                "Tick what to keep. Everything else in ",
                (display(inv.paths.config_dir, inv.paths), "bold"),
                " is deleted, after a backup. ", login,
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
            yield Static(id="keeping")
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
        self._count_kept()

    @on(SelectionList.SelectedChanged)
    def _count_kept(self) -> None:
        sel = self.selection()
        self.query_one("#keeping", Static).update(Text.assemble(
            ("Keeping  ", "dim"),
            " · ".join([_plural(len(sel.mcp_servers), "MCP server"),
                        _plural(len(sel.plugins), "plugin"),
                        _plural(len(sel.skills), "skill")]),
        ))

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
        self.app.switch_screen(ResetScreen(self.plan))


class ResetScreen(Screen):
    """Runs the reset in a thread, so the screen keeps drawing, and shows how far it is."""

    def __init__(self, plan: ResetPlan) -> None:
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        paths = self.plan.inventory.paths
        yield Header()
        with Vertical(id="progress"):
            yield Static(Text("Step 1 of 2  Backing up", style="bold"), id="step")
            yield Static(f"Counting files in {display(paths.config_dir, paths)}...",
                         id="detail")
            yield ProgressBar(total=None, show_eta=False)
            yield Static(Text("Do not close this window until the reset is done.", style="dim"))
        yield Footer()

    def on_mount(self) -> None:
        self._run()

    @work(thread=True, exit_on_error=False)
    def _run(self) -> Path | None:
        last = 0.0

        def progress(step: str, done: int, total: int) -> None:
            nonlocal last
            now = time.monotonic()
            if now - last >= 0.1 or done == total:  # redraw ten times a second at most
                last = now
                self.app.call_from_thread(self._show, step, done, total)

        return apply_reset(self.plan, progress=progress)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self.app.switch_screen(DoneScreen(event.worker.result))
        elif event.state == WorkerState.ERROR:  # show it rather than crash with a traceback
            self.app.switch_screen(DoneScreen(None, error=str(event.worker.error)))

    def _show(self, step: str, done: int, total: int) -> None:
        if step == "backup":
            title, detail = "Step 1 of 2  Backing up", f"{human_bytes(done)} of {human_bytes(total)}"
        else:
            title, detail = "Step 2 of 2  Deleting", f"{done} of {_plural(total, 'item')}"
        self.query_one("#step", Static).update(Text(title, style="bold"))
        self.query_one("#detail", Static).update(detail)
        self.query_one(ProgressBar).update(total=max(total, 1), progress=done)


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
            message.append("Backup  ", style="dim")
            message.append(f"{display(self.archive, self.app.paths)}\n")
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
    SelectionList > .selection-list--button-selected { color: $success; text-style: bold; }
    #keeping { width: 1fr; height: 3; content-align: right middle; }
    #progress { padding: 1 2; height: 1fr; }
    #progress Static { margin-bottom: 1; }
    #progress ProgressBar { margin-bottom: 1; }
    #progress Bar { width: 1fr; }
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

    async def action_quit(self) -> None:
        if isinstance(self.screen, ResetScreen):
            self.notify("Wait for the reset to finish.", severity="warning")
            return
        self.exit()


def run(paths: ClaudePaths) -> int:
    result = CleanerApp(paths).run()
    return result if isinstance(result, int) else 0
