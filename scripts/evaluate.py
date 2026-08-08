"""Measure the agent against fixtures whose correct answer is declared separately.

Every claim in the README about the proof gate has been an assertion so far. This
turns four of them into numbers, and writes them to a generated artifact CI
drift-checks, so the published figures cannot quietly stop being true.

Four things are measured, and the third is the one that matters:

  * **Localisation** — is the named cause the one the fixture declares?
  * **Refusal** — on a graph where the strongest-signalled suspect has no path,
    does the agent name nothing at all?
  * **Grounding honesty** — does the rung the agent *claims* match what the
    fixture actually supports? A tool that always said PATH_AND_TRANSFORM would
    score full marks on localisation and fail here. This checks the label against
    reality rather than trusting it.
  * **False cause** — is the ungroundable decoy ever named?

Ground truth lives in `EXPECTED` below and in the fixtures' own contents, not in
the agent's output, so this cannot grade itself.

    python scripts/evaluate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from cauzon.agent import CauzonAgent  # noqa: E402
from cauzon.datahub_client import MOCK_SCENARIOS, MockDataHubClient  # noqa: E402
from cauzon.models import GroundingLevel, Incident  # noqa: E402

OUT = ROOT / "docs" / "evaluation.json"

# The correct answer per scenario, declared here rather than read from the agent.
EXPECTED: dict[str, str] = {
    "freshness": "raw_trips",
    "schema_change": "raw_orders",
    "fanout": "user_dim",
    "shared_cause": "currency_rates",
    "shared_cause_ops": "currency_rates",
}

# Assets the agent must never name. `marketing_spend` outranks the real culprit on
# signals and has no lineage path to the symptom.
FORBIDDEN = {"marketing_spend"}


def _supported_rung(client: MockDataHubClient, cause_urn: str, proof: Any) -> GroundingLevel:
    """The best rung this fixture can honestly support for the accepted cause.

    Derived from the fixture, independently of what the agent claimed: a path
    exists if the proof reconstructed edges, and the transform is available only if
    some node on the path actually carries query text.
    """
    if proof is None or not proof.nodes:
        return GroundingLevel.UNGROUNDED
    has_transform = any(
        client._graph.get(urn, {}).get("queries") for urn in proof.nodes
    )
    return (
        GroundingLevel.PATH_AND_TRANSFORM if has_transform else GroundingLevel.PATH_ONLY
    )


def _run(scenario: str) -> dict[str, Any]:
    client = MockDataHubClient(scenario=scenario)
    incident = client.list_open_incidents()[0]
    diagnosis = CauzonAgent(client=client).investigate(
        Incident(
            urn=incident["urn"],
            title=incident["title"],
            description=incident.get("description", ""),
            failed_assertion=incident.get("failed_assertion"),
            detected_at=incident.get("detected_at"),
        ),
        write_back=False,
    )

    named = diagnosis.root_cause.name if diagnosis.root_cause else None
    expected = EXPECTED[scenario]
    supported = _supported_rung(client, named, diagnosis.proof_path)

    return {
        "scenario": scenario,
        "expected_cause": expected,
        "named_cause": named,
        "localised": named == expected,
        "claimed_grounding": diagnosis.grounding.value,
        "supported_grounding": supported.value,
        # Overclaiming is the failure. Claiming *less* than the fixture supports is
        # conservative, not dishonest, so it is not counted against the agent.
        "grounding_honest": _rung(diagnosis.grounding) <= _rung(supported),
        "named_a_forbidden_asset": named in FORBIDDEN,
        "rejected_count": sum(
            1 for c in diagnosis.ranked_candidates if c.rejected_reason
        ),
        "confidence": diagnosis.confidence,
    }


_RUNGS = {
    GroundingLevel.UNGROUNDED: 0,
    GroundingLevel.PATH_ONLY: 1,
    GroundingLevel.PATH_AND_TRANSFORM: 2,
}


def _rung(level: GroundingLevel) -> int:
    return _RUNGS[level]


def _refusal_cases() -> list[dict[str, Any]]:
    """Graphs where the top-scoring suspect cannot be connected to the symptom.

    Built by severing the lineage the fixture depends on, so the signals stay
    exactly as strong as before and only the path disappears. The agent must name
    nothing and write nothing.
    """
    cases: list[dict[str, Any]] = []
    for scenario in MOCK_SCENARIOS:
        client = MockDataHubClient(scenario=scenario)
        incident = client.list_open_incidents()[0]
        # Cut every upstream edge. Every anomaly remains; no path survives.
        for node in client._graph.values():
            node["upstreams"] = []

        diagnosis = CauzonAgent(client=client).investigate(
            Incident(urn=incident["urn"], title=incident["title"], description=""),
            write_back=True,  # deliberately allowed, to prove nothing is written
        )
        cases.append(
            {
                "scenario": f"{scenario}/severed",
                "named_cause": diagnosis.root_cause.name if diagnosis.root_cause else None,
                "refused": diagnosis.root_cause is None,
                "grounding": diagnosis.grounding.value,
                "wrote_nothing": not client.writes,
            }
        )
    return cases


def _downgrade_cases() -> list[dict[str, Any]]:
    """Graphs with the lineage intact but no query history.

    This is the case the grounding ladder exists for, and the one every planted
    scenario is too generous to test: all of them retain the transform SQL, so an
    agent that always claimed PATH_AND_TRANSFORM would look perfectly honest. Strip
    the query history and the claim has to drop a rung.

    It is also the live catalog's normal condition — Socrata retains no query
    history at all — so this measures a real deployment, not a hypothetical.
    """
    cases: list[dict[str, Any]] = []
    for scenario in MOCK_SCENARIOS:
        client = MockDataHubClient(scenario=scenario)
        incident = client.list_open_incidents()[0]
        for node in client._graph.values():
            node["queries"] = []

        diagnosis = CauzonAgent(client=client).investigate(
            Incident(urn=incident["urn"], title=incident["title"], description=""),
            write_back=False,
        )
        cases.append(
            {
                "scenario": f"{scenario}/no-query-history",
                "named_cause": diagnosis.root_cause.name if diagnosis.root_cause else None,
                "localised": (
                    diagnosis.root_cause is not None
                    and diagnosis.root_cause.name == EXPECTED[scenario]
                ),
                "claimed_grounding": diagnosis.grounding.value,
                # The path still holds; only the transform is gone.
                "downgraded_correctly": diagnosis.grounding is GroundingLevel.PATH_ONLY,
                "transform_sql": (
                    diagnosis.proof_path.transform_sql if diagnosis.proof_path else None
                ),
            }
        )
    return cases


def main() -> None:
    runs = [_run(name) for name in MOCK_SCENARIOS]
    refusals = _refusal_cases()
    downgrades = _downgrade_cases()

    localised = sum(1 for r in runs if r["localised"])
    honest = sum(1 for r in runs if r["grounding_honest"])
    forbidden = sum(1 for r in runs if r["named_a_forbidden_asset"])
    refused = sum(1 for r in refusals if r["refused"])
    silent = sum(1 for r in refusals if r["wrote_nothing"])

    downgraded = sum(1 for d in downgrades if d["downgraded_correctly"])
    still_found = sum(1 for d in downgrades if d["localised"])

    summary = {
        "scenarios": len(runs),
        "localisation": f"{localised}/{len(runs)}",
        "grounding_honesty": f"{honest}/{len(runs)}",
        "false_causes": forbidden,
        "refusal_on_ungroundable": f"{refused}/{len(refusals)}",
        "wrote_nothing_when_ungrounded": f"{silent}/{len(refusals)}",
        "downgrades_without_query_history": f"{downgraded}/{len(downgrades)}",
        "still_localises_without_query_history": f"{still_found}/{len(downgrades)}",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "note": (
                    "Generated by scripts/evaluate.py. Ground truth is declared in "
                    "that script and in the fixtures, not taken from the agent's "
                    "output. CI regenerates this and fails on drift."
                ),
                "summary": summary,
                "runs": runs,
                "refusals": refusals,
                "downgrades": downgrades,
            },
            indent=2,
        )
        + "\n"
    )

    print(f"wrote {OUT.relative_to(ROOT)}\n")
    for key, value in summary.items():
        print(f"  {key:32} {value}")

    failures = [
        f"localisation {summary['localisation']}" if localised != len(runs) else "",
        f"grounding overclaimed in {len(runs) - honest}" if honest != len(runs) else "",
        f"{forbidden} forbidden asset(s) named" if forbidden else "",
        f"refusal {summary['refusal_on_ungroundable']}" if refused != len(refusals) else "",
        "wrote when ungrounded" if silent != len(refusals) else "",
        (
            f"overclaimed the rung without query history in "
            f"{len(downgrades) - downgraded}"
            if downgraded != len(downgrades)
            else ""
        ),
        (
            f"lost the cause without query history in "
            f"{len(downgrades) - still_found}"
            if still_found != len(downgrades)
            else ""
        ),
    ]
    failures = [f for f in failures if f]
    if failures:
        print("\nFAILED: " + "; ".join(failures))
        raise SystemExit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
