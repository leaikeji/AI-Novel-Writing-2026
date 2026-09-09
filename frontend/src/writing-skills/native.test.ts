import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import {
  createNativeWritingMethodHttpTransport,
  createNativeWritingMethodRuntime,
  type NativeWritingActionBinding,
} from "./native";

const ACTION_A = "11111111-1111-4111-8111-111111111111";
const ACTION_B = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "22222222-2222-4222-8222-222222222222";
const BINDING: NativeWritingActionBinding = {
  actionId: ACTION_A,
  sessionId: "session-1",
  novelId: "44444444-4444-4444-8444-444444444444",
  documentId: "55555555-5555-4555-8555-555555555555",
  tabInstance: "anw-tab-test",
};
const DRAFT_ID = "66666666-6666-4666-8666-666666666666";
const DRAFT_BINDING: NativeWritingActionBinding = {
  actionId: ACTION_A, sessionId: "session-1", tabInstance: "anw-tab-test",
  scopeKind: "creation_draft", scopeId: DRAFT_ID, creationDraftId: DRAFT_ID,
};

function response(actionId = ACTION_A, state = "dispatched") {
  return {
    schema_version: "writing-method-status/1",
    action_id: actionId,
    dispatch_id: DISPATCH,
    state,
    selected_ids: ["suspense-writing"],
    omitted_ids: [],
    method_input_hash: ["assembled", "dispatch_started", "dispatched"].includes(state)
      ? "a".repeat(64) : null,
    semantic_enabled: false,
    auxiliary_calls: 0,
    job_ref: state === "dispatched" ? `native:${actionId}` : null,
  };
}

