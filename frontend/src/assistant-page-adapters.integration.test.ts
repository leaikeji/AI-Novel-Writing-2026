import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import type { AIApplyMeta } from "./assistant-fields";
import type * as ChapterWorkflowAdapters from "./chapter-workflow";


let adapters: typeof ChapterWorkflowAdapters;


const NOVEL = { id: "novel-1", title: "潮声替我说晚安" };


function location(documentId = "document-1") {
  return {
    novel: NOVEL,
    document: {
      id: documentId,
      volume_id: "volume-1",
      kind: "chapter" as const,
      title: "退回的旧木盒",
      version: 4,
      draft_version: 9,
      content_hash: "a".repeat(64),
    },
    chapterNumber: 4,
    dirty: false,
  };
}


function runtime(): NovelAssistantContextRuntime {
  const value = new NovelAssistantContextRuntime();
  value.setHostBinding("ai-novel-writer", "session-1");
  return value;
}


async function meta(value: string): Promise<AIApplyMeta> {
  return {
    transactionId: "transaction-1",
    agentId: "ai-novel-writer",
    sessionId: "session-1",
    operation: "replace",
    sourceValueSha256: await adapters.hashAssistantFieldValue(value),
    appliedAt: "2026-08-25T10:00:00.000Z",
  };
}


beforeAll(async () => {
  const Component = Object.assign(() => null, { TextArea: () => null });
  const components = new Proxy({ Input: Component }, {
    get: (target, key) => key === "Input" ? target.Input : Component,
  });
  vi.stubGlobal("window", {
    QwenPaw: {
      host: {
        React: { createElement: () => null },
        ReactDOM: {},
        antd: components,
        antdIcons: new Proxy({}, { get: () => Component }),
      },
    },
  });
  adapters = await import("./chapter-workflow");
});


afterAll(() => vi.unstubAllGlobals());


