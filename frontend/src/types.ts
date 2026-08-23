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
