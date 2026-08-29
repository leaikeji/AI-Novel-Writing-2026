import type {
  CharacterWorkspaceActionError,
  CharacterWorkspaceSaveCommandV1,
  CharacterWorkspaceV1,
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

export function isMultiTimeline(workspace: CharacterWorkspaceV1): boolean {
  return workspace.timeline_mode === "multiple";
}

export function rootDraftFromWorkspace(workspace: CharacterWorkspaceV1): CharacterRootDraft {
  return {
    name: workspace.character.name,
    role_type: workspace.character.role_type,
    description: workspace.character.description,
    gender: valueAsText(workspace.character.details.gender),
    core_theme: valueAsText(workspace.character.details.core_theme),
  };
}

export function profileDraftFromWorkspace(workspace: CharacterWorkspaceV1): CharacterProfileDraft {
  return { ...workspace.selected_instance.profile };
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

export function hasRootChanges(workspace: CharacterWorkspaceV1, draft: CharacterRootDraft): boolean {
  return !jsonEqual(rootDraftFromWorkspace(workspace), draft);
}

export function hasProfileChanges(
  workspace: CharacterWorkspaceV1,
  draft: CharacterProfileDraft,
): boolean {
  return !jsonEqual(profileDraftFromWorkspace(workspace), draft);
}

export function buildSaveCommand(
  workspace: CharacterWorkspaceV1,
  root: CharacterRootDraft,
  profile: CharacterProfileDraft,
): CharacterWorkspaceSaveCommandV1 {
  return {
    schema_version: "character-workspace-save/1",
    novel_id: workspace.novel_id,
    character_id: workspace.character.id,
    selected_timeline_id: workspace.selected_timeline.id,
    selected_instance_id: workspace.selected_instance.id,
    expected_character_catalog_version: workspace.character_catalog_version,
    expected_story_ledger_version: workspace.story_ledger_version,
    expected_character_version: workspace.character.version,
    expected_instance_version: workspace.selected_instance.version,
    root: hasRootChanges(workspace, root) ? root : null,
    profile: hasProfileChanges(workspace, profile) ? profile : null,
  };
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
    const source = reason as Record<string, unknown>;
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
