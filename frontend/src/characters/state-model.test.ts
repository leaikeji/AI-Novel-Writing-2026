import { describe, expect, it } from "vitest";

import {
  characterFactCorrectionErrors,
  characterProfileGroupCompletion,
  createCharacterFactCorrectionDraft,
  filterCharacterFacts,
  mergeCharacterRootDetails,
  summarizeCharacterFactRisks,
  updateCharacterFactCorrectionDraft,
  validateCharacterProfile,
  type CharacterFactStateItem,
} from "./state-model";

function fact(
  id: string,
  effectiveState: CharacterFactStateItem["effective_state"],
  health: CharacterFactStateItem["health"] = "ok",
  dimension = "location",
  sourceDocumentId: string | null = "chapter-1",
): CharacterFactStateItem {
  return {
    id,
    dimension,
    effective_state: effectiveState,
    health,
    source_document_id: sourceDocumentId,
  };
}

describe("character state model", () => {
  it("keeps effective state and health as independent filters", () => {
    const facts = [
      fact("current-conflict", "current", "conflict"),
      fact("historical-ok", "historical"),
      fact("reverted-ambiguous", "batch_reverted", "ambiguous"),
    ];

    expect(filterCharacterFacts(facts, {
      effectiveState: "current",
      health: "conflict",
    }).map((item) => item.id)).toEqual(["current-conflict"]);
    expect(filterCharacterFacts(facts, {
      effectiveState: "batch_reverted",
      health: "ambiguous",
    }).map((item) => item.id)).toEqual(["reverted-ambiguous"]);
    expect(filterCharacterFacts(facts, {
      effectiveState: "historical",
      health: "all",
      dimension: "location",
      sourceDocumentId: "chapter-1",
    }).map((item) => item.id)).toEqual(["historical-ok"]);
  });

  it("counts only actionable risks in the tab badge and deduplicates a fact", () => {
    const summary = summarizeCharacterFactRisks([
      fact("conflict", "current", "conflict"),
      fact("ambiguous", "historical", "ambiguous"),
      fact("invalid-conflict", "source_invalid", "conflict"),
      fact("reverted", "batch_reverted"),
      fact("superseded", "superseded"),
    ]);

    expect(summary).toEqual({
      actionableCount: 3,
      conflictCount: 2,
      ambiguousCount: 1,
      invalidSourceCount: 1,
    });
  });

  it("preserves unknown root details while updating only editable details", () => {
    const current = {
      gender: "未设定",
      core_theme: "旧主题",
      future_server_field: { nested: ["必须保留"] },
    } as const;
    const merged = mergeCharacterRootDetails(current, {
      gender: "女",
      core_theme: "找回自己的名字",
    });

    expect(merged).toEqual({
      gender: "女",
      core_theme: "找回自己的名字",
      future_server_field: { nested: ["必须保留"] },
    });
    expect(merged).not.toBe(current);
  });

  it("preserves every legal unedited profile field without inventing defaults", () => {
    const candidate = {
      schema_version: "character-instance-profile/2",
      public_identity: "记者",
      true_identity: null,
      cover_identity: "旅店掌柜",
      birth_year: 1992,
      birth_calendar_id: "gregorian",
      birth_information: "生于港城",
      occupation: "调查记者",
      personality: "谨慎",
      goals: ["找出真相"],
      flaws: ["不愿求助"],
      secrets: ["曾隐瞒证据"],
      growth_direction: "学会信任",
      age_at_story_start_note: "开篇三十岁",
    } as const;

    const result = validateCharacterProfile(candidate, 2);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.profile).toEqual(candidate);
      expect(Object.keys(result.profile)).toEqual(Object.keys(candidate));
    }
  });

  it("rejects unknown profile extensions instead of silently retaining or dropping them", () => {
    const result = validateCharacterProfile({
      schema_version: "character-instance-profile/2",
      public_identity: "记者",
      custom_extension: "不在协议内",
    }, 2);

    expect(result).toEqual({
      ok: false,
      fieldErrors: { custom_extension: "当前人物档案协议不支持该字段" },
    });
  });

  it("rejects a V2-only field in V1 and validates list and age constraints", () => {
    const result = validateCharacterProfile({
      schema_version: "character-instance-profile/1",
      age_at_story_start_note: "三十岁",
      birth_year: 100_001,
      goals: ["同一目标", "同一目标"],
    }, 1);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.fieldErrors.age_at_story_start_note).toBeTruthy();
      expect(result.fieldErrors.birth_year).toBeTruthy();
      expect(result.fieldErrors.goals).toBeTruthy();
    }
  });

  it("rejects undefined draft values and whitespace-only V2 age notes", () => {
    const result = validateCharacterProfile({
      schema_version: "character-instance-profile/2",
      public_identity: undefined,
      age_at_story_start_note: "   ",
    }, 2);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.fieldErrors.public_identity).toBeTruthy();
      expect(result.fieldErrors.age_at_story_start_note).toBeTruthy();
    }
  });

  it("computes group completion without treating empty values as filled", () => {
    const profile = {
      occupation: "记者",
      personality: " ",
      goals: ["追查失踪案"],
      flaws: [],
      secrets: null,
      growth_direction: "接纳他人",
      birth_year: 1992,
      birth_calendar_id: "",
      birth_information: null,
      age_at_story_start_note: "开篇三十岁",
    };

    expect(characterProfileGroupCompletion(profile, 2, "writing")).toEqual({
      key: "writing",
      filled: 3,
      total: 6,
      complete: false,
    });
    expect(characterProfileGroupCompletion(profile, 1, "birth")).toEqual({
      key: "birth",
      filled: 1,
      total: 3,
      complete: false,
    });
    expect(characterProfileGroupCompletion(profile, 2, "birth")).toEqual({
      key: "birth",
      filled: 2,
      total: 4,
      complete: false,
    });
  });

  it("keeps correction scope immutable while editing replacement content", () => {
    const draft = createCharacterFactCorrectionDraft({
      id: "fact-1",
      fact_type: "character_state",
      timeline_id: "timeline-1",
      character_id: "character-1",
      character_instance_id: "instance-1",
      relationship_id: null,
      dimension: "location",
      event_kind: "changed",
      predicate: "位置变化",
      object_text: "码头",
      details: { value: "码头" },
    });
    const updated = updateCharacterFactCorrectionDraft(draft, {
      object_text: "灯塔",
      details: { value: "灯塔" },
      reason: "章节明确写明已离开码头",
    });

    expect(updated.target_fact_id).toBe("fact-1");
    expect(updated.timeline_id).toBe("timeline-1");
    expect(updated.character_instance_id).toBe("instance-1");
    expect(updated.object_text).toBe("灯塔");
    expect(characterFactCorrectionErrors(updated)).toEqual({});
    expect(characterFactCorrectionErrors({ ...updated, reason: "" })).toEqual({
      reason: "请说明修正理由",
    });
  });
});
