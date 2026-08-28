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
  version: string;
  minimum_segments: number;
  minimum_duration_ms: number;
  target_segments: number;
  chapter_end_exception: boolean;
}

export interface ManifestAudioSource {
  url: string;
  actual_sha256: string;
  duration_ms: number;
  sample_rate: number;
  channels: number;
  etag: string;
}

export interface ManifestFailure {
  code: string;
  retryable: boolean;
  message: string;
}

export interface ManifestSegmentV2 {
  segment_id: string;
  ordinal: number;
  paragraph_ordinal: number;
  source_block_key: string;
  source_start_utf16: number;
  source_end_utf16: number;
  gap_after_ms: number;
  render_status: SegmentRenderStatus;
  audio: ManifestAudioSource | null;
  failure: ManifestFailure | null;
}

export interface ReadyRange {
  start_ordinal: number;
  end_ordinal_exclusive: number;
  segment_count: number;
  duration_ms: number;
  last_playable_start_ordinal: number;
}

export interface NarrationManifestV2 {
  schema_version: typeof MANIFEST_SCHEMA_VERSION;
  edition_id: string;
  chapter_id: string;
  source_revision_id: string;
  source_sha256: string;
  buffer_policy: ManifestBufferPolicy;
  manifest_revision: number;
  etag: string;
  generated_at: string;
  status: ManifestStatus;
  ready_prefix_count: number;
  default_start_ready: boolean;
  last_playable_start_ordinal: number | null;
  ready_ranges: ReadyRange[];
  segments: ManifestSegmentV2[];
}

export interface ManifestProblem {
  path: string;
  message: string;
}

export class ManifestValidationError extends Error {
  readonly problems: ManifestProblem[];

  constructor(problems: ManifestProblem[]) {
    super(`invalid Narration Manifest 2.0 (${problems.length} problem${problems.length === 1 ? "" : "s"})`);
    this.name = "ManifestValidationError";
    this.problems = problems;
  }
}

export type PlaybackDecision =
  | {
      kind: "play";
      edition_id: string;
      manifest_revision: number;
      target_segment_id: string;
      ready_range: ReadyRange;
    }
  | {
      kind: "prepare_required";
      edition_id: string;
      manifest_revision: number;
      target_segment_id: string;
      requested_start_ordinal: number;
      requested_end_ordinal_exclusive: number;
      reason: "target_not_ready" | "ready_window_too_short";
    }
  | {
      kind: "blocked";
      edition_id: string;
      manifest_revision: number;
      target_segment_id: string;
      reason: "target_failed" | "gap_failed" | "target_cancelled";
      failed_segment_id: string;
      failure?: ManifestFailure;
    }
  | {
      kind: "missing";
      edition_id: string;
      manifest_revision: number;
      target_segment_id: string;
    };

type JsonRecord = Record<string, unknown>;

const MANIFEST_STATUSES = new Set<ManifestStatus>([
  "pending",
  "partial_ready",
  "ready",
  "failed",
  "cancelled",
]);

const RENDER_STATUSES = new Set<SegmentRenderStatus>([
  "pending",
  "queued",
  "rendering",
  "ready",
  "failed",
  "cancelled",
]);

const MANIFEST_KEYS = [
  "schema_version",
  "edition_id",
  "chapter_id",
  "source_revision_id",
  "source_sha256",
  "buffer_policy",
  "manifest_revision",
  "etag",
  "generated_at",
  "status",
  "ready_prefix_count",
  "default_start_ready",
  "last_playable_start_ordinal",
  "ready_ranges",
  "segments",
] as const;

const BUFFER_POLICY_KEYS = [
  "version",
  "minimum_segments",
  "minimum_duration_ms",
  "target_segments",
  "chapter_end_exception",
] as const;

const READY_RANGE_KEYS = [
  "start_ordinal",
  "end_ordinal_exclusive",
  "segment_count",
  "duration_ms",
  "last_playable_start_ordinal",
] as const;

