import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import type { AIApplyMeta } from "./assistant-fields";
import type * as RelationshipContext from "./relationship-editor";


let relationshipContext: typeof RelationshipContext;


const NOVEL = { id: "novel-1", title: "潮声替我说晚安" };
const CHARACTER_IDS = ["character-1", "character-2"] as const;


function runtime(): NovelAssistantContextRuntime {
  const value = new NovelAssistantContextRuntime();
  value.setHostBinding("ai-novel-writer", "session-1");
  return value;
}


function draft(
  key = "relationship-1",
  id: string | null = "relationship-1",
): RelationshipContext.RelationshipDraft {
  return {
    key,
    id,
    expected_version: id ? 3 : null,
    source_character_id: CHARACTER_IDS[0],
    target_character_id: CHARACTER_IDS[1],
    directionality: "undirected",
    relation_kind: "ally",
    label: "盟友",
    description: "在旧电台共同追查档案。",
    status: "active",
    original: id ? "persisted-baseline" : null,
  };
}


function pageScope(contextRuntime: NovelAssistantContextRuntime) {
  return contextRuntime.mountScope({
    id: "test:page:relationship-graph",
    kind: "page",
    envelope: {
      agentId: "ai-novel-writer",
      novel: NOVEL,
      page: { section: "roles", view: "relationship-graph" },
      entity: { type: "novel", id: NOVEL.id, title: NOVEL.title },
    },
  });
}


async function meta(value: string): Promise<AIApplyMeta> {
  return {
    transactionId: "transaction-1",
    agentId: "ai-novel-writer",
    sessionId: "session-1",
    operation: "replace",
    sourceValueSha256: await relationshipContext.hashRelationshipAssistantField(value),
    appliedAt: "2026-08-25T10:00:00.000Z",
  };
}


beforeAll(async () => {
  const Component = Object.assign(() => null, {
    Group: () => null,
    TextArea: () => null,
  });
  const components = new Proxy({ Input: Component, Radio: Component }, {
    get: (target, key) => (
      key === "Input" ? target.Input : key === "Radio" ? target.Radio : Component
    ),
  });
  vi.stubGlobal("window", {
    QwenPaw: {
      host: {
        React: { createElement: () => null },
        ReactDOM: {},
        antd: components,
        antdIcons: new Proxy({}, { get: () => Component }),
      },
    },
  });
  relationshipContext = await import("./relationship-editor");
});


afterAll(() => vi.unstubAllGlobals());


