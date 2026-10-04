"""Snapshot and navigation contracts; no requests to live database services."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas_data import Atlas, AtlasDataError, DEFAULT_DATA_ROOT


@pytest.fixture(scope="module")
def atlas():
    return Atlas()


def test_original_graph_and_views_are_not_lossily_flattened(atlas):
    assert len(atlas.nodes) == 223
    assert len(atlas.edges) == 417
    assert len(atlas.views) == 9
    assert sum(len(view["panels"]) for view in atlas.views) == 40
    assert len(atlas.popularity) == 440
    assert atlas.month == "2026-10"
    assert atlas.knowledge["generatedFor"] == "2026-10-04"
    assert sum(len(p.get("edges", [])) for v in atlas.views for p in v["panels"]) == 182
    assert sum(len(p.get("rows", [])) for v in atlas.views for p in v["panels"] if p["kind"] == "matrix") == 44


def test_workspace_root_and_outputs_root_are_accepted(atlas):
    assert Atlas(DEFAULT_DATA_ROOT.parent).nodes == atlas.nodes
    assert Atlas(DEFAULT_DATA_ROOT).views == atlas.views


def test_bundled_data_is_resolved_independently_of_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert Atlas().nodes["tidb"]["label"] == "TiDB"
    assert DEFAULT_DATA_ROOT == Path(__file__).resolve().parents[1] / "data"


def test_original_workspace_outputs_layout_remains_supported(tmp_path):
    import shutil
    shutil.copytree(DEFAULT_DATA_ROOT, tmp_path / "outputs")
    assert Atlas(tmp_path).views == Atlas().views


def test_missing_data_reports_exact_path(tmp_path):
    with pytest.raises(AtlasDataError, match=str(tmp_path)):
        Atlas(tmp_path)


def test_reading_and_navigation_never_write_sources(atlas):
    paths = [
        DEFAULT_DATA_ROOT / "database-graphs-v2/graph.json",
        DEFAULT_DATA_ROOT / "database-perspectives-v3/knowledge.json",
        DEFAULT_DATA_ROOT / "database-perspectives-v3/popularity-observations.json",
    ]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    other = Atlas()
    other.search("TiDB")
    other.neighbors("tidb")
    other.panels_for_entity(4, "tidb")
    assert before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    assert atlas.graph["nodes"] == json.loads(paths[0].read_text())["nodes"]


def test_direction_compatibility_is_not_derivation(atlas):
    edges = atlas.neighbors("tidb", "out")
    compat = next(e for e in edges if e["target"] == "mysql")
    assert compat["source"] == "tidb"
    assert compat["relation"] == "兼容"
    assert "非源码分支" in compat["detail"]
    assert compat["id"] == "e241"
    assert compat["sourceUrl"].startswith("https://docs.pingcap.com/")
    assert compat in atlas.neighbors("mysql", "incoming")
    assert compat not in atlas.neighbors("tidb", "in")
    assert atlas.neighbors("tidb", "outgoing") == edges
    assert atlas.neighbors("missing") == []
    with pytest.raises(ValueError):
        atlas.neighbors("tidb", "backwards")


def test_original_component_conditions_survive(atlas):
    edges = atlas.neighbors("tidb")
    kv = next(e for e in edges if e["target"] == "tikv")
    flash = next(e for e in edges if e["target"] == "tiflash")
    assert kv["detail"] == "经典行存路径"
    assert flash["relation"] == "可选组件"
    assert flash["detail"] == "分析列式副本"
    execution = atlas.views[4]["panels"][3]
    flash_route = next(e for e in execution["edges"] if e["source"] == "td" and e["target"] == "td_flash")
    assert flash_route["note"]
    assert flash_route["sourceUrl"]
    # Panel IDs remain local; they are NOT a destructive canonical merge.
    assert "td" in {n["id"] for n in execution["nodes"]}
    assert "td" not in atlas.nodes


def test_search_is_casefolded_exact_first_and_not_capped(atlas):
    assert atlas.search(" TIDB ")[0]["id"] == "tidb"
    assert atlas.search("Microsoft SQL Server")[0]["id"] == "sql_server"
    assert len(atlas.search("")) == len(atlas.nodes)
    assert atlas.search("no such database 987654321") == []
    assert any(n["id"] == "wide_column" for n in atlas.search("列族"))
    assert atlas.label("tidb") == "TiDB"
    assert atlas.label("unmapped-panel-id") == "unmapped-panel-id"


@pytest.mark.parametrize("text,expected", [
    ("TiDB Server\n解析 / 优化 / 分布式计划", "tidb"),
    ("TiDB 7.5 / 常规事务", "tidb"),
    ("TiDB Self-Managed", "tidb"),
    ("TiKV Regions\n分片 + Raft 副本", "tikv"),
    ("TiFlash（可选）\n列式副本", "tiflash"),
    ("本地 RocksDB\n常规 TiKV 存储路径", "rocksdb"),
    ("PostgreSQL 18", "postgresql"),
    ("MySQL 8.4 / InnoDB", "mysql"),
    ("MariaDB Server / InnoDB", "mariadb"),
    ("SQLite 库\n进程内", "sqlite"),
    ("Apache Doris", "doris"),
    ("Google Cloud Spanner", "spanner"),
    ("MySQL\n网络协议 / 客户端入口", None),
    ("PostgreSQL-compatible product", None),
    ("This database uses PostgreSQL", None),
    ("OLTP", None),
    ("", None),
])
def test_aliases_are_conservative(atlas, text, expected):
    assert atlas.entity_for_text(text) == expected


def test_entity_panel_navigation_preserves_evidence_scope(atlas):
    assert atlas.panels_for_entity(0, "tidb") == [1, 4]
    assert atlas.panels_for_entity(2, "tidb") == [3]
    assert atlas.panels_for_entity(3, "tidb") == [0]
    assert atlas.panels_for_entity(4, "tidb") == [3]
    assert atlas.panels_for_entity(5, "tidb") == [1]
    assert atlas.panels_for_entity(6, "tidb") == [1]
    assert atlas.panels_for_entity(8, "tidb") == [2]
    assert atlas.panels_for_entity(7, "tidb") == []  # no invented application deployment
    assert atlas.panels_for_entity(2, "mongodb") == [2]
    assert atlas.panels_for_entity(2, "snowflake") == [4]
    assert atlas.panels_for_entity(2, "redis") == [5]
    assert atlas.panels_for_entity(1, "elasticsearch") == [3]
    assert atlas.panels_for_entity(2, "mysql") == []  # protocol client != MySQL server
    assert atlas.panels_for_entity(-1, "tidb") == []
    assert atlas.panels_for_entity(99, "tidb") == []


def test_popularity_is_the_original_dated_observation_not_usage(atlas):
    oracle = atlas.popularity[0]
    assert oracle["rank"] == 1
    assert oracle["score"] == 1119.79
    assert oracle["monthDelta"] == -2.48
    assert atlas.popularity_snapshot["month"] == "2026-10"
    assert "not usage count" in atlas.graph["metric"]
    for node in atlas.nodes.values():
        if "score" not in node:
            assert node.get("score") is None  # missing scores are not fabricated zeroes


@pytest.mark.parametrize("query,location", [
    (" pinot ", (0, 3)),
    ("VITESS", (5, 1)),
    ("Dragonfly", (5, 2)),
    ("Garnet", (5, 2)),
    ("DocumentDB", (5, 3)),
])
def test_panel_only_products_have_searchable_scoped_navigation(atlas, query, location):
    results = atlas.search_panels(query)
    assert location in {(row["view_index"], row["panel_index"]) for row in results}
    for row in results:
        assert row["title"] == atlas.views[row["view_index"]]["panels"][row["panel_index"]]["title"]
        assert "id" not in row
    assert len(atlas.nodes) == 223


def test_panel_search_headings_not_arbitrary_evidence(atlas):
    assert atlas.search_panels("") == []
    assert atlas.search_panels("  ") == []
    assert atlas.search_panels("nonexistent product 987654321") == []
    assert atlas.search_panels("standalone") == []  # appears only in MongoDB evidence note
    results = atlas.search_panels("TiDB 7.5")
    assert [(row["view_index"], row["panel_index"]) for row in results] == [(3, 0)]
    assert [(row["view_index"], row["panel_index"]) for row in atlas.search_panels("迁移验证矩阵")] == [(5, 6)]
