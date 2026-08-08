"""Tests for the real-DataHub client.

`MCPDataHubClient` is the code every "works against a real DataHub" claim rests
on, and it had no tests at all — its only validation was a screenshot and a
transcript from an older build. The gap mattered: this layer's whole job is
normalising response shapes that vary between DataHub's GraphQL and REST paths,
which is exactly the kind of code that fails silently on a shape it did not expect.

Nothing here touches a network. The client is constructed with its SDK imports
stubbed, then handed a fake `mcp_tools` module, so every branch is reachable
without an instance to point at.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from cauzon.datahub_client import (  # noqa: E402
    MCPDataHubClient,
    _first,
    _owner_of,
    _short_name,
)

SYMPTOM = "urn:li:dataset:(urn:li:dataPlatform:snowflake,nyc.daily_revenue,PROD)"
CAUSE = "urn:li:dataset:(urn:li:dataPlatform:s3,nyc.raw_trips,PROD)"


class FakeTools:
    """Stands in for `datahub_agent_context.mcp_tools`.

    Only the calls the client makes are implemented; anything else raising is the
    point — it proves the client does not depend on tools it has not declared.
    """

    def __init__(self, **overrides):
        self.calls: list[tuple[str, dict]] = []
        self._overrides = overrides

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            handler = self._overrides.get(name)
            if handler is None:
                raise AttributeError(f"tool {name!r} not configured on this fake")
            return handler(**kwargs) if callable(handler) else handler

        return call


def _client(**overrides) -> MCPDataHubClient:
    """An MCPDataHubClient with its SDK wiring bypassed."""
    client = MCPDataHubClient.__new__(MCPDataHubClient)
    client.gms_url = "http://datahub.test:8080"
    client.token = ""
    client._mt = FakeTools(**overrides)
    client._client = object()
    client._writes = []
    return client


# --------------------------------------------------------------------------- #
# Response-shape normalisation
# --------------------------------------------------------------------------- #
def test_first_prefers_the_earliest_present_key():
    assert _first({"b": 2, "a": 1}, "a", "b") == 1
    assert _first({"b": 2}, "a", "b") == 2
    assert _first({}, "a", default="fallback") == "fallback"
    # A non-dict must not explode — DataHub returns lists in places.
    assert _first([1, 2, 3], "a", default=None) is None


def test_short_name_extracts_the_table_from_a_urn():
    assert _short_name(SYMPTOM) == "daily_revenue"
    assert _short_name("not-a-urn") == "not-a-urn"


@pytest.mark.parametrize(
    "ownership, expected",
    [
        ({"owners": [{"owner": {"properties": {"email": "a@b.com"}}}]}, "a@b.com"),
        (
            {"owners": [{"owner": {"properties": {"displayName": "Data Platform"}}}]},
            "Data Platform",
        ),
        ({"owners": [{"owner": {"username": "svc-ingest"}}]}, "svc-ingest"),
        # A bare URN is trimmed to its last segment rather than shown raw.
        ({"owners": [{"owner": {"urn": "urn:li:corpuser:jo"}}]}, "jo"),
        ({"owners": [{"owner": "urn:li:corpuser:kim"}]}, "kim"),
        # Shapes that carry no owner must yield None, not a guess.
        ({"owners": []}, None),
        ({"owners": "malformed"}, None),
        ({}, None),
    ],
)
def test_owner_of_reads_every_ownership_shape_or_gives_up(ownership, expected):
    assert _owner_of({"ownership": ownership}) == expected


def test_get_entity_reads_custom_properties_as_a_list_of_pairs():
    """DataHub's GraphQL path returns customProperties as [{key,value}, ...]."""
    client = _client(
        get_entities=lambda urns: [
            {
                "urn": SYMPTOM,
                "name": "daily_revenue",
                "customProperties": [
                    {"key": "freshness_hours", "value": "49"},
                    {"key": "expected_freshness_hours", "value": "24"},
                    {"key": "row_count_delta_pct", "value": "-40.0"},
                    {"key": "schema_changed_recently", "value": "true"},
                ],
                "ownership": {"owners": [{"owner": {"properties": {"email": "rev@x.io"}}}]},
            }
        ]
    )
    entity = client.get_entity(SYMPTOM)

    assert entity["name"] == "daily_revenue"
    assert entity["freshness_hours"] == 49.0
    assert entity["expected_freshness_hours"] == 24.0
    assert entity["row_count_delta_pct"] == -40.0
    assert entity["schema_changed_recently"] is True
    assert entity["owner"] == "rev@x.io"


