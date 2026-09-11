import type {
  FailedNarrationSegmentRetryItem,
  FailedNarrationSegmentsProjection,
  RetryFailedNarrationSegmentsResponse,
} from "./chapter-contracts";


export const FAILED_SEGMENT_RETRY_BATCH_LIMIT = 100;


export type FailedSegmentFailureGroup = "recoverable" | "audio-quality" | "blocked";


export interface FailedSegmentRetrySummary {
  readonly recoverableCount: number;
  readonly audioQualityCount: number;
  readonly blockedCount: number;
  readonly retryableGroupCount: number;
  readonly retryableSegmentCount: number;
}


const AUDIO_QUALITY_FAILURE_CODES = new Set([
  "AUDIO_PUBLICATION_INVALID",
  "AUDIO_VALIDATION_UNKNOWN",
  "POSTPROCESS_DURATION_CHANGED",
  "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
  "TTS_AUDIO_INVALID",
  "WAV_CLIPPING_LIMIT_EXCEEDED",
  "WAV_DURATION_DRIFT",
  "WAV_DURATION_OUT_OF_BOUNDS",
]);


export function failedSegmentFailureGroup(
  item: FailedNarrationSegmentRetryItem,
): FailedSegmentFailureGroup {
  if (AUDIO_QUALITY_FAILURE_CODES.has(item.failure_code)) return "audio-quality";
  return item.retryable ? "recoverable" : "blocked";
}


function fanoutSignature(item: FailedNarrationSegmentRetryItem): string {
  return [...item.fanout_segment_ids].sort().join(",");
}


export function retryableFailedSegmentRepresentatives(
  items: readonly FailedNarrationSegmentRetryItem[],
): readonly FailedNarrationSegmentRetryItem[] {
  const seenJobIds = new Set<string>();
  const seenFanouts = new Set<string>();
  const representatives: FailedNarrationSegmentRetryItem[] = [];
  [...items].sort((left, right) => left.ordinal - right.ordinal).forEach((item) => {
    if (!item.retryable) return;
    const fanout = fanoutSignature(item);
    if (seenJobIds.has(item.job_id) || seenFanouts.has(fanout)) return;
    seenJobIds.add(item.job_id);
    seenFanouts.add(fanout);
    representatives.push(item);
  });
  return Object.freeze(representatives);
}


export function summarizeFailedSegments(
  items: readonly FailedNarrationSegmentRetryItem[],
): FailedSegmentRetrySummary {
  const counts = { recoverable: 0, "audio-quality": 0, blocked: 0 };
  items.forEach((item) => { counts[failedSegmentFailureGroup(item)] += 1; });
  const representatives = retryableFailedSegmentRepresentatives(items);
  return Object.freeze({
    recoverableCount: counts.recoverable,
    audioQualityCount: counts["audio-quality"],
    blockedCount: counts.blocked,
    retryableGroupCount: representatives.length,
    retryableSegmentCount: new Set(representatives.flatMap((item) => item.fanout_segment_ids)).size,
  });
}


export interface FailedSegmentRetryScope {
  readonly editionId: string;
  readonly requestId: string;
  readonly documentGeneration: number;
  readonly manifestRevision: number | null;
}


export type FailedSegmentRetryPhase =
  | "idle"
  | "loading"
  | "ready"
  | "submitting"
  | "error"
  | "disposed";


export interface FailedSegmentRetrySnapshot {
  readonly phase: FailedSegmentRetryPhase;
  readonly scope: FailedSegmentRetryScope | null;
  readonly projection: FailedNarrationSegmentsProjection | null;
  readonly busySegmentIds: readonly string[];
  readonly statusMessage: string | null;
  readonly errorMessage: string | null;
}


export interface FailedSegmentRetryControllerDependencies {
  readonly getProjection: (
    editionId: string,
    signal?: AbortSignal,
  ) => Promise<FailedNarrationSegmentsProjection>;
  readonly retry: (
    editionId: string,
    request: Readonly<{
      segment_ids: readonly string[];
      expected_request_version: number;
      expected_manifest_revision: number | null;
    }>,
    idempotencyKey: string,
    signal?: AbortSignal,
  ) => Promise<RetryFailedNarrationSegmentsResponse>;
  readonly afterAccepted: (
    response: RetryFailedNarrationSegmentsResponse,
    scope: FailedSegmentRetryScope,
    signal: AbortSignal,
  ) => Promise<void>;
  readonly createIdempotencyKey: () => string;
  readonly formatFailure: (reason: unknown) => string;
  readonly onState?: (snapshot: FailedSegmentRetrySnapshot) => void;
}


export interface FailedSegmentRetryController {
  load(scope: FailedSegmentRetryScope): Promise<void>;
  retrySegment(segmentId: string): Promise<void>;
  retryAll(): Promise<void>;
  reset(reason?: string): void;
  readSnapshot(): FailedSegmentRetrySnapshot;
  dispose(): void;
}


