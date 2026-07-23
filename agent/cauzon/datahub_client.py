"""DataHub access layer for Cauzon.

Wraps the DataHub MCP tools the agent needs:
  search, get_entities, get_lineage, get_lineage_paths_between,
  list_schema_fields, get_dataset_queries, and the mutation/document tools
  (add_tags, update_description, add_owners, save_document).

Two backends are provided behind one interface:

  1. `MCPDataHubClient` — talks to a real DataHub instance via the
     `datahub-agent-context` Python SDK / MCP server. Use this for the real demo.
  2. `MockDataHubClient` — a self-contained fixture graph with a *planted*
     freshness bug (mirrors the nyc-taxi sample datapack). Lets the whole app run
     and be demoed with zero infrastructure, and powers deterministic tests.

Select with CAUZON_DATAHUB_BACKEND=mcp|mock (default: mock).
"""

from __future__ import annotations

import os
from typing import Any, Optional, Protocol


class DataHubClient(Protocol):
    """Interface the agent depends on. Both backends implement this."""

    def list_open_incidents(self) -> list[dict[str, Any]]: ...
    def search(self, query: str) -> list[dict[str, Any]]: ...
    def get_entity(self, urn: str) -> dict[str, Any]: ...
    def get_lineage(self, urn: str, direction: str = "upstream", hops: int = 3) -> list[dict[str, Any]]: ...
    def get_lineage_paths_between(self, source_urn: str, target_urn: str) -> list[dict[str, Any]]: ...
    def list_schema_fields(self, urn: str) -> list[dict[str, Any]]: ...
    def get_dataset_queries(self, urn: str) -> list[dict[str, Any]]: ...
    # mutations / write-back
    def add_tags(self, urn: str, tags: list[str]) -> None: ...
    def update_description(self, urn: str, description: str) -> None: ...
    def save_document(self, title: str, content: str, related_urns: list[str]) -> str: ...


# --------------------------------------------------------------------------- #
# Mock backend: small graphs with planted, discoverable faults.
#
# Two named scenarios are provided (selectable via CAUZON_MOCK_SCENARIO):
#
#   "freshness" (default) — ingestion stall propagates staleness:
#       raw_trips -> trips_cleaned -> daily_revenue -> revenue_dashboard
#       Fault: raw_trips stopped receiving data 2 days ago.
#
#   "schema_change" — an upstream column rename silently breaks a transform:
#       raw_orders -> orders_enriched -> weekly_sales -> sales_dashboard
#       Fault: raw_orders renamed `amount` -> `order_amount`; the downstream
#       transform still selects `amount`, so weekly_sales revenue goes NULL/0.
# --------------------------------------------------------------------------- #

_SCENARIO_FRESHNESS = {
    "urn:li:dataset:(urn:li:dataPlatform:s3,nyc.raw_trips,PROD)": {
        "name": "raw_trips",
        "upstreams": [],
        "freshness_hours": 51,  # <-- planted fault: expected < 24h
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": -100.0,  # no new rows landed
        "queries": [
            {"query": "COPY INTO raw_trips FROM @nyc_stage/trips/", "last_run": "2 days ago"}
        ],
    },
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.trips_cleaned,PROD)": {
        "name": "trips_cleaned",
        "upstreams": ["urn:li:dataset:(urn:li:dataPlatform:s3,nyc.raw_trips,PROD)"],
        "freshness_hours": 50,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": -3.0,
        "queries": [
            {
                "query": "CREATE OR REPLACE TABLE trips_cleaned AS "
                "SELECT * FROM raw_trips WHERE fare_amount > 0",
                "last_run": "1 day ago",
            }
        ],
    },
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)": {
        "name": "daily_revenue",
        "upstreams": ["urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.trips_cleaned,PROD)"],
        "freshness_hours": 49,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": -40.0,  # the visible symptom
        "queries": [
            {
                "query": "CREATE OR REPLACE TABLE daily_revenue AS "
                "SELECT trip_date, SUM(fare_amount) AS revenue "
                "FROM trips_cleaned GROUP BY trip_date",
                "last_run": "12 hours ago",
            }
        ],
    },
    "urn:li:dataset:(urn:li:dataPlatform:looker,nyc.revenue_dashboard,PROD)": {
        "name": "revenue_dashboard",
        "upstreams": ["urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)"],
        "freshness_hours": 48,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": -40.0,
        "queries": [],
    },
}

