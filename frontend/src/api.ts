import { APP_ID } from "./contracts";
import type {
  CreativeGenerationRecord,
  GenerationJobRecord,
  GenerationModelStatus,
  IntelligenceProposalRecord,
} from "./types";

export type GenerationTaskModelEvidence = Pick<
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

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object"
    ? value as Record<string, unknown>
    : null;
}

export function generationTaskFromApiError(
  reason: unknown,
): GenerationTaskModelEvidence | null {
  if (!(reason instanceof ApiError)) return null;
  const detail = objectRecord(reason.detail);
  if (!detail) return null;
  for (const key of ["job", "proposal"] as const) {
    const task = objectRecord(detail[key]);
    if (task && typeof task.requested_model_id === "string") {
      return task as unknown as GenerationTaskModelEvidence;
    }
  }
  return null;
}

export function apiErrorMessage(reason: unknown, fallback: string): string {
  if (!(reason instanceof ApiError)) {
    return reason instanceof Error ? reason.message : fallback;
  }
  const detail = objectRecord(reason.detail);
  let message = typeof reason.detail === "string" ? reason.detail.trim() : "";
  if (!message && detail && typeof detail.message === "string") {
    message = detail.message.trim();
  }
  if (!message && detail) {
    for (const key of ["job", "proposal"] as const) {
      const task = objectRecord(detail[key]);
      if (task && typeof task.failure_message === "string" && task.failure_message.trim()) {
        message = task.failure_message.trim();
        break;
      }
    }
  }
  if (!message && detail && typeof detail.type === "string") {
    message = `${fallback}：${detail.type}`;
  }
  const task = generationTaskFromApiError(reason);
  const audit = task ? generationModelAuditLabel(task) : "";
  const base = message || reason.message || fallback;
  return audit && !base.includes(audit) ? `${base}（${audit}）` : base;
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
    const detail = payload?.detail ?? payload;
    const provisional = new ApiError(response.status, `HTTP ${response.status}`, detail);
    throw new ApiError(
      response.status,
      apiErrorMessage(provisional, `HTTP ${response.status}`),
      detail,
    );
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

export function verifiedGenerationModelLabel(value: GenerationTaskModelEvidence): string {
  const actual = actualGenerationModelLabel(value);
  return actual ? `实际 ${actual}` : generationModelAuditLabel(value);
}
