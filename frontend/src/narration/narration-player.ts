import { PlaybackApiError, prepareNarrationRange } from "./playback-api";
import {
  ManifestValidationError,
  validateManifest,
  type ManifestFailure,
  type ManifestSegmentV2,
  type NarrationManifestV2,
  type PrepareRangeReason,
  type PrepareRangeResponse,
  type ReadyRange,
} from "./playback-contracts";
import {
  SegmentPlaybackQueue,
  playbackLeasesEqual,
  type PlaybackLease,
  type SegmentPlaybackBackendKind,
  type SegmentPlaybackFailure,
  type SegmentPlaybackFailureCode,
  type SegmentPlaybackQueueEvent,
  type SegmentPlaybackQueuePort,
  type SegmentPlaybackQueueStartResult,
} from "./segment-playback-queue";


export type { PlaybackLease } from "./segment-playback-queue";


export type NarrationPlaybackSource =
  | "default"
  | "resume"
  | "gutter"
  | "command"
  | "readonly-segment";


export type NarrationPlayerPhase =
  | "idle"
  | "preparing"
  | "buffering"
  | "playing"
  | "paused"
  | "blocked"
  | "ended"
  | "error";


export interface NarrationPlayerState {
  readonly phase: NarrationPlayerPhase;
  readonly currentSegmentId: string | null;
  readonly currentOrdinal: number | null;
  readonly offsetMs: number;
  readonly durationMs: number;
  readonly rate: number;
  readonly volume: number;
  readonly followPaused: boolean;
  readonly backend: SegmentPlaybackBackendKind | null;
  readonly source: NarrationPlaybackSource | null;
  readonly failure: SegmentPlaybackFailure | null;
}


export type PlaybackDecision = Readonly<
  | {
      kind: "play";
      lease: PlaybackLease;
      segmentId: string;
      ordinal: number;
      backend: SegmentPlaybackBackendKind;
    }
  | {
      kind: "preparing";
      lease: PlaybackLease;
      segmentId: string;
      ordinal: number;
      prepareState: "ready" | "preparing";
      promotedJobIds: readonly string[];
    }
  | {
      kind: "blocked";
      lease: PlaybackLease;
      failure: SegmentPlaybackFailure;
    }
  | {
      kind: "missing";
      lease: PlaybackLease;
      segmentId: string;
    }
  | {
      kind: "aborted";
      lease: PlaybackLease;
    }
  | {
      kind: "error";
      lease: PlaybackLease;
      failure: SegmentPlaybackFailure;
    }
  | {
      kind: "noop";
      lease: PlaybackLease;
      reason: "manifest_not_bound" | "not_paused" | "no_current_segment";
    }
>;


export interface NarrationPlayerController {
  readonly lease: PlaybackLease;
  readState(): NarrationPlayerState;
  bindManifest(manifest: NarrationManifestV2): void;
  playFromSegment(
    segmentId: string,
    source: NarrationPlaybackSource,
    startOffsetMs?: number,
  ): Promise<PlaybackDecision>;
  pause(): void;
  resume(): Promise<PlaybackDecision>;
  setRate(rate: number): void;
  setVolume(volume: number): void;
  updateManifest(manifest: NarrationManifestV2): void;
  subscribe(listener: (state: NarrationPlayerState) => void): () => void;
  dispose(): void;
}


type PrepareRange = (
  editionId: string,
  startSegmentId: string,
  reason: PrepareRangeReason,
  expectedManifestRevision: number,
  idempotencyKey: string,
  signal?: AbortSignal,
) => Promise<PrepareRangeResponse>;


export interface NarrationPlayerQueueHooks {
  readonly isLeaseCurrent: (lease: PlaybackLease) => boolean;
  readonly onEvent: (event: SegmentPlaybackQueueEvent) => void;
}


