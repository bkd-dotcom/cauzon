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
    FAILED_ASSERTION = "failed_assertion"
    RECENT_QUERY_CHANGE = "recent_query_change"
    UPSTREAM_INCIDENT = "upstream_incident"


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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["signals"] = [s.value for s in self.signals]
        return d


@dataclass
class ProofPath:
    """A *verifiable* lineage path from symptom to root cause.

    This is the novel core of Cauzon (PAVE / OpenRCA 2.0): a diagnosis is only
    accepted if the path connecting the symptom to the claimed cause can be
    reconstructed from real lineage edges + the transform SQL along the way.
    """

    symptom_urn: str
    cause_urn: str
    nodes: list[str] = field(default_factory=list)  # URNs, ordered symptom->cause
    edges: list[dict[str, str]] = field(default_factory=list)  # {from,to,via_query?}
    transform_sql: Optional[str] = None  # the SQL that introduced the fault
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Diagnosis:
    """The final, proof-carrying result of an investigation."""

    incident: Incident
    root_cause: Optional[CandidateCause]
    proof_path: Optional[ProofPath]
    ranked_candidates: list[CandidateCause] = field(default_factory=list)
    recommended_fix: str = ""
    confidence: float = 0.0
    grounded: bool = False  # True only if proof_path.verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident": self.incident.to_dict(),
            "root_cause": self.root_cause.to_dict() if self.root_cause else None,
            "proof_path": self.proof_path.to_dict() if self.proof_path else None,
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
            "recommended_fix": self.recommended_fix,
            "confidence": self.confidence,
            "grounded": self.grounded,
        }


@dataclass
class TraceEvent:
    """A single step in the agent's reasoning, streamed to the UI live."""

    phase: str  # detect | scope | hypothesize | prove | writeback
    message: str
    data: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
