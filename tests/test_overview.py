"""Tests for the catalog-wide views.

These two builders decide what an operator sees before they have picked anything
to investigate, so the properties worth pinning are the ones that would mislead
if they broke: a severity label that contradicts the number printed beside it,
and a depth that puts a node to the left of something it depends on.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from cauzon.datahub_client import MockDataHubClient  # noqa: E402
from cauzon.overview import (  # noqa: E402
    _severity,
    build_catalog_map,
    build_inbox,
)


# --------------------------------------------------------------------------- #
# Severity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ratio, expected",
    [
        (4.0, "critical"),
        (2.0, "critical"),  # the boundary is inclusive
        (1.99, "overdue"),
        (1.01, "overdue"),
        (1.0, "failing"),  # exactly at SLA is not late
        (0.17, "failing"),
        (None, "failing"),  # no freshness data: cannot be a staleness problem
    ],
)
def test_severity_never_contradicts_its_own_ratio(ratio, expected):
    """A row labelled "overdue" must actually be past its SLA.

    This is the bug this function exists to prevent: `weekly_sales` shipped
    showing "0.17x SLA" beside the word OVERDUE, which told the operator two
    incompatible things at once.
    """
    assert _severity(ratio) == expected


# --------------------------------------------------------------------------- #
# Inbox
# --------------------------------------------------------------------------- #
def test_inbox_covers_every_open_incident():
    client = MockDataHubClient()
    entries = build_inbox(client)
    incident_urns = {i["urn"] for i in client.list_open_incidents()}

    assert {e.urn for e in entries} == incident_urns
    assert len(entries) == len(incident_urns), "no incident may be dropped or doubled"


def test_inbox_labels_match_the_ratios_it_reports():
    """The whole queue, not just the function in isolation."""
    for entry in build_inbox(MockDataHubClient()):
        if entry.severity == "failing":
            assert entry.overdue_ratio is None or entry.overdue_ratio <= 1.0
        else:
            assert entry.overdue_ratio is not None and entry.overdue_ratio > 1.0
            assert (entry.overdue_ratio >= 2.0) == (entry.severity == "critical")


def test_inbox_puts_critical_first():
    entries = build_inbox(MockDataHubClient())
    ranks = [0 if e.severity == "critical" else 1 for e in entries]
    assert ranks == sorted(ranks), "a critical row must not sit below a lesser one"


def test_inbox_counts_downstream_so_the_operator_can_see_what_is_at_stake():
    entries = {e.urn: e for e in build_inbox(MockDataHubClient())}
    revenue = next(e for u, e in entries.items() if "daily_revenue" in u)
    assert revenue.downstream_count > 0
    assert revenue.owner, "an assignable row needs an owner"


def test_inbox_survives_a_client_that_cannot_answer():
    """A metadata read failing must degrade one row, not empty the queue."""

    class Flaky(MockDataHubClient):
        def get_entity(self, urn: str):
            raise RuntimeError("catalog unavailable")

    entries = build_inbox(Flaky())
    assert entries, "the incident list still returned; the queue must not vanish"
    assert all(e.severity == "failing" for e in entries)
    assert all(e.freshness_hours is None for e in entries)


# --------------------------------------------------------------------------- #
# Catalog map
# --------------------------------------------------------------------------- #
def test_map_places_every_node_right_of_its_parents():
    """The layout claim the view makes: upstream is a direction, not a trace."""
    data = build_catalog_map(MockDataHubClient())
    depth = {n.urn: n.depth for n in data.nodes}

    assert data.nodes, "the mock catalog is not empty"
    for edge in data.edges:
        assert depth[edge["from"]] < depth[edge["to"]], (
            f"{edge['from']} (depth {depth[edge['from']]}) must draw left of "
            f"{edge['to']} (depth {depth[edge['to']]})"
        )


def test_map_edges_only_reference_nodes_it_returned():
    data = build_catalog_map(MockDataHubClient())
    urns = {n.urn for n in data.nodes}
    for edge in data.edges:
        assert edge["from"] in urns and edge["to"] in urns


def test_map_marks_open_incidents_as_incidents():
    client = MockDataHubClient()
    data = build_catalog_map(client)
    incident_urns = {i["urn"] for i in client.list_open_incidents()}

    for node in data.nodes:
        if node.urn in incident_urns:
            assert node.health == "incident"

    counts = data.to_dict()["counts"]
    assert counts["incident"] == len(incident_urns)
    assert counts["total"] == len(data.nodes)


def test_map_flags_the_decoy_as_carrying_a_signal_without_an_incident():
    """`marketing_spend` is stale but not the cause of anything.

    It is in the fixture precisely so the proof gate has something to reject, and
    the map must show it as a signal rather than an incident — otherwise the view
    invents an incident the catalog never reported.
    """
    data = build_catalog_map(MockDataHubClient())
    decoy = next(n for n in data.nodes if "marketing_spend" in n.urn)
    assert decoy.health == "overdue"
    assert decoy.signals


def test_map_tolerates_a_client_with_no_asset_listing():
    """A real DataHub client without `list_assets` must return empty, not raise."""

    class Minimal:
        def list_open_incidents(self):
            return []

    data = build_catalog_map(Minimal())
    assert data.nodes == [] and data.edges == []
    assert data.to_dict()["counts"]["total"] == 0
