export const SELECTION_EDIT_REVIEW_PHASES = [
  "idle",
  "preparing",
  "generating",
  "reviewing",
  "applying",
  "conflict",
  "failed",
  "applied",
  "discarded",
] as const;


export type SelectionEditReviewPhase = typeof SELECTION_EDIT_REVIEW_PHASES[number];


export const SELECTION_EDIT_OPERATIONS = [
  "polish",
  "rewrite",
  "expand",
  "shorten",
  "dialogue",
  "review",
  "custom",
] as const;


export type SelectionEditOperation = typeof SELECTION_EDIT_OPERATIONS[number];
export type SelectionEditReviewDecision = "accept" | "reject";
export type SelectionEditReviewFieldMode = "single-line" | "multiline";


export interface SelectionEditEqualSegment {
  readonly segment_id: string;
  readonly kind: "equal";
  readonly text: string;
}


export interface SelectionEditInsertSegment {
  readonly segment_id: string;
  readonly kind: "insert";
  readonly replacement_text: string;
}


export interface SelectionEditDeleteSegment {
  readonly segment_id: string;
  readonly kind: "delete";
  readonly original_text: string;
}


export interface SelectionEditReplaceSegment {
  readonly segment_id: string;
  readonly kind: "replace";
  readonly original_text: string;
  readonly replacement_text: string;
}


export type SelectionEditDiffSegment =
  | SelectionEditEqualSegment
  | SelectionEditInsertSegment
  | SelectionEditDeleteSegment
  | SelectionEditReplaceSegment;


export interface SelectionEditResultV2 {
  readonly schema_version: 2;
  readonly selection_id: string;
  readonly operation: SelectionEditOperation;
  readonly replacement_text: string;
  readonly short_summary: string;
  readonly replacement_character_count: number;
  readonly warnings: readonly string[];
  readonly diff_segments: readonly SelectionEditDiffSegment[];
}


export interface SelectionEditReconstruction {
  readonly baseText: string;
  readonly candidateText: string;
  readonly changeSegmentIds: readonly string[];
}


export type SelectionEditResultValidationReason =
  | "invalid-result"
  | "selection-mismatch"
  | "operation-mismatch"
  | "duplicate-segment-id"
  | "invalid-segment"
  | "base-rebuild-mismatch"
  | "candidate-rebuild-mismatch"
  | "character-count-mismatch";


export type SelectionEditResultValidation =
  | {
    readonly ok: true;
    readonly result: SelectionEditResultV2;
    readonly reconstruction: SelectionEditReconstruction;
  }
  | {
    readonly ok: false;
    readonly reason: SelectionEditResultValidationReason;
    readonly message: string;
  };


export interface SelectionEditReviewFieldTarget {
  readonly fieldId: string;
  readonly fieldLabel: string;
  readonly mode: SelectionEditReviewFieldMode;
}


/**
 * Identity owned by the current tab. Scope/CAS metadata stays in the page
 * coordinator and is intentionally not guessed by this API-independent core.
 */
export interface SelectionEditReviewIdentity {
  readonly reviewSessionId: string;
  readonly selectionId: string;
  readonly operation: SelectionEditOperation;
  readonly baseText: string;
  readonly target: SelectionEditReviewFieldTarget;
}


export type SelectionEditReviewFocusTarget =
  | { readonly kind: "review-heading" }
  | { readonly kind: "change"; readonly segmentId: string }
  | { readonly kind: "source-field"; readonly fieldId: string };


export type SelectionEditReviewFocusReason =
  | "session-entered"
  | "review-opened"
  | "navigation"
  | "decision-recorded"
  | "status-changed"
  | "source-return";


export interface SelectionEditReviewFocusRequest {
  readonly sequence: number;
  readonly target: SelectionEditReviewFocusTarget;
  readonly reason: SelectionEditReviewFocusReason;
}


export interface SelectionEditReviewDraft {
  readonly result: SelectionEditResultV2;
  readonly reconstruction: SelectionEditReconstruction;
  readonly decisions: Readonly<Record<string, SelectionEditReviewDecision>>;
}


interface SelectionEditReviewActiveBase {
  readonly identity: SelectionEditReviewIdentity;
  readonly focusRequest: SelectionEditReviewFocusRequest;
  readonly liveMessage: string;
}


export interface SelectionEditReviewIdleState {
  readonly phase: "idle";
  readonly focusRequest: null;
  readonly liveMessage: "";
}


