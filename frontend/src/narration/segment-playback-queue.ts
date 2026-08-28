import { fetchPlaybackMedia } from "./playback-api";
import type {
  ManifestSegmentV2,
  NarrationManifestV2,
} from "./playback-contracts";


export type PlaybackLease = Readonly<{
  documentId: string;
  documentGeneration: number;
  editionId: string;
  manifestRevision: number;
  requestGeneration: number;
}>;


export function playbackLeasesEqual(
  left: PlaybackLease,
  right: PlaybackLease,
): boolean {
  return left.documentId === right.documentId
    && left.documentGeneration === right.documentGeneration
    && left.editionId === right.editionId
    && left.manifestRevision === right.manifestRevision
    && left.requestGeneration === right.requestGeneration;
}


export type SegmentPlaybackBackendKind = "web-audio" | "dual-audio";


export type SegmentPlaybackFailureCode =
  | "STALE_PLAYBACK_LEASE"
  | "INVALID_PLAYBACK_RANGE"
  | "PENDING_GAP"
  | "FAILED_GAP"
  | "CANCELLED_GAP"
  | "MEDIA_FETCH_FAILED"
  | "MEDIA_INTEGRITY_FAILED"
  | "MEDIA_DECODE_FAILED"
  | "PLAYBACK_UNAVAILABLE"
  | "PLAYBACK_FAILED";


export interface SegmentPlaybackFailure {
  readonly code: SegmentPlaybackFailureCode;
  readonly message: string;
  readonly retryable: boolean;
  readonly segmentId: string | null;
  readonly ordinal: number | null;
}


export type SegmentPlaybackQueueEvent = Readonly<
  | {
      type: "buffering";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      segmentId: string;
      ordinal: number;
      durationMs: number;
    }
  | {
      type: "segment-start";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      segmentId: string;
      ordinal: number;
      offsetMs: number;
      durationMs: number;
    }
  | {
      type: "segment-end";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      segmentId: string;
      ordinal: number;
      offsetMs: number;
      durationMs: number;
    }
  | {
      type: "blocked";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      failure: SegmentPlaybackFailure;
    }
  | {
      type: "ended";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      lastSegmentId: string | null;
      lastOrdinal: number | null;
    }
  | {
      type: "error";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind | null;
      failure: SegmentPlaybackFailure;
    }
>;


export type SegmentPlaybackQueueStartResult = Readonly<
  | {
      kind: "started";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      segmentId: string;
      ordinal: number;
    }
  | {
      kind: "blocked";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind;
      failure: SegmentPlaybackFailure;
    }
  | {
      kind: "error";
      lease: PlaybackLease;
      backend: SegmentPlaybackBackendKind | null;
      failure: SegmentPlaybackFailure;
    }
  | {
      kind: "aborted";
      lease: PlaybackLease;
    }
>;


export interface SegmentPlaybackQueueStartOptions {
  readonly lease: PlaybackLease;
  readonly manifest: NarrationManifestV2;
  readonly startOrdinal: number;
  readonly endOrdinalExclusive?: number;
  readonly rate: number;
  readonly startOffsetMs?: number;
  readonly signal?: AbortSignal;
}


export interface PreparedPlaybackSegment {
  readonly segmentId: string;
  readonly ordinal: number;
  readonly handle: unknown;
}


/**
 * Narrow driver seam used both by the real browser backends and deterministic
 * queue tests.  A driver owns its browser resources and never changes kind.
 */
export interface SegmentPlaybackDriver {
  readonly kind: SegmentPlaybackBackendKind;
  prepare(
    segment: ManifestSegmentV2,
    bytes: ArrayBuffer,
    slot: 0 | 1,
    signal: AbortSignal,
  ): Promise<PreparedPlaybackSegment>;
  play(
    prepared: PreparedPlaybackSegment,
    rate: number,
    startOffsetMs: number,
    signal: AbortSignal,
  ): Promise<void>;
  readOffsetMs?(): number;
  release(prepared: PreparedPlaybackSegment): void;
  pause(): void;
  resume(): Promise<void>;
  setRate(rate: number): void;
  stop(): void;
  dispose(): void;
}


export interface SegmentPlaybackQueuePort {
  start(options: SegmentPlaybackQueueStartOptions): Promise<SegmentPlaybackQueueStartResult>;
  pause(): void;
  resume(): Promise<void>;
  setRate(rate: number): void;
  readPosition?(): Readonly<{ segmentId: string; ordinal: number; offsetMs: number }> | null;
  stop(): void;
  dispose(): void;
}


type MediaFetcher = typeof fetchPlaybackMedia;


export interface SegmentPlaybackQueueOptions {
  readonly prefetchSegments?: number;
  readonly fetchMedia?: MediaFetcher;
  readonly createWebAudioDriver?: () => SegmentPlaybackDriver | null;
  readonly createDualAudioDriver?: () => SegmentPlaybackDriver | null;
  readonly isLeaseCurrent?: (lease: PlaybackLease) => boolean;
  readonly onEvent?: (event: SegmentPlaybackQueueEvent) => void;
}


class PlaybackBackendCompatibilityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlaybackBackendCompatibilityError";
  }
}


class PlaybackQueueError extends Error {
  readonly failure: SegmentPlaybackFailure;

  constructor(failure: SegmentPlaybackFailure) {
    super(failure.message);
    this.name = "PlaybackQueueError";
    this.failure = failure;
  }
}


function abortError(message = "playback request was superseded"): Error {
  if (typeof DOMException === "function") return new DOMException(message, "AbortError");
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}


function isAbortError(reason: unknown): boolean {
  return reason instanceof Error && reason.name === "AbortError";
}


function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw abortError();
}


function boundedRate(rate: number): number {
  if (!Number.isFinite(rate) || rate < 0.25 || rate > 4) {
    throw new RangeError("playback rate must be between 0.25 and 4");
  }
  return rate;
}


function freezeLease(lease: PlaybackLease): PlaybackLease {
  return Object.freeze({ ...lease });
}


function failure(
  code: SegmentPlaybackFailureCode,
  message: string,
  retryable: boolean,
  segment: ManifestSegmentV2 | null = null,
): SegmentPlaybackFailure {
  return Object.freeze({
    code,
    message,
    retryable,
    segmentId: segment?.segment_id ?? null,
    ordinal: segment?.ordinal ?? null,
  });
}


function blockingFailure(segment: ManifestSegmentV2): SegmentPlaybackFailure {
  if (segment.render_status === "failed") {
    return failure(
      "FAILED_GAP",
      segment.failure?.message ?? "句段合成失败，播放已在缺口前停止。",
      segment.failure?.retryable ?? false,
      segment,
    );
  }
  if (segment.render_status === "cancelled") {
    return failure("CANCELLED_GAP", "句段生成已取消，播放已在缺口前停止。", true, segment);
  }
  return failure("PENDING_GAP", "后续句段尚未准备好，播放不会跳过该缺口。", true, segment);
}


function genericFailure(
  reason: unknown,
  segment: ManifestSegmentV2 | null,
): SegmentPlaybackFailure {
  if (reason instanceof PlaybackQueueError) return reason.failure;
  if (reason instanceof PlaybackBackendCompatibilityError) {
    return failure("PLAYBACK_UNAVAILABLE", "当前浏览器不支持可用的分段播放后端。", false, segment);
  }
  return failure("PLAYBACK_FAILED", "句段音频播放失败。", true, segment);
}


function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (milliseconds <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      reject(abortError());
    };
    if (signal.aborted) {
      globalThis.clearTimeout(timer);
      reject(abortError());
      return;
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}


type MediaResult = Readonly<
  | { ok: true; bytes: ArrayBuffer }
  | { ok: false; error: unknown }
>;


interface ActiveOperation {
  readonly lease: PlaybackLease;
  readonly manifest: NarrationManifestV2;
  readonly startOrdinal: number;
  readonly startOffsetMs: number;
  readonly endOrdinalExclusive: number;
  readonly controller: AbortController;
  readonly externalSignal: AbortSignal | undefined;
  readonly onExternalAbort: (() => void) | null;
  readonly media: Map<number, Promise<MediaResult>>;
  readonly prepared: Map<number, PreparedPlaybackSegment>;
  resolveStart: (result: SegmentPlaybackQueueStartResult) => void;
  startResolved: boolean;
  driver: SegmentPlaybackDriver | null;
  rate: number;
  paused: boolean;
  resumeWaiters: Array<() => void>;
  currentSegment: ManifestSegmentV2 | null;
}


interface WebAudioPreparedHandle {
  readonly buffer: AudioBuffer;
}


class WebAudioPlaybackDriver implements SegmentPlaybackDriver {
  readonly kind = "web-audio" as const;
  private currentSource: AudioBufferSourceNode | null = null;
  private rate = 1;
  private currentOffsetMs = 0;
  private currentStartedAt = 0;
  private currentDurationMs = 0;

  constructor(private readonly context: AudioContext) {}

  async prepare(
    segment: ManifestSegmentV2,
    bytes: ArrayBuffer,
    _slot: 0 | 1,
    signal: AbortSignal,
  ): Promise<PreparedPlaybackSegment> {
    throwIfAborted(signal);
    try {
      const buffer = await this.context.decodeAudioData(bytes.slice(0));
      throwIfAborted(signal);
      return Object.freeze({
        segmentId: segment.segment_id,
        ordinal: segment.ordinal,
        handle: Object.freeze({ buffer } satisfies WebAudioPreparedHandle),
      });
    } catch (reason) {
      if (isAbortError(reason) || signal.aborted) throw abortError();
      throw new PlaybackBackendCompatibilityError("Web Audio could not decode the playback asset");
    }
  }

