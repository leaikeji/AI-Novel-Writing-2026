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


export const EVALUATION_LABELS = {
  not_run: "尚未运行",
  pending: "评测中",
  passed: "已通过",
  failed: "未通过",
} as const;


const REASON_LABELS: Readonly<Record<string, string>> = {
  timeline_mapping_required: "正文尚未完成时间线映射。",
  embedding_secret_unavailable: "向量密钥保险箱不可用。",
  embedding_auth_failed: "API Key 验证失败。",
  embedding_rate_limited: "阿里云百炼请求过于频繁。",
  embedding_unavailable: "阿里云百炼向量服务暂时不可用。",
  consent_revoked: "小说向量授权已经撤销。",
  generation_cancelled: "本次索引构建已经取消。",
  batch_hash_mismatch: "索引来源在处理期间发生变化。",
};


export function formatEmbeddingReason(value: string | null): string | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  return REASON_LABELS[normalized] ?? `操作未完成（错误代码：${value}）`;
}


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
