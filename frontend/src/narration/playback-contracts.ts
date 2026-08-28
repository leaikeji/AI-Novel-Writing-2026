export const NARRATION_PRODUCTION_API_VERSION = "narration-production-api/1" as const;
export const MANIFEST_SCHEMA_VERSION = "narration-manifest/2.0" as const;

export type SegmentRenderStatus =
  | "pending"
  | "queued"
  | "rendering"
  | "ready"
  | "failed"
  | "cancelled";

export type ManifestStatus =
  | "pending"
  | "partial_ready"
  | "ready"
  | "failed"
  | "cancelled";

export interface ManifestBufferPolicy {
  readonly version: string;
  readonly minimum_segments: number;
  readonly minimum_duration_ms: number;
  readonly target_segments: number;
  readonly chapter_end_exception: boolean;
}

export interface ManifestAudioSource {
  readonly url: string;
  readonly actual_sha256: string;
  readonly duration_ms: number;
  readonly sample_rate: number;
  readonly channels: number;
  readonly etag: string;
}

export interface ManifestFailure {
  readonly code: string;
  readonly retryable: boolean;
  readonly message: string;
}

export interface ManifestSegmentV2 {
  readonly segment_id: string;
  readonly ordinal: number;
  readonly paragraph_ordinal: number;
  readonly source_block_key: string;
  readonly source_start_utf16: number;
  readonly source_end_utf16: number;
  readonly gap_after_ms: number;
  readonly render_status: SegmentRenderStatus;
  readonly audio: ManifestAudioSource | null;
  readonly failure: ManifestFailure | null;
}

export interface ReadyRange {
  readonly start_ordinal: number;
  readonly end_ordinal_exclusive: number;
  readonly segment_count: number;
  readonly duration_ms: number;
  readonly last_playable_start_ordinal: number;
}

export interface NarrationManifestV2 {
  readonly schema_version: typeof MANIFEST_SCHEMA_VERSION;
  readonly edition_id: string;
  readonly chapter_id: string;
  readonly source_revision_id: string;
  readonly source_sha256: string;
  readonly buffer_policy: ManifestBufferPolicy;
  readonly manifest_revision: number;
  readonly etag: string;
  readonly generated_at: string;
  readonly status: ManifestStatus;
  readonly ready_prefix_count: number;
  readonly default_start_ready: boolean;
  readonly last_playable_start_ordinal: number | null;
  readonly ready_ranges: readonly ReadyRange[];
  readonly segments: readonly ManifestSegmentV2[];
}

export interface ManifestProblem {
  readonly path: string;
  readonly message: string;
}

export class PlaybackContractError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "PlaybackContractError";
    this.path = path;
  }
}

export class ManifestValidationError extends Error {
  readonly problems: readonly ManifestProblem[];

  constructor(problems: readonly ManifestProblem[]) {
    super(`invalid Narration Manifest 2.0 (${problems.length} problem(s))`);
    this.name = "ManifestValidationError";
    this.problems = problems;
  }
}

export type PrepareRangeReason = "user_seek" | "resume";

export interface PrepareRangeRequest {
  readonly start_segment_id: string;
  readonly reason: PrepareRangeReason;
  readonly expected_manifest_revision: number;
}

export interface PrepareRangeResponse {
  readonly contract_version: typeof NARRATION_PRODUCTION_API_VERSION;
  readonly edition_id: string;
  readonly start_segment_id: string;
  readonly start_ordinal: number;
  readonly state: "ready" | "preparing" | "failed";
  readonly manifest_revision: number;
  readonly manifest_etag: string;
  readonly ready_range: ReadyRange | null;
  readonly promoted_job_ids: readonly string[];
}

