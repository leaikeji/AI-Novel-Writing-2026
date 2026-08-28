export const EDITION_HISTORY_CONTRACT_VERSION = "narration-edition-history/1" as const;

export type EditionSourceStatus = "current" | "working_copy_diverged" | "superseded";
export type EditionState = "created" | "rendering" | "partial_ready" | "ready" | "unavailable";
export type EditionSwitchMode = "immediate" | "next_playback";

export interface EditionHistoryItem {
  readonly edition_id: string;
  readonly request_id: string;
  readonly source_revision_id: string;
  readonly source_content_hash: string;
  readonly edition_fingerprint: string;
  readonly state: EditionState;
  readonly created_at: string | null;
  readonly manifest_revision: number | null;
  readonly manifest_etag: string | null;
  readonly ready_segment_count: number;
  readonly total_segment_count: number;
  readonly is_current: boolean;
  readonly source_status: EditionSourceStatus;
  readonly rights_available: boolean;
  readonly playable: boolean;
  readonly default_start_ready: boolean;
  readonly resume_available: boolean;
  readonly switch_allowed: boolean;
}

export interface DocumentEditionHistory {
  readonly contract_version: typeof EDITION_HISTORY_CONTRACT_VERSION;
  readonly document_id: string;
  readonly pointer_version: number;
  readonly current_edition_id: string | null;
  readonly working_copy_content_hash: string;
  readonly working_copy_draft_version: number;
  readonly editions: readonly EditionHistoryItem[];
}

export interface EditionSwitchIntent {
  readonly document_id: string;
  readonly edition_id: string;
  readonly expected_version: number;
  readonly switch_mode: EditionSwitchMode;
  readonly start_segment_id: string | null;
}

export class EditionHistoryContractError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "EditionHistoryContractError";
    this.path = path;
  }
}

type JsonRecord = Record<string, unknown>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256 = /^[a-f0-9]{64}$/u;
const ETAG = /^"[a-f0-9]{64}"$/u;
const ROOT_KEYS = [
  "contract_version", "document_id", "pointer_version", "current_edition_id",
  "working_copy_content_hash", "working_copy_draft_version", "editions",
] as const;
const ITEM_KEYS = [
  "edition_id", "request_id", "source_revision_id", "source_content_hash",
  "edition_fingerprint", "state", "created_at", "manifest_revision",
  "manifest_etag", "ready_segment_count", "total_segment_count", "is_current",
  "source_status", "rights_available", "playable", "default_start_ready",
  "resume_available", "switch_allowed",
] as const;
const STATES = new Set<EditionState>([
  "created", "rendering", "partial_ready", "ready", "unavailable",
]);
const SOURCE_STATUSES = new Set<EditionSourceStatus>([
  "current", "working_copy_diverged", "superseded",
]);

function exactRecord(value: unknown, path: string, keys: readonly string[]): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EditionHistoryContractError(path, "must be an object");
  }
  const record = value as JsonRecord;
  if (
    Object.keys(record).length !== keys.length
    || keys.some((key) => !Object.prototype.hasOwnProperty.call(record, key))
  ) {
    throw new EditionHistoryContractError(path, "has unexpected or missing fields");
  }
  return record;
}

function text(value: unknown, path: string, pattern?: RegExp): string {
  if (typeof value !== "string" || !value || (pattern && !pattern.test(value))) {
    throw new EditionHistoryContractError(path, "has an invalid string value");
  }
  return value;
}

function integer(value: unknown, path: string, minimum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new EditionHistoryContractError(path, `must be a safe integer >= ${minimum}`);
  }
  return value as number;
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new EditionHistoryContractError(path, "must be a boolean");
  return value;
}

function nullableUuid(value: unknown, path: string): string | null {
  return value === null ? null : text(value, path, UUID).toLowerCase();
}

function nullableDate(value: unknown, path: string): string | null {
  if (value === null) return null;
  const parsed = text(value, path);
  if (Number.isNaN(Date.parse(parsed)) || !/[zZ]|[+-]\d\d:\d\d$/u.test(parsed)) {
    throw new EditionHistoryContractError(path, "must be an RFC-3339 date-time with offset");
  }
  return parsed;
}

