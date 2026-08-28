import {
  EditionHistoryContractError,
  parseDocumentEditionHistory,
} from "./edition-history";
import type { DocumentEditionHistory, EditionState, EditionSwitchMode } from "./edition-history";


export const NARRATION_PRODUCTION_API_VERSION = "narration-production-api/1" as const;
export const DOCUMENT_NARRATION_CONTEXT_VERSION = "document-narration-context/1" as const;
export const FAILED_SEGMENT_RETRY_CONTRACT_VERSION = "narration-failed-segment-retry/1" as const;


export type NarrationWorkflowIntent = "create" | "update" | "analyze_only";
export type NarrationWorkflowState =
  | "created"
  | "analyzing"
  | "analyzed"
  | "review_required"
  | "queued"
  | "rendering"
  | "partial_ready"
  | "ready"
  | "cancel_requested"
  | "cancelled"
  | "failed";
export type DocumentNarrationCompatibility =
  | "no_current_edition"
  | "current"
  | "working_copy_diverged"
  | "superseded"
  | "unavailable";
export type NarrationSourceNoticeCode =
  | "NO_CURRENT_EDITION"
  | "CURRENT_SOURCE_SNAPSHOT"
  | "OLD_SOURCE_SNAPSHOT"
  | "HISTORICAL_EDITION"
  | "EDITION_UNAVAILABLE";
export type NarrationEditorTimelineMode =
  | "none"
  | "exact_working_copy"
  | "immutable_edition_only";


export interface CreateNarrationWorkflowRequest {
  readonly intent: NarrationWorkflowIntent;
  readonly expected_draft_version: number;
  readonly expected_content_hash: string;
  readonly expected_settings_version: number;
  readonly force_review: boolean;
}


export interface NarrationWorkflowResource {
  readonly contract_version: typeof NARRATION_PRODUCTION_API_VERSION;
  readonly request_id: string;
  readonly intent: NarrationWorkflowIntent;
  readonly request_version: number;
  readonly workflow_state: NarrationWorkflowState;
  readonly source_revision_id: string;
  readonly source_content_hash: string;
  readonly settings_fingerprint: string;
  readonly warning_count: number;
  readonly blocker_count: number;
  readonly script_version_id: string | null;
  readonly edition_id: string | null;
  readonly current_manifest_revision: number | null;
  readonly job_ids: readonly string[];
  readonly replayed: boolean;
}


export interface NarrationEditionResource {
  readonly contract_version: typeof NARRATION_PRODUCTION_API_VERSION;
  readonly edition_id: string;
  readonly request_id: string;
  readonly novel_id: string;
  readonly document_id: string;
  readonly script_version_id: string;
  readonly settings_fingerprint: string;
  readonly edition_fingerprint: string;
  readonly state: EditionState;
  readonly segment_count: number;
  readonly pending_segment_count: number;
  readonly queued_segment_count: number;
  readonly rendering_segment_count: number;
  readonly ready_segment_count: number;
  readonly failed_segment_count: number;
  readonly current_manifest_revision: number | null;
  readonly job_ids: readonly string[];
}


export interface NarrationSourceSnapshot {
  readonly revision_id: string;
  readonly content_hash: string;
  readonly matches_working_copy: boolean;
}


export interface DocumentNarrationContext {
  readonly contract_version: typeof DOCUMENT_NARRATION_CONTEXT_VERSION;
  readonly document_id: string;
  readonly novel_id: string;
  readonly pointer_version: number;
  readonly current_script_version_id: string | null;
  readonly current_edition_id: string | null;
  readonly active_edition_id: string | null;
  readonly active_is_current: boolean;
  readonly working_copy_draft_version: number;
  readonly working_copy_content_hash: string;
  readonly source_snapshot: NarrationSourceSnapshot | null;
  readonly compatibility: DocumentNarrationCompatibility;
  readonly source_notice_code: NarrationSourceNoticeCode;
  readonly editor_timeline_mode: NarrationEditorTimelineMode;
  readonly old_draft_subtitle_required: boolean;
  readonly explicit_update_required: boolean;
  readonly can_request_update: boolean;
  readonly available_current_source_edition_ids: readonly string[];
  readonly edition_history: DocumentEditionHistory;
}


export interface SwitchNarrationEditionRequest {
  readonly target_edition_id: string;
  readonly expected_version: number;
  readonly switch_mode: EditionSwitchMode;
  readonly start_segment_id: string | null;
  readonly playback_rate_millis: number;
  readonly confirmed: true;
}