export interface PlaybackApiErrorDetail {
  readonly contract_version: typeof NARRATION_PRODUCTION_API_VERSION;
  readonly code:
    | "REQUEST_VALIDATION_FAILED"
    | "RESPONSE_CONTRACT_VIOLATION"
    | "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED"
    | "STORAGE_UNAVAILABLE"
    | "RESOURCE_NOT_FOUND"
    | "SCOPE_VIOLATION"
    | "VERSION_CONFLICT"
    | "MANIFEST_REVISION_CONFLICT"
    | "INVALID_STATE"
    | "IDEMPOTENCY_CONFLICT"
    | "STALE_INPUT"
    | "VOICE_RIGHTS_UNAVAILABLE"
    | "VALIDATION_FAILED";
  readonly message: string;
  readonly retryable: boolean;
  readonly field: string | null;
  readonly current_version: number | null;
}

type JsonRecord = Record<string, unknown>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const ETAG_PATTERN = /^"[a-f0-9]{64}"$/u;
const PLAYBACK_URL_PATTERN = /^\/api\/ai-novel-world-2026\/media-assets\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/content$/iu;

const MANIFEST_KEYS = [
  "schema_version", "edition_id", "chapter_id", "source_revision_id",
  "source_sha256", "buffer_policy", "manifest_revision", "etag", "generated_at",
  "status", "ready_prefix_count", "default_start_ready",
  "last_playable_start_ordinal", "ready_ranges", "segments",
] as const;
const POLICY_KEYS = [
  "version", "minimum_segments", "minimum_duration_ms", "target_segments",
  "chapter_end_exception",
] as const;
const RANGE_KEYS = [
  "start_ordinal", "end_ordinal_exclusive", "segment_count", "duration_ms",
  "last_playable_start_ordinal",
] as const;
const SEGMENT_KEYS = [
  "segment_id", "ordinal", "paragraph_ordinal", "source_block_key",
  "source_start_utf16", "source_end_utf16", "gap_after_ms", "render_status",
  "audio", "failure",
] as const;
const AUDIO_KEYS = [
  "url", "actual_sha256", "duration_ms", "sample_rate", "channels", "etag",
] as const;
const FAILURE_KEYS = ["code", "retryable", "message"] as const;

const RENDER_STATES = new Set<SegmentRenderStatus>([
  "pending", "queued", "rendering", "ready", "failed", "cancelled",
]);
const MANIFEST_STATES = new Set<ManifestStatus>([
  "pending", "partial_ready", "ready", "failed", "cancelled",
]);
const API_ERROR_CODES = new Set<PlaybackApiErrorDetail["code"]>([
  "REQUEST_VALIDATION_FAILED", "RESPONSE_CONTRACT_VIOLATION",
  "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED", "STORAGE_UNAVAILABLE",
  "RESOURCE_NOT_FOUND", "SCOPE_VIOLATION", "VERSION_CONFLICT", "INVALID_STATE",
  "MANIFEST_REVISION_CONFLICT",
  "IDEMPOTENCY_CONFLICT", "STALE_INPUT", "VOICE_RIGHTS_UNAVAILABLE",
  "VALIDATION_FAILED",
]);

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= minimum;
}

function exactObject(
  value: unknown,
  path: string,
  keys: readonly string[],
  problems: ManifestProblem[],
): JsonRecord | undefined {
  if (!isRecord(value)) {
    problems.push({ path, message: "must be an object" });
    return undefined;
  }
  const allowed = new Set(keys);
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) problems.push({ path: `${path}.${key}`, message: "is required" });
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) problems.push({ path: `${path}.${key}`, message: "is not allowed" });
  }
  return value;
}

function checkString(
  value: unknown,
  path: string,
  problems: ManifestProblem[],
  pattern?: RegExp,
): value is string {
  if (typeof value !== "string" || value.length === 0 || (pattern && !pattern.test(value))) {
    problems.push({ path, message: "has an invalid string value" });
    return false;
  }
  return true;
}

function checkInteger(value: unknown, minimum: number, path: string, problems: ManifestProblem[]): value is number {
  if (!isInteger(value, minimum)) {
    problems.push({ path, message: `must be a safe integer >= ${minimum}` });
    return false;
  }
  return true;
}

