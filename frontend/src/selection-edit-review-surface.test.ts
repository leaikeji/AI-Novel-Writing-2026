import { describe, expect, it, vi } from "vitest";

import {
  createSelectionEditReviewSession,
  transitionSelectionEditReview,
  type SelectionEditResultV2,
  type SelectionEditReviewIdentity,
  type SelectionEditReviewSessionState,
} from "./selection-edit-review";
import {
  createSelectionEditReviewSurface,
  selectionEditReviewEventForSurfaceAction,
  type SelectionEditReviewSurfaceProps,
  type SelectionEditReviewSurfaceReactRuntime,
} from "./selection-edit-review-surface";


interface FakeElement {
  type: unknown;
  props: Record<string, unknown>;
  children: unknown[];
}


function isFakeElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function createReactHarness() {
  const refs: Array<{ current: unknown }> = [];
  let refIndex = 0;
  let effects: Array<() => void | (() => void)> = [];
  const React: SelectionEditReviewSurfaceReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return {
        type,
        props: (props ?? {}) as Record<string, unknown>,
        children,
      };
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect): void {
      effects.push(effect);
    },
  };
  return {
    React,
    render(
      Component: (props: SelectionEditReviewSurfaceProps) => unknown,
      props: SelectionEditReviewSurfaceProps,
    ): FakeElement | null {
      refIndex = 0;
      effects = [];
      return Component(props) as FakeElement | null;
    },
    flushEffects() {
      for (const effect of effects) effect();
      effects = [];
    },
  };
}


function findAll(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isFakeElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(root, (element) => (
    element.type === "button" && textContent(element) === label
  ))[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isFakeElement(root)) return "";
  return root.children.map(textContent).join("");
}


function hasClass(element: FakeElement, className: string): boolean {
  return String(element.props.className ?? "").split(/\s+/).includes(className);
}


const SELECTION_ID = "123e4567-e89b-42d3-a456-426614174000";
const identity: SelectionEditReviewIdentity = {
  reviewSessionId: "review-session-1",
  selectionId: SELECTION_ID,
  operation: "rewrite",
  baseText: "潮声旧了。",
  target: {
    fieldId: "chapter.body",
    fieldLabel: "章节正文",
    mode: "multiline",
  },
};
const result: SelectionEditResultV2 = {
  schema_version: 2,
  selection_id: SELECTION_ID,
  operation: "rewrite",
  replacement_text: "潮声近了！",
  short_summary: "增强临近感",
  replacement_character_count: 5,
  warnings: ["保留原有视角"],
  diff_segments: [
    { segment_id: "context", kind: "equal", text: "潮声" },
    { segment_id: "word", kind: "replace", original_text: "旧", replacement_text: "近" },
    { segment_id: "tail", kind: "equal", text: "了" },
    { segment_id: "punctuation", kind: "replace", original_text: "。", replacement_text: "！" },
  ],
};


function successState(
  state: SelectionEditReviewSessionState,
  event: Parameters<typeof transitionSelectionEditReview>[1],
): SelectionEditReviewSessionState {
  const transition = transitionSelectionEditReview(state, event);
  expect(transition.ok).toBe(true);
  return transition.state;
}


function reviewState(
  selectedIdentity = identity,
  selectedResult: unknown = result,
): SelectionEditReviewSessionState {
  let state = successState(createSelectionEditReviewSession(), {
    type: "prepare",
    identity: selectedIdentity,
  });
  state = successState(state, { type: "generation-started", jobId: "job-1" });
  return successState(state, { type: "generation-ready", result: selectedResult });
}


function renderSurface(
  state: SelectionEditReviewSessionState,
  options: {
    onAction?: SelectionEditReviewSurfaceProps["onAction"];
    onReturnFocus?: SelectionEditReviewSurfaceProps["onReturnFocus"];
    onFocusTarget?: SelectionEditReviewSurfaceProps["onFocusTarget"];
  } = {},
) {
  const harness = createReactHarness();
  const Surface = createSelectionEditReviewSurface(harness.React);
  const onAction = options.onAction ?? vi.fn();
  const tree = harness.render(Surface, {
    state,
    onAction,
    onReturnFocus: options.onReturnFocus,
    onFocusTarget: options.onFocusTarget,
  });
  return { harness, Surface, tree, onAction };
}