export interface SelectionEditReviewPreparingState extends SelectionEditReviewActiveBase {
  readonly phase: "preparing";
}


export interface SelectionEditReviewGeneratingState extends SelectionEditReviewActiveBase {
  readonly phase: "generating";
  readonly jobId?: string;
}


export interface SelectionEditReviewReviewingState extends SelectionEditReviewActiveBase {
  readonly phase: "reviewing";
  readonly draft: SelectionEditReviewDraft;
  readonly activeChangeIndex: number;
  readonly validationMessage?: string;
}


export interface SelectionEditApplicationRequest {
  readonly reviewSessionId: string;
  readonly selectionId: string;
  readonly fieldId: string;
  readonly baseText: string;
  readonly replacementText: string;
  readonly acceptedSegmentIds: readonly string[];
  readonly rejectedSegmentIds: readonly string[];
}


export interface SelectionEditReviewApplyingState extends SelectionEditReviewActiveBase {
  readonly phase: "applying";
  readonly draft: SelectionEditReviewDraft;
  readonly activeChangeIndex: number;
  readonly application: SelectionEditApplicationRequest;
}


interface SelectionEditReviewTerminalErrorBase extends SelectionEditReviewActiveBase {
  readonly message: string;
  readonly draft?: SelectionEditReviewDraft;
  readonly activeChangeIndex?: number;
}


export interface SelectionEditReviewConflictState extends SelectionEditReviewTerminalErrorBase {
  readonly phase: "conflict";
}


export interface SelectionEditReviewFailedState extends SelectionEditReviewTerminalErrorBase {
  readonly phase: "failed";
  readonly retryable: boolean;
}


export interface SelectionEditReviewAppliedState extends SelectionEditReviewActiveBase {
  readonly phase: "applied";
  readonly message: string;
  readonly canUndo: boolean;
  readonly undoPending: boolean;
}


export interface SelectionEditReviewDiscardedState extends SelectionEditReviewActiveBase {
  readonly phase: "discarded";
  readonly message: string;
}


export type SelectionEditReviewSessionState =
  | SelectionEditReviewIdleState
  | SelectionEditReviewPreparingState
  | SelectionEditReviewGeneratingState
  | SelectionEditReviewReviewingState
  | SelectionEditReviewApplyingState
  | SelectionEditReviewConflictState
  | SelectionEditReviewFailedState
  | SelectionEditReviewAppliedState
  | SelectionEditReviewDiscardedState;


export type SelectionEditReviewEvent =
  | { readonly type: "prepare"; readonly identity: SelectionEditReviewIdentity }
  | { readonly type: "generation-started"; readonly jobId?: string }
  | { readonly type: "generation-ready"; readonly result: unknown }
  | { readonly type: "generation-failed"; readonly message: string; readonly retryable?: boolean }
  | { readonly type: "conflict"; readonly message: string }
  | { readonly type: "cancel" }
  | { readonly type: "retry" }
  | {
    readonly type: "set-decision";
    readonly segmentId: string;
    readonly decision: SelectionEditReviewDecision;
  }
  | { readonly type: "navigate"; readonly direction: "previous" | "next" }
  | { readonly type: "request-apply" }
  | { readonly type: "accept-all" }
  | { readonly type: "reject-all" }
  | { readonly type: "exit" }
  | { readonly type: "confirm-exit" }
  | { readonly type: "apply-succeeded"; readonly message?: string; readonly canUndo?: boolean }
  | { readonly type: "apply-failed"; readonly message: string }
  | { readonly type: "apply-conflict"; readonly message: string }
  | { readonly type: "request-undo" }
  | { readonly type: "undo-succeeded"; readonly message?: string }
  | { readonly type: "undo-failed"; readonly message: string }
  | { readonly type: "reset" };


export type SelectionEditReviewEffect =
  | { readonly type: "apply"; readonly request: SelectionEditApplicationRequest }
  | {
    readonly type: "undo";
    readonly reviewSessionId: string;
    readonly selectionId: string;
    readonly fieldId: string;
  };


export type SelectionEditReviewTransitionFailureReason =
  | "invalid-transition"
  | "invalid-session"
  | "unknown-segment"
  | "equal-segment"
  | "undecided-changes"
  | "no-accepted-changes"
  | "no-changes"
  | "exit-confirmation-required";


export type SelectionEditReviewTransitionResult =
  | {
    readonly ok: true;
    readonly state: SelectionEditReviewSessionState;
    readonly effect?: SelectionEditReviewEffect;
  }
  | {
    readonly ok: false;
    readonly state: SelectionEditReviewSessionState;
    readonly reason: SelectionEditReviewTransitionFailureReason;
    readonly message: string;
    readonly undecidedSegmentIds?: readonly string[];
  };


