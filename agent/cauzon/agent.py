"""The Cauzon investigation loop.

Five phases, each grounded in recent top-venue RCA / grounding research:

  1. detect      — pick up a failing assertion / incident.
  2. scope       — pull the minimal upstream subgraph (WM-SAR: compact subgraph).
  3. hypothesize — rank candidate culprits from multimodal signals (RCRank).
  4. prove       — accept a cause ONLY with a verifiable lineage path
                   (PAVE / OpenRCA 2.0: no ungrounded diagnosis).
  5. writeback   — persist the dossier + annotate the culprit in DataHub.

The loop yields TraceEvents so a UI can stream the reasoning live.

Grounding is kept strictly separate from reasoning (DeepRoot, ICML 2026): the
code in this module decides *what is proven*, and the optional reasoner in
`reasoner.py` only ever explains a decision that has already been made.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from .datahub_client import DataHubClient, get_client
from .models import (
    CandidateCause,
    ConfidenceBreakdown,
    Diagnosis,
    GroundingLevel,
    Incident,
    PriorIncident,
    ProofPath,
    Recurrence,
    RecommendedFix,
    Signal,
    TraceEvent,
)

# Signal weights for ranking. Freshness/schema/fanout dominate because each can
# originate a fault; a volume anomaly is more often a *symptom* of one of them.
_SIGNAL_WEIGHTS: dict[Signal, float] = {
    Signal.FRESHNESS_LAG: 3.0,
    Signal.SCHEMA_CHANGE: 3.0,
    Signal.ROW_FANOUT: 3.0,
    Signal.UPSTREAM_INCIDENT: 2.5,
    Signal.VOLUME_ANOMALY: 2.0,
    Signal.RECENT_QUERY_CHANGE: 1.5,
    Signal.FAILED_ASSERTION: 1.0,
}

# A fault that also appears upstream was probably inherited, not originated here.
_INHERITED_PENALTY = 0.6

# Volume swing (percent) that counts as anomalous.
_VOLUME_ANOMALY_PCT = 20.0


class CauzonAgent:
    def __init__(
        self,
        client: Optional[DataHubClient] = None,
        reasoner: Optional[Any] = None,
    ) -> None:
        self.client = client or get_client()
        # Lazily resolved so the core never hard-depends on an LLM being present.
        self._reasoner = reasoner
        self._lineage_cache: dict[str, list[dict[str, Any]]] = {}

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

        def emit(phase: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
            ev = TraceEvent(phase=phase, message=message, data=data)
            if on_event:
                on_event(ev)

        # 1) DETECT
        emit("detect", f"Picked up incident: {incident.title}", incident.to_dict())

        # 2) SCOPE — minimal upstream subgraph
        upstream = self.client.get_lineage(incident.urn, direction="upstream", hops=3)
        emit(
            "scope",
            f"Pulled {len(upstream)} upstream nodes within 3 hops.",
            {"upstream": upstream, "symptom_urn": incident.urn},
        )

        # 3) HYPOTHESIZE — score each upstream node from multimodal signals
        candidates = self._rank_candidates(upstream, emit)

        # 4) PROVE — walk down the ranked list until a verifiable path is found
        root_cause, proof = self._prove(incident, candidates, emit)

        # 4b) Read prior dossiers back out of the catalog. Cauzon writes what it
        # learns; reading it back is what makes the knowledge compound.
        recurrence = self._find_recurrence(root_cause, emit) if root_cause else None

        # 4c) Route the diagnosis to a person.
        if root_cause:
            root_cause.owner = self._resolve_owner(root_cause.urn)

        grounding = proof.grounding if proof else GroundingLevel.UNGROUNDED
        breakdown = self._confidence(root_cause, grounding)
        diagnosis = Diagnosis(
            incident=incident,
            root_cause=root_cause,
            proof_path=proof,
            ranked_candidates=candidates,
            recommended_fix=self._recommend_fix(root_cause, proof, recurrence),
            confidence=breakdown.total if breakdown else 0.0,
            confidence_breakdown=breakdown,
            grounding=grounding,
            recurrence=recurrence,
        )

        # Explanation runs last, over facts that are already settled. It cannot
        # change the verdict — see reasoner.explain's contract.
        self._explain(diagnosis, emit)

        # 5) WRITEBACK
        if write_back and diagnosis.grounded:
            self._write_back(diagnosis, emit)
        elif write_back:
            emit(
                "writeback",
                "No verifiable root cause found — refusing to write an ungrounded "
                "diagnosis back to the catalog.",
            )

        return diagnosis

    # ------------------------------------------------------------------ #
    # Phase 3 — hypothesize
    # ------------------------------------------------------------------ #
    def _rank_candidates(
        self,
        upstream: list[dict[str, Any]],
        emit: Callable[..., None],
    ) -> list[CandidateCause]:
        """Score every upstream node, then decide which ones look like origins.

        Two passes are needed: a node's score depends on whether its *own*
        upstreams show the same fault, which we can only judge once every node
        has been profiled.
        """
        profiled: dict[str, dict[str, Any]] = {}
        for node in upstream:
            urn = node["urn"]
            signals, notes = self._signals_for(self.client.get_entity(urn))
            profiled[urn] = {"node": node, "signals": signals, "notes": notes}

        candidates: list[CandidateCause] = []
        for urn, prof in profiled.items():
            signals: list[Signal] = prof["signals"]
            notes: list[str] = list(prof["notes"])
            is_origin, origin_note = self._assess_origin(urn, signals, profiled)
            if origin_note:
                notes.append(origin_note)

            raw = sum(_SIGNAL_WEIGHTS[s] for s in signals)
            score = raw if is_origin else raw * _INHERITED_PENALTY

            candidates.append(
                CandidateCause(
                    urn=urn,
                    name=prof["node"].get("name", urn),
                    hops_from_symptom=prof["node"].get("hops", 0),
                    signals=signals,
                    score=round(score, 3),
                    evidence_notes=notes,
                    is_origin=is_origin,
                )
            )

        candidates.sort(key=lambda c: (c.score, c.hops_from_symptom), reverse=True)
        with_evidence = [c for c in candidates if c.signals]
        emit(
            "hypothesize",
            f"Ranked {len(candidates)} candidates; {len(with_evidence)} carry evidence. "
            + (f"Top: {candidates[0].name}" if candidates else "No candidates."),
            {"candidates": [c.to_dict() for c in candidates]},
        )
        return candidates

    def _signals_for(self, entity: dict[str, Any]) -> tuple[list[Signal], list[str]]:
        """Derive evidence signals from an asset's metadata.

        Every signal appends a note carrying the *actual numbers*, so the UI and
        the dossier can show why rather than merely asserting.
        """
        signals: list[Signal] = []
        notes: list[str] = []

        fresh = entity.get("freshness_hours")
        expected = entity.get("expected_freshness_hours")
        if fresh is not None and expected is not None and fresh > expected:
            signals.append(Signal.FRESHNESS_LAG)
            notes.append(
                f"Freshness {fresh}h exceeds the {expected}h SLA "
                f"(+{round(fresh - expected, 1)}h stale)."
            )

        delta = entity.get("row_count_delta_pct")
        if delta is not None and abs(delta) >= _VOLUME_ANOMALY_PCT:
            signals.append(Signal.VOLUME_ANOMALY)
            notes.append(f"Row count changed {delta:+.0f}% vs baseline.")

        if entity.get("schema_changed_recently"):
            signals.append(Signal.SCHEMA_CHANGE)
            notes.append(entity.get("schema_change_note") or "Schema changed recently.")

        if entity.get("duplicate_key_pct"):
            signals.append(Signal.ROW_FANOUT)
            notes.append(
                entity.get("fanout_note")
                or f"{entity['duplicate_key_pct']:.1f}% of join-key values are duplicated."
            )

        if entity.get("has_open_incident"):
            signals.append(Signal.UPSTREAM_INCIDENT)
            notes.append(entity.get("incident_note") or "Has its own open incident.")

        return signals, notes

    def _assess_origin(
        self,
        urn: str,
        signals: list[Signal],
        profiled: dict[str, dict[str, Any]],
    ) -> tuple[bool, Optional[str]]:
        """Does this fault *start* here, or was it inherited from further up?

        This is the causal argument that makes one candidate better than another:
        a node is the origin when it shows the fault and nothing feeding it does.
        Ranking by hop distance alone only works when the graph is a clean chain.
        """
        if not signals:
            return True, None

        shared: list[str] = []
        for parent in self._direct_upstreams(urn):
            parent_urn = parent.get("urn")
            if not parent_urn:
                continue
            parent_signals = self._signals_of(parent_urn, profiled)
            overlap = set(signals) & set(parent_signals)
            if overlap:
                shared.append(parent.get("name") or parent_urn)

        if shared:
            return False, (
                f"Same fault is already present upstream in {', '.join(shared)} — "
                f"likely inherited rather than originated here."
            )
        return True, "No upstream shows this fault — the fault appears to originate here."

    def _direct_upstreams(self, urn: str) -> list[dict[str, Any]]:
        """One-hop upstreams, via the same lineage API both backends implement."""
        if urn not in self._lineage_cache:
            try:
                self._lineage_cache[urn] = self.client.get_lineage(
                    urn, direction="upstream", hops=1
                )
            except Exception:
                self._lineage_cache[urn] = []
        return self._lineage_cache[urn]

    def _signals_of(self, urn: str, profiled: dict[str, dict[str, Any]]) -> list[Signal]:
        """Signals for a node, profiling it on demand if it fell outside scope."""
        if urn in profiled:
            return profiled[urn]["signals"]
        signals, notes = self._signals_for(self.client.get_entity(urn))
        profiled[urn] = {"node": {"urn": urn}, "signals": signals, "notes": notes}
        return signals

    # ------------------------------------------------------------------ #
    # Phase 4 — prove
    # ------------------------------------------------------------------ #
    def _prove(
        self,
        incident: Incident,
        candidates: list[CandidateCause],
        emit: Callable[..., None],
    ) -> tuple[Optional[CandidateCause], Optional[ProofPath]]:
        """Accept the highest-ranked candidate whose path we can reconstruct.

        This is the differentiator: the ranking is only a hypothesis. A candidate
        is accepted only once its lineage path back to the symptom is rebuilt
        from real edges — a high score with no path is rejected outright, and the
        rejection is recorded on the candidate so the UI can show the gate work.
        """
        for cand in candidates:
            if not cand.signals:
                continue  # no evidence at all — nothing to prove

            paths = self.client.get_lineage_paths_between(
                source_urn=incident.urn, target_urn=cand.urn
            )
            if not paths:
                cand.rejected_reason = (
                    "No lineage path connects this asset to the symptom, so the "
                    "claim cannot be grounded."
                )
                emit(
                    "prove",
                    f"Rejected {cand.name} (score {cand.score}): no lineage path to "
                    f"the symptom — cannot ground the claim.",
                    {"rejected_urn": cand.urn, "reason": cand.rejected_reason},
                )
                continue

            path = paths[0]
            edges = path.get("edges", [])
            if not edges:
                cand.rejected_reason = "Lineage path had no reconstructable edges."
                emit(
                    "prove",
                    f"Rejected {cand.name}: path had no reconstructable edges.",
                    {"rejected_urn": cand.urn, "reason": cand.rejected_reason},
                )
                continue

            transform_sql, edge_index = self._causal_transform(cand.urn, edges)
            grounding = (
                GroundingLevel.PATH_AND_TRANSFORM
                if transform_sql
                else GroundingLevel.PATH_ONLY
            )
            proof = ProofPath(
                symptom_urn=incident.urn,
                cause_urn=cand.urn,
                nodes=path.get("nodes", []),
                edges=edges,
                transform_sql=transform_sql,
                causal_edge_index=edge_index,
                grounding=grounding,
            )
            detail = (
                "transform that carried the fault captured"
                if transform_sql
                else "no transform SQL retained for this edge"
            )
            emit(
                "prove",
                f"Verified path to {cand.name} across {len(edges)} lineage edge(s) — "
                f"{detail}.",
                proof.to_dict(),
            )
            return cand, proof

        emit("prove", "No candidate could be grounded with a verifiable path.")
        return None, None

    @staticmethod
    def _causal_transform(
        cause_urn: str, edges: list[dict[str, Any]]
    ) -> tuple[Optional[str], Optional[int]]:
        """Find the SQL that carried the fault out of the culprit.

        The causal edge is the one *leaving* the culprit; that transform is what
        propagated the fault downstream. Any other edge on the path is a weaker
        witness, so it is only used as a fallback.
        """
        for i, e in enumerate(edges):
            if e.get("from") == cause_urn and e.get("via_query"):
                return e["via_query"], i
        for i, e in enumerate(edges):
            if e.get("via_query"):
                return e["via_query"], i
        return None, None

    # ------------------------------------------------------------------ #
    # Phase 4b — recurrence, read back out of the catalog
    # ------------------------------------------------------------------ #
    def _find_recurrence(
        self, cause: Optional[CandidateCause], emit: Callable[..., None]
    ) -> Optional[Recurrence]:
        if not cause:
            return None
        search = getattr(self.client, "search_documents", None)
        if not callable(search):
            return None
        try:
            hits = search(f"[Cauzon] RCA {cause.name}") or []
        except Exception:
            return None

        prior = [
            PriorIncident(
                document_urn=h.get("urn", ""),
                title=h.get("title", ""),
                detected_at=h.get("detected_at"),
            )
            for h in hits
        ]
        recurrence = Recurrence(asset_urn=cause.urn, prior=prior)
        if recurrence.is_recurring:
            emit(
                "hypothesize",
                f"{cause.name} has {recurrence.count} prior Cauzon dossier(s) — this is "
                f"a recurring failure, not a one-off.",
                recurrence.to_dict(),
            )
        return recurrence

    def _resolve_owner(self, urn: str) -> Optional[str]:
        try:
            return self.client.get_entity(urn).get("owner")
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Scoring the result
    # ------------------------------------------------------------------ #
    def _confidence(
        self, cause: Optional[CandidateCause], grounding: GroundingLevel
    ) -> Optional[ConfidenceBreakdown]:
        """Confidence as a product of three named, individually-reportable factors."""
        if not cause or not grounding.is_grounded:
            return None

        grounding_factor = 1.0 if grounding is GroundingLevel.PATH_AND_TRANSFORM else 0.75
        grounding_reason = (
            "Lineage path and the transform that carried the fault were both reconstructed."
            if grounding is GroundingLevel.PATH_AND_TRANSFORM
            else "Lineage path reconstructed, but DataHub retains no transform SQL for "
            "the causal edge."
        )

        n = len(set(cause.signals))
        signal_factor = min(0.55 + 0.15 * n, 1.0)
        signal_reason = (
            f"{n} independent signal(s) agree: "
            f"{', '.join(s.value.replace('_', ' ') for s in cause.signals)}."
        )

        origin_factor = 1.0 if cause.is_origin else 0.7
        origin_reason = (
            "No upstream asset shows this fault, so it originates here."
            if cause.is_origin
            else "An upstream asset shows the same fault, so this may be inherited."
        )

        return ConfidenceBreakdown(
            grounding_factor=grounding_factor,
            signal_factor=round(signal_factor, 2),
            origin_factor=origin_factor,
            grounding_reason=grounding_reason,
            signal_reason=signal_reason,
            origin_reason=origin_reason,
        )

    # ------------------------------------------------------------------ #
    # Recommendation — a concrete action, derived from captured facts
    # ------------------------------------------------------------------ #
    def _recommend_fix(
        self,
        cause: Optional[CandidateCause],
        proof: Optional[ProofPath],
        recurrence: Optional[Recurrence],
    ) -> RecommendedFix:
        if not cause:
            return RecommendedFix(
                summary="Escalate to a human: no grounded root cause identified.",
            )

        owner_hint = f" Owner: {cause.owner}." if cause.owner else ""
        recurring = bool(recurrence and recurrence.is_recurring)

        if Signal.SCHEMA_CHANGE in cause.signals:
            fix = self._schema_change_fix(cause, proof)
        elif Signal.FRESHNESS_LAG in cause.signals:
            fix = self._freshness_fix(cause, proof)
        elif Signal.ROW_FANOUT in cause.signals:
            fix = self._fanout_fix(cause, self._duplicated_key(cause))
        else:
            fix = RecommendedFix(
                summary=f"Inspect `{cause.name}` — it carries the strongest anomaly signals.",
            )

        fix.summary += owner_hint
        if recurring:
            fix.summary += (
                f" This is failure #{recurrence.count + 1} for this asset — treat the "
                f"schedule or contract as the real defect, not just this occurrence."
            )
        return fix

    def _schema_change_fix(
        self, cause: CandidateCause, proof: Optional[ProofPath]
    ) -> RecommendedFix:
        """Rewrite the broken transform using the culprit's *current* schema."""
        summary = (
            f"Reconcile the schema change on `{cause.name}` with its downstream "
            f"consumers, then add a schema contract so the next rename fails loudly."
        )
        old, new = self._renamed_columns(cause)
        sql = proof.transform_sql if proof else None
        if sql and old and new and old in sql:
            return RecommendedFix(
                summary=summary,
                action_kind="sql",
                action=sql.replace(old, new),
                action_note=(
                    f"The transform still reads `{old}`, which no longer exists. "
                    f"Above is the same statement with `{new}` substituted."
                ),
            )
        return RecommendedFix(summary=summary)

    def _renamed_columns(self, cause: CandidateCause) -> tuple[Optional[str], Optional[str]]:
        """Recover the (old, new) column names, confirming the new one really exists.

        The rename is read from the note that produced the signal, then checked
        against the live schema — Cauzon should not propose a column it has not
        seen.
        """
        note = next(
            (n for n in cause.evidence_notes if "renamed" in n.lower()),
            None,
        )
        if not note:
            return None, None
        quoted = [w.strip("`") for w in note.split("`")[1::2]]
        if len(quoted) < 2:
            return None, None
        old, new = quoted[0], quoted[1]
        try:
            fields = {f.get("name") for f in self.client.list_schema_fields(cause.urn)}
        except Exception:
            return None, None
        if new in fields and old not in fields:
            return old, new
        return None, None

    @staticmethod
    def _freshness_fix(cause: CandidateCause, proof: Optional[ProofPath]) -> RecommendedFix:
        downstream = [
            n.split(",")[1] if "," in n else n
            for n in (proof.nodes[1:] if proof and len(proof.nodes) > 1 else [])
        ]
        replay = " → ".join(downstream) if downstream else "the downstream transforms"
        return RecommendedFix(
            summary=(
                f"Restart the ingestion job feeding `{cause.name}` and backfill the "
                f"missing window; it is the upstream origin of the staleness."
            ),
            action_kind="command",
            action=f"# 1. backfill the stalled source\n"
            f"datahub ingest -c {cause.name}.yml\n"
            f"# 2. replay downstream, in dependency order\n"
            f"#    {replay}",
            action_note=(
                "Downstream assets only recover once fresh data lands, so replay them "
                "in lineage order after the backfill completes."
            ),
        )

    def _duplicated_key(self, cause: CandidateCause) -> Optional[str]:
        """Recover the duplicated join key, confirming it exists in the schema."""
        note = next((n for n in cause.evidence_notes if "duplicate" in n.lower()), None)
        if not note or "`" not in note:
            return None
        candidate = note.split("`")[1]
        try:
            fields = {f.get("name") for f in self.client.list_schema_fields(cause.urn)}
        except Exception:
            return None
        return candidate if candidate in fields else None

    @staticmethod
    def _fanout_fix(cause: CandidateCause, key: Optional[str]) -> RecommendedFix:
        col = key or "<join_key>"
        note = (
            "Add a uniqueness assertion on this key so a duplicate load fails at the "
            "source instead of silently inflating downstream metrics."
        )
        if not key:
            note = f"Substitute the real join key for `{col}` before running. " + note
        return RecommendedFix(
            summary=(
                f"De-duplicate `{cause.name}` and restore its key uniqueness — the "
                f"duplicate keys are fanning out every downstream join."
            ),
            action_kind="sql",
            action=(
                "-- confirm the fanout before fixing it\n"
                f"SELECT {col}, COUNT(*) AS copies\n"
                f"FROM {cause.name}\n"
                f"GROUP BY {col}\n"
                "HAVING COUNT(*) > 1\n"
                "ORDER BY copies DESC;"
            ),
            action_note=note,
        )

    # ------------------------------------------------------------------ #
    # Optional explanation layer (grounding stays separate from reasoning)
    # ------------------------------------------------------------------ #
    def _explain(self, diagnosis: Diagnosis, emit: Callable[..., None]) -> None:
        if self._reasoner is None:
            from . import reasoner as _reasoner_mod

            self._reasoner = _reasoner_mod.get_reasoner()
        try:
            narrative, source = self._reasoner.explain(diagnosis)
        except Exception:
            return
        if not narrative:
            return
        diagnosis.narrative = narrative
        diagnosis.narrative_source = source
        if source == "llm":
            emit(
                "hypothesize",
                "Wrote a plain-language explanation of the grounded evidence "
                "(explanation only — the verdict was already settled).",
                {"narrative_source": source},
            )

    # ------------------------------------------------------------------ #
    # Phase 5 — writeback
    # ------------------------------------------------------------------ #
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
            f"'{diagnosis.incident.title}' ({diagnosis.grounding.label}, "
            f"{diagnosis.confidence:.0%} confidence). See dossier {doc_urn}.",
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
            f"**Failed assertion:** {inc.failed_assertion}  ",
            f"**Grounding:** {diagnosis.grounding.label}",
            "",
            "## Root cause",
        ]
        if not (cause and proof):
            lines.append("_No grounded root cause could be established._")
            return "\n".join(lines)

        lines += [
            f"**{cause.name}** — `{cause.urn}`  ",
            f"Confidence: {diagnosis.confidence:.0%}",
        ]
        if cause.owner:
            lines.append(f"Owner: {cause.owner}")
        lines += ["", "### Evidence", *[f"- {n}" for n in cause.evidence_notes]]

        if diagnosis.confidence_breakdown:
            b = diagnosis.confidence_breakdown
            lines += [
                "",
                "### How this confidence was derived",
                f"- Grounding ×{b.grounding_factor} — {b.grounding_reason}",
                f"- Signals ×{b.signal_factor} — {b.signal_reason}",
                f"- Origin ×{b.origin_factor} — {b.origin_reason}",
            ]

        if diagnosis.recurrence and diagnosis.recurrence.is_recurring:
            lines += [
                "",
                "### Recurrence",
                f"This asset has {diagnosis.recurrence.count} prior Cauzon dossier(s):",
                *[
                    f"- {p.title} (`{p.document_urn}`)"
                    for p in diagnosis.recurrence.prior
                ],
            ]

        lines += [
            "",
            "### Verifiable lineage proof path",
            "```",
            " -> ".join(n.split(",")[1] if "," in n else n for n in proof.nodes),
            "```",
        ]
        if proof.transform_sql:
            lines += [
                "",
                "**Transform that carried the fault downstream:**",
                "```sql",
                proof.transform_sql,
                "```",
            ]
        else:
            lines += [
                "",
                "_DataHub retains no transform SQL for the causal edge, so this "
                "dossier proves the path but not the transform._",
            ]

        rejected = [c for c in diagnosis.ranked_candidates if c.rejected_reason]
        if rejected:
            lines += [
                "",
                "### Candidates rejected by the proof gate",
                *[f"- **{c.name}** (score {c.score}) — {c.rejected_reason}" for c in rejected],
            ]

        fix = diagnosis.recommended_fix
        if fix:
            lines += ["", "## Recommended fix", fix.summary]
            if fix.action:
                lang = "sql" if fix.action_kind == "sql" else "bash"
                lines += ["", f"```{lang}", fix.action, "```"]
            if fix.action_note:
                lines += ["", fix.action_note]

        if diagnosis.narrative:
            lines += ["", "## Summary", diagnosis.narrative]

        lines += [
            "",
            "---",
            "_Generated by Cauzon — path-grounded RCA agent for DataHub._",
        ]
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