  async play(
    prepared: PreparedPlaybackSegment,
    rate: number,
    startOffsetMs: number,
    signal: AbortSignal,
  ): Promise<void> {
    throwIfAborted(signal);
    const handle = prepared.handle as WebAudioPreparedHandle;
    const durationMs = Math.round(handle.buffer.duration * 1_000);
    if (!Number.isSafeInteger(startOffsetMs) || startOffsetMs < 0 || startOffsetMs > durationMs) {
      throw new PlaybackQueueError(failure("INVALID_PLAYBACK_RANGE", "恢复位置超出句段音频边界。", false));
    }
    await this.context.resume();
    throwIfAborted(signal);
    await new Promise<void>((resolve, reject) => {
      const source = this.context.createBufferSource();
      this.currentSource = source;
      this.currentOffsetMs = startOffsetMs;
      this.currentStartedAt = this.context.currentTime;
      this.currentDurationMs = durationMs;
      source.buffer = handle.buffer;
      source.playbackRate.value = boundedRate(rate);
      source.connect(this.context.destination);
      let settled = false;
      const settle = (callback: () => void) => {
        if (settled) return;
        settled = true;
        signal.removeEventListener("abort", onAbort);
        if (this.currentSource === source) {
          this.currentOffsetMs = Math.min(this.currentDurationMs, this.readOffsetMs());
          this.currentSource = null;
        }
        callback();
      };
      const onAbort = () => {
        try { source.stop(); } catch { /* already stopped */ }
        settle(() => reject(abortError()));
      };
      source.onended = () => settle(resolve);
      signal.addEventListener("abort", onAbort, { once: true });
      try {
        source.start(this.context.currentTime, startOffsetMs / 1_000);
      } catch {
        settle(() => reject(new PlaybackQueueError(
          failure("PLAYBACK_FAILED", "Web Audio 无法启动句段播放。", true),
        )));
      }
    });
  }

  release(_prepared: PreparedPlaybackSegment): void {}

  readOffsetMs(): number {
    if (!this.currentSource) return this.currentOffsetMs;
    const elapsedMs = (this.context.currentTime - this.currentStartedAt) * 1_000 * this.rate;
    return Math.max(0, Math.min(this.currentDurationMs, Math.round(this.currentOffsetMs + elapsedMs)));
  }

  pause(): void {
    void this.context.suspend().catch(() => undefined);
  }

  async resume(): Promise<void> {
    await this.context.resume();
  }

  setRate(rate: number): void {
    if (this.currentSource) {
      this.currentOffsetMs = this.readOffsetMs();
      this.currentStartedAt = this.context.currentTime;
    }
    this.rate = boundedRate(rate);
    if (this.currentSource) {
      this.currentSource.playbackRate.setValueAtTime(this.rate, this.context.currentTime);
    }
  }

  stop(): void {
    const source = this.currentSource;
    if (source) this.currentOffsetMs = this.readOffsetMs();
    this.currentSource = null;
    if (source) {
      try { source.stop(); } catch { /* already stopped */ }
    }
  }

  dispose(): void {
    this.stop();
    void this.context.close().catch(() => undefined);
  }
}


interface DualAudioSlot {
  readonly element: HTMLAudioElement;
  prepared: PreparedPlaybackSegment | null;
  objectUrl: string | null;
}


interface DualAudioPreparedHandle {
  readonly slot: 0 | 1;
  readonly element: HTMLAudioElement;
  readonly objectUrl: string;
}


class DualAudioPlaybackDriver implements SegmentPlaybackDriver {
  readonly kind = "dual-audio" as const;
  private readonly slots: readonly [DualAudioSlot, DualAudioSlot];
  private current: HTMLAudioElement | null = null;
  private rate = 1;
  private paused = false;
  private playbackStarted = false;
  private readonly resumeWaiters = new Set<() => void>();

  constructor(elements: readonly [HTMLAudioElement, HTMLAudioElement]) {
    this.slots = elements.map((element) => {
      element.preload = "auto";
      return { element, prepared: null, objectUrl: null };
    }) as unknown as readonly [DualAudioSlot, DualAudioSlot];
  }

  async prepare(
    segment: ManifestSegmentV2,
    bytes: ArrayBuffer,
    slotIndex: 0 | 1,
    signal: AbortSignal,
  ): Promise<PreparedPlaybackSegment> {
    throwIfAborted(signal);
    const slot = this.slots[slotIndex];
    if (slot.objectUrl) URL.revokeObjectURL(slot.objectUrl);
    const objectUrl = URL.createObjectURL(new Blob([bytes]));
    const prepared = Object.freeze({
      segmentId: segment.segment_id,
      ordinal: segment.ordinal,
      handle: Object.freeze({
        slot: slotIndex,
        element: slot.element,
        objectUrl,
      } satisfies DualAudioPreparedHandle),
    });
    slot.objectUrl = objectUrl;
    slot.prepared = prepared;
    slot.element.pause();
    slot.element.src = objectUrl;
    slot.element.load();
    return prepared;
  }

