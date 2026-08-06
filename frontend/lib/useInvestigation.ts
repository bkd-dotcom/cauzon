"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { mockIncidents, replayInvestigation } from "./mockInvestigation";
import type { Diagnosis, Incident, TraceEvent } from "./types";

const API = process.env.NEXT_PUBLIC_CAUZON_API ?? "http://localhost:8000";

/**
 * `live` talks to the FastAPI backend (and therefore, optionally, a real
 * DataHub). `replay` runs entirely in the browser off recorded agent output, so
 * the deployed demo works with nothing installed.
 */
export type Source = "probing" | "live" | "replay";

export interface InvestigationState {
  source: Source;
  incidents: Incident[];
  selected: Incident | null;
  select: (incident: Incident) => void;
  run: () => void;
  running: boolean;
  trace: TraceEvent[];
  diagnosis: Diagnosis | null;
}

export function useInvestigation(): InvestigationState {
  const [source, setSource] = useState<Source>("probing");
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [running, setRunning] = useState(false);

  const cancelRef = useRef<(() => void) | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  // Decide once, on mount, whether a backend is actually there. A short timeout
  // keeps the static deploy from stalling on a localhost URL that will never
  // answer.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1500);

    fetch(`${API}/api/health`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("unhealthy"))))
      .then(() => fetch(`${API}/api/incidents`))
      .then((r) => r.json())
      .then((data: Incident[]) => {
        if (cancelled) return;
        setSource("live");
        setIncidents(data);
        setSelected(data[0] ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        const fixtures = mockIncidents();
        setSource("replay");
        setIncidents(fixtures);
        setSelected(fixtures[0] ?? null);
      })
      .finally(() => clearTimeout(timeout));

    return () => {
      cancelled = true;
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  const teardown = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  useEffect(() => teardown, [teardown]);

  const select = useCallback(
    (incident: Incident) => {
      teardown();
      setSelected(incident);
      setTrace([]);
      setDiagnosis(null);
      setRunning(false);
    },
    [teardown],
  );

  const run = useCallback(() => {
    if (!selected) return;
    teardown();
    setTrace([]);
    setDiagnosis(null);
    setRunning(true);

    if (source === "replay") {
      cancelRef.current = replayInvestigation(
        selected.urn,
        (event) => setTrace((prev) => [...prev, event]),
        (result) => {
          setDiagnosis(result);
          setRunning(false);
        },
      );
      return;
    }

    const body = JSON.stringify({ ...selected, write_back: true });

    const viaPost = () => {
      fetch(`${API}/api/investigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      })
        .then((r) => r.json())
        .then((result: Diagnosis) => {
          setTrace(result.trace ?? []);
          setDiagnosis(result);
        })
        .catch(() => undefined)
        .finally(() => setRunning(false));
    };

    // Prefer the WebSocket so the trace streams as the agent reasons; fall back
    // to a single POST if the socket cannot be established.
    let settled = false;
    try {
      const socket = new WebSocket(`${API.replace(/^http/, "ws")}/ws/investigate`);
      socketRef.current = socket;

      socket.onopen = () => socket.send(body);
      socket.onmessage = (message) => {
        const payload = JSON.parse(message.data);
        if (payload.type === "trace") {
          setTrace((prev) => [...prev, payload.event as TraceEvent]);
        } else if (payload.type === "diagnosis") {
          settled = true;
          setDiagnosis(payload.diagnosis as Diagnosis);
          setRunning(false);
        }
      };
      socket.onerror = () => {
        if (settled) return;
        settled = true;
        socketRef.current = null;
        viaPost();
      };
      socket.onclose = () => {
        // A close before any diagnosis arrived means the stream failed.
        if (!settled) {
          settled = true;
          viaPost();
        }
      };
    } catch {
      viaPost();
    }
  }, [selected, source, teardown]);

  return {
    source,
    incidents,
    selected,
    select,
    run,
    running,
    trace,
    diagnosis,
  };
}

/** Phase of the most recent trace event — drives the graph's animation state. */
export function currentPhase(trace: TraceEvent[]): TraceEvent["phase"] | null {
  return trace.length ? trace[trace.length - 1].phase : null;
}
