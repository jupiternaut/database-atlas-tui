"""Read-only adapter for the existing database atlas snapshots.

The family graph and the nine perspective views deliberately remain separate:
panel-local IDs represent architectural roles, not globally unique products.
Alias resolution is only a navigation aid and never rewrites source claims.
This module uses the standard library and performs no network requests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / "data"
ENTITY_TYPES = {"product", "extension", "component", "historical"}

# These are spelling/product aliases, not compatibility or inheritance edges.
ALIASES = {
    "oracle database": "oracle",
    "microsoft sql server": "sql_server",
    "sqlserver": "sql_server",
    "db2": "ibm_db2",
    "apache cassandra": "cassandra",
    "apache hbase": "hbase",
    "apache doris": "doris",
    "apache druid": "druid",
    "apache kylin": "kylin",
    "apache pinot": "pinot",
    "apache hive": "hive",
    "apache lucene": "lucene",
    "apache flink": "flink",
    "apache solr": "solr",
    "apache iotdb": "iotdb",
    "amazon dynamodb": "dynamodb",
    "amazon redshift": "redshift",
    "amazon neptune": "neptune",
    "google cloud spanner": "spanner",
    "google spanner": "spanner",
    "google bigquery": "bigquery",
    "google cloud bigtable": "bigtable",
    "azure cosmos db": "cosmos_db",
    "databricks sql": "databricks",
    "tidb server": "tidb",
    "tidb self-managed": "tidb",
    "tikv regions": "tikv",
    "本地 rocksdb": "rocksdb",
    "sqlite 库": "sqlite",
    "mysql / innodb": "mysql",
    "mariadb server": "mariadb",
    "redis oss": "redis",
    "redis oss cluster": "redis",
    "yugabytedb / ysql": "yugabytedb",
    "vitess / vtgate": "vitess",
}

# These diagrams contain only implementation roles (e.g. shards / warehouses),
# so node-label matching alone cannot recover the product named by the panel.
# Explicit panel identity avoids accidentally matching products in edge prose.
PANEL_ENTITIES = {
    ("02-data-lifecycle", "示意 D：Elasticsearch 索引生命周期（配置后生效）"): "elasticsearch",
    ("03-architecture", "C · 路由分片：MongoDB"): "mongodb",
    ("03-architecture", "E · 存算分离：Snowflake 标准表"): "snowflake",
    ("03-architecture", "F · 客户端路由分片：Redis OSS Cluster"): "redis",
}


class AtlasDataError(ValueError):
    """A local snapshot is missing, malformed or internally inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            result = json.load(handle)
    except (OSError, ValueError) as error:
        raise AtlasDataError(f"Cannot read atlas snapshot {path}: {error}") from error
    if not isinstance(result, dict):
        raise AtlasDataError(f"Expected a JSON object in {path}")
    return result


def _normalized(text: str) -> str:
    return " ".join(str(text).strip().casefold().split())