  async play(
    prepared: PreparedPlaybackSegment,
    rate: number,
    startOffsetMs: number,
    signal: AbortSignal,
  ): Promise<void> {
    throwIfAborted(signal);
    const handle = prepared.handle as DualAudioPreparedHandle;
    const element = handle.element;
    if (element.src !== handle.objectUrl && !element.src.endsWith(handle.objectUrl)) {
      throw new PlaybackQueueError(failure("PLAYBACK_FAILED", "双 audio 预加载槽位已失效。", true));
    }
    await this.waitForMetadata(element, signal);
    throwIfAborted(signal);
    const durationMs = Math.round(element.duration * 1_000);
    if (
      !Number.isSafeInteger(startOffsetMs)
      || startOffsetMs < 0
      || !Number.isSafeInteger(durationMs)
      || durationMs < 0
      || startOffsetMs > durationMs
    ) {
      throw new PlaybackQueueError(failure(
        "INVALID_PLAYBACK_RANGE",
        "恢复位置超出双 audio 的实际音频边界。",
        false,
      ));
    }
    this.current = element;
    this.playbackStarted = false;
    element.playbackRate = boundedRate(rate);
    element.currentTime = startOffsetMs / 1_000;
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const cleanup = () => {
        element.removeEventListener("ended", onEnded);
        element.removeEventListener("error", onError);
        signal.removeEventListener("abort", onAbort);
        if (this.current === element) {
          this.current = null;
          this.playbackStarted = false;
        }
      };
      const settle = (callback: () => void) => {
        if (settled) return;
        settled = true;
        cleanup();
        callback();
      };
      const onEnded = () => settle(resolve);
      const onError = () => settle(() => reject(new PlaybackQueueError(
        failure("PLAYBACK_FAILED", "双 audio 回退无法播放句段音频。", true),
      )));
      const onAbort = () => {
        element.pause();
        settle(() => reject(abortError()));
      };
      element.addEventListener("ended", onEnded, { once: true });
      element.addEventListener("error", onError, { once: true });
      signal.addEventListener("abort", onAbort, { once: true });
      void this.waitUntilResumed(signal).then(() => {
        if (settled) return;
        throwIfAborted(signal);
        this.playbackStarted = true;
        return element.play();
      }).catch((reason) => {
        if (isAbortError(reason) || signal.aborted) onAbort();
        else onError();
      });
    });
  }

  private waitUntilResumed(signal: AbortSignal): Promise<void> {
    if (!this.paused) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      let settled = false;
      const finish = (callback: () => void) => {
        if (settled) return;
        settled = true;
        this.resumeWaiters.delete(onResume);
        signal.removeEventListener("abort", onAbort);
        callback();
      };
      const onResume = () => finish(resolve);
      const onAbort = () => finish(() => reject(abortError()));
      if (signal.aborted) {
        onAbort();
        return;
      }
      this.resumeWaiters.add(onResume);
      signal.addEventListener("abort", onAbort, { once: true });
      if (!this.paused) onResume();
    });
  }

  private waitForMetadata(element: HTMLAudioElement, signal: AbortSignal): Promise<void> {
    if (element.readyState >= 1) {
      return Number.isFinite(element.duration)
        ? Promise.resolve()
        : Promise.reject(new PlaybackQueueError(failure(
            "MEDIA_DECODE_FAILED",
            "双 audio 未提供有效的音频时长。",
            false,
          )));
    }
    return new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        element.removeEventListener("loadedmetadata", onLoaded);
        element.removeEventListener("error", onError);
        signal.removeEventListener("abort", onAbort);
      };
      const onLoaded = () => {
        cleanup();
        if (!Number.isFinite(element.duration)) {
          reject(new PlaybackQueueError(failure(
            "MEDIA_DECODE_FAILED",
            "双 audio 未提供有效的音频时长。",
            false,
          )));
          return;
        }
        resolve();
      };
      const onError = () => {
        cleanup();
        reject(new PlaybackQueueError(failure(
          "MEDIA_DECODE_FAILED",
          "双 audio 无法读取音频元数据。",
          true,
        )));
      };
      const onAbort = () => {
        cleanup();
        reject(abortError());
      };
      if (signal.aborted) {
        onAbort();
        return;
      }
      element.addEventListener("loadedmetadata", onLoaded, { once: true });
      element.addEventListener("error", onError, { once: true });
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  release(prepared: PreparedPlaybackSegment): void {
    const handle = prepared.handle as DualAudioPreparedHandle;
    const slot = this.slots[handle.slot];
    if (slot.prepared !== prepared) return;
    slot.prepared = null;
    if (slot.objectUrl === handle.objectUrl) {
      URL.revokeObjectURL(handle.objectUrl);
      slot.objectUrl = null;
    }
  }

  readOffsetMs(): number {
    const offset = (this.current?.currentTime ?? 0) * 1_000;
    return Number.isFinite(offset) ? Math.max(0, Math.round(offset)) : 0;
  }

  pause(): void {
    this.paused = true;
    this.current?.pause();
  }

  async resume(): Promise<void> {
    if (!this.paused) return;
    this.paused = false;
    for (const resolve of [...this.resumeWaiters]) resolve();
    if (this.current && this.playbackStarted) await this.current.play();
  }

  setRate(rate: number): void {
    this.rate = boundedRate(rate);
    for (const slot of this.slots) slot.element.playbackRate = this.rate;
  }

  stop(): void {
    this.current?.pause();
    this.current = null;
    this.playbackStarted = false;
    this.paused = false;
  }

  dispose(): void {
    this.stop();
    for (const slot of this.slots) {
      slot.element.pause();
      slot.element.removeAttribute("src");
      slot.element.load();
      if (slot.objectUrl) URL.revokeObjectURL(slot.objectUrl);
      slot.objectUrl = null;
      slot.prepared = null;
    }
  }
}


