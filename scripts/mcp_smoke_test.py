"""Live MCP smoke-test for Cauzon against a real DataHub instance.

This is NOT part of the unit test suite (it needs a running DataHub). Run it
manually once `datahub docker quickstart` is up and a datapack is loaded:

    datahub docker quickstart
    datahub init --username datahub --password datahub
    datahub datapack load showcase-ecommerce

    # create a personal access token in the UI (Settings -> Access Tokens),
    # or reuse the quickstart session token, then:
    export CAUZON_DATAHUB_BACKEND=mcp
    export DATAHUB_GMS_URL=http://localhost:8080
    export DATAHUB_TOKEN=<token>
    python scripts/mcp_smoke_test.py

It exercises each MCP-backed method the agent relies on and prints what came
back, so you can confirm the real wiring end-to-end before recording the demo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

os.environ.setdefault("CAUZON_DATAHUB_BACKEND", "mcp")

from cauzon.datahub_client import MCPDataHubClient  # noqa: E402


def main() -> int:
    print("Connecting to DataHub at", os.getenv("DATAHUB_GMS_URL", "http://localhost:8080"))
    client = MCPDataHubClient()

    print("\n[1] search — sample dataset entities")
    hits = client.search("snowflake")
    datasets = [h for h in hits if "dataset" in h["urn"]]
    if not datasets:
        datasets = [h for h in client.search("*") if "dataset" in h["urn"]]
    for h in datasets[:5]:
        print("   ", h["urn"])
    if not datasets:
        print("   (no datasets — is a datapack loaded and indexed?)")
        return 1

    sample_urn = datasets[0]["urn"]
    print(f"\n[2] get_entity({sample_urn})")
    ent = client.get_entity(sample_urn)
    print("    name:", ent.get("name"))
    print("    freshness_hours:", ent.get("freshness_hours"))

    print(f"\n[3] get_lineage(upstream) of {sample_urn}")
    up = client.get_lineage(sample_urn, direction="upstream", hops=3)
    for n in up[:5]:
        print(f"    {n['hops']} hop(s): {n['urn']}")

    print(f"\n[4] list_schema_fields({sample_urn})")
    fields = client.list_schema_fields(sample_urn)
    for f in fields[:8]:
        print(f"    {f['name']}: {f['type']}")

    print(f"\n[5] get_dataset_queries({sample_urn})")
    qs = client.get_dataset_queries(sample_urn)
    for q in qs[:2]:
        print("    ", (q.get("query") or "")[:120])

    if up:
        target = up[-1]["urn"]
        print(f"\n[6] get_lineage_paths_between({sample_urn} <- {target})")
        paths = client.get_lineage_paths_between(sample_urn, target)
        for p in paths[:1]:
            print("    nodes:", " -> ".join(n.split(",")[1] if "," in n else n for n in p["nodes"]))

    print("\n[7] list_open_incidents() — datasets with FAILING assertions")
    incs = client.list_open_incidents()
    if incs:
        for i in incs[:3]:
            print("    ", i["title"])
    else:
        print("    (none failing — the showcase datapack may have all-passing assertions)")

    print("\n✅ MCP smoke test completed. Read paths above to confirm shapes.")
    print("   To exercise write-back, run the agent with CAUZON_DATAHUB_BACKEND=mcp")
    print("   against an incident and ensure the MCP server has")
    print("   TOOLS_IS_MUTATION_ENABLED=true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
