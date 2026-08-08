"""Tests for multi-incident correlation.

The first test is the one that matters. Correlation's failure mode is a confident
false positive — grouping unrelated failures under whichever asset happens to sit
upstream of both — and that failure would be worse than not having the feature,
because it sends one team to fix something that was never broken. So the property
under test is mostly the refusal.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from cauzon.correlate import correlate  # noqa: E402
from cauzon.datahub_client import _SCENARIOS, MockDataHubClient  # noqa: E402
from cauzon.models import GroundingLevel  # noqa: E402


def _merged(*scenarios: str) -> MockDataHubClient:
    """One client over several scenario graphs, alerting on each symptom.

    The scenario graphs are disjoint, so this is a queue of genuinely unrelated
    failures — exactly the input correlation must decline to group.
    """
    graphs: dict = {}
    queue: list[dict] = []
    for name in scenarios:
        graph, symptom, incident = _SCENARIOS[name]
        graphs.update(graph)
        queue.append({"urn": symptom, **incident})

    client = MockDataHubClient(scenario=scenarios[0])
    client._graph = {k: dict(v) for k, v in graphs.items()}
    client.list_open_incidents = lambda: list(queue)  # type: ignore[method-assign]
    return client


# --------------------------------------------------------------------------- #
# Refusal — the property that makes the feature trustworthy
# --------------------------------------------------------------------------- #
def test_unrelated_failures_are_not_grouped():
    """Three disjoint planted faults must produce no correlation at all."""
    client = _merged("freshness", "schema_change", "fanout")
    assert correlate(client, client.list_open_incidents()) == []


def test_two_unrelated_failures_are_not_grouped():
    client = _merged("freshness", "fanout")
    assert correlate(client, client.list_open_incidents()) == []


def test_a_single_incident_is_not_a_correlation():
    client = MockDataHubClient(scenario="freshness")
    assert correlate(client, client.list_open_incidents()[:1]) == []


def test_an_empty_queue_correlates_to_nothing():
    client = MockDataHubClient(scenario="freshness")
    assert correlate(client, []) == []


HEALTHY_ROOT = "urn:li:dataset:(urn:li:dataPlatform:s3,t.config,PROD)"
BROKEN_ROOT = "urn:li:dataset:(urn:li:dataPlatform:s3,t.feed,PROD)"
LEFT = "urn:li:dataset:(urn:li:dataPlatform:snowflake,t.left,PROD)"
RIGHT = "urn:li:dataset:(urn:li:dataPlatform:snowflake,t.right,PROD)"
LONER = "urn:li:dataset:(urn:li:dataPlatform:snowflake,t.loner,PROD)"


def _diamond() -> MockDataHubClient:
    """Two symptoms over two shared roots: one broken, one perfectly healthy.

              config (healthy) ->  left  (alerting)
                               ->  right (alerting)
              feed   (stale)   ->  left
                               ->  right
              loner  (stale)   ->  right

    `config` and `feed` are both upstream of both symptoms, and only `feed` is at
    fault — so the signal requirement is the only thing keeping `config` out of the
    result. `loner` is upstream of one symptom, so it is not a correlation either.
    """
    graph = {
        HEALTHY_ROOT: {
            "name": "config",
            "upstreams": [],
            "freshness_hours": 1,
            "expected_freshness_hours": 24,
            "schema_changed_recently": False,
            "row_count_delta_pct": 0.0,
            "queries": [],
        },
        BROKEN_ROOT: {
            "name": "feed",
            "upstreams": [],
            "freshness_hours": 60,
            "expected_freshness_hours": 6,
            "schema_changed_recently": False,
            "row_count_delta_pct": -100.0,
            "queries": [{"query": "COPY INTO feed FROM @stage/", "last_run": "2 days ago"}],
        },
        LONER: {
            "name": "loner",
            "upstreams": [],
            "freshness_hours": 70,
            "expected_freshness_hours": 6,
            "schema_changed_recently": False,
            "row_count_delta_pct": -90.0,
            "queries": [],
        },
        LEFT: {
            "name": "left",
            "upstreams": [HEALTHY_ROOT, BROKEN_ROOT],
            "freshness_hours": 8,
            "expected_freshness_hours": 24,
            "schema_changed_recently": False,
            "row_count_delta_pct": -30.0,
            "queries": [{"query": "CREATE TABLE left AS SELECT * FROM feed", "last_run": "1h ago"}],
        },
        RIGHT: {
            "name": "right",
            "upstreams": [HEALTHY_ROOT, BROKEN_ROOT, LONER],
            "freshness_hours": 9,
            "expected_freshness_hours": 24,
            "schema_changed_recently": False,
            "row_count_delta_pct": -28.0,
            "queries": [{"query": "CREATE TABLE right AS SELECT * FROM feed", "last_run": "1h ago"}],
        },
    }
    client = MockDataHubClient(scenario="freshness")
    client._graph = {k: dict(v) for k, v in graph.items()}
    client.list_open_incidents = lambda: [  # type: ignore[method-assign]
        {"urn": LEFT, "title": "left dropped 30%", "description": ""},
        {"urn": RIGHT, "title": "right dropped 28%", "description": ""},
    ]
    return client


def test_a_shared_ancestor_with_no_fault_is_not_named():
    """Being a common dependency is not evidence of being the broken one.

    `config` is upstream of both symptoms and completely healthy. Intersecting
    ancestors alone would blame it; requiring a signal is what stops that.
    """
    client = _diamond()
    results = correlate(client, client.list_open_incidents())

    named = {c.cause_urn for c in results}
    assert HEALTHY_ROOT not in named, "a healthy shared ancestor must not be blamed"
    assert named == {BROKEN_ROOT}


def test_an_ancestor_of_only_one_symptom_is_not_a_correlation():
    """`loner` is stale and upstream of `right` alone — that is an investigation."""
    client = _diamond()
    named = {c.cause_urn for c in correlate(client, client.list_open_incidents())}
    assert LONER not in named


def test_a_shared_ancestor_the_proof_gate_rejects_is_not_named():
    """The gate applies to group claims exactly as it does to single ones.

    DataHub's graph index and its lineage aspects can disagree — the premise the
    `marketing_spend` decoy is built on. Here the lineage walk reports a shared
    ancestor that no path can be reconstructed to, and it carries strong signals,
    so only the gate stops it being named.
    """
    client = _diamond()
    ghost = "urn:li:dataset:(urn:li:dataPlatform:snowflake,t.ghost,PROD)"
    client._graph[ghost] = {
        "name": "ghost",
        "upstreams": [],
        "freshness_hours": 200,
        "expected_freshness_hours": 6,
        "schema_changed_recently": True,
        "schema_change_note": "Column renamed an hour ago.",
        "row_count_delta_pct": -95.0,
        "queries": [],
    }

    real_lineage = client.get_lineage
    real_paths = client.get_lineage_paths_between

    def lineage(urn, direction="upstream", hops=3):
        nodes = real_lineage(urn, direction=direction, hops=hops)
        if direction == "upstream" and urn in {LEFT, RIGHT}:
            # Surfaced by the index as a related upstream, but absent from every
            # lineage aspect below.
            nodes = nodes + [{"urn": ghost, "name": "ghost", "hops": 1}]
        return nodes

    def paths(source_urn, target_urn):
        if source_urn == ghost:
            return []
        return real_paths(source_urn, target_urn)

    client.get_lineage = lineage  # type: ignore[method-assign]
    client.get_lineage_paths_between = paths  # type: ignore[method-assign]

    named = {c.cause_urn for c in correlate(client, client.list_open_incidents())}
    assert ghost not in named, "no reconstructable path means no shared cause"
    assert named == {BROKEN_ROOT}


# --------------------------------------------------------------------------- #
# Finding a genuine shared cause
# --------------------------------------------------------------------------- #
def test_one_stalled_upstream_behind_two_separate_alerts_is_found():
    """The case the feature exists for: two teams, one outage, one dossier."""
    client = MockDataHubClient(scenario="shared_cause")
    results = correlate(client, client.list_open_incidents())

    assert len(results) == 1
    found = results[0]
    assert found.cause_name == "currency_rates"
    assert found.count >= 2
    assert found.cause_owner == "treasury-eng@example.com"
    # Grouped only on real edges: every symptom carries its own proof.
    for symptom in found.symptoms:
        assert symptom.proof.verified
        assert symptom.proof.cause_urn == found.cause_urn
        assert symptom.hops_from_cause >= 1


def test_the_shared_cause_matches_what_investigating_each_symptom_alone_concludes():
    """Correlation must not reach a verdict single-incident RCA would not.

    It reuses `CauzonAgent._prove`, so this pins the two paths together: if they
    ever disagree, one of them is wrong.
    """
    from cauzon.agent import CauzonAgent
    from cauzon.models import Incident

    client = MockDataHubClient(scenario="shared_cause")
    correlated = correlate(client, client.list_open_incidents())[0]

    for symptom in correlated.symptoms:
        solo = CauzonAgent(client=MockDataHubClient(scenario="shared_cause")).investigate(
            Incident(urn=symptom.urn, title="", description=""), write_back=False
        )
        assert solo.root_cause is not None
        assert solo.root_cause.urn == correlated.cause_urn


def test_group_grounding_is_the_weakest_rung_not_the_best():
    """A group claim cannot be better grounded than its worst link."""
    client = MockDataHubClient(scenario="shared_cause")

    # Strip the query history off one edge so that symptom proves at PATH_ONLY.
    weakened = MockDataHubClient(scenario="shared_cause")
    for node in weakened._graph.values():
        if node["name"] == "usage_rollup":
            node["queries"] = []

    full = correlate(client, client.list_open_incidents())[0]
    assert full.grounding is GroundingLevel.PATH_AND_TRANSFORM

    partial = correlate(weakened, weakened.list_open_incidents())[0]
    rungs = {s.proof.grounding for s in partial.symptoms}
    assert GroundingLevel.PATH_ONLY in rungs
    assert partial.grounding is GroundingLevel.PATH_ONLY, (
        "one unprovable transform must downgrade the whole group"
    )


def test_a_symptom_that_cannot_be_proven_is_reported_not_folded_in():
    """Upstream-of is not the same as proven-to-reach.

    A candidate that only explains some symptoms must say which ones it does not,
    rather than rounding up to the whole queue.
    """
    client = MockDataHubClient(scenario="shared_cause")
    queue = client.list_open_incidents()

    # An extra symptom the cause has no path to at all.
    unrelated = "urn:li:dataset:(urn:li:dataPlatform:snowflake,fin.unlinked,PROD)"
    client._graph[unrelated] = {
        "name": "unlinked",
        "upstreams": [],
        "freshness_hours": 99,
        "expected_freshness_hours": 24,
        "schema_changed_recently": False,
        "row_count_delta_pct": -50.0,
        "queries": [],
    }
    queue.append({"urn": unrelated, "title": "unlinked is stale", "description": ""})

    found = correlate(client, queue)[0]
    assert unrelated not in {s.urn for s in found.symptoms}
    # It is not upstream of the unrelated asset, so it is not even a candidate for
    # it — the point is that the correlation does not claim it.
    assert found.count >= 2


def test_lineage_failure_degrades_to_no_correlation():
    """Unable to look is not the same as looked and found nothing shared."""

    class Blind(MockDataHubClient):
        def get_lineage(self, urn, direction="upstream", hops=3):
            raise RuntimeError("graph index unavailable")

    client = Blind(scenario="shared_cause")
    assert correlate(client, client.list_open_incidents()) == []


def test_correlation_serialises_for_the_api():
    client = MockDataHubClient(scenario="shared_cause")
    body = correlate(client, client.list_open_incidents())[0].to_dict()

    for key in (
        "cause_urn",
        "cause_name",
        "cause_owner",
        "signals",
        "evidence_notes",
        "symptoms",
        "unexplained",
        "count",
        "grounding",
        "grounding_label",
    ):
        assert key in body, f"missing {key}"
    assert body["symptoms"][0]["proof"]["verified"] is True
    assert all(isinstance(s, str) for s in body["signals"])