describe("RelationshipEditor assistant context", () => {
  it("opens the frozen modal, registers all safe controlled fields, applies dirty without saving, and cleans up", async () => {
    const contextRuntime = runtime();
    const page = pageScope(contextRuntime);
    let current = draft();
    const dirty = new Set<string>();
    const originalSaveButton = vi.fn();
    const focus = vi.fn();
    const binding = relationshipContext.mountRelationshipAssistantScope({
      runtime: contextRuntime,
      novelId: NOVEL.id,
      novelTitle: NOVEL.title,
      draftKey: current.key,
      characterIds: CHARACTER_IDS,
      getDraft: () => current,
      applyDraftField: (field, value) => {
        if (field === "label") current = { ...current, label: value };
        else if (field === "description") current = { ...current, description: value };
        else throw new Error(`unexpected test field: ${field}`);
      },
      getDirty: (fieldId) => dirty.has(fieldId),
      markDirty: (fieldId) => { dirty.add(fieldId); },
      focus,
    });

    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "modal",
      section: "roles",
      view: "relationship-graph",
      modal: "relationship-editor",
      fieldCount: 6,
      dirtyFieldCount: 0,
    });
    expect([...binding.adapters.keys()]).toEqual([
      "relationship.sourceCharacterId",
      "relationship.targetCharacterId",
      "relationship.kind",
      "relationship.directionality",
      "relationship.label",
      "relationship.description",
    ]);
    const label = binding.adapters.get(
      relationshipContext.RELATIONSHIP_ASSISTANT_FIELD_IDS.label,
    )!;
    const receipt = await label.applyValueWithReceipt("共同守密人", await meta(current.label));

    expect(receipt).toMatchObject({
      fieldId: "relationship.label",
      persistence: "explicit-save",
      saveRequested: false,
      before: { value: "盟友", dirty: false },
      after: { value: "共同守密人", dirty: true },
    });
    expect(current.label).toBe("共同守密人");
    expect(originalSaveButton).not.toHaveBeenCalled();
    expect(contextRuntime.capture()?.context).toMatchObject({
      novel: NOVEL,
      page: {
        section: "roles",
        view: "relationship-graph",
        modal: "relationship-editor",
      },
      entity: {
        type: "relationship",
        id: "relationship-1",
      },
      editing: {
        fields: expect.arrayContaining([
          expect.objectContaining({
            id: "relationship.label",
            value: "共同守密人",
            dirty: true,
            persistence: "explicit-save",
          }),
        ]),
      },
    });

    label.focus();
    expect(focus).toHaveBeenCalledWith("relationship.label");
    binding.dispose();
    expect(() => label.getValue()).toThrow("disposed");
    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "page",
      view: "relationship-graph",
      fieldCount: 0,
    });
    page.dispose();
  });

  it("selects a focused persisted draft or the first new draft and keeps its stable key as entity id", () => {
    const existing = draft("relationship-2", "relationship-2");
    const firstNew = draft("new-stable-key-1", null);
    const secondNew = draft("new-stable-key-2", null);
    const drafts = [firstNew, existing, secondNew];

    expect(
      relationshipContext.selectRelationshipAssistantDraft(drafts, existing.id),
    ).toBe(existing);
    expect(
      relationshipContext.selectRelationshipAssistantDraft(drafts, null),
    ).toBe(firstNew);
    expect(
      relationshipContext.selectRelationshipAssistantDraft([existing], null),
    ).toBe(existing);

    const contextRuntime = runtime();
    let current = firstNew;
    const binding = relationshipContext.mountRelationshipAssistantScope({
      runtime: contextRuntime,
      novelId: NOVEL.id,
      novelTitle: NOVEL.title,
      draftKey: firstNew.key,
      characterIds: CHARACTER_IDS,
      getDraft: () => current,
      applyDraftField: (field, value) => {
        if (field === "label") current = { ...current, label: value };
      },
      getDirty: () => true,
      markDirty: vi.fn(),
      focus: vi.fn(),
    });

    expect(contextRuntime.capture()?.context.entity).toMatchObject({
      type: "relationship",
      id: "new-stable-key-1",
    });
    binding.dispose();
  });

  it("uses full WebCrypto SHA-256 and rejects an out-of-scope Select value before mutation", async () => {
    expect(await relationshipContext.hashRelationshipAssistantField("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    const contextRuntime = runtime();
    let current = draft();
    const applyDraftField = vi.fn();
    const markDirty = vi.fn();
    const binding = relationshipContext.mountRelationshipAssistantScope({
      runtime: contextRuntime,
      novelId: NOVEL.id,
      novelTitle: NOVEL.title,
      draftKey: current.key,
      characterIds: CHARACTER_IDS,
      getDraft: () => current,
      applyDraftField,
      getDirty: () => false,
      markDirty,
      focus: vi.fn(),
    });
    const source = binding.adapters.get(
      relationshipContext.RELATIONSHIP_ASSISTANT_FIELD_IDS.sourceCharacterId,
    )!;

    await expect(source.applyValue(
      "character-from-another-novel",
      await meta(current.source_character_id),
    )).rejects.toThrow("起点角色值无效");
    expect(applyDraftField).not.toHaveBeenCalled();
    expect(markDirty).not.toHaveBeenCalled();
    expect(current.source_character_id).toBe(CHARACTER_IDS[0]);
    binding.dispose();
  });
});
