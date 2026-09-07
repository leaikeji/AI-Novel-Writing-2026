import { describe, expect, it } from "vitest";
import {
  CreationMethodClient,
  creationMethodCatalog,
  type CreationMethodCatalog,
} from "./creation";

const OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c";
const WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e";
const DRAFT = "11111111-1111-4111-8111-111111111111";
const ACTION = "22222222-2222-4222-8222-222222222222";
const DISPATCH = "33333333-3333-4333-8333-333333333333";

const catalog: CreationMethodCatalog = {
  available: true,
  catalogAvailable: true,
  displayNames: {},
  binding: {
    ownerKey: OWNER,
    workspaceKey: WORKSPACE,
    tabId: "tab",
    agentId: "ai-novel-writer",
    scopeKind: "creation_draft",
    scopeId: DRAFT,
  },
};

function result(action: string, state = "dispatched") {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    scope_id: DRAFT,
    state: "ready",
    writing_method: {
      schema_version: "writing-method-status/1",
      action_id: action,
      dispatch_id: DISPATCH,
      state,
      selected_ids: [],
      omitted_ids: [],
      method_input_hash: "a".repeat(64),
      semantic_enabled: false,
      auxiliary_calls: 0,
      job_ref: "creative:44444444-4444-4444-8444-444444444444",
    },
  };
}

describe("creationMethodCatalog", () => {
  it("accepts only the exact creation draft scope", async () => {
    const loaded = await creationMethodCatalog(DRAFT, "tab", async () => ({
      schema_version: "writing-skill-catalog/1",
      agent_id: "ai-novel-writer",
      creation_helper_available: true,
      catalog_available: true,
      semantic_available: false,
      capabilities: [],
      scope: {
        owner_id: OWNER,
        workspace_id: WORKSPACE,
        kind: "creation_draft",
        scope_id: DRAFT,
        document_id: null,
        tab_id: "tab",
      },
    }) as never);
    expect(loaded.binding.scopeId).toBe(DRAFT);
    await expect(creationMethodCatalog(DRAFT, "tab", async () => ({
      schema_version: "writing-skill-catalog/1",
      agent_id: "ai-novel-writer",
      creation_helper_available: true,
      catalog_available: true,
      semantic_available: false,
      capabilities: [],
      scope: { owner_id: OWNER, workspace_id: WORKSPACE, kind: "novel",
        scope_id: DRAFT, document_id: null, tab_id: "tab" },
    }) as never)).rejects.toThrow("范围无法确认");
  });
});

describe("CreationMethodClient", () => {
  it("adds one action and reuses the same pending promise", async () => {
    const bodies: any[] = [];
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    const client = new CreationMethodClient(catalog, async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      await wait;
      return result(body.writing_action.action_id) as never;
    });
    const input = { kind: "novel_naming" as const, expected_scope_version: 3,
      input_snapshot: { genre: "悬疑" }, force_new: true };
    const first = client.start(input);
    const second = client.start(input);
    release();
    const [a, b] = await Promise.all([first, second]);
    expect(a).toEqual(b);
    expect(bodies).toHaveLength(1);
    expect(bodies[0].writing_action.preferences).toEqual({ mode: "auto", semantic_mode: "off" });
    expect(bodies[0].expected_scope_version).toBe(3);
  });

  it("recovers with GET and never resends generation", async () => {
    const key = `anw-creation-action/1:${JSON.stringify([
      OWNER, WORKSPACE, "tab", "ai-novel-writer", "creation_draft", DRAFT, null,
    ])}`;
    const stored = JSON.stringify({ action_id: ACTION, binding: catalog.binding,
      inputFingerprint: "b".repeat(64) });
    const calls: Array<[string, string | undefined]> = [];
    const client = new CreationMethodClient(catalog, async (path, init) => {
      calls.push([path, init?.method]);
      return result(ACTION) as never;
    }, { getItem: candidate => candidate === key ? stored : null, setItem: () => undefined });
    await client.recover();
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toBe("GET");
    expect(calls[0][0]).toContain(`/creation-drafts/${DRAFT}/writing-method-actions/${ACTION}`);
  });

  it("does not start when the server gate is closed", async () => {
    const client = new CreationMethodClient({ ...catalog, available: false });
    await expect(client.start({ kind: "novel_template", expected_scope_version: 1,
      input_snapshot: {}, force_new: true })).rejects.toThrow("尚未开放");
  });
});
