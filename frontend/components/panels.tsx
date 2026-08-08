"use client";

/**
 * The reading surfaces around the graph.
 *
 * Each one answers a question a reviewer will actually ask: what did it do, what
 * did it see, what did it prove, why that confidence number, and what did it
 * change in the catalog. Nothing here restates the verdict — the graph already
 * did that.
 */

import {
  PHASE_LABELS,
  ASSERTION_KIND_LABELS,
  SIGNAL_LABELS,
  datahubAssetUrl,
  shortName,
  type BlastRadius,
  type ConfidenceBreakdown,
  type Diagnosis,
  type Phase,
  type ProofPath,
  type ProposedAssertion,
  type RecommendedFix,
  type Recurrence,
  type TimelineEvent,
  type TraceEvent,
  type WriteBack,
} from "@/lib/types";

const PHASE_TONE: Record<Phase, string> = {
  detect: "text-amber",
  scope: "text-bone-dim",
  hypothesize: "text-bone-dim",
  prove: "text-jade",
  writeback: "text-jade",
};

/**
 * Render `backticked` spans as code.
 *
 * The agent's prose is written once and consumed twice: as Markdown in the
 * dossier it writes to DataHub, and as text here. Backticks are correct in the
 * first and would show up as literal characters in the second, so the UI
 * interprets them rather than the agent maintaining two phrasings.
 */
