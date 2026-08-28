import type {
  NarrationWorkflowResource,
  NarrationWorkflowState,
} from "./chapter-contracts";
import type { ScriptReviewResource } from "./script-contracts";


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const DEFAULT_POLL_SCHEDULE_MS = Object.freeze([250, 500, 1_000, 2_000]);
const DEFAULT_POLL_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_POLL_ATTEMPTS = 30;

const WAITING_STATES = new Set<NarrationWorkflowState>([
  "created",
  "analyzing",
  "analyzed",
]);
const EDITION_STATES = new Set<NarrationWorkflowState>([
  "queued",
  "rendering",
  "partial_ready",
  "ready",
]);
const PLAYABLE_STATES = new Set<NarrationWorkflowState>([
  "partial_ready",
  "ready",
]);
const CANCELLED_STATES = new Set<NarrationWorkflowState>([
  "cancel_requested",
  "cancelled",
]);


export type ApprovedScriptProductionContinueErrorCode =
  | "INVALID_INPUT"
  | "INVALID_APPROVAL"
  | "SCOPE_MISMATCH"
  | "REVIEW_REQUIRED"
  | "WORKFLOW_FAILED"
  | "WORKFLOW_CANCELLED"
  | "WORKFLOW_TIMEOUT";


export class ApprovedScriptProductionContinueError extends Error {
  readonly code: ApprovedScriptProductionContinueErrorCode;
  readonly workflow: NarrationWorkflowResource | null;

  constructor(
    code: ApprovedScriptProductionContinueErrorCode,
    message: string,
    workflow: NarrationWorkflowResource | null = null,
  ) {
    super(message);
    this.name = "ApprovedScriptProductionContinueError";
    this.code = code;
    this.workflow = workflow;
  }
}


export type GetNarrationWorkflowForContinue = (
  requestId: string,
  signal?: AbortSignal,
) => Promise<NarrationWorkflowResource>;


export interface ApprovedScriptProductionContinueDependencies {
  readonly getWorkflow: GetNarrationWorkflowForContinue;
  readonly delay?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  readonly now?: () => number;
}


export interface ContinueApprovedScriptProductionOptions {
  readonly requestId: string;
  readonly approvedReview: ScriptReviewResource;
  readonly dependencies: ApprovedScriptProductionContinueDependencies;
  readonly signal?: AbortSignal;
  readonly pollScheduleMs?: readonly number[];
  readonly pollTimeoutMs?: number;
  readonly maxPollAttempts?: number;
  readonly onWorkflow?: (
    workflow: NarrationWorkflowResource,
    attempt: number,
  ) => void;
}


export interface ApprovedScriptProductionContinueResult {
  readonly requestId: string;
  readonly scriptVersionId: string;
  readonly editionId: string;
  readonly workflow: NarrationWorkflowResource;
  readonly attempts: number;
}


interface ValidatedContinueOptions {
  readonly requestId: string;
  readonly scriptVersionId: string;
  readonly sourceRevisionId: string;
  readonly sourceContentHash: string;
  readonly schedule: readonly number[];
  readonly timeoutMs: number;
  readonly maxAttempts: number;
}


function abortError(message: string): DOMException {
  return new DOMException(message, "AbortError");
}


function isAbortError(reason: unknown): boolean {
  return reason instanceof Error && reason.name === "AbortError";
}


function fail(
  code: ApprovedScriptProductionContinueErrorCode,
  message: string,
  workflow: NarrationWorkflowResource | null = null,
): never {
  throw new ApprovedScriptProductionContinueError(code, message, workflow);
}


function normalizeUuid(value: string, field: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    fail("INVALID_INPUT", `${field} 必须是 RFC-4122 UUID。`);
  }
  return value.toLowerCase();
}


