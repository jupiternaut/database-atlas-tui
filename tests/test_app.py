"""Headless Pilot interaction tests for the real terminal application.

These exercise the production widget tree and local snapshot; they do not
claim to screenshot or verify a separate native terminal window.
"""
from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.asyncio
async def test_panel_visible_label_refreshes_when_numeric_id_is_reused():
    app = AtlasApp()
    async with app.run_test(size=(150, 40)) as pilot:
        for view_index in (4, 7, 2):
            await pilot.press(str(view_index))
            await pilot.pause()
            expected = app.current_panels[app.panel_index]["title"]
            assert expected in str(app.query_one("#panels #label").render())
from rich.console import Console
from textual.widgets import DataTable, Input, OptionList, Static

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from app import AtlasApp, DocumentModal, SearchModal, fit
from wcwidth import wcswidth


def rendered_text(renderable) -> str:
    stream = io.StringIO()
    Console(file=stream, width=160, color_system=None).print(renderable)
    return stream.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(160, 44), (120, 40), (80, 24), (60, 20)])
async def test_startup_and_responsive_terminal_regions(size):
    app = AtlasApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        table = app.query_one("#relations", DataTable)
        assert app.entity == "tidb"
        assert table.row_count == len(app.atlas.neighbors("tidb")) == 7
        assert table.size.width > 20
        assert table.size.height >= 3
        assert table.region.bottom <= size[1] - 2
        assert app.screen.has_class("compact") == (size[0] < 105)
        assert app.screen.has_class("no-evidence") == (size[0] < 140)
        assert app.screen.has_class("short") == (size[1] < 30)
        assert app.query_one("#sidebar").display == (size[0] >= 105)
        assert app.query_one("#evidence").display == (size[0] >= 140)
        if size[0] < 105:
            assert app.query_one("#sidebar").region.width == 0
        if size[0] < 140:
            assert app.query_one("#evidence").region.width == 0
        if size[1] < 30:
            assert app.query_one("#graph").size.height == 7
        assert "TiDB" in app.query_one("#context", Static).render().plain
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, DocumentModal)
        assert app.screen.query_one("#document-scroll").size.height > 0
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_resizing_live_terminal_reflows_actual_panes():
    app = AtlasApp()
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#sidebar").display
        assert app.query_one("#evidence").display
        wide_graph_height = app.query_one("#graph").size.height
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.query_one("#sidebar").display is False
        assert app.query_one("#sidebar").region.width == 0
        assert app.query_one("#evidence").display is False
        assert app.query_one("#evidence").region.width == 0
        assert app.query_one("#graph").size.height == 7
        assert app.query_one(DataTable).size.width > 70
        await pilot.resize_terminal(150, 40)
        await pilot.pause()
        assert app.query_one("#sidebar").display
        assert app.query_one("#sidebar").region.width > 0
        assert app.query_one("#evidence").display
        assert app.query_one("#evidence").region.width > 0
        assert app.query_one("#graph").size.height == wide_graph_height
        assert app.entity == "tidb"


@pytest.mark.asyncio
async def test_all_view_shortcuts_preserve_selected_entity():
    app = AtlasApp(start="postgresql")
    async with app.run_test(size=(120, 40)) as pilot:
        for index in range(10):
            await pilot.press(str(index))
            await pilot.pause()
            assert app.view_index == index
            assert app.entity == "postgresql"
            if index:
                matching = app.atlas.panels_for_entity(index - 1, "postgresql")
                assert app.panel_index == (matching[0] if matching else 0)
            assert app.query_one(DataTable).row_count == len(app.records)


