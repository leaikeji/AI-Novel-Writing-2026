import { APP_ID } from "../contracts";
import {
  PlaybackContractError,
  parseManifest,
  parsePlaybackApiErrorDetail,
  parsePrepareRangeResponse,
  type NarrationManifestV2,
  type PlaybackApiErrorDetail,
  type PrepareRangeReason,
  type PrepareRangeRequest,
  type PrepareRangeResponse,
} from "./playback-contracts";
import {
  parsePlaybackProfileId,
  parsePlaybackProgressResponse,
  parseSavePlaybackProgressRequest,
  type PlaybackProgressResponse,
  type SavePlaybackProgressRequest,
} from "./playback-progress-contracts";


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const ETAG_PATTERN = /^(?:W\/)?"[a-f0-9]{64}"$/u;
const MEDIA_URL_PATTERN = /^\/api\/ai-novel-world-2026\/media-assets\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/content$/iu;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/u;
const SINGLE_RANGE_PATTERN = /^bytes=(?:\d+-\d*|-\d+)$/u;


export class PlaybackApiError extends Error {
  readonly status: number;
  readonly detail: PlaybackApiErrorDetail | null;

  constructor(status: number, detail: PlaybackApiErrorDetail | null) {
    super(detail?.message ?? `HTTP ${status}`);
    this.name = "PlaybackApiError";
    this.status = status;
    this.detail = detail;
  }
}


export type ManifestFetchResult = Readonly<
  | { not_modified: true; etag: string; manifest: null }
  | { not_modified: false; etag: string; manifest: NarrationManifestV2 }
>;


export interface GetManifestOptions {
  readonly manifestRevision?: number;
  readonly ifNoneMatch?: string;
  readonly signal?: AbortSignal;
}


export interface PlaybackMediaRequest {
  readonly url: string;
  readonly editionId: string;
  readonly manifestRevision: number;
  readonly method?: "GET" | "HEAD";
  readonly range?: string;
  readonly ifRange?: string;
  readonly ifNoneMatch?: string;
  readonly signal?: AbortSignal;
}


export interface PlaybackProgressRequestOptions {
  readonly signal?: AbortSignal;
}


function uuid(value: string, field: string): string {
  if (!UUID_PATTERN.test(value)) {
    throw new PlaybackContractError(field, "must be an RFC-4122 UUID v1-v5");
  }
  return value.toLowerCase();
}


function revision(value: number, field: string): number {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new PlaybackContractError(field, "must be a safe integer >= 1");
  }
  return value;
}


function strongOrWeakEtag(value: string, field: string): string {
  if (!ETAG_PATTERN.test(value)) {
    throw new PlaybackContractError(field, "must be a SHA-256 ETag");
  }
  return value;
}


function strongEtag(value: string, field: string): string {
  if (!/^"[a-f0-9]{64}"$/u.test(value)) {
    throw new PlaybackContractError(field, "must be a strong SHA-256 ETag");
  }
  return value;
}


function responseEtag(response: Response, manifest?: NarrationManifestV2): string {
  const header = response.headers.get("ETag");
  const candidate = header ?? manifest?.etag;
  if (!candidate || !/^"[a-f0-9]{64}"$/u.test(candidate)) {
    throw new PlaybackContractError("response.ETag", "must be a strong SHA-256 ETag");
  }
  if (manifest && candidate !== manifest.etag) {
    throw new PlaybackContractError("response.ETag", "differs from Manifest etag");
  }
  return candidate;
}


async function parseError(response: Response): Promise<PlaybackApiError> {
  let detail: PlaybackApiErrorDetail | null = null;
  try {
    const value = await response.json() as unknown;
    if (value && typeof value === "object" && "detail" in value) {
      detail = parsePlaybackApiErrorDetail((value as { detail: unknown }).detail);
    }
  } catch {
    // A malformed or non-JSON error remains an HTTP error, never trusted data.
  }
  return new PlaybackApiError(response.status, detail);
}


async function checkedJson(response: Response): Promise<unknown> {
  if (!response.ok) throw await parseError(response);
  try {
    return await response.json() as unknown;
  } catch (error) {
    throw new PlaybackContractError("response", `must contain JSON (${String(error)})`);
  }
}


