import { describe, expect, it, vi } from "vitest";

import {
  BodyFieldBaselineConflictError,
  BodyFieldControlledUpdateError,
  createAssistantBodyFieldAdapter,
} from "./assistant-body-field";
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


describe("createAssistantBodyFieldAdapter", () => {
  it("applies through controlled state, queues autosave, and returns undo evidence", async () => {
    const state = {
      value: "旧正文",
      dirty: false,
      selection: selectionFor("旧正文") as SelectionSnapshot | null,
    };
    const applyEditorContent = vi.fn((nextValue: string) => {
      state.value = nextValue;
      state.dirty = true;
      state.selection = selectionFor(nextValue);
    });
    const scheduleAutosave = vi.fn();
    const focus = vi.fn();
    const restored: SelectionRange[] = [];
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => state.value,
      getDirty: () => state.dirty,
      getSelection: () => state.selection,
      hashValue,
      applyEditorContent,
      scheduleAutosave,
      restoreSelection: (range) => restored.push(range),
      focus,
    });

    const receipt = await adapter.applyValueWithReceipt(
      "新正文",
      applyMeta(hashValue("旧正文")),
    );

    expect(adapter.persistence).toBe("autosave");
    expect(adapter.undoPolicy).toBe("ai-transaction");
    expect(applyEditorContent).toHaveBeenCalledTimes(1);
    expect(scheduleAutosave).toHaveBeenCalledWith(
      "新正文",
      expect.objectContaining({ transactionId: "transaction-rewrite" }),
    );
    expect(receipt).toMatchObject({
      fieldId: "chapter.body",
      before: {
        value: "旧正文",
        valueSha256: hashValue("旧正文"),
        dirty: false,
      },
      after: {
        value: "新正文",
        valueSha256: hashValue("新正文"),
        dirty: true,
      },
      persistence: "autosave",
      autosaveRequested: true,
    });
    expect(adapter.getLastApplyReceipt()).toBe(receipt);

    adapter.focus();
    adapter.restoreSelection({
      startUtf16: 0,
      endUtf16: 3,
      direction: "backward",
    });
    expect(focus).toHaveBeenCalledTimes(1);
    expect(restored).toEqual([{
      startUtf16: 0,
      endUtf16: 3,
      direction: "backward",
    }]);

    const undoReceipt = await adapter.applyValueWithReceipt(
      receipt.before.value,
      applyMeta(receipt.after.valueSha256, "undo"),
    );
    expect(undoReceipt.before.value).toBe("新正文");
    expect(undoReceipt.after.value).toBe("旧正文");
    expect(scheduleAutosave).toHaveBeenCalledTimes(2);
  });

  it("rejects a stale baseline without changing state or scheduling save", async () => {
    let value = "作者刚刚修改的正文";
    const applyEditorContent = vi.fn((nextValue: string) => { value = nextValue; });
    const scheduleAutosave = vi.fn();
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => value,
      getDirty: () => true,
      getSelection: () => null,
      hashValue,
      applyEditorContent,
      scheduleAutosave,
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    await expect(adapter.applyValue(
      "AI 的过期正文",
      applyMeta(hashValue("更早的正文")),
    )).rejects.toBeInstanceOf(BodyFieldBaselineConflictError);
    expect(value).toBe("作者刚刚修改的正文");
    expect(applyEditorContent).not.toHaveBeenCalled();
    expect(scheduleAutosave).not.toHaveBeenCalled();
    expect(adapter.getLastApplyReceipt()).toBeNull();
  });

  it("rechecks the getter after asynchronous hashing to close the typing race", async () => {
    let value = "开始值";
    let releaseHash: (() => void) | undefined;
    const firstHashGate = new Promise<void>((resolve) => { releaseHash = resolve; });
    const hash = vi.fn(async (input: string) => {
      if (input === "开始值") await firstHashGate;
      return hashValue(input);
    });
    const applyEditorContent = vi.fn((nextValue: string) => { value = nextValue; });
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => value,
      getDirty: () => true,
      getSelection: () => null,
      hashValue: hash,
      applyEditorContent,
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    const applying = adapter.applyValue(
      "AI 正文",
      applyMeta(hashValue("开始值")),
    );
    value = "作者输入";
    releaseHash?.();

    await expect(applying).rejects.toBeInstanceOf(BodyFieldBaselineConflictError);
    expect(value).toBe("作者输入");
    expect(applyEditorContent).not.toHaveBeenCalled();
  });

  it("does not fall back to a DOM write when the controlled callback rejects the value", async () => {
    const scheduleAutosave = vi.fn();
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => "旧正文",
      getDirty: () => false,
      getSelection: () => null,
      hashValue,
      applyEditorContent: vi.fn(),
      scheduleAutosave,
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    await expect(adapter.applyValue(
      "新正文",
      applyMeta(hashValue("旧正文")),
    )).rejects.toBeInstanceOf(BodyFieldControlledUpdateError);
    expect(scheduleAutosave).not.toHaveBeenCalled();
  });
});
