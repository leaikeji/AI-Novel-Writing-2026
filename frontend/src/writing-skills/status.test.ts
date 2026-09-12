import { describe, expect, it } from "vitest";
import { createWritingAction, type WritingMethodSnapshot } from "./api";
import { parseWritingMethodStatus } from "./contracts";
import {
  createWritingMethodReceiptNotice,
  createWritingMethodStatusNotice,
  writingMethodPresentation,
} from "./status";

const A = "11111111-1111-4111-8111-111111111111";
const D = "22222222-2222-4222-8222-222222222222";
function status(state = "assembled") {
  return parseWritingMethodStatus({ schema_version: "writing-method-status/1", action_id: A,
    dispatch_id: D, state, selected_ids: ["suspense-writing", "future-module"], omitted_ids: ["future-module"],
    method_input_hash: ["claimed", "routing_started", "route_ready"].includes(state) ? null : "a".repeat(64),
    job_ref: state === "dispatched" ? "job-1" : null })!;
}
function detailedStatus(state = "dispatched") {
  return parseWritingMethodStatus({
    schema_version: "writing-method-status/1", action_id: A, dispatch_id: D, state,
    selected_ids: ["golden-finger-writing", "future-module"], omitted_ids: ["future-module"],
    method_input_hash: "a".repeat(64), job_ref: state === "dispatched" ? "job-1" : null,
    semantic_enabled: true, auxiliary_calls: 1,
    details: {
      schema_version: "writing-method-details/1", primary_skill: "prose-writing",
      methods: [
        { skill_id: "prose-writing", display_name: "正文写作", version: "0.4.0",
          body_sha256: "b".repeat(64), reference_count: 2, basis: "primary", evidence_refs: [] },
        { skill_id: "golden-finger-writing", display_name: "金手指机制", version: "1.0.0",
          body_sha256: "c".repeat(64), reference_count: 1, basis: "semantic",
          evidence_refs: ["task_prompt.0"] },
      ],
      reasons: ["semantic:golden-finger-writing"], estimated_tokens: 1200,
    },
  })!;
}
interface Element {
  type: unknown;
  props: Record<string, unknown>;
  children: unknown[];
}
const React = { createElement: (type: unknown, props: unknown, ...children: unknown[]) => ({ type, props, children }) };
function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return "";
  return ((value as Element).children ?? []).map(text).join("");
}
function snapshot(state = "assembled"): WritingMethodSnapshot {
  return {
    action: createWritingAction({ ownerKey: "o", workspaceKey: "w", tabId: "t", agentId: "ai-novel-writer",
      scopeKind: "novel", scopeId: "n" }, "input", () => A),
    status: status(state), connected: true, loading: false, error: null,
  };
}

describe("actionable generation notices", () => {
  it.each(["claimed", "routing_started", "route_ready", "assembled", "dispatch_started", "dispatched", "cancelled"])(
    "keeps automatic method processing silent for %s", state => {
      expect(writingMethodPresentation(status(state))).toBeNull();
      expect(createWritingMethodReceiptNotice(React)({ status: status(state) })).toBeNull();
      expect(createWritingMethodStatusNotice(React)({ snapshot: snapshot(state) })).toBeNull();
    },
  );

  it.each([
    ["failed", "请查看任务失败原因"],
    ["unknown", "明确重新生成"],
    ["stale", "请核对当前资料"],
  ])("preserves the action needed for %s without technical records", (state, action) => {
    const Receipt = createWritingMethodReceiptNotice(React);
    const root = Receipt({ status: status(state) }) as Element;
    expect(text(root)).toContain(action);
    expect(root.props).toMatchObject({ role: "status", "aria-live": "polite", "aria-label": "生成状态" });
    expect(root.props.style).toMatchObject({ minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", whiteSpace: "normal" });
    const encoded = JSON.stringify(root);
    for (const value of ["button", "details", "summary", "dangerouslySetInnerHTML", D, "a".repeat(64), "future-module", "<script>", "语义", "方法摘要"]) {
      expect(encoded).not.toContain(value);
    }
  });

  it("does not show prior-action failure for a new action", () => {
    const Notice = createWritingMethodStatusNotice(React);
    expect(Notice({ snapshot: { ...snapshot("unknown"), status: { ...status("unknown"), action_id: D } } })).toBeNull();
    expect(Notice({ snapshot: { ...snapshot(), action: null, status: null } })).toBeNull();
  });

  it.each([
    { error: "status_unavailable" as const },
    { error: "transport_unavailable" as const },
    { connected: false },
  ])("preserves uncertain-result protection on read or transport failure %#", patch => {
    const Notice = createWritingMethodStatusNotice(React);
    const root = Notice({ snapshot: { ...snapshot("dispatched"), ...patch } });
    expect(text(root)).toContain("生成状态暂时无法确认");
    expect(text(root)).toContain("不能自动重试");
    expect(JSON.stringify(root)).not.toContain("button");
  });

  it("does not manufacture a status when no evidence exists", () => {
    expect(writingMethodPresentation(null)).toBeNull();
    expect(createWritingMethodReceiptNotice(React)({ status: null })).toBeNull();
  });

  it("shows actual dispatched method blocks only when the chapter opts into success receipts", () => {
    expect(writingMethodPresentation(detailedStatus("assembled"), true)).toBeNull();
    const Receipt = createWritingMethodReceiptNotice(React);
    expect(Receipt({ status: detailedStatus() })).toBeNull();
    const root = Receipt({ status: detailedStatus(), showSuccess: true }) as Element;
    const rendered = text(root);
    expect(rendered).toContain("本次请求已提供：正文写作 · 金手指机制");
    expect(rendered).toContain("金手指机制 v1.0.0 · 本章资料判断 · 依据：本章任务资料");
    expect(rendered).toContain("因预算未装载：future-module");
    expect(rendered).toContain("本次方法判断调用：1 次");
    expect(JSON.stringify(root)).toContain('"type":"details"');
    expect(JSON.stringify(root)).toContain('"type":"summary"');
    expect(JSON.stringify(root)).not.toContain("这是一段小说正文");
  });

  it("uses the chapter-specific generic-only recovery hint without changing shared receipts", () => {
    const shared = writingMethodPresentation(status("failed"))!;
    const chapter = writingMethodPresentation(status("failed"), true)!;
    expect(shared.description).not.toContain("仅用通用方法");
    expect(chapter.description).toContain("本次仅用通用方法");
  });
});
