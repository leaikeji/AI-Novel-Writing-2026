import type {
  StoryLedgerFactDetail,
  StoryLedgerFilters,
  StoryLedgerSourceExcerpt,
  StoryLedgerSummary,
  StoryLedgerTimelineContext,
} from "./contracts";
import type {
  StoryLedgerContextSelection,
  StoryLedgerWorkspaceContext,
} from "./workspace";

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

export interface StoryLedgerAssistantContextInput {
  readonly novel: { readonly id: string; readonly title: string };
  readonly snapshotToken: string;
  readonly timeline: StoryLedgerTimelineContext;
  readonly filters: StoryLedgerFilters;
  readonly summary: StoryLedgerSummary;
  readonly selectedDetail?: StoryLedgerFactDetail | null;
  readonly selectedSource?: StoryLedgerSourceExcerpt | null;
  readonly selectedContext?: StoryLedgerContextSelection | null;
  readonly selectedFactId?: string | null;
}

export interface StoryLedgerWorkspaceAssistantContextInput {
  readonly novel: { readonly id: string; readonly title: string };
  readonly context: StoryLedgerWorkspaceContext;
}

/**
 * Converts the workspace's deliberately body-free hand-off into the frozen
 * assistant envelope. Until summary/token/timeline agree, no ledger context is
 * published at all.
 */
export function buildStoryLedgerAssistantContextFromWorkspace(
  input: StoryLedgerWorkspaceAssistantContextInput,
): StoryLedgerAssistantContextV1 | null {
  const { context } = input;
  if (!context.snapshotToken || !context.timeline || !context.summary) return null;
  if (context.summary.ledger_snapshot_token !== context.snapshotToken) return null;
  if (context.summary.novel_id !== input.novel.id) return null;
  if (context.summary.timeline.timeline_id !== context.timeline.timeline_id
    || context.summary.timeline.narrative_cutoff !== context.timeline.narrative_cutoff) return null;
  if (context.selected && context.selected.factId !== context.selectedFactId) return null;
  return buildStoryLedgerAssistantContext({
    novel: input.novel,
    snapshotToken: context.snapshotToken,
    timeline: context.timeline,
    filters: context.filters,
    summary: context.summary,
    selectedFactId: context.selectedFactId,
    selectedContext: context.selected,
  });
}

export function buildStoryLedgerAssistantContext(
  input: StoryLedgerAssistantContextInput,
): StoryLedgerAssistantContextV1 {
  const truncated = { value: false };
  const selected = input.selectedDetail
    ? selectedFact(input.selectedDetail, input.selectedSource ?? null, truncated)
    : input.selectedContext
      ? selectedFactFromWorkspace(input.selectedContext, truncated)
      : null;
  const context: StoryLedgerAssistantContextV1 = {
    schema_version: STORY_LEDGER_ASSISTANT_CONTEXT_SCHEMA,
    novel: {
      id: boundedText(input.novel.id, 128, truncated),
      title: boundedText(input.novel.title, 240, truncated),
    },
    ledger_snapshot_token: boundedText(input.snapshotToken, 512, truncated),
    timeline: {
      id: nullableBoundedText(input.timeline.timeline_id, 128, truncated),
      name: nullableBoundedText(input.timeline.timeline_name, 160, truncated),
    },
    filters: normalizeAssistantFilters(input.filters, truncated),
    summary: {
      total: safeCount(input.summary.total),
      review_required: safeCount(input.summary.review_required),
      by_fact_type: boundedCountRecord(input.summary.by_fact_type, 16, truncated),
      by_effective_state: boundedCountRecord(input.summary.by_effective_state, 8, truncated),
      by_health: boundedCountRecord(input.summary.by_health, 8, truncated),
    },
    selected_fact_id: nullableBoundedText(
      input.selectedDetail?.item.id
        ?? input.selectedContext?.factId
        ?? input.selectedFactId
        ?? null,
      128,
      truncated,
    ),
    selected_fact: selected,
    budget: {
      max_code_points: STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS,
      used_code_points: 0,
      truncated: truncated.value,
    },
  };
  stabilizeBudget(context);
  if (context.budget.used_code_points > STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS) {
    shrinkSelectedObjectText(context);
  }
  if (context.budget.used_code_points > STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS) {
    throw new Error("story ledger assistant context exceeds its frozen budget");
  }
  if (!validateStoryLedgerAssistantContext(context)) {
    throw new Error("story ledger assistant context is invalid");
  }
  return context;
}

