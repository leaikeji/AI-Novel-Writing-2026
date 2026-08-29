import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ProductionChapterPlaybackCoordinator,
} from "./chapter-playback";
import {
  deriveChapterNarrationState,
} from "./chapter-narration-state";
import {
  ProductionNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationEditorPresentationEvent,
  type NarrationSourceSegment,
} from "./editor-bridge";
import {
  EDITION_HISTORY_CONTRACT_VERSION,
  parseDocumentEditionHistory,
} from "./edition-history";
import type {
  NarrationPlayerState,
  NarrationPlaybackSource,
  PlaybackDecision,
} from "./narration-player";
import {
  ProductionParagraphGutterController,
  type NarrationParagraphDescriptor,
} from "./paragraph-gutter";
import type { NarrationManifestV2 } from "./playback-contracts";
import {
  ProductionSegmentFollowController,
  type FollowAwareNarrationPlayerController,
} from "./segment-follow";
import type { PlaybackLease } from "./segment-playback-queue";


const DOCUMENT_ID = "20000000-0000-4000-8000-000000000001";
const EDITION_ID = "10000000-0000-4000-8000-000000000001";
const REQUEST_ID = "50000000-0000-4000-8000-000000000001";
const REVISION_ID = "30000000-0000-4000-8000-000000000001";
const SEGMENT_1 = "40000000-0000-4000-8000-000000000001";
const SEGMENT_2 = "40000000-0000-4000-8000-000000000002";
const SOURCE_HASH = "a".repeat(64);
const DIVERGED_HASH = "b".repeat(64);
const TEXT = "第一章\n第一段。\n第二段。";
const LEASE: DocumentLease = { documentId: DOCUMENT_ID, generation: 6 };


function locate(sourceText: string) {
  const startUtf16 = TEXT.indexOf(sourceText);
  if (startUtf16 < 0) throw new Error(`missing fixture text: ${sourceText}`);
  return Object.freeze({ startUtf16, endUtf16: startUtf16 + sourceText.length });
}


function sourceSegments(): readonly NarrationSourceSegment[] {
  return [
    {
      segmentId: SEGMENT_1,
      sourceBlockKey: "paragraph-1",
      sourceText: "第一段。",
      sourceRange: locate("第一段。"),
    },
    {
      segmentId: SEGMENT_2,
      sourceBlockKey: "paragraph-2",
      sourceText: "第二段。",
      sourceRange: locate("第二段。"),
    },
  ];
}


function paragraphs(): readonly NarrationParagraphDescriptor[] {
  return [
    {
      paragraphOrdinal: 0,
      sourceBlockKey: "title",
      range: locate("第一章"),
      narratable: false,
    },
    {
      paragraphOrdinal: 1,
      sourceBlockKey: "paragraph-1",
      range: locate("第一段。"),
      narratable: true,
    },
    {
      paragraphOrdinal: 2,
      sourceBlockKey: "paragraph-2",
      range: locate("第二段。"),
      narratable: true,
    },
  ];
}


function playerState(patch: Partial<NarrationPlayerState> = {}): NarrationPlayerState {
  return Object.freeze({
    phase: "idle",
    currentSegmentId: null,
    currentOrdinal: null,
    offsetMs: 0,
    durationMs: 0,
    rate: 1,
    volume: 1,
    followPaused: false,
    backend: null,
    source: null,
    failure: null,
    ...patch,
  });
}


class IntegratedFakePlayer implements FollowAwareNarrationPlayerController {
  private currentLease: PlaybackLease = Object.freeze({
    documentId: DOCUMENT_ID,
    documentGeneration: LEASE.generation,
    editionId: EDITION_ID,
    manifestRevision: 4,
    requestGeneration: 0,
  });
  private state = playerState();
  private readonly listeners = new Set<(state: NarrationPlayerState) => void>();
  readonly operations: Array<Readonly<{
    segmentId: string;
    source: NarrationPlaybackSource;
    lease: PlaybackLease;
  }>> = [];

  get lease(): PlaybackLease { return this.currentLease; }
  readState(): NarrationPlayerState { return this.state; }
  bindManifest(_manifest: NarrationManifestV2): void {}

  async playFromSegment(
    segmentId: string,
    source: NarrationPlaybackSource,
  ): Promise<PlaybackDecision> {
    this.currentLease = Object.freeze({
      ...this.currentLease,
      requestGeneration: this.currentLease.requestGeneration + 1,
    });
    const lease = this.currentLease;
    const ordinal = segmentId === SEGMENT_1 ? 0 : 1;
    this.operations.push(Object.freeze({ segmentId, source, lease }));
    this.state = playerState({
      phase: "playing",
      currentSegmentId: segmentId,
      currentOrdinal: ordinal,
      durationMs: 1_200,
      backend: "web-audio",
      source,
      followPaused: this.state.followPaused,
    });
    this.emit();
    return Object.freeze({
      kind: "play",
      lease,
      segmentId,
      ordinal,
      backend: "web-audio",
    });
  }

