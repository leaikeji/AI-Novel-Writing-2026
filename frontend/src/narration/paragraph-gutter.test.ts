import { describe, expect, it, vi } from "vitest";

import {
  ProductionNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationSourceSegment,
} from "./editor-bridge";
import {
  ProductionParagraphGutterController,
  isGutterButtonActivationKey,
  isNarrationSeekKeyboardCommand,
  type NarrationParagraphDescriptor,
} from "./paragraph-gutter";
import { playbackLeasesEqual, type PlaybackLease } from "./segment-playback-queue";


const DOCUMENT_LEASE: DocumentLease = { documentId: "doc-1", generation: 6 };
const EDITION_ID = "edition-1";
const SOURCE_HASH = "a".repeat(64);
const TEXT = "第一章\n第一段。第二句。\n第二段。";


function locate(sourceText: string): { startUtf16: number; endUtf16: number } {
  const startUtf16 = TEXT.indexOf(sourceText);
  if (startUtf16 < 0) throw new Error(`fixture text not found: ${sourceText}`);
  return { startUtf16, endUtf16: startUtf16 + sourceText.length };
}


function sourceSegment(
  segmentId: string,
  sourceBlockKey: string,
  sourceText: string,
): NarrationSourceSegment {
  return { segmentId, sourceBlockKey, sourceText, sourceRange: locate(sourceText) };
}


function paragraph(
  paragraphOrdinal: number,
  sourceBlockKey: string,
  sourceText: string,
  narratable = true,
): NarrationParagraphDescriptor {
  return { paragraphOrdinal, sourceBlockKey, range: locate(sourceText), narratable };
}


function createHarness(kind: "codemirror6" | "textarea-fallback" = "codemirror6") {
  let currentDocumentLease = DOCUMENT_LEASE;
  let currentPlaybackLease: PlaybackLease = {
    documentId: DOCUMENT_LEASE.documentId,
    documentGeneration: DOCUMENT_LEASE.generation,
    editionId: EDITION_ID,
    manifestRevision: 7,
    requestGeneration: 2,
  };
  let expectedPlaybackLease = currentPlaybackLease;
  const onDocChanged = vi.fn();
  const bridge = new ProductionNarrationEditorBridge({
    kind,
    lease: DOCUMENT_LEASE,
    text: TEXT,
    currentContentHash: SOURCE_HASH,
    onDocChanged,
    isLeaseCurrent: (lease) => documentLeasesEqual(lease, currentDocumentLease),
  });
  bridge.bindEdition({
    lease: DOCUMENT_LEASE,
    editionId: EDITION_ID,
    sourceRevisionId: "revision-1",
    sourceContentHash: SOURCE_HASH,
    segments: [
      sourceSegment("segment-1", "paragraph-1", "第一段。"),
      sourceSegment("segment-2", "paragraph-1", "第二句。"),
      sourceSegment("segment-3", "paragraph-2", "第二段。"),
    ],
  });
  const intents = vi.fn();
  bridge.registerPlaybackIntent(intents);
  const controller = new ProductionParagraphGutterController({
    bridge,
    editionId: EDITION_ID,
    paragraphs: [
      paragraph(0, "title", "第一章", false),
      paragraph(1, "paragraph-1", "第一段。第二句。"),
      paragraph(2, "paragraph-2", "第二段。"),
    ],
    readPlaybackLease: () => currentPlaybackLease,
    isPlaybackLeaseCurrent: (lease) => playbackLeasesEqual(lease, expectedPlaybackLease),
  });
  return {
    bridge,
    controller,
    intents,
    onDocChanged,
    replaceDocumentLease(next: DocumentLease) { currentDocumentLease = next; },
    replacePlaybackLease(patch: Partial<PlaybackLease>) {
      currentPlaybackLease = Object.freeze({ ...currentPlaybackLease, ...patch });
    },
    replaceExpectedPlaybackLease(patch: Partial<PlaybackLease>) {
      expectedPlaybackLease = Object.freeze({ ...expectedPlaybackLease, ...patch });
    },
  };
}


describe("paragraph gutter models", () => {
  it("builds explicit, accessible buttons and starts a multi-sentence paragraph at its first segment", () => {
    const harness = createHarness();
    expect(harness.controller.listButtons()).toEqual([
      expect.objectContaining({
        paragraphOrdinal: 0,
        availability: "not_narratable",
        disabled: true,
        ariaLabel: "从第 1 段朗读",
        title: "此段没有可朗读内容。",
      }),
      expect.objectContaining({
        paragraphOrdinal: 1,
        targetSegmentId: "segment-1",
        availability: "available",
        disabled: false,
        ariaLabel: "从第 2 段朗读",
      }),
      expect.objectContaining({
        paragraphOrdinal: 2,
        targetSegmentId: "segment-3",
        availability: "available",
        disabled: false,
      }),
    ]);
  });

  it("marks only an invalidated working-copy block as update-required", () => {
    const harness = createHarness();
    const range = locate("第一段。");
    harness.bridge.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: range.startUtf16 + 1,
        endUtf16: range.startUtf16 + 1,
        insertedText: "新",
      }],
    });

    expect(harness.controller.listButtons()[1]).toMatchObject({
      availability: "update_required",
      disabled: true,
      targetSegmentId: null,
      title: "本段已变化，请更新朗读后再播放。",
    });
    expect(harness.controller.listButtons()[2]).toMatchObject({
      availability: "available",
      targetSegmentId: "segment-3",
    });
  });

  it("does not fake an editable gutter in textarea fallback", () => {
    const harness = createHarness("textarea-fallback");
    expect(harness.controller.listButtons()[1]).toMatchObject({
      availability: "editor_gutter_unavailable",
      disabled: true,
      title: "当前编辑器请使用“从光标所在段朗读”。",
    });
    expect(harness.controller.requestFromGutter(1)).toMatchObject({
      handled: false,
      reason: "editor_gutter_unavailable",
    });
    expect(harness.controller.requestFromContextMenu({ positionUtf16: locate("第二段。").startUtf16 }))
      .toMatchObject({ handled: true, intentResult: { accepted: true } });
  });
});


