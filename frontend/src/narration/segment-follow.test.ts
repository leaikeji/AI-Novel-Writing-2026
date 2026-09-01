import { describe, expect, it, vi } from "vitest";

import {
  ProductionNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationEditorPresentationEvent,
  type NarrationSourceSegment,
} from "./editor-bridge";
import type {
  NarrationPlayerState,
  PlaybackDecision,
} from "./narration-player";
import type { NarrationManifestV2 } from "./playback-contracts";
import {
  ProductionSegmentFollowController,
  type FollowAwareNarrationPlayerController,
} from "./segment-follow";
import { playbackLeasesEqual, type PlaybackLease } from "./segment-playback-queue";


const DOCUMENT_LEASE: DocumentLease = { documentId: "doc-follow", generation: 9 };
const EDITION_ID = "edition-follow";
const SOURCE_HASH = "b".repeat(64);
const TEXT = "第一句。\n第二句🙂。\n第三句。";


function segments(): readonly NarrationSourceSegment[] {
  return ["第一句。", "第二句🙂。", "第三句。"].map((sourceText, index) => {
    const startUtf16 = TEXT.indexOf(sourceText);
    return {
      segmentId: `segment-${index + 1}`,
      sourceBlockKey: `block-${index + 1}`,
      sourceText,
      sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
    };
  });
}


