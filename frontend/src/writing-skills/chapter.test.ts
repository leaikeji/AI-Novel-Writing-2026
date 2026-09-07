import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { ChapterMethodClient, chapterMethodCatalog, type ChapterMethodRequest } from "./chapter";
import type { WritingActionBinding } from "./contracts";

const DOC = "11111111-1111-4111-8111-111111111111";
const NOVEL = "22222222-2222-4222-8222-222222222222";
const JOB = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "44444444-4444-4444-8444-444444444444";
const binding: WritingActionBinding = { ownerKey: DOC, workspaceKey: NOVEL, scopeKind: "novel",
  scopeId: NOVEL, documentId: DOC, tabId: "tab", agentId: "ai-novel-writer" };
const input = { expected_brief_version: 1, force_new: true, asset_ids: [] };
function output(action: string, state = "dispatched") {
  return { id: JOB, document_id: DOC, state: "ready", candidate: { id: JOB }, writing_method: {
    schema_version: "writing-method-status/1", action_id: action, dispatch_id: DISPATCH, state,
    method_input_hash: ["dispatched", "unknown"].includes(state) ? "a".repeat(64) : null,
    job_ref: `chapter:${JOB}`, selected_ids: ["suspense-writing"], omitted_ids: [],
    semantic_enabled: false, auxiliary_calls: 0,
  } };
}
function transport(handler: (path: string, init?: RequestInit) => Promise<unknown>): ChapterMethodRequest {
  return handler as ChapterMethodRequest;
}

