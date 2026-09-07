import {
  isWritingActionId, parseWritingMethodStatus, writingActionKey, writingBindingKey, canAdvanceWritingMethodStatus,
  type WritingAction, type WritingActionBinding, type WritingMethodStatus,
} from "./contracts";

/** No fetch default: HTTP registration and scope authorization belong to entry integration. */
export interface WritingMethodStatusTransport {
  readStatus(input: {
    readonly action_id: string;
    readonly dispatch_id: string;
  }, signal: AbortSignal): Promise<unknown>;
}

function randomActionId(): string {
  if (typeof globalThis.crypto?.randomUUID !== "function") {
    throw new Error("crypto.randomUUID is required for writing actions");
  }
  return globalThis.crypto.randomUUID();
}

/** A deliberate new author submission calls this even when its words are unchanged. */
export function createWritingAction(
  binding: WritingActionBinding, inputFingerprint: string, createId: () => string = randomActionId,
): WritingAction {
  if (!inputFingerprint || inputFingerprint.length > 256
    || binding.agentId !== "ai-novel-writer"
    || !["novel", "creation_draft"].includes(binding.scopeKind)
    || [binding.ownerKey, binding.workspaceKey, binding.tabId, binding.scopeId]
      .some((item) => !item || item.length > 512)) throw new Error("invalid_writing_action_input");
  const id = createId();
  if (!isWritingActionId(id)) throw new Error("invalid_writing_action_id");
  return Object.freeze({ action_id: id, binding: Object.freeze({ ...binding }), inputFingerprint });
}

/** Retain the ticket for duplicate callbacks/transport retries of the same action.
 * Changed author input or scope starts a different action. Server model/catalog
 * versions must NOT form this fingerprint. It never sends or retries generation.
 */
export function writingActionForInput(
  previous: WritingAction | null, binding: WritingActionBinding, inputFingerprint: string,
  createId: () => string = randomActionId,
): WritingAction {
  if (previous && previous.inputFingerprint === inputFingerprint
    && writingBindingKey(previous.binding) === writingBindingKey(binding)) return previous;
  return createWritingAction(binding, inputFingerprint, createId);
}

export interface WritingMethodSnapshot {
  readonly action: WritingAction | null;
  readonly status: WritingMethodStatus | null;
  readonly connected: boolean;
  readonly loading: boolean;
  readonly error: "transport_unavailable" | "status_unavailable" | "invalid_status" | null;
}

/** One controller per mounted owner/tab/scope status area; read-only, no timers. */
export class WritingMethodStatusController {
  private snapshot: WritingMethodSnapshot;
  private pending: AbortController | null = null;
  private sequence = 0;
  private disposed = false;

  constructor(
    private readonly transport?: WritingMethodStatusTransport,
    private readonly onChange: (snapshot: WritingMethodSnapshot) => void = () => undefined,
  ) {
    this.snapshot = Object.freeze({ action: null, status: null, connected: !!transport, loading: false, error: null });
  }

  getSnapshot(): WritingMethodSnapshot { return this.snapshot; }

  activate(action: WritingAction): void {
    if (this.disposed) throw new Error("writing_method_controller_disposed");
    if (this.snapshot.action && writingActionKey(this.snapshot.action) === writingActionKey(action)) {
      if (this.snapshot.action.inputFingerprint !== action.inputFingerprint) throw new Error("action_input_conflict");
      return;
    }
    this.invalidatePending();
    this.update({ action, status: null, loading: false, error: null });
  }

  clear(): void {
    this.invalidatePending();
    this.update({ action: null, status: null, loading: false, error: null });
  }

  /** Exactly one caller-requested status read; never reissues a writing request. */
  async refresh(dispatchId: string): Promise<WritingMethodStatus | null> {
    const action = this.snapshot.action;
    if (this.disposed || !action) return null;
    if (!this.transport) {
      this.update({ error: "transport_unavailable" });
      return null;
    }
    if (!isWritingActionId(dispatchId)
      || (this.snapshot.status && this.snapshot.status.dispatch_id !== dispatchId)) {
      this.update({ error: "invalid_status" });
      return null;
    }
    this.invalidatePending();
    const sequence = this.sequence;
    const abort = new AbortController();
    this.pending = abort;
    this.update({ loading: true, error: null });
    const current = () => !this.disposed && !abort.signal.aborted && sequence === this.sequence
      && this.snapshot.action !== null && writingActionKey(this.snapshot.action) === writingActionKey(action);
    try {
      const raw = await this.transport.readStatus({ action_id: action.action_id, dispatch_id: dispatchId }, abort.signal);
      if (!current()) return null;
      const status = parseWritingMethodStatus(raw);
      if (!status || status.action_id !== action.action_id || status.dispatch_id !== dispatchId) {
        this.update({ loading: false, error: "invalid_status" });
        return null;
      }
      const previous = this.snapshot.status;
      if (previous && !canAdvanceWritingMethodStatus(previous, status)) {
        this.update({ loading: false });
        return null;
      }
      this.update({ status, loading: false, error: null });
      return status;
    } catch {
      if (current()) this.update({ loading: false, error: "status_unavailable" });
      return null;
    } finally {
      if (sequence === this.sequence) this.pending = null;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.invalidatePending();
    this.snapshot = Object.freeze({ ...this.snapshot, action: null, status: null, loading: false });
  }

  private invalidatePending(): void {
    this.sequence += 1;
    this.pending?.abort();
    this.pending = null;
  }

  private update(patch: Partial<WritingMethodSnapshot>): void {
    this.snapshot = Object.freeze({ ...this.snapshot, ...patch });
    this.onChange(this.snapshot);
  }
}