export interface SwitchNarrationEditionResponse {
  readonly contract_version: typeof DOCUMENT_NARRATION_CONTEXT_VERSION;
  readonly document_id: string;
  readonly current_edition_id: string;
  readonly pointer_version: number;
  readonly switch_mode: EditionSwitchMode;
  readonly start_segment_id: string | null;
  readonly manifest_revision: number;
  readonly playback_progress_id: string | null;
}


export interface FailedNarrationSegmentRetryItem {
  readonly segment_id: string;
  readonly ordinal: number;
  readonly failure_code: string;
  readonly retryable: boolean;
  readonly retry_reason_code: string | null;
  readonly job_id: string;
  readonly fanout_segment_ids: readonly string[];
}


export interface FailedNarrationSegmentsProjection {
  readonly contract_version: typeof FAILED_SEGMENT_RETRY_CONTRACT_VERSION;
  readonly edition_id: string;
  readonly request_id: string;
  readonly request_version: number;
  readonly manifest_revision: number | null;
  readonly request_state: NarrationWorkflowState;
  readonly edition_state: EditionState;
  readonly items: readonly FailedNarrationSegmentRetryItem[];
}


export interface RetryFailedNarrationSegmentsRequest {
  readonly segment_ids: readonly string[];
  readonly expected_request_version: number;
  readonly expected_manifest_revision: number | null;
}


export interface FailedNarrationSegmentRetryCommand {
  readonly command_id: string;
  readonly job_id: string;
  readonly affected_segment_ids: readonly string[];
}


export interface RetryFailedNarrationSegmentsResponse {
  readonly contract_version: typeof FAILED_SEGMENT_RETRY_CONTRACT_VERSION;
  readonly edition_id: string;
  readonly request_id: string;
  readonly accepted_segment_ids: readonly string[];
  readonly affected_segment_ids: readonly string[];
  readonly commands: readonly FailedNarrationSegmentRetryCommand[];
  readonly request_version: number;
  readonly request_state: NarrationWorkflowState;
  readonly edition_state: EditionState;
  readonly replayed: boolean;
}


export type NarrationProductionErrorCode =
  | "REQUEST_VALIDATION_FAILED"
  | "RESPONSE_CONTRACT_VIOLATION"
  | "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED"
  | "STORAGE_UNAVAILABLE"
  | "RESOURCE_NOT_FOUND"
  | "SCOPE_VIOLATION"
  | "VERSION_CONFLICT"
  | "INVALID_STATE"
  | "IDEMPOTENCY_CONFLICT"
  | "STALE_INPUT"
  | "VOICE_RIGHTS_UNAVAILABLE"
  | "VALIDATION_FAILED";


export interface NarrationProductionApiErrorDetail {
  readonly contract_version: typeof NARRATION_PRODUCTION_API_VERSION;
  readonly code: NarrationProductionErrorCode;
  readonly message: string;
  readonly retryable: boolean;
  readonly field: string | null;
  readonly current_version: number | null;
}


export class ChapterNarrationContractError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "ChapterNarrationContractError";
    this.path = path;
  }
}


type JsonRecord = Record<string, unknown>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const FAILURE_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,95}$/u;
const WORKFLOW_INTENTS = ["create", "update", "analyze_only"] as const;
const WORKFLOW_STATES = [
  "created", "analyzing", "analyzed", "review_required", "queued", "rendering",
  "partial_ready", "ready", "cancel_requested", "cancelled", "failed",
] as const;
const EDITION_STATES = ["created", "rendering", "partial_ready", "ready", "unavailable"] as const;
const COMPATIBILITIES = [
  "no_current_edition", "current", "working_copy_diverged", "superseded", "unavailable",
] as const;
const SOURCE_NOTICES = [
  "NO_CURRENT_EDITION", "CURRENT_SOURCE_SNAPSHOT", "OLD_SOURCE_SNAPSHOT",
  "HISTORICAL_EDITION", "EDITION_UNAVAILABLE",
] as const;
const TIMELINE_MODES = ["none", "exact_working_copy", "immutable_edition_only"] as const;
const SWITCH_MODES = ["immediate", "next_playback"] as const;
const PRODUCTION_ERROR_CODES = [
  "REQUEST_VALIDATION_FAILED",
  "RESPONSE_CONTRACT_VIOLATION",
  "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED",
  "STORAGE_UNAVAILABLE",
  "RESOURCE_NOT_FOUND",
  "SCOPE_VIOLATION",
  "VERSION_CONFLICT",
  "INVALID_STATE",
  "IDEMPOTENCY_CONFLICT",
  "STALE_INPUT",
  "VOICE_RIGHTS_UNAVAILABLE",
  "VALIDATION_FAILED",
] as const;

