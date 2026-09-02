export type JsonPrimitive = string | number | boolean | null;

export type JsonValue =
  | JsonPrimitive
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };

export const STORY_LEDGER_FACT_TYPES = [
  "character_state",
  "relationship_state",
  "storyline_event",
  "foreshadow_event",
  "story_time",
  "knowledge_event",
  "world_state",
  "general_fact",
] as const;

export type StoryLedgerFactType = (typeof STORY_LEDGER_FACT_TYPES)[number];

export const STORY_LEDGER_EFFECTIVE_STATES = [
  "current",
  "historical",
  "superseded",
  "source_invalid",
  "batch_reverted",
] as const;

export type StoryLedgerFactEffectiveState =
  (typeof STORY_LEDGER_EFFECTIVE_STATES)[number];

export const STORY_LEDGER_HEALTH_STATES = ["ok", "conflict", "ambiguous"] as const;
export type StoryLedgerFactHealth = (typeof STORY_LEDGER_HEALTH_STATES)[number];

export type StoryLedgerEntityType =
  | "character"
  | "character_instance"
  | "relationship"
  | "storyline"
  | "foreshadow";

export interface StoryLedgerTimelineContext {
  readonly mode: "none" | "single" | "multiple";
  readonly timeline_id: string | null;
  readonly timeline_name: string | null;
  readonly narrative_cutoff: number | null;
}

export interface StoryLedgerEntityReference {
  readonly entity_type: StoryLedgerEntityType;
  readonly entity_id: string;
  readonly label: string;
  readonly lifecycle_state: string | null;
  readonly reference_missing: boolean;
}

export interface StoryLedgerSourceReference {
  readonly source_document_id: string | null;
  readonly document_title: string | null;
  readonly document_position: number | null;
  readonly source_revision_id: string | null;
  readonly revision_number: number | null;
  readonly revision_is_current: boolean | null;
  readonly source_content_hash: string | null;
  readonly source_start: number | null;
  readonly source_end: number | null;
  readonly binding_state: string | null;
  readonly commit_batch_id: string | null;
  readonly evidence_available: boolean;
}

export interface StoryLedgerFactItem {
  readonly id: string;
  readonly fact_type: string;
  readonly subject: string;
  readonly predicate: string;
  readonly object_preview: string;
  readonly object_truncated: boolean;
  readonly timeline_id: string | null;
  readonly dimension: string | null;
  readonly event_kind: string | null;
  readonly story_sequence: number | null;
  readonly created_at: string;
  readonly effective_state: StoryLedgerFactEffectiveState;
  readonly effective_reason_codes: readonly string[];
  readonly included_in_current_projection: boolean;
  readonly health: StoryLedgerFactHealth;
  readonly health_reason_codes: readonly string[];
  readonly entities: readonly StoryLedgerEntityReference[];
  readonly source: StoryLedgerSourceReference | null;
}

export interface StoryLedgerEventLinkView {
  readonly id: string;
  readonly direction: "incoming" | "outgoing";
  readonly link_type: string;
  readonly other_fact_id: string;
  readonly details: Readonly<Record<string, JsonValue>>;
  readonly created_at: string;
}

export interface StoryLedgerBindingView {
  readonly id: string;
  readonly source_document_id: string;
  readonly source_revision_id: string;
  readonly source_content_hash: string;
  readonly validity_state: string;
  readonly proposal_item_id: string | null;
  readonly commit_batch_id: string | null;
  readonly commit_batch_state: string | null;
  readonly created_at: string;
}

export interface StoryLedgerSummary {
  readonly schema_version: "story-ledger-summary/1";
  readonly novel_id: string;
  readonly ledger_snapshot_token: string;
  readonly story_ledger_version: number;
  readonly timeline: StoryLedgerTimelineContext;
  readonly filter_sha256: string;
  readonly total: number;
  readonly by_fact_type: Readonly<Record<string, number>>;
  readonly by_effective_state: Readonly<Record<string, number>>;
  readonly by_health: Readonly<Record<string, number>>;
  readonly review_required: number;
}

export interface StoryLedgerFactPage {
  readonly schema_version: "story-ledger-page/1";
  readonly novel_id: string;
  readonly ledger_snapshot_token: string;
  readonly story_ledger_version: number;
  readonly timeline: StoryLedgerTimelineContext;
  readonly filter_sha256: string;
  readonly items: readonly StoryLedgerFactItem[];
  readonly next_cursor: string | null;
}

