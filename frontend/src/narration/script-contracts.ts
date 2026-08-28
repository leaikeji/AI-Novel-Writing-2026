export const NARRATION_SCRIPT_REVIEW_API_VERSION = "narration-script-review-api/1" as const;
export const NARRATION_REVIEW_TAXONOMY_VERSION = "narration-review-taxonomy/1" as const;

export const SCRIPT_WARNING_CODES = [
  "W_SPEAKER_MEDIUM_CONFIDENCE",
  "W_NEW_ANONYMOUS_SPEAKER",
  "W_GENERIC_VOICE_FALLBACK",
  "W_MANUAL_OVERRIDE_INHERITED",
  "W_PRONUNCIATION_SOFT_FALLBACK",
  "W_CLOUD_ASSISTED_USED",
  "W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE",
] as const;

export const SCRIPT_BLOCKER_CODES = [
  "B_SPEAKER_UNKNOWN",
  "B_SPEAKER_LOW_CONFIDENCE",
  "B_CHARACTER_ALIAS_CONFLICT",
  "B_CHARACTER_REFERENCE_INVALID",
  "B_ANONYMOUS_IDENTITY_CONFLICT",
  "B_CASTING_TARGET_UNRESOLVED",
  "B_VOICE_MISSING",
  "B_VOICE_VERSION_UNAVAILABLE",
  "B_VOICE_RIGHTS_UNAVAILABLE",
  "B_PRONUNCIATION_HARD_CONFLICT",
  "B_CLOUD_DECISION_UNAVAILABLE",
] as const;

export const SCRIPT_API_ERROR_CODES = [
  "REQUEST_VALIDATION_FAILED",
  "RESPONSE_CONTRACT_VIOLATION",
  "SCRIPT_BACKEND_NOT_INSTALLED",
  "STORAGE_UNAVAILABLE",
  "RESOURCE_NOT_FOUND",
  "SCOPE_VIOLATION",
  "VERSION_CONFLICT",
  "INVALID_STATE",
  "IDEMPOTENCY_CONFLICT",
  "STALE_INPUT",
  "VALIDATION_FAILED",
] as const;

export type ScriptWarningCode = typeof SCRIPT_WARNING_CODES[number];
export type ScriptBlockerCode = typeof SCRIPT_BLOCKER_CODES[number];
export type ScriptIssueCode = ScriptWarningCode | ScriptBlockerCode;
export type ScriptIssueSeverity = "warning" | "blocker";
export type ScriptApiErrorCode = typeof SCRIPT_API_ERROR_CODES[number];
export type ScriptState = "draft" | "analyzing" | "analyzed" | "review_required" | "approved" | "failed";
export type ScriptReviewPolicy = "blockers_only" | "always_review";
export type ScriptSourceStatus = "current" | "working_copy_diverged" | "superseded";
export type ScriptReviewAction =
  | "approve"
  | "edit_segment"
  | "reanalyze_segments"
  | "continue_snapshot"
  | "reanalyze_latest";
export type ScriptSpeakerKind = "narrator" | "character" | "anonymous" | "group" | "unknown";
export type ScriptSegmentKind =
  | "narration"
  | "dialogue"
  | "inner_monologue"
  | "message"
  | "letter"
  | "broadcast"
  | "phone"
  | "chapter_title"
  | "synthetic_pause";
export type ScriptConfidence = "high" | "medium" | "low" | "unknown";
export type ScriptCastingState = "resolved" | "unresolved";

export interface ScriptApiErrorDetail {
  readonly contract_version: typeof NARRATION_SCRIPT_REVIEW_API_VERSION;
  readonly code: ScriptApiErrorCode;
  readonly message: string;
  readonly retryable: boolean;
  readonly field: string | null;
  readonly current_version: number | null;
}

export interface ScriptReviewIssueResource {
  readonly taxonomy_version: typeof NARRATION_REVIEW_TAXONOMY_VERSION;
  readonly code: ScriptIssueCode;
  readonly severity: ScriptIssueSeverity;
  readonly segment_id: string | null;
  readonly evidence_summary: string | null;
  readonly evidence_digest: string | null;
}

