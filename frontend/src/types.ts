export interface RevisionSummary {
  id: string;
  document_id: string;
  revision_number: number;
  parent_revision_id: string | null;
  content_hash: string;
  source: string;
  visible_character_count: number;
  created_at: string | null;
}

export interface DocumentRecord {
  id: string;
  novel_id: string;
  volume_id: string | null;
  kind: "chapter" | "outline" | "setting";
  title: string;
  position: number;
  draft_version: number;
  base_revision_id: string | null;
  content_markdown: string;
  content_hash: string;
  visible_character_count: number;
  updated_at: string | null;
  revisions: RevisionSummary[];
}

export interface VolumeRecord {
  id: string | null;
  title: string;
  position: number;
  version: number;
  documents: DocumentRecord[];
}

export interface NovelSummary {
  id: string;
  title: string;
  description: string;
  version: number;
  chapter_count: number;
  visible_character_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface NovelRecord {
  id: string;
  title: string;
  description: string;
  version: number;
  created_at: string | null;
  updated_at: string | null;
  tree: VolumeRecord[];
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
  model_profile_fingerprint: string;
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
  model_profile_fingerprint: string;
  failure_message: string | null;
  items: IntelligenceItemRecord[];
  created_at: string | null;
  reviewed_at: string | null;
}

export interface StoryFactRecord {
  id: string;
  novel_id: string;
  fact_type: string;
  subject: string;
  predicate: string;
  object_text: string;
  details: Record<string, unknown>;
  source_revision_id: string | null;
  status: string;
  created_at: string | null;
}