function frozenSnapshot(
  value: FailedSegmentRetrySnapshot,
): FailedSegmentRetrySnapshot {
  return Object.freeze({
    ...value,
    busySegmentIds: Object.freeze([...value.busySegmentIds]),
  });
}


function isAbort(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


function isProjectionCasConflict(reason: unknown): boolean {
  if (reason === null || typeof reason !== "object" || !("detail" in reason)) return false;
  const detail = (reason as { readonly detail?: unknown }).detail;
  if (detail === null || typeof detail !== "object" || !("code" in detail)) return false;
  const code = (detail as { readonly code?: unknown }).code;
  return code === "VERSION_CONFLICT" || code === "STALE_INPUT";
}


function projectionMatchesScope(
  projection: FailedNarrationSegmentsProjection,
  scope: FailedSegmentRetryScope,
): boolean {
  return projection.edition_id === scope.editionId
    && projection.request_id === scope.requestId;
}


export function failedSegmentRetryReasonMessage(reasonCode: string | null): string {
  switch (reasonCode) {
    case "FANOUT_NOT_ALL_FAILED":
      return "同一音频组仍有未失败句段，为避免覆盖正在使用的音频，暂不能重试。";
    case "JOB_NOT_MANUALLY_RETRYABLE":
      return "后台任务尚未进入可手动重试状态，请等待当前任务结束。";
    case "LATEST_ATTEMPT_NOT_COMPLETE":
      return "最近一次合成仍在收尾，请稍后再试。";
    case "LATEST_MANUAL_ATTEMPT_NON_RETRYABLE":
      return "本句已按相同音色和参数重试，仍未通过音频校验；请更换声音或调整正文后更新朗读。";
    case "VOICE_RIGHTS_UNAVAILABLE":
      return "当前绑定音色暂不可用于合成，请先检查音色版本。";
    case "AGGREGATE_FULL_FAILURE_STATE_INVALID":
    case "AGGREGATE_PARTIAL_FAILURE_STATE_INVALID":
      return "章节合成状态仍在同步，暂不能安全重试。";
    default:
      return "当前句段暂不满足安全重试条件。";
  }
}


export class ProductionFailedSegmentRetryController
implements FailedSegmentRetryController {
  private sequence = 0;
  private activeAbort: AbortController | null = null;
  private disposed = false;
  private snapshot = frozenSnapshot({
    phase: "idle",
    scope: null,
    projection: null,
    busySegmentIds: [],
    statusMessage: null,
    errorMessage: null,
  } as FailedSegmentRetrySnapshot);

  constructor(private readonly dependencies: FailedSegmentRetryControllerDependencies) {}

  readSnapshot(): FailedSegmentRetrySnapshot {
    return this.snapshot;
  }

  async load(scope: FailedSegmentRetryScope): Promise<void> {
    this.assertActive();
    const sequence = this.beginOperation("failed-segment projection superseded");
    const controller = this.requireActiveAbort();
    this.publish({
      phase: "loading",
      scope: Object.freeze({ ...scope }),
      projection: null,
      busySegmentIds: [],
      statusMessage: "正在读取失败句段…",
      errorMessage: null,
    });
    try {
      const projection = await this.dependencies.getProjection(
        scope.editionId,
        controller.signal,
      );
      if (!this.isCurrent(sequence, controller)) return;
      if (!projectionMatchesScope(projection, scope)) {
        throw new Error("失败句段投影与当前章节朗读版本不一致。");
      }
      this.activeAbort = null;
      this.publish({
        phase: "ready",
        scope: Object.freeze({ ...scope }),
        projection,
        busySegmentIds: [],
        statusMessage: projection.items.length > 0
          ? `发现 ${projection.items.length} 个失败句段。`
          : null,
        errorMessage: null,
      });
    } catch (reason) {
      if (!this.isCurrent(sequence, controller) || isAbort(reason)) return;
      this.activeAbort = null;
      this.publish({
        phase: "error",
        scope: Object.freeze({ ...scope }),
        projection: null,
        busySegmentIds: [],
        statusMessage: null,
        errorMessage: this.dependencies.formatFailure(reason),
      });
    }
  }

  async retrySegment(segmentId: string): Promise<void> {
    this.assertActive();
    const current = this.snapshot;
    const scope = current.scope;
    let projection = current.projection;
    if (current.phase !== "ready" || !scope || !projection) return;
    let item = projection.items.find((candidate) => candidate.segment_id === segmentId);
    if (!item || !item.retryable) return;

    const sequence = this.beginOperation("failed-segment retry superseded");
    const controller = this.requireActiveAbort();
    this.publish({
      ...current,
      phase: "submitting",
      busySegmentIds: item.fanout_segment_ids,
      statusMessage: item.fanout_segment_ids.length > 1
        ? `正在同步重试 ${item.fanout_segment_ids.length} 句…`
        : "正在重试本句…",
      errorMessage: null,
    });
    try {
      let response: RetryFailedNarrationSegmentsResponse | null = null;
      for (let casAttempt = 0; response === null; casAttempt += 1) {
        try {
          response = await this.dependencies.retry(
            scope.editionId,
            {
              segment_ids: [item.segment_id],
              expected_request_version: projection.request_version,
              expected_manifest_revision: projection.manifest_revision,
            },
            this.dependencies.createIdempotencyKey(),
            controller.signal,
          );
        } catch (reason) {
          if (!isProjectionCasConflict(reason) || casAttempt >= 2) throw reason;
          const fresh = await this.dependencies.getProjection(scope.editionId, controller.signal);
          if (!projectionMatchesScope(fresh, scope)) {
            throw new Error("并发刷新后的失败句段投影与当前章节朗读版本不一致。");
          }
          projection = fresh;
          const freshItem = projection.items.find(
            (candidate) => candidate.segment_id === segmentId,
          );
          if (!freshItem) {
            this.activeAbort = null;
            this.publish({
              phase: "ready",
              scope,
              projection,
              busySegmentIds: [],
              statusMessage: "失败句段已经由后台恢复，可继续播放。",
              errorMessage: null,
            });
            return;
          }
          if (!freshItem.retryable) {
            throw new Error(failedSegmentRetryReasonMessage(freshItem.retry_reason_code));
          }
          item = freshItem;
        }
      }
      if (!this.isCurrent(sequence, controller)) return;
      if (response.request_id !== projection.request_id) {
        throw new Error("失败句段重试响应与当前请求不一致。");
      }
      this.publish({
        ...this.snapshot,
        statusMessage: response.replayed
          ? "重试请求已受理，正在恢复句段音频（幂等重放）。"
          : "重试请求已受理，正在恢复句段音频。",
      });
      await this.dependencies.afterAccepted(response, scope, controller.signal);
      if (!this.isCurrent(sequence, controller)) return;
      const fresh = await this.dependencies.getProjection(scope.editionId, controller.signal);
      if (!this.isCurrent(sequence, controller)) return;
      if (!projectionMatchesScope(fresh, scope)) {
        throw new Error("重试后的失败句段投影与当前章节朗读版本不一致。");
      }
      this.activeAbort = null;
      this.publish({
        phase: "ready",
        scope,
        projection: fresh,
        busySegmentIds: [],
        statusMessage: fresh.items.length > 0
          ? `句段状态已更新，仍有 ${fresh.items.length} 个失败句段。`
          : "失败句段已经恢复，可继续播放。",
        errorMessage: null,
      });
    } catch (reason) {
      if (!this.isCurrent(sequence, controller) || isAbort(reason)) return;
      let fresh: FailedNarrationSegmentsProjection | null = null;
      try {
        const candidate = await this.dependencies.getProjection(
          scope.editionId,
          controller.signal,
        );
        if (projectionMatchesScope(candidate, scope)) fresh = candidate;
      } catch {
        fresh = null;
      }
      if (!this.isCurrent(sequence, controller)) return;
      this.activeAbort = null;
      this.publish({
        phase: fresh ? "ready" : "error",
        scope,
        projection: fresh,
        busySegmentIds: [],
        statusMessage: null,
        errorMessage: this.dependencies.formatFailure(reason),
      });
    }
  }

  async retryAll(): Promise<void> {
    this.assertActive();
    const current = this.snapshot;
    const scope = current.scope;
    let projection = current.projection;
    if (current.phase !== "ready" || !scope || !projection) return;
    const initial = retryableFailedSegmentRepresentatives(projection.items);
    if (initial.length === 0) return;

    const pendingJobs = new Set(initial.map((item) => item.job_id));
    const pendingFanouts = new Set(initial.map(fanoutSignature));
    const sequence = this.beginOperation("failed-segment bulk retry superseded");
    const controller = this.requireActiveAbort();
    let acceptedGroupCount = 0;
    let casRefreshAttempts = 0;
    try {
      while (pendingJobs.size > 0 || pendingFanouts.size > 0) {
        const remaining = retryableFailedSegmentRepresentatives(projection.items).filter(
          (item) => pendingJobs.has(item.job_id) || pendingFanouts.has(fanoutSignature(item)),
        );
        if (remaining.length === 0) break;
        const batch = remaining.slice(0, FAILED_SEGMENT_RETRY_BATCH_LIMIT);
        const busySegmentIds = [...new Set(batch.flatMap((item) => item.fanout_segment_ids))];
        this.publish({
          phase: "submitting",
          scope,
          projection,
          busySegmentIds,
          statusMessage: `正在恢复第 ${acceptedGroupCount + 1}–${acceptedGroupCount + batch.length} 组失败音频…`,
          errorMessage: null,
        });
        let response: RetryFailedNarrationSegmentsResponse;
        try {
          response = await this.dependencies.retry(
            scope.editionId,
            {
              segment_ids: batch.map((item) => item.segment_id),
              expected_request_version: projection.request_version,
              expected_manifest_revision: projection.manifest_revision,
            },
            this.dependencies.createIdempotencyKey(),
            controller.signal,
          );
        } catch (reason) {
          if (!isProjectionCasConflict(reason) || casRefreshAttempts >= 2) throw reason;
          const fresh = await this.dependencies.getProjection(scope.editionId, controller.signal);
          if (!projectionMatchesScope(fresh, scope)) {
            throw new Error("并发刷新后的失败句段投影与当前章节朗读版本不一致。");
          }
          projection = fresh;
          casRefreshAttempts += 1;
          continue;
        }
        casRefreshAttempts = 0;
        if (!this.isCurrent(sequence, controller)) return;
        if (response.request_id !== projection.request_id) {
          throw new Error("失败句段批量重试响应与当前请求不一致。");
        }
        const acceptedIds = new Set(response.accepted_segment_ids);
        if (
          acceptedIds.size !== batch.length
          || batch.some((item) => !acceptedIds.has(item.segment_id))
        ) {
          throw new Error("失败句段批量重试响应未完整接受当前批次。");
        }
        batch.forEach((item) => {
          pendingJobs.delete(item.job_id);
          pendingFanouts.delete(fanoutSignature(item));
        });
        acceptedGroupCount += batch.length;
        await this.dependencies.afterAccepted(response, scope, controller.signal);
        if (!this.isCurrent(sequence, controller)) return;
        const fresh = await this.dependencies.getProjection(scope.editionId, controller.signal);
        if (!this.isCurrent(sequence, controller)) return;
        if (!projectionMatchesScope(fresh, scope)) {
          throw new Error("批量重试后的失败句段投影与当前章节朗读版本不一致。");
        }
        projection = fresh;
      }
      this.activeAbort = null;
      this.publish({
        phase: "ready",
        scope,
        projection,
        busySegmentIds: [],
        statusMessage: projection.items.length > 0
          ? `批量恢复已完成，仍有 ${projection.items.length} 个失败句段需要处理。`
          : "全部可重试句段已经恢复，可继续播放。",
        errorMessage: null,
      });
    } catch (reason) {
      if (!this.isCurrent(sequence, controller) || isAbort(reason)) return;
      let fresh: FailedNarrationSegmentsProjection | null = null;
      try {
        const candidate = await this.dependencies.getProjection(scope.editionId, controller.signal);
        if (projectionMatchesScope(candidate, scope)) fresh = candidate;
      } catch {
        fresh = null;
      }
      if (!this.isCurrent(sequence, controller)) return;
      this.activeAbort = null;
      this.publish({
        phase: fresh ? "ready" : "error",
        scope,
        projection: fresh,
        busySegmentIds: [],
        statusMessage: null,
        errorMessage: this.dependencies.formatFailure(reason),
      });
    }
  }

  reset(reason = "failed-segment scope reset"): void {
    if (this.disposed) return;
    this.sequence += 1;
    this.activeAbort?.abort(reason);
    this.activeAbort = null;
    this.publish({
      phase: "idle",
      scope: null,
      projection: null,
      busySegmentIds: [],
      statusMessage: null,
      errorMessage: null,
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.sequence += 1;
    this.activeAbort?.abort("failed-segment controller disposed");
    this.activeAbort = null;
    this.publish({
      phase: "disposed",
      scope: null,
      projection: null,
      busySegmentIds: [],
      statusMessage: null,
      errorMessage: null,
    });
  }

  private beginOperation(reason: string): number {
    this.sequence += 1;
    this.activeAbort?.abort(reason);
    this.activeAbort = new AbortController();
    return this.sequence;
  }

  private requireActiveAbort(): AbortController {
    if (!this.activeAbort) throw new Error("failed-segment operation is unavailable");
    return this.activeAbort;
  }

  private isCurrent(sequence: number, controller: AbortController): boolean {
    return !this.disposed
      && sequence === this.sequence
      && this.activeAbort === controller
      && !controller.signal.aborted;
  }

  private publish(next: FailedSegmentRetrySnapshot): void {
    this.snapshot = frozenSnapshot(next);
    this.dependencies.onState?.(this.snapshot);
  }

  private assertActive(): void {
    if (this.disposed) throw new Error("failed-segment controller is disposed");
  }
}


export function createFailedSegmentRetryController(
  dependencies: FailedSegmentRetryControllerDependencies,
): FailedSegmentRetryController {
  return new ProductionFailedSegmentRetryController(dependencies);
}
