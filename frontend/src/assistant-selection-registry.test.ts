import { describe, expect, it } from "vitest";

import {
  AssistantSelectionRegistry,
  SELECTION_REGISTRY_DEFAULT_CAPACITY,
  SELECTION_REGISTRY_DEFAULT_TTL_MS,
  type CreateSelectionInput,
  type SelectionRegistryScope,
  resolveSelectionDocumentId,
} from "./assistant-selection-registry";


const UUIDS = [
  "00000000-0000-4000-8000-000000000001",
  "00000000-0000-4000-8000-000000000002",
  "00000000-0000-4000-8000-000000000003",
  "00000000-0000-4000-8000-000000000004",
  "00000000-0000-4000-8000-000000000005",
] as const;


const BASE_SCOPE: SelectionRegistryScope = {
  agentId: "ai-novel-writer",
  novelId: "novel-1",
  documentId: "document-1",
  fieldId: "chapter.body",
  contextRevision: 7,
};


function selectionInput(
  overrides: Partial<CreateSelectionInput> = {},
): CreateSelectionInput {
  return {
    ...BASE_SCOPE,
    fieldValue: "abc",
    startUtf16: 1,
    endUtf16: 2,
    direction: "forward",
    ...overrides,
  };
}


function sequentialIds(ids: readonly string[] = UUIDS): () => string {
  let index = 0;
  return () => {
    const value = ids[index];
    if (!value) throw new Error("test UUID pool exhausted");
    index += 1;
    return value;
  };
}