function validatePolicy(value: unknown, problems: ManifestProblem[]): void {
  const policy = exactObject(value, "buffer_policy", POLICY_KEYS, problems);
  if (!policy) return;
  checkString(policy.version, "buffer_policy.version", problems);
  checkInteger(policy.minimum_segments, 1, "buffer_policy.minimum_segments", problems);
  checkInteger(policy.minimum_duration_ms, 0, "buffer_policy.minimum_duration_ms", problems);
  checkInteger(policy.target_segments, 1, "buffer_policy.target_segments", problems);
  if (typeof policy.chapter_end_exception !== "boolean") {
    problems.push({ path: "buffer_policy.chapter_end_exception", message: "must be a boolean" });
  }
  if (
    isInteger(policy.minimum_segments, 1)
    && isInteger(policy.target_segments, 1)
    && policy.target_segments < policy.minimum_segments
  ) {
    problems.push({ path: "buffer_policy.target_segments", message: "must cover minimum_segments" });
  }
}

function validateReadyRange(value: unknown, index: number, problems: ManifestProblem[]): void {
  const path = `ready_ranges[${index}]`;
  const range = exactObject(value, path, RANGE_KEYS, problems);
  if (!range) return;
  checkInteger(range.start_ordinal, 0, `${path}.start_ordinal`, problems);
  checkInteger(range.end_ordinal_exclusive, 1, `${path}.end_ordinal_exclusive`, problems);
  checkInteger(range.segment_count, 1, `${path}.segment_count`, problems);
  checkInteger(range.duration_ms, 1, `${path}.duration_ms`, problems);
  checkInteger(range.last_playable_start_ordinal, 0, `${path}.last_playable_start_ordinal`, problems);
  if (isInteger(range.start_ordinal, 0) && isInteger(range.end_ordinal_exclusive, 1)) {
    if (range.end_ordinal_exclusive <= range.start_ordinal) {
      problems.push({ path: `${path}.end_ordinal_exclusive`, message: "must exceed start_ordinal" });
    }
    if (isInteger(range.segment_count, 1) && range.segment_count !== range.end_ordinal_exclusive - range.start_ordinal) {
      problems.push({ path: `${path}.segment_count`, message: "does not match range bounds" });
    }
    if (
      isInteger(range.last_playable_start_ordinal, 0)
      && (range.last_playable_start_ordinal < range.start_ordinal
        || range.last_playable_start_ordinal >= range.end_ordinal_exclusive)
    ) {
      problems.push({ path: `${path}.last_playable_start_ordinal`, message: "must fall inside range" });
    }
  }
}

function validateAudio(value: unknown, path: string, problems: ManifestProblem[]): void {
  const audio = exactObject(value, path, AUDIO_KEYS, problems);
  if (!audio) return;
  if (!checkString(audio.url, `${path}.url`, problems, PLAYBACK_URL_PATTERN)) {
    // checkString recorded the problem.
  } else if (audio.url.includes("?") || audio.url.includes("#") || audio.url.includes("%") || audio.url.includes("\\")) {
    problems.push({ path: `${path}.url`, message: "must not contain query, fragment, escaping or traversal" });
  }
  checkString(audio.actual_sha256, `${path}.actual_sha256`, problems, SHA256_PATTERN);
  checkInteger(audio.duration_ms, 1, `${path}.duration_ms`, problems);
  checkInteger(audio.sample_rate, 1, `${path}.sample_rate`, problems);
  checkInteger(audio.channels, 1, `${path}.channels`, problems);
  if (checkString(audio.etag, `${path}.etag`, problems, ETAG_PATTERN)
    && typeof audio.actual_sha256 === "string"
    && audio.etag !== `"${audio.actual_sha256}"`) {
    problems.push({ path: `${path}.etag`, message: "must identify actual_sha256" });
  }
}

function validateFailure(value: unknown, path: string, problems: ManifestProblem[]): void {
  const failure = exactObject(value, path, FAILURE_KEYS, problems);
  if (!failure) return;
  if (typeof failure.code !== "string" || !/^[A-Z][A-Z0-9_]{0,95}$/u.test(failure.code)) {
    problems.push({ path: `${path}.code`, message: "must be a bounded public error code" });
  }
  if (typeof failure.retryable !== "boolean") problems.push({ path: `${path}.retryable`, message: "must be a boolean" });
  if (typeof failure.message !== "string" || failure.message.length === 0 || failure.message.length > 256) {
    problems.push({ path: `${path}.message`, message: "must be 1-256 characters" });
  }
}

