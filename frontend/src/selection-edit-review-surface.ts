import type { QwenPawReactRuntime } from "./assistant-pane";
import {
  selectionEditReviewMetrics,
  type SelectionEditDiffSegment,
  type SelectionEditOperation,
  type SelectionEditReviewDecision,
  type SelectionEditReviewDraft,
  type SelectionEditReviewEvent,
  type SelectionEditReviewFocusTarget,
  type SelectionEditReviewSessionState,
} from "./selection-edit-review";


export type SelectionEditReviewSurfaceReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useEffect" | "useRef"
>;


export type SelectionEditReviewSurfaceAction =
  | { readonly type: "previous-change" }
  | { readonly type: "next-change" }
  | {
    readonly type: "decide";
    readonly segmentId: string;
    readonly decision: SelectionEditReviewDecision;
  }
  | { readonly type: "accept-all" }
  | { readonly type: "apply-accepted" }
  | { readonly type: "reject-all" }
  | { readonly type: "exit" }
  | { readonly type: "cancel-waiting" }
  | { readonly type: "retry" }
  | { readonly type: "copy-candidate"; readonly candidateText: string }
  | { readonly type: "send-to-assistant" }
  | { readonly type: "undo" }
  | { readonly type: "dismiss-applied" };


export interface SelectionEditReviewSurfaceProps {
  readonly state: SelectionEditReviewSessionState;
  readonly onAction: (action: SelectionEditReviewSurfaceAction) => void;
  readonly onReturnFocus?: (
    target: Extract<SelectionEditReviewFocusTarget, { kind: "source-field" }>,
  ) => void;
  readonly onFocusTarget?: (target: SelectionEditReviewFocusTarget) => void;
  readonly className?: string;
}


/** Map controlled UI actions to the coordinator without coupling UI to an API. */
export function selectionEditReviewEventForSurfaceAction(
  action: SelectionEditReviewSurfaceAction,
): SelectionEditReviewEvent | null {
  switch (action.type) {
    case "previous-change":
      return { type: "navigate", direction: "previous" };
    case "next-change":
      return { type: "navigate", direction: "next" };
    case "decide":
      return {
        type: "set-decision",
        segmentId: action.segmentId,
        decision: action.decision,
      };
    case "accept-all":
      return { type: "accept-all" };
    case "apply-accepted":
      return { type: "request-apply" };
    case "reject-all":
      return { type: "reject-all" };
    case "exit":
      return { type: "exit" };
    case "cancel-waiting":
      return { type: "cancel" };
    case "retry":
      return { type: "retry" };
    case "undo":
      return { type: "request-undo" };
    case "dismiss-applied":
      return { type: "reset" };
    case "copy-candidate":
    case "send-to-assistant":
      return null;
  }
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
}


interface SurfaceKeyboardEvent {
  readonly key: string;
  readonly altKey?: boolean;
  readonly ctrlKey?: boolean;
  readonly metaKey?: boolean;
  readonly isComposing?: boolean;
  readonly keyCode?: number;
  preventDefault?(): void;
}


const HEADING_ID = "anw-selection-edit-review-heading";
const LIVE_STATUS_ID = "anw-selection-edit-review-live-status";


const OPERATION_REVIEW_LABELS: Readonly<Record<SelectionEditOperation, string>> = {
  polish: "AI 润色审阅",
  rewrite: "AI 改写审阅",
  expand: "AI 扩写审阅",
  shorten: "AI 缩写审阅",
  dialogue: "AI 增强对白审阅",
  review: "AI 问题检查审阅",
  custom: "AI 自定义修改审阅",
};


function stateDraft(
  state: SelectionEditReviewSessionState,
): SelectionEditReviewDraft | undefined {
  if (state.phase === "reviewing" || state.phase === "applying") return state.draft;
  if (state.phase === "conflict" || state.phase === "failed") return state.draft;
  return undefined;
}


function activeChangeIndex(state: SelectionEditReviewSessionState): number {
  if (state.phase === "reviewing" || state.phase === "applying") {
    return state.activeChangeIndex;
  }
  if (state.phase === "conflict" || state.phase === "failed") {
    return state.activeChangeIndex ?? -1;
  }
  return -1;
}


