"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import LineageSpine from "@/components/LineageSpine";
import {
  AssertionPanel,
  BlastRadiusPanel,
  ConfidencePanel,
  EvidencePanel,
  FixPanel,
  GroundingBadge,
  Panel,
  ProofPanel,
  Prose,
  RecurrencePanel,
  TimelinePanel,
  TraceTimeline,
  WritebackPanel,
} from "@/components/panels";
import { buildSpine } from "@/lib/spine";
import {
  LIVE_CATALOG_AVAILABLE,
  useInvestigation,
  type Catalog,
} from "@/lib/useInvestigation";
import {
  datahubAssetUrl,
  type Health,
  type LiveSource,
  type SpineNode,
} from "@/lib/types";

export default function InvestigatePage() {
  const {
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
  } = useInvestigation();
  const [inspected, setInspected] = useState<SpineNode | null>(null);

  const model = useMemo(() => buildSpine(trace, diagnosis), [trace, diagnosis]);
  const rejected = diagnosis?.ranked_candidates.filter((c) => c.rejected_reason) ?? [];

  return (
    <div className="mx-auto max-w-[1180px] px-5 pb-24 sm:px-8">
      <Header source={source} health={health} />

      <main id="main" className="space-y-4">
        {LIVE_CATALOG_AVAILABLE && (
          <CatalogSwitch value={catalog} onChange={setCatalog} />
        )}

        {health?.live_source && <LiveSourceNote source={health.live_source} />}

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

          {health?.write_back_allowed && (
            <label className="mt-4 flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                checked={writeBack}
                onChange={(e) => setWriteBack(e.target.checked)}
                className="mt-0.5 h-3.5 w-3.5 accent-[var(--color-jade)]"
              />
              <span className="text-[12px] leading-snug text-bone-dim">
                Write the finding back to the catalog
                {health.datahub_backend === "mcp" && (
                  <span className="mt-1 block text-muted">
                    This tags a real asset and files a real document in DataHub.
                    Leave it off to investigate without changing anything.
                  </span>
                )}
              </span>
            </label>
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
                  <p className="prose-evidence m-0 mt-1">
                    <Prose text={candidate.rejected_reason!} />
                  </p>
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
                {health?.datahub_ui_url && (
                  <a
                    href={datahubAssetUrl(health.datahub_ui_url, diagnosis.root_cause.urn)}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-block text-[11px] tracking-[0.1em] text-bone-dim uppercase no-underline hover:text-jade"
                  >
                    Verify in DataHub →
                  </a>
                )}
                {diagnosis.narrative && (
                  <p className="prose-evidence mt-3 mb-0">
                    <Prose text={diagnosis.narrative} />
                  </p>
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

        {diagnosis && (diagnosis.timeline?.length ?? 0) > 0 && (
          <Panel
            title="How it propagated"
            aside={<span className="label">{diagnosis.timeline!.length} steps</span>}
          >
            <TimelinePanel events={diagnosis.timeline!} />
          </Panel>
        )}

        {diagnosis?.blast_radius && (
          <Panel
            title="Blast radius"
            aside={
              diagnosis.blast_radius.silent_count > 0 ? (
                <span className="label text-oxide">
                  {diagnosis.blast_radius.silent_count} not alerting
                </span>
              ) : null
            }
          >
            <BlastRadiusPanel blast={diagnosis.blast_radius} />
          </Panel>
        )}

        {diagnosis?.proposed_assertion && (
          <Panel
            title="Missing guardrail"
            aside={<span className="label">would have caught this at the source</span>}
          >
            <AssertionPanel proposal={diagnosis.proposed_assertion} />
          </Panel>
        )}

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
            <WritebackPanel
              writes={diagnosis.write_backs}
              datahubUiUrl={health?.datahub_ui_url ?? null}
            />
          </Panel>
        )}
      </main>

      <Footer />
    </div>
  );
}

function Header({
  source,
  health,
}: {
  source: "probing" | "live" | "replay";
  health: Health | null;
}) {
  // Three distinct truths, and the UI should not blur them: is a backend there,
  // is the agent really executing, and is the catalog real.
  const { label, tone } =
    source === "probing"
      ? { label: "Connecting…", tone: "bg-muted" }
      : source === "replay"
        ? { label: "Recorded agent run", tone: "bg-amber" }
        : health?.datahub_backend === "mcp"
          ? { label: "Live agent · real DataHub", tone: "bg-jade" }
          : health?.datahub_backend === "live"
            ? { label: "Live agent · live public catalog", tone: "bg-jade" }
            : { label: "Live agent · demo catalog", tone: "bg-jade" };

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
      <div className="flex items-center gap-2" title={sourceHint(source, health)}>
        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${tone}`} />
        <span className="label">{label}</span>
      </div>
    </header>
  );
}

/**
 * Flip between the planted graph and a real public catalog.
 *
 * Same agent behind both. The demo graph is deterministic and carries the
 * ungroundable decoy; the live one has real freshness and a queue that changes
 * on its own. Seeing the identical reasoning on both is more convincing than
 * either alone.
 */
function CatalogSwitch({
  value,
  onChange,
}: {
  value: Catalog;
  onChange: (next: Catalog) => void;
}) {
  const options: { id: Catalog; label: string; hint: string }[] = [
    { id: "demo", label: "Demo catalog", hint: "Three planted faults, deterministic" },
    { id: "live", label: "Live public catalog", hint: "NYC Open Data, real freshness" },
  ];
  return (
    <div role="group" aria-label="Catalog" className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = value === option.id;
        return (
          <button
            key={option.id}
            onClick={() => onChange(option.id)}
            aria-pressed={active}
            className={`flex-1 border px-4 py-3 text-left transition-colors ${
              active
                ? "border-jade-dim bg-jade-dim/25"
                : "border-line hover:border-line-bright"
            }`}
          >
            <span
              className={`block text-[12px] font-semibold tracking-[0.1em] uppercase ${
                active ? "text-jade" : "text-bone-dim"
              }`}
            >
              {option.label}
            </span>
            <span className="mt-1 block text-[11px] text-muted">{option.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Names exactly which half of a live catalog is real.
 *
 * Freshness here is read from the source of truth on every refresh; the lineage
 * is ours, because Socrata publishes none. A tool whose argument is "only claim
 * what you can prove" has to be the one thing that does not blur that.
 */
function LiveSourceNote({ source }: { source: LiveSource }) {
  return (
    <section className="plate border-l-2 border-l-jade-dim px-5 py-4">
      <p className="label m-0">Live catalog</p>
      <p className="prose-evidence m-0 mt-2">
        Assets and freshness are read live from{" "}
        <a
          href={source.url}
          target="_blank"
          rel="noreferrer"
          className="text-bone-dim underline decoration-line-bright hover:text-jade"
        >
          {source.name}
        </a>
        , so the incidents below are whatever is genuinely past its update SLA
        right now — the list changes as the city publishes.{" "}
        <span className="text-muted">
          Lineage is declared by this project, because that catalog publishes
          none, and there is no query history to evidence a transform — findings
          land on <em>path proven, transform unavailable</em> rather than
          claiming more. It is read-only, so nothing is written back.
        </span>
      </p>
      {source.fetch_error && (
        <p className="prose-evidence m-0 mt-2 text-oxide">
          Last refresh failed ({source.fetch_error}) — showing the previous
          snapshot, which may be out of date.
        </p>
      )}
    </section>
  );
}

function sourceHint(source: string, health: Health | null): string {
  if (source === "replay")
    return "No backend reachable, so this replays a recorded run of the real agent. Start the backend to investigate live.";
  if (source === "live") {
    if (health?.datahub_backend === "mcp")
      return "The agent is executing live against a real DataHub instance.";
    if (health?.datahub_backend === "live")
      return `Assets and freshness are read live from ${health.live_source?.name}. Lineage is declared by this project, because that catalog publishes none.`;
    return "The agent is executing live against the planted demo catalog. The agent code path is identical against a real DataHub.";
  }
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
        href="https://github.com/bkd-dotcom/cauzon"
        className="text-xs text-bone-dim no-underline hover:text-jade"
      >
        Source
      </a>
    </footer>
  );
}
