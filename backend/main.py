"""FastAPI backend for Cauzon.

Exposes:
  GET  /api/incidents                 -> list open incidents
  POST /api/investigate               -> run investigation, return Diagnosis (JSON)
  WS   /ws/investigate                -> stream TraceEvents live, then the Diagnosis

The agent core lives in the `cauzon` package (../agent). This layer only
handles transport + serialisation so the same agent powers CLI, web, and mobile.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Make the sibling `agent/` package importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from cauzon.agent import CauzonAgent  # noqa: E402
from cauzon.correlate import correlate  # noqa: E402
from cauzon.datahub_client import (  # noqa: E402
    MOCK_SCENARIOS,
    MCPDataHubClient,
    MockDataHubClient,
    all_mock_incidents,
    scenario_for_symptom,
)
from cauzon.live_client import LiveDataHubClient  # noqa: E402
from cauzon.live_source import LivenessProbe  # noqa: E402
from cauzon.models import Capabilities, Incident, TraceEvent  # noqa: E402
from cauzon.overview import (  # noqa: E402
    CatalogMap,
    build_catalog_map,
    build_inbox,
    inbox_sort_key,
)
from cauzon.zone_volume import ZONE_DATASET_ID, ZoneVolume  # noqa: E402

app = FastAPI(title="Cauzon API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CAUZON_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class InvestigateRequest(BaseModel):
    urn: str
    title: str
    description: str = ""
    failed_assertion: str | None = None
    detected_at: str | None = None
    write_back: bool = True


def _backend_kind() -> str:
    """`mock`, `live` (public NYC Open Data), or `mcp` (a real DataHub)."""
    return os.getenv("CAUZON_DATAHUB_BACKEND", "mock").strip().lower()


def _using_mock() -> bool:
    return _backend_kind() == "mock"


def _using_live() -> bool:
    return _backend_kind() == "live"


# One client for the live source per process, so its TTL cache is shared rather
# than refetching the catalog on every request.
_live_client: LiveDataHubClient | None = None


def _live() -> LiveDataHubClient:
    global _live_client
    if _live_client is None:
        _live_client = LiveDataHubClient()
    return _live_client


def _writeback_allowed() -> bool:
    """Whether this deployment may mutate its catalog.

    The mock catalog is in-memory per request, so there is nothing to protect.
    A **real** DataHub is shared and durable: a public deployment where anyone can
    press Investigate would accumulate duplicate dossiers, so write-back against
    `mcp` is opt-in via CAUZON_ALLOW_WRITEBACK. Set it deliberately, once.
    """
    if _using_mock():
        return True
    if _using_live():
        # NYC Open Data is read-only. Declining is honest; offering a button that
        # silently does nothing is not.
        return False
    return os.getenv("CAUZON_ALLOW_WRITEBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _datahub_ui_url() -> str | None:
    """Base URL of the DataHub UI, so findings can be verified at the source."""
    url = os.getenv("CAUZON_DATAHUB_UI_URL", "").strip()
    return url.rstrip("/") or None


def _agent(urn: str | None = None) -> CauzonAgent:
    """Fresh agent per request, so captured write-backs stay isolated.

    On the mock backend the API serves all three planted incidents at once, so
    the agent is pinned to whichever scenario owns the symptom being
    investigated rather than to the process-wide env var.
    """
    if _using_live():
        return CauzonAgent(client=_live())
    if urn and _using_mock():
        scenario = scenario_for_symptom(urn)
        if scenario:
            return CauzonAgent(client=MockDataHubClient(scenario=scenario))
    return CauzonAgent()


def _capabilities() -> Capabilities:
    """What the configured backend can answer.

    Read off the client *class*, not an instance. `capabilities` is a class
    attribute precisely so this costs nothing: instantiating `MCPDataHubClient`
    opens an SDK connection to DataHub, and /api/health is polled by the frontend's
    wake-up probe.
    """
    return getattr(_client_class(), "capabilities", Capabilities())


def _client_class() -> type:
    if _using_live():
        return LiveDataHubClient
    if _using_mock():
        return MockDataHubClient
    return MCPDataHubClient


@app.get("/api/health")
def health() -> dict[str, Any]:
    """What this deployment actually is.

    The UI reads every field here and states it plainly. A tool whose entire
    argument is "only claim what you can prove" should not be vague about whether
    its own catalog is real.
    """
    body: dict[str, Any] = {
        "status": "ok",
        "datahub_backend": _backend_kind(),
        "write_back_allowed": _writeback_allowed(),
        "datahub_ui_url": _datahub_ui_url(),
        # Which findings this catalog can support, and why not where it cannot. The
        # UI names the unavailable ones: four post-verdict findings used to depend
        # on metadata only the demo fixtures set, so on a real catalog they came
        # back empty and read as "nothing to report".
        "capabilities": _capabilities().to_dict(),
    }
    if _using_live():
        # Say exactly which parts of this catalog are real. Signals are; lineage
        # is declared by us. Overstating that would contradict the product.
        body["live_source"] = {
            "name": "NYC Open Data (Socrata)",
            "url": "https://data.cityofnewyork.us",
            "signals_are_live": True,
            "lineage_is_declared": True,
            "supports_writeback": False,
            "fetch_error": _live().source_error,
        }
    return body


@app.get("/api/incidents")
def list_incidents() -> list[dict[str, Any]]:
    # The mock backend has one incident per scenario; surface the whole queue so
    # every fault type is reachable without restarting the server.
    if _using_mock():
        return all_mock_incidents()
    if _using_live():
        # However many are genuinely past their SLA right now — not a fixed set.
        return _live().list_open_incidents()
    return _agent().client.list_open_incidents()


def _catalog_clients() -> list[Any]:
    """Clients covering everything the incident queue exposes.

    A mock client is pinned to one scenario, but the queue serves all three, so
    the map and the inbox have to span all three too — otherwise the overview
    contradicts the list it sits above. The scenario graphs are disjoint, so the
    map simply shows three clusters.
    """
    if _using_live():
        return [_live()]
    if _using_mock():
        # One client per distinct graph, not per scenario name. Two scenarios share
        # the shared_cause graph — two teams alerting on the same outage — so
        # keying on the name would walk that graph twice and report the same
        # correlation and the same map nodes twice over.
        clients: list[Any] = []
        seen_graphs: set[frozenset[str]] = set()
        for name in MOCK_SCENARIOS:
            client = MockDataHubClient(scenario=name)
            # Keyed on the asset set, not on object identity: the client
            # deep-copies its graph, so two clients over the same scenario graph
            # hold equal-but-distinct dicts.
            key = frozenset(client._graph)
            if key in seen_graphs:
                continue
            seen_graphs.add(key)
            clients.append(client)
        return clients
    return [_agent().client]


@app.get("/api/inbox")
def inbox() -> list[dict[str, Any]]:
    """Open incidents enriched for triage, worst-overdue first."""
    entries = [e for client in _catalog_clients() for e in build_inbox(client)]
    # The builder's own key, not a copy of it: entries from several clients have to
    # be re-sorted after merging, and two copies of this tuple could drift apart.
    entries.sort(key=inbox_sort_key, reverse=True)
    return [entry.to_dict() for entry in entries]


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    """Every asset and edge, with health marked — the catalog map."""
    nodes: list[Any] = []
    edges: list[dict[str, str]] = []
    for client in _catalog_clients():
        part = build_catalog_map(client)
        nodes.extend(part.nodes)
        edges.extend(part.edges)
    nodes.sort(key=lambda n: (n.depth, n.name))
    return CatalogMap(nodes=nodes, edges=edges).to_dict()


# One instance per process so the hour-long cache is actually shared across
# requests. The aggregation takes a few seconds; doing it per request would make
# the map feel broken.
_zone_volume = ZoneVolume()


# Its own short TTL, deliberately not the catalog's 15 minutes — see LivenessProbe.
_probe = LivenessProbe()


@app.get("/api/live-check")
def live_check() -> dict[str, Any]:
    """How long ago the live feed actually published, read fresh.

    The rest of the live catalog is years stale, which makes the point about
    incidents and leaves an obvious objection: if everything is overdue, how would
    anyone know the freshness signal reads a real clock rather than always firing?

    This answers it with one asset that genuinely moves. Reload and the number
    changes; it is not a cached figure from the page build.
    """
    if not _using_live():
        raise HTTPException(
            status_code=404,
            detail=(
                "The liveness check reads NYC Open Data directly, so it is only "
                "available on the live catalog backend."
            ),
        )
    return {**_probe.read(), "checked_at_epoch": time.time()}


@app.get("/api/zones")
def zones() -> dict[str, Any]:
    """Real pickup volume per taxi zone, aggregated by Socrata.

    Only the live backend can answer this: the numbers come from the same city
    dataset the live catalog reports on. The mock backend says so rather than
    inventing traffic, because a fabricated choropleth would undercut the one
    thing the map is for.
    """
    if not _using_live():
        raise HTTPException(
            status_code=404,
            detail=(
                "Zone volume is only available on the live catalog backend, "
                "which reads it from NYC Open Data."
            ),
        )
    snapshot = _zone_volume.snapshot()
    return {
        **snapshot,
        "zone_dataset_id": ZONE_DATASET_ID,
        "zone_source_url": f"https://data.cityofnewyork.us/d/{ZONE_DATASET_ID}",
    }


@app.get("/api/correlate")
def correlate_incidents() -> list[dict[str, Any]]:
    """Open incidents that share one provable upstream cause.

    Correlated within each catalog rather than across all of them: a cause has to
    be upstream of its symptoms, and the mock's scenario graphs are disjoint, so
    cross-graph comparison could only ever produce a false positive.

    An empty list is a real answer — it means these are separate failures.
    """
    out: list[dict[str, Any]] = []
    for client in _catalog_clients():
        try:
            incidents = client.list_open_incidents()
        except Exception:
            continue
        for correlation in correlate(client, incidents):
            out.append(correlation.to_dict())
    out.sort(key=lambda c: c["count"], reverse=True)
    return out


class SweepRequest(BaseModel):
    """A sweep writes to a catalog, so its inputs are bounded deliberately."""

    limit: int = 10
    write_back: bool = True


def _sweep_token() -> str:
    return os.getenv("CAUZON_SWEEP_TOKEN", "").strip()


@app.post("/api/sweep")
def sweep(req: SweepRequest, x_cauzon_sweep_token: str = Header(default="")) -> dict[str, Any]:
    """Investigate the open queue unprompted, and file what it can prove.

    This is the difference between a tool and an agent: everything else here runs
    because somebody clicked. A scheduler calls this.

    Two things it deliberately does not do:

    * **Default open.** It requires CAUZON_SWEEP_TOKEN, and *refuses when the
      variable is unset* rather than treating "no token configured" as "no token
      required". A sweep writes dossiers into a shared catalog; an unauthenticated
      trigger for that is not acceptable even on a demo deployment.
    * **Persist anything of its own.** There is no database here, and adding one to
      hold agent output would be the wrong shape — the catalog *is* the store. So a
      sweep's durable product is the dossiers it writes back, and where the backend
      cannot accept writes it says so instead of implying the run was saved.
    """
    expected = _sweep_token()
    if not expected:
        raise HTTPException(
            status_code=403,
            detail=(
                "Sweeps are disabled: CAUZON_SWEEP_TOKEN is not set. A sweep files "
                "dossiers into the catalog, so it is opt-in rather than open by "
                "default."
            ),
        )
    if x_cauzon_sweep_token != expected:
        raise HTTPException(status_code=401, detail="Invalid sweep token.")

    limit = max(1, min(req.limit, 25))
    allowed = _writeback_allowed() and req.write_back

    investigated: list[dict[str, Any]] = []
    written = 0
    for client in _catalog_clients():
        for entry in sorted(
            build_inbox(client), key=inbox_sort_key, reverse=True
        )[:limit]:
            agent = CauzonAgent(client=client)
            diagnosis = agent.investigate(
                Incident(
                    urn=entry.urn,
                    title=entry.title or entry.name,
                    description="",
                    failed_assertion=entry.failed_assertion,
                    detected_at=entry.detected_at,
                ),
                write_back=allowed,
            )
            writes = getattr(client, "writes", [])
            written += len(writes)
            investigated.append(
                {
                    "urn": entry.urn,
                    "name": entry.name,
                    "severity": entry.severity,
                    "root_cause": diagnosis.root_cause.name if diagnosis.root_cause else None,
                    "grounding": diagnosis.grounding.value,
                    "confidence": diagnosis.confidence,
                    "write_backs": len(writes),
                }
            )

    grounded = [r for r in investigated if r["root_cause"]]
    correlations = correlate_incidents()

    return {
        "investigated": len(investigated),
        "grounded": len(grounded),
        "escalated": len(investigated) - len(grounded),
        "correlations": len(correlations),
        "write_backs": written,
        # Said plainly rather than left to be inferred from a zero.
        "persisted": bool(allowed and written),
        "persistence_note": (
            "Dossiers were filed into the catalog."
            if allowed and written
            else "Nothing was persisted: this backend does not accept write-back, "
            "so the report below is the only record of this run."
        ),
        "results": investigated,
        "shared_causes": correlations,
    }


@app.post("/api/investigate")
def investigate(req: InvestigateRequest) -> dict[str, Any]:
    agent = _agent(req.urn)
    incident = Incident(
        urn=req.urn,
        title=req.title,
        description=req.description,
        failed_assertion=req.failed_assertion,
        detected_at=req.detected_at,
    )
    trace: list[dict[str, Any]] = []
    diagnosis = agent.investigate(
        incident,
        on_event=lambda ev: trace.append(ev.to_dict()),
        # A client may decline write-back but cannot grant itself permission the
        # deployment withheld.
        write_back=req.write_back and _writeback_allowed(),
    )
    result = diagnosis.to_dict()
    result["trace"] = trace
    # Surface captured write-backs (mock backend) so the UI can show them.
    result["write_backs"] = getattr(agent.client, "writes", [])
    return result


@app.websocket("/ws/investigate")
async def ws_investigate(ws: WebSocket) -> None:
    await ws.accept()
    try:
        req = await ws.receive_json()
        agent = _agent(req.get("urn"))
        incident = Incident(
            urn=req["urn"],
            title=req.get("title", ""),
            description=req.get("description", ""),
            failed_assertion=req.get("failed_assertion"),
            detected_at=req.get("detected_at"),
        )
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue()

        def on_event(ev: TraceEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        # Run the (sync) agent in a thread so we can stream events concurrently.
        async def run() -> Any:
            diag = await asyncio.to_thread(
                agent.investigate,
                incident,
                on_event,
                bool(req.get("write_back", True)) and _writeback_allowed(),
            )
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel
            return diag

        task = asyncio.create_task(run())
        while True:
            ev = await queue.get()
            if ev is None:
                break
            await ws.send_json({"type": "trace", "event": ev.to_dict()})

        diagnosis = await task
        payload = diagnosis.to_dict()
        payload["write_backs"] = getattr(agent.client, "writes", [])
        await ws.send_json({"type": "diagnosis", "diagnosis": payload})
    except WebSocketDisconnect:
        return
    finally:
        try:
            await ws.close()
        except Exception:
            pass
