import { describe, expect, it, vi } from "vitest";

import {
  applyTextareaValueToBridge,
  computeTextareaTextChange,
  createTextareaNarrationAdapter,
  normalizeTextareaSelection,
  textareaInputOrigin,
} from "./editor-textarea-fallback";
import {
  TEXTAREA_SAFE_FALLBACK,
  documentLeasesEqual,
  type DocumentLease,
} from "./editor-bridge";
import type { OnEditorParagraphPlaybackCommand } from "./paragraph-gutter";


const LEASE: DocumentLease = { documentId: "document-textarea", generation: 4 };
const HASH = "d".repeat(64);
const TEXT = "甲🙂乙\n第二段。";


class FakeTextarea extends EventTarget {
  value: string;
  selectionStart = 0;
  selectionEnd = 0;
  selectionDirection: "forward" | "backward" | "none" = "none";
  focusCalls = 0;

  constructor(value: string) {
    super();
    this.value = value;
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
  }
}


function createHarness(
  initialValue = TEXT,
  observers: {
    readonly onFocusChange?: (focused: boolean) => void;
    readonly onAuthorInteraction?: (
      interruption: "manual-scroll" | "caret-move" | "selection" | "input" | "composition",
    ) => void;
    readonly onParagraphPlaybackCommand?: OnEditorParagraphPlaybackCommand;
  } = {},
) {
  const element = new FakeTextarea(initialValue);
  let currentLease: DocumentLease = LEASE;
  const onDocChanged = vi.fn();
  const adapter = createTextareaNarrationAdapter({
    element: element as unknown as HTMLTextAreaElement,
    lease: LEASE,
    initialValue,
    currentContentHash: HASH,
    onDocChanged,
    isLeaseCurrent: (candidate) => documentLeasesEqual(candidate, currentLease),
    ...observers,
  });
  return {
    adapter,
    element,
    onDocChanged,
    setCurrentLease(next: DocumentLease) {
      currentLease = next;
    },
  };
}


function bind(harness: ReturnType<typeof createHarness>) {
  const sourceText = "第二段。";
  const startUtf16 = TEXT.indexOf(sourceText);
  return harness.adapter.bridge.bindEdition({
    lease: LEASE,
    editionId: "edition-textarea",
    sourceRevisionId: "revision-textarea",
    sourceContentHash: HASH,
    segments: [{
      segmentId: "segment-textarea",
      sourceBlockKey: "block-textarea",
      sourceText,
      sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
    }],
  });
}


describe("textarea UTF-16 diff", () => {
  it("keeps an entire surrogate pair inside an emoji replacement", () => {
    expect(computeTextareaTextChange("甲🙂乙", "甲😃乙")).toEqual({
      startUtf16: 1,
      endUtf16: 3,
      insertedText: "😃",
    });
  });

  it("normalizes a caret that would split a surrogate pair", () => {
    expect(normalizeTextareaSelection("甲🙂乙", {
      startUtf16: 2,
      endUtf16: 2,
      direction: "none",
    })).toEqual({ startUtf16: 1, endUtf16: 1, direction: "none" });
  });

  it("returns no text change for an identical controlled value", () => {
    expect(computeTextareaTextChange(TEXT, TEXT)).toBeNull();
  });
});


