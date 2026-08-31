import {
  createNarrationWorkflow,
  getNarrationSettings,
  getNarrationWorkflow,
} from "./api";
import type {
  NarrationSettingsResource,
} from "./contracts";
import type {
  NarrationWorkflowIntent,
  NarrationWorkflowResource,
} from "./chapter-contracts";
import { createNarrationActionUuid } from "./idempotency-key";


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const DEFAULT_POLL_SCHEDULE_MS = Object.freeze([250, 500, 1_000, 2_000]);
const DEFAULT_POLL_TIMEOUT_MS = 30_000;


export interface StableChapterNarrationSource {
  readonly documentId: string;
  readonly draftVersion: number;
  readonly contentHash: string;
}


export interface ChapterNarrationWorkflowProgress {
  readonly step: "saving" | "settings" | "request" | "waiting" | "actionable";
  readonly message: string;
  readonly workflow: NarrationWorkflowResource | null;
}


export interface ChapterNarrationWorkflowResult {
  readonly source: StableChapterNarrationSource;
  readonly settings: NarrationSettingsResource;
  readonly workflow: NarrationWorkflowResource;
}


export type ChapterNarrationWorkflowErrorCode =
  | "INVALID_INPUT"
  | "SETTINGS_REQUIRED"
  | "STALE_GENERATION"
  | "WORKFLOW_TIMEOUT";


export class ChapterNarrationWorkflowError extends Error {
  readonly code: ChapterNarrationWorkflowErrorCode;

  constructor(code: ChapterNarrationWorkflowErrorCode, message: string) {
    super(message);
    this.name = "ChapterNarrationWorkflowError";
    this.code = code;
  }
}


export interface ChapterNarrationWorkflowDependencies {
  readonly getSettings: typeof getNarrationSettings;
  readonly createWorkflow: typeof createNarrationWorkflow;
  readonly getWorkflow: typeof getNarrationWorkflow;
  readonly createActionId: () => string;
  readonly delay: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  readonly now: () => number;
}


export interface StartChapterNarrationWorkflowOptions {
  readonly novelId: string;
  readonly documentId: string;
  readonly generation: number;
  readonly intent: Exclude<NarrationWorkflowIntent, "analyze_only">;
  readonly forceReview: boolean;
  readonly saveStableSource: () => Promise<StableChapterNarrationSource>;
  readonly isGenerationCurrent: (documentId: string, generation: number) => boolean;
  readonly onProgress?: (progress: ChapterNarrationWorkflowProgress) => void;
  readonly signal?: AbortSignal;
  readonly pollScheduleMs?: readonly number[];
  readonly pollTimeoutMs?: number;
  readonly dependencies?: Partial<ChapterNarrationWorkflowDependencies>;
}


function abortError(message: string): DOMException {
  return new DOMException(message, "AbortError");
}


function defaultDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError("workflow wait aborted"));
  return new Promise<void>((resolve, reject) => {
    const handle = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      clearTimeout(handle);
      signal.removeEventListener("abort", onAbort);
      reject(abortError("workflow wait aborted"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}


function defaultActionId(): string {
  return createNarrationActionUuid();
}


const DEFAULT_DEPENDENCIES: ChapterNarrationWorkflowDependencies = Object.freeze({
  getSettings: getNarrationSettings,
  createWorkflow: createNarrationWorkflow,
  getWorkflow: getNarrationWorkflow,
  createActionId: defaultActionId,
  delay: defaultDelay,
  now: () => Date.now(),
});


function fail(code: ChapterNarrationWorkflowErrorCode, message: string): never {
  throw new ChapterNarrationWorkflowError(code, message);
}


function assertCurrent(options: StartChapterNarrationWorkflowOptions): void {
  if (options.signal?.aborted) throw abortError("workflow aborted");
  let current = false;
  try {
    current = options.isGenerationCurrent(options.documentId, options.generation);
  } catch {
    current = false;
  }
  if (!current) fail("STALE_GENERATION", "章节已经切换，旧章节朗读操作已取消。");
}


function validateOptions(options: StartChapterNarrationWorkflowOptions): void {
  if (!UUID_PATTERN.test(options.novelId)) fail("INVALID_INPUT", "novelId 无效。");
  if (!UUID_PATTERN.test(options.documentId)) fail("INVALID_INPUT", "documentId 无效。");
  if (!Number.isSafeInteger(options.generation) || options.generation < 0) {
    fail("INVALID_INPUT", "generation 无效。");
  }
  if (options.intent !== "create" && options.intent !== "update") {
    fail("INVALID_INPUT", "章节生产只允许 create 或 update intent。");
  }
  const schedule = options.pollScheduleMs ?? DEFAULT_POLL_SCHEDULE_MS;
  if (
    schedule.length === 0
    || schedule.some((value) => !Number.isSafeInteger(value) || value < 1)
  ) {
    fail("INVALID_INPUT", "pollScheduleMs 必须是正整数序列。");
  }
  const timeout = options.pollTimeoutMs ?? DEFAULT_POLL_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeout) || timeout < 1) {
    fail("INVALID_INPUT", "pollTimeoutMs 必须是正整数。");
  }
}


function validateSource(
  source: StableChapterNarrationSource,
  options: StartChapterNarrationWorkflowOptions,
): void {
  if (source.documentId.toLowerCase() !== options.documentId.toLowerCase()) {
    fail("STALE_GENERATION", "保存屏障返回了其他章节。");
  }
  if (!Number.isSafeInteger(source.draftVersion) || source.draftVersion < 1) {
    fail("INVALID_INPUT", "保存屏障没有返回有效正文版本。");
  }
  if (!SHA256_PATTERN.test(source.contentHash)) {
    fail("INVALID_INPUT", "保存屏障没有返回有效正文哈希。");
  }
}


function actionable(workflow: NarrationWorkflowResource): boolean {
  const state = workflow.workflow_state;
  if (["review_required", "failed", "cancelled"].includes(state)) return true;
  if (["queued", "rendering", "partial_ready", "ready"].includes(state)) {
    if (workflow.edition_id === null || !UUID_PATTERN.test(workflow.edition_id)) {
      fail("INVALID_INPUT", "生产状态已进入队列但没有真实 Edition。");
    }
    const manifestRevision = workflow.current_manifest_revision;
    if (manifestRevision === null) {
      if (state === "partial_ready" || state === "ready") {
        fail("INVALID_INPUT", "可播放生产状态缺少 Manifest revision。");
      }
      return false;
    }
    if (!Number.isSafeInteger(manifestRevision) || manifestRevision < 1) {
      fail("INVALID_INPUT", "生产状态返回了无效的 Manifest revision。");
    }
    return state === "partial_ready" || state === "ready";
  }
  if (workflow.edition_id !== null || workflow.current_manifest_revision !== null) {
    fail("INVALID_INPUT", "生产等待态不得提前暴露 Edition 或 Manifest。");
  }
  return false;
}


function progressMessage(workflow: NarrationWorkflowResource): string {
  switch (workflow.workflow_state) {
    case "created": return "朗读请求已建立。";
    case "analyzing": return "正在识别说话人与匹配音色。";
    case "analyzed": return "人物识别完成，正在冻结朗读脚本。";
    case "review_required": return `脚本需要复核：${workflow.blocker_count} 个阻塞，${workflow.warning_count} 个提醒。`;
    case "queued": return "朗读版本已建立，句段正在排队合成。";
    case "rendering": return "正在合成独立句段音频。";
    case "partial_ready": return "首批句段已经可以播放。";
    case "ready": return "本章朗读已经准备完成。";
    case "cancel_requested": return "正在取消朗读制作。";
    case "cancelled": return "朗读制作已取消。";
    case "failed": return "朗读制作失败，正文与历史朗读版本均未被覆盖。";
  }
}


function publish(
  options: StartChapterNarrationWorkflowOptions,
  step: ChapterNarrationWorkflowProgress["step"],
  message: string,
  workflow: NarrationWorkflowResource | null,
): void {
  options.onProgress?.(Object.freeze({ step, message, workflow }));
}


export async function startChapterNarrationWorkflow(
  options: StartChapterNarrationWorkflowOptions,
): Promise<ChapterNarrationWorkflowResult> {
  validateOptions(options);
  assertCurrent(options);
  const dependencies: ChapterNarrationWorkflowDependencies = {
    ...DEFAULT_DEPENDENCIES,
    ...options.dependencies,
  };
  const controller = new AbortController();
  const abortFromParent = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", abortFromParent, { once: true });
  try {
    publish(options, "saving", "正在完成正文保存屏障。", null);
    const source = await options.saveStableSource();
    assertCurrent(options);
    validateSource(source, options);

    publish(options, "settings", "正在核对本书旁白、人物音色与朗读规则。", null);
    const settings = await dependencies.getSettings(options.novelId, controller.signal);
    assertCurrent(options);
    if (settings.novel_id !== options.novelId.toLowerCase()) {
      fail("INVALID_INPUT", "朗读设置返回了其他作品。");
    }
    if (!settings.exists || settings.version < 1) {
      fail(
        "SETTINGS_REQUIRED",
        "请先在书本管理的“朗读”中保存旁白、人物音色和朗读规则。",
      );
    }

    const actionId = dependencies.createActionId();
    if (!UUID_PATTERN.test(actionId)) {
      fail("INVALID_INPUT", "朗读操作标识必须是 UUID。");
    }
    const idempotencyKey = `chapter-tts:${actionId.toLowerCase()}`;
    publish(options, "request", "正在建立不可变正文快照与朗读脚本。", null);
    let workflow = await dependencies.createWorkflow(
      options.documentId,
      {
        intent: options.intent,
        expected_draft_version: source.draftVersion,
        expected_content_hash: source.contentHash,
        expected_settings_version: settings.version,
        force_review: options.forceReview,
      },
      idempotencyKey,
      controller.signal,
    );
    assertCurrent(options);
    publish(
      options,
      actionable(workflow) ? "actionable" : "waiting",
      progressMessage(workflow),
      workflow,
    );

    const schedule = options.pollScheduleMs ?? DEFAULT_POLL_SCHEDULE_MS;
    const timeout = options.pollTimeoutMs ?? DEFAULT_POLL_TIMEOUT_MS;
    const startedAt = dependencies.now();
    let attempt = 0;
    while (!actionable(workflow)) {
      if (dependencies.now() - startedAt >= timeout) {
        fail(
          "WORKFLOW_TIMEOUT",
          "首个可播放句段尚未准备完成，可稍后重试；已保存正文不会丢失。",
        );
      }
      await dependencies.delay(
        schedule[Math.min(attempt, schedule.length - 1)],
        controller.signal,
      );
      attempt += 1;
      assertCurrent(options);
      workflow = await dependencies.getWorkflow(workflow.request_id, controller.signal);
      assertCurrent(options);
      publish(
        options,
        actionable(workflow) ? "actionable" : "waiting",
        progressMessage(workflow),
        workflow,
      );
    }
    return Object.freeze({ source, settings, workflow });
  } finally {
    options.signal?.removeEventListener("abort", abortFromParent);
    controller.abort("workflow finished");
  }
}
