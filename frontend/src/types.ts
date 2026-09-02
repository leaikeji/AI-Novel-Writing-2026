export interface RevisionSummary {
  id: string;
  document_id: string;
  revision_number: number;
  parent_revision_id: string | null;
  restored_from_revision_id: string | null;
  content_hash: string;
  source: string;
  visible_character_count: number;
  created_at: string | null;
}

export type DocumentVersionState =
  | "empty_draft"
  | "saved_working_copy"
  | "checkpointed";

export interface DocumentRecord {
  id: string;
  novel_id: string;
  volume_id: string | null;
  kind: "chapter" | "outline" | "setting";
  title: string;
  position: number;
  version: number;
  draft_version: number;
  base_revision_id: string | null;
  content_markdown: string;
  content_hash: string;
  visible_character_count: number;
  version_state?: DocumentVersionState;
  updated_at: string | null;
  revisions: RevisionSummary[];
  revision_next_cursor?: string | null;
}

export interface NovelSearchResultRecord {
  document_id: string;
  title: string;
  kind: "chapter" | "outline" | "setting";
  base_revision_id: string | null;
  snippet: string;
}

export interface VolumeRecord {
  id: string | null;
  title: string;
  position: number;
  version: number;
  documents: DocumentRecord[];
}

export type NovelCoverMode = "ai" | "system" | "upload" | "text";