export interface ScriptReviewSegmentResource {
  readonly segment_id: string;
  readonly ordinal: number;
  readonly segment_kind: ScriptSegmentKind;
  readonly source_block_key: string;
  readonly source_start_utf16: number | null;
  readonly source_end_utf16: number | null;
  readonly source_text: string;
  readonly spoken_text: string;
  readonly local_hash: string;
  readonly speaker_kind: ScriptSpeakerKind;
  readonly speaker_label: string;
  readonly character_id: string | null;
  readonly anonymous_speaker_id: string | null;
  readonly confidence: ScriptConfidence;
  readonly casting_state: ScriptCastingState;
  readonly issue_codes: readonly ScriptIssueCode[];
  readonly editable: boolean;
}

export interface ScriptApprovalResource {
  readonly kind: "auto_no_blockers" | "manual_after_review";
  readonly request_id: string;
  readonly actor_type: "owner" | "system" | "service";
  readonly actor_id: string;
  readonly approved_at: string;
}

export interface ScriptReviewResource {
  readonly contract_version: typeof NARRATION_SCRIPT_REVIEW_API_VERSION;
  readonly taxonomy_version: typeof NARRATION_REVIEW_TAXONOMY_VERSION;
  readonly script_id: string;
  readonly script_version_id: string;
  readonly novel_id: string;
  readonly document_id: string;
  readonly revision_id: string;
  readonly source_content_hash: string;
  readonly immutable_hash: string;
  readonly version_number: number;
  readonly state: ScriptState;
  readonly effective_policy: ScriptReviewPolicy;
  readonly source_status: ScriptSourceStatus;
  readonly warning_count: number;
  readonly blocker_count: number;
  readonly allowed_actions: readonly ScriptReviewAction[];
  readonly segments: readonly ScriptReviewSegmentResource[];
  readonly issues: readonly ScriptReviewIssueResource[];
  readonly approval: ScriptApprovalResource | null;
}

export interface AnalyzeScriptRequest {
  readonly request_id: string;
  readonly source_revision_id: string;
  readonly source_content_hash: string;
}

export interface SegmentReviewPatch {
  readonly expected_request_version: number;
  readonly expected_version_number: number;
  readonly expected_immutable_hash: string;
  readonly expected_local_hash: string;
  readonly request_id: string;
  readonly speaker_kind: Exclude<ScriptSpeakerKind, "unknown">;
  readonly speaker_label: string;
  readonly character_id: string | null;
  readonly anonymous_speaker_id: string | null;
  readonly group_key: string | null;
  readonly spoken_text: string;
  readonly reason: string;
}

export interface ApproveScriptRequest {
  readonly request_id: string;
  readonly expected_request_version: number;
  readonly expected_version_number: number;
  readonly expected_immutable_hash: string;
  readonly source_revision_id: string;
  readonly confirmed: true;
}

export interface ReanalyzeSegmentsRequest {
  readonly request_id: string;
  readonly expected_request_version: number;
  readonly expected_version_number: number;
  readonly expected_immutable_hash: string;
  readonly segment_ids: readonly string[];
}

export class ScriptContractError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.path = path;
  }
}

type UnknownRecord = Record<string, unknown>;

function fail(path: string, message: string): never {
  throw new ScriptContractError(path, message);
}

function record(value: unknown, path: string): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(path, "expected object");
  }
  return value as UnknownRecord;
}

function exact(value: UnknownRecord, keys: readonly string[], path: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(path, "unexpected or missing fields");
  }
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function text(value: unknown, path: string, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): string {
  if (typeof value !== "string" || value.length < minimum || value.length > maximum) {
    fail(path, `expected string length ${minimum}-${maximum}`);
  }
  return value;
}

function nonBlankText(value: unknown, path: string, minimum = 1, maximum = Number.MAX_SAFE_INTEGER): string {
  const result = text(value, path, minimum, maximum);
  if (result.trim().length === 0) fail(path, "must not be blank");
  return result;
}

