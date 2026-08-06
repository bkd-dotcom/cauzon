/**
 * The wire contract, mirroring `agent/cauzon/models.py`.
 *
 * Kept hand-written and narrow rather than generated: it is small enough to
 * read in one sitting, and every field here is one a component actually renders.
 * If the Python `to_dict()` shapes change, this file is the single place the
 * frontend needs to follow.
 */

export type Signal =
  | "freshness_lag"
  | "schema_change"
  | "volume_anomaly"
  | "row_fanout"
  | "failed_assertion"
  | "recent_query_change"
  | "upstream_incident";

/** How well a finding can be *proven* — not merely how highly it ranked. */
export type GroundingLevel = "path_and_transform" | "path_only" | "ungrounded";

export type Phase = "detect" | "scope" | "hypothesize" | "prove" | "writeback";

export interface Incident {
  urn: string;
  title: string;
  description: string;
  failed_assertion?: string | null;
  detected_at?: string | null;
}

export interface CandidateCause {
  urn: string;
  name: string;
  hops_from_symptom: number;
  signals: Signal[];
  score: number;
  evidence_notes: string[];
  /** The fault appears to start here, rather than being inherited from upstream. */
  is_origin: boolean;
  /** Set when the proof gate eliminated this candidate. */
  rejected_reason: string | null;
  owner: string | null;
}

export interface ProofEdge {
  from: string;
  to: string;
  via_query?: string | null;
}

export interface ProofPath {
  symptom_urn: string;
  cause_urn: string;
  /** Ordered cause → symptom. */
  nodes: string[];
  edges: ProofEdge[];
  transform_sql: string | null;
  /** Which edge the transform SQL came from — the edge that carried the fault. */
  causal_edge_index: number | null;
  grounding: GroundingLevel;
  grounding_label: string;
  verified: boolean;
}

export interface ConfidenceBreakdown {
  grounding_factor: number;
  signal_factor: number;
  origin_factor: number;
  grounding_reason: string;
  signal_reason: string;
  origin_reason: string;
  total: number;
}

export interface RecommendedFix {
  summary: string;
  action_kind: "sql" | "command" | "manual";
  action: string | null;
  action_note: string | null;
}

export interface PriorIncident {
  document_urn: string;
  title: string;
  detected_at?: string | null;
}

export interface Recurrence {
  asset_urn: string;
  prior: PriorIncident[];
  count: number;
  is_recurring: boolean;
}

export interface Diagnosis {
  incident: Incident;
  root_cause: CandidateCause | null;
  proof_path: ProofPath | null;
  ranked_candidates: CandidateCause[];
  recommended_fix: RecommendedFix | null;
  confidence: number;
  confidence_breakdown: ConfidenceBreakdown | null;
  grounding: GroundingLevel;
  grounding_label: string;
  grounded: boolean;
  recurrence: Recurrence | null;
  narrative: string | null;
  narrative_source: "template" | "llm";
  /** Attached by the API layer, not the agent core. */
  write_backs?: WriteBack[];
  trace?: TraceEvent[];
}

export interface TraceEvent {
  phase: Phase;
  message: string;
  data?: Record<string, unknown> | null;
}

export type WriteBack =
  | { op: "save_document"; urn: string; title: string; related: string[] }
  | { op: "add_tags"; urn: string; tags: string[] }
  | { op: "update_description"; urn: string; description: string };

/** A node as the lineage graph needs it — resolved from trace + diagnosis. */
export interface SpineNode {
  urn: string;
  name: string;
  role: "cause" | "carrier" | "symptom" | "rejected";
  signals: Signal[];
  score: number;
  hops: number;
  isOrigin: boolean;
  rejectedReason: string | null;
  owner: string | null;
  evidence: string[];
}

export const SIGNAL_LABELS: Record<Signal, string> = {
  freshness_lag: "freshness lag",
  schema_change: "schema change",
  volume_anomaly: "volume anomaly",
  row_fanout: "key fanout",
  failed_assertion: "failed assertion",
  recent_query_change: "query change",
  upstream_incident: "upstream incident",
};

export const PHASE_LABELS: Record<Phase, string> = {
  detect: "Detect",
  scope: "Scope",
  hypothesize: "Hypothesize",
  prove: "Prove",
  writeback: "Write back",
};

/** Short, human name from a DataHub dataset URN. */
export function shortName(urn: string): string {
  const parts = urn.split(",");
  if (parts.length < 2) return urn;
  const qualified = parts[1];
  const last = qualified.split(".").pop();
  return last ?? qualified;
}

/** Platform slug from a DataHub URN, e.g. "snowflake". */
export function platformOf(urn: string): string | null {
  const m = urn.match(/dataPlatform:([^,)]+)/);
  return m ? m[1] : null;
}