export interface CreateNarrationPlayerOptions {
  readonly documentId: string;
  readonly documentGeneration: number;
  readonly editionId: string;
  readonly initialManifestRevision?: number;
  readonly initialManifest?: NarrationManifestV2;
  readonly initialPosition?: Readonly<{
    segmentId: string;
    ordinal: number;
    offsetMs: number;
  }>;
  readonly rate?: number;
  readonly initialVolume?: number;
  readonly isDocumentLeaseCurrent?: (
    documentId: string,
    documentGeneration: number,
  ) => boolean;
  readonly prepareRange?: PrepareRange;
  readonly createQueue?: (hooks: NarrationPlayerQueueHooks) => SegmentPlaybackQueuePort;
  readonly createIdempotencyKey?: (lease: PlaybackLease, segmentId: string) => string;
}


type ManifestPlaybackPlan = Readonly<
  | {
      kind: "play";
      target: ManifestSegmentV2;
      readyRange: ReadyRange;
    }
  | {
      kind: "prepare";
      target: ManifestSegmentV2;
      reason: "target_not_ready" | "ready_window_too_short";
    }
  | {
      kind: "blocked";
      target: ManifestSegmentV2;
      failedSegment: ManifestSegmentV2;
      reason: "target_failed" | "target_cancelled" | "gap_failed" | "gap_cancelled";
    }
  | {
      kind: "missing";
      segmentId: string;
    }
>;


function assertManifest(manifest: NarrationManifestV2): void {
  const problems = validateManifest(manifest);
  if (problems.length > 0) throw new ManifestValidationError(problems);
}


function boundedRate(rate: number): number {
  if (!Number.isFinite(rate) || rate < 0.5 || rate > 3) {
    throw new RangeError("playback rate must be between 0.5 and 3");
  }
  return rate;
}


function boundedVolume(volume: number): number {
  if (!Number.isFinite(volume) || volume < 0 || volume > 1) {
    throw new RangeError("playback volume must be between 0 and 1");
  }
  return volume;
}


function freezeLease(lease: PlaybackLease): PlaybackLease {
  return Object.freeze({ ...lease });
}


function freezeState(state: NarrationPlayerState): NarrationPlayerState {
  return Object.freeze({ ...state });
}