describe("managed chapter HTTP adapter", () => {
  it("freezes action-only method preferences into identity and sends only the server contract", async () => {
    const sent: Record<string, unknown>[] = [];
    let finish!: (value: unknown) => void;
    const client = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => {
      const body = JSON.parse(String(init?.body)); sent.push(body);
      await new Promise(resolve => { finish = resolve; });
      return output(body.writing_action.action_id);
    }));
    const pending = client.start({ ...input, method_mode: "generic_only" });
    await expect(client.start({ ...input, method_mode: "auto" })).rejects.toThrow("不能替换");
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).not.toHaveProperty("method_mode");
    expect(sent[0]).toMatchObject({ writing_action: { preferences: { mode: "generic_only", semantic_mode: "off" } } });
    finish(null); await pending;
  });
  it("closed release gate preserves GET recovery and never hides an unresolved ticket", async () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); } };
    let actionId = "";
    const creator = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => {
      actionId = JSON.parse(String(init?.body)).writing_action.action_id;
      return output(actionId);
    }), storage);
    await creator.start(input);
    const read = vi.fn(async () => output(actionId));
    const restored = new ChapterMethodClient(binding, () => undefined, transport(read), storage,
      { managed: false, catalog: true });
    expect(restored.getSnapshot().action?.action_id).toBe(actionId);
    await expect(restored.start(input)).rejects.toThrow("未开放");
    expect(() => restored.beginLegacyGeneration()).toThrow("先查询");
    await restored.recover();
    restored.beginLegacyGeneration();
    expect(restored.getSnapshot().action).toBeNull();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("catalog failure permits recovery but forbids silently falling back to legacy", () => {
    const client = new ChapterMethodClient(binding, () => undefined, transport(async () => null), undefined,
      { managed: false, catalog: false });
    expect(() => client.beginLegacyGeneration()).toThrow("不能降级");
  });

  it("a dispatched method is not proof that its business job completed", async () => {
    const client = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => ({
      ...output(JSON.parse(String(init?.body)).writing_action.action_id), state: "running", candidate: null,
    })));
    await client.start(input);
    await expect(client.start(input)).rejects.toThrow("先查询");
  });
  it("reload resumes its tab ID but a duplicated navigation replaces the inherited ID", async () => {
    const values = new Map<string, string>([["anw-writing-tab/1", DOC]]);
    const storage = { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); } };
    try {
      vi.resetModules();
      vi.stubGlobal("performance", { getEntriesByType: () => [{ type: "reload" }] });
      const reloaded = await import("./chapter");
      expect(reloaded.writingPageTabId(storage)).toBe(DOC);
      vi.resetModules();
      vi.stubGlobal("performance", { getEntriesByType: () => [{ type: "navigate" }] });
      const duplicate = await import("./chapter");
      expect(duplicate.writingPageTabId(storage)).not.toBe(DOC);
      expect(duplicate.writingPageTabId(storage)).toBe(values.get("anw-writing-tab/1"));
    } finally { vi.unstubAllGlobals(); }
  });
  it("a late pending GET cannot replace the completed POST status", async () => {
    let finishPost!: (value: unknown) => void;
    let finishGet!: (value: unknown) => void;
    let actionId = "";
    const client = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => {
      if (init?.method === "POST") {
        actionId = JSON.parse(String(init.body)).writing_action.action_id;
        return new Promise(resolve => { finishPost = resolve; });
      }
      return new Promise(resolve => { finishGet = resolve; });
    }));
    const post = client.start(input);
    await vi.waitFor(() => expect(actionId).not.toBe(""));
    const get = client.recover();
    finishPost(output(actionId));
    await post;
    finishGet({ state: "method_pending", writing_method: { ...output(actionId, "claimed").writing_method, job_ref: null } });
    await expect(get).rejects.toThrow("迟到");
    expect(client.getSnapshot().status?.state).toBe("dispatched");
    expect(client.getSnapshot().error).toBeNull();
  });
  it("restores only a scoped metadata ticket after refresh; recovery never POSTs", async () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); } };
    let actionId = "";
    const first = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => {
      actionId = JSON.parse(String(init?.body)).writing_action.action_id;
      throw new Error("lost");
    }), storage);
    await expect(first.start(input)).rejects.toThrow("lost");
    const saved = [...values.values()][0];
    expect(saved).not.toContain("expected_brief_version");
    expect(saved).not.toContain("asset_ids");
    const read = vi.fn(async () => output(actionId));
    const restored = new ChapterMethodClient(binding, () => undefined, transport(read), storage);
    expect(restored.getSnapshot().action?.action_id).toBe(actionId);
    await restored.recover();
    expect(read.mock.calls).toHaveLength(1);
    const other = new ChapterMethodClient({ ...binding, tabId: "other" }, () => undefined, transport(read), storage);
    expect(other.getSnapshot().action).toBeNull();
  });

  it("refuses to send if the durable recovery ticket cannot be saved", async () => {
    const call = vi.fn(async () => null);
    const client = new ChapterMethodClient(binding, () => undefined, transport(call), {
      getItem: () => null, setItem: () => { throw new Error("storage unavailable"); },
    });
    await expect(client.start(input)).rejects.toThrow("storage unavailable");
    expect(call).not.toHaveBeenCalled();
  });
  it("coalesces same-input double click and uses a new action for deliberate next generation", async () => {
    const calls: string[] = [];
    const client = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => {
      const action = JSON.parse(String(init?.body)).writing_action.action_id;
      calls.push(action);
      return output(action);
    }));
    const first = client.start(input);
    expect(client.start(input)).toBe(first);
    await expect(client.start({ ...input, force_new: false })).rejects.toThrow("不能替换");
    await first;
    await client.start(input);
    expect(calls).toHaveLength(2);
    expect(calls[0]).not.toBe(calls[1]);
    expect(client.getSnapshot().action?.inputFingerprint).toMatch(/^[a-f0-9]{64}$/);
  });

  it("sends a new action linked to the exact failed action for a length retry", async () => {
    const bodies: Record<string, unknown>[] = [];
    const client = new ChapterMethodClient(binding, () => undefined, transport(async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      const action = body.writing_action.action_id;
      if (bodies.length === 1) {
        throw new ApiError(422, "too short", { type: "chapter_length_out_of_range",
          direction: "below_target", validation_state: "below_target", retryable: true,
          writing_method: output(action).writing_method,
          job: { ...output(action), state: "failed", candidate: null } });
      }
      return output(action);
    }));
    await expect(client.start(input)).rejects.toThrow("too short");
    const parent = client.getSnapshot().action!.action_id;
    await client.start({ ...input, retry_of_action_id: parent });
    const first = bodies[0].writing_action as Record<string, unknown>;
    const second = bodies[1].writing_action as Record<string, unknown>;
    expect(first).not.toHaveProperty("retry_of_action_id");
    expect(second.retry_of_action_id).toBe(parent);
    expect(second.action_id).not.toBe(parent);
    await expect(client.start({ ...input, retry_of_action_id: "bad" })).rejects.toThrow("标识无效");
  });

  it("lost response recovers by GET with the original ID and no model/config refresh", async () => {
    let original = "";
    const calls: string[] = [];
    const client = new ChapterMethodClient(binding, () => undefined, transport(async (path, init) => {
      calls.push(`${init?.method} ${path}`);
      if (init?.method === "POST") {
        original = JSON.parse(String(init.body)).writing_action.action_id;
        throw new TypeError("connection lost");
      }
      return output(original);
    }));
    await expect(client.start(input)).rejects.toThrow("connection lost");
    await expect(client.start(input)).rejects.toThrow("先查询");
    const recovered = await client.recover();
    expect(recovered.writing_method.action_id).toBe(original);
    expect(calls).toHaveLength(2);
    expect(calls[1]).toContain(`GET /documents/${DOC}/writing-method-actions/${original}?tab_id=tab`);
  });

  it("keeps known unknown state and blocks automatic new generation", async () => {
    const call = vi.fn(async (_path: string, init?: RequestInit) => {
      const action = JSON.parse(String(init?.body)).writing_action.action_id;
      throw new ApiError(502, "uncertain", { writing_method: output(action, "unknown").writing_method });
    });
    const client = new ChapterMethodClient(binding, () => undefined, transport(call));
    await expect(client.start(input)).rejects.toThrow();
    expect(client.getSnapshot().status?.state).toBe("unknown");
    await expect(client.start(input)).rejects.toThrow("先查询");
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("rejects cross-action replies and revokes a switched chapter before sending", async () => {
    const call = vi.fn(async () => output(DOC));
    const client = new ChapterMethodClient(binding, () => undefined, transport(call));
    await expect(client.start(input)).rejects.toThrow("不匹配");
    const other = new ChapterMethodClient(binding, () => undefined, transport(call));
    const pending = other.start(input);
    other.dispose();
    await expect(pending).rejects.toThrow("未发送");
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("discovers future display names and respects the server gate", async () => {
    const get = transport(async () => ({ schema_version: "writing-skill-catalog/1", agent_id: "ai-novel-writer",
      chapter_body_available: false, semantic_available: false,
      capabilities: [{ skill_id: "fixture-third", display_name: "测试第三类", version: "1.0.0" }],
      scope: { kind: "novel", scope_id: NOVEL, document_id: DOC, tab_id: "tab", owner_id: DOC, workspace_id: NOVEL } }));
    const catalog = await chapterMethodCatalog(DOC, NOVEL, "tab", get);
    expect(catalog.available).toBe(false);
    expect(catalog.displayNames["fixture-third"]).toBe("测试第三类");
    await expect(chapterMethodCatalog(DOC, NOVEL, "other", get)).rejects.toThrow("范围");
  });
});
