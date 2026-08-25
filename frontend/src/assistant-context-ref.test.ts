import { describe, expect, it, vi } from "vitest";

import {
  createAssistantContextRefCoordinator,
  type CreatedAssistantContextRef,
} from "./assistant-context-ref";
import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import type { EditableFieldAdapter } from "./assistant-fields";
import type { RouteSessionSnapshot } from "./workbench-route";


const NOW = Date.parse("2026-08-25T10:00:00.000Z");
const OWNER = "owner_token_0000000000000001";


function bodyAdapter(value: () => string): EditableFieldAdapter {
  return {
    id: "chapter.body",
    label: "正文",
    persistence: "autosave",
    undoPolicy: "ai-transaction",
    getValue: value,
    applyValue: () => undefined,
    getSelection: () => null,
    focus: () => undefined,
    getDirty: () => true,
    dispose: () => undefined,
  };
}


function mountedRuntime(sessionId?: string) {
  const runtime = new NovelAssistantContextRuntime();
  runtime.setHostBinding("ai-novel-writer", sessionId);
  const scope = runtime.mountScope({
    id: "page:document-1",
    kind: "page",
    envelope: {
      agentId: "ai-novel-writer",
      novel: { id: "novel-1", title: "潮声替我说晚安" },
      page: { section: "chapters", view: "chapter-editor" },
      entity: { type: "document", id: "document-1", title: "退回的旧木盒" },
      document: {
        id: "document-1",
        volumeId: "volume-1",
        kind: "chapter",
        chapterNumber: 1,
        title: "退回的旧木盒",
        draftVersion: 3,
        savedContentHash: "a".repeat(64),
        dirty: true,
      },
    },
  });
  let body = "潮声从旧木盒里传来。";
  scope.registerField(bodyAdapter(() => body));
  return {
    runtime,
    scope,
    changeBody(next: string) {
      body = next;
      scope.notifyFieldChanged("chapter.body");
    },
  };
}


function workbenchRoute(overrides: Partial<RouteSessionSnapshot> = {}): RouteSessionSnapshot {
  return {
    state: "workbench-no-session",
    ownerToken: OWNER,
    route: {
      ownerToken: OWNER,
      novelId: "novel-1",
      documentId: "document-1",
    },
    ...overrides,
  };
}


function successRef(revision: number, suffix = "1"): CreatedAssistantContextRef {
  return {
    contextRef: `ctx_${"a".repeat(42)}${suffix}`,
    contextRevision: revision,
    expiresAt: new Date(NOW + 5 * 60_000).toISOString(),
    payloadCharacters: 800,
  };
}


async function flushAsync(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}


