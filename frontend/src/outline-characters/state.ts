import {
  OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION,
  OutlineCharacterDraftContractError,
  type CharacterNameConflictResolution,
  type CharacterRegenerationConfirmationState,
  type CharacterRegenerationPlan,
  type CharacterRegenerationScope,
  type ExistingCharacterSummary,
  type NameConflictDecisionState,
  type OutlineCharacterDraftIssue,
  type OutlineCharacterDraftV2,
  type OutlineCharacterNameConflict,
} from "./contracts";


const FIELD_LIMITS = {
  draft_key: 120,
  character_id: 120,
  name: 240,
  age_at_story_start_note: 2_000,
  identity_summary: 2_000,
  personality_summary: 4_000,
  core_goal: 2_000,
  bio: 8_000,
} as const;


function cleanSingleLine(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}


/** Conservative UI collision key. The backend remains the final authority. */
export function characterNameKey(value: string): string {
  return cleanSingleLine(value.normalize("NFKC")).toLocaleLowerCase("zh-CN");
}


export function createManualCharacterDraft(draftKey: string): OutlineCharacterDraftV2 {
  return {
    schema_version: OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION,
    draft_key: cleanSingleLine(draftKey),
    character_id: null,
    role_type: "supporting",
    name: "",
    gender: "未知",
    age_at_story_start_note: "",
    identity_summary: "",
    personality_summary: "",
    core_goal: "",
    bio: "",
    origin: "manual",
  };
}


export function patchCharacterDraft(
  draft: OutlineCharacterDraftV2,
  patch: Partial<Omit<OutlineCharacterDraftV2, "schema_version" | "draft_key" | "origin">>,
): OutlineCharacterDraftV2 {
  return { ...draft, ...patch };
}


export function validateCharacterDrafts(
  drafts: readonly OutlineCharacterDraftV2[],
): readonly OutlineCharacterDraftIssue[] {
  const issues: OutlineCharacterDraftIssue[] = [];
  const keyCounts = new Map<string, number>();
  const nameCounts = new Map<string, number>();

  for (const draft of drafts) {
    const key = cleanSingleLine(draft.draft_key);
    keyCounts.set(key, (keyCounts.get(key) ?? 0) + 1);
    const nameKey = characterNameKey(draft.name);
    if (nameKey) nameCounts.set(nameKey, (nameCounts.get(nameKey) ?? 0) + 1);

    if (!key) issues.push(issue(draft, "draft_key", "required", "草案标识不能为空。"));
    if (key.length > FIELD_LIMITS.draft_key) {
      issues.push(issue(draft, "draft_key", "too_long", "草案标识不能超过 120 个字符。"));
    }
    if (draft.character_id !== null && !cleanSingleLine(draft.character_id)) {
      issues.push(issue(draft, "character_id", "invalid_value", "人物 ID 不能为空字符串。"));
    }
    if (draft.character_id !== null && draft.character_id.length > FIELD_LIMITS.character_id) {
      issues.push(issue(draft, "character_id", "too_long", "人物 ID 不能超过 120 个字符。"));
    }
    if (!cleanSingleLine(draft.name)) {
      issues.push(issue(draft, "name", "required", "人物姓名不能为空。"));
    }
    if (draft.name.length > FIELD_LIMITS.name) {
      issues.push(issue(draft, "name", "too_long", "人物姓名不能超过 240 个字符。"));
    }
    for (const [field, maximum] of Object.entries(FIELD_LIMITS)) {
      if (field === "draft_key" || field === "character_id" || field === "name") continue;
      const value = draft[field as keyof OutlineCharacterDraftV2];
      if (typeof value === "string" && value.length > maximum) {
        issues.push(issue(
          draft,
          field as keyof typeof FIELD_LIMITS,
          "too_long",
          `${field} 不能超过 ${maximum} 个字符。`,
        ));
      }
    }
  }

  for (const draft of drafts) {
    const key = cleanSingleLine(draft.draft_key);
    if (key && (keyCounts.get(key) ?? 0) > 1) {
      issues.push(issue(draft, "draft_key", "duplicate_draft_key", "草案标识不能重复。"));
    }
    const nameKey = characterNameKey(draft.name);
    if (nameKey && (nameCounts.get(nameKey) ?? 0) > 1) {
      issues.push(issue(draft, "characters", "duplicate_name", "草案中的人物姓名不能重复。"));
    }
  }
  return issues;
}


function issue(
  draft: OutlineCharacterDraftV2,
  field: OutlineCharacterDraftIssue["field"],
  code: OutlineCharacterDraftIssue["code"],
  message: string,
): OutlineCharacterDraftIssue {
  return { draft_key: draft.draft_key, field, code, message };
}


export function findCharacterNameConflicts(
  drafts: readonly OutlineCharacterDraftV2[],
  existingCharacters: readonly ExistingCharacterSummary[],
): readonly OutlineCharacterNameConflict[] {
  const existingByName = new Map<string, ExistingCharacterSummary[]>();
  for (const character of existingCharacters) {
    const key = characterNameKey(character.name);
    if (!key) continue;
    const rows = existingByName.get(key) ?? [];
    rows.push(character);
    existingByName.set(key, rows);
  }
  return drafts.flatMap((draft) => {
    if (draft.character_id !== null) return [];
    const candidates = existingByName.get(characterNameKey(draft.name)) ?? [];
    return candidates.length === 0 ? [] : [{
      code: "character_link_required" as const,
      draft_key: draft.draft_key,
      draft_name: draft.name,
      candidates,
    }];
  });
}


