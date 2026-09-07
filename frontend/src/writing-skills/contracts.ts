/** Public, content-free mirror of backend/writing_skills/api.py MethodStatus. */
import { parseMethodDetails, type MethodDetails } from "./details";
export const WRITING_METHOD_STATUS_SCHEMA = "writing-method-status/1" as const;

export const WRITING_METHOD_STATES = [
  "claimed", "routing_started", "route_ready", "assembled", "dispatch_started",
  "dispatched", "failed", "cancelled", "unknown", "stale",
] as const;

export type WritingMethodState = typeof WRITING_METHOD_STATES[number];

export interface WritingMethodStatus {
  readonly schema_version: typeof WRITING_METHOD_STATUS_SCHEMA;
  readonly action_id: string;
  readonly dispatch_id: string;
  readonly state: WritingMethodState;
  readonly selected_ids: readonly string[];
  readonly omitted_ids: readonly string[];
  readonly method_input_hash: string | null;
  readonly semantic_enabled: boolean;
  readonly auxiliary_calls: number;
  readonly job_ref: string | null;
  readonly details?: MethodDetails | null;
}

/** UI correlation only. These values confer no server authorization. */
export interface WritingActionBinding {
  readonly ownerKey: string;
  readonly workspaceKey: string;
  readonly tabId: string;
  readonly agentId: "ai-novel-writer";
  readonly scopeKind: "novel" | "creation_draft";
  readonly scopeId: string;
  readonly documentId?: string;
}

export interface WritingAction {
  readonly action_id: string;
  readonly binding: WritingActionBinding;
  /** Caller-generated fingerprint of this author's input, not model/config state. */
  readonly inputFingerprint: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DIGEST = /^[0-9a-f]{64}$/;
const SKILL_ID = /^[a-z][a-z0-9-]{0,63}$/;

export function isWritingActionId(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

function methodIds(value: unknown): readonly string[] | null {
  if (!Array.isArray(value) || value.length > 256) return null;
  if (!value.every((item): item is string => typeof item === "string" && SKILL_ID.test(item))) {
    return null;
  }
  if (new Set(value).size !== value.length) return null;
  return Object.freeze([...value]);
}

export function parseWritingMethodStatus(value: unknown): WritingMethodStatus | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (data.schema_version !== WRITING_METHOD_STATUS_SCHEMA
    || !isWritingActionId(data.action_id) || !isWritingActionId(data.dispatch_id)
    || !WRITING_METHOD_STATES.includes(data.state as WritingMethodState)) return null;
  const selected = methodIds(data.selected_ids === undefined ? [] : data.selected_ids);
  const omitted = methodIds(data.omitted_ids === undefined ? [] : data.omitted_ids);
  const digest = data.method_input_hash ?? null;
  const semanticEnabled = data.semantic_enabled === undefined ? false : data.semantic_enabled;
  const calls = data.auxiliary_calls === undefined ? 0 : data.auxiliary_calls;
  const job = data.job_ref ?? null;
  if (!selected || !omitted || (digest !== null && (typeof digest !== "string" || !DIGEST.test(digest)))
    || typeof semanticEnabled !== "boolean" || typeof calls !== "number"
    || !Number.isSafeInteger(calls) || calls < 0
    || (job !== null && (typeof job !== "string" || !job || job.length > 240))) return null;
  if (["assembled", "dispatch_started", "dispatched"].includes(data.state as string) && !digest) return null;
  if (["claimed", "routing_started", "route_ready"].includes(data.state as string) && digest) return null;
  if (data.state === "dispatched" && !job) return null;
  const details = data.details == null ? null : parseMethodDetails(data.details);
  if (data.details != null && (!details || !digest)) return null;
  return Object.freeze({
    schema_version: WRITING_METHOD_STATUS_SCHEMA,
    action_id: data.action_id, dispatch_id: data.dispatch_id,
    state: data.state as WritingMethodState, selected_ids: selected, omitted_ids: omitted,
    method_input_hash: digest, semantic_enabled: semanticEnabled, auxiliary_calls: calls, job_ref: job,
    ...(data.details !== undefined ? { details } : {}),
  });
}

export function writingBindingKey(binding: WritingActionBinding): string {
  return JSON.stringify([
    binding.ownerKey, binding.workspaceKey, binding.tabId, binding.agentId,
    binding.scopeKind, binding.scopeId, binding.documentId ?? null,
  ]);
}

export function writingActionKey(action: WritingAction): string {
  return JSON.stringify([writingBindingKey(action.binding), action.action_id]);
}

export function assembledCapabilityIds(status: WritingMethodStatus): readonly string[] {
  if (!status.method_input_hash) return [];
  const omitted = new Set(status.omitted_ids);
  return status.selected_ids.filter((id) => !omitted.has(id));
}

const METHOD_PROGRESS: Partial<Record<WritingMethodState, number>> = {
  claimed: 0, routing_started: 1, route_ready: 2, assembled: 3, dispatch_started: 4, dispatched: 5,
};
const METHOD_TERMINAL: ReadonlySet<WritingMethodState> = new Set([
  "dispatched", "failed", "cancelled", "unknown", "stale",
]);

export function canAdvanceWritingMethodStatus(previous: WritingMethodStatus, next: WritingMethodStatus): boolean {
  return previous.action_id === next.action_id && previous.dispatch_id === next.dispatch_id
    && (!previous.method_input_hash || previous.method_input_hash === next.method_input_hash)
    && (!previous.job_ref || previous.job_ref === next.job_ref)
    && (!previous.details || JSON.stringify(previous.details) === JSON.stringify(next.details))
    && (!METHOD_TERMINAL.has(previous.state) || previous.state === next.state)
    && (METHOD_PROGRESS[next.state] ?? Infinity) >= (METHOD_PROGRESS[previous.state] ?? -1);
}
