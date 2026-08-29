import type {
  EmbeddingConnectionState,
  EmbeddingGenerationState,
  NovelSemanticIndexState,
  SemanticCorpus,
  SemanticCorpusState,
} from "./contracts";


export const CONNECTION_LABELS: Readonly<Record<EmbeddingConnectionState, string>> = {
  unconfigured: "尚未配置",
  untested: "待测试",
  ready: "连接正常",
  failed: "连接失败",
};


export const GENERATION_LABELS: Readonly<Record<EmbeddingGenerationState, string>> = {
  draft: "候选草稿",
  building: "构建中",
  ready: "待激活",
  active: "使用中",
  failed: "构建失败",
  cancelled: "已取消",
  stale: "已过期",
  retired: "已退役",
};


export const INDEX_STATE_LABELS: Readonly<Record<NovelSemanticIndexState, string>> = {
  not_authorized: "未授权",
  empty: "尚未构建",
  current: "当前有效",
  update_pending: "有内容待更新",
  building: "构建中",
  partial_failure: "部分失败",
  stale: "已过期",
};


export const CORPUS_LABELS: Readonly<Record<SemanticCorpus, string>> = {
  manuscript: "正式正文",
  planning: "大纲与设定",
  private_asset: "绑定私有素材",
  character: "人物",
  relationship: "关系",
  story_event: "故事事件",
  storyline: "故事线",
  foreshadow: "伏笔",
  timeline: "时间线",
};


export const CORPUS_STATE_LABELS: Readonly<Record<SemanticCorpusState, string>> = {
  disabled: "尚未启用",
  empty: "无可索引来源",
  pending: "等待构建",
  building: "构建中",
  ready: "当前有效",
  failed: "构建失败",
  stale: "有更新待构建",
};


export function formatDateTime(value: string | null): string {
  if (!value) return "暂无";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleString("zh-CN")
    : "时间格式无效";
}
