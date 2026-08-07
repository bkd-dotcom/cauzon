"use client";

/**
 * The catalog map — every asset at once, health marked.
 *
 * The investigation view answers "why did this break". This answers the question
 * you start from: what is the state of everything, and are several incidents
 * sharing an upstream cause. It reuses the investigation's visual language on
 * purpose — same plates, same palette, same meaning for each colour — so moving
 * between the two views does not require relearning anything.
 *
 * Layout is by depth: a node always draws to the right of everything it depends
 * on, which makes "the problem is upstream" readable as a direction rather than
 * something you have to trace.
 */

import { useMemo } from "react";

import type { CatalogMap as CatalogMapData, CatalogNode } from "@/lib/types";
import { SIGNAL_LABELS, humaniseHours } from "@/lib/types";

const PLATE_W = 150;
const PLATE_H = 40;
const COL_GAP = 78;
const ROW_GAP = 18;
const MARGIN = 24;

const HEALTH_TONE: Record<
  CatalogNode["health"],
  { stroke: string; text: string; label: string }
> = {
  incident: {
    stroke: "var(--color-amber)",
    text: "var(--color-amber)",
    label: "open incident",
  },
  overdue: {
    stroke: "var(--color-oxide-dim)",
    text: "var(--color-oxide)",
    label: "carries a signal",
  },
  healthy: {
    stroke: "var(--color-line)",
    text: "var(--color-bone-dim)",
    label: "healthy",
  },
  unknown: {
    stroke: "var(--color-line)",
    text: "var(--color-muted)",
    label: "no signal data",
  },
};

interface Placed {
  node: CatalogNode;
  x: number;
  y: number;
}