const CREATE_REQUEST_KEYS = [
  "intent", "expected_draft_version", "expected_content_hash",
  "expected_settings_version", "force_review",
] as const;
const WORKFLOW_KEYS = [
  "contract_version", "request_id", "intent", "request_version", "workflow_state",
  "source_revision_id", "source_content_hash", "settings_fingerprint", "warning_count",
  "blocker_count", "script_version_id", "edition_id", "current_manifest_revision",
  "job_ids", "replayed",
] as const;
const EDITION_KEYS = [
  "contract_version", "edition_id", "request_id", "novel_id", "document_id",
  "script_version_id", "settings_fingerprint", "edition_fingerprint", "state",
  "segment_count", "pending_segment_count", "queued_segment_count",
  "rendering_segment_count", "ready_segment_count", "failed_segment_count",
  "current_manifest_revision", "job_ids",
] as const;
const SOURCE_SNAPSHOT_KEYS = ["revision_id", "content_hash", "matches_working_copy"] as const;
const CONTEXT_KEYS = [
  "contract_version", "document_id", "novel_id", "pointer_version",
  "current_script_version_id", "current_edition_id", "active_edition_id",
  "active_is_current", "working_copy_draft_version", "working_copy_content_hash",
  "source_snapshot", "compatibility", "source_notice_code", "editor_timeline_mode",
  "old_draft_subtitle_required", "explicit_update_required", "can_request_update",
  "available_current_source_edition_ids", "edition_history",
] as const;
const SWITCH_REQUEST_KEYS = [
  "target_edition_id", "expected_version", "switch_mode", "start_segment_id",
  "playback_rate_millis", "confirmed",
] as const;
const SWITCH_RESPONSE_KEYS = [
  "contract_version", "document_id", "current_edition_id", "pointer_version",
  "switch_mode", "start_segment_id", "manifest_revision", "playback_progress_id",
] as const;
const FAILED_SEGMENT_ITEM_KEYS = [
  "segment_id", "ordinal", "failure_code", "retryable", "retry_reason_code",
  "job_id", "fanout_segment_ids",
] as const;
const FAILED_SEGMENTS_PROJECTION_KEYS = [
  "contract_version", "edition_id", "request_id", "request_version",
  "manifest_revision", "request_state", "edition_state", "items",
] as const;
const RETRY_FAILED_SEGMENTS_REQUEST_KEYS = [
  "segment_ids", "expected_request_version", "expected_manifest_revision",
] as const;
const FAILED_SEGMENT_COMMAND_KEYS = [
  "command_id", "job_id", "affected_segment_ids",
] as const;
const RETRY_FAILED_SEGMENTS_RESPONSE_KEYS = [
  "contract_version", "edition_id", "request_id", "accepted_segment_ids",
  "affected_segment_ids", "commands", "request_version", "request_state",
  "edition_state", "replayed",
] as const;
const ERROR_KEYS = [
  "contract_version", "code", "message", "retryable", "field", "current_version",
] as const;


function fail(path: string, message: string): never {
  throw new ChapterNarrationContractError(path, message);
}


function exactRecord(value: unknown, path: string, keys: readonly string[]): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return fail(path, "must be an object");
  }
  const record = value as JsonRecord;
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length
    || actual.some((key, index) => key !== expected[index])
  ) {
    return fail(path, "has unexpected or missing fields");
  }
  return record;
}


function text(value: unknown, path: string, minimum = 1, maximum = Number.MAX_SAFE_INTEGER): string {
  if (
    typeof value !== "string"
    || value.length < minimum
    || value.length > maximum
    || (minimum > 0 && value.trim().length === 0)
  ) {
    return fail(path, `must be a non-blank string of length ${minimum}-${maximum}`);
  }
  return value;
}


export function normalizeChapterUuid(value: string, path: string): string {
  const normalized = text(value, path, 36, 36).toLowerCase();
  if (!UUID_PATTERN.test(normalized)) return fail(path, "must be an RFC-4122 UUID v1-v5");
  return normalized;
}


function uuid(value: unknown, path: string): string {
  if (typeof value !== "string") return fail(path, "must be an RFC-4122 UUID v1-v5");
  return normalizeChapterUuid(value, path);
}


function nullableUuid(value: unknown, path: string): string | null {
  return value === null ? null : uuid(value, path);
}


function sha256(value: unknown, path: string): string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    return fail(path, "must be a lowercase SHA-256");
  }
  return value;
}


function integer(
  value: unknown,
  path: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    return fail(path, `must be a safe integer in ${minimum}-${maximum}`);
  }
  return value as number;
}


function nullableInteger(value: unknown, path: string, minimum: number): number | null {
  return value === null ? null : integer(value, path, minimum);
}


function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") return fail(path, "must be a boolean");
  return value;
}


function nullableText(value: unknown, path: string, maximum: number): string | null {
  return value === null ? null : text(value, path, 1, maximum);
}


