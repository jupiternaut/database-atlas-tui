"""Read-only, local terminal explorer for the existing database atlas."""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse
import webbrowser

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import on, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, OptionList, Select, Static
from wcwidth import wcswidth

from atlas_data import Atlas

VIEW_NAMES = ["关系地图", "工作负载", "数据生命周期", "分布式架构", "事务与一致性",
              "存储与执行", "兼容与迁移", "部署与运维", "应用生态", "普及度与变化"]
KIND_NAMES = {"product": "产品", "component": "组件", "extension": "扩展",
              "application": "应用", "category": "分类", "axis": "维度", "root": "入口"}


def plain(value) -> str:
    return str(value or "").replace("\n", " · ")


def fit(value: str, width: int) -> str:
    """Clip by display cells, never by codepoint count (CJK occupies two)."""
    value = plain(value)
    if wcswidth(value) <= width:
        return value
    result = ""
    for char in value:
        if wcswidth(result + char) > max(0, width - 1):
            break
        result += char
    return result + "…"


class DocumentModal(ModalScreen):
    BINDINGS = [("escape", "dismiss", "关闭"), ("q", "dismiss", "关闭")]

    def __init__(self, title, content, source_url=""):
        super().__init__()
        self.title_text, self.content, self.source_url = title, content, source_url

    def compose(self) -> ComposeResult:
        with Vertical(id="document-dialog"):
            yield Static(Text(self.title_text, style="bold"), id="dialog-title")
            with VerticalScroll(id="document-scroll"):
                yield Static(self.content, markup=False)
            with Horizontal(id="dialog-actions"):
                if urlparse(self.source_url).scheme in ("http", "https"):
                    yield Button("打开来源", id="open-source")
                yield Button("关闭 [Esc]", id="close-dialog")

    @on(Button.Pressed, "#close-dialog")
    def close_dialog(self):
        self.dismiss()

    @on(Button.Pressed, "#open-source")
    def open_source(self):
        # Only explicit user action opens a source. No requests at startup.
        webbrowser.open(self.source_url)


class SearchModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "关闭")]

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Static("搜索数据库 / 分类 / 组件", id="dialog-title")
            yield Input(placeholder="例如 TiDB、PostgreSQL、图数据库", id="search-input")
            yield OptionList(id="search-results")
            yield Static("↑↓ 选择 · Enter 打开 · Esc 返回", classes="hint")

    def on_mount(self):
        self.matches = []
        self.update_results("")
        self.query_one(Input).focus()

    def update_results(self, value):
        self.matches = self.app.atlas.search(value)
        self.matches += [{"id": f"panel:{p['view_index']}:{p['panel_index']}",
                          "label": p["title"], "type": "视角面板"}
                         for p in self.app.atlas.search_panels(value)]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([Text(f"{n['label']}  / {KIND_NAMES.get(n.get('type'), n.get('type', ''))}") for n in self.matches])
        if self.matches:
            options.highlighted = 0

    @on(Input.Changed)
    def changed(self, event):
        self.update_results(event.value)

    @on(Input.Submitted)
    def submit(self):
        self.choose()

    @on(OptionList.OptionSelected)
    def selected(self):
        self.choose()

    def choose(self):
        index = self.query_one(OptionList).highlighted
        if index is not None and index < len(self.matches):
            self.dismiss(self.matches[index]["id"])

    def on_key(self, event):
        if event.key in ("down", "up") and self.query_one(Input).has_focus:
            options = self.query_one(OptionList)
            if self.matches:
                current = options.highlighted or 0
                options.highlighted = (current + (1 if event.key == "down" else -1)) % len(self.matches)
            event.prevent_default()
            event.stop()

    def action_cancel(self):
        self.dismiss(None)


