import {
  EditionHistoryContractError,
  createEditionSwitchIntent,
  type DocumentEditionHistory,
  type EditionHistoryItem,
  type EditionSwitchIntent,
  type EditionSwitchMode,
} from "./edition-history";
import type { NarrationPlayerPhase } from "./narration-player";


export type ChapterDraftSaveState = "saved" | "dirty" | "saving" | "failed";
export type ChapterNarrationSourceStatus =
  | "no_current_edition"
  | "current"
  | "working_copy_diverged"
  | "superseded"
  | "unavailable";
export type ChapterTimelineMode =
  | "none"
  | "exact-working-copy"
  | "session-safe-mapping"
  | "immutable-edition-only";
export type ChapterPlayerPlacement = "full" | "compact-in-review" | "hidden";


export interface ChapterWorkingCopySnapshot {
  readonly documentId: string;
  readonly generation: number;
  readonly draftVersion: number;
  readonly contentHash: string;
  readonly saveState: ChapterDraftSaveState;
}


export interface EditionSubtitleSnapshot {
  readonly editionId: string;
  readonly segmentId: string;
  readonly ordinal: number;
  readonly speakerLabel: string;
  readonly sourceText: string;
  readonly spokenText: string;
}


export interface ActiveChapterPlayback {
  readonly editionId: string;
  readonly phase: NarrationPlayerPhase;
  readonly currentSegmentId: string | null;
  readonly currentOrdinal: number | null;
  readonly offsetMs: number;
  readonly durationMs: number;
  readonly subtitle: EditionSubtitleSnapshot | null;
}


export interface ScriptReviewSourceSnapshot {
  readonly revisionId: string;
  readonly contentHash: string;
}


export interface ChapterNarrationStateInput {
  readonly documentId: string;
  readonly generation: number;
  readonly history: DocumentEditionHistory;
  readonly workingCopy: ChapterWorkingCopySnapshot;
  readonly reviewOpen: boolean;
  readonly reviewSource: ScriptReviewSourceSnapshot | null;
  readonly playback: ActiveChapterPlayback | null;
  readonly sessionMappedSegmentIds?: ReadonlySet<string>;
  readonly liveWorkingCopyDiverged?: boolean;
}


export interface ChapterSourceNotice {
  readonly status: ChapterNarrationSourceStatus;
  readonly label: string;
  readonly revisionId: string | null;
  readonly contentHash: string | null;
}


export interface ChapterOldDraftSubtitle {
  readonly visible: boolean;
  readonly oldDraft: boolean;
  readonly segmentId: string | null;
  readonly ordinal: number | null;
  readonly speakerLabel: string | null;
  readonly sourceText: string | null;
  readonly spokenText: string | null;
}


export interface CompactNarrationPlayerView {
  readonly editionId: string;
  readonly sourceStatus: "current" | "working_copy_diverged" | "superseded";
  readonly oldDraft: boolean;
  readonly phase: NarrationPlayerPhase;
  readonly speakerLabel: string;
  readonly offsetMs: number;
  readonly durationMs: number;
}


export interface ChapterNarrationState {
  readonly documentId: string;
  readonly generation: number;
  readonly history: DocumentEditionHistory;
  readonly workingCopy: ChapterWorkingCopySnapshot;
  readonly currentEdition: EditionHistoryItem | null;
  readonly playbackEdition: EditionHistoryItem | null;
  readonly sourceStatus: ChapterNarrationSourceStatus;
  readonly sourceNotice: ChapterSourceNotice;
  readonly reviewSourceStatus: "current" | "working_copy_diverged" | null;
  readonly timelineMode: ChapterTimelineMode;
  readonly canDecorateCurrentSegment: boolean;
  readonly playerPlacement: ChapterPlayerPlacement;
  readonly fullPlayerVisible: boolean;
  readonly compactPlayer: CompactNarrationPlayerView | null;
  readonly subtitle: ChapterOldDraftSubtitle;
  readonly explicitUpdateRequired: boolean;
  readonly updateActionVisible: boolean;
  readonly updateActionEnabled: boolean;
  readonly availableCurrentSourceEditionIds: readonly string[];
}


export interface ChapterSaveBarrierReceipt {
  readonly documentId: string;
  readonly generation: number;
  readonly draftVersion: number;
  readonly contentHash: string;
  readonly stable: true;
}


export interface ExplicitNarrationUpdateIntent {
  readonly document_id: string;
  readonly intent: "update";
  readonly expected_draft_version: number;
  readonly expected_content_hash: string;
  readonly expected_settings_version: number;
  readonly force_review: boolean;
  readonly idempotency_key: string;
}


