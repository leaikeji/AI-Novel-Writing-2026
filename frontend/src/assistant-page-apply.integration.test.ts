import { describe, expect, it, vi } from "vitest";

import { createAssistantBodyFieldAdapter } from "./assistant-body-field";
import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import { createAssistantFormFieldAdapter } from "./assistant-form-field";
import { AssistantSelectionRegistry } from "./assistant-selection-registry";
import {
  AssistantProposalCoordinator,
  createAssistantToolCardModel,
  type AssistantProposalCardState,
} from "./assistant-tool-card";
import { AIEditTransactionManager } from "./assistant-transactions";


const SESSION_ID = "session-1";
const DOCUMENT_ID = "document-1";


async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


function runtime(): NovelAssistantContextRuntime {
  const value = new NovelAssistantContextRuntime();
  value.setHostBinding("ai-novel-writer", SESSION_ID);
  return value;
}


function mountEnvelope(contextRuntime: NovelAssistantContextRuntime, fieldId: string) {
  const scope = contextRuntime.mountScope({
    id: `page:${fieldId}`,
    kind: "page",
    persistenceBaseline: fieldId === "chapter.body"
      ? { kind: "draft", version: 4 }
      : { kind: "entity", version: 4 },
    envelope: {
      agentId: "ai-novel-writer",
      novel: { id: "novel-1", title: "潮声替我说晚安" },
      page: { section: "chapters", view: "chapter-editor" },
      entity: { type: "document", id: DOCUMENT_ID, title: "退回的旧木盒" },
      document: {
        id: DOCUMENT_ID,
        volumeId: "volume-1",
        kind: "chapter",
        chapterNumber: 4,
        title: "退回的旧木盒",
        draftVersion: 4,
        savedContentHash: "a".repeat(64),
        dirty: false,
      },
    },
  });
  scope.setFocusedField(undefined);
  return scope;
}


async function prepareSelection(options: {
  runtime: NovelAssistantContextRuntime;
  registry: AssistantSelectionRegistry;
  scope: ReturnType<typeof mountEnvelope>;
  fieldId: string;
  fieldValue: string;
  startUtf16: number;
  endUtf16: number;
  operation?: "polish" | "rewrite";
}) {
  const currentRevision = options.runtime.getStatus().contextRevision;
  const record = await options.registry.create({
    agentId: "ai-novel-writer",
    sessionId: SESSION_ID,
    novelId: "novel-1",
    documentId: DOCUMENT_ID,
    fieldId: options.fieldId,
    contextRevision: currentRevision + 1,
    fieldValue: options.fieldValue,
    startUtf16: options.startUtf16,
    endUtf16: options.endUtf16,
    direction: "forward",
  });
  options.scope.setSelection({
    id: record.selectionId,
    fieldId: record.fieldId,
    text: record.text,
    startUtf16: record.startUtf16,
    endUtf16: record.endUtf16,
    direction: record.direction,
    before: options.fieldValue.slice(0, record.startUtf16),
    after: options.fieldValue.slice(record.endUtf16),
    sourceValueSha256: record.sourceValueSha256,
    contextRevision: record.contextRevision,
    createdAt: new Date(record.createdAtMs).toISOString(),
    expiresAt: new Date(record.expiresAtMs).toISOString(),
  });
  return {
    record,
    model: createAssistantToolCardModel({
      sessionId: SESSION_ID,
      messageId: "message-1",
      result: {
        schema_version: 1,
        selection_id: record.selectionId,
        operation: options.operation ?? "polish",
        replacement_text: "潮声抵岸",
        short_summary: "增强画面感",
        replacement_character_count: 1,
        warnings: [],
      },
    }),
  };
}


function coordinator(
  contextRuntime: NovelAssistantContextRuntime,
  registry: AssistantSelectionRegistry,
) {
  return new AssistantProposalCoordinator({
    runtime: contextRuntime,
    registry,
    transactions: new AIEditTransactionManager(),
  });
}


