import { describe, expect, it, vi } from "vitest";

import {
  ProductionNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationEditorSelection,
  type NarrationSourceSegment,
} from "./editor-bridge";


const SOURCE_HASH = "a".repeat(64);
const SOURCE = "题记\n第一段。\n第二段“你好🙂！”\n第三段结束。";
const LEASE: DocumentLease = { documentId: "document-1", generation: 7 };


function segment(
  segmentId: string,
  sourceBlockKey: string,
  sourceText: string,
  text = SOURCE,
): NarrationSourceSegment {
  const startUtf16 = text.indexOf(sourceText);
  if (startUtf16 < 0) throw new Error(`fixture segment not found: ${sourceText}`);
  return {
    segmentId,
    sourceBlockKey,
    sourceText,
    sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
  };
}


function segments(text = SOURCE): readonly NarrationSourceSegment[] {
  return [
    segment("segment-1", "block-1", "第一段。", text),
    segment("segment-2", "block-2", "第二段“你好🙂！”", text),
    segment("segment-3", "block-3", "第三段结束。", text),
  ];
}


function createHarness(options: {
  kind?: "codemirror6" | "textarea-fallback";
  text?: string;
  currentContentHash?: string;
  selection?: NarrationEditorSelection;
} = {}) {
  let currentLease: DocumentLease = LEASE;
  const onDocChanged = vi.fn();
  const bridge = new ProductionNarrationEditorBridge({
    kind: options.kind ?? "codemirror6",
    lease: LEASE,
    text: options.text ?? SOURCE,
    currentContentHash: options.currentContentHash ?? SOURCE_HASH,
    selection: options.selection,
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


function bind(
  bridge: ProductionNarrationEditorBridge,
  sourceSegments = segments(),
  sourceContentHash = SOURCE_HASH,
) {
  return bridge.bindEdition({
    lease: LEASE,
    editionId: "edition-1",
    sourceRevisionId: "revision-1",
    sourceContentHash,
    segments: sourceSegments,
  });
}


function guard() {
  return { lease: LEASE, editionId: "edition-1" } as const;
}


function mappedRange(bridge: ProductionNarrationEditorBridge, segmentId: string) {
  const mapping = bridge.mappingFor(segmentId, guard());
  if (mapping?.state !== "mapped") throw new Error(`${segmentId} is not mapped`);
  return mapping.currentRange;
}


describe("ProductionNarrationEditorBridge UTF-16 mapping", () => {
  it("uses strict JavaScript UTF-16 offsets for emoji and combining characters", () => {
    const text = "甲🙂e\u0301乙。";
    const sourceText = "🙂e\u0301";
    const harness = createHarness({ text });
    expect(harness.bridge.bindEdition({
      lease: LEASE,
      editionId: "edition-1",
      sourceRevisionId: "revision-1",
      sourceContentHash: SOURCE_HASH,
      segments: [segment("unicode", "unicode-block", sourceText, text)],
    })).toEqual({ applied: true });

    expect(sourceText.length).toBe(4);
    expect(mappedRange(harness.bridge, "unicode")).toEqual({ startUtf16: 1, endUtf16: 5 });
    expect(harness.bridge.resolvePlaybackTarget(guard(), {
      range: { startUtf16: 1, endUtf16: 5 },
    })).toBe("unicode");
  });

  it("rejects a segment range that splits a surrogate pair", () => {
    const text = "甲🙂乙";
    const harness = createHarness({ text });
    expect(() => harness.bridge.bindEdition({
      lease: LEASE,
      editionId: "edition-1",
      sourceRevisionId: "revision-1",
      sourceContentHash: SOURCE_HASH,
      segments: [{
        segmentId: "broken",
        sourceBlockKey: "block",
        sourceText: "🙂",
        sourceRange: { startUtf16: 2, endUtf16: 4 },
      }],
    })).toThrow("must not split a UTF-16 surrogate pair");
  });

  it("rejects malformed UTF-16 insertions before notifying the save chain", () => {
    const harness = createHarness();
    bind(harness.bridge);
    expect(() => harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "\ud800" }],
    })).toThrow("unpaired UTF-16 high surrogate");
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});


describe("mapping and the sole docChanged callback", () => {
  it("maps untouched ranges and emits one fenced document event", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const before = mappedRange(harness.bridge, "segment-1");
    const report = harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "序" }],
    });

    expect(report.applied).toBe(true);
    expect(report.invalidated).toEqual({});
    expect(mappedRange(harness.bridge, "segment-1")).toEqual({
      startUtf16: before.startUtf16 + 1,
      endUtf16: before.endUtf16 + 1,
    });
    expect(harness.onDocChanged).toHaveBeenCalledOnce();
    expect(harness.onDocChanged).toHaveBeenCalledWith({
      lease: LEASE,
      nextValue: `序${SOURCE}`,
      origin: "input",
      composing: false,
    });
  });

  it("invalidates a touched block and boundary-adjacent blocks conservatively", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const second = mappedRange(harness.bridge, "segment-2");
    const report = harness.bridge.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: second.startUtf16 + 3,
        endUtf16: second.startUtf16 + 3,
        insertedText: "！",
      }],
    });

    expect(report.invalidated).toEqual({
      "segment-1": "boundary_adjacent",
      "segment-2": "transaction_intersection",
      "segment-3": "boundary_adjacent",
    });
  });

  it("does not notify for selection, decoration, scroll, focus-equivalent, or seek work", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const presentation = vi.fn();
    harness.bridge.registerPresentationListener(presentation);

    harness.bridge.setSelection({ startUtf16: 1, endUtf16: 1, direction: "none" });
    harness.bridge.focusSelection({ startUtf16: 1, endUtf16: 2, direction: "forward" });
    harness.bridge.markCurrentSegment({ ...guard(), segmentId: "segment-2" });
    harness.bridge.scrollCurrentSegmentIntoView(guard());
    harness.bridge.noteManualScroll();
    harness.bridge.resumeAutoFollow();
    harness.bridge.requestPlayback({
      ...guard(),
      source: "command",
      lookup: { segmentId: "segment-2" },
    });
    harness.bridge.clearCurrentSegment(guard());

    expect(presentation).toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("does not let playback or integration focus steal focus during composition", () => {
    const harness = createHarness();
    const presentation = vi.fn();
    harness.bridge.registerPresentationListener(presentation);
    harness.bridge.beginComposition();
    expect(harness.bridge.focusSelection({
      startUtf16: 1,
      endUtf16: 1,
      direction: "none",
    })).toEqual({ applied: false, reason: "composition" });
    expect(presentation).not.toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("does not emit a document event for an empty transaction", () => {
    const harness = createHarness();
    bind(harness.bridge);
    expect(harness.bridge.applyTransaction({ origin: "external", changes: [] }).applied).toBe(true);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});


describe("playback intent and follow safety", () => {
  it("keeps ordinary editor clicks caret-only and emits only explicit intents", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const listener = vi.fn();
    harness.bridge.registerPlaybackIntent(listener);

    expect(harness.bridge.requestPlayback({
      ...guard(),
      source: "editor-click",
      lookup: { segmentId: "segment-2" },
    })).toEqual({ accepted: false, reason: "editor_click_moves_caret_only" });
    expect(listener).not.toHaveBeenCalled();

    expect(harness.bridge.requestPlayback({
      ...guard(),
      source: "gutter",
      lookup: { sourceBlockKey: "block-2" },
    })).toMatchObject({
      accepted: true,
      intent: {
        lease: LEASE,
        editionId: "edition-1",
        source: "gutter",
        segmentId: "segment-2",
      },
    });
    expect(listener).toHaveBeenCalledOnce();
  });

  it("allows an immutable old-edition row after working-copy mapping is lost", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const second = mappedRange(harness.bridge, "segment-2");
    harness.bridge.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: second.startUtf16 + 1,
        endUtf16: second.startUtf16 + 1,
        insertedText: "改",
      }],
    });

    expect(harness.bridge.requestPlayback({
      ...guard(),
      source: "gutter",
      lookup: { segmentId: "segment-2" },
    })).toEqual({ accepted: false, reason: "unmapped_target" });
    expect(harness.bridge.requestPlayback({
      ...guard(),
      source: "readonly-segment",
      lookup: { segmentId: "segment-2" },
    })).toMatchObject({ accepted: true, intent: { segmentId: "segment-2" } });
  });

  it("coalesces composition follow to the latest segment and applies it after composition", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const presentation = vi.fn();
    harness.bridge.registerPresentationListener(presentation);
    harness.bridge.beginComposition();

    expect(harness.bridge.markCurrentSegment({ ...guard(), segmentId: "segment-1" }))
      .toEqual({ applied: false, reason: "composition" });
    expect(harness.bridge.scrollCurrentSegmentIntoView(guard()))
      .toEqual({ applied: false, reason: "composition" });
    expect(harness.bridge.markCurrentSegment({ ...guard(), segmentId: "segment-2" }))
      .toEqual({ applied: false, reason: "composition" });
    expect(presentation).not.toHaveBeenCalled();

    expect(harness.bridge.endComposition()).toEqual({ applied: true, segmentId: "segment-2" });
    expect(presentation.mock.calls.map(([event]) => event.type)).toEqual([
      "current-segment",
      "scroll-current-segment",
    ]);
    expect(presentation.mock.calls[0][0]).toMatchObject({ segmentId: "segment-2" });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("pauses auto-follow after manual scrolling", () => {
    const harness = createHarness();
    bind(harness.bridge);
    harness.bridge.markCurrentSegment({ ...guard(), segmentId: "segment-2" });
    harness.bridge.noteManualScroll();
    expect(harness.bridge.scrollCurrentSegmentIntoView(guard()))
      .toEqual({ applied: false, reason: "manual_scroll" });
    expect(harness.bridge.lastRequestedScrollSegment()).toBeNull();
  });
});


