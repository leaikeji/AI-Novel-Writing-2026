import type { QwenPawReactRuntime } from "../assistant-pane";
import type { WritingMethodSnapshot } from "./api";
import { assembledCapabilityIds, type WritingMethodStatus } from "./contracts";
import { methodDetailLines } from "./details";

export interface WritingMethodPresentation {
  readonly title: string;
  readonly description: string;
  readonly methodNames: readonly string[];
  readonly omittedNames: readonly string[];
  readonly semanticText: string;
  readonly tone: "neutral" | "success" | "warning";
}

export function writingMethodPresentation(
  status: WritingMethodStatus | null,
  displayNames: Readonly<Record<string, string>> = {},
): WritingMethodPresentation {
  const name = (id: string) => displayNames[id] || id;
  const methods = status?.details && status.method_input_hash
    ? status.details.methods.map(item => item.display_name) : status ? assembledCapabilityIds(status).map(name) : [];
  const omitted = status?.omitted_ids.map(name) ?? [];
  const semanticText = status?.semantic_enabled
    ? `语义补选按需启用；本次额外判断 ${status.auxiliary_calls} 次。`
    : `语义补选未启用；本次额外判断 ${status?.auxiliary_calls ?? 0} 次。`;
  let title = "自动选择写作方法";
  let description = "等待本次任务的方法记录。";
  let tone: WritingMethodPresentation["tone"] = "neutral";
  switch (status?.state) {
    case "routing_started": title = "正在判断适用方法"; break;
    case "route_ready": title = "方法已选择，等待组装"; break;
    case "assembled":
      title = "方法内容已组装";
      description = "尚未派发写作请求。";
      break;
    case "dispatch_started":
      title = "写作请求正在派发";
      description = "等待派发结果确认。";
      break;
    case "dispatched":
      title = methods.length ? `本次已装载到请求：${methods.join(" · ")}` : "本次请求未附加分类方法";
      description = "这是请求装载记录，不代表模型一定遵循或写作效果已经验证。";
      tone = "success";
      break;
    case "failed":
      title = "本次写作请求失败"; description = "保留本次记录，请检查任务失败原因。"; tone = "warning"; break;
    case "cancelled":
      title = "本次请求已取消"; description = "本次方法记录保留。"; tone = "warning"; break;
    case "unknown":
      title = "请求结果尚未确认";
      description = "远端是否结束仍不确定，不能自动重试；请先核查原任务状态。";
      tone = "warning";
      break;
    case "stale":
      title = "本次资料或权限已变化"; description = "请核对当前资料后发起新任务。"; tone = "warning"; break;
  }
  return { title, description, methodNames: methods, omittedNames: omitted, semanticText, tone };
}

export interface WritingMethodStatusProps {
  readonly snapshot: WritingMethodSnapshot;
  readonly displayNames?: Readonly<Record<string, string>>;
}

export interface WritingMethodReceiptProps {
  readonly status: WritingMethodStatus | null;
  readonly displayNames?: Readonly<Record<string, string>>;
}

/** Author-visible receipt for one managed button action.
 * It renders only frozen server evidence returned with that action; it never
 * reads the current catalog to reinterpret an older result.
 */
export function createWritingMethodReceiptNotice(
  React: Pick<QwenPawReactRuntime, "createElement">,
): (props: WritingMethodReceiptProps) => unknown {
  const h = React.createElement;
  return function WritingMethodReceiptNotice({
    status,
    displayNames,
  }: WritingMethodReceiptProps): unknown {
    if (!status) return null;
    const presentation = writingMethodPresentation(status, displayNames);
    const details = status.details
      ? methodDetailLines(status.details).map((line, index) => h(
          "p",
          { key: `detail-${index}` },
          line,
        ))
      : [];
    return h(
      "section",
      {
        className: "anw-writing-method-status",
        "data-tone": presentation.tone,
        "data-action-id": status.action_id,
        "aria-label": "本次写作方法",
        style: {
          minWidth: 0,
          maxWidth: "100%",
          overflowWrap: "anywhere",
          whiteSpace: "normal",
          lineHeight: 1.5,
        },
      },
      h(
        "div",
        { role: "status", "aria-live": "polite", "aria-atomic": true },
        h("strong", null, presentation.title),
        h("p", { style: { margin: "4px 0" } }, presentation.description),
      ),
      h(
        "details",
        { style: { minWidth: 0, maxWidth: "100%" } },
        h("summary", { style: { cursor: "pointer" } }, "查看写作方法记录"),
        h(
          "div",
          {
            style: {
              maxHeight: "16rem",
              overflowY: "auto",
              overflowWrap: "anywhere",
            },
            tabIndex: 0,
            "aria-label": "写作方法详细记录",
          },
          h("p", null, presentation.semanticText),
          ...details,
          h("p", null, `记录编号：${status.dispatch_id}`),
          status.method_input_hash
            ? h("p", null, `方法摘要：${status.method_input_hash}`)
            : null,
        ),
      ),
    );
  };
}

/** Host React factory. Mount in PawApp's status area, never inside novel text. */
export function createWritingMethodStatusNotice(
  React: Pick<QwenPawReactRuntime, "createElement">,
): (props: WritingMethodStatusProps) => unknown {
  const h = React.createElement;
  return function WritingMethodStatusNotice({ snapshot, displayNames }: WritingMethodStatusProps): unknown {
    if (!snapshot.action) return null;
    // Defensive check for consumers that construct a snapshot outside the controller.
    const status = snapshot.status?.action_id === snapshot.action.action_id ? snapshot.status : null;
    const presentation = writingMethodPresentation(status, displayNames);
    const error = !snapshot.connected || snapshot.error === "transport_unavailable"
      ? "写作方法状态尚未接入当前入口。"
      : snapshot.error ? "方法状态暂时无法确认，请检查原任务；不会自动重新生成。" : null;
    const detailItems: unknown[] = [h("p", { key: "semantic" }, presentation.semanticText)];
    if (status?.method_input_hash) {
      detailItems.push(h("p", { key: "methods" }, `${status.details ? "已组装方法" : "已组装的附加方法"}：${presentation.methodNames.join(" · ") || "无"}`));
    }
    if (presentation.omittedNames.length) {
      detailItems.push(h("p", { key: "omitted" }, `本次未装载：${presentation.omittedNames.join(" · ")}`));
    }
    if (status) {
      if (status.details) detailItems.push(...methodDetailLines(status.details).map((line, index) => h("p", { key: `detail-${index}` }, line)));
      detailItems.push(h("p", { key: "dispatch" }, `记录编号：${status.dispatch_id}`));
      if (status.method_input_hash) detailItems.push(h("p", { key: "hash" }, `方法摘要：${status.method_input_hash}`));
    }
    return h("section", {
      className: "anw-writing-method-status", "data-tone": presentation.tone,
      "data-action-id": snapshot.action.action_id,
      style: { minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", whiteSpace: "normal", lineHeight: 1.5 },
    },
    h("div", { role: "status", "aria-live": "polite", "aria-atomic": true },
      h("span", {}, error || presentation.title),
      h("p", { style: { margin: "4px 0" } }, presentation.description)),
    h("details", { style: { minWidth: 0, maxWidth: "100%" } },
      h("summary", { style: { cursor: "pointer" } }, "查看写作方法记录"),
      h("div", { style: { maxHeight: "16rem", overflowY: "auto", overflowWrap: "anywhere" }, tabIndex: 0,
        "aria-label": "写作方法详细记录" }, ...detailItems)));
  };
}