describe("textarea value and save isolation", () => {
  it("emits exactly once when an input event changes the actual value", () => {
    const harness = createHarness("旧稿");
    harness.element.value = "新稿";
    harness.element.selectionStart = 2;
    harness.element.selectionEnd = 2;
    harness.element.dispatchEvent(new Event("input"));

    expect(harness.onDocChanged).toHaveBeenCalledOnce();
    expect(harness.onDocChanged).toHaveBeenCalledWith({
      lease: LEASE,
      nextValue: "新稿",
      origin: "input",
      composing: false,
    });
    expect(harness.adapter.bridge.readSnapshot().text).toBe("新稿");
  });

  it("does not emit for a same-value input event", () => {
    const harness = createHarness("未变");
    harness.element.dispatchEvent(new Event("input"));
    harness.element.dispatchEvent(new Event("input"));
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("coalesces composition end without duplicating the final input", () => {
    const harness = createHarness("甲");
    harness.element.dispatchEvent(new Event("compositionstart"));
    harness.element.value = "甲乙";
    harness.element.selectionStart = 2;
    harness.element.selectionEnd = 2;
    harness.element.dispatchEvent(new Event("input"));
    harness.element.dispatchEvent(new Event("compositionend"));
    harness.element.dispatchEvent(new Event("input"));

    expect(harness.onDocChanged).toHaveBeenCalledTimes(1);
    expect(harness.onDocChanged).toHaveBeenCalledWith(expect.objectContaining({
      nextValue: "甲乙",
      origin: "composition",
      composing: true,
    }));
    expect(harness.adapter.bridge.readSnapshot().composing).toBe(false);
  });

  it("routes AI apply through the same one-shot value callback", () => {
    const harness = createHarness("旧稿");
    expect(harness.adapter.setValue("新稿", "ai-apply")).toBe(true);
    expect(harness.adapter.setValue("新稿", "ai-apply")).toBe(false);
    expect(harness.onDocChanged).toHaveBeenCalledTimes(1);
    expect(harness.onDocChanged).toHaveBeenCalledWith(expect.objectContaining({
      origin: "ai-apply",
      nextValue: "新稿",
    }));
  });

  it("preserves native textarea undo and redo origins exactly once", () => {
    const harness = createHarness("甲");
    const undoEvent = new Event("input");
    Object.defineProperty(undoEvent, "inputType", { value: "historyUndo" });
    harness.element.value = "";
    harness.element.dispatchEvent(undoEvent);
    const redoEvent = new Event("input");
    Object.defineProperty(redoEvent, "inputType", { value: "historyRedo" });
    harness.element.value = "甲";
    harness.element.dispatchEvent(redoEvent);

    expect(textareaInputOrigin(undoEvent, false)).toBe("undo");
    expect(textareaInputOrigin(redoEvent, false)).toBe("redo");
    expect(harness.onDocChanged).toHaveBeenCalledTimes(2);
    expect(harness.onDocChanged.mock.calls.map(([event]) => event.origin)).toEqual([
      "undo",
      "redo",
    ]);
  });

  it("does not save for selection, focus, scroll, or an ordinary click", () => {
    const harness = createHarness();
    bind(harness);
    const playback = vi.fn();
    harness.adapter.bridge.registerPlaybackIntent(playback);
    expect(harness.adapter.focusSelection({
      startUtf16: 1,
      endUtf16: 3,
      direction: "forward",
    })).toBe(true);
    harness.element.dispatchEvent(new Event("select"));
    harness.element.dispatchEvent(new Event("scroll"));
    harness.element.dispatchEvent(new Event("click"));

    expect(harness.element.focusCalls).toBe(1);
    expect(harness.adapter.bridge.readSnapshot().autoFollowPaused).toBe(true);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
    expect(playback).not.toHaveBeenCalled();
  });

  it("routes context menu and Mod+Alt+Enter from the cursor without saving", () => {
    const commands: Parameters<OnEditorParagraphPlaybackCommand>[0][] = [];
    const harness = createHarness(TEXT, {
      onParagraphPlaybackCommand: (command) => {
        commands.push(command);
        return true;
      },
    });
    const cursor = TEXT.indexOf("第二段。") + 2;
    harness.element.selectionStart = cursor;
    harness.element.selectionEnd = cursor;

    const shortcut = new Event("keydown", { cancelable: true });
    Object.defineProperties(shortcut, {
      key: { value: "Enter" },
      altKey: { value: true },
      ctrlKey: { value: true },
      metaKey: { value: false },
      shiftKey: { value: false },
      repeat: { value: false },
      isComposing: { value: false },
    });
    harness.element.dispatchEvent(shortcut);
    const contextMenu = new Event("contextmenu", { cancelable: true });
    harness.element.dispatchEvent(contextMenu);

    expect(commands).toEqual([
      {
        source: "keyboard",
        event: expect.objectContaining({ key: "Enter", ctrlKey: true, altKey: true }),
        lookup: { positionUtf16: cursor },
      },
      { source: "context-menu", lookup: { positionUtf16: cursor } },
    ]);
    expect(shortcut.defaultPrevented).toBe(true);
    expect(contextMenu.defaultPrevented).toBe(true);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("does not dispatch playback shortcuts during IME or key repeat", () => {
    const onParagraphPlaybackCommand = vi.fn(() => true);
    const harness = createHarness(TEXT, { onParagraphPlaybackCommand });
    for (const patch of [
      { repeat: true, isComposing: false },
      { repeat: false, isComposing: true },
    ]) {
      const event = new Event("keydown", { cancelable: true });
      Object.defineProperties(event, {
        key: { value: "Enter" },
        altKey: { value: true },
        ctrlKey: { value: true },
        metaKey: { value: false },
        shiftKey: { value: false },
        repeat: { value: patch.repeat },
        isComposing: { value: patch.isComposing },
      });
      harness.element.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    }
    harness.element.dispatchEvent(new Event("compositionstart"));
    harness.element.dispatchEvent(new Event("contextmenu", { cancelable: true }));

    expect(onParagraphPlaybackCommand).not.toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("reports author and focus interactions without creating extra document changes", () => {
    const interactions: string[] = [];
    const focusChanges: boolean[] = [];
    const harness = createHarness("甲乙", {
      onAuthorInteraction: (interaction) => interactions.push(interaction),
      onFocusChange: (focused) => focusChanges.push(focused),
    });
    harness.element.selectionStart = 1;
    harness.element.selectionEnd = 1;
    harness.element.dispatchEvent(new Event("keyup"));
    harness.element.dispatchEvent(new Event("keyup"));
    harness.element.selectionStart = 0;
    harness.element.selectionEnd = 2;
    harness.element.selectionDirection = "backward";
    harness.element.dispatchEvent(new Event("select"));
    harness.element.dispatchEvent(new Event("scroll"));
    harness.element.dispatchEvent(new Event("focus"));
    harness.element.dispatchEvent(new Event("blur"));

    expect(interactions).toEqual(["caret-move", "selection", "manual-scroll"]);
    expect(focusChanges).toEqual([true, false]);
    expect(harness.adapter.bridge.readSnapshot().autoFollowPaused).toBe(true);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("exposes the pure helper without bypassing the bridge callback", () => {
    const harness = createHarness("甲");
    const report = applyTextareaValueToBridge(harness.adapter.bridge, "甲乙", {
      startUtf16: 2,
      endUtf16: 2,
      direction: "none",
    }, "external");
    expect(report).toMatchObject({ applied: true, text: "甲乙" });
    expect(harness.onDocChanged).toHaveBeenCalledOnce();
  });
});


describe("textarea lifecycle and truthful degradation", () => {
  it("does not claim editable decorations or a gutter seek surface", () => {
    const harness = createHarness();
    bind(harness);
    expect(harness.adapter.bridge.capabilities).toEqual({
      editableDecorations: false,
      paragraphGutter: false,
      exactSegmentMapping: true,
    });
    expect(TEXTAREA_SAFE_FALLBACK).toMatchObject({
      editableDecoration: false,
      editableGutterSeek: false,
      ordinaryClickSeeks: false,
    });
    expect(harness.adapter.bridge.requestPlayback({
      lease: LEASE,
      editionId: "edition-textarea",
      source: "gutter",
      lookup: { segmentId: "segment-textarea" },
    })).toEqual({ accepted: false, reason: "unsupported_surface" });
    expect(harness.adapter.bridge.requestPlayback({
      lease: LEASE,
      editionId: "edition-textarea",
      source: "command",
      lookup: { segmentId: "segment-textarea" },
    })).toMatchObject({ accepted: true, intent: { segmentId: "segment-textarea" } });
  });

  it("does not mutate the element or save after its generation becomes stale", () => {
    const harness = createHarness("旧稿");
    harness.setCurrentLease({ documentId: LEASE.documentId, generation: LEASE.generation + 1 });
    expect(harness.adapter.setValue("过期新稿", "external")).toBe(false);
    expect(harness.element.value).toBe("旧稿");

    harness.element.value = "用户触发的过期事件";
    harness.element.dispatchEvent(new Event("input"));
    expect(harness.adapter.bridge.readSnapshot().text).toBe("旧稿");
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("removes every listener and permanently suppresses writes on dispose", () => {
    const harness = createHarness("旧稿");
    harness.adapter.dispose();
    harness.adapter.dispose();
    harness.element.value = "新稿";
    harness.element.dispatchEvent(new Event("input"));
    expect(harness.adapter.setValue("另一稿", "external")).toBe(false);
    expect(harness.adapter.bridge.readSnapshot()).toMatchObject({
      active: false,
      inactiveReason: "disposed",
      text: "旧稿",
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});
