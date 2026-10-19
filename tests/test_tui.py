from textual.widgets import SelectionList

from claude_cleaner.tui import CleanerApp, DoneScreen, ReviewScreen


async def test_pick_review_and_reset(home):
    app = CleanerApp(home)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        mcp = app.screen.query_one("#list-mcp", SelectionList)
        assert mcp.has_focus
        await pilot.press("space")  # keep the first MCP server ("fs")
        await pilot.press("r")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        assert app.screen.plan.selection.mcp_servers == {"fs"}
        assert (home.config_dir / "CLAUDE.md").exists()  # nothing happens before confirming

        await pilot.click("#reset")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, DoneScreen)
        assert app.screen.archive.exists()
    assert not (home.config_dir / "CLAUDE.md").exists()


async def test_keep_all_in_tab_and_back(home):
    app = CleanerApp(home)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("r")
        await pilot.pause()
        assert len(app.screen.plan.selection.mcp_servers) == 3
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ReviewScreen)
    assert (home.config_dir / "CLAUDE.md").exists()