function parseItem(value: unknown, index: number): EditionHistoryItem {
  const path = `editions[${index}]`;
  const item = exactRecord(value, path, ITEM_KEYS);
  const state = text(item.state, `${path}.state`) as EditionState;
  if (!STATES.has(state)) throw new EditionHistoryContractError(`${path}.state`, "is unsupported");
  const sourceStatus = text(item.source_status, `${path}.source_status`) as EditionSourceStatus;
  if (!SOURCE_STATUSES.has(sourceStatus)) {
    throw new EditionHistoryContractError(`${path}.source_status`, "is unsupported");
  }
  const manifestRevision = item.manifest_revision === null
    ? null
    : integer(item.manifest_revision, `${path}.manifest_revision`, 1);
  const manifestEtag = item.manifest_etag === null
    ? null
    : text(item.manifest_etag, `${path}.manifest_etag`, ETAG);
  if ((manifestRevision === null) !== (manifestEtag === null)) {
    throw new EditionHistoryContractError(path, "Manifest revision and ETag must be present together");
  }
  const totalSegmentCount = integer(item.total_segment_count, `${path}.total_segment_count`, 1);
  const readySegmentCount = integer(item.ready_segment_count, `${path}.ready_segment_count`, 0);
  if (readySegmentCount > totalSegmentCount) {
    throw new EditionHistoryContractError(`${path}.ready_segment_count`, "cannot exceed total_segment_count");
  }
  const isCurrent = bool(item.is_current, `${path}.is_current`);
  const rightsAvailable = bool(item.rights_available, `${path}.rights_available`);
  const playable = bool(item.playable, `${path}.playable`);
  const defaultStartReady = bool(item.default_start_ready, `${path}.default_start_ready`);
  const resumeAvailable = bool(item.resume_available, `${path}.resume_available`);
  const switchAllowed = bool(item.switch_allowed, `${path}.switch_allowed`);
  if ((isCurrent && sourceStatus === "superseded") || (!isCurrent && sourceStatus !== "superseded")) {
    throw new EditionHistoryContractError(`${path}.source_status`, "does not match is_current");
  }
  if (playable && (!rightsAvailable || manifestRevision === null || !["partial_ready", "ready"].includes(state))) {
    throw new EditionHistoryContractError(`${path}.playable`, "lacks rights, Manifest, or playable Edition state");
  }
  if (switchAllowed && (!playable || (!defaultStartReady && !resumeAvailable))) {
    throw new EditionHistoryContractError(`${path}.switch_allowed`, "lacks a legal ready start");
  }
  return Object.freeze({
    edition_id: text(item.edition_id, `${path}.edition_id`, UUID).toLowerCase(),
    request_id: text(item.request_id, `${path}.request_id`, UUID).toLowerCase(),
    source_revision_id: text(item.source_revision_id, `${path}.source_revision_id`, UUID).toLowerCase(),
    source_content_hash: text(item.source_content_hash, `${path}.source_content_hash`, SHA256),
    edition_fingerprint: text(item.edition_fingerprint, `${path}.edition_fingerprint`, SHA256),
    state,
    created_at: nullableDate(item.created_at, `${path}.created_at`),
    manifest_revision: manifestRevision,
    manifest_etag: manifestEtag,
    ready_segment_count: readySegmentCount,
    total_segment_count: totalSegmentCount,
    is_current: isCurrent,
    source_status: sourceStatus,
    rights_available: rightsAvailable,
    playable,
    default_start_ready: defaultStartReady,
    resume_available: resumeAvailable,
    switch_allowed: switchAllowed,
  });
}

