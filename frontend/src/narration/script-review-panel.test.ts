import { describe, expect, it, vi } from "vitest";

import { ScriptApiError } from "./script-api";
import {
  NARRATION_REVIEW_TAXONOMY_VERSION,
  NARRATION_SCRIPT_REVIEW_API_VERSION,
  SCRIPT_BLOCKER_CODES,
  SCRIPT_WARNING_CODES,
  ScriptContractError,
  parseScriptReviewResource,
} from "./script-contracts";
import type {
  ScriptReviewResource,
} from "./script-contracts";
import {
  buildScriptReviewPanelModel,
  buildScriptReviewSpeakerChoices,
  classifyScriptReviewFailure,
  createScriptReviewPanel,
  scriptReviewIssueLabel,
} from "./script-review-panel";
import type {
  ScriptReviewPanelApi,
  ScriptReviewPanelProps,
  ScriptReviewReactRuntime,
} from "./script-review-panel";
import { T4_CHAPTER_NARRATION_STYLES } from "./styles/t4-chapter";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  readonly dependencies: readonly unknown[];
  cleanup?: () => void;
}


function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const result = findAll(
    root,
    (element) => element.type === "button" && textContent(element) === label,
  )[0];
  if (!result) throw new Error(`button not found: ${label}`);
  return result;
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pendingEffects: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;

  const React: ScriptReviewReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
      return [
        states[index] as T,
        (next) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        },
      ];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
      pendingEffects.push({ index, effect, dependencies: [...dependencies] });
    },
  };

  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const pending = pendingEffects;
      pendingEffects = [];
      pending.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
    },
    unmount(): void {
      effects.forEach((effect) => effect?.cleanup?.());
    },
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


const SCRIPT_ID = "b1000000-0000-4000-8000-000000000001";
const VERSION_ID = "b1000000-0000-4000-8000-000000000002";
const VERSION_ID_2 = "b1000000-0000-4000-8000-000000000012";
const NOVEL_ID = "b1000000-0000-4000-8000-000000000003";
const DOCUMENT_ID = "b1000000-0000-4000-8000-000000000004";
const REVISION_ID = "b1000000-0000-4000-8000-000000000005";
const SEGMENT_ID = "b1000000-0000-4000-8000-000000000006";
const REQUEST_ID = "b1000000-0000-4000-8000-000000000007";
const CHARACTER_ID = "b1000000-0000-4000-8000-000000000008";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);
const SOURCE_BLOCK_KEY = `sb1_${"d".repeat(64)}`;
const LATEST_REVISION_ID = "b1000000-0000-4000-8000-000000000015";
const LATEST_SOURCE_HASH = "e".repeat(64);


function segment(changes: Record<string, unknown> = {}) {
  return {
    segment_id: SEGMENT_ID,
    ordinal: 0,
    segment_kind: "dialogue",
    source_block_key: SOURCE_BLOCK_KEY,
    source_start_utf16: 0,
    source_end_utf16: 4,
    source_text: "“你好”",
    spoken_text: "你好",
    local_hash: SHA_C,
    speaker_kind: "character",
    speaker_label: "林晚",
    character_id: CHARACTER_ID,
    anonymous_speaker_id: null,
    confidence: "high",
    casting_state: "resolved",
    issue_codes: [],
    editable: true,
    ...changes,
  };
}


function resource(changes: Record<string, unknown> = {}): ScriptReviewResource {
  return parseScriptReviewResource({
    contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
    taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
    script_id: SCRIPT_ID,
    script_version_id: VERSION_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    revision_id: REVISION_ID,
    source_content_hash: SHA_A,
    immutable_hash: SHA_B,
    version_number: 1,
    state: "review_required",
    effective_policy: "always_review",
    source_status: "current",
    warning_count: 0,
    blocker_count: 0,
    allowed_actions: ["approve", "edit_segment", "reanalyze_segments"],
    segments: [segment()],
    issues: [],
    approval: null,
    ...changes,
  });
}


