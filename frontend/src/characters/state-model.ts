import type { JsonValue } from "./contracts";

export const FACT_EFFECTIVE_STATES = [
  "current",
  "historical",
  "superseded",
  "source_invalid",
  "batch_reverted",
] as const;

export type FactEffectiveState = (typeof FACT_EFFECTIVE_STATES)[number];
export type FactEffectiveStateFilter = "all" | FactEffectiveState;

export const FACT_HEALTH_STATES = ["ok", "conflict", "ambiguous"] as const;
export type FactHealth = (typeof FACT_HEALTH_STATES)[number];
export type FactHealthFilter = "all" | FactHealth;

export interface CharacterFactStateItem {
  readonly id: string;
  readonly dimension: string;
  readonly effective_state: FactEffectiveState;
  readonly health: FactHealth;
  readonly source_document_id: string | null;
}

export interface CharacterFactFilters {
  readonly effectiveState: FactEffectiveStateFilter;
  readonly health: FactHealthFilter;
  readonly dimension?: string | null;
  readonly sourceDocumentId?: string | null;
}

export interface CharacterFactRiskSummary {
  readonly actionableCount: number;
  readonly conflictCount: number;
  readonly ambiguousCount: number;
  readonly invalidSourceCount: number;
}

export const FACT_EFFECTIVE_STATE_LABELS: Readonly<Record<FactEffectiveState, string>> = {
  current: "当前值",
  historical: "历史变化",
  superseded: "已被替代",
  source_invalid: "来源失效",
  batch_reverted: "已撤销同步",
};

export const FACT_HEALTH_LABELS: Readonly<Record<FactHealth, string>> = {
  ok: "正常",
  conflict: "冲突",
  ambiguous: "不确定",
};

export function matchesCharacterFactFilters(
  fact: CharacterFactStateItem,
  filters: CharacterFactFilters,
): boolean {
  return (
    (filters.effectiveState === "all" || fact.effective_state === filters.effectiveState)
    && (filters.health === "all" || fact.health === filters.health)
    && (!filters.dimension || fact.dimension === filters.dimension)
    && (!filters.sourceDocumentId || fact.source_document_id === filters.sourceDocumentId)
  );
}

export function filterCharacterFacts<T extends CharacterFactStateItem>(
  facts: readonly T[],
  filters: CharacterFactFilters,
): readonly T[] {
  return facts.filter((fact) => matchesCharacterFactFilters(fact, filters));
}

/**
 * A tab badge counts facts that need author attention, not history volume. One
 * fact is counted once even when, for example, it is both conflicted and has an
 * invalid source. Superseded and reverted facts remain auditable but are not
 * author to-dos.
 */
export function summarizeCharacterFactRisks(
  facts: readonly CharacterFactStateItem[],
): CharacterFactRiskSummary {
  const actionableIds = new Set<string>();
  const conflictIds = new Set<string>();
  const ambiguousIds = new Set<string>();
  const invalidSourceIds = new Set<string>();

  for (const fact of facts) {
    if (fact.health === "conflict") conflictIds.add(fact.id);
    if (fact.health === "ambiguous") ambiguousIds.add(fact.id);
    if (fact.effective_state === "source_invalid") invalidSourceIds.add(fact.id);
    if (
      fact.health === "conflict"
      || fact.health === "ambiguous"
      || fact.effective_state === "source_invalid"
    ) {
      actionableIds.add(fact.id);
    }
  }

  return {
    actionableCount: actionableIds.size,
    conflictCount: conflictIds.size,
    ambiguousCount: ambiguousIds.size,
    invalidSourceCount: invalidSourceIds.size,
  };
}

export interface CharacterRootEditableDetails {
  readonly gender: JsonValue;
  readonly core_theme: JsonValue;
}

/** Preserve server-owned and future root details while replacing only UI-owned fields. */
export function mergeCharacterRootDetails(
  current: Readonly<Record<string, JsonValue>>,
  editable: CharacterRootEditableDetails,
): Readonly<Record<string, JsonValue>> {
  return {
    ...current,
    gender: cloneJsonValue(editable.gender),
    core_theme: cloneJsonValue(editable.core_theme),
  };
}

export const CHARACTER_PROFILE_V1_FIELDS = [
  "schema_version",
  "public_identity",
  "true_identity",
  "cover_identity",
  "birth_year",
  "birth_calendar_id",
  "birth_information",
  "occupation",
  "personality",
  "goals",
  "flaws",
  "secrets",
  "growth_direction",
] as const;

export const CHARACTER_PROFILE_V2_FIELDS = [
  ...CHARACTER_PROFILE_V1_FIELDS,
  "age_at_story_start_note",
] as const;

export type CharacterProfileSchemaVersion = 1 | 2;

export interface CharacterProfileValidationSuccess {
  readonly ok: true;
  readonly profile: Readonly<Record<string, JsonValue>>;
}

export interface CharacterProfileValidationFailure {
  readonly ok: false;
  readonly fieldErrors: Readonly<Record<string, string>>;
}

export type CharacterProfileValidationResult =
  | CharacterProfileValidationSuccess
  | CharacterProfileValidationFailure;

const NULLABLE_TEXT_LIMITS: Readonly<Record<string, number>> = {
  public_identity: 2_000,
  true_identity: 2_000,
  cover_identity: 2_000,
  birth_calendar_id: 80,
  birth_information: 2_000,
  occupation: 2_000,
  personality: 4_000,
  growth_direction: 4_000,
  age_at_story_start_note: 2_000,
};

const LIST_FIELDS = new Set(["goals", "flaws", "secrets"]);

