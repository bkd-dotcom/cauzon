"use client";

/**
 * What this is built on, as a scanning readout.
 *
 * A rotating strip of logos is the usual answer and it tells a reader nothing —
 * you learn that a project uses React, not what React is doing there. So every
 * product stays on screen (it is a catalog, and the grouping by role is itself
 * information), and the rotation is a focus that advances through them and
 * reports what each one actually does in this project.
 *
 * That also matches the rest of the interface: an instrument that scans and
 * reports, rather than a banner that cycles.
 *
 * Pointing at or tabbing to an entry pins it, because a reader who has found the
 * line they care about should not have it move. Reduced motion means no
 * advancing at all — the list is complete without it.
 */

import { useEffect, useRef, useState } from "react";

interface Product {
  name: string;
  role: string;
  /** Shown beside the name in the readout — version or edition, where it matters. */
  detail?: string;
}

/** Grouped by what each one is responsible for, not by language or vendor. */
const GROUPS: { group: string; items: Product[] }[] = [
  {
    group: "Catalog",
    items: [
      {
        name: "DataHub",
        role: "The metadata catalog Cauzon reasons over — lineage, assertions, incidents, ownership. The dossier goes back into it.",
      },
      {
        name: "DataHub MCP Server",
        role: "The tool surface: search, lineage, schema fields, query history, and the three mutations that write a finding back.",
      },
      {
        name: "datahub-agent-context",
        role: "DataHub's own agent-context package — what turns a running instance into callable tools instead of a REST client to hand-roll.",
      },
      {
        name: "acryl-datahub",
        role: "The DataHub Python SDK. URN handling, and ingesting the demo graph into a real instance to verify against.",
      },
    ],
  },
  {
    group: "Agent",
    items: [
      {
        name: "Python",
        detail: "3.10+",
        role: "The agent core is plain dataclasses and functions. No framework — the proof gate has to be readable to be trusted.",
      },
      {
        name: "FastAPI",
        role: "HTTP and WebSocket. Each reasoning step streams as it happens, so the investigation is auditable while it runs.",
      },
      {
        name: "Uvicorn",
        role: "The ASGI server behind FastAPI, and what Cloud Run actually starts.",
      },
      {
        name: "Pydantic",
        role: "Validation at the HTTP boundary only. The agent's own models are dataclasses, so the core carries no web dependency.",
      },
      {
        name: "pytest",
        detail: "125 tests",
        role: "Adversarial about the central claim: a hostile narrator cannot flip a verdict, and the better-scoring decoy must be rejected.",
      },
      {
        name: "Claude Opus 5",
        detail: "optional",
        role: "Writes the dossier narrative and nothing else — it reaches no decision field, and its output is discarded if it invents a URN.",
      },
    ],
  },
  {
    group: "Interface",
    items: [
      {
        name: "Next.js",
        detail: "16",
        role: "Static export, so the frontend is files on a CDN with no server to keep alive.",
      },
      { name: "React", detail: "19", role: "The three views, and the trace that streams into them while the agent works." },
      {
        name: "Tailwind CSS",
        detail: "4",
        role: "Palette and type scale live in @theme tokens, so jade, oxide and amber mean the same thing on every surface.",
      },
      {
        name: "TypeScript",
        role: "Every API shape is typed on both sides, so a field the backend stops sending is a build error rather than a blank panel.",
      },
    ],
  },
  {
    group: "Live data",
    items: [
      {
        name: "NYC Open Data",
        detail: "Socrata",
        role: "Real assets and real freshness, so the live queue is whatever is genuinely past SLA. It also aggregates 38M trips per zone.",
      },
    ],
  },
  {
    group: "Infrastructure",
    items: [
      {
        name: "Google Cloud Run",
        role: "Two backends, one per catalog. Scale-to-zero, so it costs nothing idle and the app replays a recording while one wakes.",
      },
      {
        name: "Cloudflare Pages",
        role: "Hosts the static frontend at cauzon.pages.dev.",
      },
      {
        name: "GitHub Actions",
        role: "Runs the suite and checks the generated artifacts for drift on every push — fixtures and geometry are built, never hand-edited.",
      },
    ],
  },
];

