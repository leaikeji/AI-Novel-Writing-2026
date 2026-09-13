import {
  getDocumentNarrationContext, getNarrationEdition, getNarrationWorkflow,
  getFailedNarrationSegments, retryFailedNarrationSegments,
} from "./api";
import type { NarrationWorkflowResource } from "./chapter-contracts";

const DEFAULT_DEPENDENCIES = {
  getContext: getDocumentNarrationContext,
  getEdition: getNarrationEdition,
  getWorkflow: getNarrationWorkflow,
  getFailed: getFailedNarrationSegments,
  retry: retryFailedNarrationSegments,
  delay: (signal: AbortSignal): Promise<void> => new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException("朗读恢复已取消。", "AbortError")); return; }
    const abort = () => { clearTimeout(timer); reject(new DOMException("朗读恢复已取消。", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 250);
    signal.addEventListener("abort", abort, { once: true });
  }),
};

export interface RecoverExistingNarrationOptions {
  readonly novelId: string;
  readonly documentId: string;
  /** Fresh server-frozen source/settings, after the normal save barrier. */
  readonly workflow: NarrationWorkflowResource;
  readonly idempotencyKey: string;
  readonly signal: AbortSignal;
  readonly assertCurrent: () => void;
  readonly dependencies?: Partial<typeof DEFAULT_DEPENDENCIES>;
}

/** Recover existing audio without re-editing or re-approving a frozen script. */
export async function recoverExistingNarration(
  options: RecoverExistingNarrationOptions,
): Promise<NarrationWorkflowResource> {
  const { workflow, signal } = options;
  const deps = { ...DEFAULT_DEPENDENCIES, ...options.dependencies };
  const check = () => {
    if (signal.aborted) throw new DOMException("朗读恢复已取消。", "AbortError");
    options.assertCurrent();
  };
  check();
  if (workflow.workflow_state !== "review_required") return workflow;
  const context = await deps.getContext(options.documentId, undefined, signal);
  check();
  if (context.novel_id !== options.novelId || context.document_id !== options.documentId
    || context.working_copy_content_hash !== workflow.source_content_hash) {
    throw new Error("朗读恢复的作品或正文已变化，请重新打开当前章节。");
  }
  const candidates = [...context.edition_history.editions]
    .filter((item) => item.source_content_hash === workflow.source_content_hash)
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")
      || a.edition_id.localeCompare(b.edition_id));
  for (const item of candidates) {
    const edition = await deps.getEdition(item.edition_id, signal);
    check();
    if (edition.novel_id !== options.novelId || edition.document_id !== options.documentId
      || edition.edition_id !== item.edition_id || edition.request_id !== item.request_id) {
      throw new Error("朗读恢复版本范围不一致，已停止。");
    }
    if (edition.settings_fingerprint !== workflow.settings_fingerprint) continue;
    const previous = await deps.getWorkflow(edition.request_id, signal);
    check();
    if (previous.request_id !== edition.request_id || previous.edition_id !== edition.edition_id
      || previous.source_content_hash !== workflow.source_content_hash
      || previous.settings_fingerprint !== workflow.settings_fingerprint) {
      throw new Error("朗读恢复请求与冻结版本不一致，已停止。");
    }
    if (!item.rights_available) throw new Error("原朗读音色授权不可用，无法恢复。");
    if (["queued", "rendering", "partial_ready", "ready"].includes(previous.workflow_state)) {
      return previous;
    }
    if (previous.workflow_state !== "failed") continue;
    const failed = await deps.getFailed(edition.edition_id, signal);
    check();
    if (failed.edition_id !== edition.edition_id || failed.request_id !== previous.request_id
      || failed.request_state !== "failed" || failed.items.length === 0
      || failed.items.some((segment) => !segment.retryable)) {
      throw new Error("原朗读版本当前不能安全重试，请查看失败详情；正文已保留。");
    }
    // Public API accepts at most 100 IDs. Freeze this click's selection so
    // newly failed manual attempts are never picked up by an automatic loop.
    const pending = new Set(failed.items.map((segment) => segment.segment_id));
    let projection = failed;
    let batch = 0;
    while (pending.size > 0) {
      const selected = projection.items.filter((segment) => pending.has(segment.segment_id));
      if (selected.some((segment) => !segment.retryable)) {
        throw new Error("朗读恢复状态已变化；已提交的批次会保留，请稍后查看失败详情。");
      }
      const ids = selected.slice(0, 100).map((segment) => segment.segment_id);
      if (ids.length === 0) break; // Another author action already recovered the rest.
      const receipt = await deps.retry(edition.edition_id, {
        segment_ids: ids,
        expected_request_version: projection.request_version,
        expected_manifest_revision: projection.manifest_revision,
      }, `${options.idempotencyKey}:${batch}`, signal);
      check();
      for (const id of receipt.affected_segment_ids) pending.delete(id);
      // The API parser guarantees acceptance; also bound progress for injected dependencies.
      for (const id of ids) pending.delete(id);
      batch += 1;
      if (pending.size === 0) break;
      // Full failure reopens as queued; remaining batches become legal once
      // the existing worker advances to rendering. Read only while waiting.
      for (let poll = 0; ; poll += 1) {
        projection = await deps.getFailed(edition.edition_id, signal);
        check();
        if (projection.edition_id !== edition.edition_id || projection.request_id !== previous.request_id) {
          throw new Error("朗读恢复批次范围变化，已停止。");
        }
        if (projection.request_state !== "queued") break;
        if (poll >= 120) throw new Error("朗读恢复仍在排队，已提交批次保留，请稍后继续。");
        await deps.delay(signal);
        check();
      }
    }
    // Retry conflicts/errors propagate; never fall through into script approval.
    const resumed = await deps.getWorkflow(previous.request_id, signal);
    check();
    if (resumed.request_id !== previous.request_id || resumed.edition_id !== edition.edition_id
      || resumed.source_content_hash !== workflow.source_content_hash
      || resumed.settings_fingerprint !== workflow.settings_fingerprint) {
      throw new Error("朗读恢复回执不一致，请重新打开当前章节。");
    }
    return resumed;
  }
  return workflow;
}