function validateOptions(
  options: ContinueApprovedScriptProductionOptions,
): ValidatedContinueOptions {
  const requestId = normalizeUuid(options.requestId, "requestId");
  const review = options.approvedReview;
  const scriptVersionId = normalizeUuid(review.script_version_id, "script_version_id");
  const sourceRevisionId = normalizeUuid(review.revision_id, "revision_id");
  if (
    review.state !== "approved"
    || review.blocker_count !== 0
    || review.approval === null
    || review.approval.kind !== "manual_after_review"
    || review.approval.actor_type !== "owner"
    || review.approval.request_id.toLowerCase() !== requestId
  ) {
    fail(
      "INVALID_APPROVAL",
      "继续生产必须来自同一请求真实提交的人工批准脚本。",
    );
  }
  const schedule = options.pollScheduleMs ?? DEFAULT_POLL_SCHEDULE_MS;
  if (
    schedule.length === 0
    || schedule.some((value) => !Number.isSafeInteger(value) || value < 1)
  ) {
    fail("INVALID_INPUT", "pollScheduleMs 必须是正整数序列。");
  }
  const timeoutMs = options.pollTimeoutMs ?? DEFAULT_POLL_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    fail("INVALID_INPUT", "pollTimeoutMs 必须是正整数。");
  }
  const maxAttempts = options.maxPollAttempts ?? DEFAULT_MAX_POLL_ATTEMPTS;
  if (!Number.isSafeInteger(maxAttempts) || maxAttempts < 1) {
    fail("INVALID_INPUT", "maxPollAttempts 必须是正整数。");
  }
  if (typeof options.dependencies.getWorkflow !== "function") {
    fail("INVALID_INPUT", "必须显式注入 getNarrationWorkflow。");
  }
  return Object.freeze({
    requestId,
    scriptVersionId,
    sourceRevisionId,
    sourceContentHash: review.source_content_hash,
    schedule: Object.freeze([...schedule]),
    timeoutMs,
    maxAttempts,
  });
}


function defaultDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError("继续生产轮询已取消。"));
  return new Promise<void>((resolve, reject) => {
    const handle = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      clearTimeout(handle);
      signal.removeEventListener("abort", onAbort);
      reject(abortError("继续生产轮询已取消。"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}


function awaitWithAbort<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError("继续生产轮询已取消。"));
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(abortError("继续生产轮询已取消。"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    void operation.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (reason) => {
        signal.removeEventListener("abort", onAbort);
        reject(reason);
      },
    );
  });
}


function assertWorkflowScope(
  workflow: NarrationWorkflowResource,
  validated: ValidatedContinueOptions,
  previousRequestVersion: number,
): void {
  if (workflow.request_id !== validated.requestId) {
    fail("SCOPE_MISMATCH", "生产状态返回了其他 request_id。", workflow);
  }
  if (workflow.script_version_id !== validated.scriptVersionId) {
    fail("SCOPE_MISMATCH", "生产状态未绑定本次批准的 ScriptVersion。", workflow);
  }
  if (
    workflow.source_revision_id !== validated.sourceRevisionId
    || workflow.source_content_hash !== validated.sourceContentHash
  ) {
    fail("SCOPE_MISMATCH", "生产状态的不可变正文来源与批准脚本不一致。", workflow);
  }
  if (workflow.intent === "analyze_only") {
    fail("SCOPE_MISMATCH", "analyze_only 请求不得继续创建 Edition。", workflow);
  }
  if (workflow.request_version < previousRequestVersion) {
    fail("SCOPE_MISMATCH", "生产 request_version 发生倒退。", workflow);
  }
}