def test_get_entity_reads_custom_properties_nested_under_dataset_properties():
    """The REST path nests them, as a plain dict. Same fields must come out."""
    client = _client(
        get_entities=lambda urns: [
            {
                "urn": SYMPTOM,
                "datasetProperties": {
                    "customProperties": {"freshness_hours": "51", "duplicate_key_pct": "12.5"}
                },
            }
        ]
    )
    entity = client.get_entity(SYMPTOM)

    assert entity["freshness_hours"] == 51.0
    assert entity["duplicate_key_pct"] == 12.5
    # Absent name falls back to the URN's table segment.
    assert entity["name"] == "daily_revenue"


def test_get_entity_treats_unparseable_numbers_as_absent_not_zero():
    """A zero freshness lag is a claim; an unparseable one is not."""
    client = _client(
        get_entities=lambda urns: [
            {"urn": SYMPTOM, "customProperties": [{"key": "freshness_hours", "value": "n/a"}]}
        ]
    )
    entity = client.get_entity(SYMPTOM)
    assert entity["freshness_hours"] is None


def test_get_entity_survives_an_empty_result():
    client = _client(get_entities=lambda urns: [])
    entity = client.get_entity(SYMPTOM)
    assert entity["urn"] == SYMPTOM
    assert entity["freshness_hours"] is None


# --------------------------------------------------------------------------- #
# The incident queue — where silence used to be indistinguishable from health
# --------------------------------------------------------------------------- #
def _search_hit(urn: str) -> dict:
    return {"entity": {"urn": urn}}


def test_failing_assertions_become_incidents():
    client = _client(
        search=lambda **kw: {"searchResults": [_search_hit(SYMPTOM)]},
        get_dataset_assertions=lambda **kw: {
            "assertions": [
                {
                    "type": "VOLUME",
                    "description": "row_count within 10% of 7-day average",
                    "lastEvaluatedAt": "2026-08-07T06:00:00Z",
                }
            ]
        },
    )
    incidents = client.list_open_incidents()

    assert len(incidents) == 1
    assert incidents[0]["urn"] == SYMPTOM
    assert "VOLUME" in incidents[0]["title"]
    assert incidents[0]["detected_at"] == "2026-08-07T06:00:00Z"


def test_only_failing_assertions_are_requested():
    """Asking for every assertion and filtering here would be a different query."""
    client = _client(
        search=lambda **kw: {"searchResults": [_search_hit(SYMPTOM)]},
        get_dataset_assertions=lambda **kw: {"assertions": []},
    )
    client.list_open_incidents()

    call = next(c for c in client._mt.calls if c[0] == "get_dataset_assertions")
    assert call[1]["status"] == "FAILING"
    assert call[1]["urn"] == SYMPTOM


def test_non_dataset_search_hits_are_skipped_without_probing():
    client = _client(
        search=lambda **kw: {
            "searchResults": [
                {"entity": {"urn": "urn:li:dashboard:(looker,exec)"}},
                {"entity": {"urn": "urn:li:corpuser:jo"}},
            ]
        }
    )
    assert client.list_open_incidents() == []
    assert not [c for c in client._mt.calls if c[0] == "get_dataset_assertions"]


def test_a_total_assertion_failure_raises_instead_of_reporting_a_healthy_catalog():
    """The regression this method's blanket `except` used to cause.

    Every probe failing meant every asset was skipped and the queue came back
    empty — indistinguishable from a catalog with nothing wrong. "We could not
    ask" and "nothing is failing" are different answers and must not share a
    representation.
    """

    def boom(**kw):
        raise ConnectionError("DataHub unreachable")

    client = _client(
        search=lambda **kw: {"searchResults": [_search_hit(SYMPTOM), _search_hit(CAUSE)]},
        get_dataset_assertions=boom,
    )
    with pytest.raises(RuntimeError, match="Could not read assertions for any"):
        client.list_open_incidents()


