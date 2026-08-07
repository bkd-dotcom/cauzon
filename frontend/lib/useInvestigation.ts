"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { mockIncidents, replayInvestigation } from "./mockInvestigation";
import type { Diagnosis, Health, Incident, TraceEvent } from "./types";

/**
 * Two backends, both optional.
 *
 * `demo` runs the planted three-fault graph — deterministic, always available,
 * and the one that carries the decoy. `live` reads a real public catalog, where
 * the incident list is whatever is genuinely stale. Same agent behind both;
 * letting a reader flip between them is the point.
 */
export type Catalog = "demo" | "live";

const API_DEMO = process.env.NEXT_PUBLIC_CAUZON_API ?? "http://localhost:8000";
const API_LIVE = process.env.NEXT_PUBLIC_CAUZON_API_LIVE ?? "";

export const LIVE_CATALOG_AVAILABLE = Boolean(API_LIVE);

function baseFor(catalog: Catalog): string {
  return catalog === "live" && API_LIVE ? API_LIVE : API_DEMO;
}

/** Exported so the overview page reads the same backends as the investigation. */
export const apiBaseFor = baseFor;

/**
 * `live` talks to the FastAPI backend (and therefore, optionally, a real
 * DataHub). `replay` runs entirely in the browser off recorded agent output, so
 * the deployed demo works with nothing installed.
 */
export type Source = "probing" | "live" | "replay";

export interface InvestigationState {
  source: Source;
  catalog: Catalog;
  /** Switching re-probes the other backend and resets any in-flight run. */
  setCatalog: (catalog: Catalog) => void;
  /** Non-null in live mode: what the backend says it is connected to. */
  health: Health | null;
  writeBack: boolean;
  setWriteBack: (value: boolean) => void;
  incidents: Incident[];
  selected: Incident | null;
  select: (incident: Incident) => void;
  run: () => void;
  running: boolean;
  trace: TraceEvent[];
  diagnosis: Diagnosis | null;
}

export function useInvestigation(options?: {
  /** Preselect this asset once the queue loads (deep link from the inbox). */
  initialUrn?: string | null;
  initialCatalog?: Catalog | null;
}): InvestigationState {
  const [catalog, setCatalogState] = useState<Catalog>(
    options?.initialCatalog === "live" ? "live" : "demo",
  );
  const [source, setSource] = useState<Source>("probing");
  const [health, setHealth] = useState<Health | null>(null);
  const [writeBack, setWriteBack] = useState(true);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [running, setRunning] = useState(false);

  const cancelRef = useRef<(() => void) | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  // Two-stage probe, so a free-tier backend that scales to zero still gets used.
  //
  // A short first probe keeps a purely static deploy snappy: no backend means
  // replay appears immediately rather than after a spinner. But a scale-to-zero
  // host (Cloud Run without min-instances, a sleeping Space) can take several
  // seconds to wake, and giving up at 1.5s would mean a live backend that is
  // deployed and never once used. So the probe keeps going in the background and
  // upgrades replay -> live if the backend answers late.
  useEffect(() => {
    let cancelled = false;
    const API = baseFor(catalog);

    const load = async (timeoutMs: number): Promise<Health | null> => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(`${API}/api/health`, { signal: controller.signal });
        if (!res.ok) return null;
        const info = (await res.json()) as Health;
        const incidentsRes = await fetch(`${API}/api/incidents`, {
          signal: controller.signal,
        });
        if (!incidentsRes.ok) return null;
        const queue = (await incidentsRes.json()) as Incident[];
        if (cancelled) return null;

        setHealth(info);
        // Against a real, shared catalog, default to not writing. A visitor
        // should have to opt in before mutating someone's metadata.
        setWriteBack(info.datahub_backend === "mock" && info.write_back_allowed);
        setSource("live");
        setIncidents(queue);
        // Only reselect while nothing is in flight, so a late upgrade cannot
        // yank an investigation the user is already watching.
        setSelected((current) => {
          if (current) return queue.find((i) => i.urn === current.urn) ?? current;
          // Honour a deep link, but never invent a selection for a urn this
          // catalog does not have.
          const requested = options?.initialUrn
            ? queue.find((i) => i.urn === options.initialUrn)
            : undefined;
          return requested ?? queue[0] ?? null;
        });
        return info;
      } catch {
        return null;
      } finally {
        clearTimeout(timer);
      }
    };

    (async () => {
      if (await load(1500)) return;
      if (cancelled) return;

      // Fall back to replay now, so the page is usable immediately.
      const fixtures = mockIncidents();
      setSource((current) => (current === "live" ? current : "replay"));
      setIncidents((current) => (current.length ? current : fixtures));
      setSelected((current) => current ?? fixtures[0] ?? null);

      // Then keep trying. A waking instance often *refuses* the connection
      // rather than holding it open, so a single immediate retry fails too —
      // this needs spacing, not just a longer timeout.
      for (let attempt = 0; attempt < 10 && !cancelled; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 2500));
        if (cancelled) return;
        if (await load(8000)) return;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [catalog]);

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

    const API = baseFor(catalog);
    const body = JSON.stringify({ ...selected, write_back: writeBack });

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
  }, [catalog, selected, source, teardown, writeBack]);

  const setCatalog = useCallback(
    (next: Catalog) => {
      if (next === catalog) return;
      teardown();
      setCatalogState(next);
      // Reset everything: results from one catalog must never be shown under
      // the other's label.
      setSource("probing");
      setHealth(null);
      setIncidents([]);
      setSelected(null);
      setTrace([]);
      setDiagnosis(null);
      setRunning(false);
    },
    [catalog, teardown],
  );

  return {
    source,
    catalog,
    setCatalog,
    health,
    writeBack,
    setWriteBack,
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