export interface StoryLedgerFactDetail {
  readonly schema_version: "story-ledger-fact-detail/1";
  readonly novel_id: string;
  readonly ledger_snapshot_token: string;
  readonly story_ledger_version: number;
  readonly timeline: StoryLedgerTimelineContext;
  readonly item: StoryLedgerFactItem;
  readonly object_text: string;
  readonly details: Readonly<Record<string, JsonValue>>;
  readonly story_time: Readonly<Record<string, JsonValue>> | null;
  readonly visibility: Readonly<Record<string, JsonValue>> | null;
  readonly lifecycle_status: string;
  readonly schema_version_of_fact: string | null;
  readonly event_fingerprint: string | null;
  readonly event_links: readonly StoryLedgerEventLinkView[];
  readonly bindings: readonly StoryLedgerBindingView[];
}

export interface StoryLedgerSourceExcerpt {
  readonly schema_version: "story-ledger-source/1";
  readonly novel_id: string;
  readonly fact_id: string;
  readonly ledger_snapshot_token: string;
  readonly story_ledger_version: number;
  readonly timeline: StoryLedgerTimelineContext;
  readonly available: boolean;
  readonly unavailable_reason: string | null;
  readonly document_id: string | null;
  readonly document_title: string | null;
  readonly document_position: number | null;
  readonly revision_id: string | null;
  readonly revision_number: number | null;
  readonly revision_is_current: boolean | null;
  readonly source_content_hash: string | null;
  readonly source_range_hash: string | null;
  readonly source_start: number | null;
  readonly source_end: number | null;
  readonly excerpt: string;
  readonly excerpt_start: number | null;
  readonly excerpt_end: number | null;
  readonly highlight_start: number | null;
  readonly highlight_end: number | null;
  readonly truncated_before: boolean;
  readonly truncated_after: boolean;
}

export interface StoryLedgerFactImpactPreview {
  readonly schema_version: "story-ledger-fact-impact-preview/1";
  readonly novel_id: string;
  readonly fact_id: string;
  readonly preview_snapshot_token: string;
  readonly story_ledger_version: number;
  readonly timeline: StoryLedgerTimelineContext;
  readonly currently_in_projection: boolean;
  readonly current_projection_fact_count: number;
  readonly related_event_link_count: number;
  readonly embedding_rebuild_required: boolean;
  readonly commit_batch_ids: readonly string[];
  readonly batch_fact_count: number;
  readonly batch_relationship_count: number;
  readonly correction_supported: boolean;
  readonly correction_block_reason: string | null;
}

export interface StoryLedgerBatchFactImpact extends Readonly<Record<string, JsonValue>> {
  readonly id: string;
  readonly disposition: "preserve_followup" | "supersede" | "preserve";
}

export interface StoryLedgerBatchRelationshipImpact
  extends Readonly<Record<string, JsonValue>> {
  readonly id: string;
  readonly disposition: "preserve_root_reproject_visibility";
}

export interface StoryLedgerBatchImpactPreview {
  readonly schema_version: "story-ledger-batch-impact-preview/1";
  readonly novel_id: string;
  readonly batch_id: string;
  readonly preview_snapshot_token: string;
  readonly story_ledger_version: number;
  readonly timeline: StoryLedgerTimelineContext;
  readonly state: string;
  readonly already_reverted: boolean;
  readonly batch_fact_count: number;
  readonly batch_relationship_count: number;
  readonly facts: readonly StoryLedgerBatchFactImpact[];
  readonly relationships: readonly StoryLedgerBatchRelationshipImpact[];
}

export interface StoryLedgerFilters {
  readonly factTypes?: readonly string[];
  readonly effectiveState?: StoryLedgerFactEffectiveState | null;
  readonly health?: StoryLedgerFactHealth | null;
  readonly dimension?: string | null;
  readonly sourceDocumentId?: string | null;
  readonly commitBatchId?: string | null;
  readonly factTimelineId?: string | null;
  readonly entityType?: StoryLedgerEntityType | null;
  readonly entityId?: string | null;
  readonly reviewOnly?: boolean;
}

export interface StoryLedgerReadScope {
  readonly novelId: string;
  readonly timelineId?: string | null;
  readonly narrativeCutoff?: number | null;
  readonly snapshotToken?: string | null;
}

export interface StoryLedgerPageQuery extends StoryLedgerFilters {
  readonly cursor?: string | null;
  readonly limit?: number;
}

export interface StoryFactCorrectionCommandV1 {
  readonly schema_version: "story-fact-correction/1";
  readonly operation_key: string;
  readonly expected_story_ledger_version: number;
  readonly reason: string;
  readonly replacement: Readonly<Record<string, JsonValue>>;
}

export interface StoryFactCorrectionResultV1 {
  readonly replayed: boolean;
  readonly story_ledger_version: number;
  readonly fact: Readonly<Record<string, JsonValue>>;
}

export interface IntelligenceBatchRevertCommandV1 {
  readonly operation_key: string;
  readonly expected_story_ledger_version: number;
  readonly reason?: string | null;
}

export interface IntelligenceBatchRevertResultV1 {
  readonly replayed: boolean;
  readonly story_ledger_version: number;
  readonly batch_id: string;
}
