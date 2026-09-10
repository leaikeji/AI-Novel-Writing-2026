export const STORY_LEDGER_ASSISTANT_CONTEXT_SCHEMA =
  "story-ledger-assistant-context/1" as const;
export const STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS = 6_000;

export interface StoryLedgerAssistantFilters {
  readonly fact_types: readonly string[];
  readonly effective_state: string | null;
  readonly health: string | null;
  readonly dimension: string | null;
  readonly source_document_id: string | null;
  readonly commit_batch_id: string | null;
  readonly fact_timeline_id: string | null;
  readonly entity_type: string | null;
  readonly entity_id: string | null;
  readonly review_only: boolean;
}

export interface StoryLedgerAssistantSummary {
  readonly total: number;
  readonly review_required: number;
  readonly by_fact_type: Readonly<Record<string, number>>;
  readonly by_effective_state: Readonly<Record<string, number>>;
  readonly by_health: Readonly<Record<string, number>>;
}

export interface StoryLedgerAssistantSelectedSource {
  readonly document_id: string | null;
  readonly document_title: string | null;
  readonly revision_id: string | null;
  readonly revision_is_current: boolean | null;
  readonly coordinate_version: "unicode-codepoint-v1" | null;
  readonly source_start: number | null;
  readonly source_end: number | null;
  readonly range_hash: string | null;
}

export interface StoryLedgerAssistantSelectedFact {
  readonly id: string;
  readonly fact_type: string;
  readonly entity_labels: readonly string[];
  readonly predicate: string;
  readonly object_text: string;
  readonly object_text_truncated: boolean;
  readonly effective_state: string;
  readonly health: string;
  readonly effective_reason_codes: readonly string[];
  readonly health_reason_codes: readonly string[];
  readonly source: StoryLedgerAssistantSelectedSource | null;
}

export interface StoryLedgerAssistantContextV1 {
  readonly schema_version: typeof STORY_LEDGER_ASSISTANT_CONTEXT_SCHEMA;
  readonly novel: { readonly id: string; readonly title: string };
  readonly ledger_snapshot_token: string;
  readonly timeline: {
    readonly id: string | null;
    readonly name: string | null;
  };
  readonly filters: StoryLedgerAssistantFilters;
  readonly summary: StoryLedgerAssistantSummary;
  readonly selected_fact_id: string | null;
  readonly selected_fact: StoryLedgerAssistantSelectedFact | null;
  readonly budget: {
    readonly max_code_points: typeof STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS;
    used_code_points: number;
    truncated: boolean;
  };
}

export function validateStoryLedgerAssistantContext(
  value: unknown,
): value is StoryLedgerAssistantContextV1 {
  if (!isRecord(value) || !exactKeys(value, [
    "schema_version", "novel", "ledger_snapshot_token", "timeline",
    "filters", "summary", "selected_fact_id", "selected_fact", "budget",
  ])) return false;
  if (value.schema_version !== STORY_LEDGER_ASSISTANT_CONTEXT_SCHEMA) return false;
  if (!isRecord(value.novel) || !exactKeys(value.novel, ["id", "title"])
    || !nonEmpty(value.novel.id) || typeof value.novel.title !== "string") return false;
  if (!nonEmpty(value.ledger_snapshot_token)) return false;
  if (!validTimeline(value.timeline) || !validFilters(value.filters)
    || !validSummary(value.summary) || !validSelectedFact(value.selected_fact)) return false;
  if (value.selected_fact_id !== null && !nonEmpty(value.selected_fact_id)) return false;
  if (value.selected_fact !== null
    && isRecord(value.selected_fact)
    && value.selected_fact.id !== value.selected_fact_id) return false;
  if (!isRecord(value.budget)
    || !exactKeys(value.budget, ["max_code_points", "used_code_points", "truncated"])
    || value.budget.max_code_points !== STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS
    || !safeCountValue(value.budget.used_code_points)
    || typeof value.budget.truncated !== "boolean") return false;
  const used = codePointLength(JSON.stringify(value));
  return used <= STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS
    && value.budget.used_code_points === used;
}

function codePointLength(value: string): number {
  return [...value].length;
}

function safeCountValue(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === [...expected].sort()[index]);
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function validTimeline(value: unknown): boolean {
  return isRecord(value) && exactKeys(value, ["id", "name"])
    && nullableString(value.id) && nullableString(value.name);
}

function validFilters(value: unknown): boolean {
  if (!isRecord(value) || !exactKeys(value, [
    "fact_types", "effective_state", "health", "dimension",
    "source_document_id", "commit_batch_id", "fact_timeline_id",
    "entity_type", "entity_id", "review_only",
  ])) return false;
  return Array.isArray(value.fact_types)
    && value.fact_types.every((item) => typeof item === "string")
    && nullableString(value.effective_state)
    && nullableString(value.health)
    && nullableString(value.dimension)
    && nullableString(value.source_document_id)
    && nullableString(value.commit_batch_id)
    && nullableString(value.fact_timeline_id)
    && nullableString(value.entity_type)
    && nullableString(value.entity_id)
    && typeof value.review_only === "boolean";
}

function validCountRecord(value: unknown): boolean {
  return isRecord(value) && Object.entries(value).every(
    ([key, count]) => Boolean(key) && safeCountValue(count),
  );
}

function validSummary(value: unknown): boolean {
  return isRecord(value) && exactKeys(value, [
    "total", "review_required", "by_fact_type", "by_effective_state", "by_health",
  ]) && safeCountValue(value.total) && safeCountValue(value.review_required)
    && validCountRecord(value.by_fact_type)
    && validCountRecord(value.by_effective_state)
    && validCountRecord(value.by_health);
}

function validSelectedFact(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value) || !exactKeys(value, [
    "id", "fact_type", "entity_labels", "predicate", "object_text",
    "object_text_truncated", "effective_state", "health",
    "effective_reason_codes", "health_reason_codes", "source",
  ])) return false;
  return nonEmpty(value.id)
    && nonEmpty(value.fact_type)
    && Array.isArray(value.entity_labels)
    && value.entity_labels.every((item) => typeof item === "string")
    && typeof value.predicate === "string"
    && typeof value.object_text === "string"
    && typeof value.object_text_truncated === "boolean"
    && nonEmpty(value.effective_state)
    && nonEmpty(value.health)
    && Array.isArray(value.effective_reason_codes)
    && value.effective_reason_codes.every((item) => typeof item === "string")
    && Array.isArray(value.health_reason_codes)
    && value.health_reason_codes.every((item) => typeof item === "string")
    && validSource(value.source);
}

function validSource(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value) || !exactKeys(value, [
    "document_id", "document_title", "revision_id", "revision_is_current",
    "coordinate_version", "source_start", "source_end", "range_hash",
  ])) return false;
  return nullableString(value.document_id)
    && nullableString(value.document_title)
    && nullableString(value.revision_id)
    && (value.revision_is_current === null || typeof value.revision_is_current === "boolean")
    && (value.coordinate_version === null || value.coordinate_version === "unicode-codepoint-v1")
    && (value.source_start === null || safeCountValue(value.source_start))
    && (value.source_end === null || safeCountValue(value.source_end))
    && nullableString(value.range_hash);
}
