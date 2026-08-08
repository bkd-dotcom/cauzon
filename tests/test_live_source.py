"""Tests for the live public-catalog backend.

Deliberately offline: the fetcher is injected, so these never touch the network
and never depend on what NYC published today. A test that asserts "4 incidents"
against the real API would pass today and fail whenever the city ships an update,
which is the opposite of what this backend is for.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from cauzon.agent import CauzonAgent
from cauzon.live_client import LiveDataHubClient
from cauzon.live_source import (
    DECLARED_GRAPH,
    SocrataCatalog,
    humanise_age,
    id_from_urn,
    urn_for,
)
from cauzon.models import GroundingLevel, Incident

HOUR = 3600.0
NOW = 1_800_000_000.0


def _fetcher(ages_hours: dict[str, float]):
    """A fake Socrata response placing each dataset a given age in the past."""

    def fetch(ids):
        return {
            dataset_id: {
                "name": DECLARED_GRAPH[dataset_id]["label"],
                "updated_at": NOW - ages_hours.get(dataset_id, 1.0) * HOUR,
                "row_count": 1000,
                "columns": [{"name": "id", "type": "text"}],
            }
            for dataset_id in ids
        }

    return fetch


def _client(ages_hours: dict[str, float]) -> LiveDataHubClient:
    catalog = SocrataCatalog(fetch=_fetcher(ages_hours), now=lambda: NOW)
    return LiveDataHubClient(catalog=catalog)


# Everything fresh except the shared dimension table, which is 200 days stale
# against its 90-day SLA.
_ZONES_STALE = {"8meu-9t5y": 24 * 200}


def test_incident_list_is_derived_from_real_freshness_not_hardcoded():
    """Nothing fresh, nothing reported; the set follows the data."""
    assert _client({}).list_open_incidents() == []

    stale = _client({"8meu-9t5y": 24 * 200}).list_open_incidents()
    assert [i["urn"] for i in stale] == [urn_for("8meu-9t5y")]


def test_incident_count_changes_with_the_data():
    """The whole point: this is not a fixed list of three."""
    one = _client({"8meu-9t5y": 24 * 200})
    three = _client(
        {"8meu-9t5y": 24 * 200, "t29m-gskq": 24 * 900, "biws-g3hs": 24 * 900}
    )
    assert len(one.list_open_incidents()) == 1
    assert len(three.list_open_incidents()) == 3


def test_incidents_are_ordered_worst_first_for_triage():
    client = _client(
        {"8meu-9t5y": 24 * 100, "t29m-gskq": 24 * 900, "biws-g3hs": 24 * 500}
    )
    titles = [i["title"] for i in client.list_open_incidents()]
    assert "2018" in titles[0]  # 900 days
    assert "2017" in titles[1]  # 500 days
    assert "Taxi Zones" in titles[2]  # 100 days


def test_an_asset_within_its_sla_is_not_an_incident():
    """Each asset is held to its own cadence, not one global threshold."""
    # 10 days: past the 7-day operational SLA, well inside the 365-day archive one.
    client = _client({"sp7n-275u": 24 * 10, "4b4i-vvec": 24 * 10})
    urns = {i["urn"] for i in client.list_open_incidents()}
    assert urn_for("sp7n-275u") in urns
    assert urn_for("4b4i-vvec") not in urns


def test_declared_lineage_is_traversable_in_both_directions():
    client = _client(_ZONES_STALE)
    zones = urn_for("8meu-9t5y")
    trips = urn_for("4b4i-vvec")

    upstream = client.get_lineage(trips, direction="upstream", hops=3)
    assert [n["urn"] for n in upstream] == [zones]

    downstream = {n["urn"] for n in client.get_lineage(zones, direction="downstream")}
    assert trips in downstream


def test_a_real_stale_upstream_is_proven_as_the_cause():
    client = _client(_ZONES_STALE)
    agent = CauzonAgent(client=client)
    trips = urn_for("4b4i-vvec")
    diag = agent.investigate(
        Incident(urn=trips, title="stale trips", description=""), write_back=False
    )
    assert diag.root_cause is not None
    assert diag.root_cause.name == "NYC Taxi Zones"
    assert diag.grounded is True


def test_no_query_history_means_path_only_not_a_stronger_claim():
    """Socrata retains no SQL, so the ladder must downgrade rather than overclaim."""
    client = _client(_ZONES_STALE)
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(urn=urn_for("4b4i-vvec"), title="t", description=""),
        write_back=False,
    )
    assert diag.grounding is GroundingLevel.PATH_ONLY
    assert diag.proof_path.transform_sql is None
    assert diag.confidence_breakdown.grounding_factor == 0.75


def test_a_stale_asset_with_no_upstream_is_not_blamed_on_anything():
    """The honest outcome, and the one the proof gate exists to produce."""
    client = _client({"t29m-gskq": 24 * 900})
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(urn=urn_for("t29m-gskq"), title="t", description=""),
        write_back=False,
    )
    assert diag.root_cause is None
    assert diag.grounding is GroundingLevel.UNGROUNDED


def test_blast_radius_uses_the_declared_downstream_edges():
    client = _client(_ZONES_STALE)
    agent = CauzonAgent(client=client)
    diag = agent.investigate(
        Incident(urn=urn_for("8meu-9t5y"), title="t", description=""),
        write_back=False,
    )
    assert diag.blast_radius is not None
    # Four datasets are declared downstream of the zone lookup.
    assert diag.blast_radius.count == 4


def test_columns_come_from_the_catalog():
    client = _client(_ZONES_STALE)
    fields = client.list_schema_fields(urn_for("8meu-9t5y"))
    assert fields and fields[0]["name"] == "id"


def test_this_backend_declines_write_back_rather_than_faking_it():
    assert LiveDataHubClient.supports_writeback is False


# --------------------------------------------------------------------------- #
# Robustness — a public API will fail sometimes, and the demo must survive it
# --------------------------------------------------------------------------- #
def test_a_failed_refresh_reuses_the_last_snapshot_and_records_why():
    calls = {"n": 0}

    def flaky(ids):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fetcher(_ZONES_STALE)(ids)
        raise TimeoutError("socrata unreachable")

    clock = {"t": NOW}
    catalog = SocrataCatalog(fetch=flaky, ttl_s=0, now=lambda: clock["t"])
    client = LiveDataHubClient(catalog=catalog)

    assert len(client.list_open_incidents()) == 1
    assert catalog.last_error is None

    clock["t"] += 10_000  # force a refresh, which now fails
    assert len(client.list_open_incidents()) == 1  # previous snapshot retained
    assert "TimeoutError" in (client.source_error or "")


def test_a_first_fetch_failure_degrades_to_an_empty_catalog():
    def dead(ids):
        raise ConnectionError("dns")

    client = LiveDataHubClient(
        catalog=SocrataCatalog(fetch=dead, now=lambda: NOW)
    )
    assert client.list_open_incidents() == []
    assert client.source_error is not None


def test_results_are_cached_rather_than_refetched_per_call():
    calls = {"n": 0}

    def counting(ids):
        calls["n"] += 1
        return _fetcher(_ZONES_STALE)(ids)

    client = LiveDataHubClient(
        catalog=SocrataCatalog(fetch=counting, now=lambda: NOW)
    )
    for _ in range(5):
        client.list_open_incidents()
    assert calls["n"] == 1


def test_missing_timestamp_is_unknown_rather_than_fresh():
    """A dataset with no updatedAt must not be silently treated as healthy."""

    def no_timestamp(ids):
        return {i: {"name": "x", "updated_at": None} for i in ids}

    client = LiveDataHubClient(
        catalog=SocrataCatalog(fetch=no_timestamp, now=lambda: NOW)
    )
    assert client.list_open_incidents() == []  # cannot claim staleness
    entity = client.get_entity(urn_for("8meu-9t5y"))
    assert entity["freshness_hours"] is None


# --------------------------------------------------------------------------- #
# Identifiers and formatting
# --------------------------------------------------------------------------- #
def test_urns_are_readable_but_still_resolve_to_the_socrata_id():
    urn = urn_for("8meu-9t5y")
    assert "nyc_taxi_zones" in urn  # legible in a proof path
    assert id_from_urn(urn) == "8meu-9t5y"  # and still authoritative


def test_unknown_urn_resolves_to_nothing():
    assert id_from_urn("urn:li:dataset:(urn:li:dataPlatform:snowflake,a.b,PROD)") is None


@pytest.mark.parametrize(
    "hours,expected",
    [(3, "3h"), (24 * 10, "10 days"), (24 * 400, "1.1 years"), (None, "unknown")],
)
def test_ages_are_reported_in_units_a_human_reads(hours, expected):
    assert humanise_age(hours) == expected


# --------------------------------------------------------------------------- #
# The liveness probe
# --------------------------------------------------------------------------- #
def test_probe_reports_a_fresh_asset_as_healthy():
    from cauzon.live_source import DECLARED_GRAPH, LIVE_PROBE_ID, LivenessProbe

    now = 1_800_000_000.0
    sla = DECLARED_GRAPH[LIVE_PROBE_ID]["expected_freshness_hours"]

    probe = LivenessProbe(
        # Four minutes old, which is this feed's real cadence.
        fetch=lambda ids: {ids[0]: {"name": "DOT Traffic Speeds", "updated_at": now - 240}},
        now=lambda: now,
    )
    reading = probe.read()

    assert reading["healthy"] is True
    assert reading["age_label"] == "4 min", "minutes matter here; 0h proves nothing"
    assert reading["age_hours"] < sla
    assert reading["stale"] is False


def test_probe_reports_a_stalled_feed_as_past_sla():
    """The control has to be falsifiable: if the feed stops, it must say so."""
    from cauzon.live_source import LivenessProbe

    now = 1_800_000_000.0
    probe = LivenessProbe(
        fetch=lambda ids: {ids[0]: {"name": "x", "updated_at": now - 3600 * 9}},
        now=lambda: now,
    )
    assert probe.read()["healthy"] is False


def test_probe_ttl_is_short_enough_to_show_movement():
    """A 15-minute cache would show the same number to anyone who reloaded.

    The whole claim this supports is that the age changes, so the probe cannot
    inherit the catalog's TTL.
    """
    from cauzon.live_source import _CACHE_TTL_S, LivenessProbe

    probe = LivenessProbe()
    assert probe._ttl_s <= 60
    assert probe._ttl_s < _CACHE_TTL_S


def test_probe_refetches_once_its_ttl_expires():
    from cauzon.live_source import LivenessProbe

    clock = {"t": 1_000.0}
    calls = {"n": 0}

    def counted(ids):
        calls["n"] += 1
        return {ids[0]: {"name": "x", "updated_at": clock["t"] - 120}}

    probe = LivenessProbe(fetch=counted, ttl_s=45, now=lambda: clock["t"])
    probe.read()
    probe.read()
    assert calls["n"] == 1, "within the TTL it must not refetch"

    clock["t"] += 50
    probe.read()
    assert calls["n"] == 2


def test_a_failed_probe_reuses_the_last_reading_and_flags_it():
    """Better a lower bound that says so than a confident number from nowhere."""
    from cauzon.live_source import LivenessProbe

    clock = {"t": 1_000.0}
    calls = {"n": 0}

    def flaky(ids):
        calls["n"] += 1
        if calls["n"] == 1:
            return {ids[0]: {"name": "x", "updated_at": clock["t"] - 60}}
        raise TimeoutError("socrata slow")

    probe = LivenessProbe(fetch=flaky, ttl_s=10, now=lambda: clock["t"])
    first = probe.read()
    assert first["stale"] is False

    clock["t"] += 30
    again = probe.read()
    assert again["stale"] is True
    assert "TimeoutError" in again["error"]
    assert again["age_label"] == first["age_label"]


def test_the_live_catalog_now_contains_both_fresh_and_stale_assets():
    """The point of adding these: a signal that always fires is unfalsifiable.

    With every asset overdue there was nothing to show the freshness check reads a
    real clock. The catalog now has to discriminate.
    """
    from cauzon.live_source import DECLARED_GRAPH

    tight = [d for d in DECLARED_GRAPH.values() if d["expected_freshness_hours"] <= 24]
    loose = [d for d in DECLARED_GRAPH.values() if d["expected_freshness_hours"] > 24 * 300]
    assert tight, "no high-frequency asset declared"
    assert loose, "no long-horizon asset declared"
