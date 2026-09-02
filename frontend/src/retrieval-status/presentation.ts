import type { RetrievalSummaryV1 } from "./contracts";


export interface RetrievalSummaryPresentation {
  readonly tone: "success" | "info" | "warning";
  readonly title: string;
  readonly description: string;
}


const REASON_DESCRIPTIONS: Readonly<Record<RetrievalSummaryV1["reason_code"], string>> = {
  ready: "语义索引可用。",
  not_authorized: "这本小说尚未授权云端向量处理。",
  index_building: "语义索引仍在构建。",
  index_outdated: "语义索引需要刷新。",
  partial_failed: "部分索引暂时不可用。",
  provider_unavailable: "向量服务暂时不可用。",
  no_hit: "没有找到足够相关的额外内容。",
  not_applicable: "此操作不需要额外检索。",
};


export function retrievalSummaryPresentation(
  summary: RetrievalSummaryV1,
): RetrievalSummaryPresentation {
  if (summary.outcome === "used" && summary.mode === "hybrid") {
    return {
      tone: "success",
      title: "本次使用了混合检索",
      description: `向量语义与本地关键词共同提供了 ${summary.hit_count} 条相关参考。`,
    };
  }
  if (summary.mode === "lexical_only" && summary.hit_count > 0) {
    return {
      tone: summary.outcome === "degraded" ? "warning" : "success",
      title: summary.outcome === "degraded" ? "向量不可用，已自动使用本地检索" : "本次使用了本地检索",
      description: `${REASON_DESCRIPTIONS[summary.reason_code]} 本地内容提供了 ${summary.hit_count} 条相关参考。`,
    };
  }
  if (summary.outcome === "no_hit") {
    return {
      tone: "info",
      title: "没有找到额外相关内容",
      description: "这不是写作失败；本次仅使用经过范围控制的基础上下文。",
    };
  }
  if (summary.outcome === "not_run") {
    return {
      tone: "info",
      title: "本次未运行额外检索",
      description: `${REASON_DESCRIPTIONS[summary.reason_code]} 已使用经过范围控制的基础上下文。`,
    };
  }
  return {
    tone: "warning",
    title: summary.outcome === "failed" ? "额外检索未能完成" : "本次仅使用基础上下文",
    description: `${REASON_DESCRIPTIONS[summary.reason_code]} 正式正文不会因此被自动覆盖。`,
  };
}


export function semanticIndexSettingsPath(novelId: string): string {
  const query = new URLSearchParams({
    novel_workbench: "1",
    novel_id: novelId,
    section: "settings",
    settings_tab: "semantic-index",
  });
  return `/chat?${query.toString()}`;
}
