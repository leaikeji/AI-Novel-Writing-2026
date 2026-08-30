import { describe, expect, it } from "vitest";

import {
  OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION,
  OutlineCharacterDraftContractError,
  type ExistingCharacterSummary,
  type OutlineCharacterDraftV2,
} from "./contracts";
import {
  applyNameConflictResolution,
  buildRegenerationPlan,
  canConfirmRegeneration,
  createFreshCharacterGenerationPlan,
  createManualCharacterDraft,
  findCharacterNameConflicts,
  openRegenerationConfirmation,
  resolutionFromDecision,
  setRegenerationScope,
  validateCharacterDrafts,
} from "./state";


function draft(
  draftKey: string,
  origin: OutlineCharacterDraftV2["origin"] = "ai_candidate",
  name = draftKey,
): OutlineCharacterDraftV2 {
  return {
    schema_version: OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION,
    draft_key: draftKey,
    character_id: null,
    role_type: "supporting",
    name,
    gender: "未知",
    age_at_story_start_note: "约二十岁",
    identity_summary: "城中医师",
    personality_summary: "谨慎，却会在危机时先救陌生人",
    core_goal: "查清旧案",
    bio: "在边城长大。",
    origin,
  };
}


const EXISTING: ExistingCharacterSummary = {
  character_id: "character-001",
  name: "林遥",
  role_type: "main",
};


describe("OutlineCharacterDraftV2 state", () => {
  it("creates a complete manual draft without inventing formal identity", () => {
    expect(createManualCharacterDraft("manual:1")).toEqual({
      schema_version: "outline-character-draft/2",
      draft_key: "manual:1",
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
    });
  });

  it("never links by name and requires an explicit conflict resolution", () => {
    const source = draft("ai:1", "ai_candidate", " 林遥 ");
    const conflicts = findCharacterNameConflicts([source], [EXISTING]);

    expect(source.character_id).toBeNull();
    expect(conflicts).toEqual([expect.objectContaining({
      code: "character_link_required",
      draft_key: "ai:1",
      candidates: [EXISTING],
    })]);

    expect(resolutionFromDecision(conflicts[0], {
      mode: "link_existing",
      existing_character_id: EXISTING.character_id,
      renamed_name: "林遥",
    })).toEqual({ kind: "link_existing", character_id: EXISTING.character_id });
    expect(applyNameConflictResolution(source, conflicts[0], {
      kind: "link_existing",
      character_id: EXISTING.character_id,
    })).toEqual(expect.objectContaining({
      character_id: EXISTING.character_id,
      name: EXISTING.name,
    }));
  });

  it("requires a different name before create_new under backend uniqueness", () => {
    const source = draft("ai:1", "ai_candidate", "林遥");
    const conflict = findCharacterNameConflicts([source], [EXISTING])[0];

    expect(resolutionFromDecision(conflict, {
      mode: "create_new",
      existing_character_id: null,
      renamed_name: " 林遥 ",
    })).toBeNull();
    expect(() => applyNameConflictResolution(source, conflict, {
      kind: "create_new",
      renamed_name: "林遥",
    })).toThrowError(OutlineCharacterDraftContractError);
    expect(applyNameConflictResolution(source, conflict, {
      kind: "create_new",
      renamed_name: "林遥（旧线）",
    })).toEqual(expect.objectContaining({
      character_id: null,
      name: "林遥（旧线）",
    }));
  });

  it("rejects duplicate draft identity while allowing distinct same-name people", () => {
    const issues = validateCharacterDrafts([
      draft("same", "manual", "阿澄"),
      draft("same", "ai_candidate", " 阿澄 "),
    ]);
    expect(issues.filter((issue) => issue.code === "duplicate_draft_key")).toHaveLength(2);
    expect(issues.filter((issue) => issue.code === "duplicate_name")).toHaveLength(0);
  });

  it("defaults regeneration to AI drafts and protects manual drafts with a second acknowledgement", () => {
    const drafts = [draft("ai:1"), draft("manual:1", "manual")];
    const initial = openRegenerationConfirmation(drafts);

    expect(initial).toEqual({
      scope: "ai_generated_only",
      selected_draft_keys: ["ai:1"],
      manual_replacement_acknowledged: false,
    });
    expect(buildRegenerationPlan(initial, drafts)).toEqual({
      scope: "ai_generated_only",
      replace_draft_keys: ["ai:1"],
      preserve_draft_keys: ["manual:1"],
    });

    const all = setRegenerationScope(initial, "all_drafts", drafts);
    expect(canConfirmRegeneration(all, drafts)).toBe(false);
    expect(() => buildRegenerationPlan(all, drafts)).toThrowError(
      /包含手工草案时还需要单独确认/,
    );
    expect(buildRegenerationPlan({
      ...all,
      manual_replacement_acknowledged: true,
    }, drafts)).toEqual({
      scope: "all_drafts",
      replace_draft_keys: ["ai:1", "manual:1"],
      preserve_draft_keys: [],
    });
  });

  it("starts a fresh novel generation without adding a replacement confirmation step", () => {
    expect(createFreshCharacterGenerationPlan()).toEqual({
      scope: "all_drafts",
      replace_draft_keys: [],
      preserve_draft_keys: [],
    });
  });
});