function segmentOriginalText(segment: SelectionEditDiffSegment): string | undefined {
  return segment.kind === "delete" || segment.kind === "replace"
    ? segment.original_text
    : undefined;
}


function segmentReplacementText(segment: SelectionEditDiffSegment): string | undefined {
  return segment.kind === "insert" || segment.kind === "replace"
    ? segment.replacement_text
    : undefined;
}


export function createSelectionEditReviewSurface(
  React: SelectionEditReviewSurfaceReactRuntime,
): (props: SelectionEditReviewSurfaceProps) => unknown {
  const h = React.createElement;

  return function SelectionEditReviewSurface(
    props: SelectionEditReviewSurfaceProps,
  ): unknown {
    const headingRef = React.useRef<FocusableElement | null>(null);
    const changeRefs = React.useRef<Map<string, FocusableElement>>(new Map());
    const handledFocusSequence = React.useRef(0);
    const compositionActive = React.useRef(false);

    React.useEffect(() => {
      const request = props.state.focusRequest;
      if (!request || handledFocusSequence.current === request.sequence) return;
      handledFocusSequence.current = request.sequence;
      if (request.target.kind === "source-field") {
        props.onReturnFocus?.(request.target);
        props.onFocusTarget?.(request.target);
        return;
      }
      const target = request.target.kind === "change"
        ? changeRefs.current.get(request.target.segmentId)
        : headingRef.current;
      target?.focus({ preventScroll: request.target.kind === "review-heading" });
      props.onFocusTarget?.(request.target);
    }, [props.state.focusRequest?.sequence, props.onFocusTarget, props.onReturnFocus]);

    if (props.state.phase === "idle" || props.state.phase === "discarded") {
      return null;
    }

    const state = props.state;
    const identity = state.identity;
    const draft = stateDraft(state);
    const currentIndex = activeChangeIndex(state);
    const rootClassName = [
      "anw-selection-edit-review",
      `is-${state.phase}`,
      identity.target.mode === "single-line" ? "is-compact" : "is-multiline",
      props.className ?? "",
    ].filter(Boolean).join(" ");

    const emit = (action: SelectionEditReviewSurfaceAction) => props.onAction(action);
    const emitPrimary = () => {
      if (state.phase !== "reviewing") return;
      const metrics = selectionEditReviewMetrics(state.draft);
      if (metrics.changeCount === 0) return;
      if (metrics.decidedCount > 0
        && (metrics.undecidedCount > 0 || metrics.acceptedCount === 0)) return;
      emit(metrics.decidedCount === 0
        ? { type: "accept-all" }
        : { type: "apply-accepted" });
    };
    const currentSegmentId = draft?.reconstruction.changeSegmentIds[currentIndex];
    const onKeyDown = (event: SurfaceKeyboardEvent) => {
      if (compositionActive.current || event.isComposing || event.keyCode === 229) return;
      if (event.key === "Escape") {
        if (state.phase === "preparing" || state.phase === "generating") {
          event.preventDefault?.();
          emit({ type: "cancel-waiting" });
        } else if (state.phase === "reviewing"
          || state.phase === "failed"
          || state.phase === "conflict") {
          event.preventDefault?.();
          emit({ type: "exit" });
        }
        return;
      }
      if (state.phase !== "reviewing") return;
      if (event.altKey && event.key === "ArrowUp") {
        event.preventDefault?.();
        emit({ type: "previous-change" });
        return;
      }
      if (event.altKey && event.key === "ArrowDown") {
        event.preventDefault?.();
        emit({ type: "next-change" });
        return;
      }
      if (event.altKey && event.key.toLowerCase() === "a" && currentSegmentId) {
        event.preventDefault?.();
        emit({ type: "decide", segmentId: currentSegmentId, decision: "accept" });
        return;
      }
      if (event.altKey && event.key.toLowerCase() === "r" && currentSegmentId) {
        event.preventDefault?.();
        emit({ type: "decide", segmentId: currentSegmentId, decision: "reject" });
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault?.();
        emitPrimary();
      }
    };

    const commonRootProps = {
      "aria-busy": state.phase === "preparing"
        || state.phase === "generating"
        || state.phase === "applying",
      "aria-describedby": LIVE_STATUS_ID,
      "aria-labelledby": HEADING_ID,
      className: rootClassName,
      "data-review-field-id": identity.target.fieldId,
      "data-review-phase": state.phase,
      onCompositionEnd: () => { compositionActive.current = false; },
      onCompositionStart: () => { compositionActive.current = true; },
      onKeyDown,
      role: "region",
    };
    const heading = (label: string) => h(
      "h2",
      {
        id: HEADING_ID,
        ref: (element: FocusableElement | null) => { headingRef.current = element; },
        tabIndex: -1,
      },
      label,
    );
    const liveStatus = h(
      "p",
      {
        className: "anw-selection-edit-review-live",
        id: LIVE_STATUS_ID,
        "aria-live": "polite",
        role: "status",
      },
      state.liveMessage,
    );
    const originalText = h(
      "pre",
      {
        className: "anw-selection-edit-review-original",
        "aria-label": "原选区，只读",
      },
      identity.baseText,
    );

    const renderDiff = (
      reviewDraft: SelectionEditReviewDraft,
      interactive: boolean,
    ) => {
      const changeIndexById = new Map(
        reviewDraft.reconstruction.changeSegmentIds.map((segmentId, index) => [
          segmentId,
          index,
        ]),
      );
      return h(
        "ol",
        {
          className: "anw-selection-edit-review-diff",
          "aria-label": "统一差异审阅",
        },
        ...reviewDraft.result.diff_segments.map((segment) => {
          if (segment.kind === "equal") {
            return h(
              "li",
              {
                key: segment.segment_id,
                className: "anw-selection-edit-review-context",
                "aria-label": "未修改上下文",
              },
              h("span", null, segment.text),
            );
          }
          const segmentIndex = changeIndexById.get(segment.segment_id) ?? -1;
          const decision = reviewDraft.decisions[segment.segment_id];
          const original = segmentOriginalText(segment);
          const replacement = segmentReplacementText(segment);
          const current = segmentIndex === currentIndex;
          return h(
            "li",
            {
              key: segment.segment_id,
              ref: (element: FocusableElement | null) => {
                if (element) changeRefs.current.set(segment.segment_id, element);
                else changeRefs.current.delete(segment.segment_id);
              },
              className: [
                "anw-selection-edit-review-change",
                current ? "is-current" : "",
                decision ? `is-${decision}` : "is-undecided",
              ].filter(Boolean).join(" "),
              "aria-current": current ? "step" : undefined,
              "aria-label": `第 ${segmentIndex + 1} 处修改，${decision === "accept"
                ? "已接受"
                : decision === "reject" ? "已拒绝" : "未决定"}`,
              "data-review-decision": decision ?? "undecided",
              "data-review-segment-id": segment.segment_id,
              tabIndex: -1,
            },
            h(
              "div",
              { className: "anw-selection-edit-review-change-lines" },
              original !== undefined
                ? h(
                  "div",
                  {
                    className: [
                      "anw-selection-edit-review-line",
                      "anw-selection-edit-review-delete",
                    ].join(" "),
                    "data-diff-kind": "delete",
                  },
                  h("span", { "aria-hidden": "true" }, "−"),
                  h("strong", null, "删除"),
                  h("span", null, original || "（空文本）"),
                )
                : null,
              replacement !== undefined
                ? h(
                  "div",
                  {
                    className: [
                      "anw-selection-edit-review-line",
                      "anw-selection-edit-review-insert",
                    ].join(" "),
                    "data-diff-kind": "insert",
                  },
                  h("span", { "aria-hidden": "true" }, "+"),
                  h("strong", null, "新增"),
                  h("span", null, replacement || "（空文本）"),
                )
                : null,
              segment.kind === "delete"
                ? h(
                  "div",
                  {
                    className: [
                      "anw-selection-edit-review-line",
                      "anw-selection-edit-review-result",
                      "anw-selection-edit-review-empty-result",
                    ].join(" "),
                    "data-diff-kind": "result-empty",
                    role: "note",
                    "aria-label": "应用后结果为空，删除此段文字",
                  },
                  h("span", { "aria-hidden": "true" }, "="),
                  h("strong", null, "应用后结果"),
                  h("span", null, "为空（删除此段，不保留文字）"),
                )
                : null,
            ),
            h(
              "div",
              {
                className: [
                  "anw-selection-edit-review-inline-actions",
                  interactive ? "" : "is-read-only",
                ].filter(Boolean).join(" "),
                ...(interactive
                  ? {
                    role: "group",
                    "aria-label": `第 ${segmentIndex + 1} 处修改决定`,
                  }
                  : {}),
              },
              interactive
                ? h(
                  "button",
                  {
                    type: "button",
                    "aria-label": `接受第 ${segmentIndex + 1} 处修改`,
                    "aria-pressed": decision === "accept",
                    onClick: () => emit({
                      type: "decide",
                      segmentId: segment.segment_id,
                      decision: "accept",
                    }),
                    title: "接受当前修改（Alt+A）",
                  },
                  "接受",
                )
                : h(
                  "p",
                  { className: "anw-selection-edit-review-decision-label" },
                  decision === "accept" ? "已接受" : decision === "reject" ? "已拒绝" : "未决定",
                ),
              interactive
                ? h(
                  "button",
                  {
                    type: "button",
                    "aria-label": `拒绝第 ${segmentIndex + 1} 处修改`,
                    "aria-pressed": decision === "reject",
                    onClick: () => emit({
                      type: "decide",
                      segmentId: segment.segment_id,
                      decision: "reject",
                    }),
                    title: "拒绝当前修改（Alt+R）",
                  },
                  "拒绝",
                )
                : null,
            ),
          );
        }),
      );
    };

    if (state.phase === "preparing" || state.phase === "generating") {
      return h(
        "section",
        commonRootProps,
        heading(state.phase === "preparing" ? "正在准备 AI 修改" : "AI 正在生成候选"),
        liveStatus,
        originalText,
        h(
          "div",
          { className: "anw-selection-edit-review-status-actions" },
          h(
            "button",
            { type: "button", onClick: () => emit({ type: "cancel-waiting" }) },
            "停止等待",
          ),
        ),
      );
    }

    if (state.phase === "failed") {
      return h(
        "section",
        commonRootProps,
        heading("选区编辑失败"),
        liveStatus,
        h("p", { className: "anw-selection-edit-review-error" }, state.message),
        originalText,
        h(
          "div",
          { className: "anw-selection-edit-review-status-actions", role: "group", "aria-label": "失败处理" },
          state.retryable
            ? h("button", { type: "button", onClick: () => emit({ type: "retry" }) }, "重试")
            : null,
          h(
            "button",
            { type: "button", onClick: () => emit({ type: "send-to-assistant" }) },
            "发送到助手",
          ),
          h("button", { type: "button", onClick: () => emit({ type: "exit" }) }, "退出"),
        ),
      );
    }

    if (state.phase === "conflict") {
      return h(
        "section",
        commonRootProps,
        heading("内容发生冲突"),
        liveStatus,
        h("p", { className: "anw-selection-edit-review-error" }, state.message),
        draft ? renderDiff(draft, false) : originalText,
        h(
          "div",
          { className: "anw-selection-edit-review-status-actions", role: "group", "aria-label": "冲突处理" },
          draft
            ? h(
              "button",
              {
                type: "button",
                onClick: () => emit({
                  type: "copy-candidate",
                  candidateText: draft.reconstruction.candidateText,
                }),
              },
              "复制候选",
            )
            : null,
          h("button", { type: "button", onClick: () => emit({ type: "retry" }) }, "基于新稿重新生成"),
          h("button", { type: "button", onClick: () => emit({ type: "exit" }) }, "放弃"),
        ),
      );
    }

    if (state.phase === "applied") {
      return h(
        "section",
        commonRootProps,
        heading("AI 修改已应用"),
        liveStatus,
        h("p", null, state.message),
        h(
          "div",
          { className: "anw-selection-edit-review-status-actions", role: "group", "aria-label": "应用完成操作" },
          state.canUndo
            ? h(
              "button",
              {
                type: "button",
                disabled: state.undoPending,
                onClick: () => emit({ type: "undo" }),
              },
              state.undoPending ? "正在撤销" : "撤销 AI 修改",
            )
            : null,
          h(
            "button",
            {
              type: "button",
              disabled: state.undoPending,
              onClick: () => emit({ type: "dismiss-applied" }),
            },
            "继续编辑",
          ),
        ),
      );
    }

    const reviewState = state;
    const metrics = selectionEditReviewMetrics(reviewState.draft);
    const isApplying = reviewState.phase === "applying";
    const primaryIsApplyAccepted = metrics.decidedCount > 0;
    const primaryDisabled = isApplying
      || metrics.changeCount === 0
      || (primaryIsApplyAccepted
        && (metrics.undecidedCount > 0 || metrics.acceptedCount === 0));
    const primaryLabel = primaryIsApplyAccepted
      ? `应用已接受修改（${metrics.acceptedCount}处）`
      : "接受全部";
    const activeHumanIndex = reviewState.activeChangeIndex + 1;
    const operationReviewLabel = OPERATION_REVIEW_LABELS[identity.operation];

    return h(
      "section",
      commonRootProps,
      h(
        "div",
        {
          className: "anw-selection-edit-review-toolbar",
          role: "toolbar",
          "aria-label": "差异审阅操作",
        },
        h(
          "div",
          { className: "anw-selection-edit-review-toolbar-summary" },
          heading(operationReviewLabel),
          h(
            "span",
            { className: "anw-selection-edit-review-change-count" },
            `${metrics.changeCount} 处修改`,
          ),
        ),
        h(
          "button",
          {
            type: "button",
            disabled: isApplying || reviewState.activeChangeIndex <= 0,
            onClick: () => emit({ type: "previous-change" }),
            title: "上一处（Alt+↑）",
          },
          "上一处",
        ),
        h(
          "button",
          {
            type: "button",
            disabled: isApplying
              || reviewState.activeChangeIndex < 0
              || reviewState.activeChangeIndex >= metrics.changeCount - 1,
            onClick: () => emit({ type: "next-change" }),
            title: "下一处（Alt+↓）",
          },
          "下一处",
        ),
        h(
          "button",
          {
            type: "button",
            disabled: isApplying || metrics.changeCount === 0,
            onClick: () => emit({ type: "reject-all" }),
          },
          "拒绝全部",
        ),
        h(
          "button",
          {
            type: "button",
            disabled: primaryDisabled,
            onClick: emitPrimary,
            title: primaryIsApplyAccepted ? "应用已完成决定的修改（Ctrl/⌘+Enter）" : undefined,
          },
          isApplying ? "正在应用" : primaryLabel,
        ),
        h(
          "button",
          {
            type: "button",
            disabled: isApplying,
            onClick: () => emit({ type: "exit" }),
          },
          "退出审阅",
        ),
      ),
      h(
        "header",
        {
          className: "anw-selection-edit-review-header",
          "aria-label": isApplying ? "正在应用选区修改" : "候选摘要",
        },
        h("p", null, reviewState.draft.result.short_summary),
        reviewState.draft.result.warnings.length > 0
          ? h(
            "ul",
            { className: "anw-selection-edit-review-warnings", "aria-label": "候选提醒" },
            ...reviewState.draft.result.warnings.map((warning, index) => h(
              "li",
              { key: `${index}:${warning}` },
              warning,
            )),
          )
          : null,
      ),
      metrics.changeCount === 0
        ? h(
          "div",
          { className: "anw-selection-edit-review-empty", role: "status" },
          "未发现需要修改的差异",
        )
        : renderDiff(reviewState.draft, !isApplying),
      liveStatus,
      h(
        "footer",
        { className: "anw-selection-edit-review-footer" },
        h("span", null, metrics.changeCount > 0 ? `当前 ${activeHumanIndex}/${metrics.changeCount}` : "无差异"),
        h("span", null, `已处理 ${metrics.decidedCount}/${metrics.changeCount}`),
        h("span", null, `候选 ${reviewState.draft.result.replacement_character_count} 字`),
      ),
    );
  };
}
