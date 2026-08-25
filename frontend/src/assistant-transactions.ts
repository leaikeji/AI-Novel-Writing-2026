import type {
  AIApplyMeta,
  EditableFieldAdapter,
  EditableFieldPersistence,
  SelectionRange,
  SelectionSnapshot,
} from "./assistant-fields";


export type AIEditOperation = "replace-selection" | "insert-after-selection" | "undo";
export type AIEditPersistenceStatus = "autosave-requested" | "dirty-explicit-save";


export interface AIEditTransaction {
  transactionId: string;
  agentId: string;
  sessionId?: string;
  selectionId?: string;
  novelId: string;
  documentId?: string;
  fieldId: string;
  beforeValue: string;
  afterValue: string;
  beforeSelection: SelectionRange | null;
  afterSelection: SelectionRange | null;
  sourceValueSha256: string;
  appliedAt: string;
  persistence: EditableFieldPersistence;
  persistenceStatus: AIEditPersistenceStatus;
  operation: Exclude<AIEditOperation, "undo">;
}


export interface ApplyAIEditInput {
  adapter: EditableFieldAdapter;
  operation: Exclude<AIEditOperation, "undo">;
  nextValue: string;
  sourceValueSha256: string;
  agentId: string;
  sessionId?: string;
  selectionId?: string;
  novelId: string;
  documentId?: string;
  afterSelection?: SelectionRange | null;
}


export interface AIEditTransactionManagerOptions {
  now?: () => number;
  uuid?: () => string;
  sha256?: (value: string) => Promise<string>;
}


export type AIEditTransactionResult =
  | {
    ok: true;
    transaction: AIEditTransaction;
    persistenceWarning: boolean;
  }
  | { ok: false; reason: "source-conflict" | "concurrent-change" | "apply-mismatch" };


export type AIEditUndoResult =
  | {
    ok: true;
    transaction: AIEditTransaction;
    persistenceWarning: boolean;
  }
  | { ok: false; reason: "nothing-to-undo" | "field-changed" | "undo-mismatch" };


function defaultUuid(): string {
  return globalThis.crypto.randomUUID();
}


async function defaultSha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


function selectionRange(selection: SelectionSnapshot | null): SelectionRange | null {
  if (!selection) return null;
  return {
    startUtf16: selection.startUtf16,
    endUtf16: selection.endUtf16,
    direction: selection.direction,
  };
}


function persistenceStatus(
  persistence: EditableFieldPersistence,
): AIEditPersistenceStatus {
  return persistence === "autosave" ? "autosave-requested" : "dirty-explicit-save";
}


/** Build the exact next full-field value for a version-bound proposal. */
export function applySelectionOperation(
  sourceValue: string,
  selection: SelectionRange,
  candidateText: string,
  operation: Exclude<AIEditOperation, "undo">,
): { value: string; selection: SelectionRange } {
  const start = Math.max(0, Math.min(sourceValue.length, selection.startUtf16));
  const end = Math.max(start, Math.min(sourceValue.length, selection.endUtf16));
  const insertionPoint = operation === "insert-after-selection" ? end : start;
  const replacedEnd = operation === "insert-after-selection" ? end : end;
  const value = operation === "insert-after-selection"
    ? `${sourceValue.slice(0, insertionPoint)}${candidateText}${sourceValue.slice(insertionPoint)}`
    : `${sourceValue.slice(0, start)}${candidateText}${sourceValue.slice(replacedEnd)}`;
  const selectedStart = insertionPoint;
  return {
    value,
    selection: {
      startUtf16: selectedStart,
      endUtf16: selectedStart + candidateText.length,
      direction: "forward",
    },
  };
}


/**
 * Keeps the latest AI transaction per field for the mounted page only.
 * Applying and undoing always re-enter the controlled adapter; no DOM value is
 * assigned directly and no persistence button is bypassed.
 */
export class AIEditTransactionManager {
  private readonly latestByField = new Map<string, AIEditTransaction>();
  private readonly now: () => number;
  private readonly uuid: () => string;
  private readonly sha256: (value: string) => Promise<string>;