describe("SelectionEditReviewSurface reviewing state", () => {
  it("maps pure surface actions to coordinator events without inventing API work", () => {
    expect(selectionEditReviewEventForSurfaceAction({
      type: "decide",
      segmentId: "word",
      decision: "accept",
    })).toEqual({
      type: "set-decision",
      segmentId: "word",
      decision: "accept",
    });
    expect(selectionEditReviewEventForSurfaceAction({ type: "next-change" }))
      .toEqual({ type: "navigate", direction: "next" });
    expect(selectionEditReviewEventForSurfaceAction({ type: "dismiss-applied" }))
      .toEqual({ type: "reset" });
    expect(selectionEditReviewEventForSurfaceAction({ type: "send-to-assistant" }))
      .toBeNull();
  });

  it("renders one accessible unified diff without a nested editor", () => {
    const { tree } = renderSurface(reviewState());

    expect(tree?.props.role).toBe("region");
    expect(tree?.props["aria-busy"]).toBe(false);
    expect(findAll(tree, (element) => element.props.role === "toolbar")).toHaveLength(1);
    expect(findAll(tree, (element) => element.props["aria-label"] === "统一差异审阅"))
      .toHaveLength(1);
    expect(findAll(tree, (element) => element.type === "textarea")).toHaveLength(0);
    expect(textContent(tree)).toContain("−删除旧");
    expect(textContent(tree)).toContain("+新增近");
    expect(textContent(tree)).toContain("保留原有视角");
    expect(findAll(tree, (element) => element.props["aria-current"] === "step"))
      .toHaveLength(1);
    expect(findAll(tree, (element) => element.props["aria-live"] === "polite"))
      .toHaveLength(1);
  });

  it("attaches the retrieval status to an applicable selection review", () => {
    const harness = createReactHarness();
    const Surface = createSelectionEditReviewSurface(harness.React);
    const tree = harness.render(Surface, {
      state: reviewState(),
      onAction: vi.fn(),
      retrievalNovelId: "novel-1",
      retrievalSummary: {
        schema_version: "retrieval-summary/1",
        outcome: "no_hit",
        mode: "context_only",
        reason_code: "no_hit",
        hit_count: 0,
        index_state: "ready",
      },
    });
    const status = findAll(tree, (element) => (
      typeof element.type === "function"
      && (element.props as Record<string, unknown>).novelId === "novel-1"
    ));
    expect(status).toHaveLength(1);
    expect(status[0].props).toMatchObject({
      summary: { mode: "context_only", outcome: "no_hit" },
    });
  });

  it.each([
    ["polish", "AI 润色审阅"],
    ["rewrite", "AI 改写审阅"],
    ["expand", "AI 扩写审阅"],
    ["shorten", "AI 缩写审阅"],
    ["dialogue", "AI 增强对白审阅"],
    ["review", "AI 问题检查审阅"],
    ["custom", "AI 自定义修改审阅"],
  ] as const)("renders the %s operation and change count directly in the toolbar", (
    operation,
    expectedLabel,
  ) => {
    const selectedIdentity = { ...identity, operation };
    const selectedResult = { ...result, operation };
    const { tree } = renderSurface(reviewState(selectedIdentity, selectedResult));
    const toolbar = findAll(tree, (element) => element.props.role === "toolbar")[0];
    const summary = findAll(toolbar, (element) => (
      hasClass(element, "anw-selection-edit-review-toolbar-summary")
    ));

    expect(summary).toHaveLength(1);
    expect(textContent(summary[0])).toContain(expectedLabel);
    expect(textContent(summary[0])).toContain("2 处修改");
    expect(findAll(toolbar, (element) => element.props.id === "anw-selection-edit-review-heading"))
      .toHaveLength(1);
    expect(textContent(tree)).not.toContain("审阅 章节正文 修改");
  });

  it("keeps each change's lines and decisions in one continuous inline group", () => {
    const { tree } = renderSurface(reviewState());
    const changes = findAll(tree, (element) => (
      hasClass(element, "anw-selection-edit-review-change")
    ));

    expect(changes).toHaveLength(2);
    for (const change of changes) {
      const directElements = change.children.filter(isFakeElement);
      expect(directElements).toHaveLength(2);
      expect(hasClass(directElements[0], "anw-selection-edit-review-change-lines")).toBe(true);
      expect(hasClass(directElements[1], "anw-selection-edit-review-inline-actions")).toBe(true);
      expect(directElements[1].props.role).toBe("group");
      expect(findAll(directElements[0], (element) => (
        hasClass(element, "anw-selection-edit-review-line")
      ))).toHaveLength(2);
    }
    expect(findAll(tree, (element) => (
      hasClass(element, "anw-selection-edit-review-change-actions")
    ))).toHaveLength(0);
  });

  it("renders an explicit final-result line for a pure deletion", () => {
    const deleteResult: SelectionEditResultV2 = {
      ...result,
      replacement_text: "潮声了。",
      short_summary: "删除重复修饰",
      replacement_character_count: 4,
      warnings: [],
      diff_segments: [
        { segment_id: "before-delete", kind: "equal", text: "潮声" },
        { segment_id: "delete-only", kind: "delete", original_text: "旧" },
        { segment_id: "after-delete", kind: "equal", text: "了。" },
      ],
    };
    const { tree } = renderSurface(reviewState(identity, deleteResult));
    const emptyResult = findAll(tree, (element) => (
      element.props["data-diff-kind"] === "result-empty"
    ));

    expect(emptyResult).toHaveLength(1);
    expect(emptyResult[0].props.role).toBe("note");
    expect(emptyResult[0].props["aria-label"]).toBe("应用后结果为空，删除此段文字");
    expect(hasClass(emptyResult[0], "anw-selection-edit-review-result")).toBe(true);
    expect(textContent(emptyResult[0])).toBe("=应用后结果为空（删除此段，不保留文字）");
    expect(textContent(tree)).toContain("−删除旧");
  });

  it("emits per-change, navigation, accept-all, reject-all and exit actions", () => {
    const onAction = vi.fn();
    const { tree } = renderSurface(reviewState(), { onAction });

    (findButton(tree, "接受").props.onClick as () => void)();
    (findButton(tree, "下一处").props.onClick as () => void)();
    (findButton(tree, "接受全部").props.onClick as () => void)();
    (findButton(tree, "拒绝全部").props.onClick as () => void)();
    (findButton(tree, "退出审阅").props.onClick as () => void)();

    expect(onAction.mock.calls.map(([action]) => action)).toEqual([
      { type: "decide", segmentId: "word", decision: "accept" },
      { type: "next-change" },
      { type: "accept-all" },
      { type: "reject-all" },
      { type: "exit" },
    ]);
  });

  it("changes the primary action after a decision and blocks unresolved application", () => {
    let state = reviewState();
    state = successState(state, {
      type: "set-decision",
      segmentId: "word",
      decision: "accept",
    });
    const { tree } = renderSurface(state);
    const primary = findButton(tree, "应用已接受修改（1处）");

    expect(primary.props.disabled).toBe(true);
    expect(textContent(tree)).toContain("已处理 1/2");
  });

  it("supports keyboard navigation and decisions while ignoring IME composition", () => {
    const onAction = vi.fn();
    const { tree } = renderSurface(reviewState(), { onAction });
    if (!tree) throw new Error("review surface did not render");
    const keyDown = tree.props.onKeyDown as (event: Record<string, unknown>) => void;
    const preventDefault = vi.fn();

    keyDown({ key: "ArrowDown", altKey: true, preventDefault });
    keyDown({ key: "a", altKey: true, preventDefault });
    (tree.props.onCompositionStart as () => void)();
    keyDown({ key: "r", altKey: true, preventDefault });
    (tree.props.onCompositionEnd as () => void)();
    keyDown({ key: "Escape", preventDefault });

    expect(onAction.mock.calls.map(([action]) => action)).toEqual([
      { type: "next-change" },
      { type: "decide", segmentId: "word", decision: "accept" },
      { type: "exit" },
    ]);
    expect(preventDefault).toHaveBeenCalledTimes(3);
  });

  it("focuses the requested change and reports the semantic focus target", () => {
    const onFocusTarget = vi.fn();
    const { tree, harness } = renderSurface(reviewState(), { onFocusTarget });
    const current = findAll(tree, (element) => element.props["aria-current"] === "step")[0];
    const focus = vi.fn();
    (current.props.ref as (element: { focus: typeof focus }) => void)({ focus });

    harness.flushEffects();

    expect(focus).toHaveBeenCalledOnce();
    expect(onFocusTarget).toHaveBeenCalledWith({ kind: "change", segmentId: "word" });
  });
});


