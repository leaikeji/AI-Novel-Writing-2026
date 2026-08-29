import { describe, expect, it, vi, type Mock } from "vitest";

import {
  deriveManifestStatus,
  deriveReadyPrefixCount,
  deriveReadyRanges,
  type NarrationManifestV2,
  type PrepareRangeReason,
  type PrepareRangeResponse,
  type SegmentRenderStatus,
} from "./playback-contracts";
import {
  ProductionNarrationPlayerController,
  decideManifestPlayback,
  type NarrationPlayerQueueHooks,
} from "./narration-player";
import type {
  PlaybackLease,
  SegmentPlaybackQueueEvent,
  SegmentPlaybackQueuePort,
  SegmentPlaybackQueueStartOptions,
  SegmentPlaybackQueueStartResult,
} from "./segment-playback-queue";


const DOCUMENT_ID = "10000000-0000-4000-8000-000000000002";
const EDITION_ID = "10000000-0000-4000-8000-000000000001";


function segmentId(ordinal: number): string {
  return `10000000-0000-4000-8000-${String(ordinal + 10).padStart(12, "0")}`;
}


function assetId(ordinal: number): string {
  return `20000000-0000-4000-8000-${String(ordinal + 20).padStart(12, "0")}`;
}


function manifest(
  states: SegmentRenderStatus[],
  revision = 4,
  etagDigit = "9",
): NarrationManifestV2 {
  const segments = states.map((renderStatus, ordinal) => {
    const digest = String((ordinal % 8) + 1).repeat(64);
    return {
      segment_id: segmentId(ordinal),
      ordinal,
      paragraph_ordinal: ordinal,
      source_block_key: `sb1_${digest}`,
      source_start_utf16: 0,
      source_end_utf16: 8,
      gap_after_ms: 0,
      render_status: renderStatus,
      audio: renderStatus === "ready" ? {
        url: `/api/ai-novel-world-2026/media-assets/${assetId(ordinal)}/content`,
        actual_sha256: digest,
        duration_ms: 3_000,
        sample_rate: 48_000,
        channels: 2,
        etag: `"${digest}"`,
      } : null,
      failure: renderStatus === "failed" ? {
        code: "RENDER_FAILED",
        retryable: true,
        message: "fixture failure",
      } : null,
    };
  });
  const bufferPolicy = {
    version: "initial-buffer/v1-3-segments-8000ms",
    minimum_segments: 3,
    minimum_duration_ms: 8_000,
    target_segments: 5,
    chapter_end_exception: true,
  } as const;
  const readyRanges = deriveReadyRanges(segments, bufferPolicy);
  return {
    schema_version: "narration-manifest/2.0",
    edition_id: EDITION_ID,
    chapter_id: "10000000-0000-4000-8000-000000000003",
    source_revision_id: "10000000-0000-4000-8000-000000000004",
    source_sha256: "a".repeat(64),
    buffer_policy: bufferPolicy,
    manifest_revision: revision,
    etag: `"${etagDigit.repeat(64)}"`,
    generated_at: "2026-08-27T08:00:00Z",
    status: deriveManifestStatus(segments),
    ready_prefix_count: deriveReadyPrefixCount(segments),
    default_start_ready: readyRanges.some((range) => range.start_ordinal === 0),
    last_playable_start_ordinal: readyRanges.length
      ? Math.max(...readyRanges.map((range) => range.last_playable_start_ordinal))
      : null,
    ready_ranges: readyRanges,
    segments,
  };
}


class FakeQueue implements SegmentPlaybackQueuePort {
  readonly starts: SegmentPlaybackQueueStartOptions[] = [];
  readonly rates: number[] = [];
  readonly volumes: number[] = [];
  pauseCount = 0;
  resumeCount = 0;
  stopCount = 0;
  disposeCount = 0;
  position: Readonly<{ segmentId: string; ordinal: number; offsetMs: number }> | null = null;
  startImplementation: (
    options: SegmentPlaybackQueueStartOptions,
  ) => Promise<SegmentPlaybackQueueStartResult>;