function oneOf<T extends string>(value: unknown, choices: readonly T[], path: string): T {
  if (typeof value !== "string" || !(choices as readonly string[]).includes(value)) {
    return fail(path, `must be one of ${choices.join(", ")}`);
  }
  return value as T;
}


function uuidArray(value: unknown, path: string): readonly string[] {
  if (!Array.isArray(value)) return fail(path, "must be an array");
  const result = value.map((item, index) => uuid(item, `${path}[${index}]`));
  if (new Set(result).size !== result.length) return fail(path, "must contain unique UUIDs");
  return Object.freeze(result);
}


function boundedUuidArray(
  value: unknown,
  path: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): readonly string[] {
  const result = uuidArray(value, path);
  if (result.length < minimum || result.length > maximum) {
    return fail(path, `must contain ${minimum}-${maximum} UUIDs`);
  }
  return result;
}


function stableCode(value: unknown, path: string): string {
  if (typeof value !== "string" || !FAILURE_CODE_PATTERN.test(value)) {
    return fail(path, "must be a stable uppercase code of length 1-96");
  }
  return value;
}


function nullableStableCode(value: unknown, path: string): string | null {
  return value === null ? null : stableCode(value, path);
}


function equalOrdered(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}


export function parseCreateNarrationWorkflowRequest(
  value: unknown,
): CreateNarrationWorkflowRequest {
  const item = exactRecord(value, "request", CREATE_REQUEST_KEYS);
  return Object.freeze({
    intent: oneOf(item.intent, WORKFLOW_INTENTS, "request.intent"),
    expected_draft_version: integer(
      item.expected_draft_version,
      "request.expected_draft_version",
      1,
    ),
    expected_content_hash: sha256(
      item.expected_content_hash,
      "request.expected_content_hash",
    ),
    expected_settings_version: integer(
      item.expected_settings_version,
      "request.expected_settings_version",
      1,
    ),
    force_review: boolean(item.force_review, "request.force_review"),
  });
}


export function parseNarrationWorkflowResource(value: unknown): NarrationWorkflowResource {
  const item = exactRecord(value, "workflow", WORKFLOW_KEYS);
  if (item.contract_version !== NARRATION_PRODUCTION_API_VERSION) {
    return fail("workflow.contract_version", "is unsupported");
  }
  const intent = oneOf(item.intent, WORKFLOW_INTENTS, "workflow.intent");
  const editionId = nullableUuid(item.edition_id, "workflow.edition_id");
  const manifestRevision = nullableInteger(
    item.current_manifest_revision,
    "workflow.current_manifest_revision",
    1,
  );
  const jobIds = uuidArray(item.job_ids, "workflow.job_ids");
  if (editionId === null && manifestRevision !== null) {
    return fail("workflow.current_manifest_revision", "requires an Edition");
  }
  if (intent === "analyze_only" && (editionId !== null || manifestRevision !== null || jobIds.length > 0)) {
    return fail("workflow", "analyze_only cannot expose production resources");
  }
  return Object.freeze({
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    request_id: uuid(item.request_id, "workflow.request_id"),
    intent,
    request_version: integer(item.request_version, "workflow.request_version", 1),
    workflow_state: oneOf(item.workflow_state, WORKFLOW_STATES, "workflow.workflow_state"),
    source_revision_id: uuid(item.source_revision_id, "workflow.source_revision_id"),
    source_content_hash: sha256(item.source_content_hash, "workflow.source_content_hash"),
    settings_fingerprint: sha256(item.settings_fingerprint, "workflow.settings_fingerprint"),
    warning_count: integer(item.warning_count, "workflow.warning_count", 0),
    blocker_count: integer(item.blocker_count, "workflow.blocker_count", 0),
    script_version_id: nullableUuid(item.script_version_id, "workflow.script_version_id"),
    edition_id: editionId,
    current_manifest_revision: manifestRevision,
    job_ids: jobIds,
    replayed: boolean(item.replayed, "workflow.replayed"),
  });
}


