import { afterEach, describe, expect, it, vi } from "vitest";

import { STORY_LEDGER_FACT_TYPES, type StoryLedgerFactItem } from "./contracts";
import { renderStoryLedgerFactList } from "./fact-list";
import type { StoryLedgerReactRuntime } from "./runtime";

interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}

const React: StoryLedgerReactRuntime = {
  createElement(type, props, ...children): FakeElement {
    return { type, props: props ?? {}, children };
  },
};

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

function fact(overrides: Partial<StoryLedgerFactItem> = {}): StoryLedgerFactItem {
  return {
    id: "fact-1",
    fact_type: "character_state",
    subject: "林舟",
    predicate: "location",
    object_preview: "林舟抵达北塔",
    object_truncated: false,
    timeline_id: "timeline-branch",
    dimension: "location",
    event_kind: null,
    story_sequence: 8,
    created_at: "2026-09-01T00:00:00Z",
    effective_state: "current",
    effective_reason_codes: ["active_and_selected"],
    included_in_current_projection: true,
    health: "ok",
    health_reason_codes: [],
    entities: [{
      entity_type: "character",
      entity_id: "character-1",
      label: "林舟",
      lifecycle_state: "active",
      reference_missing: false,
    }],
    source: {
      source_document_id: "chapter-8",
      document_title: "第八章 北塔",
      document_position: 8,
      source_revision_id: "revision-8",
      revision_number: 2,
      revision_is_current: true,
      source_content_hash: "hash",
      source_start: 2,
      source_end: 9,
      binding_state: "current",
      commit_batch_id: "batch-8",
      evidence_available: true,
    },
    ...overrides,
  };
}

function props(items: readonly StoryLedgerFactItem[]) {
  return {
    idPrefix: "ledger-test",
    items,
    selectedFactId: null,
    multipleTimelines: true,
    loading: false,
    loadingMore: false,
    error: null,
    nextCursor: null,
    openMenuFactId: null,
    onSelect: vi.fn(),
    onOpenSource: vi.fn(),
    onCorrect: vi.fn(),
    onPreviewBatchRevert: vi.fn(),
    onMenuOpenChange: vi.fn(),
    onLoadMore: vi.fn(),
    onRetry: vi.fn(),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("story ledger semantic fact list", () => {
  it("renders every frozen fact type as labelled records without fake table roles", () => {
    const items = STORY_LEDGER_FACT_TYPES.map((factType, index) => fact({
      id: `fact-${index}`,
      fact_type: factType,
      subject: `主体 ${index}`,
    }));
    const root = renderStoryLedgerFactList(React, props(items));

    expect(findAll(root, (element) => element.type === "ul")).toHaveLength(1);
    expect(findAll(root, (element) => element.type === "li")).toHaveLength(8);
    expect(findAll(root, (element) => ["table", "row", "cell"].includes(
      String(element.props.role),
    ))).toHaveLength(0);
    for (const label of [
      "人物状态",
      "关系状态",
      "故事线事件",
      "伏笔事件",
      "故事时间",
      "知情变化",
      "世界状态",
      "通用事实",
    ]) expect(textContent(root)).toContain(label);
    expect(textContent(root)).toContain("事实时间线timeline-branch");
  });

  it("preserves missing and absent entity references instead of dropping the fact", () => {
    const missing = fact({
      id: "missing",
      subject: "被删除人物的旧称",
      entities: [{
        entity_type: "character",
        entity_id: "deleted-character",
        label: "旧人物",
        lifecycle_state: "deleted",
        reference_missing: true,
      }],
    });
    const unlinked = fact({
      id: "unlinked",
      fact_type: "general_fact",
      subject: "北塔旧律",
      entities: [],
      source: null,
    });
    const root = renderStoryLedgerFactList(React, props([missing, unlinked]));

    expect(textContent(root)).toContain("历史／未链接人物：旧人物");
    expect(textContent(root)).toContain("未关联实体 · 保留原始主体：北塔旧律");
    expect(textContent(root)).toContain("作者手工事实／无来源绑定");
    expect(findAll(root, (element) => element.type === "article")).toHaveLength(2);
  });

  it("exposes one primary action and a labelled keyboard menu with Escape focus return", () => {
    const onMenuOpenChange = vi.fn();
    const focus = vi.fn();
    vi.stubGlobal("document", { getElementById: vi.fn(() => ({ focus })) });
    const base = { ...props([fact()]), onMenuOpenChange };
    let root = renderStoryLedgerFactList(React, base);
    const more = findAll(root, (element) => element.props["aria-haspopup"] === "menu")[0];
    expect(more.props["aria-label"]).toBe("更多操作：林舟");

    (more.props.onKeyDown as (event: unknown) => void)({
      key: "ArrowDown",
      currentTarget: {},
      preventDefault: vi.fn(),
    });
    expect(onMenuOpenChange).toHaveBeenCalledWith("fact-1");

    root = renderStoryLedgerFactList(React, { ...base, openMenuFactId: "fact-1" });
    const menu = findAll(root, (element) => element.props.role === "menu")[0];
    expect(findAll(menu, (element) => element.props.role === "menuitem").map(textContent))
      .toEqual(["查看来源", "修正事实", "预览撤销第 8 章同步"]);
    expect(findAll(root, (element) => element.type === "button" && textContent(element) === "查看"))
      .toHaveLength(1);

    (menu.props.onKeyDown as (event: unknown) => void)({
      key: "Escape",
      currentTarget: {},
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });
    expect(onMenuOpenChange).toHaveBeenLastCalledWith(null);
    expect(focus).toHaveBeenCalledWith();
  });

  it("renders distinct loading, empty and error states", () => {
    const base = props([]);
    const loading = renderStoryLedgerFactList(React, { ...base, loading: true });
    const empty = renderStoryLedgerFactList(React, base);
    const error = renderStoryLedgerFactList(React, { ...base, error: "网络中断" });

    expect(textContent(loading)).toContain("正在读取故事事实");
    expect(findAll(loading, (element) => element.props.role === "status")).toHaveLength(1);
    expect(textContent(empty)).toContain("当前筛选下没有事实");
    expect(textContent(error)).toContain("网络中断");
    expect(findAll(error, (element) => element.props.role === "alert")).toHaveLength(1);
  });
});