  constructor(readonly hooks: NarrationPlayerQueueHooks) {
    this.startImplementation = async (options) => {
      const segment = options.manifest.segments[options.startOrdinal];
      const durationMs = segment.audio?.duration_ms ?? 0;
      this.emit({
        type: "buffering",
        lease: options.lease,
        backend: "web-audio",
        segmentId: segment.segment_id,
        ordinal: segment.ordinal,
        durationMs,
      });
      this.emit({
        type: "segment-start",
        lease: options.lease,
        backend: "web-audio",
        segmentId: segment.segment_id,
        ordinal: segment.ordinal,
        offsetMs: options.startOffsetMs ?? 0,
        durationMs,
      });
      return {
        kind: "started",
        lease: options.lease,
        backend: "web-audio",
        segmentId: segment.segment_id,
        ordinal: segment.ordinal,
      };
    };
  }

  async start(options: SegmentPlaybackQueueStartOptions): Promise<SegmentPlaybackQueueStartResult> {
    this.starts.push(options);
    return this.startImplementation(options);
  }

  pause(): void { this.pauseCount += 1; }
  async resume(): Promise<void> { this.resumeCount += 1; }
  setRate(rate: number): void { this.rates.push(rate); }
  setVolume(volume: number): void { this.volumes.push(volume); }
  readPosition(): Readonly<{ segmentId: string; ordinal: number; offsetMs: number }> | null {
    return this.position;
  }
  stop(): void { this.stopCount += 1; }
  dispose(): void { this.disposeCount += 1; }

  emit(event: SegmentPlaybackQueueEvent): void {
    this.hooks.onEvent(event);
  }
}


function prepareResponse(
  startSegmentId: string,
  state: PrepareRangeResponse["state"] = "preparing",
): PrepareRangeResponse {
  return {
    contract_version: "narration-production-api/1",
    edition_id: EDITION_ID,
    start_segment_id: startSegmentId,
    start_ordinal: 0,
    state,
    manifest_revision: 4,
    manifest_etag: `"${"9".repeat(64)}"`,
    ready_range: null,
    promoted_job_ids: ["30000000-0000-4000-8000-000000000001"],
  };
}


type PrepareRange = (
  editionId: string,
  startSegmentId: string,
  reason: PrepareRangeReason,
  expectedManifestRevision: number,
  idempotencyKey: string,
  signal?: AbortSignal,
) => Promise<PrepareRangeResponse>;


function createHarness(
  initialManifest: NarrationManifestV2,
  prepareRange: Mock<PrepareRange> = vi.fn<PrepareRange>(async (
    _editionId,
    segment,
  ) => prepareResponse(segment)),
) {
  let queue: FakeQueue | null = null;
  let documentGeneration = 3;
  const controller = new ProductionNarrationPlayerController({
    documentId: DOCUMENT_ID,
    documentGeneration,
    editionId: EDITION_ID,
    initialManifest,
    prepareRange,
    isDocumentLeaseCurrent: (documentId, generation) => (
      documentId === DOCUMENT_ID && generation === documentGeneration
    ),
    createQueue: (hooks) => {
      queue = new FakeQueue(hooks);
      return queue;
    },
  });
  if (!queue) throw new Error("queue factory was not called");
  return {
    controller,
    queue: queue as FakeQueue,
    prepareRange,
    replaceDocumentGeneration(next: number) { documentGeneration = next; },
  };
}


