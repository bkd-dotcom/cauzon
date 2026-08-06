"""Optional explanation layer — reasoning kept strictly separate from grounding.

The README cites DeepRoot (ICML 2026): *separate grounding from reasoning to cut
hallucination.* This module is that separation made real.

Everything that decides **what is true** lives in `agent.py`: the signal
extraction, the origin rule, the proof gate, the confidence factors. By the time
this module runs, the verdict is already settled and immutable. All this layer
does is put the settled facts into readable prose.

Three guarantees, enforced by construction rather than by prompt instruction:

1. **It cannot see anything ungrounded.** `_facts()` builds a plain dict from a
   diagnosis that already passed the proof gate. The model never receives the
   candidate list, the raw graph, or any hypothesis that was rejected.
2. **It cannot change the verdict.** `explain()` returns a string. The caller
   assigns it to `Diagnosis.narrative` and nothing else. There is no code path
   from this module to `grounded`, `root_cause`, `proof_path`, or `confidence`.
3. **It cannot invent an asset.** Output containing a URN is discarded — a
   fabricated `urn:li:dataset:(...)` is the one failure mode that would let prose
   contradict the proof, so it is checked rather than merely discouraged.

Narration is opt-in (`CAUZON_LLM_NARRATION=1`). Default behaviour, and the
behaviour with no API key or no SDK installed, is a deterministic template — so
the test suite is hermetic and a demo cannot fail on a network call.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .models import Diagnosis

_DEFAULT_MODEL = "claude-opus-5"

_SYSTEM = """You explain data-incident root-cause findings to the on-call data engineer who owns the broken pipeline.

You are given a finding that has ALREADY been proven by a separate grounding
system: the lineage path was reconstructed from real DataHub edges before you
were called. Your only job is to make that finding readable.

Rules:
- Explain only what the facts state. Never add a cause, a mechanism, or a number
  that is not in the facts.
- Never invent or write an asset URN. Refer to assets by their short name.
- Do not hedge about whether the diagnosis is correct — the proof already
  happened, upstream of you. Report the grounding level as the facts state it.
- If the facts say the transform SQL was unavailable, say the path is proven but
  the transform is not. Do not overclaim.
- Two short paragraphs, at most about 120 words. Plain prose, no headings, no
  bullet lists, no XML or internal tags.
