import { ApiError, apiRequest } from "../../api";
import { parseTtsCloudProfilesResource, parseTtsCloudProfileTestResponse } from "./contracts";
import type {
  CreateTtsCloudProfileRequest,
  TestTtsCloudProfileRequest,
  TtsCloudProfilesResource,
  TtsCloudProfileTestResponse,
  TtsCloudProfileVersionRequest,
  UpdateTtsCloudProfileRequest,
} from "./contracts";


export class TtsCloudProfileApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
    message: string,
  ) {
    super(message);
  }
}


const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  tts_cloud_profile_version_conflict: "渠道配置已在其他窗口更新，请重新加载后再试。",
  tts_cloud_profile_not_found: "没有找到该语音渠道，可能已被删除。",
  tts_cloud_profile_name_conflict: "已有同名语音渠道，请更换名称。",
  tts_cloud_profile_active: "请先停用语音渠道，再删除配置。",
  tts_cloud_profile_not_verified: "请先分别验证已配置的模型，再启用该渠道。",
  tts_cloud_profile_credential_required: "请先保存 API Key。",
  tts_cloud_profile_billing_confirmation_required: "请先明确确认本次云端模型测试可能计费。",
  tts_cloud_secret_unavailable: "语音密钥保险箱不可用，请检查部署状态。",
  tts_cloud_provider_url_invalid: "Base URL 无效，请填写安全的 HTTPS 服务地址。",
  tts_cloud_provider_ssrf_blocked: "Base URL 指向了不允许访问的本机、私网或保留地址。",
  tts_cloud_provider_auth_failed: "API Key 验证失败，请检查渠道凭据。",
  tts_cloud_provider_model_unavailable: "所选语音模型当前不可用，请检查模型 ID 和渠道权限。",
  tts_cloud_provider_rate_limited: "语音渠道请求过于频繁，请稍后再试。",
  tts_cloud_provider_protocol_error: "语音渠道返回了无法识别的响应。",
  tts_provider_auth_failed: "API Key 验证失败，请检查渠道凭据。",
  tts_provider_unavailable: "语音渠道当前不可用，请检查地址、模型权限或稍后重试。",
  tts_provider_timeout: "语音渠道响应超时，请稍后重试。",
  tts_provider_rate_limited: "语音渠道请求过于频繁，请稍后再试。",
  tts_provider_response_invalid: "语音渠道返回了无法识别的响应。",
};


function pathSegment(value: string): string {
  return encodeURIComponent(value);
}


function errorCode(detail: unknown): string | null {
  if (detail === null || typeof detail !== "object") return null;
  const code = (detail as Record<string, unknown>).code;
  return typeof code === "string" ? code.toLowerCase() : null;
}


function normalizeError(reason: unknown, fallback: string): never {
  if (!(reason instanceof ApiError)) throw reason;
  const code = errorCode(reason.detail);
  throw new TtsCloudProfileApiError(
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


function jsonInit(
  method: "POST" | "PATCH" | "DELETE",
  payload: object,
  signal?: AbortSignal,
): RequestInit {
  return { method, body: JSON.stringify(payload), signal };
}


export function getTtsCloudProfiles(signal?: AbortSignal): Promise<TtsCloudProfilesResource> {
  return request(
    "/tts-cloud-profiles",
    parseTtsCloudProfilesResource,
    "加载语音模型渠道失败。",
    { signal },
  );
}


export function createTtsCloudProfile(
  payload: CreateTtsCloudProfileRequest,
  signal?: AbortSignal,
): Promise<TtsCloudProfilesResource> {
  return request(
    "/tts-cloud-profiles",
    parseTtsCloudProfilesResource,
    "新增语音渠道失败。",
    jsonInit("POST", payload, signal),
  );
}


export function updateTtsCloudProfile(
  profileId: string,
  payload: UpdateTtsCloudProfileRequest,
  signal?: AbortSignal,
): Promise<TtsCloudProfilesResource> {
  return request(
    `/tts-cloud-profiles/${pathSegment(profileId)}`,
    parseTtsCloudProfilesResource,
    "保存语音渠道失败。",
    jsonInit("PATCH", payload, signal),
  );
}


export function testTtsCloudProfile(
  profileId: string,
  payload: TestTtsCloudProfileRequest,
  signal?: AbortSignal,
): Promise<TtsCloudProfileTestResponse> {
  return request(
    `/tts-cloud-profiles/${pathSegment(profileId)}/test`,
    parseTtsCloudProfileTestResponse,
    "测试语音模型失败。",
    jsonInit("POST", payload, signal),
  );
}


function profileAction(
  profileId: string,
  action: "activate" | "disable",
  payload: TtsCloudProfileVersionRequest,
  signal?: AbortSignal,
): Promise<TtsCloudProfilesResource> {
  return request(
    `/tts-cloud-profiles/${pathSegment(profileId)}/${action}`,
    parseTtsCloudProfilesResource,
    action === "activate" ? "启用语音渠道失败。" : "停用语音渠道失败。",
    jsonInit("POST", payload, signal),
  );
}


export const activateTtsCloudProfile = (
  profileId: string,
  payload: TtsCloudProfileVersionRequest,
  signal?: AbortSignal,
) => profileAction(profileId, "activate", payload, signal);


export const disableTtsCloudProfile = (
  profileId: string,
  payload: TtsCloudProfileVersionRequest,
  signal?: AbortSignal,
) => profileAction(profileId, "disable", payload, signal);


export function deleteTtsCloudProfile(
  profileId: string,
  payload: TtsCloudProfileVersionRequest,
  signal?: AbortSignal,
): Promise<TtsCloudProfilesResource> {
  return request(
    `/tts-cloud-profiles/${pathSegment(profileId)}`,
    parseTtsCloudProfilesResource,
    "删除语音渠道失败。",
    jsonInit("DELETE", payload, signal),
  );
}
