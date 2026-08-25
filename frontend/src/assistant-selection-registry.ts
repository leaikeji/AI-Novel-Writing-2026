import type { EditableFieldSelectionDirection } from "./assistant-fields";
import type { NovelAssistantContextEnvelope } from "./assistant-context-schema";


export const SELECTION_REGISTRY_DEFAULT_TTL_MS = 20 * 60 * 1_000;
export const SELECTION_REGISTRY_DEFAULT_CAPACITY = 50;
export const SELECTION_REGISTRY_MAX_CAPACITY = 50;


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;


type SelectionLocationIdentity = Pick<
  NovelAssistantContextEnvelope,
  "novel" | "page" | "entity" | "document"
>;


/**
 * `documentId` is the frozen registry field name, but non-document editors
 * (character/storyline/settings drafts) still need an equally strong resource
 * binding.  This helper creates one deterministic, namespaced identity for
 * every supported editor without pretending an entity draft is a document.
 */
export function resolveSelectionDocumentId(
  location: SelectionLocationIdentity,
): string {
  if (location.document?.id?.trim()) return location.document.id.trim();
  const entityType = location.entity?.type ?? "novel";
  const entityId = location.entity?.id?.trim();
  if (entityId) return `entity:${entityType}:${entityId}`;
  const view = location.page.modal ?? location.page.view;
  return `draft:${location.novel.id}:${entityType}:${view}`;
}


export interface SelectionRegistryScope {
  agentId: string;
  novelId: string;
  documentId: string;
  fieldId: string;
  contextRevision: number;
}


export interface CreateSelectionInput extends SelectionRegistryScope {
  sessionId?: string;
  fieldValue: string;
  startUtf16: number;
  endUtf16: number;
  direction: EditableFieldSelectionDirection;
}


export interface SelectionRegistryRecord extends SelectionRegistryScope {
  readonly selectionId: string;
  readonly sessionId?: string;
  readonly startUtf16: number;
  readonly endUtf16: number;
  readonly direction: EditableFieldSelectionDirection;
  readonly text: string;
  readonly sourceValueSha256: string;
  readonly createdAtMs: number;
  readonly expiresAtMs: number;
}


export interface SelectionSessionBindingInput extends SelectionRegistryScope {
  selectionId: string;
  sessionId: string;
}


export interface SelectionApplyValidationInput extends SelectionRegistryScope {
  selectionId: string;
  sessionId: string;
  fieldValue: string;
}


export interface SelectionFieldIdentity {
  novelId: string;
  documentId: string;
  fieldId: string;
}


export type SelectionInvalidReason =
  | "not-found"
  | "expired"
  | "agent-mismatch"
  | "novel-mismatch"
  | "document-mismatch"
  | "field-mismatch"
  | "context-revision-mismatch"
  | "session-unbound"
  | "session-mismatch"
  | "source-value-changed";


type SelectionScopeMismatchReason =
  | "agent-mismatch"
  | "novel-mismatch"
  | "document-mismatch"
  | "field-mismatch"
  | "context-revision-mismatch";


export type SelectionSessionBindingResult =
  | {
    ok: true;
    status: "bound" | "already-bound";
    record: SelectionRegistryRecord;
  }
  | {
    ok: false;
    reason: Exclude<SelectionInvalidReason, "session-unbound" | "source-value-changed">;
  };


export type SelectionApplyValidationResult =
  | { ok: true; record: SelectionRegistryRecord }
  | { ok: false; reason: SelectionInvalidReason };


export interface SelectionRegistryOptions {
  ttlMs?: number;
  capacity?: number;
  now?: () => number;
  idProvider?: () => string;
  sha256?: (value: string) => Promise<string>;
}


interface StoredSelection {
  record: SelectionRegistryRecord;
  sequence: number;
}


function requireNonEmpty(value: string, field: string): string {
  if (!value.trim()) {
    throw new Error(`${field} must not be empty`);
  }
  return value;
}


