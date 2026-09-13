import { EditorState, Transaction } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { describe, expect, it, vi } from "vitest";

import {
  applyCodeMirrorUpdateToBridge,
  codeMirrorAuthorInteraction,
  codeMirrorChangesToEditorChanges,
  codeMirrorNarrationEffect,
  codeMirrorNarrationPresentationAnnotation,
  codeMirrorNarrationRanges,
  codeMirrorOriginAnnotation,
  codeMirrorTransactionOrigin,
  codeMirrorValueReplacement,
  createCodeMirrorNarrationState,
  dispatchCodeMirrorContextPlaybackCommand,
  dispatchCodeMirrorKeyboardPlaybackCommand,
  selectionFromCodeMirror,
} from "./editor-codemirror";
import {
  ProductionNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationEditorSelection,
} from "./editor-bridge";


const LEASE: DocumentLease = { documentId: "document-cm", generation: 3 };
const HASH = "c".repeat(64);


function createHarness(text = "甲🙂乙\n第二段。", selection?: NarrationEditorSelection) {
  let currentLease: DocumentLease = LEASE;
  const onDocChanged = vi.fn();
  const bridge = new ProductionNarrationEditorBridge({
    kind: "codemirror6",
    lease: LEASE,
    text,
    selection,
    currentContentHash: HASH,
    onDocChanged,
    isLeaseCurrent: (candidate) => documentLeasesEqual(candidate, currentLease),
  });
  return {
    bridge,
    onDocChanged,
    setCurrentLease(next: DocumentLease) {
      currentLease = next;
    },
  };
}


function applyTransaction(
  bridge: ProductionNarrationEditorBridge,
  transaction: Transaction,
  composing = false,
) {
  return applyCodeMirrorUpdateToBridge(bridge, {
    changes: transaction.changes,
    state: transaction.state,
    transactions: [transaction],
    docChanged: transaction.docChanged,
    selectionSet: transaction.selection !== transaction.startState.selection,
    composing,
  });
}


function bridgeUpdate(transaction: Transaction, composing = false) {
  return {
    changes: transaction.changes,
    state: transaction.state,
    transactions: [transaction],
    docChanged: transaction.docChanged,
    selectionSet: transaction.selection !== transaction.startState.selection,
    composing,
  };
}


