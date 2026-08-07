"use client";

/**
 * The 263 real taxi zones the stale lookup table defines — and the real traffic
 * that depends on them.
 *
 * This is the one view that is not about lineage, and it earns its place by
 * giving the abstraction a footprint. `NYC Taxi Zones` is years past its
 * freshness SLA, and *this* is what it is a lookup for: every trip record in
 * every downstream dataset resolves its pickup and dropoff through one of these
 * polygons. Shaded by volume, the map answers the question the incident actually
 * raises — how much traffic is riding on a definition nobody has updated.
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

const VIEW_W = 760;
const VIEW_H = 620;
const PAD = 12;

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
  const normalised = Math.min(Math.log10(trips) / maxLog, 1);
  return Math.pow(normalised, CONTRAST);
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

export default function ZoneMap({
  stale,
  apiBase,
}: {
  stale?: boolean;
  /** Live backend to read real per-zone volume from. Omitted: borough view only. */
  apiBase?: string;
}) {
  const [hovered, setHovered] = useState<TaxiZone | null>(null);
  const [volume, setVolume] = useState<ZoneVolume | null>(null);
  const [volumeFailed, setVolumeFailed] = useState(false);
  const [view, setView] = useState<View>("volume");

  // Fetched separately from the rest of the page: Socrata aggregates tens of
  // millions of rows for this, so folding it into the page's initial load would
  // hold the inbox and the catalog map behind it. The borough view renders
  // immediately and the shading arrives when it arrives.
  useEffect(() => {
    if (!apiBase) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/zones`);
        if (!res.ok) throw new Error(String(res.status));
        const data: ZoneVolume = await res.json();
        if (cancelled) return;
        if (!data.zones_covered) throw new Error("no zones covered");
        setVolume(data);
      } catch {
        if (!cancelled) setVolumeFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  const showVolume = view === "volume" && Boolean(volume);

  const { paths, boroughs, maxLog, top } = useMemo(() => {
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
    const scale = Math.min((VIEW_W - PAD * 2) / spanX, (VIEW_H - PAD * 2) / spanY);
    const offsetX = (VIEW_W - spanX * scale) / 2;
    const offsetY = (VIEW_H - spanY * scale) / 2;

    const project = ([lon, lat]: number[]): [number, number] => [
      offsetX + (lon - minLon) * lonScale * scale,
      // Flip: SVG y grows downward, latitude grows upward.
      offsetY + (maxLat - lat) * scale,
    ];

    const trips = volume?.trips ?? {};
    const peak = Math.max(1, ...Object.values(trips));

    const ranked = DATA.zones
      .map((z) => ({ zone: z, trips: trips[String(z.id)] ?? 0 }))
      .filter((r) => r.trips > 0)
      .sort((a, b) => b.trips - a.trips)
      .slice(0, 5);

    return {
      paths: DATA.zones.map((zone) => ({
        zone,
        trips: trips[String(zone.id)],
        d: zone.rings
          .map(
            (ring) =>
              "M " +
              ring
                .map((point) => project(point).map((n) => n.toFixed(1)).join(","))
                .join(" L ") +
              " Z",
          )
          .join(" "),
      })),
      boroughs: [...new Set(DATA.zones.map((z) => z.borough).filter(Boolean))] as string[],
      maxLog: Math.log10(peak),
      top: ranked,
    };
  }, [volume]);

  const hoveredTrips = hovered ? volume?.trips?.[String(hovered.id)] : undefined;

  return (
    <div className="space-y-3">
      <p className="prose-evidence m-0">
        {stale ? (
          <>
            These are the {DATA.zones.length} zones that stale lookup table
            defines. Every trip record downstream resolves its pickup and dropoff
            through one of these polygons, so a stale zone table is{" "}
            <span className="text-oxide">stale geography</span>, not just a stale
            row count.
          </>
        ) : (
          <>
            The {DATA.zones.length} zones the taxi lookup table defines. Every
            trip record downstream resolves its pickup and dropoff through one of
            these polygons.
          </>
        )}
      </p>

      {volume && (
        <p className="prose-evidence m-0">
          Shaded by real pickup volume:{" "}
          <span className="text-amber">
            {volume.total_trips.toLocaleString()} trips
          </span>{" "}
          across {volume.zones_covered} zones, every one of them resolved through
          a definition in that table.
        </p>
      )}

      {/* View switch. Only offered once there is something to switch to. */}
      {volume && (
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

      {volumeFailed && (
        <p className="prose-evidence m-0 text-muted">
          Pickup volume is unavailable right now, so the map is shaded by borough
          instead. An unshaded choropleth would read as <em>no trips here</em>,
          which is not what a failed request means.
        </p>
      )}

      <figure className="well m-0 overflow-hidden p-2">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
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
              ? // Floor of 0.06 so a zero-traffic zone is still visibly part of the
                // city rather than a hole in the map.
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
              >
                <title>
                  {zone.zone}
                  {trips !== undefined ? ` — ${trips.toLocaleString()} pickups` : ""}
                </title>
              </path>
            );
          })}
        </svg>
      </figure>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {showVolume ? (
          <VolumeLegend />
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

      {top.length > 0 && (
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
                  {trips.toLocaleString()}
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
        , simplified for delivery — 98,192 points reduced to 7,286, which is
        indistinguishable at this size and about a twenty-fifth of the payload.
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
            </a>{" "}
            at request time — the browser never receives the trip data. That
            dataset is historical, so these totals are stable rather than moving
            minute to minute; what moves is the lookup table&rsquo;s freshness.
            Shading is logarithmic, because the range runs from one pickup to two
            million and a linear ramp would show only the airports.
          </>
        )}
      </p>
    </div>
  );
}

/** Continuous ramp, labelled at decade boundaries since the scale is log. */
function VolumeLegend() {
  return (
    <div className="flex items-center gap-2">
      <span className="label">Pickups</span>
      <span
        aria-hidden
        className="h-2 w-28"
        style={{
          background:
            "linear-gradient(to right, color-mix(in oklab, var(--color-amber) 6%, transparent), var(--color-amber))",
        }}
      />
      <span className="label text-bone-dim">1 → 2M</span>
    </div>
  );
}
