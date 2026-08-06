/**
 * Derive the lineage graph from whatever the agent has emitted so far.
 *
 * The graph is built progressively out of the live trace rather than assembled
 * from the finished diagnosis, so what the viewer watches really is the agent
 * reasoning: nodes appear when `scope` finds them, scores appear when
 * `hypothesize` ranks them, and the spine only connects once `prove` has
 * reconstructed a path.
 *
 * Nodes land in one of three bands, which is the whole argument of the product:
 *
 *   detached — carries anomaly signals but no lineage path reaches the symptom,
 *              so the proof gate rejected it. Drawn severed from the spine.
 *   spine    — the proven path, cause through to symptom.
 *   cleared  — a real upstream carrying no anomaly signal. Innocent.
 */

import type {
  CandidateCause,
  Diagnosis,
  Phase,
  Signal,
  SpineNode,
  TraceEvent,
} from "./types";
import { shortName } from "./types";

export interface SpineModel {
  symptomUrn: string | null;
  spine: SpineNode[];
  detached: SpineNode[];
  cleared: SpineNode[];
  /** True once a lineage path has actually been reconstructed. */
  proven: boolean;
  /** Index of the spine edge whose transform SQL was captured. */
  causalEdgeIndex: number | null;
  phases: Set<Phase>;
}

interface ScopeData {
  symptom_urn?: string;
  upstream?: { urn: string; name?: string; hops?: number }[];
}

const EMPTY: SpineModel = {
  symptomUrn: null,
  spine: [],
  detached: [],
  cleared: [],
  proven: false,
  causalEdgeIndex: null,
  phases: new Set(),
};

export function buildSpine(
  trace: TraceEvent[],
  diagnosis: Diagnosis | null,
): SpineModel {
  if (!trace.length && !diagnosis) return EMPTY;

  const phases = new Set<Phase>(trace.map((e) => e.phase));
  let symptomUrn: string | null = diagnosis?.incident.urn ?? null;
  const known = new Map<string, { name: string; hops: number }>();
  const rejectedUrns = new Set<string>();
  let pathUrns: string[] | null = null;
  let causalEdgeIndex: number | null = null;

  for (const event of trace) {
    const data = (event.data ?? {}) as ScopeData & Record<string, unknown>;

    if (event.phase === "detect" && typeof data.urn === "string") {
      symptomUrn = data.urn;
    }

    if (event.phase === "scope") {
      if (typeof data.symptom_urn === "string") symptomUrn = data.symptom_urn;
      for (const node of data.upstream ?? []) {
        known.set(node.urn, {
          name: node.name ?? shortName(node.urn),
          hops: node.hops ?? 1,
        });
      }
    }

    if (event.phase === "prove") {
      if (typeof data.rejected_urn === "string") rejectedUrns.add(data.rejected_urn);
      if (Array.isArray(data.nodes)) {
        pathUrns = data.nodes as string[];
        const idx = data.causal_edge_index;
        causalEdgeIndex = typeof idx === "number" ? idx : null;
      }
    }
  }

  // The finished diagnosis is authoritative once it lands.
  if (diagnosis?.proof_path) {
    pathUrns = diagnosis.proof_path.nodes;
    causalEdgeIndex = diagnosis.proof_path.causal_edge_index;
  }

  const candidates = new Map<string, CandidateCause>();
  const rankedFromTrace = lastHypothesisRanking(trace);
  for (const candidate of diagnosis?.ranked_candidates ?? rankedFromTrace) {
    candidates.set(candidate.urn, candidate);
    if (candidate.rejected_reason) rejectedUrns.add(candidate.urn);
  }

  const causeUrn = diagnosis?.root_cause?.urn ?? pathUrns?.[0] ?? null;

  const toNode = (
    urn: string,
    role: SpineNode["role"],
  ): SpineNode => {
    const candidate = candidates.get(urn);
    const fallback = known.get(urn);
    return {
      urn,
      name: candidate?.name ?? fallback?.name ?? shortName(urn),
      role,
      signals: (candidate?.signals ?? []) as Signal[],
      score: candidate?.score ?? 0,
      hops: candidate?.hops_from_symptom ?? fallback?.hops ?? 0,
      isOrigin: candidate?.is_origin ?? true,
      rejectedReason: candidate?.rejected_reason ?? null,
      owner: candidate?.owner ?? null,
      evidence: candidate?.evidence_notes ?? [],
    };
  };

  // ---- spine -------------------------------------------------------------- #
  // Before a path exists, order by distance from the symptom so the layout is
  // already the shape the proof will confirm — furthest upstream on the left.
  let spineUrns: string[];
  if (pathUrns?.length) {
    spineUrns = pathUrns;
  } else {
    const scoped = [...known.entries()]
      .filter(([urn]) => !rejectedUrns.has(urn))
      .sort((a, b) => b[1].hops - a[1].hops)
      .map(([urn]) => urn);
    spineUrns = symptomUrn ? [...scoped, symptomUrn] : scoped;
  }

  const spine = spineUrns.map((urn) =>
    toNode(
      urn,
      urn === symptomUrn ? "symptom" : urn === causeUrn ? "cause" : "carrier",
    ),
  );

  const onSpine = new Set(spineUrns);

  // ---- detached: signals, but unprovable ---------------------------------- #
  const detached = [...rejectedUrns]
    .filter((urn) => !onSpine.has(urn))
    .map((urn) => toNode(urn, "rejected"));

  // ---- cleared: real upstreams with nothing anomalous -------------------- #
  const cleared = [...known.keys()]
    .filter(
      (urn) =>
        !onSpine.has(urn) &&
        !rejectedUrns.has(urn) &&
        (candidates.get(urn)?.signals.length ?? 0) === 0,
    )
    .map((urn) => toNode(urn, "carrier"));

  return {
    symptomUrn,
    spine,
    detached,
    cleared,
    proven: Boolean(pathUrns?.length),
    causalEdgeIndex,
    phases,
  };
}

/** Candidate ranking from the most recent `hypothesize` event that carried one. */
function lastHypothesisRanking(trace: TraceEvent[]): CandidateCause[] {
  for (let i = trace.length - 1; i >= 0; i--) {
    const event = trace[i];
    if (event.phase !== "hypothesize") continue;
    const candidates = (event.data as { candidates?: CandidateCause[] } | null)
      ?.candidates;
    if (Array.isArray(candidates)) return candidates;
  }
  return [];
}

/** Highest score in the graph, for normalising the score bars. */
export function peakScore(model: SpineModel): number {
  const all = [...model.spine, ...model.detached, ...model.cleared];
  return all.reduce((max, node) => Math.max(max, node.score), 0) || 1;
}
