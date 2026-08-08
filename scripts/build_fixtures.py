"""Regenerate the frontend's replay fixtures from real agent output.

The deployed demo replays these in the browser so a judge can run a full
investigation with no backend. They must therefore be genuine agent output, not
hand-authored JSON — run this after any change to the agent, its scenarios, or
the serialised shapes.

    PYTHONPATH=agent python scripts/build_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from cauzon.agent import CauzonAgent  # noqa: E402
from cauzon.datahub_client import MockDataHubClient  # noqa: E402
from cauzon.models import Incident  # noqa: E402

# Every planted scenario, read from the registry rather than restated here — a
# hand-kept list means a new scenario is served by the API but missing from the
# replay, so the offline fallback silently covers less than the queue offers.
from cauzon.datahub_client import MOCK_SCENARIOS  # noqa: E402

SCENARIOS = list(MOCK_SCENARIOS)
OUT = ROOT / "frontend" / "lib" / "fixtures.json"

_INCIDENT_FIELDS = ["urn", "title", "description", "failed_assertion", "detected_at"]


def build() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for scenario in SCENARIOS:
        client = MockDataHubClient(scenario=scenario)
        agent = CauzonAgent(client=client)
        raw = client.list_open_incidents()[0]
        incident = Incident(**{k: raw.get(k) for k in _INCIDENT_FIELDS})

        trace: list[dict] = []
        diagnosis = agent.investigate(
            incident, on_event=lambda ev: trace.append(ev.to_dict()), write_back=True
        )
        result = diagnosis.to_dict()
        result["trace"] = trace
        result["write_backs"] = client.writes
        out[scenario] = {"incident": raw, "result": result}
    return out


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    for scenario, payload in data.items():
        r = payload["result"]
        rejected = [c for c in r["ranked_candidates"] if c["rejected_reason"]]
        print(
            f"  {scenario:14} cause={r['root_cause']['name']:16} "
            f"grounding={r['grounding']:19} "
            f"trace={len(r['trace'])} rejected={len(rejected)} "
            f"writes={len(r['write_backs'])}"
        )


if __name__ == "__main__":
    main()
