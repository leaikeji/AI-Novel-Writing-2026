import { describe, expect, it, vi } from "vitest";

import type {
  NarrationWorkflowResource,
  NarrationWorkflowState,
} from "./chapter-contracts";
import {
  ApprovedScriptProductionContinueError,
  continueApprovedScriptProduction,
  type ApprovedScriptProductionContinueDependencies,
} from "./script-review-continue";
import type { ScriptReviewResource } from "./script-contracts";


const REQUEST_ID = "10000000-0000-4000-8000-000000000001";
const OTHER_REQUEST_ID = "10000000-0000-4000-8000-000000000002";
const SCRIPT_ID = "10000000-0000-4000-8000-000000000003";
const SCRIPT_VERSION_ID = "10000000-0000-4000-8000-000000000004";
const OTHER_SCRIPT_VERSION_ID = "10000000-0000-4000-8000-000000000005";
const NOVEL_ID = "10000000-0000-4000-8000-000000000006";
const DOCUMENT_ID = "10000000-0000-4000-8000-000000000007";
const REVISION_ID = "10000000-0000-4000-8000-000000000008";
const OTHER_REVISION_ID = "10000000-0000-4000-8000-000000000009";
const EDITION_ID = "10000000-0000-4000-8000-000000000010";
const SOURCE_HASH = "a".repeat(64);


function approvedReview(
  overrides: Partial<ScriptReviewResource> = {},
): ScriptReviewResource {
  return {
    contract_version: "narration-script-review-api/1",
    taxonomy_version: "narration-review-taxonomy/1",
    script_id: SCRIPT_ID,
    script_version_id: SCRIPT_VERSION_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    revision_id: REVISION_ID,
    source_content_hash: SOURCE_HASH,
    immutable_hash: "b".repeat(64),
    version_number: 3,
    state: "approved",
    effective_policy: "always_review",
    source_status: "current",
    warning_count: 0,
    blocker_count: 0,
    allowed_actions: [],
    segments: [],
    issues: [],
    approval: {
      kind: "manual_after_review",
      request_id: REQUEST_ID,
      actor_type: "owner",
      actor_id: "local-owner",
      approved_at: "2026-08-27T08:00:00Z",
    },
    ...overrides,
  };
}


function workflow(
  state: NarrationWorkflowState,
  editionId: string | null = null,
  overrides: Partial<NarrationWorkflowResource> = {},
): NarrationWorkflowResource {
  return {
    contract_version: "narration-production-api/1",
    request_id: REQUEST_ID,
    intent: "create",
    request_version: 4,
    workflow_state: state,
    source_revision_id: REVISION_ID,
    source_content_hash: SOURCE_HASH,
    settings_fingerprint: "c".repeat(64),
    warning_count: 0,
    blocker_count: state === "review_required" ? 1 : 0,
    script_version_id: SCRIPT_VERSION_ID,
    edition_id: editionId,
    current_manifest_revision: editionId === null ? null : 1,
    job_ids: [],
    replayed: false,
    ...overrides,
  };
}


function dependencies(
  getWorkflow: ApprovedScriptProductionContinueDependencies["getWorkflow"],
  overrides: Partial<ApprovedScriptProductionContinueDependencies> = {},
): ApprovedScriptProductionContinueDependencies {
  return {
    getWorkflow: vi.fn(getWorkflow),
    delay: vi.fn(async () => undefined),
    now: () => 0,
    ...overrides,
  };
}


function options(
  deps: ApprovedScriptProductionContinueDependencies,
  overrides: Partial<Parameters<typeof continueApprovedScriptProduction>[0]> = {},
) {
  return {
    requestId: REQUEST_ID,
    approvedReview: approvedReview(),
    dependencies: deps,
    pollScheduleMs: [1],
    pollTimeoutMs: 100,
    maxPollAttempts: 5,
    ...overrides,
  } satisfies Parameters<typeof continueApprovedScriptProduction>[0];
}


