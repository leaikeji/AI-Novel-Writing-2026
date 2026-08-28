import { describe, expect, it, vi } from "vitest";

import { FAILED_SEGMENT_RETRY_CONTRACT_VERSION } from "./chapter-contracts";
import {
  createFailedSegmentRetryController,
  failedSegmentRetryReasonMessage,
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

  it("refreshes CAS after failure and creates a new root key for the next click", async () => {
    const keys = ["retry-root-0001", "retry-root-0002"];
    const retry = vi.fn().mockResolvedValue(response());
    const afterAccepted = vi.fn()
      .mockRejectedValueOnce(new Error("render failed again"))
      .mockResolvedValueOnce(undefined);
    const getProjection = vi.fn()
      .mockResolvedValueOnce(projection())
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, {
        request_version: 5,
        manifest_revision: 8,
      }))
      .mockResolvedValueOnce(projection(EDITION_A, REQUEST_A, { items: Object.freeze([]) }));
    const controller = createFailedSegmentRetryController({
      getProjection,
      retry,
      afterAccepted,
      createIdempotencyKey: () => keys.shift() ?? "unexpected-key",
      formatFailure: (reason) => reason instanceof Error ? reason.message : "失败",
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
      projection: { request_version: 5, manifest_revision: 8 },
      errorMessage: "render failed again",
    });
    await controller.retrySegment(SEGMENT_A);

    expect(retry.mock.calls.map((call) => call[2])).toEqual([
      "retry-root-0001",
      "retry-root-0002",
    ]);
    expect(retry.mock.calls[1]?.[1]).toMatchObject({
      expected_request_version: 5,
      expected_manifest_revision: 8,
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
    expect(failedSegmentRetryReasonMessage("UNKNOWN_FUTURE_REASON")).toBe(
      "当前句段暂不满足安全重试条件。",
    );
  });
});