export function parseNarrationEditionResource(value: unknown): NarrationEditionResource {
  const item = exactRecord(value, "edition", EDITION_KEYS);
  if (item.contract_version !== NARRATION_PRODUCTION_API_VERSION) {
    return fail("edition.contract_version", "is unsupported");
  }
  const segmentCount = integer(item.segment_count, "edition.segment_count", 1);
  const pending = integer(item.pending_segment_count, "edition.pending_segment_count", 0);
  const queued = integer(item.queued_segment_count, "edition.queued_segment_count", 0);
  const rendering = integer(item.rendering_segment_count, "edition.rendering_segment_count", 0);
  const ready = integer(item.ready_segment_count, "edition.ready_segment_count", 0);
  const failed = integer(item.failed_segment_count, "edition.failed_segment_count", 0);
  if (pending + queued + rendering + ready + failed > segmentCount) {
    return fail("edition", "segment-state counts exceed segment_count");
  }
  return Object.freeze({
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    edition_id: uuid(item.edition_id, "edition.edition_id"),
    request_id: uuid(item.request_id, "edition.request_id"),
    novel_id: uuid(item.novel_id, "edition.novel_id"),
    document_id: uuid(item.document_id, "edition.document_id"),
    script_version_id: uuid(item.script_version_id, "edition.script_version_id"),
    settings_fingerprint: sha256(item.settings_fingerprint, "edition.settings_fingerprint"),
    edition_fingerprint: sha256(item.edition_fingerprint, "edition.edition_fingerprint"),
    state: oneOf(item.state, EDITION_STATES, "edition.state"),
    segment_count: segmentCount,
    pending_segment_count: pending,
    queued_segment_count: queued,
    rendering_segment_count: rendering,
    ready_segment_count: ready,
    failed_segment_count: failed,
    current_manifest_revision: nullableInteger(
      item.current_manifest_revision,
      "edition.current_manifest_revision",
      1,
    ),
    job_ids: uuidArray(item.job_ids, "edition.job_ids"),
  });
}


function parseSourceSnapshot(value: unknown): NarrationSourceSnapshot {
  const item = exactRecord(value, "context.source_snapshot", SOURCE_SNAPSHOT_KEYS);
  return Object.freeze({
    revision_id: uuid(item.revision_id, "context.source_snapshot.revision_id"),
    content_hash: sha256(item.content_hash, "context.source_snapshot.content_hash"),
    matches_working_copy: boolean(
      item.matches_working_copy,
      "context.source_snapshot.matches_working_copy",
    ),
  });
}


function contextCompatibility(
  active: DocumentEditionHistory["editions"][number] | undefined,
  currentEditionId: string | null,
  workingCopyHash: string,
): readonly [DocumentNarrationCompatibility, NarrationSourceNoticeCode] {
  if (active === undefined) return ["no_current_edition", "NO_CURRENT_EDITION"];
  if (!active.playable || active.state === "unavailable") {
    return ["unavailable", "EDITION_UNAVAILABLE"];
  }
  if (active.edition_id !== currentEditionId) return ["superseded", "HISTORICAL_EDITION"];
  if (active.source_content_hash !== workingCopyHash) {
    return ["working_copy_diverged", "OLD_SOURCE_SNAPSHOT"];
  }
  return ["current", "CURRENT_SOURCE_SNAPSHOT"];
}