export function Prose({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const parts = text.split("`");
  return (
    <span className={className}>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <code key={i} className="font-mono text-[0.9em] text-bone">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </span>
  );
}

export function Panel({
  title,
  aside,
  children,
  className = "",
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`plate min-w-0 ${className}`}>
      {/* flex-wrap + min-w-0 so a long title wraps instead of widening the
          panel past the viewport on a phone. */}
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-5 py-3">
        <h2 className="label min-w-0">{title}</h2>
        {aside}
      </header>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

/** Live reasoning trace. Phases are a real pipeline, so they are numbered. */
export function TraceTimeline({ trace }: { trace: TraceEvent[] }) {
  if (!trace.length) {
    return <p className="label">Awaiting first step</p>;
  }
  return (
    <ol className="m-0 list-none space-y-0 p-0">
      {trace.map((event, i) => (
        <li key={i} className="relative flex gap-4 pb-4 last:pb-0">
          {/* Connector between steps, so the trace reads as one sequence. */}
          {i < trace.length - 1 && (
            <span
              aria-hidden
              className="absolute left-[11px] top-5 h-full w-px bg-line"
            />
          )}
          <span
            aria-hidden
            className="relative z-10 mt-1 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border border-line bg-ink-sunken text-[9px] text-muted"
          >
            {String(i + 1).padStart(2, "0")}
          </span>
          <div className="min-w-0 flex-1">
            <span className={`label ${PHASE_TONE[event.phase]}`}>
              {PHASE_LABELS[event.phase]}
            </span>
            <p className="prose-evidence mt-1 mb-0 break-words">{event.message}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Evidence, showing the numbers rather than asserting a conclusion. */
export function EvidencePanel({ diagnosis }: { diagnosis: Diagnosis }) {
  const cause = diagnosis.root_cause;
  if (!cause) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {cause.signals.map((signal) => (
          <span
            key={signal}
            className="border border-line bg-ink-sunken px-2 py-1 text-[10px] tracking-[0.1em] text-bone-dim uppercase"
          >
            {SIGNAL_LABELS[signal]}
          </span>
        ))}
      </div>
      <ul className="m-0 list-none space-y-3 p-0">
        {cause.evidence_notes.map((note, i) => (
          <li key={i} className="flex gap-3">
            <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 bg-jade" />
            <Prose text={note} className="prose-evidence" />
          </li>
        ))}
      </ul>
      {cause.owner && (
        <p className="label m-0">
          Owner <span className="ml-2 text-bone-dim normal-case">{cause.owner}</span>
        </p>
      )}
    </div>
  );
}

/** Why the confidence number is what it is — every factor with its reason. */
export function ConfidencePanel({
  confidence,
  breakdown,
}: {
  confidence: number;
  breakdown: ConfidenceBreakdown | null;
}) {
  if (!breakdown) return null;
  const factors = [
    { name: "Grounding", value: breakdown.grounding_factor, reason: breakdown.grounding_reason },
    { name: "Signals", value: breakdown.signal_factor, reason: breakdown.signal_reason },
    { name: "Origin", value: breakdown.origin_factor, reason: breakdown.origin_reason },
  ];

  return (
    <div className="space-y-4">
      <p className="m-0 flex items-baseline gap-3">
        <span className="text-4xl font-semibold text-bone tabular-nums">
          {Math.round(confidence * 100)}%
        </span>
        <span className="label">
          {factors.map((f) => f.value).join(" × ")}
        </span>
      </p>
      <dl className="m-0 space-y-3">
        {factors.map((factor) => (
          <div key={factor.name} className="rule pt-3">
            <dt className="flex items-baseline justify-between gap-3">
              <span className="label">{factor.name}</span>
              <span className="text-xs text-jade tabular-nums">×{factor.value}</span>
            </dt>
            <dd className="prose-evidence m-0 mt-1">{factor.reason}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** The proof itself: the path, and the transform that carried the fault. */
export function ProofPanel({ proof }: { proof: ProofPath }) {
  const causal =
    proof.causal_edge_index !== null ? proof.edges[proof.causal_edge_index] : null;

  return (
    <div className="space-y-4">
      <ol className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-2 p-0">
        {proof.nodes.map((urn, i) => (
          <li key={urn} className="flex items-center gap-2">
            <span
              title={urn}
              className={`border px-2 py-1 text-xs ${
                i === 0
                  ? "border-jade-dim text-jade"
                  : i === proof.nodes.length - 1
                    ? "border-amber-dim text-amber"
                    : "border-line text-bone-dim"
              }`}
            >
              {shortName(urn)}
            </span>
            {i < proof.nodes.length - 1 && (
              <span aria-hidden className="text-muted">
                →
              </span>
            )}
          </li>
        ))}
      </ol>

      {/* Column-level proof, when the catalog can support it. Naming the field
          is strictly stronger than naming the table. */}
      {proof.column_path && (
        <div className="well p-3">
          <p className="label m-0 mb-2 text-jade">Field that carried the fault</p>
          <ol className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0">
            {proof.column_path.fields.map((f, i) => (
              <li key={`${f}-${i}`} className="flex items-center gap-2">
                <code
                  className={`text-xs ${
                    i === 0
                      ? "text-jade"
                      : i === proof.column_path!.fields.length - 1
                        ? "text-amber"
                        : "text-bone-dim"
                  }`}
                >
                  {f}
                </code>
                {i < proof.column_path!.fields.length - 1 && (
                  <span aria-hidden className="text-muted">
                    →
                  </span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {proof.transform_sql ? (
        <div>
          <p className="label m-0 mb-2">
            {causal
              ? `Transform on ${shortName(causal.from)} → ${shortName(causal.to)}`
              : "Transform that carried the fault"}
          </p>
          <pre className="well m-0 overflow-x-auto p-3 text-[12.5px] leading-relaxed text-bone-dim">
            {proof.transform_sql}
          </pre>
        </div>
      ) : (
        <p className="prose-evidence m-0">
          DataHub retains no query history for the causal edge, so this proves the
          path but not the transform. The finding is labelled accordingly rather
          than overclaiming.
        </p>
      )}
    </div>
  );
}

/** The next action — copyable, and derived from captured facts. */
export function FixPanel({ fix }: { fix: RecommendedFix }) {
  return (
    <div className="space-y-3">
      <p className="prose-evidence m-0">
        <Prose text={fix.summary} />
      </p>
      {fix.action && (
        <pre className="well m-0 overflow-x-auto p-3 text-[12.5px] leading-relaxed text-bone-dim">
          {fix.action}
        </pre>
      )}
      {fix.action_note && (
        <p className="prose-evidence m-0 text-muted">
          <Prose text={fix.action_note} />
        </p>
      )}
    </div>
  );
}

/** Prior dossiers for the same asset — the write-back read back. */
export function RecurrencePanel({ recurrence }: { recurrence: Recurrence }) {
  return (
    <div className="space-y-3">
      <p className="prose-evidence m-0">
        Cauzon has diagnosed this asset {recurrence.count} time
        {recurrence.count === 1 ? "" : "s"} before. Each of those dossiers was read
        back out of the catalog, not remembered — so the recommendation escalates
        from fixing this occurrence to fixing the schedule.
      </p>
      <ul className="m-0 list-none space-y-2 p-0">
        {recurrence.prior.map((prior) => (
          <li key={prior.document_urn} className="rule flex flex-wrap gap-x-3 pt-2">
            <span className="text-xs text-bone-dim">{prior.title}</span>
            {prior.detected_at && (
              <span className="text-xs text-muted tabular-nums">{prior.detected_at}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Exactly what changed in DataHub. Receipts, not a summary. */
export function WritebackPanel({
  writes,
  datahubUiUrl = null,
}: {
  writes: WriteBack[];
  /** When a real DataHub is behind this, every receipt becomes checkable. */
  datahubUiUrl?: string | null;
}) {
  return (
    <div className="space-y-3">
      <ul className="m-0 list-none space-y-2 p-0">
        {writes.map((write, i) => (
          <li key={i} className="rule flex flex-wrap items-baseline gap-x-3 gap-y-1 pt-2">
            <code className="text-xs text-jade">{write.op}</code>
            <span className="min-w-0 flex-1 text-xs text-bone-dim">
              {write.op === "save_document" && write.title}
              {write.op === "add_tags" &&
                `${write.tags.join(", ")} → ${shortName(write.urn)}`}
              {write.op === "update_description" && shortName(write.urn)}
            </span>
            {datahubUiUrl && write.op !== "save_document" && (
              <a
                href={datahubAssetUrl(datahubUiUrl, write.urn)}
                target="_blank"
                rel="noreferrer"
                className="text-[10px] tracking-[0.1em] text-muted uppercase no-underline hover:text-jade"
              >
                Check →
              </a>
            )}
          </li>
        ))}
      </ul>
      <p className="prose-evidence m-0 border-t border-line pt-3 text-muted">
        The next person — or agent — inherits this without re-deriving it.
      </p>
    </div>
  );
}

/** Grounding level, stated plainly. The artifact declares its own rung. */
export function GroundingBadge({ diagnosis }: { diagnosis: Diagnosis }) {
  const tone = diagnosis.grounded
    ? diagnosis.grounding === "path_and_transform"
      ? "border-jade-dim text-jade"
      : "border-amber-dim text-amber"
    : "border-oxide-dim text-oxide";

  return (
    <span
      className={`border px-2 py-1 text-[10px] tracking-[0.12em] uppercase ${tone}`}
    >
      {diagnosis.grounding_label}
    </span>
  );
}


/** Where else the fault landed. The alerting asset is rarely the only victim. */
export function BlastRadiusPanel({ blast }: { blast: BlastRadius }) {
  if (!blast.count) {
    return (
      <p className="prose-evidence m-0">
        Nothing consumes this asset downstream — the damage stops here.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <p className="prose-evidence m-0">
        {blast.count} downstream asset{blast.count === 1 ? "" : "s"} inherit this
        data.{" "}
        {blast.silent_count > 0 && (
          <>
            <span className="text-oxide">
              {blast.silent_count} {blast.silent_count === 1 ? "is" : "are"} wrong
              without alerting
            </span>{" "}
            — nobody is currently being told.
          </>
        )}
        {/* Said rather than implied: an undetermined alerting status is not the
            same as a confirmed silence, and this panel must not read as though
            it were. */}
        {(blast.unknown_count ?? 0) > 0 && (
          <>
            {blast.silent_count > 0 ? " " : ""}
            This catalog did not report alerting status for{" "}
            {blast.silent_count > 0
              ? `${blast.unknown_count} of them`
              : `${blast.unknown_count === blast.count ? "any of them" : `${blast.unknown_count}`}`}
            , so whether anyone is watching{" "}
            {blast.unknown_count === 1 ? "it" : "them"} is unknown.
          </>
        )}
      </p>
      <ul className="m-0 list-none space-y-0 p-0">
        {blast.impacted.map((asset) => (
          <li
            key={asset.urn}
            className="rule flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2"
          >
            <span
              className={`text-[13px] font-medium ${
                asset.alerting === false ? "text-oxide" : "text-bone-dim"
              }`}
            >
              {asset.name}
            </span>
            <span className="label">
              {asset.kind} · {asset.hops_from_symptom} hop
              {asset.hops_from_symptom === 1 ? "" : "s"} downstream
            </span>
            {asset.owner && (
              <span className="text-[11px] text-muted">{asset.owner}</span>
            )}
            <span className="ml-auto shrink-0">
              {asset.alerting === true ? (
                <span className="label text-amber">alerting</span>
              ) : asset.alerting === false ? (
                <span className="label text-oxide">silent</span>
              ) : (
                <span className="label text-muted" title="This backend does not report alerting status">
                  unknown
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The check that would have caught this at the source. */
export function AssertionPanel({
  proposal,
}: {
  proposal: ProposedAssertion;
}) {
  return (
    <div className="space-y-3">
      <p className="m-0 flex flex-wrap items-baseline gap-x-3">
        <span className="text-[13px] font-semibold text-jade">
          {ASSERTION_KIND_LABELS[proposal.kind]} on {proposal.target_name}
        </span>
        {proposal.lead_time && (
          <span className="label text-amber">{proposal.lead_time}</span>
        )}
      </p>
      <p className="prose-evidence m-0">
        <Prose text={proposal.description} />
      </p>
      <p className="prose-evidence m-0 text-muted">
        <Prose text={proposal.rationale} />
      </p>
      <pre className="well m-0 overflow-x-auto p-3 text-[12.5px] leading-relaxed text-bone-dim">
        {proposal.definition}
      </pre>
    </div>
  );
}

const TIMELINE_TONE: Record<TimelineEvent["kind"], string> = {
  fault_origin: "border-jade bg-jade",
  transform_ran: "border-line-bright bg-line-bright",
  assertion_fired: "border-amber bg-amber",
  detected: "border-amber bg-amber",
};

/** The fault ordered in time rather than topology. */
export function TimelinePanel({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="m-0 list-none space-y-0 p-0">
      {events.map((event, i) => (
        <li key={i} className="relative flex gap-4 pb-4 last:pb-0">
          {i < events.length - 1 && (
            <span
              aria-hidden
              className="absolute left-[5px] top-4 h-full w-px bg-line"
            />
          )}
          <span
            aria-hidden
            className={`relative z-10 mt-[6px] h-[11px] w-[11px] shrink-0 rounded-full border ${TIMELINE_TONE[event.kind]}`}
          />
          <div className="min-w-0 flex-1">
            <p className="m-0 flex flex-wrap items-baseline gap-x-3">
              <span className="text-[12px] text-bone tabular-nums">{event.at}</span>
              <span className="label">{event.asset_name}</span>
            </p>
            <p className="prose-evidence m-0 mt-0.5 text-[14px]">{event.label}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
