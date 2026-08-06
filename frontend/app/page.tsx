import Link from "next/link";

import HeroSpine from "@/components/HeroSpine";

const REPO = "https://github.com/bkd-dotcom/cauzon";

/** The investigation loop. Numbered because it genuinely is a sequence. */
const PHASES = [
  {
    name: "Detect",
    body: "Pick up a failing assertion or open incident from the catalog.",
    tools: "search · incidents",
  },
  {
    name: "Scope",
    body: "Pull the minimal upstream subgraph — three hops, not the whole warehouse.",
    tools: "get_lineage",
  },
  {
    name: "Hypothesize",
    body:
      "Rank candidates on freshness lag, volume anomaly, schema change and key uniqueness. A node scores as the origin when it carries the fault and nothing feeding it does.",
    tools: "get_entities · list_schema_fields",
  },
  {
    name: "Prove",
    body:
      "Reconstruct the lineage path from real edges. No path, no diagnosis — however strong the signals.",
    tools: "get_lineage_paths_between · get_dataset_queries",
  },
  {
    name: "File",
    body:
      "Write the dossier back, tag the culprit, and read prior dossiers so a repeat failure is recognised as a pattern.",
    tools: "save_document · add_tags · search_documents",
  },
];

const RUNGS = [
  {
    level: "Path + transform proven",
    tone: "text-jade border-jade-dim",
    body: "The lineage path was reconstructed and the transform that carried the fault was captured.",
  },
  {
    level: "Path proven, transform unavailable",
    tone: "text-amber border-amber-dim",
    body: "The path holds, but DataHub retains no query history for the causal edge. Confidence drops and the dossier says so.",
  },
  {
    level: "Not grounded",
    tone: "text-oxide border-oxide-dim",
    body: "Nothing connects the suspect to the symptom. Cauzon names no cause and writes nothing.",
  },
];