function idlePlayerState(patch: Partial<NarrationPlayerState> = {}): NarrationPlayerState {
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


class FakeFollowPlayer implements FollowAwareNarrationPlayerController {
  private currentLease: PlaybackLease = {
    documentId: DOCUMENT_LEASE.documentId,
    documentGeneration: DOCUMENT_LEASE.generation,
    editionId: EDITION_ID,
    manifestRevision: 4,
    requestGeneration: 0,
  };
  private state = idlePlayerState();
  private readonly listeners = new Set<(state: NarrationPlayerState) => void>();
  followChanges: boolean[] = [];
  disposeCount = 0;

  get lease(): PlaybackLease { return this.currentLease; }
  readState(): NarrationPlayerState { return this.state; }
  bindManifest(_manifest: NarrationManifestV2): void {}
  async playFromSegment(): Promise<PlaybackDecision> {
    return { kind: "noop", lease: this.currentLease, reason: "manifest_not_bound" };
  }
  pause(): void {}
  async resume(): Promise<PlaybackDecision> {
    return { kind: "noop", lease: this.currentLease, reason: "not_paused" };
  }
  setRate(_rate: number): void {}
  setVolume(_volume: number): void {}
  updateManifest(_manifest: NarrationManifestV2): void {}
  subscribe(listener: (state: NarrationPlayerState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  dispose(): void { this.disposeCount += 1; }

  setFollowPaused(paused: boolean): void {
    this.followChanges.push(paused);
    this.state = idlePlayerState({ ...this.state, followPaused: paused });
    this.emit();
  }

  publish(
    patch: Partial<NarrationPlayerState>,
    leasePatch: Partial<PlaybackLease> = {},
  ): void {
    this.currentLease = Object.freeze({ ...this.currentLease, ...leasePatch });
    this.state = idlePlayerState({ ...this.state, ...patch });
    this.emit();
  }

  replaceLease(patch: Partial<PlaybackLease>): void {
    this.currentLease = Object.freeze({ ...this.currentLease, ...patch });
  }

  private emit(): void {
    for (const listener of [...this.listeners]) listener(this.state);
  }
}


function createHarness(options: { resumeOnExplicitPlayback?: boolean } = {}) {
  let currentDocumentLease = DOCUMENT_LEASE;
  let expectedPlaybackLease: PlaybackLease | null = null;
  const onDocChanged = vi.fn();
  const bridge = new ProductionNarrationEditorBridge({
    kind: "codemirror6",
    lease: DOCUMENT_LEASE,
    text: TEXT,
    currentContentHash: SOURCE_HASH,
    onDocChanged,
    isLeaseCurrent: (lease) => documentLeasesEqual(lease, currentDocumentLease),
  });
  bridge.bindEdition({
    lease: DOCUMENT_LEASE,
    editionId: EDITION_ID,
    sourceRevisionId: "revision-follow",
    sourceContentHash: SOURCE_HASH,
    segments: segments(),
  });
  const presentation: NarrationEditorPresentationEvent[] = [];
  bridge.registerPresentationListener((event) => presentation.push(event));
  const player = new FakeFollowPlayer();
  expectedPlaybackLease = player.lease;
  const controller = new ProductionSegmentFollowController({
    bridge,
    player,
    editionId: EDITION_ID,
    resumeOnExplicitPlayback: options.resumeOnExplicitPlayback,
    isPlaybackLeaseCurrent: (lease) => (
      expectedPlaybackLease !== null && playbackLeasesEqual(lease, expectedPlaybackLease)
    ),
  });
  return {
    bridge,
    player,
    controller,
    presentation,
    onDocChanged,
    setExpectedToPlayer() { expectedPlaybackLease = player.lease; },
    setExpected(patch: Partial<PlaybackLease>) {
      expectedPlaybackLease = Object.freeze({
        ...(expectedPlaybackLease ?? player.lease),
        ...patch,
      });
    },
    setDocumentLease(next: DocumentLease) { currentDocumentLease = next; },
  };
}


function eventsOfType(
  events: readonly NarrationEditorPresentationEvent[],
  type: NarrationEditorPresentationEvent["type"],
): readonly NarrationEditorPresentationEvent[] {
  return events.filter((event) => event.type === type);
}


describe("segment-level highlight and follow", () => {
  it("marks and scrolls exactly at a fenced playing-segment boundary", () => {
    const harness = createHarness();
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-1",
      currentOrdinal: 0,
      durationMs: 2_000,
      backend: "media-element",
      source: "gutter",
    }, { requestGeneration: 1 });
    harness.setExpectedToPlayer();
    harness.controller.synchronizeNow();

    expect(eventsOfType(harness.presentation, "current-segment")).toHaveLength(1);
    expect(eventsOfType(harness.presentation, "scroll-current-segment")).toHaveLength(1);
    expect(harness.bridge.readSnapshot()).toMatchObject({
      currentSegmentId: "segment-1",
      autoFollowPaused: false,
    });
    expect(harness.controller.readState()).toMatchObject({
      active: true,
      paused: false,
      currentSegmentId: "segment-1",
      lastAppliedFence: { manifestRevision: 4, requestGeneration: 1 },
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("pauses follow for every author-first interaction while playback continues", () => {
    const harness = createHarness();
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-1",
      currentOrdinal: 0,
      backend: "media-element",
      source: "command",
    }, { requestGeneration: 1 });
    harness.setExpectedToPlayer();
    harness.controller.synchronizeNow();
    harness.presentation.length = 0;

    expect(harness.controller.noteAuthorInteraction("manual-scroll")).toBe(true);
    expect(harness.controller.readState()).toMatchObject({
      paused: true,
      resumeVisible: true,
      pausedBy: "manual-scroll",
    });
    expect(harness.player.readState().phase).toBe("playing");
    expect(harness.player.followChanges).toContain(true);

    harness.player.publish({ currentSegmentId: "segment-2", currentOrdinal: 1 });
    expect(eventsOfType(harness.presentation, "current-segment")).toHaveLength(1);
    expect(eventsOfType(harness.presentation, "scroll-current-segment")).toHaveLength(0);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it.each(["caret-move", "selection", "input", "composition"] as const)(
    "treats %s as presentation-only follow interruption",
    (interruption) => {
      const harness = createHarness();
      expect(harness.controller.noteAuthorInteraction(interruption)).toBe(true);
      expect(harness.controller.readState()).toMatchObject({
        paused: true,
        resumeVisible: true,
        pausedBy: interruption,
      });
      expect(harness.onDocChanged).not.toHaveBeenCalled();
    },
  );

  it("restores follow only through an explicit resume action and does not move selection", () => {
    const harness = createHarness();
    harness.bridge.setSelection({ startUtf16: 2, endUtf16: 2, direction: "none" });
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-2",
      currentOrdinal: 1,
      backend: "media-element",
      source: "command",
    }, { requestGeneration: 1 });
    harness.setExpectedToPlayer();
    harness.controller.synchronizeNow();
    harness.controller.noteAuthorInteraction("selection");
    harness.presentation.length = 0;

    expect(harness.controller.resumeExplicitly()).toBe(true);
    expect(harness.controller.readState()).toMatchObject({
      paused: false,
      resumeVisible: false,
      pausedBy: null,
    });
    expect(eventsOfType(harness.presentation, "scroll-current-segment")).toHaveLength(1);
    expect(harness.bridge.readSnapshot().selection).toEqual({
      startUtf16: 2,
      endUtf16: 2,
      direction: "none",
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("treats an explicit new playback generation as a request to resume following", () => {
    const harness = createHarness();
    harness.controller.noteAuthorInteraction("caret-move");
    expect(harness.bridge.readSnapshot().autoFollowPaused).toBe(true);

    harness.player.publish({
      phase: "buffering",
      currentSegmentId: "segment-3",
      currentOrdinal: 2,
      backend: "media-element",
      source: "gutter",
    }, { requestGeneration: 1 });
    harness.setExpectedToPlayer();
    harness.controller.synchronizeNow();
    expect(harness.bridge.readSnapshot().autoFollowPaused).toBe(true);

    harness.player.publish({ phase: "playing" });

    expect(harness.bridge.readSnapshot().autoFollowPaused).toBe(false);
    expect(harness.controller.readState().resumeVisible).toBe(false);
    const scrollEvents = eventsOfType(harness.presentation, "scroll-current-segment");
    expect(scrollEvents[scrollEvents.length - 1]).toMatchObject({ segmentId: "segment-3" });
  });

  it("buffers composition presentation until the editor has ended composition", () => {
    const harness = createHarness();
    harness.bridge.beginComposition();
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-2",
      currentOrdinal: 1,
      backend: "media-element",
      source: "command",
    }, { requestGeneration: 1 });
    harness.setExpectedToPlayer();
    harness.controller.synchronizeNow();
    expect(eventsOfType(harness.presentation, "current-segment")).toHaveLength(0);

    harness.bridge.endComposition();
    harness.controller.synchronizeNow();
    expect(eventsOfType(harness.presentation, "current-segment")).toHaveLength(1);
    expect(eventsOfType(harness.presentation, "scroll-current-segment")).toHaveLength(1);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});


describe("segment follow fencing and safety", () => {
  it("ignores callbacks whose Manifest or request generation fails the external full fence", () => {
    const harness = createHarness();
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-1",
      currentOrdinal: 0,
      backend: "media-element",
      source: "command",
    }, { manifestRevision: 5, requestGeneration: 1 });
    harness.controller.synchronizeNow();

    expect(harness.presentation).toHaveLength(0);
    expect(harness.controller.readState()).toMatchObject({
      active: false,
      lastFailure: "stale_playback_lease",
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("rejects changed document and Edition scopes before decoration or scrolling", () => {
    const documentHarness = createHarness();
    documentHarness.setDocumentLease({ documentId: "other-doc", generation: 10 });
    documentHarness.player.replaceLease({ documentId: "other-doc", documentGeneration: 10 });
    documentHarness.setExpectedToPlayer();
    documentHarness.controller.synchronizeNow();
    expect(documentHarness.controller.readState()).toMatchObject({
      active: false,
      lastFailure: "document_generation_changed",
    });
    expect(documentHarness.presentation).toHaveLength(0);

    const editionHarness = createHarness();
    editionHarness.player.replaceLease({ editionId: "other-edition" });
    editionHarness.setExpectedToPlayer();
    editionHarness.controller.synchronizeNow();
    expect(editionHarness.controller.readState()).toMatchObject({
      active: false,
      lastFailure: "edition_mismatch",
    });
    expect(editionHarness.presentation).toHaveLength(0);
  });

  it("does not attach old audio highlighting to a locally invalidated segment", () => {
    const harness = createHarness();
    const secondStart = TEXT.indexOf("第二句🙂。");
    harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: secondStart + 1, endUtf16: secondStart + 1, insertedText: "改" }],
    });
    harness.onDocChanged.mockClear();
    harness.presentation.length = 0;
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-2",
      currentOrdinal: 1,
      backend: "media-element",
      source: "command",
    }, { requestGeneration: 1 });
    harness.setExpectedToPlayer();
    harness.controller.synchronizeNow();

    expect(harness.controller.readState().lastFailure).toBe("unmapped_segment");
    expect(eventsOfType(harness.presentation, "current-segment")).toHaveLength(0);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("unsubscribes without disposing the separately owned bridge or player", () => {
    const harness = createHarness();
    harness.controller.dispose();
    harness.player.publish({
      phase: "playing",
      currentSegmentId: "segment-1",
      currentOrdinal: 0,
    }, { requestGeneration: 1 });
    expect(harness.controller.readState()).toMatchObject({ active: false, lastFailure: "disposed" });
    expect(harness.presentation).toHaveLength(0);
    expect(harness.player.disposeCount).toBe(0);
    expect(harness.bridge.readSnapshot().active).toBe(true);
  });
});