function nullableText(value: unknown, path: string, maximum: number): string | null {
  return value === null ? null : nonBlankText(value, path, 1, maximum);
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function integer(value: unknown, path: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    fail(path, `expected safe integer >= ${minimum}`);
  }
  return value as number;
}

function nullableInteger(value: unknown, path: string, minimum = 0): number | null {
  return value === null ? null : integer(value, path, minimum);
}

function oneOf<T extends string>(value: unknown, values: readonly T[], path: string): T {
  if (typeof value !== "string" || !(values as readonly string[]).includes(value)) {
    fail(path, `expected one of ${values.join(", ")}`);
  }
  return value as T;
}

function uuid(value: unknown, path: string): string {
  const result = text(value, path, 36, 36).toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(result)) {
    fail(path, "expected RFC-4122 UUID v1-v5");
  }
  return result;
}

function nullableUuid(value: unknown, path: string): string | null {
  return value === null ? null : uuid(value, path);
}

function sha256(value: unknown, path: string): string {
  const result = text(value, path, 64, 64);
  if (!/^[a-f0-9]{64}$/.test(result)) fail(path, "expected lowercase SHA-256");
  return result;
}

function nullableSha256(value: unknown, path: string): string | null {
  return value === null ? null : sha256(value, path);
}

function timestamp(value: unknown, path: string): string {
  const result = text(value, path, 1, 80);
  const parsed = Date.parse(result);
  if (!Number.isFinite(parsed) || !result.endsWith("Z")) {
    fail(path, "expected UTC timestamp");
  }
  return result;
}

export function scriptIssueSeverity(code: ScriptIssueCode): ScriptIssueSeverity {
  if ((SCRIPT_WARNING_CODES as readonly string[]).includes(code)) return "warning";
  if ((SCRIPT_BLOCKER_CODES as readonly string[]).includes(code)) return "blocker";
  return fail("issue.code", "unknown review taxonomy code");
}

function issueCode(value: unknown, path: string): ScriptIssueCode {
  const all = [...SCRIPT_WARNING_CODES, ...SCRIPT_BLOCKER_CODES] as readonly ScriptIssueCode[];
  return oneOf(value, all, path);
}

function parseIssue(value: unknown, path: string): ScriptReviewIssueResource {
  const item = record(value, path);
  exact(item, [
    "taxonomy_version", "code", "severity", "segment_id", "evidence_summary", "evidence_digest",
  ], path);
  if (item.taxonomy_version !== NARRATION_REVIEW_TAXONOMY_VERSION) {
    fail(`${path}.taxonomy_version`, "unknown taxonomy version");
  }
  const code = issueCode(item.code, `${path}.code`);
  const severity = oneOf(item.severity, ["warning", "blocker"] as const, `${path}.severity`);
  if (severity !== scriptIssueSeverity(code)) {
    fail(`${path}.severity`, "server-owned severity differs from taxonomy");
  }
  const evidenceSummary = nullableText(item.evidence_summary, `${path}.evidence_summary`, 500);
  const evidenceDigest = nullableSha256(item.evidence_digest, `${path}.evidence_digest`);
  if (evidenceSummary !== null && evidenceDigest === null) {
    fail(`${path}.evidence_summary`, "requires evidence_digest");
  }
  return {
    taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
    code,
    severity,
    segment_id: nullableUuid(item.segment_id, `${path}.segment_id`),
    evidence_summary: evidenceSummary,
    evidence_digest: evidenceDigest,
  };
}