describe("AssistantSelectionRegistry", () => {
  it("binds document editors to the real document and entity drafts to a namespaced resource", () => {
    const base = {
      novel: { id: "novel-1", title: "书" },
      page: { section: "roles" as const, view: "character-list" as const },
    };
    expect(resolveSelectionDocumentId({
      ...base,
      document: {
        id: "document-1",
        kind: "chapter",
        title: "章",
        draftVersion: 1,
        savedContentHash: "",
        dirty: false,
      },
    })).toBe("document-1");
    expect(resolveSelectionDocumentId({
      ...base,
      page: { ...base.page, modal: "character-editor" },
      entity: { type: "character", id: "character-1", title: "苏晚" },
    })).toBe("entity:character:character-1");
    expect(resolveSelectionDocumentId({
      ...base,
      page: { ...base.page, modal: "character-editor" },
      entity: { type: "character", title: "新增角色" },
    })).toBe("draft:novel-1:character:character-editor");
  });

  it("stores a UTF-16 range, direction, selected text and full-value SHA-256", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
      now: () => 1_000,
    });

    const record = await registry.create(selectionInput());

    expect(record).toEqual({
      ...BASE_SCOPE,
      selectionId: UUIDS[0],
      delivery: { kind: "unbound" },
      sessionId: undefined,
      jobId: undefined,
      startUtf16: 1,
      endUtf16: 2,
      direction: "forward",
      text: "b",
      sourceValueSha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      createdAtMs: 1_000,
      expiresAtMs: 1_000 + SELECTION_REGISTRY_DEFAULT_TTL_MS,
    });
    expect(Object.isFrozen(record)).toBe(true);
    expect(SELECTION_REGISTRY_DEFAULT_CAPACITY).toBe(50);
  });

  it("uses JavaScript UTF-16 offsets without splitting a surrogate pair", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });

    const record = await registry.create(selectionInput({
      fieldValue: "A😀B",
      startUtf16: 1,
      endUtf16: 3,
      direction: "backward",
    }));

    expect(record.text).toBe("😀");
    expect(record.endUtf16 - record.startUtf16).toBe(2);
  });

  it("keeps explicitly supplied legacy chat sessions on the chat delivery path", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });

    const record = await registry.create(selectionInput({ sessionId: "session-legacy" }));

    expect(record.sessionId).toBe("session-legacy");
    expect(record.delivery).toEqual({
      kind: "chat-session",
      sessionId: "session-legacy",
    });
    expect(registry.bindToEditorTask({
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      jobId: "job-1",
    })).toEqual({ ok: false, reason: "delivery-mismatch" });
  });

  it("rejects empty/out-of-range selections, weak ids and invalid registry bounds", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });

    await expect(registry.create(selectionInput({ endUtf16: 1 }))).rejects.toThrow(
      "non-empty valid UTF-16 range",
    );
    await expect(registry.create(selectionInput({ endUtf16: 99 }))).rejects.toThrow(
      "non-empty valid UTF-16 range",
    );
    await expect(new AssistantSelectionRegistry({
      idProvider: () => "guessable-1",
    }).create(selectionInput())).rejects.toThrow("must return a UUID");
    expect(() => new AssistantSelectionRegistry({ capacity: 51 })).toThrow(
      "must not exceed 50",
    );
    expect(() => new AssistantSelectionRegistry({ ttlMs: 0 })).toThrow(
      "ttlMs must be a positive safe integer",
    );
  });

  it("expires at the default 20-minute boundary and reports expiry once", async () => {
    let now = 5_000;
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
      now: () => now,
    });
    const record = await registry.create(selectionInput());

    now = record.expiresAtMs - 1;
    expect(registry.get(record.selectionId)).toBe(record);
    now = record.expiresAtMs;
    expect(registry.bindToSession({
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      sessionId: "session-1",
    })).toEqual({ ok: false, reason: "expired" });
    expect(registry.get(record.selectionId)).toBeUndefined();
  });

  it("evicts the oldest registration by FIFO order at capacity", async () => {
    const registry = new AssistantSelectionRegistry({
      capacity: 3,
      idProvider: sequentialIds(),
    });
    const first = await registry.create(selectionInput({ contextRevision: 1 }));
    const second = await registry.create(selectionInput({ contextRevision: 2 }));
    const third = await registry.create(selectionInput({ contextRevision: 3 }));
    const fourth = await registry.create(selectionInput({ contextRevision: 4 }));

    expect(registry.get(first.selectionId)).toBeUndefined();
    expect(registry.list().map(({ selectionId }) => selectionId)).toEqual([
      second.selectionId,
      third.selectionId,
      fourth.selectionId,
    ]);
  });

  it("atomically binds the first session and never rebinds it", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });
    const record = await registry.create(selectionInput());
    const request = {
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      sessionId: "session-1",
    };

    const first = registry.bindToSession(request);
    const sameSession = registry.bindToSession(request);
    const otherSession = registry.bindToSession({
      ...request,
      sessionId: "session-2",
    });

    expect(first.ok && first.status).toBe("bound");
    expect(sameSession.ok && sameSession.status).toBe("already-bound");
    expect(otherSession).toEqual({ ok: false, reason: "session-mismatch" });
    expect(registry.get(record.selectionId)?.sessionId).toBe("session-1");
    expect(registry.get(record.selectionId)?.delivery).toEqual({
      kind: "chat-session",
      sessionId: "session-1",
    });
  });

  it("atomically binds the editor task and never crosses into chat delivery", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });
    const record = await registry.create(selectionInput());
    const request = {
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      jobId: "job-1",
    };

    expect(registry.bindToEditorTask(request)).toMatchObject({
      ok: true,
      status: "bound",
    });
    expect(registry.bindToEditorTask(request)).toMatchObject({
      ok: true,
      status: "already-bound",
    });
    expect(registry.bindToEditorTask({ ...request, jobId: "job-2" })).toEqual({
      ok: false,
      reason: "job-mismatch",
    });
    expect(registry.bindToSession({
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      sessionId: "session-1",
    })).toEqual({ ok: false, reason: "delivery-mismatch" });
    expect(registry.get(record.selectionId)).toMatchObject({
      jobId: "job-1",
      sessionId: undefined,
      delivery: { kind: "editor-task", jobId: "job-1" },
    });
  });

  it("does not bind when Agent, work, document, field or revision changed", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });
    const record = await registry.create(selectionInput());

    const cases = [
      [{ agentId: "other-agent" }, "agent-mismatch"],
      [{ novelId: "novel-2" }, "novel-mismatch"],
      [{ documentId: "document-2" }, "document-mismatch"],
      [{ fieldId: "chapter.title" }, "field-mismatch"],
      [{ contextRevision: 8 }, "context-revision-mismatch"],
    ] as const;

    for (const [override, reason] of cases) {
      expect(registry.bindToSession({
        ...BASE_SCOPE,
        selectionId: record.selectionId,
        sessionId: "session-1",
        ...override,
      })).toEqual({ ok: false, reason });
    }
    expect(registry.get(record.selectionId)?.sessionId).toBeUndefined();
  });

  it("requires the bound scope/session and unchanged full field before apply", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });
    const record = await registry.create(selectionInput());
    const applyInput = {
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      sessionId: "session-1",
      fieldValue: "abc",
    };

    await expect(registry.validateForApply(applyInput)).resolves.toEqual({
      ok: false,
      reason: "session-unbound",
    });
    registry.bindToSession(applyInput);
    await expect(registry.validateForApply(applyInput)).resolves.toMatchObject({
      ok: true,
      record: { selectionId: record.selectionId },
    });
    await expect(registry.validateForApply({
      ...applyInput,
      fieldValue: "abC",
    })).resolves.toEqual({ ok: false, reason: "source-value-changed" });
    await expect(registry.validateForApply({
      ...applyInput,
      sessionId: "session-2",
    })).resolves.toEqual({ ok: false, reason: "session-mismatch" });
  });

  it("requires the bound editor job and unchanged full field before apply", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });
    const record = await registry.create(selectionInput());
    const applyInput = {
      ...BASE_SCOPE,
      selectionId: record.selectionId,
      jobId: "job-1",
      fieldValue: "abc",
    };

    await expect(registry.validateForEditorTaskApply(applyInput)).resolves.toEqual({
      ok: false,
      reason: "job-unbound",
    });
    registry.bindToEditorTask(applyInput);
    await expect(registry.validateForEditorTaskApply(applyInput)).resolves.toMatchObject({
      ok: true,
      record: { selectionId: record.selectionId },
    });
    await expect(registry.validateForEditorTaskApply({
      ...applyInput,
      fieldValue: "abC",
    })).resolves.toEqual({ ok: false, reason: "source-value-changed" });
    await expect(registry.validateForEditorTaskApply({
      ...applyInput,
      jobId: "job-2",
    })).resolves.toEqual({ ok: false, reason: "job-mismatch" });
  });

  it("cleans expired, previous-work and destroyed-field selections", async () => {
    let now = 10;
    const registry = new AssistantSelectionRegistry({
      ttlMs: 100,
      idProvider: sequentialIds(),
      now: () => now,
    });
    const expired = await registry.create(selectionInput({ novelId: "novel-old" }));
    now = 50;
    const previousWork = await registry.create(selectionInput({ novelId: "novel-old" }));
    const destroyedField = await registry.create(selectionInput({
      fieldId: "chapter.title",
    }));
    const retained = await registry.create(selectionInput());

    now = 111;
    expect(registry.clearExpired()).toBe(1);
    expect(registry.get(expired.selectionId)).toBeUndefined();
    expect(registry.clearForNovelSwitch("novel-1")).toBe(1);
    expect(registry.get(previousWork.selectionId)).toBeUndefined();
    expect(registry.clearField({
      novelId: "novel-1",
      documentId: "document-1",
      fieldId: "chapter.title",
    })).toBe(1);
    expect(registry.list()).toEqual([retained]);
  });

  it("clears page memory on dispose and rejects later reuse", async () => {
    const registry = new AssistantSelectionRegistry({
      idProvider: sequentialIds(),
    });
    await registry.create(selectionInput());

    registry.dispose();
    registry.dispose();

    expect(() => registry.size()).toThrow("registry is disposed");
    await expect(registry.create(selectionInput())).rejects.toThrow(
      "registry is disposed",
    );
  });
});
