"use client";

/**
 * The 263 real taxi zones the stale lookup table defines — and the real traffic
 * that depends on them.
 *
 * This is the one view that is not about lineage, and it earns its place by
 * giving the abstraction a footprint. `NYC Taxi Zones` is years past its
 * freshness SLA, and *this* is what it is a lookup for: every trip record in
 * every downstream dataset resolves its pickup and dropoff through one of these
 * polygons. Shaded by volume and annotated, the map answers the question the
 * incident actually raises — how much traffic is riding on a definition nobody
 * has updated.
 *
 * Geometry is real, from the same dataset Cauzon reports on, simplified with
 * Douglas-Peucker for delivery (98,192 points to 7,286). No mapping library: a
 * plain equirectangular projection is accurate enough across a single city and
 * costs nothing.
 */

import { useEffect, useMemo, useState } from "react";

import zoneData from "@/lib/taxi_zones.json";
import type { TaxiZone, TaxiZoneSet, ZoneVolume } from "@/lib/types";

const DATA = zoneData as TaxiZoneSet;

// The projected city is very nearly square (its corrected span is 0.421 by 0.419
// degrees), so the frame is square too. A wider box left ~80px of dead margin on
// each side while the map itself sat scaled down in the middle.
const VIEW = 760;
const PAD = 10;

// Six boroughs need six distinguishable fills, and the palette has three
// accents — so each borough gets an accent plus its own opacity rather than a
// seventh colour being invented. Manhattan and Staten Island are both green
// because they are both green-family, but at values far enough apart to read.
const BOROUGH_FILL: Record<string, { fill: string; opacity: number }> = {
  Manhattan: { fill: "var(--color-jade)", opacity: 0.55 },
  Brooklyn: { fill: "var(--color-amber)", opacity: 0.5 },
  Queens: { fill: "var(--color-oxide)", opacity: 0.5 },
  Bronx: { fill: "var(--color-bone-dim)", opacity: 0.32 },
  "Staten Island": { fill: "var(--color-jade-dim)", opacity: 0.95 },
  EWR: { fill: "var(--color-muted)", opacity: 0.4 },
};

const DEFAULT_FILL = { fill: "var(--color-line-bright)", opacity: 0.6 };

type View = "volume" | "borough";

/**
 * Zones worth naming on the map itself, and which way their label leans.
 *
 * Four of the five busiest zones sit within a few blocks of each other in
 * midtown Manhattan, so labelling the top five by rank would stack four labels
 * on top of one another. These are chosen to be far apart instead — the two
 * airports and the midtown core — and each leans into empty water or land, which
 * is also what fills the corner the city's diagonal shape leaves blank.
 */
const ANNOTATED: { id: string; lean: "left" | "right"; dx: number; dy: number }[] = [
  { id: "132", lean: "right", dx: 54, dy: 42 }, // JFK, out over Jamaica Bay
  { id: "138", lean: "right", dx: 66, dy: -46 }, // LaGuardia, out over the Sound
  { id: "161", lean: "left", dx: -74, dy: -8 }, // Midtown Center, out over the Hudson
];

/**
 * Volume to ink, on a log scale with a contrast curve.
 *
 * Log alone is not enough. The range runs from one pickup to two million, so a
 * linear ramp shows only the airports — but plain log puts the median zone at
 * better than half brightness and the whole city washes out to one flat tone.
 * The exponent pushes the low and middle deciles back down so the shading tracks
 * what the map is actually about: the handful of zones carrying enough traffic
 * that a stale definition matters.
 */
const CONTRAST = 2.2;