function parseSegment(value: unknown, path: string): ScriptReviewSegmentResource {
  const item = record(value, path);
  exact(item, [
    "segment_id", "ordinal", "segment_kind", "source_block_key", "source_start_utf16",
    "source_end_utf16", "source_text", "spoken_text", "local_hash", "speaker_kind",
    "speaker_label", "character_id", "anonymous_speaker_id", "confidence", "casting_state",
    "issue_codes", "editable",
  ], path);
  const start = nullableInteger(item.source_start_utf16, `${path}.source_start_utf16`);
  const end = nullableInteger(item.source_end_utf16, `${path}.source_end_utf16`);
  if ((start === null) !== (end === null) || (start !== null && end !== null && end < start)) {
    fail(path, "invalid UTF-16 source range");
  }
  const speakerKind = oneOf(
    item.speaker_kind,
    ["narrator", "character", "anonymous", "group", "unknown"] as const,
    `${path}.speaker_kind`,
  );
  const characterId = nullableUuid(item.character_id, `${path}.character_id`);
  const anonymousId = nullableUuid(item.anonymous_speaker_id, `${path}.anonymous_speaker_id`);
  if (speakerKind === "character") {
    if (characterId === null || anonymousId !== null) fail(path, "invalid character identity shape");
  } else if (speakerKind === "anonymous") {
    if (anonymousId === null || characterId !== null) fail(path, "invalid anonymous identity shape");
  } else if (characterId !== null || anonymousId !== null) {
    fail(path, "non-identity speaker carries identity id");
  }
  const codes = array(item.issue_codes, `${path}.issue_codes`).map((entry, index) => (
    issueCode(entry, `${path}.issue_codes[${index}]`)
  ));
  if (codes.length !== new Set(codes).size || codes.some((code, index) => code !== [...codes].sort()[index])) {
    fail(`${path}.issue_codes`, "must be unique and sorted");
  }
  const confidence = oneOf(item.confidence, ["high", "medium", "low", "unknown"] as const, `${path}.confidence`);
  const castingState = oneOf(item.casting_state, ["resolved", "unresolved"] as const, `${path}.casting_state`);
  if (speakerKind === "unknown" && !codes.includes("B_SPEAKER_UNKNOWN")) {
    fail(`${path}.issue_codes`, "unknown speaker lacks B_SPEAKER_UNKNOWN");
  }
  if (confidence === "low" && !codes.includes("B_SPEAKER_LOW_CONFIDENCE")) {
    fail(`${path}.issue_codes`, "low confidence lacks B_SPEAKER_LOW_CONFIDENCE");
  }
  if (confidence === "unknown" && !codes.includes("B_SPEAKER_LOW_CONFIDENCE")) {
    fail(`${path}.issue_codes`, "unknown confidence lacks B_SPEAKER_LOW_CONFIDENCE");
  }
  if (confidence === "medium" && !codes.includes("W_SPEAKER_MEDIUM_CONFIDENCE")) {
    fail(`${path}.issue_codes`, "medium confidence lacks warning");
  }
  if (castingState === "unresolved" && !codes.includes("B_CASTING_TARGET_UNRESOLVED")) {
    fail(`${path}.issue_codes`, "unresolved casting lacks blocker");
  }
  return {
    segment_id: uuid(item.segment_id, `${path}.segment_id`),
    ordinal: integer(item.ordinal, `${path}.ordinal`),
    segment_kind: oneOf(item.segment_kind, [
      "narration", "dialogue", "inner_monologue", "message", "letter", "broadcast",
      "phone", "chapter_title", "synthetic_pause",
    ] as const, `${path}.segment_kind`),
    source_block_key: (() => {
      const key = text(item.source_block_key, `${path}.source_block_key`, 68, 68);
      if (!/^sb1_[a-f0-9]{64}$/.test(key)) {
        fail(`${path}.source_block_key`, "expected narration-source-block/1 key");
      }
      return key;
    })(),
    source_start_utf16: start,
    source_end_utf16: end,
    source_text: text(item.source_text, `${path}.source_text`),
    spoken_text: text(item.spoken_text, `${path}.spoken_text`),
    local_hash: sha256(item.local_hash, `${path}.local_hash`),
    speaker_kind: speakerKind,
    speaker_label: nonBlankText(item.speaker_label, `${path}.speaker_label`, 1, 160),
    character_id: characterId,
    anonymous_speaker_id: anonymousId,
    confidence,
    casting_state: castingState,
    issue_codes: Object.freeze(codes),
    editable: boolean(item.editable, `${path}.editable`),
  };
}

