"""Terminal entrypoint for Cauzon — great for the demo and CI.

Usage:
    python -m cauzon.cli                 # investigate the first open incident
    python -m cauzon.cli --no-writeback  # dry run, don't mutate the catalog
"""

from __future__ import annotations

import argparse
import os

from .agent import investigate_first_open_incident
from .models import TraceEvent

_PHASE_COLORS = {
    "detect": "\033[96m",
    "scope": "\033[94m",
    "hypothesize": "\033[95m",
    "prove": "\033[92m",
    "writeback": "\033[93m",
}
_RESET = "\033[0m"


def _printer(ev: TraceEvent) -> None:
    color = _PHASE_COLORS.get(ev.phase, "")
    print(f"{color}[{ev.phase.upper():11}]{_RESET} {ev.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cauzon RCA agent for DataHub")
    parser.add_argument(
        "--no-writeback",
        action="store_true",
        help="Do not write the dossier / tags back to DataHub.",
    )
    parser.add_argument(
        "--scenario",
        choices=["freshness", "schema_change", "fanout"],
        help="Mock scenario to investigate (sets CAUZON_MOCK_SCENARIO).",
    )
    args = parser.parse_args()

    if args.scenario:
        os.environ["CAUZON_MOCK_SCENARIO"] = args.scenario

    print("\n🔍 Cauzon — path-grounded root-cause analysis\n")
    diagnosis = investigate_first_open_incident(
        on_event=_printer, write_back=not args.no_writeback
    )

    print("\n" + "=" * 60)
    if diagnosis.grounded and diagnosis.root_cause:
        cause = diagnosis.root_cause
        print(f"✅ ROOT CAUSE: {cause.name}   [{diagnosis.grounding.label}]")
        print(f"   Confidence: {diagnosis.confidence:.0%}")
        if diagnosis.confidence_breakdown:
            b = diagnosis.confidence_breakdown
            print(
                f"     = grounding ×{b.grounding_factor}"
                f" · signals ×{b.signal_factor}"
                f" · origin ×{b.origin_factor}"
            )
        if cause.owner:
            print(f"   Owner: {cause.owner}")
        if diagnosis.proof_path:
            path = " -> ".join(
                n.split(",")[1] if "," in n else n for n in diagnosis.proof_path.nodes
            )
            print(f"   Proof path: {path}")

        rejected = [c for c in diagnosis.ranked_candidates if c.rejected_reason]
        for c in rejected:
            print(f"   Rejected by proof gate: {c.name} (score {c.score})")

        if diagnosis.recurrence and diagnosis.recurrence.is_recurring:
            print(f"   Recurrence: {diagnosis.recurrence.count} prior dossier(s)")

        if diagnosis.proof_path and diagnosis.proof_path.column_path:
            cp = diagnosis.proof_path.column_path
            print(f"   Column path: {' -> '.join(cp.fields)}")

        blast = diagnosis.blast_radius
        if blast and blast.count:
            if blast.unknown and not blast.silent:
                tail = "alerting status unavailable on this backend"
            else:
                tail = f"{len(blast.silent)} not alerting"
            print(f"   Blast radius: {blast.count} downstream, {tail}")
            for asset in blast.impacted:
                if asset.alerting is False:
                    flag = "  <- nobody watching"
                elif asset.alerting is None:
                    flag = "  <- alerting status unknown"
                else:
                    flag = "  <- alerting"
                print(f"     - {asset.name} ({asset.kind}){flag}")

        if diagnosis.timeline:
            print("\n   How it propagated:")
            for e in diagnosis.timeline:
                print(f"     {e.at:22} {e.asset_name:22} {e.label}")

        proposal = diagnosis.proposed_assertion
        if proposal:
            print(
                f"\n   Missing guardrail: no {proposal.kind} assertion on "
                f"`{proposal.target_name}`"
            )
            if proposal.lead_time:
                print(f"     Would have fired {proposal.lead_time}")

        fix = diagnosis.recommended_fix
        if fix:
            print(f"\n   Recommended fix: {fix.summary}")
            if fix.action:
                print("   ---")
                for line in fix.action.splitlines():
                    print(f"   {line}")
    else:
        print("⚠️  No grounded root cause — escalating to a human.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