describe("real chapter page assistant adapters", () => {
  it("uses UTF-16 ranges, bounded context and full WebCrypto SHA-256", async () => {
    const value = `${"前".repeat(1_600)}😀选中${"后".repeat(1_600)}`;
    const start = 1_600;
    const end = start + "😀选中".length;
    const control = {
      selectionStart: start,
      selectionEnd: end,
      selectionDirection: "backward",
      focus: vi.fn(),
      setSelectionRange: vi.fn(),
    };

    const selection = adapters.readAssistantTextSelection(control, value);

    expect(selection).toMatchObject({
      startUtf16: start,
      endUtf16: end,
      direction: "backward",
      text: "😀选中",
    });
    expect(selection?.before).toHaveLength(1_500);
    expect(selection?.after).toHaveLength(1_500);
    expect(await adapters.hashAssistantFieldValue("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("mounts chapter.body with live state, invalidates selection and requests the existing autosave", async () => {
    const contextRuntime = runtime();
    let body = "潮声渐近";
    const autosaves: string[] = [];
    const binding = adapters.mountChapterBodyAssistantScope({
      runtime: contextRuntime,
      location: location(),
      getValue: () => body,
      getDirty: () => body !== "潮声渐近",
      getSelection: () => null,
      applyEditorContent: (nextValue) => { body = nextValue; },
      scheduleAutosave: (nextValue) => { autosaves.push(nextValue); },
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    const revision = contextRuntime.getStatus().contextRevision;
    const selectionCreatedAt = Date.now();
    binding.scope.setSelection({
      id: "123e4567-e89b-42d3-a456-426614174000",
      fieldId: adapters.CHAPTER_BODY_FIELD_ID,
      text: "潮声",
      startUtf16: 0,
      endUtf16: 2,
      direction: "forward",
      before: "",
      after: "渐近",
      sourceValueSha256: await adapters.hashAssistantFieldValue(body),
      contextRevision: revision,
      createdAt: new Date(selectionCreatedAt).toISOString(),
      expiresAt: new Date(selectionCreatedAt + 5 * 60 * 1_000).toISOString(),
    });

    const receipt = await binding.adapter.applyValueWithReceipt("潮声抵岸", await meta(body));
    const capture = contextRuntime.capture();

    expect(receipt).toMatchObject({ persistence: "autosave", autosaveRequested: true });
    expect(body).toBe("潮声抵岸");
    expect(autosaves).toEqual(["潮声抵岸"]);
    expect(capture?.context).toMatchObject({
      novel: NOVEL,
      page: { section: "chapters", view: "chapter-editor" },
      document: {
        id: "document-1",
        volumeId: "volume-1",
        chapterNumber: 4,
        draftVersion: 9,
        savedContentHash: "a".repeat(64),
        dirty: false,
      },
      editing: {
        fields: [{ id: "chapter.body", value: "潮声抵岸", dirty: true, persistence: "autosave" }],
      },
    });
    expect(capture?.context.selection).toBeUndefined();

    const replacement = adapters.mountChapterBodyAssistantScope({
      runtime: contextRuntime,
      location: location("document-2"),
      getValue: () => "第二章",
      getDirty: () => false,
      getSelection: () => null,
      applyEditorContent: vi.fn(),
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    expect(contextRuntime.capture()?.context.document?.id).toBe("document-2");
    expect(() => binding.adapter.getValue()).toThrow("disposed");
    replacement.dispose();
    expect(contextRuntime.getStatus().active).toBe(false);
  });

  it("keeps title AI edits dirty and explicit-save, then restores the page scope on close", async () => {
    const contextRuntime = runtime();
    let body = "正文";
    const page = adapters.mountChapterBodyAssistantScope({
      runtime: contextRuntime,
      location: location(),
      getValue: () => body,
      getDirty: () => false,
      getSelection: () => null,
      applyEditorContent: (next) => { body = next; },
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    const baseline = "旧木盒";
    let title = baseline;
    const dirtyMarks: string[] = [];
    const modal = adapters.mountChapterTitleAssistantScope({
      runtime: contextRuntime,
      location: location(),
      getValue: () => title,
      getDirty: () => title !== baseline,
      getSelection: () => null,
      applyDraftValue: (next) => { title = next; },
      markDirty: (fieldId) => { dirtyMarks.push(fieldId); },
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });

    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "modal",
      modal: "title-editor",
      fieldCount: 1,
    });
    const receipt = await modal.adapters.applyValueWithReceipt("潮声里的旧木盒", await meta(title));
    expect(receipt).toMatchObject({ persistence: "explicit-save", saveRequested: false });
    expect(title).toBe("潮声里的旧木盒");
    expect(dirtyMarks).toEqual(["chapter.title"]);
    expect(contextRuntime.capture()?.context.editing?.fields[0]).toMatchObject({
      id: "chapter.title",
      dirty: true,
      persistence: "explicit-save",
    });

    modal.dispose();
    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "page",
      view: "chapter-editor",
      fieldCount: 1,
    });
    page.dispose();
  });

  it("registers every outline field as explicit-save and destroys them when the modal closes", async () => {
    const contextRuntime = runtime();
    const page = adapters.mountChapterBodyAssistantScope({
      runtime: contextRuntime,
      location: location(),
      getValue: () => "正文",
      getDirty: () => false,
      getSelection: () => null,
      applyEditorContent: vi.fn(),
      scheduleAutosave: vi.fn(),
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    const baseline: ChapterWorkflowAdapters.BriefFormState = {
      targetWordCount: 2_500,
      expectationText: "",
      outlineText: "旧章纲",
      forbiddenText: "",
      requiredRoles: "",
      allowedRoles: "",
      contextOnlyRoles: "",
      forbiddenRoles: "",
    };
    let form = { ...baseline };
    const dirtyMarks: string[] = [];
    const modal = adapters.mountChapterOutlineAssistantScope({
      runtime: contextRuntime,
      location: location(),
      getPersistenceVersion: () => 3,
      getForm: () => form,
      getBaseline: () => baseline,
      getSelection: () => null,
      applyField: (field, value) => { form = { ...form, [field]: value }; },
      markDirty: (fieldId) => { dirtyMarks.push(fieldId); },
      restoreSelection: vi.fn(),
      focus: vi.fn(),
    });
    const expectedIds = Object.values(adapters.CHAPTER_OUTLINE_FIELD_IDS).sort();
    const capture = contextRuntime.capture();

    expect(capture?.context.page).toEqual({
      section: "chapters",
      view: "chapter-editor",
      modal: "chapter-outline-editor",
    });
    expect(capture?.context.editing?.fields.map((field) => field.id).sort()).toEqual(expectedIds);
    expect(capture?.context.editing?.fields.every((field) => field.persistence === "explicit-save")).toBe(true);

    const outline = modal.adapters[adapters.CHAPTER_OUTLINE_FIELD_IDS.outlineText];
    const target = modal.adapters[adapters.CHAPTER_OUTLINE_FIELD_IDS.targetCharacters];
    const required = modal.adapters[adapters.CHAPTER_OUTLINE_FIELD_IDS.requiredRoles];
    await outline.applyValue("新章纲", await meta(outline.getValue()));
    await target.applyValue("3200", await meta(target.getValue()));
    await required.applyValue("林夏、周野", await meta(required.getValue()));

    expect(form).toMatchObject({
      outlineText: "新章纲",
      targetWordCount: 3_200,
      requiredRoles: "林夏、周野",
    });
    expect(contextRuntime.getStatus().dirtyFieldCount).toBe(3);
    expect(dirtyMarks).toEqual([
      adapters.CHAPTER_OUTLINE_FIELD_IDS.outlineText,
      adapters.CHAPTER_OUTLINE_FIELD_IDS.targetCharacters,
      adapters.CHAPTER_OUTLINE_FIELD_IDS.requiredRoles,
    ]);

    modal.dispose();
    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "page",
      fieldCount: 1,
    });
    expect(() => outline.getValue()).toThrow("disposed");
    page.dispose();
  });
});
