"use client";

/**
 * What this is built on, as a continuously drifting carousel.
 *
 * The track holds the marks twice and slides by exactly half its width, so the
 * moment the animation loops the second copy is standing where the first began.
 * The result is one unbroken drift with no seam and no JavaScript running per
 * frame — it is a CSS animation on a composited transform, so the browser slides
 * a layer rather than repainting twenty-six pieces of vector artwork.
 *
 * The readout underneath names the current product and says what it does here.
 * Names are not on the tiles — a strip of logos reads at a glance — but a mark you
 * do not recognise is useless, and no logo can say what the product is doing in
 * this project. The current one is lit jade wherever it happens to be in the
 * drift, so the readout and the strip stay tied together without the strip having
 * to stop.
 *
 * Marks render monochrome from `currentColor`. Thirteen full-colour brand logos on
 * a near-black instrument UI would be the loudest thing on the page.
 *
 * Hovering the strip or tabbing into it stops the drift, and pointing at a mark
 * shows that one — a reader who has found the entry they care about should not
 * have to chase it. Reduced motion stops the drift entirely and turns the strip
 * into an ordinary scrollable row, so nothing becomes unreachable.
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
        markClass: "h-12 w-12",
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
// Slow enough to finish reading a role before the track moves on. Pointing at the
// carousel stops it anyway.
const ADVANCE_MS = 4200;

const TILE_W = 128;
const TILE_H = 96;
const GAP = 16;
// One full pass at a readable pace. Thirteen tiles at 144px is 1,872px per copy,
// so this works out around 50px a second — slow enough to look at a mark as it
// goes by, quick enough that the strip is not mistaken for a static row.
const DRIFT_S = 38;

const EDGE_FADE =
  "linear-gradient(to right, transparent, black 11%, black 89%, transparent)";

export default function StackCatalog() {
  const [active, setActive] = useState(0);
  const [held, setHeld] = useState(false);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);

  // The readout advances on its own so a passive reader still learns what each
  // product does. It is not tied to the drift's position: with a continuous track
  // there is no "current" slot to read off, so the tie is the other way round —
  // whichever product the readout names is lit in the strip.
  useEffect(() => {
    if (held || reduced.current) return;
    const timer = setInterval(
      () => setActive((i) => (i + 1) % FLAT.length),
      ADVANCE_MS,
    );
    return () => clearInterval(timer);
  }, [held]);

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

      <div
        className="marquee relative mt-8 overflow-hidden py-1"
        role="group"
        aria-roledescription="carousel"
        aria-label="Products this is built with"
        onMouseEnter={() => setHeld(true)}
        onMouseLeave={() => setHeld(false)}
        onFocus={() => setHeld(true)}
        onBlur={() => setHeld(false)}
        style={{
          // Fade at both edges instead of a hard cut, so a mark entering or
          // leaving does not look clipped off. Roughly one tile wide: any narrower
          // and the fade reads as a crop rather than a fade.
          maskImage: EDGE_FADE,
          WebkitMaskImage: EDGE_FADE,
        }}
      >
        <ul
          className="marquee-track m-0 flex w-max list-none p-0"
          style={{ gap: `${GAP}px`, ["--marquee-duration" as string]: `${DRIFT_S}s` }}
        >
          {/* Twice, so the loop closes on itself. The second pass is hidden from
              assistive tech: it is the same thirteen products, and announcing
              twenty-six would misreport what the project uses. */}
          {[0, 1].map((pass) =>
            FLAT.map((item, index) => (
              <li
                key={`${pass}-${item.name}`}
                className="shrink-0"
                aria-hidden={pass === 1 ? true : undefined}
              >
                <button
                  onMouseEnter={() => setActive(index)}
                  onFocus={() => setActive(index)}
                  onClick={() => setActive(index)}
                  tabIndex={pass === 1 ? -1 : undefined}
                  aria-current={index === active ? "true" : undefined}
                  /* The name is the accessible label and the tooltip: the tile is
                     a picture, and a screen reader gets nothing from a path. */
                  aria-label={item.name}
                  title={item.name}
                  className={`flex items-center justify-center border transition-colors duration-300 ${
                    index === active
                      ? "border-jade-dim bg-jade-dim/20 text-jade"
                      : "border-line text-bone-dim hover:border-line-bright hover:text-bone"
                  }`}
                  style={{ width: TILE_W, height: TILE_H }}
                >
                  <Mark item={item} />
                </button>
              </li>
            )),
          )}
        </ul>
      </div>

      {/* Fixed height, set from the measured natural height of the longest role at
          each breakpoint, so the readout never resizes as the carousel advances —
          otherwise everything below it walks up and down every few seconds. */}
      <div
        className="well mt-5 min-h-[194px] p-5 sm:min-h-[124px] xl:min-h-[99px]"
        aria-live="polite"
        aria-atomic="true"
      >
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-jade" aria-hidden>
            ▸
          </span>
          <span className="text-sm font-semibold text-bone">{current.name}</span>
          {current.detail && <span className="label">{current.detail}</span>}
          <span className="label ml-auto">
            {current.group} · {active + 1}/{FLAT.length}
          </span>
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
        className="text-center text-[10px] leading-[1.15] font-semibold tracking-[0.06em]"
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
      className={item.markClass ?? "h-10 w-10"}
      fill="currentColor"
      focusable="false"
    >
      {mark.paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
