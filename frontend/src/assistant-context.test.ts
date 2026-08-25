import { describe, expect, it } from "vitest";

import {
  NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS,
  NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS,
  NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
  NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS,
  type NovelAssistantContextV2,
  validateNovelAssistantContextV2,
} from "./assistant-context-schema";
import { NovelAssistantContextStore } from "./assistant-context-store";
import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import type { AIApplyMeta, EditableFieldAdapter } from "./assistant-fields";


function validContext(): NovelAssistantContextV2 {
  return {
    schemaVersion: 2,
    contextRevision: 7,
    capturedAt: "2026-08-25T10:00:00.000Z",
    expiresAt: "2026-08-25T10:10:00.000Z",
    agentId: "ai-novel-writer",
    sessionId: "session-1",
    novel: { id: "novel-1", title: "潮声替我说晚安" },
    page: {
      section: "chapters",
      view: "chapter-editor",
      modal: "chapter-outline-editor",
    },
    entity: { type: "document", id: "document-1", title: "退回的旧木盒" },
    document: {
      id: "document-1",
      volumeId: "volume-2",
      kind: "chapter",
      chapterNumber: 4,
      title: "退回的旧木盒",
      draftVersion: 9,
      savedContentHash: "a".repeat(64),
      dirty: true,
    },
    editing: {
      focusedFieldId: "chapter.outline",
      fields: [
        {
          id: "chapter.body",
          label: "正文",
          value: "苏晚推开木门。",
          dirty: false,
          truncated: false,
          characterCount: 8,
          persistence: "autosave",
        },
        {
          id: "chapter.outline",
          label: "章节大纲",
          value: "旧木盒将线索引向废弃广播站。",
          dirty: true,
          truncated: false,
          characterCount: 16,
          persistence: "explicit-save",
        },
      ],
    },
    selection: {
      id: "selection-1",
      fieldId: "chapter.outline",
      text: "废弃广播站",
      startUtf16: 8,
      endUtf16: 14,
      direction: "forward",
      before: "旧木盒将线索引向",
      after: "。",
      sourceValueSha256: "b".repeat(64),
      contextRevision: 7,
      createdAt: "2026-08-25T10:00:01.000Z",
      expiresAt: "2026-08-25T10:10:01.000Z",
    },
    budget: {
      maxCharacters: NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS,
      usedCharacters: 1_200,
      truncated: false,
      omittedFieldIds: [],
    },
  };
}


describe("NovelAssistantContextV2 frozen wire contract", () => {
  it("accepts a complete chapter modal snapshot without coercion", () => {
    const context = validContext();
    const result = validateNovelAssistantContextV2(context);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.context).toBe(context);
      expect(JSON.parse(result.serialized)).toEqual(context);
    }
  });

  it.each([
    ["section", { section: "billing", view: "chapter-editor" }, "invalid-page"],
    ["view", { section: "chapters", view: "unknown-editor" }, "invalid-page"],
    ["entity", { type: "invoice", id: "1" }, "invalid-entity"],
  ])("rejects an unfrozen %s enum", (_label, value, reason) => {
    const context = validContext() as unknown as Record<string, any>;
    if (_label === "entity") context.entity = value;
    else context.page = value;

    expect(validateNovelAssistantContextV2(context)).toEqual({ ok: false, reason });
  });

  it("rejects duplicate fields and a focus target outside the registry", () => {
    const duplicate = validContext();
    duplicate.editing!.fields.push({ ...duplicate.editing!.fields[0] });
    expect(validateNovelAssistantContextV2(duplicate)).toEqual({
      ok: false,
      reason: "invalid-editing",
    });

    const missingFocus = validContext();
    missingFocus.editing!.focusedFieldId = "character.name";
    expect(validateNovelAssistantContextV2(missingFocus)).toEqual({
      ok: false,
      reason: "invalid-editing",
    });
  });

  it("enforces selection size, context, revision, hash, and lifetime", () => {
    const cases: NovelAssistantContextV2[] = [];

    const oversizedText = validContext();
    oversizedText.selection!.text = "x".repeat(NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS + 1);
    cases.push(oversizedText);

    const oversizedBefore = validContext();
    oversizedBefore.selection!.before = "x".repeat(
      NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS + 1,
    );
    cases.push(oversizedBefore);

    const staleRevision = validContext();
    staleRevision.selection!.contextRevision -= 1;
    cases.push(staleRevision);

    const badHash = validContext();
    badHash.selection!.sourceValueSha256 = "not-a-sha256";
    cases.push(badHash);

    const longLived = validContext();
    longLived.selection!.expiresAt = new Date(
      Date.parse(longLived.selection!.createdAt) + NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS + 1,
    ).toISOString();
    cases.push(longLived);

    for (const context of cases) {
      expect(validateNovelAssistantContextV2(context)).toEqual({
        ok: false,
        reason: "invalid-selection",
      });
    }
  });

  it("rejects a context lifetime beyond twenty minutes", () => {
    const context = validContext();
    context.expiresAt = new Date(
      Date.parse(context.capturedAt) + NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS + 1,
    ).toISOString();

    expect(validateNovelAssistantContextV2(context)).toEqual({
      ok: false,
      reason: "invalid-time-window",
    });
  });

  it("rejects a serialized envelope above the global 24k budget", () => {
    const context = validContext();
    context.editing!.fields[0].value = "x".repeat(NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS);

    expect(validateNovelAssistantContextV2(context)).toEqual({
      ok: false,
      reason: "oversized",
    });
  });
});


