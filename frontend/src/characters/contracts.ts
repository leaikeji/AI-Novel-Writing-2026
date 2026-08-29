export type JsonPrimitive = string | number | boolean | null;

export type JsonValue =
  | JsonPrimitive
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };

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

export interface ProjectedFactView {
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

export interface CharacterProjectedState {
  readonly timeline_id: string;
  readonly narrative_cutoff: number | null;
  readonly current_facts: readonly ProjectedFactView[];
  readonly conflicts: readonly ProjectionConflictView[];
  readonly ambiguous_fact_ids: readonly string[];
}

/**
 * Frozen UI boundary for the formal character workspace. Keep the field names in
 * sync with backend/character_workspace/contracts.py; the shared frontend DTO is
 * intentionally not imported so this feature can be integrated independently.
 */
export interface CharacterWorkspaceV1 {
  readonly schema_version: string;
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
  readonly projected_state: CharacterProjectedState;
}

export interface CharacterRootPatchV1 {
  readonly name: string;
  readonly role_type: string;
  readonly description: string;
  readonly gender: string;
  readonly core_theme: string;
}

export interface CharacterWorkspaceSaveCommandV1 {
  readonly schema_version: "character-workspace-save/1";
  readonly novel_id: string;
  readonly character_id: string;
  readonly selected_timeline_id: string;
  readonly selected_instance_id: string;
  readonly expected_character_catalog_version: number;
  readonly expected_story_ledger_version: number;
  readonly expected_character_version: number;
  readonly expected_instance_version: number;
  readonly root: CharacterRootPatchV1 | null;
  readonly profile: Readonly<Record<string, JsonValue>> | null;
}

export interface CharacterWorkspaceSelectionV1 {
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
  readonly current_workspace?: CharacterWorkspaceV1;
}

export interface CharacterWorkspaceVoiceSlotProps {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly binding: CharacterVoiceBindingView | null;
}