class AtlasApp(App):
    TITLE = "DATABASE ATLAS / 数据库关系图谱"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "atlas.tcss"
    BINDINGS = [
        Binding("slash", "search", "搜索"),
        Binding("q", "quit", "退出"),
        Binding("question_mark", "help", "帮助"),
        Binding("e", "evidence", "证据"),
        Binding("backspace", "back", "返回"),
        Binding("left_square_bracket", "panel(-1)", "上个面板"),
        Binding("right_square_bracket", "panel(1)", "下个面板"),
        Binding("f", "direction", "方向"),
        Binding("r", "relation", "关系类型"),
        Binding("space", "pin", "加入对照"),
        Binding("c", "compare", "对照"),
        Binding("v", "view_menu", "视角"),
        *[Binding(str(i), f"view({i})", VIEW_NAMES[i], show=False) for i in range(10)],
    ]

    def __init__(self, data_root=None, start="tidb"):
        super().__init__()
        self.atlas = Atlas(data_root) if data_root else Atlas()
        self.entity = start if start in self.atlas.nodes else "database"
        self.view_index = 0
        self.panel_index = 0
        self.history = []
        self.pins = []
        self.direction = "both"
        self.relation_filter = "全部"
        self.records = []
        self.selected_index = 0
        self.detail_content = Text("")
        self.source_url = ""
        self._rebuilding = False

    def compose(self) -> ComposeResult:
        yield Static(id="masthead")
        yield Static(id="context")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("VIEWS / 观察视角", classes="section-title")
                yield OptionList(*[Text(f"{i}  {name}") for i, name in enumerate(VIEW_NAMES)], id="views")
                yield Static(id="inventory")
                yield Static(id="pins")
            with Vertical(id="workspace"):
                yield Select([("关系地图", 0)], id="panels", allow_blank=False)
                yield Static(id="panel-caption")
                yield Static(id="graph", markup=False)
                yield DataTable(id="relations", cursor_type="row", zebra_stripes=False)
            with VerticalScroll(id="evidence"):
                yield Static("EVIDENCE / 关系证据", classes="section-title")
                yield Static(id="details", markup=False)
        yield Static(id="status")
        yield Static("/ 搜索  0–9 视角  ↑↓ 选择  Enter 跟随  e 证据  ? 帮助  q 退出", id="keys")

    def on_mount(self):
        self.theme = "textual-light"
        self.query_one("#inventory", Static).update(
            f"{len(self.atlas.nodes)} nodes\n{len(self.atlas.edges)} relations\n40 panels / 9 views\n\nLOCAL · READ ONLY\n数据快照 {self.atlas.month}"
        )
        self.update_pins()
        self.on_resize()
        self.rebuild()
        self.query_one("#relations").focus()

    def on_resize(self, event: events.Resize | None = None):
        size = event.size if event else self.size
        self.screen_stack[0].set_class(size.width < 105, "compact")
        self.screen_stack[0].set_class(size.width < 140, "no-evidence")
        self.screen_stack[0].set_class(size.height < 30, "short")
        if self.is_mounted and len(self.screen_stack) == 1:
            self.call_after_refresh(self.draw_graph)

    def check_action(self, action, parameters):
        # Modal documents own their keys; don't mutate the obscured main view.
        return len(self.screen_stack) <= 1

    @property
    def current_panels(self):
        if not self.view_index:
            return []
        panels = list(self.atlas.views[self.view_index - 1]["panels"])
        if self.view_index == 9:
            panels.append({"title": "完整榜单 · 440 条历史快照", "kind": "bars", "rows": self.atlas.popularity,
                           "sourceUrl": "https://db-engines.com/en/ranking"})
        return panels

    def remember(self):
        self.history.append((self.entity, self.view_index, self.panel_index, self.direction, self.relation_filter, self.selected_index))

    def rebuild(self):
        self._rebuilding = True
        self.query_one("#views", OptionList).highlighted = self.view_index
        panel_select = self.query_one("#panels", Select)
        panel_select.display = bool(self.view_index)
        node = self.atlas.nodes[self.entity]
        self.query_one("#masthead", Static).update(Text("DATABASE ATLAS  /  数据库关系图谱", style="bold"))
        self.query_one("#context", Static).update(Text(f"{self.view_index:02d} {VIEW_NAMES[self.view_index]}  /  焦点 {node['label']}  /  {self.atlas.month} 快照"))
        table = self.query_one("#relations", DataTable)
        table.clear(columns=True)
        self.records = []
        self.selected_index = 0
        self.source_url = ""
        if not self.view_index:
            edges = self.atlas.neighbors(self.entity, direction=self.direction)
            if self.relation_filter != "全部":
                edges = [e for e in edges if e["relation"] == self.relation_filter]
            table.add_columns("源节点", "关系", "目标节点")
            for edge in edges:
                record = dict(edge, kind="edge")
                record["source_label"] = self.atlas.label(edge["source"])
                record["target_label"] = self.atlas.label(edge["target"])
                record["neighbor"] = edge["target"] if edge["source"] == self.entity else edge["source"]
                self.records.append(record)
            direction_label = {"both": "双向", "out": "出边", "in": "入边"}[self.direction]
            caption = f"一跳邻域 · {len(edges)} 条关系 · {direction_label} · {self.relation_filter}  [f/r 筛选]"
        else:
            panels = self.current_panels
            self.panel_index = min(self.panel_index, len(panels) - 1)
            with panel_select.prevent(Select.Changed):
                panel_select.set_options([(p["title"], i) for i, p in enumerate(panels)])
                panel_select.value = self.panel_index
                # Different views reuse numeric panel IDs. Refresh the label even
                # when the selected number is still zero after options changed.
                panel_select.mutate_reactive(Select.value)
            panel = panels[self.panel_index]
            kind = panel["kind"]
            matches = self.atlas.panels_for_entity(self.view_index - 1, self.entity)
            scope = ("焦点相关" if self.panel_index in matches else
                     "焦点未收录；浏览全体" if not matches else "浏览面板全体（非焦点专属）")
            caption = f"{self.panel_index + 1}/{len(panels)} · {scope} · [ / ] 切换面板"
            if kind == "graph":
                table.add_columns("源节点", "关系", "目标节点")
                nodes = {n["id"]: n for n in panel["nodes"]}
                for edge in panel["edges"]:
                    self.records.append(dict(edge, kind="edge", relation=edge["label"],
                        source_label=plain(nodes[edge["source"]]["label"]),
                        target_label=plain(nodes[edge["target"]]["label"]),
                        source_entity=self.atlas.entity_for_text(nodes[edge["source"]]["label"]),
                        target_entity=self.atlas.entity_for_text(nodes[edge["target"]]["label"]),
                        detail=edge.get("note", "")))
            elif kind == "matrix":
                table.add_columns(*panel["columns"])
                for row in panel["rows"]:
                    self.records.append(dict(row, kind="matrix", columns=panel["columns"]))
            else:
                table.add_columns("名次", "产品", "分数", "环比 Δ", "线性分数 / 0 起点" if kind == "bars" else "环比变化 / 0 中心")
                maximum = max((r.get("score", 0) or 0 for r in panel["rows"]), default=1) or 1
                delta_max = max((abs(r.get("monthDelta", 0) or 0) for r in panel["rows"]), default=1) or 1
                for row in panel["rows"]:
                    score, delta = row.get("score"), row.get("monthDelta")
                    if kind == "bars":
                        bar = "—" if score is None else "█" * round(score / maximum * 18)
                    else:
                        length = round(abs(delta or 0) / delta_max * 9)
                        bar = "—" if delta is None else (("█" * length).rjust(9) + "│" if delta < 0 else " " * 9 + "│" + "█" * length)
                    cells = [str(row.get("rank", "—")), row["name"], "—" if score is None else f"{score:.2f}",
                             "—" if delta is None else f"{delta:+.2f}", bar]
                    self.records.append(dict(row, kind="popularity", cells=cells))
                caption = f"{self.panel_index + 1}/{len(panels)} · 热度 ≠ 使用率 / 市占率 · {self.atlas.month} · {len(self.records)} 条"
        self.query_one("#panel-caption", Static).update(Text(caption))
        # Fixed, bounded widths keep the initial cells legible; horizontal scrolling
        # and the full evidence view expose text that cannot fit in a narrow terminal.
        widths = [wcswidth(str(col.label)) for col in table.columns.values()]
        for index, record in enumerate(self.records):
            cells = ([record["source_label"], record["relation"], record["target_label"]]
                     if record["kind"] == "edge" else record["cells"])
            table.add_row(*[Text(plain(c)) for c in cells], key=str(index), height=1)
            widths = [max(width, wcswidth(plain(cell))) for width, cell in zip(widths, cells)]
        for column, width in zip(table.columns.values(), widths):
            column.auto_width = False
            column.width = min(28, max(8, width))
        if self.records:
            table.move_cursor(row=0, column=0, animate=False)
            self.show_record(0)
        else:
            self.detail_content = Text("此筛选条件下没有记录。\n按 f / r 更换筛选，或 / 搜索其他节点。")
            self.query_one("#details", Static).update(self.detail_content)
            self.draw_graph()
            self.set_status("无匹配关系；不是『该能力不受支持』。")
        self._rebuilding = False
        self.call_after_refresh(self.draw_graph)

    def draw_graph(self):
        graph = self.query_one("#graph", Static)
        is_graph = not self.view_index or self.current_panels[self.panel_index]["kind"] == "graph"
        graph.display = is_graph
        if not is_graph:
            return
        width = max(20, self.query_one("#workspace").size.width - 4)
        lines = Text()
        if not self.view_index:
            label = fit(self.atlas.label(self.entity), min(width - 4, 32))
            cells = max(1, wcswidth(label))
            lines.append("┌─" + "─" * cells + "─┐\n│ " + label + " │\n└─" + "─" * cells + "─┘\n", style="bold")
            limit = 3 if self.size.height < 30 else 7
            shown = list(range(min(limit, len(self.records))))
            if self.selected_index >= limit:
                shown[-1:] = [self.selected_index]
            for n, idx in enumerate(shown):
                r = self.records[idx]
                inward = r["target"] == self.entity
                other = r["source_label"] if inward else r["target_label"]
                line = f"{'└' if n == len(shown)-1 else '├'}─ {'←' if inward else '→'} {other}  / {r['relation']}"
                lines.append(fit(line, width) + "\n", style="reverse" if idx == self.selected_index else "")
            if len(self.records) > limit:
                lines.append(f"   … {len(self.records)} 条完整关系见下表")
        elif self.records:
            r = self.records[self.selected_index]
            lines.append("SELECTED RELATION / 当前关系\n", style="bold")
            lines.append(f"┌ {fit(r['source_label'], width - 4)}\n│\n├─ {fit(r['relation'], width - 6)}\n│\n└→ {fit(r['target_label'], width - 4)}")
        graph.update(lines)

    def show_record(self, index):
        if index >= len(self.records):
            return
        self.selected_index = index
        r = self.records[index]
        text = Text()
        if r["kind"] == "edge":
            text.append(r["source_label"] + "\n  ── " + r["relation"] + " ──▶\n" + r["target_label"] + "\n\n", style="bold")
            text.append("条件 / 范围\n", style="bold")
            text.append((r.get("detail") or r.get("note") or "原资料未单列条件；不等于无条件成立。") + "\n\n")
            text.append("关系说明\n", style="bold")
            text.append("箭头固定为源 → 目标。兼容不是继承；可选组件不是必需依赖。\n\n")
        elif r["kind"] == "matrix":
            for name, value in zip(r["columns"], r["cells"]):
                text.append(name + "\n", style="bold")
                text.append(str(value) + "\n\n")
            text.append("条件 / 版本\n", style="bold")
            text.append(r.get("note", "原资料未单列条件。") + "\n\n")
        else:
            text.append(f"{r['name']}\n\n", style="bold")
            for name, key in [("本期名次", "rank"), ("热度分数", "score"), ("上月名次", "previousMonthRank"),
                              ("去年同期名次", "previousYearRank"), ("分数环比", "monthDelta"), ("分数同比", "yearDelta")]:
                value = r.get(key)
                text.append(f"{name}: {'未收录' if value is None else value}\n")
            text.append(f"\n本地快照 {self.atlas.month}，不实时刷新。\n热度指标，不是安装量、性能或招聘数量。只有离散时点，不推导连续趋势。\n\n")
        if self.view_index:
            view = self.atlas.views[self.view_index - 1]
            if view.get("takeaway"):
                text.append("视角说明\n", style="bold")
                text.append(view["takeaway"] + "\n\n")
        self.source_url = r.get("sourceUrl", "")
        text.append("SOURCE / 来源\n", style="bold")
        text.append(self.source_url or "未收录来源")
        self.detail_content = text
        self.query_one("#details", Static).update(text)
        self.draw_graph()
        self.set_status(f"{index + 1}/{len(self.records)}  ·  e 查看完整条件与来源  ·  Space 收藏焦点  ·  c 对照")

    def set_status(self, message):
        self.query_one("#status", Static).update(Text(message))

    @on(DataTable.RowHighlighted, "#relations")
    def row_highlighted(self, event):
        if not self._rebuilding and event.row_key.value is not None:
            self.show_record(int(event.row_key.value))

    @on(DataTable.RowSelected, "#relations")
    def follow_row(self, event):
        if not self.records:
            return
        r = self.records[int(event.row_key.value)]
        if not self.view_index:
            self.open_entity(r["neighbor"], keep_view=False)
        else:
            # Panel-local IDs are never treated as canonical entity IDs.
            candidate = (r.get("target_label") if r["kind"] == "edge" else r.get("name") or r.get("cells", [""])[0])
            entity = r.get("target_entity") if r["kind"] == "edge" else self.atlas.entity_for_text(candidate or "")
            if r["kind"] == "edge" and (not entity or entity == self.entity):
                entity = r.get("source_entity")
            if entity:
                self.open_entity(entity, keep_view=False)
            else:
                self.action_evidence()

    @on(OptionList.OptionSelected, "#views")
    def choose_view(self, event):
        self.action_view(event.option_index)

    @on(Select.Changed, "#panels")
    def choose_panel(self, event):
        if not self._rebuilding and isinstance(event.value, int) and event.value != self.panel_index:
            self.remember()
            self.panel_index = event.value
            self.rebuild()
            self.query_one("#relations").focus()

    def open_entity(self, entity, keep_view=True):
        if not entity:
            return
        self.remember()
        self.entity = entity
        self.direction, self.relation_filter = "both", "全部"
        if not keep_view:
            self.view_index = 0
        if self.view_index:
            matches = self.atlas.panels_for_entity(self.view_index - 1, entity)
            self.panel_index = matches[0] if matches else 0
        self.rebuild()
        self.query_one("#relations").focus()

    def action_search(self):
        self.push_screen(SearchModal(), self.open_search_result)

    def open_search_result(self, result):
        if result and result.startswith("panel:"):
            _, view, panel = result.split(":")
            self.remember()
            self.view_index, self.panel_index = int(view) + 1, int(panel)
            self.rebuild()
            self.query_one("#relations").focus()
        else:
            self.open_entity(result)

    def action_view(self, index):
        self.remember()
        self.view_index, self.panel_index = index, 0
        if index:
            matches = self.atlas.panels_for_entity(index - 1, self.entity)
            self.panel_index = matches[0] if matches else 0
        self.rebuild()
        self.query_one("#relations").focus()

    def action_panel(self, offset):
        if self.view_index:
            self.remember()
            self.panel_index = (self.panel_index + offset) % len(self.current_panels)
            self.rebuild()

    def action_back(self):
        if self.history:
            self.entity, self.view_index, self.panel_index, self.direction, self.relation_filter, selected = self.history.pop()
            self.rebuild()
            if self.records:
                selected = min(selected, len(self.records) - 1)
                self.query_one("#relations", DataTable).move_cursor(row=selected, animate=False)
                self.show_record(selected)

    def action_direction(self):
        if not self.view_index:
            self.direction = {"both": "out", "out": "in", "in": "both"}[self.direction]
            self.rebuild()

    def action_relation(self):
        if not self.view_index:
            kinds = ["全部"] + sorted({r["relation"] for r in self.atlas.neighbors(self.entity)})
            self.relation_filter = kinds[(kinds.index(self.relation_filter) + 1) % len(kinds)]
            self.rebuild()

    def action_evidence(self):
        self.push_screen(DocumentModal("EVIDENCE / 完整记录", self.detail_content, self.source_url))

    def action_view_menu(self):
        content = Text("视角快捷键\n\n" + "\n".join(f"{i}  {n}" for i, n in enumerate(VIEW_NAMES)) + "\n\nEsc 关闭后按数字切换；当前焦点会保留。")
        self.push_screen(DocumentModal("VIEWS / 视角导航", content))

    def update_pins(self):
        self.query_one("#pins", Static).update("COMPARE / 对照篮\n" + ("\n".join(self.atlas.label(n) for n in self.pins) or "尚未加入\nSpace 添加焦点\nc 打开对照"))

    def action_pin(self):
        if self.entity in self.pins:
            self.pins.remove(self.entity)
        elif len(self.pins) < 3:
            self.pins.append(self.entity)
        else:
            self.set_status("最多对照 3 项；回到已选节点按 Space 移除。")
            return
        self.update_pins()
        self.set_status("对照篮: " + (" / ".join(self.atlas.label(n) for n in self.pins) or "空") + "  [c 查看]")

    def action_compare(self):
        if not self.pins:
            self.set_status("先按 Space 将当前焦点加入对照篮；搜索第二个产品后再按 Space。")
            return
        table = Table(box=None, expand=True, padding=(0, 1), header_style="bold", border_style="black")
        table.add_column("字段")
        for n in self.pins:
            table.add_column(self.atlas.label(n))
        nodes = [self.atlas.nodes[n] for n in self.pins]
        table.add_row("对象类型", *[KIND_NAMES.get(n.get("type"), n.get("type", "未收录")) for n in nodes])
        table.add_row("数据模型", *[", ".join(n.get("models", [])) or "未收录" for n in nodes])
        table.add_row(f"{self.atlas.month} 热度名次", *[str(n.get("rank") or "未收录") for n in nodes])
        table.add_row("热度分数", *[str(n["score"]) if n.get("score") is not None else "未收录" for n in nodes])
        table.add_row("一跳关系数", *[str(len(self.atlas.neighbors(n))) for n in self.pins])
        table.add_row("已收录视角", *[" / ".join(str(i + 1) for i in range(9) if self.atlas.panels_for_entity(i, n)) or "未收录" for n in self.pins])
        sources = Text("\n热度不是性能或市场占有率；未收录不等于不支持。\n关系数只表示这份图谱的收录情况。\n\n")
        for n in nodes:
            sources.append(n["label"] + "\n" + (n.get("sourceUrl") or "原节点未收录来源") + "\n\n")
        self.push_screen(DocumentModal("COMPARE / 描述性对照", Group(table, sources)))

    def action_help(self):
        self.push_screen(DocumentModal("DATABASE ATLAS / 操作手册", Text(
            "/       搜索数据库、组件或分类；输入时数字不会切换视角\n"
            "0       原关系图的一跳邻域（不是排他分类树）\n"
            "1–9     九种观察视角；保留当前焦点，优先相关面板\n"
            "[ / ]   上一个 / 下一个面板；也可点击顶部选择框\n"
            "↑ / ↓   选择关系或表格行，右侧同步显示证据\n"
            "Enter   原图中跟随邻接节点；视角中打开可识别产品或证据\n"
            "Backspace 返回上一焦点 / 视角 / 面板\n"
            "f / r   在关系地图中循环筛选方向 / 关系类型\n"
            "e       完整记录、条件和来源；可显式打开外部来源\n"
            "Space   当前焦点加入 / 移出对照篮（最多 3 项）\n"
            "c       查看描述性对照\n"
            "Tab     在控件之间切换；← → 横向滚动宽表\n"
            "Esc     关闭弹窗；q 退出\n\n"
            "设计原则\n"
            "同一数据库可跨越多种视角，不能把兼容关系画成继承。\n"
            "窄终端自动收起导航与证据；e 随时看全文。\n"
            "图中的架构来自文档，不是本机服务拓扑。\n"
            "仅读取本地历史快照；不连接或修改任何数据库。\n"
            "字体由终端设置决定；中文须配备 CJK 字体。")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, help="Atlas outputs directory (original snapshots, read-only)")
    parser.add_argument("--start", default="tidb", help="Canonical graph node id, default: tidb")
    args = parser.parse_args()
    try:
        app = AtlasApp(args.data_root, args.start)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Cannot load atlas: {error}\nUse --data-root /absolute/path/to/outputs\n")
    app.run()


if __name__ == "__main__":
    main()
