import type {
  CharacterWorkspaceActionError,
  CharacterWorkspaceSaveCommandV2,
  CharacterWorkspaceV2,
  JsonValue,
} from "./contracts";

export const CHARACTER_WORKSPACE_TABS = ["basic", "line-profile", "growth", "voice"] as const;
export type CharacterWorkspaceTab = (typeof CHARACTER_WORKSPACE_TABS)[number];

export const PROFILE_FIELD_KEYS = [
  "public_identity",
  "true_identity",
  "cover_identity",
  "birth_year",
  "birth_calendar_id",
  "birth_information",
  "age_at_story_start_note",
  "occupation",
  "personality",
  "goals",
  "flaws",
  "secrets",
  "growth_direction",
] as const;

export type ProfileFieldKey = (typeof PROFILE_FIELD_KEYS)[number];

export interface CharacterRootDraft {
  readonly name: string;
  readonly role_type: string;
  readonly description: string;
  readonly gender: string;
  readonly core_theme: string;
}

export type CharacterProfileDraft = Record<string, JsonValue>;

export function isMultiTimeline(workspace: CharacterWorkspaceV2): boolean {
  return workspace.timeline_mode === "multiple";
}

export function characterRoleLabel(roleType: string): string {
  return ({
    main: "主角",
    supporting: "配角",
  }[roleType] ?? roleType) || "未设置角色定位";
}

export function characterFactDimensionLabel(dimension: string): string {
  return ({
    action: "行动",
    presence: "出场",
    knowledge: "认知",
    knowledge_event: "认知变化",
    character_state: "人物状态",
    relationship_state: "关系状态",
    storyline_event: "故事线进展",
    foreshadow_event: "伏笔进展",
    story_time: "故事时间",
    world_state: "世界状态",
    general_fact: "其他事实",
    location: "位置",
    health: "健康",
    emotion: "情绪",
    attitude: "态度",
    relationship: "关系",
    goal: "目标",
    possession: "持有物",
    identity: "身份",
  }[dimension] ?? dimension) || "未分类状态";
}

export function rootDraftFromWorkspace(workspace: CharacterWorkspaceV2): CharacterRootDraft {
  return {
    name: workspace.character.name,
    role_type: workspace.character.role_type,
    description: workspace.character.description,
    gender: valueAsText(workspace.character.details.gender),
    core_theme: valueAsText(workspace.character.details.core_theme),
  };
}

export function profileDraftFromWorkspace(workspace: CharacterWorkspaceV2): CharacterProfileDraft {
  const schemaVersion = workspace.selected_instance.profile_schema_version === 1 ? 1 : 2;
  return {
    schema_version: `character-instance-profile/${schemaVersion}`,
    ...workspace.selected_instance.profile,
  };
}

export function valueAsText(value: JsonValue | undefined): string {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.map((item) => String(item)).join("\n");
  if (typeof value === "object") return "";
  return String(value);
}

export function textAsLines(value: string): readonly string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function updateProfileText(
  draft: CharacterProfileDraft,
  key: ProfileFieldKey,
  value: string,
  multilineList = false,
): CharacterProfileDraft {
  let normalized: JsonValue = multilineList ? textAsLines(value) : value;
  if (key === "birth_year") {
    normalized = value.trim() === "" ? null : /^-?\d+$/.test(value.trim()) ? Number(value.trim()) : value;
  }
  return { ...draft, [key]: normalized };
}

function jsonEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function hasRootChanges(workspace: CharacterWorkspaceV2, draft: CharacterRootDraft): boolean {
  return !jsonEqual(rootDraftFromWorkspace(workspace), draft);
}

export function hasProfileChanges(
  workspace: CharacterWorkspaceV2,
  draft: CharacterProfileDraft,
): boolean {
  return !jsonEqual(profileDraftFromWorkspace(workspace), draft);
}