function blockerReview(): ScriptReviewResource {
  return resource({
    effective_policy: "blockers_only",
    blocker_count: 2,
    allowed_actions: ["edit_segment", "reanalyze_segments"],
    segments: [segment({
      speaker_kind: "unknown",
      speaker_label: "待确认人物",
      character_id: null,
      confidence: "unknown",
      issue_codes: ["B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"],
    })],
    issues: ["B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"].map((code) => ({
      taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
      code,
      severity: "blocker",
      segment_id: SEGMENT_ID,
      evidence_summary: null,
      evidence_digest: null,
    })),
  });
}


function approvedReview(): ScriptReviewResource {
  return resource({
    state: "approved",
    allowed_actions: [],
    approval: {
      kind: "manual_after_review",
      request_id: REQUEST_ID,
      actor_type: "owner",
      actor_id: "local-owner",
      approved_at: "2026-08-26T12:00:00Z",
    },
  });
}


function nextReview(): ScriptReviewResource {
  return resource({
    script_version_id: VERSION_ID_2,
    version_number: 2,
  });
}


function latestReview(): ScriptReviewResource {
  return resource({
    script_version_id: VERSION_ID_2,
    version_number: 2,
    revision_id: LATEST_REVISION_ID,
    source_content_hash: LATEST_SOURCE_HASH,
  });
}


function api(overrides: Partial<ScriptReviewPanelApi> = {}): ScriptReviewPanelApi {
  return {
    approve: vi.fn(async () => approvedReview()),
    reanalyzeSegments: vi.fn(async () => nextReview()),
    ...overrides,
  };
}


function props(
  review: ScriptReviewResource,
  changes: Partial<ScriptReviewPanelProps> = {},
): ScriptReviewPanelProps {
  return {
    review,
    requestId: REQUEST_ID,
    requestVersion: 7,
    createIdempotencyKey: () => "script-review-panel-0001",
    ...changes,
  };
}


describe("script review panel model", () => {
  it("blocks the primary action while any blocker remains", () => {
    const model = buildScriptReviewPanelModel({
      review: blockerReview(),
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });
    expect(model.canApprove).toBe(false);
    expect(model.primaryLabel).toBe("仍有 2 个阻塞");
    expect(model.visibleIssues).toHaveLength(2);
  });

  it("allows the always-review owner path only when blockers are zero", () => {
    const model = buildScriptReviewPanelModel({
      review: resource(),
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });
    expect(model.canApprove).toBe(true);
    expect(model.primaryLabel).toBe("确认并冻结脚本");
    expect(model.visibleSegments).toHaveLength(1);
    expect(model.showEdit).toBe(true);
    expect(model.showReanalyze).toBe(true);
  });

  it("removes immutable segment actions after the script is frozen", () => {
    const model = buildScriptReviewPanelModel({
      review: approvedReview(),
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });
    expect(model.showEdit).toBe(false);
    expect(model.showReanalyze).toBe(false);

    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, props(approvedReview(), {
      onEditSegment: vi.fn(),
    }));
    expect(textContent(tree)).not.toContain("修正说话人或朗读文本");
    expect(textContent(tree)).not.toContain("重新分析此句");
  });

  it("requires a deliberate old-snapshot choice after working copy divergence", () => {
    const diverged = resource({
      source_status: "working_copy_diverged",
      allowed_actions: [
        "approve", "edit_segment", "reanalyze_segments", "continue_snapshot", "reanalyze_latest",
      ],
    });
    expect(buildScriptReviewPanelModel({
      review: diverged,
      showAllIssues: false,
      snapshotConfirmed: false,
      busy: false,
    }).canApprove).toBe(false);
    expect(buildScriptReviewPanelModel({
      review: diverged,
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    }).canApprove).toBe(true);
  });

  it("has a stable Chinese label for every frozen taxonomy code", () => {
    for (const code of [...SCRIPT_WARNING_CODES, ...SCRIPT_BLOCKER_CODES]) {
      expect(scriptReviewIssueLabel(code).length).toBeGreaterThan(4);
    }
  });

  it("renders every confidence value with an exhaustive Chinese display label", () => {
    const expectedLabels: Record<
      ScriptReviewResource["segments"][number]["confidence"],
      string
    > = {
      high: "高",
      medium: "中",
      low: "低",
      unknown: "未知",
    };
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());

    const entries = Object.entries(expectedLabels) as Array<
      [ScriptReviewResource["segments"][number]["confidence"], string]
    >;
    for (const [confidence, label] of entries) {
      const base = resource();
      const review: ScriptReviewResource = {
        ...base,
        segments: [{ ...base.segments[0], confidence }],
      };
      const tree = harness.render(Panel, props(review));
      expect(textContent(tree)).toContain(`置信度：${label}`);
      expect(textContent(tree)).not.toContain(`置信度：${confidence}`);
    }
  });

  it("offers only narrator, resolved character bindings, and resolved anonymous speakers", () => {
    const current = resource();
    const base = current.segments[0];
    const review = {
      ...current,
      segments: [
        base,
        {
          ...base,
          segment_id: "b1000000-0000-4000-8000-000000000021",
          ordinal: 1,
          speaker_kind: "anonymous",
          speaker_label: "店员",
          character_id: null,
          anonymous_speaker_id: "b1000000-0000-4000-8000-000000000022",
        },
        {
          ...base,
          segment_id: "b1000000-0000-4000-8000-000000000023",
          ordinal: 2,
          speaker_kind: "character",
          speaker_label: "未绑定角色",
          character_id: "b1000000-0000-4000-8000-000000000024",
          casting_state: "unresolved",
        },
        {
          ...base,
          segment_id: "b1000000-0000-4000-8000-000000000025",
          ordinal: 3,
          speaker_kind: "group",
          speaker_label: "众人",
          character_id: null,
          casting_state: "resolved",
        },
      ],
    } as ScriptReviewResource;

    expect(buildScriptReviewSpeakerChoices(review, [{
      characterId: CHARACTER_ID,
      speakerLabel: "林晚",
    }])).toEqual([
      expect.objectContaining({ key: "narrator", speakerKind: "narrator" }),
      expect.objectContaining({
        key: `character:${CHARACTER_ID}`,
        speakerKind: "character",
        speakerLabel: "林晚",
      }),
      expect.objectContaining({
        key: "anonymous:b1000000-0000-4000-8000-000000000022",
        speakerKind: "anonymous",
        speakerLabel: "店员",
      }),
    ]);
  });
});


