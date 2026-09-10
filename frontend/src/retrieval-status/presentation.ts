import type { RetrievalSummaryV1 } from "./contracts";

export interface RetrievalSummaryPresentation {
  readonly tone: "warning";
  readonly title: string;
  readonly description: string;
}

/** Retrieval and successful local fallback run without author intervention. */
export function retrievalSummaryPresentation(
  summary: RetrievalSummaryV1,
): RetrievalSummaryPresentation | null {
  if (summary.outcome === "failed") {
    return {
      tone: "warning",
      title: "部分参考资料未能读取",
      description: "本次参考可能不完整，请核对生成内容与前文是否一致。",
    };
  }
  if (summary.reason_code === "index_outdated" && summary.mode === "context_only") {
    return {
      tone: "warning",
      title: "部分参考资料尚未更新",
      description: "本次参考可能不完整，请核对生成内容与最新正文是否一致。",
    };
  }
  return null;
}
