import { describe, expect, it, vi } from "vitest";

import {
  AssistantSelectionController,
  type AssistantSelectionAnchor,
  type AssistantSelectionControllerOptions,
  type AssistantSelectionEventTarget,
} from "./assistant-selection-controller";
import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import { AssistantSelectionRegistry } from "./assistant-selection-registry";
import type { AssistantSuggestionRegistry } from "./assistant-suggestions";
import type { EditableFieldAdapter, SelectionSnapshot } from "./assistant-fields";


const SELECTION_ID = "00000000-0000-4000-8000-000000000011";
const SHA = "a".repeat(64);


class FakeEvents implements AssistantSelectionEventTarget {
  private readonly listeners = new Map<string, Set<EventListenerOrEventListenerObject>>();

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const values = this.listeners.get(type) ?? new Set();
    values.add(listener);
    this.listeners.set(type, values);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: string, target: unknown): void {
    const event = { type, target } as Event;
    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") listener(event);
      else listener.handleEvent(event);
    }
  }

  count(type: string): number {
    return this.listeners.get(type)?.size ?? 0;
  }
}


function fakeSuggestions() {
  const definitions = new Map<string, { items: ReadonlyArray<QwenPawSuggestionItem> }>();
  const registry: AssistantSuggestionRegistry = {
    upsert: vi.fn((definition) => {
      definitions.set(definition.id, definition);
      return "registered" as const;
    }),
    remove: vi.fn((id) => definitions.delete(id)),
    clear: vi.fn(() => definitions.clear()),
    dispose: vi.fn(() => definitions.clear()),
    registeredIds: () => [...definitions.keys()],
  };
  return { registry, definitions };
}


function setup(options: {
  sessionId?: string;
  sha256?: (value: string) => Promise<string>;
  now?: () => number;
  documentTarget?: FakeEvents;
  onStartEditorTask?: AssistantSelectionControllerOptions["onStartEditorTask"];
} = {}) {
  let value = "潮声从旧木盒里传来。";
  let selection: SelectionSnapshot | null = {
    startUtf16: 0,
    endUtf16: 2,
    direction: "forward",
    text: "潮声",
    before: "",
    after: "从旧木盒里传来。",
  };
  const adapter: EditableFieldAdapter = {
    id: "chapter.body",
    label: "章节正文",
    persistence: "autosave",
    undoPolicy: "ai-transaction",
    getValue: () => value,
    applyValue: () => undefined,
    getSelection: () => selection ? { ...selection } : null,
    focus: () => undefined,
    getDirty: () => true,
    dispose: () => undefined,
  };
  const runtime = new NovelAssistantContextRuntime();
  runtime.setHostBinding("ai-novel-writer", options.sessionId);
  const scope = runtime.mountScope({
    id: "page:document-1",
    kind: "page",
    envelope: {
      agentId: "ai-novel-writer",
      novel: { id: "novel-1", title: "潮声替我说晚安" },
      page: { section: "chapters", view: "chapter-editor" },
      entity: { type: "document", id: "document-1", title: "旧木盒" },
      document: {
        id: "document-1",
        kind: "chapter",
        chapterNumber: 4,
        title: "退回的旧木盒",
        draftVersion: 3,
        savedContentHash: "b".repeat(64),
        dirty: true,
      },
    },
  });
  scope.registerField(adapter);
  scope.setFocusedField(adapter.id);
  const suggestions = fakeSuggestions();
  const registry = new AssistantSelectionRegistry({
    idProvider: () => SELECTION_ID,
    sha256: options.sha256 ?? (async () => SHA),
    now: options.now,
  });
  const onStartEditorTask = options.onStartEditorTask ?? vi.fn(
    async () => ({ jobId: "job-1" }),
  );
  const controller = new AssistantSelectionController({
    runtime,
    registry,
    suggestions: suggestions.registry,
    onStartEditorTask,
    documentTarget: options.documentTarget ?? null,
    windowTarget: null,
    getViewportRect: () => ({ left: 0, top: 0, width: 1920, height: 1080 }),
    getVisualViewportScale: () => 1,
    getDevicePixelRatio: () => 2,
    now: options.now,
  });
  const anchor: AssistantSelectionAnchor = {
    isConnected: true,
    tagName: "TEXTAREA",
    scrollLeft: 0,
    scrollTop: 12,
    scrollWidth: 900,
    clientWidth: 720,
    getBoundingClientRect: () => ({ left: 300, top: 180, width: 720, height: 480 }),
    closest: () => null,
  };
  return {
    runtime,
    scope,
    adapter,
    registry,
    controller,
    suggestions,
    onStartEditorTask,
    anchor,
    setValue(next: string) { value = next; },
    setSelection(next: SelectionSnapshot | null) { selection = next; },
  };
}


