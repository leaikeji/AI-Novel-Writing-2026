import { ApiError, apiRequest } from "../api";
import {
  parseEmbeddingConfigResource,
  parseEmbeddingConnectionTestResult,
  parseNovelEmbeddingConsentResource,
  parseNovelSemanticIndexStatus,
} from "./contracts";
import type {
  EmbeddingConfigResource,
  EmbeddingConnectionTestResult,
  NovelEmbeddingConsentResource,
  NovelSemanticIndexStatus,
  PutNovelEmbeddingConsentRequest,
  SaveEmbeddingCandidateRequest,
  TestEmbeddingConnectionRequest,
} from "./contracts";


export class EmbeddingApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
    message: string,
  ) {
    super(message);
  }
}


function pathSegment(value: string): string {
  return encodeURIComponent(value);
}


function jsonInit(method: "POST" | "PUT", payload: object, signal?: AbortSignal): RequestInit {
  return { method, body: JSON.stringify(payload), signal };
}


const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  embedding_secret_unavailable: "向量密钥保险箱尚未初始化。",
  secret_unavailable: "向量密钥保险箱不可用，请检查初始化状态。",
  secret_permissions_invalid: "向量密钥保险箱权限不安全，请重新初始化。",
  secret_key_invalid: "向量密钥保险箱根密钥无效。",
  secret_record_invalid: "保存的 API Key 记录无效，请重新填写。",
  secret_orphaned_records: "检测到无法解密的旧凭据记录，请先恢复原密钥保险箱。",
  secret_value_invalid: "API Key 格式无效，请检查后重新输入。",
  secret_write_failed: "API Key 加密保存失败，请稍后重试。",
  secret_delete_failed: "API Key 清除失败，请稍后重试。",
  embedding_base_url_invalid: "服务地址无效，可填写百炼 API Host、DashScope Base URL 或完整 Native Embedding 接口。",
  embedding_dns_failed: "无法解析阿里云百炼服务地址，请检查网络。",
  embedding_ssrf_blocked: "服务地址未通过安全检查，请使用阿里云百炼官方地址。",
  embedding_auth_failed: "API Key 验证失败，请检查后重新输入。",
  embedding_authentication_failed: "API Key 验证失败，请检查后重新输入。",
  embedding_model_access_denied: "当前 API Key 无权使用该向量模型，请检查百炼业务空间和模型权限。",
  embedding_quota_unavailable: "当前百炼业务空间的向量模型额度不可用，请检查服务开通状态。",
  embedding_rate_limited: "阿里云百炼请求过于频繁，请稍后重试。",
  embedding_unavailable: "阿里云百炼向量服务暂时不可用，请稍后重试。",
  embedding_protocol_error: "阿里云百炼返回了无法识别的响应。",
  embedding_request_invalid: "向量请求参数无效，请检查模型和维度。",
  embedding_dimension_mismatch: "模型返回维度与所选受支持维度不一致。",
  embedding_not_configured: "请先填写并保存 API Key。",
  dimension_mismatch: "模型返回维度与所选受支持维度不一致，候选配置未保存。",
  version_conflict: "配置已在其他窗口更新，请刷新后重试。",
  candidate_missing: "请先保存并验证候选配置。",
  candidate_not_ready: "候选索引尚未就绪。",
  candidate_evaluation_failed: "候选检索评测尚未通过。",
  previous_generation_missing: "没有可回退的上一代索引。",
  previous_generation_not_ready: "上一代索引当前不可恢复。",
  consent_not_found: "没有找到有效的小说向量授权。",
  timeline_required: "当前小说包含多条时间线，请先选择时间线。",
};


function errorCode(detail: unknown): string | null {
  if (detail === null || typeof detail !== "object") return null;
  const code = (detail as Record<string, unknown>).code;
  return typeof code === "string" ? code.toLowerCase() : null;
}


function normalizeError(reason: unknown, fallback: string): never {
  if (!(reason instanceof ApiError)) throw reason;
  const code = errorCode(reason.detail);
  throw new EmbeddingApiError(
    reason.status,
    reason.detail,
    (code && ERROR_MESSAGES[code]) || fallback,
  );
}


async function request<T>(
  path: string,
  parser: (value: unknown) => T,
  fallback: string,
  init?: RequestInit,
): Promise<T> {
  try {
    return parser(await apiRequest<unknown>(path, init));
  } catch (reason) {
    normalizeError(reason, fallback);
  }
}


export function getEmbeddingConfig(signal?: AbortSignal): Promise<EmbeddingConfigResource> {
  return request(
    "/embedding-config",
    parseEmbeddingConfigResource,
    "加载向量模型配置失败",
    { signal },
  );
}


