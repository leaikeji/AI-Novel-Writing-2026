import type { NarrationEditionVoiceIdentity } from "./chapter-contracts";
import type { NarrationPlayerPhase, NarrationPlayerState } from "./narration-player";
import type { ManifestSegmentV2, SegmentRenderStatus } from "./playback-contracts";


export const LEGACY_EDITION_VOICE_NAME = "旧版未保存名称" as const;


export type ChapterPlayerLayoutMode = "compact" | "expanded" | "failure-details";


export interface ChapterPlayerLayoutState {
  readonly mode: ChapterPlayerLayoutMode;
}


export type ChapterPlayerLayoutAction = Readonly<
  | { type: "toggle-expanded" }
  | { type: "open-failure-details"; failureCount: number }
  | { type: "close-details" }
  | { type: "failures-cleared" }
>;


export const INITIAL_CHAPTER_PLAYER_LAYOUT_STATE: ChapterPlayerLayoutState = Object.freeze({
  mode: "compact",
});


export function transitionChapterPlayerLayout(
  state: ChapterPlayerLayoutState,
  action: ChapterPlayerLayoutAction,
): ChapterPlayerLayoutState {
  let mode = state.mode;
  switch (action.type) {
    case "toggle-expanded":
      mode = state.mode === "expanded" ? "compact" : "expanded";
      break;
    case "open-failure-details":
      if (action.failureCount > 0) mode = "failure-details";
      break;
    case "close-details":
      mode = "compact";
      break;
    case "failures-cleared":
      if (state.mode === "failure-details") mode = "compact";
      break;
  }
  return mode === state.mode ? state : Object.freeze({ mode });
}


export type ChapterPlayerContentPhase =
  | "loading"
  | "no-edition"
  | "ready"
  | "unavailable"
  | "error";


export type ChapterPlayerSourceKind =
  | "current"
  | "working-copy-diverged"
  | "historical";


export type ChapterGenerationState =
  | "empty"
  | "unknown"
  | "processing"
  | "partial"
  | "complete"
  | "failed";


export interface ChapterPlayerGenerationProjection {
  readonly state: ChapterGenerationState;
  readonly totalCount: number;
  readonly readyCount: number;
  readonly pendingCount: number;
  readonly failedCount: number;
  readonly cancelledCount: number;
  readonly completedCount: number;
  readonly completionPercent: number;
  readonly label: string;
}


export interface ChapterPlayerVoiceIdentityProjection {
  readonly key: string;
  readonly displayName: string;
  readonly sourceLabel: string;
  readonly legacy: boolean;
}


export interface ChapterPlayerViewProjection {
  readonly contentPhase: ChapterPlayerContentPhase;
  readonly contentLabel: string;
  readonly playbackPhase: NarrationPlayerPhase;
  readonly playbackLabel: string;
  readonly sourceKind: ChapterPlayerSourceKind;
  readonly sourceLabel: string;
  readonly generation: ChapterPlayerGenerationProjection;
  readonly currentTimeMs: number;
  readonly currentTimeLabel: string;
  readonly currentTimeBasis: "chapter" | "segment";
  readonly playableDurationMs: number | null;
  readonly playableDurationLabel: string;
  readonly voiceSummary: string;
  readonly voiceIdentities: readonly ChapterPlayerVoiceIdentityProjection[];
}


export interface ChapterPlaybackStartPosition {
  readonly ordinal: number;
  readonly offsetMs: number;
  readonly resumeExistingSession: boolean;
}


export interface ChapterPlayerViewInput {
  readonly contentPhase: ChapterPlayerContentPhase;
  readonly sourceKind: ChapterPlayerSourceKind;
  readonly playerState: NarrationPlayerState | null;
  readonly segmentIds: readonly string[];
  readonly segmentStates?: readonly SegmentRenderStatus[];
  readonly manifestSegments?: readonly ManifestSegmentV2[];
  readonly voiceIdentities?: readonly NarrationEditionVoiceIdentity[];
}