describe("continueApprovedScriptProduction", () => {
  it("polls the known request until its real Edition has a playable Manifest", async () => {
    const getWorkflow = vi.fn()
      .mockResolvedValueOnce(workflow("analyzed", null, { request_version: 4 }))
      .mockResolvedValueOnce(workflow("queued", EDITION_ID, {
        request_version: 5,
        current_manifest_revision: null,
      }))
      .mockResolvedValueOnce(workflow("rendering", EDITION_ID, {
        request_version: 6,
        current_manifest_revision: null,
      }))
      .mockResolvedValueOnce(workflow("partial_ready", EDITION_ID, {
        request_version: 7,
        current_manifest_revision: 1,
      }));
    const deps = dependencies(getWorkflow);
    const observed = vi.fn();

    await expect(continueApprovedScriptProduction({
      ...options(deps),
      onWorkflow: observed,
    })).resolves.toEqual({
      requestId: REQUEST_ID,
      scriptVersionId: SCRIPT_VERSION_ID,
      editionId: EDITION_ID,
      workflow: workflow("partial_ready", EDITION_ID, {
        request_version: 7,
        current_manifest_revision: 1,
      }),
      attempts: 4,
    });

    expect(deps.getWorkflow).toHaveBeenCalledTimes(4);
    expect(deps.getWorkflow).toHaveBeenNthCalledWith(
      1,
      REQUEST_ID,
      expect.any(AbortSignal),
    );
    expect(deps.delay).toHaveBeenCalledTimes(3);
    expect(observed).toHaveBeenCalledTimes(4);
  });

  it.each(["queued", "rendering", "partial_ready", "ready"] as const)(
    "accepts %s only with a non-empty Edition from the same request",
    async (state) => {
      const deps = dependencies(async () => workflow(state, EDITION_ID));

      await expect(continueApprovedScriptProduction(options(deps))).resolves.toMatchObject({
        editionId: EDITION_ID,
        attempts: 1,
        workflow: { workflow_state: state },
      });
      expect(deps.delay).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["request_id", { request_id: OTHER_REQUEST_ID }, "request_id"],
    ["script_version_id", { script_version_id: OTHER_SCRIPT_VERSION_ID }, "ScriptVersion"],
    ["source revision", { source_revision_id: OTHER_REVISION_ID }, "正文来源"],
    ["source hash", { source_content_hash: "d".repeat(64) }, "正文来源"],
  ] as const)("fails closed on %s drift", async (_label, drift, message) => {
    const deps = dependencies(async () => workflow("queued", EDITION_ID, drift));

    await expect(continueApprovedScriptProduction(options(deps))).rejects.toMatchObject({
      code: "SCOPE_MISMATCH",
      message: expect.stringContaining(message),
    } satisfies Partial<ApprovedScriptProductionContinueError>);
  });

  it("rejects queued without Edition instead of manufacturing success", async () => {
    const deps = dependencies(async () => workflow("queued"));

    await expect(continueApprovedScriptProduction(options(deps))).rejects.toMatchObject({
      code: "SCOPE_MISMATCH",
      workflow: { workflow_state: "queued", edition_id: null },
    });
  });

  it.each(["queued", "rendering"] as const)(
    "keeps polling while %s has an Edition but no Manifest",
    async (state) => {
      const getWorkflow = vi.fn()
        .mockResolvedValueOnce(workflow(state, EDITION_ID, {
          current_manifest_revision: null,
        }))
        .mockResolvedValueOnce(workflow("partial_ready", EDITION_ID));
      const deps = dependencies(getWorkflow);

      await expect(continueApprovedScriptProduction(options(deps))).resolves.toMatchObject({
        attempts: 2,
        workflow: { workflow_state: "partial_ready", current_manifest_revision: 1 },
      });
      expect(deps.delay).toHaveBeenCalledOnce();
    },
  );

  it.each(["partial_ready", "ready"] as const)(
    "fails closed when %s claims playability without a Manifest",
    async (state) => {
      const deps = dependencies(async () => workflow(state, EDITION_ID, {
        current_manifest_revision: null,
      }));

      await expect(continueApprovedScriptProduction(options(deps))).rejects.toMatchObject({
        code: "SCOPE_MISMATCH",
        workflow: { workflow_state: state, current_manifest_revision: null },
      });
      expect(deps.delay).not.toHaveBeenCalled();
    },
  );

  it("fails closed on a non-positive Manifest revision", async () => {
    const deps = dependencies(async () => workflow("rendering", EDITION_ID, {
      current_manifest_revision: 0,
    }));

    await expect(continueApprovedScriptProduction(options(deps))).rejects.toMatchObject({
      code: "SCOPE_MISMATCH",
    });
  });

  it("rejects an Edition leaked from a pre-production waiting state", async () => {
    const deps = dependencies(async () => workflow("analyzed", EDITION_ID));

    await expect(continueApprovedScriptProduction(options(deps))).rejects.toMatchObject({
      code: "SCOPE_MISMATCH",
    } satisfies Partial<ApprovedScriptProductionContinueError>);
  });

  it.each([
    ["review_required", "REVIEW_REQUIRED"],
    ["failed", "WORKFLOW_FAILED"],
    ["cancel_requested", "WORKFLOW_CANCELLED"],
    ["cancelled", "WORKFLOW_CANCELLED"],
  ] as const)("reports %s as a real terminal failure", async (state, code) => {
    const deps = dependencies(async () => workflow(state));

    await expect(continueApprovedScriptProduction(options(deps))).rejects.toMatchObject({
      code,
      workflow: { workflow_state: state },
    });
    expect(deps.delay).not.toHaveBeenCalled();
  });

  it.each([
    approvedReview({ state: "review_required", approval: null }),
    approvedReview({ blocker_count: 1 }),
    approvedReview({
      approval: {
        kind: "manual_after_review",
        request_id: REQUEST_ID,
        actor_type: "service",
        actor_id: "forged-service",
        approved_at: "2026-08-27T08:00:00Z",
      },
    }),
    approvedReview({
      approval: {
        kind: "manual_after_review",
        request_id: OTHER_REQUEST_ID,
        actor_type: "owner",
        actor_id: "local-owner",
        approved_at: "2026-08-27T08:00:00Z",
      },
    }),
  ])("never polls without an exact real approval audit", async (review) => {
    const deps = dependencies(async () => workflow("queued", EDITION_ID));

    await expect(continueApprovedScriptProduction(options(deps, {
      approvedReview: review,
    }))).rejects.toMatchObject({ code: "INVALID_APPROVAL" });
    expect(deps.getWorkflow).not.toHaveBeenCalled();
  });

  it("fails after a bounded number of waiting responses", async () => {
    const deps = dependencies(async () => workflow("analyzed"));

    await expect(continueApprovedScriptProduction({
      ...options(deps),
      maxPollAttempts: 2,
    })).rejects.toMatchObject({
      code: "WORKFLOW_TIMEOUT",
      workflow: { workflow_state: "analyzed" },
    });
    expect(deps.getWorkflow).toHaveBeenCalledTimes(2);
    expect(deps.delay).toHaveBeenCalledOnce();
  });

  it("hard-times out even if the injected workflow request ignores AbortSignal", async () => {
    let requestSignal: AbortSignal | undefined;
    const deps = dependencies(async (_requestId, signal) => {
      requestSignal = signal;
      return new Promise<NarrationWorkflowResource>(() => undefined);
    });

    await expect(continueApprovedScriptProduction({
      ...options(deps),
      pollTimeoutMs: 10,
    })).rejects.toMatchObject({ code: "WORKFLOW_TIMEOUT" });
    expect(requestSignal?.aborted).toBe(true);
  });

  it("propagates caller Abort as AbortError and performs no later poll", async () => {
    const controller = new AbortController();
    let notifyDelay!: () => void;
    const delayStarted = new Promise<void>((resolve) => { notifyDelay = resolve; });
    const delay = vi.fn(async (_milliseconds: number, signal: AbortSignal) => (
      new Promise<void>((_resolve, reject) => {
        notifyDelay();
        signal.addEventListener("abort", () => {
          reject(new DOMException("caller aborted", "AbortError"));
        }, { once: true });
      })
    ));
    const deps = dependencies(async () => workflow("analyzed"), { delay });
    const operation = continueApprovedScriptProduction({
      ...options(deps),
      signal: controller.signal,
    });
    await delayStarted;

    controller.abort("closed review");

    await expect(operation).rejects.toMatchObject({ name: "AbortError" });
    expect(deps.getWorkflow).toHaveBeenCalledOnce();
  });

  it("rejects request_version regression and ignores observer failures", async () => {
    const getWorkflow = vi.fn()
      .mockResolvedValueOnce(workflow("analyzed", null, { request_version: 5 }))
      .mockResolvedValueOnce(workflow("analyzed", null, { request_version: 4 }));
    const deps = dependencies(getWorkflow);

    await expect(continueApprovedScriptProduction({
      ...options(deps),
      onWorkflow: () => { throw new Error("presentation failed"); },
    })).rejects.toMatchObject({ code: "SCOPE_MISMATCH" });
    expect(deps.getWorkflow).toHaveBeenCalledTimes(2);
  });
});
