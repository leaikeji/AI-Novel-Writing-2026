import type {
  IntelligenceBatchRevertCommandV1 as SharedIntelligenceBatchRevertCommandV1,
  StoryFactCorrectionCommandV1 as SharedStoryFactCorrectionCommandV1,
  StoryFactCorrectionResultV1 as SharedStoryFactCorrectionResultV1,
  StoryLedgerFactEffectiveState,
  StoryLedgerFactHealth,
  StoryLedgerBatchImpactPreview,
} from "../story-ledger/contracts";

export type { JsonPrimitive, JsonValue } from "../story-ledger/contracts";
import type { JsonValue } from "../story-ledger/contracts";

export interface CharacterRootView {
  readonly id: string;
  readonly novel_id: string;
  readonly name: string;
  readonly role_type: string;
  readonly description: string;
  readonly details: Readonly<Record<string, JsonValue>>;
  readonly lifecycle_state: string;
  readonly position: number;
  readonly version: number;
  readonly current_revision_id: string | null;
}

export interface TimelineView {
  readonly id: string;
  readonly name: string;
  readonly timeline_kind: string;
  readonly is_primary: boolean;
  readonly parent_timeline_id: string | null;
  readonly fork_story_sequence: number | null;
}

export interface CharacterInstanceView {
  readonly id: string;
  readonly character_id: string;
  readonly origin_timeline_id: string;
  readonly continuity_kind: string;
  readonly display_label: string;
  readonly derived_from_instance_id: string | null;
  readonly lifecycle_state: string;
  readonly version: number;
  readonly current_revision_id: string | null;
  readonly profile: Readonly<Record<string, JsonValue>>;
  readonly profile_schema_version: number | null;
}

export interface CharacterAliasView {
  readonly id: string;
  readonly alias: string;
  readonly alias_kind: string | null;
  readonly timeline_id: string | null;
  readonly character_instance_id: string | null;
  readonly identity_layer: string | null;
  readonly valid_from_sequence: number | null;
  readonly valid_to_sequence: number | null;
  readonly lifecycle_state: string;
}

export interface CharacterRelationshipView {
  readonly id: string;
  readonly timeline_id: string | null;
  readonly source_character_id: string;
  readonly target_character_id: string;
  readonly source_character_instance_id: string | null;
  readonly target_character_instance_id: string | null;
  readonly directionality: string;
  readonly relation_kind: string;
  readonly label: string;
  readonly description: string;
  readonly status: string;
  readonly manual_override: boolean;
  readonly version: number;
}

export interface ChapterCharacterReference {
  readonly document_id: string;
  readonly document_title: string;
  readonly document_position: number;
  readonly reference_kinds: readonly ("required" | "point_of_view")[];
  readonly character_instance_id: string | null;
  readonly timeline_id: string | null;
}

export interface CharacterVoiceBindingView {
  readonly binding_id: string;
  readonly binding_policy: string;
  readonly profile_id: string | null;
  readonly voice_version_id: string | null;
  readonly language: string;
  readonly version: number;
}

interface ProjectedFactCore {
  readonly id: string;
  readonly fact_type: string;
  readonly timeline_id: string;
  readonly character_id: string | null;
  readonly character_instance_id: string | null;
  readonly relationship_id: string | null;
  readonly dimension: string;
  readonly event_kind: string;
  readonly predicate: string;
  readonly object_text: string;
  readonly details: Readonly<Record<string, JsonValue>>;
  readonly story_sequence: number | null;
  readonly source_revision_id: string | null;
}

export interface ProjectionConflictView {
  readonly conflict_key: string;
  readonly fact_ids: readonly string[];
  readonly reason: string;
}

export type CharacterFactEffectiveState = StoryLedgerFactEffectiveState;
export type CharacterFactHealth = StoryLedgerFactHealth;

export interface CharacterFactSourceV2 {
  readonly document_id: string;
  readonly document_title: string;
  readonly document_position: number;
  readonly revision_id: string;
  readonly revision_is_current: boolean;
  readonly source_content_hash: string;
  readonly source_coordinate: "unicode-codepoint-v1";
  readonly source_start: number | null;
  readonly source_end: number | null;
  readonly source_range_hash: string | null;
  readonly source_excerpt: string;
  readonly source_excerpt_truncated: boolean;
  readonly binding_state: string | null;
  readonly proposal_item_id: string | null;
  readonly commit_batch_id: string | null;
}

export interface ProjectedFactViewV2 extends ProjectedFactCore {
  readonly source_document_id: string | null;
  readonly story_time: Readonly<Record<string, JsonValue>> | null;
  readonly created_at: string | null;
  readonly effective_state: CharacterFactEffectiveState;
  readonly health: CharacterFactHealth;
  readonly source: CharacterFactSourceV2 | null;
}

