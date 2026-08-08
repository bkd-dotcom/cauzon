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


# --------------------------------------------------------------------------- #
# Blast radius — the other direction
# --------------------------------------------------------------------------- #
def test_blast_radius_finds_downstream_assets_nobody_is_watching():
    """The asset that alerted is rarely the only one that is wrong."""
    _client, diag = _investigate("freshness")
    blast = diag.blast_radius
    assert blast is not None
    names = {a.name for a in blast.impacted}
    assert names == {"revenue_dashboard", "exec_weekly_summary", "driver_payouts"}
    # None of them has its own assertion, which is precisely the danger.
    assert len(blast.silent) == blast.count == 3


def test_alerting_status_is_derived_from_the_open_incident_list():
    """The one asset that is alerting is the symptom's own sibling, not a guess.

    `daily_revenue` has an open incident in this fixture, and the mock's downstream
    assets do not, so the queue is the source of that fact.
    """
    client, diag = _investigate("freshness")
    open_urns = {i["urn"] for i in client.list_open_incidents()}
    for asset in diag.blast_radius.impacted:
        assert asset.alerting is (asset.urn in open_urns)


def test_undeterminable_alerting_status_is_unknown_not_silent():
    """A catalog that cannot report alerting must not be read as reporting silence.

    This is the regression that matters most in the project. `alerting` used to
    default to False, so every backend without the mock's `has_open_incident` key
    recorded its whole blast radius as "wrong and nobody is looking" — an unchecked
    negative, filed into the catalog, by a tool whose entire claim is that it never
    states what it cannot prove.
    """

    class Unreportable(MockDataHubClient):
        def list_open_incidents(self):
            raise RuntimeError("this catalog exposes no incident API")

    client = Unreportable()
    symptom = next(
        urn for urn, n in client._graph.items() if n["name"] == "daily_revenue"
    )
    diag = CauzonAgent(client=client).investigate(
        Incident(urn=symptom, title="volume drop", description=""), write_back=False
    )

    blast = diag.blast_radius
    assert blast.count == 3
    assert all(a.alerting is None for a in blast.impacted)
    # Unknown is not silence.
    assert blast.silent == []
    assert len(blast.unknown) == 3

    dossier = CauzonAgent._render_dossier(diag)
    assert "not alerting" not in dossier
    assert "nobody is currently looking" not in dossier
    assert "alerting status unavailable" in dossier


def test_partly_determinable_alerting_reports_both_counts_separately():
    """Some known-silent and some unknown must not be merged into one number.

    Rolling the undetermined assets into the silent count would restate the same
    unchecked negative in aggregate, which is the bug this whole change exists to
    remove.
    """

    class PartialReport(MockDataHubClient):
        def list_open_incidents(self):
            # Reports the queue, but this catalog only covers one platform, so the
            # Looker assets' status is genuinely not knowable from it.
            return [i for i in super().list_open_incidents() if "looker" not in i["urn"]]

    client = PartialReport()
    symptom = next(
        urn for urn, n in client._graph.items() if n["name"] == "daily_revenue"
    )
    diag = CauzonAgent(client=client).investigate(
        Incident(urn=symptom, title="volume drop", description=""), write_back=False
    )
    blast = diag.blast_radius

    # The queue answered, so nothing is unknown — every asset gets a real verdict.
    assert len(blast.unknown) == 0
    assert len(blast.silent) + len(blast.alerting) == blast.count
    dossier = CauzonAgent._render_dossier(diag)
    assert "alerting status unavailable" not in dossier


def test_blast_radius_distinguishes_dashboards_from_datasets():
    """A wrong dashboard matters more than a wrong intermediate table."""
    _client, diag = _investigate("freshness")
    kinds = {a.name: a.kind for a in diag.blast_radius.impacted}
    assert kinds["revenue_dashboard"] == "dashboard"
    assert kinds["driver_payouts"] == "dataset"


def test_blast_radius_does_not_include_the_symptom_or_upstreams():
    _client, diag = _investigate("freshness")
    urns = {a.urn for a in diag.blast_radius.impacted}
    assert diag.incident.urn not in urns
    assert diag.root_cause.urn not in urns


