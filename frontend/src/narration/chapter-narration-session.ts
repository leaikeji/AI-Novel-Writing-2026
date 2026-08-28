import {
  getDocumentNarrationContext,
  getNarrationEdition,
} from "./api";
import type {
  DocumentNarrationContext,
  NarrationEditionResource,
} from "./chapter-contracts";
import {
  createChapterPlaybackCoordinator,
  type ChapterPlaybackCoordinator,
  type ChapterPlaybackRequestResult,
} from "./chapter-playback";
import type {
  NarrationEditorBridge,
  NarrationSourceSegment,
} from "./editor-bridge";
import {
  createNarrationPlayerController,
  decideManifestPlayback,
  type CreateNarrationPlayerOptions,
  type NarrationPlaybackSource,
  type NarrationPlayerController,
  type NarrationPlayerState,
  type PlaybackDecision,
} from "./narration-player";
import {
  type NarrationParagraphDescriptor,
} from "./paragraph-gutter";
import {
  getNarrationPlaybackProgress,
  getNarrationManifest,
  prepareNarrationRange,
  putNarrationPlaybackProgress,
  type ManifestFetchResult,
} from "./playback-api";
import { PlaybackApiError } from "./playback-api";
import type {
  NarrationManifestV2,
} from "./playback-contracts";
import {
  parsePlaybackProfileId,
  type PlaybackProgressProjection,
  type SavePlaybackProgressRequest,
} from "./playback-progress-contracts";
import {
  getNarrationScriptVersionForEdition,
  type ScriptReviewDocumentScope,
} from "./script-api";
import type {
  ScriptReviewResource,
  ScriptReviewSegmentResource,
} from "./script-contracts";
import {
  createSegmentFollowController,
  type AuthorFollowInterruption,
  type FollowAwareNarrationPlayerController,
  type SegmentFollowController,
} from "./segment-follow";
import {
  playbackLeasesEqual,
  type PlaybackLease,
} from "./segment-playback-queue";


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const DEFAULT_POLL_SCHEDULE_MS = Object.freeze([250, 500, 1_000, 2_000]);
const DEFAULT_POLL_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_POLL_ATTEMPTS = 30;
const PROGRESS_SAVE_DEBOUNCE_MS = 250;
export const DEFAULT_PLAYBACK_PROFILE_ID = "desktop.default";


export type ChapterNarrationSessionErrorCode =
  | "INVALID_INPUT"
  | "STALE_GENERATION"
  | "SCOPE_MISMATCH"
  | "CONTRACT_MISMATCH"
  | "SESSION_NOT_READY"
  | "SESSION_DISPOSED";


export class ChapterNarrationSessionError extends Error {
  readonly code: ChapterNarrationSessionErrorCode;

  constructor(code: ChapterNarrationSessionErrorCode, message: string) {
    super(message);
    this.name = "ChapterNarrationSessionError";
    this.code = code;
  }
}


export interface ChapterNarrationBundleSegment {
  readonly script: ScriptReviewSegmentResource;
  readonly manifest: NarrationManifestV2["segments"][number];
}


export interface ChapterNarrationBundle {
  readonly context: DocumentNarrationContext;
  readonly edition: NarrationEditionResource;
  readonly script: ScriptReviewResource;
  readonly manifest: NarrationManifestV2;
  readonly bridgeSegments: readonly NarrationSourceSegment[];
  readonly paragraphs: readonly NarrationParagraphDescriptor[];
  readonly segmentById: ReadonlyMap<string, ChapterNarrationBundleSegment>;
}


export type ChapterNarrationBundleLoadResult = Readonly<
  | {
      status: "no-edition";
      context: DocumentNarrationContext;
    }
  | {
      status: "ready";
      bundle: ChapterNarrationBundle;
    }
>;


export interface LoadChapterNarrationBundleOptions {
  readonly novelId: string;
  readonly documentId: string;
  readonly generation: number;
  readonly activeEditionId?: string;
  readonly signal?: AbortSignal;
  readonly isGenerationCurrent: (documentId: string, generation: number) => boolean;
}


interface ChapterNarrationNetworkDependencies {
  readonly getDocumentNarrationContext: typeof getDocumentNarrationContext;
  readonly getNarrationEdition: typeof getNarrationEdition;
  readonly getNarrationScriptVersionForEdition: typeof getNarrationScriptVersionForEdition;
  readonly getNarrationManifest: typeof getNarrationManifest;
  readonly prepareNarrationRange: typeof prepareNarrationRange;
  readonly getNarrationPlaybackProgress: typeof getNarrationPlaybackProgress;
  readonly putNarrationPlaybackProgress: typeof putNarrationPlaybackProgress;
}


export interface ChapterNarrationSessionDependencies
  extends ChapterNarrationNetworkDependencies {
  readonly createPlayer: (
    options: CreateNarrationPlayerOptions,
  ) => FollowAwareNarrationPlayerController;
  readonly delay: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  readonly now: () => number;
}


const DEFAULT_NETWORK: ChapterNarrationNetworkDependencies = Object.freeze({
  getDocumentNarrationContext,
  getNarrationEdition,
  getNarrationScriptVersionForEdition,
  getNarrationManifest,
  prepareNarrationRange,
  getNarrationPlaybackProgress,
  putNarrationPlaybackProgress,
});


function abortError(message: string): DOMException {
  return new DOMException(message, "AbortError");
}


function defaultDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError("polling aborted"));
  return new Promise<void>((resolve, reject) => {
    const handle = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      clearTimeout(handle);
      signal.removeEventListener("abort", onAbort);
      reject(abortError("polling aborted"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}


function awaitWithAbort<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError("operation aborted"));
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(abortError("operation aborted"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    void operation.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (reason) => {
        signal.removeEventListener("abort", onAbort);
        reject(reason);
      },
    );
  });
}


const DEFAULT_DEPENDENCIES: ChapterNarrationSessionDependencies = Object.freeze({
  ...DEFAULT_NETWORK,
  createPlayer: (options: CreateNarrationPlayerOptions) => (
    createNarrationPlayerController(options)
  ),
  delay: defaultDelay,
  now: () => Date.now(),
});


function fail(
  code: ChapterNarrationSessionErrorCode,
  message: string,
): never {
  throw new ChapterNarrationSessionError(code, message);
}


function uuid(value: string, field: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    fail("INVALID_INPUT", `${field} must be an RFC-4122 UUID`);
  }
  return value.toLowerCase();
}


function generation(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    fail("INVALID_INPUT", "generation must be a non-negative safe integer");
  }
  return value;
}


function ensureGenerationCurrent(
  options: LoadChapterNarrationBundleOptions,
): void {
  if (options.signal?.aborted) throw abortError("chapter narration load aborted");
  let current = false;
  try {
    current = options.isGenerationCurrent(options.documentId, options.generation);
  } catch {
    current = false;
  }
  if (!current) fail("STALE_GENERATION", "chapter generation is stale");
}


function requireEqual(
  actual: unknown,
  expected: unknown,
  field: string,
  code: ChapterNarrationSessionErrorCode = "SCOPE_MISMATCH",
): void {
  if (actual !== expected) fail(code, `${field} does not match the requested chapter`);
}