const SEGMENT_KEYS = [
  "segment_id",
  "ordinal",
  "paragraph_ordinal",
  "source_block_key",
  "source_start_utf16",
  "source_end_utf16",
  "gap_after_ms",
  "render_status",
  "audio",
  "failure",
] as const;

const AUDIO_KEYS = [
  "url",
  "actual_sha256",
  "duration_ms",
  "sample_rate",
  "channels",
  "etag",
] as const;

const FAILURE_KEYS = ["code", "retryable", "message"] as const;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isSafeIntegerAtLeast(value: unknown, minimum: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= minimum;
}

function isPositiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);
}

function isStrongSha256Etag(value: unknown): value is string {
  return typeof value === "string" && /^"[a-f0-9]{64}"$/u.test(value);
}

function isControlledMediaUrl(value: unknown): value is string {
  if (
    typeof value !== "string"
    || !/^\/api\/ai-novel-world-2026\/[A-Za-z0-9_~-]+(?:\/[A-Za-z0-9_~-]+)*$/u.test(value)
    || value.includes("?")
    || value.includes("#")
    || value.includes("%")
    || value.includes("\\")
  ) {
    return false;
  }
  return value.split("/").every((part) => part !== "." && part !== "..");
}

function inspectObject(
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
    if (!Object.hasOwn(value, key)) {
      problems.push({ path: path === "$" ? key : `${path}.${key}`, message: "is required" });
    }
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      problems.push({ path: path === "$" ? key : `${path}.${key}`, message: "is not allowed by the public wire contract" });
    }
  }
  return value;
}

function expectNonEmptyString(record: JsonRecord, key: string, path: string, problems: ManifestProblem[]): void {
  if (!isNonEmptyString(record[key])) {
    problems.push({ path: `${path}.${key}`, message: "must be a non-empty string" });
  }
}

function expectSafeInteger(
  record: JsonRecord,
  key: string,
  minimum: number,
  path: string,
  problems: ManifestProblem[],
): void {
  if (!isSafeIntegerAtLeast(record[key], minimum)) {
    problems.push({ path: `${path}.${key}`, message: `must be a safe integer >= ${minimum}` });
  }
}

function validateBufferPolicy(value: unknown, problems: ManifestProblem[]): void {
  const path = "buffer_policy";
  const policy = inspectObject(value, path, BUFFER_POLICY_KEYS, problems);
  if (!policy) return;
  expectNonEmptyString(policy, "version", path, problems);
  expectSafeInteger(policy, "minimum_segments", 1, path, problems);
  expectSafeInteger(policy, "minimum_duration_ms", 0, path, problems);
  expectSafeInteger(policy, "target_segments", 1, path, problems);
  if (typeof policy.chapter_end_exception !== "boolean") {
    problems.push({ path: `${path}.chapter_end_exception`, message: "must be a boolean" });
  }
  if (
    isSafeIntegerAtLeast(policy.minimum_segments, 1)
    && isSafeIntegerAtLeast(policy.target_segments, 1)
    && policy.target_segments < policy.minimum_segments
  ) {
    problems.push({ path: `${path}.target_segments`, message: "must be >= minimum_segments" });
  }
}