function parseApproval(value: unknown, path: string): ScriptApprovalResource | null {
  if (value === null) return null;
  const item = record(value, path);
  exact(item, ["kind", "request_id", "actor_type", "actor_id", "approved_at"], path);
  const kind = oneOf(item.kind, ["auto_no_blockers", "manual_after_review"] as const, `${path}.kind`);
  const actorType = oneOf(item.actor_type, ["owner", "system", "service"] as const, `${path}.actor_type`);
  if (kind === "auto_no_blockers" && !["system", "service"].includes(actorType)) {
    fail(`${path}.actor_type`, "automatic approval requires system/service");
  }
  if (kind === "manual_after_review" && actorType !== "owner") {
    fail(`${path}.actor_type`, "manual approval requires owner");
  }
  return {
    kind,
    request_id: uuid(item.request_id, `${path}.request_id`),
    actor_type: actorType,
    actor_id: nonBlankText(item.actor_id, `${path}.actor_id`, 1, 120),
    approved_at: timestamp(item.approved_at, `${path}.approved_at`),
  };
}

export function parseScriptApiErrorDetail(value: unknown): ScriptApiErrorDetail {
  const item = record(value, "error");
  exact(item, ["contract_version", "code", "message", "retryable", "field", "current_version"], "error");
  if (item.contract_version !== NARRATION_SCRIPT_REVIEW_API_VERSION) {
    fail("error.contract_version", "unknown contract version");
  }
  return {
    contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
    code: oneOf(item.code, SCRIPT_API_ERROR_CODES, "error.code"),
    message: nonBlankText(item.message, "error.message", 1, 400),
    retryable: boolean(item.retryable, "error.retryable"),
    field: nullableText(item.field, "error.field", 160),
    current_version: item.current_version === null
      ? null
      : integer(item.current_version, "error.current_version", 1),
  };
}

