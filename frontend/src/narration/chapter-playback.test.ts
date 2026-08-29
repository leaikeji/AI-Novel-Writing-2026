import { describe, expect, it, vi } from "vitest";

import {
  ProductionNarrationEditorBridge,
  documentLeasesEqual,
  type DocumentLease,
  type NarrationSourceSegment,
} from "./editor-bridge";
import {
  ProductionChapterPlaybackCoordinator,
  T4_G_DESKTOP_VIEWPORTS,
  playbackLeaseMatchesDocument,
  staleChapterPlaybackReason,
} from "./chapter-playback";
import type {
  NarrationPlayerController,
  NarrationPlayerState,
  NarrationPlaybackSource,
  PlaybackDecision,
} from "./narration-player";
import type { NarrationManifestV2 } from "./playback-contracts";
import type { PlaybackLease } from "./segment-playback-queue";


const TEXT = "第一段。\n第二段。";
const SOURCE_HASH = "a".repeat(64);
const DOCUMENT_LEASE: DocumentLease = { documentId: "document-1", generation: 4 };
const EDITION_ID = "edition-1";


function segments(): readonly NarrationSourceSegment[] {
  return ["第一段。", "第二段。"].map((sourceText, index) => {
    const startUtf16 = TEXT.indexOf(sourceText);
    return {
      segmentId: `segment-${index + 1}`,
      sourceBlockKey: `block-${index + 1}`,
      sourceText,
      sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
    };
  });
}


function playerState(patch: Partial<NarrationPlayerState> = {}): NarrationPlayerState {
  return {
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
  };
}


interface DeferredOperation {
  readonly segmentId: string;
  readonly source: NarrationPlaybackSource;
  readonly lease: PlaybackLease;
  resolve(decision?: PlaybackDecision): void;
  reject(reason: unknown): void;
}


class FakePlayer implements NarrationPlayerController {
  private currentLease: PlaybackLease = {
    documentId: DOCUMENT_LEASE.documentId,
    documentGeneration: DOCUMENT_LEASE.generation,
    editionId: EDITION_ID,
    manifestRevision: 3,
    requestGeneration: 0,
  };
  private state = playerState();
  private readonly listeners = new Set<(state: NarrationPlayerState) => void>();
  readonly operations: DeferredOperation[] = [];
  disposeCount = 0;

  get lease(): PlaybackLease { return this.currentLease; }
  readState(): NarrationPlayerState { return this.state; }
  bindManifest(_manifest: NarrationManifestV2): void {}

  playFromSegment(segmentId: string, source: NarrationPlaybackSource): Promise<PlaybackDecision> {
    this.currentLease = Object.freeze({
      ...this.currentLease,
      requestGeneration: this.currentLease.requestGeneration + 1,
    });
    const lease = this.currentLease;
    return new Promise<PlaybackDecision>((resolve, reject) => {
      this.operations.push({
        segmentId,
        source,
        lease,
        resolve(decision = {
          kind: "play",
          lease,
          segmentId,
          ordinal: segmentId === "segment-1" ? 0 : 1,
          backend: "web-audio",
        }) { resolve(decision); },
        reject,
      });
    });
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

  replaceLease(patch: Partial<PlaybackLease>): void {
    this.currentLease = Object.freeze({ ...this.currentLease, ...patch });
  }
}


function createHarness() {
  let currentDocumentLease = DOCUMENT_LEASE;
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
    sourceRevisionId: "revision-1",
    sourceContentHash: SOURCE_HASH,
    segments: segments(),
  });
  const player = new FakePlayer();
  const results = vi.fn();
  let externalFenceCurrent = true;
  const coordinator = new ProductionChapterPlaybackCoordinator({
    bridge,
    player,
    isPlaybackLeaseCurrent: () => externalFenceCurrent,
    onResult: results,
  });
  return {
    bridge,
    player,
    coordinator,
    onDocChanged,
    results,
    setDocumentLease(lease: DocumentLease) { currentDocumentLease = lease; },
    rejectExternalFence() { externalFenceCurrent = false; },
  };
}