class Atlas:
    """Load the original snapshots without flattening their different models.

    ``data_root`` accepts a snapshot directory, this repository root, or the
    original ``outputs`` directory / its containing workspace.
    Dictionaries retain their source fields; callers should treat them read-only.
    """

    def __init__(self, data_root: Path | str | None = None) -> None:
        root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
        for child in ("data", "outputs"):
            if (root / child / "database-graphs-v2" / "graph.json").is_file():
                root = root / child
                break
        self.data_root = root.resolve()
        self.graph = _read_json(self.data_root / "database-graphs-v2" / "graph.json")
        self.knowledge = _read_json(self.data_root / "database-perspectives-v3" / "knowledge.json")
        self.popularity_snapshot = _read_json(
            self.data_root / "database-perspectives-v3" / "popularity-observations.json"
        )
        try:
            graph_nodes = self.graph["nodes"]
            self.nodes: dict[str, dict[str, Any]] = {node["id"]: node for node in graph_nodes}
            self.edges: list[dict[str, Any]] = self.graph["edges"]
            self.views: list[dict[str, Any]] = self.knowledge["views"]
            self.month: str = self.graph["month"]
            # Scores/deltas/ranks remain exactly as observed: missing != zero.
            self.popularity: list[dict[str, Any]] = self.popularity_snapshot["rows"]
        except (KeyError, TypeError) as error:
            raise AtlasDataError(f"Invalid atlas schema under {self.data_root}: {error}") from error
        if len(self.nodes) != len(graph_nodes):
            raise AtlasDataError("Family graph contains duplicate node IDs")
        edge_ids = [edge.get("id") for edge in self.edges]
        if None in edge_ids or len(edge_ids) != len(set(edge_ids)):
            raise AtlasDataError("Family graph edges need unique IDs")
        for edge in self.edges:
            if edge.get("source") not in self.nodes or edge.get("target") not in self.nodes:
                raise AtlasDataError(f"Dangling family-graph edge: {edge.get('id')}")
        self._aliases: dict[str, str] = {}
        for node_id, node in self.nodes.items():
            if node.get("type") in ENTITY_TYPES:
                self._aliases[_normalized(node_id)] = node_id
                self._aliases[_normalized(node["label"])] = node_id
        self._aliases.update({alias: node_id for alias, node_id in ALIASES.items() if node_id in self.nodes})
        self._panel_entities: dict[tuple[int, int], set[str]] = {}
        for view_index, view in enumerate(self.views):
            for panel_index, panel in enumerate(view.get("panels", [])):
                entities: set[str] = set()
                for node in panel.get("nodes", []):
                    # A protocol/client concept is not the database product.
                    if node.get("kind") not in {"product", "component"}:
                        continue
                    entity = self.entity_for_text(node.get("label", ""))
                    if entity:
                        entities.add(entity)
                for row in panel.get("rows", []):
                    cells = row.get("cells", [])
                    label = cells[0] if cells else row.get("name", "")
                    entity = self.entity_for_text(label)
                    if entity:
                        entities.add(entity)
                known = PANEL_ENTITIES.get((view.get("id", ""), panel.get("title", "")))
                if known in self.nodes:
                    entities.add(known)
                self._panel_entities[view_index, panel_index] = entities

    def label(self, node_id: str) -> str:
        """Return the source label, or the ID for an unknown/local identifier."""
        return str(self.nodes.get(node_id, {}).get("label", node_id))

    def neighbors(self, node_id: str, direction: str = "both") -> list[dict[str, Any]]:
        """Return original directed claims, never inverted or synthesized.

        ``in`` / ``incoming`` and ``out`` / ``outgoing`` are accepted aliases.
        Unknown nodes have no neighbors; invalid direction is a caller error.
        """
        direction = {"incoming": "in", "outgoing": "out"}.get(direction, direction)
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be both, in/incoming, or out/outgoing")
        return [
            edge for edge in self.edges
            if (direction in {"out", "both"} and edge["source"] == node_id)
            or (direction in {"in", "both"} and edge["target"] == node_id)
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search labels/IDs/aliases, then descriptions; never silently cap results."""
        query = _normalized(query)
        aliases = {node_id for alias, node_id in self._aliases.items() if query and query in alias}
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for node_id, node in self.nodes.items():
            label = _normalized(node["label"])
            ident = _normalized(node_id)
            detail = _normalized(node.get("detail", ""))
            if not query:
                score = 0
            elif query in {label, ident}:
                score = 0
            elif label.startswith(query) or ident.startswith(query):
                score = 1
            elif query in label or query in ident or node_id in aliases:
                score = 2
            elif query in detail:
                score = 3
            else:
                continue
            scored.append((score, label, node))
        return [node for _, _, node in sorted(scored, key=lambda item: (item[0], item[1]))]

    def search_panels(self, query: str) -> list[dict[str, Any]]:
        """Find scoped panels, including products absent from the family graph.

        This is separate from canonical node search: the result identifies a
        view/panel, not a synthesized database identity. Only titles, local node
        labels, and row headings are searched, never edge prose or footnotes.
        """
        query = _normalized(query)
        if not query:
            return []
        matches: list[dict[str, Any]] = []
        for view_index, view in enumerate(self.views):
            for panel_index, panel in enumerate(view.get("panels", [])):
                headings = [panel.get("title", "")]
                headings.extend(node.get("label", "") for node in panel.get("nodes", []))
                for row in panel.get("rows", []):
                    cells = row.get("cells", [])
                    headings.append(cells[0] if cells else row.get("name", ""))
                if any(query in _normalized(heading) for heading in headings):
                    matches.append({
                        "view_index": view_index,
                        "panel_index": panel_index,
                        "title": panel.get("title", ""),
                    })
        return matches

    def entity_for_text(self, text: str) -> str | None:
        """Resolve a product/component heading, not arbitrary prose or concepts.

        Versions, slash-delimited deployment qualifiers, and parenthetical
        qualifiers may follow an exact heading. No fuzzy substring matching is
        used, so e.g. 'PostgreSQL-compatible' cannot become PostgreSQL.
        """
        if not text:
            return None
        first_line = _normalized(str(text).splitlines()[0])
        # Prevent named protocol/driver roles from masquerading as products.
        if re.search(r"协议|客户端|\bprotocol\b|\bdriver\b", str(text), re.I):
            return None
        if first_line in self._aliases:
            return self._aliases[first_line]
        # Qualified matrix rows: e.g. TiDB 7.5 / 常规事务, SQLite 3, TiFlash（可选）.
        for alias in sorted(self._aliases, key=len, reverse=True):
            if not first_line.startswith(alias):
                continue
            suffix = first_line[len(alias):]
            if re.match(r"^(?:\s*/|\s*[（(]|\s+v?\d+(?:\.|\s|$))", suffix):
                return self._aliases[alias]
        return None

    def panels_for_entity(self, view_index: int, node_id: str) -> list[int]:
        """Indices of panels explicitly containing an entity in this view.

        An empty list means the snapshot contains no matching panel; it does not
        mean the database lacks the capability represented by that viewpoint.
        """
        if view_index < 0 or view_index >= len(self.views):
            return []
        return [
            index for index, _ in enumerate(self.views[view_index].get("panels", []))
            if node_id in self._panel_entities.get((view_index, index), set())
        ]