function validateContext(
  context: DocumentNarrationContext,
  options: LoadChapterNarrationBundleOptions,
): string | null {
  const novelId = uuid(options.novelId, "novelId");
  const documentId = uuid(options.documentId, "documentId");
  requireEqual(context.novel_id, novelId, "context.novel_id");
  requireEqual(context.document_id, documentId, "context.document_id");
  requireEqual(
    context.edition_history.document_id,
    documentId,
    "context.edition_history.document_id",
  );
  requireEqual(
    context.edition_history.pointer_version,
    context.pointer_version,
    "context.edition_history.pointer_version",
    "CONTRACT_MISMATCH",
  );
  requireEqual(
    context.edition_history.current_edition_id,
    context.current_edition_id,
    "context.edition_history.current_edition_id",
    "CONTRACT_MISMATCH",
  );
  requireEqual(
    context.edition_history.working_copy_content_hash,
    context.working_copy_content_hash,
    "context.edition_history.working_copy_content_hash",
    "CONTRACT_MISMATCH",
  );
  requireEqual(
    context.edition_history.working_copy_draft_version,
    context.working_copy_draft_version,
    "context.edition_history.working_copy_draft_version",
    "CONTRACT_MISMATCH",
  );
  const requestedActive = options.activeEditionId === undefined
    ? undefined
    : uuid(options.activeEditionId, "activeEditionId");
  if (requestedActive !== undefined) {
    requireEqual(context.active_edition_id, requestedActive, "context.active_edition_id");
  }
  const activeId = context.active_edition_id;
  if (activeId === null) {
    if (
      context.current_edition_id !== null
      || context.current_script_version_id !== null
      || context.source_snapshot !== null
      || context.active_is_current
    ) {
      fail("CONTRACT_MISMATCH", "no-edition context carries active Edition state");
    }
    return null;
  }
  uuid(activeId, "context.active_edition_id");
  if (context.active_is_current !== (activeId === context.current_edition_id)) {
    fail("CONTRACT_MISMATCH", "context.active_is_current is inconsistent");
  }
  if (context.active_is_current && context.current_script_version_id === null) {
    fail("CONTRACT_MISMATCH", "current Edition lacks a current ScriptVersion");
  }
  const historyItem = context.edition_history.editions.find(
    (item) => item.edition_id === activeId,
  );
  if (!historyItem) {
    fail("CONTRACT_MISMATCH", "active Edition is absent from document history");
  }
  if (historyItem.is_current !== context.active_is_current) {
    fail("CONTRACT_MISMATCH", "active Edition history current flag is inconsistent");
  }
  if (!historyItem.rights_available || historyItem.state === "unavailable") {
    fail("CONTRACT_MISMATCH", "active Edition is unavailable for playback");
  }
  if (!context.source_snapshot) {
    fail("CONTRACT_MISMATCH", "active Edition lacks an immutable source snapshot");
  }
  requireEqual(
    context.source_snapshot.revision_id,
    historyItem.source_revision_id,
    "context.source_snapshot.revision_id",
    "CONTRACT_MISMATCH",
  );
  requireEqual(
    context.source_snapshot.content_hash,
    historyItem.source_content_hash,
    "context.source_snapshot.content_hash",
    "CONTRACT_MISMATCH",
  );
  if (
    context.source_snapshot.matches_working_copy
    !== (context.source_snapshot.content_hash === context.working_copy_content_hash)
  ) {
    fail("CONTRACT_MISMATCH", "source snapshot working-copy flag is inconsistent");
  }
  return activeId;
}


function validateEdition(
  context: DocumentNarrationContext,
  edition: NarrationEditionResource,
  activeEditionId: string,
): void {
  requireEqual(edition.edition_id, activeEditionId, "edition.edition_id");
  requireEqual(edition.novel_id, context.novel_id, "edition.novel_id");
  requireEqual(edition.document_id, context.document_id, "edition.document_id");
  if (context.active_is_current) {
    requireEqual(
      edition.script_version_id,
      context.current_script_version_id,
      "edition.script_version_id",
      "CONTRACT_MISMATCH",
    );
  }
  const historyItem = context.edition_history.editions.find(
    (item) => item.edition_id === activeEditionId,
  );
  if (!historyItem) fail("CONTRACT_MISMATCH", "Edition history item disappeared");
  requireEqual(edition.request_id, historyItem.request_id, "edition.request_id", "CONTRACT_MISMATCH");
  requireEqual(
    edition.edition_fingerprint,
    historyItem.edition_fingerprint,
    "edition.edition_fingerprint",
    "CONTRACT_MISMATCH",
  );
  requireEqual(edition.state, historyItem.state, "edition.state", "CONTRACT_MISMATCH");
  requireEqual(
    edition.segment_count,
    historyItem.total_segment_count,
    "edition.segment_count",
    "CONTRACT_MISMATCH",
  );
  requireEqual(
    edition.current_manifest_revision,
    historyItem.manifest_revision,
    "edition.current_manifest_revision",
    "CONTRACT_MISMATCH",
  );
  if (edition.current_manifest_revision === null) {
    fail("CONTRACT_MISMATCH", "active Edition has no Manifest revision");
  }
}


function scriptScope(context: DocumentNarrationContext): ScriptReviewDocumentScope {
  const source = context.source_snapshot;
  if (!source) fail("CONTRACT_MISMATCH", "script scope lacks source snapshot");
  return Object.freeze({
    novel_id: context.novel_id,
    document_id: context.document_id,
    revision_id: source.revision_id,
    source_content_hash: source.content_hash,
  });
}


function validateScript(
  context: DocumentNarrationContext,
  edition: NarrationEditionResource,
  script: ScriptReviewResource,
): void {
  requireEqual(script.novel_id, context.novel_id, "script.novel_id");
  requireEqual(script.document_id, context.document_id, "script.document_id");
  requireEqual(
    script.script_version_id,
    edition.script_version_id,
    "script.script_version_id",
  );
  const source = context.source_snapshot;
  if (!source) fail("CONTRACT_MISMATCH", "script has no source snapshot authority");
  requireEqual(script.revision_id, source.revision_id, "script.revision_id");
  requireEqual(script.source_content_hash, source.content_hash, "script.source_content_hash");
  if (script.state !== "approved" || script.approval === null) {
    fail("CONTRACT_MISMATCH", "Edition must reference an approved ScriptVersion");
  }
  if (script.segments.length !== edition.segment_count) {
    fail("CONTRACT_MISMATCH", "script segment count differs from Edition");
  }
}


function validateManifestIdentity(
  context: DocumentNarrationContext,
  edition: NarrationEditionResource,
  script: ScriptReviewResource,
  manifest: NarrationManifestV2,
  options: Readonly<{ initial: boolean }>,
): void {
  requireEqual(manifest.edition_id, edition.edition_id, "manifest.edition_id");
  requireEqual(manifest.chapter_id, context.document_id, "manifest.chapter_id");
  requireEqual(manifest.source_revision_id, script.revision_id, "manifest.source_revision_id");
  requireEqual(manifest.source_sha256, script.source_content_hash, "manifest.source_sha256");
  if (options.initial) {
    requireEqual(
      manifest.manifest_revision,
      edition.current_manifest_revision,
      "manifest.manifest_revision",
      "CONTRACT_MISMATCH",
    );
    const historyItem = context.edition_history.editions.find(
      (item) => item.edition_id === edition.edition_id,
    );
    requireEqual(
      manifest.etag,
      historyItem?.manifest_etag,
      "manifest.etag",
      "CONTRACT_MISMATCH",
    );
  }
}