function fieldAdapter(options: {
  id: string;
  label?: string;
  value: () => string;
  dirty?: () => boolean;
  persistence?: "autosave" | "explicit-save";
  onDispose?: () => void;
}): EditableFieldAdapter {
  return {
    id: options.id,
    label: options.label ?? options.id,
    persistence: options.persistence ?? "explicit-save",
    undoPolicy: "ai-transaction",
    getValue: options.value,
    applyValue: (_next: string, _meta: AIApplyMeta) => undefined,
    getSelection: () => null,
    focus: () => undefined,
    getDirty: options.dirty ?? (() => false),
    dispose: options.onDispose ?? (() => undefined),
  };
}


function contextStore(now: () => number = () => Date.parse("2026-08-25T10:00:00.000Z")) {
  return new NovelAssistantContextStore({
    agentId: "ai-novel-writer",
    sessionId: "session-1",
    now,
    envelope: {
      agentId: "ai-novel-writer",
      novel: { id: "novel-1", title: "潮声替我说晚安" },
      page: { section: "chapters", view: "chapter-editor" },
      entity: { type: "document", id: "document-1", title: "退回的旧木盒" },
      document: {
        id: "document-1",
        volumeId: "volume-2",
        kind: "chapter",
        chapterNumber: 4,
        title: "退回的旧木盒",
        draftVersion: 9,
        savedContentHash: "a".repeat(64),
        dirty: false,
      },
    },
  });
}


describe("NovelAssistantContextStore", () => {
  it("keeps live getters and materialises an immutable value only at capture", () => {
    let body = "第一稿";
    const store = contextStore();
    store.registerField(fieldAdapter({
      id: "chapter.body",
      label: "正文",
      value: () => body,
      dirty: () => true,
      persistence: "autosave",
    }));

    body = "发送前的最新稿";
    const first = store.capture();
    body = "发送后又修改";

    expect(first.context.editing?.fields[0].value).toBe("发送前的最新稿");
    expect(first.serialized).not.toContain("发送后又修改");
    expect(first.context.budget.usedCharacters).toBe(first.serialized.length);
  });

  it("increments revisions and invalidates a selection when its field changes", () => {
    const store = contextStore();
    store.registerField(fieldAdapter({ id: "chapter.body", value: () => "潮声渐近" }));
    const beforeSelection = store.getStatus().contextRevision;
    store.setSelection({
      id: "selection-1",
      fieldId: "chapter.body",
      text: "潮声",
      startUtf16: 0,
      endUtf16: 2,
      direction: "forward",
      before: "",
      after: "渐近",
      sourceValueSha256: "b".repeat(64),
      contextRevision: 0,
      createdAt: "2026-08-25T09:59:59.000Z",
      expiresAt: "2026-08-25T10:10:00.000Z",
    });

    expect(store.getStatus().contextRevision).toBe(beforeSelection + 1);
    expect(store.getStatus().selectionCharacters).toBe(2);
    expect(store.capture().context.selection?.contextRevision).toBe(
      store.getStatus().contextRevision,
    );

    store.notifyFieldChanged("chapter.body");
    expect(store.getStatus().selectionCharacters).toBe(0);
    expect(store.capture().context.selection).toBeUndefined();
  });

  it("does not duplicate selected text inside the selected field snapshot", () => {
    const store = contextStore();
    store.registerField(fieldAdapter({
      id: "chapter.body",
      label: "正文",
      value: () => "木门后的潮声渐近",
      dirty: () => true,
      persistence: "autosave",
    }));
    store.setFocusedField("chapter.body");
    store.setSelection({
      id: "selection-1",
      fieldId: "chapter.body",
      text: "潮声渐近",
      startUtf16: 4,
      endUtf16: 8,
      direction: "forward",
      before: "木门后的",
      after: "",
      sourceValueSha256: "c".repeat(64),
      contextRevision: 0,
      createdAt: "2026-08-25T09:59:59.000Z",
      expiresAt: "2026-08-25T10:10:00.000Z",
    });

    const snapshot = store.capture().context;
    expect(snapshot.selection?.text).toBe("潮声渐近");
    expect(snapshot.editing?.fields[0]).toMatchObject({
      id: "chapter.body",
      value: "",
      truncated: true,
      characterCount: 8,
    });
    expect(snapshot.budget.truncated).toBe(true);
  });

  it("prioritises the focused dirty field and keeps the final wire value under 24k", () => {
    const store = contextStore();
    store.registerField(fieldAdapter({
      id: "outline.focused",
      value: () => "甲".repeat(20_000),
      dirty: () => true,
    }));
    store.registerField(fieldAdapter({
      id: "outline.other",
      value: () => "乙".repeat(20_000),
      dirty: () => true,
    }));
    store.setFocusedField("outline.focused");

    const { context, serialized } = store.capture();
    const focused = context.editing?.fields.find((field) => field.id === "outline.focused");
    const other = context.editing?.fields.find((field) => field.id === "outline.other");

    expect(serialized.length).toBeLessThanOrEqual(NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS);
    expect(focused?.value.length).toBeGreaterThan(other?.value.length ?? 0);
    expect(context.budget.truncated).toBe(true);
    expect(validateNovelAssistantContextV2(context).ok).toBe(true);
  });

  it("expires selections and destroys old adapters on location replacement", () => {
    let now = Date.parse("2026-08-25T10:00:00.000Z");
    let disposed = 0;
    const store = contextStore(() => now);
    const registration = store.registerField(fieldAdapter({
      id: "character.name",
      value: () => "苏晚",
      onDispose: () => { disposed += 1; },
    }));
    store.setSelection({
      id: "selection-1",
      fieldId: "character.name",
      text: "苏晚",
      startUtf16: 0,
      endUtf16: 2,
      direction: "none",
      before: "",
      after: "",
      sourceValueSha256: "d".repeat(64),
      contextRevision: 0,
      createdAt: "2026-08-25T10:00:00.000Z",
      expiresAt: "2026-08-25T10:00:10.000Z",
    });
    now += 10_001;
    expect(store.expireSelection()).toBe(true);

    store.replaceLocation({
      agentId: "ai-novel-writer",
      novel: { id: "novel-2", title: "雾岭守灯人" },
      page: { section: "roles", view: "character-list" },
      entity: { type: "novel", id: "novel-2", title: "雾岭守灯人" },
    });
    expect(disposed).toBe(1);
    expect(store.getStatus().fieldCount).toBe(0);
    expect(store.capture().context.novel.id).toBe("novel-2");

    registration.dispose();
    expect(disposed).toBe(1);
  });
});


