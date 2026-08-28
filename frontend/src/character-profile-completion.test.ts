import { describe, expect, it } from "vitest";

import {
  characterProfileCompletionCandidateViews,
  characterProfileCompletionPresentation,
  characterProfileCompletionSelectionSummary,
  createCharacterProfileCompletionSelectionState,
  reduceCharacterProfileCompletionSelection,
  type CharacterProfileCompletionCandidate,
  type CharacterProfileCompletionStatusRecord,
} from "./character-profile-completion";


function candidate(
  override: Partial<CharacterProfileCompletionCandidate> = {},
): CharacterProfileCompletionCandidate {
  return {
    character_id: "character-1",
    character_name: "江述",
    base_version: 2,
    current_personality: null,
    status: "candidate",
    personality: "重事实、强控制，在压力下会把求真变成对他人的逼迫。",
    basis: "mixed",
    confidence: 86,
    evidence: [
      { source_type: "character", source_id: "character-1", quote: "认死理，凡事要有证据。" },
      { source_type: "chapter", source_id: "chapter-1", quote: "江述反复核对卷宗页码。" },
    ],
    warnings: ["当前仅有一章正文，行为结论仍需后续验证"],
    ...override,
  };
}


function status(
  override: Partial<CharacterProfileCompletionStatusRecord> = {},
): CharacterProfileCompletionStatusRecord {
  return {
    eligible: true,
    state: "never",
    stale: false,
    source_summary: {
      characters: 6,
      characters_without_personality: 6,
      chapters: 1,
      story_facts: 2,
    },
    job: null,
    candidates: [],
    ...override,
  };
}


const idle = { phase: "idle" as const, error: "", confirming: false };


describe("characterProfileCompletionPresentation", () => {
  it("covers never, running, ready, and stale without claiming automatic writes", () => {
    const never = characterProfileCompletionPresentation(status(), idle);
    const running = characterProfileCompletionPresentation(status({
      state: "running",
      job: { id: "job-1", actual_model: "Qwen3.7-Plus" },
    }), idle);
    const ready = characterProfileCompletionPresentation(status({
      state: "ready",
      candidates: [candidate()],
    }), idle);
    const stale = characterProfileCompletionPresentation(status({
      state: "stale",
      stale: true,
      candidates: [candidate()],
    }), idle);

    expect(never.title).toContain("尚未分析");
    expect(never.description).toContain("只生成候选，不会自动写入");
    expect(running.title).toBe("角色性格正在分析");
    expect(running.actionDisabled).toBe(true);
    expect(running.description).toContain("Qwen3.7-Plus");
    expect(ready.action).toBe("apply");
    expect(ready.actionDisabled).toBe(true);
    expect(ready.description).toContain("默认未选择任何候选");
    expect(stale.action).toBe("reanalyze");
    expect(stale.description).toContain("旧候选仅供查看");
  });

  it("enables the apply action only after candidates are explicitly selected", () => {
    const selectedReady = characterProfileCompletionPresentation(status({
      state: "ready",
      candidates: [candidate()],
    }), { ...idle, selectedCount: 1 });

    expect(selectedReady.action).toBe("apply");
    expect(selectedReady.actionLabel).toBe("应用所选候选（1）");
    expect(selectedReady.actionDisabled).toBe(false);
  });

  it("covers failed, conflict, and applied with safe recovery actions", () => {
    const failed = characterProfileCompletionPresentation(status({
      state: "failed",
      last_error: "模型没有返回最终 JSON",
    }), idle);
    const conflict = characterProfileCompletionPresentation(status({ state: "conflict" }), idle);
    const applied = characterProfileCompletionPresentation(status({
      state: "applied",
      can_restore: true,
      last_applied_at: "2026-08-26T12:00:00Z",
    }), idle);

    expect(failed.actionLabel).toBe("重新分析");
    expect(failed.action).toBe("reanalyze");
    expect(failed.description).toContain("正式角色资料未改变");
    expect(conflict.action).toBe("reload-status");
    expect(conflict.description).toContain("未写入任何角色");
    expect(applied.action).toBe("restore");
    expect(applied.description).toContain("其他扩展字段均未改变");
  });

  it("uses reload-status after a read error and disables unavailable generation", () => {
    const error = characterProfileCompletionPresentation(status(), {
      ...idle,
      error: "网络暂时不可用",
    });
    const ineligible = characterProfileCompletionPresentation(status({ eligible: false }), idle);

    expect(error.action).toBe("reload-status");
    expect(error.description).toContain("现有角色资料均已保留");
    expect(ineligible.actionDisabled).toBe(true);
    expect(ineligible.actionLabel).toBe("暂不可分析");
  });
});