describe("assistant context_ref coordinator", () => {
  it("waits for the 400ms settle window, captures once, and consumes a ready ref once", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    try {
      const { runtime } = mountedRuntime("session-1");
      const createRef = vi.fn(async (input) => successRef(
        input.snapshot.contextRevision,
      ));
      const coordinator = createAssistantContextRefCoordinator({
        runtime,
        getRouteSession: () => workbenchRoute({ state: "workbench-session" }),
        createRef,
        tabInstance: "anw-tab-test-1",
        now: () => NOW,
      });

      coordinator.start();
      expect(runtime.getStatus().preparation).toBe("settling");
      expect(createRef).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(399);
      expect(createRef).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      await flushAsync();

      expect(createRef).toHaveBeenCalledOnce();
      expect(createRef.mock.calls[0][0]).toMatchObject({
        binding: {
          ownerToken: OWNER,
          tabInstance: "anw-tab-test-1",
          agentId: "ai-novel-writer",
          novelId: "novel-1",
          documentId: "document-1",
          sessionId: "session-1",
        },
      });
      expect(runtime.getStatus().preparation).toBe("ready");

      const first = coordinator.requestPatch({
        selectedAgent: "ai-novel-writer",
        sessionId: "session-1",
      });
      expect(first).toEqual({ context_ref: successRef(0).contextRef });
      expect(coordinator.requestPatch({
        selectedAgent: "ai-novel-writer",
        sessionId: "session-1",
      })).toBeNull();
      coordinator.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("allows an unbound first ref to be leased by the first native session", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    try {
      const { runtime } = mountedRuntime();
      const coordinator = createAssistantContextRefCoordinator({
        runtime,
        getRouteSession: workbenchRoute,
        createRef: async (input) => successRef(input.snapshot.contextRevision),
        tabInstance: "anw-tab-first-session",
        now: () => NOW,
        settleMs: 0,
      });
      coordinator.start();
      await vi.runOnlyPendingTimersAsync();
      await flushAsync();

      expect(coordinator.requestPatch({
        selectedAgent: "ai-novel-writer",
        sessionId: "new-native-session",
      })).toEqual({ context_ref: successRef(0).contextRef });
      coordinator.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("atomically binds a captured selection before leasing its context ref", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    try {
      const { runtime, scope } = mountedRuntime("session-1");
      scope.setSelection({
        id: "00000000-0000-4000-8000-000000000099",
        fieldId: "chapter.body",
        text: "潮声",
        startUtf16: 0,
        endUtf16: 2,
        direction: "forward",
        before: "",
        after: "从旧木盒里传来。",
        sourceValueSha256: "a".repeat(64),
        contextRevision: 0,
        createdAt: new Date(NOW).toISOString(),
        expiresAt: new Date(NOW + 20 * 60_000).toISOString(),
      });
      const selectionRevision = runtime.getStatus().contextRevision;
      const bindSelectionForSend = vi.fn(() => true);
      const coordinator = createAssistantContextRefCoordinator({
        runtime,
        getRouteSession: () => workbenchRoute({ state: "workbench-session" }),
        createRef: async (input) => successRef(input.snapshot.contextRevision),
        bindSelectionForSend,
        tabInstance: "anw-tab-selection",
        now: () => NOW,
        settleMs: 0,
      });
      coordinator.start();
      await vi.runOnlyPendingTimersAsync();
      await flushAsync();

      expect(coordinator.requestPatch({
        selectedAgent: "ai-novel-writer",
        sessionId: "session-1",
      })).toEqual({ context_ref: successRef(selectionRevision).contextRef });
      expect(bindSelectionForSend).toHaveBeenCalledWith({
        selectionId: "00000000-0000-4000-8000-000000000099",
        sessionId: "session-1",
        agentId: "ai-novel-writer",
        novelId: "novel-1",
        documentId: "document-1",
        fieldId: "chapter.body",
        contextRevision: selectionRevision,
      });
      coordinator.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("aborts a stale in-flight capture when the field revision changes", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    try {
      const { runtime, changeBody } = mountedRuntime("session-1");
      const resolvers: Array<(value: CreatedAssistantContextRef) => void> = [];
      const signals: AbortSignal[] = [];
      const createRef = vi.fn((input, signal: AbortSignal) => {
        signals.push(signal);
        return new Promise<CreatedAssistantContextRef>((resolve) => {
          resolvers.push((value) => resolve({
            ...value,
            contextRevision: input.snapshot.contextRevision,
          }));
        });
      });
      const coordinator = createAssistantContextRefCoordinator({
        runtime,
        getRouteSession: workbenchRoute,
        createRef,
        tabInstance: "anw-tab-stale",
        now: () => NOW,
        settleMs: 0,
      });
      coordinator.start();
      await vi.runOnlyPendingTimersAsync();
      expect(createRef).toHaveBeenCalledOnce();

      changeBody("正文已经在等待期间变化。");
      expect(signals[0].aborted).toBe(true);
      await vi.runOnlyPendingTimersAsync();
      expect(createRef).toHaveBeenCalledTimes(2);

      resolvers[0](successRef(0, "old"));
      await flushAsync();
      expect(coordinator.getReadyRef()).toBeNull();

      const currentRevision = createRef.mock.calls[1][0].snapshot.contextRevision;
      resolvers[1](successRef(currentRevision, "new"));
      await flushAsync();
      expect(coordinator.getReadyRef()?.contextRevision).toBe(currentRevision);
      coordinator.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects wrong Agent/session/route and never prepares on ordinary chat", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    try {
      const { runtime } = mountedRuntime("session-1");
      let route = workbenchRoute({ state: "workbench-session" });
      const createRef = vi.fn(async (input) => successRef(input.snapshot.contextRevision));
      const coordinator = createAssistantContextRefCoordinator({
        runtime,
        getRouteSession: () => route,
        createRef,
        tabInstance: "anw-tab-isolation",
        now: () => NOW,
        settleMs: 0,
      });
      coordinator.start();
      await vi.runOnlyPendingTimersAsync();
      await flushAsync();

      expect(coordinator.requestPatch({
        selectedAgent: "default",
        sessionId: "session-1",
      })).toBeNull();
      coordinator.refresh();
      await vi.runOnlyPendingTimersAsync();
      await flushAsync();
      expect(coordinator.requestPatch({
        selectedAgent: "ai-novel-writer",
        sessionId: "other-session",
      })).toBeNull();

      route = { state: "ordinary-chat", route: null, ownerToken: null };
      coordinator.refresh();
      await vi.runOnlyPendingTimersAsync();
      expect(coordinator.getReadyRef()).toBeNull();
      const callsAfterOrdinary = createRef.mock.calls.length;
      coordinator.refresh();
      await vi.runOnlyPendingTimersAsync();
      expect(createRef).toHaveBeenCalledTimes(callsAfterOrdinary);
      coordinator.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("fails closed on invalid/expired transport responses and disposes timers", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    try {
      const { runtime, changeBody } = mountedRuntime("session-1");
      const createRef = vi.fn(async (input) => ({
        ...successRef(input.snapshot.contextRevision),
        expiresAt: new Date(NOW - 1).toISOString(),
      }));
      const coordinator = createAssistantContextRefCoordinator({
        runtime,
        getRouteSession: workbenchRoute,
        createRef,
        tabInstance: "anw-tab-invalid",
        now: () => NOW,
      });
      coordinator.start();
      await vi.advanceTimersByTimeAsync(400);
      await flushAsync();
      expect(coordinator.getReadyRef()).toBeNull();
      expect(runtime.getStatus().preparation).toBe("failed");

      changeBody("这一轮计时器会在销毁时取消。");
      coordinator.dispose();
      await vi.runAllTimersAsync();
      expect(createRef).toHaveBeenCalledOnce();
      expect(() => coordinator.start()).toThrow(/disposed/);
    } finally {
      vi.useRealTimers();
    }
  });
});
