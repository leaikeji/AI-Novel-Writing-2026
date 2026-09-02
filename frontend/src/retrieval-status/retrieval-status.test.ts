import { describe, expect, it, vi } from "vitest";

import {
  createRetrievalStatusNotice,
  parseRetrievalSummary,
  retrievalSummaryPresentation,
  retrievalSummaryFromJob,
  semanticIndexSettingsPath,
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
    [HYBRID, "本次使用了混合检索"],
    [{ ...HYBRID, outcome: "degraded", mode: "lexical_only", reason_code: "provider_unavailable", hit_count: 3 }, "向量不可用，已自动使用本地检索"],
    [{ ...HYBRID, outcome: "no_hit", mode: "context_only", reason_code: "no_hit", hit_count: 0 }, "没有找到额外相关内容"],
    [{ ...HYBRID, outcome: "not_run", mode: "context_only", reason_code: "not_authorized", hit_count: 0, index_state: "not_authorized" }, "本次未运行额外检索"],
  ] as const)("uses author-facing language for %#", (summary, title) => {
    expect(retrievalSummaryPresentation(summary).title).toBe(title);
  });

  it("renders an aria-live status and keyboard-native management deep link", () => {
    const React = {
      createElement: (type: unknown, props: unknown, ...children: unknown[]) => ({ type, props, children }),
      useEffect: vi.fn(),
    };
    const Notice = createRetrievalStatusNotice(React);
    const root = Notice({ summary: HYBRID, novelId: "novel / 1" }) as {
      props: Record<string, unknown>;
      children: Array<{ type: string; props: Record<string, unknown> }>;
    };
    expect(root.props).toMatchObject({ role: "status", "aria-live": "polite" });
    expect(textContent(root)).toContain("本次使用了混合检索");
    expect(root.children[root.children.length - 1]).toMatchObject({
      type: "a",
      props: { href: semanticIndexSettingsPath("novel / 1") },
    });
    expect(semanticIndexSettingsPath("novel / 1")).toContain("settings_tab=semantic-index");
  });
});
