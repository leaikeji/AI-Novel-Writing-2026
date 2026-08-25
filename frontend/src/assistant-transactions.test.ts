import { describe, expect, it, vi } from "vitest";

import {
  AIEditTransactionManager,
  applySelectionOperation,
} from "./assistant-transactions";
import type {
  AIApplyMeta,
  EditableFieldAdapter,
  EditableFieldPersistence,
  SelectionRange,
} from "./assistant-fields";


function controlledAdapter(
  initial: string,
  persistence: EditableFieldPersistence = "explicit-save",
) {
  let value = initial;
  let dirty = false;
  let restored: SelectionRange | undefined;
  const apply = vi.fn((nextValue: string, _meta: AIApplyMeta) => {
    value = nextValue;
    dirty = true;
  });
  const focus = vi.fn();
  const adapter: EditableFieldAdapter = {
    id: "chapter.body",
    label: "正文",
    persistence,
    undoPolicy: "ai-transaction",
    getValue: () => value,
    applyValue: apply,
    getSelection: () => ({
      text: value.slice(2, 4),
      startUtf16: 2,
      endUtf16: 4,
      direction: "forward",
      before: value.slice(0, 2),
      after: value.slice(4),
    }),
    restoreSelection: (range) => { restored = range; },
    focus,
    getDirty: () => dirty,
    dispose: () => undefined,
  };
  return {
    adapter,
    apply,
    focus,
    value: () => value,
    restored: () => restored,
    authorChange: (nextValue: string) => { value = nextValue; },
  };
}


describe("applySelectionOperation", () => {
  it("replaces only the selected UTF-16 range", () => {
    expect(applySelectionOperation(
      "木门后潮声渐近",
      { startUtf16: 3, endUtf16: 5, direction: "forward" },
      "海潮声",
      "replace-selection",
    )).toEqual({
      value: "木门后海潮声渐近",
      selection: { startUtf16: 3, endUtf16: 6, direction: "forward" },
    });
  });

  it("inserts after the selection without deleting it", () => {
    expect(applySelectionOperation(
      "甲乙丙丁",
      { startUtf16: 1, endUtf16: 3, direction: "backward" },
      "戊",
      "insert-after-selection",
    )).toEqual({
      value: "甲乙丙戊丁",
      selection: { startUtf16: 3, endUtf16: 4, direction: "forward" },
    });
  });
});


