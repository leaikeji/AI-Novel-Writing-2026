import { describe, expect, it, vi } from "vitest";

import { FAILED_SEGMENT_RETRY_CONTRACT_VERSION } from "./chapter-contracts";
import {
  FAILED_SEGMENT_RETRY_BATCH_LIMIT,
  createFailedSegmentRetryController,
  failedSegmentRetryReasonMessage,
  retryableFailedSegmentRepresentatives,
  summarizeFailedSegments,
} from "./failed-segment-retry-state";


const EDITION_A = "10000000-0000-4000-8000-000000000001";
const EDITION_B = "10000000-0000-4000-8000-000000000002";
const REQUEST_A = "20000000-0000-4000-8000-000000000001";
const REQUEST_B = "20000000-0000-4000-8000-000000000002";
const SEGMENT_A = "30000000-0000-4000-8000-000000000001";
const SEGMENT_B = "30000000-0000-4000-8000-000000000002";
const JOB_ID = "40000000-0000-4000-8000-000000000001";
const COMMAND_ID = "50000000-0000-4000-8000-000000000001";


function projection(
  editionId = EDITION_A,
  requestId = REQUEST_A,
  changes: Record<string, unknown> = {},
) {
  return Object.freeze({
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: editionId,
    request_id: requestId,
    request_version: 4,
    manifest_revision: 7,
    request_state: "partial_ready" as const,
    edition_state: "partial_ready" as const,
    items: Object.freeze([Object.freeze({
      segment_id: SEGMENT_A,
      ordinal: 0,
      failure_code: "LEASE_EXPIRED",
      retryable: true,
      retry_reason_code: null,
      job_id: JOB_ID,
      fanout_segment_ids: Object.freeze([SEGMENT_A, SEGMENT_B]),
    })]),
    ...changes,
  });
}


function response(changes: Record<string, unknown> = {}) {
  return Object.freeze({
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: EDITION_A,
    request_id: REQUEST_A,
    accepted_segment_ids: Object.freeze([SEGMENT_A]),
    affected_segment_ids: Object.freeze([SEGMENT_A, SEGMENT_B]),
    commands: Object.freeze([Object.freeze({
      command_id: COMMAND_ID,
      job_id: JOB_ID,
      affected_segment_ids: Object.freeze([SEGMENT_A, SEGMENT_B]),
    })]),
    request_version: 5,
    request_state: "rendering" as const,
    edition_state: "rendering" as const,
    replayed: false,
    ...changes,
  });
}


function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}