describe("native writing method status runtime", () => {
  it("reads a creation receipt through its own scope without sending a novel request", async () => {
    const request = vi.fn(async (_path: string, _init?: RequestInit) => response());
    const signal = new AbortController().signal;
    await createNativeWritingMethodHttpTransport(
      async <T,>(path: string, init?: RequestInit): Promise<T> => await request(path, init) as T,
    ).read(DRAFT_BINDING, signal);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      `/creation-drafts/${DRAFT_ID}/native-writing-actions/${ACTION_A}?tab_id=anw-tab-test`, { signal },
    );
  });

  it("restores a creation receipt in the same tab without inventing a novel identity", async () => {
    vi.useFakeTimers();
    try {
      const values = new Map([["anw.native-writing-method.last-action.v1", JSON.stringify(DRAFT_BINDING)]]);
      const read = vi.fn(async () => response());
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [0],
        storage: { getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); }, removeItem: key => { values.delete(key); } },
        expectedTabInstance: DRAFT_BINDING.tabInstance,
      });
      await vi.runAllTimersAsync();
      expect(read).toHaveBeenCalledOnce();
      expect(runtime.getSnapshot().binding).toEqual(DRAFT_BINDING);
      runtime.dispose();
    } finally { vi.useRealTimers(); }
  });

  it.each([
    { ...DRAFT_BINDING, scopeId: ACTION_B },
    { ...DRAFT_BINDING, novelId: BINDING.novelId },
    { ...DRAFT_BINDING, scopeKind: "unknown" },
    { ...BINDING, creationDraftId: DRAFT_ID },
  ])("drops a mixed, unknown or mismatched stored scope %#", async (binding) => {
    vi.useFakeTimers();
    try {
      const removeItem = vi.fn();
      const read = vi.fn(async () => response());
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [0],
        storage: { getItem: () => JSON.stringify(binding), setItem: vi.fn(), removeItem },
        expectedTabInstance: binding.tabInstance,
      });
      await vi.runAllTimersAsync();
      expect(read).not.toHaveBeenCalled();
      expect(removeItem).toHaveBeenCalledOnce();
      expect(runtime.getSnapshot().binding).toBeNull();
      runtime.dispose();
    } finally { vi.useRealTimers(); }
  });

  it("restores a durable receipt only in the same tab", async () => {
    vi.useFakeTimers();
    try {
      const values = new Map<string, string>([[
        "anw.native-writing-method.last-action.v1",
        JSON.stringify(BINDING),
      ]]);
      const storage = {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => { values.set(key, value); },
        removeItem: (key: string) => { values.delete(key); },
      };
      const read = vi.fn(async () => response());
      const runtime = createNativeWritingMethodRuntime({
        transport: { read },
        delaysMs: [0],
        storage,
        expectedTabInstance: BINDING.tabInstance,
      });
      await vi.runAllTimersAsync();
      expect(read).toHaveBeenCalledOnce();
      expect(runtime.getSnapshot().status?.state).toBe("dispatched");
    } finally { vi.useRealTimers(); }
  });

  it("persists on bind so refresh recovery does not wait for the first GET", async () => {
    vi.useFakeTimers();
    try {
      const values = new Map<string, string>();
      const storage = {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => { values.set(key, value); },
        removeItem: (key: string) => { values.delete(key); },
      };
      const firstRead = vi.fn(() => new Promise<unknown>(() => undefined));
      const first = createNativeWritingMethodRuntime({
        transport: { read: firstRead },
        delaysMs: [0],
        storage,
        expectedTabInstance: BINDING.tabInstance,
      });
      first.bind(BINDING);
      expect(JSON.parse(values.get("anw.native-writing-method.last-action.v1") ?? "null"))
        .toEqual(BINDING);
      first.dispose();

      const recoveredRead = vi.fn(async () => response());
      const recovered = createNativeWritingMethodRuntime({
        transport: { read: recoveredRead },
        delaysMs: [0],
        storage,
        expectedTabInstance: BINDING.tabInstance,
      });
      await vi.runAllTimersAsync();
      expect(recoveredRead).toHaveBeenCalledOnce();
      expect(recovered.getSnapshot().status?.state).toBe("dispatched");
    } finally { vi.useRealTimers(); }
  });

  it("drops a copied receipt after a duplicated tab rotates identity", async () => {
    vi.useFakeTimers();
    try {
      const values = new Map<string, string>([[
        "anw.native-writing-method.last-action.v1",
        JSON.stringify(BINDING),
      ]]);
      const storage = {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => { values.set(key, value); },
        removeItem: (key: string) => { values.delete(key); },
      };
      const read = vi.fn(async () => response());
      const runtime = createNativeWritingMethodRuntime({
        transport: { read },
        delaysMs: [0],
        storage,
        expectedTabInstance: "anw-tab-another",
      });
      await vi.runAllTimersAsync();
      expect(read).not.toHaveBeenCalled();
      expect(runtime.getSnapshot().binding).toBeNull();
      expect(values.size).toBe(0);
    } finally { vi.useRealTimers(); }
  });

  it("stays silent for ordinary chat when no native action is claimed", async () => {
    vi.useFakeTimers();
    try {
      const read = vi.fn(async () => null);
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [0, 10] });
      runtime.bind(BINDING);
      await vi.runAllTimersAsync();
      expect(read).toHaveBeenCalledTimes(2);
      expect(runtime.getSnapshot()).toMatchObject({ status: null, checking: false, error: null });
    } finally { vi.useRealTimers(); }
  });

  it("shows only a correlated durable action and follows it to terminal state", async () => {
    vi.useFakeTimers();
    try {
      const read = vi.fn().mockResolvedValueOnce(null)
        .mockResolvedValueOnce(response(ACTION_A, "dispatch_started"))
        .mockResolvedValueOnce(response());
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [0, 10, 20] });
      runtime.bind(BINDING);
      await vi.runAllTimersAsync();
      expect(runtime.getSnapshot().status?.state).toBe("dispatched");
      expect(runtime.getSnapshot().checking).toBe(false);
      expect(read).toHaveBeenCalledTimes(3);
    } finally { vi.useRealTimers(); }
  });

  it("aborts and hides the prior action when a new send is bound", async () => {
    vi.useFakeTimers();
    try {
      let firstSignal: AbortSignal | undefined;
      const read = vi.fn((binding: NativeWritingActionBinding, signal: AbortSignal) => {
        if (binding.actionId === ACTION_A) {
          firstSignal = signal;
          return new Promise(() => undefined);
        }
        return Promise.resolve(response(ACTION_B));
      });
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [0] });
      runtime.bind(BINDING);
      await vi.advanceTimersByTimeAsync(0);
      runtime.bind({ ...BINDING, actionId: ACTION_B });
      await vi.runAllTimersAsync();
      expect(firstSignal?.aborted).toBe(true);
      expect(runtime.getSnapshot().status?.action_id).toBe(ACTION_B);
    } finally { vi.useRealTimers(); }
  });

  it("rejects a status returned for another action", async () => {
    vi.useFakeTimers();
    try {
      const runtime = createNativeWritingMethodRuntime({
        transport: { read: async () => response(ACTION_B) }, delaysMs: [0],
      });
      runtime.bind(BINDING);
      await vi.runAllTimersAsync();
      expect(runtime.getSnapshot()).toMatchObject({ status: null, error: "invalid_status" });
    } finally { vi.useRealTimers(); }
  });

  it("does not replace terminal evidence with a stale earlier state", async () => {
    vi.useFakeTimers();
    try {
      const read = vi.fn().mockResolvedValueOnce(response())
        .mockResolvedValueOnce(response(ACTION_A, "assembled"));
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [0, 10] });
      runtime.bind(BINDING);
      await vi.runAllTimersAsync();
      expect(read).toHaveBeenCalledTimes(1);
      expect(runtime.getSnapshot().status?.state).toBe("dispatched");
    } finally { vi.useRealTimers(); }
  });

  it("clears scope state and cancels pending reads", async () => {
    vi.useFakeTimers();
    try {
      const read = vi.fn(async () => response());
      const runtime = createNativeWritingMethodRuntime({ transport: { read }, delaysMs: [100] });
      runtime.bind(BINDING);
      runtime.clear();
      await vi.runAllTimersAsync();
      expect(read).not.toHaveBeenCalled();
      expect(runtime.getSnapshot().binding).toBeNull();
    } finally { vi.useRealTimers(); }
  });
});

describe("native writing status HTTP transport", () => {
  it("uses only the scoped read endpoint and treats 404 as unclaimed", async () => {
    const request = vi.fn().mockRejectedValue(new ApiError(404, "not found", null));
    const transport = createNativeWritingMethodHttpTransport(request);
    expect(await transport.read(BINDING, new AbortController().signal)).toBeNull();
    expect(request.mock.calls[0][0]).toContain(
      `/novels/${BINDING.novelId}/native-writing-actions/${BINDING.actionId}`,
    );
    expect(request.mock.calls[0][0]).toContain("tab_id=anw-tab-test");
    expect(request.mock.calls[0][0]).toContain(`document_id=${BINDING.documentId}`);
  });
});
