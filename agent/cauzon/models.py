"""Typed data models for the Cauzon agent.

These are deliberately plain dataclasses (no pydantic dependency needed in the
core) so the agent package stays lightweight and easy to test. The FastAPI layer
converts them to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Signal(str, Enum):
    """Multimodal evidence signals used to rank candidate root causes.

    Mirrors RCRank (VLDB 2025): root cause ranking benefits from *multiple*
    heterogeneous signals rather than a single anomaly score.
    """

    FRESHNESS_LAG = "freshness_lag"
    SCHEMA_CHANGE = "schema_change"
    VOLUME_ANOMALY = "volume_anomaly"
    ROW_FANOUT = "row_fanout"
    FAILED_ASSERTION = "failed_assertion"
    RECENT_QUERY_CHANGE = "recent_query_change"
    UPSTREAM_INCIDENT = "upstream_incident"


class GroundingLevel(str, Enum):
    """How well a diagnosis can be *proven*, not merely ranked.

    Cauzon's central claim is that it never blames an asset it cannot connect to
    the symptom with real lineage evidence. A boolean cannot express the honest
    middle case — a reconstructable path whose transform SQL DataHub does not
    retain — so grounding is a ladder and every artifact states its own rung.
    """

    PATH_AND_TRANSFORM = "path_and_transform"  # edges + the SQL that carried the fault
    PATH_ONLY = "path_only"  # edges reconstructed, no transform SQL available
    UNGROUNDED = "ungrounded"  # no path — hypothesis rejected

    @property
    def is_grounded(self) -> bool:
        return self is not GroundingLevel.UNGROUNDED

    @property
    def label(self) -> str:
        return {
            GroundingLevel.PATH_AND_TRANSFORM: "Path + transform proven",
            GroundingLevel.PATH_ONLY: "Path proven, transform unavailable",
            GroundingLevel.UNGROUNDED: "Not grounded",
        }[self]


@dataclass
class Incident:
    """A data-quality symptom to investigate."""

    urn: str  # URN of the affected (symptom) dataset
    title: str
    description: str
    failed_assertion: Optional[str] = None
    detected_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateCause:
    """A hypothesized upstream culprit, with its accumulated evidence."""

    urn: str
    name: str
    hops_from_symptom: int
    signals: list[Signal] = field(default_factory=list)
    score: float = 0.0
    evidence_notes: list[str] = field(default_factory=list)
    # True when this node carries the signal and none of its own upstreams do —
    # i.e. the fault appears to *originate* here rather than being inherited.
    is_origin: bool = True
    # Set when the proof gate rejected this candidate, so the UI can show the
    # gate working rather than silently dropping the suspect.
    rejected_reason: Optional[str] = None
    owner: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["signals"] = [s.value for s in self.signals]
        return d


@dataclass
class ProofPath:
    """A *verifiable* lineage path from symptom to root cause.

    This is the novel core of Cauzon (PAVE / OpenRCA 2.0): a diagnosis is only
    accepted if the path connecting the symptom to the claimed cause can be
    reconstructed from real lineage edges. When the transform SQL along that path
    is also retrievable the proof is complete; when it is not, the path still
    stands but the artifact says so instead of overclaiming.
    """

    symptom_urn: str
    cause_urn: str
    nodes: list[str] = field(default_factory=list)  # URNs, ordered cause->symptom
    edges: list[dict[str, Any]] = field(default_factory=list)  # {from,to,via_query?}
    transform_sql: Optional[str] = None  # the SQL that carried the fault downstream
    causal_edge_index: Optional[int] = None  # which edge transform_sql came from
    grounding: GroundingLevel = GroundingLevel.UNGROUNDED

    @property
    def verified(self) -> bool:
        """A path was reconstructed from real lineage edges."""
        return self.grounding.is_grounded

    def to_dict(self) -> dict[str, Any]:
        return {
            "symptom_urn": self.symptom_urn,
            "cause_urn": self.cause_urn,
            "nodes": self.nodes,
            "edges": self.edges,
            "transform_sql": self.transform_sql,
            "causal_edge_index": self.causal_edge_index,
            "grounding": self.grounding.value,
            "grounding_label": self.grounding.label,
            "verified": self.verified,
        }


@dataclass
class ConfidenceBreakdown:
    """Why the confidence number is what it is.

    Confidence is a product of three named factors so every number the UI shows
    traces back to a stated reason rather than a tuned constant.
    """

    grounding_factor: float
    signal_factor: float
    origin_factor: float
    grounding_reason: str = ""
    signal_reason: str = ""
    origin_reason: str = ""

    @property
    def total(self) -> float:
        return round(self.grounding_factor * self.signal_factor * self.origin_factor, 2)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total"] = self.total
        return d


@dataclass
class RecommendedFix:
    """A concrete next action, not just advice.

    `action` is derived deterministically from facts Cauzon already captured (the
    transform SQL on the causal edge, the culprit's schema). Nothing here is
    model-generated — a tool whose pitch is "only what it can prove" should not
    hand out an unverifiable statement.
    """

    summary: str
    action_kind: str = "manual"  # sql | command | manual
    action: Optional[str] = None
    action_note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PriorIncident:
    """A previous Cauzon dossier found in the catalog for the same asset."""

    document_urn: str
    title: str
    detected_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Recurrence:
    """Whether this asset has failed before, read back out of the catalog.

    Cauzon writes dossiers with `save_document`; reading them back with
    `search_documents` closes the loop, so each investigation inherits what the
    previous one learned instead of starting cold.
    """

    asset_urn: str
    prior: list[PriorIncident] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.prior)

    @property
    def is_recurring(self) -> bool:
        return self.count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_urn": self.asset_urn,
            "prior": [p.to_dict() for p in self.prior],
            "count": self.count,
            "is_recurring": self.is_recurring,
        }


@dataclass
class Diagnosis:
    """The final, proof-carrying result of an investigation."""

    incident: Incident
    root_cause: Optional[CandidateCause]
    proof_path: Optional[ProofPath]
    ranked_candidates: list[CandidateCause] = field(default_factory=list)
    recommended_fix: Optional[RecommendedFix] = None
    confidence: float = 0.0
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    grounding: GroundingLevel = GroundingLevel.UNGROUNDED
    recurrence: Optional[Recurrence] = None
    narrative: Optional[str] = None  # optional LLM-written explanation
    narrative_source: str = "template"  # template | llm

    @property
    def grounded(self) -> bool:
        return self.grounding.is_grounded

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident": self.incident.to_dict(),
            "root_cause": self.root_cause.to_dict() if self.root_cause else None,
            "proof_path": self.proof_path.to_dict() if self.proof_path else None,
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
            "recommended_fix": (
                self.recommended_fix.to_dict() if self.recommended_fix else None
            ),
            "confidence": self.confidence,
            "confidence_breakdown": (
                self.confidence_breakdown.to_dict() if self.confidence_breakdown else None
            ),
            "grounding": self.grounding.value,
            "grounding_label": self.grounding.label,
            "grounded": self.grounded,
            "recurrence": self.recurrence.to_dict() if self.recurrence else None,
            "narrative": self.narrative,
            "narrative_source": self.narrative_source,
        }


@dataclass
class TraceEvent:
    """A single step in the agent's reasoning, streamed to the UI live."""

    phase: str  # detect | scope | hypothesize | prove | writeback
    message: str
    data: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
