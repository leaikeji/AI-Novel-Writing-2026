import { describe, expect, it } from "vitest";

import {
  CharacterProfileMethodClient,
  characterProfileMethodCatalog,
  type CharacterProfileMethodCatalog,
} from "./profile";

const OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c";
const WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e";
const NOVEL = "11111111-1111-4111-8111-111111111111";
const ACTION = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "44444444-4444-4444-8444-444444444444";
const JOB = "55555555-5555-4555-8555-555555555555";
const SOURCE_HASH = "a".repeat(64);

const catalog: CharacterProfileMethodCatalog = {
  available: true,
  catalogAvailable: true,
  displayNames: {},
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
    id: JOB,
    scope_id: NOVEL,
    kind: "character_profile_completion",
    state: "ready",
    writing_method: {
      schema_version: "writing-method-status/1",
      action_id: action,
      dispatch_id: DISPATCH,
      state: "dispatched",
      selected_ids: ["suspense-writing"],
      omitted_ids: [],
      method_input_hash: "b".repeat(64),
      semantic_enabled: false,
      auxiliary_calls: 0,
      job_ref: `creative:${JOB}`,
    },
  };
}

describe("characterProfileMethodCatalog", () => {
  it("accepts only the exact novel scope and profile task gate", async () => {
    const loaded = await characterProfileMethodCatalog(
      NOVEL,
      "tab",
      async path => {
        expect(path).toContain(`novel_id=${NOVEL}`);
        expect(path).toContain("creative_kind=character_profile_completion");
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
    expect(loaded.available).toBe(true);
    expect(loaded.binding.scopeId).toBe(NOVEL);
  });
});

describe("CharacterProfileMethodClient", () => {
  it("deduplicates one source snapshot and never invents an integer scope version", async () => {
    const bodies: any[] = [];
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    const client = new CharacterProfileMethodClient(catalog, async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      await wait;
      return result(body.writing_action.action_id) as never;
    });
    const input = { expectedSourceHash: SOURCE_HASH, forceNew: true };
    const first = client.start(input);
    const second = client.start(input);
    release();
    await Promise.all([first, second]);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      scope_type: "novel",
      scope_id: NOVEL,
      novel_id: NOVEL,
      kind: "character_profile_completion",
      input_snapshot: { expected_source_hash: SOURCE_HASH },
      writing_action: {
        preferences: { mode: "auto", semantic_mode: "off" },
      },
    });
    expect(bodies[0]).not.toHaveProperty("expected_scope_version");
  });

  it("recovers only through the exact novel-scoped GET", async () => {
    const key = `anw-character-profile-action/1:${JSON.stringify([
      OWNER, WORKSPACE, "tab", "ai-novel-writer", "novel", NOVEL, null,
    ])}`;
    const stored = JSON.stringify({
      action_id: ACTION,
      binding: catalog.binding,
      inputFingerprint: "c".repeat(64),
    });
    const calls: Array<[string, string | undefined]> = [];
    const client = new CharacterProfileMethodClient(
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

  it("persists before POST and a rebuilt client recovers with GET only", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    };
    const calls: Array<[string, string | undefined]> = [];
    const first = new CharacterProfileMethodClient(
      catalog,
      async (path, init) => {
        calls.push([path, init?.method]);
        const saved = Array.from(values.values());
        expect(saved).toHaveLength(1);
        const actionId = JSON.parse(saved[0]).action_id;
        return result(actionId) as never;
      },
      storage,
    );
    await first.start({ expectedSourceHash: SOURCE_HASH, forceNew: false });

    const restored = new CharacterProfileMethodClient(
      catalog,
      async (path, init) => {
        calls.push([path, init?.method]);
        const actionId = JSON.parse(Array.from(values.values())[0]).action_id;
        return result(actionId) as never;
      },
      storage,
    );
    expect(restored.hasRecoveryTicket).toBe(true);
    await restored.recover();
    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual(["/creative-generations", "POST"]);
    expect(calls[1][0]).toMatch(new RegExp(
      `^/novels/${NOVEL}/writing-method-actions/[0-9a-f-]+\\?tab_id=tab$`,
    ));
    expect(calls[1][1]).toBe("GET");
  });

  it("rejects a malformed source hash before transport", async () => {
    let calls = 0;
    const client = new CharacterProfileMethodClient(catalog, async () => {
      calls += 1;
      return result(ACTION) as never;
    });
    await expect(client.start({
      expectedSourceHash: "bad",
      forceNew: false,
    })).rejects.toThrow("来源摘要无效");
    expect(calls).toBe(0);
  });
});
