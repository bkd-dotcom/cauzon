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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Make the sibling `agent/` package importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from cauzon.agent import CauzonAgent  # noqa: E402
from cauzon.datahub_client import (  # noqa: E402
    MockDataHubClient,
    all_mock_incidents,
    scenario_for_symptom,
)
from cauzon.live_client import LiveDataHubClient  # noqa: E402
from cauzon.models import Incident, TraceEvent  # noqa: E402

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
