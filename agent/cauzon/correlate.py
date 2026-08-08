"""One cause behind several alerts.

Single-incident RCA answers "why did *this* break". When one upstream asset fails,
every team downstream of it opens their own incident on their own asset, and that
question gets answered three times — three investigations, three dossiers, one
outage. The queue looks like three problems.

This finds the shared ancestor instead, and it is deliberately built on the same
proof gate as the single-incident path rather than a second kind of reasoning:

  1. Collect each symptom's upstream ancestors from real lineage.
  2. Intersect them. A cause of several symptoms has to be upstream of all of them.
  3. Drop any common ancestor carrying no signal — being central in a graph is not
     evidence of being broken.
  4. Prove a path from the candidate to **each** symptom, using `CauzonAgent._prove`
     unchanged. A shared cause is claimed only where the path holds for every
     symptom in the group.
  5. Grade the claim at the *weakest* rung across those proofs. A group finding
     cannot be better grounded than its worst link.

Where a candidate explains only some of the symptoms, the rest are reported as
unexplained rather than folded in. That is the same discipline as the rest of the
project: the interesting output is often the refusal.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .agent import CauzonAgent
from .models import (
    Correlation,
    CorrelatedSymptom,
    GroundingLevel,
    Incident,
)

# How far upstream to look for a shared ancestor. Matches the single-incident
# scope, so correlation cannot claim a cause an investigation would never find.
_HOPS = 3

# Weakest first, so `min` over a set of rungs gives the grade for the group.
_RUNG_ORDER = {
    GroundingLevel.UNGROUNDED: 0,
    GroundingLevel.PATH_ONLY: 1,
    GroundingLevel.PATH_AND_TRANSFORM: 2,
}


def correlate(
    client: Any,
    incidents: list[dict[str, Any]],
    on_event: Optional[Callable[[str, str], None]] = None,
) -> list[Correlation]:
    """Group open incidents that share a provable upstream cause.

    Returns one `Correlation` per shared cause found, strongest first. An empty
    list means no cause could be proven to more than one symptom — which is the
    correct answer for a queue of unrelated failures, and the property most worth
    testing.
    """

    def emit(message: str, phase: str = "scope") -> None:
        if on_event:
            on_event(phase, message)

    symptoms = [i for i in incidents if i.get("urn")]
    if len(symptoms) < 2:
        emit("Fewer than two open incidents — nothing to correlate.")
        return []

    agent = CauzonAgent(client=client)

    # Ancestors per symptom, from real lineage edges.
    ancestors: dict[str, dict[str, dict[str, Any]]] = {}
    for incident in symptoms:
        urn = incident["urn"]
        try:
            nodes = client.get_lineage(urn, direction="upstream", hops=_HOPS)
        except Exception:
            nodes = []
        ancestors[urn] = {n["urn"]: n for n in nodes if n.get("urn")}

    shared = set.intersection(*(set(a) for a in ancestors.values())) if ancestors else set()
    # Also consider ancestors shared by a subset: an outage rarely hits everything.
    for urn, nodes in ancestors.items():
        for candidate_urn in nodes:
            covered = [s["urn"] for s in symptoms if candidate_urn in ancestors[s["urn"]]]
            if len(covered) >= 2:
                shared.add(candidate_urn)

    if not shared:
        emit(
            f"No upstream asset is shared by two or more of the {len(symptoms)} open "
            f"incidents — these are separate failures."
        )
        return []

    emit(f"{len(shared)} upstream asset(s) are shared by two or more incidents.")

    correlations: list[Correlation] = []
    for candidate_urn in sorted(shared):
        try:
            entity = client.get_entity(candidate_urn)
        except Exception:
            entity = {}
        signals, notes = agent._signals_for(entity)
        if not signals:
            # Central, but showing no fault. Being a common dependency is not
            # evidence of being the broken one.
            continue

        proven: list[CorrelatedSymptom] = []
        unexplained: list[str] = []

        for incident in symptoms:
            symptom_urn = incident["urn"]
            if candidate_urn not in ancestors[symptom_urn]:
                continue
            hops = ancestors[symptom_urn][candidate_urn].get("hops", 1)
            proof = _prove_one(agent, incident, candidate_urn, entity, signals, notes)
            if proof is None:
                unexplained.append(symptom_urn)
                continue
            proven.append(
                CorrelatedSymptom(
                    urn=symptom_urn,
                    name=incident.get("title") or symptom_urn,
                    hops_from_cause=hops,
                    proof=proof,
                )
            )

        if len(proven) < 2:
            # One symptom is an ordinary investigation, not a correlation.
            continue

        grounding = min(
            (s.proof.grounding for s in proven), key=lambda g: _RUNG_ORDER[g]
        )
        correlations.append(
            Correlation(
                cause_urn=candidate_urn,
                cause_name=entity.get("name") or candidate_urn,
                cause_owner=entity.get("owner"),
                signals=signals,
                evidence_notes=notes,
                symptoms=proven,
                unexplained=unexplained,
                grounding=grounding,
            )
        )
        emit(
            f"{entity.get('name') or candidate_urn} is a proven upstream cause of "
            f"{len(proven)} of the {len(symptoms)} open incidents.",
            phase="prove",
        )

    # Most symptoms explained first, then the better-grounded claim.
    correlations.sort(
        key=lambda c: (len(c.symptoms), _RUNG_ORDER[c.grounding]), reverse=True
    )
    if not correlations:
        emit(
            "Shared upstreams exist, but none could be proven to more than one "
            "symptom while carrying a fault of its own.",
            phase="prove",
        )
    return correlations


def _prove_one(
    agent: CauzonAgent,
    incident: dict[str, Any],
    candidate_urn: str,
    entity: dict[str, Any],
    signals: list[Any],
    notes: list[str],
):
    """Run the single-incident proof gate for one (cause, symptom) pair.

    Reuses `CauzonAgent._prove` rather than reimplementing path reconstruction, so
    a correlation can never be grounded on evidence an investigation would reject.
    """
    from .models import CandidateCause

    candidate = CandidateCause(
        urn=candidate_urn,
        name=entity.get("name") or candidate_urn,
        hops_from_symptom=1,
        signals=list(signals),
        evidence_notes=list(notes),
        owner=entity.get("owner"),
    )
    symptom = Incident(
        urn=incident["urn"],
        title=incident.get("title") or "",
        description=incident.get("description") or "",
        failed_assertion=incident.get("failed_assertion"),
        detected_at=incident.get("detected_at"),
    )
    accepted, proof = agent._prove(symptom, [candidate], lambda *a, **k: None)
    if accepted is None or proof is None or not proof.verified:
        return None
    return proof
