import type { QwenPawReactRuntime } from "../assistant-pane";
import {
  ScriptApiError,
  approveNarrationScriptVersion,
  reanalyzeNarrationScriptSegments,
} from "./script-api";
import { ScriptContractError } from "./script-contracts";
import type {
  ApproveScriptRequest,
  ReanalyzeSegmentsRequest,
  ScriptApiErrorCode,
  ScriptIssueCode,
  ScriptReviewIssueResource,
  ScriptReviewResource,
  ScriptReviewSegmentResource,
} from "./script-contracts";
import type { ScriptReviewVersionScope } from "./script-api";
import type { CompactNarrationPlayerView } from "./chapter-narration-state";
import { createNarrationIdempotencyKey } from "./idempotency-key";


export type ScriptReviewReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useState" | "useRef" | "useEffect"
>;


export interface ScriptReviewFocusTarget {
  focus(): void;
}


export interface ScriptReviewFocusRef {
  readonly current: ScriptReviewFocusTarget | null;
}


export interface ScriptReviewPanelApi {
  approve(
    versionId: string,
    payload: ApproveScriptRequest,
    expectedScope: ScriptReviewVersionScope,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ScriptReviewResource>;
  reanalyzeSegments(
    versionId: string,
    payload: ReanalyzeSegmentsRequest,
    expectedScope: ScriptReviewVersionScope,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ScriptReviewResource>;
}


export interface ScriptReviewPanelProps {
  readonly review: ScriptReviewResource;
  readonly requestId: string;
  readonly requestVersion: number;
  readonly triggerRef?: ScriptReviewFocusRef;
  readonly onReviewChanged?: (review: ScriptReviewResource) => void;
  readonly onEditSegment?: (segment: ScriptReviewSegmentResource) => void;
  readonly onUseLatestSource?: (
    review: ScriptReviewResource,
    signal: AbortSignal,
  ) => Promise<ScriptReviewResource>;
  readonly onClose?: () => void;
  readonly createIdempotencyKey?: () => string;
  readonly compactPlayer?: ScriptReviewCompactPlayerProps;
}


export interface ScriptReviewCompactPlayerProps extends CompactNarrationPlayerView {
  readonly onTogglePlayback: () => void;
  readonly onOpenOldDraft?: () => void;
}


export interface ScriptReviewPanelFailure {
  readonly code: ScriptApiErrorCode | "NETWORK_ERROR" | "CANCELLED" | "RESPONSE_SCOPE_MISMATCH";
  readonly message: string;
  readonly retryable: boolean;
  readonly refreshRequired: boolean;
}


export interface ScriptReviewPanelModel {
  readonly visibleIssues: readonly ScriptReviewIssueResource[];
  readonly visibleSegments: readonly ScriptReviewSegmentResource[];
  readonly canApprove: boolean;
  readonly canEdit: boolean;
  readonly canReanalyze: boolean;
  readonly showEdit: boolean;
  readonly showReanalyze: boolean;
  readonly needsSnapshotChoice: boolean;
  readonly primaryLabel: string;
  readonly summary: string;
}


export type ScriptReviewAssignableSpeakerKind = "narrator" | "character" | "anonymous";


export interface ScriptReviewSpeakerChoice {
  readonly key: string;
  readonly speakerKind: ScriptReviewAssignableSpeakerKind;
  readonly speakerLabel: string;
  readonly characterId: string | null;
  readonly anonymousSpeakerId: string | null;
}


export interface ScriptReviewActiveCharacterBinding {
  readonly characterId: string;
  readonly speakerLabel: string;
}


interface OperationState {
  readonly busy: boolean;
  readonly message: string | null;
  readonly failure: ScriptReviewPanelFailure | null;
}


const IDLE_OPERATION: OperationState = { busy: false, message: null, failure: null };

const DEFAULT_API: ScriptReviewPanelApi = {
  approve: approveNarrationScriptVersion,
  reanalyzeSegments: reanalyzeNarrationScriptSegments,
};

const ISSUE_LABELS: Readonly<Record<ScriptIssueCode, string>> = {
  W_SPEAKER_MEDIUM_CONFIDENCE: "说话人判断为中等置信度",
  W_NEW_ANONYMOUS_SPEAKER: "发现新的匿名人物",
  W_GENERIC_VOICE_FALLBACK: "使用了通用音色回退",
  W_MANUAL_OVERRIDE_INHERITED: "继承了作者的历史人工修正",
  W_PRONUNCIATION_SOFT_FALLBACK: "发音规则使用了安全回退",
  W_CLOUD_ASSISTED_USED: "该句使用了已授权的云端辅助",
  W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE: "场景边界为中等置信度",
  B_SPEAKER_UNKNOWN: "无法确定这一句由谁说",
  B_SPEAKER_LOW_CONFIDENCE: "说话人判断置信度过低",
  B_CHARACTER_ALIAS_CONFLICT: "人物别名指向多个角色",
  B_CHARACTER_REFERENCE_INVALID: "人物卡引用无效或不属于本作品",
  B_ANONYMOUS_IDENTITY_CONFLICT: "匿名人物身份发生冲突",
  B_CASTING_TARGET_UNRESOLVED: "尚未解析到可用音色",
  B_VOICE_MISSING: "缺少所需音色",
  B_VOICE_VERSION_UNAVAILABLE: "锁定的音色版本当前不可用",
  B_VOICE_RIGHTS_UNAVAILABLE: "音色授权当前不可用于合成",
  B_PRONUNCIATION_HARD_CONFLICT: "发音规则存在硬冲突",
  B_CLOUD_DECISION_UNAVAILABLE: "云端辅助不可用且本地规则无法确定",
};


export function scriptReviewIssueLabel(code: ScriptIssueCode): string {
  return ISSUE_LABELS[code];
}


export function buildScriptReviewPanelModel(input: {
  readonly review: ScriptReviewResource;
  readonly showAllIssues: boolean;
  readonly snapshotConfirmed: boolean;
  readonly busy: boolean;
}): ScriptReviewPanelModel {
  const review = input.review;
  const visibleIssues = review.issues.filter((issue) => (
    input.showAllIssues || issue.severity === "blocker"
  ));
  const visibleSegmentIds = new Set(
    visibleIssues
      .map((issue) => issue.segment_id)
      .filter((segmentId): segmentId is string => segmentId !== null),
  );
  const visibleSegments = visibleIssues.length === 0
    ? review.issues.length === 0
      ? [...review.segments]
      : []
    : review.segments.filter((segment) => visibleSegmentIds.has(segment.segment_id));
  const actionSet = new Set(review.allowed_actions);
  const showEdit = actionSet.has("edit_segment");
  const showReanalyze = actionSet.has("reanalyze_segments");
  const needsSnapshotChoice = review.source_status === "working_copy_diverged"
    && !input.snapshotConfirmed;
  const canApprove = actionSet.has("approve")
    && review.state === "review_required"
    && review.blocker_count === 0
    && !needsSnapshotChoice
    && !input.busy;
  let primaryLabel = "确认并冻结脚本";
  if (review.blocker_count > 0) primaryLabel = `仍有 ${review.blocker_count} 个阻塞`;
  if (review.state === "approved") primaryLabel = "脚本已冻结";
  return {
    visibleIssues: Object.freeze(visibleIssues),
    visibleSegments: Object.freeze(visibleSegments),
    canApprove,
    canEdit: showEdit && !input.busy,
    canReanalyze: showReanalyze && !input.busy,
    showEdit,
    showReanalyze,
    needsSnapshotChoice,
    primaryLabel,
    summary: `${review.blocker_count} 个阻塞 · ${review.warning_count} 个提醒 · ${review.segments.length} 个句段`,
  };
}


/**
 * Combine the current server-produced review authority with a freshly loaded
 * active-character binding list. Group targets stay unavailable until the
 * backend publishes a dedicated group correction contract.
 */
export function buildScriptReviewSpeakerChoices(
  review: ScriptReviewResource,
  activeCharacterBindings: readonly ScriptReviewActiveCharacterBinding[] = [],
): readonly ScriptReviewSpeakerChoice[] {
  const choices = new Map<string, ScriptReviewSpeakerChoice>();
  choices.set("narrator", Object.freeze({
    key: "narrator",
    speakerKind: "narrator",
    speakerLabel: review.segments.find((segment) => segment.speaker_kind === "narrator")
      ?.speaker_label || "旁白",
    characterId: null,
    anonymousSpeakerId: null,
  }));
  for (const binding of activeCharacterBindings) {
    const key = `character:${binding.characterId}`;
    if (!choices.has(key)) {
      choices.set(key, Object.freeze({
        key,
        speakerKind: "character",
        speakerLabel: binding.speakerLabel,
        characterId: binding.characterId,
        anonymousSpeakerId: null,
      }));
    }
  }
  for (const segment of review.segments) {
    if (segment.casting_state !== "resolved") continue;
    if (segment.speaker_kind === "anonymous" && segment.anonymous_speaker_id !== null) {
      const key = `anonymous:${segment.anonymous_speaker_id}`;
      if (!choices.has(key)) {
        choices.set(key, Object.freeze({
          key,
          speakerKind: "anonymous",
          speakerLabel: segment.speaker_label,
          characterId: null,
          anonymousSpeakerId: segment.anonymous_speaker_id,
        }));
      }
    }
  }
  return Object.freeze([...choices.values()]);
}


function abortLike(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


export function classifyScriptReviewFailure(reason: unknown): ScriptReviewPanelFailure {
  if (abortLike(reason)) {
    return {
      code: "CANCELLED",
      message: "操作已取消。",
      retryable: false,
      refreshRequired: false,
    };
  }
  if (reason instanceof ScriptContractError) {
    return scopeMismatchFailure();
  }
  if (!(reason instanceof ScriptApiError)) {
    return {
      code: "NETWORK_ERROR",
      message: "脚本复核服务连接失败，已保留当前复核内容。",
      retryable: true,
      refreshRequired: false,
    };
  }
  if (["VERSION_CONFLICT", "STALE_INPUT"].includes(reason.detail.code)) {
    return {
      code: reason.detail.code,
      message: "正文或脚本版本已经变化，请加载最新复核结果。",
      retryable: false,
      refreshRequired: true,
    };
  }
  if (["RESOURCE_NOT_FOUND", "SCOPE_VIOLATION"].includes(reason.detail.code)) {
    return {
      code: reason.detail.code,
      message: "找不到本作品的脚本快照，或访问范围已经变化。",
      retryable: false,
      refreshRequired: true,
    };
  }
  if (reason.detail.code === "SCRIPT_BACKEND_NOT_INSTALLED") {
    return {
      code: reason.detail.code,
      message: "脚本复核仍处于 T3 产品门禁，当前不可操作。",
      retryable: false,
      refreshRequired: false,
    };
  }
  return {
    code: reason.detail.code,
    message: "脚本复核操作未完成，旧脚本版本没有被覆盖。",
    retryable: reason.detail.retryable,
    refreshRequired: false,
  };
}


function scopeMismatchFailure(): ScriptReviewPanelFailure {
  return {
    code: "RESPONSE_SCOPE_MISMATCH",
    message: "服务返回了其他作品或脚本的结果，已拒绝应用。",
    retryable: false,
    refreshRequired: true,
  };
}


function defaultIdempotencyKey(): string {
  return createNarrationIdempotencyKey("script", ":");
}


function hasBlocker(
  segment: ScriptReviewSegmentResource,
  issues: readonly ScriptReviewIssueResource[],
): boolean {
  return issues.some((issue) => (
    issue.segment_id === segment.segment_id && issue.severity === "blocker"
  ));
}


function versionScope(review: ScriptReviewResource): ScriptReviewVersionScope {
  return {
    novel_id: review.novel_id,
    document_id: review.document_id,
    revision_id: review.revision_id,
    source_content_hash: review.source_content_hash,
    script_id: review.script_id,
    script_version_id: review.script_version_id,
  };
}


function sameFrozenSource(
  candidate: ScriptReviewResource,
  current: ScriptReviewResource,
): boolean {
  return candidate.script_id === current.script_id
    && candidate.novel_id === current.novel_id
    && candidate.document_id === current.document_id
    && candidate.revision_id === current.revision_id
    && candidate.source_content_hash === current.source_content_hash;
}


function compactPlayerActionLabel(phase: CompactNarrationPlayerView["phase"]): string {
  return phase === "paused" ? "继续朗读" : "暂停朗读";
}


function renderCompactPlayer(
  h: ScriptReviewReactRuntime["createElement"],
  player: ScriptReviewCompactPlayerProps,
): unknown {
  const boundedDuration = Math.max(1, player.durationMs);
  const boundedOffset = Math.min(Math.max(0, player.offsetMs), boundedDuration);
  return h(
    "div",
    {
      className: "anw-script-review__compact-player",
      role: "group",
      "aria-label": "紧凑朗读播放器",
      "data-player-layout": "compact",
      "data-source-status": player.sourceStatus,
    },
    h(
      "div",
      { className: "anw-script-review__compact-player-status" },
      h("strong", null, player.oldDraft ? "旧稿朗读" : "当前稿朗读"),
      h("span", null, `说话人：${player.speakerLabel}`),
      h(
        "span",
        { role: "status", "aria-live": "polite" },
        player.phase === "playing" ? "正在播放" : player.phase === "paused" ? "已暂停" : "正在准备",
      ),
    ),
    h("progress", {
      value: boundedOffset,
      max: boundedDuration,
      "aria-label": "当前句段朗读进度",
    }),
    h(
      "div",
      { className: "anw-script-review__compact-player-actions" },
      h("button", {
        type: "button",
        onClick: player.onTogglePlayback,
        "aria-label": compactPlayerActionLabel(player.phase),
      }, compactPlayerActionLabel(player.phase)),
      player.oldDraft && player.onOpenOldDraft !== undefined
        ? h("button", {
          type: "button",
          onClick: player.onOpenOldDraft,
        }, "查看不可变旧稿")
        : null,
    ),
  );
}


export function createScriptReviewPanel(
  React: ScriptReviewReactRuntime,
  api: ScriptReviewPanelApi = DEFAULT_API,
): (props: ScriptReviewPanelProps) => unknown {
  const h = React.createElement;
  return function ScriptReviewPanel(props: ScriptReviewPanelProps): unknown {
    const [showAllIssues, setShowAllIssues] = React.useState(
      props.review.blocker_count === 0,
    );
    const [snapshotConfirmed, setSnapshotConfirmed] = React.useState(
      props.review.source_status !== "working_copy_diverged",
    );
    const [operation, setOperation] = React.useState<OperationState>(IDLE_OPERATION);
    const titleRef = React.useRef<ScriptReviewFocusTarget | null>(null);
    const firstBlockerRef = React.useRef<ScriptReviewFocusTarget | null>(null);
    const controllers = React.useRef<Set<AbortController>>(new Set());
    const actionKeys = React.useRef<Map<string, string>>(new Map());
    const versionRef = React.useRef(props.review.script_version_id);
    const requestVersionRef = React.useRef(props.requestVersion);
    const restoredRef = React.useRef(false);

    const restoreFocus = (): void => {
      if (restoredRef.current) return;
      restoredRef.current = true;
      props.triggerRef?.current?.focus();
    };

    React.useEffect(() => () => {
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
      restoreFocus();
    }, []);

    React.useEffect(() => {
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
      versionRef.current = props.review.script_version_id;
      requestVersionRef.current = props.requestVersion;
      restoredRef.current = false;
      setShowAllIssues(props.review.blocker_count === 0);
      setSnapshotConfirmed(props.review.source_status !== "working_copy_diverged");
      setOperation(IDLE_OPERATION);
      actionKeys.current.clear();
      firstBlockerRef.current?.focus();
      if (firstBlockerRef.current === null) titleRef.current?.focus();
    }, [props.review.script_version_id, props.requestVersion]);

    const model = buildScriptReviewPanelModel({
      review: props.review,
      showAllIssues,
      snapshotConfirmed,
      busy: operation.busy,
    });

    const begin = (): AbortController => {
      const controller = new AbortController();
      controllers.current.add(controller);
      setOperation({ busy: true, message: null, failure: null });
      return controller;
    };
    const finish = (controller: AbortController): boolean => {
      controllers.current.delete(controller);
      return !controller.signal.aborted
        && versionRef.current === props.review.script_version_id
        && requestVersionRef.current === props.requestVersion;
    };
    const fail = (controller: AbortController, reason: unknown): void => {
      if (!finish(controller)) return;
      const failure = classifyScriptReviewFailure(reason);
      if (failure.code === "CANCELLED") return;
      setOperation({ busy: false, message: null, failure });
    };
    const keyFor = (action: string): string | null => {
      const existing = actionKeys.current.get(action);
      if (existing) return existing;
      try {
        const value = (props.createIdempotencyKey ?? defaultIdempotencyKey)();
        actionKeys.current.set(action, value);
        return value;
      } catch (reason) {
        setOperation({
          busy: false,
          message: null,
          failure: classifyScriptReviewFailure(reason),
        });
        return null;
      }
    };

    const approve = (): void => {
      if (!model.canApprove) return;
      const action = `approve:${props.review.script_version_id}`;
      const idempotencyKey = keyFor(action);
      if (idempotencyKey === null) return;
      const controller = begin();
      void api.approve(
        props.review.script_version_id,
        {
          request_id: props.requestId,
          expected_request_version: props.requestVersion,
          expected_version_number: props.review.version_number,
          expected_immutable_hash: props.review.immutable_hash,
          source_revision_id: props.review.revision_id,
          confirmed: true,
        },
        versionScope(props.review),
        idempotencyKey,
        controller.signal,
      ).then((resource) => {
        if (!finish(controller)) return;
        if (
          !sameFrozenSource(resource, props.review)
          || resource.script_version_id !== props.review.script_version_id
          || resource.immutable_hash !== props.review.immutable_hash
          || resource.version_number !== props.review.version_number
          || resource.state !== "approved"
          || resource.blocker_count !== 0
          || resource.approval?.kind !== "manual_after_review"
          || resource.approval.actor_type !== "owner"
          || resource.approval.request_id !== props.requestId
        ) {
          setOperation({ busy: false, message: null, failure: scopeMismatchFailure() });
          return;
        }
        actionKeys.current.delete(action);
        setOperation({ busy: false, message: "脚本已由作者确认并冻结。", failure: null });
        props.onReviewChanged?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    const reanalyze = (segment: ScriptReviewSegmentResource): void => {
      if (!model.canReanalyze) return;
      const action = `reanalyze:${props.review.script_version_id}:${segment.segment_id}`;
      const idempotencyKey = keyFor(action);
      if (idempotencyKey === null) return;
      const controller = begin();
      void api.reanalyzeSegments(
        props.review.script_version_id,
        {
          request_id: props.requestId,
          expected_request_version: props.requestVersion,
          expected_version_number: props.review.version_number,
          expected_immutable_hash: props.review.immutable_hash,
          segment_ids: [segment.segment_id],
        },
        versionScope(props.review),
        idempotencyKey,
        controller.signal,
      ).then((resource) => {
        if (!finish(controller)) return;
        if (
          !sameFrozenSource(resource, props.review)
          || resource.version_number <= props.review.version_number
          || resource.script_version_id === props.review.script_version_id
        ) {
          setOperation({ busy: false, message: null, failure: scopeMismatchFailure() });
          return;
        }
        actionKeys.current.delete(action);
        setOperation({ busy: false, message: "已生成新的复核版本。", failure: null });
        props.onReviewChanged?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    const useLatestSource = (): void => {
      if (operation.busy || props.onUseLatestSource === undefined) return;
      const controller = begin();
      void props.onUseLatestSource(props.review, controller.signal).then((resource) => {
        if (!finish(controller)) return;
        if (
          resource.script_id !== props.review.script_id
          || resource.novel_id !== props.review.novel_id
          || resource.document_id !== props.review.document_id
          || (
            resource.revision_id === props.review.revision_id
            && resource.source_content_hash === props.review.source_content_hash
          )
          || resource.version_number <= props.review.version_number
          || resource.script_version_id === props.review.script_version_id
        ) {
          setOperation({ busy: false, message: null, failure: scopeMismatchFailure() });
          return;
        }
        setOperation({ busy: false, message: "已载入最新正文的复核版本。", failure: null });
        props.onReviewChanged?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    const close = (): void => {
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
      restoreFocus();
      props.onClose?.();
    };

    const issueBySegment = new Map<string, ScriptReviewIssueResource[]>();
    for (const issue of model.visibleIssues) {
      if (issue.segment_id === null) continue;
      const current = issueBySegment.get(issue.segment_id) ?? [];
      current.push(issue);
      issueBySegment.set(issue.segment_id, current);
    }
    const globalIssues = model.visibleIssues.filter((issue) => issue.segment_id === null);

    const operationNode = operation.failure !== null
      ? h(
        "div",
        { className: "anw-script-review__error", role: "alert" },
        h("p", null, operation.failure.message),
        operation.failure.refreshRequired
          && props.onUseLatestSource !== undefined
          ? h("button", {
            type: "button",
            disabled: operation.busy,
            onClick: useLatestSource,
          }, "重新分析最新正文")
          : null,
      )
      : null;

    let firstFocusableAssigned = false;
    return h(
      "section",
      {
        className: "anw-script-review",
        role: "dialog",
        "aria-modal": "false",
        "aria-labelledby": "anw-script-review-title",
        "aria-describedby": "anw-script-review-summary",
        "aria-busy": operation.busy || undefined,
        "data-min-viewport": "1920x1080",
      },
      h(
        "header",
        { className: "anw-script-review__header" },
        h(
          "div",
          null,
          h("p", { className: "anw-script-review__eyebrow" }, `脚本版本 ${props.review.version_number}`),
          h("h2", { id: "anw-script-review-title", tabIndex: -1, ref: titleRef }, "多角色朗读脚本复核"),
          h("p", { id: "anw-script-review-summary" }, model.summary),
        ),
        h("button", { type: "button", onClick: close, "aria-label": "关闭脚本复核" }, "关闭"),
      ),
      props.compactPlayer === undefined
        ? null
        : renderCompactPlayer(h, props.compactPlayer),
      h(
        "div",
        { className: "anw-script-review__snapshot" },
        h("span", null, `来源 revision ${props.review.revision_id.slice(0, 8)}…`),
        h("span", null, `内容哈希 ${props.review.source_content_hash.slice(0, 12)}…`),
        props.review.source_status === "current"
          ? h("strong", null, "当前正文快照")
          : h("strong", null, props.review.source_status === "working_copy_diverged" ? "正文已继续修改" : "设置或脚本已更新"),
      ),
      props.review.source_status !== "working_copy_diverged"
        ? null
        : h(
          "div",
          { className: "anw-script-review__snapshot-choice", role: "note" },
          h(
            "p",
            null,
            props.onUseLatestSource === undefined
              ? "这份复核绑定旧正文快照。可继续复核该快照；最新正文重新分析入口尚未接线。"
              : "这份复核绑定旧正文快照。请选择继续复核该快照，或重新分析最新正文。",
          ),
          new Set(props.review.allowed_actions).has("continue_snapshot")
            ? h("button", {
              type: "button",
              disabled: operation.busy,
              onClick: () => {
                setSnapshotConfirmed(true);
                setOperation({ busy: false, message: "已选择继续复核该正文快照。", failure: null });
              },
            }, snapshotConfirmed ? "已选择复核此快照" : "选择继续复核此快照")
            : null,
          new Set(props.review.allowed_actions).has("reanalyze_latest")
            && props.onUseLatestSource !== undefined
            ? h("button", {
              type: "button",
              disabled: operation.busy,
              onClick: useLatestSource,
            }, "重新分析最新正文")
            : null,
        ),
      props.review.blocker_count === 0 || props.review.warning_count === 0
        ? null
        : h(
          "nav",
          { className: "anw-script-review__filters", "aria-label": "复核问题筛选" },
          h("button", {
            type: "button",
            "aria-pressed": !showAllIssues,
            onClick: () => setShowAllIssues(false),
          }, `仅看阻塞 (${props.review.blocker_count})`),
          h("button", {
            type: "button",
            "aria-pressed": showAllIssues,
            onClick: () => setShowAllIssues(true),
          }, `全部问题 (${props.review.blocker_count + props.review.warning_count})`),
        ),
      operationNode,
      globalIssues.length === 0
        ? null
        : h(
          "ul",
          { className: "anw-script-review__global-issues", "aria-label": "整章问题" },
          ...globalIssues.map((issue) => h(
            "li",
            { key: `${issue.code}:${issue.evidence_digest ?? ""}`, "data-severity": issue.severity },
            h("strong", null, issue.severity === "blocker" ? "阻塞" : "提醒"),
            h("span", null, scriptReviewIssueLabel(issue.code)),
          )),
        ),
      h(
        "div",
        { className: "anw-script-review__workspace" },
        h(
          "ol",
          { className: "anw-script-review__segments", "aria-label": "待复核句段" },
          ...model.visibleSegments.map((segment) => {
            const issues = issueBySegment.get(segment.segment_id) ?? [];
            const blocker = hasBlocker(segment, props.review.issues);
            const firstBlocker = blocker && !firstFocusableAssigned;
            if (firstBlocker) firstFocusableAssigned = true;
            return h(
              "li",
              {
                key: segment.segment_id,
                className: "anw-script-review__segment",
                tabIndex: blocker ? -1 : undefined,
                ref: firstBlocker ? firstBlockerRef : undefined,
                "data-severity": blocker ? "blocker" : issues.length > 0 ? "warning" : "clear",
              },
              h("div", null,
                h("span", null, `句段 ${segment.ordinal + 1}`),
                h("strong", null, segment.speaker_label),
                h("span", null, `置信度 ${segment.confidence}`),
              ),
              h("p", { className: "anw-script-review__source-text" }, segment.source_text || "（结构停顿）"),
              segment.spoken_text === segment.source_text
                ? null
                : h("p", { className: "anw-script-review__spoken-text" }, `实际朗读：${segment.spoken_text || "（不发声）"}`),
              issues.length === 0
                ? h("p", null, "未发现需要处理的问题")
                : h("ul", null, ...issues.map((issue) => h(
                  "li",
                  { key: `${issue.code}:${issue.evidence_digest ?? ""}` },
                  h("strong", null, issue.severity === "blocker" ? "阻塞：" : "提醒："),
                  scriptReviewIssueLabel(issue.code),
                  issue.evidence_summary ? `；${issue.evidence_summary}` : "",
                ))),
              !model.showEdit && !model.showReanalyze
                ? null
                : h(
                  "div",
                  { className: "anw-script-review__segment-actions" },
                  !model.showEdit || props.onEditSegment === undefined
                    ? null
                    : h("button", {
                      type: "button",
                      disabled: !model.canEdit || !segment.editable,
                      onClick: () => props.onEditSegment?.(segment),
                    }, "修正说话人或朗读文本"),
                  !model.showReanalyze
                    ? null
                    : h("button", {
                      type: "button",
                      disabled: !model.canReanalyze,
                      onClick: () => reanalyze(segment),
                    }, "重新分析此句"),
                ),
            );
          }),
        ),
        h(
          "aside",
          { className: "anw-script-review__guide", "aria-label": "复核说明" },
          h("h3", null, "处理原则"),
          h("p", null, "修正说话人、匿名身份或朗读文本会创建新的脚本版本，不覆盖历史版本。"),
          h("p", null, "提醒不阻塞脚本冻结；所有阻塞必须在新版本中清零。"),
          h("p", null, "冻结脚本是 T3 产物，不代表音频已经生成。"),
        ),
      ),
      h(
        "footer",
        { className: "anw-script-review__footer" },
        h("span", { role: "status", "aria-live": "polite" }, operation.message ?? model.summary),
        h("button", {
          type: "button",
          disabled: !model.canApprove,
          onClick: approve,
        }, model.primaryLabel),
      ),
    );
  };
}