export function buildSaveCommand(
  workspace: CharacterWorkspaceV2,
  root: CharacterRootDraft,
  profile: CharacterProfileDraft,
  operationKey = createCharacterWorkspaceOperationKey(),
): CharacterWorkspaceSaveCommandV2 {
  return {
    schema_version: "character-workspace-save/2",
    operation_key: operationKey,
    selected_timeline_id: workspace.selected_timeline.id,
    selected_instance_id: workspace.selected_instance.id,
    expected_character_catalog_version: workspace.character_catalog_version,
    expected_story_ledger_version: workspace.story_ledger_version,
    expected_character_version: workspace.character.version,
    expected_instance_version: workspace.selected_instance.version,
    root_patch: hasRootChanges(workspace, root) ? root : null,
    profile: hasProfileChanges(workspace, profile) ? profile : null,
  };
}

export function createCharacterWorkspaceOperationKey(): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `character-workspace:${random}`;
}

export function characterWorkspaceTabFromKey(
  current: CharacterWorkspaceTab,
  key: string,
): CharacterWorkspaceTab | null {
  const index = CHARACTER_WORKSPACE_TABS.indexOf(current);
  if (key === "Home") return CHARACTER_WORKSPACE_TABS[0];
  if (key === "End") return CHARACTER_WORKSPACE_TABS[CHARACTER_WORKSPACE_TABS.length - 1];
  if (key === "ArrowRight" || key === "ArrowDown") {
    return CHARACTER_WORKSPACE_TABS[(index + 1) % CHARACTER_WORKSPACE_TABS.length];
  }
  if (key === "ArrowLeft" || key === "ArrowUp") {
    return CHARACTER_WORKSPACE_TABS[(index - 1 + CHARACTER_WORKSPACE_TABS.length) % CHARACTER_WORKSPACE_TABS.length];
  }
  return null;
}

export function tabForField(field: string): CharacterWorkspaceTab {
  const normalized = field.toLowerCase();
  if (normalized.startsWith("profile.") || PROFILE_FIELD_KEYS.some((key) => normalized.endsWith(key))) {
    return "line-profile";
  }
  return "basic";
}

export function normalizeActionError(reason: unknown): CharacterWorkspaceActionError {
  if (typeof reason === "object" && reason !== null) {
    const outer = reason as Record<string, unknown>;
    const source = typeof outer.detail === "object" && outer.detail !== null
      ? outer.detail as Record<string, unknown>
      : outer;
    const message = typeof source.message === "string" ? source.message : "保存失败，请稍后重试。";
    const code = typeof source.code === "string" ? source.code : "character_workspace_failed";
    const rawFields = source.field_errors;
    const fieldErrors: Record<string, string> = {};
    if (typeof rawFields === "object" && rawFields !== null) {
      for (const [key, value] of Object.entries(rawFields)) {
        if (typeof value === "string") fieldErrors[key] = value;
      }
    }
    return {
      code,
      message,
      ...(Object.keys(fieldErrors).length > 0 ? { field_errors: fieldErrors } : {}),
      ...(typeof source.current_workspace === "object" && source.current_workspace !== null
        ? { current_workspace: source.current_workspace as CharacterWorkspaceV2 }
        : {}),
    };
  }
  return { code: "character_workspace_failed", message: "保存失败，请稍后重试。" };
}

export function fieldError(
  error: CharacterWorkspaceActionError | null,
  field: string,
): string | undefined {
  if (!error?.field_errors) return undefined;
  const parts = field.split(".");
  const nested = Object.entries(error.field_errors).find(([key]) => key.startsWith(`${field}.`));
  return error.field_errors[field] ?? error.field_errors[parts[parts.length - 1] ?? field] ?? nested?.[1];
}

export function continuityLabel(kind: string): string {
  const labels: Record<string, string> = {
    default: "本线人物",
    derived: "分支人物",
    traveler: "跨线来客",
    parallel: "平行人物",
  };
  return labels[kind] ?? "人物版本";
}
