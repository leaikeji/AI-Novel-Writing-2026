import { describe, expect, it, vi } from "vitest";

import {
  OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION,
  type CharacterRegenerationConfirmationState,
  type NameConflictDecisionState,
  type OutlineCharacterDraftV2,
} from "./contracts";
import {
  createOutlineCharacterDraftsPanel,
  type OutlineCharacterDraftsPanelProps,
} from "./outline-character-drafts-panel";
import { openRegenerationConfirmation } from "./state";
import {
  TEST_ANTD,
  TEST_REACT,
  findAll,
  findButton,
  textContent,
} from "./test-harness";


function draft(
  key: string,
  origin: OutlineCharacterDraftV2["origin"],
  name: string,
): OutlineCharacterDraftV2 {
  return {
    schema_version: OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION,
    draft_key: key,
    character_id: null,
    role_type: "main",
    name,
    gender: "女",
    age_at_story_start_note: "二十一岁左右",
    identity_summary: "档案员",
    personality_summary: "克制但执着",
    core_goal: "找回失踪档案",
    bio: "来自河湾镇。",
    origin,
  };
}


function baseProps(
  patches: Partial<OutlineCharacterDraftsPanelProps> = {},
): OutlineCharacterDraftsPanelProps {
  return {
    drafts: [draft("ai:1", "ai_candidate", "林遥")],
    existingCharacters: [],
    generation: { phase: "idle", failure_message: null },
    regenerationConfirmation: null,
    onDraftChange: vi.fn(),
    onAddManualDraft: vi.fn(),
    onConflictDecisionChange: vi.fn(),
    onResolveNameConflict: vi.fn(),
    onRegenerationConfirmationChange: vi.fn(),
    onConfirmRegeneration: vi.fn(),
    ...patches,
  };
}


describe("outline character drafts panel", () => {
  it("exposes every V2 field and keeps manual editing available after AI failure", () => {
    const onAddManualDraft = vi.fn();
    const props = baseProps({
      generation: { phase: "failed", failure_message: "模型暂不可用" },
      onAddManualDraft,
    });
    const Component = createOutlineCharacterDraftsPanel(TEST_REACT, TEST_ANTD);
    const root = Component(props);

    expect(findAll(
      root,
      (item) => item.type === "alert" && item.props.message === "AI 生成人物失败",
    )).toHaveLength(1);
    expect(findAll(root, (item) => item.props["aria-label"] === "人物1姓名")).toHaveLength(1);
    for (const label of [
      "林遥性别",
      "林遥故事开始时年龄说明",
      "林遥身份摘要",
      "林遥性格摘要",
      "林遥核心目标",
      "林遥人物小传",
    ]) {
      expect(findAll(root, (item) => item.props["aria-label"] === label)).toHaveLength(1);
    }
    expect(textContent(root)).toContain("ai:1");
    const card = findAll(root, (item) => item.type === "article")[0];
    expect(textContent(card.props.extra)).toContain("AI 草案");

    (findButton(root, "手工新增人物").props.onClick as () => void)();
    expect(onAddManualDraft).toHaveBeenCalledOnce();
  });

  it("requires explicit link_existing or a non-conflicting create_new name", () => {
    let decision: NameConflictDecisionState = {
      mode: "create_new",
      existing_character_id: "formal:1",
      renamed_name: "林遥",
    };
    const onDecision = vi.fn((_: string, next: NameConflictDecisionState) => {
      decision = next;
    });
    const onResolve = vi.fn();
    const Component = createOutlineCharacterDraftsPanel(TEST_REACT, TEST_ANTD);
    const render = () => Component(baseProps({
      existingCharacters: [{ character_id: "formal:1", name: "林遥", role_type: "main" }],
      conflictDecisions: { "ai:1": decision },
      onConflictDecisionChange: onDecision,
      onResolveNameConflict: onResolve,
    }));

    let root = render();
    const conflictAlert = findAll(
      root,
      (item) => item.type === "alert"
        && item.props.message === "发现同名正式人物，请明确处理",
    )[0];
    expect(conflictAlert.props.description).toContain("系统不会按姓名自动关联");
    expect(findButton(root, "确认改名并新建").props.disabled).toBe(true);

    const rename = findAll(
      root,
      (element) => element.props["aria-label"] === "林遥新建时的姓名",
    )[0];
    (rename.props.onChange as (event: unknown) => void)({ target: { value: "林遥（旧线）" } });
    root = render();
    expect(findButton(root, "确认改名并新建").props.disabled).toBe(false);
    (findButton(root, "确认改名并新建").props.onClick as () => void)();
    expect(onResolve).toHaveBeenCalledWith("ai:1", {
      kind: "create_new",
      renamed_name: "林遥（旧线）",
    });
  });

  it("returns an explicit replacement plan and does not include manual drafts by default", () => {
    const drafts = [
      draft("ai:1", "ai_candidate", "林遥"),
      draft("manual:1", "manual", "周岚"),
    ];
    let confirmation: CharacterRegenerationConfirmationState | null = null;
    const onConfirmationChange = vi.fn((next: CharacterRegenerationConfirmationState | null) => {
      confirmation = next;
    });
    const onConfirm = vi.fn();
    const Component = createOutlineCharacterDraftsPanel(TEST_REACT, TEST_ANTD);
    const render = () => Component(baseProps({
      drafts,
      regenerationConfirmation: confirmation,
      onRegenerationConfirmationChange: onConfirmationChange,
      onConfirmRegeneration: onConfirm,
    }));

    let root = render();
    (findButton(root, "再次生成人物").props.onClick as () => void)();
    expect(confirmation).toEqual(openRegenerationConfirmation(drafts));

    root = render();
    expect(textContent(root)).toContain("将替换 1 项，保留 1 项");
    (findButton(root, "确认并再次生成").props.onClick as () => void)();
    expect(onConfirm).toHaveBeenCalledWith({
      scope: "ai_generated_only",
      replace_draft_keys: ["ai:1"],
      preserve_draft_keys: ["manual:1"],
    });
  });

  it("starts first generation directly when a fresh novel has no drafts", () => {
    const onConfirm = vi.fn();
    const Component = createOutlineCharacterDraftsPanel(TEST_REACT, TEST_ANTD);
    const root = Component(baseProps({ drafts: [], onConfirmRegeneration: onConfirm }));

    (findButton(root, "生成人物").props.onClick as () => void)();
    expect(onConfirm).toHaveBeenCalledWith({
      scope: "all_drafts",
      replace_draft_keys: [],
      preserve_draft_keys: [],
    });
  });
});