export function initialNameConflictDecision(
  conflict: OutlineCharacterNameConflict,
): NameConflictDecisionState {
  return {
    mode: "unresolved",
    existing_character_id: conflict.candidates[0]?.character_id ?? null,
    renamed_name: conflict.draft_name,
  };
}


export function resolutionFromDecision(
  conflict: OutlineCharacterNameConflict,
  decision: NameConflictDecisionState,
): CharacterNameConflictResolution | null {
  if (decision.mode === "unresolved") return null;
  if (decision.mode === "link_existing") {
    const candidate = conflict.candidates.find(
      (item) => item.character_id === decision.existing_character_id,
    );
    return candidate ? { kind: "link_existing", character_id: candidate.character_id } : null;
  }
  const renamed = cleanSingleLine(decision.renamed_name);
  if (!renamed) return null;
  const collides = conflict.candidates.some(
    (candidate) => characterNameKey(candidate.name) === characterNameKey(renamed),
  );
  return collides ? null : { kind: "create_new", renamed_name: renamed };
}


export function applyNameConflictResolution(
  draft: OutlineCharacterDraftV2,
  conflict: OutlineCharacterNameConflict,
  resolution: CharacterNameConflictResolution,
): OutlineCharacterDraftV2 {
  if (draft.draft_key !== conflict.draft_key) {
    throw new OutlineCharacterDraftContractError(
      "draft_not_found",
      "姓名冲突不属于当前人物草案。",
    );
  }
  if (resolution.kind === "link_existing") {
    const candidate = conflict.candidates.find(
      (item) => item.character_id === resolution.character_id,
    );
    if (!candidate) {
      throw new OutlineCharacterDraftContractError(
        "candidate_not_found",
        "所选已有人物不在本次冲突候选中。",
      );
    }
    return { ...draft, character_id: candidate.character_id, name: candidate.name };
  }

  const renamedName = cleanSingleLine(resolution.renamed_name);
  if (!renamedName || conflict.candidates.some(
    (candidate) => characterNameKey(candidate.name) === characterNameKey(renamedName),
  )) {
    throw new OutlineCharacterDraftContractError(
      "rename_required",
      "后端人物姓名唯一；新建人物前必须改为不冲突的姓名。",
    );
  }
  return { ...draft, character_id: null, name: renamedName };
}


export function openRegenerationConfirmation(
  drafts: readonly OutlineCharacterDraftV2[],
): CharacterRegenerationConfirmationState {
  return {
    scope: "ai_generated_only",
    selected_draft_keys: drafts
      .filter((draft) => draft.origin === "ai_candidate")
      .map((draft) => draft.draft_key),
    manual_replacement_acknowledged: false,
  };
}


/** Fresh generation has nothing to replace and therefore needs no confirmation step. */
export function createFreshCharacterGenerationPlan(): CharacterRegenerationPlan {
  return {
    scope: "all_drafts",
    replace_draft_keys: [],
    preserve_draft_keys: [],
  };
}


export function setRegenerationScope(
  state: CharacterRegenerationConfirmationState,
  scope: CharacterRegenerationScope,
  drafts: readonly OutlineCharacterDraftV2[],
): CharacterRegenerationConfirmationState {
  const selected = scope === "ai_generated_only"
    ? drafts.filter((draft) => draft.origin === "ai_candidate").map((draft) => draft.draft_key)
    : scope === "all_drafts"
      ? drafts.map((draft) => draft.draft_key)
      : state.selected_draft_keys.filter(
          (key) => drafts.some((draft) => draft.draft_key === key),
        );
  return {
    scope,
    selected_draft_keys: selected,
    manual_replacement_acknowledged: false,
  };
}


export function toggleRegenerationDraft(
  state: CharacterRegenerationConfirmationState,
  draftKey: string,
  selected: boolean,
): CharacterRegenerationConfirmationState {
  const keys = new Set(state.selected_draft_keys);
  if (selected) keys.add(draftKey);
  else keys.delete(draftKey);
  return {
    ...state,
    scope: "selected_drafts",
    selected_draft_keys: [...keys],
    manual_replacement_acknowledged: false,
  };
}


export function regenerationAffectedDrafts(
  state: CharacterRegenerationConfirmationState,
  drafts: readonly OutlineCharacterDraftV2[],
): readonly OutlineCharacterDraftV2[] {
  const keys = new Set(state.selected_draft_keys);
  return drafts.filter((draft) => keys.has(draft.draft_key));
}


export function canConfirmRegeneration(
  state: CharacterRegenerationConfirmationState,
  drafts: readonly OutlineCharacterDraftV2[],
): boolean {
  const affected = regenerationAffectedDrafts(state, drafts);
  return affected.length > 0 && (
    affected.every((draft) => draft.origin !== "manual")
    || state.manual_replacement_acknowledged
  );
}


export function buildRegenerationPlan(
  state: CharacterRegenerationConfirmationState,
  drafts: readonly OutlineCharacterDraftV2[],
): CharacterRegenerationPlan {
  if (!canConfirmRegeneration(state, drafts)) {
    throw new OutlineCharacterDraftContractError(
      "regeneration_confirmation_required",
      "请选择替换范围；包含手工草案时还需要单独确认。",
    );
  }
  const replaceKeys = new Set(state.selected_draft_keys);
  return {
    scope: state.scope,
    replace_draft_keys: drafts
      .filter((draft) => replaceKeys.has(draft.draft_key))
      .map((draft) => draft.draft_key),
    preserve_draft_keys: drafts
      .filter((draft) => !replaceKeys.has(draft.draft_key))
      .map((draft) => draft.draft_key),
  };
}