const CONTENT_LABELS: Readonly<Record<ChapterPlayerContentPhase, string>> = Object.freeze({
  loading: "正在读取朗读版本",
  "no-edition": "尚未生成朗读",
  ready: "朗读版本可用",
  unavailable: "朗读版本不可用",
  error: "朗读加载失败",
});


const PLAYBACK_LABELS: Readonly<Record<NarrationPlayerPhase, string>> = Object.freeze({
  idle: "尚未播放",
  preparing: "正在准备",
  buffering: "正在缓冲",
  playing: "正在播放",
  paused: "已暂停",
  blocked: "等待可播放句段",
  ended: "本章播放结束",
  error: "播放失败",
});


const SOURCE_LABELS: Readonly<Record<ChapterPlayerSourceKind, string>> = Object.freeze({
  current: "当前稿",
  "working-copy-diverged": "旧稿朗读 · 正文待更新",
  historical: "历史版本",
});


function boundedInteger(value: number, minimum: number, maximum: number): number {
  if (!Number.isFinite(value)) return minimum;
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}


function alignedManifestSegments(
  segmentIds: readonly string[],
  manifestSegments: readonly ManifestSegmentV2[] | undefined,
): readonly ManifestSegmentV2[] | null {
  if (!manifestSegments || manifestSegments.length !== segmentIds.length) return null;
  return manifestSegments.every((segment, index) => (
    segment.ordinal === index && segment.segment_id === segmentIds[index]
  )) ? manifestSegments : null;
}


function observableStates(
  segmentIds: readonly string[],
  segmentStates: readonly SegmentRenderStatus[] | undefined,
  manifestSegments: readonly ManifestSegmentV2[] | null,
): readonly SegmentRenderStatus[] | null {
  if (manifestSegments) return manifestSegments.map((segment) => segment.render_status);
  return segmentStates?.length === segmentIds.length ? segmentStates : null;
}


function generationProjection(
  totalCount: number,
  states: readonly SegmentRenderStatus[] | null,
): ChapterPlayerGenerationProjection {
  if (totalCount === 0) {
    return Object.freeze({
      state: "empty",
      totalCount: 0,
      readyCount: 0,
      pendingCount: 0,
      failedCount: 0,
      cancelledCount: 0,
      completedCount: 0,
      completionPercent: 0,
      label: "全章尚无句段",
    });
  }
  if (!states) {
    return Object.freeze({
      state: "unknown",
      totalCount,
      readyCount: 0,
      pendingCount: 0,
      failedCount: 0,
      cancelledCount: 0,
      completedCount: 0,
      completionPercent: 0,
      label: `全章生成进度待同步 · 共 ${totalCount} 句`,
    });
  }

  const counts = states.reduce((result, state) => {
    if (state === "ready") result.readyCount += 1;
    else if (state === "failed") result.failedCount += 1;
    else if (state === "cancelled") result.cancelledCount += 1;
    else result.pendingCount += 1;
    return result;
  }, { readyCount: 0, pendingCount: 0, failedCount: 0, cancelledCount: 0 });
  const completedCount = counts.readyCount;
  const completionPercent = Math.round((completedCount / totalCount) * 100);
  const terminalFailureCount = counts.failedCount + counts.cancelledCount;
  const state: ChapterGenerationState = counts.readyCount === totalCount
    ? "complete"
    : terminalFailureCount > 0 && counts.readyCount === 0 && counts.pendingCount === 0
    ? "failed"
    : counts.readyCount > 0
    ? "partial"
    : "processing";
  const parts = [`全章生成 ${completedCount}/${totalCount}`, `可播 ${counts.readyCount} 句`];
  if (counts.pendingCount > 0) parts.push(`处理中 ${counts.pendingCount} 句`);
  if (terminalFailureCount > 0) parts.push(`未完成 ${terminalFailureCount} 句`);
  return Object.freeze({
    state,
    totalCount,
    ...counts,
    completedCount,
    completionPercent,
    label: parts.join(" · "),
  });
}