describe("Narration manifest decisions", () => {
  it("uses only an authoritative ready range and never crosses a failed gap", () => {
    const ready = manifest(["ready", "ready", "ready", "pending", "ready"]);
    expect(decideManifestPlayback(ready, segmentId(0))).toMatchObject({
      kind: "play",
      target: { ordinal: 0 },
      readyRange: { start_ordinal: 0, end_ordinal_exclusive: 3 },
    });
    expect(decideManifestPlayback(
      manifest(["ready", "ready", "failed", "ready"]),
      segmentId(0),
    )).toMatchObject({
      kind: "blocked",
      reason: "gap_failed",
      failedSegment: { ordinal: 2 },
    });
  });
});


describe("ProductionNarrationPlayerController boundary state", () => {
  it("restores an initial position and forwards the exact start offset", async () => {
    const currentManifest = manifest(["ready", "ready", "ready"]);
    let queue: FakeQueue | null = null;
    const controller = new ProductionNarrationPlayerController({
      documentId: DOCUMENT_ID,
      documentGeneration: 3,
      editionId: EDITION_ID,
      initialManifest: currentManifest,
      initialPosition: { segmentId: segmentId(1), ordinal: 1, offsetMs: 1_250 },
      rate: 1.25,
      initialVolume: 0.65,
      createQueue: (hooks) => {
        queue = new FakeQueue(hooks);
        return queue;
      },
    });

    expect(controller.readState()).toMatchObject({
      phase: "idle",
      currentSegmentId: segmentId(1),
      currentOrdinal: 1,
      offsetMs: 1_250,
      rate: 1.25,
      volume: 0.65,
    });
    await controller.playFromSegment(segmentId(1), "resume", 1_250);
    expect((queue as unknown as FakeQueue).starts[0]).toMatchObject({
      startOrdinal: 1,
      startOffsetMs: 1_250,
      rate: 1.25,
      volume: 0.65,
    });
    expect(controller.readState()).toMatchObject({ phase: "playing", offsetMs: 1_250 });
  });

  it("materializes only valid author playback defaults", () => {
    const currentManifest = manifest(["ready"]);
    const base = {
      documentId: DOCUMENT_ID,
      documentGeneration: 3,
      editionId: EDITION_ID,
      initialManifest: currentManifest,
    } as const;

    expect(() => new ProductionNarrationPlayerController({
      ...base,
      rate: 0.49,
    })).toThrow(/between 0.5 and 3/);
    expect(() => new ProductionNarrationPlayerController({
      ...base,
      initialVolume: Number.NaN,
    })).toThrow(/between 0 and 1/);

    const lower = new ProductionNarrationPlayerController({
      ...base,
      rate: 0.5,
      initialVolume: 0,
    });
    const upper = new ProductionNarrationPlayerController({
      ...base,
      rate: 3,
      initialVolume: 1,
    });
    expect(lower.readState()).toMatchObject({ rate: 0.5, volume: 0 });
    expect(upper.readState()).toMatchObject({ rate: 3, volume: 1 });
    lower.dispose();
    upper.dispose();
  });

  it("publishes playing and highlight state only from segment boundaries", async () => {
    const harness = createHarness(manifest(["ready", "ready", "ready", "pending"]));
    const snapshots = vi.fn();
    harness.controller.subscribe(snapshots);

    await expect(harness.controller.playFromSegment(segmentId(0), "gutter")).resolves.toMatchObject({
      kind: "play",
      segmentId: segmentId(0),
      ordinal: 0,
      backend: "web-audio",
    });
    const activeLease = harness.queue.starts[0].lease;
    expect(harness.controller.readState()).toMatchObject({
      phase: "playing",
      currentSegmentId: segmentId(0),
      currentOrdinal: 0,
      offsetMs: 0,
      durationMs: 3_000,
      volume: 1,
      source: "gutter",
    });
    expect(harness.queue.starts[0].volume).toBe(1);

    harness.queue.emit({
      type: "segment-end",
      lease: activeLease,
      backend: "web-audio",
      segmentId: segmentId(0),
      ordinal: 0,
      offsetMs: 3_000,
      durationMs: 3_000,
    });
    harness.queue.emit({
      type: "segment-start",
      lease: activeLease,
      backend: "web-audio",
      segmentId: segmentId(1),
      ordinal: 1,
      offsetMs: 0,
      durationMs: 3_000,
    });

    expect(harness.controller.readState()).toMatchObject({
      phase: "playing",
      currentSegmentId: segmentId(1),
      currentOrdinal: 1,
      offsetMs: 0,
    });
    expect(snapshots.mock.calls.some(([state]) => (
      state.currentSegmentId === segmentId(0) && state.offsetMs === 3_000
    ))).toBe(true);
  });

  it("supports bounded rate and volume, pause and resume without changing the segment", async () => {
    const harness = createHarness(manifest(["ready", "ready", "ready"]));
    await harness.controller.playFromSegment(segmentId(0), "default");
    harness.queue.position = { segmentId: segmentId(0), ordinal: 0, offsetMs: 875 };
    harness.controller.pause();
    harness.controller.setRate(1.75);
    harness.controller.setVolume(0.45);

    expect(harness.controller.readState()).toMatchObject({
      phase: "paused",
      currentSegmentId: segmentId(0),
      offsetMs: 875,
      rate: 1.75,
      volume: 0.45,
    });
    expect(harness.queue.pauseCount).toBe(1);
    expect(harness.queue.rates).toContain(1.75);
    expect(harness.queue.volumes).toContain(0.45);

    await expect(harness.controller.resume()).resolves.toMatchObject({
      kind: "play",
      segmentId: segmentId(0),
    });
    expect(harness.queue.resumeCount).toBe(1);
    expect(harness.controller.readState().phase).toBe("playing");
    expect(() => harness.controller.setRate(0.49)).toThrow(/between 0.5 and 3/);
    expect(() => harness.controller.setRate(3.01)).toThrow(/between 0.5 and 3/);
    expect(() => harness.controller.setVolume(-0.01)).toThrow(/between 0 and 1/);
    expect(() => harness.controller.setVolume(1.01)).toThrow(/between 0 and 1/);
  });

  it("surfaces a pending queue gap and does not manufacture a later start", async () => {
    const harness = createHarness(manifest(["ready", "ready", "ready", "pending", "ready"]));
    await harness.controller.playFromSegment(segmentId(0), "default");
    const activeLease = harness.queue.starts[0].lease;
    harness.queue.emit({
      type: "blocked",
      lease: activeLease,
      backend: "web-audio",
      failure: {
        code: "PENDING_GAP",
        message: "pending",
        retryable: true,
        segmentId: segmentId(3),
        ordinal: 3,
      },
    });

    expect(harness.controller.readState()).toMatchObject({
      phase: "blocked",
      failure: { code: "PENDING_GAP", ordinal: 3 },
    });
    expect(harness.queue.starts).toHaveLength(1);
  });
});


