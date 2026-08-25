import { describe, expect, it, vi } from "vitest";

import {
  composeSelectionEditReview,
  createSelectionEditReviewCoordinator,
  createSelectionEditReviewDraft,
  createSelectionEditReviewSession,
  decideAllSelectionEditChanges,
  rebuildSelectionEditTexts,
  selectionEditReviewMetrics,
  setSelectionEditReviewDecision,
  shouldConfirmSelectionEditReviewExit,
  transitionSelectionEditReview,
  validateSelectionEditResultV2,
  type SelectionEditResultV2,
  type SelectionEditReviewIdentity,
  type SelectionEditReviewSessionState,
} from "./selection-edit-review";


const SELECTION_ID = "123e4567-e89b-42d3-a456-426614174000";
const identity: SelectionEditReviewIdentity = {
  reviewSessionId: "review-session-1",
  selectionId: SELECTION_ID,
  operation: "polish",
  baseText: "甲旧乙删丙",
  target: {
    fieldId: "chapter.body",
    fieldLabel: "章节正文",
    mode: "multiline",
  },
};


const result: SelectionEditResultV2 = {
  schema_version: 2,
  selection_id: SELECTION_ID,
  operation: "polish",
  replacement_text: "甲新乙丙增",
  short_summary: "调整表达并删除冗字",
  replacement_character_count: 5,
  warnings: ["请确认语气。"],
  diff_segments: [
    { segment_id: "s0", kind: "equal", text: "甲" },
    { segment_id: "s1", kind: "replace", original_text: "旧", replacement_text: "新" },
    { segment_id: "s2", kind: "equal", text: "乙" },
    { segment_id: "s3", kind: "delete", original_text: "删" },
    { segment_id: "s4", kind: "equal", text: "丙" },
    { segment_id: "s5", kind: "insert", replacement_text: "增" },
  ],
};


const noDifferenceResult: SelectionEditResultV2 = {
  schema_version: 2,
  selection_id: SELECTION_ID,
  operation: "polish",
  replacement_text: "潮声",
  short_summary: "未发现需要修改的差异",
  replacement_character_count: 2,
  warnings: [],
  diff_segments: [{ segment_id: "same", kind: "equal", text: "潮声" }],
};


function expectStatePhase(
  transition: ReturnType<typeof transitionSelectionEditReview>,
  phase: SelectionEditReviewSessionState["phase"],
): SelectionEditReviewSessionState {
  expect(transition.ok).toBe(true);
  expect(transition.state.phase).toBe(phase);
  return transition.state;
}


function openReview(
  selectedIdentity: SelectionEditReviewIdentity = identity,
  selectedResult: unknown = result,
): SelectionEditReviewSessionState {
  let state = expectStatePhase(
    transitionSelectionEditReview(createSelectionEditReviewSession(), {
      type: "prepare",
      identity: selectedIdentity,
    }),
    "preparing",
  );
  state = expectStatePhase(
    transitionSelectionEditReview(state, { type: "generation-started", jobId: "job-1" }),
    "generating",
  );
  return expectStatePhase(
    transitionSelectionEditReview(state, { type: "generation-ready", result: selectedResult }),
    "reviewing",
  );
}