describe("script review panel component", () => {
  it("declares the desktop target and renders blocker evidence with disabled approval", () => {
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, props(blockerReview()));

    expect(tree.props["data-min-viewport"]).toBe("1920x1080");
    expect(textContent(tree)).toContain("无法确定这一句由谁说");
    expect(findButton(tree, "仍有 2 个阻塞").props.disabled).toBe(true);
  });

  it("moves focus to the first blocker and restores the trigger exactly once", () => {
    const triggerFocus = vi.fn();
    const blockerFocus = vi.fn();
    const titleFocus = vi.fn();
    const close = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, props(blockerReview(), {
      triggerRef: { current: { focus: triggerFocus } },
      onClose: close,
    }));
    const blocker = findAll(tree, (element) => element.props["data-severity"] === "blocker")[0];
    const title = findAll(tree, (element) => element.props.id === "anw-script-review-title")[0];
    (blocker.props.ref as { current: unknown }).current = { focus: blockerFocus };
    (title.props.ref as { current: unknown }).current = { focus: titleFocus };

    harness.commitEffects();
    expect(blockerFocus).toHaveBeenCalledTimes(1);
    expect(titleFocus).not.toHaveBeenCalled();

    (findButton(tree, "关闭").props.onClick as () => void)();
    harness.unmount();
    expect(close).toHaveBeenCalledTimes(1);
    expect(triggerFocus).toHaveBeenCalledTimes(1);
  });

  it("focuses the title when always-review has no blockers", () => {
    const titleFocus = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, props(resource()));
    const title = findAll(tree, (element) => element.props.id === "anw-script-review-title")[0];
    (title.props.ref as { current: unknown }).current = { focus: titleFocus };
    harness.commitEffects();
    expect(titleFocus).toHaveBeenCalledTimes(1);
    expect(findAll(tree, (element) => (
      element.props["aria-label"] === "复核问题筛选"
    ))).toHaveLength(0);
  });

  it("calls the real approval operation with immutable guards and no actor field", async () => {
    const approve = vi.fn<ScriptReviewPanelApi["approve"]>(async () => approvedReview());
    const changed = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api({ approve }));
    const tree = harness.render(Panel, props(resource(), { onReviewChanged: changed }));

    (findButton(tree, "确认并冻结脚本").props.onClick as () => void)();
    await settle();

    expect(approve).toHaveBeenCalledTimes(1);
    const [versionId, payload, expectedScope, idempotencyKey] = approve.mock.calls[0];
    expect(versionId).toBe(VERSION_ID);
    expect(idempotencyKey).toBe("script-review-panel-0001");
    expect(expectedScope).toEqual({
      novel_id: NOVEL_ID,
      document_id: DOCUMENT_ID,
      revision_id: REVISION_ID,
      source_content_hash: SHA_A,
      script_id: SCRIPT_ID,
      script_version_id: VERSION_ID,
    });
    expect(payload).toEqual({
      request_id: REQUEST_ID,
      expected_request_version: 7,
      expected_version_number: 1,
      expected_immutable_hash: SHA_B,
      source_revision_id: REVISION_ID,
      confirmed: true,
    });
    expect(payload).not.toHaveProperty("actor_id");
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ state: "approved" }));
  });

  it("rejects a cross-novel approval response and hides unwired edit capability", async () => {
    const crossNovel = resource({
      novel_id: "d1000000-0000-4000-8000-000000000099",
      state: "approved",
      allowed_actions: [],
      approval: {
        kind: "manual_after_review",
        request_id: REQUEST_ID,
        actor_type: "owner",
        actor_id: "local-owner",
        approved_at: "2026-08-26T12:00:00Z",
      },
    });
    const changed = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api({
      approve: vi.fn(async () => crossNovel),
    }));
    const componentProps = props(resource(), { onReviewChanged: changed });
    let tree = harness.render(Panel, componentProps);

    expect(textContent(tree)).not.toContain("修改人物或音色");
    expect(textContent(tree)).not.toContain("修正说话人或朗读文本");
    (findButton(tree, "确认并冻结脚本").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, componentProps);

    expect(changed).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("服务返回了其他作品或脚本的结果");
  });

  it("never invokes approval while blockers remain", () => {
    const approve = vi.fn(async () => approvedReview());
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api({ approve }));
    const tree = harness.render(Panel, props(blockerReview()));

    (findButton(tree, "仍有 2 个阻塞").props.onClick as () => void)();
    expect(approve).not.toHaveBeenCalled();
  });

  it("reanalyzes one exact segment and only accepts a new immutable version", async () => {
    const reanalyzeSegments = vi.fn(async () => nextReview());
    const changed = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api({ reanalyzeSegments }));
    const review = blockerReview();
    const tree = harness.render(Panel, props(review, { onReviewChanged: changed }));

    (findButton(tree, "重新分析此句").props.onClick as () => void)();
    await settle();

    expect(reanalyzeSegments).toHaveBeenCalledWith(
      VERSION_ID,
      {
        request_id: REQUEST_ID,
        expected_request_version: 7,
        expected_version_number: 1,
        expected_immutable_hash: SHA_B,
        segment_ids: [SEGMENT_ID],
      },
      {
        novel_id: NOVEL_ID,
        document_id: DOCUMENT_ID,
        revision_id: REVISION_ID,
        source_content_hash: SHA_A,
        script_id: SCRIPT_ID,
        script_version_id: VERSION_ID,
      },
      "script-review-panel-0001",
      expect.any(AbortSignal),
    );
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({
      script_version_id: VERSION_ID_2,
      version_number: 2,
    }));
  });

  it("rejects a same-version reanalysis response instead of replacing the panel", async () => {
    const changed = vi.fn();
    const reanalyzeSegments = vi.fn(async () => blockerReview());
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api({ reanalyzeSegments }));
    let tree = harness.render(Panel, props(blockerReview(), { onReviewChanged: changed }));

    (findButton(tree, "重新分析此句").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, props(blockerReview(), { onReviewChanged: changed }));

    expect(changed).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("服务返回了其他作品或脚本的结果");
  });

  it("requires explicit snapshot selection before enabling approval", () => {
    const diverged = resource({
      source_status: "working_copy_diverged",
      allowed_actions: [
        "approve", "edit_segment", "reanalyze_segments", "continue_snapshot", "reanalyze_latest",
      ],
    });
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const componentProps = props(diverged);
    let tree = harness.render(Panel, componentProps);
    expect(findButton(tree, "确认并冻结脚本").props.disabled).toBe(true);

    (findButton(tree, "选择继续复核此快照").props.onClick as () => void)();
    tree = harness.render(Panel, componentProps);
    expect(findButton(tree, "确认并冻结脚本").props.disabled).toBe(false);
    expect(textContent(tree)).toContain("已选择继续复核该正文快照");
  });

  it("offers the latest-source action only when a real async boundary is wired", async () => {
    const diverged = resource({
      source_status: "working_copy_diverged",
      allowed_actions: [
        "approve", "edit_segment", "reanalyze_segments", "continue_snapshot", "reanalyze_latest",
      ],
    });
    const useLatest = vi.fn(async () => latestReview());
    const changed = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    let tree = harness.render(Panel, props(diverged));
    expect(findAll(tree, (element) => (
      element.type === "button" && textContent(element) === "重新分析最新正文"
    ))).toHaveLength(0);

    tree = harness.render(Panel, props(diverged, {
      onUseLatestSource: useLatest,
      onReviewChanged: changed,
    }));
    const button = findButton(tree, "重新分析最新正文");
    expect(button.props.disabled).toBe(false);
    (button.props.onClick as () => void)();
    await settle();
    expect(useLatest).toHaveBeenCalledWith(diverged, expect.any(AbortSignal));
    expect(changed).toHaveBeenCalledWith(latestReview());
  });

  it("shows warning-only reviews directly without a redundant issue filter", () => {
    const warning = resource({
      warning_count: 1,
      segments: [segment({
        confidence: "medium",
        issue_codes: ["W_SPEAKER_MEDIUM_CONFIDENCE"],
      })],
      issues: [{
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code: "W_SPEAKER_MEDIUM_CONFIDENCE",
        severity: "warning",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      }],
    });
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const componentProps = props(warning);
    const tree = harness.render(Panel, componentProps);
    expect(textContent(tree)).toContain("说话人判断为中等置信度");
    expect(findAll(tree, (element) => (
      element.props["aria-label"] === "复核问题筛选"
    ))).toHaveLength(0);
  });
});