  pause(): void {
    this.state = playerState({ ...this.state, phase: "paused" });
    this.emit();
  }

  async resume(): Promise<PlaybackDecision> {
    return Object.freeze({ kind: "noop", lease: this.currentLease, reason: "not_paused" });
  }

  setRate(rate: number): void {
    this.state = playerState({ ...this.state, rate });
    this.emit();
  }

  setVolume(volume: number): void {
    this.state = playerState({ ...this.state, volume });
    this.emit();
  }

  setFollowPaused(paused: boolean): void {
    this.state = playerState({ ...this.state, followPaused: paused });
    this.emit();
  }

  updateManifest(_manifest: NarrationManifestV2): void {}

  subscribe(listener: (state: NarrationPlayerState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose(): void {
    this.listeners.clear();
  }

  publishSegment(segmentId: string): void {
    this.state = playerState({
      ...this.state,
      phase: "playing",
      currentSegmentId: segmentId,
      currentOrdinal: segmentId === SEGMENT_1 ? 0 : 1,
      durationMs: 1_200,
    });
    this.emit();
  }

  private emit(): void {
    for (const listener of [...this.listeners]) listener(this.state);
  }
}


function createHarness() {
  let currentLease = LEASE;
  const onDocChanged = vi.fn();
  const bridge = new ProductionNarrationEditorBridge({
    kind: "codemirror6",
    lease: LEASE,
    text: TEXT,
    currentContentHash: SOURCE_HASH,
    onDocChanged,
    isLeaseCurrent: (lease) => documentLeasesEqual(lease, currentLease),
  });
  expect(bridge.bindEdition({
    lease: LEASE,
    editionId: EDITION_ID,
    sourceRevisionId: REVISION_ID,
    sourceContentHash: SOURCE_HASH,
    segments: sourceSegments(),
  })).toEqual({ applied: true });
  const presentation: NarrationEditorPresentationEvent[] = [];
  bridge.registerPresentationListener((event) => presentation.push(event));
  const player = new IntegratedFakePlayer();
  const follow = new ProductionSegmentFollowController({
    bridge,
    player,
    editionId: EDITION_ID,
  });
  const results = vi.fn();
  const coordinator = new ProductionChapterPlaybackCoordinator({
    bridge,
    player,
    onResult: results,
  });
  const gutter = new ProductionParagraphGutterController({
    bridge,
    editionId: EDITION_ID,
    paragraphs: paragraphs(),
    readPlaybackLease: () => player.lease,
  });
  return {
    bridge,
    player,
    follow,
    coordinator,
    gutter,
    results,
    presentation,
    onDocChanged,
    replaceDocumentLease(next: DocumentLease) { currentLease = next; },
  };
}


function history() {
  return parseDocumentEditionHistory({
    contract_version: EDITION_HISTORY_CONTRACT_VERSION,
    document_id: DOCUMENT_ID,
    pointer_version: 3,
    current_edition_id: EDITION_ID,
    working_copy_content_hash: SOURCE_HASH,
    working_copy_draft_version: 4,
    editions: [{
      edition_id: EDITION_ID,
      request_id: REQUEST_ID,
      source_revision_id: REVISION_ID,
      source_content_hash: SOURCE_HASH,
      edition_fingerprint: "c".repeat(64),
      state: "ready",
      created_at: "2026-08-27T12:00:00Z",
      manifest_revision: 4,
      manifest_etag: `"${"d".repeat(64)}"`,
      ready_segment_count: 2,
      total_segment_count: 2,
      is_current: true,
      source_status: "current",
      rights_available: true,
      playable: true,
      default_start_ready: true,
      resume_available: true,
      switch_allowed: true,
    }],
  });
}


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("chapter narration input isolation", () => {
  it("keeps ordinary keys, clicks, selection, highlight, and follow free of TTS or body writes", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const harness = createHarness();

    for (const event of [
      { key: "a" },
      { key: "Enter" },
      { key: "ArrowDown" },
      { key: "Enter", ctrlKey: true, altKey: true, isComposing: true },
      { key: "Enter", ctrlKey: true, altKey: true, repeat: true },
    ]) {
      expect(harness.gutter.requestFromKeyboard(event, { segmentId: SEGMENT_1 }))
        .toMatchObject({ handled: false, reason: "unsupported_key" });
    }
    expect(harness.gutter.requestOrdinaryEditorClick({ segmentId: SEGMENT_1 }))
      .toEqual({ accepted: false, reason: "editor_click_moves_caret_only" });
    harness.bridge.setSelection({ startUtf16: 2, endUtf16: 2, direction: "none" });
    harness.bridge.markCurrentSegment({
      lease: LEASE,
      editionId: EDITION_ID,
      segmentId: SEGMENT_1,
    });
    harness.bridge.scrollCurrentSegmentIntoView({ lease: LEASE, editionId: EDITION_ID });
    expect(harness.follow.noteAuthorInteraction("selection")).toBe(true);
    expect(harness.follow.resumeExplicitly()).toBe(true);

    expect(harness.player.operations).toHaveLength(0);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();

    const report = harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "序" }],
    });
    expect(report.applied).toBe(true);
    expect(harness.onDocChanged).toHaveBeenCalledOnce();
    expect(harness.player.operations).toHaveLength(0);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("routes only an explicit seek to playback, then highlights and follows without saving", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const harness = createHarness();
    harness.bridge.setSelection({ startUtf16: 2, endUtf16: 2, direction: "none" });

    const action = harness.gutter.requestFromKeyboard(
      { key: "Enter", ctrlKey: true, altKey: true },
      { segmentId: SEGMENT_2 },
    );
    expect(action).toMatchObject({
      handled: true,
      intentResult: {
        accepted: true,
        intent: { source: "command", segmentId: SEGMENT_2 },
      },
    });
    expect(harness.player.operations).toEqual([
      expect.objectContaining({
        segmentId: SEGMENT_2,
        source: "command",
        lease: expect.objectContaining({ manifestRevision: 4, requestGeneration: 1 }),
      }),
    ]);
    await Promise.resolve();
    await Promise.resolve();
    expect(harness.results).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
    expect(harness.presentation).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "current-segment", segmentId: SEGMENT_2 }),
      expect.objectContaining({ type: "scroll-current-segment", segmentId: SEGMENT_2 }),
    ]));
    expect(harness.bridge.readSnapshot().selection).toEqual({
      startUtf16: 2,
      endUtf16: 2,
      direction: "none",
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    harness.presentation.length = 0;
    expect(harness.follow.noteAuthorInteraction("manual-scroll")).toBe(true);
    harness.player.publishSegment(SEGMENT_1);
    expect(harness.presentation.filter((event) => event.type === "scroll-current-segment"))
      .toHaveLength(0);
    expect(harness.follow.resumeExplicitly()).toBe(true);
    expect(harness.presentation).toContainEqual(
      expect.objectContaining({ type: "scroll-current-segment", segmentId: SEGMENT_1 }),
    );
    expect(harness.onDocChanged).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("keeps changed text on the editable draft and old audio on immutable subtitles", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const harness = createHarness();
    const second = locate("第二段。");
    const change = harness.bridge.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: second.startUtf16 + 1,
        endUtf16: second.startUtf16 + 1,
        insertedText: "新",
      }],
    });
    expect(change.invalidated[SEGMENT_2]).toBe("transaction_intersection");
    expect(harness.onDocChanged).toHaveBeenCalledOnce();
    harness.onDocChanged.mockClear();
    harness.presentation.length = 0;

    expect(harness.gutter.requestFromGutter(2)).toMatchObject({
      handled: true,
      intentResult: { accepted: false, reason: "unmapped_target" },
    });
    expect(harness.player.operations).toHaveLength(0);

    await expect(harness.coordinator.requestPlayback({
      source: "readonly-segment",
      lookup: { segmentId: SEGMENT_2 },
    })).resolves.toMatchObject({ status: "completed" });
    expect(harness.player.operations).toHaveLength(1);
    expect(harness.follow.readState().lastFailure).toBe("unmapped_segment");
    expect(harness.presentation.filter((event) => event.type === "current-segment"))
      .toHaveLength(0);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    const state = deriveChapterNarrationState({
      documentId: DOCUMENT_ID,
      generation: LEASE.generation,
      history: history(),
      workingCopy: {
        documentId: DOCUMENT_ID,
        generation: LEASE.generation,
        draftVersion: 4,
        contentHash: DIVERGED_HASH,
        saveState: "dirty",
      },
      reviewOpen: false,
      reviewSource: null,
      playback: {
        editionId: EDITION_ID,
        phase: "playing",
        currentSegmentId: SEGMENT_2,
        currentOrdinal: 1,
        offsetMs: 300,
        durationMs: 1_200,
        subtitle: {
          editionId: EDITION_ID,
          segmentId: SEGMENT_2,
          ordinal: 1,
          speakerLabel: "旁白",
          sourceText: "第二段。",
          spokenText: "第二段。",
        },
      },
      sessionMappedSegmentIds: new Set(),
    });
    expect(state.sourceStatus).toBe("working_copy_diverged");
    expect(state.timelineMode).toBe("immutable-edition-only");
    expect(state.canDecorateCurrentSegment).toBe(false);
    expect(state.subtitle).toMatchObject({ visible: true, oldDraft: true });
    expect(state.explicitUpdateRequired).toBe(true);
  });
});
