"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import LineageSpine from "@/components/LineageSpine";
import {
  ConfidencePanel,
  EvidencePanel,
  FixPanel,
  GroundingBadge,
  Panel,
  ProofPanel,
  RecurrencePanel,
  TraceTimeline,
  WritebackPanel,
} from "@/components/panels";
import { buildSpine } from "@/lib/spine";
import { useInvestigation } from "@/lib/useInvestigation";
import type { SpineNode } from "@/lib/types";

export default function InvestigatePage() {
  const {
    source,
    incidents,
    selected,
    select,
    run,
    running,
    trace,
    diagnosis,
  } = useInvestigation();
  const [inspected, setInspected] = useState<SpineNode | null>(null);

  const model = useMemo(() => buildSpine(trace, diagnosis), [trace, diagnosis]);
  const rejected = diagnosis?.ranked_candidates.filter((c) => c.rejected_reason) ?? [];

  return (
    <div className="mx-auto max-w-[1180px] px-5 pb-24 sm:px-8">
      <Header source={source} />

      <main id="main" className="space-y-4">
        {/* ---- incident queue -------------------------------------------- */}
        <Panel
          title="Open incidents"
          aside={
            <span className="label">
              {incidents.length} in queue
            </span>
          }
        >
          {incidents.length === 0 ? (
            <p className="prose-evidence m-0">Loading the incident queue…</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-3">
              {incidents.map((incident) => {
                const active = selected?.urn === incident.urn;
                return (
                  <button
                    key={incident.urn}
                    onClick={() => select(incident)}
                    aria-pressed={active}
                    className={`border p-3 text-left transition-colors ${
                      active
                        ? "border-amber-dim bg-ink-sunken"
                        : "border-line hover:border-line-bright"
                    }`}
                  >
                    <span
                      className={`block text-[13px] leading-snug font-medium ${
                        active ? "text-amber" : "text-bone"
                      }`}
                    >
                      {incident.title}
                    </span>
                    {incident.failed_assertion && (
                      <span className="mt-2 block text-[11px] leading-snug text-muted">
                        {incident.failed_assertion}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          <button
            onClick={run}
            disabled={!selected || running}
            className="mt-4 w-full border border-jade-dim bg-jade-dim/25 py-3 text-[13px] font-semibold tracking-[0.1em] text-jade uppercase transition-colors hover:bg-jade-dim/45 disabled:cursor-default disabled:opacity-40"
          >
            {running ? "Investigating…" : "Investigate"}
          </button>
        </Panel>

        {/* ---- the signature: lineage spine ------------------------------ */}
        {(trace.length > 0 || diagnosis) && (
          <Panel
            title="Lineage graph"
            aside={diagnosis ? <GroundingBadge diagnosis={diagnosis} /> : null}
          >
            <LineageSpine
              model={model}
              running={running}
              onSelect={setInspected}
              selectedUrn={inspected?.urn ?? null}
            />
            {inspected && <NodeInspector node={inspected} />}
          </Panel>
        )}

        {/* ---- the gate working ------------------------------------------ */}
        {rejected.length > 0 && (
          <Panel title="Rejected by the proof gate">
            <div className="space-y-3">
              {rejected.map((candidate) => (
                <div key={candidate.urn} className="rule pt-3 first:border-0 first:pt-0">
                  <p className="m-0 flex flex-wrap items-baseline gap-x-3">
                    <span className="text-sm font-semibold text-oxide line-through">
                      {candidate.name}
                    </span>
                    <span className="label">
                      ranked first · score {candidate.score.toFixed(1)}
                    </span>
                  </p>
                  <p className="prose-evidence m-0 mt-1">{candidate.rejected_reason}</p>
                </div>
              ))}
              <p className="prose-evidence m-0 border-t border-line pt-3 text-muted">
                Signal strength alone would have blamed this asset. Ranking is a
                hypothesis; only a reconstructable path is proof.
              </p>
            </div>
          </Panel>
        )}

        {/* ---- trace + verdict ------------------------------------------- */}
        <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          {trace.length > 0 && (
            <Panel title="Reasoning trace">
              <TraceTimeline trace={trace} />
            </Panel>
          )}

          {diagnosis?.root_cause && (
            <div className="min-w-0 space-y-4">
              <Panel
                title="Root cause"
                aside={<span className="label">{diagnosis.root_cause.hops_from_symptom} hops upstream</span>}
              >
                <p className="m-0 text-2xl font-semibold text-jade">
                  {diagnosis.root_cause.name}
                </p>
                {diagnosis.narrative && (
                  <p className="prose-evidence mt-3 mb-0">{diagnosis.narrative}</p>
                )}
              </Panel>
              <Panel title="Evidence">
                <EvidencePanel diagnosis={diagnosis} />
              </Panel>
            </div>
          )}
        </div>

        {diagnosis && !diagnosis.grounded && (
          <Panel title="No grounded root cause" aside={<GroundingBadge diagnosis={diagnosis} />}>
            <p className="prose-evidence m-0">
              No candidate could be connected to the symptom with a verifiable
              lineage path. Cauzon is not naming a cause and has written nothing
              to the catalog. Escalating to a human is the correct outcome here,
              not a failure.
            </p>
          </Panel>
        )}

        {diagnosis?.proof_path && (
          <Panel
            title="Proof"
            aside={<GroundingBadge diagnosis={diagnosis} />}
          >
            <ProofPanel proof={diagnosis.proof_path} />
          </Panel>
        )}

        <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          {diagnosis?.confidence_breakdown && (
            <Panel title="Confidence">
              <ConfidencePanel
                confidence={diagnosis.confidence}
                breakdown={diagnosis.confidence_breakdown}
              />
            </Panel>
          )}
          {diagnosis?.recommended_fix && (
            <Panel title="Recommended fix">
              <FixPanel fix={diagnosis.recommended_fix} />
            </Panel>
          )}
        </div>

        {diagnosis?.recurrence?.is_recurring && (
          <Panel
            title="Recurrence"
            aside={<span className="label">{diagnosis.recurrence.count} prior dossiers</span>}
          >
            <RecurrencePanel recurrence={diagnosis.recurrence} />
          </Panel>
        )}

        {diagnosis?.write_backs && diagnosis.write_backs.length > 0 && (
          <Panel title="Written back to DataHub">
            <WritebackPanel writes={diagnosis.write_backs} />
          </Panel>
        )}
      </main>

      <Footer />
    </div>
  );
}

function Header({ source }: { source: "probing" | "live" | "replay" }) {
  const label =
    source === "live"
      ? "Live backend"
      : source === "replay"
        ? "Recorded agent run"
        : "Connecting…";

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 py-6">
      <div className="flex items-baseline gap-4">
        <Link href="/" className="text-lg font-semibold tracking-tight text-bone no-underline">
          Cauzon
        </Link>
        <span className="hidden text-xs text-muted sm:inline">
          path-grounded RCA for DataHub
        </span>
      </div>
      <div className="flex items-center gap-2" title={sourceHint(source)}>
        <span
          aria-hidden
          className={`h-1.5 w-1.5 rounded-full ${
            source === "live" ? "bg-jade" : source === "replay" ? "bg-amber" : "bg-muted"
          }`}
        />
        <span className="label">{label}</span>
      </div>
    </header>
  );
}

function sourceHint(source: string): string {
  if (source === "live") return "Connected to the FastAPI backend.";
  if (source === "replay")
    return "No backend reachable, so this replays a recorded run of the real agent. Start the backend to investigate live.";
  return "Checking whether a backend is reachable.";
}

function NodeInspector({ node }: { node: SpineNode }) {
  return (
    <div className="well mt-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="text-sm font-semibold text-bone">{node.name}</span>
        <code className="text-[11px] break-all text-muted">{node.urn}</code>
      </div>
      {node.evidence.length > 0 ? (
        <ul className="m-0 mt-3 list-none space-y-2 p-0">
          {node.evidence.map((note, i) => (
            <li key={i} className="prose-evidence">
              {note}
            </li>
          ))}
        </ul>
      ) : (
        <p className="prose-evidence m-0 mt-2">
          No anomaly signal on this asset.
        </p>
      )}
      {node.rejectedReason && (
        <p className="prose-evidence m-0 mt-3 text-oxide">{node.rejectedReason}</p>
      )}
    </div>
  );
}

function Footer() {
  return (
    <footer className="rule mt-12 flex flex-wrap items-center justify-between gap-4 pt-5">
      <span className="label">Apache-2.0 · built on the DataHub MCP server</span>
      <a
        href="https://github.com/binaydalai/cauzon"
        className="text-xs text-bone-dim no-underline hover:text-jade"
      >
        Source
      </a>
    </footer>
  );
}
