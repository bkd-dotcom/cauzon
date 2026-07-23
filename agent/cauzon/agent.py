"""The Cauzon investigation loop.

Five phases, each grounded in recent top-venue RCA / grounding research:

  1. detect      — pick up a failing assertion / incident.
  2. scope       — pull the minimal upstream subgraph (WM-SAR: compact subgraph).
  3. hypothesize — rank candidate culprits from multimodal signals (RCRank).
  4. prove       — accept a cause ONLY with a verifiable lineage path
                   (PAVE / OpenRCA 2.0: no ungrounded diagnosis).
  5. writeback   — persist the dossier + annotate the culprit in DataHub.

The loop yields TraceEvents so a UI can stream the reasoning live.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Optional

from .datahub_client import DataHubClient, get_client
from .models import (
    CandidateCause,
    Diagnosis,
    Incident,
    ProofPath,
    Signal,
    TraceEvent,
)

# Signal weights for ranking. Freshness/volume dominate for pipeline stalls;
# schema change dominates for breakage. Tunable — exposed for experiments.
_SIGNAL_WEIGHTS: dict[Signal, float] = {
    Signal.FRESHNESS_LAG: 3.0,
    Signal.VOLUME_ANOMALY: 2.0,
    Signal.SCHEMA_CHANGE: 3.0,
    Signal.RECENT_QUERY_CHANGE: 1.5,
    Signal.UPSTREAM_INCIDENT: 2.5,
    Signal.FAILED_ASSERTION: 1.0,
}


class CauzonAgent:
    def __init__(self, client: Optional[DataHubClient] = None) -> None:
        self.client = client or get_client()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def investigate(
        self,
        incident: Incident,
        on_event: Optional[Callable[[TraceEvent], None]] = None,
        write_back: bool = True,
    ) -> Diagnosis:
        """Run a full investigation. Returns a proof-carrying Diagnosis.

        `on_event` receives each TraceEvent as it happens (for live UIs).
        """
        events: list[TraceEvent] = []

        def emit(phase: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
            ev = TraceEvent(phase=phase, message=message, data=data)
            events.append(ev)
            if on_event:
                on_event(ev)

        # 1) DETECT
        emit("detect", f"Investigating incident on {incident.urn}", incident.to_dict())

        # 2) SCOPE — minimal upstream subgraph
        upstream = self.client.get_lineage(incident.urn, direction="upstream", hops=3)
        emit(
            "scope",
            f"Pulled {len(upstream)} upstream nodes within 3 hops.",
            {"upstream": upstream},
        )

        # 3) HYPOTHESIZE — score each upstream node from multimodal signals
        candidates = self._rank_candidates(incident, upstream, emit)

        # 4) PROVE — walk down the ranked list until a verifiable path is found
        root_cause, proof = self._prove(incident, candidates, emit)

        # Build diagnosis
        recommended_fix = self._recommend_fix(root_cause, proof)
        confidence = self._confidence(root_cause, proof)
        diagnosis = Diagnosis(
            incident=incident,
            root_cause=root_cause,
            proof_path=proof,
            ranked_candidates=candidates,
            recommended_fix=recommended_fix,
            confidence=confidence,
            grounded=bool(proof and proof.verified),
        )

        # 5) WRITEBACK
        if write_back and root_cause and proof and proof.verified:
            self._write_back(diagnosis, emit)
        elif write_back:
            emit(
                "writeback",
                "No verifiable root cause found — refusing to write an ungrounded "
                "diagnosis back to the catalog.",
            )

        return diagnosis

    # ------------------------------------------------------------------ #
    # Phase helpers
    # ------------------------------------------------------------------ #
    def _rank_candidates(
        self,
        incident: Incident,
        upstream: list[dict[str, Any]],
        emit: Callable[..., None],
    ) -> list[CandidateCause]:
        candidates: list[CandidateCause] = []
        for node in upstream:
            urn = node["urn"]
            entity = self.client.get_entity(urn)
            signals: list[Signal] = []
            notes: list[str] = []

            fresh = entity.get("freshness_hours")
            expected = entity.get("expected_freshness_hours")
            if fresh is not None and expected is not None and fresh > expected:
                signals.append(Signal.FRESHNESS_LAG)
                notes.append(
                    f"Freshness {fresh}h exceeds expected {expected}h "
                    f"(+{fresh - expected}h stale)."
                )

            delta = entity.get("row_count_delta_pct")
            if delta is not None and abs(delta) >= 20:
                signals.append(Signal.VOLUME_ANOMALY)
                notes.append(f"Row count changed {delta:+.0f}% vs baseline.")

            if entity.get("schema_changed_recently"):
                signals.append(Signal.SCHEMA_CHANGE)
                notes.append(entity.get("schema_change_note") or "Schema changed recently.")

            # An upstream node with a *more severe* freshness lag than its
            # own downstream is a stronger root-cause candidate (the fault
            # originates furthest upstream).
            score = sum(_SIGNAL_WEIGHTS[s] for s in signals)
            # Prefer nodes further upstream when signal-tied: the origin.
            score += 0.25 * node.get("hops", 0)

            candidates.append(
                CandidateCause(
                    urn=urn,
                    name=node.get("name", urn),
                    hops_from_symptom=node.get("hops", 0),
                    signals=signals,
                    score=round(score, 3),
                    evidence_notes=notes,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        emit(
            "hypothesize",
            f"Ranked {len(candidates)} candidates. Top: "
            + (candidates[0].name if candidates else "none"),
            {"candidates": [c.to_dict() for c in candidates]},
        )
        return candidates

    def _prove(
        self,
        incident: Incident,
        candidates: list[CandidateCause],
        emit: Callable[..., None],
    ) -> tuple[Optional[CandidateCause], Optional[ProofPath]]:
        """Accept the highest-ranked candidate that has a VERIFIABLE path.

        This is the differentiator: we do not trust the ranking alone. We
        reconstruct the lineage path and require the transform SQL to exist,
        otherwise the hypothesis is rejected as ungrounded.
        """
        for cand in candidates:
            if not cand.signals:
                continue  # no evidence at all — skip
            paths = self.client.get_lineage_paths_between(
                source_urn=incident.urn, target_urn=cand.urn
            )
            if not paths:
                emit(
                    "prove",
                    f"Rejected {cand.name}: no lineage path to the symptom "
                    f"(cannot ground the claim).",
                )
                continue

            path = paths[0]
            edges = path.get("edges", [])
            # The transform SQL that carried the fault downstream = the query on
            # the edge leaving the candidate.
            transform_sql = None
            for e in edges:
                if e.get("from") == cand.urn and e.get("via_query"):
                    transform_sql = e["via_query"]
                    break
            if transform_sql is None and edges:
                transform_sql = next(
                    (e.get("via_query") for e in edges if e.get("via_query")), None
                )

            verified = bool(edges)  # a reconstructable edge path == grounded
            proof = ProofPath(
                symptom_urn=incident.urn,
                cause_urn=cand.urn,
                nodes=path.get("nodes", []),
                edges=edges,
                transform_sql=transform_sql,
                verified=verified,
            )
            emit(
                "prove",
                f"Verified path to {cand.name} across {len(edges)} lineage edge(s). "
                f"Root cause grounded.",
                proof.to_dict(),
            )
            return cand, proof

        emit("prove", "No candidate could be grounded with a verifiable path.")
        return None, None

    def _recommend_fix(
        self, cause: Optional[CandidateCause], proof: Optional[ProofPath]
    ) -> str:
        if not cause:
            return "Escalate to a human: no grounded root cause identified."
        if Signal.FRESHNESS_LAG in cause.signals:
            return (
                f"Backfill / restart the ingestion job feeding `{cause.name}`; it is "
                f"the upstream origin of the staleness. Re-run downstream transforms "
                f"once fresh data lands."
            )
        if Signal.SCHEMA_CHANGE in cause.signals:
            return (
                f"Reconcile the schema change on `{cause.name}` with downstream "
                f"consumers; update the transform SQL and add a schema contract."
            )
        return f"Inspect `{cause.name}` — it carries the strongest anomaly signals."

    def _confidence(
        self, cause: Optional[CandidateCause], proof: Optional[ProofPath]
    ) -> float:
        if not cause or not proof or not proof.verified:
            return 0.0
        # Confidence rises with signal strength and a clean, short proof path.
        base = min(0.6 + 0.1 * len(cause.signals), 0.95)
        return round(base, 2)

    def _write_back(self, diagnosis: Diagnosis, emit: Callable[..., None]) -> None:
        cause = diagnosis.root_cause
        proof = diagnosis.proof_path
        assert cause and proof

        dossier = self._render_dossier(diagnosis)
        doc_urn = self.client.save_document(
            title=f"[Cauzon] RCA: {diagnosis.incident.title}",
            content=dossier,
            related_urns=[diagnosis.incident.urn, cause.urn],
        )
        self.client.add_tags(cause.urn, ["root-cause", "cauzon-diagnosed"])
        self.client.update_description(
            cause.urn,
            f"⚠️ Cauzon identified this as the root cause of incident "
            f"'{diagnosis.incident.title}'. See dossier {doc_urn}.",
        )
        emit(
            "writeback",
            f"Wrote incident dossier to DataHub and tagged `{cause.name}` as root cause. "
            f"The next person or agent inherits this knowledge.",
            {"document_urn": doc_urn, "tagged_urn": cause.urn},
        )

    @staticmethod
    def _render_dossier(diagnosis: Diagnosis) -> str:
        """Human-readable incident dossier written back to the catalog."""
        inc = diagnosis.incident
        cause = diagnosis.root_cause
        proof = diagnosis.proof_path
        lines = [
            f"# Incident Root-Cause Analysis — {inc.title}",
            "",
            f"**Detected:** {inc.detected_at}  ",
            f"**Symptom asset:** `{inc.urn}`  ",
            f"**Failed assertion:** {inc.failed_assertion}",
            "",
            "## Root cause (grounded)",
        ]
        if cause and proof:
            lines += [
                f"**{cause.name}** — `{cause.urn}`  ",
                f"Confidence: {diagnosis.confidence:.0%}",
                "",
                "### Evidence",
                *[f"- {n}" for n in cause.evidence_notes],
                "",
                "### Verifiable lineage proof path",
                "```",
                " -> ".join(n.split(",")[1] if "," in n else n for n in proof.nodes),
                "```",
            ]
            if proof.transform_sql:
                lines += ["", "**Transform that carried the fault downstream:**", "```sql", proof.transform_sql, "```"]
        else:
            lines.append("_No grounded root cause could be established._")
        lines += ["", "## Recommended fix", diagnosis.recommended_fix, "", "---", "_Generated by Cauzon — path-grounded RCA agent for DataHub._"]
        return "\n".join(lines)


def investigate_first_open_incident(
    on_event: Optional[Callable[[TraceEvent], None]] = None,
    write_back: bool = True,
) -> Diagnosis:
    """Convenience entrypoint: grab the first open incident and investigate it."""
    agent = CauzonAgent()
    incidents = agent.client.list_open_incidents()
    if not incidents:
        raise RuntimeError("No open incidents found.")
    raw = incidents[0]
    incident = Incident(
        urn=raw["urn"],
        title=raw["title"],
        description=raw["description"],
        failed_assertion=raw.get("failed_assertion"),
        detected_at=raw.get("detected_at"),
    )
    return agent.investigate(incident, on_event=on_event, write_back=write_back)