export function parseDocumentNarrationContext(value: unknown): DocumentNarrationContext {
  const item = exactRecord(value, "context", CONTEXT_KEYS);
  if (item.contract_version !== DOCUMENT_NARRATION_CONTEXT_VERSION) {
    return fail("context.contract_version", "is unsupported");
  }
  let history: DocumentEditionHistory;
  try {
    history = parseDocumentEditionHistory(item.edition_history);
  } catch (reason) {
    if (reason instanceof EditionHistoryContractError) {
      return fail(`context.edition_history.${reason.path}`, reason.message);
    }
    throw reason;
  }
  const documentId = uuid(item.document_id, "context.document_id");
  const pointerVersion = integer(item.pointer_version, "context.pointer_version", 0);
  const currentEditionId = nullableUuid(item.current_edition_id, "context.current_edition_id");
  const activeEditionId = nullableUuid(item.active_edition_id, "context.active_edition_id");
  const workingCopyVersion = integer(
    item.working_copy_draft_version,
    "context.working_copy_draft_version",
    1,
  );
  const workingCopyHash = sha256(
    item.working_copy_content_hash,
    "context.working_copy_content_hash",
  );
  if (
    history.document_id !== documentId
    || history.pointer_version !== pointerVersion
    || history.current_edition_id !== currentEditionId
    || history.working_copy_draft_version !== workingCopyVersion
    || history.working_copy_content_hash !== workingCopyHash
  ) {
    return fail("context.edition_history", "does not match the outer document state");
  }
  const current = currentEditionId === null
    ? undefined
    : history.editions.find((entry) => entry.edition_id === currentEditionId);
  if (current !== undefined) {
    const expectedStatus = current.source_content_hash === workingCopyHash
      ? "current"
      : "working_copy_diverged";
    if (current.source_status !== expectedStatus) {
      return fail("context.edition_history.current.source_status", "does not match working copy");
    }
  }
  const active = activeEditionId === null
    ? undefined
    : history.editions.find((entry) => entry.edition_id === activeEditionId);
  if (activeEditionId !== null && active === undefined) {
    return fail("context.active_edition_id", "is outside edition_history");
  }
  const activeIsCurrent = boolean(item.active_is_current, "context.active_is_current");
  if (activeIsCurrent !== (activeEditionId !== null && activeEditionId === currentEditionId)) {
    return fail("context.active_is_current", "does not match active/current Edition identities");
  }
  const sourceSnapshot = item.source_snapshot === null
    ? null
    : parseSourceSnapshot(item.source_snapshot);
  const sourceMatches = active !== undefined && active.source_content_hash === workingCopyHash;
  if (
    (active === undefined && sourceSnapshot !== null)
    || (active !== undefined && (
      sourceSnapshot === null
      || sourceSnapshot.revision_id !== active.source_revision_id
      || sourceSnapshot.content_hash !== active.source_content_hash
      || sourceSnapshot.matches_working_copy !== sourceMatches
    ))
  ) {
    return fail("context.source_snapshot", "does not match the active Edition source");
  }
  const [expectedCompatibility, expectedNotice] = contextCompatibility(
    active,
    currentEditionId,
    workingCopyHash,
  );
  const compatibility = oneOf(
    item.compatibility,
    COMPATIBILITIES,
    "context.compatibility",
  );
  const sourceNotice = oneOf(
    item.source_notice_code,
    SOURCE_NOTICES,
    "context.source_notice_code",
  );
  if (compatibility !== expectedCompatibility || sourceNotice !== expectedNotice) {
    return fail("context.compatibility", "does not match the active Edition");
  }
  const expectedTimeline: NarrationEditorTimelineMode = active === undefined
    ? "none"
    : sourceMatches
      ? "exact_working_copy"
      : "immutable_edition_only";
  const timeline = oneOf(
    item.editor_timeline_mode,
    TIMELINE_MODES,
    "context.editor_timeline_mode",
  );
  if (timeline !== expectedTimeline) {
    return fail("context.editor_timeline_mode", "does not match the active Edition source");
  }
  const oldDraftRequired = boolean(
    item.old_draft_subtitle_required,
    "context.old_draft_subtitle_required",
  );
  if (oldDraftRequired !== (active !== undefined && !sourceMatches)) {
    return fail("context.old_draft_subtitle_required", "does not match source divergence");
  }
  const explicitUpdateRequired = boolean(
    item.explicit_update_required,
    "context.explicit_update_required",
  );
  if (
    explicitUpdateRequired
    !== (current !== undefined && current.source_content_hash !== workingCopyHash)
  ) {
    return fail("context.explicit_update_required", "does not match current Edition source");
  }
  const canRequestUpdate = boolean(item.can_request_update, "context.can_request_update");
  if (canRequestUpdate !== (current !== undefined)) {
    return fail("context.can_request_update", "does not match current Edition availability");
  }
  const available = uuidArray(
    item.available_current_source_edition_ids,
    "context.available_current_source_edition_ids",
  );
  const expectedAvailable = history.editions
    .filter((entry) => (
      entry.edition_id !== currentEditionId
      && entry.source_content_hash === workingCopyHash
      && entry.playable
      && entry.switch_allowed
    ))
    .map((entry) => entry.edition_id);
  if (!equalOrdered(available, expectedAvailable)) {
    return fail(
      "context.available_current_source_edition_ids",
      "does not match playable current-source history",
    );
  }
  const currentScriptVersionId = nullableUuid(
    item.current_script_version_id,
    "context.current_script_version_id",
  );
  if (current !== undefined && currentScriptVersionId === null) {
    return fail("context.current_script_version_id", "is required for a current Edition");
  }
  return Object.freeze({
    contract_version: DOCUMENT_NARRATION_CONTEXT_VERSION,
    document_id: documentId,
    novel_id: uuid(item.novel_id, "context.novel_id"),
    pointer_version: pointerVersion,
    current_script_version_id: currentScriptVersionId,
    current_edition_id: currentEditionId,
    active_edition_id: activeEditionId,
    active_is_current: activeIsCurrent,
    working_copy_draft_version: workingCopyVersion,
    working_copy_content_hash: workingCopyHash,
    source_snapshot: sourceSnapshot,
    compatibility,
    source_notice_code: sourceNotice,
    editor_timeline_mode: timeline,
    old_draft_subtitle_required: oldDraftRequired,
    explicit_update_required: explicitUpdateRequired,
    can_request_update: canRequestUpdate,
    available_current_source_edition_ids: available,
    edition_history: history,
  });
}


