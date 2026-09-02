import { describe, expect, it, vi } from "vitest";

import type { StoryLedgerFactDetail, StoryLedgerFactItem } from "./contracts";
import { renderStoryLedgerFactDetail } from "./fact-detail";
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

function item(): StoryLedgerFactItem {
  return {
    id: "fact-1",
    fact_type: "knowledge_event",
    subject: "林舟",
    predicate: "knows",
    object_preview: "知道北塔密钥藏在钟下",
    object_truncated: false,
    timeline_id: "branch",
    dimension: "secret_knowledge",
    event_kind: "learned",
    story_sequence: 12,
    created_at: "2026-09-01T00:00:00Z",
    effective_state: "source_invalid",
    effective_reason_codes: ["source_binding_invalid"],
    included_in_current_projection: false,
    health: "ambiguous",
    health_reason_codes: ["reference_missing"],
    entities: [{
      entity_type: "character",
      entity_id: "character-deleted",
      label: "林舟旧实例",
      lifecycle_state: "deleted",
      reference_missing: true,
    }],
    source: {
      source_document_id: "chapter-12",
      document_title: "第十二章",
      document_position: 12,
      source_revision_id: "revision-12",
      revision_number: 3,
      revision_is_current: false,
      source_content_hash: "hash",
      source_start: 1,
      source_end: 8,
      binding_state: "invalid",
      commit_batch_id: "batch-12",
      evidence_available: true,
    },
  };
}

function detail(): StoryLedgerFactDetail {
  return {
    schema_version: "story-ledger-fact-detail/1",
    novel_id: "novel-1",
    ledger_snapshot_token: "snapshot-1",
    story_ledger_version: 18,
    timeline: {
      mode: "multiple",
      timeline_id: "branch",
      timeline_name: "雨夜分支",
      narrative_cutoff: 20,
    },
    item: item(),
    object_text: "林舟知道北塔密钥藏在钟下。",
    details: { confidence: "uncertain", witnesses: ["闻川"] },
    story_time: { day: 3 },
    visibility: { author_only: true },
    lifecycle_status: "active",
    schema_version_of_fact: "story-fact/3",
    event_fingerprint: "fingerprint",
    event_links: [{
      id: "link-1",
      direction: "incoming",
      link_type: "reveals",
      other_fact_id: "fact-0",
      details: {},
      created_at: "2026-09-01T00:00:00Z",
    }],
    bindings: [{
      id: "binding-1",
      source_document_id: "chapter-12",
      source_revision_id: "revision-12",
      source_content_hash: "hash",
      validity_state: "invalid",
      proposal_item_id: "proposal-1",
      commit_batch_id: "batch-12",
      commit_batch_state: "committed",
      created_at: "2026-09-01T00:00:00Z",
    }],
  };
}

function props(overrides: Partial<Parameters<typeof renderStoryLedgerFactDetail>[1]> = {}) {
  return {
    idPrefix: "detail-test",
    selectedItem: item(),
    detail: detail(),
    loading: false,
    error: null,
    multipleTimelines: true,
    onRetry: vi.fn(),
    onClose: vi.fn(),
    onOpenSource: vi.fn(),
    onCorrect: vi.fn(),
    onPreviewBatchRevert: vi.fn(),
    ...overrides,
  };
}

describe("story ledger fact detail", () => {
  it("keeps effective state and health as independent explained axes", () => {
    const root = renderStoryLedgerFactDetail(React, props());

    expect(textContent(root)).toContain("生命周期结果来源失效");
    expect(textContent(root)).toContain("健康度不确定");
    expect(textContent(root)).toContain("来源绑定已失效");
    expect(textContent(root)).toContain("关联对象已不存在");
    expect(textContent(root)).toContain("当前投影未纳入");
  });

  it("shows structured data, links, bindings, explicit timeline and deleted references", () => {
    const root = renderStoryLedgerFactDetail(React, props());
    const text = textContent(root);

    expect(text).toContain("事实时间线branch");
    expect(text).toContain("历史／未链接人物：林舟旧实例");
    expect(text).toContain("结构化详情");
    expect(text).toContain("confidenceuncertain");
    expect(text).toContain("事件链接（1）");
    expect(text).toContain("传入 · reveals · 关联事实 fact-0");
    expect(text).toContain("不可变来源绑定（1）");
    expect(text).toContain("批次 batch-12（committed）");
    expect(findAll(root, (element) => element.type === "textarea")).toHaveLength(0);
  });

  it("uses separate selected, loading and error states", () => {
    const empty = renderStoryLedgerFactDetail(React, props({
      selectedItem: null,
      detail: null,
    }));
    const loading = renderStoryLedgerFactDetail(React, props({
      detail: null,
      loading: true,
    }));
    const error = renderStoryLedgerFactDetail(React, props({
      detail: null,
      error: "详情版本过期",
    }));

    expect(textContent(empty)).toContain("选择一条事实查看详情");
    expect(textContent(loading)).toContain("正在读取事实详情");
    expect(findAll(loading, (element) => element.props.role === "status")).toHaveLength(1);
    expect(textContent(error)).toContain("详情版本过期");
    expect(findAll(error, (element) => element.props.role === "alert")).toHaveLength(1);
  });

  it("closes the responsive detail drawer with Escape", () => {
    const onClose = vi.fn();
    const root = renderStoryLedgerFactDetail(React, props({ onClose }));
    const aside = findAll(root, (element) => element.type === "aside")[0];
    const preventDefault = vi.fn();

    (aside.props.onKeyDown as (event: unknown) => void)({
      key: "Escape",
      preventDefault,
    });

    expect(preventDefault).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