function validateSegment(value: unknown, index: number, problems: ManifestProblem[]): void {
  const path = `segments[${index}]`;
  const segment = exactObject(value, path, SEGMENT_KEYS, problems);
  if (!segment) return;
  checkString(segment.segment_id, `${path}.segment_id`, problems, UUID_PATTERN);
  if (checkInteger(segment.ordinal, 0, `${path}.ordinal`, problems) && segment.ordinal !== index) {
    problems.push({ path: `${path}.ordinal`, message: "must be contiguous and zero-based" });
  }
  checkInteger(segment.paragraph_ordinal, 0, `${path}.paragraph_ordinal`, problems);
  checkString(segment.source_block_key, `${path}.source_block_key`, problems);
  checkInteger(segment.source_start_utf16, 0, `${path}.source_start_utf16`, problems);
  checkInteger(segment.source_end_utf16, 1, `${path}.source_end_utf16`, problems);
  if (isInteger(segment.source_start_utf16, 0) && isInteger(segment.source_end_utf16, 1)
    && segment.source_end_utf16 <= segment.source_start_utf16) {
    problems.push({ path: `${path}.source_end_utf16`, message: "must exceed source_start_utf16" });
  }
  checkInteger(segment.gap_after_ms, 0, `${path}.gap_after_ms`, problems);
  if (typeof segment.render_status !== "string" || !RENDER_STATES.has(segment.render_status as SegmentRenderStatus)) {
    problems.push({ path: `${path}.render_status`, message: "is unsupported" });
    return;
  }
  if (segment.render_status === "ready") {
    validateAudio(segment.audio, `${path}.audio`, problems);
    if (segment.failure !== null) problems.push({ path: `${path}.failure`, message: "ready requires null" });
  } else if (segment.render_status === "failed") {
    if (segment.audio !== null) problems.push({ path: `${path}.audio`, message: "failed requires null" });
    validateFailure(segment.failure, `${path}.failure`, problems);
  } else if (segment.audio !== null || segment.failure !== null) {
    problems.push({ path, message: "non-ready/non-failed segment cannot expose audio or failure" });
  }
}

function rangeDuration(segments: readonly ManifestSegmentV2[], start: number, end: number): number {
  let duration = 0;
  for (let index = start; index < end; index += 1) {
    duration += segments[index].audio?.duration_ms ?? 0;
    if (index + 1 < end) duration += segments[index].gap_after_ms;
  }
  return duration;
}

export function deriveReadyPrefixCount(segments: readonly ManifestSegmentV2[]): number {
  let count = 0;
  while (segments[count]?.render_status === "ready" && segments[count].audio) count += 1;
  return count;
}

export function deriveManifestStatus(segments: readonly ManifestSegmentV2[]): ManifestStatus {
  if (segments.every((segment) => segment.render_status === "ready")) return "ready";
  if (segments.some((segment) => segment.render_status === "ready")) return "partial_ready";
  if (segments.some((segment) => ["pending", "queued", "rendering"].includes(segment.render_status))) return "pending";
  if (segments.some((segment) => segment.render_status === "failed")) return "failed";
  return "cancelled";
}