function validateReadyRange(value: unknown, index: number, problems: ManifestProblem[]): void {
  const path = `ready_ranges[${index}]`;
  const range = inspectObject(value, path, READY_RANGE_KEYS, problems);
  if (!range) return;
  expectSafeInteger(range, "start_ordinal", 0, path, problems);
  expectSafeInteger(range, "end_ordinal_exclusive", 1, path, problems);
  expectSafeInteger(range, "segment_count", 1, path, problems);
  if (!isPositiveFinite(range.duration_ms)) {
    problems.push({ path: `${path}.duration_ms`, message: "must be a positive finite number" });
  }
  expectSafeInteger(range, "last_playable_start_ordinal", 0, path, problems);
  if (
    isSafeIntegerAtLeast(range.start_ordinal, 0)
    && isSafeIntegerAtLeast(range.end_ordinal_exclusive, 1)
    && range.end_ordinal_exclusive <= range.start_ordinal
  ) {
    problems.push({ path: `${path}.end_ordinal_exclusive`, message: "must be greater than start_ordinal" });
  }
  if (
    isSafeIntegerAtLeast(range.start_ordinal, 0)
    && isSafeIntegerAtLeast(range.end_ordinal_exclusive, 1)
    && isSafeIntegerAtLeast(range.segment_count, 1)
    && range.segment_count !== range.end_ordinal_exclusive - range.start_ordinal
  ) {
    problems.push({ path: `${path}.segment_count`, message: "must equal end_ordinal_exclusive - start_ordinal" });
  }
  if (
    isSafeIntegerAtLeast(range.start_ordinal, 0)
    && isSafeIntegerAtLeast(range.end_ordinal_exclusive, 1)
    && isSafeIntegerAtLeast(range.last_playable_start_ordinal, 0)
    && (
      range.last_playable_start_ordinal < range.start_ordinal
      || range.last_playable_start_ordinal >= range.end_ordinal_exclusive
    )
  ) {
    problems.push({ path: `${path}.last_playable_start_ordinal`, message: "must fall inside the ready range" });
  }
}

function validateAudio(value: unknown, path: string, problems: ManifestProblem[]): void {
  const audio = inspectObject(value, path, AUDIO_KEYS, problems);
  if (!audio) return;
  if (!isControlledMediaUrl(audio.url)) {
    problems.push({
      path: `${path}.url`,
      message: "must be a same-origin PawApp API path without query, fragment, credentials, token or traversal",
    });
  }
  if (!isSha256(audio.actual_sha256)) {
    problems.push({ path: `${path}.actual_sha256`, message: "must be a lowercase SHA-256 digest" });
  }
  if (!isPositiveFinite(audio.duration_ms)) {
    problems.push({ path: `${path}.duration_ms`, message: "must be a positive finite number" });
  }
  expectSafeInteger(audio, "sample_rate", 1, path, problems);
  expectSafeInteger(audio, "channels", 1, path, problems);
  if (!isStrongSha256Etag(audio.etag)) {
    problems.push({ path: `${path}.etag`, message: "must be a quoted strong SHA-256 ETag" });
  }
  if (
    isSha256(audio.actual_sha256)
    && isStrongSha256Etag(audio.etag)
    && audio.etag !== `"${audio.actual_sha256}"`
  ) {
    problems.push({ path: `${path}.etag`, message: "must identify the actual audio SHA-256" });
  }
}

function validateFailure(value: unknown, path: string, problems: ManifestProblem[]): void {
  const failure = inspectObject(value, path, FAILURE_KEYS, problems);
  if (!failure) return;
  if (typeof failure.code !== "string" || !/^[A-Z][A-Z0-9_]*$/u.test(failure.code) || failure.code.length > 96) {
    problems.push({ path: `${path}.code`, message: "must be a bounded public uppercase error code" });
  }
  if (typeof failure.retryable !== "boolean") {
    problems.push({ path: `${path}.retryable`, message: "must be a boolean" });
  }
  if (!isNonEmptyString(failure.message) || failure.message.length > 256) {
    problems.push({ path: `${path}.message`, message: "must be a non-empty redacted message <= 256 characters" });
  }
}