function buildSegments(
  edition: NarrationEditionResource,
  script: ScriptReviewResource,
  manifest: NarrationManifestV2,
): Pick<ChapterNarrationBundle, "bridgeSegments" | "paragraphs" | "segmentById"> {
  if (
    manifest.segments.length !== edition.segment_count
    || script.segments.length !== manifest.segments.length
  ) {
    fail("CONTRACT_MISMATCH", "Edition, script, and Manifest segment counts differ");
  }
  const ids = new Set<string>();
  const paragraphBlocks = new Map<
    number,
    { sourceBlockKey: string; startUtf16: number; endUtf16: number }
  >();
  const bridgeSegments: NarrationSourceSegment[] = [];
  const entries: Array<[string, ChapterNarrationBundleSegment]> = [];
  let previousEndUtf16 = 0;
  let previousParagraphOrdinal = -1;
  for (let index = 0; index < manifest.segments.length; index += 1) {
    const manifestSegment = manifest.segments[index];
    const scriptSegment = script.segments[index];
    if (
      manifestSegment.ordinal !== index
      || scriptSegment.ordinal !== index
      || manifestSegment.segment_id !== scriptSegment.segment_id
    ) {
      fail("CONTRACT_MISMATCH", `segment ${index} identity or order drifted`);
    }
    if (ids.has(manifestSegment.segment_id)) {
      fail("CONTRACT_MISMATCH", "duplicate segment ID");
    }
    if (manifestSegment.paragraph_ordinal < previousParagraphOrdinal) {
      fail("CONTRACT_MISMATCH", `segment ${index} paragraph order drifted`);
    }
    ids.add(manifestSegment.segment_id);
    if (
      scriptSegment.source_start_utf16 === null
      || scriptSegment.source_end_utf16 === null
      || !scriptSegment.source_block_key.trim()
      || scriptSegment.source_start_utf16 < 0
      || scriptSegment.source_end_utf16 <= scriptSegment.source_start_utf16
      || scriptSegment.source_start_utf16 < previousEndUtf16
      || scriptSegment.source_text.length
        !== scriptSegment.source_end_utf16 - scriptSegment.source_start_utf16
    ) {
      fail("CONTRACT_MISMATCH", `segment ${index} lacks a complete source anchor`);
    }
    previousEndUtf16 = scriptSegment.source_end_utf16;
    previousParagraphOrdinal = manifestSegment.paragraph_ordinal;
    if (
      manifestSegment.source_block_key !== scriptSegment.source_block_key
      || manifestSegment.source_start_utf16 !== scriptSegment.source_start_utf16
      || manifestSegment.source_end_utf16 !== scriptSegment.source_end_utf16
    ) {
      fail("CONTRACT_MISMATCH", `segment ${index} source anchor drifted`);
    }
    const bridgeSegment = Object.freeze({
      segmentId: scriptSegment.segment_id,
      sourceBlockKey: scriptSegment.source_block_key,
      sourceRange: Object.freeze({
        startUtf16: scriptSegment.source_start_utf16,
        endUtf16: scriptSegment.source_end_utf16,
      }),
      sourceText: scriptSegment.source_text,
    });
    bridgeSegments.push(bridgeSegment);
    entries.push([
      scriptSegment.segment_id,
      Object.freeze({ script: scriptSegment, manifest: manifestSegment }),
    ]);
    const paragraph = paragraphBlocks.get(manifestSegment.paragraph_ordinal);
    if (paragraph && paragraph.sourceBlockKey !== scriptSegment.source_block_key) {
      fail("CONTRACT_MISMATCH", "one paragraph ordinal maps to multiple source blocks");
    }
    if (paragraph) {
      paragraph.startUtf16 = Math.min(paragraph.startUtf16, scriptSegment.source_start_utf16);
      paragraph.endUtf16 = Math.max(paragraph.endUtf16, scriptSegment.source_end_utf16);
    } else {
      paragraphBlocks.set(manifestSegment.paragraph_ordinal, {
        sourceBlockKey: scriptSegment.source_block_key,
        startUtf16: scriptSegment.source_start_utf16,
        endUtf16: scriptSegment.source_end_utf16,
      });
    }
  }
  const paragraphs = [...paragraphBlocks.entries()]
    .sort(([left], [right]) => left - right)
    .map(([paragraphOrdinal, value]) => Object.freeze({
      paragraphOrdinal,
      sourceBlockKey: value.sourceBlockKey,
      range: Object.freeze({
        startUtf16: value.startUtf16,
        endUtf16: value.endUtf16,
      }),
      narratable: true,
    }));
  return Object.freeze({
    bridgeSegments: Object.freeze(bridgeSegments),
    paragraphs: Object.freeze(paragraphs),
    segmentById: new Map(entries),
  });
}


function assembleBundle(
  context: DocumentNarrationContext,
  edition: NarrationEditionResource,
  script: ScriptReviewResource,
  manifest: NarrationManifestV2,
): ChapterNarrationBundle {
  validateScript(context, edition, script);
  validateManifestIdentity(context, edition, script, manifest, { initial: true });
  const renderCounts = manifest.segments.reduce((counts, segment) => {
    counts[segment.render_status] += 1;
    return counts;
  }, {
    pending: 0,
    queued: 0,
    rendering: 0,
    ready: 0,
    failed: 0,
    cancelled: 0,
  });
  requireEqual(edition.pending_segment_count, renderCounts.pending, "edition.pending_segment_count", "CONTRACT_MISMATCH");
  requireEqual(edition.queued_segment_count, renderCounts.queued, "edition.queued_segment_count", "CONTRACT_MISMATCH");
  requireEqual(edition.rendering_segment_count, renderCounts.rendering, "edition.rendering_segment_count", "CONTRACT_MISMATCH");
  requireEqual(edition.ready_segment_count, renderCounts.ready, "edition.ready_segment_count", "CONTRACT_MISMATCH");
  requireEqual(edition.failed_segment_count, renderCounts.failed, "edition.failed_segment_count", "CONTRACT_MISMATCH");
  const historyItem = context.edition_history.editions.find(
    (item) => item.edition_id === edition.edition_id,
  );
  requireEqual(
    historyItem?.ready_segment_count,
    renderCounts.ready,
    "edition_history.ready_segment_count",
    "CONTRACT_MISMATCH",
  );
  const mapped = buildSegments(edition, script, manifest);
  return Object.freeze({ context, edition, script, manifest, ...mapped });
}