export interface PendingEditionSelection {
  readonly documentId: string;
  readonly generation: number;
  readonly expectedPointerVersion: number;
  readonly currentEditionId: string | null;
  readonly targetEditionId: string;
  readonly sourceRevisionId: string;
  readonly sourceContentHash: string;
  readonly oldDraft: boolean;
  readonly explicitImmediateStartSegmentId: string | null;
  readonly confirmationRequired: true;
}


const SHA256 = /^[a-f0-9]{64}$/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/u;
const AUDIO_ACTIVE_PHASES = new Set<NarrationPlayerPhase>([
  "preparing", "buffering", "playing", "paused",
]);
const PLAYER_PHASES = new Set<NarrationPlayerPhase>([
  "idle", "preparing", "buffering", "playing", "paused", "blocked", "ended", "error",
]);


function fail(path: string, message: string): never {
  throw new EditionHistoryContractError(path, message);
}


function safeInteger(value: number, path: string, minimum: number): number {
  if (!Number.isSafeInteger(value) || value < minimum) fail(path, `must be >= ${minimum}`);
  return value;
}


function sha256(value: string, path: string): string {
  if (!SHA256.test(value)) fail(path, "must be a lowercase SHA-256");
  return value;
}


function uuid(value: string, path: string): string {
  if (!UUID.test(value)) fail(path, "must be an RFC-4122 UUID");
  return value.toLowerCase();
}


function historyItem(history: DocumentEditionHistory, editionId: string): EditionHistoryItem {
  const item = history.editions.find((candidate) => candidate.edition_id === editionId);
  if (!item) fail("edition_id", "is outside this document history");
  return item;
}


function sourceStatus(
  item: EditionHistoryItem | null,
  history: DocumentEditionHistory,
  workingHash: string,
): ChapterNarrationSourceStatus {
  if (item === null) return "no_current_edition";
  if (!item.playable || item.state === "unavailable") return "unavailable";
  if (item.edition_id !== history.current_edition_id) return "superseded";
  return item.source_content_hash === workingHash ? "current" : "working_copy_diverged";
}


function sourceLabel(status: ChapterNarrationSourceStatus): string {
  switch (status) {
    case "no_current_edition": return "尚未生成朗读";
    case "current": return "当前正文朗读";
    case "working_copy_diverged": return "旧稿朗读·正文待更新";
    case "superseded": return "历史朗读版本";
    case "unavailable": return "朗读版本当前不可用";
  }
}


function emptySubtitle(): ChapterOldDraftSubtitle {
  return Object.freeze({
    visible: false,
    oldDraft: false,
    segmentId: null,
    ordinal: null,
    speakerLabel: null,
    sourceText: null,
    spokenText: null,
  });
}