export interface SelectionEditReviewMetrics {
  readonly changeCount: number;
  readonly acceptedCount: number;
  readonly rejectedCount: number;
  readonly undecidedCount: number;
  readonly decidedCount: number;
}


export type SelectionEditReviewComposition =
  | {
    readonly ok: true;
    readonly replacementText: string;
    readonly acceptedSegmentIds: readonly string[];
    readonly rejectedSegmentIds: readonly string[];
  }
  | {
    readonly ok: false;
    readonly reason: "undecided-changes" | "no-accepted-changes" | "no-changes";
    readonly undecidedSegmentIds: readonly string[];
  };


export interface SelectionEditReviewCoordinator {
  getState(): SelectionEditReviewSessionState;
  subscribe(listener: (state: SelectionEditReviewSessionState) => void): () => void;
  dispatch(event: SelectionEditReviewEvent): SelectionEditReviewTransitionResult;
  dispose(): void;
}


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SELECTION_EDIT_RESULT_KEYS = [
  "schema_version",
  "selection_id",
  "operation",
  "replacement_text",
  "short_summary",
  "replacement_character_count",
  "warnings",
  "diff_segments",
] as const;
const SELECTION_EDIT_SEGMENT_KEYS = {
  equal: ["segment_id", "kind", "text"],
  delete: ["segment_id", "kind", "original_text"],
  insert: ["segment_id", "kind", "replacement_text"],
  replace: ["segment_id", "kind", "original_text", "replacement_text"],
} as const;
const SELECTION_EDIT_MAX_REPLACEMENT_CHARACTERS = 24_000;
const SELECTION_EDIT_MAX_SUMMARY_CHARACTERS = 240;
const SELECTION_EDIT_MAX_WARNING_CHARACTERS = 240;


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}


function hasExactKeys(
  value: Record<string, unknown>,
  expectedKeys: readonly string[],
): boolean {
  const actualKeys = Object.keys(value);
  return actualKeys.length === expectedKeys.length
    && expectedKeys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}


function isOperation(value: unknown): value is SelectionEditOperation {
  return typeof value === "string"
    && SELECTION_EDIT_OPERATIONS.includes(value as SelectionEditOperation);
}


function characterCount(value: string): number {
  return Array.from(value).length;
}


function freezeSegments(
  segments: readonly SelectionEditDiffSegment[],
): readonly SelectionEditDiffSegment[] {
  return Object.freeze(segments.map((segment) => Object.freeze({ ...segment })));
}


function parseSegment(value: unknown): SelectionEditDiffSegment | null {
  if (!isRecord(value)
    || typeof value.segment_id !== "string"
    || value.segment_id.length === 0
    || !(value.kind === "equal"
      || value.kind === "insert"
      || value.kind === "delete"
      || value.kind === "replace")
    || !hasExactKeys(value, SELECTION_EDIT_SEGMENT_KEYS[value.kind])) {
    return null;
  }
  switch (value.kind) {
    case "equal":
      return typeof value.text === "string"
        ? { segment_id: value.segment_id, kind: "equal", text: value.text }
        : null;
    case "insert":
      return typeof value.replacement_text === "string"
        ? {
          segment_id: value.segment_id,
          kind: "insert",
          replacement_text: value.replacement_text,
        }
        : null;
    case "delete":
      return typeof value.original_text === "string"
        ? {
          segment_id: value.segment_id,
          kind: "delete",
          original_text: value.original_text,
        }
        : null;
    case "replace":
      return typeof value.original_text === "string"
        && typeof value.replacement_text === "string"
        ? {
          segment_id: value.segment_id,
          kind: "replace",
          original_text: value.original_text,
          replacement_text: value.replacement_text,
        }
        : null;
    default:
      return null;
  }
}


export function rebuildSelectionEditTexts(
  segments: readonly SelectionEditDiffSegment[],
): SelectionEditReconstruction {
  let baseText = "";
  let candidateText = "";
  const changeSegmentIds: string[] = [];
  for (const segment of segments) {
    switch (segment.kind) {
      case "equal":
        baseText += segment.text;
        candidateText += segment.text;
        break;
      case "insert":
        candidateText += segment.replacement_text;
        changeSegmentIds.push(segment.segment_id);
        break;
      case "delete":
        baseText += segment.original_text;
        changeSegmentIds.push(segment.segment_id);
        break;
      case "replace":
        baseText += segment.original_text;
        candidateText += segment.replacement_text;
        changeSegmentIds.push(segment.segment_id);
        break;
    }
  }
  return Object.freeze({
    baseText,
    candidateText,
    changeSegmentIds: Object.freeze(changeSegmentIds),
  });
}


