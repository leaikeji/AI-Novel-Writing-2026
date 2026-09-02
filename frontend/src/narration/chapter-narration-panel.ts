import type { QwenPawReactRuntime } from "../assistant-pane";
import type {
  FailedNarrationSegmentsProjection,
  NarrationEditionVoiceIdentity,
} from "./chapter-contracts";
import {
  INITIAL_CHAPTER_PLAYER_LAYOUT_STATE,
  chapterPlaybackHasEnded,
  deriveChapterPlayerView,
  transitionChapterPlayerLayout,
  type ChapterPlayerLayoutMode,
} from "./chapter-player-view-state";
import type { EditionHistoryItem } from "./edition-history";
import { failedSegmentRetryReasonMessage } from "./failed-segment-retry-state";
import type { NarrationPlayerPhase, NarrationPlayerState } from "./narration-player";
import type { ManifestSegmentV2, SegmentRenderStatus } from "./playback-contracts";
import type { ScriptReviewSegmentResource } from "./script-contracts";


export type ChapterNarrationPanelPhase =
  | "loading"
  | "no-edition"
  | "ready"
  | "unavailable"
  | "error";


export type ChapterNarrationSourceKind =
  | "current"
  | "working-copy-diverged"
  | "historical";


export interface ChapterNarrationPanelProps {
  readonly phase: ChapterNarrationPanelPhase;
  readonly sourceKind: ChapterNarrationSourceKind;
  readonly playerState: NarrationPlayerState | null;
  readonly segments: readonly ScriptReviewSegmentResource[];
  readonly segmentStates?: readonly SegmentRenderStatus[];
  readonly manifestSegments?: readonly ManifestSegmentV2[];
  readonly editions: readonly EditionHistoryItem[];
  readonly activeEditionId: string | null;
  readonly currentEditionId: string | null;
  readonly busy: boolean;
  readonly productionAllowed: boolean;
  readonly statusMessage: string;
  readonly errorMessage?: string | null;
  readonly followPaused?: boolean;
  readonly reviewAvailable?: boolean;
  readonly updateRequired?: boolean;
  readonly failedSegments?: FailedNarrationSegmentsProjection | null;
  readonly retryBusySegmentIds?: readonly string[];
  readonly retrySubmitting?: boolean;
  readonly retryStatusMessage?: string | null;
  readonly retryErrorMessage?: string | null;
  readonly retryFocusSegmentId?: string | null;
  readonly voiceIdentities?: readonly NarrationEditionVoiceIdentity[];
  readonly playbackPreferenceStatus?: Readonly<{
    state: "idle" | "saving" | "saved" | "conflict" | "error";
    message?: string;
  }> | null;
  readonly onGenerate: () => void;
  readonly onUpdate: () => void;
  readonly onTogglePlayback: () => void;
  readonly onSeekOrdinal: (ordinal: number) => void;
  readonly cursorPlaybackAvailable?: boolean;
  readonly onPlaybackFromCursor?: () => void;
  readonly onRateChange: (rate: number) => void;
  readonly onVolumeChange: (volume: number) => void;
  readonly onResumeFollow: () => void;
  readonly onSelectEdition: (editionId: string) => void;
  readonly onOpenReview?: () => void;
  readonly onRetryFailedSegment?: (segmentId: string) => void;
  readonly reviewTriggerRef?: {
    readonly current: { focus(): void } | null;
  };
  readonly retryTriggerRef?: {
    readonly current: { focus(): void } | null;
  };
}


export interface ChapterNarrationPanelModel {
  readonly hasEdition: boolean;
  readonly canPlay: boolean;
  readonly canSeek: boolean;
  readonly canGenerate: boolean;
  readonly canUpdate: boolean;
  readonly currentOrdinal: number | null;
  readonly currentSegment: ScriptReviewSegmentResource | null;
  readonly previousOrdinal: number | null;
  readonly nextOrdinal: number | null;
  readonly progressLabel: string;
  readonly sourceLabel: string;
  readonly playbackLabel: string;
}


