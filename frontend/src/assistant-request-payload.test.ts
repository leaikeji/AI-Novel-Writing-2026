import { describe, expect, it, vi } from "vitest";

import {
  createAssistantRequestPayloadTransformer,
  registerAssistantRequestPayload,
} from "./assistant-request-payload";


describe("assistant request payload", () => {
  it("takes a fresh snapshot for every send and preserves host request_context", () => {
    let revision = 0;
    const getPatch = vi.fn(() => ({
      ai_novel_context: { contextRevision: ++revision },
    }));
    const transform = createAssistantRequestPayloadTransformer(getPatch);
    const originalPayload = {
      content: "继续",
      request_context: { host_trace: "keep-me" },
    };

    const first = transform({
      payload: originalPayload,
      sessionId: "session-1",
      selectedAgent: "ai-novel-writer",
    });
    const second = transform({
      payload: originalPayload,
      sessionId: "session-1",
      selectedAgent: "ai-novel-writer",
    });

    expect(getPatch).toHaveBeenCalledTimes(2);
    expect(getPatch).toHaveBeenLastCalledWith({
      sessionId: "session-1",
      selectedAgent: "ai-novel-writer",
    });
    expect(first).toEqual({
      content: "继续",
      request_context: {
        host_trace: "keep-me",
        ai_novel_context: { contextRevision: 1 },
      },
    });
    expect(second).toEqual({
      content: "继续",
      request_context: {
        host_trace: "keep-me",
        ai_novel_context: { contextRevision: 2 },
      },
    });
    expect(originalPayload).toEqual({
      content: "继续",
      request_context: { host_trace: "keep-me" },
    });
  });

  it("supports a context_ref patch without deciding retention policy", () => {
    const transform = createAssistantRequestPayloadTransformer(() => ({
      context_ref: "opaque-reference",
    }));

    expect(transform({ payload: { content: "润色" } })).toEqual({
      content: "润色",
      request_context: { context_ref: "opaque-reference" },
    });
  });

  it("skips injection instead of replacing an unknown host context shape", () => {
    const transform = createAssistantRequestPayloadTransformer(() => ({
      ai_novel_context: { novelId: "novel-1" },
    }));

    expect(transform({
      payload: { request_context: "host-private-shape" },
    })).toBeUndefined();
    expect(createAssistantRequestPayloadTransformer(() => null)({
      payload: { content: "no-context" },
    })).toBeUndefined();
  });

  it("does not block the host send when the snapshot getter fails", () => {
    const transform = createAssistantRequestPayloadTransformer(() => {
      throw new Error("page adapter was disposed");
    });

    expect(() => transform({
      payload: { content: "宿主消息仍应发送" },
      sessionId: "session-1",
    })).not.toThrow();
    expect(transform({
      payload: { content: "宿主消息仍应发送" },
      sessionId: "session-1",
    })).toBeUndefined();
  });

  it("registers through the public extension point and returns its disposer", () => {
    let transformer: ((args: QwenPawRequestPayloadArgs) => Record<string, unknown> | undefined) | undefined;
    const dispose = vi.fn();
    const add = vi.fn((_pluginId, nextTransformer) => {
      transformer = nextTransformer;
      return { dispose };
    });

    const registration = registerAssistantRequestPayload({
      pluginId: "ai-novel-world-2026",
      requestPayload: { add },
      getRequestContextPatch: () => ({ context_ref: "ref-1" }),
      order: 20,
    });

    expect(add).toHaveBeenCalledWith(
      "ai-novel-world-2026",
      expect.any(Function),
      { id: "ai-novel-world-2026.assistant-context", order: 20 },
    );
    expect(transformer?.({ payload: {} })).toEqual({
      request_context: { context_ref: "ref-1" },
    });
    registration.dispose();
    expect(dispose).toHaveBeenCalledOnce();
  });
});
