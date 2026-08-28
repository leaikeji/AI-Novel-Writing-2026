import type { EditorView } from "@codemirror/view";
import { describe, expect, it, vi } from "vitest";

import {
  CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE,
  createChapterEditorSurface,
  type ChapterEditorSurfaceDependencies,
} from "./chapter-editor-surface";
import type {
  CodeMirrorNarrationAdapter,
  CodeMirrorNarrationAdapterOptions,
} from "./editor-codemirror";
import {
  createNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationEditorSelection,
} from "./editor-bridge";


const LEASE: DocumentLease = { documentId: "document-surface", generation: 9 };
const HASH = "a".repeat(64);
const INITIAL_VALUE_SHA256 = "04b5246f7bae510dc54ae986b0082ed862e9048486c3bfa14eeec7038d42bab8";
const EDITED_VALUE_SHA256 = "c5d55cd3906a244c970dc91f94c612d785c927dabb881bfe45b95b734a45ecd0";


class FakeNode {
  parentNode: FakeParent | null = null;
}


class FakeParent extends FakeNode {
  readonly childNodes: FakeNode[] = [];
  readonly ownerDocument: Document | null;
  readonly attributes = new Map<string, string>();

  constructor(ownerDocument: Document | null = null) {
    super();
    this.ownerDocument = ownerDocument;
  }

  appendChild<T extends FakeNode>(child: T): T {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  removeChild<T extends FakeNode>(child: T): T {
    const index = this.childNodes.indexOf(child);
    if (index >= 0) this.childNodes.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name: string): void {
    this.attributes.delete(name);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }
}


class FakeDomElement extends EventTarget {
  parentNode: FakeDomElement | null = null;
  readonly children: FakeDomElement[] = [];
  readonly attributes = new Map<string, string>();
  readonly style: Record<string, string> = {};
  className = "";
  textContent = "";
  type = "";
  focusCalls = 0;

  appendChild<T extends FakeDomElement>(child: T): T {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  contains(target: unknown): boolean {
    return target === this || this.children.some((child) => child.contains(target));
  }

  remove(): void {
    const parent = this.parentNode;
    if (!parent) return;
    const index = parent.children.indexOf(this);
    if (index >= 0) parent.children.splice(index, 1);
    this.parentNode = null;
  }

  focus(): void {
    this.focusCalls += 1;
  }
}


class FakeDocument extends EventTarget {
  readonly body = new FakeDomElement();

  createElement(): FakeDomElement {
    return new FakeDomElement();
  }
}


class FakeTextarea extends EventTarget {
  parentNode: FakeParent | null = null;
  value = "";
  selectionStart = 0;
  selectionEnd = 0;
  selectionDirection: "forward" | "backward" | "none" = "none";
  className = "";
  spellcheck = false;
  wrap = "";
  focusCalls = 0;
  readonly attributes = new Map<string, string>();

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  setSelectionRange(
    start: number,
    end: number,
    direction: "forward" | "backward" | "none" = "none",
  ): void {
    this.selectionStart = start;
    this.selectionEnd = end;
    this.selectionDirection = direction;
  }

