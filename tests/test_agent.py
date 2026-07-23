"""Deterministic tests for the Cauzon agent against the mock (planted-fault) graph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from cauzon.agent import CauzonAgent, investigate_first_open_incident
from cauzon.datahub_client import MockDataHubClient
from cauzon.models import Signal


def test_finds_true_upstream_origin_not_intermediate():
    """The fault is planted in raw_trips; the symptom is daily_revenue.
    Cauzon must blame the ORIGIN (raw_trips), not the visible/intermediate node.
    """
    diag = investigate_first_open_incident(write_back=False)
    assert diag.root_cause is not None
    assert diag.root_cause.name == "raw_trips"


def test_diagnosis_is_grounded_with_verifiable_path():
    diag = investigate_first_open_incident(write_back=False)
    assert diag.grounded is True
    assert diag.proof_path is not None
    assert diag.proof_path.verified is True
    # path must connect origin -> ... -> symptom
    names = [n.split(",")[1] for n in diag.proof_path.nodes]
    assert names[0].endswith("raw_trips")
    assert names[-1].endswith("daily_revenue")
    # the transform SQL that carried the fault must be captured
    assert diag.proof_path.transform_sql is not None


def test_freshness_signal_detected():
    diag = investigate_first_open_incident(write_back=False)
    assert Signal.FRESHNESS_LAG in diag.root_cause.signals


def test_writeback_persists_dossier_and_tags():
    client = MockDataHubClient()
    agent = CauzonAgent(client=client)
    incidents = client.list_open_incidents()
    from cauzon.models import Incident

    inc = Incident(**{k: incidents[0].get(k) for k in
                      ["urn", "title", "description", "failed_assertion", "detected_at"]})
    agent.investigate(inc, write_back=True)
    ops = {w["op"] for w in client.writes}
    assert "save_document" in ops
    assert "add_tags" in ops
    assert "update_description" in ops


def test_refuses_ungrounded_writeback_when_no_evidence():
    """If no candidate has signals, Cauzon must NOT write an ungrounded diagnosis."""
    client = MockDataHubClient()
    # wipe all anomaly signals so nothing is groundable
    for node in client._graph.values():
        node["freshness_hours"] = node["expected_freshness_hours"]
        node["row_count_delta_pct"] = 0.0
        node["schema_changed_recently"] = False
    agent = CauzonAgent(client=client)
    from cauzon.models import Incident

    inc = Incident(urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)",
                   title="test", description="")
    diag = agent.investigate(inc, write_back=True)
    assert diag.grounded is False
    assert not any(w["op"] == "save_document" for w in client.writes)


# --------------------------------------------------------------------------- #
# Schema-change scenario: a column rename upstream silently breaks a transform.
# --------------------------------------------------------------------------- #

def _investigate_scenario(scenario: str):
    from cauzon.models import Incident

    client = MockDataHubClient(scenario=scenario)
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    inc = Incident(**{k: raw.get(k) for k in
                      ["urn", "title", "description", "failed_assertion", "detected_at"]})
    return agent, client, agent.investigate(inc, write_back=True)


def test_schema_change_blames_the_renamed_source():
    """weekly_sales reports $0; the origin is raw_orders (column renamed)."""
    _agent, _client, diag = _investigate_scenario("schema_change")
    assert diag.root_cause is not None
    assert diag.root_cause.name == "raw_orders"
    assert Signal.SCHEMA_CHANGE in diag.root_cause.signals


def test_schema_change_is_grounded_with_transform_sql():
    _agent, _client, diag = _investigate_scenario("schema_change")
    assert diag.grounded is True
    assert diag.proof_path is not None
    # the captured transform SQL should be the one still selecting the old column
    assert diag.proof_path.transform_sql is not None
    assert "amount AS revenue" in diag.proof_path.transform_sql


def test_schema_change_evidence_names_the_rename():
    _agent, _client, diag = _investigate_scenario("schema_change")
    joined = " ".join(diag.root_cause.evidence_notes).lower()
    assert "renamed" in joined


def test_scenarios_are_isolated():
    """Selecting a scenario must not leak state into the default one."""
    from cauzon.datahub_client import MockDataHubClient as C

    assert C(scenario="freshness")._symptom_urn.endswith("daily_revenue,PROD)")
    assert C(scenario="schema_change")._symptom_urn.endswith("weekly_sales,PROD)")
    # unknown scenario falls back to freshness
    assert C(scenario="nonsense").scenario == "freshness"