export function validateSelectionEditResultV2(
  value: unknown,
  expected: {
    readonly selectionId: string;
    readonly operation: SelectionEditOperation;
    readonly baseText: string;
  },
): SelectionEditResultValidation {
  if (!isRecord(value)
    || !hasExactKeys(value, SELECTION_EDIT_RESULT_KEYS)
    || value.schema_version !== 2
    || !UUID_PATTERN.test(String(value.selection_id ?? ""))
    || !isOperation(value.operation)
    || typeof value.replacement_text !== "string"
    || !value.replacement_text.trim()
    || characterCount(value.replacement_text) > SELECTION_EDIT_MAX_REPLACEMENT_CHARACTERS
    || typeof value.short_summary !== "string"
    || !value.short_summary.trim()
    || characterCount(value.short_summary) > SELECTION_EDIT_MAX_SUMMARY_CHARACTERS
    || !Number.isSafeInteger(value.replacement_character_count)
    || !Array.isArray(value.warnings)
    || !value.warnings.every((warning) => (
      typeof warning === "string"
      && characterCount(warning) <= SELECTION_EDIT_MAX_WARNING_CHARACTERS
    ))
    || !Array.isArray(value.diff_segments)
    || value.diff_segments.length === 0) {
    return {
      ok: false,
      reason: "invalid-result",
      message: "选区编辑结果不符合 V2 契约。",
    };
  }
  if (value.selection_id !== expected.selectionId) {
    return {
      ok: false,
      reason: "selection-mismatch",
      message: "候选不属于当前选区。",
    };
  }
  if (value.operation !== expected.operation) {
    return {
      ok: false,
      reason: "operation-mismatch",
      message: "候选操作与当前任务不一致。",
    };
  }
  const parsedSegments: SelectionEditDiffSegment[] = [];
  const ids = new Set<string>();
  for (const rawSegment of value.diff_segments) {
    const segment = parseSegment(rawSegment);
    if (!segment) {
      return {
        ok: false,
        reason: "invalid-segment",
        message: "差异结果包含无效片段。",
      };
    }
    if (ids.has(segment.segment_id)) {
      return {
        ok: false,
        reason: "duplicate-segment-id",
        message: "差异结果包含重复片段标识。",
      };
    }
    ids.add(segment.segment_id);
    parsedSegments.push(segment);
  }
  const frozenSegments = freezeSegments(parsedSegments);
  const reconstruction = rebuildSelectionEditTexts(frozenSegments);
  if (reconstruction.baseText !== expected.baseText) {
    return {
      ok: false,
      reason: "base-rebuild-mismatch",
      message: "差异结果无法严格重建原选区。",
    };
  }
  if (reconstruction.candidateText !== value.replacement_text) {
    return {
      ok: false,
      reason: "candidate-rebuild-mismatch",
      message: "差异结果无法严格重建候选文本。",
    };
  }
  if (value.replacement_character_count !== characterCount(value.replacement_text)) {
    return {
      ok: false,
      reason: "character-count-mismatch",
      message: "候选字符数与项目计算结果不一致。",
    };
  }
  const result: SelectionEditResultV2 = Object.freeze({
    schema_version: 2,
    selection_id: value.selection_id,
    operation: value.operation,
    replacement_text: value.replacement_text,
    short_summary: value.short_summary,
    replacement_character_count: value.replacement_character_count,
    warnings: Object.freeze([...value.warnings] as string[]),
    diff_segments: frozenSegments,
  });
  return { ok: true, result, reconstruction };
}


export function createSelectionEditReviewDraft(
  result: SelectionEditResultV2,
  reconstruction = rebuildSelectionEditTexts(result.diff_segments),
): SelectionEditReviewDraft {
  return Object.freeze({
    result,
    reconstruction,
    decisions: Object.freeze({}),
  });
}


