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

/** Which field carried the fault, when column-level lineage exists. */
export interface ColumnPath {
  cause_field: string;
  symptom_field: string;
  /** Ordered cause -> symptom, one entry per node on the proof path. */
  fields: string[];
}

export interface ImpactedAsset {
  urn: string;
  name: string;
  hops_from_symptom: number;
  kind: "dataset" | "dashboard";
  owner: string | null;
  /** False means it is wrong and nobody is being told — the dangerous case. */
  is_alerting: boolean;
}

export interface BlastRadius {
  symptom_urn: string;
  impacted: ImpactedAsset[];
  count: number;
  silent_count: number;
}

export interface ProposedAssertion {
  target_urn: string;
  target_name: string;
  kind: "freshness" | "volume" | "uniqueness" | "schema_contract";
  description: string;
  definition: string;
  rationale: string;
  lead_time: string | null;
}

export interface TimelineEvent {
  at: string;
  asset_name: string;
  label: string;
  kind: "fault_origin" | "transform_ran" | "assertion_fired" | "detected";
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
  /** Null when the catalog has no column-level lineage to follow. */
  column_path: ColumnPath | null;
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
  // Optional, not just nullable: an older backend omits these keys entirely.
  // The UI deploys independently of the API, so it must tolerate the skew.
  blast_radius?: BlastRadius | null;
  proposed_assertion?: ProposedAssertion | null;
  timeline?: TimelineEvent[];
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

/** What the backend reports about itself, from GET /api/health. */
export interface LiveSource {
  name: string;
  url: string;
  /** Freshness read live from the source of truth on every refresh. */
  signals_are_live: boolean;
  /** The catalog publishes no lineage; the graph is declared by this project. */
  lineage_is_declared: boolean;
  supports_writeback: boolean;
  /** Non-null when the last refresh failed, so the UI can flag possible staleness. */
  fetch_error: string | null;
}

export interface Health {
  status: string;
  /**
   * "mock" = planted in-memory graph, three fixed faults.
   * "live" = real public catalog; incident list is whatever is genuinely stale.
   * "mcp"  = a real DataHub instance.
   */
  datahub_backend: "mock" | "live" | "mcp";
  write_back_allowed: boolean;
  /** Base URL of the DataHub UI, when there is a real one to link to. */
  datahub_ui_url: string | null;
  live_source?: LiveSource | null;
}

/** Deep link to an asset in the DataHub UI, so a finding can be checked. */
export function datahubAssetUrl(uiBase: string, urn: string): string {
  return `${uiBase.replace(/\/$/, "")}/dataset/${encodeURIComponent(urn)}/`;
}

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

export const ASSERTION_KIND_LABELS: Record<
  ProposedAssertion["kind"],
  string
> = {
  freshness: "Freshness check",
  volume: "Volume check",
  uniqueness: "Uniqueness check",
  schema_contract: "Schema contract",
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
/**
 * Shorten a name to fit a fixed-width plate, cutting from the middle.
 *
 * Dataset names carry meaning at both ends — `2023_yellow_taxi_trip_data` is
 * identified by its year and by what it holds — so a trailing ellipsis throws
 * away half of what distinguishes it from its siblings.
 */
export function ellipsise(name: string, max: number): string {
  if (name.length <= max) return name;
  // Two characters of the budget go to the ellipsis and the join, so the head
  // gets the larger half when the remainder is odd.
  const keep = max - 1;
  const head = Math.ceil(keep / 2);
  const tail = keep - head;
  return `${name.slice(0, head)}…${tail > 0 ? name.slice(-tail) : ""}`;
}

export function platformOf(urn: string): string | null {
  const m = urn.match(/dataPlatform:([^,)]+)/);
  return m ? m[1] : null;
}

/** One row of the triage inbox — enriched enough to sort without investigating. */
export interface InboxEntry {
  urn: string;
  name: string;
  title: string;
  /**
   * critical — at least twice its own freshness SLA
   * overdue  — past its SLA but not yet double
   * failing  — an assertion is failing while freshness is fine, so this is not
   *            a staleness problem and must not be labelled as one
   */
  severity: "critical" | "overdue" | "failing";
  platform: string | null;
  owner: string | null;
  failed_assertion: string | null;
  detected_at: string | null;
  freshness_hours: number | null;
  expected_freshness_hours: number | null;
  /** How many times past its own SLA. 2.0 or more counts as critical. */
  overdue_ratio: number | null;
  signals: Signal[];
  downstream_count: number;
  upstream_count: number;
}

export type AssetHealth = "incident" | "overdue" | "healthy" | "unknown";

export interface CatalogNode {
  urn: string;
  name: string;
  /** Longest path from a root, so a node always draws right of its upstreams. */
  depth: number;
  health: AssetHealth;
  platform: string | null;
  owner: string | null;
  signals: Signal[];
  freshness_hours: number | null;
  expected_freshness_hours: number | null;
}

export interface CatalogMap {
  nodes: CatalogNode[];
  edges: { from: string; to: string }[];
  counts: {
    total: number;
    incident: number;
    overdue: number;
    healthy: number;
  };
}

/** Real pickup volume per zone id, aggregated by Socrata at request time. */
export interface ZoneVolume {
  /** Zone id (the lookup table's own `locationid`) to pickup count. */
  trips: Record<string, number>;
  total_trips: number;
  zones_covered: number;
  dataset_id: string;
  dataset_label: string;
  source_url: string;
  /** True when the fetch failed and this is a reused or empty snapshot. */
  stale: boolean;
  error?: string;
}

/** Real NYC taxi-zone geometry, simplified for the browser. */
export interface TaxiZone {
  id: string | null;
  zone: string | null;
  borough: string | null;
  rings: number[][][];
}

export interface TaxiZoneSet {
  source: string;
  dataset_id: string;
  note: string;
  zones: TaxiZone[];
}

/** Readable age from a freshness lag in hours. Mirrors the agent's formatting. */
export function humaniseHours(hours: number | null): string {
  if (hours === null) return "unknown";
  if (hours < 48) return `${Math.round(hours)}h`;
  const days = hours / 24;
  if (days < 90) return `${Math.round(days)} days`;
  return `${(days / 365).toFixed(1)} years`;
}
