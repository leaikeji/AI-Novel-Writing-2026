import { describe, expect, it, vi } from "vitest";

import {
  createAssistantFormFieldAdapter,
  FormFieldBaselineConflictError,
  FormFieldControlledUpdateError,
} from "./assistant-form-field";
import type {
  AIApplyMeta,
  SelectionRange,
  SelectionSnapshot,
} from "./assistant-fields";


function hashValue(value: string): string {
  return `sha256:${value}`;
}


function applyMeta(
  sourceValueSha256: string,
  operation = "rewrite",
): AIApplyMeta {
  return {
    transactionId: `transaction-${operation}`,
    agentId: "ai-novel-writer",
    sessionId: "session-1",
    selectionId: "selection-1",
    operation,
    sourceValueSha256,
    appliedAt: "2026-08-25T12:00:00+08:00",
  };
}


function selectionFor(value: string): SelectionSnapshot {
  return {
    startUtf16: 0,
    endUtf16: value.length,
    direction: "forward",
    text: value,
    before: "",
    after: "",
  };
}


describe("createAssistantFormFieldAdapter", () => {
  it("updates the controlled draft and marks dirty without invoking original save", async () => {
    const state = {
      value: "旧标题",
      dirty: false,
      selection: selectionFor("旧标题") as SelectionSnapshot | null,
    };
    const applyDraftValue = vi.fn((nextValue: string) => {
      state.value = nextValue;
      state.selection = selectionFor(nextValue);
    });
    const markDirty = vi.fn(() => { state.dirty = true; });
    const originalSaveButtonAction = vi.fn(() => { state.dirty = false; });
    const adapter = createAssistantFormFieldAdapter({
      id: "chapter.title",
      label: "章节标题",
      getValue: () => state.value,
      getDirty: () => state.dirty,
      getSelection: () => state.selection,
      hashValue,
      applyDraftValue,
      markDirty,
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    const receipt = await adapter.applyValueWithReceipt(
      "新标题",
      applyMeta(hashValue("旧标题")),
    );

    expect(adapter.persistence).toBe("explicit-save");
    expect(applyDraftValue).toHaveBeenCalledTimes(1);
    expect(markDirty).toHaveBeenCalledTimes(1);
    expect(originalSaveButtonAction).not.toHaveBeenCalled();
    expect(state).toMatchObject({ value: "新标题", dirty: true });
    expect(receipt).toMatchObject({
      fieldId: "chapter.title",
      before: {
        value: "旧标题",
        valueSha256: hashValue("旧标题"),
        dirty: false,
      },
      after: {
        value: "新标题",
        valueSha256: hashValue("新标题"),
        dirty: true,
      },
      persistence: "explicit-save",
      saveRequested: false,
    });

    // The page's existing button remains the only route that persists.
    originalSaveButtonAction();
    expect(originalSaveButtonAction).toHaveBeenCalledTimes(1);
    expect(state.dirty).toBe(false);
  });

  it("supports focus, selection restore, and a dirty undo receipt", async () => {
    const state = {
      value: "原章纲",
      dirty: false,
      selection: selectionFor("原章纲") as SelectionSnapshot | null,
    };
    const restored: SelectionRange[] = [];
    const focus = vi.fn();
    const adapter = createAssistantFormFieldAdapter({
      id: "chapter.outline",
      label: "章节大纲",
      getValue: () => state.value,
      getDirty: () => state.dirty,
      getSelection: () => state.selection,
      hashValue,
      applyDraftValue: (nextValue) => {
        state.value = nextValue;
        state.selection = selectionFor(nextValue);
      },
      markDirty: () => { state.dirty = true; },
      restoreSelection: (range) => restored.push(range),
      focus,
    });

    const receipt = await adapter.applyValueWithReceipt(
      "AI 章纲",
      applyMeta(hashValue("原章纲")),
    );
    const undoReceipt = await adapter.applyValueWithReceipt(
      receipt.before.value,
      applyMeta(receipt.after.valueSha256, "undo"),
    );
    adapter.focus();
    adapter.restoreSelection({
      startUtf16: 0,
      endUtf16: 3,
      direction: "none",
    });

    expect(undoReceipt).toMatchObject({
      before: { value: "AI 章纲", dirty: true },
      after: { value: "原章纲", dirty: true },
      saveRequested: false,
    });
    expect(focus).toHaveBeenCalledTimes(1);
    expect(restored).toEqual([{
      startUtf16: 0,
      endUtf16: 3,
      direction: "none",
    }]);
  });

  it("rejects a stale baseline before changing the draft or dirty state", async () => {
    let value = "作者刚改的标题";
    let dirty = false;
    const applyDraftValue = vi.fn((nextValue: string) => { value = nextValue; });
    const markDirty = vi.fn(() => { dirty = true; });
    const adapter = createAssistantFormFieldAdapter({
      id: "chapter.title",
      label: "章节标题",
      getValue: () => value,
      getDirty: () => dirty,
      getSelection: () => null,
      hashValue,
      applyDraftValue,
      markDirty,
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    await expect(adapter.applyValue(
      "AI 的过期标题",
      applyMeta(hashValue("更早的标题")),
    )).rejects.toBeInstanceOf(FormFieldBaselineConflictError);
    expect(value).toBe("作者刚改的标题");
    expect(dirty).toBe(false);
    expect(applyDraftValue).not.toHaveBeenCalled();
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("does not mark dirty or save when controlled draft state rejects the value", async () => {
    const markDirty = vi.fn();
    const originalSaveButtonAction = vi.fn();
    const adapter = createAssistantFormFieldAdapter({
      id: "chapter.title",
      label: "章节标题",
      getValue: () => "旧标题",
      getDirty: () => false,
      getSelection: () => null,
      hashValue,
      applyDraftValue: vi.fn(),
      markDirty,
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    await expect(adapter.applyValue(
      "新标题",
      applyMeta(hashValue("旧标题")),
    )).rejects.toBeInstanceOf(FormFieldControlledUpdateError);
    expect(markDirty).not.toHaveBeenCalled();
    expect(originalSaveButtonAction).not.toHaveBeenCalled();
  });
});