describe("SelectionEditReviewSurface non-review states", () => {
  it("keeps the original visible and offers stop-waiting during generation", () => {
    let state = successState(createSelectionEditReviewSession(), { type: "prepare", identity });
    state = successState(state, { type: "generation-started", jobId: "job-1" });
    const onAction = vi.fn();
    const { tree } = renderSurface(state, { onAction });

    expect(tree?.props["aria-busy"]).toBe(true);
    expect(textContent(tree)).toContain(identity.baseText);
    (findButton(tree, "停止等待").props.onClick as () => void)();
    expect(onAction).toHaveBeenCalledWith({ type: "cancel-waiting" });
  });

  it("renders retry, assistant compatibility and exit actions after failure", () => {
    let state = successState(createSelectionEditReviewSession(), { type: "prepare", identity });
    state = successState(state, {
      type: "generation-failed",
      message: "网络不可用",
      retryable: true,
    });
    const onAction = vi.fn();
    const { tree } = renderSurface(state, { onAction });

    expect(textContent(tree)).toContain("网络不可用");
    (findButton(tree, "重试").props.onClick as () => void)();
    (findButton(tree, "发送到助手").props.onClick as () => void)();
    (findButton(tree, "退出").props.onClick as () => void)();
    expect(onAction.mock.calls.map(([action]) => action)).toEqual([
      { type: "retry" },
      { type: "send-to-assistant" },
      { type: "exit" },
    ]);
  });

  it("keeps a conflict diff read-only and exposes copy/regenerate/discard", () => {
    let state = reviewState();
    state = successState(state, { type: "conflict", message: "作者已修改正文" });
    const onAction = vi.fn();
    const { tree } = renderSurface(state, { onAction });

    expect(textContent(tree)).toContain("作者已修改正文");
    expect(findAll(tree, (element) => element.props["aria-label"] === "统一差异审阅"))
      .toHaveLength(1);
    expect(findAll(tree, (element) => element.props.role === "group"
      && String(element.props["aria-label"] ?? "").includes("修改决定"))).toHaveLength(0);
    (findButton(tree, "复制候选").props.onClick as () => void)();
    (findButton(tree, "基于新稿重新生成").props.onClick as () => void)();
    (findButton(tree, "放弃").props.onClick as () => void)();
    expect(onAction.mock.calls.map(([action]) => action)).toEqual([
      { type: "copy-candidate", candidateText: result.replacement_text },
      { type: "retry" },
      { type: "exit" },
    ]);
  });

  it("renders no-difference state with no apply action", () => {
    const sameIdentity = { ...identity, baseText: "潮声" };
    const sameResult: SelectionEditResultV2 = {
      ...result,
      replacement_text: "潮声",
      replacement_character_count: 2,
      diff_segments: [{ segment_id: "same", kind: "equal", text: "潮声" }],
    };
    const { tree } = renderSurface(reviewState(sameIdentity, sameResult));

    expect(textContent(tree)).toContain("未发现需要修改的差异");
    expect(findButton(tree, "接受全部").props.disabled).toBe(true);
    expect(findAll(tree, (element) => element.props["aria-label"] === "统一差异审阅"))
      .toHaveLength(0);
  });

  it("returns focus to the source field after apply and exposes one undo action", () => {
    let state = reviewState();
    const applying = transitionSelectionEditReview(state, { type: "accept-all" });
    if (!applying.ok) throw new Error(applying.message);
    state = successState(applying.state, { type: "apply-succeeded" });
    const onReturnFocus = vi.fn();
    const onAction = vi.fn();
    const { tree, harness } = renderSurface(state, { onReturnFocus, onAction });

    harness.flushEffects();
    expect(onReturnFocus).toHaveBeenCalledWith({
      kind: "source-field",
      fieldId: "chapter.body",
    });
    (findButton(tree, "撤销 AI 修改").props.onClick as () => void)();
    (findButton(tree, "继续编辑").props.onClick as () => void)();
    expect(onAction.mock.calls.map(([action]) => action)).toEqual([
      { type: "undo" },
      { type: "dismiss-applied" },
    ]);
  });

  it("returns no review UI after discard but still returns source focus", () => {
    const state = successState(reviewState(), { type: "reject-all" });
    const onReturnFocus = vi.fn();
    const { tree, harness } = renderSurface(state, { onReturnFocus });

    expect(tree).toBeNull();
    harness.flushEffects();
    expect(onReturnFocus).toHaveBeenCalledWith({
      kind: "source-field",
      fieldId: "chapter.body",
    });
  });
});