function requireContextRevision(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error("contextRevision must be a non-negative safe integer");
  }
  return value;
}


function requirePositiveInteger(value: number, field: string): number {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${field} must be a positive safe integer`);
  }
  return value;
}


function defaultIdProvider(): string {
  if (typeof globalThis.crypto?.randomUUID !== "function") {
    throw new Error("crypto.randomUUID is required for selection ids");
  }
  return globalThis.crypto.randomUUID();
}


async function defaultSha256(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is required for selections");
  }
  const bytes = new TextEncoder().encode(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


function normalizeSha256(value: string): string {
  if (!SHA256_PATTERN.test(value)) {
    throw new Error("sha256 provider must return a 64-character hexadecimal digest");
  }
  return value.toLowerCase();
}


function freezeRecord(
  record: SelectionRegistryRecord,
): SelectionRegistryRecord {
  return Object.freeze(record);
}


function scopeMismatch(
  record: SelectionRegistryRecord,
  scope: SelectionRegistryScope,
): SelectionScopeMismatchReason | null {
  if (record.agentId !== scope.agentId) return "agent-mismatch";
  if (record.novelId !== scope.novelId) return "novel-mismatch";
  if (record.documentId !== scope.documentId) return "document-mismatch";
  if (record.fieldId !== scope.fieldId) return "field-mismatch";
  if (record.contextRevision !== scope.contextRevision) {
    return "context-revision-mismatch";
  }
  return null;
}


/**
 * 当前标签页内的短生命周期选区注册表。
 *
 * 它不使用 localStorage/IndexedDB，也不保存完整字段值。id 与 SHA-256 的默认
 * provider 都来自 Web Crypto；注入入口只用于可信宿主和确定性测试，不提供弱随机
 * 或弱哈希回退。
 */
export class AssistantSelectionRegistry {
  private readonly entries = new Map<string, StoredSelection>();
  private readonly reservedIds = new Set<string>();
  private readonly ttlMs: number;
  private readonly capacity: number;
  private readonly now: () => number;
  private readonly idProvider: () => string;
  private readonly sha256: (value: string) => Promise<string>;
  private nextSequence = 0;
  private disposed = false;

  constructor(options: SelectionRegistryOptions = {}) {
    this.ttlMs = requirePositiveInteger(
      options.ttlMs ?? SELECTION_REGISTRY_DEFAULT_TTL_MS,
      "ttlMs",
    );
    this.capacity = requirePositiveInteger(
      options.capacity ?? SELECTION_REGISTRY_DEFAULT_CAPACITY,
      "capacity",
    );
    if (this.capacity > SELECTION_REGISTRY_MAX_CAPACITY) {
      throw new Error(
        `capacity must not exceed ${SELECTION_REGISTRY_MAX_CAPACITY}`,
      );
    }
    this.now = options.now ?? Date.now;
    this.idProvider = options.idProvider ?? defaultIdProvider;
    this.sha256 = options.sha256 ?? defaultSha256;
  }

  async create(input: CreateSelectionInput): Promise<SelectionRegistryRecord> {
    this.assertActive();
    this.validateCreateInput(input);
    const createdAtMs = this.readNow();
    this.removeExpiredAt(createdAtMs);
    const selectionId = this.reserveSelectionId();
    const sequence = ++this.nextSequence;

    let sourceValueSha256: string;
    try {
      sourceValueSha256 = normalizeSha256(await this.sha256(input.fieldValue));
    } finally {
      this.reservedIds.delete(selectionId);
    }

    this.assertActive();
    const currentTime = this.readNow();
    if (currentTime >= createdAtMs + this.ttlMs) {
      throw new Error("selection expired before registration completed");
    }

    const record = freezeRecord({
      selectionId,
      agentId: input.agentId,
      sessionId: input.sessionId,
      novelId: input.novelId,
      documentId: input.documentId,
      fieldId: input.fieldId,
      contextRevision: input.contextRevision,
      startUtf16: input.startUtf16,
      endUtf16: input.endUtf16,
      direction: input.direction,
      text: input.fieldValue.slice(input.startUtf16, input.endUtf16),
      sourceValueSha256,
      createdAtMs,
      expiresAtMs: createdAtMs + this.ttlMs,
    });
    this.entries.set(selectionId, { record, sequence });
    this.enforceCapacity();
    return record;
  }

  get(selectionId: string): SelectionRegistryRecord | undefined {
    this.assertActive();
    const stored = this.readLiveEntry(selectionId);
    return stored?.record;
  }

  list(): SelectionRegistryRecord[] {
    this.assertActive();
    this.removeExpiredAt(this.readNow());
    return [...this.entries.values()]
      .sort((left, right) => left.sequence - right.sequence)
      .map(({ record }) => record);
  }

  size(): number {
    this.assertActive();
    this.removeExpiredAt(this.readNow());
    return this.entries.size;
  }

  /**
   * requestPayload 发送阶段调用。整个校验与首次绑定过程同步完成，中间没有 await，
   * 因而同一 JS realm 内不会出现两个会话同时抢占成功。
   */
  bindToSession(
    input: SelectionSessionBindingInput,
  ): SelectionSessionBindingResult {
    this.assertActive();
    requireNonEmpty(input.sessionId, "sessionId");
    const lookup = this.lookupForOperation(input.selectionId);
    if (!lookup.ok) return lookup;

    const mismatch = scopeMismatch(lookup.stored.record, input);
    if (mismatch) return { ok: false, reason: mismatch };

    const currentSessionId = lookup.stored.record.sessionId;
    if (currentSessionId !== undefined) {
      if (currentSessionId !== input.sessionId) {
        return { ok: false, reason: "session-mismatch" };
      }
      return {
        ok: true,
        status: "already-bound",
        record: lookup.stored.record,
      };
    }

    const boundRecord = freezeRecord({
      ...lookup.stored.record,
      sessionId: input.sessionId,
    });
    this.entries.set(input.selectionId, {
      ...lookup.stored,
      record: boundRecord,
    });
    return { ok: true, status: "bound", record: boundRecord };
  }

  /**
   * 工具卡应用前调用。哈希在 registry 之外的当前字段快照上重算；await 后会再次
   * 读取 registry，避免散列期间发生过期、清理或上下文切换却仍返回成功。
   */
  async validateForApply(
    input: SelectionApplyValidationInput,
  ): Promise<SelectionApplyValidationResult> {
    this.assertActive();
    requireNonEmpty(input.sessionId, "sessionId");
    const beforeHash = this.validateBoundOperation(input);
    if (!beforeHash.ok) return beforeHash;

    const currentValueSha256 = normalizeSha256(await this.sha256(input.fieldValue));
    this.assertActive();
    const afterHash = this.validateBoundOperation(input);
    if (!afterHash.ok) return afterHash;
    if (afterHash.record.sourceValueSha256 !== currentValueSha256) {
      return { ok: false, reason: "source-value-changed" };
    }
    return afterHash;
  }

  delete(selectionId: string): boolean {
    this.assertActive();
    return this.entries.delete(selectionId);
  }

  clearExpired(): number {
    this.assertActive();
    return this.removeExpiredAt(this.readNow());
  }

  clearForNovelSwitch(activeNovelId: string): number {
    this.assertActive();
    requireNonEmpty(activeNovelId, "activeNovelId");
    return this.removeWhere((record) => record.novelId !== activeNovelId);
  }

  clearField(identity: SelectionFieldIdentity): number {
    this.assertActive();
    requireNonEmpty(identity.novelId, "novelId");
    requireNonEmpty(identity.documentId, "documentId");
    requireNonEmpty(identity.fieldId, "fieldId");
    return this.removeWhere((record) => (
      record.novelId === identity.novelId
      && record.documentId === identity.documentId
      && record.fieldId === identity.fieldId
    ));
  }

  clear(): void {
    this.assertActive();
    this.entries.clear();
  }

  dispose(): void {
    if (this.disposed) return;
    this.entries.clear();
    this.reservedIds.clear();
    this.disposed = true;
  }

  private assertActive(): void {
    if (this.disposed) {
      throw new Error("Assistant selection registry is disposed");
    }
  }

  private readNow(): number {
    const value = this.now();
    if (!Number.isFinite(value)) {
      throw new Error("now provider must return a finite timestamp");
    }
    return value;
  }

  private validateCreateInput(input: CreateSelectionInput): void {
    requireNonEmpty(input.agentId, "agentId");
    requireNonEmpty(input.novelId, "novelId");
    requireNonEmpty(input.documentId, "documentId");
    requireNonEmpty(input.fieldId, "fieldId");
    requireContextRevision(input.contextRevision);
    if (input.sessionId !== undefined) {
      requireNonEmpty(input.sessionId, "sessionId");
    }
    if (
      !Number.isSafeInteger(input.startUtf16)
      || !Number.isSafeInteger(input.endUtf16)
      || input.startUtf16 < 0
      || input.endUtf16 <= input.startUtf16
      || input.endUtf16 > input.fieldValue.length
    ) {
      throw new Error("selection must be a non-empty valid UTF-16 range");
    }
    if (!(["forward", "backward", "none"] as const).includes(input.direction)) {
      throw new Error("selection direction is invalid");
    }
  }

  private reserveSelectionId(): string {
    const selectionId = this.idProvider();
    if (!UUID_PATTERN.test(selectionId)) {
      throw new Error("selection id provider must return a UUID");
    }
    if (this.entries.has(selectionId) || this.reservedIds.has(selectionId)) {
      throw new Error("selection id provider returned a duplicate UUID");
    }
    this.reservedIds.add(selectionId);
    return selectionId;
  }

  private readLiveEntry(selectionId: string): StoredSelection | undefined {
    const stored = this.entries.get(selectionId);
    if (!stored) return undefined;
    if (this.readNow() >= stored.record.expiresAtMs) {
      this.entries.delete(selectionId);
      return undefined;
    }
    return stored;
  }

  private lookupForOperation(selectionId: string):
    | { ok: true; stored: StoredSelection }
    | { ok: false; reason: "not-found" | "expired" } {
    const stored = this.entries.get(selectionId);
    if (!stored) return { ok: false, reason: "not-found" };
    if (this.readNow() >= stored.record.expiresAtMs) {
      this.entries.delete(selectionId);
      return { ok: false, reason: "expired" };
    }
    return { ok: true, stored };
  }

  private validateBoundOperation(
    input: SelectionApplyValidationInput,
  ): SelectionApplyValidationResult {
    const lookup = this.lookupForOperation(input.selectionId);
    if (!lookup.ok) return lookup;
    const mismatch = scopeMismatch(lookup.stored.record, input);
    if (mismatch) return { ok: false, reason: mismatch };
    if (lookup.stored.record.sessionId === undefined) {
      return { ok: false, reason: "session-unbound" };
    }
    if (lookup.stored.record.sessionId !== input.sessionId) {
      return { ok: false, reason: "session-mismatch" };
    }
    return { ok: true, record: lookup.stored.record };
  }

  private removeExpiredAt(now: number): number {
    return this.removeWhere((record) => now >= record.expiresAtMs);
  }

  private removeWhere(
    predicate: (record: SelectionRegistryRecord) => boolean,
  ): number {
    let removed = 0;
    for (const [selectionId, stored] of this.entries) {
      if (!predicate(stored.record)) continue;
      this.entries.delete(selectionId);
      removed += 1;
    }
    return removed;
  }

  private enforceCapacity(): void {
    while (this.entries.size > this.capacity) {
      let oldest: [string, StoredSelection] | undefined;
      for (const entry of this.entries) {
        if (!oldest || entry[1].sequence < oldest[1].sequence) {
          oldest = entry;
        }
      }
      if (!oldest) return;
      this.entries.delete(oldest[0]);
    }
  }
}
