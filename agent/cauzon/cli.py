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
        choices=["freshness", "schema_change"],
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
        print(f"✅ GROUNDED ROOT CAUSE: {diagnosis.root_cause.name}")
        print(f"   Confidence: {diagnosis.confidence:.0%}")
        if diagnosis.proof_path:
            path = " -> ".join(
                n.split(",")[1] if "," in n else n for n in diagnosis.proof_path.nodes
            )
            print(f"   Proof path: {path}")
        print(f"\n   Recommended fix: {diagnosis.recommended_fix}")
    else:
        print("⚠️  No grounded root cause — escalating to a human.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