function playerFailure(
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


function failureFromManifest(
  segment: ManifestSegmentV2,
  manifestFailure: ManifestFailure | null,
): SegmentPlaybackFailure {
  if (segment.render_status === "cancelled") {
    return playerFailure("CANCELLED_GAP", "该句段生成已取消。", true, segment);
  }
  return playerFailure(
    "FAILED_GAP",
    manifestFailure?.message ?? "该句段合成失败。",
    manifestFailure?.retryable ?? false,
    segment,
  );
}


function contiguousReadyEnd(manifest: NarrationManifestV2, startOrdinal: number): number {
  let end = startOrdinal;
  while (
    end < manifest.segments.length
    && manifest.segments[end].render_status === "ready"
    && manifest.segments[end].audio
  ) {
    end += 1;
  }
  return end;
}


/**
 * Consumes only server-authoritative ready ranges.  It never searches past the
 * first gap for a later ready island.
 */
export function decideManifestPlayback(
  manifest: NarrationManifestV2,
  segmentId: string,
): ManifestPlaybackPlan {
  assertManifest(manifest);
  const target = manifest.segments.find((segment) => segment.segment_id === segmentId);
  if (!target) return Object.freeze({ kind: "missing", segmentId });
  if (target.render_status === "failed") {
    return Object.freeze({
      kind: "blocked",
      target,
      failedSegment: target,
      reason: "target_failed",
    });
  }
  if (target.render_status === "cancelled") {
    return Object.freeze({
      kind: "blocked",
      target,
      failedSegment: target,
      reason: "target_cancelled",
    });
  }
  if (target.render_status !== "ready" || !target.audio) {
    return Object.freeze({ kind: "prepare", target, reason: "target_not_ready" });
  }

  const readyEnd = contiguousReadyEnd(manifest, target.ordinal);
  const authoritativeRange = manifest.ready_ranges.find((range) => (
    range.start_ordinal <= target.ordinal
    && range.end_ordinal_exclusive > target.ordinal
    && range.last_playable_start_ordinal >= target.ordinal
  ));
  if (authoritativeRange) {
    return Object.freeze({ kind: "play", target, readyRange: authoritativeRange });
  }
  const gap = manifest.segments[readyEnd];
  if (gap?.render_status === "failed") {
    return Object.freeze({
      kind: "blocked",
      target,
      failedSegment: gap,
      reason: "gap_failed",
    });
  }
  if (gap?.render_status === "cancelled") {
    return Object.freeze({
      kind: "blocked",
      target,
      failedSegment: gap,
      reason: "gap_cancelled",
    });
  }
  return Object.freeze({ kind: "prepare", target, reason: "ready_window_too_short" });
}


function validateManifestRefresh(
  current: NarrationManifestV2,
  incoming: NarrationManifestV2,
): void {
  assertManifest(incoming);
  if (incoming.edition_id !== current.edition_id || incoming.chapter_id !== current.chapter_id) {
    throw new Error("Manifest refresh cannot switch Edition or chapter");
  }
  if (
    incoming.source_revision_id !== current.source_revision_id
    || incoming.source_sha256 !== current.source_sha256
  ) {
    throw new Error("Manifest refresh cannot switch immutable source");
  }
  if (incoming.manifest_revision < current.manifest_revision) {
    throw new Error("Manifest revision cannot regress");
  }
  if (
    incoming.manifest_revision === current.manifest_revision
    && incoming.etag !== current.etag
  ) {
    throw new Error("Manifest revision collision");
  }
}


function defaultIdempotencyKey(lease: PlaybackLease, segmentId: string): string {
  return `seek:${lease.editionId}:${lease.manifestRevision}:${lease.requestGeneration}:${segmentId}`;
}


function apiFailure(reason: unknown, segment: ManifestSegmentV2): SegmentPlaybackFailure {
  if (reason instanceof PlaybackApiError) {
    const code = reason.detail?.code;
    if (code === "MANIFEST_REVISION_CONFLICT") {
      return playerFailure(
        "STALE_PLAYBACK_LEASE",
        "Manifest 已更新，请使用新版本重试。",
        true,
        segment,
      );
    }
    return playerFailure(
      "PLAYBACK_FAILED",
      reason.detail?.message ?? "准备播放范围失败。",
      reason.detail?.retryable ?? reason.status >= 500,
      segment,
    );
  }
  if (reason instanceof Error && reason.name === "AbortError") {
    return playerFailure("STALE_PLAYBACK_LEASE", "播放请求已被新的跳播取代。", true, segment);
  }
  return playerFailure("PLAYBACK_FAILED", "准备播放范围失败。", true, segment);
}


export class ProductionNarrationPlayerController implements NarrationPlayerController {
  private readonly listeners = new Set<(state: NarrationPlayerState) => void>();
  private readonly isDocumentLeaseCurrent: (
    documentId: string,
    documentGeneration: number,
  ) => boolean;
  private readonly prepareRange: PrepareRange;
  private readonly createIdempotencyKey: (lease: PlaybackLease, segmentId: string) => string;
  private readonly queue: SegmentPlaybackQueuePort;
  private manifest: NarrationManifestV2 | null;
  private currentLease: PlaybackLease;
  private state: NarrationPlayerState;
  private requestGeneration = 0;
  private requestAbort: AbortController | null = null;
  private disposed = false;

  constructor(private readonly options: CreateNarrationPlayerOptions) {
    if (!options.documentId || !options.editionId) {
      throw new Error("documentId and editionId are required");
    }
    if (!Number.isSafeInteger(options.documentGeneration) || options.documentGeneration < 0) {
      throw new RangeError("documentGeneration must be a non-negative safe integer");
    }
    const initialRevision = options.initialManifest?.manifest_revision
      ?? options.initialManifestRevision
      ?? 1;
    if (!Number.isSafeInteger(initialRevision) || initialRevision < 1) {
      throw new RangeError("initialManifestRevision must be a positive safe integer");
    }
    const rate = boundedRate(options.rate ?? 1);
    const volume = boundedVolume(options.initialVolume ?? 1);
    this.manifest = options.initialManifest ?? null;
    if (this.manifest) {
      assertManifest(this.manifest);
      if (this.manifest.edition_id !== options.editionId) {
        throw new Error("initial Manifest Edition does not match the player scope");
      }
    }
    const initialPosition = options.initialPosition;
    let initialSegment: ManifestSegmentV2 | null = null;
    if (initialPosition) {
      initialSegment = this.manifest?.segments[initialPosition.ordinal] ?? null;
      if (
        !initialSegment
        || initialSegment.segment_id !== initialPosition.segmentId
        || initialSegment.render_status !== "ready"
        || !initialSegment.audio
        || !Number.isSafeInteger(initialPosition.offsetMs)
        || initialPosition.offsetMs < 0
        || initialPosition.offsetMs > initialSegment.audio.duration_ms
      ) {
        throw new RangeError("initial playback position must match ready Manifest audio");
      }
    }
    this.currentLease = freezeLease({
      documentId: options.documentId,
      documentGeneration: options.documentGeneration,
      editionId: options.editionId,
      manifestRevision: initialRevision,
      requestGeneration: 0,
    });
    this.state = freezeState({
      phase: "idle",
      currentSegmentId: initialSegment?.segment_id ?? null,
      currentOrdinal: initialSegment?.ordinal ?? null,
      offsetMs: initialPosition?.offsetMs ?? 0,
      durationMs: initialSegment?.audio?.duration_ms ?? 0,
      rate,
      volume,
      followPaused: false,
      backend: null,
      source: null,
      failure: null,
    });
    this.isDocumentLeaseCurrent = options.isDocumentLeaseCurrent ?? (() => true);
    this.prepareRange = options.prepareRange ?? prepareNarrationRange;
    this.createIdempotencyKey = options.createIdempotencyKey ?? defaultIdempotencyKey;
    const createQueue = options.createQueue ?? ((hooks: NarrationPlayerQueueHooks) => (
      new SegmentPlaybackQueue({
        isLeaseCurrent: hooks.isLeaseCurrent,
        onEvent: hooks.onEvent,
      })
    ));
    this.queue = createQueue({
      isLeaseCurrent: (lease) => this.isLeaseCurrent(lease),
      onEvent: (event) => this.handleQueueEvent(event),
    });
  }

  get lease(): PlaybackLease {
    return this.currentLease;
  }

  readState(): NarrationPlayerState {
    return this.state;
  }

  bindManifest(manifest: NarrationManifestV2): void {
    this.assertUsable();
    assertManifest(manifest);
    if (manifest.edition_id !== this.options.editionId) {
      throw new Error("Manifest Edition does not match the player scope");
    }
    this.cancelCurrentRequest();
    this.manifest = manifest;
    this.currentLease = freezeLease({
      ...this.currentLease,
      manifestRevision: manifest.manifest_revision,
    });
    this.publish({
      phase: "idle",
      currentSegmentId: null,
      currentOrdinal: null,
      offsetMs: 0,
      durationMs: 0,
      backend: null,
      source: null,
      failure: null,
    });
  }

  async playFromSegment(
    segmentId: string,
    source: NarrationPlaybackSource,
    startOffsetMs = 0,
  ): Promise<PlaybackDecision> {
    this.assertUsable();
    if (!this.manifest) {
      return Object.freeze({ kind: "noop", lease: this.currentLease, reason: "manifest_not_bound" });
    }
    const plan = decideManifestPlayback(this.manifest, segmentId);
    const lease = this.beginRequest(this.manifest.manifest_revision);
    if (plan.kind === "missing") {
      this.publish({
        phase: "error",
        source,
        failure: playerFailure("INVALID_PLAYBACK_RANGE", "Manifest 中不存在目标句段。", false),
      });
      return Object.freeze({ kind: "missing", lease, segmentId });
    }
    if (plan.kind === "blocked") {
      const currentFailure = failureFromManifest(plan.failedSegment, plan.failedSegment.failure);
      this.publish({
        phase: "blocked",
        currentSegmentId: plan.target.segment_id,
        currentOrdinal: plan.target.ordinal,
        offsetMs: 0,
        durationMs: plan.target.audio?.duration_ms ?? 0,
        source,
        failure: currentFailure,
      });
      this.finishRequest(lease);
      return Object.freeze({ kind: "blocked", lease, failure: currentFailure });
    }
    if (!Number.isSafeInteger(startOffsetMs) || startOffsetMs < 0) {
      throw new RangeError("startOffsetMs must be a non-negative safe integer");
    }
    if (plan.kind === "prepare") {
      return this.prepare(plan.target, source, lease);
    }

    const targetAudio = plan.target.audio;
    if (!targetAudio) {
      const currentFailure = playerFailure("MEDIA_FETCH_FAILED", "句段缺少播放资产。", true, plan.target);
      this.publish({ phase: "error", source, failure: currentFailure });
      this.finishRequest(lease);
      return Object.freeze({ kind: "error", lease, failure: currentFailure });
    }
    if (startOffsetMs > targetAudio.duration_ms) {
      throw new RangeError("startOffsetMs exceeds the target audio duration");
    }
    this.publish({
      phase: "buffering",
      currentSegmentId: plan.target.segment_id,
      currentOrdinal: plan.target.ordinal,
      offsetMs: startOffsetMs,
      durationMs: targetAudio.duration_ms,
      backend: null,
      source,
      failure: null,
    });
    const signal = this.requestAbort?.signal;
    const result = await this.queue.start({
      lease,
      manifest: this.manifest,
      startOrdinal: plan.target.ordinal,
      endOrdinalExclusive: plan.readyRange.end_ordinal_exclusive,
      rate: this.state.rate,
      volume: boundedVolume(this.state.volume),
      startOffsetMs,
      signal,
    });
    return this.decisionFromQueueResult(result, source);
  }

  pause(): void {
    if (this.disposed || !["playing", "buffering"].includes(this.state.phase)) return;
    this.queue.pause();
    const position = this.queue.readPosition?.();
    this.publish({
      phase: "paused",
      ...(position ? {
        currentSegmentId: position.segmentId,
        currentOrdinal: position.ordinal,
        offsetMs: position.offsetMs,
      } : {}),
    });
  }

  async resume(): Promise<PlaybackDecision> {
    this.assertUsable();
    if (this.state.phase === "blocked" && this.state.failure?.code === "PENDING_GAP") {
      const segmentId = this.state.failure.segmentId ?? this.state.currentSegmentId;
      if (!segmentId) {
        return Object.freeze({ kind: "noop", lease: this.currentLease, reason: "no_current_segment" });
      }
      return this.playFromSegment(segmentId, "resume");
    }
    if (this.state.phase !== "paused") {
      return Object.freeze({ kind: "noop", lease: this.currentLease, reason: "not_paused" });
    }
    const lease = this.currentLease;
    try {
      await this.queue.resume();
      if (!this.isLeaseCurrent(lease)) return Object.freeze({ kind: "aborted", lease });
      this.publish({ phase: "playing", failure: null });
      if (
        this.state.currentSegmentId === null
        || this.state.currentOrdinal === null
        || this.state.backend === null
      ) {
        return Object.freeze({ kind: "noop", lease, reason: "no_current_segment" });
      }
      return Object.freeze({
        kind: "play",
        lease,
        segmentId: this.state.currentSegmentId,
        ordinal: this.state.currentOrdinal,
        backend: this.state.backend,
      });
    } catch {
      const currentFailure = playerFailure("PLAYBACK_FAILED", "恢复播放失败。", true);
      this.publish({ phase: "error", failure: currentFailure });
      this.finishRequest(lease);
      return Object.freeze({ kind: "error", lease, failure: currentFailure });
    }
  }

  setRate(rate: number): void {
    this.assertUsable();
    const normalized = boundedRate(rate);
    this.queue.setRate(normalized);
    this.publish({ rate: normalized });
  }

  setVolume(volume: number): void {
    this.assertUsable();
    const normalized = boundedVolume(volume);
    this.queue.setVolume(normalized);
    this.publish({ volume: normalized });
  }

  setFollowPaused(paused: boolean): void {
    this.assertUsable();
    this.publish({ followPaused: paused });
  }

  updateManifest(manifest: NarrationManifestV2): void {
    this.assertUsable();
    if (!this.manifest) {
      this.bindManifest(manifest);
      return;
    }
    validateManifestRefresh(this.manifest, manifest);
    if (
      manifest.manifest_revision === this.manifest.manifest_revision
      && manifest.etag === this.manifest.etag
    ) return;
    this.manifest = manifest;
    // Already queued assets retain their original complete lease.  The newer
    // revision becomes active only after that request reaches a boundary.
    if (!this.requestAbort) this.adoptLatestManifestRevision();
  }

  subscribe(listener: (state: NarrationPlayerState) => void): () => void {
    this.assertUsable();
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.cancelCurrentRequest();
    this.queue.dispose();
    this.listeners.clear();
  }

  private assertUsable(): void {
    if (this.disposed) throw new Error("NarrationPlayerController is disposed");
  }

  private isLeaseCurrent(lease: PlaybackLease): boolean {
    return !this.disposed
      && playbackLeasesEqual(lease, this.currentLease)
      && this.isDocumentLeaseCurrent(lease.documentId, lease.documentGeneration);
  }

  private beginRequest(manifestRevision: number): PlaybackLease {
    this.cancelCurrentRequest();
    this.requestGeneration += 1;
    this.requestAbort = new AbortController();
    this.currentLease = freezeLease({
      documentId: this.options.documentId,
      documentGeneration: this.options.documentGeneration,
      editionId: this.options.editionId,
      manifestRevision,
      requestGeneration: this.requestGeneration,
    });
    return this.currentLease;
  }

  private cancelCurrentRequest(): void {
    this.requestAbort?.abort("superseded");
    this.requestAbort = null;
    this.queue?.stop();
  }

  private finishRequest(lease: PlaybackLease): void {
    if (!this.isLeaseCurrent(lease)) return;
    this.requestAbort = null;
    this.adoptLatestManifestRevision();
  }

  private adoptLatestManifestRevision(): void {
    if (!this.manifest || this.currentLease.manifestRevision === this.manifest.manifest_revision) return;
    this.currentLease = freezeLease({
      ...this.currentLease,
      manifestRevision: this.manifest.manifest_revision,
    });
  }

  private publish(patch: Partial<NarrationPlayerState>): void {
    if (this.disposed) return;
    this.state = freezeState({ ...this.state, ...patch });
    for (const listener of [...this.listeners]) listener(this.state);
  }

  private async prepare(
    target: ManifestSegmentV2,
    source: NarrationPlaybackSource,
    lease: PlaybackLease,
  ): Promise<PlaybackDecision> {
    this.publish({
      phase: "preparing",
      currentSegmentId: target.segment_id,
      currentOrdinal: target.ordinal,
      offsetMs: 0,
      durationMs: target.audio?.duration_ms ?? 0,
      backend: null,
      source,
      failure: null,
    });
    const reason: PrepareRangeReason = source === "resume" ? "resume" : "user_seek";
    try {
      const response = await this.prepareRange(
        lease.editionId,
        target.segment_id,
        reason,
        lease.manifestRevision,
        this.createIdempotencyKey(lease, target.segment_id),
        this.requestAbort?.signal,
      );
      if (!this.isLeaseCurrent(lease)) return Object.freeze({ kind: "aborted", lease });
      if (response.state === "failed") {
        const currentFailure = playerFailure("PLAYBACK_FAILED", "目标播放范围准备失败。", true, target);
        this.publish({ phase: "blocked", failure: currentFailure });
        this.finishRequest(lease);
        return Object.freeze({ kind: "blocked", lease, failure: currentFailure });
      }
      this.publish({ phase: "preparing", failure: null });
      this.finishRequest(lease);
      return Object.freeze({
        kind: "preparing",
        lease,
        segmentId: target.segment_id,
        ordinal: target.ordinal,
        prepareState: response.state,
        promotedJobIds: Object.freeze([...response.promoted_job_ids]),
      });
    } catch (reason) {
      if (!this.isLeaseCurrent(lease)) return Object.freeze({ kind: "aborted", lease });
      const currentFailure = apiFailure(reason, target);
      if (currentFailure.code === "STALE_PLAYBACK_LEASE") {
        this.publish({ phase: "blocked", failure: currentFailure });
        this.finishRequest(lease);
        return Object.freeze({ kind: "blocked", lease, failure: currentFailure });
      }
      this.publish({ phase: "error", failure: currentFailure });
      this.finishRequest(lease);
      return Object.freeze({ kind: "error", lease, failure: currentFailure });
    }
  }

  private decisionFromQueueResult(
    result: SegmentPlaybackQueueStartResult,
    source: NarrationPlaybackSource,
  ): PlaybackDecision {
    if (result.kind === "aborted") return Object.freeze({ kind: "aborted", lease: result.lease });
    if (!this.isLeaseCurrent(result.lease)) {
      return Object.freeze({ kind: "aborted", lease: result.lease });
    }
    if (result.kind === "blocked") {
      this.publish({ phase: "blocked", source, failure: result.failure });
      this.finishRequest(result.lease);
      return Object.freeze({ kind: "blocked", lease: result.lease, failure: result.failure });
    }
    if (result.kind === "error") {
      this.publish({ phase: "error", source, failure: result.failure });
      this.finishRequest(result.lease);
      return Object.freeze({ kind: "error", lease: result.lease, failure: result.failure });
    }
    return Object.freeze({
      kind: "play",
      lease: result.lease,
      segmentId: result.segmentId,
      ordinal: result.ordinal,
      backend: result.backend,
    });
  }

  private handleQueueEvent(event: SegmentPlaybackQueueEvent): void {
    if (!this.isLeaseCurrent(event.lease)) return;
    if (event.type === "buffering") {
      this.publish({
        phase: this.state.phase === "paused" ? "paused" : "buffering",
        currentSegmentId: event.segmentId,
        currentOrdinal: event.ordinal,
        offsetMs: this.state.currentSegmentId === event.segmentId ? this.state.offsetMs : 0,
        durationMs: event.durationMs,
        backend: event.backend,
        failure: null,
      });
      return;
    }
    if (event.type === "segment-start") {
      this.publish({
        phase: "playing",
        currentSegmentId: event.segmentId,
        currentOrdinal: event.ordinal,
        offsetMs: event.offsetMs,
        durationMs: event.durationMs,
        backend: event.backend,
        failure: null,
      });
      return;
    }
    if (event.type === "segment-end") {
      this.publish({
        currentSegmentId: event.segmentId,
        currentOrdinal: event.ordinal,
        offsetMs: event.offsetMs,
        durationMs: event.durationMs,
        backend: event.backend,
      });
      return;
    }
    if (event.type === "blocked") {
      this.publish({ phase: "blocked", backend: event.backend, failure: event.failure });
      this.finishRequest(event.lease);
      return;
    }
    if (event.type === "ended") {
      this.publish({
        phase: "ended",
        currentSegmentId: event.lastSegmentId,
        currentOrdinal: event.lastOrdinal,
        backend: event.backend,
        failure: null,
      });
      this.finishRequest(event.lease);
      return;
    }
    this.publish({ phase: "error", backend: event.backend, failure: event.failure });
    this.finishRequest(event.lease);
  }
}


export function createNarrationPlayerController(
  options: CreateNarrationPlayerOptions,
): NarrationPlayerController {
  return new ProductionNarrationPlayerController(options);
}
