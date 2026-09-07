import { describe, expect, it, vi } from "vitest";
import {
  createWritingAction, writingActionForInput, WritingMethodStatusController,
} from "./api";
import type { WritingActionBinding } from "./contracts";

const A = "11111111-1111-4111-8111-111111111111";
const B = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "22222222-2222-4222-8222-222222222222";
const BINDING: WritingActionBinding = {
  ownerKey: "owner", workspaceKey: "workspace", tabId: "tab", agentId: "ai-novel-writer",
  scopeKind: "novel", scopeId: "novel", documentId: "chapter",
};
function response(action = A, state = "claimed") {
  return { schema_version: "writing-method-status/1", action_id: action, dispatch_id: DISPATCH, state,
    method_input_hash: ["assembled", "dispatch_started", "dispatched"].includes(state) ? "a".repeat(64) : null,
    job_ref: state === "dispatched" ? "job-1" : null };
}
function deferred() {
  let resolve!: (value: unknown) => void;
  const promise = new Promise<unknown>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("writing author action identity", () => {
  it("uses crypto.randomUUID once per action; transport retry reuses the ticket", () => {
    const id = vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValueOnce(A).mockReturnValueOnce(B);
    try {
      const first = createWritingAction(BINDING, "input-hash");
      expect(writingActionForInput(first, BINDING, "input-hash")).toBe(first);
      expect(id).toHaveBeenCalledTimes(1);
      expect(createWritingAction(BINDING, "input-hash").action_id).toBe(B);
      expect(id).toHaveBeenCalledTimes(2);
      expect(Object.isFrozen(first.binding)).toBe(true);
    } finally { id.mockRestore(); }
  });

  it.each([
    { ownerKey: "owner-2" }, { workspaceKey: "workspace-2" }, { tabId: "tab-2" },
    { scopeId: "novel-2" }, { documentId: "chapter-2" }, { scopeKind: "creation_draft" as const },
  ])("changed scope produces a distinct ticket %#", (patch) => {
    const first = createWritingAction(BINDING, "same", () => A);
    expect(writingActionForInput(first, { ...BINDING, ...patch }, "same", () => B).action_id).toBe(B);
  });

  it("changed author input starts a new action without mutating the previous one", () => {
    const first = createWritingAction(BINDING, "first", () => A);
    const second = writingActionForInput(first, BINDING, "second", () => B);
    expect(second.action_id).toBe(B);
    expect(first.inputFingerprint).toBe("first");
  });
});

describe("writing method status transport", () => {
  it("has no network default or automatic model calls", async () => {
    const controller = new WritingMethodStatusController();
    controller.activate(createWritingAction(BINDING, "input", () => A));
    expect(await controller.refresh(DISPATCH)).toBeNull();
    expect(controller.getSnapshot()).toMatchObject({ connected: false, status: null, error: "transport_unavailable" });
  });

  it("correlates the requested action and dispatch; uses one read only", async () => {
    const readStatus = vi.fn(async () => response());
    const controller = new WritingMethodStatusController({ readStatus });
    controller.activate(createWritingAction(BINDING, "input", () => A));
    expect((await controller.refresh(DISPATCH))?.action_id).toBe(A);
    expect(readStatus).toHaveBeenCalledTimes(1);
    expect(readStatus.mock.calls[0]).toEqual([{ action_id: A, dispatch_id: DISPATCH }, expect.any(AbortSignal)]);
  });

  it("discards late previous-action results even when transport ignores abort", async () => {
    const old = deferred();
    const readStatus = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce(response(B));
    const controller = new WritingMethodStatusController({ readStatus });
    controller.activate(createWritingAction(BINDING, "first", () => A));
    const pending = controller.refresh(DISPATCH);
    controller.activate(createWritingAction(BINDING, "second", () => B));
    await controller.refresh(DISPATCH);
    old.resolve(response(A, "dispatched"));
    expect(await pending).toBeNull();
    expect(controller.getSnapshot().status?.action_id).toBe(B);
  });

  it("discards an older read within the same action and blocks status regression", async () => {
    const old = deferred();
    const readStatus = vi.fn().mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(response(A, "assembled")).mockResolvedValueOnce(response());
    const controller = new WritingMethodStatusController({ readStatus });
    controller.activate(createWritingAction(BINDING, "input", () => A));
    const pending = controller.refresh(DISPATCH);
    await controller.refresh(DISPATCH);
    old.resolve(response());
    await pending;
    await controller.refresh(DISPATCH);
    expect(controller.getSnapshot().status?.state).toBe("assembled");
  });

  it("unknown does not trigger automatic retries or turn into an unrelated success", async () => {
    vi.useFakeTimers();
    try {
      const readStatus = vi.fn().mockResolvedValueOnce(response(A, "unknown"))
        .mockResolvedValueOnce(response(A, "dispatched"));
      const controller = new WritingMethodStatusController({ readStatus });
      controller.activate(createWritingAction(BINDING, "input", () => A));
      await controller.refresh(DISPATCH);
      await vi.runAllTimersAsync();
      expect(readStatus).toHaveBeenCalledTimes(1);
      await controller.refresh(DISPATCH);
      expect(controller.getSnapshot().status?.state).toBe("unknown");
    } finally { vi.useRealTimers(); }
  });

  it.each([{ action_id: B }, { dispatch_id: B }, { schema_version: "new" }])(
    "rejects wrong response correlation %#", async (patch) => {
      const controller = new WritingMethodStatusController({ readStatus: async () => ({ ...response(), ...patch }) });
      controller.activate(createWritingAction(BINDING, "input", () => A));
      expect(await controller.refresh(DISPATCH)).toBeNull();
      expect(controller.getSnapshot()).toMatchObject({ status: null, error: "invalid_status" });
    },
  );

  it("clears prior success when activating another scope and ignores disposed results", async () => {
    const slow = deferred();
    const readStatus = vi.fn().mockResolvedValueOnce(response(A, "dispatched")).mockReturnValueOnce(slow.promise);
    const controller = new WritingMethodStatusController({ readStatus });
    controller.activate(createWritingAction(BINDING, "first", () => A));
    await controller.refresh(DISPATCH);
    controller.activate(createWritingAction({ ...BINDING, scopeId: "novel-2" }, "second", () => B));
    expect(controller.getSnapshot().status).toBeNull();
    const pending = controller.refresh(DISPATCH);
    controller.dispose();
    slow.resolve(response(B, "dispatched"));
    expect(await pending).toBeNull();
    expect(controller.getSnapshot().status).toBeNull();
  });

  it("reports a read failure without automatic retry", async () => {
    const readStatus = vi.fn(async () => { throw new Error("transport failed"); });
    const controller = new WritingMethodStatusController({ readStatus });
    controller.activate(createWritingAction(BINDING, "input", () => A));
    await controller.refresh(DISPATCH);
    expect(readStatus).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot()).toMatchObject({ loading: false, error: "status_unavailable" });
  });
});