describe("ProductionChapterPlaybackCoordinator", () => {
  it("forwards a fenced gutter intent to the player and returns its exact decision lease", async () => {
    const harness = createHarness();
    const pending = harness.coordinator.requestPlayback({
      source: "gutter",
      lookup: { sourceBlockKey: "block-2" },
    });

    expect(harness.player.operations).toHaveLength(1);
    expect(harness.player.operations[0]).toMatchObject({
      segmentId: "segment-2",
      source: "gutter",
      lease: { manifestRevision: 3, requestGeneration: 1 },
    });
    harness.player.operations[0].resolve();
    await expect(pending).resolves.toMatchObject({
      status: "completed",
      intent: { segmentId: "segment-2", source: "gutter" },
      fence: { manifestRevision: 3, requestGeneration: 1 },
      decision: { kind: "play", segmentId: "segment-2" },
    });
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("lets the latest rapid seek win and rejects the older completion by request generation", async () => {
    const harness = createHarness();
    const first = harness.coordinator.requestPlayback({
      source: "command",
      lookup: { segmentId: "segment-1" },
    });
    const second = harness.coordinator.requestPlayback({
      source: "command",
      lookup: { segmentId: "segment-2" },
    });

    expect(harness.player.operations.map((operation) => operation.lease.requestGeneration))
      .toEqual([1, 2]);
    harness.player.operations[0].resolve();
    harness.player.operations[1].resolve();
    await expect(first).resolves.toMatchObject({ status: "stale", reason: "request_superseded" });
    await expect(second).resolves.toMatchObject({
      status: "completed",
      fence: { requestGeneration: 2 },
    });
  });

  it("rejects a delayed completion after a Manifest revision changes", async () => {
    const harness = createHarness();
    const pending = harness.coordinator.requestPlayback({
      source: "readonly-segment",
      lookup: { segmentId: "segment-1" },
    });
    harness.player.replaceLease({ manifestRevision: 4 });
    harness.player.operations[0].resolve();

    await expect(pending).resolves.toMatchObject({
      status: "stale",
      reason: "manifest_revision_changed",
    });
  });

  it("fails closed when document, Edition, or the external full fence changes", async () => {
    const documentHarness = createHarness();
    const pending = documentHarness.coordinator.requestPlayback({
      source: "command",
      lookup: { segmentId: "segment-1" },
    });
    documentHarness.setDocumentLease({ documentId: "document-2", generation: 5 });
    documentHarness.player.replaceLease({ documentId: "document-2", documentGeneration: 5 });
    documentHarness.player.operations[0].resolve();
    await expect(pending).resolves.toMatchObject({
      status: "stale",
      reason: "document_generation_changed",
    });

    const editionHarness = createHarness();
    editionHarness.player.replaceLease({ editionId: "edition-2" });
    await expect(editionHarness.coordinator.requestPlayback({
      source: "command",
      lookup: { segmentId: "segment-1" },
    })).resolves.toMatchObject({ status: "stale", reason: "edition_changed" });

    const externalHarness = createHarness();
    externalHarness.rejectExternalFence();
    await expect(externalHarness.coordinator.requestPlayback({
      source: "command",
      lookup: { segmentId: "segment-1" },
    })).resolves.toMatchObject({ status: "stale", reason: "external_fence_rejected" });
  });

  it("keeps ordinary editor clicks caret-only and never invokes the player", () => {
    const harness = createHarness();
    expect(harness.coordinator.requestOrdinaryEditorClick({ positionUtf16: 2 })).toEqual({
      accepted: false,
      reason: "editor_click_moves_caret_only",
    });
    expect(harness.player.operations).toHaveLength(0);
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("also consumes raw bridge intents emitted by the CodeMirror gutter seam", async () => {
    const harness = createHarness();
    harness.bridge.requestPlayback({
      lease: DOCUMENT_LEASE,
      editionId: EDITION_ID,
      source: "gutter",
      lookup: { sourceBlockKey: "block-1" },
    });
    expect(harness.player.operations).toHaveLength(1);
    harness.player.operations[0].resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(harness.results).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
  });

  it("unsubscribes on dispose and optionally owns player cleanup", async () => {
    const harness = createHarness();
    harness.coordinator.dispose();
    await expect(harness.coordinator.requestPlayback({
      source: "command",
      lookup: { segmentId: "segment-1" },
    })).resolves.toEqual({ status: "rejected", reason: "coordinator_disposed", fence: null });
    expect(harness.player.operations).toHaveLength(0);

    const owned = createHarness();
    const coordinator = new ProductionChapterPlaybackCoordinator({
      bridge: owned.bridge,
      player: owned.player,
      disposePlayer: true,
    });
    coordinator.dispose();
    expect(owned.player.disposeCount).toBe(1);
  });
});


describe("T4-G scope helpers", () => {
  it("freezes only the two approved desktop targets and marks smaller layouts non-blocking", () => {
    expect(T4_G_DESKTOP_VIEWPORTS).toEqual({
      minimum: { width: 1_920, height: 1_080 },
      supplemental: { width: 2_560, height: 1_440 },
      belowMinimumIsBlocking: false,
    });
  });

  it("compares all document, Edition, Manifest, and request fence dimensions", () => {
    const lease: PlaybackLease = {
      documentId: "doc",
      documentGeneration: 8,
      editionId: "edition",
      manifestRevision: 5,
      requestGeneration: 2,
    };
    expect(playbackLeaseMatchesDocument(
      lease,
      { documentId: "doc", generation: 8 },
      "edition",
    )).toBe(true);
    expect(staleChapterPlaybackReason(lease, { ...lease, manifestRevision: 6 }))
      .toBe("manifest_revision_changed");
    expect(staleChapterPlaybackReason(lease, { ...lease, requestGeneration: 3 }))
      .toBe("request_superseded");
  });
});