describe("script review failures", () => {
  it("classifies strict response scope failures without calling them network errors", () => {
    expect(classifyScriptReviewFailure(
      new ScriptContractError("novel_id", "response scope mismatch"),
    )).toMatchObject({
      code: "RESPONSE_SCOPE_MISMATCH",
      refreshRequired: true,
    });
  });

  it("turns stale/version failures into refresh-required messages", () => {
    const failure = classifyScriptReviewFailure(new ScriptApiError(409, {
      contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
      code: "STALE_INPUT",
      message: "internal detail",
      retryable: false,
      field: null,
      current_version: 2,
    }));
    expect(failure.refreshRequired).toBe(true);
    expect(failure.message).not.toContain("internal detail");
  });

  it("keeps network failure recoverable without claiming a write occurred", () => {
    expect(classifyScriptReviewFailure(new Error("offline"))).toMatchObject({
      code: "NETWORK_ERROR",
      retryable: true,
      refreshRequired: false,
    });
  });
});


describe("script review responsive layout", () => {
  it("collapses the workspace and removes the inset shell on narrow screens", () => {
    expect(T4_CHAPTER_NARRATION_STYLES).toContain("@media (max-width: 768px)");
    expect(T4_CHAPTER_NARRATION_STYLES).toMatch(
      /@media \(max-width: 768px\)[\s\S]*?\.anw-script-review-shell\s*\{[\s\S]*?inset: 0;[\s\S]*?width: 100%;/,
    );
    expect(T4_CHAPTER_NARRATION_STYLES).toMatch(
      /@media \(max-width: 768px\)[\s\S]*?\.anw-script-review__workspace\s*\{[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/,
    );
    expect(T4_CHAPTER_NARRATION_STYLES).toMatch(
      /@media \(max-width: 768px\)[\s\S]*?\.anw-script-review__guide\s*\{[\s\S]*?position: static;/,
    );
  });
});
