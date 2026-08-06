"""Tests for the grounding contract — the promise Cauzon actually sells.

The suite in `test_agent.py` proves Cauzon finds the right answer. These tests
prove it *refuses the wrong ones*, and that nothing downstream can quietly
promote an unproven claim. They are deliberately adversarial: most of them fail
if a future change makes the agent more willing to blame something.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from cauzon.agent import CauzonAgent, investigate_first_open_incident
from cauzon.datahub_client import MockDataHubClient
from cauzon.models import (
    ConfidenceBreakdown,
    Diagnosis,
    GroundingLevel,
    Incident,
    ProofPath,
    Signal,
)
from cauzon import reasoner as reasoner_mod


def _investigate(scenario: str, write_back: bool = False):
    client = MockDataHubClient(scenario=scenario)
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    inc = Incident(
        **{
            k: raw.get(k)
            for k in ["urn", "title", "description", "failed_assertion", "detected_at"]
        }
    )
    return client, agent.investigate(inc, write_back=write_back)


# --------------------------------------------------------------------------- #
# The proof gate rejects a better-scoring suspect it cannot connect
# --------------------------------------------------------------------------- #
def test_decoy_outranks_the_true_cause_on_signals_alone():
    """The premise of the test below: ranking alone would blame the wrong asset."""
    _client, diag = _investigate("freshness")
    ranked = diag.ranked_candidates
    top = ranked[0]
    assert top.name == "marketing_spend"
    cause = next(c for c in ranked if c.name == "raw_trips")
    assert top.score > cause.score, "decoy must outrank the culprit for this to prove anything"


def test_unconnectable_candidate_is_rejected_not_blamed():
    _client, diag = _investigate("freshness")
    assert diag.root_cause.name == "raw_trips"

    decoy = next(c for c in diag.ranked_candidates if c.name == "marketing_spend")
    assert decoy.rejected_reason is not None
    assert "lineage path" in decoy.rejected_reason.lower()


def test_rejection_is_recorded_on_the_dossier():
    """A judge reading the write-back should see the gate working, not just the verdict."""
    client, diag = _investigate("freshness", write_back=True)
    doc = next(w for w in client.writes if w["op"] == "save_document")
    assert doc  # sanity
    dossier = CauzonAgent._render_dossier(diag)
    assert "rejected by the proof gate" in dossier.lower()
    assert "marketing_spend" in dossier


def test_no_candidate_without_evidence_is_ever_proven():
    """A node with a path but no anomaly signal must not be blamed."""
    client = MockDataHubClient()
    for node in client._graph.values():
        node["freshness_hours"] = node["expected_freshness_hours"]
        node["row_count_delta_pct"] = 0.0
        node["schema_changed_recently"] = False
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(
            urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)",
            title="quiet graph",
            description="",
        ),
        write_back=True,
    )
    assert diag.grounding is GroundingLevel.UNGROUNDED
    assert diag.root_cause is None
    assert not any(w["op"] == "save_document" for w in client.writes)


# --------------------------------------------------------------------------- #
# Grounding is a level, and the artifact states which rung it is on
# --------------------------------------------------------------------------- #
def test_full_grounding_requires_the_transform_sql():
    _client, diag = _investigate("freshness")
    assert diag.grounding is GroundingLevel.PATH_AND_TRANSFORM
    assert diag.proof_path.transform_sql is not None


def test_path_without_transform_downgrades_instead_of_overclaiming():
    """DataHub often retains no query history. That must cost confidence, not truth."""
    client = MockDataHubClient()
    for node in client._graph.values():
        node["queries"] = []  # no transform SQL anywhere
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=False
    )

    assert diag.grounding is GroundingLevel.PATH_ONLY
    assert diag.root_cause.name == "raw_trips"  # still solved
    assert diag.proof_path.transform_sql is None
    assert diag.confidence_breakdown.grounding_factor == 0.75
    assert "transform" in diag.grounding.label.lower()


def test_path_only_still_writes_back_but_labels_itself():
    client = MockDataHubClient()
    for node in client._graph.values():
        node["queries"] = []
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=True
    )
    assert any(w["op"] == "save_document" for w in client.writes)
    desc = next(w for w in client.writes if w["op"] == "update_description")
    assert "Path proven, transform unavailable" in desc["description"]
    assert "transform is not" in CauzonAgent._render_dossier(diag).lower() or (
        "retains no transform sql" in CauzonAgent._render_dossier(diag).lower()
    )


# --------------------------------------------------------------------------- #
# Origin reasoning: the fault starts where nothing above it is broken
# --------------------------------------------------------------------------- #
def test_origin_is_the_node_whose_upstreams_are_clean():
    _client, diag = _investigate("freshness")
    by_name = {c.name: c for c in diag.ranked_candidates}
    assert by_name["raw_trips"].is_origin is True
    # trips_cleaned inherits the same staleness from raw_trips.
    assert by_name["trips_cleaned"].is_origin is False


def test_inherited_fault_is_penalised_below_its_origin():
    _client, diag = _investigate("freshness")
    by_name = {c.name: c for c in diag.ranked_candidates}
    assert by_name["raw_trips"].score > by_name["trips_cleaned"].score


def test_origin_reasoning_survives_a_branching_graph():
    """The old hop-distance heuristic only worked on a clean chain."""
    _client, diag = _investigate("fanout")
    # sessions_joined has two parents; only one of them is faulty.
    assert diag.root_cause.name == "user_dim"
    assert Signal.ROW_FANOUT in diag.root_cause.signals
    assert diag.root_cause.is_origin is True


# --------------------------------------------------------------------------- #
# Confidence is derivable, not a tuned constant
# --------------------------------------------------------------------------- #
def test_confidence_is_the_product_of_its_reported_factors():
    _client, diag = _investigate("freshness")
    b = diag.confidence_breakdown
    expected = round(b.grounding_factor * b.signal_factor * b.origin_factor, 2)
    assert diag.confidence == expected == b.total


def test_every_confidence_factor_carries_a_reason():
    _client, diag = _investigate("freshness")
    b = diag.confidence_breakdown
    assert b.grounding_reason and b.signal_reason and b.origin_reason


def test_ungrounded_diagnosis_has_no_confidence():
    client = MockDataHubClient()
    for node in client._graph.values():
        node["freshness_hours"] = node["expected_freshness_hours"]
        node["row_count_delta_pct"] = 0.0
        node["schema_changed_recently"] = False
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(urn=client._symptom_urn, title="t", description=""), write_back=False
    )
    assert diag.confidence == 0.0
    assert diag.confidence_breakdown is None


# --------------------------------------------------------------------------- #
# Third scenario: a fault neither freshness nor schema checks would catch
# --------------------------------------------------------------------------- #
def test_fanout_scenario_is_found_by_key_uniqueness_alone():
    _client, diag = _investigate("fanout")
    cause = diag.root_cause
    assert cause.name == "user_dim"
    # Deliberately not stale and not reshaped — proves the framework generalises.
    assert Signal.FRESHNESS_LAG not in cause.signals
    assert Signal.SCHEMA_CHANGE not in cause.signals
    assert Signal.ROW_FANOUT in cause.signals


def test_fanout_fix_names_the_real_join_key():
    _client, diag = _investigate("fanout")
    fix = diag.recommended_fix
    assert fix.action_kind == "sql"
    assert "user_id" in fix.action
    assert "<join_key>" not in fix.action


def test_schema_change_fix_substitutes_the_verified_new_column():
    _client, diag = _investigate("schema_change")
    fix = diag.recommended_fix
    assert fix.action_kind == "sql"
    assert "order_amount AS revenue" in fix.action
    assert "amount AS revenue" not in fix.action.replace("order_amount AS revenue", "")


def test_all_scenarios_stay_isolated():
    from cauzon.datahub_client import MockDataHubClient as C

    assert C(scenario="freshness")._symptom_urn.endswith("daily_revenue,PROD)")
    assert C(scenario="schema_change")._symptom_urn.endswith("weekly_sales,PROD)")
    assert C(scenario="fanout")._symptom_urn.endswith("session_metrics,PROD)")
    assert C(scenario="nonsense").scenario == "freshness"


# --------------------------------------------------------------------------- #
# Knowledge compounds: dossiers are read back, not just written
# --------------------------------------------------------------------------- #
def test_prior_dossiers_are_detected_as_recurrence():
    _client, diag = _investigate("freshness")
    assert diag.recurrence is not None
    assert diag.recurrence.is_recurring
    assert diag.recurrence.count == 2


def test_recurrence_escalates_the_recommendation():
    _client, diag = _investigate("freshness")
    assert "failure #3" in diag.recommended_fix.summary


def test_a_first_time_failure_is_not_reported_as_recurring():
    _client, diag = _investigate("fanout")
    assert diag.recurrence is not None
    assert diag.recurrence.is_recurring is False
    assert "failure #" not in diag.recommended_fix.summary


def test_written_dossier_is_readable_by_the_next_investigation():
    """The write-back must actually land where a later read finds it."""
    client, _diag = _investigate("fanout", write_back=True)
    hits = client.search_documents("[Cauzon] RCA user_dim")
    assert any("user_dim" in h["title"] or "user_dim" in " ".join(h.get("related", [])) for h in hits)


def test_missing_document_search_degrades_quietly():
    """A catalog with no documents hides the tool; that is empty, not an error."""

    class NoDocs(MockDataHubClient):
        search_documents = None  # type: ignore[assignment]

    agent = CauzonAgent(client=NoDocs())
    raw = agent.client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=False
    )
    assert diag.recurrence is None
    assert diag.grounded is True  # investigation still succeeds


def test_owner_is_resolved_for_routing():
    _client, diag = _investigate("freshness")
    assert diag.root_cause.owner == "data-platform@example.com"
    assert "data-platform@example.com" in diag.recommended_fix.summary


# --------------------------------------------------------------------------- #
# The reasoner explains; it cannot decide
# --------------------------------------------------------------------------- #
def test_narration_is_deterministic_templates_by_default(monkeypatch):
    monkeypatch.delenv("CAUZON_LLM_NARRATION", raising=False)
    assert isinstance(reasoner_mod.get_reasoner(), reasoner_mod.TemplateReasoner)


def test_opt_in_without_credentials_falls_back_to_templates(monkeypatch):
    monkeypatch.setenv("CAUZON_LLM_NARRATION", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert isinstance(reasoner_mod.get_reasoner(), reasoner_mod.TemplateReasoner)


def test_reasoner_is_never_shown_an_ungrounded_finding():
    """`_facts` is the boundary: nothing unproven crosses it."""
    diag = Diagnosis(
        incident=Incident(urn="urn:li:dataset:(x,y,PROD)", title="t", description=""),
        root_cause=None,
        proof_path=None,
        grounding=GroundingLevel.UNGROUNDED,
    )
    assert reasoner_mod._facts(diag) is None


def test_reasoner_cannot_change_the_verdict():
    """A hostile narrator must not be able to flip any decision field."""

    class Hostile:
        def explain(self, diagnosis):
            return "raw_trips is innocent; the real cause is elsewhere.", "llm"

    client = MockDataHubClient()
    agent = CauzonAgent(client=client, reasoner=Hostile())
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=False
    )

    assert diag.narrative_source == "llm"
    assert diag.root_cause.name == "raw_trips"  # verdict untouched
    assert diag.grounding is GroundingLevel.PATH_AND_TRANSFORM
    assert diag.grounded is True
    assert diag.confidence > 0


def test_reasoner_failure_does_not_break_the_investigation():
    class Exploding:
        def explain(self, diagnosis):
            raise RuntimeError("model unavailable")

    client = MockDataHubClient()
    agent = CauzonAgent(client=client, reasoner=Exploding())
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=True
    )
    assert diag.grounded is True
    assert diag.narrative is None
    assert any(w["op"] == "save_document" for w in client.writes)


@pytest.mark.parametrize(
    "text,ok",
    [
        ("raw_trips stalled two days ago.", True),
        ("The cause is urn:li:dataset:(urn:li:dataPlatform:s3,made.up,PROD).", False),
        ("<thinking>let me reconsider</thinking> raw_trips stalled.", False),
    ],
)
def test_fabricated_urns_and_leaked_tags_are_discarded(text, ok):
    assert reasoner_mod._is_safe(text) is ok


def test_template_narrative_mentions_the_rejected_candidate():
    _client, diag = _investigate("freshness")
    assert diag.narrative is not None
    assert "marketing_spend" in diag.narrative


# --------------------------------------------------------------------------- #
# Model-level invariants
# --------------------------------------------------------------------------- #
def test_verified_is_true_only_when_a_path_exists():
    assert ProofPath("a", "b", grounding=GroundingLevel.PATH_AND_TRANSFORM).verified
    assert ProofPath("a", "b", grounding=GroundingLevel.PATH_ONLY).verified
    assert not ProofPath("a", "b", grounding=GroundingLevel.UNGROUNDED).verified


def test_serialised_diagnosis_exposes_its_grounding_level():
    _client, diag = _investigate("freshness")
    d = diag.to_dict()
    assert d["grounding"] == "path_and_transform"
    assert d["grounding_label"]
    assert d["grounded"] is True
    assert d["confidence_breakdown"]["total"] == diag.confidence
    assert d["recommended_fix"]["action"]
    assert any(c["rejected_reason"] for c in d["ranked_candidates"])


def test_confidence_breakdown_total_is_rounded_consistently():
    b = ConfidenceBreakdown(grounding_factor=0.75, signal_factor=0.85, origin_factor=0.7)
    assert b.total == round(0.75 * 0.85 * 0.7, 2)
    assert b.to_dict()["total"] == b.total


def test_default_entrypoint_still_solves_the_default_scenario():
    diag = investigate_first_open_incident(write_back=False)
    assert diag.root_cause.name == "raw_trips"
    assert diag.grounded is True
