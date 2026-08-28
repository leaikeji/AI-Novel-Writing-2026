import {
  NARRATION_PRODUCTION_API_VERSION,
  PlaybackContractError,
} from "./playback-contracts";


export interface SavePlaybackProgressRequest {
  readonly profile_id: string;
  readonly manifest_revision: number;
  readonly manifest_etag: string;
  readonly edition_segment_id?: string;
  readonly segment_id: string;
  readonly offset_ms: number;
  readonly last_legal_start_ordinal: number;
  readonly playback_rate_millis: number;
  readonly expected_updated_at: string | null;
}


export interface PlaybackProgressProjection {
  readonly manifest_revision: number;
  readonly manifest_etag: string;
  readonly edition_segment_id: string;
  readonly segment_id: string;
  readonly ordinal: number;
  readonly offset_ms: number;
  readonly last_legal_start_ordinal: number;
  readonly playback_rate_millis: number;
  readonly manifest_advanced: boolean;
  readonly progress_updated_at: string;
}


export interface PlaybackProgressResponse {
  readonly contract_version: typeof NARRATION_PRODUCTION_API_VERSION;
  readonly edition_id: string;
  readonly profile_id: string;
  readonly progress: PlaybackProgressProjection | null;
}


type JsonRecord = Record<string, unknown>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ETAG_PATTERN = /^"[a-f0-9]{64}"$/u;
const PROFILE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/u;
const TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-](\d{2}):(\d{2}))$/u;

const SAVE_KEYS = [
  "profile_id", "manifest_revision", "manifest_etag", "edition_segment_id",
  "segment_id", "offset_ms", "last_legal_start_ordinal",
  "playback_rate_millis", "expected_updated_at",
] as const;
const SAVE_REQUIRED_KEYS = SAVE_KEYS.filter((key) => key !== "edition_segment_id");
const PROJECTION_KEYS = [
  "manifest_revision", "manifest_etag", "edition_segment_id", "segment_id",
  "ordinal", "offset_ms", "last_legal_start_ordinal", "playback_rate_millis",
  "manifest_advanced", "progress_updated_at",
] as const;
const RESPONSE_KEYS = [
  "contract_version", "edition_id", "profile_id", "progress",
] as const;


function requireExact(
  value: unknown,
  path: string,
  keys: readonly string[],
  requiredKeys: readonly string[] = keys,
): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PlaybackContractError(path, "must be an object");
  }
  const item = value as JsonRecord;
  const allowed = new Set(keys);
  for (const key of requiredKeys) {
    if (!Object.prototype.hasOwnProperty.call(item, key)) {
      throw new PlaybackContractError(`${path}.${key}`, "is required");
    }
  }
  for (const key of Object.keys(item)) {
    if (!allowed.has(key)) {
      throw new PlaybackContractError(`${path}.${key}`, "is not allowed");
    }
  }
  return item;
}


function requireInteger(value: unknown, minimum: number, maximum: number | null, path: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum
    || (maximum !== null && (value as number) > maximum)) {
    const upper = maximum === null ? "" : ` and <= ${maximum}`;
    throw new PlaybackContractError(path, `must be a safe integer >= ${minimum}${upper}`);
  }
  return value as number;
}


function requireUuid(value: unknown, path: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw new PlaybackContractError(path, "must be an RFC-4122 UUID v1-v5");
  }
  return value.toLowerCase();
}


function requireEtag(value: unknown, path: string): string {
  if (typeof value !== "string" || !ETAG_PATTERN.test(value)) {
    throw new PlaybackContractError(path, "must be a strong SHA-256 ETag");
  }
  return value;
}


export function parsePlaybackProfileId(value: unknown, path = "profile_id"): string {
  if (typeof value !== "string" || !PROFILE_PATTERN.test(value)) {
    throw new PlaybackContractError(path, "must be a bounded playback profile identity");
  }
  return value;
}


