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
  | "model_evidence"
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

export function isRetryableChapterLengthFailure(reason: unknown): boolean {
  if (!(reason instanceof ApiError) || reason.status !== 422) return false;
  const detail = objectRecord(reason.detail);
  return detail?.type === "chapter_length_out_of_range"
    && detail.retryable === true
    && (detail.direction === "above_target" || detail.direction === "below_target")
    && (detail.validation_state === "above_target" || detail.validation_state === "below_target");
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


export interface StartCreativeGenerationPayload {
  readonly scope_type: "document" | "novel";
  readonly scope_id: string;
  readonly kind: "selection_edit";
  readonly input_snapshot: Record<string, unknown>;
  readonly novel_id: string;
  readonly document_id: string | null;
  readonly target_character_count: null;
  readonly force_new: boolean;
}


export function startCreativeGeneration(
  payload: StartCreativeGenerationPayload,
  signal?: AbortSignal,
): Promise<CreativeGenerationRecord> {
  return apiRequest<CreativeGenerationRecord>("/creative-generations", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}


export function listSelectionEditGenerations(
  scopeType: "document" | "novel",
  scopeId: string,
  selectionId?: string,
): Promise<CreativeGenerationRecord[]> {
  const query = new URLSearchParams({
    scope_type: scopeType,
    scope_id: scopeId,
    kind: "selection_edit",
  });
  if (selectionId) query.set("selection_id", selectionId);
  return apiRequest<CreativeGenerationRecord[]>(`/creative-generations?${query.toString()}`);
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
  const evidence = objectRecord(value.model_evidence);
  if (evidence?.schema_version === "model-execution-evidence/2") {
    if (evidence.status === "not_exposed") {
      return `宿主未公开实际模型；任务前后有效模型一致（${requested}）`;
    }
    if (evidence.status === "rejected") {
      return `请求 ${requested} · 模型公开证据已拒绝`;
    }
  }
  return actual ? `请求 ${requested} · 实际 ${actual}` : `请求 ${requested} · 实际未核验`;
}

export function verifiedGenerationModelLabel(value: GenerationTaskModelEvidence): string {
  const evidence = objectRecord(value.model_evidence);
  if (evidence?.schema_version === "model-execution-evidence/2"
    && evidence.status === "not_exposed") {
    return generationModelAuditLabel(value);
  }
  const actual = actualGenerationModelLabel(value);
  return actual ? `实际 ${actual}` : generationModelAuditLabel(value);
}