function validateSegment(value: unknown, index: number, problems: ManifestProblem[]): void {
  const path = `segments[${index}]`;
  const segment = inspectObject(value, path, SEGMENT_KEYS, problems);
  if (!segment) return;
  expectNonEmptyString(segment, "segment_id", path, problems);
  expectSafeInteger(segment, "ordinal", 0, path, problems);
  if (isSafeIntegerAtLeast(segment.ordinal, 0) && segment.ordinal !== index) {
    problems.push({ path: `${path}.ordinal`, message: "must be contiguous and zero-based" });
  }
  expectSafeInteger(segment, "paragraph_ordinal", 0, path, problems);
  expectNonEmptyString(segment, "source_block_key", path, problems);
  expectSafeInteger(segment, "source_start_utf16", 0, path, problems);
  expectSafeInteger(segment, "source_end_utf16", 1, path, problems);
  if (
    isSafeIntegerAtLeast(segment.source_start_utf16, 0)
    && isSafeIntegerAtLeast(segment.source_end_utf16, 1)
    && segment.source_end_utf16 <= segment.source_start_utf16
  ) {
    problems.push({ path: `${path}.source_end_utf16`, message: "must be greater than source_start_utf16" });
  }
  expectSafeInteger(segment, "gap_after_ms", 0, path, problems);
  if (typeof segment.render_status !== "string" || !RENDER_STATUSES.has(segment.render_status as SegmentRenderStatus)) {
    problems.push({ path: `${path}.render_status`, message: "is not a supported render status" });
    return;
  }

  if (segment.render_status === "ready") {
    if (segment.audio === null || segment.audio === undefined) {
      problems.push({ path: `${path}.audio`, message: "ready segments require audio" });
    } else {
      validateAudio(segment.audio, `${path}.audio`, problems);
    }
    if (segment.failure !== null) {
      problems.push({ path: `${path}.failure`, message: "ready segments require failure=null" });
    }
    return;
  }

  if (segment.audio !== null) {
    problems.push({ path: `${path}.audio`, message: "non-ready segments require audio=null" });
  }
  if (segment.render_status === "failed") {
    if (segment.failure === null || segment.failure === undefined) {
      problems.push({ path: `${path}.failure`, message: "failed segments require failure metadata" });
    } else {
      validateFailure(segment.failure, `${path}.failure`, problems);
    }
  } else if (segment.failure !== null) {
    problems.push({ path: `${path}.failure`, message: "only failed segments may expose failure metadata" });
  }
}

function rangeDurationMs(segments: ManifestSegmentV2[], start: number, endExclusive: number): number {
  let durationMs = 0;
  for (let index = start; index < endExclusive; index += 1) {
    durationMs += segments[index].audio?.duration_ms ?? 0;
    if (index + 1 < endExclusive) durationMs += segments[index].gap_after_ms;
  }
  return durationMs;
}

export function deriveReadyPrefixCount(segments: ManifestSegmentV2[]): number {
  let count = 0;
  while (segments[count]?.render_status === "ready" && segments[count]?.audio) count += 1;
  return count;
}

export function deriveManifestStatus(segments: ManifestSegmentV2[]): ManifestStatus {
  if (segments.every((segment) => segment.render_status === "ready")) return "ready";
  if (segments.some((segment) => segment.render_status === "ready")) return "partial_ready";
  if (segments.some((segment) => ["pending", "queued", "rendering"].includes(segment.render_status))) {
    return "pending";
  }
  if (segments.some((segment) => segment.render_status === "failed")) return "failed";
  return "cancelled";
}

export function deriveReadyRanges(
  segments: ManifestSegmentV2[],
  policy: ManifestBufferPolicy,
): ReadyRange[] {
  const ranges: ReadyRange[] = [];
  let start = 0;
  while (start < segments.length) {
    if (segments[start].render_status !== "ready" || !segments[start].audio) {
      start += 1;
      continue;
    }
    let endExclusive = start + 1;
    while (
      endExclusive < segments.length
      && segments[endExclusive].render_status === "ready"
      && segments[endExclusive].audio
    ) {
      endExclusive += 1;
    }

    let lastPlayableStart: number | null = null;
    const reachesChapterEnd = endExclusive === segments.length;
    for (let candidate = start; candidate < endExclusive; candidate += 1) {
      const chapterEndAllowed = reachesChapterEnd && policy.chapter_end_exception;
      const thresholdReached = (
        endExclusive - candidate >= policy.minimum_segments
        && rangeDurationMs(segments, candidate, endExclusive) >= policy.minimum_duration_ms
      );
      if (chapterEndAllowed || thresholdReached) lastPlayableStart = candidate;
    }

    if (lastPlayableStart !== null) {
      ranges.push({
        start_ordinal: start,
        end_ordinal_exclusive: endExclusive,
        segment_count: endExclusive - start,
        duration_ms: rangeDurationMs(segments, start, endExclusive),
        last_playable_start_ordinal: lastPlayableStart,
      });
    }
    start = endExclusive;
  }
  return ranges;
}