export function deriveReadyRanges(
  segments: readonly ManifestSegmentV2[],
  policy: ManifestBufferPolicy,
): ReadyRange[] {
  const ranges: ReadyRange[] = [];
  let start = 0;
  while (start < segments.length) {
    if (segments[start].render_status !== "ready" || !segments[start].audio) {
      start += 1;
      continue;
    }
    let end = start + 1;
    while (end < segments.length && segments[end].render_status === "ready" && segments[end].audio) end += 1;
    let lastPlayable: number | null = null;
    for (let candidate = start; candidate < end; candidate += 1) {
      const chapterEnd = end === segments.length && policy.chapter_end_exception;
      const threshold = end - candidate >= policy.minimum_segments
        && rangeDuration(segments, candidate, end) >= policy.minimum_duration_ms;
      if (chapterEnd || threshold) lastPlayable = candidate;
    }
    if (lastPlayable !== null) {
      ranges.push({
        start_ordinal: start,
        end_ordinal_exclusive: end,
        segment_count: end - start,
        duration_ms: rangeDuration(segments, start, end),
        last_playable_start_ordinal: lastPlayable,
      });
    }
    start = end;
  }
  return ranges;
}

function derivable(root: JsonRecord): root is JsonRecord & {
  buffer_policy: ManifestBufferPolicy;
  segments: ManifestSegmentV2[];
  ready_ranges: ReadyRange[];
} {
  return isRecord(root.buffer_policy)
    && Array.isArray(root.segments)
    && root.segments.every((item) => isRecord(item)
      && typeof item.render_status === "string"
      && RENDER_STATES.has(item.render_status as SegmentRenderStatus)
      && isInteger(item.gap_after_ms, 0)
      && (item.render_status !== "ready" || (isRecord(item.audio) && isInteger(item.audio.duration_ms, 1))))
    && Array.isArray(root.ready_ranges);
}

export function validateManifest(value: unknown): ManifestProblem[] {
  const problems: ManifestProblem[] = [];
  const root = exactObject(value, "$", MANIFEST_KEYS, problems);
  if (!root) return problems;
  if (root.schema_version !== MANIFEST_SCHEMA_VERSION) problems.push({ path: "schema_version", message: "is unsupported" });
  checkString(root.edition_id, "edition_id", problems, UUID_PATTERN);
  checkString(root.chapter_id, "chapter_id", problems, UUID_PATTERN);
  checkString(root.source_revision_id, "source_revision_id", problems, UUID_PATTERN);
  checkString(root.source_sha256, "source_sha256", problems, SHA256_PATTERN);
  validatePolicy(root.buffer_policy, problems);
  checkInteger(root.manifest_revision, 1, "manifest_revision", problems);
  checkString(root.etag, "etag", problems, ETAG_PATTERN);
  if (typeof root.generated_at !== "string" || Number.isNaN(Date.parse(root.generated_at)) || !/[zZ]|[+-]\d\d:\d\d$/u.test(root.generated_at)) {
    problems.push({ path: "generated_at", message: "must be an RFC-3339 date-time with offset" });
  }
  if (typeof root.status !== "string" || !MANIFEST_STATES.has(root.status as ManifestStatus)) problems.push({ path: "status", message: "is unsupported" });
  checkInteger(root.ready_prefix_count, 0, "ready_prefix_count", problems);
  if (typeof root.default_start_ready !== "boolean") problems.push({ path: "default_start_ready", message: "must be a boolean" });
  if (root.last_playable_start_ordinal !== null) checkInteger(root.last_playable_start_ordinal, 0, "last_playable_start_ordinal", problems);
  if (!Array.isArray(root.ready_ranges)) problems.push({ path: "ready_ranges", message: "must be an array" });
  else root.ready_ranges.forEach((item, index) => validateReadyRange(item, index, problems));
  if (!Array.isArray(root.segments) || root.segments.length === 0) problems.push({ path: "segments", message: "must be non-empty" });
  else {
    root.segments.forEach((item, index) => validateSegment(item, index, problems));
    const ids = new Set<string>();
    const ends = new Map<string, number>();
    root.segments.forEach((item, index) => {
      if (!isRecord(item)) return;
      if (typeof item.segment_id === "string") {
        if (ids.has(item.segment_id)) problems.push({ path: `segments[${index}].segment_id`, message: "must be unique" });
        ids.add(item.segment_id);
      }
      if (typeof item.source_block_key === "string" && isInteger(item.source_start_utf16, 0) && isInteger(item.source_end_utf16, 1)) {
        const previous = ends.get(item.source_block_key);
        if (previous !== undefined && item.source_start_utf16 < previous) problems.push({ path: `segments[${index}].source_start_utf16`, message: "overlaps an earlier source range" });
        ends.set(item.source_block_key, item.source_end_utf16);
      }
    });
  }
  if (derivable(root)) {
    const expectedRanges = deriveReadyRanges(root.segments, root.buffer_policy);
    if (
      root.ready_ranges.length !== expectedRanges.length
      || root.ready_ranges.some((candidate, index) => {
        if (!isRecord(candidate)) return true;
        const expected = expectedRanges[index];
        return expected === undefined || RANGE_KEYS.some((key) => candidate[key] !== expected[key]);
      })
    ) problems.push({ path: "ready_ranges", message: "drifts from segments and buffer_policy" });
    const expectedPrefix = deriveReadyPrefixCount(root.segments);
    if (root.ready_prefix_count !== expectedPrefix) problems.push({ path: "ready_prefix_count", message: "drifts from segments" });
    if (root.default_start_ready !== expectedRanges.some((range) => range.start_ordinal === 0)) problems.push({ path: "default_start_ready", message: "drifts from ready_ranges" });
    const expectedLast = expectedRanges.length ? Math.max(...expectedRanges.map((range) => range.last_playable_start_ordinal)) : null;
    if (root.last_playable_start_ordinal !== expectedLast) problems.push({ path: "last_playable_start_ordinal", message: "drifts from ready_ranges" });
    if (root.status !== deriveManifestStatus(root.segments)) problems.push({ path: "status", message: "drifts from segments" });
  }
  return problems;
}

