"""Ingest a controlled lineage graph with a planted fault into a live DataHub.

This gives Cauzon a real, multi-hop lineage graph to investigate end-to-end
against a running `datahub docker quickstart`, so the write-back can be
demonstrated for real.

Topology (upstream -> downstream), mirroring the mock "freshness" scenario:

    raw_trips  ->  trips_cleaned  ->  daily_revenue  ->  revenue_dashboard

The planted fault lives in `raw_trips` (ingestion stalled). We record the
freshness/volume signals as custom properties so Cauzon's ranker can read them
via get_entity, and we attach the transform SQL to each lineage edge so the
proof path carries real transform text.

Usage:
    export DATAHUB_GMS_URL=http://localhost:8080
    export DATAHUB_TOKEN=<personal access token>
    python scripts/ingest_demo_lineage.py
"""

from __future__ import annotations

import os

from datahub.sdk import DataHubClient, Dataset


PLATFORM_BY_NODE = {
    "raw_trips": "s3",
    "trips_cleaned": "snowflake",
    "daily_revenue": "snowflake",
    "revenue_dashboard": "looker",
}

# name -> (custom_properties signalling the fault, schema fields)
NODES = {
    "raw_trips": {
        "props": {
            "freshness_hours": "51",
            "expected_freshness_hours": "24",
            "row_count_delta_pct": "-100.0",
            "schema_changed_recently": "false",
        },
        "schema": {"trip_id": "string", "pickup_ts": "time", "fare_amount": "double"},
    },
    "trips_cleaned": {
        "props": {
            "freshness_hours": "50",
            "expected_freshness_hours": "24",
            "row_count_delta_pct": "-3.0",
            "schema_changed_recently": "false",
        },
        "schema": {"trip_id": "string", "trip_date": "date", "fare_amount": "double"},
    },
    "daily_revenue": {
        "props": {
            "freshness_hours": "49",
            "expected_freshness_hours": "24",
            "row_count_delta_pct": "-40.0",
            "schema_changed_recently": "false",
        },
        "schema": {"trip_date": "date", "revenue": "double"},
    },
    "revenue_dashboard": {
        "props": {
            "freshness_hours": "48",
            "expected_freshness_hours": "24",
            "row_count_delta_pct": "-40.0",
            "schema_changed_recently": "false",
        },
        "schema": {"trip_date": "date", "revenue": "double"},
    },
}

EDGES = [
    # (upstream, downstream, transform SQL)
    (
        "raw_trips",
        "trips_cleaned",
        "CREATE OR REPLACE TABLE trips_cleaned AS "
        "SELECT * FROM raw_trips WHERE fare_amount > 0",
    ),
    (
        "trips_cleaned",
        "daily_revenue",
        "CREATE OR REPLACE TABLE daily_revenue AS "
        "SELECT trip_date, SUM(fare_amount) AS revenue FROM trips_cleaned GROUP BY trip_date",
    ),
    (
        "daily_revenue",
        "revenue_dashboard",
        "SELECT trip_date, revenue FROM daily_revenue ORDER BY trip_date",
    ),
]


def urn_for(client: DataHubClient, name: str) -> str:
    from datahub.metadata.urns import DatasetUrn

    return str(DatasetUrn(platform=PLATFORM_BY_NODE[name], name=f"nyc.{name}", env="PROD"))


def main() -> int:
    server = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.getenv("DATAHUB_TOKEN", "")
    client = DataHubClient(server=server, token=token or None)

    print(f"Ingesting demo lineage into {server} ...")

    # 1) upsert the datasets with schema + fault-signalling custom properties
    for name, spec in NODES.items():
        ds = Dataset(
            platform=PLATFORM_BY_NODE[name],
            name=f"nyc.{name}",
            env="PROD",
            description=f"Demo dataset '{name}' for Cauzon RCA.",
            custom_properties=spec["props"],
            schema=list(spec["schema"].items()),
        )
        client.entities.upsert(ds)
        print(f"  upserted dataset: {name}")

    # 2) wire lineage edges, attaching the transform SQL to each
    for up, down, sql in EDGES:
        client.lineage.add_dataset_transform_lineage(
            upstream=urn_for(client, up),
            downstream=urn_for(client, down),
            transformation_text=sql,
        )
        print(f"  lineage: {up} -> {down}  (transform attached)")

    symptom = urn_for(client, "daily_revenue")
    print("\nDone. Symptom asset to investigate:")
    print("  ", symptom)
    print("\nNext:")
    print("  export CAUZON_DATAHUB_BACKEND=mcp")
    print("  python scripts/run_live_writeback.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
