import { describe, expect, it, vi } from "vitest";

import type { CreateAssistantContextRefInput } from "./assistant-context-ref";
import { createAssistantContextRefHttpClient } from "./assistant-context-transport";


function input(): CreateAssistantContextRefInput {
  const snapshot = {
    schemaVersion: 2 as const,
    contextRevision: 9,
    capturedAt: "2026-08-25T10:00:00.000Z",
    expiresAt: "2026-08-25T10:20:00.000Z",
    agentId: "ai-novel-writer",
    sessionId: "session-1",
    novel: { id: "novel-1", title: "潮声替我说晚安" },
    page: { section: "chapters" as const, view: "chapter-editor" as const },
    budget: {
      maxCharacters: 24_000,
      usedCharacters: 300,
      truncated: false,
      omittedFieldIds: [],
    },
  };
  return {
    binding: {
      ownerToken: "owner_token_0000000000000001",
      tabInstance: "anw_tab_000000000000000000001",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
      documentId: "document-1",
      sessionId: "session-1",
    },
    snapshot,
    serialized: JSON.stringify(snapshot),
  };
}


describe("assistant context_ref HTTP transport", () => {
  it("posts only the approved binding and snapshot through the PawApp API", async () => {
    const request = vi.fn(async (_path: string, _init?: RequestInit): Promise<unknown> => ({
      contextRef: "A".repeat(43),
      expiresAt: "2026-08-25T10:05:00.000Z",
      contextRevision: 9,
      payloadCharacters: 300,
    }));
    const client = createAssistantContextRefHttpClient({ request });
    const controller = new AbortController();

    await expect(client(input(), controller.signal)).resolves.toEqual({
      contextRef: "A".repeat(43),
      expiresAt: "2026-08-25T10:05:00.000Z",
      contextRevision: 9,
      payloadCharacters: 300,
    });
    expect(request).toHaveBeenCalledWith("/assistant-contexts", {
      method: "POST",
      signal: controller.signal,
      body: expect.any(String),
    });
    const rawBody = request.mock.calls[0]?.[1]?.body;
    expect(typeof rawBody).toBe("string");
    const body = JSON.parse(String(rawBody));
    expect(body).toEqual({
      ownerToken: "owner_token_0000000000000001",
      tabInstance: "anw_tab_000000000000000000001",
      agentId: "ai-novel-writer",
      novelId: "novel-1",
      documentId: "document-1",
      sessionId: "session-1",
      snapshot: input().snapshot,
    });
    expect(body).not.toHaveProperty("serialized");
  });

  it("omits absent first-session/document bindings rather than sending null", async () => {
    const request = vi.fn(async (_path: string, _init?: RequestInit): Promise<unknown> => ({
      contextRef: "B".repeat(43),
      expiresAt: "2026-08-25T10:05:00.000Z",
      contextRevision: 9,
      payloadCharacters: 280,
    }));
    const client = createAssistantContextRefHttpClient({ request });
    const value = input();
    delete value.binding.documentId;
    delete value.binding.sessionId;
    delete value.snapshot.sessionId;
    await client(value, new AbortController().signal);

    const rawBody = request.mock.calls[0]?.[1]?.body;
    expect(typeof rawBody).toBe("string");
    const body = JSON.parse(String(rawBody));
    expect(body).not.toHaveProperty("documentId");
    expect(body).not.toHaveProperty("sessionId");
  });

  it.each([
    null,
    {},
    { contextRef: "short", expiresAt: "2026-08-25T10:05:00Z", contextRevision: 9, payloadCharacters: 1 },
    { contextRef: "A".repeat(43), expiresAt: "bad", contextRevision: 9, payloadCharacters: 1 },
    { contextRef: "A".repeat(43), expiresAt: "2026-08-25T10:05:00Z", contextRevision: -1, payloadCharacters: 1 },
  ])("fails closed on an invalid endpoint response %#", async (response) => {
    const client = createAssistantContextRefHttpClient({
      request: async (_path: string, _init?: RequestInit): Promise<unknown> => response,
    });
    await expect(client(input(), new AbortController().signal)).rejects.toThrow(
      "invalid assistant context ref response",
    );
  });

  it("propagates AbortSignal cancellation without retrying", async () => {
    const request = vi.fn(async (_path, init?: RequestInit) => {
      if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      throw new Error("expected an aborted signal");
    });
    const client = createAssistantContextRefHttpClient({ request });
    const controller = new AbortController();
    controller.abort();

    await expect(client(input(), controller.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(request).toHaveBeenCalledOnce();
  });
});
