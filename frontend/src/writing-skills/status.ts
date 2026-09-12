import type { QwenPawReactRuntime } from "../assistant-pane";
import type { WritingMethodSnapshot } from "./api";
import type { WritingMethodStatus } from "./contracts";

export interface WritingMethodPresentation {
  readonly title: string;
  readonly description: string;
  readonly tone: "info" | "warning";
  readonly methods?: readonly string[];
  readonly omittedMethods?: readonly string[];
  readonly auxiliaryCalls?: number | null;
}

function basisLabel(value: string): string {
  return ({
    primary: "正文主方法",
    explicit: "作者明确指定",
    deterministic: "分类资料匹配",
    semantic: "本章资料判断",
  } as Record<string, string>)[value] ?? "已冻结依据";
}

function evidenceLabel(value: string): string {
  if (value === "genre") return "题材分类";
  if (value === "subgenre") return "细分类别";
  if (value === "author_method_requirements") return "作者方法要求";
  if (value.startsWith("task_prompt.")) return "本章任务资料";
  return "已冻结资料";
}

/** Automatic method selection is silent; surface only actions needing attention. */
export function writingMethodPresentation(
  status: WritingMethodStatus | null,
  showSuccess = false,
): WritingMethodPresentation | null {
  switch (status?.state) {
    case "failed":
      return {
        title: "本次生成未完成",
        description: showSuccess
          ? "本次未完成，请核查原因；可选择“本次仅用通用方法”重新发起。"
          : "请查看任务失败原因后重试。",
        tone: "warning",
      };
    case "unknown":
      return { title: "上一次生成需要确认", description: "请先查询原任务；确认没有进行中的正文任务后，可由你明确重新生成。", tone: "warning" };
    case "stale":
      return { title: "本次资料或权限已变化", description: "请核对当前资料后重新生成。", tone: "warning" };
    default:
      if (showSuccess && status?.state === "dispatched" && status.method_input_hash && status.details) {
        return {
          title: `本次请求已提供：${status.details.methods.map(item => item.display_name).join(" · ")}`,
          description: "方法按本次资料自动选择；它们不会覆盖作者设定或直接修改正式正文。",
          tone: "info",
          methods: status.details.methods.map(item => {
            const refs = [...new Set(item.evidence_refs.map(evidenceLabel))];
            return `${item.display_name}${item.version ? ` v${item.version}` : ""} · ${basisLabel(item.basis)}`
              + `${refs.length ? ` · 依据：${refs.join("、")}` : ""}`;
          }),
          omittedMethods: status.omitted_ids,
          auxiliaryCalls: status.semantic_enabled ? status.auxiliary_calls : 0,
        };
      }
      return null;
  }
}

export interface WritingMethodStatusProps {
  readonly snapshot: WritingMethodSnapshot;
}

export interface WritingMethodReceiptProps {
  readonly status: WritingMethodStatus | null;
  readonly showSuccess?: boolean;
}

function renderNotice(
  React: Pick<QwenPawReactRuntime, "createElement">,
  presentation: WritingMethodPresentation | null,
): unknown {
  if (!presentation) return null;
  const h = React.createElement;
  return h("section", {
    className: "anw-writing-method-status",
    "data-tone": presentation.tone,
    "aria-label": "生成状态",
    role: "status",
    "aria-live": "polite",
    "aria-atomic": true,
    style: { minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", whiteSpace: "normal", lineHeight: 1.5 },
  },
  h("strong", null, presentation.title),
  h("p", { style: { margin: "4px 0" } }, presentation.description),
  presentation.methods ? h("details", { style: { marginTop: 4 } },
    h("summary", null, "查看方法依据"),
    h("ul", null, ...presentation.methods.map(item => h("li", { key: item }, item))),
    presentation.omittedMethods?.length
      ? h("p", null, `因预算未装载：${presentation.omittedMethods.join("、")}`)
      : null,
    h("p", null, presentation.auxiliaryCalls === null
      ? "判断调用次数未确认"
      : `本次方法判断调用：${presentation.auxiliaryCalls} 次`),
  ) : null);
}

/** Frozen action evidence stays in the response; only failures need a notice. */
export function createWritingMethodReceiptNotice(
  React: Pick<QwenPawReactRuntime, "createElement">,
): (props: WritingMethodReceiptProps) => unknown {
  return function WritingMethodReceiptNotice({ status, showSuccess = false }: WritingMethodReceiptProps): unknown {
    return renderNotice(React, writingMethodPresentation(status, showSuccess));
  };
}

export function createWritingMethodStatusNotice(
  React: Pick<QwenPawReactRuntime, "createElement">,
): (props: WritingMethodStatusProps) => unknown {
  return function WritingMethodStatusNotice({ snapshot }: WritingMethodStatusProps): unknown {
    if (!snapshot.action) return null;
    const status = snapshot.status?.action_id === snapshot.action.action_id ? snapshot.status : null;
    if (!snapshot.connected || snapshot.error) {
      return renderNotice(React, {
        title: "生成状态暂时无法确认",
        description: "请先查询原任务结果；当前不能自动重试，以免重复生成。",
        tone: "warning",
      });
    }
    return renderNotice(React, writingMethodPresentation(status, true));
  };
}
