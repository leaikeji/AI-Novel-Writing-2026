import { describe, expect, it } from "vitest";
import {
  ChapterCreativeMethodClient,
  chapterCreativeMethodCatalog,
  managedChapterCreativeInputSnapshot,
  type ChapterCreativeMethodCatalog,
} from "./chapter-creative";

const OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c";
const WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e";
const NOVEL = "11111111-1111-4111-8111-111111111111";
const DRAFT = "22222222-2222-4222-8222-222222222222";
const ACTION = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "44444444-4444-4444-8444-444444444444";

const catalog: ChapterCreativeMethodCatalog = {
  available: true,
  catalogAvailable: true,
  displayNames: {},
  chapterDraftId: DRAFT,
  chapterDraftVersion: 4,
  kind: "chapter_outline",
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
    kind: "chapter_outline",
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

describe("chapterCreativeMethodCatalog", () => {
  it("accepts only the exact novel scope and chapter task gate", async () => {
    const loaded = await chapterCreativeMethodCatalog(
      NOVEL,
      DRAFT,
      4,
      "chapter_outline",
      "tab",
      async path => {
        expect(path).toContain(`novel_id=${NOVEL}`);
        expect(path).toContain("creative_kind=chapter_outline");
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
    expect(loaded.chapterDraftId).toBe(DRAFT);
    expect(loaded.chapterDraftVersion).toBe(4);
    expect(loaded.kind).toBe("chapter_outline");
  });
});

describe("ChapterCreativeMethodClient", () => {
  it("binds one exact chapter draft version to one action", async () => {
    const bodies: any[] = [];
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    const client = new ChapterCreativeMethodClient(catalog, async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      await wait;
      return result(body.writing_action.action_id) as never;
    });
    const input = {
      kind: "chapter_outline" as const,
      expected_scope_version: 4,
      input_snapshot: { novel: {}, chapter_number: 1, rewrite_attempt: 1 },
      force_new: true,
    };
    const first = client.start(input);
    const second = client.start(input);
    release();
    await Promise.all([first, second]);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({
      scope_type: "chapter_creation",
      scope_id: DRAFT,
      novel_id: NOVEL,
      expected_scope_version: 4,
      writing_action: {
        preferences: { mode: "auto", semantic_mode: "off" },
      },
      input_snapshot: { rewrite_attempt: 1 },
    });
    expect(bodies[0].input_snapshot).not.toHaveProperty("novel");
  });

  it("removes browser story data from managed chapter requests", () => {
    expect(managedChapterCreativeInputSnapshot(
      "chapter_storyline_recommendation",
      { novel: { genre: "伪造题材" }, storylines: [{ id: "foreign" }] },
    )).toEqual({});
    expect(managedChapterCreativeInputSnapshot(
      "chapter_outline",
      {
        rewrite_attempt: 2,
        previous_chapter: { ending: "伪造前章" },
        required_roles: [{ id: "foreign" }],
      },
    )).toEqual({ rewrite_attempt: 2 });
  });

  it("recovers only through the novel-scoped endpoint", async () => {
    const key = `anw-chapter-creative-action/1:chapter_outline:${DRAFT}:v4:${JSON.stringify([
      OWNER, WORKSPACE, "tab", "ai-novel-writer", "novel", NOVEL, null,
    ])}`;
    const stored = JSON.stringify({
      action_id: ACTION,
      binding: catalog.binding,
      inputFingerprint: "b".repeat(64),
    });
    const calls: Array<[string, string | undefined]> = [];
    const client = new ChapterCreativeMethodClient(
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

  it("rejects a different chapter task on the frozen catalog", async () => {
    const client = new ChapterCreativeMethodClient(catalog);
    await expect(client.start({
      kind: "chapter_storyline_recommendation",
      expected_scope_version: 4,
      input_snapshot: {},
      force_new: true,
    })).rejects.toThrow("不属于当前写作范围");
  });
});
