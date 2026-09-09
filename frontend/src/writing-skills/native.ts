import { ApiError, apiRequest } from "../api";
import type { QwenPawReactRuntime } from "../assistant-pane";
import {
  canAdvanceWritingMethodStatus,
  parseWritingMethodStatus,
  type WritingMethodStatus,
} from "./contracts";
import { createWritingMethodReceiptNotice } from "./status";


interface NativeWritingActionIdentity {
  readonly actionId: string;
  readonly sessionId: string;
  readonly tabInstance: string;
}

export type NativeWritingActionBinding = NativeWritingActionIdentity & ({
  readonly scopeKind?: "novel";
  readonly scopeId?: never;
  readonly creationDraftId?: never;
  readonly novelId: string;
  readonly documentId?: string;
} | {
  readonly scopeKind: "creation_draft";
  readonly scopeId: string;
  readonly creationDraftId: string;
  readonly novelId?: never;
  readonly documentId?: never;
});


export interface NativeWritingMethodSnapshot {
  readonly binding: NativeWritingActionBinding | null;
  readonly status: WritingMethodStatus | null;
  readonly checking: boolean;
  readonly error: "status_unavailable" | "invalid_status" | null;
}


export interface NativeWritingMethodTransport {
  read(
    binding: NativeWritingActionBinding,
    signal: AbortSignal,
  ): Promise<unknown | null>;
}


export interface NativeWritingMethodRuntime {
  bind(binding: NativeWritingActionBinding): void;
  clear(): void;
  getSnapshot(): NativeWritingMethodSnapshot;
  subscribe(listener: (snapshot: NativeWritingMethodSnapshot) => void): () => void;
  dispose(): void;
}


export interface NativeWritingMethodStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}


const DEFAULT_DELAYS_MS = Object.freeze([
  0, 120, 300, 700, 1_500, 3_000, 5_000, 8_000, 13_000, 21_000, 30_000,
]);
const TERMINAL_STATES = new Set(["dispatched", "failed", "cancelled", "unknown", "stale"]);


function sameBinding(
  left: NativeWritingActionBinding,
  right: NativeWritingActionBinding,
): boolean {
  return left.actionId === right.actionId
    && left.sessionId === right.sessionId
    && left.scopeKind === right.scopeKind
    && left.scopeId === right.scopeId
    && left.creationDraftId === right.creationDraftId
    && left.novelId === right.novelId
    && left.documentId === right.documentId
    && left.tabInstance === right.tabInstance;
}


function defaultTimer(callback: () => void, delayMs: number): ReturnType<typeof setTimeout> {
  return setTimeout(callback, delayMs);
}


/**
 * Read-only observer for a single native send. A 404 means the current message
 * was not claimed as a writing task yet (or is ordinary chat), so the UI stays
 * silent. It never creates, retries or dispatches generation.
 */