export function createWebAudioPlaybackDriver(): SegmentPlaybackDriver | null {
  const scope = globalThis as unknown as {
    AudioContext?: new () => AudioContext;
    webkitAudioContext?: new () => AudioContext;
  };
  const Context = scope.AudioContext ?? scope.webkitAudioContext;
  if (!Context) return null;
  try {
    return new WebAudioPlaybackDriver(new Context());
  } catch {
    return null;
  }
}


export function createDualAudioPlaybackDriver(): SegmentPlaybackDriver | null {
  if (typeof document === "undefined" || typeof document.createElement !== "function") return null;
  return new DualAudioPlaybackDriver([
    document.createElement("audio"),
    document.createElement("audio"),
  ]);
}


/**
 * Fetches 3-5 contiguous ready segment assets, prefers one Web Audio clock,
 * and uses exactly two HTMLAudioElements as the only compatibility fallback.
 * It deliberately stops at the first non-ready segment instead of searching
 * for a later ready island.
 */
export class SegmentPlaybackQueue implements SegmentPlaybackQueuePort {
  private readonly prefetchSegments: number;
  private readonly fetchMedia: MediaFetcher;
  private readonly createWebAudioDriver: () => SegmentPlaybackDriver | null;
  private readonly createDualAudioDriver: () => SegmentPlaybackDriver | null;
  private readonly isLeaseCurrent: (lease: PlaybackLease) => boolean;
  private readonly onEvent: (event: SegmentPlaybackQueueEvent) => void;
  private active: ActiveOperation | null = null;
  private disposed = false;

  constructor(options: SegmentPlaybackQueueOptions = {}) {
    const prefetchSegments = options.prefetchSegments ?? 4;
    if (!Number.isSafeInteger(prefetchSegments) || prefetchSegments < 3 || prefetchSegments > 5) {
      throw new RangeError("prefetchSegments must be an integer between 3 and 5");
    }
    this.prefetchSegments = prefetchSegments;
    this.fetchMedia = options.fetchMedia ?? fetchPlaybackMedia;
    this.createWebAudioDriver = options.createWebAudioDriver ?? createWebAudioPlaybackDriver;
    this.createDualAudioDriver = options.createDualAudioDriver ?? createDualAudioPlaybackDriver;
    this.isLeaseCurrent = options.isLeaseCurrent ?? (() => true);
    this.onEvent = options.onEvent ?? (() => undefined);
  }

  start(options: SegmentPlaybackQueueStartOptions): Promise<SegmentPlaybackQueueStartResult> {
    if (this.disposed) {
      return Promise.resolve({
        kind: "error",
        lease: freezeLease(options.lease),
        backend: null,
        failure: failure("PLAYBACK_UNAVAILABLE", "播放队列已关闭。", false),
      });
    }
    const rate = boundedRate(options.rate);
    const lease = freezeLease(options.lease);
    const endOrdinalExclusive = options.endOrdinalExclusive ?? options.manifest.segments.length;
    const startOffsetMs = options.startOffsetMs ?? 0;
    const startSegment = options.manifest.segments[options.startOrdinal];
    if (
      lease.editionId !== options.manifest.edition_id
      || lease.manifestRevision !== options.manifest.manifest_revision
      || !Number.isSafeInteger(options.startOrdinal)
      || !Number.isSafeInteger(endOrdinalExclusive)
      || options.startOrdinal < 0
      || endOrdinalExclusive <= options.startOrdinal
      || endOrdinalExclusive > options.manifest.segments.length
      || !Number.isSafeInteger(startOffsetMs)
      || startOffsetMs < 0
      || startSegment?.render_status !== "ready"
      || !startSegment.audio
      || startOffsetMs > startSegment.audio.duration_ms
    ) {
      return Promise.resolve({
        kind: "error",
        lease,
        backend: null,
        failure: failure("INVALID_PLAYBACK_RANGE", "播放范围与 Manifest 租约不一致。", false),
      });
    }

    this.stop();
    const controller = new AbortController();
    const onExternalAbort = options.signal
      ? () => controller.abort(options.signal?.reason)
      : null;
    if (options.signal?.aborted) controller.abort(options.signal.reason);
    else if (onExternalAbort) options.signal?.addEventListener("abort", onExternalAbort, { once: true });

    let resolveStart!: (result: SegmentPlaybackQueueStartResult) => void;
    const startResult = new Promise<SegmentPlaybackQueueStartResult>((resolve) => {
      resolveStart = resolve;
    });
    const operation: ActiveOperation = {
      lease,
      manifest: options.manifest,
      startOrdinal: options.startOrdinal,
      startOffsetMs,
      endOrdinalExclusive,
      controller,
      externalSignal: options.signal,
      onExternalAbort,
      media: new Map(),
      prepared: new Map(),
      resolveStart,
      startResolved: false,
      driver: null,
      rate,
      paused: false,
      resumeWaiters: [],
      currentSegment: null,
    };
    this.active = operation;
    void this.run(operation);
    return startResult;
  }

