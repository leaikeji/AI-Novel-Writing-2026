import type {
  JsonValue,
  StoryLedgerFactEffectiveState,
  StoryLedgerFactHealth,
  StoryLedgerFilters,
} from "./contracts";

export const FACT_EFFECTIVE_STATE_LABELS: Readonly<
  Record<StoryLedgerFactEffectiveState, string>
> = {
  current: "当前值",
  historical: "历史变化",
  superseded: "已被替代",
  source_invalid: "来源失效",
  batch_reverted: "已撤销同步",
};

export const FACT_HEALTH_LABELS: Readonly<Record<StoryLedgerFactHealth, string>> = {
  ok: "正常",
  conflict: "冲突",
  ambiguous: "不确定",
};

export const FACT_EFFECTIVE_REASON_LABELS: Readonly<Record<string, string>> = {
  active_and_selected: "当前投影已采用",
  active_not_selected: "当前投影未采用",
  after_narrative_cutoff: "晚于当前叙事位置",
  incoming_supersedes: "已有替代事实",
  source_binding_invalid: "来源绑定已失效",
  source_revision_mismatch: "来源版本不匹配",
  commit_batch_reverted: "所属同步批次已撤销",
  lifecycle_inactive: "事实生命周期已结束",
};

export const FACT_HEALTH_REASON_LABELS: Readonly<Record<string, string>> = {
  same_slot_conflict: "同一状态槽存在多个候选值",
  projection_ambiguous: "无法确定唯一投影",
  reference_missing: "关联对象已不存在",
};

export interface StoryLedgerFactStateItem {
  readonly id: string;
  readonly dimension: string | null;
  readonly effective_state: StoryLedgerFactEffectiveState;
  readonly health: StoryLedgerFactHealth;
  readonly source_document_id?: string | null;
  readonly source?: { readonly source_document_id: string | null } | null;
}

export interface StoryLedgerFactFilters {
  readonly effectiveState: StoryLedgerFactEffectiveState | "all";
  readonly health: StoryLedgerFactHealth | "all";
  readonly dimension?: string | null;
  readonly sourceDocumentId?: string | null;
}

export interface StoryLedgerRiskSummary {
  readonly actionableCount: number;
  readonly conflictCount: number;
  readonly ambiguousCount: number;
  readonly invalidSourceCount: number;
}

function sourceDocumentId(fact: StoryLedgerFactStateItem): string | null {
  return fact.source_document_id ?? fact.source?.source_document_id ?? null;
}

export function matchesStoryLedgerFactFilters(
  fact: StoryLedgerFactStateItem,
  filters: StoryLedgerFactFilters,
): boolean {
  return (
    (filters.effectiveState === "all" || fact.effective_state === filters.effectiveState)
    && (filters.health === "all" || fact.health === filters.health)
    && (!filters.dimension || fact.dimension === filters.dimension)
    && (!filters.sourceDocumentId || sourceDocumentId(fact) === filters.sourceDocumentId)
  );
}

export function filterStoryLedgerFacts<T extends StoryLedgerFactStateItem>(
  facts: readonly T[],
  filters: StoryLedgerFactFilters,
): readonly T[] {
  return facts.filter((fact) => matchesStoryLedgerFactFilters(fact, filters));
}

export function summarizeStoryLedgerRisks(
  facts: readonly StoryLedgerFactStateItem[],
): StoryLedgerRiskSummary {
  const actionableIds = new Set<string>();
  const conflictIds = new Set<string>();
  const ambiguousIds = new Set<string>();
  const invalidSourceIds = new Set<string>();
  for (const fact of facts) {
    if (fact.health === "conflict") conflictIds.add(fact.id);
    if (fact.health === "ambiguous") ambiguousIds.add(fact.id);
    if (fact.effective_state === "source_invalid") invalidSourceIds.add(fact.id);
    if (
      fact.health === "conflict"
      || fact.health === "ambiguous"
      || fact.effective_state === "source_invalid"
    ) actionableIds.add(fact.id);
  }
  return {
    actionableCount: actionableIds.size,
    conflictCount: conflictIds.size,
    ambiguousCount: ambiguousIds.size,
    invalidSourceCount: invalidSourceIds.size,
  };
}

export interface StoryLedgerFactCorrectionTarget {
  readonly id: string;
  readonly fact_type: string;
  readonly timeline_id: string | null;
  readonly character_id?: string | null;
  readonly character_instance_id?: string | null;
  readonly relationship_id?: string | null;
  readonly dimension: string | null;
  readonly event_kind: string | null;
  readonly predicate: string;
  readonly object_text: string;
  readonly details: Readonly<Record<string, JsonValue>>;
}

export interface StoryLedgerFactCorrectionDraft extends StoryLedgerFactCorrectionTarget {
  readonly target_fact_id: string;
  readonly reason: string;
}

export function createStoryLedgerFactCorrectionDraft(
  target: StoryLedgerFactCorrectionTarget,
): StoryLedgerFactCorrectionDraft {
  return {
    ...target,
    details: cloneJsonValue(target.details) as Readonly<Record<string, JsonValue>>,
    target_fact_id: target.id,
    reason: "",
  };
}

export function updateStoryLedgerFactCorrectionDraft(
  draft: StoryLedgerFactCorrectionDraft,
  patch: Readonly<{
    object_text?: string;
    details?: Readonly<Record<string, JsonValue>>;
    reason?: string;
  }>,
): StoryLedgerFactCorrectionDraft {
  return {
    ...draft,
    ...(patch.object_text === undefined ? {} : { object_text: patch.object_text }),
    ...(patch.details === undefined
      ? {}
      : { details: cloneJsonValue(patch.details) as Readonly<Record<string, JsonValue>> }),
    ...(patch.reason === undefined ? {} : { reason: patch.reason }),
  };
}

