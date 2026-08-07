"""Catalog-wide views: the triage inbox and the map.

Everything else in Cauzon answers "why did *this* break". These answer "what is
the state of the whole catalog" — the question you actually start from, before
you have picked an incident to investigate.

Both are built from the same `DataHubClient` protocol as the investigation, so
they work identically over the planted graph, a live public catalog, and a real
DataHub. Neither runs an investigation: enriching a queue must stay cheap enough
to load on every page view, so these use only metadata reads and one-hop lineage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Freshness ratio above which an overdue asset counts as critical rather than
# merely late. Twice its own SLA is a blunt line, stated rather than tuned so the
# severity badge in the UI traces back to something a reader can check.
_CRITICAL_RATIO = 2.0


@dataclass
class InboxEntry:
    """One row of the triage queue, enriched enough to sort without investigating."""

    urn: str
    name: str
    title: str
    # critical — at least twice its own freshness SLA
    # overdue  — past its SLA but not yet double
    # failing  — an assertion is failing while freshness is fine, so this is not
    #            a staleness problem at all and must not be labelled as one
    severity: str
    platform: Optional[str] = None
    owner: Optional[str] = None
    failed_assertion: Optional[str] = None
    detected_at: Optional[str] = None
    freshness_hours: Optional[float] = None
    expected_freshness_hours: Optional[float] = None
    overdue_ratio: Optional[float] = None
    signals: list[str] = field(default_factory=list)
    # How many assets sit downstream — a proxy for how much is at stake, without
    # paying for a full blast-radius walk per row.
    downstream_count: int = 0
    upstream_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CatalogNode:
    urn: str
    name: str
    depth: int
    health: str  # incident | overdue | healthy | unknown
    platform: Optional[str] = None
    owner: Optional[str] = None
    signals: list[str] = field(default_factory=list)
    freshness_hours: Optional[float] = None
    expected_freshness_hours: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CatalogMap:
    """Every asset and edge the catalog exposes, with health marked on each node."""

    nodes: list[CatalogNode] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": self.edges,
            "counts": {
                "total": len(self.nodes),
                "incident": sum(1 for n in self.nodes if n.health == "incident"),
                "overdue": sum(1 for n in self.nodes if n.health == "overdue"),
                "healthy": sum(1 for n in self.nodes if n.health == "healthy"),
            },
        }


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _platform_of(urn: str) -> Optional[str]:
    if "dataPlatform:" not in urn:
        return None
    return urn.split("dataPlatform:")[-1].split(",")[0] or None


def _signal_names(entity: dict[str, Any]) -> list[str]:
    """Cheap signal read for a queue row.

    Deliberately a subset of what the agent computes: this is a triage hint, not
    a diagnosis, and it must not cost a lineage walk per row.
    """
    names: list[str] = []
    lag, sla = entity.get("freshness_hours"), entity.get("expected_freshness_hours")
    if lag is not None and sla is not None and lag > sla:
        names.append("freshness_lag")
    delta = entity.get("row_count_delta_pct")
    if delta is not None and abs(delta) >= 20:
        names.append("volume_anomaly")
    if entity.get("schema_changed_recently"):
        names.append("schema_change")
    if entity.get("duplicate_key_pct"):
        names.append("row_fanout")
    return names


def _overdue_ratio(entity: dict[str, Any]) -> Optional[float]:
    lag, sla = entity.get("freshness_hours"), entity.get("expected_freshness_hours")
    if lag is None or not sla:
        return None
    return round(lag / sla, 2)


def _severity(ratio: Optional[float]) -> str:
    """Name the problem the asset actually has.

    A ratio at or below 1.0 means freshness is fine, so whatever opened the
    incident was not staleness — calling that "overdue" would contradict the
    number shown beside it.
    """
    if ratio is None or ratio <= 1.0:
        return "failing"
    return "critical" if ratio >= _CRITICAL_RATIO else "overdue"


def build_inbox(client: Any) -> list[InboxEntry]:
    """The open-incident queue, enriched and ordered for triage.

    Sorted by how far past its own SLA each asset is, not by absolute staleness —
    a daily feed two days late is a live problem, while an annual archive two
    months late is not.
    """
    entries: list[InboxEntry] = []
    for incident in client.list_open_incidents():
        urn = incident.get("urn")
        if not urn:
            continue
        try:
            entity = client.get_entity(urn)
        except Exception:
            entity = {}

        # One hop each way: enough to show what is at stake without investigating.
        def _count(direction: str) -> int:
            try:
                return len(client.get_lineage(urn, direction=direction, hops=3))
            except Exception:
                return 0

        ratio = _overdue_ratio(entity)
        entries.append(
            InboxEntry(
                urn=urn,
                name=entity.get("name") or incident.get("title") or urn,
                title=incident.get("title") or "",
                severity=_severity(ratio),
                platform=_platform_of(urn),
                owner=entity.get("owner"),
                failed_assertion=incident.get("failed_assertion"),
                detected_at=incident.get("detected_at"),
                freshness_hours=entity.get("freshness_hours"),
                expected_freshness_hours=entity.get("expected_freshness_hours"),
                overdue_ratio=ratio,
                signals=_signal_names(entity),
                downstream_count=_count("downstream"),
                upstream_count=_count("upstream"),
            )
        )

    # Critical first, then by how much is downstream, then by staleness. Ordering
    # on the ratio alone would bury a failing assertion on a fresh asset, which is
    # a live problem even though nothing is late.
    entries.sort(
        key=lambda e: (
            2 if e.severity == "critical" else 1,
            e.downstream_count,
            e.overdue_ratio or 0.0,
        ),
        reverse=True,
    )
    return entries


def build_catalog_map(client: Any) -> CatalogMap:
    """Every asset and edge, with health marked and depth assigned for layout.

    Depth is the longest path from a root, so a node always renders to the right
    of everything it depends on. Cycles cannot happen in declared lineage, but the
    walk is bounded anyway rather than trusting that.
    """
    assets = client.list_assets() if hasattr(client, "list_assets") else []
    by_urn: dict[str, dict[str, Any]] = {}
    for asset in assets:
        urn = asset.get("urn")
        if urn:
            by_urn[urn] = asset

    incident_urns = set()
    try:
        incident_urns = {i["urn"] for i in client.list_open_incidents() if i.get("urn")}
    except Exception:
        pass

    # Edges from declared upstreams, restricted to assets we actually know about.
    edges: list[dict[str, str]] = []
    parents: dict[str, list[str]] = {urn: [] for urn in by_urn}
    for urn, asset in by_urn.items():
        for parent in asset.get("upstreams") or []:
            if parent in by_urn:
                edges.append({"from": parent, "to": urn})
                parents[urn].append(parent)

    def depth_of(urn: str, seen: frozenset[str] = frozenset()) -> int:
        if urn in seen:  # defensive: a cycle would otherwise recurse forever
            return 0
        ancestors = parents.get(urn) or []
        if not ancestors:
            return 0
        return 1 + max(depth_of(p, seen | {urn}) for p in ancestors)

    nodes: list[CatalogNode] = []
    for urn, asset in by_urn.items():
        try:
            entity = client.get_entity(urn)
        except Exception:
            entity = {}
        signals = _signal_names(entity)
        if urn in incident_urns:
            health = "incident"
        elif signals:
            health = "overdue"
        elif entity.get("freshness_hours") is None:
            health = "unknown"
        else:
            health = "healthy"

        nodes.append(
            CatalogNode(
                urn=urn,
                name=entity.get("name") or asset.get("name") or urn,
                depth=depth_of(urn),
                health=health,
                platform=_platform_of(urn),
                owner=entity.get("owner"),
                signals=signals,
                freshness_hours=entity.get("freshness_hours"),
                expected_freshness_hours=entity.get("expected_freshness_hours"),
            )
        )

    nodes.sort(key=lambda n: (n.depth, n.name))
    return CatalogMap(nodes=nodes, edges=edges)