def test_one_asset_failing_does_not_sink_the_whole_queue():
    """Partial failure is tolerable; the assets that answered still count."""
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if kw["urn"] == CAUSE:
            raise TimeoutError("slow shard")
        return {"assertions": [{"type": "FRESHNESS", "description": "stale"}]}

    client = _client(
        search=lambda **kw: {"searchResults": [_search_hit(SYMPTOM), _search_hit(CAUSE)]},
        get_dataset_assertions=flaky,
    )
    incidents = client.list_open_incidents()

    assert calls["n"] == 2
    assert [i["urn"] for i in incidents] == [SYMPTOM]


def test_a_catalog_with_no_datasets_reports_no_incidents_rather_than_raising():
    """Nothing probed is not the same as everything failing."""
    client = _client(search=lambda **kw: {"searchResults": []})
    assert client.list_open_incidents() == []


# --------------------------------------------------------------------------- #
# Lineage
# --------------------------------------------------------------------------- #
def test_lineage_paths_between_degrades_to_empty_rather_than_raising():
    """No path is a verdict the proof gate handles; an exception is not."""

    def boom(**kw):
        raise RuntimeError("graph index unavailable")

    client = _client(get_lineage_paths_between=boom)
    assert client.get_lineage_paths_between(CAUSE, SYMPTOM) == []


def test_upstream_aspect_walk_is_bounded_by_hops():
    """A chain longer than the hop limit must be truncated, not followed to the end."""

    class Upstream:
        def __init__(self, dataset):
            self.dataset = dataset

    class Aspect:
        def __init__(self, upstreams):
            self.upstreams = upstreams

    chain = {f"urn:d{i}": f"urn:d{i + 1}" for i in range(6)}

    class Graph:
        def get_aspect(self, urn, _cls):
            nxt = chain.get(urn)
            return Aspect([Upstream(nxt)]) if nxt else None

    class Inner:
        _graph = Graph()

    client = _client()
    client._client = Inner()

    walked = client._walk_upstream_aspects("urn:d0", hops=2)
    assert [n["hops"] for n in walked] == [1, 2]
    assert {n["urn"] for n in walked} == {"urn:d1", "urn:d2"}


def test_upstream_aspect_walk_does_not_revisit_a_cycle():
    class Upstream:
        def __init__(self, dataset):
            self.dataset = dataset

    class Aspect:
        def __init__(self, upstreams):
            self.upstreams = upstreams

    loop = {"urn:a": "urn:b", "urn:b": "urn:a"}

    class Graph:
        def get_aspect(self, urn, _cls):
            return Aspect([Upstream(loop[urn])])

    class Inner:
        _graph = Graph()

    client = _client()
    client._client = Inner()

    walked = client._walk_upstream_aspects("urn:a", hops=5)
    assert [n["urn"] for n in walked] == ["urn:b"]


def test_aspect_walk_without_a_graph_handle_returns_empty():
    client = _client()
    client._client = object()  # no `_graph`
    assert client._walk_upstream_aspects(SYMPTOM, hops=3) == []


# --------------------------------------------------------------------------- #
# Documents and writes
# --------------------------------------------------------------------------- #
def test_search_documents_returns_empty_when_the_tool_is_unavailable():
    """Recurrence read-back must degrade, not crash an investigation."""
    client = _client()  # every tool raises AttributeError
    assert client.search_documents("cauzon") == []


def test_writes_are_recorded_for_the_receipt_panel():
    client = _client(
        add_tags=lambda **kw: {"ok": True},
        update_description=lambda **kw: {"ok": True},
    )
    client.add_tags(SYMPTOM, ["root-cause"])
    client.update_description(SYMPTOM, "Investigated by Cauzon.")

    ops = [w["op"] for w in client.writes]
    assert "add_tags" in ops and "update_description" in ops
