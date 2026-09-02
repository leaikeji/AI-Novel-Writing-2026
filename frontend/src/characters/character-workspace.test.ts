import { describe, expect, it, vi } from "vitest";

import {
  createCharacterWorkspaceDialog,
  type CharacterWorkspaceDialogProps,
} from "./character-workspace";
import { characterWorkspace, multiTimelineWorkspace, storyFactImpact } from "./test-fixtures";
import { createReactHarness, findAll, findButton, settle, textContent } from "./test-harness";

describe("formal character workspace", () => {
  it("portals the modal outside the isolated workbench stacking context", () => {
    const harness = createReactHarness();
    const container = {} as Element;
    const createPortal = vi.fn((node: unknown) => node);
    const getContainer = vi.fn(() => container);
    const Component = createCharacterWorkspaceDialog(harness.React, {
      createPortal,
      getContainer,
    });
    const root = harness.render(Component, { workspace: characterWorkspace() });

    expect(getContainer).toHaveBeenCalledOnce();
    expect(createPortal).toHaveBeenCalledWith(root, container);
    expect(root.props.className).toBe("anw-character-workspace-backdrop");
  });

  it("renders four accessible tabs and hides timeline mechanics in single-line mode", () => {
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const root = harness.render(Component, { workspace: characterWorkspace() });
    const tabs = findAll(root, (element) => element.props.role === "tab");

    expect(tabs.map((tab) => textContent(tab.children[0]))).toEqual(["基础资料", "当前线设定", "状态与经历", "声音"]);
    expect(tabs.map((tab) => tab.props["aria-controls"])).toHaveLength(4);
    expect(findAll(root, (element) => element.type === "select")).toHaveLength(1);
    expect(textContent(root)).not.toContain("instance-main");
    expect(textContent(root)).not.toContain("主线版本");
    expect(textContent(root)).not.toContain("本线人物");
    expect(textContent(root)).toContain("主角");
    expect(textContent(root)).not.toContain("main");
    const roleSelect = findAll(root, (element) =>
      String(element.props.id).endsWith("field-character-role_type"),
    )[0];
    expect(roleSelect.type).toBe("select");
    expect(roleSelect.props.value).toBe("main");
    expect(textContent(root)).toContain("正式人物卡 · v4");
    expect(textContent(root)).toContain("人物基础信息");
  });

  it("shows explicit timeline and instance selectors after entering multi-line mode", () => {
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const root = harness.render(Component, { workspace: multiTimelineWorkspace() });
    const selects = findAll(root, (element) => element.type === "select");

    expect(selects).toHaveLength(3);
    expect(textContent(root)).toContain("雨夜分支");
    expect(textContent(root)).toContain("雨夜后的林舟");
    expect(textContent(root)).not.toContain("instance-branch");
  });

  it("keeps projected growth read-only", () => {
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace: characterWorkspace() });
    const growthTab = findAll(root, (element) =>
      element.props.role === "tab" && textContent(element).startsWith("状态与经历"),
    )[0];
    (growthTab.props.onClick as () => void)();
    root = harness.render(Component, { workspace: characterWorkspace() });
    const growthPanel = findAll(root, (element) => element.props.id === "character-workspace-character-1-panel-growth")[0];

    expect(growthPanel.props["aria-label"]).toContain("只读");
    expect(textContent(growthPanel)).toContain("当前写作状态");
    expect(textContent(growthPanel)).toContain("勇气");
    expect(textContent(growthPanel)).toContain("开始主动承担风险");
    expect(textContent(growthPanel)).toContain("查看全部事实（1）");
    expect(findAll(growthPanel, (element) => ["input", "textarea", "select"].includes(String(element.type)))).toHaveLength(0);
  });

  it("loads the auditable fact history only after the author expands it", async () => {
    const workspace = characterWorkspace();
    const onLoadFacts = vi.fn().mockResolvedValue({
      schema_version: "character-fact-history/1",
      items: workspace.projected_state.current_facts,
      next_cursor: null,
      total_summary: workspace.writing_state.history_summary,
    });
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace, onLoadFacts });
    (findButton(root, "状态与经历").props.onClick as () => void)();
    root = harness.render(Component, { workspace, onLoadFacts });

    expect(onLoadFacts).not.toHaveBeenCalled();
    (findButton(root, "查看全部事实（1）").props.onClick as () => void)();
    root = harness.render(Component, { workspace, onLoadFacts });
    harness.commitEffects();
    await settle();
    root = harness.render(Component, { workspace, onLoadFacts });

    expect(onLoadFacts).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 20,
        effective_state: "all",
        health: "all",
      }),
      expect.any(AbortSignal),
    );
    expect(textContent(root)).toContain("历史、失效与已撤销事实保留用于审计");
    expect(textContent(root)).toContain("开始主动承担风险");
  });

  it("creates a replacement fact instead of editing the old fact", async () => {
    const workspace = characterWorkspace();
    const onCorrectFact = vi.fn().mockResolvedValue({
      ...workspace,
      story_ledger_version: 20,
    });
    const onLoadFactImpact = vi.fn().mockResolvedValue(storyFactImpact());
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const props = { workspace, onCorrectFact, onLoadFactImpact };
    let root = harness.render(Component, props);
    (findButton(root, "状态与经历").props.onClick as () => void)();
    root = harness.render(Component, props);
    const correctionTrigger = {} as HTMLElement;
    (findButton(root, "修正").props.onClick as (
      event: { currentTarget: HTMLElement },
    ) => void)({ currentTarget: correctionTrigger });
    await settle();
    root = harness.render(Component, props);
    let drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    const textareas = findAll(drawer, (element) => element.type === "textarea");
    (textareas[0].props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "开始主动保护同伴" },
    });
    (textareas[1].props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "章节明确写出新的选择" },
    });
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    (findButton(drawer, "创建替代事实").props.onClick as () => void)();
    await settle();

    expect(onCorrectFact).toHaveBeenCalledWith(
      "fact-1",
      expect.objectContaining({
        schema_version: "story-fact-correction/1",
        expected_story_ledger_version: 19,
        reason: "章节明确写出新的选择",
        replacement: { object_text: "开始主动保护同伴" },
      }),
      expect.any(AbortSignal),
    );
  });

  it("renders voice UI only through the injected slot", () => {
    const voiceSlot = vi.fn(() => ({ type: "voice-owner", props: {}, children: ["共用声音设置"] }));
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace: characterWorkspace(), voiceSlot });
    (findButton(root, "声音").props.onClick as () => void)();
    root = harness.render(Component, { workspace: characterWorkspace(), voiceSlot });

    expect(voiceSlot).toHaveBeenCalledWith(expect.objectContaining({ characterId: "character-1" }));
    expect(textContent(root)).toContain("共用声音设置");
  });

  it("shows only close on a clean voice tab and preserves draft actions when other fields are dirty", () => {
    const voiceSlot = vi.fn(() => ({ type: "voice-owner", props: {}, children: ["共用声音设置"] }));
    const onRequestClose = vi.fn();
    const onSave = vi.fn();
    const props: CharacterWorkspaceDialogProps = {
      workspace: characterWorkspace(),
      voiceSlot,
      onRequestClose,
      onSave,
    };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    (findButton(root, "声音").props.onClick as () => void)();
    root = harness.render(Component, props);
    let footer = findAll(root, (element) => (
      element.type === "footer" && element.props.className === "anw-character-workspace-footer"
    ))[0];
    expect(findAll(footer, (element) => element.type === "button").map(textContent))
      .toEqual(["关闭"]);
    expect(textContent(footer)).toContain("声音设置由共用声音组件独立保存");

    (findButton(root, "基础资料").props.onClick as () => void)();
    root = harness.render(Component, props);
    const nameInput = findAll(root, (element) => String(element.props.id).endsWith("field-character-name"))[0];
    (nameInput.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "林舟的新名字" },
    });
    root = harness.render(Component, props);
    (findButton(root, "声音").props.onClick as () => void)();
    root = harness.render(Component, props);
    footer = findAll(root, (element) => (
      element.type === "footer" && element.props.className === "anw-character-workspace-footer"
    ))[0];
    expect(findAll(footer, (element) => element.type === "button").map(textContent))
      .toEqual(["撤销修改", "关闭", "保存人物卡"]);
    expect(textContent(footer)).toContain("其他栏目还有未保存修改");
    expect(textContent(footer)).toContain("只处理人物卡字段");
  });

  it("offers an explicit header close action", () => {
    const onRequestClose = vi.fn();
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const root = harness.render(Component, { workspace: characterWorkspace(), onRequestClose });

    (findButton(root, "×").props.onClick as () => void)();

    expect(onRequestClose).toHaveBeenCalledOnce();
  });

  it("preserves the draft and locates the field after a CAS conflict", async () => {
    const onSave = vi.fn().mockRejectedValue({
      code: "cas_conflict",
      message: "人物已被另一处更新，请核对后重试。",
      field_errors: { "character.name": "服务端版本已变化。" },
    });
    const props: CharacterWorkspaceDialogProps = { workspace: characterWorkspace(), onSave };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    const nameInput = findAll(root, (element) => String(element.props.id).endsWith("field-character-name"))[0];
    (nameInput.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "林舟的新名字" },
    });
    root = harness.render(Component, props);
    (findButton(root, "保存人物卡").props.onClick as () => void)();
    await settle();
    root = harness.render(Component, props);

    const retained = findAll(root, (element) => String(element.props.id).endsWith("field-character-name"))[0];
    expect(retained.props.value).toBe("林舟的新名字");
    expect(retained.props["aria-invalid"]).toBe(true);
    expect(textContent(root)).toContain("人物卡已在其他位置更新");
    expect(textContent(root)).toContain("服务端版本已变化");
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ expected_character_version: 4, expected_instance_version: 7 }),
    );
  });
});
