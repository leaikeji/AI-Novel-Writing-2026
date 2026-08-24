import { APP_ID } from "./contracts";
import type {
  CreativeGenerationRecord,
  GenerationJobRecord,
  GenerationModelStatus,
  IntelligenceProposalRecord,
} from "./types";

type GenerationTaskModelEvidence = Pick<
  CreativeGenerationRecord | GenerationJobRecord | IntelligenceProposalRecord,
  | "requested_provider_id"
  | "requested_model_id"
  | "actual_provider_id"
  | "actual_model_id"
  | "provider_profile"
>;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await window.QwenPaw.host.fetch(`/${APP_ID}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, `HTTP ${response.status}`, payload?.detail ?? payload);
  }
  return payload as T;
}

export async function getGenerationModelStatus(): Promise<GenerationModelStatus> {
  return apiRequest<GenerationModelStatus>("/generation-model");
}

export function generationModelLabel(
  value: Pick<GenerationModelStatus, "provider_id" | "model_id">,
): string {
  return `${value.provider_id} / ${value.model_id}`;
}

function modelIdentityLabel(providerId: string | null | undefined, modelId: string | null | undefined): string | null {
  const provider = String(providerId || "").trim();
  const model = String(modelId || "").trim();
  if (!model) return null;
  return provider ? `${provider} / ${model}` : model;
}

export function requestedGenerationModelLabel(value: GenerationTaskModelEvidence): string {
  return modelIdentityLabel(value.requested_provider_id, value.requested_model_id) || "请求模型未记录";
}

export function actualGenerationModelLabel(value: GenerationTaskModelEvidence): string | null {
  return modelIdentityLabel(value.actual_provider_id || value.provider_profile, value.actual_model_id);
}

/**
 * Label a completed task from that task's immutable audit evidence.  Never
 * accept the current effective model here: doing so would relabel history
 * after an Agent model switch.
 */
export function completedGenerationModelLabel(value: GenerationTaskModelEvidence): string {
  return actualGenerationModelLabel(value) || requestedGenerationModelLabel(value);
}

export function generationModelAuditLabel(value: GenerationTaskModelEvidence): string {
  const requested = requestedGenerationModelLabel(value);
  const actual = actualGenerationModelLabel(value);
  return actual ? `请求 ${requested} · 实际 ${actual}` : `请求 ${requested} · 实际未核验`;
}