const FLAT = GROUPS.flatMap((g) => g.items.map((item) => ({ ...item, group: g.group })));
const INDEX_OF = new Map(FLAT.map((item, i) => [item.name, i]));
// Slow enough to finish reading a role before it moves. At 18 entries a full
// cycle runs a bit over a minute, which is fine for something ambient — and
// pointing at an entry pins it anyway.
const ADVANCE_MS = 4200;

export default function StackCatalog() {
  const [active, setActive] = useState(0);
  const [pinned, setPinned] = useState(false);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);

  useEffect(() => {
    if (pinned || reduced.current) return;
    const timer = setInterval(
      () => setActive((i) => (i + 1) % FLAT.length),
      ADVANCE_MS,
    );
    return () => clearInterval(timer);
  }, [pinned]);

  const current = FLAT[active];

  return (
    <section className="rule py-16">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="m-0 text-2xl font-semibold tracking-tight">Built with</h2>
        <span className="label">
          {FLAT.length} products · {GROUPS.length} roles
        </span>
      </div>

      <p className="prose-evidence mt-3 max-w-2xl">
        Every product here is doing one job, and the list is short on purpose. The
        lineage graph, the catalog map and the zone map are hand-drawn SVG — there
        is no charting or mapping library in the bundle.
      </p>

      <dl className="m-0 mt-8 space-y-0">
        {GROUPS.map(({ group, items }) => (
          <div
            key={group}
            className="grid gap-2 border-t border-line py-4 sm:grid-cols-[132px_1fr] sm:gap-6"
          >
            <dt className="label m-0 pt-1">{group}</dt>
            <dd className="m-0 flex flex-wrap items-baseline gap-x-1 gap-y-2">
              {items.map((item) => {
                const index = INDEX_OF.get(item.name) ?? 0;
                const on = index === active;
                return (
                  <button
                    key={item.name}
                    onMouseEnter={() => {
                      setActive(index);
                      setPinned(true);
                    }}
                    onMouseLeave={() => setPinned(false)}
                    onFocus={() => {
                      setActive(index);
                      setPinned(true);
                    }}
                    onBlur={() => setPinned(false)}
                    onClick={() => {
                      setActive(index);
                      setPinned(true);
                    }}
                    aria-current={on ? "true" : undefined}
                    className={`border px-2.5 py-1 text-[12.5px] transition-colors ${
                      on
                        ? "border-jade-dim bg-jade-dim/20 text-jade"
                        : "border-transparent text-bone-dim hover:border-line-bright"
                    }`}
                  >
                    {item.name}
                    {item.detail && (
                      <span className={on ? "text-jade/70" : "text-muted"}>
                        {" "}
                        {item.detail}
                      </span>
                    )}
                  </button>
                );
              })}
            </dd>
          </div>
        ))}
      </dl>

      {/* Fixed height: the readout changes every couple of seconds, and text of
          varying length would otherwise walk the rest of the page up and down. */}
      <div
        /* Heights measured against the longest role at each breakpoint, so the
           readout never changes size as it advances — otherwise everything below
           it walks up and down every few seconds. */
        className="well mt-6 min-h-[148px] p-5 sm:min-h-[124px]"
        aria-live="polite"
        aria-atomic="true"
      >
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-jade" aria-hidden>
            ▸
          </span>
          <span className="text-sm font-semibold text-bone">{current.name}</span>
          {current.detail && <span className="label">{current.detail}</span>}
          <span className="label ml-auto">{current.group}</span>
        </div>
        <p className="prose-evidence m-0 mt-2">{current.role}</p>
      </div>
    </section>
  );
}
