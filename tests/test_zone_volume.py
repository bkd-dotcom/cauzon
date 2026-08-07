"""Tests for the live per-zone trip aggregation.

The map's whole value is that its numbers are real, so the properties worth
pinning are the ones that would let a wrong number look right: a malformed row
must not become a zero (which reads as "no trips in this zone" rather than "we
could not parse this"), and a failed fetch must not present an empty map as
though the city reported no traffic.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from cauzon.zone_volume import TRIP_DATASET_ID, ZoneVolume  # noqa: E402


def _rows(pairs):
    return [{"pulocationid": z, "trips": t} for z, t in pairs]


def test_aggregates_rows_into_zone_counts():
    volume = ZoneVolume(fetch=lambda _: _rows([("132", "1992304"), ("237", "1791795")]))
    snap = volume.snapshot()

    assert snap["trips"] == {"132": 1992304, "237": 1791795}
    assert snap["total_trips"] == 3784099
    assert snap["zones_covered"] == 2
    assert snap["stale"] is False
    assert snap["dataset_id"] == TRIP_DATASET_ID


def test_zone_ids_are_normalised_so_the_geometry_join_lands():
    """Socrata returns ids as strings; the geometry keys on the integer value.

    `"007"` and `"7"` are the same zone, and if they key differently the polygon
    silently renders as having no traffic. A non-integer id is not a zone at all,
    so it is dropped rather than guessed at.
    """
    volume = ZoneVolume(fetch=lambda _: _rows([("007", "50"), ("7.0", "1")]))
    trips = volume.snapshot()["trips"]

    assert trips == {"7": 50}


def test_a_malformed_row_is_dropped_not_zeroed():
    volume = ZoneVolume(
        fetch=lambda _: _rows([("132", "100"), (None, "5"), ("161", "oops")])
    )
    trips = volume.snapshot()["trips"]

    assert trips == {"132": 100}
    assert "161" not in trips, "an unparseable count must not become a real zero"


def test_a_failed_fetch_is_marked_stale_rather_than_reported_as_no_traffic():
    def boom(_):
        raise TimeoutError("socrata took too long")

    volume = ZoneVolume(fetch=boom)
    snap = volume.snapshot()

    assert snap["stale"] is True
    assert snap["zones_covered"] == 0
    assert snap["total_trips"] == 0
    assert "TimeoutError" in (snap.get("error") or "")
    assert volume.last_error


def test_an_empty_aggregation_is_an_error_not_a_result():
    """A 200 with no rows means the query stopped working, not that nobody rode."""
    volume = ZoneVolume(fetch=lambda _: [])
    snap = volume.snapshot()

    assert snap["stale"] is True
    assert volume.last_error


def test_a_later_failure_keeps_serving_the_last_good_snapshot():
    calls = {"n": 0}
    clock = {"t": 1000.0}

    def flaky(_):
        calls["n"] += 1
        if calls["n"] == 1:
            return _rows([("132", "10")])
        raise ConnectionError("network went away")

    volume = ZoneVolume(fetch=flaky, ttl_s=60, now=lambda: clock["t"])
    assert volume.snapshot()["trips"] == {"132": 10}

    clock["t"] += 120  # past the TTL, so it refetches and the refetch fails
    again = volume.snapshot()
    assert again["trips"] == {"132": 10}, "the last good numbers are better than none"
    assert volume.last_error


def test_the_cache_prevents_refetching_within_the_ttl():
    """The aggregation scans tens of millions of rows; per-request would be unusable."""
    calls = {"n": 0}

    def counted(_):
        calls["n"] += 1
        return _rows([("132", "10")])

    volume = ZoneVolume(fetch=counted, ttl_s=3600, now=lambda: 500.0)
    for _ in range(5):
        volume.snapshot()

    assert calls["n"] == 1
