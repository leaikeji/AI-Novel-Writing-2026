export const LEXICON_SCHEMA_VERSION = "lexicon-pack/1" as const;
export const LIBRARY_CHANGE_SCHEMA_VERSION = "library-change/1" as const;
export const LIBRARY_CHECK_SCHEMA_VERSION = "library-check/1" as const;

export type PrivateLibraryCategory = "vocabulary" | "writing_style" | "plot" | "idea";
export type LibraryScope =
  | { kind: "library"; novelId?: never }
  | { kind: "novel"; novelId: string };
export type LexiconAction = "recommend" | "watch" | "forbid";
export type LexiconMatchMode = "phrase" | "ascii_word";
export type LexiconEntryState = "active" | "inactive";
export type LexiconPosition = "body" | "dialogue" | "title" | "synopsis" | "any";

export interface LexiconSourceRef {
  source_type: "author" | "selection" | "licensed_material" | "public_domain" | "research";
  label: string;
  locator?: string;
  observed_at?: string;
  evidence_scope?: string;
  verified_popularity: boolean;
}

export interface LexiconEntry {
  entry_id: string;
  term: string;
  action: LexiconAction;
  state: LexiconEntryState;
  match_mode: LexiconMatchMode;
  case_sensitive: boolean;
  variants: string[];
  categories: string[];
  genres: string[];
  eras: string[];
  positions: LexiconPosition[];
  note: string;
  example: string;
  counterexample: string;
  replacement_hint: string;
  watch_threshold?: { count: number; window_characters: number };
  source_refs: LexiconSourceRef[];
}

export interface LexiconPack {
  schema_version: typeof LEXICON_SCHEMA_VERSION;
  renderer_version: "lexicon-renderer/1";
  entries: LexiconEntry[];
}

export interface LibraryAssetSummary {
  id: string;
  asset_type: PrivateLibraryCategory;
  title: string;
  version: number;
  current_version_id: string;
  archived: boolean;
  scope_kind: "library" | "novel";
  scope_novel_id?: string;
  tags: string[];
  binding_count: number;
  binding_version?: number;
  updated_at: string;
  entry_count?: number;
  detail_loaded?: boolean;
}

export interface LibraryQueryFilters {
  readonly category: PrivateLibraryCategory;
  readonly query: string;
  readonly scope: "all" | "library" | "novel";
  readonly enabled: "all" | "enabled" | "disabled";
  readonly includeArchived?: boolean;
}

export interface LibraryAssetPage<T extends LibraryAssetSummary = LibraryAssetSummary> {
  items: T[];
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface LibraryChangeReceipt {
  schema_version: typeof LIBRARY_CHANGE_SCHEMA_VERSION;
  id: string;
  state: "proposed" | "applied" | "cancelled" | "conflict";
  scope: LibraryScope;
  idempotent_replay: boolean;
  undo_available: boolean;
  affected_assets: Array<{ asset_id: string; before_version?: string; after_version?: string }>;
}

export interface LibraryCheckHit {
  hit_id: string;
  entry_id: string;
  asset_id: string;
  asset_version_id: string;
  action: "watch" | "forbid";
  matched_text: string;
  start_utf16: number;
  end_utf16: number;
  reason: string;
  count: number;
  window?: number;
}

export interface LibraryCheckReport {
  schema_version: typeof LIBRARY_CHECK_SCHEMA_VERSION;
  id: string;
  status: "complete" | "incomplete" | "stale" | "failed";
  text_sha256: string;
  rules_sha256: string;
  scanned_rule_count: number;
  omitted_rule_count: number;
  visible_character_count: number;
  hits: LibraryCheckHit[];
  offset: number;
  limit: number;
  total_hits: number;
  has_more: boolean;
}