  pause(): void {
    const operation = this.active;
    if (!operation || operation.controller.signal.aborted || operation.paused) return;
    operation.paused = true;
    operation.driver?.pause();
  }

  async resume(): Promise<void> {
    const operation = this.active;
    if (!operation || operation.controller.signal.aborted || !operation.paused) return;
    operation.paused = false;
    await operation.driver?.resume();
    for (const resolve of operation.resumeWaiters.splice(0)) resolve();
  }

  setRate(rate: number): void {
    const normalized = boundedRate(rate);
    if (!this.active) return;
    this.active.rate = normalized;
    this.active.driver?.setRate(normalized);
  }

  readPosition(): Readonly<{ segmentId: string; ordinal: number; offsetMs: number }> | null {
    const operation = this.active;
    const segment = operation?.currentSegment;
    if (!operation || !segment?.audio) return null;
    const offset = operation.driver?.readOffsetMs?.()
      ?? (segment.ordinal === operation.startOrdinal ? operation.startOffsetMs : 0);
    return Object.freeze({
      segmentId: segment.segment_id,
      ordinal: segment.ordinal,
      offsetMs: Math.max(0, Math.min(segment.audio.duration_ms, Math.round(offset))),
    });
  }

  stop(): void {
    const operation = this.active;
    if (!operation) return;
    operation.controller.abort("stopped");
    operation.driver?.stop();
    for (const resolve of operation.resumeWaiters.splice(0)) resolve();
    if (!operation.startResolved) {
      operation.startResolved = true;
      operation.resolveStart({ kind: "aborted", lease: operation.lease });
    }
    if (this.active === operation) this.active = null;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stop();
  }

  private operationIsCurrent(operation: ActiveOperation): boolean {
    return !this.disposed
      && this.active === operation
      && !operation.controller.signal.aborted
      && this.isLeaseCurrent(operation.lease);
  }

  private assertCurrent(operation: ActiveOperation): void {
    throwIfAborted(operation.controller.signal);
    if (!this.operationIsCurrent(operation)) throw abortError("stale playback lease");
  }

  private emit(
    operation: ActiveOperation,
    event: SegmentPlaybackQueueEvent,
  ): void {
    if (!this.operationIsCurrent(operation)) return;
    this.onEvent(Object.freeze(event));
  }

  private resolveStart(
    operation: ActiveOperation,
    result: SegmentPlaybackQueueStartResult,
  ): void {
    if (operation.startResolved) return;
    operation.startResolved = true;
    operation.resolveStart(Object.freeze(result));
  }

  private selectInitialDriver(): SegmentPlaybackDriver {
    const preferred = this.createWebAudioDriver();
    if (preferred) {
      if (preferred.kind !== "web-audio") {
        preferred.dispose();
        throw new PlaybackBackendCompatibilityError("preferred driver must be Web Audio");
      }
      return preferred;
    }
    const fallback = this.createDualAudioDriver();
    if (!fallback || fallback.kind !== "dual-audio") {
      fallback?.dispose();
      throw new PlaybackBackendCompatibilityError("neither Web Audio nor dual audio is available");
    }
    return fallback;
  }

  private switchToDualAudio(operation: ActiveOperation): void {
    const previous = operation.driver;
    if (previous?.kind === "dual-audio") throw new PlaybackBackendCompatibilityError("dual audio is unavailable");
    for (const prepared of operation.prepared.values()) previous?.release(prepared);
    operation.prepared.clear();
    previous?.dispose();
    const fallback = this.createDualAudioDriver();
    if (!fallback || fallback.kind !== "dual-audio") {
      fallback?.dispose();
      operation.driver = null;
      throw new PlaybackBackendCompatibilityError("dual audio is unavailable");
    }
    operation.driver = fallback;
    fallback.setRate(operation.rate);
    if (operation.paused) fallback.pause();
  }

