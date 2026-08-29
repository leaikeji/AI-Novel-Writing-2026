import { ApiError, apiErrorMessage, apiRequest } from "../api";
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


function normalizeError(reason: unknown, fallback: string): never {
  if (!(reason instanceof ApiError)) throw reason;
  throw new EmbeddingApiError(
    reason.status,
    reason.detail,
    apiErrorMessage(reason, fallback),
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
