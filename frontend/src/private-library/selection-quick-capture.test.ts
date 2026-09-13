import { describe, expect, it, vi } from "vitest";

import { createSelectionQuickCapture } from "./selection-quick-capture";
import {
  TEST_ANTD,
  createPrivateLibraryHarness,
  findAll,
  findButton,
  findByLabel,
  textContent,
} from "./test-harness";


describe("selection quick capture", () => {
  it("offers collection only when there is no active novel", () => {
    const harness = createPrivateLibraryHarness();
    const Capture = createSelectionQuickCapture(harness.React, TEST_ANTD);
    const tree = harness.render(Capture, {
      selectedText: "排水坡度",
      targets: [],
      onCancel: vi.fn(),
      onSave: vi.fn(),
    });
    const destination = findByLabel(tree, "选中文本保存动作");
    expect(destination.props.options).toEqual([
      { value: "collect", label: "仅收藏到通用库" },
    ]);
    expect(textContent(tree)).toContain("不会自动用于任何作品");
  });

  it("saves the exact selection to the visible current-book destination", async () => {
    const harness = createPrivateLibraryHarness();
    const Capture = createSelectionQuickCapture(harness.React, TEST_ANTD);
    const onSave = vi.fn();
    const input = {
      selectedText: "不禁让人皱眉",
      activeNovel: { id: "novel-a", title: "危楼之下" },
      targets: [{
        assetId: "book-words",
        title: "本书用词",
        category: "vocabulary" as const,
        scopeKind: "novel" as const,
        scopeNovelId: "novel-a",
      }, {
        assetId: "other-book",
        title: "另一部书",
        category: "vocabulary" as const,
        scopeKind: "novel" as const,
        scopeNovelId: "novel-b",
      }],
      onCancel: vi.fn(),
      onSave,
    };
    let tree = harness.render(Capture, input);
    (findByLabel(tree, "选中文本保存动作").props.onChange as (value: string) => void)("use_current_novel");
    tree = harness.render(Capture, input);
    expect(findByLabel(tree, "选中文本目标资料").props.options).toEqual([
      { value: "book-words", label: "本书用词" },
    ]);
    (findByLabel(tree, "选中文本目标资料").props.onChange as (value: string) => void)("book-words");
    tree = harness.render(Capture, input);
    (findByLabel(tree, "选中文本使用方式").props.onChange as (value: string) => void)("forbid");
    tree = harness.render(Capture, input);
    (findButton(tree, "保存并用于本书").props.onClick as () => void)();
    expect(onSave).toHaveBeenCalledWith({
      selectedText: "不禁让人皱眉",
      category: "vocabulary",
      targetAssetId: "book-words",
      action: "forbid",
      destination: "use_current_novel",
      novelId: "novel-a",
    });
    await Promise.resolve();
  });

  it("keeps the selected text visible when an injected save fails", async () => {
    const harness = createPrivateLibraryHarness();
    const Capture = createSelectionQuickCapture(harness.React, TEST_ANTD);
    const input = {
      selectedText: "泛着一丝",
      targets: [],
      onCancel: vi.fn(),
      onSave: vi.fn().mockRejectedValue(new Error("保存请求失败")),
    };
    let tree = harness.render(Capture, input);
    (findButton(tree, "收藏").props.onClick as () => void)();
    await Promise.resolve();
    await Promise.resolve();
    tree = harness.render(Capture, input);
    expect(findByLabel(tree, "要收藏的选中文本").props.value).toBe("泛着一丝");
    const error = findAll(tree, (element) => element.type === "alert" && element.props.type === "error")[0];
    expect(error?.props.message).toBe("保存请求失败");
  });
});