function heat(trips: number | undefined, maxLog: number): number {
  if (!trips || trips <= 0) return 0;
  const shade = Math.pow(Math.min(Math.log10(trips) / maxLog, 1), CONTRAST);
  // Rounded because this lands in a `fill-opacity` attribute, and the spec lets
  // `Math.pow` and `Math.log10` be implementation-dependent: Node and the browser
  // disagreed on the last bit (…24007 vs …24008), which React sees as a hydration
  // mismatch. Three decimals is finer than an alpha channel can show anyway.
  return Math.round(shade * 1000) / 1000;
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

export default function ZoneMap({
  stale,
  apiBase,
  variant = "full",
}: {
  stale?: boolean;
  /** Live backend to read current per-zone volume from. Optional. */
  apiBase?: string;
  /** `brief` drops the chrome for use on a page that is making one point. */
  variant?: "full" | "brief";
}) {
  const [hovered, setHovered] = useState<TaxiZone | null>(null);
  const [live, setLive] = useState<ZoneVolume | null>(null);
  const [view, setView] = useState<View>("volume");
  const brief = variant === "brief";

  // Fetched separately from the rest of the page: Socrata aggregates tens of
  // millions of rows for this, so folding it into the page's initial load would
  // hold the inbox and the catalog map behind it. The recorded snapshot draws
  // immediately and live figures replace it when they arrive.
  useEffect(() => {
    if (!apiBase) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/zones`);
        if (!res.ok) throw new Error(String(res.status));
        const data: ZoneVolume = await res.json();
        if (!cancelled && data.zones_covered) setLive(data);
      } catch {
        // The recorded snapshot is already on screen; nothing to announce.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  // Live when we have it, recorded otherwise. Either way the numbers are real —
  // the distinction is when they were counted, and the caption says which.
  const volume = live ?? DATA.volume ?? null;
  const showVolume = view === "volume" && Boolean(volume);

  const { paths, boroughs, maxLog, top, height, notes, legendAt } = useMemo(() => {
    const all = DATA.zones.flatMap((z) => z.rings.flat());
    const lons = all.map((p) => p[0]);
    const lats = all.map((p) => p[1]);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);

    // Equirectangular, corrected for latitude so the city is not stretched.
    const midLat = ((minLat + maxLat) / 2) * (Math.PI / 180);
    const lonScale = Math.cos(midLat);
    const spanX = (maxLon - minLon) * lonScale;
    const spanY = maxLat - minLat;

    // Fit the frame to the geometry instead of fitting the geometry into a frame
    // of some other shape — that is what left the empty band down each side.
    const scale = (VIEW - PAD * 2) / spanX;
    const viewH = spanY * scale + PAD * 2;

    const project = ([lon, lat]: number[]): [number, number] => [
      PAD + (lon - minLon) * lonScale * scale,
      // Flip: SVG y grows downward, latitude grows upward.
      PAD + (maxLat - lat) * scale,
    ];

    const trips = volume?.trips ?? {};
    const peak = Math.max(1, ...Object.values(trips));

    const laid = DATA.zones.map((zone) => {
      const projected = zone.rings.map((ring) => ring.map(project));
      // Centroid of the largest ring: good enough to hang a label off, and it
      // cannot land outside the shape the way a bbox centre can.
      const largest = projected.reduce(
        (best, r) => (r.length > best.length ? r : best),
        projected[0] ?? [],
      );
      const cx = largest.reduce((s, p) => s + p[0], 0) / Math.max(largest.length, 1);
      const cy = largest.reduce((s, p) => s + p[1], 0) / Math.max(largest.length, 1);
      return {
        zone,
        trips: trips[String(zone.id)],
        centre: [cx, cy] as [number, number],
        d: projected
          .map(
            (ring) =>
              "M " +
              ring.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ") +
              " Z",
          )
          .join(" "),
      };
    });

    const byId = new Map(laid.map((l) => [String(l.zone.id), l]));

    return {
      paths: laid,
      boroughs: [...new Set(DATA.zones.map((z) => z.borough).filter(Boolean))] as string[],
      maxLog: Math.log10(peak),
      height: viewH,
      top: laid
        .filter((l) => (l.trips ?? 0) > 0)
        .sort((a, b) => (b.trips ?? 0) - (a.trips ?? 0))
        .slice(0, 5),
      notes: ANNOTATED.map((a) => {
        const hit = byId.get(a.id);
        if (!hit || !hit.trips) return null;
        const name = hit.zone.zone ?? "";
        // Widest of the two lines, at roughly the advance of the label font.
        const width = Math.max(name.length, `${compact(hit.trips)} pickups`.length) * 7.2;

        let lean = a.lean;
        let x = hit.centre[0] + a.dx;
        // Flip inward rather than run off the edge — JFK sits far enough southeast
        // that a right-leaning label leaves the frame and gets clipped.
        if (lean === "right" && x + 5 + width > VIEW - PAD) lean = "left";
        else if (lean === "left" && x - 5 - width < PAD) lean = "right";
        if (lean === "left") x = Math.max(x, PAD + width + 5);
        else x = Math.min(x, VIEW - PAD - width - 5);

        // Keep both lines of the label inside the frame vertically too.
        const y = Math.min(Math.max(hit.centre[1] + a.dy, PAD + 10), viewH - PAD - 18);

        return {
          ...a,
          lean,
          name,
          trips: hit.trips,
          from: hit.centre,
          to: [x, y] as [number, number],
        };
      }).filter(Boolean) as {
        id: string;
        lean: "left" | "right";
        name: string;
        trips: number;
        from: [number, number];
        to: [number, number];
      }[],
      // The city runs diagonally, so the top-left stays empty at any scale.
      legendAt: [PAD + 6, PAD + 14] as [number, number],
    };
  }, [volume]);

  const hoveredTrips = hovered ? volume?.trips?.[String(hovered.id)] : undefined;

  return (
    <div className="space-y-3">
      {!brief && (
        <p className="prose-evidence m-0">
          {stale ? (
            <>
              These are the {DATA.zones.length} zones that stale lookup table
              defines. Every trip record downstream resolves its pickup and
              dropoff through one of these polygons, so a stale zone table is{" "}
              <span className="text-oxide">stale geography</span>, not just a
              stale row count.
            </>
          ) : (
            <>
              The {DATA.zones.length} zones the taxi lookup table defines. Every
              trip record downstream resolves its pickup and dropoff through one
              of these polygons.
            </>
          )}
        </p>
      )}

      {volume && !brief && (
        <p className="prose-evidence m-0">
          Shaded by real pickup volume:{" "}
          <span className="text-amber">
            {volume.total_trips.toLocaleString()} trips
          </span>{" "}
          across {volume.zones_covered} zones, every one of them resolved through
          a definition in that table.
        </p>
      )}

      {volume && !brief && (
        <div role="group" aria-label="Shading" className="flex flex-wrap gap-2">
          {(
            [
              ["volume", "Pickup volume"],
              ["borough", "Borough"],
            ] as [View, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setView(key)}
              aria-pressed={view === key}
              className={`border px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase transition-colors ${
                view === key
                  ? "border-jade-dim text-jade"
                  : "border-line text-muted hover:border-line-bright"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <figure className="well m-0 overflow-hidden p-2">
        <svg
          viewBox={`0 0 ${VIEW} ${height}`}
          className="h-auto w-full"
          role="img"
          aria-label={
            showVolume
              ? `Map of ${DATA.zones.length} NYC taxi zones shaded by pickup volume`
              : `Map of ${DATA.zones.length} NYC taxi zones by borough`
          }
        >
          {paths.map(({ zone, d, trips }, i) => {
            const borough = BOROUGH_FILL[zone.borough ?? ""] ?? DEFAULT_FILL;
            const dim = hovered && hovered !== zone;
            const opacity = showVolume
              ? // Floor of 0.06 so a zero-traffic zone is still visibly part of
                // the city rather than a hole in the map.
                0.06 + heat(trips, maxLog) * 0.89
              : borough.opacity;
            return (
              <path
                key={`${zone.id ?? "z"}-${i}`}
                d={d}
                fill={showVolume ? "var(--color-amber)" : borough.fill}
                fillOpacity={opacity * (dim ? 0.45 : 1)}
                stroke="var(--color-ink)"
                strokeWidth="0.5"
                onMouseEnter={() => setHovered(zone)}
                onMouseLeave={() => setHovered(null)}
                style={{ transition: "fill-opacity 120ms" }}
                /* No <title> child: React 19 treats <title> as hoistable document
                   metadata even inside an <svg>, which desyncs hydration. The
                   hover readout below carries the name and the count. */
                aria-label={`${zone.zone ?? "Unknown zone"}${
                  trips !== undefined ? `, ${trips.toLocaleString()} pickups` : ""
                }`}
              />
            );
          })}

          {/* Labelled on the map, so it reads as a diagram rather than a shape
              you have to hover to interpret. */}
          {showVolume &&
            notes.map((note) => (
              <g key={note.id} pointerEvents="none">
                <line
                  x1={note.from[0]}
                  y1={note.from[1]}
                  x2={note.to[0]}
                  y2={note.to[1]}
                  stroke="var(--color-bone-dim)"
                  strokeWidth="0.75"
                  strokeOpacity="0.55"
                />
                <circle
                  cx={note.from[0]}
                  cy={note.from[1]}
                  r="2"
                  fill="var(--color-bone)"
                />
                <text
                  x={note.to[0] + (note.lean === "left" ? -5 : 5)}
                  y={note.to[1]}
                  textAnchor={note.lean === "left" ? "end" : "start"}
                  fill="var(--color-bone)"
                  fontSize="12"
                  fontWeight="600"
                >
                  {note.name}
                </text>
                <text
                  x={note.to[0] + (note.lean === "left" ? -5 : 5)}
                  y={note.to[1] + 14}
                  textAnchor={note.lean === "left" ? "end" : "start"}
                  fill="var(--color-amber)"
                  fontSize="11"
                >
                  {compact(note.trips)} pickups
                </text>
              </g>
            ))}

          {/* The legend lives in the corner the city's diagonal leaves blank. */}
          {showVolume && volume && (
            <g pointerEvents="none" transform={`translate(${legendAt[0]}, ${legendAt[1]})`}>
              <text fill="var(--color-bone-dim)" fontSize="13" fontWeight="600">
                {volume.total_trips.toLocaleString()} pickups
              </text>
              <text y="17" fill="var(--color-muted)" fontSize="10.5">
                resolved through {volume.zones_covered} zone definitions
              </text>
              <defs>
                <linearGradient id="zone-ramp" x1="0" x2="1">
                  <stop offset="0" stopColor="var(--color-amber)" stopOpacity="0.08" />
                  <stop offset="1" stopColor="var(--color-amber)" stopOpacity="0.95" />
                </linearGradient>
              </defs>
              <rect y="30" width="120" height="7" fill="url(#zone-ramp)" />
              <text y="51" fill="var(--color-muted)" fontSize="9.5">
                1
              </text>
              <text x="120" y="51" textAnchor="end" fill="var(--color-muted)" fontSize="9.5">
                2M
              </text>
              <text y="67" fill="var(--color-muted)" fontSize="9">
                log scale
              </text>
            </g>
          )}
        </svg>
      </figure>

      {!brief && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {showVolume ? (
            <span className="label text-muted">
              Brighter is busier · {live ? "live figures" : "recorded snapshot"}
            </span>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {boroughs.map((borough) => (
                <span key={borough} className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className="h-2 w-2"
                    style={{
                      background: (BOROUGH_FILL[borough] ?? DEFAULT_FILL).fill,
                      opacity: (BOROUGH_FILL[borough] ?? DEFAULT_FILL).opacity,
                    }}
                  />
                  <span className="label">{borough}</span>
                </span>
              ))}
            </div>
          )}
          <span className="label min-h-[1em] text-bone-dim">
            {hovered
              ? `${hovered.zone} · ${hovered.borough}${
                  hoveredTrips !== undefined
                    ? ` · ${hoveredTrips.toLocaleString()} pickups`
                    : ""
                }`
              : "Hover a zone"}
          </span>
        </div>
      )}

      {!brief && top.length > 0 && (
        <div className="well p-4">
          <span className="label">Most traffic riding on the stale definition</span>
          <ol className="m-0 mt-2 list-none space-y-1 p-0">
            {top.map(({ zone, trips }, i) => (
              <li
                key={`${zone.id}-${i}`}
                className="flex items-baseline gap-3 text-[13px]"
              >
                <span className="w-4 shrink-0 text-right text-muted">{i + 1}</span>
                <span className="text-bone-dim">{zone.zone}</span>
                <span className="ml-auto shrink-0 tabular-nums text-amber">
                  {trips?.toLocaleString()}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <p className="prose-evidence m-0 text-muted">
        Real geometry from{" "}
        <a
          href={DATA.source}
          target="_blank"
          rel="noreferrer"
          className="text-bone-dim underline decoration-line-bright hover:text-jade"
        >
          the same dataset Cauzon reports on
        </a>
        , simplified for delivery — 98,192 points reduced to 7,286.
        {volume && (
          <>
            {" "}
            Pickup counts are real, aggregated by Socrata over all{" "}
            {volume.total_trips.toLocaleString()} records of{" "}
            <a
              href={volume.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-bone-dim underline decoration-line-bright hover:text-jade"
            >
              {volume.dataset_label}
            </a>
            {live
              ? " at request time — the browser never receives the trip data."
              : " and recorded into this page, which has no backend to ask."}{" "}
            That dataset is historical, so the totals are stable rather than
            moving minute to minute; what moves is the lookup table&rsquo;s
            freshness. Shading is logarithmic, because the range runs from one
            pickup to two million and a linear ramp would show only the airports.
          </>
        )}
      </p>
    </div>
  );
}
