"""Run Cauzon end-to-end against a LIVE DataHub, with write-back enabled.

Prereqs:
  1. `datahub docker quickstart` is running.
  2. `python scripts/ingest_demo_lineage.py` has planted the demo lineage graph.
  3. Env:
       export CAUZON_DATAHUB_BACKEND=mcp
       export DATAHUB_GMS_URL=http://localhost:8080
       export DATAHUB_TOKEN=<personal access token>

This investigates the planted `daily_revenue` incident against the real catalog
and writes the dossier + tags + description back into DataHub.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

os.environ.setdefault("CAUZON_DATAHUB_BACKEND", "mcp")

from cauzon.agent import CauzonAgent  # noqa: E402
from cauzon.models import Incident  # noqa: E402

SYMPTOM = "urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)"

_COLORS = {
    "detect": "\033[96m", "scope": "\033[94m", "hypothesize": "\033[95m",
    "prove": "\033[92m", "writeback": "\033[93m",
}
_RESET = "\033[0m"


def _printer(ev):
    print(f"{_COLORS.get(ev.phase, '')}[{ev.phase.upper():11}]{_RESET} {ev.message}")


def main() -> int:
    print("\n🔎 Cauzon — LIVE run against", os.getenv("DATAHUB_GMS_URL"), "\n")
    agent = CauzonAgent()  # uses MCPDataHubClient

    incident = Incident(
        urn=SYMPTOM,
        title="daily_revenue is 40% below expected volume",
        description="The revenue dashboard shows a sharp drop; a volume assertion failed.",
        failed_assertion="row_count within 10% of 7-day average",
        detected_at="live-demo",
    )

    diagnosis = agent.investigate(incident, on_event=_printer, write_back=True)

    print("\n" + "=" * 64)
    if diagnosis.grounded and diagnosis.root_cause:
        print(f"✅ GROUNDED ROOT CAUSE: {diagnosis.root_cause.name}")
        print(f"   Confidence: {diagnosis.confidence:.0%}")
        if diagnosis.proof_path:
            path = " -> ".join(
                n.split(",")[1] if "," in n else n for n in diagnosis.proof_path.nodes
            )
            print(f"   Proof path: {path}")
        print(f"   Fix: {diagnosis.recommended_fix}")
    else:
        print("⚠️  No grounded root cause — nothing written back.")
    print("=" * 64)

    writes = getattr(agent.client, "writes", [])
    print(f"\nWrite-backs to live DataHub ({len(writes)}):")
    for w in writes:
        if w["op"] == "save_document":
            print(f"   📄 save_document -> {w['urn']}")
        elif w["op"] == "add_tags":
            print(f"   🏷️  add_tags {w['tags']} -> {w['urn'].split(',')[1]}")
        elif w["op"] == "update_description":
            print(f"   📝 update_description -> {w['urn'].split(',')[1]}")

    print("\nVerify in the UI: http://localhost:9002  (search 'raw_trips')")
    return 0 if diagnosis.grounded else 1


if __name__ == "__main__":
    raise SystemExit(main())