export function parseSwitchNarrationEditionRequest(value: unknown): SwitchNarrationEditionRequest {
  const item = exactRecord(value, "switch_request", SWITCH_REQUEST_KEYS);
  const mode = oneOf(item.switch_mode, SWITCH_MODES, "switch_request.switch_mode");
  const startSegmentId = nullableUuid(item.start_segment_id, "switch_request.start_segment_id");
  if (item.confirmed !== true) {
    return fail("switch_request.confirmed", "must be exactly true");
  }
  if (mode === "next_playback" && startSegmentId !== null) {
    return fail("switch_request.start_segment_id", "is invalid for next_playback");
  }
  return Object.freeze({
    target_edition_id: uuid(item.target_edition_id, "switch_request.target_edition_id"),
    expected_version: integer(
      item.expected_version,
      "switch_request.expected_version",
      0,
      Number.MAX_SAFE_INTEGER - 1,
    ),
    switch_mode: mode,
    start_segment_id: startSegmentId,
    playback_rate_millis: integer(
      item.playback_rate_millis,
      "switch_request.playback_rate_millis",
      250,
      4000,
    ),
    confirmed: true,
  });
}


export function parseSwitchNarrationEditionResponse(
  value: unknown,
): SwitchNarrationEditionResponse {
  const item = exactRecord(value, "switch_response", SWITCH_RESPONSE_KEYS);
  if (item.contract_version !== DOCUMENT_NARRATION_CONTEXT_VERSION) {
    return fail("switch_response.contract_version", "is unsupported");
  }
  return Object.freeze({
    contract_version: DOCUMENT_NARRATION_CONTEXT_VERSION,
    document_id: uuid(item.document_id, "switch_response.document_id"),
    current_edition_id: uuid(
      item.current_edition_id,
      "switch_response.current_edition_id",
    ),
    pointer_version: integer(item.pointer_version, "switch_response.pointer_version", 1),
    switch_mode: oneOf(item.switch_mode, SWITCH_MODES, "switch_response.switch_mode"),
    start_segment_id: nullableUuid(
      item.start_segment_id,
      "switch_response.start_segment_id",
    ),
    manifest_revision: integer(
      item.manifest_revision,
      "switch_response.manifest_revision",
      1,
    ),
    playback_progress_id: nullableUuid(
      item.playback_progress_id,
      "switch_response.playback_progress_id",
    ),
  });
}


function parseFailedNarrationSegmentRetryItem(
  value: unknown,
  index: number,
): FailedNarrationSegmentRetryItem {
  const path = `failed_segments.items[${index}]`;
  const item = exactRecord(value, path, FAILED_SEGMENT_ITEM_KEYS);
  const segmentId = uuid(item.segment_id, `${path}.segment_id`);
  const retryable = boolean(item.retryable, `${path}.retryable`);
  const retryReason = nullableStableCode(
    item.retry_reason_code,
    `${path}.retry_reason_code`,
  );
  const fanout = boundedUuidArray(
    item.fanout_segment_ids,
    `${path}.fanout_segment_ids`,
    1,
  );
  if (!fanout.includes(segmentId)) {
    return fail(`${path}.fanout_segment_ids`, "must contain segment_id");
  }
  if ((retryable && retryReason !== null) || (!retryable && retryReason === null)) {
    return fail(`${path}.retry_reason_code`, "does not match retryable");
  }
  return Object.freeze({
    segment_id: segmentId,
    ordinal: integer(item.ordinal, `${path}.ordinal`, 0),
    failure_code: stableCode(item.failure_code, `${path}.failure_code`),
    retryable,
    retry_reason_code: retryReason,
    job_id: uuid(item.job_id, `${path}.job_id`),
    fanout_segment_ids: fanout,
  });
}


export function parseFailedNarrationSegmentsProjection(
  value: unknown,
): FailedNarrationSegmentsProjection {
  const item = exactRecord(value, "failed_segments", FAILED_SEGMENTS_PROJECTION_KEYS);
  if (item.contract_version !== FAILED_SEGMENT_RETRY_CONTRACT_VERSION) {
    return fail("failed_segments.contract_version", "is unsupported");
  }
  if (!Array.isArray(item.items)) {
    return fail("failed_segments.items", "must be an array");
  }
  const items = item.items.map(parseFailedNarrationSegmentRetryItem);
  if (
    new Set(items.map((entry) => entry.segment_id)).size !== items.length
    || new Set(items.map((entry) => entry.ordinal)).size !== items.length
  ) {
    return fail("failed_segments.items", "must have unique segment_id and ordinal values");
  }
  return Object.freeze({
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: uuid(item.edition_id, "failed_segments.edition_id"),
    request_id: uuid(item.request_id, "failed_segments.request_id"),
    request_version: integer(item.request_version, "failed_segments.request_version", 1),
    manifest_revision: nullableInteger(
      item.manifest_revision,
      "failed_segments.manifest_revision",
      1,
    ),
    request_state: oneOf(
      item.request_state,
      WORKFLOW_STATES,
      "failed_segments.request_state",
    ),
    edition_state: oneOf(
      item.edition_state,
      EDITION_STATES,
      "failed_segments.edition_state",
    ),
    items: Object.freeze(items),
  });
}


