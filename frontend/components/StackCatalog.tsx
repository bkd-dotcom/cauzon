"use client";

/**
 * What this is built on: the marks, with the names in the readout.
 *
 * The list shows logos rather than labels, so the strip reads at a glance. Names
 * are not gone — a mark you do not recognise is useless — they surface in the
 * readout as the focus advances, along with what each product actually does here.
 * That is the part a logo can never carry: a logo tells you a project uses React,
 * not what React is doing in it.
 *
 * Marks render monochrome from `currentColor`. Twelve full-colour brand logos on a
 * near-black instrument UI would be the loudest thing on the page, and this
 * section is meant to be read rather than to shout.
 *
 * Pointing at or tabbing to a mark pins it, because a reader who has found the
 * entry they care about should not have it move. Reduced motion means no
 * advancing at all — nothing is hidden without it.
 *
 * Marks come from scripts/build_logos.py. Two products have no usable vector mark
 * and are not faked: Uvicorn publishes only a raster, so it is named inside
 * FastAPI's entry, and NYC Open Data publishes none, so it gets a typographic
 * tile rather than an invented symbol.
 */

import { useEffect, useRef, useState } from "react";

import logoData from "@/lib/logos.json";

const MARKS = (
  logoData as {
    marks: Record<string, { name: string; viewBox: string; paths: string[] }>;
  }
).marks;

interface Product {
  /** Key into the generated marks, or null for a product with no vector mark. */
  mark: string | null;
  /**
   * Optical size override. Marks are not drawn to a common weight — a thin ring
   * reads lighter than a solid glyph at the same box — so a few need nudging to
   * sit evenly beside the others.
   */
  markClass?: string;
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
        mark: "datahub",
        markClass: "h-8 w-8",
        name: "DataHub",
        detail: "+ MCP server, SDK",
        role: "The catalog Cauzon reasons over, via DataHub's MCP server: search, lineage, schema fields, query history, and write-back.",
      },
    ],
  },
  {
    group: "Agent",
    items: [
      {
        mark: "python",
        name: "Python",
        detail: "3.10+",
        role: "The agent core is plain dataclasses and functions. No framework — the proof gate has to be readable to be trusted.",
      },
      {
        mark: "fastapi",
        name: "FastAPI",
        detail: "on Uvicorn",
        role: "HTTP and WebSocket, served by Uvicorn. Each reasoning step streams as it happens, so an investigation is auditable while it runs.",
      },
      {
        mark: "pydantic",
        name: "Pydantic",
        role: "Validation at the HTTP boundary only. The agent's own models are dataclasses, so the core carries no web dependency.",
      },
      {
        mark: "pytest",
        name: "pytest",
        detail: "125 tests",
        role: "Adversarial about the central claim: a hostile narrator cannot flip a verdict, and the better-scoring decoy must be rejected.",
      },
    ],
  },
  {
    group: "Interface",
    items: [
      {
        mark: "nextjs",
        name: "Next.js",
        detail: "16",
        role: "Static export, so the frontend is files on a CDN with no server to keep alive.",
      },
      {
        mark: "react",
        name: "React",
        detail: "19",
        role: "The three views, and the trace that streams into them while the agent works.",
      },
      {
        mark: "tailwind",
        name: "Tailwind CSS",
        detail: "4",
        role: "Palette and type scale live in @theme tokens, so jade, oxide and amber mean the same thing on every surface.",
      },
      {
        mark: "typescript",
        name: "TypeScript",
        role: "Every API shape is typed on both sides, so a field the backend stops sending is a build error rather than a blank panel.",
      },
    ],
  },
  {
    group: "Live data",
    items: [
      {
        mark: null,
        name: "NYC Open Data",
        detail: "Socrata",
        role: "Real assets and real freshness, so the live queue is whatever is genuinely past SLA. It also aggregates 38M taxi trips per zone for the map.",
      },
    ],
  },
  {
    group: "Infrastructure",
    items: [
      {
        mark: "cloudrun",
        name: "Google Cloud Run",
        role: "Two backends, one per catalog. Scale-to-zero, so it costs nothing idle and the app replays a recording while one wakes.",
      },
      {
        mark: "cloudflare",
        name: "Cloudflare Pages",
        role: "Hosts the static frontend at cauzon.pages.dev.",
      },
      {
        mark: "actions",
        name: "GitHub Actions",
        role: "Runs the suite on every push, and fails if the recorded fixtures have drifted from what the agent actually produces.",
      },
    ],
  },
];

const FLAT = GROUPS.flatMap((g) => g.items.map((item) => ({ ...item, group: g.group })));
const INDEX_OF = new Map(FLAT.map((item, i) => [item.name, i]));
// Slow enough to finish reading a role before it moves, and pointing at a mark
// pins it anyway.
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
            className="grid gap-3 border-t border-line py-5 sm:grid-cols-[132px_1fr] sm:gap-6"
          >
            <dt className="label m-0 pt-2">{group}</dt>
            <dd className="m-0 flex flex-wrap items-center gap-2">
              {items.map((item) => {
                const index = INDEX_OF.get(item.name) ?? 0;
                const on = index === active;
                const pin = () => {
                  setActive(index);
                  setPinned(true);
                };
                return (
                  <button
                    key={item.name}
                    onMouseEnter={pin}
                    onMouseLeave={() => setPinned(false)}
                    onFocus={pin}
                    onBlur={() => setPinned(false)}
                    onClick={pin}
                    aria-current={on ? "true" : undefined}
                    /* The name is the accessible label and the tooltip: the tile
                       is a picture, and a screen reader gets nothing from a path. */
                    aria-label={item.name}
                    title={item.name}
                    className={`flex h-14 w-16 items-center justify-center border transition-colors ${
                      on
                        ? "border-jade-dim bg-jade-dim/20 text-jade"
                        : "border-line text-bone-dim hover:border-line-bright hover:text-bone"
                    }`}
                  >
                    <Mark item={item} />
                  </button>
                );
              })}
            </dd>
          </div>
        ))}
      </dl>

      {/* Fixed height, set from the measured natural height of the longest role at
          each breakpoint, so the readout never resizes as it advances — otherwise
          everything below it walks up and down every few seconds. Measured rather
          than guessed: the first guesses reserved up to 48px of dead space. */}
      <div
        className="well mt-6 min-h-[173px] p-5 sm:min-h-[124px] xl:min-h-[99px]"
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

/**
 * One mark, monochrome. Falls back to a wordmark for a product that publishes no
 * vector logo — drawing a symbol for the City of New York would be inventing a
 * brand, which is worse than setting its name in type.
 */
function Mark({ item }: { item: Product }) {
  const mark = item.mark ? MARKS[item.mark] : undefined;

  if (!mark) {
    return (
      <span
        aria-hidden
        className="text-center text-[9px] leading-[1.15] font-semibold tracking-[0.06em]"
      >
        NYC
        <br />
        OPEN
        <br />
        DATA
      </span>
    );
  }

  return (
    <svg
      aria-hidden
      viewBox={mark.viewBox}
      className={item.markClass ?? "h-6 w-6"}
      fill="currentColor"
      focusable="false"
    >
      {mark.paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