  private kickMediaPrefetch(operation: ActiveOperation, fromOrdinal: number): void {
    const limit = Math.min(
      operation.endOrdinalExclusive,
      fromOrdinal + this.prefetchSegments,
    );
    for (let ordinal = fromOrdinal; ordinal < limit; ordinal += 1) {
      const segment = operation.manifest.segments[ordinal];
      if (segment.render_status !== "ready" || !segment.audio) break;
      if (operation.media.has(ordinal)) continue;
      const mediaPromise = this.fetchSegment(operation, segment)
        .then((bytes): MediaResult => ({ ok: true, bytes }))
        .catch((error): MediaResult => ({ ok: false, error }));
      operation.media.set(ordinal, mediaPromise);
    }
  }

  private async fetchSegment(
    operation: ActiveOperation,
    segment: ManifestSegmentV2,
  ): Promise<ArrayBuffer> {
    const audio = segment.audio;
    if (!audio) {
      throw new PlaybackQueueError(failure("MEDIA_FETCH_FAILED", "句段没有可播放资产。", true, segment));
    }
    let response: Response;
    try {
      response = await this.fetchMedia({
        url: audio.url,
        editionId: operation.lease.editionId,
        manifestRevision: operation.lease.manifestRevision,
        signal: operation.controller.signal,
      });
    } catch (reason) {
      if (isAbortError(reason) || operation.controller.signal.aborted) throw abortError();
      throw new PlaybackQueueError(failure(
        "MEDIA_FETCH_FAILED",
        "句段音频读取失败。",
        true,
        segment,
      ));
    }
    this.assertCurrent(operation);
    if (response.status !== 200 && response.status !== 206) {
      throw new PlaybackQueueError(failure(
        "MEDIA_FETCH_FAILED",
        `句段音频返回不可播放状态 ${response.status}。`,
        response.status === 416,
        segment,
      ));
    }
    const responseEtag = response.headers.get("ETag");
    if (responseEtag && responseEtag !== audio.etag) {
      throw new PlaybackQueueError(failure(
        "MEDIA_INTEGRITY_FAILED",
        "句段音频 ETag 与 Manifest 不一致。",
        false,
        segment,
      ));
    }
    const bytes = await response.arrayBuffer();
    this.assertCurrent(operation);
    if (bytes.byteLength === 0) {
      throw new PlaybackQueueError(failure("MEDIA_INTEGRITY_FAILED", "句段音频为空。", false, segment));
    }
    return bytes;
  }

  private async prepareWindow(operation: ActiveOperation, fromOrdinal: number): Promise<void> {
    this.assertCurrent(operation);
    this.kickMediaPrefetch(operation, fromOrdinal);
    const driver = operation.driver;
    if (!driver) throw new PlaybackBackendCompatibilityError("playback driver is unavailable");
    const prepareCount = driver.kind === "web-audio" ? this.prefetchSegments : 2;
    const limit = Math.min(operation.endOrdinalExclusive, fromOrdinal + prepareCount);
    for (let ordinal = fromOrdinal; ordinal < limit; ordinal += 1) {
      const segment = operation.manifest.segments[ordinal];
      if (segment.render_status !== "ready" || !segment.audio) break;
      if (operation.prepared.has(ordinal)) continue;
      const media = await operation.media.get(ordinal);
      this.assertCurrent(operation);
      if (!media) throw new PlaybackQueueError(failure("MEDIA_FETCH_FAILED", "句段预取未启动。", true, segment));
      if (!media.ok) throw media.error;
      try {
        const prepared = await driver.prepare(
          segment,
          media.bytes,
          (ordinal % 2) as 0 | 1,
          operation.controller.signal,
        );
        this.assertCurrent(operation);
        operation.prepared.set(ordinal, prepared);
      } catch (reason) {
        if (reason instanceof PlaybackBackendCompatibilityError && driver.kind === "web-audio") {
          this.switchToDualAudio(operation);
          await this.prepareWindow(operation, fromOrdinal);
          return;
        }
        throw reason;
      }
    }
  }

