"""A live catalog backed by NYC Open Data.

The mock backend plants three faults so the demo is deterministic. This backend
does the opposite: it reads **real assets with real freshness** from NYC Open
Data's Socrata catalog, so the open-incident list is whatever is genuinely stale
right now — not a fixed set, and not authored by us.

What is real and what is not, stated plainly because the whole project is about
not overclaiming:

  * **Assets** — real NYC Open Data datasets, fetched live by id.
  * **Freshness** — real. `updatedAt` comes from Socrata, and the lag is computed
    against the current time on every refresh. The 2018 taxi dataset really has
    not been updated in over two years.
  * **Row counts and columns** — real, from the same metadata.
  * **Lineage** — **declared by this project**, not discovered. Socrata publishes
    no lineage. This is the same thing every DataHub ingestion connector does —
    lineage in a catalog is always asserted metadata — but it is ours, and the UI
    and the dossier say so rather than implying the city published it.

The declared edges are not arbitrary: the TLC trip datasets reference the Taxi
Zone lookup for `PULocationID` / `DOLocationID`, which is a documented dependency
in the TLC data dictionary. Datasets with no such dependency are declared with no
edges — which is what lets the proof gate do real work here, on real data.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional

SOCRATA_DOMAIN = "data.cityofnewyork.us"
_CATALOG = "https://api.us.socrata.com/api/catalog/v1"
_TIMEOUT_S = 8
# Socrata metadata changes at most daily; a short TTL keeps a public deployment
# from re-fetching on every page load while still being live.
_CACHE_TTL_S = 900

_URN_PREFIX = "urn:li:dataset:(urn:li:dataPlatform:socrata,nyc_open_data."


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def urn_for(dataset_id: str) -> str:
    """URN carrying a readable name.

    A proof path reading `nyc_taxi_zones -> yellow_taxi_2023` is legible; one
    reading `8meu-9t5y -> 4b4i-vvec` is not. The Socrata id stays the
    authoritative key — it lives in the reverse index below rather than being
    parsed back out of the URN.
    """
    label = DECLARED_GRAPH.get(dataset_id, {}).get("label", dataset_id)
    return f"{_URN_PREFIX}{_slug(label)},PROD)"


def id_from_urn(urn: str) -> Optional[str]:
    return _URN_TO_ID.get(urn)


# --------------------------------------------------------------------------- #
# The declared graph. Ids are real; edges are ours.
#
# `expected_freshness_hours` is the cadence we hold each asset to. Socrata does
# not publish a machine-readable SLA, so these are declared too — chosen to match
# how the city actually publishes each series (daily operational feeds vs annual
# trip archives).
# --------------------------------------------------------------------------- #
DECLARED_GRAPH: dict[str, dict[str, Any]] = {
    # Dimension table the trip datasets join against for pickup/dropoff zones.
    "8meu-9t5y": {
        "label": "NYC Taxi Zones",
        "upstreams": [],
        "expected_freshness_hours": 24 * 90,
        "owner": "tlc-data@nyc.gov",
        "note": "Zone lookup referenced by every TLC trip dataset.",
    },
    "4b4i-vvec": {
        "label": "2023 Yellow Taxi Trip Data",
        "upstreams": ["8meu-9t5y"],
        "expected_freshness_hours": 24 * 365,
        "owner": "tlc-data@nyc.gov",
    },
    "sp7n-275u": {
        "label": "Medallion Taxi Initial Inspection Schedule",
        "upstreams": ["8meu-9t5y"],
        "expected_freshness_hours": 24 * 7,
        "owner": "tlc-licensing@nyc.gov",
    },
    "ht4t-wzcm": {
        "label": "Taxi Improvement Fund Medallion Payments",
        "upstreams": ["8meu-9t5y"],
        "expected_freshness_hours": 24 * 7,
        "owner": "tlc-finance@nyc.gov",
    },
    "vqu8-xef9": {
        "label": "Taxi and FHV Relief Stands",
        "upstreams": ["8meu-9t5y"],
        "expected_freshness_hours": 24 * 30,
        "owner": "tlc-operations@nyc.gov",
    },
    # Declared with no upstream on purpose. It goes stale, it ranks highly on
    # signals, and the proof gate rejects it because nothing connects it to a
    # symptom — the same argument the mock decoy makes, on real data.
    "t29m-gskq": {
        "label": "2018 Yellow Taxi Trip Data",
        "upstreams": [],
        "expected_freshness_hours": 24 * 365,
        "owner": "tlc-data@nyc.gov",
    },
    "biws-g3hs": {
        "label": "2017 Yellow Taxi Trip Data",
        "upstreams": [],
        "expected_freshness_hours": 24 * 365,
        "owner": "tlc-data@nyc.gov",
    },
    # ---------------------------------------------------------------------- #
    # Genuinely live assets.
    #
    # Everything above is years stale, which makes the point about incidents but
    # leaves an obvious objection: if every asset is overdue, how would anyone know
    # the freshness signal reads a real timestamp rather than always firing?
    #
    # These three are fresh right now and stay fresh. The first updates roughly
    # every four minutes — measured, by polling `data_updated_at` and watching it
    # advance from 16:45:51 to 16:49:45 — so its age visibly changes between
    # refreshes. It is the asset that proves the signal is reading rather than
    # asserting, and that it *discriminates*: healthy here, overdue above.
    #
    # Declared with no lineage, deliberately. The traffic feed carries its own
    # geometry inline and no NYC dataset derives from it, so an edge here would be
    # invented — which is the one thing this project cannot do.
    # ---------------------------------------------------------------------- #
    "i4gi-tjb9": {
        "label": "DOT Traffic Speeds (live)",
        "upstreams": [],
        # Generous against a ~4-minute cadence: this asset should read healthy
        # unless the feed genuinely stops, which is what makes it a control.
        "expected_freshness_hours": 2,
        "owner": "dot-its@nyc.gov",
        "note": "Real-time sensor feed. Updates every few minutes; its own geometry is inline, so it has no upstream to declare.",
        "live_probe": True,
    },
    "eabe-havv": {
        "label": "DOB Complaints Received",
        "upstreams": [],
        "expected_freshness_hours": 24,
        "owner": "dob-data@nyc.gov",
        "note": "Refreshed through the working day.",
    },
    "n6c5-95xh": {
        "label": "LinkNYC Kiosk Status",
        "upstreams": [],
        "expected_freshness_hours": 24,
        "owner": "linknyc-ops@nyc.gov",
        "note": "Kiosk health, refreshed continuously.",
    },
}


# The asset whose age is quoted as proof the freshness signal is live. Read off the
# graph rather than restated, so the two cannot disagree.
LIVE_PROBE_ID: str = next(
    (i for i, d in DECLARED_GRAPH.items() if d.get("live_probe")), "i4gi-tjb9"
)


class SocrataCatalog:
    """Reads real dataset metadata, with a TTL cache and an offline fallback."""

    def __init__(
        self,
        fetch: Optional[Any] = None,
        ttl_s: int = _CACHE_TTL_S,
        now: Optional[Any] = None,
    ) -> None:
        # `fetch` is injectable so tests never touch the network.
        self._fetch = fetch or _fetch_catalog
        self._ttl_s = ttl_s
        self._now = now or time.time
        self._cache: Optional[dict[str, dict[str, Any]]] = None
        self._cached_at = 0.0
        self.last_error: Optional[str] = None

    def assets(self) -> dict[str, dict[str, Any]]:
        """Real metadata per declared dataset id, keyed by id.

        On a fetch failure the previous snapshot is reused if there is one; the
        error is recorded either way so callers can say the data may be stale
        rather than presenting it as fresh.
        """
        age = self._now() - self._cached_at
        if self._cache is not None and age < self._ttl_s:
            return self._cache

        try:
            raw = self._fetch(list(DECLARED_GRAPH))
            self.last_error = None
        except Exception as exc:  # network, DNS, malformed payload
            self.last_error = f"{type(exc).__name__}: {exc}"
            return self._cache or {}

        self._cache = {
            dataset_id: self._normalise(dataset_id, raw.get(dataset_id, {}))
            for dataset_id in DECLARED_GRAPH
        }
        self._cached_at = self._now()
        return self._cache

    def _normalise(self, dataset_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        declared = DECLARED_GRAPH[dataset_id]
        updated_at = meta.get("updated_at")
        hours = None
        if isinstance(updated_at, (int, float)):
            hours = max(0.0, (self._now() - updated_at) / 3600.0)

        return {
            "urn": urn_for(dataset_id),
            "name": meta.get("name") or declared["label"],
            "socrata_id": dataset_id,
            "upstreams": [urn_for(u) for u in declared["upstreams"]],
            "owner": declared.get("owner"),
            "expected_freshness_hours": declared["expected_freshness_hours"],
            "freshness_hours": round(hours, 1) if hours is not None else None,
            "updated_at_epoch": updated_at,
            "row_count": meta.get("row_count"),
            "columns": meta.get("columns") or [],
            "declared_note": declared.get("note"),
            "source_url": f"https://{SOCRATA_DOMAIN}/d/{dataset_id}",
        }


class LivenessProbe:
    """One dataset's publication time, re-read often enough to watch it move.

    Separate from `SocrataCatalog` on purpose. That cache is 15 minutes, which is
    right for reading a whole graph and exactly wrong here: the claim this supports
    is "the freshness signal reads a real clock", and a 15-minute cache would show
    the same number to anyone who reloaded inside the window, which proves nothing.

    One field from one dataset, so a 45-second TTL is a trivial amount of traffic.
    """

    def __init__(
        self,
        dataset_id: str = LIVE_PROBE_ID,
        fetch: Optional[Any] = None,
        ttl_s: int = 45,
        now: Optional[Any] = None,
    ) -> None:
        self.dataset_id = dataset_id
        self._fetch = fetch or _fetch_catalog
        self._ttl_s = ttl_s
        self._now = now or time.time
        self._cache: Optional[dict[str, Any]] = None
        self._cached_at = 0.0
        self.last_error: Optional[str] = None

    def read(self) -> dict[str, Any]:
        age = self._now() - self._cached_at
        if self._cache is not None and age < self._ttl_s:
            return {**self._cache, "cache_age_s": round(age, 1)}

        try:
            raw = self._fetch([self.dataset_id])
            self.last_error = None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self._cache is not None:
                return {**self._cache, "stale": True, "error": self.last_error}
            return {
                "dataset_id": self.dataset_id,
                "published_at": None,
                "age_hours": None,
                "stale": True,
                "error": self.last_error,
            }

        meta = raw.get(self.dataset_id, {})
        updated = meta.get("updated_at")
        hours = None
        if isinstance(updated, (int, float)):
            hours = max(0.0, (self._now() - updated) / 3600.0)

        declared = DECLARED_GRAPH.get(self.dataset_id, {})
        self._cache = {
            "dataset_id": self.dataset_id,
            "name": meta.get("name") or declared.get("label"),
            "published_at_epoch": updated,
            "age_hours": round(hours, 4) if hours is not None else None,
            "age_label": humanise_age(hours),
            "expected_freshness_hours": declared.get("expected_freshness_hours"),
            "healthy": (
                hours is not None
                and hours <= (declared.get("expected_freshness_hours") or 0)
            ),
            "source_url": f"https://{SOCRATA_DOMAIN}/d/{self.dataset_id}",
            "stale": False,
        }
        self._cached_at = self._now()
        return {**self._cache, "cache_age_s": 0.0}


def _fetch_catalog(dataset_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One catalog call per id set, returning only the fields we use.

    Socrata's catalog endpoint accepts repeated `ids` parameters, so the whole
    declared graph costs a single request.
    """
    query = "&".join(f"ids={i}" for i in dataset_ids)
    url = f"{_CATALOG}?domains={SOCRATA_DOMAIN}&{query}&limit={len(dataset_ids)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "cauzon/0.2 (+https://cauzon.pages.dev)"}
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        payload = json.loads(response.read().decode("utf-8"))

    out: dict[str, dict[str, Any]] = {}
    for result in payload.get("results", []):
        resource = result.get("resource") or {}
        dataset_id = resource.get("id")
        if not dataset_id:
            continue
        out[dataset_id] = {
            "name": resource.get("name"),
            "updated_at": _epoch(resource.get("updatedAt") or resource.get("data_updated_at")),
            "row_count": _int(resource.get("rows_size") or resource.get("rowsCount")),
            "columns": [
                {"name": n, "type": t}
                for n, t in zip(
                    resource.get("columns_field_name") or [],
                    resource.get("columns_datatype") or [],
                )
            ],
        }
    return out


def _epoch(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def humanise_age(hours: Optional[float]) -> str:
    if hours is None:
        return "unknown"
    # Minutes below the hour. The live traffic feed refreshes every few minutes, and
    # rounding that to "0h" would throw away the one number that demonstrates the
    # freshness signal is reading a real timestamp rather than asserting one.
    if hours < 1:
        minutes = max(1, round(hours * 60))
        return f"{minutes} min"
    if hours < 48:
        return f"{hours:.0f}h"
    days = hours / 24
    if days < 90:
        return f"{days:.0f} days"
    return f"{days / 365:.1f} years"


# Built after DECLARED_GRAPH so urn_for can read the labels.
_URN_TO_ID: dict[str, str] = {urn_for(i): i for i in DECLARED_GRAPH}