export function selectionEditReviewMetrics(
  draft: SelectionEditReviewDraft,
): SelectionEditReviewMetrics {
  let acceptedCount = 0;
  let rejectedCount = 0;
  for (const segmentId of draft.reconstruction.changeSegmentIds) {
    if (draft.decisions[segmentId] === "accept") acceptedCount += 1;
    if (draft.decisions[segmentId] === "reject") rejectedCount += 1;
  }
  const changeCount = draft.reconstruction.changeSegmentIds.length;
  return Object.freeze({
    changeCount,
    acceptedCount,
    rejectedCount,
    undecidedCount: changeCount - acceptedCount - rejectedCount,
    decidedCount: acceptedCount + rejectedCount,
  });
}


function findSegment(
  draft: SelectionEditReviewDraft,
  segmentId: string,
): SelectionEditDiffSegment | undefined {
  return draft.result.diff_segments.find((segment) => segment.segment_id === segmentId);
}


export function setSelectionEditReviewDecision(
  draft: SelectionEditReviewDraft,
  segmentId: string,
  decision: SelectionEditReviewDecision,
): SelectionEditReviewDraft {
  const segment = findSegment(draft, segmentId);
  if (!segment) throw new Error(`unknown review segment: ${segmentId}`);
  if (segment.kind === "equal") throw new Error("equal review segments cannot be decided");
  return Object.freeze({
    ...draft,
    decisions: Object.freeze({ ...draft.decisions, [segmentId]: decision }),
  });
}


export function decideAllSelectionEditChanges(
  draft: SelectionEditReviewDraft,
  decision: SelectionEditReviewDecision,
): SelectionEditReviewDraft {
  const decisions: Record<string, SelectionEditReviewDecision> = {};
  for (const segmentId of draft.reconstruction.changeSegmentIds) {
    decisions[segmentId] = decision;
  }
  return Object.freeze({
    ...draft,
    decisions: Object.freeze(decisions),
  });
}


export function composeSelectionEditReview(
  draft: SelectionEditReviewDraft,
): SelectionEditReviewComposition {
  const metrics = selectionEditReviewMetrics(draft);
  if (metrics.changeCount === 0) {
    return { ok: false, reason: "no-changes", undecidedSegmentIds: [] };
  }
  const undecidedSegmentIds = draft.reconstruction.changeSegmentIds.filter(
    (segmentId) => draft.decisions[segmentId] === undefined,
  );
  if (undecidedSegmentIds.length > 0) {
    return {
      ok: false,
      reason: "undecided-changes",
      undecidedSegmentIds: Object.freeze(undecidedSegmentIds),
    };
  }
  if (metrics.acceptedCount === 0) {
    return { ok: false, reason: "no-accepted-changes", undecidedSegmentIds: [] };
  }
  let replacementText = "";
  const acceptedSegmentIds: string[] = [];
  const rejectedSegmentIds: string[] = [];
  for (const segment of draft.result.diff_segments) {
    if (segment.kind === "equal") {
      replacementText += segment.text;
      continue;
    }
    const decision = draft.decisions[segment.segment_id];
    if (decision === "accept") {
      acceptedSegmentIds.push(segment.segment_id);
      if (segment.kind === "insert" || segment.kind === "replace") {
        replacementText += segment.replacement_text;
      }
      continue;
    }
    rejectedSegmentIds.push(segment.segment_id);
    if (segment.kind === "delete" || segment.kind === "replace") {
      replacementText += segment.original_text;
    }
  }
  return Object.freeze({
    ok: true,
    replacementText,
    acceptedSegmentIds: Object.freeze(acceptedSegmentIds),
    rejectedSegmentIds: Object.freeze(rejectedSegmentIds),
  });
}


export function hasUnappliedAcceptedDecision(
  state: SelectionEditReviewSessionState,
): boolean {
  return state.phase === "reviewing"
    && selectionEditReviewMetrics(state.draft).acceptedCount > 0;
}


export function shouldConfirmSelectionEditReviewExit(
  state: SelectionEditReviewSessionState,
): boolean {
  return hasUnappliedAcceptedDecision(state);
}


function initialState(): SelectionEditReviewIdleState {
  return Object.freeze({ phase: "idle", focusRequest: null, liveMessage: "" });
}


function isValidReviewIdentity(identity: SelectionEditReviewIdentity): boolean {
  return Boolean(
    identity.reviewSessionId.trim()
    && UUID_PATTERN.test(identity.selectionId)
    && isOperation(identity.operation)
    && identity.baseText.length > 0
    && identity.target.fieldId.trim()
    && identity.target.fieldLabel.trim()
    && (identity.target.mode === "single-line" || identity.target.mode === "multiline"),
  );
}


export function createSelectionEditReviewSession(): SelectionEditReviewSessionState {
  return initialState();
}