describe("assistant selection controller", () => {
  it("captures through the active adapter and starts an editor task in one click", async () => {
    const harness = setup({ sessionId: "session-1" });

    await expect(harness.controller.capture(harness.anchor)).resolves.toBe(true);
    const ready = harness.controller.getState();
    expect(ready).toMatchObject({
      phase: "ready",
      visible: true,
      selectionId: SELECTION_ID,
      fieldId: "chapter.body",
      fieldLabel: "章节正文",
      selectedCharacters: 2,
      placement: { strategy: "field-anchor", precision: "field-level" },
    });
    expect(harness.runtime.getStatus().selectionCharacters).toBe(2);

    expect(harness.controller.selectOperation("polish")).toBe(true);
    await Promise.resolve();
    await Promise.resolve();

    expect(harness.onStartEditorTask).toHaveBeenCalledWith(expect.objectContaining({
      operation: "polish",
      record: expect.objectContaining({ selectionId: SELECTION_ID }),
    }));
    expect(harness.controller.getState()).toMatchObject({ phase: "sent", visible: false });
    expect(harness.suggestions.registry.registeredIds()).toEqual([]);
    expect(harness.registry.get(SELECTION_ID)?.delivery).toEqual({
      kind: "editor-task",
      jobId: "job-1",
    });
  });

  it("does not create a suggestion or touch a clipboard-style callback on the default path", async () => {
    const start = vi.fn(async () => ({ jobId: "job-2" }));
    const harness = setup({ sessionId: "session-1", onStartEditorTask: start });
    await harness.controller.capture(harness.anchor);

    expect(harness.controller.selectOperation("polish")).toBe(true);
    await Promise.resolve();

    expect(start).toHaveBeenCalledTimes(1);
    expect(harness.suggestions.registry.registeredIds()).toEqual([]);
  });

  it("collects and validates a custom instruction before starting", async () => {
    const start = vi.fn(async () => ({ jobId: "job-custom" }));
    const harness = setup({ onStartEditorTask: start });
    await harness.controller.capture(harness.anchor);

    expect(harness.controller.selectOperation("custom")).toBe(true);
    expect(harness.controller.getState()).toMatchObject({
      phase: "customizing",
      visible: true,
    });
    expect(start).not.toHaveBeenCalled();
    expect(harness.controller.submitCustomInstruction("   ")).toBe(false);
    expect(harness.controller.submitCustomInstruction("保留事实，改成克制语气")).toBe(true);
    await Promise.resolve();
    expect(start).toHaveBeenCalledWith(expect.objectContaining({
      operation: "custom",
      customInstruction: "保留事实，改成克制语气",
    }));
  });

  it("keeps the public slash suggestion only as an explicit fallback", async () => {
    const harness = setup();
    await harness.controller.capture(harness.anchor);

    expect(harness.controller.prepareAssistantFallback(SELECTION_ID, "rewrite")).toBe(true);
    const [suggestionId] = harness.suggestions.registry.registeredIds();
    const suggestion = harness.suggestions.definitions.get(suggestionId);

    expect(suggestion?.items[0]).toMatchObject({
      label: "/rewrite-selection · 改写选区",
      value: "rewrite-selection",
    });
    expect(harness.suggestions.registry.registeredIds()).toHaveLength(1);
    expect(harness.onStartEditorTask).not.toHaveBeenCalled();
  });

  it("does not lose the logical field on blur, but invalidates after an actual field mutation", async () => {
    const harness = setup({ sessionId: "session-1" });
    const stop = harness.controller.start();
    await harness.controller.capture(harness.anchor);
    const revision = harness.runtime.getStatus().contextRevision;

    harness.scope.setFocusedField(undefined);
    expect(harness.runtime.getStatus().contextRevision).toBe(revision);
    expect(harness.controller.selectOperation("rewrite")).toBe(true);

    harness.setValue("潮声已经被作者改写。" );
    harness.scope.notifyFieldChanged("chapter.body");
    expect(harness.controller.getState()).toMatchObject({
      phase: "invalid",
      visible: false,
    });
    expect(harness.controller.selectOperation("polish")).toBe(false);
    expect(harness.registry.get(SELECTION_ID)).toBeDefined();
    stop();
  });

  it("keeps an explicitly registered fallback when the native sender receives mouse/select events", async () => {
    const events = new FakeEvents();
    const harness = setup({ sessionId: "session-1", documentTarget: events });
    const stop = harness.controller.start();
    await harness.controller.capture(harness.anchor);
    expect(harness.controller.prepareAssistantFallback(SELECTION_ID, "polish")).toBe(true);
    const registered = harness.suggestions.registry.registeredIds();

    const nativeSender: AssistantSelectionAnchor = {
      ...harness.anchor,
      getBoundingClientRect: () => ({ left: 1400, top: 900, width: 360, height: 96 }),
      closest: (selector: string) => selector === ".anw-assistant-pane" ? {} : null,
    };
    events.emit("mouseup", nativeSender);
    events.emit("select", nativeSender);
    await Promise.resolve();

    expect(harness.suggestions.registry.registeredIds()).toEqual(registered);
    expect(harness.controller.getState()).toMatchObject({
      phase: "suggested",
      visible: false,
      operation: "polish",
    });
    expect(harness.registry.get(SELECTION_ID)).toBeDefined();
    expect(harness.runtime.getStatus().selectionCharacters).toBe(2);
    stop();
  });

  it("clears the logical selection when the active field range collapses", async () => {
    const events = new FakeEvents();
    const harness = setup({ sessionId: "session-1", documentTarget: events });
    const stop = harness.controller.start();
    await harness.controller.capture(harness.anchor);
    harness.setSelection(null);
    events.emit("keyup", harness.anchor);
    await Promise.resolve();

    expect(harness.controller.getState()).toMatchObject({
      phase: "idle",
      visible: false,
      selectedCharacters: 0,
    });
    expect(harness.registry.get(SELECTION_ID)).toBeUndefined();
    expect(harness.suggestions.registry.registeredIds()).toEqual([]);
    expect(harness.runtime.getStatus().selectionCharacters).toBe(0);
    stop();
  });

  it("hides on assistant focus without breaking the native-sender handoff", async () => {
    const events = new FakeEvents();
    const harness = setup({ sessionId: "session-1", documentTarget: events });
    const stop = harness.controller.start();
    await harness.controller.capture(harness.anchor);
    expect(harness.controller.prepareAssistantFallback(SELECTION_ID, "rewrite")).toBe(true);

    events.emit("focusin", {
      closest: (selector: string) => selector === ".anw-assistant-pane" ? {} : null,
    });

    expect(harness.controller.getState()).toMatchObject({
      phase: "suggested",
      visible: false,
      operation: "rewrite",
    });
    expect(harness.registry.get(SELECTION_ID)).toBeDefined();
    expect(harness.suggestions.registry.registeredIds()).toHaveLength(1);
    expect(harness.runtime.getStatus().selectionCharacters).toBe(2);

    stop();
    expect(events.count("focusin")).toBe(0);
  });

  it("clears a stale selection when focus moves elsewhere in the workbench", async () => {
    const events = new FakeEvents();
    const harness = setup({ sessionId: "session-1", documentTarget: events });
    const stop = harness.controller.start();
    await harness.controller.capture(harness.anchor);
    events.emit("focusin", { closest: () => null });

    expect(harness.controller.getState()).toMatchObject({
      phase: "idle",
      visible: false,
      selectedCharacters: 0,
    });
    expect(harness.registry.get(SELECTION_ID)).toBeUndefined();
    expect(harness.suggestions.registry.registeredIds()).toEqual([]);
    expect(harness.runtime.getStatus().selectionCharacters).toBe(0);
    stop();
  });

  it("does not auto-close for pointer events inside the selection toolbar", async () => {
    const events = new FakeEvents();
    const harness = setup({ documentTarget: events });
    const stop = harness.controller.start();
    await harness.controller.capture(harness.anchor);

    events.emit("mouseup", {
      closest: (selector: string) => selector === "[data-assistant-selection-toolbar]"
        ? {}
        : null,
    });

    expect(harness.controller.getState()).toMatchObject({
      phase: "ready",
      visible: true,
    });
    stop();
  });

  it("rejects a stale async hash capture when value/revision changes during hashing", async () => {
    let resolveHash!: (value: string) => void;
    const harness = setup({
      sha256: () => new Promise<string>((resolve) => { resolveHash = resolve; }),
    });
    const capture = harness.controller.capture(harness.anchor);
    harness.setValue("作者在散列期间继续输入。" );
    harness.scope.notifyFieldChanged("chapter.body");
    resolveHash(SHA);

    await expect(capture).resolves.toBe(false);
    expect(harness.registry.size()).toBe(0);
    expect(harness.runtime.getStatus().selectionCharacters).toBe(0);
  });

  it("suppresses capture during IME composition and captures after compositionend", async () => {
    const events = new FakeEvents();
    const harness = setup({ documentTarget: events });
    const stop = harness.controller.start();
    expect(events.count("mouseup")).toBe(1);

    events.emit("compositionstart", harness.anchor);
    events.emit("mouseup", harness.anchor);
    await Promise.resolve();
    expect(harness.registry.size()).toBe(0);

    events.emit("compositionend", harness.anchor);
    await Promise.resolve();
    await Promise.resolve();
    expect(harness.registry.size()).toBe(1);
    expect(harness.controller.getState().phase).toBe("ready");

    stop();
    expect(events.count("mouseup")).toBe(0);
    expect(harness.registry.size()).toBe(0);
  });

  it("keeps the selection when Escape-style hiding only closes the toolbar", async () => {
    const harness = setup();
    await harness.controller.capture(harness.anchor);
    harness.controller.hideToolbar();

    expect(harness.controller.getState().visible).toBe(false);
    expect(harness.runtime.getStatus().selectionCharacters).toBe(2);
    expect(harness.registry.get(SELECTION_ID)).toBeDefined();
  });

  it("preserves an in-flight selection across a host remount but clears it on a real stop", async () => {
    const events = new FakeEvents();
    const harness = setup({ sessionId: "session-1", documentTarget: events });
    harness.controller.start();
    await harness.controller.capture(harness.anchor);
    const record = harness.registry.get(SELECTION_ID)!;
    expect(harness.controller.prepareAssistantFallback(SELECTION_ID, "polish")).toBe(true);
    expect(harness.controller.bindSelectionForSend({
      selectionId: record.selectionId,
      sessionId: "session-1",
      agentId: record.agentId,
      novelId: record.novelId,
      documentId: record.documentId,
      fieldId: record.fieldId,
      contextRevision: record.contextRevision,
    })).toBe(true);

    harness.controller.suspend();
    expect(events.count("mouseup")).toBe(0);
    expect(harness.registry.get(SELECTION_ID)).toMatchObject({
      sessionId: "session-1",
    });

    harness.controller.start();
    expect(events.count("mouseup")).toBe(1);
    expect(harness.registry.get(SELECTION_ID)).toBeDefined();

    harness.controller.stop();
    expect(events.count("mouseup")).toBe(0);
    expect(harness.registry.size()).toBe(0);
  });
});
