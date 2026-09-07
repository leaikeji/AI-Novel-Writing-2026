import { describe, expect, it } from "vitest";

import type { StartCreativeGenerationPayload } from "../api";
import { SelectionEditMethodGenerationClient } from "./selection";

const OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c";
const WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e";
const NOVEL = "11111111-1111-4111-8111-111111111111";
const DOCUMENT = "22222222-2222-4222-8222-222222222222";
const SELECTION = "33333333-3333-4333-8333-333333333333";
const DISPATCH = "44444444-4444-4444-8444-444444444444";
const JOB = "55555555-5555-4555-8555-555555555555";
const HASH = "a".repeat(64);

const payload: StartCreativeGenerationPayload = {
  scope_type: "document",
  scope_id: DOCUMENT,
  kind: "selection_edit",
  novel_id: NOVEL,
  document_id: DOCUMENT,
  target_character_count: null,
  force_new: false,
  input_snapshot: {
    schema_version: 1,
    selection_id: SELECTION,
    operation: "polish",
    custom_instruction: null,
    use_novel_context: false,
    target: {
      novel_id: NOVEL,
      document_id: DOCUMENT,
      entity_type: "document",
      entity_id: DOCUMENT,
      field_id: "chapter.body",
      field_label: "正文",
      persistence: "autosave",
      context_revision: 7,
    },
    base: {
      field_value_sha256: HASH,
      persistence_version_kind: "draft",
      persistence_version: 3,
      start_utf16: 0,
      end_utf16: 2,
      selection_text: "旧句",
      selection_text_sha256: "b".repeat(64),
      before: "",
      after: "仍在这里。",
    },
  },
};

function methodResult(actionId: string) {
  return {
    id: JOB,
    scope_type: "document",
    scope_id: DOCUMENT,
    novel_id: NOVEL,
    document_id: DOCUMENT,
    kind: "selection_edit",
    state: "ready",
    writing_method: {
      schema_version: "writing-method-status/1",
      action_id: actionId,
      dispatch_id: DISPATCH,
      state: "dispatched",
      selected_ids: ["suspense-writing"],
      omitted_ids: [],
      method_input_hash: "c".repeat(64),
      semantic_enabled: false,
      auxiliary_calls: 0,
      job_ref: `creative:${JOB}`,
    },
  };
}

function catalog() {
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
  };
}

describe("SelectionEditMethodGenerationClient", () => {
  it("loads the operation-specific catalog and sends one managed action", async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    const client = new SelectionEditMethodGenerationClient({
      tabId: "tab",
      request: async (path, init) => {
        calls.push([path, init]);
        if (path.startsWith("/writing-skills?")) return catalog() as never;
        const body = JSON.parse(String(init?.body));
        return methodResult(body.writing_action.action_id) as never;
      },
    });

    const [first, second] = await Promise.all([
      client.start(payload),
      client.start(payload),
    ]);

    expect(first.id).toBe(JOB);
    expect(second.id).toBe(JOB);
    expect(calls).toHaveLength(2);
    expect(calls[0][0]).toContain("creative_kind=selection_edit");
    expect(calls[0][0]).toContain("selection_operation=polish");
    const body = JSON.parse(String(calls[1][1]?.body));
    expect(body).toMatchObject({
      scope_type: "document",
      scope_id: DOCUMENT,
      expected_scope_version: 3,
      writing_action: {
        preferences: { mode: "auto", semantic_mode: "off" },
      },
    });
    expect(client.currentStatus?.state).toBe("dispatched");
  });

  it("uses GET recovery after a lost POST response and never repeats POST", async () => {
    let actionId = "";
    let posts = 0;
    let gets = 0;
    const client = new SelectionEditMethodGenerationClient({
      tabId: "tab",
      request: async (path, init) => {
        if (path.startsWith("/writing-skills?")) return catalog() as never;
        if (init?.method === "POST") {
          posts += 1;
          actionId = JSON.parse(String(init.body)).writing_action.action_id;
          throw new Error("response lost");
        }
        gets += 1;
        expect(path).toBe(
          `/documents/${DOCUMENT}/writing-method-actions/${actionId}?tab_id=tab`,
        );
        return methodResult(actionId) as never;
      },
    });

    const result = await client.start(payload);
    expect(result.id).toBe(JOB);
    expect(posts).toBe(1);
    expect(gets).toBe(1);
  });
});