async function loadBundleWithDependencies(
  options: LoadChapterNarrationBundleOptions,
  dependencies: ChapterNarrationNetworkDependencies,
): Promise<ChapterNarrationBundleLoadResult> {
  uuid(options.novelId, "novelId");
  const documentId = uuid(options.documentId, "documentId");
  generation(options.generation);
  ensureGenerationCurrent(options);
  const context = await dependencies.getDocumentNarrationContext(
    documentId,
    options.activeEditionId,
    options.signal,
  );
  ensureGenerationCurrent(options);
  const activeEditionId = validateContext(context, options);
  if (activeEditionId === null) {
    return Object.freeze({ status: "no-edition", context });
  }
  const edition = await dependencies.getNarrationEdition(
    activeEditionId,
    options.signal,
  );
  ensureGenerationCurrent(options);
  validateEdition(context, edition, activeEditionId);
  const expectedScope = scriptScope(context);
  const script = await dependencies.getNarrationScriptVersionForEdition(
    edition.script_version_id,
    expectedScope,
    options.signal,
  );
  ensureGenerationCurrent(options);
  validateScript(context, edition, script);
  const manifestResult = await dependencies.getNarrationManifest(edition.edition_id, {
    manifestRevision: edition.current_manifest_revision ?? undefined,
    signal: options.signal,
  });
  ensureGenerationCurrent(options);
  if (manifestResult.not_modified || manifestResult.manifest === null) {
    fail("CONTRACT_MISMATCH", "initial Manifest request returned no payload");
  }
  requireEqual(
    manifestResult.etag,
    manifestResult.manifest.etag,
    "Manifest response ETag",
    "CONTRACT_MISMATCH",
  );
  return Object.freeze({
    status: "ready",
    bundle: assembleBundle(context, edition, script, manifestResult.manifest),
  });
}


export function loadChapterNarrationBundle(
  options: LoadChapterNarrationBundleOptions,
): Promise<ChapterNarrationBundleLoadResult> {
  return loadBundleWithDependencies(options, DEFAULT_NETWORK);
}


export type ChapterNarrationSessionPhase =
  | "idle"
  | "loading"
  | "no-edition"
  | "ready"
  | "error"
  | "disposed";


export type ChapterNarrationSessionPlayResult = Readonly<
  | { status: "completed"; decision: PlaybackDecision }
  | { status: "rejected"; reason: string }
  | { status: "superseded"; segmentId: string }
  | { status: "timeout"; segmentId: string; attempts: number }
  | { status: "error"; segmentId: string; error: unknown }
>;


export interface ChapterNarrationSessionSnapshot {
  readonly phase: ChapterNarrationSessionPhase;
  readonly loadResult: ChapterNarrationBundleLoadResult | null;
  readonly bundle: ChapterNarrationBundle | null;
  readonly playerState: NarrationPlayerState | null;
  readonly pollingSegmentId: string | null;
  readonly lastPlayResult: ChapterNarrationSessionPlayResult | null;
  readonly error: unknown | null;
  readonly workingCopyDiverged: boolean;
  readonly mappedSegmentIds: readonly string[];
}


export interface ChapterNarrationSessionOptions {
  readonly novelId: string;
  readonly documentId: string;
  readonly generation: number;
  readonly activeEditionId?: string;
  readonly profileId?: string;
  readonly bridge: NarrationEditorBridge;
  readonly isGenerationCurrent: (documentId: string, generation: number) => boolean;
  readonly onState?: (snapshot: ChapterNarrationSessionSnapshot) => void;
  readonly pollScheduleMs?: readonly number[];
  readonly pollTimeoutMs?: number;
  readonly maxPollAttempts?: number;
  readonly dependencies?: ChapterNarrationSessionDependencies;
}


export interface ChapterNarrationSession {
  readonly player: NarrationPlayerController | null;
  readonly coordinator: ChapterPlaybackCoordinator | null;
  readonly follow: SegmentFollowController | null;
  load(activeEditionId?: string): Promise<ChapterNarrationBundleLoadResult>;
  refresh(): Promise<ChapterNarrationBundleLoadResult>;
  readSnapshot(): ChapterNarrationSessionSnapshot;
  playSegment(
    segmentId: string,
    source?: "gutter" | "command" | "readonly-segment",
    startOffsetMs?: number,
  ): Promise<ChapterNarrationSessionPlayResult>;
  pause(): void;
  resume(): Promise<ChapterNarrationSessionPlayResult>;
  setRate(rate: number): void;
  noteAuthorInteraction(interruption: AuthorFollowInterruption): boolean;
  noteWorkingCopyChanged(): boolean;
  resumeFollow(): boolean;
  dispose(): void;
}


function frozenSnapshot(
  value: ChapterNarrationSessionSnapshot,
): ChapterNarrationSessionSnapshot {
  return Object.freeze({ ...value });
}


function asError(reason: unknown): Error {
  return reason instanceof Error ? reason : new Error(String(reason));
}


function isAbort(reason: unknown): boolean {
  return reason instanceof Error && reason.name === "AbortError";
}


function validatePollOptions(options: ChapterNarrationSessionOptions): {
  schedule: readonly number[];
  timeout: number;
  attempts: number;
} {
  const schedule = options.pollScheduleMs ?? DEFAULT_POLL_SCHEDULE_MS;
  if (
    schedule.length === 0
    || schedule.some((value) => !Number.isSafeInteger(value) || value < 1)
  ) {
    fail("INVALID_INPUT", "pollScheduleMs must contain positive safe integers");
  }
  const timeout = options.pollTimeoutMs ?? DEFAULT_POLL_TIMEOUT_MS;
  const attempts = options.maxPollAttempts ?? DEFAULT_MAX_POLL_ATTEMPTS;
  if (!Number.isSafeInteger(timeout) || timeout < 1) {
    fail("INVALID_INPUT", "pollTimeoutMs must be a positive safe integer");
  }
  if (!Number.isSafeInteger(attempts) || attempts < 1) {
    fail("INVALID_INPUT", "maxPollAttempts must be a positive safe integer");
  }
  return { schedule: Object.freeze([...schedule]), timeout, attempts };
}


type PendingProgressSave = Readonly<{
  runtimeEpoch: number;
  editionId: string;
  request: Omit<SavePlaybackProgressRequest, "expected_updated_at">;
}>;


export class ProductionChapterNarrationSession implements ChapterNarrationSession {
  private readonly dependencies: ChapterNarrationSessionDependencies;
  private readonly pollSchedule: readonly number[];
  private readonly pollTimeoutMs: number;
  private readonly maxPollAttempts: number;
  private readonly profileId: string;
  private currentPlayer: FollowAwareNarrationPlayerController | null = null;
  private currentCoordinator: ChapterPlaybackCoordinator | null = null;
  private currentFollow: SegmentFollowController | null = null;
  private unsubscribePlayer: (() => void) | null = null;
  private currentBundle: ChapterNarrationBundle | null = null;
  private requestedActiveEditionId: string | undefined;
  private loadAbort: AbortController | null = null;
  private pollAbort: AbortController | null = null;
  private loadSequence = 0;
  private playSequence = 0;
  private liveDivergenceObserved = false;
  private runtimeEpoch = 0;
  private progressSaveTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingProgressSave: PendingProgressSave | null = null;
  private progressSaveInFlight = false;
  private readonly progressCasTokens = new Map<string, string | null>();
  private disposed = false;
  private snapshot: ChapterNarrationSessionSnapshot = frozenSnapshot({
    phase: "idle",
    loadResult: null,
    bundle: null,
    playerState: null,
    pollingSegmentId: null,
    lastPlayResult: null,
    error: null,
    workingCopyDiverged: false,
    mappedSegmentIds: Object.freeze([]),
  });

