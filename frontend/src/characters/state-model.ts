import type { JsonValue } from "./contracts";
import type {
  StoryLedgerFactCorrectionDraft,
  StoryLedgerFactCorrectionTarget,
  StoryLedgerFactFilters,
  StoryLedgerFactStateItem,
  StoryLedgerRiskSummary,
} from "../story-ledger/state-model";
import type {
  StoryLedgerFactEffectiveState,
  StoryLedgerFactHealth,
} from "../story-ledger/contracts";

export {
  FACT_EFFECTIVE_STATE_LABELS,
  FACT_HEALTH_LABELS,
  createStoryLedgerFactCorrectionDraft as createCharacterFactCorrectionDraft,
  filterStoryLedgerFacts as filterCharacterFacts,
  matchesStoryLedgerFactFilters as matchesCharacterFactFilters,
  storyLedgerFactCorrectionErrors as characterFactCorrectionErrors,
  summarizeStoryLedgerRisks as summarizeCharacterFactRisks,
  updateStoryLedgerFactCorrectionDraft as updateCharacterFactCorrectionDraft,
} from "../story-ledger/state-model";
export {
  STORY_LEDGER_EFFECTIVE_STATES as FACT_EFFECTIVE_STATES,
  STORY_LEDGER_HEALTH_STATES as FACT_HEALTH_STATES,
} from "../story-ledger/contracts";

export type FactEffectiveState = StoryLedgerFactEffectiveState;
export type FactEffectiveStateFilter = "all" | FactEffectiveState;
export type FactHealth = StoryLedgerFactHealth;
export type FactHealthFilter = "all" | FactHealth;
export type CharacterFactStateItem = StoryLedgerFactStateItem;
export type CharacterFactFilters = StoryLedgerFactFilters;
export type CharacterFactRiskSummary = StoryLedgerRiskSummary;

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

export type CharacterFactCorrectionTarget = StoryLedgerFactCorrectionTarget;
export type CharacterFactCorrectionDraft = StoryLedgerFactCorrectionDraft;

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