describe("ProductionNarrationPlayerController fencing and prepare-range", () => {
  it("sends pending targets to prepare-range with requestGeneration and AbortSignal", async () => {
    const harness = createHarness(manifest(["pending", "pending", "pending"]));

    await expect(harness.controller.playFromSegment(segmentId(1), "command")).resolves.toMatchObject({
      kind: "preparing",
      segmentId: segmentId(1),
      prepareState: "preparing",
    });

    expect(harness.prepareRange).toHaveBeenCalledOnce();
    const call = harness.prepareRange.mock.calls[0];
    expect(call.slice(0, 4)).toEqual([EDITION_ID, segmentId(1), "user_seek", 4]);
    expect(call[4]).toMatch(/^seek:/u);
    expect(call[5]).toBeInstanceOf(AbortSignal);
    expect(harness.controller.lease.requestGeneration).toBe(1);
    expect(harness.queue.starts).toHaveLength(0);
  });

  it("aborts a rapid older seek and ignores its late completion", async () => {
    let resolveOld!: (value: PrepareRangeResponse) => void;
    const signals: AbortSignal[] = [];
    let calls = 0;
    const prepareRange = vi.fn<PrepareRange>(async (
      _edition: string,
      segment: string,
      _reason: string,
      _revision: number,
      _key: string,
      signal?: AbortSignal,
    ) => {
      if (!signal) throw new Error("signal required");
      signals.push(signal);
      calls += 1;
      if (calls === 1) {
        return new Promise<PrepareRangeResponse>((resolve) => { resolveOld = resolve; });
      }
      return prepareResponse(segment);
    });
    const harness = createHarness(manifest(["pending", "pending", "pending"]), prepareRange);

    const oldDecision = harness.controller.playFromSegment(segmentId(0), "gutter");
    await vi.waitFor(() => expect(signals).toHaveLength(1));
    const newDecision = harness.controller.playFromSegment(segmentId(1), "gutter");
    await expect(newDecision).resolves.toMatchObject({ kind: "preparing", segmentId: segmentId(1) });
    expect(signals[0].aborted).toBe(true);

    resolveOld(prepareResponse(segmentId(0)));
    await expect(oldDecision).resolves.toMatchObject({ kind: "aborted" });
    expect(harness.controller.readState()).toMatchObject({
      phase: "preparing",
      currentSegmentId: segmentId(1),
    });
    expect(harness.controller.lease.requestGeneration).toBe(2);
  });

  it("rejects stale queue events using every PlaybackLease field", async () => {
    const harness = createHarness(manifest(["ready", "ready", "ready", "ready"]));
    await harness.controller.playFromSegment(segmentId(0), "default");
    const staleLease = harness.queue.starts[0].lease;
    await harness.controller.playFromSegment(segmentId(1), "gutter");
    const currentLease = harness.queue.starts[1].lease;
    expect(currentLease.requestGeneration).toBe(staleLease.requestGeneration + 1);

    harness.queue.emit({
      type: "segment-start",
      lease: staleLease,
      backend: "web-audio",
      segmentId: segmentId(3),
      ordinal: 3,
      offsetMs: 0,
      durationMs: 3_000,
    });

    expect(harness.controller.readState()).toMatchObject({
      currentSegmentId: segmentId(1),
      currentOrdinal: 1,
    });
    expect(harness.controller.lease).toEqual(currentLease);
  });

  it("keeps queued assets on the old revision and adopts a refresh at the boundary", async () => {
    const initial = manifest(["ready", "ready", "ready", "pending"], 4, "9");
    const refreshed = manifest(["ready", "ready", "ready", "ready"], 5, "8");
    const harness = createHarness(initial);
    await harness.controller.playFromSegment(segmentId(0), "default");
    const activeLease = harness.queue.starts[0].lease;

    harness.controller.updateManifest(refreshed);
    expect(harness.controller.lease.manifestRevision).toBe(4);
    harness.queue.emit({
      type: "ended",
      lease: activeLease,
      backend: "web-audio",
      lastSegmentId: segmentId(2),
      lastOrdinal: 2,
    });

    expect(harness.controller.readState().phase).toBe("ended");
    expect(harness.controller.lease.manifestRevision).toBe(5);

    const collision = { ...refreshed, etag: `"${"7".repeat(64)}"` };
    expect(() => harness.controller.updateManifest(collision)).toThrow(/collision/);
  });

  it("drops events when the document generation is no longer current", async () => {
    const harness = createHarness(manifest(["ready", "ready", "ready"]));
    await harness.controller.playFromSegment(segmentId(0), "default");
    const activeLease: PlaybackLease = harness.queue.starts[0].lease;
    harness.replaceDocumentGeneration(4);
    harness.queue.emit({
      type: "segment-start",
      lease: activeLease,
      backend: "web-audio",
      segmentId: segmentId(2),
      ordinal: 2,
      offsetMs: 0,
      durationMs: 3_000,
    });
    expect(harness.controller.readState().currentSegmentId).toBe(segmentId(0));
  });
});
