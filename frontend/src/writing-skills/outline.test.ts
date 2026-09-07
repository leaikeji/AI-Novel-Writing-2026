import { describe, expect, it } from "vitest";
import {
  OutlineMethodClient,
  outlineMethodCatalog,
  type OutlineMethodCatalog,
} from "./outline";

const OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c";
const WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e";
const NOVEL = "11111111-1111-4111-8111-111111111111";
const DRAFT = "22222222-2222-4222-8222-222222222222";
const ACTION = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "44444444-4444-4444-8444-444444444444";

const catalog: OutlineMethodCatalog = {
  available: true,
  catalogAvailable: true,
  displayNames: {},
  outlineDraftId: DRAFT,
  outlineDraftVersion: 3,
  kind: "outline_background",
  binding: {
    ownerKey: OWNER,
    workspaceKey: WORKSPACE,
    tabId: "tab",
    agentId: "ai-novel-writer",
    scopeKind: "novel",
    scopeId: NOVEL,
  },
};

function result(action: string) {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    scope_id: DRAFT,
    kind: "outline_background",
    state: "ready",
    writing_method: {
      schema_version: "writing-method-status/1",
      action_id: action,
      dispatch_id: DISPATCH,
      state: "dispatched",
      selected_ids: ["suspense-writing"],
      omitted_ids: [],
      method_input_hash: "a".repeat(64),
      semantic_enabled: false,
      auxiliary_calls: 0,
      job_ref: "creative:55555555-5555-4555-8555-555555555555",
    },
  };
}

describe("outlineMethodCatalog", () => {
  it("accepts only an exact novel scope and task-specific server gate", async () => {
    const loaded = await outlineMethodCatalog(
      NOVEL,
      DRAFT,
      3,
      "outline_background",
      "tab",
      async path => {
        expect(path).toContain(`novel_id=${NOVEL}`);
        expect(path).toContain("creative_kind=outline_background");
        return {
          schema_version: "writing-skill-catalog/1",
          agent_id: "ai-novel-writer",
          novel_creative_available: true,
          catalog_available: true,
          semantic_available: false,
          capabilities: [],
          scope: {
            owner_id: OWNER,
            workspace_id: WORKSPACE,
            kind: "novel",
            scope_id: NOVEL,
            document_id: null,
            tab_id: "tab",
          },
        } as never;
      },
    );
    expect(loaded.outlineDraftId).toBe(DRAFT);
    expect(loaded.outlineDraftVersion).toBe(3);
    expect(loaded.kind).toBe("outline_background");
  });
});

describe("OutlineMethodClient", () => {
  it("binds the business draft and stable novel scope exactly once", async () => {
    const bodies: any[] = [];
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    const client = new OutlineMethodClient(catalog, async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      await wait;
      return result(body.writing_action.action_id) as never;
    });
    const input = {
      kind: "outline_background" as const,
      expected_scope_version: 3,
      input_snapshot: {
        schema_version: "outline-generation-request-v1",
        intent: "fresh",
        expected_outline_version: 3,
      },
      force_new: true,
    };
    const first = client.start(input);
    const second = client.start(input);
    release();
    await Promise.all([first, second]);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      scope_type: "outline",
      scope_id: DRAFT,
      novel_id: NOVEL,
      expected_scope_version: 3,
      writing_action: {
        preferences: { mode: "auto", semantic_mode: "off" },
      },
    });
  });

  it("recovers only through the novel-scoped GET endpoint", async () => {
    const key = `anw-outline-action/1:outline_background:v3:${JSON.stringify([
      OWNER, WORKSPACE, "tab", "ai-novel-writer", "novel", NOVEL, null,
    ])}`;
    const stored = JSON.stringify({
      action_id: ACTION,
      binding: catalog.binding,
      inputFingerprint: "b".repeat(64),
    });
    const calls: Array<[string, string | undefined]> = [];
    const client = new OutlineMethodClient(
      catalog,
      async (path, init) => {
        calls.push([path, init?.method]);
        return result(ACTION) as never;
      },
      {
        getItem: candidate => candidate === key ? stored : null,
        setItem: () => undefined,
      },
    );
    await client.recover();
    expect(calls).toEqual([[
      `/novels/${NOVEL}/writing-method-actions/${ACTION}?tab_id=tab`,
      "GET",
    ]]);
  });

  it("rejects another outline task on a task-frozen catalog", async () => {
    const client = new OutlineMethodClient(catalog);
    await expect(client.start({
      kind: "outline_plot",
      expected_scope_version: 3,
      input_snapshot: {},
      force_new: true,
    })).rejects.toThrow("不属于当前写作范围");
  });
});
