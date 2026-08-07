"use client";

/**
 * The lineage spine — Cauzon's argument drawn as geometry.
 *
 * Not a force-directed graph. A chain of custody: the proven path is one
 * continuous illuminated line, and a candidate that cannot be connected to the
 * symptom floats above it with a connector that visibly stops short. Attached
 * means provable. Severed means rejected. The reader gets the thesis before
 * reading a word of it.
 *
 * Vertical position encodes epistemic status, matching the palette:
 *   top    (oxide)  — signals present, no provable path. Rejected.
 *   middle (jade)   — the proven path.
 *   bottom (muted)  — real upstreams with no anomaly. Cleared.
 *
 * Implementation note: positioning and animation live on *separate* groups. A
 * CSS `transform` in a keyframe overrides SVG's `transform` attribute, so
 * animating a plate that also carries `transform="translate(...)"` collapses it
 * to the origin.
 */

import { useMemo } from "react";

import { peakScore, type SpineModel } from "@/lib/spine";
import { SIGNAL_LABELS, ellipsise, platformOf, type SpineNode } from "@/lib/types";

const VIEW_W = 980;
const PLATE_W = 172;
const PLATE_H = 58;
const MARGIN_X = 26;

/** Room below a plate for its signal caption. */
const CAPTION_H = 20;
/** Room for the severed connector between the rejected band and the spine. */
const SEVER_H = 62;
/** Room below the spine for the transform-SQL edge tag. */
const EDGE_TAG_H = 27;
/** The visible gap that makes "no path exists" legible at a glance. */
const SEVER_GAP = 24;

interface Props {
  model: SpineModel;
  /** Staggers the reveal while a run is streaming. */
  running?: boolean;
  onSelect?: (node: SpineNode) => void;
  selectedUrn?: string | null;
}

interface Placed {
  node: SpineNode;
  x: number;
  y: number;
}

function layoutRow(nodes: SpineNode[], y: number): Placed[] {
  if (!nodes.length) return [];
  const usable = VIEW_W - MARGIN_X * 2;
  if (nodes.length === 1) {
    return [{ node: nodes[0], x: MARGIN_X + (usable - PLATE_W) / 2, y }];
  }
  const step = (usable - PLATE_W) / (nodes.length - 1);
  return nodes.map((node, i) => ({ node, x: MARGIN_X + step * i, y }));
}

/**
 * Stack only the bands that have content, so an incident with no rejected
 * candidate (or no cleared upstreams) doesn't leave a hole in the diagram.
 */
function layoutBands(model: SpineModel) {
  let y = 18;
  const rows: { detached: number; spine: number; cleared: number } = {
    detached: 0,
    spine: 0,
    cleared: 0,
  };

  if (model.detached.length) {
    rows.detached = y;
    y += PLATE_H + CAPTION_H + SEVER_H;
  }
  rows.spine = y;
  y += PLATE_H + CAPTION_H + (model.proven ? EDGE_TAG_H : 8);

  if (model.cleared.length) {
    rows.cleared = y + 10;
    y = rows.cleared + PLATE_H + CAPTION_H;
  }

  return { rows, height: y + 6 };
}