@pytest.mark.asyncio
async def test_every_panel_and_full_ranking_render_without_losing_rows():
    app = AtlasApp()
    visited = 0
    async with app.run_test(size=(160, 44)) as pilot:
        for view in range(1, 10):
            app.action_view(view)
            for index, panel in enumerate(app.current_panels):
                app.panel_index = index
                app.rebuild()
                await pilot.pause()
                expected_rows = panel.get("edges", panel.get("rows", []))
                assert app.query_one(DataTable).row_count == len(expected_rows)
                assert len(app.records) == len(expected_rows)
                assert app.query_one("#graph").display == (panel["kind"] == "graph")
                if expected_rows:
                    app.query_one(DataTable).move_cursor(row=len(expected_rows) - 1)
                    await pilot.pause()
                    assert app.selected_index == len(expected_rows) - 1
                    assert app.source_url == expected_rows[-1].get("sourceUrl", "")
                visited += 1
        assert visited == 41  # 40 existing panels + full 440-row snapshot
        assert len(app.records) == 440
        assert app.records[-1]["name"] == app.atlas.popularity[-1]["name"]
        assert "热度" in app.detail_content.plain


@pytest.mark.asyncio
async def test_search_input_does_not_trigger_global_quit_or_view_shortcuts():
    app = AtlasApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(app.screen, SearchModal)
        await pilot.press("q", "1", "9", "0")
        assert app.screen.query_one(Input).value == "q190"
        assert app.view_index == 0
        assert app.entity == "tidb"
        assert app.screen.query_one(OptionList).option_count == 0
        await pilot.press("enter")
        assert isinstance(app.screen, SearchModal)
        await pilot.press("escape")
        assert not isinstance(app.screen, SearchModal)
        assert app.entity == "tidb"


@pytest.mark.asyncio
async def test_search_follow_and_back_use_canonical_nodes():
    app = AtlasApp(start="mysql")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("slash")
        await pilot.press("T", "i", "D", "B")
        await pilot.pause()
        assert app.screen.matches[0]["id"] == "tidb"
        await pilot.press("enter")
        await pilot.pause()
        assert app.entity == "tidb"
        row = next(i for i, r in enumerate(app.records) if r["target"] == "tikv")
        app.query_one(DataTable).move_cursor(row=row)
        await pilot.press("enter")
        await pilot.pause()
        assert app.entity == "tikv"
        assert app.view_index == 0
        await pilot.press("backspace")
        await pilot.pause()
        assert app.entity == "tidb"
        assert app.selected_index == row
        assert app.query_one(DataTable).cursor_row == row
        await pilot.press("backspace")
        await pilot.pause()
        assert app.entity == "mysql"


@pytest.mark.asyncio
async def test_panel_only_search_result_opens_evidence_without_inventing_node():
    app = AtlasApp()
    async with app.run_test(size=(120, 40)) as pilot:
        assert "pinot" not in app.atlas.nodes
        await pilot.press("slash", "P", "i", "n", "o", "t")
        await pilot.pause()
        assert app.screen.matches[0]["id"] == "panel:0:3"
        await pilot.press("enter")
        await pilot.pause()
        assert app.entity == "tidb", "Panel search must not invent a canonical product node"
        assert (app.view_index, app.panel_index) == (1, 3)
        assert any("Pinot" in r.get("source_label", "") for r in app.records)


@pytest.mark.asyncio
async def test_complete_evidence_preserves_conditions_and_source():
    app = AtlasApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert app.panel_index == 3  # TiDB execution model
        row = next(i for i, r in enumerate(app.records)
                   if r["source"] == "td" and r["target"] == "td_flash")
        app.query_one(DataTable).move_cursor(row=row)
        await pilot.pause()
        record = app.records[row]
        assert record["note"] in app.detail_content.plain
        assert record["sourceUrl"] in app.detail_content.plain
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, DocumentModal)
        assert app.screen.content.plain == app.detail_content.plain
        assert app.screen.source_url == record["sourceUrl"]
        # An evidence document owns focus: hidden main-screen shortcuts cannot
        # change the underlying view while the user reads it.
        await pilot.press("9", "space", "slash")
        assert isinstance(app.screen, DocumentModal)
        assert app.view_index == 5
        assert app.pins == []
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_direction_relation_filters_and_empty_intersection():
    app = AtlasApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f")
        assert app.direction == "out"
        assert app.records and all(r["source"] == "tidb" for r in app.records)
        await pilot.press("f")
        assert app.direction == "in"
        assert app.records and all(r["target"] == "tidb" for r in app.records)
        # An incoming dependency does not exist in the source snapshot. This
        # natural empty result must stay navigable and not be called unsupported.
        kinds = ["全部"] + sorted({r["relation"] for r in app.atlas.neighbors("tidb")})
        for _ in range(kinds.index("依赖")):
            await pilot.press("r")
        assert app.relation_filter == "依赖"
        assert app.records == []
        assert app.query_one(DataTable).row_count == 0
        assert "没有记录" in app.detail_content.plain
        assert "不受支持" in app.query_one("#status", Static).render().plain
        await pilot.press("e")
        assert isinstance(app.screen, DocumentModal)
        await pilot.press("escape", "f")
        assert app.direction == "both"
        assert app.records and all(r["relation"] == "依赖" for r in app.records)


