import { describe, expect, it, vi } from "vitest";

import {
  createRetrievalStatusNotice,
  parseRetrievalSummary,
  retrievalSummaryPresentation,
  retrievalSummaryFromJob,
  type RetrievalSummaryV1,
} from ".";


const HYBRID: RetrievalSummaryV1 = {
  schema_version: "retrieval-summary/1",
  outcome: "used",
  mode: "hybrid",
  reason_code: "ready",
  hit_count: 6,
  index_state: "ready",
};


function textContent(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (!value || typeof value !== "object") return "";
  const children = (value as { children?: unknown[] }).children ?? [];
  return children.map(textContent).join("");
}


describe("retrieval-summary/1", () => {
  it("keeps only the redacted public fields", () => {
    expect(parseRetrievalSummary({
      ...HYBRID,
      query: "private query",
      snippet: "private passage",
      prompt: "private prompt",
      vector: [1, 2, 3],
    })).toEqual(HYBRID);
    expect(retrievalSummaryFromJob({ retrieval_summary: HYBRID })).toEqual(HYBRID);
  });

  it("fails closed for unknown versions and impossible counts", () => {
    expect(parseRetrievalSummary({ ...HYBRID, schema_version: "retrieval-summary/2" })).toBeNull();
    expect(parseRetrievalSummary({ ...HYBRID, hit_count: -1 })).toBeNull();
    expect(parseRetrievalSummary({ ...HYBRID, mode: "configured_only" })).toBeNull();
  });

  it.each([
    HYBRID,
    { ...HYBRID, mode: "lexical_only", hit_count: 3 },
    { ...HYBRID, outcome: "degraded", mode: "lexical_only", reason_code: "provider_unavailable", hit_count: 3 },
    { ...HYBRID, outcome: "degraded", mode: "lexical_only", reason_code: "index_outdated", hit_count: 3 },
    { ...HYBRID, outcome: "no_hit", mode: "context_only", reason_code: "no_hit", hit_count: 0 },
    { ...HYBRID, outcome: "not_run", mode: "context_only", reason_code: "not_authorized", hit_count: 0, index_state: "not_authorized" },
    { ...HYBRID, outcome: "not_run", mode: "context_only", reason_code: "index_building", hit_count: 0, index_state: "building" },
  ] as const)("keeps successful retrieval and automatic fallback silent %#", summary => {
    const React = {
      createElement: (type: unknown, props: unknown, ...children: unknown[]) => ({ type, props, children }),
      useEffect: vi.fn(),
    };
    expect(retrievalSummaryPresentation(summary)).toBeNull();
    expect(createRetrievalStatusNotice(React)({ summary, novelId: "novel / 1" })).toBeNull();
  });

  it.each([
    [{ ...HYBRID, outcome: "failed", mode: "context_only", reason_code: "provider_unavailable", hit_count: 0 }, "部分参考资料未能读取"],
    [{ ...HYBRID, outcome: "degraded", mode: "context_only", reason_code: "index_outdated", hit_count: 0, index_state: "outdated" }, "部分参考资料尚未更新"],
  ] as const)("shows actionable missing or outdated reference warnings without management links %#", (summary, title) => {
    const React = {
      createElement: (type: unknown, props: unknown, ...children: unknown[]) => ({ type, props, children }),
      useEffect: vi.fn(),
    };
    const root = createRetrievalStatusNotice(React)({ summary, novelId: "novel / 1" }) as {
      props: Record<string, unknown>;
      children: Array<{ type: string; props: Record<string, unknown> }>;
    };
    expect(root.props).toMatchObject({ role: "status", "aria-live": "polite" });
    expect(textContent(root)).toContain(title);
    expect(textContent(root)).toContain("请核对生成内容");
    expect(root.children.some(child => child.type === "a" || child.type === "button")).toBe(false);
    expect(textContent(root)).not.toMatch(/语义|向量|管理|索引/);
  });
});