function compareReadyRanges(actual: ReadyRange[], expected: ReadyRange[], problems: ManifestProblem[]): void {
  if (actual.length !== expected.length) {
    problems.push({ path: "ready_ranges", message: `must contain exactly ${expected.length} server-derived range(s)` });
    return;
  }
  for (const [index, expectedRange] of expected.entries()) {
    const actualRange = actual[index];
    for (const key of READY_RANGE_KEYS) {
      if (actualRange[key] !== expectedRange[key]) {
        problems.push({ path: `ready_ranges[${index}].${key}`, message: "does not match segments and buffer_policy" });
      }
    }
  }
}

function validateDerivedFields(manifest: NarrationManifestV2, problems: ManifestProblem[]): void {
  const expectedRanges = deriveReadyRanges(manifest.segments, manifest.buffer_policy);
  compareReadyRanges(manifest.ready_ranges, expectedRanges, problems);

  const expectedPrefix = deriveReadyPrefixCount(manifest.segments);
  if (manifest.ready_prefix_count !== expectedPrefix) {
    problems.push({ path: "ready_prefix_count", message: "does not match the contiguous ready prefix from ordinal 0" });
  }
  const expectedDefaultReady = expectedRanges.some((range) => (
    range.start_ordinal === 0 && range.last_playable_start_ordinal >= 0
  ));
  if (manifest.default_start_ready !== expectedDefaultReady) {
    problems.push({ path: "default_start_ready", message: "does not match the server-derived ordinal 0 ready window" });
  }
  const expectedLastPlayable = expectedRanges.length > 0
    ? Math.max(...expectedRanges.map((range) => range.last_playable_start_ordinal))
    : null;
  if (manifest.last_playable_start_ordinal !== expectedLastPlayable) {
    problems.push({ path: "last_playable_start_ordinal", message: "does not match ready_ranges" });
  }
  const expectedStatus = deriveManifestStatus(manifest.segments);
  if (manifest.status !== expectedStatus) {
    problems.push({ path: "status", message: `must be ${expectedStatus} for the current segment states` });
  }
}

function hasDerivableShape(manifest: JsonRecord): boolean {
  if (!isRecord(manifest.buffer_policy) || !Array.isArray(manifest.segments) || !Array.isArray(manifest.ready_ranges)) {
    return false;
  }
  const policy = manifest.buffer_policy;
  if (
    !isSafeIntegerAtLeast(policy.minimum_segments, 1)
    || !isSafeIntegerAtLeast(policy.minimum_duration_ms, 0)
    || !isSafeIntegerAtLeast(policy.target_segments, 1)
    || typeof policy.chapter_end_exception !== "boolean"
  ) {
    return false;
  }
  if (!manifest.segments.every((candidate) => {
    if (!isRecord(candidate) || typeof candidate.render_status !== "string") return false;
    if (!RENDER_STATUSES.has(candidate.render_status as SegmentRenderStatus)) return false;
    if (!isSafeIntegerAtLeast(candidate.gap_after_ms, 0)) return false;
    if (candidate.render_status !== "ready") return true;
    return isRecord(candidate.audio) && isPositiveFinite(candidate.audio.duration_ms);
  })) {
    return false;
  }
  return manifest.ready_ranges.every((candidate) => (
    isRecord(candidate)
    && READY_RANGE_KEYS.every((key) => typeof candidate[key] === "number")
  ));
}