  constructor(private readonly options: ChapterNarrationSessionOptions) {
    uuid(options.novelId, "novelId");
    uuid(options.documentId, "documentId");
    generation(options.generation);
    if (
      options.bridge.lease.documentId !== options.documentId
      || options.bridge.lease.generation !== options.generation
    ) {
      fail("SCOPE_MISMATCH", "bridge lease differs from the chapter session");
    }
    const poll = validatePollOptions(options);
    this.pollSchedule = poll.schedule;
    this.pollTimeoutMs = poll.timeout;
    this.maxPollAttempts = poll.attempts;
    this.dependencies = options.dependencies ?? DEFAULT_DEPENDENCIES;
    this.profileId = parsePlaybackProfileId(
      options.profileId ?? DEFAULT_PLAYBACK_PROFILE_ID,
      "profileId",
    );
    this.requestedActiveEditionId = options.activeEditionId;
  }

  get player(): NarrationPlayerController | null { return this.currentPlayer; }
  get coordinator(): ChapterPlaybackCoordinator | null { return this.currentCoordinator; }
  get follow(): SegmentFollowController | null { return this.currentFollow; }

  readSnapshot(): ChapterNarrationSessionSnapshot {
    return this.snapshot;
  }

  async load(activeEditionId = this.requestedActiveEditionId): Promise<ChapterNarrationBundleLoadResult> {
    this.assertNotDisposed();
    this.requestedActiveEditionId = activeEditionId;
    const sequence = ++this.loadSequence;
    ++this.playSequence;
    this.loadAbort?.abort("superseded");
    this.cancelPolling();
    this.flushProgressSave();
    this.runtimeEpoch += 1;
    this.teardownRuntime();
    const controller = new AbortController();
    this.loadAbort = controller;
    this.publish({
      phase: "loading",
      loadResult: null,
      bundle: null,
      playerState: null,
      pollingSegmentId: null,
      lastPlayResult: null,
      error: null,
      workingCopyDiverged: false,
      mappedSegmentIds: Object.freeze([]),
    });
    try {
      const result = await loadBundleWithDependencies({
        novelId: this.options.novelId,
        documentId: this.options.documentId,
        generation: this.options.generation,
        activeEditionId,
        signal: controller.signal,
        isGenerationCurrent: this.options.isGenerationCurrent,
      }, this.dependencies);
      if (!this.isLoadCurrent(sequence, controller)) throw abortError("load superseded");
      if (result.status === "no-edition") {
        this.loadAbort = null;
        this.publish({
          phase: "no-edition",
          loadResult: result,
          bundle: null,
          playerState: null,
          error: null,
          workingCopyDiverged: false,
          mappedSegmentIds: Object.freeze([]),
        });
        return result;
      }
      let bundle = result.bundle;
      let restoredProgress: PlaybackProgressProjection | null = null;
      try {
        const restored = await this.restoreProgress(bundle, sequence, controller);
        bundle = restored.bundle;
        restoredProgress = restored.progress;
      } catch (reason) {
        if (isAbort(reason)) throw reason;
        // Progress is derivative convenience state. It cannot block the exact
        // Edition/script/Manifest bundle from becoming available.
      }
      if (!this.isLoadCurrent(sequence, controller)) throw abortError("load superseded");
      const readyResult = Object.freeze({ status: "ready", bundle } as const);
      this.installBundle(bundle, restoredProgress);
      const liveProjection = this.readLiveWorkingCopyProjection(bundle);
      this.publish({
        phase: "ready",
        loadResult: readyResult,
        bundle,
        playerState: this.currentPlayer?.readState() ?? null,
        error: null,
        ...liveProjection,
      });
      this.loadAbort = null;
      return readyResult;
    } catch (reason) {
      if (this.isLoadCurrent(sequence, controller)) {
        controller.abort("load_failed");
        this.loadAbort = null;
        this.teardownRuntime();
        this.publish({ phase: "error", error: asError(reason) });
      }
      throw reason;
    }
  }

  refresh(): Promise<ChapterNarrationBundleLoadResult> {
    return this.load(this.requestedActiveEditionId);
  }

  async playSegment(
    segmentId: string,
    source: "gutter" | "command" | "readonly-segment" = "readonly-segment",
    startOffsetMs = 0,
  ): Promise<ChapterNarrationSessionPlayResult> {
    this.assertReady();
    if (!this.currentBundle?.segmentById.has(segmentId)) {
      return this.recordPlay(
        { status: "rejected", reason: "segment_not_in_bundle" },
        this.playSequence,
      );
    }
    const sequence = ++this.playSequence;
    this.cancelPolling();
    const initial = await this.issuePlayback(segmentId, source, sequence, startOffsetMs);
    if (initial.status !== "completed" || initial.decision.kind !== "preparing") {
      return this.recordPlay(initial, sequence);
    }
    return this.pollPreparedTarget(segmentId, source, sequence, startOffsetMs);
  }

  pause(): void {
    this.assertReady();
    ++this.playSequence;
    this.cancelPolling();
    this.currentPlayer?.pause();
    this.publish({ pollingSegmentId: null });
  }

  async resume(): Promise<ChapterNarrationSessionPlayResult> {
    this.assertReady();
    const player = this.currentPlayer;
    if (!player) fail("SESSION_NOT_READY", "session player is unavailable");
    const sequence = ++this.playSequence;
    this.cancelPolling();
    const decision = await player.resume();
    if (sequence !== this.playSequence) {
      return this.recordPlay({
        status: "superseded",
        segmentId: decision.kind === "preparing" ? decision.segmentId : "resume",
      }, sequence);
    }
    if (decision.kind !== "preparing") {
      return this.recordPlay({ status: "completed", decision }, sequence);
    }
    return this.pollPreparedTarget(decision.segmentId, "readonly-segment", sequence);
  }

  setRate(rate: number): void {
    this.assertReady();
    this.currentPlayer?.setRate(rate);
  }

  noteAuthorInteraction(interruption: AuthorFollowInterruption): boolean {
    this.assertReady();
    return this.currentFollow?.noteAuthorInteraction(interruption) ?? false;
  }

  noteWorkingCopyChanged(): boolean {
    if (
      this.disposed
      || !this.isSessionCurrent()
    ) return false;
    this.liveDivergenceObserved = true;
    if (this.snapshot.phase !== "ready" || !this.currentBundle) return true;
    const projection = this.readLiveWorkingCopyProjection(this.currentBundle);
    if (
      projection.workingCopyDiverged === this.snapshot.workingCopyDiverged
      && projection.mappedSegmentIds.length === this.snapshot.mappedSegmentIds.length
      && projection.mappedSegmentIds.every(
        (segmentId, index) => segmentId === this.snapshot.mappedSegmentIds[index],
      )
    ) return true;
    this.publish(projection);
    return true;
  }

  resumeFollow(): boolean {
    this.assertReady();
    return this.currentFollow?.resumeExplicitly() ?? false;
  }