export default function LandingPage() {
  return (
    <div className="mx-auto max-w-[1180px] px-5 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-4 py-6">
        <span className="text-lg font-semibold tracking-tight">Cauzon</span>
        <nav className="flex items-center gap-6">
          <a href="#how" className="text-xs text-bone-dim no-underline hover:text-bone">
            How it works
          </a>
          <a href={REPO} className="text-xs text-bone-dim no-underline hover:text-bone">
            Source
          </a>
          <Link
            href="/investigate"
            className="border border-jade-dim bg-jade-dim/25 px-3 py-2 text-[11px] font-semibold tracking-[0.12em] text-jade uppercase no-underline hover:bg-jade-dim/45"
          >
            Open the app
          </Link>
        </nav>
      </header>

      <main id="main">
        {/* ---- hero: the thesis, then the proof of it -------------------- */}
        <section className="pt-10 pb-16 sm:pt-16">
          <p className="label mb-5">
            Build with DataHub · agents that do real work
          </p>
          <h1 className="m-0 max-w-3xl text-4xl leading-[1.12] font-semibold tracking-[-0.02em] text-balance sm:text-5xl">
            Every root cause,{" "}
            <span className="text-jade">proven from the source.</span>
          </h1>
          <p className="prose-evidence mt-6 max-w-2xl text-base">
            Observability tools tell you something broke. Cauzon walks DataHub&rsquo;s
            lineage graph upstream, ranks candidate culprits from multimodal
            signals, and names a root cause{" "}
            <em>only when it can reconstruct the exact path</em> connecting that
            cause to the symptom. Then it files the dossier back into the catalog,
            so the next person inherits the answer instead of re-deriving it.
          </p>

          <div className="mt-10">
            <HeroSpine />
          </div>

          <p className="prose-evidence mt-4 max-w-2xl text-muted">
            That is a recording of the real agent, not an illustration.{" "}
            <span className="text-oxide">marketing_spend</span> is the most
            suspicious asset in the graph — stale, schema-changed, volume
            collapsed — and it scores highest. It still gets rejected, because no
            lineage edge connects it to the symptom.
          </p>
        </section>

        {/* ---- the distinction the product exists for -------------------- */}
        <section className="rule grid gap-8 py-16 lg:grid-cols-[1fr_1fr]">
          <div>
            <h2 className="m-0 text-2xl font-semibold tracking-tight">
              A ranking is a hypothesis.
              <br />
              A path is proof.
            </h2>
            <p className="prose-evidence mt-4">
              Every anomaly detector produces a ranked list of suspects. The
              failure mode is confident, well-scored, wrong answers — and a
              diagnosis you cannot audit is worse than none, because someone acts
              on it. Cauzon separates the two steps and lets the second one veto
              the first.
            </p>
            <p className="prose-evidence mt-3">
              The design follows recent RCA and grounding research directly:
              multimodal ranking from RCRank (VLDB 2025), the ungrounded-diagnosis
              problem from PAVE / OpenRCA 2.0, and the separation of grounding
              from reasoning from DeepRoot (ICML 2026) — which is why the proof
              gate is deterministic code and the language model only ever
              explains a verdict already settled.
            </p>
          </div>

          <div className="space-y-3">
            <p className="label m-0">Every finding states its own rung</p>
            {RUNGS.map((rung) => (
              <div key={rung.level} className={`plate border-l-2 p-4 ${rung.tone}`}>
                <p className="m-0 text-[13px] font-semibold">{rung.level}</p>
                <p className="prose-evidence m-0 mt-2">{rung.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ---- the loop -------------------------------------------------- */}
        <section id="how" className="rule py-16">
          <h2 className="m-0 text-2xl font-semibold tracking-tight">
            The investigation loop
          </h2>
          <p className="prose-evidence mt-3 max-w-2xl">
            Five phases against the DataHub MCP server. Each one streams to the UI
            as it happens, so the reasoning is auditable while it runs rather than
            summarised afterwards.
          </p>

          <ol className="m-0 mt-8 list-none space-y-0 p-0">
            {PHASES.map((phase, i) => (
              <li
                key={phase.name}
                className="grid gap-3 border-t border-line py-5 sm:grid-cols-[56px_180px_1fr] sm:gap-6"
              >
                <span className="text-sm text-muted tabular-nums">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="text-sm font-semibold text-bone">{phase.name}</span>
                <div>
                  <p className="prose-evidence m-0">{phase.body}</p>
                  <code className="mt-2 block text-[11px] text-jade">{phase.tools}</code>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* ---- knowledge compounds -------------------------------------- */}
        <section className="rule grid gap-8 py-16 lg:grid-cols-[1fr_1fr]">
          <div>
            <h2 className="m-0 text-2xl font-semibold tracking-tight">
              The write-back is a loop, not a gesture
            </h2>
            <p className="prose-evidence mt-4">
              Cauzon files each dossier with <code className="text-jade">save_document</code>,
              tags the culprit <code className="text-jade">root-cause</code>, and
              notes the owner. It then reads those dossiers back on the next
              investigation — so the third time an ingestion job stalls, the
              recommendation stops being &ldquo;backfill this window&rdquo; and starts
              being &ldquo;the schedule is the defect.&rdquo;
            </p>
            <p className="prose-evidence mt-3">
              Verified end to end against a live{" "}
              <code className="text-bone-dim">datahub docker quickstart</code>: the
              tags, the description, and the dossier document were all read back
              out of the running catalog after the agent finished.
            </p>
          </div>
          <div className="space-y-3">
            <div className="plate p-4">
              <p className="label m-0">Contributed upstream</p>
              <p className="prose-evidence m-0 mt-2">
                <code className="text-bone">datahub-rca</code> — a DataHub Skill
                that teaches any MCP-connected agent to do path-grounded RCA,
                formatted to the conventions of{" "}
                <code className="text-bone-dim">datahub-project/datahub-skills</code>.
              </p>
            </div>
            <div className="plate p-4">
              <p className="label m-0">Try it with nothing installed</p>
              <p className="prose-evidence m-0 mt-2">
                The app replays recorded runs of the real agent in the browser.
                Point it at a live backend — and a real DataHub instance — by
                setting <code className="text-bone-dim">NEXT_PUBLIC_CAUZON_API</code>.
              </p>
            </div>
          </div>
        </section>

        <section className="rule flex flex-wrap items-center justify-between gap-6 py-16">
          <div>
            <h2 className="m-0 text-xl font-semibold tracking-tight">
              Watch it reject the obvious suspect
            </h2>
            <p className="prose-evidence mt-2 mb-0">
              Three planted incidents. Three different signals. One proof gate.
            </p>
          </div>
          <Link
            href="/investigate"
            className="border border-jade-dim bg-jade-dim/25 px-5 py-3 text-[12px] font-semibold tracking-[0.12em] text-jade uppercase no-underline hover:bg-jade-dim/45"
          >
            Run an investigation
          </Link>
        </section>
      </main>

      <footer className="rule flex flex-wrap items-center justify-between gap-4 py-6">
        <span className="label">Apache-2.0 · built on the DataHub MCP server</span>
        <a href={REPO} className="text-xs text-bone-dim no-underline hover:text-jade">
          github.com/bkd-dotcom/cauzon
        </a>
      </footer>
    </div>
  );
}