export function deriveChapterNarrationState(
  input: ChapterNarrationStateInput,
): ChapterNarrationState {
  if (input.history.document_id !== input.documentId) {
    fail("history.document_id", "does not match the open chapter");
  }
  if (
    input.workingCopy.documentId !== input.documentId
    || input.workingCopy.generation !== input.generation
  ) {
    fail("working_copy", "belongs to another document lease");
  }
  safeInteger(input.generation, "generation", 0);
  safeInteger(input.workingCopy.draftVersion, "working_copy.draft_version", 1);
  sha256(input.workingCopy.contentHash, "working_copy.content_hash");
  if (
    input.workingCopy.saveState === "saved"
    && (
      input.history.working_copy_draft_version !== input.workingCopy.draftVersion
      || input.history.working_copy_content_hash !== input.workingCopy.contentHash
    )
  ) {
    fail("working_copy", "saved state does not match the server history snapshot");
  }

  const currentEdition = input.history.current_edition_id === null
    ? null
    : historyItem(input.history, input.history.current_edition_id);
  const playbackEdition = input.playback === null
    ? currentEdition
    : historyItem(input.history, input.playback.editionId);
  if (input.playback !== null) {
    if (!PLAYER_PHASES.has(input.playback.phase)) fail("playback.phase", "is unsupported");
    safeInteger(input.playback.offsetMs, "playback.offset_ms", 0);
    safeInteger(input.playback.durationMs, "playback.duration_ms", 0);
    if (input.playback.offsetMs > input.playback.durationMs) {
      fail("playback.offset_ms", "cannot exceed playback.duration_ms");
    }
  }
  if (
    input.playback?.subtitle !== null
    && input.playback?.subtitle !== undefined
    && input.playback.subtitle.editionId !== input.playback.editionId
  ) {
    fail("playback.subtitle.edition_id", "does not match the playback Edition");
  }
  if (
    input.playback?.subtitle !== null
    && input.playback?.subtitle !== undefined
    && input.playback.currentSegmentId !== input.playback.subtitle.segmentId
  ) {
    fail("playback.subtitle.segment_id", "does not match the current segment");
  }
  if (
    input.playback?.subtitle !== null
    && input.playback?.subtitle !== undefined
    && input.playback.currentOrdinal !== input.playback.subtitle.ordinal
  ) {
    fail("playback.subtitle.ordinal", "does not match the current segment ordinal");
  }
  if (input.reviewSource !== null) {
    sha256(input.reviewSource.contentHash, "review_source.content_hash");
  }

  const serverSourceStatus = sourceStatus(
    playbackEdition,
    input.history,
    input.workingCopy.contentHash,
  );
  const liveWorkingCopyDiverged = input.liveWorkingCopyDiverged === true;
  const status: ChapterNarrationSourceStatus = liveWorkingCopyDiverged
    && serverSourceStatus === "current"
    ? "working_copy_diverged"
    : serverSourceStatus;
  const sourceMatches = playbackEdition !== null
    && playbackEdition.source_content_hash === input.workingCopy.contentHash
    && !liveWorkingCopyDiverged;
  const mapped = Boolean(
    !sourceMatches
    && input.playback?.currentSegmentId
    && input.sessionMappedSegmentIds?.has(input.playback.currentSegmentId),
  );
  const timelineMode: ChapterTimelineMode = playbackEdition === null
    ? "none"
    : sourceMatches
    ? "exact-working-copy"
    : mapped
    ? "session-safe-mapping"
    : "immutable-edition-only";
  const audioActive = input.playback !== null
    && AUDIO_ACTIVE_PHASES.has(input.playback.phase);
  const playerPlacement: ChapterPlayerPlacement = input.reviewOpen
    ? audioActive ? "compact-in-review" : "hidden"
    : playbackEdition === null ? "hidden" : "full";
  const oldDraft = playbackEdition !== null && !sourceMatches;
  const subtitleSnapshot = input.playback?.subtitle ?? null;
  const subtitle = subtitleSnapshot === null
    ? emptySubtitle()
    : Object.freeze({
      visible: true,
      oldDraft,
      segmentId: subtitleSnapshot.segmentId,
      ordinal: subtitleSnapshot.ordinal,
      speakerLabel: subtitleSnapshot.speakerLabel,
      sourceText: subtitleSnapshot.sourceText,
      spokenText: subtitleSnapshot.spokenText,
    });
  const compactPlayer = playerPlacement !== "compact-in-review" || input.playback === null
    ? null
    : Object.freeze({
      editionId: input.playback.editionId,
      sourceStatus: status === "working_copy_diverged"
        ? "working_copy_diverged" as const
        : status === "superseded"
        ? "superseded" as const
        : "current" as const,
      oldDraft,
      phase: input.playback.phase,
      speakerLabel: subtitleSnapshot?.speakerLabel ?? "当前句段",
      offsetMs: input.playback.offsetMs,
      durationMs: input.playback.durationMs,
    });
  const currentSourceMatches = currentEdition !== null
    && currentEdition.source_content_hash === input.workingCopy.contentHash
    && !liveWorkingCopyDiverged;
  const availableCurrentSourceEditionIds = Object.freeze(
    (liveWorkingCopyDiverged ? [] : input.history.editions)
      .filter((item) => (
        item.edition_id !== input.history.current_edition_id
        && item.source_content_hash === input.workingCopy.contentHash
        && item.playable
        && item.switch_allowed
      ))
      .map((item) => item.edition_id),
  );
  const noticeItem = playbackEdition;
  return Object.freeze({
    documentId: input.documentId,
    generation: input.generation,
    history: input.history,
    workingCopy: input.workingCopy,
    currentEdition,
    playbackEdition,
    sourceStatus: status,
    sourceNotice: Object.freeze({
      status,
      label: sourceLabel(status),
      revisionId: noticeItem?.source_revision_id ?? null,
      contentHash: noticeItem?.source_content_hash ?? null,
    }),
    reviewSourceStatus: input.reviewSource === null
      ? null
      : input.reviewSource.contentHash === input.workingCopy.contentHash
      ? "current"
      : "working_copy_diverged",
    timelineMode,
    canDecorateCurrentSegment: timelineMode === "exact-working-copy" || mapped,
    playerPlacement,
    fullPlayerVisible: playerPlacement === "full",
    compactPlayer,
    subtitle,
    explicitUpdateRequired: currentEdition !== null && !currentSourceMatches,
    updateActionVisible: currentEdition !== null,
    updateActionEnabled: currentEdition !== null && input.workingCopy.saveState !== "saving",
    availableCurrentSourceEditionIds,
  });
}