describe("NovelAssistantContextRuntime", () => {
  const envelope = (view: "chapter-editor" | "title-editor") => ({
    agentId: "ai-novel-writer",
    novel: { id: "novel-1", title: "潮声替我说晚安" },
    page: view === "chapter-editor"
      ? { section: "chapters" as const, view }
      : { section: "chapters" as const, view: "chapter-editor" as const, modal: view },
    entity: { type: "document" as const, id: "document-1", title: "退回的旧木盒" },
  });

  it("activates a modal scope and restores the still-mounted page scope", () => {
    const runtime = new NovelAssistantContextRuntime();
    runtime.setHostBinding("ai-novel-writer", "session-1");
    const page = runtime.mountScope({
      id: "page:document-1",
      kind: "page",
      envelope: envelope("chapter-editor"),
    });
    page.registerField(fieldAdapter({ id: "chapter.body", value: () => "正文" }));
    const pageRevision = runtime.getStatus().contextRevision;

    const modal = runtime.mountScope({
      id: "modal:title:document-1",
      kind: "modal",
      envelope: envelope("title-editor"),
    });
    modal.registerField(fieldAdapter({ id: "chapter.title", value: () => "新标题" }));
    expect(runtime.getStatus()).toMatchObject({
      scopeKind: "modal",
      modal: "title-editor",
      fieldCount: 1,
    });
    const modalRevision = runtime.getStatus().contextRevision;

    modal.dispose();
    expect(runtime.getStatus()).toMatchObject({
      scopeKind: "page",
      view: "chapter-editor",
      fieldCount: 1,
    });
    expect(runtime.getStatus().contextRevision).toBeGreaterThan(modalRevision);
    expect(runtime.getStatus().contextRevision).toBeGreaterThan(pageRevision);
    expect(runtime.capture()?.context.editing?.fields[0].id).toBe("chapter.body");
  });

  it("withholds snapshots for every non-target Agent", () => {
    const runtime = new NovelAssistantContextRuntime();
    runtime.setHostBinding("default", "session-1");
    const page = runtime.mountScope({
      id: "page:document-1",
      kind: "page",
      envelope: envelope("chapter-editor"),
    });
    page.registerField(fieldAdapter({ id: "chapter.body", value: () => "不应发送" }));

    expect(runtime.getStatus().supportedAgent).toBe(false);
    expect(runtime.capture()).toBeNull();

    runtime.setHostBinding("ai-novel-writer", "session-1");
    expect(runtime.capture()?.serialized).toContain("不应发送");
  });

  it("clears every page field and modal when leaving the workbench", () => {
    const runtime = new NovelAssistantContextRuntime();
    runtime.setHostBinding("ai-novel-writer", "session-1");
    runtime.mountScope({
      id: "page:document-1",
      kind: "page",
      envelope: envelope("chapter-editor"),
    });
    runtime.mountScope({
      id: "modal:title:document-1",
      kind: "modal",
      envelope: envelope("title-editor"),
    });

    runtime.clear();
    expect(runtime.getStatus()).toMatchObject({ active: false, fieldCount: 0 });
    expect(runtime.capture()).toBeNull();
  });
});