export function parseScriptReviewResource(value: unknown): ScriptReviewResource {
  const item = record(value, "script_review");
  exact(item, [
    "contract_version", "taxonomy_version", "script_id", "script_version_id", "novel_id",
    "document_id", "revision_id", "source_content_hash", "immutable_hash", "version_number",
    "state", "effective_policy", "source_status", "warning_count", "blocker_count",
    "allowed_actions", "segments", "issues", "approval",
  ], "script_review");
  if (item.contract_version !== NARRATION_SCRIPT_REVIEW_API_VERSION) {
    fail("script_review.contract_version", "unknown contract version");
  }
  if (item.taxonomy_version !== NARRATION_REVIEW_TAXONOMY_VERSION) {
    fail("script_review.taxonomy_version", "unknown taxonomy version");
  }
  const state = oneOf(item.state, ["draft", "analyzing", "analyzed", "review_required", "approved", "failed"] as const, "script_review.state");
  const sourceStatus = oneOf(item.source_status, ["current", "working_copy_diverged", "superseded"] as const, "script_review.source_status");
  const actions = array(item.allowed_actions, "script_review.allowed_actions").map((entry, index) => (
    oneOf(entry, ["approve", "edit_segment", "reanalyze_segments", "continue_snapshot", "reanalyze_latest"] as const, `script_review.allowed_actions[${index}]`)
  ));
  if (actions.length !== new Set(actions).size) fail("script_review.allowed_actions", "must be unique");
  const segments = array(item.segments, "script_review.segments").map((entry, index) => (
    parseSegment(entry, `script_review.segments[${index}]`)
  ));
  if (segments.some((segment, index) => segment.ordinal !== index)) {
    fail("script_review.segments", "ordinals must be contiguous from zero");
  }
  const segmentIds = new Set(segments.map((segment) => segment.segment_id));
  if (segmentIds.size !== segments.length) fail("script_review.segments", "duplicate segment ids");
  const issues = array(item.issues, "script_review.issues").map((entry, index) => (
    parseIssue(entry, `script_review.issues[${index}]`)
  ));
  const issueKeys = issues.map((issue) => `${issue.code}\0${issue.segment_id ?? ""}\0${issue.evidence_digest ?? ""}`);
  if (new Set(issueKeys).size !== issueKeys.length) fail("script_review.issues", "duplicate issue rows");
  if (issueKeys.some((key, index) => key !== [...issueKeys].sort()[index])) {
    fail("script_review.issues", "must use canonical order");
  }
  for (const issue of issues) {
    if (issue.segment_id !== null && !segmentIds.has(issue.segment_id)) {
      fail("script_review.issues", "issue references unknown segment");
    }
  }
  const warningCount = integer(item.warning_count, "script_review.warning_count");
  const blockerCount = integer(item.blocker_count, "script_review.blocker_count");
  if (
    issues.filter((issue) => issue.severity === "warning").length !== warningCount
    || issues.filter((issue) => issue.severity === "blocker").length !== blockerCount
  ) {
    fail("script_review", "issue counts differ from issue rows");
  }
  for (const segment of segments) {
    const rowCodes = issues
      .filter((issue) => issue.segment_id === segment.segment_id)
      .map((issue) => issue.code)
      .sort();
    if (
      rowCodes.length !== segment.issue_codes.length
      || rowCodes.some((code, index) => code !== segment.issue_codes[index])
    ) {
      fail("script_review.segments", "segment issue_codes differ from issue rows");
    }
  }
  const approval = parseApproval(item.approval, "script_review.approval");
  if (state === "approved") {
    if (blockerCount !== 0 || approval === null || actions.length !== 0) {
      fail("script_review", "approved script must be blocker-free, audited, and terminal");
    }
    if (approval.kind === "auto_no_blockers" && item.effective_policy !== "blockers_only") {
      fail("script_review.approval", "automatic approval is only valid for blockers_only");
    }
  } else if (approval !== null) {
    fail("script_review.approval", "only approved state may contain approval");
  }
  const actionSet = new Set(actions);
  if (actionSet.has("approve") && (state !== "review_required" || blockerCount !== 0)) {
    fail("script_review.allowed_actions", "approve requires zero-blocker review_required state");
  }
  if (blockerCount > 0 && state !== "review_required") {
    fail("script_review.state", "blockers require review_required");
  }
  if (state !== "review_required" && actions.length !== 0) {
    fail("script_review.allowed_actions", "only review_required script may expose review actions");
  }
  if (sourceStatus === "superseded" && actions.length !== 0) {
    fail("script_review.allowed_actions", "superseded script must be read-only");
  }
  const snapshotActions = ["continue_snapshot", "reanalyze_latest"] as const;
  if (sourceStatus === "current" && snapshotActions.some((action) => actionSet.has(action))) {
    fail("script_review.allowed_actions", "current source cannot expose snapshot decisions");
  }
  if (
    state === "review_required"
    && sourceStatus === "working_copy_diverged"
    && (!actionSet.has("continue_snapshot") || !actionSet.has("reanalyze_latest"))
  ) {
    fail("script_review.allowed_actions", "diverged source requires both snapshot choices");
  }
  return Object.freeze({
    contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
    taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
    script_id: uuid(item.script_id, "script_review.script_id"),
    script_version_id: uuid(item.script_version_id, "script_review.script_version_id"),
    novel_id: uuid(item.novel_id, "script_review.novel_id"),
    document_id: uuid(item.document_id, "script_review.document_id"),
    revision_id: uuid(item.revision_id, "script_review.revision_id"),
    source_content_hash: sha256(item.source_content_hash, "script_review.source_content_hash"),
    immutable_hash: sha256(item.immutable_hash, "script_review.immutable_hash"),
    version_number: integer(item.version_number, "script_review.version_number", 1),
    state,
    effective_policy: oneOf(item.effective_policy, ["blockers_only", "always_review"] as const, "script_review.effective_policy"),
    source_status: sourceStatus,
    warning_count: warningCount,
    blocker_count: blockerCount,
    allowed_actions: Object.freeze(actions),
    segments: Object.freeze(segments),
    issues: Object.freeze(issues),
    approval,
  });
}