export function createExplicitNarrationUpdateIntent(
  state: ChapterNarrationState,
  barrier: ChapterSaveBarrierReceipt,
  options: Readonly<{
    settingsVersion: number;
    forceReview: boolean;
    idempotencyKey: string;
  }>,
): ExplicitNarrationUpdateIntent {
  if (state.currentEdition === null) fail("current_edition_id", "is required for an update");
  if (state.workingCopy.saveState !== "saved") {
    fail("save_barrier", "must complete before updating narration");
  }
  if (
    barrier.stable !== true
    || barrier.documentId !== state.documentId
    || barrier.generation !== state.generation
    || barrier.draftVersion !== state.workingCopy.draftVersion
    || barrier.contentHash !== state.workingCopy.contentHash
  ) {
    fail("save_barrier", "does not match the latest document lease and working copy");
  }
  safeInteger(options.settingsVersion, "expected_settings_version", 1);
  if (typeof options.forceReview !== "boolean") fail("force_review", "must be a boolean");
  if (!IDEMPOTENCY_KEY.test(options.idempotencyKey)) {
    fail("idempotency_key", "must be 8-128 safe characters");
  }
  return Object.freeze({
    document_id: state.documentId,
    intent: "update",
    expected_draft_version: barrier.draftVersion,
    expected_content_hash: barrier.contentHash,
    expected_settings_version: options.settingsVersion,
    force_review: options.forceReview,
    idempotency_key: options.idempotencyKey,
  });
}


export function selectEditionForConfirmation(
  state: ChapterNarrationState,
  targetEditionId: string,
  explicitImmediateStartSegmentId: string | null = null,
): PendingEditionSelection {
  const target = historyItem(state.history, targetEditionId);
  if (target.is_current) fail("edition_id", "is already current");
  const normalizedStart = explicitImmediateStartSegmentId === null
    ? null
    : uuid(explicitImmediateStartSegmentId, "start_segment_id");
  if (!target.switch_allowed && (!target.playable || normalizedStart === null)) {
    fail("edition_id", "has no legal playable switch target");
  }
  return Object.freeze({
    documentId: state.documentId,
    generation: state.generation,
    expectedPointerVersion: state.history.pointer_version,
    currentEditionId: state.history.current_edition_id,
    targetEditionId: target.edition_id,
    sourceRevisionId: target.source_revision_id,
    sourceContentHash: target.source_content_hash,
    oldDraft: target.source_content_hash !== state.workingCopy.contentHash,
    explicitImmediateStartSegmentId: normalizedStart,
    confirmationRequired: true,
  });
}


export function confirmEditionSelection(
  state: ChapterNarrationState,
  pending: PendingEditionSelection,
  switchMode: EditionSwitchMode,
  startSegmentId: string | null = null,
): EditionSwitchIntent {
  if (
    pending.confirmationRequired !== true
    || pending.documentId !== state.documentId
    || pending.generation !== state.generation
    || pending.expectedPointerVersion !== state.history.pointer_version
    || pending.currentEditionId !== state.history.current_edition_id
  ) {
    fail("edition_selection", "is stale for the current document pointer");
  }
  if (pending.explicitImmediateStartSegmentId !== null) {
    if (switchMode !== "immediate") {
      fail("switch_mode", "a selected immediate start cannot be deferred");
    }
    const resolvedStart = startSegmentId ?? pending.explicitImmediateStartSegmentId;
    if (resolvedStart.toLowerCase() !== pending.explicitImmediateStartSegmentId) {
      fail("start_segment_id", "does not match the confirmed Edition selection");
    }
    return Object.freeze({
      document_id: state.documentId,
      edition_id: pending.targetEditionId,
      expected_version: state.history.pointer_version,
      switch_mode: "immediate",
      start_segment_id: pending.explicitImmediateStartSegmentId,
    });
  }
  return createEditionSwitchIntent(
    state.history,
    pending.targetEditionId,
    switchMode,
    startSegmentId,
  );
}
