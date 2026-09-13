import { describe, expect, it, vi } from "vitest";
import { AIEditTransactionManager } from "../assistant-transactions";
import { createAssistantBodyFieldAdapter } from "../assistant-body-field";
import {
  acknowledgePendingLibrarySave,
  createRecoveryDraft,
  isCurrentRecoveryDraft,
  samePendingLibrarySave,
  type PendingLibrarySave,
} from "../recovery";
import type { AIApplyMeta } from "../assistant-fields";

const pending: PendingLibrarySave = {
  contentMarkdown: "潮水拍上木阶。",
  application: {
    schema_version: "selection-library-application/1",
    application_id: "10000000-0000-4000-8000-000000000001",
    job_id: "10000000-0000-4000-8000-000000000002",
    attempt: 1,
    base_draft_version: 4,
    base_content_hash: "a".repeat(64),
    replacement_sha256: "b".repeat(64),
    accepted_segment_ids: ["change-1"],
    library_check_report_id: "10000000-0000-4000-8000-000000000003",
    library_check_version: 2,
  },
};

describe("controlled selection metadata and existing recovery record", () => {
  it("passes one application identity through transaction, editor and autosave; undo is ordinary", async () => {
    let value = "潮声渐近。";
    const editorMetas: AIApplyMeta[] = [];
    const scheduleAutosave = vi.fn();
    const adapter = createAssistantBodyFieldAdapter({
      id: "chapter.body", label: "正文", getValue: () => value,
      getDirty: () => true, getSelection: () => null,
      hashValue: (text) => `hash:${text}`,
      applyEditorContent: (text, meta) => { value = text; editorMetas.push(meta); },
      scheduleAutosave, restoreSelection: vi.fn(), focus: vi.fn(),
    });
    const manager = new AIEditTransactionManager({ sha256: async (text) => `hash:${text}` });
    const result = await manager.apply({
      adapter, operation: "replace-selection", nextValue: pending.contentMarkdown,
      sourceValueSha256: `hash:${value}`, agentId: "ai-novel-writer",
      novelId: "novel", documentId: "document", libraryApplication: pending.application,
    });
    expect(result).toMatchObject({ ok: true, transaction: { transactionId: pending.application.application_id } });
    expect(editorMetas[0]?.libraryApplication).toEqual(pending.application);
    expect(editorMetas[0]?.libraryApplication).not.toBe(pending.application);
    expect(scheduleAutosave).toHaveBeenCalledWith(pending.contentMarkdown,
      expect.objectContaining({ libraryApplication: pending.application }));
    await manager.undo(adapter);
    expect(value).toBe("潮声渐近。");
    expect(editorMetas[1]?.operation).toBe("undo");
    expect(editorMetas[1]?.libraryApplication).toBeUndefined();
  });

  it("keeps the exact AI snapshot while later typing and refresh retain both texts", () => {
    const draft = createRecoveryDraft("chapter", 4, "潮水拍上木阶。他退了半步。", "a".repeat(64), 1, pending);
    const restored = structuredClone(draft);
    expect(restored.contentMarkdown).toBe("潮水拍上木阶。他退了半步。");
    expect(restored.pendingLibrarySave?.contentMarkdown).toBe(pending.contentMarkdown);
    expect(restored.pendingLibrarySave?.application).toEqual(pending.application);
    expect(draft.pendingLibrarySave?.application.accepted_segment_ids)
      .not.toBe(pending.application.accepted_segment_ids);
  });

  it("acknowledges only the saved application and rebases later typing without losing it", () => {
    const draft = createRecoveryDraft("chapter", 4, "潮水拍上木阶。他退了半步。", "a".repeat(64), 1, pending);
    const saved = acknowledgePendingLibrarySave(draft, pending, { draft_version: 5, content_hash: "c".repeat(64) });
    expect(saved).toMatchObject({ contentMarkdown: draft.contentMarkdown, draftVersion: 5, baseContentHash: "c".repeat(64) });
    expect(saved.pendingLibrarySave).toBeUndefined();
    expect(draft.pendingLibrarySave).toBeDefined();
    const newerReport = { ...pending, application: { ...pending.application, library_check_version: 3 } };
    expect(acknowledgePendingLibrarySave(draft, newerReport, { draft_version: 5, content_hash: "c".repeat(64) })).toBe(draft);
  });

  it("does not let legacy or outdated acknowledgements clear controlled recovery evidence", () => {
    const draft = createRecoveryDraft("chapter", 4, pending.contentMarkdown, "a".repeat(64), 1, pending);
    const legacy = { ...draft, pendingLibrarySave: undefined };
    expect(isCurrentRecoveryDraft(draft, legacy)).toBe(false);
    expect(isCurrentRecoveryDraft(draft, structuredClone(draft))).toBe(true);
    const changed = { ...draft, pendingLibrarySave: {
      ...pending, application: { ...pending.application, library_check_version: 3 },
    } };
    expect(isCurrentRecoveryDraft(changed, draft)).toBe(false);
    expect(samePendingLibrarySave(undefined, pending)).toBe(false);
  });
});
