import type { QwenPawReactRuntime } from "../assistant-pane";
import type { WritingMethodSnapshot } from "./api";
import type { WritingMethodStatus } from "./contracts";

export interface WritingMethodPresentation {
  readonly title: string;
  readonly description: string;
  readonly tone: "warning";
}

/** Automatic method selection is silent; surface only actions needing attention. */
export function writingMethodPresentation(
  status: WritingMethodStatus | null,
): WritingMethodPresentation | null {
  switch (status?.state) {
    case "failed":
      return { title: "本次生成未完成", description: "请查看任务失败原因后重试。", tone: "warning" };
    case "unknown":
      return { title: "生成结果尚未确认", description: "请先查询原任务结果；当前不能自动重试，以免重复生成。", tone: "warning" };
    case "stale":
      return { title: "本次资料或权限已变化", description: "请核对当前资料后重新生成。", tone: "warning" };
    default:
      return null;
  }
}

export interface WritingMethodStatusProps {
  readonly snapshot: WritingMethodSnapshot;
}

export interface WritingMethodReceiptProps {
  readonly status: WritingMethodStatus | null;
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
  h("p", { style: { margin: "4px 0" } }, presentation.description));
}

/** Frozen action evidence stays in the response; only failures need a notice. */
export function createWritingMethodReceiptNotice(
  React: Pick<QwenPawReactRuntime, "createElement">,
): (props: WritingMethodReceiptProps) => unknown {
  return function WritingMethodReceiptNotice({ status }: WritingMethodReceiptProps): unknown {
    return renderNotice(React, writingMethodPresentation(status));
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
    return renderNotice(React, writingMethodPresentation(status));
  };
}
