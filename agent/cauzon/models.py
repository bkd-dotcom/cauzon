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
    # Present only when column-level lineage is available. None means the proof
    # holds at table level and says nothing about which field.
    column_path: Optional[ColumnPath] = None

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
            "column_path": self.column_path.to_dict() if self.column_path else None,
        }


@dataclass
class ColumnPath:
    """Which *field* carried the fault, when column lineage is available.

    A further rung on the same ladder as GroundingLevel: naming the column is
    strictly stronger than naming the table, and when DataHub has no
    column-level lineage the proof says so rather than implying it.
    """

    cause_field: str  # e.g. "amount"
    symptom_field: str  # e.g. "revenue"
    fields: list[str] = field(default_factory=list)  # ordered cause -> symptom

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImpactedAsset:
    """Something downstream of the symptom that inherits the same bad data."""

    urn: str
    name: str
    hops_from_symptom: int
    kind: str = "dataset"  # dataset | dashboard
    owner: Optional[str] = None
    # Whether this asset has its own failing assertion. Three states, not two:
    #
    #   True  — it is alerting, so somebody has been told
    #   False — it is affected and silent, which is the dangerous case
    #   None  — we could not determine it on this backend
    #
    # `None` exists because the alternative was worse. This field used to default
    # to False, and the catalogs that cannot report alerting status therefore had
    # every downstream asset recorded as "wrong and nobody is looking" — an
    # unchecked negative, asserted by a project whose whole claim is that it never
    # states what it cannot prove.
    alerting: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BlastRadius:
    """Everything the fault reached, not just the asset that happened to alert.

    Cauzon walks upstream to find the cause; this is the other direction. An
    on-call engineer's next question after "what broke it" is "what else is
    wrong that nobody has noticed yet".
    """

    symptom_urn: str
    impacted: list[ImpactedAsset] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.impacted)

    @property
    def silent(self) -> list[ImpactedAsset]:
        """Affected and confirmed not alerting — the ones that will surprise someone.

        Deliberately `is False` rather than falsy: an asset whose alerting status we
        could not determine is not evidence that nobody is looking at it.
        """
        return [a for a in self.impacted if a.alerting is False]

    @property
    def alerting(self) -> list[ImpactedAsset]:
        return [a for a in self.impacted if a.alerting is True]

    @property
    def unknown(self) -> list[ImpactedAsset]:
        """Affected, with alerting status this backend could not report."""
        return [a for a in self.impacted if a.alerting is None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symptom_urn": self.symptom_urn,
            "impacted": [a.to_dict() for a in self.impacted],
            "count": self.count,
            "silent_count": len(self.silent),
            "alerting_count": len(self.alerting),
            "unknown_count": len(self.unknown),
        }


@dataclass
class ProposedAssertion:
    """The check that would have caught this earlier, and closer to the source.

    Diagnosing a recurring failure without proposing the missing guardrail leaves
    the same incident free to happen again. This is the part that makes the
    write-back preventative rather than archival.
    """

    target_urn: str
    target_name: str
    kind: str  # freshness | volume | uniqueness | schema_contract
    description: str
    definition: str  # concrete, copyable assertion spec
    rationale: str
    # Roughly how much earlier this would have fired than the alert that did.
    lead_time: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineEvent:
    """One moment in the fault's propagation, ordered in time not topology."""

    at: str
    asset_name: str
    label: str
    kind: str  # fault_origin | transform_ran | assertion_fired | detected

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    blast_radius: Optional[BlastRadius] = None
    proposed_assertion: Optional[ProposedAssertion] = None
    timeline: list[TimelineEvent] = field(default_factory=list)
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
            "blast_radius": self.blast_radius.to_dict() if self.blast_radius else None,
            "proposed_assertion": (
                self.proposed_assertion.to_dict() if self.proposed_assertion else None
            ),
            "timeline": [e.to_dict() for e in self.timeline],
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


# --------------------------------------------------------------------------- #
# What a catalog can actually answer
# --------------------------------------------------------------------------- #
# Post-verdict findings each depend on metadata not every catalog holds. Naming
# them lets a backend declare its own limits up front, instead of the finding
# silently coming back empty and reading as "there is nothing to report".
CAP_COLUMN_LINEAGE = "column_lineage"
CAP_TRANSFORM_SQL = "transform_sql"
CAP_FAULT_ONSET = "fault_onset"
CAP_ALERTING_STATUS = "alerting_status"
CAP_PRIOR_DOSSIERS = "prior_dossiers"
CAP_WRITEBACK = "writeback"

CAPABILITY_LABELS = {
    CAP_COLUMN_LINEAGE: "Column-level proof",
    CAP_TRANSFORM_SQL: "Transform SQL",
    CAP_FAULT_ONSET: "Fault onset time",
    CAP_ALERTING_STATUS: "Downstream alerting status",
    CAP_PRIOR_DOSSIERS: "Prior dossiers",
    CAP_WRITEBACK: "Write-back",
}


@dataclass(frozen=True)
class Capabilities:
    """Which findings a backend can support, and why not where it cannot.

    An absent finding is ambiguous on its own: "no column path" could mean the
    fault did not travel through a column, or that the catalog has no column
    lineage to read. Four of Cauzon's post-verdict findings were presented as
    agent capabilities while being driven by metadata only the demo fixtures set,
    so on a real catalog they vanished with no explanation. A backend now states
    what it cannot answer, and the UI and dossier repeat the reason.
    """

    # name -> why it is unavailable. Absent from the dict means available.
    unavailable: dict[str, str] = field(default_factory=dict)

    def has(self, name: str) -> bool:
        return name not in self.unavailable

    def why(self, name: str) -> Optional[str]:
        return self.unavailable.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: {
                "label": CAPABILITY_LABELS.get(name, name),
                "available": name not in self.unavailable,
                "reason": self.unavailable.get(name),
            }
            for name in CAPABILITY_LABELS
        }