function deepFreezeManifest(value: NarrationManifestV2): NarrationManifestV2 {
  Object.freeze(value.buffer_policy);
  value.ready_ranges.forEach(Object.freeze);
  value.segments.forEach((segment) => {
    if (segment.audio) Object.freeze(segment.audio);
    if (segment.failure) Object.freeze(segment.failure);
    Object.freeze(segment);
  });
  Object.freeze(value.ready_ranges);
  Object.freeze(value.segments);
  return Object.freeze(value);
}

export function parseManifest(value: unknown): NarrationManifestV2 {
  const problems = validateManifest(value);
  if (problems.length) throw new ManifestValidationError(problems);
  return deepFreezeManifest(value as NarrationManifestV2);
}

export const parseNarrationManifestV2 = parseManifest;

function requireExact(value: unknown, path: string, keys: readonly string[]): JsonRecord {
  if (!isRecord(value) || Object.keys(value).length !== keys.length || keys.some((key) => !Object.prototype.hasOwnProperty.call(value, key))) {
    throw new PlaybackContractError(path, "has unexpected or missing fields");
  }
  return value;
}

function requireUuid(value: unknown, path: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) throw new PlaybackContractError(path, "must be an RFC-4122 UUID");
  return value.toLowerCase();
}

function requireInteger(value: unknown, minimum: number, path: string): number {
  if (!isInteger(value, minimum)) throw new PlaybackContractError(path, `must be an integer >= ${minimum}`);
  return value;
}

function parseReadyRange(value: unknown, path: string): ReadyRange {
  const item = requireExact(value, path, RANGE_KEYS);
  const result: ReadyRange = {
    start_ordinal: requireInteger(item.start_ordinal, 0, `${path}.start_ordinal`),
    end_ordinal_exclusive: requireInteger(item.end_ordinal_exclusive, 1, `${path}.end_ordinal_exclusive`),
    segment_count: requireInteger(item.segment_count, 1, `${path}.segment_count`),
    duration_ms: requireInteger(item.duration_ms, 1, `${path}.duration_ms`),
    last_playable_start_ordinal: requireInteger(item.last_playable_start_ordinal, 0, `${path}.last_playable_start_ordinal`),
  };
  if (result.end_ordinal_exclusive <= result.start_ordinal
    || result.segment_count !== result.end_ordinal_exclusive - result.start_ordinal
    || result.last_playable_start_ordinal < result.start_ordinal
    || result.last_playable_start_ordinal >= result.end_ordinal_exclusive) {
    throw new PlaybackContractError(path, "has inconsistent bounds");
  }
  return Object.freeze(result);
}