describe("selection edit result V2", () => {
  it("strictly rebuilds the base and candidate across all segment kinds", () => {
    expect(rebuildSelectionEditTexts(result.diff_segments)).toEqual({
      baseText: "甲旧乙删丙",
      candidateText: "甲新乙丙增",
      changeSegmentIds: ["s1", "s3", "s5"],
    });
    expect(validateSelectionEditResultV2(result, {
      selectionId: SELECTION_ID,
      operation: "polish",
      baseText: "甲旧乙删丙",
    })).toMatchObject({ ok: true });
  });

  it.each([
    {
      label: "duplicate segment ids",
      value: {
        ...result,
        diff_segments: [
          { segment_id: "same", kind: "equal", text: "甲旧乙删丙" },
          { segment_id: "same", kind: "insert", replacement_text: "增" },
        ],
      },
      reason: "duplicate-segment-id",
    },
    {
      label: "base rebuild mismatch",
      value: result,
      expectedBaseText: "作者已经改过",
      reason: "base-rebuild-mismatch",
    },
    {
      label: "candidate rebuild mismatch",
      value: { ...result, replacement_text: "伪造候选" },
      reason: "candidate-rebuild-mismatch",
    },
    {
      label: "character count mismatch",
      value: { ...result, replacement_character_count: 999 },
      reason: "character-count-mismatch",
    },
    {
      label: "invalid segment shape",
      value: {
        ...result,
        diff_segments: [{ segment_id: "bad", kind: "insert" }],
      },
      reason: "invalid-segment",
    },
    {
      label: "an extra root field",
      value: { ...result, debug_trace: "must not cross the contract" },
      reason: "invalid-result",
    },
    {
      label: "an extra segment field",
      value: {
        ...result,
        diff_segments: result.diff_segments.map((segment, index) => (
          index === 1 ? { ...segment, html: "<strong>unsafe</strong>" } : segment
        )),
      },
      reason: "invalid-segment",
    },
    {
      label: "a blank summary",
      value: { ...result, short_summary: "  \n  " },
      reason: "invalid-result",
    },
    {
      label: "an overlong summary",
      value: { ...result, short_summary: "摘".repeat(241) },
      reason: "invalid-result",
    },
    {
      label: "a blank replacement",
      value: { ...result, replacement_text: "   " },
      reason: "invalid-result",
    },
    {
      label: "an overlong replacement",
      value: { ...result, replacement_text: "候".repeat(24_001) },
      reason: "invalid-result",
    },
    {
      label: "an overlong warning",
      value: { ...result, warnings: ["警".repeat(241)] },
      reason: "invalid-result",
    },
    {
      label: "an empty segment id",
      value: {
        ...result,
        diff_segments: result.diff_segments.map((segment, index) => (
          index === 1 ? { ...segment, segment_id: "" } : segment
        )),
      },
      reason: "invalid-segment",
    },
  ])("fails closed for $label", ({ value, expectedBaseText, reason }) => {
    expect(validateSelectionEditResultV2(value, {
      selectionId: SELECTION_ID,
      operation: "polish",
      baseText: expectedBaseText ?? "甲旧乙删丙",
    })).toMatchObject({ ok: false, reason });
  });

  it("accepts the backend contract limits exactly at their boundary", () => {
    const replacement = "候".repeat(24_000);
    expect(validateSelectionEditResultV2({
      ...result,
      replacement_text: replacement,
      short_summary: "摘".repeat(240),
      replacement_character_count: 24_000,
      warnings: ["警".repeat(240)],
      diff_segments: [{
        segment_id: "boundary",
        kind: "replace",
        original_text: identity.baseText,
        replacement_text: replacement,
      }],
    }, {
      selectionId: SELECTION_ID,
      operation: "polish",
      baseText: identity.baseText,
    })).toMatchObject({ ok: true });
  });
});


describe("review draft decisions", () => {
  it("records decisions immutably and composes accepted/rejected changes exactly once", () => {
    const draft = createSelectionEditReviewDraft(result);
    const acceptedReplace = setSelectionEditReviewDecision(draft, "s1", "accept");
    const rejectedDelete = setSelectionEditReviewDecision(acceptedReplace, "s3", "reject");
    const acceptedInsert = setSelectionEditReviewDecision(rejectedDelete, "s5", "accept");

    expect(draft.decisions).toEqual({});
    expect(selectionEditReviewMetrics(acceptedInsert)).toEqual({
      changeCount: 3,
      acceptedCount: 2,
      rejectedCount: 1,
      undecidedCount: 0,
      decidedCount: 3,
    });
    expect(composeSelectionEditReview(acceptedInsert)).toEqual({
      ok: true,
      replacementText: "甲新乙删丙增",
      acceptedSegmentIds: ["s1", "s5"],
      rejectedSegmentIds: ["s3"],
    });
  });

  it("blocks applying while any change remains undecided", () => {
    const draft = setSelectionEditReviewDecision(
      createSelectionEditReviewDraft(result),
      "s1",
      "accept",
    );
    expect(composeSelectionEditReview(draft)).toEqual({
      ok: false,
      reason: "undecided-changes",
      undecidedSegmentIds: ["s3", "s5"],
    });
  });

  it("does not create an application from no differences or all rejected changes", () => {
    expect(composeSelectionEditReview(
      createSelectionEditReviewDraft(noDifferenceResult),
    )).toEqual({ ok: false, reason: "no-changes", undecidedSegmentIds: [] });
    expect(composeSelectionEditReview(
      decideAllSelectionEditChanges(createSelectionEditReviewDraft(result), "reject"),
    )).toEqual({
      ok: false,
      reason: "no-accepted-changes",
      undecidedSegmentIds: [],
    });
  });

  it("rejects decisions for equal or unknown segments", () => {
    const draft = createSelectionEditReviewDraft(result);
    expect(() => setSelectionEditReviewDecision(draft, "s0", "accept"))
      .toThrow("equal review segments cannot be decided");
    expect(() => setSelectionEditReviewDecision(draft, "missing", "reject"))
      .toThrow("unknown review segment");
  });
});