function classifyWorkflow(
  workflow: NarrationWorkflowResource,
): "waiting" | "success" {
  const state = workflow.workflow_state;
  if (state === "review_required") {
    fail("REVIEW_REQUIRED", "生产请求仍处于人工复核状态，未建立 Edition。", workflow);
  }
  if (state === "failed") {
    fail("WORKFLOW_FAILED", "人工批准后的朗读生产失败。", workflow);
  }
  if (CANCELLED_STATES.has(state)) {
    fail("WORKFLOW_CANCELLED", "人工批准后的朗读生产已取消。", workflow);
  }
  if (EDITION_STATES.has(state)) {
    if (workflow.edition_id === null || !UUID_PATTERN.test(workflow.edition_id)) {
      fail("SCOPE_MISMATCH", "生产状态已进入队列但没有真实 Edition。", workflow);
    }
    const manifestRevision = workflow.current_manifest_revision;
    if (manifestRevision === null) {
      if (PLAYABLE_STATES.has(state)) {
        fail("SCOPE_MISMATCH", "可播放生产状态缺少 Manifest revision。", workflow);
      }
      return "waiting";
    }
    if (!Number.isSafeInteger(manifestRevision) || manifestRevision < 1) {
      fail("SCOPE_MISMATCH", "生产状态返回了无效的 Manifest revision。", workflow);
    }
    return "success";
  }
  if (WAITING_STATES.has(state)) {
    if (workflow.edition_id !== null) {
      fail("SCOPE_MISMATCH", "生产等待态不得提前暴露 Edition。", workflow);
    }
    return "waiting";
  }
  fail("SCOPE_MISMATCH", `不支持的生产状态：${String(state)}。`, workflow);
}


function publishWorkflow(
  options: ContinueApprovedScriptProductionOptions,
  workflow: NarrationWorkflowResource,
  attempt: number,
): void {
  try {
    options.onWorkflow?.(workflow, attempt);
  } catch {
    // 展示观察者不能改变 request/Edition 权威或中断生产轮询。
  }
}


/**
 * Continues only after the caller has received the real approved resource from
 * `approveNarrationScriptVersion`.  This function never manufactures an
 * Edition and never repeats the approval mutation.
 */
export async function continueApprovedScriptProduction(
  options: ContinueApprovedScriptProductionOptions,
): Promise<ApprovedScriptProductionContinueResult> {
  const validated = validateOptions(options);
  const delay = options.dependencies.delay ?? defaultDelay;
  const now = options.dependencies.now ?? (() => Date.now());
  const controller = new AbortController();
  let timedOut = false;
  const abortFromParent = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) controller.abort(options.signal.reason);
  else options.signal?.addEventListener("abort", abortFromParent, { once: true });
  const timeoutHandle = setTimeout(() => {
    timedOut = true;
    controller.abort("continue_timeout");
  }, validated.timeoutMs);
  const startedAt = now();
  let previousRequestVersion = 0;
  try {
    for (let attempt = 1; attempt <= validated.maxAttempts; attempt += 1) {
      if (controller.signal.aborted) throw abortError("继续生产轮询已取消。");
      if (now() - startedAt >= validated.timeoutMs) {
        fail("WORKFLOW_TIMEOUT", "等待真实 Edition 超时，请刷新后查看生产状态。");
      }
      const workflow = await awaitWithAbort(
        options.dependencies.getWorkflow(validated.requestId, controller.signal),
        controller.signal,
      );
      assertWorkflowScope(workflow, validated, previousRequestVersion);
      previousRequestVersion = workflow.request_version;
      publishWorkflow(options, workflow, attempt);
      if (classifyWorkflow(workflow) === "success") {
        const editionId = workflow.edition_id;
        if (editionId === null) {
          fail("SCOPE_MISMATCH", "生产成功态缺少真实 Edition。", workflow);
        }
        return Object.freeze({
          requestId: validated.requestId,
          scriptVersionId: validated.scriptVersionId,
          editionId,
          workflow,
          attempts: attempt,
        });
      }
      if (attempt === validated.maxAttempts) {
        fail("WORKFLOW_TIMEOUT", "等待真实 Edition 超过最大轮询次数。", workflow);
      }
      await awaitWithAbort(
        delay(
          validated.schedule[Math.min(attempt - 1, validated.schedule.length - 1)],
          controller.signal,
        ),
        controller.signal,
      );
    }
    fail("WORKFLOW_TIMEOUT", "等待真实 Edition 超时。");
  } catch (reason) {
    if (isAbortError(reason) && timedOut) {
      fail("WORKFLOW_TIMEOUT", "等待真实 Edition 超时，请刷新后查看生产状态。");
    }
    throw reason;
  } finally {
    clearTimeout(timeoutHandle);
    options.signal?.removeEventListener("abort", abortFromParent);
    controller.abort("continue_finished");
  }
  return fail("WORKFLOW_TIMEOUT", "等待真实 Edition 超时。");
}
