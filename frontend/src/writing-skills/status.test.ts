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

describe("writing method status presentation", () => {
  it("keeps selected, assembled, and dispatched meanings separate", () => {
    expect(writingMethodPresentation(status("route_ready")).title).toContain("已选择");
    expect(writingMethodPresentation(status("assembled")).title).toBe("方法内容已组装");
    expect(writingMethodPresentation(status("dispatch_started")).title).toBe("写作请求正在派发");
    expect(writingMethodPresentation(status("dispatched"), { "suspense-writing": "悬疑" }).title)
      .toBe("本次已装载到请求：悬疑");
  });

  it("never presents an omitted future module as loaded", () => {
    const view = writingMethodPresentation(status("dispatched"), { "future-module": "未来模块" });
    expect(view.methodNames).toEqual(["suspense-writing"]);
    expect(view.omittedNames).toEqual(["未来模块"]);
    expect(view.title).not.toContain("未来模块");
  });

  it("defaults semantic off and explains unknown without a retry button", () => {
    expect(writingMethodPresentation(null).semanticText).toContain("未启用");
    expect(writingMethodPresentation(null).semanticText).toContain("0 次");
    const view = writingMethodPresentation(status("unknown"));
    expect(view.tone).toBe("warning");
    expect(view.description).toContain("不能自动重试");
    const Notice = createWritingMethodStatusNotice(React);
    expect(text(Notice({ snapshot: snapshot("unknown") }))).toContain("不能自动重试");
  });

  it("renders a keyboard-native details control and narrow-width wrapping outside正文", () => {
    const Notice = createWritingMethodStatusNotice(React);
    const root = Notice({ snapshot: snapshot() }) as Element;
    expect(root.type).toBe("section");
    expect(root.props.style).toMatchObject({ minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", whiteSpace: "normal" });
    const live = root.children[0] as Element;
    expect(live.props).toMatchObject({ role: "status", "aria-live": "polite" });
    const details = root.children[1] as Element;
    expect(details.type).toBe("details");
    expect((details.children[0] as Element).type).toBe("summary");
    expect((details.children[1] as Element).props).toMatchObject({ tabIndex: 0 });
    expect(text(root)).toContain("查看写作方法记录");
    expect(root.props).not.toHaveProperty("dangerouslySetInnerHTML");
  });

  it("uses dynamic display names as text, without a fixed category list", () => {
    const Notice = createWritingMethodStatusNotice(React);
    const tree = Notice({ snapshot: snapshot("dispatched"), displayNames: { "suspense-writing": "<script>not html</script>" } });
    expect(text(tree)).toContain("<script>not html</script>");
    expect(JSON.stringify(tree)).not.toContain("dangerouslySetInnerHTML");
  });

  it("renders a frozen button receipt without consulting the live catalog", () => {
    const Receipt = createWritingMethodReceiptNotice(React);
    const root = Receipt({ status: status("dispatched") }) as Element;
    expect(root.props["aria-label"]).toBe("本次写作方法");
    expect(text(root)).toContain("本次已装载到请求");
    expect(text(root)).toContain("查看写作方法记录");
    expect(text(root)).toContain("记录编号");
  });

  it("does not display prior-action success for a new action or a read failure", () => {
    const Notice = createWritingMethodStatusNotice(React);
    const stale = { ...snapshot("dispatched"), status: { ...status("dispatched"), action_id: D } };
    expect(text(Notice({ snapshot: stale }))).not.toContain("本次已装载到请求");
    const failed = { ...snapshot("dispatched"), error: "status_unavailable" as const };
    expect(text(Notice({ snapshot: failed }))).toContain("方法状态暂时无法确认");
    expect(Notice({ snapshot: { ...snapshot(), action: null, status: null } })).toBeNull();
  });
});