_SCENARIO_SCHEMA_CHANGE = {
    "urn:li:dataset:(urn:li:dataPlatform:postgres,shop.raw_orders,PROD)": {
        "name": "raw_orders",
        "upstreams": [],
        "freshness_hours": 2,  # fresh — this is NOT a freshness problem
        "expected_freshness_hours": 24,
        "schema_changed_recently": True,  # <-- planted fault: column renamed
        "schema_change_note": "Column `amount` renamed to `order_amount` 6 hours ago.",
        "schema_fields": [
            {"name": "order_id", "type": "STRING"},
            {"name": "customer_id", "type": "STRING"},
            {"name": "order_amount", "type": "DECIMAL"},  # was `amount`
            {"name": "created_at", "type": "TIMESTAMP"},
        ],
        "row_count_delta_pct": 1.0,
        "queries": [
            {"query": "-- ingested from application DB (Debezium CDC)", "last_run": "5 min ago"}
        ],
    },
    "urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders_enriched,PROD)": {
        "name": "orders_enriched",
        "upstreams": ["urn:li:dataset:(urn:li:dataPlatform:postgres,shop.raw_orders,PROD)"],
        "freshness_hours": 3,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": 0.0,
        # The transform still references the OLD column name `amount`.
        "queries": [
            {
                "query": "SELECT order_id, customer_id, amount AS revenue, "
                "created_at FROM raw_orders",
                "last_run": "3 hours ago",
            }
        ],
    },
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop.weekly_sales,PROD)": {
        "name": "weekly_sales",
        "upstreams": ["urn:li:dataset:(urn:li:dataPlatform:dbt,shop.orders_enriched,PROD)"],
        "freshness_hours": 4,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": 0.0,  # rows fine — but revenue column is all zero
        "queries": [
            {
                "query": "CREATE OR REPLACE TABLE weekly_sales AS "
                "SELECT date_trunc('week', created_at) AS wk, SUM(revenue) AS revenue "
                "FROM orders_enriched GROUP BY 1",
                "last_run": "2 hours ago",
            }
        ],
    },
    "urn:li:dataset:(urn:li:dataPlatform:looker,shop.sales_dashboard,PROD)": {
        "name": "sales_dashboard",
        "upstreams": ["urn:li:dataset:(urn:li:dataPlatform:snowflake,shop.weekly_sales,PROD)"],
        "freshness_hours": 5,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": 0.0,
        "queries": [],
    },
}

_SCENARIOS: dict[str, tuple[dict, str, dict]] = {
    # name -> (graph, symptom_urn, incident_dict)
    "freshness": (
        _SCENARIO_FRESHNESS,
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)",
        {
            "title": "daily_revenue is 40% below expected volume",
            "description": (
                "The Looker revenue dashboard shows a sharp drop. A volume "
                "assertion on daily_revenue failed this morning."
            ),
            "failed_assertion": "row_count within 10% of 7-day average",
            "detected_at": "today 08:04",
        },
    ),
    "schema_change": (
        _SCENARIO_SCHEMA_CHANGE,
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop.weekly_sales,PROD)",
        {
            "title": "weekly_sales revenue is reporting $0 for all weeks",
            "description": (
                "The sales dashboard shows zero revenue everywhere, though order "
                "volume looks normal. A SQL assertion (revenue > 0) on weekly_sales "
                "is failing."
            ),
            "failed_assertion": "weekly_sales.revenue must be > 0",
            "detected_at": "today 09:12",
        },
    ),
}

# Backwards-compatible aliases (freshness scenario is the default).
_MOCK_GRAPH = _SCENARIO_FRESHNESS
_SYMPTOM_URN = _SCENARIOS["freshness"][1]