function generatedUuid(prefix: "3" | "4" | "5", index: number): string {
  return `${prefix}0000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
}


function retryItems(count: number) {
  return Object.freeze(Array.from({ length: count }, (_, index) => {
    const segmentId = generatedUuid("3", index);
    return Object.freeze({
      segment_id: segmentId,
      ordinal: index,
      failure_code: index === 0 ? "SHORT_CHINESE_DURATION_IMPLAUSIBLE" : "LEASE_EXPIRED",
      retryable: true,
      retry_reason_code: null,
      job_id: generatedUuid("4", index),
      fanout_segment_ids: Object.freeze([segmentId]),
    });
  }));
}


describe("failed-segment retry state", () => {
  it("fences a stale Edition load and aborts its request", async () => {
    const first = deferred<ReturnType<typeof projection>>();
    const signals: AbortSignal[] = [];
    const getProjection = vi.fn((editionId: string, signal?: AbortSignal) => {
      if (signal) signals.push(signal);
      return editionId === EDITION_A
        ? first.promise
        : Promise.resolve(projection(EDITION_B, REQUEST_B));
    });
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry: vi.fn(),
      afterAccepted: vi.fn(),
      createIdempotencyKey: () => "retry-key-0001",
      formatFailure: () => "失败",
    });

    const stale = controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });
    const current = controller.load({
      editionId: EDITION_B,
      requestId: REQUEST_B,
      documentGeneration: 2,
      manifestRevision: 8,
    });
    first.resolve(projection());
    await Promise.all([stale, current]);

    expect(signals[0]?.aborted).toBe(true);
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      scope: { editionId: EDITION_B, documentGeneration: 2 },
      projection: { edition_id: EDITION_B, request_id: REQUEST_B },
    });
  });

  it("submits projection CAS, marks the whole fanout busy, and accepts replay", async () => {
    const retry = vi.fn().mockResolvedValue(response({ replayed: true }));
    const afterAccepted = vi.fn().mockResolvedValue(undefined);
    const states: unknown[] = [];
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection())
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, { items: Object.freeze([]) }));
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry,
      afterAccepted,
      createIdempotencyKey: () => "retry-root-0001",
      formatFailure: () => "失败",
      onState: (state) => states.push(state),
    });
    const scope = {
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 3,
      manifestRevision: 7,
    };
    await controller.load(scope);
    await controller.retrySegment(SEGMENT_A);

    expect(states).toContainEqual(expect.objectContaining({
      phase: "submitting",
      busySegmentIds: [SEGMENT_A, SEGMENT_B],
    }));
    expect(retry).toHaveBeenCalledWith(
      EDITION_A,
      {
        segment_ids: [SEGMENT_A],
        expected_request_version: 4,
        expected_manifest_revision: 7,
      },
      "retry-root-0001",
      expect.any(AbortSignal),
    );
    expect(afterAccepted).toHaveBeenCalledWith(
      expect.objectContaining({ replayed: true }),
      scope,
      expect.any(AbortSignal),
    );
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      projection: { items: [] },
      busySegmentIds: [],
      statusMessage: "失败句段已经恢复，可继续播放。",
    });
  });

  it("keeps refreshing after the completion waiter fails until the projection is terminal", async () => {
    const retry = vi.fn().mockResolvedValue(response());
    const afterAccepted = vi.fn().mockRejectedValue(new Error("render failed again"));
    const waitForProjectionRefresh = vi.fn().mockResolvedValue(undefined);
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection())
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 5,
        manifest_revision: 8,
        items: Object.freeze([]),
      }))
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 6,
        manifest_revision: 8,
        items: Object.freeze([Object.freeze({
          ...projection().items[0],
          failure_code: "TTS_AUDIO_INVALID",
          retryable: false,
          retry_reason_code: "LATEST_MANUAL_ATTEMPT_NON_RETRYABLE",
        })]),
      }));
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry,
      afterAccepted,
      createIdempotencyKey: () => "retry-root-0001",
      formatFailure: (reason) => reason instanceof Error ? reason.message : "失败",
      waitForProjectionRefresh,
    });
    await controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });

    await controller.retrySegment(SEGMENT_A);
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      projection: {
        request_version: 6,
        manifest_revision: 8,
        items: [{
          retryable: false,
          retry_reason_code: "LATEST_MANUAL_ATTEMPT_NON_RETRYABLE",
        }],
      },
      errorMessage: "render failed again",
    });
    expect(getProjection).toHaveBeenCalledTimes(3);
    expect(waitForProjectionRefresh).toHaveBeenCalledOnce();
    expect(retry).toHaveBeenCalledOnce();
  });

  it("does not trust an early completion callback while the worker projection is still transient", async () => {
    const waitForProjectionRefresh = vi.fn().mockResolvedValue(undefined);
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection())
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 5,
        items: Object.freeze([Object.freeze({
          ...projection().items[0],
          retryable: false,
          retry_reason_code: "LATEST_ATTEMPT_NOT_COMPLETE",
        })]),
      }))
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 6,
        items: Object.freeze([]),
      }));
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry: vi.fn().mockResolvedValue(response()),
      afterAccepted: vi.fn().mockResolvedValue(undefined),
      createIdempotencyKey: () => "retry-root-0001",
      formatFailure: (reason) => reason instanceof Error ? reason.message : "失败",
      waitForProjectionRefresh,
    });
    await controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });

    await controller.retrySegment(SEGMENT_A);

    expect(waitForProjectionRefresh).toHaveBeenCalledOnce();
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      projection: { request_version: 6, items: [] },
      statusMessage: "失败句段已经恢复，可继续播放。",
      errorMessage: null,
    });
  });

  it("keeps non-retryable explanations stable and never submits them", async () => {
    const retry = vi.fn();
    const controller = createFailedSegmentRetryController({
      getProjection: vi.fn().mockResolvedValue(projection(EDITION_A, REQUEST_A, {
        items: Object.freeze([Object.freeze({
          ...projection().items[0],
          retryable: false,
          retry_reason_code: "FANOUT_NOT_ALL_FAILED",
        })]),
      })),
      retry,
      afterAccepted: vi.fn(),
      createIdempotencyKey: () => "retry-root-0001",
      formatFailure: () => "失败",
    });
    await controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });
    await controller.retrySegment(SEGMENT_A);

    expect(retry).not.toHaveBeenCalled();
    expect(failedSegmentRetryReasonMessage("FANOUT_NOT_ALL_FAILED")).toContain(
      "暂不能重试",
    );
    expect(failedSegmentRetryReasonMessage("LATEST_MANUAL_ATTEMPT_NON_RETRYABLE")).toContain(
      "更换声音或调整正文",
    );
    expect(failedSegmentRetryReasonMessage("UNKNOWN_FUTURE_REASON")).toBe(
      "当前句段暂不满足安全重试条件。",
    );
  });

  it("groups quality failures and deduplicates retry representatives by job and fanout", () => {
    const first = projection().items[0];
    const duplicate = Object.freeze({
      ...first,
      segment_id: SEGMENT_B,
      ordinal: 1,
    });
    const quality = Object.freeze({
      ...first,
      segment_id: generatedUuid("3", 9),
      ordinal: 2,
      job_id: generatedUuid("4", 9),
      fanout_segment_ids: Object.freeze([generatedUuid("3", 9)]),
      failure_code: "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
    });
    const items = [first, duplicate, quality];

    expect(retryableFailedSegmentRepresentatives(items).map((item) => item.segment_id)).toEqual([
      SEGMENT_A,
      quality.segment_id,
    ]);
    expect(summarizeFailedSegments(items)).toEqual({
      recoverableCount: 2,
      audioQualityCount: 1,
      blockedCount: 0,
      retryableGroupCount: 2,
      retryableSegmentCount: 3,
    });
  });

  it("serializes bulk recovery into 100-item batches and refreshes CAS after every batch", async () => {
    const items = retryItems(FAILED_SEGMENT_RETRY_BATCH_LIMIT + 1);
    const remaining = Object.freeze([items[items.length - 1]!]);
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, { items }))
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 5,
        manifest_revision: 8,
        items: remaining,
      }))
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 6,
        manifest_revision: 9,
        items: Object.freeze([]),
      }));
    const retry = vi.fn((
      _editionId: string,
      request: { readonly segment_ids: readonly string[] },
    ) => Promise.resolve(Object.freeze({
      ...response(),
      accepted_segment_ids: request.segment_ids,
      affected_segment_ids: request.segment_ids,
      commands: request.segment_ids.map((segmentId, index) => Object.freeze({
        command_id: generatedUuid("5", index),
        job_id: generatedUuid("4", index),
        affected_segment_ids: Object.freeze([segmentId]),
      })),
    })));
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry,
      afterAccepted: vi.fn().mockResolvedValue(undefined),
      createIdempotencyKey: vi.fn()
        .mockReturnValueOnce("retry-batch-0001")
        .mockReturnValueOnce("retry-batch-0002"),
      formatFailure: (reason) => reason instanceof Error ? reason.message : "失败",
    });
    await controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });
    await controller.retryAll();

    expect(retry).toHaveBeenCalledTimes(2);
    expect(retry.mock.calls[0]?.[1].segment_ids).toHaveLength(100);
    expect(retry.mock.calls[0]?.[1]).toMatchObject({
      expected_request_version: 4,
      expected_manifest_revision: 7,
    });
    expect(retry.mock.calls[1]?.[1]).toMatchObject({
      segment_ids: [remaining[0].segment_id],
      expected_request_version: 5,
      expected_manifest_revision: 8,
    });
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      projection: { request_version: 6, items: [] },
      statusMessage: "全部可重试句段已经恢复，可继续播放。",
    });
  });

  it("stops bulk recovery on the first error instead of blindly continuing", async () => {
    const items = retryItems(FAILED_SEGMENT_RETRY_BATCH_LIMIT + 1);
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, { items }))
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, { items }));
    const retry = vi.fn().mockRejectedValue(new Error("provider unavailable"));
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry,
      afterAccepted: vi.fn(),
      createIdempotencyKey: () => "retry-batch-0001",
      formatFailure: (reason) => reason instanceof Error ? reason.message : "失败",
    });
    await controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });
    await controller.retryAll();

    expect(retry).toHaveBeenCalledTimes(1);
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      errorMessage: "provider unavailable",
      busySegmentIds: [],
    });
  });

  it("refreshes projection CAS and retries a bulk click during manifest publication", async () => {
    const conflict = Object.assign(new Error("version conflict"), {
      detail: { code: "VERSION_CONFLICT" },
    });
    const freshProjection = projection(EDITION_A, REQUEST_A, {
      request_version: 9,
      manifest_revision: 12,
    });
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection())
      .mockResolvedValueOnce(freshProjection)
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, { items: Object.freeze([]) }));
    const retry = vi.fn()
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce(response());
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry,
      afterAccepted: vi.fn().mockResolvedValue(undefined),
      createIdempotencyKey: vi.fn()
        .mockReturnValueOnce("retry-cas-0001")
        .mockReturnValueOnce("retry-cas-0002"),
      formatFailure: (reason) => reason instanceof Error ? reason.message : "失败",
    });
    await controller.load({
      editionId: EDITION_A,
      requestId: REQUEST_A,
      documentGeneration: 1,
      manifestRevision: 7,
    });
    await controller.retryAll();

    expect(retry).toHaveBeenCalledTimes(2);
    expect(retry.mock.calls[1]?.[1]).toMatchObject({
      expected_request_version: 9,
      expected_manifest_revision: 12,
    });
    expect(controller.readSnapshot()).toMatchObject({
      phase: "ready",
      projection: { items: [] },
      errorMessage: null,
    });
  });
});