export function initializeEmbeddingSecretStore(
  signal?: AbortSignal,
): Promise<EmbeddingConfigResource> {
  return request(
    "/embedding-config/secret-store/initialize",
    parseEmbeddingConfigResource,
    "初始化向量密钥保险箱失败",
    jsonInit("POST", {}, signal),
  );
}


export function testEmbeddingConnection(
  payload: TestEmbeddingConnectionRequest,
  signal?: AbortSignal,
): Promise<EmbeddingConnectionTestResult> {
  return request(
    "/embedding-config/test",
    parseEmbeddingConnectionTestResult,
    "测试向量模型连接失败",
    jsonInit("POST", payload, signal),
  );
}


export function saveEmbeddingCandidate(
  payload: SaveEmbeddingCandidateRequest,
  signal?: AbortSignal,
): Promise<EmbeddingConfigResource> {
  return request(
    "/embedding-config/candidate",
    parseEmbeddingConfigResource,
    "保存候选配置失败",
    jsonInit("PUT", payload, signal),
  );
}


async function configAction(
  path: string,
  fallback: string,
  signal?: AbortSignal,
  needsVersion = false,
) {
  try {
    const current = needsVersion ? await getEmbeddingConfig(signal) : null;
    await apiRequest<unknown>(
      path,
      jsonInit("POST", needsVersion ? { expected_version: current?.version } : {}, signal),
    );
    return await getEmbeddingConfig(signal);
  } catch (reason) {
    normalizeError(reason, fallback);
  }
}


export const rebuildEmbeddingCandidate = (signal?: AbortSignal) => configAction(
  "/embedding-config/candidate/rebuild",
  "启动候选索引构建失败",
  signal,
);


export const cancelEmbeddingCandidate = (signal?: AbortSignal) => configAction(
  "/embedding-config/candidate/cancel",
  "取消候选索引构建失败",
  signal,
);


export const activateEmbeddingCandidate = (signal?: AbortSignal) => configAction(
  "/embedding-config/candidate/activate",
  "激活候选索引失败",
  signal,
  true,
);


export const evaluateEmbeddingCandidate = (signal?: AbortSignal) => configAction(
  "/embedding-config/candidate/evaluate",
  "运行候选检索评测失败",
  signal,
  true,
);


export const rollbackEmbeddingGeneration = (signal?: AbortSignal) => configAction(
  "/embedding-config/rollback",
  "回退上一代索引失败",
  signal,
  true,
);


export function getNovelEmbeddingConsent(
  novelId: string,
  signal?: AbortSignal,
): Promise<NovelEmbeddingConsentResource> {
  return request(
    `/novels/${pathSegment(novelId)}/embedding-consent`,
    parseNovelEmbeddingConsentResource,
    "加载小说向量授权失败",
    { signal },
  );
}


export function putNovelEmbeddingConsent(
  novelId: string,
  payload: PutNovelEmbeddingConsentRequest,
  signal?: AbortSignal,
): Promise<NovelEmbeddingConsentResource> {
  return request(
    `/novels/${pathSegment(novelId)}/embedding-consent`,
    parseNovelEmbeddingConsentResource,
    payload.action === "grant" ? "保存小说向量授权失败" : "撤销小说向量授权失败",
    jsonInit("PUT", payload, signal),
  );
}


export function getNovelSemanticIndexStatus(
  novelId: string,
  signal?: AbortSignal,
): Promise<NovelSemanticIndexStatus> {
  return request(
    `/novels/${pathSegment(novelId)}/semantic-index/status`,
    parseNovelSemanticIndexStatus,
    "加载小说语义索引状态失败",
    { signal },
  );
}


function novelIndexAction(
  novelId: string,
  action: "rebuild" | "cancel" | "retry-failed",
  fallback: string,
  signal?: AbortSignal,
): Promise<NovelSemanticIndexStatus> {
  return request(
    `/novels/${pathSegment(novelId)}/semantic-index/${action}`,
    parseNovelSemanticIndexStatus,
    fallback,
    jsonInit("POST", {}, signal),
  );
}


export const rebuildNovelSemanticIndex = (novelId: string, signal?: AbortSignal) => (
  novelIndexAction(novelId, "rebuild", "重建小说语义索引失败", signal)
);


export const cancelNovelSemanticIndex = (novelId: string, signal?: AbortSignal) => (
  novelIndexAction(novelId, "cancel", "取消小说语义索引构建失败", signal)
);


export const retryFailedNovelSemanticIndex = (novelId: string, signal?: AbortSignal) => (
  novelIndexAction(novelId, "retry-failed", "重试失败索引批次失败", signal)
);


export async function clearNovelSemanticIndex(
  novelId: string,
  signal?: AbortSignal,
): Promise<NovelSemanticIndexStatus> {
  return request(
    `/novels/${pathSegment(novelId)}/semantic-index`,
    parseNovelSemanticIndexStatus,
    "清理小说本地派生向量失败",
    { method: "DELETE", signal },
  );
}
