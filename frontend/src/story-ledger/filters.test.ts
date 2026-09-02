import { describe, expect, it, vi } from "vitest";

import {
  describeStoryLedgerFilters,
  normalizeStoryLedgerFilters,
  renderStoryLedgerFilters,
  storyLedgerFilterCount,
} from "./filters";
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

describe("story ledger filter view", () => {
  it("normalizes a stable combined server filter without inventing client search", () => {
    const normalized = normalizeStoryLedgerFilters({
      factTypes: ["world_state", "character_state", "world_state", ""],
      effectiveState: "source_invalid",
      health: "ambiguous",
      dimension: "  location ",
      sourceDocumentId: " chapter-1 ",
      commitBatchId: " batch-1 ",
      factTimelineId: " branch ",
      entityType: "character",
      entityId: " character-1 ",
      reviewOnly: true,
    });

    expect(normalized).toEqual({
      factTypes: ["character_state", "world_state"],
      effectiveState: "source_invalid",
      health: "ambiguous",
      dimension: "location",
      sourceDocumentId: "chapter-1",
      commitBatchId: "batch-1",
      factTimelineId: "branch",
      entityType: "character",
      entityId: "character-1",
      reviewOnly: true,
    });
    expect(storyLedgerFilterCount(normalized)).toBe(10);
    expect(describeStoryLedgerFilters(normalized)).toContain("仅待核对");
    expect(describeStoryLedgerFilters(normalized)).toContain("来源失效");
    expect(describeStoryLedgerFilters(normalized)).toContain("实体：人物 / character-1");
    expect("query" in normalized).toBe(false);
  });

  it("drops an entity ID when no entity type establishes its meaning", () => {
    expect(normalizeStoryLedgerFilters({ entityId: "orphan-id" })).toEqual({});
  });

  it("renders labelled controls for all eight types and explicit multi-timeline filtering", () => {
    const onChange = vi.fn();
    const root = renderStoryLedgerFilters(React, {
      idPrefix: "filters",
      filters: {},
      multipleTimelines: true,
      timelineOptions: [
        { id: "main", name: "主线" },
        { id: "branch", name: "雨夜分支" },
      ],
      onChange,
    });

    expect(findAll(root, (element) => element.type === "form")[0].props["aria-label"])
      .toBe("故事账本组合筛选");
    expect(findAll(root, (element) => element.props.type === "checkbox")).toHaveLength(9);
    expect(textContent(root)).toContain("人物状态");
    expect(textContent(root)).toContain("关系状态");
    expect(textContent(root)).toContain("故事线事件");
    expect(textContent(root)).toContain("伏笔事件");
    expect(textContent(root)).toContain("故事时间");
    expect(textContent(root)).toContain("知情变化");
    expect(textContent(root)).toContain("世界状态");
    expect(textContent(root)).toContain("通用事实");
    expect(textContent(root)).toContain("事实所属时间线");
    expect(textContent(root)).toContain("雨夜分支");
    expect(textContent(root)).not.toContain("全文搜索");
  });

  it("emits a combined filter immediately from each visible field", () => {
    const onChange = vi.fn();
    const root = renderStoryLedgerFilters(React, {
      idPrefix: "filters",
      filters: { effectiveState: "current", sourceDocumentId: "chapter-1" },
      multipleTimelines: false,
      onChange,
    });
    const health = findAll(root, (element) => element.type === "select")[1];
    (health.props.onChange as (event: unknown) => void)({ target: { value: "conflict" } });

    expect(onChange).toHaveBeenCalledWith({
      effectiveState: "current",
      health: "conflict",
      sourceDocumentId: "chapter-1",
    });
  });
});