  dispose(): void {
    if (this.disposed) return;
    this.flushProgressSave();
    this.disposed = true;
    this.runtimeEpoch += 1;
    ++this.loadSequence;
    ++this.playSequence;
    this.loadAbort?.abort("disposed");
    this.loadAbort = null;
    this.cancelPolling();
    this.teardownRuntime();
    this.publish({
      phase: "disposed",
      loadResult: null,
      bundle: null,
      playerState: null,
      pollingSegmentId: null,
      error: null,
      workingCopyDiverged: false,
      mappedSegmentIds: Object.freeze([]),
    });
  }

  private installBundle(
    bundle: ChapterNarrationBundle,
    restoredProgress: PlaybackProgressProjection | null,
  ): void {
    const currentSource = bundle.script.source_content_hash
      === bundle.context.working_copy_content_hash;
    this.unbindBridge();
    if (currentSource) {
      const text = this.options.bridge.readSnapshot().text;
      const visibleTextMatchesSource = bundle.bridgeSegments.every((segment) => (
        segment.sourceRange.endUtf16 <= text.length
        && text.slice(segment.sourceRange.startUtf16, segment.sourceRange.endUtf16)
          === segment.sourceText
      ));
      const bound = this.options.bridge.bindEdition({
        lease: this.options.bridge.lease,
        editionId: bundle.edition.edition_id,
        sourceRevisionId: bundle.script.revision_id,
        sourceContentHash: bundle.script.source_content_hash,
        segments: bundle.bridgeSegments,
      });
      if (!bound.applied) {
        fail("STALE_GENERATION", `bridge rejected Edition binding: ${bound.reason}`);
      }
      const boundSnapshot = this.options.bridge.readSnapshot();
      if (boundSnapshot.edition?.editionId !== bundle.edition.edition_id) {
        fail("CONTRACT_MISMATCH", "Bridge did not confirm the exact current source");
      }
      if (
        visibleTextMatchesSource
        && !boundSnapshot.exactEditionText
        && !this.liveDivergenceObserved
      ) {
        fail("CONTRACT_MISMATCH", "Bridge did not confirm the exact current source");
      }
    }
    const player = this.dependencies.createPlayer({
      documentId: this.options.documentId,
      documentGeneration: this.options.generation,
      editionId: bundle.edition.edition_id,
      initialManifest: bundle.manifest,
      rate: restoredProgress ? restoredProgress.playback_rate_millis / 1_000 : 1,
      initialPosition: restoredProgress ? {
        segmentId: restoredProgress.segment_id,
        ordinal: restoredProgress.ordinal,
        offsetMs: restoredProgress.offset_ms,
      } : undefined,
      isDocumentLeaseCurrent: (documentId, documentGeneration) => (
        this.isSessionCurrent()
        && documentId === this.options.documentId
        && documentGeneration === this.options.generation
      ),
      prepareRange: this.dependencies.prepareNarrationRange,
    });
    this.currentBundle = bundle;
    this.currentPlayer = player;
    const fence = (lease: PlaybackLease) => this.isPlaybackFenceCurrent(lease);
    this.currentCoordinator = createChapterPlaybackCoordinator({
      bridge: this.options.bridge,
      player,
      isPlaybackLeaseCurrent: fence,
    });
    this.currentFollow = createSegmentFollowController({
      bridge: this.options.bridge,
      player,
      editionId: bundle.edition.edition_id,
      isPlaybackLeaseCurrent: fence,
    });
    let previousState = player.readState();
    this.unsubscribePlayer = player.subscribe(() => {
      if (player !== this.currentPlayer || this.disposed) return;
      const nextState = player.readState();
      this.publish({ playerState: nextState });
      if (
        nextState.currentSegmentId !== null
        && (
          (previousState.phase !== "paused" && nextState.phase === "paused")
          || previousState.currentSegmentId !== nextState.currentSegmentId
          || previousState.offsetMs !== nextState.offsetMs
          || previousState.rate !== nextState.rate
          || (previousState.phase !== "ended" && nextState.phase === "ended")
        )
      ) {
        this.scheduleProgressSave();
      }
      previousState = nextState;
    });
  }

  private async issuePlayback(
    segmentId: string,
    source: "gutter" | "command" | "readonly-segment",
    sequence: number,
    startOffsetMs = 0,
  ): Promise<ChapterNarrationSessionPlayResult> {
    const player = this.currentPlayer;
    const bundle = this.currentBundle;
    if (!player || !bundle) {
      return { status: "rejected", reason: "session_not_ready" };
    }
    const bridgeBound = this.options.bridge.readSnapshot().edition?.editionId
      === bundle.edition.edition_id;
    if (bridgeBound && this.currentCoordinator && startOffsetMs === 0) {
      const result = await this.currentCoordinator.requestPlayback({
        source,
        lookup: { segmentId },
      });
      if (sequence !== this.playSequence) return { status: "superseded", segmentId };
      return this.coordinatorResult(result, segmentId);
    }
    const decision = await player.playFromSegment(
      segmentId,
      source as NarrationPlaybackSource,
      startOffsetMs,
    );
    if (sequence !== this.playSequence) return { status: "superseded", segmentId };
    return { status: "completed", decision };
  }

  private coordinatorResult(
    result: ChapterPlaybackRequestResult,
    segmentId: string,
  ): ChapterNarrationSessionPlayResult {
    if (result.status === "completed") {
      return { status: "completed", decision: result.decision };
    }
    if (result.status === "stale") return { status: "superseded", segmentId };
    if (result.status === "failed") {
      return { status: "error", segmentId, error: result.error };
    }
    return { status: "rejected", reason: result.reason };
  }

  private async pollPreparedTarget(
    segmentId: string,
    source: "gutter" | "command" | "readonly-segment",
    sequence: number,
    startOffsetMs = 0,
  ): Promise<ChapterNarrationSessionPlayResult> {
    const controller = new AbortController();
    this.pollAbort = controller;
    const startedAt = this.dependencies.now();
    let attempts = 0;
    let timedOut = false;
    const timeoutHandle = setTimeout(() => {
      timedOut = true;
      controller.abort("poll_timeout");
    }, this.pollTimeoutMs);
    this.publish({ pollingSegmentId: segmentId });
    try {
      while (attempts < this.maxPollAttempts) {
        if (!this.isPlayCurrent(sequence, segmentId, controller)) {
          return this.recordPlay({ status: "superseded", segmentId }, sequence);
        }
        const elapsed = this.dependencies.now() - startedAt;
        if (elapsed >= this.pollTimeoutMs) {
          return this.recordPlay({ status: "timeout", segmentId, attempts }, sequence);
        }
        const delay = this.pollSchedule[Math.min(attempts, this.pollSchedule.length - 1)];
        await this.dependencies.delay(delay, controller.signal);
        if (!this.isPlayCurrent(sequence, segmentId, controller)) {
          return this.recordPlay({ status: "superseded", segmentId }, sequence);
        }
        attempts += 1;
        if (this.dependencies.now() - startedAt >= this.pollTimeoutMs) {
          return this.recordPlay({ status: "timeout", segmentId, attempts }, sequence);
        }
        const bundle = this.currentBundle;
        const player = this.currentPlayer;
        if (!bundle || !player) {
          return this.recordPlay({ status: "superseded", segmentId }, sequence);
        }
        const fetched = await awaitWithAbort(
          this.dependencies.getNarrationManifest(
            bundle.edition.edition_id,
            { ifNoneMatch: bundle.manifest.etag, signal: controller.signal },
          ),
          controller.signal,
        );
        if (
          !this.isPlayCurrent(sequence, segmentId, controller)
          || bundle !== this.currentBundle
          || player !== this.currentPlayer
        ) {
          return this.recordPlay({ status: "superseded", segmentId }, sequence);
        }
        if (!fetched.not_modified && fetched.manifest) {
          this.adoptPolledManifest(fetched, bundle, player);
        } else if (fetched.etag !== bundle.manifest.etag) {
          fail("CONTRACT_MISMATCH", "not-modified Manifest ETag changed");
        }
        const current = this.currentBundle;
        if (!current) return this.recordPlay({ status: "superseded", segmentId }, sequence);
        const plan = decideManifestPlayback(current.manifest, segmentId);
        if (plan.kind === "prepare") continue;
        const replay = await this.issuePlayback(segmentId, source, sequence, startOffsetMs);
        return this.recordPlay(replay, sequence);
      }
      return this.recordPlay({ status: "timeout", segmentId, attempts }, sequence);
    } catch (reason) {
      if (isAbort(reason)) {
        if (timedOut && !this.disposed && sequence === this.playSequence) {
          return this.recordPlay({ status: "timeout", segmentId, attempts }, sequence);
        }
        return this.recordPlay({ status: "superseded", segmentId }, sequence);
      }
      return this.recordPlay({ status: "error", segmentId, error: reason }, sequence);
    } finally {
      clearTimeout(timeoutHandle);
      if (this.pollAbort === controller) this.pollAbort = null;
      if (!this.disposed && sequence === this.playSequence) {
        this.publish({ pollingSegmentId: null });
      }
    }
  }