export interface CharacterProjectedStateV2 {
  readonly timeline_id: string;
  readonly narrative_cutoff: number | null;
  readonly current_facts: readonly ProjectedFactViewV2[];
  readonly conflicts: readonly ProjectionConflictView[];
  readonly ambiguous_fact_ids: readonly string[];
}

export interface CharacterWritingStateAsOfV2 {
  readonly timeline_id: string;
  readonly narrative_cutoff: number | null;
  readonly story_time: Readonly<Record<string, JsonValue>> | null;
}

export interface CharacterWritingStateSlotValueV2 {
  readonly fact_id: string;
  readonly object_text: string;
  readonly story_sequence: number | null;
  readonly story_time: Readonly<Record<string, JsonValue>> | null;
  readonly source: CharacterFactSourceV2 | null;
}

export interface CharacterWritingStateSlotV2 {
  readonly key: string;
  readonly label: string;
  readonly mode: string;
  readonly values: readonly CharacterWritingStateSlotValueV2[];
  readonly health: "ok" | "conflicted" | "ambiguous" | "missing";
}

export interface CharacterHistorySummaryV2 {
  readonly total: number;
  readonly current: number;
  readonly historical: number;
  readonly superseded: number;
  readonly source_invalid: number;
  readonly batch_reverted: number;
}

export interface CharacterWritingStateV2 {
  readonly as_of: CharacterWritingStateAsOfV2;
  readonly slots: readonly CharacterWritingStateSlotV2[];
  readonly recent_changes: readonly ProjectedFactViewV2[];
  readonly risk_summary: {
    readonly conflict_count: number;
    readonly ambiguous_count: number;
    readonly invalid_source_count: number;
  };
  readonly history_summary: CharacterHistorySummaryV2;
}

export interface CharacterWorkspaceV2
{
  readonly schema_version: "character-workspace/2";
  readonly novel_id: string;
  readonly character_catalog_version: number;
  readonly story_ledger_version: number;
  readonly timeline_mode: "single" | "multiple";
  readonly character: CharacterRootView;
  readonly selected_timeline: TimelineView;
  readonly selected_instance: CharacterInstanceView;
  readonly timelines: readonly TimelineView[];
  readonly instances: readonly CharacterInstanceView[];
  readonly aliases: readonly CharacterAliasView[];
  readonly relationships: readonly CharacterRelationshipView[];
  readonly chapter_references: readonly ChapterCharacterReference[];
  readonly voice_binding: CharacterVoiceBindingView | null;
  readonly projected_state: CharacterProjectedStateV2;
  readonly writing_state: CharacterWritingStateV2;
}

export interface CharacterRootPatchV2 {
  readonly name: string;
  readonly role_type: string;
  readonly description: string;
  readonly gender: string;
  readonly core_theme: string;
}

export interface CharacterWorkspaceSaveCommandV2 {
  readonly schema_version: "character-workspace-save/2";
  readonly operation_key: string;
  readonly selected_timeline_id: string;
  readonly selected_instance_id: string;
  readonly expected_character_catalog_version: number;
  readonly expected_story_ledger_version: number;
  readonly expected_character_version: number;
  readonly expected_instance_version: number;
  readonly root_patch: CharacterRootPatchV2 | null;
  readonly profile: Readonly<Record<string, JsonValue>> | null;
}

export interface CharacterFactHistoryPageV2 {
  readonly schema_version: "character-fact-history/1";
  readonly items: readonly ProjectedFactViewV2[];
  readonly next_cursor: string | null;
  readonly total_summary: CharacterHistorySummaryV2;
}

export interface CharacterFactHistoryQueryV2 {
  readonly cursor?: string | null;
  readonly limit?: number;
  readonly effective_state?: CharacterFactEffectiveState | "all";
  readonly health?: CharacterFactHealth | "all";
  readonly dimension?: string | null;
  readonly source_document_id?: string | null;
}

export type StoryFactCorrectionCommandV1 = SharedStoryFactCorrectionCommandV1;
export type StoryFactCorrectionResultV1 = SharedStoryFactCorrectionResultV1;
export type CharacterBatchRevertImpact = StoryLedgerBatchImpactPreview;
export type IntelligenceBatchRevertCommandV1 = SharedIntelligenceBatchRevertCommandV1;

export interface CharacterWorkspaceSelection {
  readonly timelineId: string;
  readonly instanceId: string;
}

export interface CharacterWorkspaceFieldErrors {
  readonly [field: string]: string;
}

export interface CharacterWorkspaceActionError {
  readonly code: string;
  readonly message: string;
  readonly field_errors?: CharacterWorkspaceFieldErrors;
  readonly current_workspace?: CharacterWorkspaceV2;
}

export interface CharacterWorkspaceVoiceSlotProps {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly binding: CharacterVoiceBindingView | null;
}
