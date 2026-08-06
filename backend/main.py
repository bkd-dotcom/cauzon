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


def _using_mock() -> bool:
    return os.getenv("CAUZON_DATAHUB_BACKEND", "mock") == "mock"


def _agent(urn: str | None = None) -> CauzonAgent:
    """Fresh agent per request, so captured write-backs stay isolated.

    On the mock backend the API serves all three planted incidents at once, so
    the agent is pinned to whichever scenario owns the symptom being
    investigated rather than to the process-wide env var.
    """
    if urn and _using_mock():
        scenario = scenario_for_symptom(urn)
        if scenario:
            return CauzonAgent(client=MockDataHubClient(scenario=scenario))
    return CauzonAgent()


@app.get("/api/health")
def health() -> dict[str, str]:
    backend = os.getenv("CAUZON_DATAHUB_BACKEND", "mock")
    return {"status": "ok", "datahub_backend": backend}


@app.get("/api/incidents")
def list_incidents() -> list[dict[str, Any]]:
    # The mock backend has one incident per scenario; surface the whole queue so
    # every fault type is reachable without restarting the server.
    if _using_mock():
        return all_mock_incidents()
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
        write_back=req.write_back,
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
                agent.investigate, incident, on_event, req.get("write_back", True)
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