  private async restoreProgress(
    bundle: ChapterNarrationBundle,
    sequence: number,
    controller: AbortController,
  ): Promise<Readonly<{
    bundle: ChapterNarrationBundle;
    progress: PlaybackProgressProjection | null;
  }>> {
    const response = await this.dependencies.getNarrationPlaybackProgress(
      bundle.edition.edition_id,
      this.profileId,
      { signal: controller.signal },
    );
    if (!this.isLoadCurrent(sequence, controller)) throw abortError("load superseded");
    requireEqual(
      response.edition_id,
      bundle.edition.edition_id,
      "playback progress Edition",
      "CONTRACT_MISMATCH",
    );
    requireEqual(
      response.profile_id,
      this.profileId,
      "playback progress profile",
      "CONTRACT_MISMATCH",
    );
    const progress = response.progress;
    this.progressCasTokens.set(
      bundle.edition.edition_id,
      progress?.progress_updated_at ?? null,
    );
    if (progress === null || progress.manifest_revision < bundle.manifest.manifest_revision) {
      return Object.freeze({ bundle, progress: null });
    }

    let restoredBundle = bundle;
    if (progress.manifest_revision > bundle.manifest.manifest_revision) {
      const fetched = await this.dependencies.getNarrationManifest(
        bundle.edition.edition_id,
        { manifestRevision: progress.manifest_revision, signal: controller.signal },
      );
      if (!this.isLoadCurrent(sequence, controller)) throw abortError("load superseded");
      if (fetched.not_modified || fetched.manifest === null) {
        fail("CONTRACT_MISMATCH", "restore Manifest request returned no payload");
      }
      requireEqual(fetched.etag, progress.manifest_etag, "restore Manifest ETag", "CONTRACT_MISMATCH");
      requireEqual(fetched.manifest.etag, progress.manifest_etag, "restore Manifest payload ETag", "CONTRACT_MISMATCH");
      validateManifestIdentity(bundle.context, bundle.edition, bundle.script, fetched.manifest, {
        initial: false,
      });
      const mapped = buildSegments(bundle.edition, bundle.script, fetched.manifest);
      restoredBundle = Object.freeze({ ...bundle, manifest: fetched.manifest, ...mapped });
    } else {
      requireEqual(
        progress.manifest_etag,
        bundle.manifest.etag,
        "restore Manifest ETag",
        "CONTRACT_MISMATCH",
      );
    }

    const segment = restoredBundle.manifest.segments[progress.ordinal];
    const readyRange = restoredBundle.manifest.ready_ranges.find((range) => (
      range.start_ordinal <= progress.ordinal
      && progress.ordinal < range.end_ordinal_exclusive
    ));
    if (
      !segment
      || segment.segment_id !== progress.segment_id
      || segment.render_status !== "ready"
      || !segment.audio
      || progress.offset_ms > segment.audio.duration_ms
      || !readyRange
      || progress.last_legal_start_ordinal < readyRange.start_ordinal
      || progress.last_legal_start_ordinal >= readyRange.end_ordinal_exclusive
      || progress.last_legal_start_ordinal > readyRange.last_playable_start_ordinal
      || progress.last_legal_start_ordinal > progress.ordinal
    ) {
      fail("CONTRACT_MISMATCH", "saved playback position is unavailable in the exact Edition");
    }
    return Object.freeze({ bundle: restoredBundle, progress });
  }

  private scheduleProgressSave(): void {
    const bundle = this.currentBundle;
    const state = this.currentPlayer?.readState();
    if (
      !bundle
      || !state
      || state.currentSegmentId === null
      || state.currentOrdinal === null
      || !this.isSessionCurrent()
    ) return;
    const segment = bundle.manifest.segments[state.currentOrdinal];
    const readyRange = bundle.manifest.ready_ranges.find((range) => (
      range.start_ordinal <= state.currentOrdinal!
      && state.currentOrdinal! < range.end_ordinal_exclusive
    ));
    if (
      !segment
      || segment.segment_id !== state.currentSegmentId
      || segment.render_status !== "ready"
      || !segment.audio
      || !readyRange
    ) return;
    const offsetMs = Math.max(0, Math.min(segment.audio.duration_ms, Math.round(state.offsetMs)));
    const playbackRateMillis = Math.round(state.rate * 1_000);
    if (playbackRateMillis < 250 || playbackRateMillis > 4_000) return;
    this.pendingProgressSave = Object.freeze({
      runtimeEpoch: this.runtimeEpoch,
      editionId: bundle.edition.edition_id,
      request: Object.freeze({
        profile_id: this.profileId,
        manifest_revision: bundle.manifest.manifest_revision,
        manifest_etag: bundle.manifest.etag,
        segment_id: segment.segment_id,
        offset_ms: offsetMs,
        last_legal_start_ordinal: Math.min(
          state.currentOrdinal,
          readyRange.last_playable_start_ordinal,
        ),
        playback_rate_millis: playbackRateMillis,
      }),
    });
    if (this.progressSaveTimer !== null) clearTimeout(this.progressSaveTimer);
    this.progressSaveTimer = setTimeout(() => {
      this.progressSaveTimer = null;
      void this.pumpProgressSave();
    }, PROGRESS_SAVE_DEBOUNCE_MS);
  }

  private flushProgressSave(): void {
    const player = this.currentPlayer;
    if (player && ["playing", "buffering"].includes(player.readState().phase)) player.pause();
    this.scheduleProgressSave();
    if (this.progressSaveTimer !== null) {
      clearTimeout(this.progressSaveTimer);
      this.progressSaveTimer = null;
    }
    void this.pumpProgressSave();
  }