function nextFocus(
  state: SelectionEditReviewSessionState,
  target: SelectionEditReviewFocusTarget,
  reason: SelectionEditReviewFocusReason,
): SelectionEditReviewFocusRequest {
  return Object.freeze({
    sequence: (state.focusRequest?.sequence ?? 0) + 1,
    target: Object.freeze({ ...target }),
    reason,
  });
}


function failure(
  state: SelectionEditReviewSessionState,
  reason: SelectionEditReviewTransitionFailureReason,
  message: string,
  undecidedSegmentIds?: readonly string[],
): SelectionEditReviewTransitionResult {
  return { ok: false, state, reason, message, undecidedSegmentIds };
}


function activeIdentity(
  state: SelectionEditReviewSessionState,
): SelectionEditReviewIdentity | null {
  return state.phase === "idle" ? null : state.identity;
}


function reviewData(
  state: SelectionEditReviewSessionState,
): { draft?: SelectionEditReviewDraft; activeChangeIndex?: number } {
  if (state.phase === "reviewing" || state.phase === "applying") {
    return { draft: state.draft, activeChangeIndex: state.activeChangeIndex };
  }
  if (state.phase === "conflict" || state.phase === "failed") {
    return { draft: state.draft, activeChangeIndex: state.activeChangeIndex };
  }
  return {};
}


function applicationRequest(
  identity: SelectionEditReviewIdentity,
  composition: Extract<SelectionEditReviewComposition, { ok: true }>,
): SelectionEditApplicationRequest {
  return Object.freeze({
    reviewSessionId: identity.reviewSessionId,
    selectionId: identity.selectionId,
    fieldId: identity.target.fieldId,
    baseText: identity.baseText,
    replacementText: composition.replacementText,
    acceptedSegmentIds: composition.acceptedSegmentIds,
    rejectedSegmentIds: composition.rejectedSegmentIds,
  });
}


function requestApplication(
  state: SelectionEditReviewReviewingState,
  draft: SelectionEditReviewDraft,
): SelectionEditReviewTransitionResult {
  const composition = composeSelectionEditReview(draft);
  if (!composition.ok) {
    const message = composition.reason === "undecided-changes"
      ? "仍有未决定的修改，全部接受或拒绝后才能应用。"
      : composition.reason === "no-accepted-changes"
        ? "没有已接受的修改；可以拒绝全部并退出审阅。"
        : "候选与原文没有差异，无需应用。";
    return failure(
      state,
      composition.reason,
      message,
      composition.undecidedSegmentIds,
    );
  }
  const application = applicationRequest(state.identity, composition);
  const next: SelectionEditReviewApplyingState = Object.freeze({
    phase: "applying",
    identity: state.identity,
    draft,
    activeChangeIndex: state.activeChangeIndex,
    application,
    focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
    liveMessage: "正在校验并应用已接受的修改。",
  });
  return { ok: true, state: next, effect: { type: "apply", request: application } };
}


