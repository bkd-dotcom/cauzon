"use client";

/**
 * The 263 real taxi zones the stale lookup table defines.
 *
 * This is the one view that is not about lineage, and it earns its place by
 * giving the abstraction a footprint: `NYC Taxi Zones` is 1.1 years stale, and
 * *this* is what it is a lookup for. Every trip record in every downstream
 * dataset resolves its pickup and dropoff through one of these polygons, so a
 * stale zone table is stale geography, not just a stale row count.
 *
 * Geometry is real, from the same dataset Cauzon reports on, simplified with
 * Douglas-Peucker for delivery (98,192 points to 7,286). No mapping library: a
 * plain equirectangular projection is accurate enough across a single city and
 * costs nothing.
 */

import { useMemo, useState } from "react";

import zoneData from "@/lib/taxi_zones.json";
import type { TaxiZone, TaxiZoneSet } from "@/lib/types";

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

export default function ZoneMap({ stale }: { stale?: boolean }) {
  const [hovered, setHovered] = useState<TaxiZone | null>(null);

  const { paths, boroughs } = useMemo(() => {
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

    return {
      paths: DATA.zones.map((zone) => ({
        zone,
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
    };
  }, []);

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

      <figure className="well m-0 overflow-hidden p-2">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="h-auto w-full"
          role="img"
          aria-label={`Map of ${DATA.zones.length} NYC taxi zones`}
        >
          {paths.map(({ zone, d }, i) => (
            <path
              key={`${zone.id ?? "z"}-${i}`}
              d={d}
              fill={(BOROUGH_FILL[zone.borough ?? ""] ?? DEFAULT_FILL).fill}
              fillOpacity={
                (BOROUGH_FILL[zone.borough ?? ""] ?? DEFAULT_FILL).opacity *
                (hovered && hovered !== zone ? 0.45 : 1)
              }
              stroke="var(--color-ink)"
              strokeWidth="0.5"
              onMouseEnter={() => setHovered(zone)}
              onMouseLeave={() => setHovered(null)}
              style={{ transition: "fill-opacity 120ms" }}
            />
          ))}
        </svg>
      </figure>

      <div className="flex flex-wrap items-center justify-between gap-3">
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
        <span className="label min-h-[1em] text-bone-dim">
          {hovered ? `${hovered.zone} · ${hovered.borough}` : "Hover a zone"}
        </span>
      </div>

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
      </p>
    </div>
  );
}