@pytest.mark.asyncio
async def test_compare_pins_are_limited_toggleable_and_truthfully_labelled():
    app = AtlasApp()
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.press("space")
        assert app.pins == ["tidb"]
        app.open_entity("mysql")
        await pilot.press("space")
        app.open_entity("postgresql")
        await pilot.press("space")
        app.open_entity("rocksdb")
        await pilot.press("space")
        assert app.pins == ["tidb", "mysql", "postgresql"]
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, DocumentModal)
        content = rendered_text(app.screen.content)
        assert all(name in content for name in ["TiDB", "MySQL", "PostgreSQL"])
        assert "未收录不等于不支持" in content
        assert "热度不是性能" in content
        await pilot.press("escape")
        app.open_entity("mysql")
        await pilot.press("space")
        assert app.pins == ["tidb", "postgresql"]


@pytest.mark.asyncio
async def test_panel_keys_round_trip_and_back_restore_navigation():
    app = AtlasApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("3")
        old = app.panel_index
        await pilot.press("right_square_bracket")
        assert app.panel_index == (old + 1) % len(app.current_panels)
        await pilot.press("left_square_bracket")
        assert app.panel_index == old
        await pilot.press("backspace")
        assert app.panel_index == (old + 1) % len(app.current_panels)
        assert app.entity == "tidb"


@pytest.mark.asyncio
async def test_multiline_panel_product_identity_follows_to_canonical_node():
    app = AtlasApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("5")
        await pilot.pause()
        row = next(i for i, r in enumerate(app.records)
                   if r["source"] == "td" and r["target"] == "td_kv")
        app.query_one(DataTable).move_cursor(row=row)
        await pilot.press("enter")
        assert app.entity == "tikv", "TiKV's multiline panel role is still the canonical product"
        assert app.view_index == 0
        await pilot.press("backspace")
        assert (app.entity, app.view_index, app.panel_index) == ("tidb", 5, 3)


@pytest.mark.asyncio
async def test_mouse_navigation_and_panel_dropdown():
    app = AtlasApp()
    async with app.run_test(size=(160, 44)) as pilot:
        # The sidebar's six line is view 5 (0-based views).
        await pilot.click("#views", offset=(4, 5))
        await pilot.pause()
        assert app.view_index == 5
        assert app.panel_index == 3
        await pilot.click("#panels", offset=(4, 1))
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.panel_index == 4
        assert app.entity == "tidb"
        assert app.query_one(DataTable).has_focus


@pytest.mark.asyncio
async def test_source_opens_only_after_explicit_button_action(monkeypatch):
    opened = []
    monkeypatch.setattr("app.webbrowser.open", lambda url: opened.append(url))
    app = AtlasApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert opened == []
        await pilot.press("e")
        await pilot.pause()
        assert opened == []
        expected = app.screen.source_url
        await pilot.click("#open-source")
        assert opened == [expected]
        assert expected.startswith("https://")
        await pilot.click("#close-dialog")
        assert not isinstance(app.screen, DocumentModal)


def test_missing_snapshot_exits_with_actionable_path_not_traceback(tmp_path):
    result = subprocess.run([sys.executable, str(PROJECT / "app.py"), "--data-root", str(tmp_path)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "Cannot load atlas:" in result.stderr
    assert str(tmp_path) in result.stderr
    assert "--data-root" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("text,width", [("数据库 TiDB", 8), ("TiDB", 4), ("列式副本", 5)])
def test_graph_clipping_respects_terminal_character_cells(text, width):
    assert wcswidth(fit(text, width)) <= width