export default function CatalogMap({
  data,
  onSelect,
  selectedUrn,
}: {
  data: CatalogMapData;
  onSelect?: (node: CatalogNode) => void;
  selectedUrn?: string | null;
}) {
  const { placed, width, height } = useMemo(() => {
    const columns = new Map<number, CatalogNode[]>();
    for (const node of data.nodes) {
      const column = columns.get(node.depth) ?? [];
      column.push(node);
      columns.set(node.depth, column);
    }

    const depths = [...columns.keys()].sort((a, b) => a - b);

    // Barycentre pass: order each column by the average row of its parents in the
    // column to its left. Alphabetical ordering makes unrelated clusters
    // interleave and their edges cross for no reason; this keeps a node near
    // whatever feeds it. One pass is enough for graphs this size.
    const rowOf = new Map<string, number>();
    const parentsOf = new Map<string, string[]>();
    for (const edge of data.edges) {
      parentsOf.set(edge.to, [...(parentsOf.get(edge.to) ?? []), edge.from]);
    }
    depths.forEach((depth) => {
      const column = columns.get(depth)!;
      column.sort((a, b) => {
        const key = (node: CatalogNode) => {
          const parents = parentsOf.get(node.urn) ?? [];
          const rows = parents
            .map((p) => rowOf.get(p))
            .filter((r): r is number => r !== undefined);
          // No positioned parent yet: fall back to the name so the order is at
          // least stable between renders.
          return rows.length
            ? rows.reduce((sum, r) => sum + r, 0) / rows.length
            : Number.MAX_SAFE_INTEGER;
        };
        const delta = key(a) - key(b);
        return delta !== 0 ? delta : a.name.localeCompare(b.name);
      });
      column.forEach((node, rowIndex) => rowOf.set(node.urn, rowIndex));
    });

    const tallest = Math.max(1, ...depths.map((d) => columns.get(d)!.length));

    const laid: Placed[] = [];
    depths.forEach((depth, columnIndex) => {
      const column = columns.get(depth)!;
      // Centre each column vertically so the graph reads as a shape rather than
      // a set of left-aligned lists.
      const offset = ((tallest - column.length) * (PLATE_H + ROW_GAP)) / 2;
      column.forEach((node, rowIndex) => {
        laid.push({
          node,
          x: MARGIN + columnIndex * (PLATE_W + COL_GAP),
          y: MARGIN + offset + rowIndex * (PLATE_H + ROW_GAP),
        });
      });
    });

    return {
      placed: laid,
      width: MARGIN * 2 + depths.length * (PLATE_W + COL_GAP) - COL_GAP,
      height: MARGIN * 2 + tallest * (PLATE_H + ROW_GAP) - ROW_GAP,
    };
  }, [data.nodes, data.edges]);

  const byUrn = useMemo(
    () => new Map(placed.map((p) => [p.node.urn, p])),
    [placed],
  );

  if (!data.nodes.length) {
    return (
      <p className="prose-evidence m-0">
        The catalog reported no assets.
      </p>
    );
  }

  return (
    <figure className="m-0 -mx-2 overflow-x-auto px-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        style={{ minWidth: Math.min(width, 900) }}
        role="img"
        aria-label={`Catalog map: ${data.counts.total} assets, ${data.counts.incident} with open incidents`}
      >
        <defs>
          <marker
            id="map-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 z" fill="var(--color-line-bright)" />
          </marker>
        </defs>

        {data.edges.map((edge, i) => {
          const from = byUrn.get(edge.from);
          const to = byUrn.get(edge.to);
          if (!from || !to) return null;
          const x1 = from.x + PLATE_W;
          const y1 = from.y + PLATE_H / 2;
          const x2 = to.x;
          const y2 = to.y + PLATE_H / 2;
          const mid = (x1 + x2) / 2;
          return (
            <path
              key={i}
              d={`M ${x1},${y1} C ${mid},${y1} ${mid},${y2} ${x2},${y2}`}
              fill="none"
              stroke="var(--color-line-bright)"
              strokeWidth="1.25"
              markerEnd="url(#map-arrow)"
            />
          );
        })}

        {placed.map(({ node, x, y }) => {
          const tone = HEALTH_TONE[node.health];
          const selected = selectedUrn === node.urn;
          const interactive = Boolean(onSelect);
          return (
            <g key={node.urn} transform={`translate(${x}, ${y})`}>
              <g
                role={interactive ? "button" : undefined}
                tabIndex={interactive ? 0 : undefined}
                aria-label={`${node.name}, ${tone.label}`}
                style={{ cursor: interactive ? "pointer" : "default" }}
                onClick={() => onSelect?.(node)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect?.(node);
                  }
                }}
              >
                {node.health === "incident" && (
                  <rect
                    className="anim-pulse-symptom"
                    x="-3"
                    y="-3"
                    width={PLATE_W + 6}
                    height={PLATE_H + 6}
                    rx="4"
                    fill="none"
                    stroke="var(--color-amber)"
                  />
                )}
                <rect
                  width={PLATE_W}
                  height={PLATE_H}
                  rx="3"
                  fill="var(--color-ink-raised)"
                  stroke={selected ? "var(--color-bone-dim)" : tone.stroke}
                  strokeWidth={selected ? 1.5 : 1}
                />
                <text x="10" y="17" fill={tone.text} fontSize="11.5" fontWeight="600">
                  {node.name.length > 19 ? `${node.name.slice(0, 18)}…` : node.name}
                </text>
                <text x="10" y="30" fill="var(--color-muted)" fontSize="8.5">
                  {[node.platform?.toUpperCase(), humaniseHours(node.freshness_hours)]
                    .filter(Boolean)
                    .join(" · ")}
                </text>
              </g>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function CatalogNodeDetail({ node }: { node: CatalogNode }) {
  return (
    <div className="well mt-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="text-sm font-semibold text-bone">{node.name}</span>
        <span className="label">{HEALTH_TONE[node.health].label}</span>
      </div>
      <dl className="m-0 mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Row label="Platform" value={node.platform ?? "—"} />
        <Row label="Owner" value={node.owner ?? "unassigned"} />
        <Row label="Last updated" value={humaniseHours(node.freshness_hours)} />
        <Row
          label="Expected within"
          value={
            node.expected_freshness_hours
              ? humaniseHours(node.expected_freshness_hours)
              : "—"
          }
        />
      </dl>
      {node.signals.length > 0 && (
        <p className="prose-evidence m-0 mt-3">
          Signals: {node.signals.map((s) => SIGNAL_LABELS[s]).join(", ")}
        </p>
      )}
      <code className="mt-3 block text-[11px] break-all text-muted">{node.urn}</code>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label m-0">{label}</dt>
      <dd className="m-0 text-[13px] text-bone-dim">{value}</dd>
    </div>
  );
}