export type ChapterNarrationPanelReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useEffect" | "useRef" | "useState"
>;


export interface ChapterNarrationPanelIcons {
  readonly Previous: unknown;
  readonly Next: unknown;
  readonly Play: unknown;
  readonly Pause: unknown;
  readonly Loading: unknown;
  readonly Volume: unknown;
  readonly Speaker: unknown;
  readonly More: unknown;
  readonly Warning: unknown;
}


const ACTIVE_PLAYER_PHASES = new Set<NarrationPlayerPhase>([
  "preparing",
  "buffering",
  "playing",
  "paused",
]);


function clampOrdinal(value: number, segmentCount: number): number {
  if (!Number.isFinite(value) || segmentCount <= 0) return 0;
  return Math.max(0, Math.min(segmentCount - 1, Math.round(value)));
}


function observableSegmentStates(
  segments: readonly ScriptReviewSegmentResource[],
  states: readonly SegmentRenderStatus[] | undefined,
): string {
  if (!states || states.length !== segments.length) return "";
  return states.map((state) => (
    state === "queued" || state === "rendering" ? "pending" : state
  )).join(",");
}


export function deriveChapterNarrationPanelModel(
  props: ChapterNarrationPanelProps,
): ChapterNarrationPanelModel {
  const hasEdition = props.activeEditionId !== null && props.segments.length > 0;
  const rawOrdinal = props.playerState?.currentOrdinal ?? null;
  const currentOrdinal = rawOrdinal === null
    || !Number.isSafeInteger(rawOrdinal)
    || rawOrdinal < 0
    || rawOrdinal >= props.segments.length
    ? null
    : rawOrdinal;
  const currentSegment = currentOrdinal === null ? null : props.segments[currentOrdinal] ?? null;
  const canPlay = props.phase === "ready" && hasEdition && !props.busy;
  const canSeek = canPlay;
  const lastManifestSegment = props.manifestSegments?.length === props.segments.length
    ? props.manifestSegments[props.manifestSegments.length - 1]
    : undefined;
  const playbackEnded = chapterPlaybackHasEnded(
    props.playerState,
    props.segments.length,
    lastManifestSegment?.ordinal === props.segments.length - 1
      ? lastManifestSegment.audio?.duration_ms
      : undefined,
  );
  const playbackLabel = props.playerState?.phase === "playing"
    ? "暂停"
    : props.playerState?.phase === "preparing"
    ? "准备中"
    : props.playerState?.phase === "buffering"
    ? "缓冲中"
    : playbackEnded
    ? "重新播放"
    : "播放";
  return Object.freeze({
    hasEdition,
    canPlay,
    canSeek,
    canGenerate: props.productionAllowed && props.phase === "no-edition" && !props.busy,
    canUpdate: props.productionAllowed && props.phase === "ready" && hasEdition && !props.busy,
    currentOrdinal,
    currentSegment,
    previousOrdinal: currentOrdinal !== null && currentOrdinal > 0 ? currentOrdinal - 1 : null,
    nextOrdinal: currentOrdinal !== null && currentOrdinal + 1 < props.segments.length
      ? currentOrdinal + 1
      : currentOrdinal === null && props.segments.length > 0 ? 0 : null,
    progressLabel: props.segments.length === 0
      ? "尚无可播放句段"
      : currentOrdinal === null
      ? `未开始 · 0 / ${props.segments.length} 句`
      : `${currentOrdinal + 1} / ${props.segments.length} 句`,
    sourceLabel: props.sourceKind === "current"
      ? "当前稿"
      : props.sourceKind === "working-copy-diverged" ? "旧稿朗读 · 正文待更新" : "历史版本",
    playbackLabel,
  });
}


function editionOptionLabel(edition: EditionHistoryItem): string {
  const source = edition.is_current
    ? "当前版本"
    : edition.source_status === "superseded" ? "历史版本" : "旧稿版本";
  const readiness = `${edition.ready_segment_count}/${edition.total_segment_count} 句可用`;
  return `${source} · ${readiness}`;
}