describe("assistant proposal page apply integration", () => {
  it("replaces only the chapter selection, requests autosave, then undoes through the same adapter", async () => {
    const contextRuntime = runtime();
    const registry = new AssistantSelectionRegistry();
    const scope = mountEnvelope(contextRuntime, "chapter.body");
    let value = "木门后的潮声渐近";
    const autosaves: string[] = [];
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => value,
      getDirty: () => value !== "木门后的潮声渐近",
      getSelection: () => null,
      hashValue: sha256,
      applyEditorContent: (next) => {
        value = next;
        scope.notifyFieldChanged("chapter.body");
      },
      scheduleAutosave: (next) => { autosaves.push(next); },
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    scope.registerField(adapter);
    scope.setFocusedField(adapter.id);
    const prepared = await prepareSelection({
      runtime: contextRuntime,
      registry,
      scope,
      fieldId: adapter.id,
      fieldValue: value,
      startUtf16: 4,
      endUtf16: 8,
    });
    const proposals = coordinator(contextRuntime, registry);

    await expect(proposals.inspect(prepared.model)).resolves.toMatchObject({
      phase: "ready",
      applicable: true,
      fieldLabel: "正文",
      originalCharacterCount: 4,
    });
    const applied = await proposals.apply(prepared.model, "replace-selection");

    expect(applied).toMatchObject({
      phase: "applied",
      canUndo: true,
      statusMessage: "已应用，正在自动保存",
    });
    expect(value).toBe("木门后的潮声抵岸");
    expect(autosaves).toEqual(["木门后的潮声抵岸"]);

    const undone = await proposals.undo(prepared.model, applied);
    expect(undone).toMatchObject({
      phase: "undone",
      canUndo: false,
      statusMessage: "已撤销 AI 修改，正在自动保存",
    });
    expect(value).toBe("木门后的潮声渐近");
    expect(autosaves).toEqual(["木门后的潮声抵岸", "木门后的潮声渐近"]);
  });

  it("inserts after a selection without deleting the original text", async () => {
    const contextRuntime = runtime();
    const registry = new AssistantSelectionRegistry();
    const scope = mountEnvelope(contextRuntime, "chapter.body");
    let value = "甲乙丙丁";
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => value,
      getDirty: () => true,
      getSelection: () => null,
      hashValue: sha256,
      applyEditorContent: (next) => {
        value = next;
        scope.notifyFieldChanged("chapter.body");
      },
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    scope.registerField(adapter);
    scope.setFocusedField(adapter.id);
    const prepared = await prepareSelection({
      runtime: contextRuntime,
      registry,
      scope,
      fieldId: adapter.id,
      fieldValue: value,
      startUtf16: 1,
      endUtf16: 3,
    });

    await coordinator(contextRuntime, registry).apply(
      prepared.model,
      "insert-after-selection",
    );
    expect(value).toBe("甲乙丙潮声抵岸丁");
  });

  it("keeps title proposals dirty and never invokes the page save action", async () => {
    const contextRuntime = runtime();
    const registry = new AssistantSelectionRegistry();
    const scope = mountEnvelope(contextRuntime, "chapter.title");
    const baseline = "退回的旧木盒";
    let value = baseline;
    let dirty = false;
    const save = vi.fn();
    const adapter = createAssistantFormFieldAdapter({
      id: "chapter.title",
      label: "章节标题",
      getValue: () => value,
      getDirty: () => dirty,
      getSelection: () => null,
      hashValue: sha256,
      applyDraftValue: (next) => {
        value = next;
        scope.notifyFieldChanged("chapter.title");
      },
      markDirty: () => { dirty = true; },
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    scope.registerField(adapter);
    scope.setFocusedField(adapter.id);
    const prepared = await prepareSelection({
      runtime: contextRuntime,
      registry,
      scope,
      fieldId: adapter.id,
      fieldValue: value,
      startUtf16: 0,
      endUtf16: value.length,
      operation: "rewrite",
    });

    const applied = await coordinator(contextRuntime, registry).apply(
      prepared.model,
      "replace-selection",
    );

    expect(value).toBe("潮声抵岸");
    expect(dirty).toBe(true);
    expect(save).not.toHaveBeenCalled();
    expect(applied).toMatchObject({
      phase: "applied",
      persistence: "explicit-save",
      statusMessage: "已应用到章节标题草稿，尚未保存",
    });
  });

  it("fails closed after author edits, session switches, or selection is discarded", async () => {
    const contextRuntime = runtime();
    const registry = new AssistantSelectionRegistry();
    const scope = mountEnvelope(contextRuntime, "chapter.body");
    let value = "潮声渐近";
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => value,
      getDirty: () => true,
      getSelection: () => null,
      hashValue: sha256,
      applyEditorContent: (next) => { value = next; },
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    scope.registerField(adapter);
    scope.setFocusedField(adapter.id);
    const prepared = await prepareSelection({
      runtime: contextRuntime,
      registry,
      scope,
      fieldId: adapter.id,
      fieldValue: value,
      startUtf16: 0,
      endUtf16: 2,
    });
    const proposals = coordinator(contextRuntime, registry);

    value = "作者刚刚改过";
    await expect(proposals.inspect(prepared.model)).resolves.toMatchObject({
      phase: "conflict",
      applicable: false,
      statusMessage: "字段内容已变化，只能复制候选",
    });
    expect(value).toBe("作者刚刚改过");

    contextRuntime.setHostBinding("ai-novel-writer", "session-2");
    await expect(proposals.inspect(prepared.model)).resolves.toMatchObject({
      phase: "conflict",
      statusMessage: "当前 Agent 或会话已变化，只能复制候选",
    });

    const discarded = proposals.discard(prepared.model, {
      phase: "conflict",
      applicable: false,
      canUndo: false,
      statusMessage: "冲突",
    } satisfies AssistantProposalCardState);
    expect(discarded).toMatchObject({ phase: "discarded", applicable: false });
    expect(registry.get(prepared.record.selectionId)).toBeUndefined();
  });

  it("fails closed when full-hash validation throws", async () => {
    const contextRuntime = runtime();
    const registry = new AssistantSelectionRegistry();
    const scope = mountEnvelope(contextRuntime, "chapter.body");
    let value = "潮声渐近";
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body",
      label: "正文",
      getValue: () => value,
      getDirty: () => false,
      getSelection: () => null,
      hashValue: sha256,
      applyEditorContent: (next) => { value = next; },
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    scope.registerField(adapter);
    scope.setFocusedField(adapter.id);
    const prepared = await prepareSelection({
      runtime: contextRuntime,
      registry,
      scope,
      fieldId: adapter.id,
      fieldValue: value,
      startUtf16: 0,
      endUtf16: 2,
    });
    vi.spyOn(registry, "validateForApply").mockRejectedValue(
      new Error("crypto unavailable"),
    );
    const proposals = coordinator(contextRuntime, registry);

    await expect(proposals.inspect(prepared.model)).resolves.toMatchObject({
      phase: "failed",
      applicable: false,
      statusMessage: "候选校验失败，未修改页面内容；仍可复制候选",
    });
    await expect(
      proposals.apply(prepared.model, "replace-selection"),
    ).resolves.toMatchObject({
      phase: "failed",
      applicable: false,
      statusMessage: "应用前校验失败，未修改页面内容；仍可复制候选",
    });
    expect(value).toBe("潮声渐近");
  });
});
