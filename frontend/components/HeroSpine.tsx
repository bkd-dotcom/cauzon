"use client";

/**
 * The landing hero: a real investigation, replaying itself.
 *
 * Not a screenshot and not a mock-up — this is the recorded output of the actual
 * agent, replayed on the same cadence it produced. The first thing a visitor
 * sees is the highest-scoring suspect in the graph being *rejected*, which is
 * the one claim the product is making.
 */

import { useEffect, useRef, useState } from "react";

import LineageSpine from "@/components/LineageSpine";
import { buildSpine } from "@/lib/spine";
import { mockIncidents, replayInvestigation } from "@/lib/mockInvestigation";
import type { Diagnosis, TraceEvent } from "@/lib/types";

export default function HeroSpine() {
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [started, setStarted] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  // Guarding with a ref rather than the `started` state matters: if this effect
  // depended on `started`, calling setStarted would re-run it, and the cleanup
  // would cancel every replay timer before the first one fired.
  const launched = useRef(false);

  // Start when it scrolls into view, so the reveal is not already over by the
  // time anyone looks at it.
  useEffect(() => {
    const host = hostRef.current;
    if (!host || launched.current) return;

    const urn = mockIncidents()[0]?.urn;
    if (!urn) return;

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const start = () => {
      launched.current = true;
      setStarted(true);
      if (reduceMotion) {
        // Skip the staged reveal; show the finished result.
        return replayInvestigation(
          urn,
          () => undefined,
          (result) => {
            setTrace(result.trace ?? []);
            setDiagnosis(result);
          },
        );
      }
      return replayInvestigation(
        urn,
        (event) => setTrace((prev) => [...prev, event]),
        setDiagnosis,
      );
    };

    let cancelReplay: (() => void) | null = null;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        observer.disconnect();
        cancelReplay = start();
      },
      { threshold: 0.2 },
    );
    observer.observe(host);

    return () => {
      observer.disconnect();
      cancelReplay?.();
    };
  }, []);

  const model = buildSpine(trace, diagnosis);
  const latest = trace[trace.length - 1];

  return (
    <div ref={hostRef} className="plate overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <span className="label">
          daily_revenue · volume assertion failed
        </span>
        <span className="label text-jade">
          {diagnosis ? diagnosis.grounding_label : started ? "Investigating…" : "Ready"}
        </span>
      </div>

      <div className="px-2 py-4 sm:px-4">
        <LineageSpine model={model} running={started && !diagnosis} />
      </div>

      {/* One live line of the agent's own trace, so the motion has a caption. */}
      <div className="min-h-[52px] border-t border-line px-5 py-3">
        {latest ? (
          <p className="prose-evidence m-0 text-[13px] break-words">{latest.message}</p>
        ) : (
          <p className="label m-0">Scroll to run the investigation</p>
        )}
      </div>
    </div>
  );
}