  focus(): void {
    this.focusCalls += 1;
    this.dispatchEvent(new Event("focus"));
  }
}


function asParent(parent: FakeParent): HTMLElement {
  return parent as unknown as HTMLElement;
}


function createFakeCodeMirrorAdapter(
  options: CodeMirrorNarrationAdapterOptions,
  root: FakeNode,
): CodeMirrorNarrationAdapter & { readonly focusCalls: () => number } {
  const parent = options.parent as unknown as FakeParent;
  parent.appendChild(root);
  const bridge = createNarrationEditorBridge({
    kind: "codemirror6",
    lease: options.lease,
    text: options.initialValue,
    currentContentHash: options.currentContentHash,
    selection: options.selection,
    onDocChanged: options.onDocChanged,
    isLeaseCurrent: options.isLeaseCurrent,
  });
  let focusCalls = 0;
  let disposed = false;

  const setSelection = (selection: NarrationEditorSelection): boolean => {
    if (disposed) return false;
    const result = bridge.setSelection(selection);
    if (!result.applied) return false;
    focusCalls += 1;
    return true;
  };

  return {
    bridge,
    view: { dom: root } as unknown as EditorView,
    readValue: () => bridge.readSnapshot().text,
    readSelection: () => bridge.readSnapshot().selection,
    setValue(nextValue, origin) {
      const snapshot = bridge.readSnapshot();
      if (disposed || !snapshot.active || snapshot.text === nextValue) return false;
      return bridge.applyTransaction({
        changes: [{
          startUtf16: 0,
          endUtf16: snapshot.text.length,
          insertedText: nextValue,
        }],
        selectionAfter: {
          startUtf16: nextValue.length,
          endUtf16: nextValue.length,
          direction: "none",
        },
        origin,
      }).applied;
    },
    setParagraphGutter() {
      return !disposed;
    },
    focusSelection: setSelection,
    focus() {
      if (!disposed && bridge.readSnapshot().active) focusCalls += 1;
    },
    undo: () => false,
    redo: () => false,
    dispose() {
      if (disposed) return;
      disposed = true;
      bridge.dispose();
    },
    focusCalls: () => focusCalls,
  };
}


function commonOptions(parent: FakeParent, onDocChanged = vi.fn()) {
  return {
    parent: asParent(parent),
    lease: LEASE,
    initialValue: "甲🙂乙",
    currentContentHash: HASH,
    ariaLabel: "章节正文",
    onDocChanged,
    isLeaseCurrent: (lease: DocumentLease) => documentLeasesEqual(lease, LEASE),
  };
}


describe("chapter editor surface CodeMirror owner", () => {
  it("exposes the real CodeMirror selection, focus, and one-shot value path", () => {
    const parent = new FakeParent();
    const preserved = parent.appendChild(new FakeNode());
    const editorRoot = new FakeNode();
    const onDocChanged = vi.fn();
    let readFocusCalls = () => -1;
    const createTextareaElement = vi.fn(() => new FakeTextarea() as unknown as HTMLTextAreaElement);
    const handle = createChapterEditorSurface(commonOptions(parent, onDocChanged), {
      createCodeMirrorAdapter(options) {
        const adapter = createFakeCodeMirrorAdapter(options, editorRoot);
        readFocusCalls = adapter.focusCalls;
        return adapter;
      },
      createTextareaElement,
    });

    expect(handle.kind).toBe("codemirror6");
    expect(createTextareaElement).not.toHaveBeenCalled();
    expect(parent.childNodes).toEqual([preserved, editorRoot]);
    expect(handle.readValue()).toBe("甲🙂乙");

    handle.assistantControl.setSelectionRange(1, 3, "backward");
    expect(handle.assistantControl.selectionStart).toBe(1);
    expect(handle.assistantControl.selectionEnd).toBe(3);
    expect(handle.assistantControl.selectionDirection).toBe("backward");
    handle.assistantControl.focus();

    expect(handle.setValue("AI 新稿", "ai-apply")).toBe(true);
    expect(handle.setValue("AI 新稿", "ai-apply")).toBe(false);
    expect(onDocChanged).toHaveBeenCalledOnce();
    expect(onDocChanged).toHaveBeenCalledWith(expect.objectContaining({
      lease: LEASE,
      nextValue: "AI 新稿",
      origin: "ai-apply",
    }));
    expect(readFocusCalls()).toBe(2);

    handle.dispose();
    handle.dispose();
    expect(parent.childNodes).toEqual([preserved]);
    expect(handle.bridge.readSnapshot().active).toBe(false);
    expect(handle.setValue("不得写入", "external")).toBe(false);
    expect(handle.assistantControl.selectionStart).toBeNull();
  });

  it("keeps an existing parent child when CodeMirror construction throws", () => {
    const parent = new FakeParent();
    const preserved = parent.appendChild(new FakeNode());
    const partialCodeMirrorNode = new FakeNode();
    const textarea = new FakeTextarea();
    const onDocChanged = vi.fn();
    const interactions: string[] = [];
    const focusChanges: boolean[] = [];

    const handle = createChapterEditorSurface({
      ...commonOptions(parent, onDocChanged),
      onAuthorInteraction: (interaction) => interactions.push(interaction),
      onFocusChange: (focused) => focusChanges.push(focused),
    }, {
      createCodeMirrorAdapter(options) {
        (options.parent as unknown as FakeParent).appendChild(partialCodeMirrorNode);
        throw new Error("synthetic CodeMirror constructor failure");
      },
      createTextareaElement: () => textarea as unknown as HTMLTextAreaElement,
    });

    expect(handle.kind).toBe("textarea-fallback");
    expect(parent.childNodes).toEqual([preserved, textarea]);
    expect(partialCodeMirrorNode.parentNode).toBeNull();
    expect(textarea.attributes.get("aria-label")).toBe("章节正文");
    expect(textarea.className).toBe("anw-chapter-editor-textarea-fallback");
    expect(handle.bridge.capabilities).toMatchObject({
      editableDecorations: false,
      paragraphGutter: false,
      exactSegmentMapping: true,
    });

    textarea.value = "第一次输入";
    textarea.selectionStart = textarea.value.length;
    textarea.selectionEnd = textarea.value.length;
    textarea.dispatchEvent(new Event("input"));
    textarea.dispatchEvent(new Event("compositionstart"));
    textarea.value = "组合输入";
    textarea.selectionStart = textarea.value.length;
    textarea.selectionEnd = textarea.value.length;
    textarea.dispatchEvent(new Event("input"));
    textarea.dispatchEvent(new Event("compositionend"));
    textarea.dispatchEvent(new Event("input"));

    expect(onDocChanged).toHaveBeenCalledTimes(2);
    expect(onDocChanged.mock.calls.map(([event]) => event.origin)).toEqual([
      "input",
      "composition",
    ]);
    expect(interactions).toContain("input");
    expect(interactions).toContain("composition");

    expect(handle.setValue("AI 接管一次", "ai-apply")).toBe(true);
    expect(handle.setValue("AI 接管一次", "ai-apply")).toBe(false);
    expect(onDocChanged).toHaveBeenCalledTimes(3);
    handle.assistantControl.setSelectionRange(0, 2, "forward");
    expect(textarea.selectionStart).toBe(0);
    expect(textarea.selectionEnd).toBe(2);
    expect(textarea.selectionDirection).toBe("forward");
    handle.focus();
    textarea.dispatchEvent(new Event("blur"));
    expect(focusChanges).toEqual([true, true, false]);

    handle.dispose();
    textarea.value = "销毁后输入";
    textarea.dispatchEvent(new Event("input"));
    expect(onDocChanged).toHaveBeenCalledTimes(3);
    expect(parent.childNodes).toEqual([preserved]);
  });
});


describe("chapter editor surface canonical value digest", () => {
  it("publishes only the SHA-256 of the bridge value and follows edit then undo", async () => {
    const parent = new FakeParent();
    const editorRoot = new FakeNode();
    const onDocChanged = vi.fn();
    const handle = createChapterEditorSurface(commonOptions(parent, onDocChanged), {
      createCodeMirrorAdapter: (options) => createFakeCodeMirrorAdapter(options, editorRoot),
    });

    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();
    await vi.waitFor(() => {
      expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBe(
        INITIAL_VALUE_SHA256,
      );
    });

    expect(handle.setValue("编辑后正文", "input")).toBe(true);
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();
    await vi.waitFor(() => {
      expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBe(
        EDITED_VALUE_SHA256,
      );
    });

    expect(handle.setValue("甲🙂乙", "undo")).toBe(true);
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();
    await vi.waitFor(() => {
      expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBe(
        INITIAL_VALUE_SHA256,
      );
    });
    expect(onDocChanged.mock.calls.map(([event]) => event.origin)).toEqual(["input", "undo"]);
    expect([...parent.attributes.entries()]).toEqual([
      [CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE, INITIAL_VALUE_SHA256],
    ]);
    expect(parent.attributes.has("data-editor-value")).toBe(false);
    expect(parent.attributes.has("data-editor-value-length")).toBe(false);
    expect(parent.attributes.has("data-document-id")).toBe(false);

    handle.dispose();
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();
  });

  it("rejects stale async digest results and exposes only the latest canonical value", async () => {
    const parent = new FakeParent();
    const pending: Array<{
      readonly value: string;
      readonly resolve: (digest: string) => void;
    }> = [];
    const hashEditorValue = vi.fn((value: string) => new Promise<string>((resolve) => {
      pending.push({ value, resolve });
    }));
    const handle = createChapterEditorSurface(commonOptions(parent), {
      createCodeMirrorAdapter: (options) => createFakeCodeMirrorAdapter(options, new FakeNode()),
      hashEditorValue,
    });

    expect(handle.setValue("编辑后正文", "input")).toBe(true);
    expect(handle.setValue("甲🙂乙", "undo")).toBe(true);
    await vi.waitFor(() => expect(pending).toHaveLength(3));
    expect(pending.map(({ value }) => value)).toEqual(["甲🙂乙", "编辑后正文", "甲🙂乙"]);

    pending[1].resolve(EDITED_VALUE_SHA256);
    pending[0].resolve(INITIAL_VALUE_SHA256);
    await Promise.resolve();
    await Promise.resolve();
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();

    pending[2].resolve(INITIAL_VALUE_SHA256);
    await vi.waitFor(() => {
      expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBe(
        INITIAL_VALUE_SHA256,
      );
    });
    handle.dispose();
  });

  it("fails closed when hashing throws or returns a non-SHA-256 value", async () => {
    const parent = new FakeParent();
    const hashEditorValue = vi.fn((value: string): Promise<string> => {
      if (value === "甲🙂乙") return Promise.resolve(INITIAL_VALUE_SHA256);
      if (value === "同步异常") throw new Error("synthetic synchronous hash failure");
      return Promise.resolve("not-a-sha256");
    });
    const handle = createChapterEditorSurface(commonOptions(parent), {
      createCodeMirrorAdapter: (options) => createFakeCodeMirrorAdapter(options, new FakeNode()),
      hashEditorValue,
    });
    await vi.waitFor(() => {
      expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBe(
        INITIAL_VALUE_SHA256,
      );
    });

    expect(handle.setValue("同步异常", "input")).toBe(true);
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();
    await Promise.resolve();
    await Promise.resolve();
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();

    expect(handle.setValue("无效摘要", "input")).toBe(true);
    await Promise.resolve();
    await Promise.resolve();
    expect(parent.getAttribute(CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE)).toBeNull();
    handle.dispose();
  });
});


describe("chapter editor surface presentation isolation", () => {
  it("does not seek or save for an ordinary textarea click or bridge presentation", () => {
    const parent = new FakeParent();
    const textarea = new FakeTextarea();
    const onDocChanged = vi.fn();
    const handle = createChapterEditorSurface({
      ...commonOptions(parent, onDocChanged),
      initialValue: "第一段。",
    }, {
      createCodeMirrorAdapter() {
        throw new Error("force truthful fallback");
      },
      createTextareaElement: () => textarea as unknown as HTMLTextAreaElement,
    });
    const playback = vi.fn();
    handle.bridge.registerPlaybackIntent(playback);
    expect(handle.bridge.bindEdition({
      lease: LEASE,
      editionId: "edition-surface",
      sourceRevisionId: "revision-surface",
      sourceContentHash: HASH,
      segments: [{
        segmentId: "segment-surface",
        sourceBlockKey: "paragraph-1",
        sourceText: "第一段。",
        sourceRange: { startUtf16: 0, endUtf16: 4 },
      }],
    })).toEqual({ applied: true });

    textarea.dispatchEvent(new Event("click"));
    expect(handle.bridge.markCurrentSegment({
      lease: LEASE,
      editionId: "edition-surface",
      segmentId: "segment-surface",
    })).toMatchObject({ applied: true });
    expect(handle.bridge.scrollCurrentSegmentIntoView({
      lease: LEASE,
      editionId: "edition-surface",
    })).toMatchObject({ applied: false, reason: "unsupported_capability" });

    expect(playback).not.toHaveBeenCalled();
    expect(onDocChanged).not.toHaveBeenCalled();
    handle.dispose();
  });

  it("exposes an explicit cursor command for the truthful textarea fallback", () => {
    const parent = new FakeParent();
    const textarea = new FakeTextarea();
    const onDocChanged = vi.fn();
    const onParagraphPlaybackCommand = vi.fn(() => true);
    const handle = createChapterEditorSurface({
      ...commonOptions(parent, onDocChanged),
      initialValue: "第一段。\n第二段。",
      onParagraphPlaybackCommand,
    }, {
      createCodeMirrorAdapter() {
        throw new Error("force truthful fallback");
      },
      createTextareaElement: () => textarea as unknown as HTMLTextAreaElement,
    });
    textarea.selectionStart = 7;
    textarea.selectionEnd = 7;

    expect(handle.requestPlaybackFromCursor()).toBe(true);
    expect(onParagraphPlaybackCommand).toHaveBeenCalledWith({
      source: "cursor-command",
      lookup: { positionUtf16: 7 },
    });
    expect(onDocChanged).not.toHaveBeenCalled();

    textarea.dispatchEvent(new Event("compositionstart"));
    expect(handle.requestPlaybackFromCursor()).toBe(false);
    expect(onParagraphPlaybackCommand).toHaveBeenCalledTimes(1);
    handle.dispose();
  });

  it("opens an accessible context command and plays only after its menu item is clicked", () => {
    const ownerDocument = new FakeDocument();
    const parent = new FakeParent(ownerDocument as unknown as Document);
    const textarea = new FakeTextarea();
    const onDocChanged = vi.fn();
    const onParagraphPlaybackCommand = vi.fn(() => true);
    const handle = createChapterEditorSurface({
      ...commonOptions(parent, onDocChanged),
      initialValue: "第一段。\n第二段。",
      onParagraphPlaybackCommand,
    }, {
      createCodeMirrorAdapter() {
        throw new Error("force truthful fallback");
      },
      createTextareaElement: () => textarea as unknown as HTMLTextAreaElement,
    });
    textarea.selectionStart = 6;
    textarea.selectionEnd = 6;
    const contextMenu = new Event("contextmenu", { cancelable: true });
    Object.defineProperties(contextMenu, {
      clientX: { value: 30 },
      clientY: { value: 40 },
    });
    textarea.dispatchEvent(contextMenu);

    expect(contextMenu.defaultPrevented).toBe(true);
    expect(onParagraphPlaybackCommand).not.toHaveBeenCalled();
    expect(ownerDocument.body.children).toHaveLength(1);
    const menu = ownerDocument.body.children[0];
    expect(menu.attributes.get("role")).toBe("menu");
    expect(menu.attributes.get("aria-label")).toBe("段落朗读命令");
    expect(menu.style.left).toBe("30px");
    expect(menu.style.top).toBe("40px");
    const command = menu.children[0];
    expect(command.attributes.get("role")).toBe("menuitem");
    expect(command.textContent).toBe("从本段朗读");
    expect(command.focusCalls).toBe(1);

    command.dispatchEvent(new Event("click"));
    expect(onParagraphPlaybackCommand).toHaveBeenCalledWith({
      source: "context-menu",
      lookup: { positionUtf16: 6 },
    });
    expect(ownerDocument.body.children).toHaveLength(0);
    expect(onDocChanged).not.toHaveBeenCalled();
    handle.dispose();
  });

  it("rejects an empty accessible name before constructing either editor", () => {
    const parent = new FakeParent();
    const createCodeMirrorAdapter = vi.fn();
    expect(() => createChapterEditorSurface({
      ...commonOptions(parent),
      ariaLabel: "   ",
    }, {
      createCodeMirrorAdapter: createCodeMirrorAdapter as unknown as ChapterEditorSurfaceDependencies["createCodeMirrorAdapter"],
    })).toThrow("ariaLabel must not be empty");
    expect(createCodeMirrorAdapter).not.toHaveBeenCalled();
  });
});
