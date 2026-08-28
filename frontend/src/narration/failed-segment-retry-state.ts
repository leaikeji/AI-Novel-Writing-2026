import type {
  FailedNarrationSegmentsProjection,
  RetryFailedNarrationSegmentsResponse,
} from "./chapter-contracts";


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
    const projection = current.projection;
    if (current.phase !== "ready" || !scope || !projection) return;
    const item = projection.items.find((candidate) => candidate.segment_id === segmentId);
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
      const response = await this.dependencies.retry(
        scope.editionId,
        {
          segment_ids: [item.segment_id],
          expected_request_version: projection.request_version,
          expected_manifest_revision: projection.manifest_revision,
        },
        this.dependencies.createIdempotencyKey(),
        controller.signal,
      );
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