export function validateManifest(value: unknown): ManifestProblem[] {
  const problems: ManifestProblem[] = [];
  const manifest = inspectObject(value, "$", MANIFEST_KEYS, problems);
  if (!manifest) return problems;

  if (manifest.schema_version !== MANIFEST_SCHEMA_VERSION) {
    problems.push({ path: "schema_version", message: `must equal ${MANIFEST_SCHEMA_VERSION}` });
  }
  for (const key of ["edition_id", "chapter_id", "source_revision_id"] as const) {
    if (!isNonEmptyString(manifest[key])) {
      problems.push({ path: key, message: "must be a non-empty string" });
    }
  }
  if (!isSha256(manifest.source_sha256)) {
    problems.push({ path: "source_sha256", message: "must be a lowercase SHA-256 digest" });
  }
  validateBufferPolicy(manifest.buffer_policy, problems);
  if (!isSafeIntegerAtLeast(manifest.manifest_revision, 1)) {
    problems.push({ path: "manifest_revision", message: "must be a safe integer >= 1" });
  }
  if (!isStrongSha256Etag(manifest.etag)) {
    problems.push({ path: "etag", message: "must be a quoted strong SHA-256 ETag" });
  }
  if (
    !isNonEmptyString(manifest.generated_at)
    || !/^\d{4}-\d{2}-\d{2}T/u.test(manifest.generated_at)
    || Number.isNaN(Date.parse(manifest.generated_at))
  ) {
    problems.push({ path: "generated_at", message: "must be an RFC 3339 date-time" });
  }
  if (typeof manifest.status !== "string" || !MANIFEST_STATUSES.has(manifest.status as ManifestStatus)) {
    problems.push({ path: "status", message: "is not a supported manifest status" });
  }
  if (!isSafeIntegerAtLeast(manifest.ready_prefix_count, 0)) {
    problems.push({ path: "ready_prefix_count", message: "must be a safe integer >= 0" });
  }
  if (typeof manifest.default_start_ready !== "boolean") {
    problems.push({ path: "default_start_ready", message: "must be a boolean" });
  }
  if (manifest.last_playable_start_ordinal !== null && !isSafeIntegerAtLeast(manifest.last_playable_start_ordinal, 0)) {
    problems.push({ path: "last_playable_start_ordinal", message: "must be null or a safe integer >= 0" });
  }

  if (!Array.isArray(manifest.ready_ranges)) {
    problems.push({ path: "ready_ranges", message: "must be an array" });
  } else {
    manifest.ready_ranges.forEach((range, index) => validateReadyRange(range, index, problems));
  }

  if (!Array.isArray(manifest.segments) || manifest.segments.length === 0) {
    problems.push({ path: "segments", message: "must be a non-empty array" });
  } else {
    manifest.segments.forEach((segment, index) => validateSegment(segment, index, problems));
    const seenIds = new Set<string>();
    const lastEndByBlock = new Map<string, number>();
    for (const [index, candidate] of manifest.segments.entries()) {
      if (!isRecord(candidate)) continue;
      if (isNonEmptyString(candidate.segment_id)) {
        if (seenIds.has(candidate.segment_id)) {
          problems.push({ path: `segments[${index}].segment_id`, message: "must be unique" });
        }
        seenIds.add(candidate.segment_id);
      }
      if (
        isNonEmptyString(candidate.source_block_key)
        && isSafeIntegerAtLeast(candidate.source_start_utf16, 0)
        && isSafeIntegerAtLeast(candidate.source_end_utf16, 1)
      ) {
        const previousEnd = lastEndByBlock.get(candidate.source_block_key);
        if (previousEnd !== undefined && candidate.source_start_utf16 < previousEnd) {
          problems.push({ path: `segments[${index}].source_start_utf16`, message: "must not overlap an earlier range in the same source block" });
        }
        lastEndByBlock.set(candidate.source_block_key, Math.max(previousEnd ?? 0, candidate.source_end_utf16));
      }
    }
  }

  if (hasDerivableShape(manifest)) {
    validateDerivedFields(manifest as unknown as NarrationManifestV2, problems);
  }
  return problems;
}

export function parseManifest(value: unknown): NarrationManifestV2 {
  const problems = validateManifest(value);
  if (problems.length > 0) throw new ManifestValidationError(problems);
  return value as NarrationManifestV2;
}