describe("AIEditTransactionManager", () => {
  const digest = async (value: string) => `hash:${value}`;

  it("applies through the adapter and records autosave state", async () => {
    const field = controlledAdapter("原稿", "autosave");
    const manager = new AIEditTransactionManager({
      sha256: digest,
      uuid: () => "transaction-1",
      now: () => Date.parse("2026-08-25T10:00:00.000Z"),
    });

    const result = await manager.apply({
      adapter: field.adapter,
      operation: "replace-selection",
      nextValue: "修订稿",
      sourceValueSha256: "hash:原稿",
      agentId: "ai-novel-writer",
      sessionId: "session-1",
      selectionId: "selection-1",
      novelId: "novel-1",
      documentId: "document-1",
      afterSelection: { startUtf16: 0, endUtf16: 3, direction: "forward" },
    });

    expect(result.ok).toBe(true);
    expect(result.ok && result.persistenceWarning).toBe(false);
    expect(field.value()).toBe("修订稿");
    expect(field.apply).toHaveBeenCalledOnce();
    expect(field.focus).toHaveBeenCalledOnce();
    expect(field.restored()).toEqual({ startUtf16: 0, endUtf16: 3, direction: "forward" });
    expect(manager.latest("chapter.body")).toMatchObject({
      transactionId: "transaction-1",
      beforeValue: "原稿",
      afterValue: "修订稿",
      persistence: "autosave",
      persistenceStatus: "autosave-requested",
    });
  });

  it("keeps explicit-save edits dirty without invoking a save action", async () => {
    const field = controlledAdapter("旧标题", "explicit-save");
    const manager = new AIEditTransactionManager({ sha256: digest, uuid: () => "t-2" });
    const result = await manager.apply({
      adapter: field.adapter,
      operation: "replace-selection",
      nextValue: "新标题",
      sourceValueSha256: "hash:旧标题",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
    });

    expect(result.ok && result.transaction.persistenceStatus).toBe("dirty-explicit-save");
    expect(field.adapter.getDirty()).toBe(true);
  });

  it("keeps an undoable transaction when persistence scheduling fails after controlled apply", async () => {
    let value = "原稿";
    const adapter: EditableFieldAdapter = {
      id: "chapter.body",
      label: "正文",
      persistence: "autosave",
      undoPolicy: "ai-transaction",
      getValue: () => value,
      applyValue: (nextValue) => {
        value = nextValue;
        throw new Error("autosave scheduler unavailable");
      },
      getSelection: () => null,
      focus: vi.fn(),
      getDirty: () => true,
      dispose: () => undefined,
    };
    const manager = new AIEditTransactionManager({
      sha256: digest,
      uuid: () => "transaction-warning",
    });

    const result = await manager.apply({
      adapter,
      operation: "replace-selection",
      nextValue: "AI 修订稿",
      sourceValueSha256: "hash:原稿",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
    });

    expect(result).toMatchObject({ ok: true, persistenceWarning: true });
    expect(manager.latest(adapter.id)).toMatchObject({
      beforeValue: "原稿",
      afterValue: "AI 修订稿",
    });
  });

  it("does not call the adapter when the complete source hash conflicts", async () => {
    const field = controlledAdapter("作者刚改过");
    const manager = new AIEditTransactionManager({ sha256: digest });

    await expect(manager.apply({
      adapter: field.adapter,
      operation: "replace-selection",
      nextValue: "AI 候选",
      sourceValueSha256: "hash:旧值",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
    })).resolves.toEqual({ ok: false, reason: "source-conflict" });
    expect(field.apply).not.toHaveBeenCalled();
    expect(field.value()).toBe("作者刚改过");
  });

  it("rechecks the getter after asynchronous hashing", async () => {
    const field = controlledAdapter("原值");
    let release!: (value: string) => void;
    const sha256 = () => new Promise<string>((resolve) => { release = resolve; });
    const manager = new AIEditTransactionManager({ sha256 });
    const pending = manager.apply({
      adapter: field.adapter,
      operation: "replace-selection",
      nextValue: "AI 候选",
      sourceValueSha256: "hash:原值",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
    });
    field.authorChange("作者输入");
    release("hash:原值");

    await expect(pending).resolves.toEqual({ ok: false, reason: "concurrent-change" });
    expect(field.apply).not.toHaveBeenCalled();
    expect(field.value()).toBe("作者输入");
  });

  it("undoes through the same adapter and then consumes the transaction", async () => {
    let sequence = 0;
    const field = controlledAdapter("原稿", "autosave");
    const manager = new AIEditTransactionManager({
      sha256: digest,
      uuid: () => `t-${++sequence}`,
    });
    await manager.apply({
      adapter: field.adapter,
      operation: "replace-selection",
      nextValue: "修订稿",
      sourceValueSha256: "hash:原稿",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
      afterSelection: { startUtf16: 0, endUtf16: 3, direction: "forward" },
    });

    const undone = await manager.undo(field.adapter);
    expect(undone.ok).toBe(true);
    expect(undone.ok && undone.persistenceWarning).toBe(false);
    expect(field.value()).toBe("原稿");
    expect(field.apply).toHaveBeenCalledTimes(2);
    expect(manager.latest("chapter.body")).toBeUndefined();
    await expect(manager.undo(field.adapter)).resolves.toEqual({
      ok: false,
      reason: "nothing-to-undo",
    });
  });

  it("refuses undo after the author changes the applied value", async () => {
    const field = controlledAdapter("原稿");
    const manager = new AIEditTransactionManager({ sha256: digest });
    await manager.apply({
      adapter: field.adapter,
      operation: "replace-selection",
      nextValue: "AI 修订稿",
      sourceValueSha256: "hash:原稿",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
    });
    field.authorChange("作者在 AI 稿上继续修改");

    await expect(manager.undo(field.adapter)).resolves.toEqual({
      ok: false,
      reason: "field-changed",
    });
    expect(field.value()).toBe("作者在 AI 稿上继续修改");
    expect(manager.latest("chapter.body")).toBeDefined();
  });
});
