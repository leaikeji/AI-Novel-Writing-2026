import {
  approveNarrationScriptVersion,
  patchNarrationScriptSegment,
  type ScriptReviewVersionScope,
} from "./script-api";
import type {
  ScriptIssueCode,
  ScriptReviewResource,
} from "./script-contracts";
import { createNarrationIdempotencyKey } from "./idempotency-key";


const BASIC_NARRATOR_RESOLVABLE_CODES = new Set<ScriptIssueCode>([
  "B_SPEAKER_UNKNOWN",
  "B_SPEAKER_LOW_CONFIDENCE",
  "B_CHARACTER_ALIAS_CONFLICT",
  "B_CHARACTER_REFERENCE_INVALID",
  "B_ANONYMOUS_IDENTITY_CONFLICT",
  "B_CASTING_TARGET_UNRESOLVED",
  "B_VOICE_MISSING",
  "B_VOICE_VERSION_UNAVAILABLE",
  "B_VOICE_RIGHTS_UNAVAILABLE",
]);


export interface BasicSingleNarratorProgress {
  readonly completed: number;
  readonly total: number;
  readonly message: string;
}


export interface BasicSingleNarratorDependencies {
  readonly patchSegment: typeof patchNarrationScriptSegment;
  readonly approve: typeof approveNarrationScriptVersion;
  readonly createIdempotencyKey: (prefix: string) => string;
}


export interface PrepareBasicSingleNarratorOptions {
  readonly review: ScriptReviewResource;
  readonly requestId: string;
  readonly requestVersion: number;
  readonly signal?: AbortSignal;
  readonly dependencies?: Partial<BasicSingleNarratorDependencies>;
  readonly onProgress?: (progress: BasicSingleNarratorProgress) => void;
}


export interface PrepareBasicSingleNarratorResult {
  readonly approvedReview: ScriptReviewResource;
  readonly requestVersion: number;
  readonly correctedSegmentCount: number;
}


const DEFAULT_DEPENDENCIES: BasicSingleNarratorDependencies = Object.freeze({
  patchSegment: patchNarrationScriptSegment,
  approve: approveNarrationScriptVersion,
  createIdempotencyKey: (prefix: string) => createNarrationIdempotencyKey(prefix, ":"),
});


function versionScope(review: ScriptReviewResource): ScriptReviewVersionScope {
  return {
    novel_id: review.novel_id,
    document_id: review.document_id,
    revision_id: review.revision_id,
    source_content_hash: review.source_content_hash,
    script_id: review.script_id,
    script_version_id: review.script_version_id,
  };
}


function abortError(): DOMException {
  return new DOMException("基础单旁白朗读已取消。", "AbortError");
}


function nextResolvableOrdinal(review: ScriptReviewResource): number | null {
  const blockerCodesBySegment = new Map<string, ScriptIssueCode[]>();
  for (const issue of review.issues) {
    if (issue.severity !== "blocker" || issue.segment_id === null) continue;
    const codes = blockerCodesBySegment.get(issue.segment_id) ?? [];
    codes.push(issue.code);
    blockerCodesBySegment.set(issue.segment_id, codes);
  }
  const candidate = [...review.segments]
    .sort((left, right) => left.ordinal - right.ordinal)
    .find((segment) => {
      const codes = blockerCodesBySegment.get(segment.segment_id);
      return segment.editable
        && codes !== undefined
        && codes.length > 0
        && codes.every((code) => BASIC_NARRATOR_RESOLVABLE_CODES.has(code));
    });
  return candidate?.ordinal ?? null;
}


function unresolvedBlockerSummary(review: ScriptReviewResource): string {
  const codes = [...new Set(review.issues
    .filter((issue) => issue.severity === "blocker")
    .map((issue) => issue.code))];
  return codes.length ? codes.join(", ") : "UNKNOWN_REVIEW_BLOCKER";
}


/**
 * Convert only review-authorized, editable speaker/casting failures to the
 * novel's already-frozen narrator voice. Every correction uses the existing
 * immutable child-version and request CAS path; unrelated blockers remain
 * fail-closed and are never auto-approved.
 */
export async function prepareBasicSingleNarrator(
  options: PrepareBasicSingleNarratorOptions,
): Promise<PrepareBasicSingleNarratorResult> {
  const dependencies = { ...DEFAULT_DEPENDENCIES, ...options.dependencies };
  let review = options.review;
  let requestVersion = options.requestVersion;
  let corrected = 0;
  const initialOrdinals = new Set(review.issues
    .filter((issue) => issue.severity === "blocker" && issue.segment_id !== null)
    .map((issue) => review.segments.find((segment) => segment.segment_id === issue.segment_id)?.ordinal)
    .filter((ordinal): ordinal is number => ordinal !== undefined));
  const total = initialOrdinals.size;

  while (review.blocker_count > 0) {
    if (options.signal?.aborted) throw abortError();
    const ordinal = nextResolvableOrdinal(review);
    if (ordinal === null) {
      throw new Error(`基础单旁白无法安全处理剩余阻塞：${unresolvedBlockerSummary(review)}`);
    }
    const segment = review.segments.find((item) => item.ordinal === ordinal);
    if (!segment) throw new Error("基础单旁白目标句段已经变化，请重新开始朗读。");
    options.onProgress?.({
      completed: corrected,
      total,
      message: `正在把第 ${ordinal + 1} 句纳入基础旁白（${corrected + 1}/${total}）…`,
    });
    review = await dependencies.patchSegment(
      review.script_version_id,
      segment.segment_id,
      {
        expected_request_version: requestVersion,
        expected_version_number: review.version_number,
        expected_immutable_hash: review.immutable_hash,
        expected_local_hash: segment.local_hash,
        request_id: options.requestId,
        speaker_kind: "narrator",
        speaker_label: "旁白",
        character_id: null,
        anonymous_speaker_id: null,
        group_key: null,
        spoken_text: segment.spoken_text,
        reason: "作者从可见界面选择基础单旁白朗读",
      },
      versionScope(review),
      dependencies.createIdempotencyKey("basic-narrator-segment"),
      options.signal,
    );
    requestVersion += 1;
    corrected += 1;
  }

  if (!review.allowed_actions.includes("approve")) {
    throw new Error("基础单旁白脚本已清除阻塞，但当前版本不允许批准。");
  }
  options.onProgress?.({ completed: corrected, total, message: "基础旁白脚本已就绪，正在冻结版本…" });
  const approvedReview = await dependencies.approve(
    review.script_version_id,
    {
      request_id: options.requestId,
      expected_request_version: requestVersion,
      expected_version_number: review.version_number,
      expected_immutable_hash: review.immutable_hash,
      source_revision_id: review.revision_id,
      confirmed: true,
    },
    versionScope(review),
    dependencies.createIdempotencyKey("basic-narrator-approve"),
    options.signal,
  );
  return Object.freeze({ approvedReview, requestVersion: requestVersion + 1, correctedSegmentCount: corrected });
}