describe("DocumentLease and lifecycle fencing", () => {
  it("fails every stale-generation mutation closed without callbacks", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const presentation = vi.fn();
    const playback = vi.fn();
    harness.bridge.registerPresentationListener(presentation);
    harness.bridge.registerPlaybackIntent(playback);
    harness.setCurrentLease({ documentId: LEASE.documentId, generation: LEASE.generation + 1 });

    expect(harness.bridge.readSnapshot()).toMatchObject({
      active: false,
      inactiveReason: "stale_generation",
    });
    expect(harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "旧" }],
    })).toMatchObject({ applied: false, inactiveReason: "stale_generation", text: SOURCE });
    expect(harness.bridge.markCurrentSegment({ ...guard(), segmentId: "segment-1" }))
      .toEqual({ applied: false, reason: "stale_generation" });
    expect(harness.bridge.requestPlayback({
      ...guard(),
      source: "command",
      lookup: { segmentId: "segment-1" },
    })).toEqual({ accepted: false, reason: "stale_generation" });
    expect(harness.bridge.mappingFor("segment-1")).toBeNull();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
    expect(presentation).not.toHaveBeenCalled();
    expect(playback).not.toHaveBeenCalled();
  });

  it("rejects an explicitly mismatched guard even while its own lease is current", () => {
    const harness = createHarness();
    bind(harness.bridge);
    expect(harness.bridge.markCurrentSegment({
      lease: { documentId: LEASE.documentId, generation: LEASE.generation - 1 },
      editionId: "edition-1",
      segmentId: "segment-1",
    })).toEqual({ applied: false, reason: "stale_generation" });
  });

  it("dispose is idempotent and permanently suppresses writes and listeners", () => {
    const harness = createHarness();
    bind(harness.bridge);
    const playback = vi.fn();
    harness.bridge.registerPlaybackIntent(playback);
    harness.bridge.dispose();
    harness.bridge.dispose();

    expect(harness.bridge.readSnapshot()).toMatchObject({ active: false, inactiveReason: "disposed" });
    expect(harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "旧" }],
    })).toMatchObject({ applied: false, inactiveReason: "disposed" });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
    expect(playback).not.toHaveBeenCalled();
  });
});


describe("textarea fallback capability truthfulness", () => {
  it("does not claim editable decoration or gutter seek", () => {
    const harness = createHarness({ kind: "textarea-fallback" });
    bind(harness.bridge);
    expect(harness.bridge.capabilities).toEqual({
      editableDecorations: false,
      paragraphGutter: false,
      exactSegmentMapping: true,
    });
    expect(harness.bridge.requestPlayback({
      ...guard(),
      source: "gutter",
      lookup: { segmentId: "segment-1" },
    })).toEqual({ accepted: false, reason: "unsupported_surface" });
    harness.bridge.markCurrentSegment({ ...guard(), segmentId: "segment-1" });
    expect(harness.bridge.scrollCurrentSegmentIntoView(guard()))
      .toEqual({ applied: false, reason: "unsupported_capability" });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("fails mappings closed when the working-copy hash differs", () => {
    const harness = createHarness({ currentContentHash: "b".repeat(64) });
    bind(harness.bridge);
    expect(harness.bridge.mappingFor("segment-1", guard())).toEqual({
      segmentId: "segment-1",
      sourceBlockKey: "block-1",
      state: "invalidated",
      currentRange: null,
      reason: "source_diverged",
    });
  });
});
