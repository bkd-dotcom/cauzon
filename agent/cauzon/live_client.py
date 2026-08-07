"""A DataHubClient over a live public catalog (NYC Open Data).

Same interface as the mock and MCP backends, so the agent is unchanged: the
ranking, the origin rule, the proof gate, the blast radius and the guardrail
proposal all run exactly as they do everywhere else.

Two properties of this backend are worth understanding, because they are honest
consequences of the data rather than limitations to hide:

  * **Socrata retains no query history**, so no transform SQL can be captured.
    Findings here land on `PATH_ONLY` — the path is proven, the transform is not,
    and the artifact says so. This is the grounding ladder earning its keep on a
    real catalog rather than on a planted one.
  * **Socrata is read-only.** There is no write-back, so this backend declines it
    instead of pretending. `supports_writeback` is False and the API reports it.

See `live_source.py` for exactly which fields are real and which are declared.
"""

from __future__ import annotations

from typing import Any, Optional

from .live_source import (
    DECLARED_GRAPH,
    SocrataCatalog,
    humanise_age,
    id_from_urn,
    urn_for,
)


class LiveDataHubClient:
    """Real assets, real freshness, declared lineage."""

    # The agent never consults this; the API layer does, to avoid offering a
    # write-back button against a catalog nobody can write to.
    supports_writeback = False

    def __init__(self, catalog: Optional[SocrataCatalog] = None) -> None:
        self._catalog = catalog or SocrataCatalog()
        self._writes: list[dict[str, Any]] = []

    # ---- reads ----------------------------------------------------------- #
    def _assets(self) -> dict[str, dict[str, Any]]:
        return self._catalog.assets()

    @property
    def source_error(self) -> Optional[str]:
        """Set when the last refresh failed, so callers can flag possible staleness."""
        return self._catalog.last_error

    def list_open_incidents(self) -> list[dict[str, Any]]:
        """Whatever is genuinely past its freshness SLA right now.

        Not a fixed list. The count and the membership change as the city
        publishes — an asset updated this morning drops out on the next refresh.
        """
        # One snapshot for the whole call, so a refresh cannot happen partway
        # through and the fetch count stays obvious.
        assets = self._assets()
        overdue: list[tuple[float, dict[str, Any]]] = []
        for asset in assets.values():
            lag = asset["freshness_hours"]
            sla = asset["expected_freshness_hours"]
            if lag is None or lag <= sla:
                continue
            overdue.append(
                (
                    lag,
                    {
                        "urn": asset["urn"],
                        "title": (
                            f"{asset['name']} has not been updated in "
                            f"{humanise_age(lag)}"
                        ),
                        "description": (
                            f"Expected an update at least every {sla // 24} days; "
                            f"the catalog reports the last one {humanise_age(lag)} "
                            f"ago. Read live from NYC Open Data."
                        ),
                        "failed_assertion": f"freshness within {sla // 24} days",
                        "detected_at": "now (live check)",
                    },
                )
            )
        # Worst offenders first — the order an on-call would triage in.
        overdue.sort(key=lambda pair: pair[0], reverse=True)
        return [incident for _lag, incident in overdue]

    def search(self, query: str) -> list[dict[str, Any]]:
        needle = query.lower()
        return [
            {"urn": a["urn"], "name": a["name"]}
            for a in self._assets().values()
            if needle in a["name"].lower() or needle in a["socrata_id"]
        ]

    def get_entity(self, urn: str) -> dict[str, Any]:
        dataset_id = id_from_urn(urn)
        asset = self._assets().get(dataset_id or "")
        if not asset:
            return {"urn": urn}
        return {
            "urn": urn,
            "name": asset["name"],
            "upstreams": asset["upstreams"],
            "owner": asset["owner"],
            "freshness_hours": asset["freshness_hours"],
            "expected_freshness_hours": asset["expected_freshness_hours"],
            # Socrata publishes no row-count baseline and no schema history, so
            # these signals are genuinely unavailable rather than negative.
            "row_count_delta_pct": None,
            "schema_changed_recently": False,
            "duplicate_key_pct": None,
            "source_url": asset["source_url"],
            "declared_note": asset["declared_note"],
            "queries": [],
        }

    def _downstreams_of(self, urn: str) -> list[str]:
        return [
            a["urn"] for a in self._assets().values() if urn in a["upstreams"]
        ]

    def get_lineage(
        self, urn: str, direction: str = "upstream", hops: int = 3
    ) -> list[dict[str, Any]]:
        assets = self._assets()
        by_urn = {a["urn"]: a for a in assets.values()}
        results: list[dict[str, Any]] = []
        frontier = [(urn, 0)]
        seen = {urn}
        while frontier:
            current, distance = frontier.pop(0)
            if distance >= hops:
                continue
            node = by_urn.get(current)
            neighbours = (
                (node or {}).get("upstreams", [])
                if direction == "upstream"
                else self._downstreams_of(current)
            )
            for nxt in neighbours:
                if nxt in seen or nxt not in by_urn:
                    continue
                seen.add(nxt)
                results.append(
                    {"urn": nxt, "hops": distance + 1, "name": by_urn[nxt]["name"]}
                )
                frontier.append((nxt, distance + 1))
        return results

    def get_lineage_paths_between(
        self, source_urn: str, target_urn: str
    ) -> list[dict[str, Any]]:
        """Walk the declared edges from the symptom up to the candidate."""
        by_urn = {a["urn"]: a for a in self._assets().values()}
        path: list[str] = []

        def walk(node: str) -> bool:
            path.append(node)
            if node == target_urn:
                return True
            for parent in (by_urn.get(node) or {}).get("upstreams", []):
                if walk(parent):
                    return True
            path.pop()
            return False

        if not walk(source_urn):
            return []
        ordered = list(reversed(path))  # cause -> symptom
        # No via_query: Socrata retains no query history, so the transform cannot
        # be evidenced. The agent downgrades to PATH_ONLY on its own.
        edges = [
            {"from": a, "to": b, "via_query": None}
            for a, b in zip(ordered, ordered[1:])
        ]
        return [{"nodes": ordered, "edges": edges}]

    def list_schema_fields(self, urn: str) -> list[dict[str, Any]]:
        dataset_id = id_from_urn(urn)
        asset = self._assets().get(dataset_id or "")
        return list(asset["columns"]) if asset else []

    def get_dataset_queries(self, urn: str) -> list[dict[str, Any]]:
        return []  # Socrata exposes none.

    def list_assets(self) -> list[dict[str, Any]]:
        return [
            {"urn": a["urn"], "name": a["name"], "upstreams": list(a["upstreams"])}
            for a in self._assets().values()
        ]

    def search_documents(self, query: str) -> list[dict[str, Any]]:
        return []  # No document store to read prior dossiers from.

    # ---- write-backs ----------------------------------------------------- #
    # Captured so the UI can show what *would* be written, never sent anywhere.
    # NYC Open Data is read-only and this backend does not pretend otherwise.
    def add_tags(self, urn: str, tags: list[str]) -> None:
        self._writes.append({"op": "add_tags", "urn": urn, "tags": tags})

    def update_description(self, urn: str, description: str) -> None:
        self._writes.append(
            {"op": "update_description", "urn": urn, "description": description}
        )

    def save_document(self, title: str, content: str, related_urns: list[str]) -> str:
        doc_urn = f"urn:li:document:(cauzon-local,{title.replace(' ', '-').lower()})"
        self._writes.append(
            {"op": "save_document", "urn": doc_urn, "title": title, "related": related_urns}
        )
        return doc_urn

    @property
    def writes(self) -> list[dict[str, Any]]:
        return self._writes


def declared_edge_count() -> int:
    return sum(len(v["upstreams"]) for v in DECLARED_GRAPH.values())