export function storyLedgerFactCorrectionErrors(
  draft: StoryLedgerFactCorrectionDraft,
): Readonly<Record<string, string>> {
  const errors: Record<string, string> = {};
  if (!draft.object_text.trim()) errors.object_text = "请填写替代事实";
  if (!draft.reason.trim()) errors.reason = "请说明修正理由";
  if (draft.reason.length > 1_000) errors.reason = "修正理由不能超过 1000 个字符";
  return errors;
}

export type StoryLedgerOperationKind = "correction" | "batch-revert";

export interface StoryLedgerOperationAttempt {
  readonly kind: StoryLedgerOperationKind;
  readonly targetId: string;
  readonly payloadIdentity: string;
  readonly operationKey: string;
}

export type StoryLedgerOperationKeyFactory = (
  kind: StoryLedgerOperationKind,
  targetId: string,
) => string;

/**
 * Return the existing attempt for an exact retry. Editing any semantic payload
 * field deliberately creates a new operation key, so retries and new intents
 * cannot be confused by the backend idempotency guard.
 */
export function prepareStoryLedgerOperationAttempt(
  previous: StoryLedgerOperationAttempt | null,
  kind: StoryLedgerOperationKind,
  targetId: string,
  payload: JsonValue,
  keyFactory: StoryLedgerOperationKeyFactory = createStoryLedgerOperationKey,
): StoryLedgerOperationAttempt {
  const payloadIdentity = canonicalJson(payload);
  if (
    previous?.kind === kind
    && previous.targetId === targetId
    && previous.payloadIdentity === payloadIdentity
  ) return previous;
  const operationKey = keyFactory(kind, targetId);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(operationKey)) {
    throw new Error("story ledger operation key must contain 1-120 safe ASCII characters");
  }
  return { kind, targetId, payloadIdentity, operationKey };
}

export function createStoryLedgerOperationKey(
  kind: StoryLedgerOperationKind,
  _targetId: string,
): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `story-ledger-${kind}:${random}`;
}

export function storyLedgerFilterIdentity(filters: StoryLedgerFilters): string {
  return canonicalJson({
    commitBatchId: filters.commitBatchId ?? null,
    dimension: filters.dimension ?? null,
    effectiveState: filters.effectiveState ?? null,
    entityId: filters.entityId ?? null,
    entityType: filters.entityType ?? null,
    factTimelineId: filters.factTimelineId ?? null,
    factTypes: [...(filters.factTypes ?? [])].filter(Boolean).sort(),
    health: filters.health ?? null,
    reviewOnly: filters.reviewOnly === true,
    sourceDocumentId: filters.sourceDocumentId ?? null,
  });
}

export interface StoryLedgerRequestLease {
  readonly channel: string;
  readonly identity: string;
  readonly generation: number;
  readonly scopeGeneration: number;
  readonly signal: AbortSignal;
  isCurrent(): boolean;
}

interface ActiveRequest {
  readonly identity: string;
  readonly generation: number;
  readonly scopeGeneration: number;
  readonly controller: AbortController;
}

/** Isolate late page, source, preview and mutation completions by named channel. */
export class StoryLedgerRequestFence {
  private readonly active = new Map<string, ActiveRequest>();
  private readonly generations = new Map<string, number>();
  private scopeIdentity = "";
  private scopeGeneration = 0;

  setScope(identity: string): void {
    if (identity === this.scopeIdentity) return;
    this.scopeIdentity = identity;
    this.scopeGeneration += 1;
    this.abortAll();
  }

  begin(channel: string, identity: string): StoryLedgerRequestLease {
    this.invalidate(channel);
    const generation = (this.generations.get(channel) ?? 0) + 1;
    this.generations.set(channel, generation);
    const controller = new AbortController();
    const request: ActiveRequest = {
      identity,
      generation,
      scopeGeneration: this.scopeGeneration,
      controller,
    };
    this.active.set(channel, request);
    return {
      channel,
      identity,
      generation,
      scopeGeneration: request.scopeGeneration,
      signal: controller.signal,
      isCurrent: () => this.isCurrent(channel, request),
    };
  }

  invalidate(channel: string): void {
    this.active.get(channel)?.controller.abort();
    this.active.delete(channel);
  }

  invalidateMany(channels: readonly string[]): void {
    for (const channel of channels) this.invalidate(channel);
  }

  dispose(): void {
    this.abortAll();
    this.scopeGeneration += 1;
  }

  private abortAll(): void {
    for (const request of this.active.values()) request.controller.abort();
    this.active.clear();
  }

  private isCurrent(channel: string, request: ActiveRequest): boolean {
    const current = this.active.get(channel);
    return current === request
      && !request.controller.signal.aborted
      && request.scopeGeneration === this.scopeGeneration;
  }
}

export function isAbortLike(reason: unknown): boolean {
  return reason instanceof DOMException
    ? reason.name === "AbortError"
    : reason instanceof Error && reason.name === "AbortError";
}

function canonicalJson(value: JsonValue): string {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Readonly<Record<string, JsonValue>>;
    return `{${Object.keys(record).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(record[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value);
}

function cloneJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map((item) => cloneJsonValue(item));
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, cloneJsonValue(item)]),
    );
  }
  return value;
}