- Lead with what broke and where it started. Then why the runner-up was rejected,
  if the facts include one."""


class TemplateReasoner:
    """Deterministic fallback. No network, no key, no variance."""

    source = "template"

    def explain(self, diagnosis: Diagnosis) -> tuple[Optional[str], str]:
        return _render_template(diagnosis), self.source


class ClaudeReasoner:
    """Writes the narrative with Claude. Explanation only — never the verdict."""

    source = "llm"

    def __init__(self, model: Optional[str] = None) -> None:
        import anthropic  # imported lazily so the core never requires the SDK

        self._client = anthropic.Anthropic()
        self._model = model or os.getenv("CAUZON_LLM_MODEL", _DEFAULT_MODEL)

    def explain(self, diagnosis: Diagnosis) -> tuple[Optional[str], str]:
        facts = _facts(diagnosis)
        if not facts:
            return _render_template(diagnosis), TemplateReasoner.source

        response = self._client.messages.create(
            model=self._model,
            # Generous: on Claude Opus 5 thinking is on by default and max_tokens
            # caps thinking + visible text together, so a tight cap here would
            # truncate the narrative rather than the reasoning.
            max_tokens=4096,
            output_config={"effort": "low"},  # short explanatory task
            system=_SYSTEM,
            messages=[{"role": "user", "content": _render_facts(facts)}],
        )

        # A refused request returns HTTP 200 with empty/partial content, so this
        # is checked before reading the blocks.
        if response.stop_reason == "refusal":
            return _render_template(diagnosis), TemplateReasoner.source

        text = "\n".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()

        if not text or not _is_safe(text):
            return _render_template(diagnosis), TemplateReasoner.source
        return text, self.source


def get_reasoner() -> Any:
    """Pick a reasoner. Anything missing or misconfigured falls back to templates."""
    if os.getenv("CAUZON_LLM_NARRATION", "").lower() not in {"1", "true", "yes"}:
        return TemplateReasoner()
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return TemplateReasoner()
    try:
        return ClaudeReasoner()
    except Exception:
        return TemplateReasoner()


# --------------------------------------------------------------------------- #
# Fact extraction — the boundary the model cannot reach past
# --------------------------------------------------------------------------- #
def _facts(diagnosis: Diagnosis) -> Optional[dict[str, Any]]:
    """Flatten a *grounded* diagnosis into plain, already-proven statements.

    Returns None when there is nothing proven to explain, so the model is never
    asked to narrate an ungrounded result.
    """
    cause = diagnosis.root_cause
    proof = diagnosis.proof_path
    if not (diagnosis.grounded and cause and proof):
        return None

    rejected = next(
        (
            {"name": c.name, "reason": c.rejected_reason, "score": c.score}
            for c in diagnosis.ranked_candidates
            if c.rejected_reason
        ),
        None,
    )
    return {
        "symptom": diagnosis.incident.title,
        "failed_assertion": diagnosis.incident.failed_assertion,
        "cause_name": cause.name,
        "evidence": list(cause.evidence_notes),
        "path": [_short_name(n) for n in proof.nodes],
        "grounding": diagnosis.grounding.label,
        "has_transform_sql": proof.transform_sql is not None,
        "confidence_pct": round(diagnosis.confidence * 100),
        "owner": cause.owner,
        "recurrence_count": (
            diagnosis.recurrence.count if diagnosis.recurrence else 0
        ),
        "fix": diagnosis.recommended_fix.summary if diagnosis.recommended_fix else None,
        "rejected": rejected,
    }


def _render_facts(f: dict[str, Any]) -> str:
    lines = [
        "PROVEN FINDING (do not re-litigate; explain only):",
        f"- Symptom: {f['symptom']}",
    ]
    if f.get("failed_assertion"):
        lines.append(f"- Failed assertion: {f['failed_assertion']}")
    lines += [
        f"- Root cause asset: {f['cause_name']}",
        f"- Lineage path, cause to symptom: {' -> '.join(f['path'])}",
        f"- Grounding level: {f['grounding']}",
        f"- Transform SQL captured: {'yes' if f['has_transform_sql'] else 'no'}",
        f"- Confidence: {f['confidence_pct']}%",
        "- Evidence:",
        *[f"    * {n}" for n in f["evidence"]],
    ]
    if f.get("owner"):
        lines.append(f"- Owner: {f['owner']}")
    if f.get("recurrence_count"):
        lines.append(
            f"- Prior Cauzon dossiers for this asset: {f['recurrence_count']}"
        )
    if f.get("rejected"):
        r = f["rejected"]
        lines.append(
            f"- Higher-scoring candidate REJECTED by the proof gate: "
            f"{r['name']} (score {r['score']}) — {r['reason']}"
        )
    if f.get("fix"):
        lines.append(f"- Recommended fix: {f['fix']}")
    return "\n".join(lines)


def _is_safe(text: str) -> bool:
    """Reject narration that fabricates an asset identifier.

    A made-up URN is the one output that could contradict the proof path, so it
    is checked rather than trusted to the prompt.
    """
    lowered = text.lower()
    return "urn:li:" not in lowered and "<thinking" not in lowered


def _short_name(urn: str) -> str:
    return urn.split(",")[1] if "," in urn else urn


# --------------------------------------------------------------------------- #
# Deterministic template
# --------------------------------------------------------------------------- #
def _render_template(diagnosis: Diagnosis) -> Optional[str]:
    cause = diagnosis.root_cause
    proof = diagnosis.proof_path
    if not (diagnosis.grounded and cause and proof):
        return (
            "No candidate could be connected to the symptom with a verifiable "
            "lineage path, so Cauzon is not naming a root cause. Escalating to a "
            "human rather than writing an unproven diagnosis to the catalog."
        )

    path = " → ".join(_short_name(n) for n in proof.nodes)
    parts = [
        f"`{cause.name}` is the origin of this incident, and the fault reached "
        f"the symptom along {path}. "
        f"{diagnosis.grounding.label} at {diagnosis.confidence:.0%} confidence."
    ]
    if cause.evidence_notes:
        parts.append(f"Evidence: {cause.evidence_notes[0]}")

    rejected = next(
        (c for c in diagnosis.ranked_candidates if c.rejected_reason), None
    )
    if rejected:
        parts.append(
            f"`{rejected.name}` scored higher on signals alone but was rejected: "
            f"{rejected.rejected_reason}"
        )
    if diagnosis.recurrence and diagnosis.recurrence.is_recurring:
        parts.append(
            f"This asset has failed {diagnosis.recurrence.count} time(s) before."
        )
    return " ".join(parts)