/**
 * Validate the complete versioned profile before save. Unknown keys are errors;
 * they are never silently copied or stripped into a supposedly valid payload.
 */
export function validateCharacterProfile(
  candidate: Readonly<Record<string, unknown>>,
  schemaVersion: CharacterProfileSchemaVersion,
): CharacterProfileValidationResult {
  const allowed = new Set<string>(
    schemaVersion === 1 ? CHARACTER_PROFILE_V1_FIELDS : CHARACTER_PROFILE_V2_FIELDS,
  );
  const fieldErrors: Record<string, string> = {};
  const expectedSchema = `character-instance-profile/${schemaVersion}`;

  for (const key of Object.keys(candidate)) {
    if (!allowed.has(key)) fieldErrors[key] = "当前人物档案协议不支持该字段";
  }
  if (candidate.schema_version !== expectedSchema) {
    fieldErrors.schema_version = `必须为 ${expectedSchema}`;
  }

  for (const [field, limit] of Object.entries(NULLABLE_TEXT_LIMITS)) {
    if (!allowed.has(field) || !hasOwn(candidate, field)) continue;
    const value = candidate[field];
    if (value !== null && typeof value !== "string") {
      fieldErrors[field] = "必须为文本或 null";
    } else if (typeof value === "string" && value.length > limit) {
      fieldErrors[field] = `不能超过 ${limit} 个字符`;
    } else if (field === "age_at_story_start_note" && value?.trim() === "") {
      fieldErrors[field] = "如填写开篇年龄说明则不能为空";
    }
  }

  if (hasOwn(candidate, "birth_year")) {
    const value = candidate.birth_year;
    if (
      value !== null
      && (!Number.isInteger(value) || (value as number) < -100_000 || (value as number) > 100_000)
    ) {
      fieldErrors.birth_year = "必须为 -100000 至 100000 的整数或 null";
    }
  }

  for (const field of LIST_FIELDS) {
    if (!hasOwn(candidate, field)) continue;
    const value = candidate[field];
    if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
      fieldErrors[field] = "必须为文本列表";
      continue;
    }
    const cleaned = value.map((item) => (item as string).trim()).filter(Boolean);
    if (cleaned.length !== value.length) {
      fieldErrors[field] = "列表不能包含空项";
    } else if (new Set(cleaned).size !== cleaned.length) {
      fieldErrors[field] = "列表不能包含重复项";
    }
  }

  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors };

  const profile: Record<string, JsonValue> = {};
  for (const key of Object.keys(candidate)) {
    profile[key] = cloneJsonValue(candidate[key] as JsonValue);
  }
  return { ok: true, profile };
}

export type CharacterProfileGroupKey = "writing" | "identity" | "birth";

export interface CharacterProfileGroupCompletion {
  readonly key: CharacterProfileGroupKey;
  readonly filled: number;
  readonly total: number;
  readonly complete: boolean;
}

const PROFILE_GROUP_FIELDS: Readonly<Record<CharacterProfileGroupKey, readonly string[]>> = {
  writing: ["occupation", "personality", "goals", "flaws", "secrets", "growth_direction"],
  identity: ["public_identity", "true_identity", "cover_identity"],
  birth: ["birth_year", "birth_calendar_id", "birth_information", "age_at_story_start_note"],
};

export function characterProfileGroupCompletion(
  profile: Readonly<Record<string, unknown>>,
  schemaVersion: CharacterProfileSchemaVersion,
  key: CharacterProfileGroupKey,
): CharacterProfileGroupCompletion {
  const fields = PROFILE_GROUP_FIELDS[key].filter(
    (field) => schemaVersion === 2 || field !== "age_at_story_start_note",
  );
  const filled = fields.filter((field) => isFilledProfileValue(profile[field])).length;
  return { key, filled, total: fields.length, complete: filled === fields.length };
}

export interface CharacterFactCorrectionTarget {
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
}

export interface CharacterFactCorrectionDraft extends CharacterFactCorrectionTarget {
  readonly target_fact_id: string;
  readonly reason: string;
}

export function createCharacterFactCorrectionDraft(
  target: CharacterFactCorrectionTarget,
): CharacterFactCorrectionDraft {
  return {
    ...target,
    details: cloneJsonValue(target.details) as Readonly<Record<string, JsonValue>>,
    target_fact_id: target.id,
    reason: "",
  };
}

export function updateCharacterFactCorrectionDraft(
  draft: CharacterFactCorrectionDraft,
  patch: Readonly<{
    object_text?: string;
    details?: Readonly<Record<string, JsonValue>>;
    reason?: string;
  }>,
): CharacterFactCorrectionDraft {
  return {
    ...draft,
    ...(patch.object_text === undefined ? {} : { object_text: patch.object_text }),
    ...(patch.details === undefined
      ? {}
      : { details: cloneJsonValue(patch.details) as Readonly<Record<string, JsonValue>> }),
    ...(patch.reason === undefined ? {} : { reason: patch.reason }),
  };
}

export function characterFactCorrectionErrors(
  draft: CharacterFactCorrectionDraft,
): Readonly<Record<string, string>> {
  const errors: Record<string, string> = {};
  if (!draft.object_text.trim()) errors.object_text = "请填写替代事实";
  if (!draft.reason.trim()) errors.reason = "请说明修正理由";
  if (draft.reason.length > 1_000) errors.reason = "修正理由不能超过 1000 个字符";
  return errors;
}

function isFilledProfileValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.some((item) => typeof item !== "string" || item.trim());
  return true;
}

function hasOwn(value: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function cloneJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) {
    return value.map((item) => cloneJsonValue(item));
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, cloneJsonValue(item)]),
    );
  }
  return value;
}