export function parsePrepareRangeResponse(value: unknown): PrepareRangeResponse {
  const item = requireExact(value, "$", [
    "contract_version", "edition_id", "start_segment_id", "start_ordinal", "state",
    "manifest_revision", "manifest_etag", "ready_range", "promoted_job_ids",
  ]);
  if (item.contract_version !== NARRATION_PRODUCTION_API_VERSION) throw new PlaybackContractError("contract_version", "is unsupported");
  if (!new Set(["ready", "preparing", "failed"]).has(item.state as string)) throw new PlaybackContractError("state", "is unsupported");
  if (typeof item.manifest_etag !== "string" || !ETAG_PATTERN.test(item.manifest_etag)) throw new PlaybackContractError("manifest_etag", "must be a strong SHA-256 ETag");
  if (!Array.isArray(item.promoted_job_ids)) throw new PlaybackContractError("promoted_job_ids", "must be an array");
  const promoted = item.promoted_job_ids.map((id, index) => requireUuid(id, `promoted_job_ids[${index}]`));
  if (new Set(promoted).size !== promoted.length) throw new PlaybackContractError("promoted_job_ids", "must be unique");
  const result: PrepareRangeResponse = {
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    edition_id: requireUuid(item.edition_id, "edition_id"),
    start_segment_id: requireUuid(item.start_segment_id, "start_segment_id"),
    start_ordinal: requireInteger(item.start_ordinal, 0, "start_ordinal"),
    state: item.state as PrepareRangeResponse["state"],
    manifest_revision: requireInteger(item.manifest_revision, 1, "manifest_revision"),
    manifest_etag: item.manifest_etag,
    ready_range: item.ready_range === null ? null : parseReadyRange(item.ready_range, "ready_range"),
    promoted_job_ids: Object.freeze(promoted),
  };
  if ((result.state === "ready") !== (result.ready_range !== null)) throw new PlaybackContractError("ready_range", "must exist exactly when state=ready");
  if (result.ready_range && (result.start_ordinal < result.ready_range.start_ordinal
    || result.start_ordinal > result.ready_range.last_playable_start_ordinal)) {
    throw new PlaybackContractError("ready_range", "does not authorize start_ordinal");
  }
  if (result.state !== "preparing" && result.promoted_job_ids.length > 0) {
    throw new PlaybackContractError("promoted_job_ids", "are only valid while preparing");
  }
  return Object.freeze(result);
}

export function parsePlaybackApiErrorDetail(value: unknown): PlaybackApiErrorDetail {
  const item = requireExact(value, "$", [
    "contract_version", "code", "message", "retryable", "field", "current_version",
  ]);
  if (item.contract_version !== NARRATION_PRODUCTION_API_VERSION) throw new PlaybackContractError("contract_version", "is unsupported");
  if (typeof item.code !== "string" || !API_ERROR_CODES.has(item.code as PlaybackApiErrorDetail["code"])) throw new PlaybackContractError("code", "is unsupported");
  if (typeof item.message !== "string" || item.message.length === 0 || item.message.length > 400) throw new PlaybackContractError("message", "is invalid");
  if (typeof item.retryable !== "boolean") throw new PlaybackContractError("retryable", "must be a boolean");
  if (item.field !== null && (typeof item.field !== "string" || item.field.length === 0 || item.field.length > 160)) {
    throw new PlaybackContractError("field", "must be null or a bounded field path");
  }
  const currentVersion = item.current_version === null ? null : requireInteger(item.current_version, 1, "current_version");
  const normalizedCode = item.code === "VERSION_CONFLICT"
    ? "MANIFEST_REVISION_CONFLICT"
    : item.code as PlaybackApiErrorDetail["code"];
  return Object.freeze({
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    code: normalizedCode,
    message: item.message,
    retryable: item.retryable,
    field: item.field,
    current_version: currentVersion,
  });
}
