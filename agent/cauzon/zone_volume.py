"""Real trip volume per taxi zone, aggregated by Socrata.

The zone map draws the 263 polygons the lookup table defines. On its own that is
a picture of a schema. This is what makes it an argument: every one of the 38
million trips in the 2023 dataset resolves its pickup through one of those
polygons, so the map can show how much traffic actually depends on a lookup table
that is several times past its freshness SLA. JFK alone routes about two million
pickups through one zone definition.

The aggregation runs **on Socrata**, not here — `$select=pulocationid,count(1)`
with `$group` returns 263 rows for 38 million records, so the browser never sees
the trip data and this process never holds it. It takes a few seconds, hence the
long TTL.

Being exact about what is live, since the project's whole claim is not
overclaiming:

  * **The counts are real**, computed by the city's API over the full dataset at
    request time. Nothing here is authored or sampled.
  * **They are stable, not moving.** The 2023 trip dataset is historical, so
    these totals do not change minute to minute. What changes — and what the
    incident is about — is the *lookup table's* freshness.
  * **The join is real.** `pulocationid` is the lookup's own `locationid`; that
    is the documented dependency the declared lineage edge represents.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

# The trip dataset to aggregate. 2023 is the most recent of the three declared
# trip datasets and the one whose zone coverage is complete.
TRIP_DATASET_ID = "4b4i-vvec"
TRIP_DATASET_LABEL = "2023 Yellow Taxi Trip Data"
# The lookup whose freshness is the actual incident.
ZONE_DATASET_ID = "8meu-9t5y"

_RESOURCE = "https://data.cityofnewyork.us/resource"
# Server-side aggregation over tens of millions of rows takes a few seconds, and
# a historical dataset's totals do not move, so this is cached for an hour.
_CACHE_TTL_S = 3600
_TIMEOUT_S = 45


def _fetch_volume(dataset_id: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "$select": "pulocationid,count(1) as trips",
            "$group": "pulocationid",
            "$order": "trips DESC",
            # 263 zones exist; the ceiling is slack, not a target.
            "$limit": "400",
        }
    )
    url = f"{_RESOURCE}/{dataset_id}.json?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of rows, got {type(payload).__name__}")
    return payload


class ZoneVolume:
    """Pickup counts per zone id, cached, with an injectable fetch for tests."""

    def __init__(
        self,
        fetch: Optional[Any] = None,
        ttl_s: int = _CACHE_TTL_S,
        now: Optional[Any] = None,
    ) -> None:
        self._fetch = fetch or _fetch_volume
        self._ttl_s = ttl_s
        self._now = now or time.time
        self._cache: Optional[dict[str, Any]] = None
        self._cached_at = 0.0
        self.last_error: Optional[str] = None

    def snapshot(self) -> dict[str, Any]:
        """Trips per zone plus provenance.

        On a fetch failure the previous snapshot is reused if there is one, and
        the error is recorded either way — the map then says the numbers may be
        stale rather than presenting a gap as zero traffic, which would read as
        "no trips here" when it means "we could not ask".
        """
        age = self._now() - self._cached_at
        if self._cache is not None and age < self._ttl_s:
            return self._cache

        try:
            rows = self._fetch(TRIP_DATASET_ID)
            self.last_error = None
        except Exception as exc:  # network, timeout, malformed payload
            self.last_error = f"{type(exc).__name__}: {exc}"
            return self._cache or self._empty()

        trips: dict[str, int] = {}
        for row in rows:
            zone_id = row.get("pulocationid")
            count = row.get("trips")
            if zone_id is None or count is None:
                continue
            try:
                trips[str(int(zone_id))] = int(count)
            except (TypeError, ValueError):
                # A malformed row is dropped rather than defaulting to zero,
                # which would claim a real zone had no traffic.
                continue

        if not trips:
            self.last_error = "aggregation returned no usable rows"
            return self._cache or self._empty()

        self._cache = {
            "trips": trips,
            "total_trips": sum(trips.values()),
            "zones_covered": len(trips),
            "dataset_id": TRIP_DATASET_ID,
            "dataset_label": TRIP_DATASET_LABEL,
            "source_url": f"https://data.cityofnewyork.us/d/{TRIP_DATASET_ID}",
            "aggregated_by": "socrata",
            "stale": False,
        }
        self._cached_at = self._now()
        return self._cache

    def _empty(self) -> dict[str, Any]:
        return {
            "trips": {},
            "total_trips": 0,
            "zones_covered": 0,
            "dataset_id": TRIP_DATASET_ID,
            "dataset_label": TRIP_DATASET_LABEL,
            "source_url": f"https://data.cityofnewyork.us/d/{TRIP_DATASET_ID}",
            "aggregated_by": "socrata",
            "stale": True,
            "error": self.last_error,
        }
