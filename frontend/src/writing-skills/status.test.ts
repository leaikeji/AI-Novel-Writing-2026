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
    ["unknown", "不能自动重试"],
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
});