  private async waitWhilePaused(operation: ActiveOperation): Promise<void> {
    while (operation.paused) {
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          operation.controller.signal.removeEventListener("abort", onAbort);
          reject(abortError());
        };
        operation.controller.signal.addEventListener("abort", onAbort, { once: true });
        operation.resumeWaiters.push(() => {
          operation.controller.signal.removeEventListener("abort", onAbort);
          resolve();
        });
      });
      this.assertCurrent(operation);
    }
  }

  private block(
    operation: ActiveOperation,
    segment: ManifestSegmentV2,
  ): SegmentPlaybackQueueStartResult {
    const currentFailure = blockingFailure(segment);
    const backend = operation.driver?.kind ?? "dual-audio";
    const event: SegmentPlaybackQueueEvent = {
      type: "blocked",
      lease: operation.lease,
      backend,
      failure: currentFailure,
    };
    this.emit(operation, event);
    const result: SegmentPlaybackQueueStartResult = {
      kind: "blocked",
      lease: operation.lease,
      backend,
      failure: currentFailure,
    };
    this.resolveStart(operation, result);
    return result;
  }

  private async run(operation: ActiveOperation): Promise<void> {
    let currentSegment: ManifestSegmentV2 | null = null;
    let lastPlayed: ManifestSegmentV2 | null = null;
    try {
      this.assertCurrent(operation);
      operation.driver = this.selectInitialDriver();
      operation.driver.setRate(operation.rate);

      for (
        let ordinal = operation.startOrdinal;
        ordinal < operation.endOrdinalExclusive;
        ordinal += 1
      ) {
        this.assertCurrent(operation);
        currentSegment = operation.manifest.segments[ordinal];
        operation.currentSegment = currentSegment;
        if (currentSegment.render_status !== "ready" || !currentSegment.audio) {
          this.block(operation, currentSegment);
          return;
        }

        await this.waitWhilePaused(operation);
        this.emit(operation, {
          type: "buffering",
          lease: operation.lease,
          backend: operation.driver.kind,
          segmentId: currentSegment.segment_id,
          ordinal,
          durationMs: currentSegment.audio.duration_ms,
        });
        await this.prepareWindow(operation, ordinal);
        this.assertCurrent(operation);
        // A pause issued while fetch/decode was in flight remains authoritative.
        // Decoding completion must never start audio behind the user's back.
        await this.waitWhilePaused(operation);
        const prepared = operation.prepared.get(ordinal);
        if (!prepared) {
          throw new PlaybackQueueError(failure("MEDIA_DECODE_FAILED", "句段音频未完成解码。", true, currentSegment));
        }

        this.emit(operation, {
          type: "segment-start",
          lease: operation.lease,
          backend: operation.driver.kind,
          segmentId: currentSegment.segment_id,
          ordinal,
          offsetMs: ordinal === operation.startOrdinal ? operation.startOffsetMs : 0,
          durationMs: currentSegment.audio.duration_ms,
        });
        this.resolveStart(operation, {
          kind: "started",
          lease: operation.lease,
          backend: operation.driver.kind,
          segmentId: currentSegment.segment_id,
          ordinal,
        });
        await operation.driver.play(
          prepared,
          operation.rate,
          ordinal === operation.startOrdinal ? operation.startOffsetMs : 0,
          operation.controller.signal,
        );
        this.assertCurrent(operation);
        this.emit(operation, {
          type: "segment-end",
          lease: operation.lease,
          backend: operation.driver.kind,
          segmentId: currentSegment.segment_id,
          ordinal,
          offsetMs: currentSegment.audio.duration_ms,
          durationMs: currentSegment.audio.duration_ms,
        });
        operation.driver.release(prepared);
        operation.prepared.delete(ordinal);
        operation.media.delete(ordinal);
        lastPlayed = currentSegment;

        const nextOrdinal = ordinal + 1;
        if (nextOrdinal < operation.endOrdinalExclusive) {
          const next = operation.manifest.segments[nextOrdinal];
          if (next.render_status !== "ready" || !next.audio) {
            this.block(operation, next);
            return;
          }
          await delay(currentSegment.gap_after_ms / operation.rate, operation.controller.signal);
          await this.waitWhilePaused(operation);
        }
      }

      if (operation.endOrdinalExclusive < operation.manifest.segments.length) {
        const next = operation.manifest.segments[operation.endOrdinalExclusive];
        if (next.render_status !== "ready" || !next.audio) {
          this.block(operation, next);
          return;
        }
      }
      this.emit(operation, {
        type: "ended",
        lease: operation.lease,
        backend: operation.driver.kind,
        lastSegmentId: lastPlayed?.segment_id ?? null,
        lastOrdinal: lastPlayed?.ordinal ?? null,
      });
    } catch (reason) {
      if (isAbortError(reason) || operation.controller.signal.aborted || !this.operationIsCurrent(operation)) {
        this.resolveStart(operation, { kind: "aborted", lease: operation.lease });
        return;
      }
      const currentFailure = genericFailure(reason, currentSegment);
      const result: SegmentPlaybackQueueStartResult = {
        kind: "error",
        lease: operation.lease,
        backend: operation.driver?.kind ?? null,
        failure: currentFailure,
      };
      this.emit(operation, {
        type: "error",
        lease: operation.lease,
        backend: operation.driver?.kind ?? null,
        failure: currentFailure,
      });
      this.resolveStart(operation, result);
    } finally {
      if (operation.externalSignal && operation.onExternalAbort) {
        operation.externalSignal.removeEventListener("abort", operation.onExternalAbort);
      }
      for (const prepared of operation.prepared.values()) operation.driver?.release(prepared);
      operation.prepared.clear();
      operation.driver?.dispose();
      if (this.active === operation) this.active = null;
      if (!operation.startResolved) {
        operation.startResolved = true;
        operation.resolveStart({ kind: "aborted", lease: operation.lease });
      }
    }
  }
}
