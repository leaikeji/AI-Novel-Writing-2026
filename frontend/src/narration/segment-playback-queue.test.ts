import { describe, expect, it, vi } from "vitest";

import {
  deriveManifestStatus,
  deriveReadyPrefixCount,
  deriveReadyRanges,
  type ManifestSegmentV2,
  type NarrationManifestV2,
  type SegmentRenderStatus,
} from "./playback-contracts";
import {
  SegmentPlaybackQueue,
  createDualAudioPlaybackDriver,
  playbackLeasesEqual,
  type PlaybackLease,
  type PreparedPlaybackSegment,
  type SegmentPlaybackDriver,
  type SegmentPlaybackQueueEvent,
} from "./segment-playback-queue";


const EDITION_ID = "10000000-0000-4000-8000-000000000001";
const DOCUMENT_ID = "10000000-0000-4000-8000-000000000002";


function segmentId(ordinal: number): string {
  return `10000000-0000-4000-8000-${String(ordinal + 10).padStart(12, "0")}`;
}


function assetId(ordinal: number): string {
  return `20000000-0000-4000-8000-${String(ordinal + 20).padStart(12, "0")}`;
}


function createSegment(status: SegmentRenderStatus, ordinal: number): ManifestSegmentV2 {
  const digest = String((ordinal % 8) + 1).repeat(64);
  return {
    segment_id: segmentId(ordinal),
    ordinal,
    paragraph_ordinal: ordinal,
    source_block_key: `sb1_${digest}`,
    source_start_utf16: 0,
    source_end_utf16: 8,
    gap_after_ms: 0,
    render_status: status,
    audio: status === "ready" ? {
      url: `/api/ai-novel-world-2026/media-assets/${assetId(ordinal)}/content`,
      actual_sha256: digest,
      duration_ms: 3_000,
      sample_rate: 48_000,
      channels: 2,
      etag: `"${digest}"`,
    } : null,
    failure: status === "failed" ? {
      code: "RENDER_FAILED",
      retryable: true,
      message: "fixture failure",
    } : null,
  };
}


function createManifest(states: SegmentRenderStatus[]): NarrationManifestV2 {
  const segments = states.map(createSegment);
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
    manifest_revision: 4,
    etag: `"${"9".repeat(64)}"`,
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


function lease(requestGeneration = 1): PlaybackLease {
  return {
    documentId: DOCUMENT_ID,
    documentGeneration: 7,
    editionId: EDITION_ID,
    manifestRevision: 4,
    requestGeneration,
  };
}


function abortError(): Error {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
}


class FakeDriver implements SegmentPlaybackDriver {
  readonly prepared: number[] = [];
  readonly played: number[] = [];
  readonly released: number[] = [];
  readonly rates: number[] = [];
  readonly offsets: number[] = [];
  pauseCount = 0;
  resumeCount = 0;
  stopCount = 0;
  disposeCount = 0;

  constructor(
    readonly kind: "web-audio" | "dual-audio",
    private readonly holdPlayback = false,
  ) {}

  async prepare(
    segment: ManifestSegmentV2,
    _bytes: ArrayBuffer,
    slot: 0 | 1,
    _signal: AbortSignal,
  ): Promise<PreparedPlaybackSegment> {
    this.prepared.push(segment.ordinal);
    return { segmentId: segment.segment_id, ordinal: segment.ordinal, handle: { slot } };
  }

  async play(
    prepared: PreparedPlaybackSegment,
    rate: number,
    startOffsetMs: number,
    signal: AbortSignal,
  ): Promise<void> {
    this.played.push(prepared.ordinal);
    this.rates.push(rate);
    this.offsets.push(startOffsetMs);
    if (!this.holdPlayback) return;
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => reject(abortError());
      signal.addEventListener("abort", onAbort, { once: true });
      void resolve;
    });
  }

  release(prepared: PreparedPlaybackSegment): void {
    this.released.push(prepared.ordinal);
  }

  pause(): void { this.pauseCount += 1; }
  async resume(): Promise<void> { this.resumeCount += 1; }
  setRate(rate: number): void { this.rates.push(rate); }
  stop(): void { this.stopCount += 1; }
  dispose(): void { this.disposeCount += 1; }
}


class FakeAudioElement extends EventTarget {
  preload = "";
  src = "";
  playbackRate = 1;
  readyState = 0;
  duration = Number.NaN;
  seekWrites: number[] = [];
  playCount = 0;
  private position = 0;

  get currentTime(): number { return this.position; }
  set currentTime(value: number) {
    this.seekWrites.push(value);
    this.position = value;
  }

  pause(): void {}
  load(): void {}
  removeAttribute(name: string): void {
    if (name === "src") this.src = "";
  }
  async play(): Promise<void> {
    this.playCount += 1;
    queueMicrotask(() => this.dispatchEvent(new Event("ended")));
  }
}