describe("character profile completion selection", () => {
  it("loads candidates with zero selections and disables apply", () => {
    const loaded = reduceCharacterProfileCompletionSelection(
      createCharacterProfileCompletionSelectionState(),
      { type: "load-candidates", jobId: "job-1", candidates: [candidate()] },
    );

    expect(loaded.selectedCharacterIds).toEqual({});
    expect(loaded.replacementConfirmedCharacterIds).toEqual({});
    expect(characterProfileCompletionSelectionSummary(loaded)).toMatchObject({
      selectedCount: 0,
      candidateCount: 1,
      insufficientEvidenceCount: 0,
      applyDisabled: true,
      decisions: [],
    });
  });

  it("requires explicit replacement confirmation before selecting an existing manual value", () => {
    const manual = candidate({ current_personality: "谨慎克制，习惯先观察再表态。" });
    let state = reduceCharacterProfileCompletionSelection(
      createCharacterProfileCompletionSelectionState(),
      { type: "load-candidates", jobId: "job-1", candidates: [manual] },
    );
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "set-selected",
      characterId: manual.character_id,
      selected: true,
    });

    expect(characterProfileCompletionSelectionSummary(state).selectedCount).toBe(0);
    expect(characterProfileCompletionCandidateViews(state)[0]).toMatchObject({
      currentPersonality: "谨慎克制，习惯先观察再表态。",
      selected: false,
      selectionDisabled: true,
      selectionDisabledReason: "replacement-confirmation-required",
      requiresReplacementConfirmation: true,
      replacementConfirmed: false,
    });

    state = reduceCharacterProfileCompletionSelection(state, {
      type: "confirm-replacement",
      characterId: manual.character_id,
    });
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "set-selected",
      characterId: manual.character_id,
      selected: true,
    });

    expect(characterProfileCompletionSelectionSummary(state)).toMatchObject({
      selectedCount: 1,
      applyDisabled: false,
    });
    expect(characterProfileCompletionCandidateViews(state)[0]).toMatchObject({
      selected: true,
      selectionDisabled: false,
      replacementConfirmed: true,
    });
  });

  it("cancels replacement consent and selection together", () => {
    const manual = candidate({ current_personality: "谨慎克制。" });
    let state = reduceCharacterProfileCompletionSelection(
      createCharacterProfileCompletionSelectionState(),
      { type: "load-candidates", jobId: "job-1", candidates: [manual] },
    );
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "confirm-replacement",
      characterId: manual.character_id,
    });
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "set-selected",
      characterId: manual.character_id,
      selected: true,
    });
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "cancel-replacement",
      characterId: manual.character_id,
    });

    expect(state.selectedCharacterIds).toEqual({});
    expect(state.replacementConfirmedCharacterIds).toEqual({});
    expect(characterProfileCompletionSelectionSummary(state).applyDisabled).toBe(true);
  });

  it("never selects insufficient-evidence or empty candidates", () => {
    const insufficient = candidate({
      character_id: "character-2",
      character_name: "魏秋萍",
      status: "insufficient_evidence",
      personality: null,
      basis: null,
      confidence: null,
      evidence: [],
      warnings: ["没有足够的可核验证据"],
    });
    const invalid = candidate({
      character_id: "character-3",
      character_name: "冯远征",
      personality: "  ",
    });
    let state = reduceCharacterProfileCompletionSelection(
      createCharacterProfileCompletionSelectionState(),
      { type: "load-candidates", jobId: "job-1", candidates: [insufficient, invalid] },
    );
    for (const item of state.candidates) {
      state = reduceCharacterProfileCompletionSelection(state, {
        type: "set-selected",
        characterId: item.character_id,
        selected: true,
      });
    }

    const views = characterProfileCompletionCandidateViews(state);
    expect(characterProfileCompletionSelectionSummary(state)).toMatchObject({
      selectedCount: 0,
      candidateCount: 0,
      insufficientEvidenceCount: 1,
      applyDisabled: true,
    });
    expect(views[0]).toMatchObject({
      statusLabel: "证据不足",
      selectionDisabledReason: "insufficient-evidence",
      suggestedPersonality: "无可应用候选",
    });
    expect(views[0].warnings).toContain("证据不足：不会生成或应用推测性格");
    expect(views[1].selectionDisabledReason).toBe("invalid-candidate");
  });

  it("derives explicit evidence, warning, basis, confidence, and apply decision fields", () => {
    let state = reduceCharacterProfileCompletionSelection(
      createCharacterProfileCompletionSelectionState(),
      { type: "load-candidates", jobId: "job-1", candidates: [candidate()] },
    );
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "set-selected",
      characterId: "character-1",
      selected: true,
    });

    const view = characterProfileCompletionCandidateViews(state)[0];
    const summary = characterProfileCompletionSelectionSummary(state);
    expect(view).toMatchObject({
      statusLabel: "候选可审阅",
      basisLabel: "设定与正文混合依据",
      confidenceLabel: "置信度 86/100",
      warnings: ["当前仅有一章正文，行为结论仍需后续验证"],
      selected: true,
      selectionDisabled: false,
    });
    expect(view.evidence).toEqual([
      { sourceTypeLabel: "角色资料", sourceIdLabel: "character-1", quote: "认死理，凡事要有证据。" },
      { sourceTypeLabel: "正式正文", sourceIdLabel: "chapter-1", quote: "江述反复核对卷宗页码。" },
    ]);
    expect(summary.decisions).toEqual([{
      character_id: "character-1",
      base_version: 2,
      replace_existing: false,
    }]);
  });

  it("resets selections and replacement consent when candidates are reloaded", () => {
    let state = reduceCharacterProfileCompletionSelection(
      createCharacterProfileCompletionSelectionState(),
      { type: "load-candidates", jobId: "job-1", candidates: [candidate()] },
    );
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "set-selected",
      characterId: "character-1",
      selected: true,
    });
    state = reduceCharacterProfileCompletionSelection(state, {
      type: "load-candidates",
      jobId: "job-2",
      candidates: [candidate({ base_version: 3 })],
    });

    expect(state.jobId).toBe("job-2");
    expect(characterProfileCompletionSelectionSummary(state).selectedCount).toBe(0);
    expect(characterProfileCompletionSelectionSummary(state).applyDisabled).toBe(true);
  });
});