export function transitionSelectionEditReview(
  state: SelectionEditReviewSessionState,
  event: SelectionEditReviewEvent,
): SelectionEditReviewTransitionResult {
  if (event.type === "reset") {
    return { ok: true, state: initialState() };
  }
  if (event.type === "prepare") {
    if (![
      "idle",
      "applied",
      "discarded",
    ].includes(state.phase)) {
      return failure(state, "invalid-transition", "当前审阅尚未结束，不能启动另一项任务。");
    }
    if (!isValidReviewIdentity(event.identity)) {
      return failure(state, "invalid-session", "选区审阅会话缺少有效的选区或字段身份。");
    }
    const next: SelectionEditReviewPreparingState = Object.freeze({
      phase: "preparing",
      identity: Object.freeze({
        ...event.identity,
        target: Object.freeze({ ...event.identity.target }),
      }),
      focusRequest: nextFocus(state, { kind: "review-heading" }, "session-entered"),
      liveMessage: "正在准备选区编辑任务。",
    });
    return { ok: true, state: next };
  }

  const identity = activeIdentity(state);
  if (!identity) {
    return failure(state, "invalid-transition", "当前没有活动的选区编辑任务。");
  }

  if (event.type === "generation-started"
    && (state.phase === "preparing" || state.phase === "generating")) {
    const next: SelectionEditReviewGeneratingState = Object.freeze({
      phase: "generating",
      identity,
      jobId: event.jobId,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: "AI 正在生成候选，原文尚未改变。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "generation-ready"
    && (state.phase === "preparing" || state.phase === "generating")) {
    const validation = validateSelectionEditResultV2(event.result, {
      selectionId: identity.selectionId,
      operation: identity.operation,
      baseText: identity.baseText,
    });
    if (!validation.ok) {
      const next: SelectionEditReviewFailedState = Object.freeze({
        phase: "failed",
        identity,
        message: validation.message,
        retryable: true,
        focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
        liveMessage: validation.message,
      });
      return { ok: true, state: next };
    }
    const draft = createSelectionEditReviewDraft(
      validation.result,
      validation.reconstruction,
    );
    const firstChange = draft.reconstruction.changeSegmentIds[0];
    const noDifferences = firstChange === undefined;
    const next: SelectionEditReviewReviewingState = Object.freeze({
      phase: "reviewing",
      identity,
      draft,
      activeChangeIndex: noDifferences ? -1 : 0,
      focusRequest: nextFocus(
        state,
        noDifferences
          ? { kind: "review-heading" }
          : { kind: "change", segmentId: firstChange },
        "review-opened",
      ),
      liveMessage: noDifferences
        ? "未发现需要修改的差异。"
        : `候选已生成，共 ${draft.reconstruction.changeSegmentIds.length} 处修改。`,
    });
    return { ok: true, state: next };
  }

  if (event.type === "generation-failed"
    && (state.phase === "preparing" || state.phase === "generating")) {
    const data = reviewData(state);
    const next: SelectionEditReviewFailedState = Object.freeze({
      phase: "failed",
      identity,
      message: event.message,
      retryable: event.retryable !== false,
      ...data,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: event.message,
    });
    return { ok: true, state: next };
  }

  if ((event.type === "conflict"
    && (state.phase === "preparing"
      || state.phase === "generating"
      || state.phase === "reviewing"
      || state.phase === "applying"))
    || (event.type === "apply-conflict" && state.phase === "applying")) {
    const data = reviewData(state);
    const next: SelectionEditReviewConflictState = Object.freeze({
      phase: "conflict",
      identity,
      message: event.message,
      ...data,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: event.message,
    });
    return { ok: true, state: next };
  }

  if (event.type === "cancel"
    && (state.phase === "preparing" || state.phase === "generating")) {
    const next: SelectionEditReviewDiscardedState = Object.freeze({
      phase: "discarded",
      identity,
      message: "已停止等待；原文没有改变。",
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: "已停止等待；原文没有改变。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "retry"
    && (state.phase === "failed" || state.phase === "conflict")) {
    const next: SelectionEditReviewPreparingState = Object.freeze({
      phase: "preparing",
      identity,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: "正在重新准备选区编辑任务。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "set-decision" && state.phase === "reviewing") {
    const segment = findSegment(state.draft, event.segmentId);
    if (!segment) return failure(state, "unknown-segment", "找不到这处修改。");
    if (segment.kind === "equal") {
      return failure(state, "equal-segment", "未改变的上下文不能接受或拒绝。");
    }
    const draft = setSelectionEditReviewDecision(
      state.draft,
      event.segmentId,
      event.decision,
    );
    const next: SelectionEditReviewReviewingState = Object.freeze({
      ...state,
      draft,
      validationMessage: undefined,
      focusRequest: nextFocus(
        state,
        { kind: "change", segmentId: event.segmentId },
        "decision-recorded",
      ),
      liveMessage: event.decision === "accept" ? "已接受当前修改。" : "已拒绝当前修改。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "navigate" && state.phase === "reviewing") {
    const lastIndex = state.draft.reconstruction.changeSegmentIds.length - 1;
    if (lastIndex < 0) return failure(state, "no-changes", "候选与原文没有差异。");
    const activeChangeIndex = event.direction === "next"
      ? Math.min(lastIndex, state.activeChangeIndex + 1)
      : Math.max(0, state.activeChangeIndex - 1);
    const segmentId = state.draft.reconstruction.changeSegmentIds[activeChangeIndex];
    const next: SelectionEditReviewReviewingState = Object.freeze({
      ...state,
      activeChangeIndex,
      validationMessage: undefined,
      focusRequest: nextFocus(
        state,
        { kind: "change", segmentId },
        "navigation",
      ),
      liveMessage: `当前为第 ${activeChangeIndex + 1} 处修改。`,
    });
    return { ok: true, state: next };
  }

  if (event.type === "accept-all" && state.phase === "reviewing") {
    const draft = decideAllSelectionEditChanges(state.draft, "accept");
    return requestApplication(state, draft);
  }

  if (event.type === "request-apply" && state.phase === "reviewing") {
    return requestApplication(state, state.draft);
  }

  if (event.type === "reject-all" && state.phase === "reviewing") {
    const next: SelectionEditReviewDiscardedState = Object.freeze({
      phase: "discarded",
      identity,
      message: "已拒绝全部修改；原文没有改变。",
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: "已拒绝全部修改；原文没有改变。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "exit" && state.phase === "reviewing") {
    if (shouldConfirmSelectionEditReviewExit(state)) {
      return failure(
        state,
        "exit-confirmation-required",
        "存在尚未应用的已接受修改，退出前需要确认。",
      );
    }
    const next: SelectionEditReviewDiscardedState = Object.freeze({
      phase: "discarded",
      identity,
      message: "已退出审阅；原文没有改变。",
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: "已退出审阅；原文没有改变。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "confirm-exit" && state.phase === "reviewing") {
    const next: SelectionEditReviewDiscardedState = Object.freeze({
      phase: "discarded",
      identity,
      message: "已放弃未应用的审阅决定；原文没有改变。",
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: "已放弃未应用的审阅决定；原文没有改变。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "exit"
    && (state.phase === "failed" || state.phase === "conflict")) {
    const next: SelectionEditReviewDiscardedState = Object.freeze({
      phase: "discarded",
      identity,
      message: "已退出选区编辑；原文没有改变。",
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: "已退出选区编辑；原文没有改变。",
    });
    return { ok: true, state: next };
  }

  if (event.type === "apply-succeeded" && state.phase === "applying") {
    const message = event.message ?? "AI 修改已应用。";
    const next: SelectionEditReviewAppliedState = Object.freeze({
      phase: "applied",
      identity,
      message,
      canUndo: event.canUndo !== false,
      undoPending: false,
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: message,
    });
    return { ok: true, state: next };
  }

  if (event.type === "apply-failed" && state.phase === "applying") {
    const next: SelectionEditReviewFailedState = Object.freeze({
      phase: "failed",
      identity,
      message: event.message,
      retryable: true,
      draft: state.draft,
      activeChangeIndex: state.activeChangeIndex,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: event.message,
    });
    return { ok: true, state: next };
  }

  if (event.type === "request-undo" && state.phase === "applied" && state.canUndo) {
    const next: SelectionEditReviewAppliedState = Object.freeze({
      ...state,
      undoPending: true,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: "正在撤销整次 AI 修改。",
    });
    return {
      ok: true,
      state: next,
      effect: {
        type: "undo",
        reviewSessionId: identity.reviewSessionId,
        selectionId: identity.selectionId,
        fieldId: identity.target.fieldId,
      },
    };
  }

  if (event.type === "undo-succeeded" && state.phase === "applied" && state.undoPending) {
    const message = event.message ?? "已撤销整次 AI 修改。";
    const next: SelectionEditReviewDiscardedState = Object.freeze({
      phase: "discarded",
      identity,
      message,
      focusRequest: nextFocus(
        state,
        { kind: "source-field", fieldId: identity.target.fieldId },
        "source-return",
      ),
      liveMessage: message,
    });
    return { ok: true, state: next };
  }

  if (event.type === "undo-failed" && state.phase === "applied" && state.undoPending) {
    const next: SelectionEditReviewAppliedState = Object.freeze({
      ...state,
      undoPending: false,
      message: event.message,
      focusRequest: nextFocus(state, { kind: "review-heading" }, "status-changed"),
      liveMessage: event.message,
    });
    return { ok: true, state: next };
  }

  return failure(state, "invalid-transition", `状态 ${state.phase} 不允许执行 ${event.type}。`);
}


export function createSelectionEditReviewCoordinator(): SelectionEditReviewCoordinator {
  let state: SelectionEditReviewSessionState = initialState();
  const listeners = new Set<(next: SelectionEditReviewSessionState) => void>();
  let disposed = false;
  return {
    getState: () => state,
    subscribe(listener) {
      if (disposed) throw new Error("selection edit review coordinator is disposed");
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    dispatch(event) {
      if (disposed) throw new Error("selection edit review coordinator is disposed");
      const result = transitionSelectionEditReview(state, event);
      if (result.ok && result.state !== state) {
        state = result.state;
        for (const listener of listeners) listener(state);
      }
      return result;
    },
    dispose() {
      disposed = true;
      listeners.clear();
      state = initialState();
    },
  };
}
