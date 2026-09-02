import type { StoryLedgerSourceExcerpt } from "./contracts";
import type { StoryLedgerElementNode, StoryLedgerReactRuntime } from "./runtime";
import { splitBoundedSourceExcerpt } from "./source-coordinate";

export interface StoryLedgerSourceViewerProps {
  readonly dialogId: string;
  readonly titleId: string;
  readonly source: StoryLedgerSourceExcerpt | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly onClose: () => void;
}

/** Render only the server-bounded excerpt; no full chapter revision is loaded. */
export function renderStoryLedgerSourceViewer(
  React: StoryLedgerReactRuntime,
  props: StoryLedgerSourceViewerProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  const split = props.source?.available
    ? splitBoundedSourceExcerpt(
        props.source.excerpt,
        props.source.highlight_start,
        props.source.highlight_end,
      )
    : null;
  return h(
    "aside",
    {
      id: props.dialogId,
      className: "anw-character-source-viewer anw-story-ledger-source-viewer",
      role: "dialog",
      "aria-modal": true,
      "aria-labelledby": props.titleId,
      "aria-busy": props.loading || undefined,
      tabIndex: -1,
    },
    h("header", null, h("div", null, h("h3", { id: props.titleId }, "来源证据"), h("p", null, props.source?.document_title ?? "来源不可用")), h("button", { type: "button", "aria-label": "关闭来源证据", "data-character-drawer-close": "true", onClick: props.onClose }, "×")),
    h(
      "div",
      { className: "anw-character-source-body" },
      props.source ? h("div", { className: "anw-character-source-meta" }, h("span", null, props.source.revision_is_current ? "当前正文" : "历史版本"), h("span", null, `revision ${props.source.revision_number ?? "—"}`), h("span", null, split ? "来源区间已定位" : "无法安全定位")) : null,
      props.loading ? h("div", { className: "anw-character-workspace-empty", role: "status" }, "正在读取有界来源摘录…") : null,
      props.error ? h("div", { className: "anw-character-workspace-alert", role: "alert" }, props.error) : null,
      !props.loading && !props.error && split
        ? h("pre", { className: "anw-character-source-text" }, props.source?.truncated_before ? "…" : "", split.before, h("mark", null, split.highlighted), split.after, props.source?.truncated_after ? "…" : "")
        : !props.loading && !props.error && props.source && !split
          ? h("div", { className: "anw-character-source-fallback" }, h("strong", null, "无法安全定位原文区间"), h("p", null, "系统不会搜索相似文本或猜测位置。"), h("blockquote", null, props.source.excerpt || "没有可显示的安全摘录"))
          : null,
    ),
  );
}
