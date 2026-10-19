"""Terminal UI: pick the MCP servers, plugins and skills to keep, review, then reset."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from rich.segment import Segment
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.strip import Strip
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
from textual.widgets.option_list import OptionDoesNotExist
from textual.worker import Worker, WorkerState

from .cli import display, human_bytes
from .fsutil import tree_size
from .inventory import Inventory, logged_in, scan
from .paths import ClaudePaths
from .procs import claude_running
from .reset import ResetPlan, Selection, apply_reset, plan_reset


def _table(rows: list[list[str]]) -> list[Text]:
    """Rows as aligned columns: the first bold, the rest dim, the last left ragged."""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)] if rows else []
    lines = []
    for row in rows:
        text = Text()
        for i, cell in enumerate(row):
            if i:
                text.append("  ")
            text.append(cell.ljust(widths[i]) if i < len(widths) else cell,
                        style="bold" if i == 0 else "dim")
        lines.append(text)
    return lines


class KeepList(SelectionList[str]):
    """A SelectionList that marks kept rows with a check and leaves the rest empty. The
    stock box shows an X on every row, which reads as "delete" in this app."""

    BINDINGS = [Binding("space", "select", "Keep / delete")]  # the stock one is hidden

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        try:
            option = self.get_option_at_index(self.scroll_offset.y + y)
        except OptionDoesNotExist:
            return strip
        segments = list(strip)
        box = segments[1]
        segments[1] = Segment("✓" if option.value in self.selected else " ", box.style)
        return Strip(segments, strip.cell_length)


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
                yield self._list("mcp", [s.key for s in inv.mcp_servers], [
                    [s.name, s.scope, s.summary,
                     display(Path(s.project), inv.paths) if s.project else ""]
                    for s in inv.mcp_servers
                ], "No MCP servers configured at user or local scope.")
            with TabPane(f"Plugins ({len(inv.plugins)})", id="tab-plugins"):
                yield self._list("plugins", [p.key for p in inv.plugins], [
                    [p.key, p.version, "" if p.enabled else "disabled",
                     ", ".join(filter(None, [
                         _plural(len(p.skills), "skill") if p.skills else "",
                         _plural(len(p.mcp_servers), "MCP server") if p.mcp_servers else "",
                     ])), p.description]
                    for p in inv.plugins
                ], "No plugins installed.")
            with TabPane(f"Skills ({len(inv.skills)})", id="tab-skills"):
                yield self._list("skills", [s.name for s in inv.skills], [
                    [s.name, "link" if s.is_symlink else "", s.description]
                    for s in inv.skills
                ], "No personal skills installed.")
        with Horizontal(id="actions"):
            yield Button("Review", id="review", variant="primary")
            yield Button("Quit", id="quit")
            yield Static(id="keeping")
        yield Footer()

    def _list(self, name: str, values: list[str], rows: list[list[str]], empty: str):
        if not values:
            return Static(empty, classes="empty")
        return KeepList(*zip(_table(rows), values), id=f"list-{name}")

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
        self.sizes: dict[Path, int] | None = None

    def compose(self) -> ComposeResult:
        plan, paths = self.plan, self.plan.inventory.paths
        yield Header()
        with VerticalScroll(id="summary"):
            keep = Text()
            keep.append("Keeping\n", style="bold green")
            kept = [("your login", "")]
            kept += [("MCP server", s.key) for s in plan.kept_mcp]
            kept += [("plugin", p.key) for p in plan.kept_plugins]
            kept += [("skill", s.name) for s in plan.kept_skills]
            for kind, name in kept:
                keep.append("  ✓ ", style="green")
                keep.append(f"{kind:<12}{name}\n")
            yield Static(keep)
            yield Static(self._gone(), id="gone")

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

    def on_mount(self) -> None:
        self.query_one("#back", Button).focus()  # the safe choice first
        self._measure()

    @work(thread=True, exit_on_error=False)
    def _measure(self) -> dict[Path, int]:
        return {path: tree_size(path) for path in self.plan.delete}

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self.sizes = event.worker.result
            self.query_one("#gone", Static).update(self._gone())

    def _gone(self) -> Text:
        plan, paths, sizes = self.plan, self.plan.inventory.paths, self.sizes
        names = {path: display(path, paths) for path in [*plan.delete, *plan.write]}
        width = max(map(len, names.values()), default=0)
        doomed = sorted(plan.delete, key=lambda p: -sizes[p]) if sizes else plan.delete
        text = Text()
        text.append(f"Deleting {_plural(len(plan.delete), 'item')}", style="bold red")
        text.append(f"  {human_bytes(sum(sizes.values()))}\n" if sizes else "  measuring...\n",
                    style="dim")
        for path in doomed:
            text.append(f"  {names[path]:<{width}}")
            if sizes:
                text.append(f"  {human_bytes(sizes[path]):>9}", style="dim")
            text.append("\n")
        text.append(f"\nRewriting {_plural(len(plan.write), 'file')}\n", style="bold yellow")
        for path in plan.write:
            text.append(f"  {names[path]}\n")
        return text

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#reset")
    def _reset(self) -> None:
        freed = sum(self.sizes.values()) if self.sizes else None
        self.app.switch_screen(ResetScreen(self.plan, freed))


class ResetScreen(Screen):
    """Runs the reset in a thread, so the screen keeps drawing, and shows how far it is."""

    def __init__(self, plan: ResetPlan, freed: int | None = None) -> None:
        super().__init__()
        self.plan = plan
        self.freed = freed

    def compose(self) -> ComposeResult:
        paths = self.plan.inventory.paths
        yield Header()
        with Vertical(classes="panel"):
            yield Static(self._steps("backup"), id="steps")
            yield Static(f"Counting files in {display(paths.config_dir, paths)}...",
                         id="detail")
            yield ProgressBar(total=None, show_eta=False)
            yield Static(Text("Do not close this window until the reset is done.", style="dim"))
        yield Footer()

    @staticmethod
    def _steps(step: str) -> Text:
        if step == "backup":
            return Text.assemble(("▸ Back up\n", "bold"), ("  Delete", "dim"))
        return Text.assemble(("✓ Back up\n", "green"), ("▸ Delete", "bold"))

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
            self.app.switch_screen(DoneScreen(event.worker.result, self.freed))
        elif event.state == WorkerState.ERROR:  # show it rather than crash with a traceback
            self.app.switch_screen(DoneScreen(None, error=str(event.worker.error)))

    def _show(self, step: str, done: int, total: int) -> None:
        if step == "backup":
            detail = f"{human_bytes(done)} of {human_bytes(total)}"
        else:
            detail = f"{done} of {_plural(total, 'item')}"
        self.query_one("#steps", Static).update(self._steps(step))
        self.query_one("#detail", Static).update(detail)
        self.query_one(ProgressBar).update(total=max(total, 1), progress=done)


class DoneScreen(Screen):
    BINDINGS = [Binding("q,enter,escape", "app.quit", "Quit")]

    def __init__(self, archive: Path | None, freed: int | None = None,
                 error: str | None = None) -> None:
        super().__init__()
        self.archive = archive
        self.freed = freed
        self.error = error

    def compose(self) -> ComposeResult:
        yield Header()
        message = Text()
        if self.error:
            message.append("✗ The reset stopped with an error\n\n", style="bold red")
            message.append(self.error + "\n\n")
            message.append("If a backup was made, 'claude-cleaner restore' puts it back.")
        else:
            message.append("✓ Claude Code has been reset\n\n", style="bold green")
            if self.freed is not None:
                message.append(f"{'Freed':<8}", style="dim")
                message.append(f"{human_bytes(self.freed)}\n")
            message.append(f"{'Backup':<8}", style="dim")
            message.append(f"{display(self.archive, self.app.paths)} "
                           f"({human_bytes(self.archive.stat().st_size)})\n")
            message.append(f"{'Undo':<8}", style="dim")
            message.append("claude-cleaner restore")
        with Vertical(classes="panel -error" if self.error else "panel"):
            yield Static(message, id="done")
            yield Button("Quit", id="quit", variant="primary")
        yield Footer()

    @on(Button.Pressed, "#quit")
    def _quit(self) -> None:
        self.app.exit(1 if self.error else 0)


class CleanerApp(App):
    TITLE = "Claude Cleaner"
    SUB_TITLE = "Reset Claude Code, keep your login"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    SelectionList > .selection-list--button-selected { color: $success; text-style: bold; }
    /* Textual's default focus style reverses only the label text; mark the whole
       button and tab instead. */
    Button:focus { text-style: bold; border-top: tall $accent; border-bottom: tall $accent; }
    Tabs:focus .-active { text-style: bold; color: $accent; background: transparent; }
    Tabs:focus .underline--bar { color: $accent; }
    #keeping { width: 1fr; height: 3; content-align: right middle; }
    ResetScreen, DoneScreen { align: center middle; }
    .panel { width: 96; max-width: 100%; height: auto; padding: 1 2;
             border: round $primary; }
    .panel.-error { border: round $error; }
    .panel Static { margin-bottom: 1; }
    .panel ProgressBar { margin-bottom: 1; }
    .panel Bar { width: 1fr; }
    #intro { padding: 1 2; }
    .empty { padding: 1 2; color: $text-muted; }
    SelectionList { height: 1fr; }
    TabbedContent, TabPane { height: 1fr; }
    #summary { padding: 1 2; height: 1fr; scrollbar-size-vertical: 1; }
    #summary Static { margin-bottom: 1; }
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