const PLAYBACK_RATE_OPTIONS = Object.freeze([
  0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3,
]);


function boundedPlaybackRate(rate: number | undefined): number {
  if (rate === undefined || !Number.isFinite(rate)) return 1;
  return Math.min(3, Math.max(0.5, rate));
}


function volumePercent(volume: number | undefined): number {
  if (volume === undefined || !Number.isFinite(volume)) return 100;
  return Math.round(Math.min(1, Math.max(0, volume)) * 100);
}


function playbackPreferenceMessage(
  status: ChapterNarrationPanelProps["playbackPreferenceStatus"],
): string | null {
  if (!status) return null;
  if (status.message) return status.message;
  if (status.state === "saving") return "正在保存播放偏好…";
  if (status.state === "saved") return "播放偏好已保存。";
  if (status.state === "conflict") return "播放偏好已在别处更新，请刷新后重试。";
  if (status.state === "error") return "播放偏好保存失败，本次会话仍已即时生效。";
  return null;
}


function detailsHeading(mode: ChapterPlayerLayoutMode): string {
  return mode === "failure-details" ? "失败句段详情" : "朗读详情";
}


export function createChapterNarrationPanel(
  React: ChapterNarrationPanelReactRuntime,
  icons: ChapterNarrationPanelIcons,
): (props: ChapterNarrationPanelProps) => unknown {
  const h = React.createElement;
  return function ChapterNarrationPanel(props) {
    const model = deriveChapterNarrationPanelModel(props);
    const playerState = props.playerState;
    const playbackBusy = playerState !== null
      && ["preparing", "buffering"].includes(playerState.phase);
    const toggleDisabled = !model.canPlay || playbackBusy;
    const sliderValue = model.currentOrdinal ?? 0;
    const activeEdition = props.editions.find((item) => item.edition_id === props.activeEditionId);
    const editionDisabled = props.busy || ACTIVE_PLAYER_PHASES.has(playerState?.phase ?? "idle");
    const observedStates = props.manifestSegments?.map((segment) => segment.render_status)
      ?? props.segmentStates;
    const segmentStates = observableSegmentStates(props.segments, observedStates);
    const failedItems = props.failedSegments?.items ?? [];
    const retryBusySegmentIds = new Set(props.retryBusySegmentIds ?? []);
    const focusedRetryItemStillVisible = props.retryFocusSegmentId !== null
      && props.retryFocusSegmentId !== undefined
      && failedItems.some((item) => item.segment_id === props.retryFocusSegmentId);
    const retryAnnouncement = props.retryErrorMessage ?? props.retryStatusMessage;
    const preferenceAnnouncement = playbackPreferenceMessage(props.playbackPreferenceStatus);
    const [layoutState, setLayoutState] = React.useState(INITIAL_CHAPTER_PLAYER_LAYOUT_STATE);
    const [volumeOpen, setVolumeOpen] = React.useState(false);
    const moreTriggerRef = React.useRef<{ focus(): void } | null>(null);
    const failureTriggerRef = React.useRef<{ focus(): void } | null>(null);
    const volumeTriggerRef = React.useRef<{ focus(): void } | null>(null);
    const volumeInputRef = React.useRef<{ focus(): void } | null>(null);
    const playerRootRef = React.useRef<HTMLElement | null>(null);
    React.useEffect(() => {
      if (failedItems.length === 0) {
        setLayoutState((current) => transitionChapterPlayerLayout(current, {
          type: "failures-cleared",
        }));
      }
    }, [failedItems.length]);
    const layoutMode = failedItems.length === 0 && layoutState.mode === "failure-details"
      ? "compact"
      : layoutState.mode;
    const detailsVisible = layoutMode !== "compact";
    const view = deriveChapterPlayerView({
      contentPhase: props.phase,
      sourceKind: props.sourceKind,
      playerState,
      segmentIds: props.segments.map((segment) => segment.segment_id),
      segmentStates: props.segmentStates,
      manifestSegments: props.manifestSegments,
      voiceIdentities: props.voiceIdentities,
    });
    const currentVolumePercent = volumePercent(playerState?.volume);
    const currentRate = boundedPlaybackRate(playerState?.rate);
    const detailsId = "anw-chapter-player-details";
    const volumeId = "anw-chapter-player-volume";
    const speakerLabel = model.currentSegment?.speaker_label
      ?? props.segments[0]?.speaker_label
      ?? "章节朗读";

    const setLayout = (action: Parameters<typeof transitionChapterPlayerLayout>[1]) => {
      setLayoutState((current) => transitionChapterPlayerLayout(current, action));
    };
    const closeDetails = () => {
      const returnTarget = layoutMode === "failure-details"
        ? failureTriggerRef.current
        : moreTriggerRef.current;
      setLayout({ type: "close-details" });
      returnTarget?.focus();
    };
    React.useEffect(() => {
      if (volumeOpen) volumeInputRef.current?.focus();
    }, [volumeOpen]);
    React.useEffect(() => {
      const root = playerRootRef.current;
      const scrollSurface = root?.parentElement?.querySelector<HTMLElement>(
        ":scope > .anw-editor-scroll",
      ) ?? null;
      if (!root || !scrollSurface) return undefined;
      const synchronizeScrollbarWidth = () => {
        const width = Math.max(0, scrollSurface.offsetWidth - scrollSurface.clientWidth);
        root.style.setProperty("--anw-chapter-editor-scrollbar-width", `${width}px`);
      };
      synchronizeScrollbarWidth();
      if (typeof ResizeObserver === "undefined") return undefined;
      const observer = new ResizeObserver(synchronizeScrollbarWidth);
      observer.observe(scrollSurface);
      return () => observer.disconnect();
    }, []);

    const editionSelect = props.editions.length > 0
      ? h(
          "label",
          { className: "anw-chapter-narration-select" },
          h("span", null, "朗读版本"),
          h(
            "select",
            {
              value: activeEdition?.edition_id ?? "",
              disabled: editionDisabled,
              onChange: (event: { target: { value: string } }) => {
                if (event.target.value && event.target.value !== props.activeEditionId) {
                  props.onSelectEdition(event.target.value);
                }
              },
              "aria-label": "选择章节朗读版本",
            },
            activeEdition
              ? null
              : h("option", { value: "", disabled: true }, "选择已有朗读版本"),
            ...props.editions.map((edition) => h(
              "option",
              {
                key: edition.edition_id,
                value: edition.edition_id,
                disabled: !edition.playable,
              },
              editionOptionLabel(edition),
            )),
          ),
        )
      : null;

    const failureList = failedItems.length > 0
      ? h(
          "section",
          {
            className: "anw-chapter-narration-failures",
            "aria-label": "失败句段重试",
            hidden: layoutMode !== "failure-details",
          },
          h(
            "div",
            { className: "anw-chapter-narration-failures__header" },
            h("strong", null, `失败句段（${failedItems.length}）`),
            h("span", null, "只重试失败音频，不修改正文、人物绑定或既有朗读版本。"),
          ),
          h(
            "ul",
            { className: "anw-chapter-narration-failures__list" },
            ...failedItems.map((item) => {
              const source = props.segments[item.ordinal];
              const descriptionId = `anw-failed-segment-${item.segment_id}`;
              const groupBusy = retryBusySegmentIds.has(item.segment_id);
              const disabled = !item.retryable
                || props.retrySubmitting === true
                || props.onRetryFailedSegment === undefined;
              return h(
                "li",
                {
                  key: item.segment_id,
                  className: `anw-chapter-narration-failure ${groupBusy ? "is-busy" : ""}`,
                  "data-segment-id": item.segment_id,
                  "data-failure-code": item.failure_code,
                },
                h(
                  "div",
                  { className: "anw-chapter-narration-failure__copy" },
                  h("strong", null, `第 ${item.ordinal + 1} 句 · ${source?.speaker_label ?? "章节朗读"}`),
                  h(
                    "span",
                    { title: source?.source_text ?? item.failure_code },
                    source?.source_text ?? `合成失败（${item.failure_code}）`,
                  ),
                  h(
                    "small",
                    { id: descriptionId },
                    item.retryable
                      ? item.fanout_segment_ids.length > 1
                        ? `此音频被 ${item.fanout_segment_ids.length} 句共用，重试会同步重试 ${item.fanout_segment_ids.length} 句。`
                        : "重试只会重新合成本句音频。"
                      : failedSegmentRetryReasonMessage(item.retry_reason_code),
                  ),
                ),
                h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-retry-button",
                    disabled,
                    "aria-describedby": descriptionId,
                    "aria-busy": groupBusy ? "true" : "false",
                    ref: props.retryFocusSegmentId === item.segment_id
                      ? props.retryTriggerRef
                      : undefined,
                    onClick: () => {
                      if (!disabled) props.onRetryFailedSegment?.(item.segment_id);
                    },
                  },
                  groupBusy ? "正在重试…" : item.retryable ? "重试本句" : "暂不可重试",
                ),
              );
            }),
          ),
        )
      : null;

    let noticeKind: "warning" | "error" | "progress" | "info" | null = null;
    let noticeText = "";
    let noticeActionLabel: string | null = null;
    let noticeAction: (() => void) | null = null;
    let noticeShowsProgress = false;
    const updateNoticeActive = props.sourceKind === "working-copy-diverged"
      || props.updateRequired === true;
    if (props.errorMessage) {
      noticeKind = "error";
      noticeText = props.errorMessage;
    } else if (updateNoticeActive) {
      noticeKind = "warning";
      noticeText = "朗读内容与当前正文不一致";
      noticeActionLabel = "更新朗读";
      noticeAction = props.onUpdate;
    } else if (props.sourceKind === "historical") {
      noticeKind = "warning";
      noticeText = "正在播放历史朗读版本";
    } else if (failedItems.length > 0) {
      noticeKind = "error";
      noticeText = `有 ${failedItems.length} 个句段生成失败`;
      noticeActionLabel = "查看失败";
      noticeAction = () => {
        setVolumeOpen(false);
        setLayout({ type: "open-failure-details", failureCount: failedItems.length });
      };
    } else if (view.generation.state === "failed") {
      noticeKind = "error";
      noticeText = view.generation.label;
    } else if (
      view.generation.state === "processing"
      || view.generation.state === "partial"
      || view.generation.state === "unknown"
    ) {
      noticeKind = "progress";
      noticeText = view.generation.label;
      noticeShowsProgress = view.generation.state !== "unknown";
    } else if (
      props.playbackPreferenceStatus?.state === "conflict"
      || props.playbackPreferenceStatus?.state === "error"
    ) {
      noticeKind = props.playbackPreferenceStatus.state === "error" ? "error" : "warning";
      noticeText = preferenceAnnouncement ?? "播放偏好暂未保存";
    } else if (props.retryErrorMessage) {
      noticeKind = "error";
      noticeText = props.retryErrorMessage;
    } else if (props.followPaused) {
      noticeKind = "info";
      noticeText = "已暂停自动跟随朗读位置";
      noticeActionLabel = "返回朗读位置";
      noticeAction = props.onResumeFollow;
    }

    return h(
      "section",
      {
        ref: playerRootRef,
        className: `anw-chapter-narration-player is-${props.phase} is-layout-${layoutMode}`,
        "aria-label": "章节智能朗读播放器",
        "data-content-phase": props.phase,
        "data-source-kind": props.sourceKind,
        "data-player-phase": playerState?.phase ?? "idle",
        "data-generation-state": view.generation.state,
        "data-layout-mode": layoutMode,
        "data-preference-state": props.playbackPreferenceStatus?.state ?? "idle",
        "data-player-failure-code": playerState?.failure?.code ?? "",
        "data-current-ordinal": playerState?.currentOrdinal === null
          || playerState?.currentOrdinal === undefined
          ? ""
          : String(playerState.currentOrdinal),
        "data-segment-states": segmentStates,
        onKeyDown: (event: { key: string; preventDefault(): void }) => {
          if (event.key !== "Escape") return;
          if (volumeOpen) {
            event.preventDefault();
            setVolumeOpen(false);
            volumeTriggerRef.current?.focus();
            return;
          }
          if (!detailsVisible) return;
          event.preventDefault();
          closeDetails();
        },
      },
      noticeKind
        ? h(
            "div",
            {
              className: `anw-chapter-narration-notice is-${noticeKind}`,
              role: noticeKind === "error" ? "alert" : "status",
            },
            h(
              "span",
              { className: "anw-chapter-narration-notice__icon", "aria-hidden": "true" },
              h(
                noticeKind === "progress"
                  ? icons.Loading
                  : noticeKind === "info" ? icons.Speaker : icons.Warning,
                noticeKind === "progress" ? { spin: true } : null,
              ),
            ),
            h(
              "div",
              { className: "anw-chapter-narration-notice__copy" },
              h("span", null, noticeText),
              noticeShowsProgress
                ? h("progress", {
                    max: Math.max(1, view.generation.totalCount),
                    value: view.generation.completedCount,
                    "aria-label": "全章音频生成进度",
                    "aria-valuetext": view.generation.label,
                  })
                : null,
            ),
            noticeAction && noticeActionLabel
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-notice__action",
                    disabled: noticeActionLabel === "更新朗读" && !model.canUpdate,
                    onClick: noticeAction,
                    ...(noticeActionLabel === "查看失败"
                      ? {
                          ref: failureTriggerRef,
                          "aria-controls": detailsId,
                          "aria-expanded": layoutMode === "failure-details",
                        }
                      : {}),
                  },
                  noticeActionLabel,
                )
              : null,
          )
        : null,
      model.hasEdition
        ? h(
            "div",
            { className: "anw-chapter-narration-player__timeline" },
            h("input", {
              type: "range",
              min: 0,
              max: Math.max(0, props.segments.length - 1),
              step: 1,
              value: sliderValue,
              disabled: !model.canSeek,
              onChange: (event: { target: { value: string } }) => {
                props.onSeekOrdinal(clampOrdinal(Number(event.target.value), props.segments.length));
              },
              "aria-label": "按句段跳转章节朗读位置",
              "aria-valuetext": model.progressLabel,
            }),
            h(
              "span",
              { className: "anw-chapter-narration-sr-only", "aria-live": "polite" },
              `${model.progressLabel} · ${view.playbackLabel}`,
            ),
          )
        : null,
      h(
        "div",
        { className: "anw-chapter-narration-player__compact" },
        h(
          "div",
          {
            className: "anw-chapter-narration-player__identity",
            "data-player-zone": "identity",
            "aria-live": "polite",
            "aria-atomic": "true",
          },
          h(
            "span",
            { className: "anw-chapter-narration-player__speaker-icon", "aria-hidden": "true" },
            h(icons.Speaker),
          ),
          h("strong", { title: speakerLabel }, speakerLabel),
        ),
        h(
          "div",
          {
            className: "anw-chapter-narration-player__controls",
            "data-player-zone": "transport",
          },
          model.hasEdition
            ? h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-icon-button",
                  disabled: !model.canSeek || model.previousOrdinal === null,
                  onClick: () => {
                    if (model.previousOrdinal !== null) props.onSeekOrdinal(model.previousOrdinal);
                  },
                  title: "上一句",
                  "aria-label": "朗读上一句",
                },
                h(icons.Previous, { "aria-hidden": "true" }),
              )
            : null,
          model.hasEdition
            ? h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-play-button",
                  disabled: toggleDisabled,
                  onClick: props.onTogglePlayback,
                  title: model.playbackLabel,
                  "aria-label": model.playbackLabel === "暂停"
                    ? "暂停章节朗读"
                    : model.playbackLabel === "重新播放"
                    ? "从头重新播放章节朗读"
                    : "播放章节朗读",
                },
                h(
                  playbackBusy
                    ? icons.Loading
                    : model.playbackLabel === "暂停" ? icons.Pause : icons.Play,
                  playbackBusy ? { spin: true, "aria-hidden": "true" } : { "aria-hidden": "true" },
                ),
              )
            : props.phase === "no-edition"
            ? h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-primary-action",
                  disabled: !model.canGenerate,
                  onClick: props.onGenerate,
                },
                props.busy ? "正在准备朗读…" : "智能朗读",
              )
            : h("span", { className: "anw-chapter-narration-player__phase" }, view.contentLabel),
          model.hasEdition
            ? h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-icon-button",
                  disabled: !model.canSeek || model.nextOrdinal === null,
                  onClick: () => {
                    if (model.nextOrdinal !== null) props.onSeekOrdinal(model.nextOrdinal);
                  },
                  title: "下一句",
                  "aria-label": "朗读下一句",
                },
                h(icons.Next, { "aria-hidden": "true" }),
              )
            : null,
        ),
        model.hasEdition
          ? h(
              "div",
              {
                className: "anw-chapter-narration-player__tools",
                "data-player-zone": "tools",
              },
              h(
                "span",
                {
                  className: "anw-chapter-narration-player__time",
                  "aria-label": `当前 ${view.currentTimeLabel}，总时长 ${view.playableDurationLabel}`,
                },
                `${view.currentTimeLabel} / ${view.playableDurationLabel}`,
              ),
              h(
                "label",
                { className: "anw-chapter-narration-rate" },
                h("span", { className: "anw-chapter-narration-sr-only" }, "倍速"),
                h(
                  "select",
                  {
                    className: "anw-chapter-narration-rate__select",
                    value: String(currentRate),
                    disabled: props.busy,
                    onChange: (event: { target: { value: string } }) => {
                      props.onRateChange(Number(event.target.value));
                    },
                    "aria-label": "朗读倍速，范围 0.5 到 3 倍",
                  },
                  ...PLAYBACK_RATE_OPTIONS.map((rate) => h(
                    "option",
                    { key: rate, value: String(rate) },
                    `${rate}×`,
                  )),
                ),
              ),
              h(
                "div",
                { className: "anw-chapter-narration-volume-control" },
                h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-tool-button",
                    ref: volumeTriggerRef,
                    disabled: props.busy,
                    "aria-label": `章节朗读音量，当前 ${currentVolumePercent}%`,
                    "aria-controls": volumeId,
                    "aria-expanded": volumeOpen,
                    onClick: () => {
                      setLayout({ type: "close-details" });
                      setVolumeOpen((current) => !current);
                    },
                  },
                  h(icons.Volume, { "aria-hidden": "true" }),
                ),
                h(
                  "label",
                  {
                    id: volumeId,
                    className: "anw-chapter-narration-volume-popover",
                    hidden: !volumeOpen,
                  },
                  h("span", null, `音量 ${currentVolumePercent}%`),
                  h("input", {
                    ref: volumeInputRef,
                    type: "range",
                    min: 0,
                    max: 100,
                    step: 1,
                    value: currentVolumePercent,
                    disabled: props.busy,
                    onChange: (event: { target: { value: string } }) => {
                      const percent = Math.min(100, Math.max(0, Number(event.target.value)));
                      props.onVolumeChange(percent / 100);
                    },
                    "aria-label": "章节朗读音量",
                    "aria-valuetext": `${currentVolumePercent}%`,
                  }),
                ),
              ),
              h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-more",
                  ref: moreTriggerRef,
                  "aria-controls": detailsId,
                  "aria-expanded": detailsVisible,
                  "aria-label": detailsVisible ? "关闭朗读详情" : "打开朗读详情",
                  onClick: () => {
                    setVolumeOpen(false);
                    if (detailsVisible) closeDetails();
                    else setLayout({ type: "toggle-expanded" });
                  },
                },
                h(icons.More, { "aria-hidden": "true" }),
                h("span", null, detailsVisible ? "关闭" : "更多"),
              ),
            )
          : h("div", { className: "anw-chapter-narration-player__tools", "aria-hidden": "true" }),
      ),
      h(
        "section",
        {
          id: detailsId,
          className: `anw-chapter-narration-details is-${layoutMode}`,
          hidden: !detailsVisible,
          role: "region",
          "aria-labelledby": `${detailsId}-title`,
        },
        h(
          "header",
          { className: "anw-chapter-narration-details__header" },
          h("div", null,
            h("strong", { id: `${detailsId}-title` }, detailsHeading(layoutMode)),
            h("span", null, layoutMode === "failure-details"
              ? "失败详情不会改变正文、选角或历史版本。"
              : "朗读版本、声音与维护操作"),
          ),
        ),
        h(
          "div",
          {
            className: "anw-chapter-narration-details__overview",
            hidden: layoutMode !== "expanded",
          },
          h(
            "div",
            { className: "anw-chapter-narration-details__version" },
            editionSelect,
            h("span", null, `${view.sourceLabel} · ${view.playbackLabel}`),
          ),
          h(
            "details",
            { className: "anw-chapter-narration-voices", "aria-label": "本朗读版本的冻结声音" },
            h("summary", null, `本版本声音（${view.voiceIdentities.length}）`),
            view.voiceIdentities.length > 0
              ? h(
                  "ul",
                  null,
                  ...view.voiceIdentities.map((identity) => h(
                    "li",
                    { key: identity.key },
                    h("span", null, identity.displayName),
                    h("small", null, identity.sourceLabel),
                  )),
                )
              : h("p", null, view.voiceSummary),
          ),
          h(
            "div",
            { className: "anw-chapter-narration-player__actions" },
            props.followPaused && noticeActionLabel !== "返回朗读位置"
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-link-button",
                    onClick: props.onResumeFollow,
                  },
                  "返回当前朗读位置",
                )
              : null,
            model.hasEdition && props.cursorPlaybackAvailable && props.onPlaybackFromCursor
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-link-button",
                    disabled: !model.canSeek,
                    onClick: props.onPlaybackFromCursor,
                    title: "从光标所在段朗读（Mod+Alt+Enter）",
                  },
                  "从光标所在段朗读",
                )
              : null,
            props.reviewAvailable && props.onOpenReview
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-link-button",
                    onClick: props.onOpenReview,
                    ref: props.reviewTriggerRef,
                  },
                  "复核脚本",
                )
              : null,
            model.hasEdition && !updateNoticeActive
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-update",
                    disabled: !model.canUpdate,
                    onClick: props.onUpdate,
                  },
                  props.busy ? "正在处理…" : "重新生成朗读",
                )
              : null,
          ),
        ),
        failureList,
      ),
      preferenceAnnouncement
        ? h(
            "div",
            {
              className: `anw-chapter-narration-preference-live is-${
                props.playbackPreferenceStatus?.state ?? "idle"
              }`,
              role: "status",
              "aria-live": "polite",
              "aria-atomic": "true",
            },
            preferenceAnnouncement,
          )
        : null,
      retryAnnouncement
        ? h(
            "div",
            {
              className: props.retryErrorMessage
                ? "anw-chapter-narration-retry-live is-error"
                : "anw-chapter-narration-retry-live",
              role: "status",
              "aria-live": "polite",
              tabIndex: focusedRetryItemStillVisible ? undefined : -1,
              ref: focusedRetryItemStillVisible ? undefined : props.retryTriggerRef,
            },
            retryAnnouncement,
          )
        : null,
      h(
        "div",
        {
          className: "anw-chapter-narration-live",
          role: "status",
          "aria-live": "polite",
          "aria-atomic": "true",
        },
        props.errorMessage ?? props.statusMessage,
      ),
    );
  };
}