def test_empty_blast_radius_is_reported_not_omitted():
    """Looking and finding nothing is a different answer from not looking."""
    client = MockDataHubClient()
    agent = CauzonAgent(client=client)
    # Investigate the leaf: nothing consumes it.
    leaf = next(
        urn for urn, n in client._graph.items() if n["name"] == "driver_payouts"
    )
    diag = agent.investigate(
        Incident(urn=leaf, title="leaf", description=""), write_back=False
    )
    assert diag.blast_radius is not None
    assert diag.blast_radius.count == 0


def test_unreachable_downstream_lineage_degrades_to_none():
    class NoDownstream(MockDataHubClient):
        def get_lineage(self, urn, direction="upstream", hops=3):
            if direction == "downstream":
                raise RuntimeError("graph index unavailable")
            return super().get_lineage(urn, direction=direction, hops=hops)

    client = NoDownstream()
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=False
    )
    assert diag.blast_radius is None  # could not look
    assert diag.grounded is True  # investigation still succeeds


# --------------------------------------------------------------------------- #
# Column-level proof — a further rung on the same ladder
# --------------------------------------------------------------------------- #
def test_column_path_names_the_field_that_carried_the_fault():
    _client, diag = _investigate("schema_change")
    cp = diag.proof_path.column_path
    assert cp is not None
    assert cp.cause_field == "amount"
    assert cp.symptom_field == "revenue"
    assert len(cp.fields) == len(diag.proof_path.nodes)


def test_column_path_is_absent_rather_than_guessed():
    """No column lineage means the proof holds at table level and says so."""
    client = MockDataHubClient()
    for node in client._graph.values():
        node.pop("column_lineage", None)
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=False
    )
    assert diag.grounded is True
    assert diag.proof_path.column_path is None


def test_partial_column_lineage_yields_no_column_claim():
    """A gap anywhere in the chain must not produce a half-invented path."""
    client = MockDataHubClient()
    mid = next(u for u, n in client._graph.items() if n["name"] == "trips_cleaned")
    client._graph[mid].pop("column_lineage")
    agent = CauzonAgent(client=client)
    raw = client.list_open_incidents()[0]
    diag = agent.investigate(
        Incident(urn=raw["urn"], title=raw["title"], description=""), write_back=False
    )
    assert diag.proof_path.column_path is None


# --------------------------------------------------------------------------- #
# Assertion proposal — diagnosis that prevents the next occurrence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "scenario,kind,target",
    [
        ("freshness", "freshness", "raw_trips"),
        ("schema_change", "schema_contract", "raw_orders"),
        ("fanout", "uniqueness", "user_dim"),
    ],
)
def test_proposed_assertion_matches_the_fault_and_sits_on_the_origin(
    scenario, kind, target
):
    _client, diag = _investigate(scenario)
    proposal = diag.proposed_assertion
    assert proposal is not None
    assert proposal.kind == kind
    # On the origin, not on the asset that happened to alert.
    assert proposal.target_name == target
    assert proposal.target_urn == diag.root_cause.urn
    assert proposal.definition.strip()


def test_proposed_assertion_quantifies_the_lead_time_it_would_have_given():
    _client, diag = _investigate("freshness")
    # 51h actual against a 24h SLA — a check at the source fires 27h earlier.
    assert diag.proposed_assertion.lead_time == "~27h earlier than the downstream alert"


def test_proposed_assertion_cites_recurrence_as_the_reason_it_is_needed():
    _client, diag = _investigate("freshness")
    assert "failed 2 time(s) before" in diag.proposed_assertion.rationale


def test_assertion_definitions_use_the_real_identifiers():
    _client, schema = _investigate("schema_change")
    assert "amount" in schema.proposed_assertion.definition
    _client, fanout = _investigate("fanout")
    assert "user_id" in fanout.proposed_assertion.definition
    assert "<join_key>" not in fanout.proposed_assertion.definition


