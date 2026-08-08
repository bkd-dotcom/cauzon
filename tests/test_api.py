"""Tests for the HTTP/WebSocket layer.

The agent had good coverage and the API had none, which is how the incident
queue ended up serving one scenario while the UI expected three. These tests
cover the transport contract the frontend actually depends on.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT))

fastapi = pytest.importorskip("fastapi", reason="API extras not installed")
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)

FRESHNESS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)"
SCHEMA_CHANGE = "urn:li:dataset:(urn:li:dataPlatform:snowflake,shop.weekly_sales,PROD)"
FANOUT = "urn:li:dataset:(urn:li:dataPlatform:snowflake,app.session_metrics,PROD)"


def test_health_reports_what_this_deployment_actually_is():
    """The UI states these fields verbatim, so they are part of the contract."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["datahub_backend"] == "mock"
    # The mock catalog is in-memory, so there is nothing to protect.
    assert body["write_back_allowed"] is True
    assert body["datahub_ui_url"] is None


def test_datahub_ui_url_is_normalised(monkeypatch):
    monkeypatch.setenv("CAUZON_DATAHUB_UI_URL", "https://datahub.example.com/")
    assert (
        client.get("/api/health").json()["datahub_ui_url"]
        == "https://datahub.example.com"
    )


def test_a_real_catalog_is_read_only_unless_explicitly_permitted(monkeypatch):
    """A public deployment must not let visitors mutate someone's metadata."""
    monkeypatch.setenv("CAUZON_DATAHUB_BACKEND", "mcp")
    monkeypatch.delenv("CAUZON_ALLOW_WRITEBACK", raising=False)
    assert client.get("/api/health").json()["write_back_allowed"] is False

    monkeypatch.setenv("CAUZON_ALLOW_WRITEBACK", "1")
    assert client.get("/api/health").json()["write_back_allowed"] is True


def test_client_cannot_grant_itself_writeback_the_deployment_withheld(monkeypatch):
    """write_back=true in the request must not override the server's policy."""
    import backend.main as main

    monkeypatch.setattr(main, "_writeback_allowed", lambda: False)
    body = client.post(
        "/api/investigate",
        json={"urn": FRESHNESS, "title": "t", "write_back": True},
    ).json()
    assert body["grounded"] is True  # still investigates
    assert body["write_backs"] == []  # but wrote nothing


def test_incident_queue_exposes_every_scenario():
    """One incident per planted fault, so every one is reachable live.

    `shared_cause` contributes two: one graph, two teams alerting separately on the
    same outage, which is the case correlation exists to collapse.
    """
    from cauzon.datahub_client import all_mock_incidents

    incidents = client.get("/api/incidents").json()
    expected = {i["urn"] for i in all_mock_incidents()}

    assert {i["urn"] for i in incidents} == expected
    # Two scenarios share the shared_cause graph, so the queue must not repeat an
    # asset that alerts in both.
    assert len(incidents) == len({i["urn"] for i in incidents})
    assert {FRESHNESS, SCHEMA_CHANGE, FANOUT} <= expected
    for incident in incidents:
        assert incident["title"]


@pytest.mark.parametrize(
    "urn,expected_cause",
    [(FRESHNESS, "raw_trips"), (SCHEMA_CHANGE, "raw_orders"), (FANOUT, "user_dim")],
)
def test_each_incident_routes_to_its_own_scenario(urn, expected_cause):
    """A request must be investigated against the graph that owns its symptom."""
    body = client.post(
        "/api/investigate", json={"urn": urn, "title": "t", "write_back": False}
    ).json()
    assert body["root_cause"]["name"] == expected_cause
    assert body["grounded"] is True


def test_investigate_returns_the_full_contract_the_ui_renders():
    body = client.post(
        "/api/investigate", json={"urn": FRESHNESS, "title": "t", "write_back": True}
    ).json()

    for key in (
        "incident",
        "root_cause",
        "proof_path",
        "ranked_candidates",
        "recommended_fix",
        "confidence",
        "confidence_breakdown",
        "grounding",
        "grounding_label",
        "grounded",
        "recurrence",
        "narrative",
        "narrative_source",
        "trace",
        "write_backs",
    ):
        assert key in body, f"missing {key}"

    assert body["grounding"] == "path_and_transform"
    assert body["confidence"] == body["confidence_breakdown"]["total"]
    assert body["proof_path"]["causal_edge_index"] is not None
    assert body["recommended_fix"]["action"]
    assert {w["op"] for w in body["write_backs"]} == {
        "save_document",
        "add_tags",
        "update_description",
    }


def test_rejected_candidate_survives_serialisation():
    """The UI's rejected-by-the-gate panel depends on this field."""
    body = client.post(
        "/api/investigate", json={"urn": FRESHNESS, "title": "t", "write_back": False}
    ).json()
    rejected = [c for c in body["ranked_candidates"] if c["rejected_reason"]]
    assert [c["name"] for c in rejected] == ["marketing_spend"]
    assert rejected[0]["score"] > body["root_cause"]["score"]


def test_no_writeback_when_write_back_is_false():
    body = client.post(
        "/api/investigate", json={"urn": FRESHNESS, "title": "t", "write_back": False}
    ).json()
    assert body["write_backs"] == []


def test_requests_do_not_leak_write_backs_into_each_other():
    """A fresh client per request; otherwise write-backs accumulate across runs."""
    first = client.post(
        "/api/investigate", json={"urn": FRESHNESS, "title": "t", "write_back": True}
    ).json()
    second = client.post(
        "/api/investigate", json={"urn": FRESHNESS, "title": "t", "write_back": True}
    ).json()
    assert len(first["write_backs"]) == len(second["write_backs"]) == 3


def test_websocket_streams_the_trace_then_the_diagnosis():
    with client.websocket_connect("/ws/investigate") as ws:
        ws.send_json({"urn": FRESHNESS, "title": "t", "write_back": True})

        phases, diagnosis = [], None
        for _ in range(40):
            message = ws.receive_json()
            if message["type"] == "trace":
                phases.append(message["event"]["phase"])
            elif message["type"] == "diagnosis":
                diagnosis = message["diagnosis"]
                break

    assert phases[0] == "detect"
    assert "prove" in phases
    assert "writeback" in phases
    assert diagnosis is not None
    assert diagnosis["root_cause"]["name"] == "raw_trips"
    assert diagnosis["write_backs"]


def test_websocket_investigates_the_scenario_it_was_sent():
    with client.websocket_connect("/ws/investigate") as ws:
        ws.send_json({"urn": FANOUT, "title": "t", "write_back": False})
        diagnosis = None
        for _ in range(40):
            message = ws.receive_json()
            if message["type"] == "diagnosis":
                diagnosis = message["diagnosis"]
                break
    assert diagnosis is not None
    assert diagnosis["root_cause"]["name"] == "user_dim"
