import { describe, expect, it, vi } from "vitest";

import {
  createCharacterWorkspaceDialog,
  type CharacterWorkspaceDialogProps,
} from "./character-workspace";
import { characterWorkspace, multiTimelineWorkspace } from "./test-fixtures";
import { createReactHarness, findAll, findButton, settle, textContent } from "./test-harness";

describe("formal character workspace", () => {
  it("renders four accessible tabs and hides timeline mechanics in single-line mode", () => {
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const root = harness.render(Component, { workspace: characterWorkspace() });
    const tabs = findAll(root, (element) => element.props.role === "tab");

    expect(tabs.map(textContent)).toEqual(["基础资料", "本线档案", "成长与状态", "声音"]);
    expect(tabs.map((tab) => tab.props["aria-controls"])).toHaveLength(4);
    expect(findAll(root, (element) => element.type === "select")).toHaveLength(0);
    expect(textContent(root)).not.toContain("instance-main");
    expect(textContent(root)).not.toContain("主线版本");
    expect(textContent(root)).not.toContain("本线人物");
  });

  it("shows explicit timeline and instance selectors after entering multi-line mode", () => {
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const root = harness.render(Component, { workspace: multiTimelineWorkspace() });
    const selects = findAll(root, (element) => element.type === "select");

    expect(selects).toHaveLength(2);
    expect(textContent(root)).toContain("雨夜分支");
    expect(textContent(root)).toContain("雨夜后的林舟");
    expect(textContent(root)).not.toContain("instance-branch");
  });

  it("keeps projected growth read-only", () => {
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace: characterWorkspace() });
    (findButton(root, "成长与状态").props.onClick as () => void)();
    root = harness.render(Component, { workspace: characterWorkspace() });
    const growthPanel = findAll(root, (element) => element.props.id === "character-workspace-character-1-panel-growth")[0];

    expect(growthPanel.props["aria-label"]).toContain("只读");
    expect(textContent(growthPanel)).toContain("开始主动承担风险");
    expect(findAll(growthPanel, (element) => ["input", "textarea", "select"].includes(String(element.type)))).toHaveLength(0);
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