export default function LineageSpine({
  model,
  running = false,
  onSelect,
  selectedUrn,
}: Props) {
  const { rows, height } = useMemo(() => layoutBands(model), [model]);

  const spine = useMemo(
    () => layoutRow(model.spine, rows.spine),
    [model.spine, rows.spine],
  );
  const detached = useMemo(
    () => layoutRow(model.detached, rows.detached),
    [model.detached, rows.detached],
  );
  const cleared = useMemo(
    () => layoutRow(model.cleared, rows.cleared),
    [model.cleared, rows.cleared],
  );

  const peak = peakScore(model);
  const proven = model.proven && model.phases.has("prove");
  const ranked = model.phases.has("hypothesize");

  const spinePoints = spine.map((p) => ({
    x: p.x + PLATE_W / 2,
    y: p.y + PLATE_H / 2,
  }));
  const spineLength = spinePoints.reduce(
    (total, point, i) =>
      i === 0 ? 0 : total + Math.abs(point.x - spinePoints[i - 1].x),
    0,
  );

  if (!spine.length && !detached.length) {
    return (
      <div className="flex h-[200px] items-center justify-center px-6 text-center">
        <p className="label max-w-sm leading-relaxed">
          Run an investigation to trace the lineage graph
        </p>
      </div>
    );
  }

  const causeName = model.spine[0]?.name;
  const symptomName = model.spine[model.spine.length - 1]?.name;

  return (
    /* The spine is inherently wide. On a phone, panning it at a legible size
       beats shrinking the labels to nothing. */
    <figure className="m-0 -mx-2 overflow-x-auto px-2">
      <svg
        viewBox={`0 0 ${VIEW_W} ${height}`}
        className="h-auto w-full min-w-[680px]"
        role="img"
        aria-label={
          proven
            ? `Proven lineage path from ${causeName} to ${symptomName}${
                model.detached.length
                  ? `. ${model.detached.length} candidate rejected for having no path to the symptom.`
                  : ""
              }`
            : "Lineage graph of candidate root causes"
        }
      >
        <defs>
          <marker
            id="spine-arrow"
            viewBox="0 0 8 8"
            refX="6"
            refY="4"
            markerWidth="7"
            markerHeight="7"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 z" fill="var(--color-jade)" />
          </marker>
          <marker
            id="pending-arrow"
            viewBox="0 0 8 8"
            refX="6"
            refY="4"
            markerWidth="7"
            markerHeight="7"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 z" fill="var(--color-line-bright)" />
          </marker>
        </defs>

        {/* Band labels: the vertical axis is epistemic status, so it is named. */}
        {detached.length > 0 && (
          <BandLabel
            y={rows.detached - 10}
            text="No path to symptom — rejected"
            tone="oxide"
          />
        )}
        {spine.length > 0 && (
          <BandLabel
            y={rows.spine - 10}
            text={proven ? "Proven lineage path" : "Candidate path"}
            tone={proven ? "jade" : "muted"}
          />
        )}
        {cleared.length > 0 && (
          <BandLabel
            y={rows.cleared - 10}
            text="Cleared — no anomaly signal"
            tone="muted"
          />
        )}

        {/* The spine. Dashed grey while unproven; draws in jade once proven. */}
        {spinePoints.length > 1 && (
          <>
            <polyline
              points={spinePoints.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none"
              stroke="var(--color-line-bright)"
              strokeWidth="1.5"
              strokeDasharray="3 4"
              markerEnd={proven ? undefined : "url(#pending-arrow)"}
            />
            {proven && (
              <polyline
                points={spinePoints.map((p) => `${p.x},${p.y}`).join(" ")}
                fill="none"
                stroke="var(--color-jade)"
                strokeWidth="2"
                markerEnd="url(#spine-arrow)"
                style={
                  {
                    "--spine-length": spineLength,
                    strokeDasharray: spineLength,
                    animation: "spine-draw 1s cubic-bezier(0.4,0,0.2,1) both",
                  } as React.CSSProperties
                }
              />
            )}
          </>
        )}

        {/* Which edge actually carried the fault downstream. */}
        {proven &&
          model.causalEdgeIndex !== null &&
          spinePoints[model.causalEdgeIndex] &&
          spinePoints[model.causalEdgeIndex + 1] && (
            <EdgeTag
              x={
                (spinePoints[model.causalEdgeIndex].x +
                  spinePoints[model.causalEdgeIndex + 1].x) /
                2
              }
              y={rows.spine + PLATE_H + CAPTION_H}
            />
          )}

        {/* Severed connectors: the gap is the whole point. */}
        {detached.map((placed) => (
          <SeveredConnector
            key={`sever-${placed.node.urn}`}
            x={placed.x + PLATE_W / 2}
            fromY={placed.y + PLATE_H + CAPTION_H}
            toY={rows.spine}
            severed={proven}
          />
        ))}

        {[...spine, ...detached, ...cleared].map((placed, index) => (
          <Plate
            key={placed.node.urn}
            placed={placed}
            peak={peak}
            showScore={ranked}
            proven={proven}
            revealDelay={running ? index * 70 : 0}
            selected={selectedUrn === placed.node.urn}
            onSelect={onSelect}
          />
        ))}
      </svg>
    </figure>
  );
}

function BandLabel({
  y,
  text,
  tone,
}: {
  y: number;
  text: string;
  tone: "jade" | "oxide" | "muted";
}) {
  const fill =
    tone === "jade"
      ? "var(--color-jade)"
      : tone === "oxide"
        ? "var(--color-oxide)"
        : "var(--color-muted)";
  return (
    <text
      x={MARGIN_X}
      y={y}
      fill={fill}
      fontSize="10"
      fontWeight="600"
      letterSpacing="0.14em"
      style={{ textTransform: "uppercase" }}
    >
      {text}
    </text>
  );
}

function EdgeTag({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x - 44}, ${y})`}>
      <rect
        width="88"
        height="19"
        rx="2"
        fill="var(--color-ink-sunken)"
        stroke="var(--color-jade-dim)"
      />
      <text
        x="44"
        y="13"
        textAnchor="middle"
        fill="var(--color-jade)"
        fontSize="9"
        letterSpacing="0.1em"
      >
        TRANSFORM SQL
      </text>
    </g>
  );
}

/**
 * A connector that deliberately fails to arrive. Before the gate runs it
 * reaches toward the spine; once rejected it retracts and is struck through.
 */
function SeveredConnector({
  x,
  fromY,
  toY,
  severed,
}: {
  x: number;
  fromY: number;
  toY: number;
  severed: boolean;
}) {
  const end = severed ? toY - SEVER_GAP : toY - 4;
  const midpoint = (end + toY) / 2;
  return (
    <g>
      <line
        x1={x}
        y1={fromY}
        x2={x}
        y2={end}
        stroke={severed ? "var(--color-oxide)" : "var(--color-line-bright)"}
        strokeWidth="1.5"
        strokeDasharray="3 4"
        opacity={severed ? 0.75 : 1}
      />
      {severed && (
        <g stroke="var(--color-oxide)" strokeWidth="1.5">
          <line x1={x - 5} y1={midpoint - 5} x2={x + 5} y2={midpoint + 5} />
          <line x1={x + 5} y1={midpoint - 5} x2={x - 5} y2={midpoint + 5} />
        </g>
      )}
    </g>
  );
}

function Plate({
  placed,
  peak,
  showScore,
  proven,
  revealDelay,
  selected,
  onSelect,
}: {
  placed: Placed;
  peak: number;
  showScore: boolean;
  proven: boolean;
  revealDelay: number;
  selected: boolean;
  onSelect?: (node: SpineNode) => void;
}) {
  const { node, x, y } = placed;
  const rejected = node.role === "rejected" && proven;

  const tone =
    node.role === "rejected"
      ? { border: "var(--color-oxide-dim)", text: "var(--color-oxide)" }
      : node.role === "symptom"
        ? { border: "var(--color-amber-dim)", text: "var(--color-amber)" }
        : node.role === "cause" && proven
          ? { border: "var(--color-jade-dim)", text: "var(--color-jade)" }
          : { border: "var(--color-line)", text: "var(--color-bone)" };

  const platform = platformOf(node.urn);
  const interactive = Boolean(onSelect);
  const barWidth = PLATE_W - 24;
  // Long asset names would otherwise run under the score, so the name gets the
  // full plate width and the score sits on the row above it.
  const nameSize = node.name.length > 17 ? 12 : 13.5;
  // Live-catalog names are long enough to run off the plate entirely
  // (`2023_yellow_taxi_trip_data` overshoots by about 30px), which also drags the
  // group's focus outline out over its neighbours. Truncate from the middle: both
  // ends of a dataset name carry meaning, so `2023_yellow…rip_data` identifies it
  // where a trailing ellipsis would not. The full name is in the title and in the
  // detail panel a click away.
  const label = ellipsise(node.name, nameSize === 12 ? 20 : 18);

  return (
    /* Outer group positions. Inner group animates. Keeping these separate is
       load-bearing: a CSS transform in a keyframe overrides the SVG transform
       attribute, which would collapse every plate onto the origin. */
    <g transform={`translate(${x}, ${y})`}>
      <g
        className="plate-hit anim-plate-land"
        style={{
          animationDelay: `${revealDelay}ms`,
          cursor: interactive ? "pointer" : "default",
        }}
        role={interactive ? "button" : undefined}
        tabIndex={interactive ? 0 : undefined}
        aria-label={`${node.name}${
          node.signals.length ? `, ${node.signals.length} signals` : ", no signals"
        }${rejected ? ", rejected: no path to symptom" : ""}`}
        onClick={() => onSelect?.(node)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect?.(node);
          }
        }}
      >
        {/* The pulse draws the eye to the asset that alerted. Once the plate is
            selected that job is done, and keeping it would stack a second ring
            outside the selection border for no added meaning — the amber name
            still says which node is the symptom. */}
        {node.role === "symptom" && !selected && (
          <rect
            className="anim-pulse-symptom"
            x="-4"
            y="-4"
            width={PLATE_W + 8}
            height={PLATE_H + 8}
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
          stroke={selected ? "var(--color-bone-dim)" : tone.border}
          strokeWidth={selected ? 1.5 : 1}
        />

        {/* Keyboard focus, shown via CSS on :focus-visible so a mouse click gets
            the selected border alone rather than both indicators at once. */}
        <rect
          className="focus-ring"
          x="-3"
          y="-3"
          width={PLATE_W + 6}
          height={PLATE_H + 6}
          rx="4"
          fill="none"
          stroke="var(--color-jade)"
          strokeWidth="2"
        />

        {platform && (
          <text
            x="12"
            y="16"
            fill="var(--color-muted)"
            fontSize="8.5"
            letterSpacing="0.12em"
          >
            {platform.toUpperCase()}
          </text>
        )}

        {showScore && node.score > 0 && (
          <text
            x={PLATE_W - 12}
            y="16"
            textAnchor="end"
            fill="var(--color-muted)"
            fontSize="9.5"
          >
            {node.score.toFixed(1)}
          </text>
        )}

        {/* The full name is on the group's aria-label and in the detail panel a
            click away. Not a <title>: React 19 hoists those as document
            metadata, which breaks hydration. */}
        <text x="12" y="36" fill={tone.text} fontSize={nameSize} fontWeight="600">
          {label}
        </text>
        {rejected && (
          /* Drawn rather than text-decoration, which overshoots in SVG. */
          <line
            x1="12"
            y1="32"
            x2={12 + label.length * nameSize * 0.58}
            y2="32"
            stroke="var(--color-oxide)"
            strokeWidth="1.25"
          />
        )}

        {/* Score bar grows during `hypothesize`, which is when ranking happens. */}
        {showScore && node.score > 0 && (
          <>
            <rect
              x="12"
              y="46"
              width={barWidth}
              height="3"
              fill="var(--color-line)"
              rx="1.5"
            />
            <rect
              className="anim-score"
              x="12"
              y="46"
              width={barWidth * Math.min(node.score / peak, 1)}
              height="3"
              rx="1.5"
              fill={node.role === "rejected" ? "var(--color-oxide)" : "var(--color-jade)"}
              style={{ animationDelay: `${revealDelay + 120}ms` }}
            />
          </>
        )}
      </g>

      {node.signals.length > 0 && (
        <text x="1" y={PLATE_H + 15} fill="var(--color-muted)" fontSize="9.5">
          {node.signals.map((s) => SIGNAL_LABELS[s]).join(" · ")}
        </text>
      )}

    </g>
  );
}