function requireAwareTimestamp(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new PlaybackContractError(path, "must be an ISO-8601 timestamp with timezone");
  }
  const match = TIMESTAMP_PATTERN.exec(value);
  if (!match) {
    throw new PlaybackContractError(path, "must be an ISO-8601 timestamp with timezone");
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[8] === undefined ? 0 : Number(match[8]);
  const offsetMinute = match[9] === undefined ? 0 : Number(match[9]);
  const calendar = new Date(0);
  calendar.setUTCHours(0, 0, 0, 0);
  calendar.setUTCFullYear(year, month - 1, day);
  if (
    year < 1
    || calendar.getUTCFullYear() !== year
    || calendar.getUTCMonth() !== month - 1
    || calendar.getUTCDate() !== day
    || hour > 23
    || minute > 59
    || second > 59
    || offsetHour > 23
    || offsetMinute > 59
    || !Number.isFinite(Date.parse(value))
  ) {
    throw new PlaybackContractError(path, "must be a valid ISO-8601 timestamp with timezone");
  }
  return value;
}


export function parseSavePlaybackProgressRequest(value: unknown): SavePlaybackProgressRequest {
  const item = requireExact(value, "$", SAVE_KEYS, SAVE_REQUIRED_KEYS);
  const expectedUpdatedAt = item.expected_updated_at === null
    ? null
    : requireAwareTimestamp(item.expected_updated_at, "expected_updated_at");
  const editionSegmentId = item.edition_segment_id === undefined
    ? undefined
    : requireUuid(item.edition_segment_id, "edition_segment_id");
  return Object.freeze({
    profile_id: parsePlaybackProfileId(item.profile_id),
    manifest_revision: requireInteger(item.manifest_revision, 1, null, "manifest_revision"),
    manifest_etag: requireEtag(item.manifest_etag, "manifest_etag"),
    ...(editionSegmentId === undefined ? {} : { edition_segment_id: editionSegmentId }),
    segment_id: requireUuid(item.segment_id, "segment_id"),
    offset_ms: requireInteger(item.offset_ms, 0, null, "offset_ms"),
    last_legal_start_ordinal: requireInteger(
      item.last_legal_start_ordinal,
      0,
      null,
      "last_legal_start_ordinal",
    ),
    playback_rate_millis: requireInteger(
      item.playback_rate_millis,
      250,
      4_000,
      "playback_rate_millis",
    ),
    expected_updated_at: expectedUpdatedAt,
  });
}


function parseProjection(value: unknown): PlaybackProgressProjection {
  const item = requireExact(value, "progress", PROJECTION_KEYS);
  const ordinal = requireInteger(item.ordinal, 0, null, "progress.ordinal");
  const legalStart = requireInteger(
    item.last_legal_start_ordinal,
    0,
    null,
    "progress.last_legal_start_ordinal",
  );
  if (legalStart > ordinal) {
    throw new PlaybackContractError(
      "progress.last_legal_start_ordinal",
      "cannot follow the playback position",
    );
  }
  if (typeof item.manifest_advanced !== "boolean") {
    throw new PlaybackContractError("progress.manifest_advanced", "must be a boolean");
  }
  return Object.freeze({
    manifest_revision: requireInteger(
      item.manifest_revision,
      1,
      null,
      "progress.manifest_revision",
    ),
    manifest_etag: requireEtag(item.manifest_etag, "progress.manifest_etag"),
    edition_segment_id: requireUuid(
      item.edition_segment_id,
      "progress.edition_segment_id",
    ),
    segment_id: requireUuid(item.segment_id, "progress.segment_id"),
    ordinal,
    offset_ms: requireInteger(item.offset_ms, 0, null, "progress.offset_ms"),
    last_legal_start_ordinal: legalStart,
    playback_rate_millis: requireInteger(
      item.playback_rate_millis,
      250,
      4_000,
      "progress.playback_rate_millis",
    ),
    manifest_advanced: item.manifest_advanced,
    progress_updated_at: requireAwareTimestamp(
      item.progress_updated_at,
      "progress.progress_updated_at",
    ),
  });
}


export function parsePlaybackProgressResponse(value: unknown): PlaybackProgressResponse {
  const item = requireExact(value, "$", RESPONSE_KEYS);
  if (item.contract_version !== NARRATION_PRODUCTION_API_VERSION) {
    throw new PlaybackContractError("contract_version", "is unsupported");
  }
  return Object.freeze({
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    edition_id: requireUuid(item.edition_id, "edition_id"),
    profile_id: parsePlaybackProfileId(item.profile_id),
    progress: item.progress === null ? null : parseProjection(item.progress),
  });
}