function contiguousReadyEnd(manifest: NarrationManifestV2, startOrdinal: number): number {
  let end = startOrdinal;
  while (
    end < manifest.segments.length
    && manifest.segments[end].render_status === "ready"
    && manifest.segments[end].audio
  ) {
    end += 1;
  }
  return end;
}

export function decidePlayback(
  manifest: NarrationManifestV2,
  targetSegmentId?: string,
): PlaybackDecision {
  const problems = validateManifest(manifest);
  if (problems.length > 0) throw new ManifestValidationError(problems);

  const target = targetSegmentId
    ? manifest.segments.find((segment) => segment.segment_id === targetSegmentId)
    : manifest.segments[0];
  const resolvedTargetId = targetSegmentId ?? target?.segment_id ?? "";
  if (!target) {
    return {
      kind: "missing",
      edition_id: manifest.edition_id,
      manifest_revision: manifest.manifest_revision,
      target_segment_id: resolvedTargetId,
    };
  }
  if (target.render_status === "failed") {
    return {
      kind: "blocked",
      edition_id: manifest.edition_id,
      manifest_revision: manifest.manifest_revision,
      target_segment_id: target.segment_id,
      reason: "target_failed",
      failed_segment_id: target.segment_id,
      failure: target.failure ?? undefined,
    };
  }
  if (target.render_status === "cancelled") {
    return {
      kind: "blocked",
      edition_id: manifest.edition_id,
      manifest_revision: manifest.manifest_revision,
      target_segment_id: target.segment_id,
      reason: "target_cancelled",
      failed_segment_id: target.segment_id,
    };
  }
  if (target.render_status !== "ready" || !target.audio) {
    return {
      kind: "prepare_required",
      edition_id: manifest.edition_id,
      manifest_revision: manifest.manifest_revision,
      target_segment_id: target.segment_id,
      requested_start_ordinal: target.ordinal,
      requested_end_ordinal_exclusive: Math.min(
        manifest.segments.length,
        target.ordinal + manifest.buffer_policy.target_segments,
      ),
      reason: "target_not_ready",
    };
  }

  const readyEnd = contiguousReadyEnd(manifest, target.ordinal);
  const next = manifest.segments[readyEnd];
  const authoritativeRange = manifest.ready_ranges.find((range) => (
    range.start_ordinal <= target.ordinal
    && range.end_ordinal_exclusive > target.ordinal
    && range.last_playable_start_ordinal >= target.ordinal
  ));
  if (!authoritativeRange) {
    if (next?.render_status === "failed") {
      return {
        kind: "blocked",
        edition_id: manifest.edition_id,
        manifest_revision: manifest.manifest_revision,
        target_segment_id: target.segment_id,
        reason: "gap_failed",
        failed_segment_id: next.segment_id,
        failure: next.failure ?? undefined,
      };
    }
    return {
      kind: "prepare_required",
      edition_id: manifest.edition_id,
      manifest_revision: manifest.manifest_revision,
      target_segment_id: target.segment_id,
      requested_start_ordinal: target.ordinal,
      requested_end_ordinal_exclusive: Math.min(
        manifest.segments.length,
        target.ordinal + manifest.buffer_policy.target_segments,
      ),
      reason: "ready_window_too_short",
    };
  }

  return {
    kind: "play",
    edition_id: manifest.edition_id,
    manifest_revision: manifest.manifest_revision,
    target_segment_id: target.segment_id,
    ready_range: {
      ...authoritativeRange,
      start_ordinal: target.ordinal,
      segment_count: authoritativeRange.end_ordinal_exclusive - target.ordinal,
      duration_ms: rangeDurationMs(manifest.segments, target.ordinal, authoritativeRange.end_ordinal_exclusive),
    },
  };
}