describe("explicit paragraph playback gestures", () => {
  it("emits gutter, context-menu, and keyboard commands with their frozen sources", () => {
    const harness = createHarness();
    expect(harness.controller.requestFromGutter(1)).toMatchObject({
      handled: true,
      fence: { manifestRevision: 7, requestGeneration: 2 },
      intentResult: {
        accepted: true,
        intent: { source: "gutter", segmentId: "segment-1" },
      },
    });
    expect(harness.controller.requestFromContextMenu({ segmentId: "segment-2" }))
      .toMatchObject({
        handled: true,
        intentResult: {
          accepted: true,
          intent: { source: "command", segmentId: "segment-2" },
        },
      });
    expect(harness.controller.requestFromKeyboard(
      { key: "Enter", ctrlKey: true, altKey: true },
      { positionUtf16: locate("第二段。").startUtf16 },
    )).toMatchObject({
      handled: true,
      intentResult: { accepted: true, intent: { source: "command", segmentId: "segment-3" } },
    });
    expect(harness.intents).toHaveBeenCalledTimes(3);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("supports Enter and Space on a focused gutter button but ignores unrelated keys", () => {
    const harness = createHarness();
    expect(harness.controller.requestFromGutterKeyboard(2, { key: "Enter" }))
      .toMatchObject({ handled: true, intentResult: { accepted: true } });
    expect(harness.controller.requestFromGutterKeyboard(2, { key: " " }))
      .toMatchObject({ handled: true, intentResult: { accepted: true } });
    expect(harness.controller.requestFromGutterKeyboard(2, { key: "ArrowDown" }))
      .toMatchObject({ handled: false, reason: "unsupported_key" });
    expect(harness.controller.requestFromGutterKeyboard(2, { key: "Enter", isComposing: true }))
      .toMatchObject({ handled: false, reason: "unsupported_key" });
  });

  it("keeps ordinary text clicks caret-only and produces zero save callbacks", () => {
    const harness = createHarness();
    expect(harness.controller.requestOrdinaryEditorClick({ positionUtf16: 10 })).toEqual({
      accepted: false,
      reason: "editor_click_moves_caret_only",
    });
    expect(harness.intents).not.toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("fails closed for non-narratable, missing, disposed, and stale full scopes", () => {
    const harness = createHarness();
    expect(harness.controller.requestFromGutter(0)).toMatchObject({
      handled: false,
      reason: "not_narratable",
    });
    expect(harness.controller.requestFromGutter(99)).toMatchObject({
      handled: false,
      reason: "paragraph_not_found",
    });

    harness.replaceExpectedPlaybackLease({ manifestRevision: 8 });
    expect(harness.controller.requestFromContextMenu({ segmentId: "segment-1" }))
      .toMatchObject({ handled: false, reason: "stale_scope" });
    harness.replaceExpectedPlaybackLease({ manifestRevision: 7, requestGeneration: 3 });
    expect(harness.controller.requestFromContextMenu({ segmentId: "segment-1" }))
      .toMatchObject({ handled: false, reason: "stale_scope" });

    harness.controller.dispose();
    expect(harness.controller.listButtons().every((button) => button.availability === "stale_scope"))
      .toBe(true);
  });

  it("also rejects a changed document generation before issuing any intent", () => {
    const harness = createHarness();
    harness.replaceDocumentLease({ documentId: "doc-2", generation: 7 });
    harness.replacePlaybackLease({ documentId: "doc-2", documentGeneration: 7 });
    expect(harness.controller.requestFromContextMenu({ segmentId: "segment-1" }))
      .toMatchObject({ handled: false, reason: "stale_scope" });
    expect(harness.intents).not.toHaveBeenCalled();
  });
});


describe("keyboard command recognition", () => {
  it("uses an explicit Mod+Alt+Enter chord without intercepting IME or repeats", () => {
    expect(isNarrationSeekKeyboardCommand({ key: "Enter", ctrlKey: true, altKey: true }))
      .toBe(true);
    expect(isNarrationSeekKeyboardCommand({ key: "Enter", metaKey: true, altKey: true }))
      .toBe(true);
    expect(isNarrationSeekKeyboardCommand({ key: "Enter", ctrlKey: true })).toBe(false);
    expect(isNarrationSeekKeyboardCommand({
      key: "Enter",
      ctrlKey: true,
      altKey: true,
      isComposing: true,
    })).toBe(false);
    expect(isNarrationSeekKeyboardCommand({
      key: "Enter",
      ctrlKey: true,
      altKey: true,
      repeat: true,
    })).toBe(false);
    expect(isGutterButtonActivationKey({ key: " " })).toBe(true);
  });
});