function responseFor(segment: ManifestSegmentV2): Response {
  if (!segment.audio) throw new Error("fixture requires ready audio");
  return new Response(new Uint8Array([segment.ordinal + 1]), {
    status: 200,
    headers: { ETag: segment.audio.etag },
  });
}


describe("SegmentPlaybackQueue backend and prefetch contract", () => {
  it("uses the default full-media facade without Range or If-Range", async () => {
    const currentManifest = createManifest(["ready"]);
    const segment = currentManifest.segments[0];
    if (!segment.audio) throw new Error("fixture requires ready audio");
    const audio = segment.audio;
    const hostFetch = vi.fn<(
      path: string,
      init?: RequestInit,
    ) => Promise<Response>>(async () => new Response(new Uint8Array([1, 2, 3]), {
      status: 200,
      headers: {
        "Accept-Ranges": "bytes",
        "Content-Length": "3",
        "Content-Type": "audio/ogg",
        ETag: audio.etag,
      },
    }));
    vi.stubGlobal("window", { QwenPaw: { host: { fetch: hostFetch } } });
    const driver = new FakeDriver("web-audio", true);
    const queue = new SegmentPlaybackQueue({
      createWebAudioDriver: () => driver,
    });

    try {
      await expect(queue.start({
        lease: lease(),
        manifest: currentManifest,
        startOrdinal: 0,
        rate: 1,
      })).resolves.toMatchObject({ kind: "started", backend: "web-audio" });

      expect(hostFetch).toHaveBeenCalledOnce();
      const [path, init] = hostFetch.mock.calls[0];
      expect(path).toBe(`/ai-novel-world-2026/media-assets/${assetId(0)}/content`);
      const headers = new Headers(init?.headers);
      expect(headers.get("Range")).toBeNull();
      expect(headers.get("If-Range")).toBeNull();
      expect(headers.get("X-Narration-Edition-Id")).toBe(EDITION_ID);
      expect(headers.get("X-Narration-Manifest-Revision")).toBe("4");
    } finally {
      queue.stop();
      vi.unstubAllGlobals();
    }
  });

  it("waits for dual-audio metadata before validating and applying a restore seek", async () => {
    const elements = [new FakeAudioElement(), new FakeAudioElement()];
    let index = 0;
    vi.stubGlobal("document", {
      createElement: () => elements[index++],
    });
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-audio");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    try {
      const driver = createDualAudioPlaybackDriver();
      if (!driver) throw new Error("dual audio driver was not created");
      const currentManifest = createManifest(["ready"]);
      const controller = new AbortController();
      const prepared = await driver.prepare(
        currentManifest.segments[0],
        new Uint8Array([1]).buffer,
        0,
        controller.signal,
      );
      const playing = driver.play(prepared, 1, 1_250, controller.signal);
      await Promise.resolve();
      expect(elements[0].seekWrites).toEqual([]);

      elements[0].duration = 3;
      elements[0].readyState = 1;
      elements[0].dispatchEvent(new Event("loadedmetadata"));
      await playing;

      expect(elements[0].seekWrites).toEqual([1.25]);
      const boundaryPrepared = await driver.prepare(
        currentManifest.segments[0],
        new Uint8Array([2]).buffer,
        1,
        controller.signal,
      );
      elements[1].duration = 1;
      elements[1].readyState = 1;
      await expect(driver.play(boundaryPrepared, 1, 1_250, controller.signal)).rejects.toMatchObject({
        failure: { code: "INVALID_PLAYBACK_RANGE" },
      });

      elements[1].duration = Number.NaN;
      elements[1].readyState = 0;
      const metadataAbort = new AbortController();
      const waiting = driver.play(boundaryPrepared, 1, 0, metadataAbort.signal);
      metadataAbort.abort();
      await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
      driver.dispose();
      expect(createUrl).toHaveBeenCalledTimes(2);
      expect(revokeUrl).toHaveBeenCalled();
    } finally {
      createUrl.mockRestore();
      revokeUrl.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("keeps a dual-audio start paused while metadata is still loading", async () => {
    const elements = [new FakeAudioElement(), new FakeAudioElement()];
    let index = 0;
    vi.stubGlobal("document", {
      createElement: () => elements[index++],
    });
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-paused-audio");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    try {
      const driver = createDualAudioPlaybackDriver();
      if (!driver) throw new Error("dual audio driver was not created");
      const currentManifest = createManifest(["ready"]);
      const controller = new AbortController();
      const prepared = await driver.prepare(
        currentManifest.segments[0],
        new Uint8Array([1]).buffer,
        0,
        controller.signal,
      );
      const playing = driver.play(prepared, 1, 900, controller.signal);
      driver.pause();
      elements[0].duration = 3;
      elements[0].readyState = 1;
      elements[0].dispatchEvent(new Event("loadedmetadata"));
      await Promise.resolve();
      await Promise.resolve();

      expect(elements[0].seekWrites).toEqual([0.9]);
      expect(elements[0].playCount).toBe(0);

      await driver.resume();
      await playing;
      expect(elements[0].playCount).toBe(1);
      driver.dispose();
    } finally {
      createUrl.mockRestore();
      revokeUrl.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("validates and forwards the first segment restore offset", async () => {
    const manifest = createManifest(["ready"]);
    const driver = new FakeDriver("web-audio", true);
    const events: SegmentPlaybackQueueEvent[] = [];
    const queue = new SegmentPlaybackQueue({
      fetchMedia: (async () => responseFor(manifest.segments[0])) as never,
      createWebAudioDriver: () => driver,
      onEvent: (event) => events.push(event),
    });

    await expect(queue.start({
      lease: lease(), manifest, startOrdinal: 0, startOffsetMs: 1_250, rate: 1,
    })).resolves.toMatchObject({ kind: "started" });
    expect(driver.offsets).toEqual([1_250]);
    expect(events).toContainEqual(expect.objectContaining({
      type: "segment-start",
      offsetMs: 1_250,
    }));
    queue.stop();

    await expect(new SegmentPlaybackQueue().start({
      lease: lease(), manifest, startOrdinal: 0, startOffsetMs: 3_001, rate: 1,
    })).resolves.toMatchObject({
      kind: "error",
      failure: { code: "INVALID_PLAYBACK_RANGE" },
    });
  });

  it("prefers Web Audio and fetches a bounded four-segment window", async () => {
    const manifest = createManifest(["ready", "ready", "ready", "ready", "ready"]);
    const driver = new FakeDriver("web-audio", true);
    const dualFactory = vi.fn(() => new FakeDriver("dual-audio"));
    const fetchMedia = vi.fn(async (request: { url: string }) => {
      const segment = manifest.segments.find((candidate) => candidate.audio?.url === request.url);
      if (!segment) throw new Error("unknown URL");
      return responseFor(segment);
    });
    let currentLease = lease();
    const queue = new SegmentPlaybackQueue({
      prefetchSegments: 4,
      fetchMedia: fetchMedia as never,
      createWebAudioDriver: () => driver,
      createDualAudioDriver: dualFactory,
      isLeaseCurrent: (candidate) => playbackLeasesEqual(candidate, currentLease),
    });

    const result = await queue.start({
      lease: currentLease,
      manifest,
      startOrdinal: 0,
      endOrdinalExclusive: 5,
      rate: 1,
    });

    expect(result).toMatchObject({ kind: "started", backend: "web-audio", ordinal: 0 });
    expect(fetchMedia).toHaveBeenCalledTimes(4);
    expect(driver.prepared).toEqual([0, 1, 2, 3]);
    expect(driver.played).toEqual([0]);
    expect(dualFactory).not.toHaveBeenCalled();
    currentLease = lease(2);
    queue.stop();
  });

  it("uses dual audio as the only fallback when Web Audio is unavailable", async () => {
    const manifest = createManifest(["ready"]);
    const dual = new FakeDriver("dual-audio", true);
    const queue = new SegmentPlaybackQueue({
      fetchMedia: (async () => responseFor(manifest.segments[0])) as never,
      createWebAudioDriver: () => null,
      createDualAudioDriver: () => dual,
    });

    const result = await queue.start({
      lease: lease(),
      manifest,
      startOrdinal: 0,
      rate: 1,
    });

    expect(result).toMatchObject({ kind: "started", backend: "dual-audio" });
    expect(dual.prepared).toEqual([0]);
    queue.stop();
  });

  it("rejects prefetch windows outside the frozen 3-5 segment bound", () => {
    expect(() => new SegmentPlaybackQueue({ prefetchSegments: 2 })).toThrow(/between 3 and 5/);
    expect(() => new SegmentPlaybackQueue({ prefetchSegments: 6 })).toThrow(/between 3 and 5/);
  });
});


describe("SegmentPlaybackQueue gaps, cancellation and controls", () => {
  it("plays only the contiguous prefix and blocks at a pending gap", async () => {
    const manifest = createManifest(["ready", "ready", "ready", "pending", "ready"]);
    const driver = new FakeDriver("web-audio");
    const events: SegmentPlaybackQueueEvent[] = [];
    const queue = new SegmentPlaybackQueue({
      fetchMedia: (async (request: { url: string }) => {
        const segment = manifest.segments.find((candidate) => candidate.audio?.url === request.url);
        if (!segment) throw new Error("unknown URL");
        return responseFor(segment);
      }) as never,
      createWebAudioDriver: () => driver,
      onEvent: (event) => events.push(event),
    });

    await expect(queue.start({
      lease: lease(),
      manifest,
      startOrdinal: 0,
      endOrdinalExclusive: 3,
      rate: 1,
    })).resolves.toMatchObject({ kind: "started" });
    await vi.waitFor(() => {
      expect(events.some((event) => event.type === "blocked")).toBe(true);
    });

    expect(driver.played).toEqual([0, 1, 2]);
    expect(driver.played).not.toContain(4);
    expect(events.filter((event) => event.type === "segment-start").map((event) => (
      event.type === "segment-start" ? event.ordinal : -1
    ))).toEqual([0, 1, 2]);
    expect(events[events.length - 1]).toMatchObject({
      type: "blocked",
      failure: { code: "PENDING_GAP", ordinal: 3 },
    });
  });

  it("forwards pause, resume and bounded rate to the active backend", async () => {
    const manifest = createManifest(["ready"]);
    const driver = new FakeDriver("web-audio", true);
    const queue = new SegmentPlaybackQueue({
      fetchMedia: (async () => responseFor(manifest.segments[0])) as never,
      createWebAudioDriver: () => driver,
    });
    await queue.start({ lease: lease(), manifest, startOrdinal: 0, rate: 1 });

    queue.pause();
    queue.setRate(1.75);
    await queue.resume();

    expect(driver.pauseCount).toBe(1);
    expect(driver.resumeCount).toBe(1);
    expect(driver.rates).toContain(1.75);
    expect(() => queue.setRate(4.1)).toThrow(/between 0.25 and 4/);
    queue.stop();
  });

  it("keeps a pause authoritative while media preparation is still in flight", async () => {
    const currentManifest = createManifest(["ready"]);
    const driver = new FakeDriver("web-audio", true);
    let releasePrepare!: () => void;
    const prepareGate = new Promise<void>((resolve) => { releasePrepare = resolve; });
    const enteredPrepare = vi.fn();
    vi.spyOn(driver, "prepare").mockImplementation(async (segment, _bytes, slot) => {
      enteredPrepare();
      await prepareGate;
      driver.prepared.push(segment.ordinal);
      return { segmentId: segment.segment_id, ordinal: segment.ordinal, handle: { slot } };
    });
    const queue = new SegmentPlaybackQueue({
      fetchMedia: (async () => responseFor(currentManifest.segments[0])) as never,
      createWebAudioDriver: () => driver,
    });

    let startSettled = false;
    const start = queue.start({
      lease: lease(),
      manifest: currentManifest,
      startOrdinal: 0,
      rate: 1,
    }).then((result) => {
      startSettled = true;
      return result;
    });
    await vi.waitFor(() => expect(enteredPrepare).toHaveBeenCalledOnce());
    queue.pause();
    releasePrepare();
    await Promise.resolve();
    await Promise.resolve();
    expect(startSettled).toBe(false);
    expect(driver.played).toEqual([]);

    await queue.resume();
    await expect(start).resolves.toMatchObject({ kind: "started" });
    expect(driver.played).toEqual([0]);
    queue.stop();
  });

  it("aborts an older fetch and rejects every late completion by full lease", async () => {
    const manifest = createManifest(["ready"]);
    const firstLease = lease(1);
    const secondLease = lease(2);
    let currentLease = firstLease;
    let callCount = 0;
    const firstSignal: AbortSignal[] = [];
    const fetchMedia = vi.fn(async (request: { signal?: AbortSignal }) => {
      callCount += 1;
      if (callCount === 1) {
        if (!request.signal) throw new Error("AbortSignal required");
        firstSignal.push(request.signal);
        await new Promise<void>((_resolve, reject) => {
          request.signal?.addEventListener("abort", () => reject(abortError()), { once: true });
        });
      }
      return responseFor(manifest.segments[0]);
    });
    const queue = new SegmentPlaybackQueue({
      fetchMedia: fetchMedia as never,
      createWebAudioDriver: () => new FakeDriver("web-audio", true),
      isLeaseCurrent: (candidate) => playbackLeasesEqual(candidate, currentLease),
    });

    const oldResult = queue.start({ lease: firstLease, manifest, startOrdinal: 0, rate: 1 });
    await vi.waitFor(() => expect(firstSignal).toHaveLength(1));
    currentLease = secondLease;
    const newResult = queue.start({ lease: secondLease, manifest, startOrdinal: 0, rate: 1 });

    await expect(oldResult).resolves.toEqual({ kind: "aborted", lease: firstLease });
    await expect(newResult).resolves.toMatchObject({ kind: "started", lease: secondLease });
    expect(firstSignal[0].aborted).toBe(true);
    queue.stop();
  });
});