class MockDataHubClient:
    """Zero-infra backend with a planted, discoverable fault.

    Select a scenario with the CAUZON_MOCK_SCENARIO env var
    ("freshness" [default] or "schema_change"), or pass `scenario=` directly.
    """

    def __init__(self, scenario: Optional[str] = None) -> None:
        scenario = (scenario or os.getenv("CAUZON_MOCK_SCENARIO", "freshness")).lower()
        if scenario not in _SCENARIOS:
            scenario = "freshness"
        graph, symptom_urn, incident = _SCENARIOS[scenario]
        self.scenario = scenario
        self._symptom_urn = symptom_urn
        self._incident = incident
        self._graph = {k: dict(v) for k, v in graph.items()}
        self._writes: list[dict[str, Any]] = []  # captured write-backs for the UI

    # ---- reads ----------------------------------------------------------- #
    def list_open_incidents(self) -> list[dict[str, Any]]:
        return [
            {
                "urn": self._symptom_urn,
                "title": self._incident["title"],
                "description": self._incident["description"],
                "failed_assertion": self._incident.get("failed_assertion"),
                "detected_at": self._incident.get("detected_at"),
            }
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        return [
            {"urn": urn, "name": node["name"]}
            for urn, node in self._graph.items()
            if q in node["name"].lower() or q in urn.lower()
        ]

    def get_entity(self, urn: str) -> dict[str, Any]:
        node = self._graph.get(urn, {})
        return {"urn": urn, **node}

    def get_lineage(self, urn: str, direction: str = "upstream", hops: int = 3) -> list[dict[str, Any]]:
        """BFS upstream up to `hops`, returning each node with its distance."""
        results: list[dict[str, Any]] = []
        frontier = [(urn, 0)]
        seen = {urn}
        while frontier:
            cur, dist = frontier.pop(0)
            if dist >= hops:
                continue
            for up in self._graph.get(cur, {}).get("upstreams", []):
                if up in seen:
                    continue
                seen.add(up)
                results.append({"urn": up, "hops": dist + 1, "name": self._graph[up]["name"]})
                frontier.append((up, dist + 1))
        return results

    def get_lineage_paths_between(self, source_urn: str, target_urn: str) -> list[dict[str, Any]]:
        """Return the ordered node/edge path from target (upstream) to source (symptom)."""
        # DFS upstream from source looking for target.
        path: list[str] = []

        def dfs(node: str) -> bool:
            path.append(node)
            if node == target_urn:
                return True
            for up in self._graph.get(node, {}).get("upstreams", []):
                if dfs(up):
                    return True
            path.pop()
            return False

        if not dfs(source_urn):
            return []
        ordered = list(reversed(path))  # target ... symptom
        edges = []
        for a, b in zip(ordered, ordered[1:]):
            # the "via" query is the transform on the downstream node (b) reading a
            via = None
            for qi in self._graph.get(b, {}).get("queries", []):
                via = qi["query"]
                break
            edges.append({"from": a, "to": b, "via_query": via})
        return [{"nodes": ordered, "edges": edges}]

    def list_schema_fields(self, urn: str) -> list[dict[str, Any]]:
        # Per-node fixtures. For the schema_change scenario the renamed column is
        # reflected here so an agent inspecting the schema can spot the mismatch.
        node = self._graph.get(urn, {})
        fields = node.get("schema_fields")
        if fields is not None:
            return fields
        return [{"name": "trip_date", "type": "DATE"}, {"name": "fare_amount", "type": "DECIMAL"}]

    def get_dataset_queries(self, urn: str) -> list[dict[str, Any]]:
        return self._graph.get(urn, {}).get("queries", [])

    # ---- write-backs ----------------------------------------------------- #
    def add_tags(self, urn: str, tags: list[str]) -> None:
        self._writes.append({"op": "add_tags", "urn": urn, "tags": tags})

    def update_description(self, urn: str, description: str) -> None:
        self._writes.append({"op": "update_description", "urn": urn, "description": description})

    def save_document(self, title: str, content: str, related_urns: list[str]) -> str:
        doc_urn = f"urn:li:document:(cauzon,{title.replace(' ', '-').lower()})"
        self._writes.append(
            {"op": "save_document", "urn": doc_urn, "title": title, "related": related_urns}
        )
        return doc_urn

    @property
    def writes(self) -> list[dict[str, Any]]:
        return self._writes


# --------------------------------------------------------------------------- #
# Real MCP backend — wraps datahub-agent-context (the Agent Context Kit).
#
# Verified against datahub-agent-context 1.6.0.x. The kit exposes the MCP tools
# as plain Python callables in `datahub_agent_context.mcp_tools`, which read the
# active DataHubClient from a contextvar set by `set_client(...)`. We therefore:
#   1. build a DataHubClient(server=..., token=...),
#   2. register it once with set_client(),
#   3. call the mcp_tools.* functions and normalise their (GraphQL-derived)
#      responses into the SAME shape MockDataHubClient returns, so the agent is
#      completely backend-agnostic.
#
# Kept import-lazy so the mock path never needs the SDK installed.
# --------------------------------------------------------------------------- #

def _first(d: Any, *keys: str, default: Any = None) -> Any:
    """Return the first present key from a dict, tolerating missing keys."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _short_name(urn: str) -> str:
    """Best-effort human name from a dataset URN."""
    import re

    m = re.search(r",([^,]+),[A-Z]+\)$", urn)
    if m:
        return m.group(1).split(".")[-1]
    return urn


class MCPDataHubClient:
    """Talks to a real DataHub instance through the Agent Context Kit / MCP."""

    def __init__(self, gms_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
        self.token = token or os.getenv("DATAHUB_TOKEN", "")
        try:
            from datahub.sdk import DataHubClient  # type: ignore
            from datahub_agent_context import set_client  # type: ignore
            from datahub_agent_context import mcp_tools as mt  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "datahub-agent-context not installed. Run "
                "`pip install datahub-agent-context` or set CAUZON_DATAHUB_BACKEND=mock."
            ) from exc

        self._mt = mt
        # Build + register the client in the current context.
        client = DataHubClient(server=self.gms_url, token=self.token or None)
        set_client(client)
        self._client = client
        self._writes: list[dict[str, Any]] = []

    # ---- reads ----------------------------------------------------------- #
    def list_open_incidents(self) -> list[dict[str, Any]]:
        """Find datasets with FAILING assertions and turn them into incidents.

        Strategy: search for datasets, check their assertions, surface any that
        are currently failing. In a real deployment you would subscribe to the
        DataHub incidents/assertion-run events; for an on-demand agent we poll.
        """
        incidents: list[dict[str, Any]] = []
        res = self._mt.search(query="*", num_results=25)
        entities = _first(res, "searchResults", "entities", "results", default=[]) or []
        for ent in entities:
            urn = _first(ent, "urn") or _first(_first(ent, "entity", default={}), "urn")
            if not urn or "dataset" not in urn:
                continue
            try:
                assertions = self._mt.get_dataset_assertions(urn=urn, status="FAILING")
            except Exception:
                continue
            items = _first(assertions, "assertions", "results", default=[]) or []
            for a in items:
                incidents.append(
                    {
                        "urn": urn,
                        "title": f"{_short_name(urn)}: failing {_first(a, 'type', default='assertion')}",
                        "description": _first(a, "description", default="A data-quality assertion is failing."),
                        "failed_assertion": _first(a, "type", "description"),
                        "detected_at": _first(a, "lastEvaluatedAt", "latestResultTime"),
                    }
                )
        return incidents

    def search(self, query: str) -> list[dict[str, Any]]:
        res = self._mt.search(query=query, num_results=10)
        entities = _first(res, "searchResults", "entities", "results", default=[]) or []
        out = []
        for ent in entities:
            e = ent.get("entity", ent) if isinstance(ent, dict) else {}
            urn = _first(e, "urn")
            if urn:
                out.append({"urn": urn, "name": _short_name(urn)})
        return out

    def get_entity(self, urn: str) -> dict[str, Any]:
        results = self._mt.get_entities(urns=[urn])
        raw = results[0] if results else {}

        # DataHub returns customProperties as a list of {key,value} pairs, either
        # at the top level or under a properties/datasetProperties object.
        cprops: dict[str, str] = {}
        candidates = [
            raw.get("customProperties"),
            (_first(raw, "properties", "datasetProperties", default={}) or {}).get("customProperties"),
        ]
        for c in candidates:
            if isinstance(c, list):
                for item in c:
                    if isinstance(item, dict) and "key" in item:
                        cprops[item["key"]] = item.get("value")
            elif isinstance(c, dict):
                cprops.update(c)

        def _num(key: str):
            v = cprops.get(key)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        schema_changed = str(cprops.get("schema_changed_recently", "")).lower() == "true"

        return {
            "urn": urn,
            "name": _first(raw, "name") or _short_name(urn),
            "upstreams": [],  # lineage is fetched separately via get_lineage
            "freshness_hours": _num("freshness_hours"),
            "expected_freshness_hours": _num("expected_freshness_hours"),
            "schema_changed_recently": schema_changed,
            "schema_change_note": cprops.get("schema_change_note"),
            "row_count_delta_pct": _num("row_count_delta_pct"),
            "queries": [],
            "_raw": raw,  # kept for debugging / richer heuristics
        }

    def get_lineage(self, urn: str, direction: str = "upstream", hops: int = 3) -> list[dict[str, Any]]:
        res = self._mt.get_lineage(urn=urn, upstream=(direction == "upstream"), max_hops=hops)
        # DataHub nests results under "upstreams"/"downstreams" -> may contain
        # a "relationships"/"entities" list, or be a search-style facet block.
        block = _first(res, "upstreams", "downstreams", default=res) or {}
        entities = _first(block, "relationships", "entities", "results", default=[])
        if not entities and isinstance(res, dict):
            entities = _first(res, "entities", "results", "lineage", default=[])
        entities = entities or []
        out = []
        for ent in entities:
            e = ent.get("entity", ent) if isinstance(ent, dict) else {}
            u = _first(e, "urn")
            if not u or u == urn:
                continue
            out.append(
                {
                    "urn": u,
                    "hops": _first(ent, "hops", "degree", "distance", default=1),
                    "name": _short_name(u),
                }
            )
        # Fallback: the lineage *search* API relies on the graph index, which can
        # lag behind (or, in a constrained quickstart, stall) even though the
        # upstreamLineage ASPECT is durably stored. If the indexed query returns
        # nothing, walk the raw aspects directly so RCA still works.
        if not out and direction == "upstream":
            out = self._walk_upstream_aspects(urn, hops)
        return out

    def _walk_upstream_aspects(self, urn: str, hops: int) -> list[dict[str, Any]]:
        """Graph-index-independent BFS over the raw upstreamLineage aspect."""
        try:
            graph = self._client._graph
        except Exception:
            return []
        import datahub.metadata.schema_classes as models

        results: list[dict[str, Any]] = []
        frontier = [(urn, 0)]
        seen = {urn}
        while frontier:
            cur, dist = frontier.pop(0)
            if dist >= hops:
                continue
            try:
                aspect = graph.get_aspect(cur, models.UpstreamLineageClass)
            except Exception:
                aspect = None
            if not aspect:
                continue
            for up in aspect.upstreams:
                u = up.dataset
                if u in seen:
                    continue
                seen.add(u)
                results.append({"urn": u, "hops": dist + 1, "name": _short_name(u)})
                frontier.append((u, dist + 1))
        return results

    def get_lineage_paths_between(self, source_urn: str, target_urn: str) -> list[dict[str, Any]]:
        try:
            res = self._mt.get_lineage_paths_between(
                source_urn=source_urn, target_urn=target_urn, direction="upstream"
            )
        except Exception:
            # The MCP tool raises when the graph index has no path; fall back to
            # reconstructing from raw aspects.
            res = {}
        raw_paths = _first(res, "paths", "lineagePaths", default=[]) or []
        norm = []
        for p in raw_paths:
            nodes = _first(p, "nodes", "path", default=[]) or []
            node_urns = [
                _first(n, "urn") if isinstance(n, dict) else n for n in nodes
            ]
            node_urns = [n for n in node_urns if n]
            edges = []
            for a, b in zip(node_urns, node_urns[1:]):
                via = None
                # Try to attach the transform query joining a -> b.
                try:
                    q = self.get_dataset_queries(b)
                    via = q[0]["query"] if q else None
                except Exception:
                    via = None
                edges.append({"from": a, "to": b, "via_query": via})
            norm.append({"nodes": node_urns, "edges": edges})
        # Fallback when the indexed path API returns nothing (graph-index lag):
        # reconstruct the path from raw upstreamLineage aspects.
        if not norm:
            norm = self._path_from_aspects(source_urn, target_urn)
        return norm

    def _path_from_aspects(self, source_urn: str, target_urn: str) -> list[dict[str, Any]]:
        """Reconstruct symptom->cause path via raw aspects (index-independent)."""
        try:
            graph = self._client._graph
        except Exception:
            return []
        import datahub.metadata.schema_classes as models

        # DFS upstream from source toward target.
        path: list[str] = []

        def dfs(node: str, depth: int = 0) -> bool:
            if depth > 10:
                return False
            path.append(node)
            if node == target_urn:
                return True
            try:
                aspect = graph.get_aspect(node, models.UpstreamLineageClass)
            except Exception:
                aspect = None
            for up in (aspect.upstreams if aspect else []):
                if dfs(up.dataset, depth + 1):
                    return True
            path.pop()
            return False

        if not dfs(source_urn):
            return []
        ordered = list(reversed(path))  # target ... source(symptom)
        edges = []
        for a, b in zip(ordered, ordered[1:]):
            via = None
            try:
                q = self.get_dataset_queries(b)
                via = q[0]["query"] if q else None
            except Exception:
                via = None
            edges.append({"from": a, "to": b, "via_query": via})
        return [{"nodes": ordered, "edges": edges}]

    def list_schema_fields(self, urn: str) -> list[dict[str, Any]]:
        res = self._mt.list_schema_fields(urn=urn)
        fields = _first(res, "fields", "schemaFields", default=[]) or []
        return [
            {"name": _first(f, "fieldPath", "name", default=""), "type": _first(f, "type", default="")}
            for f in fields
        ]

    def get_dataset_queries(self, urn: str) -> list[dict[str, Any]]:
        res = self._mt.get_dataset_queries(urn=urn, count=5)
        queries = _first(res, "queries", default=[]) or []
        out = []
        for q in queries:
            props = _first(q, "queryProperties", "properties", default={}) or {}
            stmt = _first(props, "statement", default={})
            text = _first(stmt, "value") if isinstance(stmt, dict) else stmt
            out.append({"query": text or "", "last_run": _first(props, "lastModified", "created")})
        return out

    # ---- write-backs ----------------------------------------------------- #
    def _ensure_tag_exists(self, tag_urn: str) -> None:
        """Create the tag entity if it doesn't exist yet.

        DataHub rejects applying a tag whose entity hasn't been created, so we
        emit a minimal tagProperties aspect first (idempotent).
        """
        try:
            import datahub.metadata.schema_classes as models
            from datahub.emitter.mcp import MetadataChangeProposalWrapper
            from datahub.metadata.urns import TagUrn

            name = tag_urn.split(":")[-1]
            graph = self._client._graph  # DataHubGraph under the SDK client
            mcp = MetadataChangeProposalWrapper(
                entityUrn=str(TagUrn(name)),
                aspect=models.TagPropertiesClass(name=name),
            )
            graph.emit(mcp)
        except Exception:
            # Best-effort: if creation fails we still attempt to apply the tag,
            # which will surface a clear error to the caller.
            pass

    def add_tags(self, urn: str, tags: list[str]) -> None:
        # DataHub tags are URNs; coerce bare names into tag URNs.
        tag_urns = [t if t.startswith("urn:li:tag:") else f"urn:li:tag:{t}" for t in tags]
        for t in tag_urns:
            self._ensure_tag_exists(t)
        self._mt.add_tags(tag_urns=tag_urns, entity_urns=[urn])
        self._writes.append({"op": "add_tags", "urn": urn, "tags": tags})

    def update_description(self, urn: str, description: str) -> None:
        self._mt.update_description(entity_urn=urn, operation="append", description=description)
        self._writes.append({"op": "update_description", "urn": urn, "description": description})

    def save_document(self, title: str, content: str, related_urns: list[str]) -> str:
        res = self._mt.save_document(
            document_type="Analysis",
            title=title,
            content=content,
            related_assets=related_urns,
        )
        doc_urn = _first(res, "urn", "documentUrn", default=f"urn:li:document:(cauzon,{title})")
        self._writes.append(
            {"op": "save_document", "urn": doc_urn, "title": title, "related": related_urns}
        )
        return doc_urn

    @property
    def writes(self) -> list[dict[str, Any]]:
        return self._writes


def get_client() -> DataHubClient:
    """Factory honouring CAUZON_DATAHUB_BACKEND (default: mock)."""
    backend = os.getenv("CAUZON_DATAHUB_BACKEND", "mock").lower()
    if backend == "mcp":
        return MCPDataHubClient()
    return MockDataHubClient()