export interface NovelSummary {
  id: string;
  title: string;
  author_name: string;
  description: string;
  writing_type: string;
  audience: string;
  genre: string;
  subgenre: string;
  cover_mode: NovelCoverMode;
  cover_image_data: string;
  cover_asset_id: string | null;
  version: number;
  chapter_count: number;
  visible_character_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface NovelRecord {
  id: string;
  title: string;
  author_name: string;
  description: string;
  writing_type: string;
  audience: string;
  genre: string;
  subgenre: string;
  idea: string;
  template_key: string | null;
  template_name: string;
  template_data: Record<string, unknown>;
  cover_mode: NovelCoverMode;
  cover_image_data: string;
  cover_asset_id: string | null;
  outline_target_chapters: number;
  highlight: string;
  background: string;
  main_plot: string;
  story_ledger_version: number;
  version: number;
  created_at: string | null;
  updated_at: string | null;
  tree: VolumeRecord[];
}

export type NovelMetadataRecord = Omit<NovelRecord, "tree"> & {
  visible_character_count: number;
};

export interface WorkspaceManifestItem {
  kind: "volume" | "document";
  id: string;
  parent_volume_id: string | null;
  document_type: DocumentRecord["kind"] | null;
  title: string;
  position: number;
  status: string | null;
  version: number;
  draft_version: number | null;
  base_revision_id: string | null;
  content_hash: string | null;
  visible_character_count: number | null;
  updated_at: string | null;
}

export interface WorkspaceManifestPage {
  schema_version: "novel-workspace-manifest/1";
  novel: {
    id: string;
    title: string;
    description: string;
    story_ledger_version: number;
    visible_character_count: number;
    updated_at: string | null;
  };
  items: WorkspaceManifestItem[];
  next_cursor: string | null;
  manifest_etag: string;
}

export type PrivateAssetType = "plot" | "writing_style" | "vocabulary" | "idea";

export interface NovelCreationDraftRecord {
  id: string;
  draft_key: string;
  step: number;
  state: "draft" | "completed";
  version: number;
  data: Record<string, any>;
  completed_novel_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PrivateAssetRecord {
  id: string;
  asset_type: PrivateAssetType;
  title: string;
  content: string;
  version: number;
  archived: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface AssetPresetRecord {
  id: string;
  title: string;
  description: string;
  version: number;
  archived: boolean;
  assets: PrivateAssetRecord[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CreativeGenerationRecord {
  id: string;
  scope_type: string;
  scope_id: string;
  novel_id: string | null;
  document_id: string | null;
  kind: string;
  state: "running" | "ready" | "failed";
  input_hash: string;
  input_snapshot?: Record<string, unknown>;
  execution_agent_id: string | null;
  requested_provider_id: string | null;
  requested_model_id: string;
  generation_contract_version: string | null;
  actual_provider_id: string | null;
  actual_model_id: string | null;
  model_evidence?: Record<string, unknown> | null;
  provider_profile: string | null;
  output_json: Record<string, any>;
  output_text: string;
  target_character_count: number | null;
  output_visible_character_count: number;
  attempt: number;
  failure_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface RoleConstraints {
  required: string[];
  allowed: string[];
  context_only: string[];
  forbidden: string[];
}

export interface ChapterBriefRecord {
  id: string | null;
  document_id: string;
  version: number;
  target_word_count: number;
  expectation_text: string;
  outline_text: string;
  forbidden_text: string;
  role_constraints: RoleConstraints;
  created_at: string | null;
  updated_at: string | null;
}

export interface ChapterCreationDraftRecord {
  id: string;
  draft_key: string;
  novel_id: string;
  volume_id: string | null;
  step: number;
  state: "draft" | "completed";
  version: number;
  title: string;
  target_character_count: number;
  expectation_text: string;
  outline_text: string;
  data: Record<string, any>;
  completed_document_id: string | null;
  recovery?: {
    kind: "volume_rebound";
    from_volume_id: string | null;
    to_volume_id: string;
  };
  created_at: string | null;
  updated_at: string | null;
}

export interface ChapterCreationCompleteRecord {
  draft: ChapterCreationDraftRecord;
  document: DocumentRecord;
}

export interface CandidateRecord {
  id: string;
  document_id: string;
  generation_job_id: string;
  base_revision_id: string | null;
  base_draft_version: number;
  base_content_hash: string;
  base_content_markdown: string;
  content_markdown: string;
  content_text: string;
  content_hash: string;
  state: "ready" | "accepted" | "rejected";
  adopted_revision_id: string | null;
  visible_character_count: number;
  unified_diff: string;
  created_at: string | null;
  decided_at: string | null;
}

export interface GenerationJobRecord {
  id: string;
  document_id: string;
  kind: "body";
  input_hash: string;
  state: "running" | "ready" | "failed";
  brief_version: number;
  base_revision_id: string | null;
  base_draft_version: number;
  base_content_hash: string;
  execution_agent_id: string | null;
  requested_provider_id: string | null;
  model_profile_fingerprint: string | null;
  asset_snapshot: Array<{
    id: string;
    asset_type: PrivateAssetType;
    title: string;
    version: number;
  }>;
  requested_model_id: string;
  generation_contract_version: string | null;
  actual_provider_id: string | null;
  actual_model_id: string | null;
  model_evidence?: Record<string, unknown> | null;
  provider_profile: string | null;
  target_visible_character_count: number;
  minimum_visible_character_count?: number;
  maximum_visible_character_count?: number;
  requested_visible_character_count?: number;
  output_visible_character_count: number;
  validation_state: string;
  attempt: number;
  failure_message: string | null;
  candidate: CandidateRecord | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface IntelligenceItemRecord {
  id: string;
  proposal_id: string;
  position: number;
  item_type: string;
  suggested_payload: {
    subject: string;
    predicate: string;
    object: string;
    entity_key?: string | null;
    entity?: {
      relationship_id?: string | null;
      source_character_key?: string | null;
      target_character_key?: string | null;
      source_label?: string;
      target_label?: string;
      directionality?: "directed" | "undirected";
      relation_kind?: string;
      label?: string;
      manual_override?: boolean;
      is_new?: boolean;
    };
  };
  confidence: number;
  source_text: string;
  reasoning_summary: string;
  review_state: "pending" | "accepted" | "rejected";
  committed_story_fact_id: string | null;
  created_at: string | null;
}

export interface IntelligenceProposalRecord {
  id: string;
  novel_id: string;
  document_id: string;
  chapter_revision_id: string;
  input_hash: string;
  state:
    | "running"
    | "ready"
    | "partially_accepted"
    | "accepted"
    | "rejected"
    | "superseded"
    | "failed";
  source_current: boolean;
  execution_agent_id: string | null;
  requested_provider_id: string | null;
  requested_model_id: string;
  generation_contract_version: string | null;
  actual_provider_id: string | null;
  actual_model_id: string | null;
  model_evidence?: Record<string, unknown> | null;
  provider_profile: string | null;
  model_profile_fingerprint: string | null;
  attempt: number;
  failure_message: string | null;
  items: IntelligenceItemRecord[];
  created_at: string | null;
  reviewed_at: string | null;
  relationship_sync?: {
    created: number;
    updated: number;
    skipped: number;
  };
  rejected_invalid_item_ids?: string[];
}

export interface GenerationModelStatus {
  agent_id: "ai-novel-writer";
  provider_id: string;
  model_id: string;
  effective_max_input_length: number | null;
  policy: "follow-agent-effective";
}

export interface RestorePreviewFactRecord {
  id: string;
  fact_type: string;
  subject: string;
  predicate: string;
  object_text: string;
  status: string;
}

export interface RestorePreviewRecord {
  document_id: string;
  expected_draft_version: number;
  fact_plan_hash: string;
  current_revision: RevisionSummary | null;
  target_revision: RevisionSummary;
  working_copy_dirty: boolean;
  unified_diff: string;
  will_deactivate: RestorePreviewFactRecord[];
  will_reactivate: RestorePreviewFactRecord[];
  will_remain_current: RestorePreviewFactRecord[];
  available_commit_batches: Array<{
    id: string;
    proposal_id: string;
    chapter_revision_id: string;
    state: string;
    accepted_item_ids: string[];
  }>;
}

export interface OutlineCharacterDraft {
  schema_version?: "outline-character-draft/2";
  draft_key?: string;
  character_id?: string | null;
  name: string;
  role_type: "main" | "supporting";
  gender?: string;
  age_at_story_start_note?: string;
  identity_summary?: string;
  personality_summary?: string;
  core_goal?: string;
  bio?: string;
  origin?: "manual" | "ai_candidate";
  /** Read-only compatibility projection for older installed bundles. */
  description: string;
  details: Record<string, unknown>;
}

export interface OutlineDraftRecord {
  id: string;
  novel_id: string;
  step: number;
  state: "draft" | "completed";
  version: number;
  target_chapter_count: number;
  background_text: string;
  characters: OutlineCharacterDraft[];
  plot_text: string;
  highlight_text: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface NovelCharacterRecord {
  id: string;
  novel_id: string;
  role_type: "main" | "supporting";
  name: string;
  description: string;
  details: Record<string, unknown>;
  lifecycle_state: "active" | "archived";
  archived_at: string | null;
  required_next_chapter: boolean;
  position: number;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export type RelationshipDirectionality = "directed" | "undirected" | "legacy_unspecified";

export type RelationshipKind =
  | "family"
  | "colleague"
  | "mentor"
  | "ally"
  | "enemy"
  | "romance"
  | "other";

export interface StoryProjectionSummary {
  timeline_id: string;
  narrative_cutoff: number | null;
  event_count: number;
  fact_ids: string[];
  current_fact_ids: string[];
  latest_event: {
    fact_id: string;
    story_sequence: number | null;
    event_kind: string;
    predicate: string;
    text: string;
    details: Record<string, unknown>;
  } | null;
  conflicted: boolean;
  conflicts: Array<{ conflict_key: string; fact_ids: string[]; reason: string }>;
}

export interface CharacterRelationshipRecord {
  id: string;
  novel_id: string;
  source_character_id: string;
  target_character_id: string;
  directionality: RelationshipDirectionality;
  relation_kind: RelationshipKind;
  label: string;
  description: string;
  status: "active" | "resolved" | "archived";
  definition_status?: "active" | "resolved" | "archived";
  latest_state?: string;
  projection?: StoryProjectionSummary | null;
  created_by: "manual" | "ai_accepted" | "ai_auto" | "import";
  manual_override: boolean;
  confidence: number | null;
  evidence: string[];
  source_generation_job_id: string | null;
  relation_pair_key: string;
  source_chapter_revision_id: string | null;
  proposal_item_id: string | null;
  current_revision_id: string | null;
  archived_at: string | null;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface RelationshipAutoSyncStatusRecord {
  eligible: boolean;
  stale: boolean;
  state: "never" | "running" | "ready" | "failed";
  input_hash: string;
  last_synced_at: string | null;
  ai_relationship_count: number;
  manual_relationship_count: number;
  source_summary: {
    characters: number;
    relationship_facts: number;
    chapters: number;
    excluded_chapters: number;
  };
  job: CreativeGenerationRecord | null;
}

export interface RelationshipAutoSyncResponseRecord {
  job: CreativeGenerationRecord;
  status: RelationshipAutoSyncStatusRecord;
  changes: {
    created: number;
    updated: number;
    archived: number;
    skipped: number;
  };
  relationships: CharacterRelationshipRecord[];
}

export interface RelationshipGraphPositionRecord {
  character_id: string;
  x: number;
  y: number;
  pinned: boolean;
}

export interface RelationshipGraphViewRecord {
  id: string | null;
  novel_id: string;
  name: string;
  layout_algorithm: string;
  random_seed: string;
  zoom: number;
  pan_x: number;
  pan_y: number;
  version: number;
  positions: RelationshipGraphPositionRecord[];
  updated_at: string | null;
}

export type StorylineType = "main" | "support" | "romance" | "faction";

export interface StorylineRecord {
  id: string;
  novel_id: string;
  storyline_type: StorylineType;
  title: string;
  description: string;
  status: "active" | "paused" | "completed" | "archived";
  progress: number;
  planning_status?: "active" | "paused" | "completed" | "archived";
  planning_progress?: number;
  latest_progress?: string;
  projection?: StoryProjectionSummary | null;
  position: number;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ForeshadowRecord {
  id: string;
  novel_id: string;
  title: string;
  content: string;
  latest_progress: string;
  status: "planned" | "active" | "resolved" | "dropped";
  progress: number;
  planning_latest_progress?: string;
  planning_status?: "planned" | "active" | "resolved" | "dropped";
  planning_progress?: number;
  projection?: StoryProjectionSummary | null;
  position: number;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface NovelExportRecord {
  id: string;
  novel_id: string;
  export_format: "markdown" | "text";
  state: "ready";
  content_hash: string;
  content: string;
  metadata: {
    novel_title: string;
    volume_count: number;
    ungrouped_chapter_count: number;
    chapter_count: number;
    visible_character_count: number;
  };
  created_at: string | null;
  completed_at: string | null;
}