export function parseDocumentEditionHistory(value: unknown): DocumentEditionHistory {
  const root = exactRecord(value, "$", ROOT_KEYS);
  if (root.contract_version !== EDITION_HISTORY_CONTRACT_VERSION) {
    throw new EditionHistoryContractError("contract_version", "is unsupported");
  }
  if (!Array.isArray(root.editions)) {
    throw new EditionHistoryContractError("editions", "must be an array");
  }
  const editions = root.editions.map(parseItem);
  const ids = new Set<string>();
  for (const item of editions) {
    if (ids.has(item.edition_id)) throw new EditionHistoryContractError("editions", "contains duplicate Edition IDs");
    ids.add(item.edition_id);
  }
  const currentEditionId = nullableUuid(root.current_edition_id, "current_edition_id");
  const currentRows = editions.filter((item) => item.is_current);
  if (
    (currentEditionId === null && currentRows.length !== 0)
    || (currentEditionId !== null
      && (currentRows.length !== 1 || currentRows[0].edition_id !== currentEditionId))
  ) {
    throw new EditionHistoryContractError("current_edition_id", "does not match the unique current Edition");
  }
  const result: DocumentEditionHistory = {
    contract_version: EDITION_HISTORY_CONTRACT_VERSION,
    document_id: text(root.document_id, "document_id", UUID).toLowerCase(),
    pointer_version: integer(root.pointer_version, "pointer_version", 0),
    current_edition_id: currentEditionId,
    working_copy_content_hash: text(root.working_copy_content_hash, "working_copy_content_hash", SHA256),
    working_copy_draft_version: integer(root.working_copy_draft_version, "working_copy_draft_version", 1),
    editions: Object.freeze(editions),
  };
  return Object.freeze(result);
}

export function createEditionSwitchIntent(
  history: DocumentEditionHistory,
  editionId: string,
  switchMode: EditionSwitchMode,
  startSegmentId: string | null = null,
): EditionSwitchIntent {
  const normalizedEditionId = text(editionId, "edition_id", UUID).toLowerCase();
  if (switchMode !== "immediate" && switchMode !== "next_playback") {
    throw new EditionHistoryContractError("switch_mode", "is unsupported");
  }
  const target = history.editions.find((item) => item.edition_id === normalizedEditionId);
  if (!target) throw new EditionHistoryContractError("edition_id", "is outside this document history");
  if (!target.switch_allowed) throw new EditionHistoryContractError("edition_id", "has no legal playable switch target");
  if (target.is_current) throw new EditionHistoryContractError("edition_id", "is already current");
  const normalizedStart = startSegmentId === null
    ? null
    : text(startSegmentId, "start_segment_id", UUID).toLowerCase();
  if (switchMode === "immediate" && normalizedStart === null && !target.default_start_ready) {
    throw new EditionHistoryContractError("start_segment_id", "is required when chapter start is not ready");
  }
  if (switchMode === "next_playback" && normalizedStart !== null) {
    throw new EditionHistoryContractError("start_segment_id", "is only valid for immediate switching");
  }
  return Object.freeze({
    document_id: history.document_id,
    edition_id: target.edition_id,
    expected_version: history.pointer_version,
    switch_mode: switchMode,
    start_segment_id: normalizedStart,
  });
}

export type LatestIntentResult<T> =
  | Readonly<{ accepted: true; sequence: number; value: T }>
  | Readonly<{ accepted: false; sequence: number; reason: "superseded" | "disposed" }>;

export class LatestNarrationIntentCoordinator {
  private sequence = 0;
  private controller: AbortController | null = null;
  private disposed = false;

  async run<T>(operation: (signal: AbortSignal, sequence: number) => Promise<T>): Promise<LatestIntentResult<T>> {
    if (this.disposed) return Object.freeze({ accepted: false, sequence: this.sequence, reason: "disposed" });
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const sequence = ++this.sequence;
    try {
      const value = await operation(controller.signal, sequence);
      if (this.disposed) return Object.freeze({ accepted: false, sequence, reason: "disposed" });
      if (controller.signal.aborted || sequence !== this.sequence) {
        return Object.freeze({ accepted: false, sequence, reason: "superseded" });
      }
      return Object.freeze({ accepted: true, sequence, value });
    } catch (reason) {
      if (controller.signal.aborted || sequence !== this.sequence) {
        return Object.freeze({ accepted: false, sequence, reason: "superseded" });
      }
      throw reason;
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.sequence += 1;
    this.controller?.abort();
    this.controller = null;
  }
}