  private async pumpProgressSave(): Promise<void> {
    if (this.progressSaveInFlight || this.pendingProgressSave === null) return;
    const pending = this.pendingProgressSave;
    this.pendingProgressSave = null;
    this.progressSaveInFlight = true;
    const expectedUpdatedAt = this.progressCasTokens.get(pending.editionId) ?? null;
    try {
      const response = await this.dependencies.putNarrationPlaybackProgress(
        pending.editionId,
        { ...pending.request, expected_updated_at: expectedUpdatedAt },
      );
      if (response.progress !== null) {
        this.progressCasTokens.set(pending.editionId, response.progress.progress_updated_at);
      }
    } catch (reason) {
      if (
        reason instanceof PlaybackApiError
        && reason.detail?.code === "MANIFEST_REVISION_CONFLICT"
      ) {
        try {
          const response = await this.dependencies.getNarrationPlaybackProgress(
            pending.editionId,
            this.profileId,
          );
          this.progressCasTokens.set(
            pending.editionId,
            response.progress?.progress_updated_at ?? null,
          );
        } catch {
          // A failed reconciliation never guesses another Edition or retries a stale write.
        }
      }
    } finally {
      this.progressSaveInFlight = false;
      if (this.pendingProgressSave !== null) void this.pumpProgressSave();
    }
  }

  private adoptPolledManifest(
    fetched: Extract<ManifestFetchResult, { not_modified: false }>,
    bundle: ChapterNarrationBundle,
    player: FollowAwareNarrationPlayerController,
  ): void {
    const manifest = fetched.manifest;
    requireEqual(
      fetched.etag,
      manifest.etag,
      "Manifest response ETag",
      "CONTRACT_MISMATCH",
    );
    if (manifest.manifest_revision < bundle.manifest.manifest_revision) {
      fail("CONTRACT_MISMATCH", "polled Manifest revision regressed");
    }
    if (
      manifest.manifest_revision === bundle.manifest.manifest_revision
      && manifest.etag !== bundle.manifest.etag
    ) {
      fail("CONTRACT_MISMATCH", "polled Manifest revision collided");
    }
    if (manifest.manifest_revision === bundle.manifest.manifest_revision) return;
    validateManifestIdentity(bundle.context, bundle.edition, bundle.script, manifest, {
      initial: false,
    });
    const mapped = buildSegments(bundle.edition, bundle.script, manifest);
    player.updateManifest(manifest);
    this.currentBundle = Object.freeze({ ...bundle, manifest, ...mapped });
    this.publish({
      bundle: this.currentBundle,
      loadResult: Object.freeze({ status: "ready", bundle: this.currentBundle }),
      playerState: player.readState(),
    });
  }

  private recordPlay(
    result: ChapterNarrationSessionPlayResult,
    sequence: number,
  ): ChapterNarrationSessionPlayResult {
    if (!this.disposed && sequence === this.playSequence) {
      this.publish({ lastPlayResult: result });
    }
    return Object.freeze(result);
  }

  private isLoadCurrent(sequence: number, controller: AbortController): boolean {
    return !this.disposed
      && sequence === this.loadSequence
      && this.loadAbort === controller
      && !controller.signal.aborted
      && this.isSessionCurrent();
  }

  private isPlayCurrent(
    sequence: number,
    segmentId: string,
    controller: AbortController,
  ): boolean {
    return !this.disposed
      && sequence === this.playSequence
      && this.pollAbort === controller
      && !controller.signal.aborted
      && this.currentBundle?.segmentById.has(segmentId) === true
      && this.isSessionCurrent();
  }

  private isSessionCurrent(): boolean {
    if (this.disposed) return false;
    try {
      return this.options.isGenerationCurrent(
        this.options.documentId,
        this.options.generation,
      );
    } catch {
      return false;
    }
  }

  private isPlaybackFenceCurrent(lease: PlaybackLease): boolean {
    const player = this.currentPlayer;
    const bundle = this.currentBundle;
    return player !== null
      && bundle !== null
      && this.isSessionCurrent()
      && lease.documentId === this.options.documentId
      && lease.documentGeneration === this.options.generation
      && lease.editionId === bundle.edition.edition_id
      && lease.manifestRevision === bundle.manifest.manifest_revision
      && playbackLeasesEqual(lease, player.lease);
  }

  private readLiveWorkingCopyProjection(
    bundle: ChapterNarrationBundle,
  ): Pick<ChapterNarrationSessionSnapshot, "workingCopyDiverged" | "mappedSegmentIds"> {
    if (
      !bundle.context.active_is_current
      || this.options.bridge.readSnapshot().edition?.editionId !== bundle.edition.edition_id
    ) {
      return Object.freeze({
        workingCopyDiverged: false,
        mappedSegmentIds: Object.freeze([]),
      });
    }
    const bridgeSnapshot = this.options.bridge.readSnapshot();
    const workingCopyDiverged = !bridgeSnapshot.exactEditionText;
    const mappedSegmentIds = workingCopyDiverged
      ? bundle.bridgeSegments
          .filter((segment) => this.options.bridge.mappingFor(segment.segmentId, {
            lease: this.options.bridge.lease,
            editionId: bundle.edition.edition_id,
          })?.state === "mapped")
          .map((segment) => segment.segmentId)
      : [];
    return Object.freeze({
      workingCopyDiverged,
      mappedSegmentIds: Object.freeze(mappedSegmentIds),
    });
  }

  private cancelPolling(): void {
    this.pollAbort?.abort("superseded");
    this.pollAbort = null;
  }

  private unbindBridge(): void {
    const editionId = this.options.bridge.readSnapshot().edition?.editionId;
    if (!editionId) return;
    this.options.bridge.unbindEdition({
      lease: this.options.bridge.lease,
      editionId,
    });
  }

  private teardownRuntime(): void {
    this.unsubscribePlayer?.();
    this.unsubscribePlayer = null;
    this.currentFollow?.dispose();
    this.currentFollow = null;
    this.currentCoordinator?.dispose();
    this.currentCoordinator = null;
    if (this.currentPlayer) {
      this.currentPlayer.pause();
      this.currentPlayer.dispose();
    }
    this.currentPlayer = null;
    this.currentBundle = null;
    this.unbindBridge();
  }

  private assertNotDisposed(): void {
    if (this.disposed) fail("SESSION_DISPOSED", "chapter narration session is disposed");
  }

  private assertReady(): void {
    this.assertNotDisposed();
    if (
      this.snapshot.phase !== "ready"
      || !this.currentBundle
      || !this.currentPlayer
      || !this.isSessionCurrent()
    ) {
      fail("SESSION_NOT_READY", "chapter narration session is not ready");
    }
  }

  private publish(patch: Partial<ChapterNarrationSessionSnapshot>): void {
    this.snapshot = frozenSnapshot({ ...this.snapshot, ...patch });
    try {
      this.options.onState?.(this.snapshot);
    } catch {
      // Presentation observers cannot change session authority or playback.
    }
  }
}


export function createChapterNarrationSession(
  options: ChapterNarrationSessionOptions,
): ChapterNarrationSession {
  return new ProductionChapterNarrationSession(options);
}