describe("CodeMirror narration public state", () => {
  it("enables visual line wrapping without changing the stored document", () => {
    const text = `${"长段落。".repeat(80)}\n第二段。`;
    const harness = createHarness(text);
    const state = createCodeMirrorNarrationState(text, harness.bridge);

    expect(state.facet(EditorView.contentAttributes)).toContainEqual({
      class: "cm-lineWrapping",
    });
    expect(state.doc.toString()).toBe(text);
    expect(state.doc.lines).toBe(2);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("maps a decoration through UTF-16 edits without changing selection or saving", () => {
    const harness = createHarness();
    let state = createCodeMirrorNarrationState("甲🙂乙\n第二段。", harness.bridge);
    const selectionBefore = state.selection.main;
    state = state.update({
      effects: codeMirrorNarrationEffect({ startUtf16: 1, endUtf16: 3 }),
    }).state;
    expect(codeMirrorNarrationRanges(state)).toEqual([{ startUtf16: 1, endUtf16: 3 }]);
    expect(state.selection.main).toEqual(selectionBefore);

    state = state.update({ changes: { from: 0, insert: "序" } }).state;
    expect(codeMirrorNarrationRanges(state)).toEqual([{ startUtf16: 2, endUtf16: 4 }]);
    state = state.update({ effects: codeMirrorNarrationEffect(null) }).state;
    expect(codeMirrorNarrationRanges(state)).toEqual([]);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("requires CodeMirror and bridge to start from the same document", () => {
    const harness = createHarness("甲乙");
    expect(() => createCodeMirrorNarrationState("不同", harness.bridge))
      .toThrow("must equal the NarrationEditorBridge snapshot");
  });
});


describe("CodeMirror whole-document replacement", () => {
  it.each([
    { name: "forward growth", start: 2, end: 6, direction: "forward", next: "ABCDEFGHIJK", expectedStart: 2, expectedEnd: 6 },
    { name: "backward growth", start: 2, end: 6, direction: "backward", next: "ABCDEFGHIJK", expectedStart: 2, expectedEnd: 6 },
    { name: "forward truncation", start: 2, end: 6, direction: "forward", next: "ABCD", expectedStart: 2, expectedEnd: 4 },
    { name: "backward truncation", start: 2, end: 6, direction: "backward", next: "ABCD", expectedStart: 2, expectedEnd: 4 },
    { name: "selection past new end", start: 2, end: 6, direction: "backward", next: "A", expectedStart: 1, expectedEnd: 1 },
    { name: "empty replacement", start: 2, end: 6, direction: "forward", next: "", expectedStart: 0, expectedEnd: 0 },
    { name: "forward surrogate boundaries", start: 2, end: 6, direction: "forward", next: "甲🙂乙丙🧰丁", expectedStart: 1, expectedEnd: 7 },
    { name: "backward surrogate boundaries", start: 2, end: 6, direction: "backward", next: "甲🙂乙丙🧰丁", expectedStart: 1, expectedEnd: 7 },
    { name: "caret inside new surrogate", start: 2, end: 2, direction: "none", next: "甲🙂乙", expectedStart: 1, expectedEnd: 1 },
    { name: "empty document growth", initial: "", start: 0, end: 0, direction: "none", next: "甲🙂乙", expectedStart: 0, expectedEnd: 0 },
  ] as const)("keeps $name ordered and UTF-16-safe in the real state and bridge", (example) => {
    const initial = ("initial" in example ? example.initial : undefined) ?? "abcdefghi";
    const harness = createHarness(initial, {
      startUtf16: example.start,
      endUtf16: example.end,
      direction: example.direction,
    });
    const state = createCodeMirrorNarrationState(initial, harness.bridge);
    const replacement = codeMirrorValueReplacement(state, example.next, "ai-apply");
    expect(replacement).not.toBeNull();
    const transaction = state.update(replacement!);
    const expected = {
      startUtf16: example.expectedStart,
      endUtf16: example.expectedEnd,
      direction: example.expectedStart === example.expectedEnd ? "none" : example.direction,
    };

    expect(selectionFromCodeMirror(transaction.state)).toEqual(expected);
    expect(applyTransaction(harness.bridge, transaction)).toMatchObject({
      applied: true,
      text: example.next,
    });
    expect(harness.bridge.readSnapshot()).toMatchObject({ text: example.next, selection: expected });
    expect(harness.onDocChanged).toHaveBeenCalledExactlyOnceWith({
      lease: LEASE,
      nextValue: example.next,
      origin: "ai-apply",
      composing: false,
    });
  });

  it("preserves safe existing emoji selection offsets", () => {
    const text = "甲🙂乙\n第二段。";
    const harness = createHarness(text, { startUtf16: 1, endUtf16: 3, direction: "backward" });
    const state = createCodeMirrorNarrationState(text, harness.bridge);
    const transaction = state.update(codeMirrorValueReplacement(state, `${text}续写。`, "external")!);

    expect(applyTransaction(harness.bridge, transaction)?.applied).toBe(true);
    expect(harness.bridge.readSnapshot().selection).toEqual({
      startUtf16: 1, endUtf16: 3, direction: "backward",
    });
    expect(harness.onDocChanged).toHaveBeenCalledOnce();
  });

  it("does not dispatch an unchanged value or accept malformed replacement text", () => {
    const harness = createHarness("甲🙂乙");
    const state = createCodeMirrorNarrationState("甲🙂乙", harness.bridge);
    expect(codeMirrorValueReplacement(state, "甲🙂乙", "external")).toBeNull();
    expect(() => codeMirrorValueReplacement(state, "甲\ud83d乙", "external"))
      .toThrow("unpaired UTF-16 high surrogate");
    expect(state.doc.toString()).toBe("甲🙂乙");
    expect(harness.bridge.readSnapshot().text).toBe("甲🙂乙");
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});


describe("CodeMirror docChanged isolation", () => {
  it("converts one public ChangeSet into strict UTF-16 changes", () => {
    const state = EditorState.create({ doc: "甲🙂乙" });
    const transaction = state.update({ changes: { from: 1, to: 3, insert: "丁" } });
    expect(codeMirrorChangesToEditorChanges(transaction.changes)).toEqual([{
      startUtf16: 1,
      endUtf16: 3,
      insertedText: "丁",
    }]);
  });

  it("calls OnEditorDocChanged exactly once for a document update", () => {
    const harness = createHarness("第一段。");
    const state = createCodeMirrorNarrationState("第一段。", harness.bridge);
    const transaction = state.update({
      changes: { from: 0, to: 2, insert: "首" },
      userEvent: "input.type",
    });

    expect(applyTransaction(harness.bridge, transaction)).toMatchObject({
      applied: true,
      text: "首段。",
    });
    expect(harness.onDocChanged).toHaveBeenCalledOnce();
    expect(harness.onDocChanged).toHaveBeenCalledWith({
      lease: LEASE,
      nextValue: "首段。",
      origin: "input",
      composing: false,
    });
  });

  it("does not save for selection-only or decoration-only transactions", () => {
    const harness = createHarness("第一段。");
    let state = createCodeMirrorNarrationState("第一段。", harness.bridge);
    const selection = state.update({ selection: { anchor: 1, head: 3 } });
    expect(applyTransaction(harness.bridge, selection)).toBeNull();
    state = selection.state;
    expect(harness.bridge.readSnapshot().selection).toEqual({
      startUtf16: 1,
      endUtf16: 3,
      direction: "forward",
    });

    const decoration = state.update({
      effects: codeMirrorNarrationEffect({ startUtf16: 1, endUtf16: 3 }),
    });
    expect(applyTransaction(harness.bridge, decoration)).toBeNull();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("keeps one save per AI apply, undo and external replacement while allowing exact selection restoration", () => {
    const harness = createHarness("旧稿第一段。", {
      startUtf16: 2, endUtf16: 5, direction: "backward",
    });
    let state = createCodeMirrorNarrationState("旧稿第一段。", harness.bridge);
    const replacements = [
      { origin: "ai-apply", text: "新稿改写的段落。", anchor: 7, head: 2 },
      { origin: "ai-undo", text: "旧稿第一段。", anchor: 5, head: 2 },
      { origin: "external", text: "同步后的段落。", anchor: 0, head: 2 },
    ] as const;

    for (const [index, replacement] of replacements.entries()) {
      const transaction = state.update(codeMirrorValueReplacement(state, replacement.text, replacement.origin)!);
      expect(applyTransaction(harness.bridge, transaction)?.applied).toBe(true);
      state = transaction.state;
      const restored = state.update({
        selection: { anchor: replacement.anchor, head: replacement.head },
        annotations: codeMirrorNarrationPresentationAnnotation(),
      });
      expect(applyTransaction(harness.bridge, restored)).toBeNull();
      state = restored.state;
      expect(harness.bridge.readSnapshot().selection).toEqual(selectionFromCodeMirror(state));
      expect(state.selection.main.anchor).toBe(replacement.anchor);
      expect(state.selection.main.head).toBe(replacement.head);
      expect(harness.onDocChanged).toHaveBeenCalledTimes(index + 1);
      expect(harness.onDocChanged).toHaveBeenLastCalledWith({
        lease: LEASE,
        nextValue: replacement.text,
        origin: replacement.origin,
        composing: false,
      });
    }
  });

  it("recognizes public undo, redo, and composition user events", () => {
    const state = EditorState.create({ doc: "甲" });
    const undoTransaction = state.update({ annotations: Transaction.userEvent.of("undo") });
    const redoTransaction = state.update({ annotations: Transaction.userEvent.of("redo") });
    const compositionTransaction = state.update({
      annotations: Transaction.userEvent.of("input.type.compose"),
    });

    expect(codeMirrorTransactionOrigin([undoTransaction], false)).toBe("undo");
    expect(codeMirrorTransactionOrigin([redoTransaction], false)).toBe("redo");
    expect(codeMirrorTransactionOrigin([compositionTransaction], false)).toBe("composition");
  });

  it("routes undo and redo document changes through exactly one bridge callback each", () => {
    const harness = createHarness("甲");
    let state = createCodeMirrorNarrationState("甲", harness.bridge);
    const undoTransaction = state.update({
      changes: { from: 1, insert: "乙" },
      annotations: Transaction.userEvent.of("undo"),
    });
    applyTransaction(harness.bridge, undoTransaction);
    state = undoTransaction.state;
    const redoTransaction = state.update({
      changes: { from: 1, to: 2 },
      annotations: Transaction.userEvent.of("redo"),
    });
    applyTransaction(harness.bridge, redoTransaction);

    expect(harness.onDocChanged).toHaveBeenCalledTimes(2);
    expect(harness.onDocChanged.mock.calls.map(([event]) => event.origin)).toEqual([
      "undo",
      "redo",
    ]);
  });

  it("marks composition events as composing and closes the bridge after the final update", () => {
    const harness = createHarness("甲");
    let state = createCodeMirrorNarrationState("甲", harness.bridge);
    const composing = state.update({
      changes: { from: 1, insert: "乙" },
      annotations: Transaction.userEvent.of("input.type.compose"),
    });
    applyTransaction(harness.bridge, composing, true);
    expect(harness.onDocChanged).toHaveBeenCalledWith(expect.objectContaining({
      origin: "composition",
      composing: true,
    }));
    expect(harness.bridge.readSnapshot().composing).toBe(true);

    state = composing.state;
    const compositionEnd = state.update({ selection: { anchor: 2 } });
    applyTransaction(harness.bridge, compositionEnd, false);
    expect(harness.bridge.readSnapshot().composing).toBe(false);
    expect(harness.onDocChanged).toHaveBeenCalledTimes(1);
  });

  it("fails a stale CodeMirror update closed before the save callback", () => {
    const harness = createHarness("甲");
    const state = createCodeMirrorNarrationState("甲", harness.bridge);
    const transaction = state.update({ changes: { from: 1, insert: "乙" } });
    harness.setCurrentLease({ documentId: LEASE.documentId, generation: LEASE.generation + 1 });

    expect(applyTransaction(harness.bridge, transaction)).toMatchObject({
      applied: false,
      inactiveReason: "stale_generation",
      text: "甲",
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});


describe("CodeMirror author interaction and seek isolation", () => {
  it("dispatches only explicit non-composing, non-repeat paragraph commands", () => {
    const onCommand = vi.fn(() => true);
    expect(dispatchCodeMirrorKeyboardPlaybackCommand(
      { key: "Enter", metaKey: true, altKey: true },
      7,
      onCommand,
    )).toBe(true);
    expect(onCommand).toHaveBeenLastCalledWith({
      source: "keyboard",
      event: { key: "Enter", metaKey: true, altKey: true },
      lookup: { positionUtf16: 7 },
    });
    expect(dispatchCodeMirrorKeyboardPlaybackCommand(
      { key: "Enter", metaKey: true, altKey: true, repeat: true },
      7,
      onCommand,
    )).toBe(false);
    expect(dispatchCodeMirrorKeyboardPlaybackCommand(
      { key: "Enter", metaKey: true, altKey: true, isComposing: true },
      7,
      onCommand,
    )).toBe(false);
    expect(dispatchCodeMirrorContextPlaybackCommand(9, true, onCommand)).toBe(false);
    expect(dispatchCodeMirrorContextPlaybackCommand(9, false, onCommand)).toBe(true);
    expect(onCommand).toHaveBeenLastCalledWith({
      source: "context-menu",
      lookup: { positionUtf16: 9 },
    });
    expect(onCommand).toHaveBeenCalledTimes(2);
  });

  it("classifies input, IME, selection, and caret movement without inventing writes", () => {
    const harness = createHarness("甲乙");
    let state = createCodeMirrorNarrationState("甲乙", harness.bridge);
    const input = state.update({
      changes: { from: 2, insert: "丙" },
      annotations: Transaction.userEvent.of("input.type"),
    });
    expect(codeMirrorAuthorInteraction(bridgeUpdate(input))).toBe("input");
    state = input.state;
    const composition = state.update({
      changes: { from: 3, insert: "丁" },
      annotations: Transaction.userEvent.of("input.type.compose"),
    });
    expect(codeMirrorAuthorInteraction(bridgeUpdate(composition, true))).toBe("composition");

    state = composition.state;
    const selection = state.update({ selection: { anchor: 0, head: 2 } });
    expect(codeMirrorAuthorInteraction(bridgeUpdate(selection))).toBe("selection");
    state = selection.state;
    const caret = state.update({ selection: { anchor: 3 } });
    expect(codeMirrorAuthorInteraction(bridgeUpdate(caret))).toBe("caret-move");
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("does not treat a presentation selection as an author interruption", () => {
    const harness = createHarness("甲乙");
    const state = createCodeMirrorNarrationState("甲乙", harness.bridge);
    const presentation = state.update({
      selection: { anchor: 0, head: 2 },
      annotations: codeMirrorNarrationPresentationAnnotation(),
    });
    expect(codeMirrorAuthorInteraction(bridgeUpdate(presentation))).toBeNull();
    expect(applyTransaction(harness.bridge, presentation)).toBeNull();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("keeps an ordinary editor click selection-only and never requests playback", () => {
    const harness = createHarness("第一段。");
    expect(harness.bridge.bindEdition({
      lease: LEASE,
      editionId: "edition-cm",
      sourceRevisionId: "revision-cm",
      sourceContentHash: HASH,
      segments: [{
        segmentId: "segment-cm",
        sourceBlockKey: "paragraph-1",
        sourceText: "第一段。",
        sourceRange: { startUtf16: 0, endUtf16: 4 },
      }],
    })).toEqual({ applied: true });
    const playback = vi.fn();
    harness.bridge.registerPlaybackIntent(playback);
    const state = createCodeMirrorNarrationState("第一段。", harness.bridge);
    const ordinaryClick = state.update({ selection: { anchor: 2 } });

    expect(codeMirrorAuthorInteraction(bridgeUpdate(ordinaryClick))).toBe("caret-move");
    expect(applyTransaction(harness.bridge, ordinaryClick)).toBeNull();
    expect(playback).not.toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});