  constructor(options: AIEditTransactionManagerOptions = {}) {
    this.now = options.now ?? Date.now;
    this.uuid = options.uuid ?? defaultUuid;
    this.sha256 = options.sha256 ?? defaultSha256;
  }

  latest(fieldId: string): AIEditTransaction | undefined {
    const transaction = this.latestByField.get(fieldId);
    return transaction ? { ...transaction } : undefined;
  }

  async apply(input: ApplyAIEditInput): Promise<AIEditTransactionResult> {
    const beforeValue = input.adapter.getValue();
    const actualHash = await this.sha256(beforeValue);
    if (actualHash !== input.sourceValueSha256) {
      return { ok: false, reason: "source-conflict" };
    }
    if (input.adapter.getValue() !== beforeValue) {
      return { ok: false, reason: "concurrent-change" };
    }

    const transactionId = this.uuid();
    const appliedAt = new Date(this.now()).toISOString();
    const beforeSelection = selectionRange(input.adapter.getSelection());
    const meta: AIApplyMeta = {
      transactionId,
      agentId: input.agentId,
      sessionId: input.sessionId,
      selectionId: input.selectionId,
      operation: input.operation,
      sourceValueSha256: input.sourceValueSha256,
      appliedAt,
    };
    let adapterError: unknown;
    try {
      await input.adapter.applyValue(input.nextValue, meta);
    } catch (error) {
      // A body adapter can update its controlled recovery draft before an
      // autosave scheduler reports a failure.  If the requested value is
      // already present, preserve a transaction so the author can undo it;
      // otherwise fail closed as an apply mismatch.
      adapterError = error;
    }
    if (input.adapter.getValue() !== input.nextValue) {
      return { ok: false, reason: "apply-mismatch" };
    }

    if (input.afterSelection && input.adapter.restoreSelection) {
      input.adapter.restoreSelection(input.afterSelection);
    }
    input.adapter.focus();
    const transaction: AIEditTransaction = {
      transactionId,
      agentId: input.agentId,
      sessionId: input.sessionId,
      selectionId: input.selectionId,
      novelId: input.novelId,
      documentId: input.documentId,
      fieldId: input.adapter.id,
      beforeValue,
      afterValue: input.nextValue,
      beforeSelection,
      afterSelection: input.afterSelection ?? null,
      sourceValueSha256: input.sourceValueSha256,
      appliedAt,
      persistence: input.adapter.persistence,
      persistenceStatus: persistenceStatus(input.adapter.persistence),
      operation: input.operation,
    };
    this.latestByField.set(input.adapter.id, transaction);
    return {
      ok: true,
      transaction: { ...transaction },
      persistenceWarning: adapterError !== undefined,
    };
  }

  async undo(adapter: EditableFieldAdapter): Promise<AIEditUndoResult> {
    const transaction = this.latestByField.get(adapter.id);
    if (!transaction) return { ok: false, reason: "nothing-to-undo" };
    const currentValue = adapter.getValue();
    if (currentValue !== transaction.afterValue) {
      return { ok: false, reason: "field-changed" };
    }
    const currentHash = await this.sha256(currentValue);
    if (adapter.getValue() !== currentValue) {
      return { ok: false, reason: "field-changed" };
    }
    let adapterError: unknown;
    try {
      await adapter.applyValue(transaction.beforeValue, {
        transactionId: this.uuid(),
        agentId: transaction.agentId,
        sessionId: transaction.sessionId,
        selectionId: transaction.selectionId,
        operation: "undo",
        sourceValueSha256: currentHash,
        appliedAt: new Date(this.now()).toISOString(),
      });
    } catch (error) {
      adapterError = error;
    }
    if (adapter.getValue() !== transaction.beforeValue) {
      return { ok: false, reason: "undo-mismatch" };
    }
    if (transaction.beforeSelection && adapter.restoreSelection) {
      adapter.restoreSelection(transaction.beforeSelection);
    }
    adapter.focus();
    this.latestByField.delete(adapter.id);
    return {
      ok: true,
      transaction: { ...transaction },
      persistenceWarning: adapterError !== undefined,
    };
  }

  clearField(fieldId: string): void {
    this.latestByField.delete(fieldId);
  }

  clear(): void {
    this.latestByField.clear();
  }
}