function playableDuration(
  manifestSegments: readonly ManifestSegmentV2[] | null,
): number | null {
  if (!manifestSegments) return null;
  return manifestSegments.reduce((duration, segment, index) => {
    if (segment.render_status !== "ready" || !segment.audio) return duration;
    const next = manifestSegments[index + 1];
    const contiguousGap = next?.render_status === "ready" ? segment.gap_after_ms : 0;
    return duration + segment.audio.duration_ms + contiguousGap;
  }, 0);
}


function currentChapterTime(
  playerState: NarrationPlayerState | null,
  manifestSegments: readonly ManifestSegmentV2[] | null,
): Readonly<{ milliseconds: number; basis: "chapter" | "segment" }> {
  const offsetMs = Math.max(0, Math.round(playerState?.offsetMs ?? 0));
  const ordinal = playerState?.currentOrdinal;
  if (
    !manifestSegments
    || ordinal === null
    || ordinal === undefined
    || !Number.isSafeInteger(ordinal)
    || ordinal < 0
    || ordinal >= manifestSegments.length
  ) {
    return Object.freeze({ milliseconds: offsetMs, basis: "segment" });
  }
  const currentOrdinal = boundedInteger(ordinal, 0, Math.max(0, manifestSegments.length - 1));
  let milliseconds = 0;
  for (let index = 0; index < currentOrdinal; index += 1) {
    const segment = manifestSegments[index];
    const next = manifestSegments[index + 1];
    if (segment.render_status === "ready" && segment.audio) {
      milliseconds += segment.audio.duration_ms;
      if (next?.render_status === "ready") milliseconds += segment.gap_after_ms;
    }
  }
  const currentDuration = manifestSegments[currentOrdinal]?.audio?.duration_ms ?? offsetMs;
  milliseconds += Math.min(offsetMs, currentDuration);
  return Object.freeze({ milliseconds, basis: "chapter" });
}


export function formatChapterPlayerTime(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1_000));
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}


export function chapterPlaybackHasEnded(
  playerState: NarrationPlayerState | null,
  segmentCount: number,
  lastSegmentDurationMs?: number | null,
): boolean {
  const safeSegmentCount = Number.isSafeInteger(segmentCount) && segmentCount > 0
    ? segmentCount
    : 0;
  if (safeSegmentCount === 0 || !playerState) return false;
  if (playerState.phase === "ended") return true;
  const currentOrdinal = playerState.currentOrdinal;
  if (
    currentOrdinal === null
    || currentOrdinal === undefined
    || !Number.isSafeInteger(currentOrdinal)
    || currentOrdinal !== safeSegmentCount - 1
  ) return false;
  const manifestDuration = lastSegmentDurationMs !== null
    && lastSegmentDurationMs !== undefined
    && Number.isFinite(lastSegmentDurationMs)
    && lastSegmentDurationMs > 0
    ? Math.round(lastSegmentDurationMs)
    : null;
  const stateDuration = Number.isFinite(playerState.durationMs) && playerState.durationMs > 0
    ? Math.round(playerState.durationMs)
    : null;
  const terminalDuration = manifestDuration ?? stateDuration;
  return terminalDuration !== null
    && Math.max(0, Math.round(playerState.offsetMs)) >= terminalDuration;
}


function voiceSourceLabel(identity: NarrationEditionVoiceIdentity): string {
  if (identity.legacy_fallback) return "历史音色标识";
  if (identity.source_type === "preset") return "官方预设";
  if (identity.source_type === "uploaded") return "上传音色";
  // CORE currently persists Nano advanced tuning as a generated version.  It
  // must not be presented as a VoiceGenerator-created character voice before
  // the separately gated VG pipeline exists and freezes a distinct identity.
  if (identity.source_type === "generated") return "高级调音";
  return "冻结声音";
}


function voiceIdentityProjection(
  identities: readonly NarrationEditionVoiceIdentity[] | undefined,
): readonly ChapterPlayerVoiceIdentityProjection[] {
  if (!identities) return Object.freeze([]);
  return Object.freeze(identities.map((identity) => Object.freeze({
    key: identity.voice_version_id,
    displayName: identity.legacy_fallback
      ? LEGACY_EDITION_VOICE_NAME
      : identity.display_name,
    sourceLabel: voiceSourceLabel(identity),
    legacy: identity.legacy_fallback,
  })));
}