export function createNativeWritingMethodRuntime(options: {
  transport: NativeWritingMethodTransport;
  delaysMs?: readonly number[];
  setTimer?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  clearTimer?: (timer: ReturnType<typeof setTimeout>) => void;
  storage?: NativeWritingMethodStorage | null;
  storageKey?: string;
  expectedTabInstance?: string;
}): NativeWritingMethodRuntime {
  const delays = options.delaysMs ?? DEFAULT_DELAYS_MS;
  const setTimer = options.setTimer ?? defaultTimer;
  const clearTimer = options.clearTimer ?? clearTimeout;
  const storage = options.storage === undefined
    ? (typeof sessionStorage === "undefined" ? null : sessionStorage)
    : options.storage;
  const storageKey = options.storageKey ?? "anw.native-writing-method.last-action.v1";
  const listeners = new Set<(snapshot: NativeWritingMethodSnapshot) => void>();
  const restore = (): NativeWritingActionBinding | null => {
    try {
      const raw = storage?.getItem(storageKey);
      if (!raw) return null;
      const value = JSON.parse(raw) as Partial<NativeWritingActionBinding>;
      if (typeof value.actionId !== "string"
        || !/^[0-9a-f-]{36}$/i.test(value.actionId)
        || typeof value.sessionId !== "string" || !value.sessionId || value.sessionId.length > 240
        || typeof value.tabInstance !== "string" || !value.tabInstance || value.tabInstance.length > 160
        || (options.expectedTabInstance !== undefined
          && value.tabInstance !== options.expectedTabInstance)) {
        storage?.removeItem(storageKey);
        return null;
      }
      const identity = {
        actionId: value.actionId,
        sessionId: value.sessionId,
        tabInstance: value.tabInstance,
      };
      if (value.scopeKind === "creation_draft") {
        if (typeof value.scopeId !== "string" || !/^[0-9a-f-]{36}$/i.test(value.scopeId)
          || value.creationDraftId !== value.scopeId
          || value.novelId !== undefined || value.documentId !== undefined) {
          storage?.removeItem(storageKey);
          return null;
        }
        return Object.freeze({ ...identity, scopeKind: "creation_draft", scopeId: value.scopeId, creationDraftId: value.scopeId });
      }
      if ((value.scopeKind !== undefined && value.scopeKind !== "novel")
        || typeof value.novelId !== "string" || !/^[0-9a-f-]{36}$/i.test(value.novelId)
        || value.scopeId !== undefined || value.creationDraftId !== undefined
        || (value.documentId !== undefined
          && (typeof value.documentId !== "string" || !/^[0-9a-f-]{36}$/i.test(value.documentId)))) {
        storage?.removeItem(storageKey);
        return null;
      }
      return Object.freeze({ ...identity,
        ...(value.scopeKind ? { scopeKind: value.scopeKind } : {}),
        novelId: value.novelId,
        ...(value.documentId ? { documentId: value.documentId } : {}),
      });
    } catch {
      try { storage?.removeItem(storageKey); } catch { /* storage is best-effort UI recovery only */ }
      return null;
    }
  };
  const restored = restore();
  let snapshot: NativeWritingMethodSnapshot = Object.freeze({
    binding: restored,
    status: null,
    checking: restored !== null,
    error: null,
  });
  let abort: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let generation = 0;
  let disposed = false;

  const update = (patch: Partial<NativeWritingMethodSnapshot>) => {
    snapshot = Object.freeze({ ...snapshot, ...patch });
    for (const listener of listeners) listener(snapshot);
  };
  const cancel = () => {
    generation += 1;
    abort?.abort();
    abort = null;
    if (timer !== null) clearTimer(timer);
    timer = null;
  };
  const schedule = (binding: NativeWritingActionBinding, attempt: number, token: number) => {
    if (disposed || token !== generation || attempt >= delays.length) {
      if (token === generation) update({ checking: false });
      return;
    }
    timer = setTimer(() => {
      timer = null;
      void read(binding, attempt, token);
    }, Math.max(0, delays[attempt] ?? 0));
  };
  const read = async (binding: NativeWritingActionBinding, attempt: number, token: number) => {
    if (disposed || token !== generation) return;
    const controller = new AbortController();
    abort = controller;
    try {
      const raw = await options.transport.read(binding, controller.signal);
      if (disposed || controller.signal.aborted || token !== generation) return;
      if (raw === null) {
        // Native middleware claims an eligible action before model/catalog
        // preparation. A few early misses cover the request race; continuing
        // to poll an ordinary chat message would create misleading activity.
        if (snapshot.status === null && attempt >= 3) {
          try { storage?.removeItem(storageKey); } catch { /* best-effort */ }
          update({ checking: false });
        }
        else schedule(binding, attempt + 1, token);
        return;
      }
      const status = parseWritingMethodStatus(raw);
      if (!status || status.action_id !== binding.actionId) {
        update({ checking: false, error: "invalid_status" });
        return;
      }
      const previous = snapshot.status;
      if (previous && previous.dispatch_id !== status.dispatch_id) {
        update({ checking: false, error: "invalid_status" });
        return;
      }
      if (previous && !canAdvanceWritingMethodStatus(previous, status)) {
        schedule(binding, attempt + 1, token);
        return;
      }
      update({ status, error: null });
      try {
        storage?.setItem(storageKey, JSON.stringify(binding));
      } catch {
        // The server record remains authoritative when browser storage is full
        // or unavailable; only refresh recovery is omitted.
      }
      if (TERMINAL_STATES.has(status.state)) update({ checking: false });
      else schedule(binding, attempt + 1, token);
    } catch {
      if (!disposed && !controller.signal.aborted && token === generation) {
        update({ checking: false, error: "status_unavailable" });
      }
    } finally {
      if (abort === controller) abort = null;
    }
  };

  const runtime: NativeWritingMethodRuntime = {
    bind(binding) {
      if (disposed) throw new Error("native_writing_method_runtime_disposed");
      if (snapshot.binding && sameBinding(snapshot.binding, binding)) return;
      cancel();
      try { storage?.removeItem(storageKey); } catch { /* best-effort */ }
      snapshot = Object.freeze({ binding, status: null, checking: true, error: null });
      try {
        storage?.setItem(storageKey, JSON.stringify(binding));
      } catch {
        // A failed browser write cannot weaken the server-side action claim;
        // it only disables refresh recovery for this send.
      }
      for (const listener of listeners) listener(snapshot);
      schedule(binding, 0, generation);
    },
    clear() {
      cancel();
      try { storage?.removeItem(storageKey); } catch { /* best-effort */ }
      update({ binding: null, status: null, checking: false, error: null });
    },
    getSnapshot() { return snapshot; },
    subscribe(listener) {
      if (disposed) return () => undefined;
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      cancel();
      listeners.clear();
      snapshot = Object.freeze({ binding: null, status: null, checking: false, error: null });
    },
  };
  if (restored) schedule(restored, 0, generation);
  return runtime;
}


export function createNativeWritingMethodHttpTransport(
  request: <T>(path: string, init?: RequestInit) => Promise<T> = apiRequest,
): NativeWritingMethodTransport {
  return {
    async read(binding, signal) {
      const query = new URLSearchParams({ tab_id: binding.tabInstance });
      if (binding.documentId) query.set("document_id", binding.documentId);
      const scopePath = binding.scopeKind === "creation_draft"
        ? `/creation-drafts/${encodeURIComponent(binding.creationDraftId)}`
        : `/novels/${encodeURIComponent(binding.novelId)}`;
      try {
        return await request<unknown>(
          `${scopePath}/native-writing-actions/${encodeURIComponent(binding.actionId)}?${query.toString()}`,
          { signal },
        );
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 404) return null;
        throw reason;
      }
    },
  };
}


export function createNativeWritingMethodNotice(
  React: Pick<QwenPawReactRuntime, "createElement" | "useEffect" | "useState">,
): (props: { runtime: NativeWritingMethodRuntime }) => unknown {
  const h = React.createElement;
  const Receipt = createWritingMethodReceiptNotice(React);
  return function NativeWritingMethodNotice({ runtime }): unknown {
    const [snapshot, setSnapshot] = React.useState(() => runtime.getSnapshot());
    React.useEffect(() => runtime.subscribe(setSnapshot), [runtime]);
    // Do not claim that ordinary chat used writing methods while the server has
    // no matching native action. Only a correlated durable record is visible.
    if (!snapshot.status || snapshot.status.action_id !== snapshot.binding?.actionId) return null;
    return h(Receipt, { status: snapshot.status });
  };
}