export function acceptManifestRefresh(
  current: NarrationManifestV2,
  incoming: NarrationManifestV2,
): {
  accepted: boolean;
  reason?: "edition_changed" | "revision_regressed" | "revision_collision" | "source_changed" | "invalid";
} {
  if (validateManifest(current).length > 0 || validateManifest(incoming).length > 0) {
    return { accepted: false, reason: "invalid" };
  }
  if (incoming.edition_id !== current.edition_id) return { accepted: false, reason: "edition_changed" };
  if (
    incoming.source_revision_id !== current.source_revision_id
    || incoming.source_sha256 !== current.source_sha256
  ) {
    return { accepted: false, reason: "source_changed" };
  }
  if (incoming.manifest_revision < current.manifest_revision) {
    return { accepted: false, reason: "revision_regressed" };
  }
  if (
    incoming.manifest_revision === current.manifest_revision
    && incoming.etag !== current.etag
  ) {
    return { accepted: false, reason: "revision_collision" };
  }
  return { accepted: true };
}

export type PrepareRangePriority = "interactive" | "chapter" | "background";

export interface PrepareRangeIntent {
  requestId: string;
  clientId: string;
  editionId: string;
  targetSegmentId: string;
  startOrdinal: number;
  endOrdinalExclusive: number;
  manifestRevision: number;
  priority: PrepareRangePriority;
  createdAtMs: number;
}

const BASE_PRIORITY: Record<PrepareRangePriority, number> = {
  interactive: 300,
  chapter: 200,
  background: 100,
};

export class PrepareRangeQueue {
  private readonly intents = new Map<string, PrepareRangeIntent>();

  enqueue(intent: PrepareRangeIntent): string[] {
    if (intent.startOrdinal < 0 || intent.endOrdinalExclusive <= intent.startOrdinal) {
      throw new Error("prepare range must be non-empty and non-negative");
    }
    const superseded: string[] = [];
    if (intent.priority === "interactive") {
      for (const [requestId, candidate] of this.intents) {
        if (
          candidate.priority === "interactive"
          && candidate.clientId === intent.clientId
          && candidate.editionId === intent.editionId
          && candidate.requestId !== intent.requestId
        ) {
          superseded.push(requestId);
          this.intents.delete(requestId);
        }
      }
    }
    this.intents.set(intent.requestId, { ...intent });
    return superseded;
  }

  delete(requestId: string): boolean {
    return this.intents.delete(requestId);
  }

  has(requestId: string): boolean {
    return this.intents.has(requestId);
  }

  size(): number {
    return this.intents.size;
  }

  next(nowMs: number, agingIntervalMs = 5_000): PrepareRangeIntent | undefined {
    const safeAgingInterval = Math.max(1, agingIntervalMs);
    return [...this.intents.values()].sort((left, right) => {
      const leftAge = Math.max(0, nowMs - left.createdAtMs);
      const rightAge = Math.max(0, nowMs - right.createdAtMs);
      const leftScore = BASE_PRIORITY[left.priority] + Math.floor(leftAge / safeAgingInterval);
      const rightScore = BASE_PRIORITY[right.priority] + Math.floor(rightAge / safeAgingInterval);
      if (leftScore !== rightScore) return rightScore - leftScore;
      if (left.createdAtMs !== right.createdAtMs) return left.createdAtMs - right.createdAtMs;
      return left.requestId.localeCompare(right.requestId);
    })[0];
  }
}

export class RapidSeekGuard {
  private generation = 0;
  private active?: { generation: number; requestId: string; editionId: string; targetSegmentId: string };

  begin(requestId: string, editionId: string, targetSegmentId: string) {
    this.generation += 1;
    this.active = {
      generation: this.generation,
      requestId,
      editionId,
      targetSegmentId,
    };
    return { ...this.active };
  }

  accepts(candidate: {
    generation: number;
    requestId: string;
    editionId: string;
    targetSegmentId: string;
  }): boolean {
    return Boolean(
      this.active
      && candidate.generation === this.active.generation
      && candidate.requestId === this.active.requestId
      && candidate.editionId === this.active.editionId
      && candidate.targetSegmentId === this.active.targetSegmentId,
    );
  }
}
