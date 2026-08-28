import type { QwenPawReactRuntime } from "../assistant-pane";
import type { FailedNarrationSegmentsProjection } from "./chapter-contracts";
import type { EditionHistoryItem } from "./edition-history";
import { failedSegmentRetryReasonMessage } from "./failed-segment-retry-state";
import type { NarrationPlayerPhase, NarrationPlayerState } from "./narration-player";
import type { SegmentRenderStatus } from "./playback-contracts";
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
  readonly onGenerate: () => void;
  readonly onUpdate: () => void;
  readonly onTogglePlayback: () => void;
  readonly onSeekOrdinal: (ordinal: number) => void;
  readonly cursorPlaybackAvailable?: boolean;
  readonly onPlaybackFromCursor?: () => void;
  readonly onRateChange: (rate: number) => void;
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
  "createElement"
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
  const currentOrdinal = rawOrdinal === null || rawOrdinal >= props.segments.length
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
      : `${(currentOrdinal ?? 0) + 1} / ${props.segments.length} 句`,
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
    const segmentStates = observableSegmentStates(props.segments, props.segmentStates);
    const failedItems = props.failedSegments?.items ?? [];
    const retryBusySegmentIds = new Set(props.retryBusySegmentIds ?? []);
    const focusedRetryItemStillVisible = props.retryFocusSegmentId !== null
      && props.retryFocusSegmentId !== undefined
      && failedItems.some((item) => item.segment_id === props.retryFocusSegmentId);
    const retryAnnouncement = props.retryErrorMessage ?? props.retryStatusMessage;

    return h(
      "section",
      {
        className: `anw-chapter-narration-player is-${props.phase}`,
        "aria-label": "章节智能朗读播放器",
        "data-source-kind": props.sourceKind,
        "data-player-phase": playerState?.phase ?? "idle",
        "data-player-failure-code": playerState?.failure?.code ?? "",
        "data-current-ordinal": playerState?.currentOrdinal === null
          || playerState?.currentOrdinal === undefined
          ? ""
          : String(playerState.currentOrdinal),
        "data-segment-states": segmentStates,
      },
      h(
        "div",
        { className: "anw-chapter-narration-player__identity" },
        h("span", { className: `anw-chapter-narration-source is-${props.sourceKind}` }, model.sourceLabel),
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
            h("span", null, model.progressLabel),
          )
        : null,
      h(
        "div",
        { className: "anw-chapter-narration-player__actions" },
        model.hasEdition
          ? h(
              "label",
              { className: "anw-chapter-narration-select" },
              h("span", null, "倍速"),
              h(
                "select",
                {
                  value: String(playerState?.rate ?? 1),
                  disabled: props.busy,
                  onChange: (event: { target: { value: string } }) => props.onRateChange(Number(event.target.value)),
                  "aria-label": "朗读倍速",
                },
                ...[0.75, 1, 1.25, 1.5, 2].map((rate) => h(
                  "option",
                  { key: rate, value: String(rate) },
                  `${rate}×`,
                )),
              ),
            )
          : null,
        props.editions.length > 0
          ? h(
              "label",
              { className: "anw-chapter-narration-select" },
              h("span", null, "版本"),
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
          : null,
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
      ),
      failedItems.length > 0
        ? h(
            "section",
            {
              className: "anw-chapter-narration-failures",
              "aria-label": "失败句段重试",
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