def test_no_assertion_proposed_when_nothing_was_proven():
    client = MockDataHubClient()
    for node in client._graph.values():
        node["freshness_hours"] = node["expected_freshness_hours"]
        node["row_count_delta_pct"] = 0.0
        node["schema_changed_recently"] = False
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(urn=client._symptom_urn, title="t", description=""), write_back=False
    )
    assert diag.proposed_assertion is None


def test_missing_guardrail_is_tagged_so_it_is_findable_by_search():
    client, _diag = _investigate("freshness", write_back=True)
    tags = next(w for w in client.writes if w["op"] == "add_tags")["tags"]
    assert "needs-assertion" in tags


# --------------------------------------------------------------------------- #
# Propagation timeline — the fault in time, not topology
# --------------------------------------------------------------------------- #
def test_timeline_runs_from_the_origin_to_the_alert():
    _client, diag = _investigate("freshness")
    kinds = [e.kind for e in diag.timeline]
    assert kinds[0] == "fault_origin"
    assert kinds[-1] == "assertion_fired"
    assert "transform_ran" in kinds


def test_timeline_shows_transforms_consuming_already_bad_data():
    """The point of the timeline: downstream jobs ran *after* the fault began."""
    _client, diag = _investigate("freshness")
    ran = [e for e in diag.timeline if e.kind == "transform_ran"]
    assert [e.asset_name for e in ran] == ["trips_cleaned", "daily_revenue"]
    assert all("already bad" in e.label for e in ran)


def test_timeline_is_empty_when_nothing_was_proven():
    client = MockDataHubClient()
    for node in client._graph.values():
        node["freshness_hours"] = node["expected_freshness_hours"]
        node["row_count_delta_pct"] = 0.0
        node["schema_changed_recently"] = False
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(urn=client._symptom_urn, title="t", description=""), write_back=False
    )
    assert diag.timeline == []


# --------------------------------------------------------------------------- #
# All of it must survive serialisation and reach the dossier
# --------------------------------------------------------------------------- #
def test_new_findings_survive_serialisation():
    _client, diag = _investigate("freshness")
    d = diag.to_dict()
    assert d["blast_radius"]["silent_count"] == 3
    assert d["proposed_assertion"]["kind"] == "freshness"
    assert len(d["timeline"]) == 4
    assert d["proof_path"]["column_path"]["cause_field"] == "fare_amount"


def test_dossier_records_every_new_finding():
    _client, diag = _investigate("freshness", write_back=True)
    dossier = CauzonAgent._render_dossier(diag).lower()
    assert "column-level proof" in dossier
    assert "how it propagated" in dossier
    assert "blast radius" in dossier
    assert "missing guardrail" in dossier
    assert "not alerting" in dossier


# --------------------------------------------------------------------------- #
# Backend dispatch
# --------------------------------------------------------------------------- #
def test_get_client_honours_every_documented_backend(monkeypatch):
    """`live` used to fall through to the mock, which is the worst failure here.

    A backend that silently becomes the planted demo graph makes the CLI print a
    confident finding about an asset that does not exist in the catalog the operator
    asked about, with nothing to indicate it is fiction.
    """
    from cauzon.datahub_client import MockDataHubClient as _Mock, get_client
    from cauzon.live_client import LiveDataHubClient

    monkeypatch.delenv("CAUZON_DATAHUB_BACKEND", raising=False)
    assert isinstance(get_client(), _Mock), "default must stay mock"

    monkeypatch.setenv("CAUZON_DATAHUB_BACKEND", "mock")
    assert isinstance(get_client(), _Mock)

    monkeypatch.setenv("CAUZON_DATAHUB_BACKEND", "LIVE")  # case-insensitive
    assert isinstance(get_client(), LiveDataHubClient)


def test_get_client_refuses_an_unknown_backend(monkeypatch):
    """Better to fail loudly than to serve the demo graph as though it were real."""
    from cauzon.datahub_client import get_client

    monkeypatch.setenv("CAUZON_DATAHUB_BACKEND", "postgres")
    with pytest.raises(ValueError, match="not a known backend"):
        get_client()
