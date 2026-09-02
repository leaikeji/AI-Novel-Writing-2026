import type { QwenPawReactRuntime } from "../assistant-pane";
import type { RetrievalSummaryV1 } from "./contracts";
import { retrievalSummaryPresentation, semanticIndexSettingsPath } from "./presentation";
import { ensureRetrievalStatusStyles } from "./styles";


export type RetrievalStatusReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useEffect"
>;


export interface RetrievalStatusNoticeProps {
  readonly summary: RetrievalSummaryV1 | null | undefined;
  readonly novelId: string;
  readonly compact?: boolean;
  readonly className?: string;
}


export function createRetrievalStatusNotice(
  React: RetrievalStatusReactRuntime,
): (props: RetrievalStatusNoticeProps) => unknown {
  const h = React.createElement;
  return function RetrievalStatusNotice(props: RetrievalStatusNoticeProps): unknown {
    React.useEffect(() => ensureRetrievalStatusStyles(), []);
    if (!props.summary) return null;
    const presentation = retrievalSummaryPresentation(props.summary);
    return h(
      "section",
      {
        className: [
          "anw-retrieval-status",
          `is-${presentation.tone}`,
          props.compact ? "is-compact" : "",
          props.className ?? "",
        ].filter(Boolean).join(" "),
        role: "status",
        "aria-live": "polite",
        "aria-atomic": "true",
        "data-retrieval-mode": props.summary.mode,
        "data-retrieval-outcome": props.summary.outcome,
      },
      h("span", { className: "anw-retrieval-status__title" }, presentation.title),
      h("span", { className: "anw-retrieval-status__description" }, presentation.description),
      h(
        "a",
        {
          className: "anw-retrieval-status__link",
          href: semanticIndexSettingsPath(props.novelId),
        },
        "管理语义索引",
      ),
    );
  };
}
