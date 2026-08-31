import type { CharacterReactRuntime } from "./character-workspace";
import type { CharacterFactSourceV2 } from "./contracts";
import type { SourceRangeResolution } from "./source-coordinate";

type ElementNode = unknown;

export interface CharacterSourceRevisionV1 {
  readonly id: string;
  readonly document_id: string;
  readonly revision_number: number;
  readonly content_hash: string;
  readonly content_markdown: string;
  readonly content_text: string;
}

export interface CharacterSourceViewerProps {
  readonly source: CharacterFactSourceV2;
  readonly revision: CharacterSourceRevisionV1 | null;
  readonly resolution: SourceRangeResolution | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly onClose: () => void;
}

export function renderCharacterSourceViewer(
  React: CharacterReactRuntime,
  props: CharacterSourceViewerProps,
): ElementNode {
  const h = React.createElement;
  const content = props.revision?.content_text ?? "";
  const verified = props.resolution?.status === "verified" ? props.resolution : null;
  return h(
    "aside",
    { className: "anw-character-source-viewer", role: "dialog", "aria-modal": true, "aria-labelledby": "anw-character-source-title" },
    h("header", null, h("div", null, h("h3", { id: "anw-character-source-title" }, "来源证据"), h("p", null, props.source.document_title)), h("button", { type: "button", "aria-label": "关闭来源证据", onClick: props.onClose }, "×")),
    h(
      "div",
      { className: "anw-character-source-body" },
      h("div", { className: "anw-character-source-meta" }, h("span", null, props.source.revision_is_current ? "当前正文" : "历史版本"), h("span", null, `revision ${props.revision?.revision_number ?? "—"}`), h("span", null, verified ? "坐标与区间哈希已验证" : "无法安全定位")),
      props.loading ? h("div", { className: "anw-character-workspace-empty", role: "status" }, "正在读取不可变来源版本…") : null,
      props.error ? h("div", { className: "anw-character-workspace-alert", role: "alert" }, props.error) : null,
      !props.loading && !props.error && verified
        ? h("pre", { className: "anw-character-source-text" }, content.slice(0, verified.startUtf16), h("mark", null, content.slice(verified.startUtf16, verified.endUtf16)), content.slice(verified.endUtf16))
        : !props.loading && !props.error && props.resolution?.status === "fallback"
          ? h("div", { className: "anw-character-source-fallback" }, h("strong", null, "无法安全定位原文区间"), h("p", null, "系统不会搜索相似文本或猜测位置。以下仅为保存时的有界摘录。"), h("blockquote", null, props.resolution.excerpt || "没有可显示的安全摘录"))
          : null,
    ),
  );
}
