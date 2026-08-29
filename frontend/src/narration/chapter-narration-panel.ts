import type { QwenPawReactRuntime } from "../assistant-pane";
import type {
  FailedNarrationSegmentsProjection,
  NarrationEditionVoiceIdentity,
} from "./chapter-contracts";
import {
  INITIAL_CHAPTER_PLAYER_LAYOUT_STATE,
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
  const playbackLabel = props.playerState?.phase === "playing"
    ? "暂停"
    : props.playerState?.phase === "preparing"
    ? "准备中"
    : props.playerState?.phase === "buffering"
    ? "缓冲中"
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


function buttonIcon(label: string): string {
  switch (label) {
    case "上一句": return "⏮";
    case "下一句": return "⏭";
    case "暂停": return "Ⅱ";
    case "准备中": return "…";
    case "缓冲中": return "…";
    default: return "▶";
  }
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
    const moreTriggerRef = React.useRef<{ focus(): void } | null>(null);
    const failureTriggerRef = React.useRef<{ focus(): void } | null>(null);
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

    return h(
      "section",
      {
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
      },
      h(
        "div",
        { className: "anw-chapter-narration-player__compact" },
        h(
          "div",
          { className: "anw-chapter-narration-player__identity" },
          h("span", { className: `anw-chapter-narration-source is-${props.sourceKind}` }, view.sourceLabel),
          h(
            "div",
            { className: "anw-chapter-narration-current-copy" },
            h(
              "strong",
              null,
              `${model.currentSegment?.speaker_label ?? "章节朗读"}${
                props.sourceKind === "working-copy-diverged" ? " · 旧稿字幕" : ""
              }`,
            ),
            h(
              "span",
              { className: "anw-chapter-narration-voice-summary" },
              view.voiceSummary,
            ),
            h(
              "span",
              { title: model.currentSegment?.source_text ?? props.statusMessage },
              model.currentSegment?.source_text ?? props.statusMessage,
            ),
          ),
        ),
        h(
          "div",
          { className: "anw-chapter-narration-player__controls" },
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
                buttonIcon("上一句"),
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
                  "aria-label": model.playbackLabel === "暂停" ? "暂停章节朗读" : "播放章节朗读",
                },
                buttonIcon(model.playbackLabel),
              )
            : h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-primary-action",
                  disabled: !model.canGenerate,
                  onClick: props.onGenerate,
                },
                props.busy ? "正在分析人物与选角…" : "智能朗读",
              ),
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
                buttonIcon("下一句"),
              )
            : null,
        ),
        h(
          "div",
          { className: "anw-chapter-narration-player__metrics", "aria-label": "朗读进度摘要" },
          h(
            "div",
            { className: "anw-chapter-narration-metric" },
            h("span", null, "当前"),
            h("strong", null, `${view.currentTimeLabel} · 第 ${view.currentSentenceLabel} 句`),
          ),
          h(
            "div",
            { className: "anw-chapter-narration-metric" },
            h("span", null, "可播放"),
            h("strong", null, `${view.playableDurationLabel} · ${view.playableSentenceLabel} 句`),
          ),
          h(
            "div",
            { className: `anw-chapter-narration-generation is-${view.generation.state}` },
            h(
              "div",
              null,
              h("span", null, "全章生成"),
              h("strong", null, `${view.generation.completionPercent}%`),
            ),
            h("progress", {
              max: Math.max(1, view.generation.totalCount),
              value: view.generation.completedCount,
              "aria-label": "全章音频生成进度",
              "aria-valuetext": view.generation.label,
            }),
          ),
        ),
        model.hasEdition
          ? h(
              "div",
              { className: "anw-chapter-narration-player__preferences" },
              h(
                "label",
                { className: "anw-chapter-narration-select" },
                h("span", null, "倍速"),
                h(
                  "select",
                  {
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
                "label",
                { className: "anw-chapter-narration-volume" },
                h("span", null, "音量"),
                h("input", {
                  id: "anw-chapter-narration-volume",
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
                h("output", { htmlFor: "anw-chapter-narration-volume" }, `${currentVolumePercent}%`),
              ),
            )
          : null,
        h(
          "div",
          { className: "anw-chapter-narration-player__view-actions" },
          failedItems.length > 0
            ? h(
                "button",
                {
                  type: "button",
                  className: "anw-chapter-narration-failure-trigger",
                  ref: failureTriggerRef,
                  "aria-controls": detailsId,
                  "aria-expanded": layoutMode === "failure-details",
                  onClick: () => setLayout({
                    type: "open-failure-details",
                    failureCount: failedItems.length,
                  }),
                },
                `失败 ${failedItems.length}`,
              )
            : null,
          h(
            "button",
            {
              type: "button",
              className: "anw-chapter-narration-more",
              ref: moreTriggerRef,
              "aria-controls": detailsId,
              "aria-expanded": layoutMode === "expanded",
              onClick: () => setLayout({ type: "toggle-expanded" }),
            },
            layoutMode === "expanded" ? "收起" : "更多",
          ),
        ),
      ),
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
            h("span", null, `${model.progressLabel} · ${view.playbackLabel}`),
          )
        : null,
      h(
        "section",
        {
          id: detailsId,
          className: `anw-chapter-narration-details is-${layoutMode}`,
          hidden: !detailsVisible,
          role: "region",
          "aria-label": detailsHeading(layoutMode),
        },
        h(
          "header",
          { className: "anw-chapter-narration-details__header" },
          h("div", null,
            h("strong", null, detailsHeading(layoutMode)),
            h("span", null, layoutMode === "failure-details"
              ? "失败详情不会改变正文、选角或历史版本。"
              : "状态、冻结音色和次要操作"),
          ),
          h(
            "button",
            {
              type: "button",
              className: "anw-chapter-narration-details__close",
              onClick: closeDetails,
              "aria-label": "关闭朗读详情",
            },
            "关闭",
          ),
        ),
        h(
          "div",
          {
            className: "anw-chapter-narration-details__overview",
            hidden: layoutMode !== "expanded",
          },
          h(
            "dl",
            { className: "anw-chapter-narration-status-grid", "aria-label": "朗读正交状态" },
            h("div", null, h("dt", null, "内容"), h("dd", null, view.contentLabel)),
            h("div", null, h("dt", null, "播放"), h("dd", null, view.playbackLabel)),
            h("div", null, h("dt", null, "来源"), h("dd", null, view.sourceLabel)),
            h("div", null, h("dt", null, "生成"), h("dd", null, view.generation.label)),
          ),
          h(
            "section",
            { className: "anw-chapter-narration-voices", "aria-label": "本朗读版本冻结音色" },
            h("strong", null, "本 Edition 冻结音色"),
            view.voiceIdentities.length > 0
              ? h(
                  "ul",
                  null,
                  ...view.voiceIdentities.map((identity) => h(
                    "li",
                    { key: identity.key },
                    h("span", null, identity.displayName),
                    h("small", null, `${identity.sourceLabel} · 稳定标识 ${identity.stableIdentifier}`),
                  )),
                )
              : h("p", null, view.voiceSummary),
          ),
          h(
            "div",
            { className: "anw-chapter-narration-player__actions" },
            editionSelect,
            props.followPaused
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
            model.hasEdition
              ? h(
                  "button",
                  {
                    type: "button",
                    className: `anw-chapter-narration-update ${props.updateRequired ? "is-required" : ""}`,
                    disabled: !model.canUpdate,
                    onClick: props.onUpdate,
                  },
                  props.busy ? "正在处理…" : props.updateRequired ? "更新朗读" : "重新生成朗读",
                )
              : null,
            failedItems.length > 0
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-chapter-narration-link-button",
                    onClick: () => setLayout({
                      type: "open-failure-details",
                      failureCount: failedItems.length,
                    }),
                  },
                  `查看 ${failedItems.length} 个失败句段`,
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
          className: `anw-chapter-narration-live ${props.errorMessage ? "is-error" : ""}`,
          role: "status",
          "aria-live": "polite",
        },
        props.errorMessage ?? props.statusMessage,
      ),
    );
  };
}