export function parseRetryFailedNarrationSegmentsRequest(
  value: unknown,
): RetryFailedNarrationSegmentsRequest {
  const item = exactRecord(value, "retry_request", RETRY_FAILED_SEGMENTS_REQUEST_KEYS);
  return Object.freeze({
    segment_ids: boundedUuidArray(item.segment_ids, "retry_request.segment_ids", 1, 100),
    expected_request_version: integer(
      item.expected_request_version,
      "retry_request.expected_request_version",
      1,
    ),
    expected_manifest_revision: nullableInteger(
      item.expected_manifest_revision,
      "retry_request.expected_manifest_revision",
      1,
    ),
  });
}


function parseFailedNarrationSegmentRetryCommand(
  value: unknown,
  index: number,
): FailedNarrationSegmentRetryCommand {
  const path = `retry_response.commands[${index}]`;
  const item = exactRecord(value, path, FAILED_SEGMENT_COMMAND_KEYS);
  return Object.freeze({
    command_id: uuid(item.command_id, `${path}.command_id`),
    job_id: uuid(item.job_id, `${path}.job_id`),
    affected_segment_ids: boundedUuidArray(
      item.affected_segment_ids,
      `${path}.affected_segment_ids`,
      1,
    ),
  });
}


export function parseRetryFailedNarrationSegmentsResponse(
  value: unknown,
): RetryFailedNarrationSegmentsResponse {
  const item = exactRecord(value, "retry_response", RETRY_FAILED_SEGMENTS_RESPONSE_KEYS);
  if (item.contract_version !== FAILED_SEGMENT_RETRY_CONTRACT_VERSION) {
    return fail("retry_response.contract_version", "is unsupported");
  }
  const accepted = boundedUuidArray(
    item.accepted_segment_ids,
    "retry_response.accepted_segment_ids",
    1,
    100,
  );
  const affected = boundedUuidArray(
    item.affected_segment_ids,
    "retry_response.affected_segment_ids",
    1,
  );
  if (!Array.isArray(item.commands) || item.commands.length === 0) {
    return fail("retry_response.commands", "must be a non-empty array");
  }
  const commands = item.commands.map(parseFailedNarrationSegmentRetryCommand);
  if (
    new Set(commands.map((command) => command.command_id)).size !== commands.length
    || new Set(commands.map((command) => command.job_id)).size !== commands.length
  ) {
    return fail("retry_response.commands", "must have unique command_id and job_id values");
  }
  const affectedSet = new Set(affected);
  if (!accepted.every((segmentId) => affectedSet.has(segmentId))) {
    return fail("retry_response.accepted_segment_ids", "must be a subset of affected_segment_ids");
  }
  const commandAffected = new Set(commands.flatMap((command) => command.affected_segment_ids));
  if (
    commandAffected.size !== affectedSet.size
    || [...commandAffected].some((segmentId) => !affectedSet.has(segmentId))
  ) {
    return fail("retry_response.commands", "must cover exactly affected_segment_ids");
  }
  return Object.freeze({
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: uuid(item.edition_id, "retry_response.edition_id"),
    request_id: uuid(item.request_id, "retry_response.request_id"),
    accepted_segment_ids: accepted,
    affected_segment_ids: affected,
    commands: Object.freeze(commands),
    request_version: integer(item.request_version, "retry_response.request_version", 1),
    request_state: oneOf(
      item.request_state,
      WORKFLOW_STATES,
      "retry_response.request_state",
    ),
    edition_state: oneOf(
      item.edition_state,
      EDITION_STATES,
      "retry_response.edition_state",
    ),
    replayed: boolean(item.replayed, "retry_response.replayed"),
  });
}


export function parseNarrationProductionApiErrorDetail(
  value: unknown,
): NarrationProductionApiErrorDetail {
  const item = exactRecord(value, "error", ERROR_KEYS);
  if (item.contract_version !== NARRATION_PRODUCTION_API_VERSION) {
    return fail("error.contract_version", "is unsupported");
  }
  return Object.freeze({
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    code: oneOf(item.code, PRODUCTION_ERROR_CODES, "error.code"),
    message: text(item.message, "error.message", 1, 400),
    retryable: boolean(item.retryable, "error.retryable"),
    field: nullableText(item.field, "error.field", 160),
    current_version: nullableInteger(item.current_version, "error.current_version", 1),
  });
}