export async function getNarrationManifest(
  editionId: string,
  options: GetManifestOptions = {},
): Promise<ManifestFetchResult> {
  const normalizedEdition = uuid(editionId, "edition_id");
  const query = options.manifestRevision === undefined
    ? ""
    : `?manifest_revision=${revision(options.manifestRevision, "manifest_revision")}`;
  // The public PawApp bridge expects JSON-serializable request init values.
  // Keep this a plain object just like scoped media headers so conditional
  // Manifest requests survive the real host boundary.
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.ifNoneMatch) {
    headers["If-None-Match"] = strongOrWeakEtag(options.ifNoneMatch, "if_none_match");
  }
  const response = await window.QwenPaw.host.fetch(
    `/${APP_ID}/narration-editions/${normalizedEdition}/manifest${query}`,
    { method: "GET", headers: Object.freeze(headers), signal: options.signal },
  );
  if (response.status === 304) {
    return Object.freeze({ not_modified: true, etag: responseEtag(response), manifest: null });
  }
  const manifest = parseManifest(await checkedJson(response));
  if (manifest.edition_id !== normalizedEdition) {
    throw new PlaybackContractError("edition_id", "response scope mismatch");
  }
  if (options.manifestRevision !== undefined && manifest.manifest_revision !== options.manifestRevision) {
    throw new PlaybackContractError("manifest_revision", "response scope mismatch");
  }
  return Object.freeze({
    not_modified: false,
    etag: responseEtag(response, manifest),
    manifest,
  });
}


export async function prepareNarrationRange(
  editionId: string,
  startSegmentId: string,
  reason: PrepareRangeReason,
  expectedManifestRevision: number,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<PrepareRangeResponse> {
  const normalizedEdition = uuid(editionId, "edition_id");
  const normalizedSegment = uuid(startSegmentId, "start_segment_id");
  if (reason !== "user_seek" && reason !== "resume") {
    throw new PlaybackContractError("reason", "is unsupported");
  }
  if (!IDEMPOTENCY_PATTERN.test(idempotencyKey)) {
    throw new PlaybackContractError("idempotency_key", "must be 8-128 safe characters");
  }
  const payload: PrepareRangeRequest = {
    start_segment_id: normalizedSegment,
    reason,
    expected_manifest_revision: revision(expectedManifestRevision, "expected_manifest_revision"),
  };
  const response = await window.QwenPaw.host.fetch(
    `/${APP_ID}/narration-editions/${normalizedEdition}/prepare-range`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(payload),
      signal,
    },
  );
  const result = parsePrepareRangeResponse(await checkedJson(response));
  if (result.edition_id !== normalizedEdition || result.start_segment_id !== normalizedSegment) {
    throw new PlaybackContractError("response", "prepare-range scope mismatch");
  }
  if (result.manifest_revision !== expectedManifestRevision) {
    throw new PlaybackContractError("manifest_revision", "response scope mismatch");
  }
  return result;
}


function progressPath(editionId: string, profileId: string): string {
  const normalizedEdition = uuid(editionId, "edition_id");
  const normalizedProfile = parsePlaybackProfileId(profileId);
  return `/${APP_ID}/narration-editions/${normalizedEdition}/playback-progress?profile_id=${encodeURIComponent(normalizedProfile)}`;
}


function requireProgressScope(
  response: PlaybackProgressResponse,
  editionId: string,
  profileId: string,
): PlaybackProgressResponse {
  if (response.edition_id !== editionId || response.profile_id !== profileId) {
    throw new PlaybackContractError("response", "playback progress scope mismatch");
  }
  return response;
}


export async function getNarrationPlaybackProgress(
  editionId: string,
  profileId: string,
  options: PlaybackProgressRequestOptions = {},
): Promise<PlaybackProgressResponse> {
  const normalizedEdition = uuid(editionId, "edition_id");
  const normalizedProfile = parsePlaybackProfileId(profileId);
  const response = await window.QwenPaw.host.fetch(
    progressPath(normalizedEdition, normalizedProfile),
    {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: options.signal,
    },
  );
  return requireProgressScope(
    parsePlaybackProgressResponse(await checkedJson(response)),
    normalizedEdition,
    normalizedProfile,
  );
}


export async function putNarrationPlaybackProgress(
  editionId: string,
  request: SavePlaybackProgressRequest,
  options: PlaybackProgressRequestOptions = {},
): Promise<PlaybackProgressResponse> {
  const normalizedEdition = uuid(editionId, "edition_id");
  const payload = parseSavePlaybackProgressRequest(request);
  const response = await window.QwenPaw.host.fetch(
    progressPath(normalizedEdition, payload.profile_id),
    {
      method: "PUT",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: options.signal,
    },
  );
  const result = requireProgressScope(
    parsePlaybackProgressResponse(await checkedJson(response)),
    normalizedEdition,
    payload.profile_id,
  );
  if (result.progress === null) {
    throw new PlaybackContractError("progress", "must be non-null after save");
  }
  if (
    (payload.edition_segment_id !== undefined
      && result.progress.edition_segment_id !== payload.edition_segment_id)
    || result.progress.segment_id !== payload.segment_id
    || result.progress.offset_ms !== payload.offset_ms
    || result.progress.last_legal_start_ordinal !== payload.last_legal_start_ordinal
    || result.progress.playback_rate_millis !== payload.playback_rate_millis
    || result.progress.manifest_revision < payload.manifest_revision
    || (
      result.progress.manifest_revision === payload.manifest_revision
      && (
        result.progress.manifest_etag !== payload.manifest_etag
        || result.progress.manifest_advanced
      )
    )
    || (
      result.progress.manifest_revision > payload.manifest_revision
      && !result.progress.manifest_advanced
    )
  ) {
    throw new PlaybackContractError("progress", "saved playback position mismatch");
  }
  return result;
}


