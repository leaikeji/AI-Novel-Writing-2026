import { describe, expect, it } from "vitest";
import {
  ReviewMethodClient,
  reviewMethodCatalog,
  type ReviewMethodCatalog,
} from "./review";

const OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c";
const WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e";
const NOVEL = "11111111-1111-4111-8111-111111111111";
const DOCUMENT = "22222222-2222-4222-8222-222222222222";
const ACTION = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "44444444-4444-4444-8444-444444444444";
const HASH = "a".repeat(64);

const catalog: ReviewMethodCatalog = {
  available: true,
  catalogAvailable: true,
  displayNames: {},
  documentId: DOCUMENT,
  draftVersion: 7,
  contentHash: HASH,
  binding: {
    ownerKey: OWNER,
    workspaceKey: WORKSPACE,
    tabId: "tab",
    agentId: "ai-novel-writer",
    scopeKind: "novel",
    scopeId: NOVEL,
    documentId: DOCUMENT,
  },
};

function result(action: string) {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    scope_id: DOCUMENT,
    kind: "review",
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
      job_ref: "creative:55555555-5555-4555-8555-555555555555",
    },
  };
}

describe("reviewMethodCatalog", () => {
  it("accepts only the exact document scope and review gate", async () => {
    const loaded = await reviewMethodCatalog(
      NOVEL,
      DOCUMENT,
      7,
      HASH,
      "tab",
      async path => {
        expect(path).toContain(`document_id=${DOCUMENT}`);
        expect(path).toContain("creative_kind=review");
        return {
          schema_version: "writing-skill-catalog/1",
          agent_id: "ai-novel-writer",
          document_creative_available: true,
          catalog_available: true,
          semantic_available: false,
          capabilities: [],
          scope: {
            owner_id: OWNER,
            workspace_id: WORKSPACE,
            kind: "novel",
            scope_id: NOVEL,
            document_id: DOCUMENT,
            tab_id: "tab",
          },
        } as never;
      },
    );
    expect(loaded.documentId).toBe(DOCUMENT);
    expect(loaded.draftVersion).toBe(7);
    expect(loaded.contentHash).toBe(HASH);
  });
});

describe("ReviewMethodClient", () => {
  it("deduplicates concurrent callbacks for one exact working copy", async () => {
    const bodies: any[] = [];
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    const client = new ReviewMethodClient(catalog, async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      await wait;
      return result(body.writing_action.action_id) as never;
    });
    const input = {
      expected_scope_version: 7,
      input_snapshot: { draft_version: 7, content_hash: HASH },
      force_new: true,
    };
    const first = client.start(input);
    const second = client.start(input);
    release();
    await Promise.all([first, second]);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      scope_type: "document",
      scope_id: DOCUMENT,
      novel_id: NOVEL,
      document_id: DOCUMENT,
      expected_scope_version: 7,
      writing_action: {
        preferences: { mode: "auto", semantic_mode: "off" },
      },
    });
  });

  it("recovers only through the document action endpoint", async () => {
    const key = `anw-review-action/1:${DOCUMENT}:v7:${HASH}:${JSON.stringify([
      OWNER, WORKSPACE, "tab", "ai-novel-writer", "novel", NOVEL, DOCUMENT,
    ])}`;
    const stored = JSON.stringify({
      action_id: ACTION,
      binding: catalog.binding,
      inputFingerprint: "c".repeat(64),
    });
    const calls: Array<[string, string | undefined]> = [];
    const client = new ReviewMethodClient(
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
      `/documents/${DOCUMENT}/writing-method-actions/${ACTION}?tab_id=tab`,
      "GET",
    ]]);
  });

  it("rejects a different document version", async () => {
    const client = new ReviewMethodClient(catalog);
    await expect(client.start({
      expected_scope_version: 8,
      input_snapshot: {},
      force_new: true,
    })).rejects.toThrow("不属于当前写作范围");
  });
});