function selectedFactFromWorkspace(
  selected: StoryLedgerContextSelection,
  truncated: { value: boolean },
): StoryLedgerAssistantSelectedFact {
  return {
    id: boundedText(selected.factId, 128, truncated),
    fact_type: boundedText(selected.factType, 80, truncated),
    entity_labels: [],
    predicate: "",
    object_text: "",
    object_text_truncated: false,
    effective_state: boundedText(selected.effectiveState, 40, truncated),
    health: boundedText(selected.health, 40, truncated),
    effective_reason_codes: [],
    health_reason_codes: [],
    source: selected.source
      ? {
          document_id: nullableBoundedText(
            selected.source.source_document_id,
            128,
            truncated,
          ),
          document_title: nullableBoundedText(
            selected.source.document_title,
            240,
            truncated,
          ),
          revision_id: nullableBoundedText(
            selected.source.source_revision_id,
            128,
            truncated,
          ),
          revision_is_current: selected.source.revision_is_current,
          coordinate_version: null,
          source_start: null,
          source_end: null,
          range_hash: null,
        }
      : null,
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

function normalizeAssistantFilters(
  filters: StoryLedgerFilters,
  truncated: { value: boolean },
): StoryLedgerAssistantFilters {
  return {
    fact_types: boundedTexts(
      [...new Set(filters.factTypes ?? [])].filter(Boolean).sort(),
      8,
      80,
      truncated,
    ),
    effective_state: nullableBoundedText(filters.effectiveState ?? null, 40, truncated),
    health: nullableBoundedText(filters.health ?? null, 40, truncated),
    dimension: nullableBoundedText(filters.dimension ?? null, 80, truncated),
    source_document_id: nullableBoundedText(filters.sourceDocumentId ?? null, 128, truncated),
    commit_batch_id: nullableBoundedText(filters.commitBatchId ?? null, 128, truncated),
    fact_timeline_id: nullableBoundedText(filters.factTimelineId ?? null, 128, truncated),
    entity_type: nullableBoundedText(filters.entityType ?? null, 40, truncated),
    entity_id: nullableBoundedText(filters.entityId ?? null, 128, truncated),
    review_only: filters.reviewOnly === true,
  };
}

function selectedFact(
  detail: StoryLedgerFactDetail,
  source: StoryLedgerSourceExcerpt | null,
  truncated: { value: boolean },
): StoryLedgerAssistantSelectedFact {
  const objectText = boundedText(detail.object_text, 1_800, truncated);
  return {
    id: boundedText(detail.item.id, 128, truncated),
    fact_type: boundedText(detail.item.fact_type, 80, truncated),
    entity_labels: boundedTexts(
      detail.item.entities.map((entity) => entity.label),
      6,
      120,
      truncated,
    ),
    predicate: boundedText(detail.item.predicate, 240, truncated),
    object_text: objectText,
    object_text_truncated: codePointLength(objectText) < codePointLength(detail.object_text),
    effective_state: boundedText(detail.item.effective_state, 40, truncated),
    health: boundedText(detail.item.health, 40, truncated),
    effective_reason_codes: boundedTexts(
      detail.item.effective_reason_codes,
      8,
      64,
      truncated,
    ),
    health_reason_codes: boundedTexts(
      detail.item.health_reason_codes,
      8,
      64,
      truncated,
    ),
    source: sourceMetadata(detail, source, truncated),
  };
}

function sourceMetadata(
  detail: StoryLedgerFactDetail,
  source: StoryLedgerSourceExcerpt | null,
  truncated: { value: boolean },
): StoryLedgerAssistantSelectedSource | null {
  const reference = detail.item.source;
  if (!reference && !source) return null;
  const start = source?.source_start ?? reference?.source_start ?? null;
  const end = source?.source_end ?? reference?.source_end ?? null;
  return {
    document_id: nullableBoundedText(
      source?.document_id ?? reference?.source_document_id ?? null,
      128,
      truncated,
    ),
    document_title: nullableBoundedText(
      source?.document_title ?? reference?.document_title ?? null,
      240,
      truncated,
    ),
    revision_id: nullableBoundedText(
      source?.revision_id ?? reference?.source_revision_id ?? null,
      128,
      truncated,
    ),
    revision_is_current: source?.revision_is_current ?? reference?.revision_is_current ?? null,
    coordinate_version: start !== null && end !== null ? "unicode-codepoint-v1" : null,
    source_start: safeNullableOffset(start),
    source_end: safeNullableOffset(end),
    range_hash: nullableBoundedText(source?.source_range_hash ?? null, 64, truncated),
  };
}

function shrinkSelectedObjectText(context: StoryLedgerAssistantContextV1): void {
  const selected = context.selected_fact;
  if (!selected) return;
  const original = selected.object_text;
  let low = 0;
  let high = codePointLength(original);
  let best = "";
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const candidate = truncateCodePoints(original, middle);
    (selected as { object_text: string; object_text_truncated: boolean }).object_text = candidate;
    (selected as { object_text: string; object_text_truncated: boolean }).object_text_truncated = true;
    context.budget.truncated = true;
    stabilizeBudget(context);
    if (context.budget.used_code_points <= STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS) {
      best = candidate;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  (selected as { object_text: string }).object_text = best;
  stabilizeBudget(context);
}

function stabilizeBudget(context: StoryLedgerAssistantContextV1): void {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const used = codePointLength(JSON.stringify(context));
    if (context.budget.used_code_points === used) return;
    context.budget.used_code_points = used;
  }
  context.budget.used_code_points = codePointLength(JSON.stringify(context));
}

function boundedCountRecord(
  record: Readonly<Record<string, number>>,
  maximumEntries: number,
  truncated: { value: boolean },
): Readonly<Record<string, number>> {
  const entries = Object.entries(record).sort(([left], [right]) => left.localeCompare(right));
  if (entries.length > maximumEntries) truncated.value = true;
  return Object.fromEntries(entries.slice(0, maximumEntries).map(([key, count]) => [
    boundedText(key, 80, truncated),
    safeCount(count),
  ]));
}

function boundedTexts(
  values: readonly string[],
  maximumItems: number,
  maximumCodePoints: number,
  truncated: { value: boolean },
): readonly string[] {
  if (values.length > maximumItems) truncated.value = true;
  return values.slice(0, maximumItems).map(
    (value) => boundedText(value, maximumCodePoints, truncated),
  );
}

function boundedText(
  value: string,
  maximumCodePoints: number,
  truncated: { value: boolean },
): string {
  const result = truncateCodePoints(String(value), maximumCodePoints);
  if (result !== value) truncated.value = true;
  return result;
}

function nullableBoundedText(
  value: string | null,
  maximumCodePoints: number,
  truncated: { value: boolean },
): string | null {
  return value === null ? null : boundedText(value, maximumCodePoints, truncated);
}

function truncateCodePoints(value: string, maximum: number): string {
  const points = [...value];
  if (points.length <= maximum) return value;
  if (maximum <= 0) return "";
  if (maximum === 1) return "…";
  return `${points.slice(0, maximum - 1).join("")}…`;
}

function codePointLength(value: string): number {
  return [...value].length;
}

function safeCount(value: number): number {
  return safeCountValue(value) ? value : 0;
}

function safeCountValue(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function safeNullableOffset(value: number | null): number | null {
  return value === null || !safeCountValue(value) ? null : value;
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