export function resolveChapterPlaybackStartPosition(
  playerState: NarrationPlayerState | null,
  segmentCount: number,
  lastSegmentDurationMs?: number | null,
): ChapterPlaybackStartPosition {
  const safeSegmentCount = Number.isSafeInteger(segmentCount) && segmentCount > 0
    ? segmentCount
    : 0;
  if (chapterPlaybackHasEnded(playerState, safeSegmentCount, lastSegmentDurationMs)) {
    return Object.freeze({ ordinal: 0, offsetMs: 0, resumeExistingSession: false });
  }
  const currentOrdinal = playerState?.currentOrdinal;
  const hasValidOrdinal = currentOrdinal !== null
    && currentOrdinal !== undefined
    && Number.isSafeInteger(currentOrdinal)
    && currentOrdinal >= 0
    && currentOrdinal < safeSegmentCount;
  if (!hasValidOrdinal) {
    return Object.freeze({ ordinal: 0, offsetMs: 0, resumeExistingSession: false });
  }
  const validOrdinal = currentOrdinal;
  const offsetMs = Math.max(0, Math.round(playerState?.offsetMs ?? 0));
  return Object.freeze({
    ordinal: validOrdinal,
    offsetMs,
    resumeExistingSession: playerState?.phase === "paused",
  });
}


export function deriveChapterPlayerView(
  input: ChapterPlayerViewInput,
): ChapterPlayerViewProjection {
  const manifestSegments = alignedManifestSegments(input.segmentIds, input.manifestSegments);
  const states = observableStates(input.segmentIds, input.segmentStates, manifestSegments);
  const generation = generationProjection(input.segmentIds.length, states);
  const durationMs = playableDuration(manifestSegments);
  const currentTime = currentChapterTime(input.playerState, manifestSegments);
  const currentOrdinal = input.playerState?.currentOrdinal;
  const currentSentence = currentOrdinal !== null
    && currentOrdinal !== undefined
    && Number.isSafeInteger(currentOrdinal)
    && currentOrdinal >= 0
    && currentOrdinal < input.segmentIds.length
    ? currentOrdinal + 1
    : null;
  const identities = voiceIdentityProjection(input.voiceIdentities);
  const playbackPhase = input.playerState?.phase ?? "idle";
  const lastManifestSegment = manifestSegments?.[manifestSegments.length - 1];
  const playbackEnded = chapterPlaybackHasEnded(
    input.playerState,
    input.segmentIds.length,
    lastManifestSegment?.audio?.duration_ms,
  );
  const playbackLabel = playbackPhase === "idle" && playbackEnded
    ? PLAYBACK_LABELS.ended
    : playbackPhase === "idle" && currentSentence !== null
    ? `上次停在第 ${currentSentence} 段`
    : PLAYBACK_LABELS[playbackPhase];
  const voiceSummary = input.voiceIdentities === undefined
    ? "音色身份待加载"
    : identities.length === 0
    ? "音色身份不可用"
    : identities.length === 1
    ? `${identities[0].displayName} · ${identities[0].sourceLabel}`
    : `${identities.length} 个冻结声音`;

  return Object.freeze({
    contentPhase: input.contentPhase,
    contentLabel: CONTENT_LABELS[input.contentPhase],
    playbackPhase,
    playbackLabel,
    sourceKind: input.sourceKind,
    sourceLabel: SOURCE_LABELS[input.sourceKind],
    generation,
    currentTimeMs: currentTime.milliseconds,
    currentTimeLabel: formatChapterPlayerTime(currentTime.milliseconds),
    currentTimeBasis: currentTime.basis,
    playableDurationMs: durationMs,
    playableDurationLabel: durationMs === null ? "待计算" : formatChapterPlayerTime(durationMs),
    voiceSummary,
    voiceIdentities: identities,
  });
}