describe("review session state machine", () => {
  it("covers preparation, generation, review, apply, undo and discarded states", () => {
    let state = openReview();
    expect(state.focusRequest?.target).toEqual({ kind: "change", segmentId: "s1" });

    state = expectStatePhase(
      transitionSelectionEditReview(state, {
        type: "set-decision",
        segmentId: "s1",
        decision: "accept",
      }),
      "reviewing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, {
        type: "set-decision",
        segmentId: "s3",
        decision: "reject",
      }),
      "reviewing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, {
        type: "set-decision",
        segmentId: "s5",
        decision: "accept",
      }),
      "reviewing",
    );
    const applying = transitionSelectionEditReview(state, { type: "request-apply" });
    expect(applying).toMatchObject({
      ok: true,
      state: { phase: "applying" },
      effect: {
        type: "apply",
        request: {
          reviewSessionId: "review-session-1",
          selectionId: SELECTION_ID,
          fieldId: "chapter.body",
          baseText: "甲旧乙删丙",
          replacementText: "甲新乙删丙增",
          acceptedSegmentIds: ["s1", "s5"],
          rejectedSegmentIds: ["s3"],
        },
      },
    });
    state = applying.state;
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "apply-succeeded" }),
      "applied",
    );
    expect(state.focusRequest?.target).toEqual({
      kind: "source-field",
      fieldId: "chapter.body",
    });
    const undo = transitionSelectionEditReview(state, { type: "request-undo" });
    expect(undo).toMatchObject({ ok: true, effect: { type: "undo", fieldId: "chapter.body" } });
    state = undo.state;
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "undo-succeeded" }),
      "discarded",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "reset" }),
      "idle",
    );
  });

  it("accept-all resolves every change and emits one application effect", () => {
    const applying = transitionSelectionEditReview(openReview(), { type: "accept-all" });
    expect(applying).toMatchObject({
      ok: true,
      state: { phase: "applying" },
      effect: {
        type: "apply",
        request: {
          replacementText: result.replacement_text,
          acceptedSegmentIds: ["s1", "s3", "s5"],
          rejectedSegmentIds: [],
        },
      },
    });
  });

  it("blocks an application with undecided changes and requires exit confirmation after acceptance", () => {
    let state = openReview();
    state = expectStatePhase(transitionSelectionEditReview(state, {
      type: "set-decision",
      segmentId: "s1",
      decision: "accept",
    }), "reviewing");
    expect(transitionSelectionEditReview(state, { type: "request-apply" })).toMatchObject({
      ok: false,
      reason: "undecided-changes",
      undecidedSegmentIds: ["s3", "s5"],
    });
    expect(shouldConfirmSelectionEditReviewExit(state)).toBe(true);
    expect(transitionSelectionEditReview(state, { type: "exit" })).toMatchObject({
      ok: false,
      reason: "exit-confirmation-required",
    });
    expectStatePhase(
      transitionSelectionEditReview(state, { type: "confirm-exit" }),
      "discarded",
    );
  });

  it("moves focus with bounded previous/next navigation", () => {
    let state = openReview();
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "navigate", direction: "next" }),
      "reviewing",
    );
    expect(state).toMatchObject({
      activeChangeIndex: 1,
      focusRequest: { target: { kind: "change", segmentId: "s3" } },
    });
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "navigate", direction: "next" }),
      "reviewing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "navigate", direction: "next" }),
      "reviewing",
    );
    expect(state).toMatchObject({
      activeChangeIndex: 2,
      focusRequest: { target: { kind: "change", segmentId: "s5" } },
    });
  });

  it("shows no-difference review without creating a pseudo change", () => {
    const noDifferenceIdentity = { ...identity, baseText: "潮声" };
    const state = openReview(noDifferenceIdentity, noDifferenceResult);
    expect(state).toMatchObject({
      phase: "reviewing",
      activeChangeIndex: -1,
      liveMessage: "未发现需要修改的差异。",
      focusRequest: { target: { kind: "review-heading" } },
    });
    expect(transitionSelectionEditReview(state, { type: "accept-all" })).toMatchObject({
      ok: false,
      reason: "no-changes",
    });
  });

  it("keeps original text across generation failure, conflict, retry and cancellation", () => {
    let state = expectStatePhase(
      transitionSelectionEditReview(createSelectionEditReviewSession(), {
        type: "prepare",
        identity,
      }),
      "preparing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "generation-failed", message: "模型超时" }),
      "failed",
    );
    if (state.phase !== "failed") throw new Error("expected failed state");
    expect(state.identity.baseText).toBe("甲旧乙删丙");
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "retry" }),
      "preparing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "generation-started" }),
      "generating",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "conflict", message: "字段已变化" }),
      "conflict",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "retry" }),
      "preparing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "generation-started" }),
      "generating",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "cancel" }),
      "discarded",
    );
    if (state.phase !== "discarded") throw new Error("expected discarded state");
    expect(state.identity.baseText).toBe("甲旧乙删丙");
  });

  it("fails closed when a ready result cannot rebuild the frozen base", () => {
    let state = expectStatePhase(
      transitionSelectionEditReview(createSelectionEditReviewSession(), {
        type: "prepare",
        identity,
      }),
      "preparing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "generation-started" }),
      "generating",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, {
        type: "generation-ready",
        result: { ...result, replacement_text: "伪造候选" },
      }),
      "failed",
    );
    expect(state.phase).toBe("failed");
    expect(state.liveMessage).toContain("重建候选");
  });

  it("allows only one active review session", () => {
    const state = openReview();
    expect(transitionSelectionEditReview(state, {
      type: "prepare",
      identity: { ...identity, reviewSessionId: "another" },
    })).toMatchObject({ ok: false, reason: "invalid-transition" });
  });

  it("rejects an invalid session identity before entering preparation", () => {
    expect(transitionSelectionEditReview(createSelectionEditReviewSession(), {
      type: "prepare",
      identity: { ...identity, selectionId: "not-a-uuid" },
    })).toMatchObject({
      ok: false,
      reason: "invalid-session",
      state: { phase: "idle" },
    });
  });

  it("does not reopen a discarded session when a late generation event arrives", () => {
    let state = expectStatePhase(
      transitionSelectionEditReview(createSelectionEditReviewSession(), {
        type: "prepare",
        identity,
      }),
      "preparing",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "generation-started" }),
      "generating",
    );
    state = expectStatePhase(
      transitionSelectionEditReview(state, { type: "cancel" }),
      "discarded",
    );
    expect(transitionSelectionEditReview(state, {
      type: "generation-failed",
      message: "迟到失败",
    })).toMatchObject({
      ok: false,
      reason: "invalid-transition",
      state: { phase: "discarded" },
    });
    expect(transitionSelectionEditReview(state, {
      type: "generation-ready",
      result,
    })).toMatchObject({
      ok: false,
      reason: "invalid-transition",
      state: { phase: "discarded" },
    });
  });
});


describe("review coordinator", () => {
  it("publishes successful transitions and keeps blocked transitions silent", () => {
    const coordinator = createSelectionEditReviewCoordinator();
    const listener = vi.fn();
    const unsubscribe = coordinator.subscribe(listener);
    coordinator.dispatch({ type: "prepare", identity });
    coordinator.dispatch({ type: "generation-started", jobId: "job-1" });
    coordinator.dispatch({ type: "generation-ready", result });
    const beforeBlocked = listener.mock.calls.length;
    const blocked = coordinator.dispatch({ type: "request-apply" });

    expect(coordinator.getState().phase).toBe("reviewing");
    expect(listener).toHaveBeenCalledTimes(3);
    expect(blocked).toMatchObject({ ok: false, reason: "undecided-changes" });
    expect(listener).toHaveBeenCalledTimes(beforeBlocked);
    unsubscribe();
    coordinator.dispatch({ type: "reject-all" });
    expect(listener).toHaveBeenCalledTimes(beforeBlocked);
    coordinator.dispose();
    expect(() => coordinator.dispatch({ type: "reset" })).toThrow("disposed");
  });
});