function mediaHostPath(url: string): string {
  if (
    !MEDIA_URL_PATTERN.test(url)
    || url.includes("?")
    || url.includes("#")
    || url.includes("%")
    || url.includes("\\")
    || url.toLowerCase().includes("token")
  ) {
    throw new PlaybackContractError(
      "media.url",
      "must be the controlled token-free playback route",
    );
  }
  // QwenPaw host.fetch itself prefixes /api.  Passing the Manifest URL as-is
  // would create /api/api/... and bypass the fixed host contract.
  return url.slice("/api".length);
}


function mediaHeaders(request: PlaybackMediaRequest): Readonly<Record<string, string>> {
  // QwenPaw's public host.fetch bridge serializes a plain header object across
  // the PawApp boundary. Passing a browser Headers instance works in direct
  // fetch mocks but loses the custom playback scope headers in the real host.
  const headers: Record<string, string> = {
    "X-Narration-Edition-Id": uuid(request.editionId, "edition_id"),
    "X-Narration-Manifest-Revision": String(revision(request.manifestRevision, "manifest_revision")),
  };
  if (request.range !== undefined) {
    if (!SINGLE_RANGE_PATTERN.test(request.range) || request.range.includes(",")) {
      throw new PlaybackContractError("range", "only one bytes range is supported");
    }
    headers.Range = request.range;
  }
  if (request.ifRange !== undefined) {
    if (request.range === undefined) {
      throw new PlaybackContractError("if_range", "requires a Range request");
    }
    headers["If-Range"] = strongEtag(request.ifRange, "if_range");
  }
  if (request.ifNoneMatch !== undefined) {
    headers["If-None-Match"] = strongOrWeakEtag(request.ifNoneMatch, "if_none_match");
  }
  return Object.freeze(headers);
}


function validateMediaResponse(response: Response, request: PlaybackMediaRequest): void {
  const etag = response.headers.get("ETag");
  if (!etag || !/^"[a-f0-9]{64}"$/u.test(etag)) {
    throw new PlaybackContractError("media.response.ETag", "must be a strong SHA-256 ETag");
  }
  if (request.ifRange !== undefined && etag !== request.ifRange) {
    throw new PlaybackContractError("media.response.ETag", "differs from the Manifest audio ETag");
  }
  if (response.status === 304 && (
    request.ifNoneMatch === undefined
    || request.ifNoneMatch.replace(/^W\//u, "") !== etag
  )) {
    throw new PlaybackContractError("media.response.ETag", "does not satisfy If-None-Match");
  }
  if (response.status === 200 || response.status === 206) {
    const contentType = response.headers.get("Content-Type")?.split(";", 1)[0].trim();
    if (!contentType?.startsWith("audio/")) {
      throw new PlaybackContractError("media.response.Content-Type", "must be an audio MIME type");
    }
    if (response.headers.get("Accept-Ranges") !== "bytes") {
      throw new PlaybackContractError("media.response.Accept-Ranges", "must equal bytes");
    }
    const contentLength = response.headers.get("Content-Length");
    if (!contentLength || !/^\d+$/u.test(contentLength)) {
      throw new PlaybackContractError("media.response.Content-Length", "must be a byte count");
    }
  }
  if (response.status === 206 && !/^bytes \d+-\d+\/\d+$/u.test(response.headers.get("Content-Range") ?? "")) {
    throw new PlaybackContractError("media.response.Content-Range", "must identify one satisfied range");
  }
  if (response.status === 416 && !/^bytes \*\/\d+$/u.test(response.headers.get("Content-Range") ?? "")) {
    throw new PlaybackContractError("media.response.Content-Range", "must identify the unsatisfied size");
  }
}


/**
 * Fetch raw playback bytes through the fixed host facade.
 *
 * This deliberately returns Response and never calls response.json() for a
 * successful 200/206/304/416 media response, so Range streaming remains raw.
 */
export async function fetchPlaybackMedia(request: PlaybackMediaRequest): Promise<Response> {
  const method = request.method ?? "GET";
  if (method !== "GET" && method !== "HEAD") {
    throw new PlaybackContractError("method", "must be GET or HEAD");
  }
  const response = await window.QwenPaw.host.fetch(mediaHostPath(request.url), {
    method,
    headers: mediaHeaders(request),
    signal: request.signal,
  });
  if (![200, 206, 304, 416].includes(response.status)) {
    throw await parseError(response);
  }
  validateMediaResponse(response, request);
  return response;
}


export function headPlaybackMedia(
  request: Omit<PlaybackMediaRequest, "method">,
): Promise<Response> {
  return fetchPlaybackMedia({ ...request, method: "HEAD" });
}
