import { describe, expect, it } from "vitest";

import { isCurrentRecoveryDraft, type RecoveryDraft } from "./recovery";
import { shouldApplyLifecycleNotice } from "./recycle-bin";


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";


describe("recycle and local recovery races", () => {
  const savedRequestDraft: RecoveryDraft = {
    documentId: "doc-1",
    draftVersion: 4,
    contentMarkdown: "旧标签页已提交的正文",
    updatedAt: 10,
    draftId: "draft-old",
    baseContentHash: "hash-v4",
  };

  it("does not clear another tab's newer draft after a late save response", () => {
    const newerTabDraft: RecoveryDraft = {
      ...savedRequestDraft,
      contentMarkdown: "另一个标签页的更新正文",
      updatedAt: 20,
      draftId: "draft-new",
    };
    expect(isCurrentRecoveryDraft(newerTabDraft, savedRequestDraft)).toBe(false);
    expect(isCurrentRecoveryDraft(savedRequestDraft, savedRequestDraft)).toBe(true);
  });

  it("keeps compatibility with old records while requiring the expected baseline", () => {
    const legacy: RecoveryDraft = {
      documentId: "doc-1",
      draftVersion: 4,
      contentMarkdown: "旧标签页已提交的正文",
      updatedAt: 1,
    };
    expect(isCurrentRecoveryDraft(legacy, {
      documentId: legacy.documentId,
      draftVersion: legacy.draftVersion,
      contentMarkdown: legacy.contentMarkdown,
    })).toBe(true);
    expect(isCurrentRecoveryDraft(legacy, savedRequestDraft)).toBe(false);
  });

  it("deduplicates old lifecycle versions and isolates other novels", () => {
    const notice = {
      novel_id: NOVEL_ID,
      event_id: "22222222-2222-4222-8222-222222222222",
      action: "recycled" as const,
      version: 8,
    };
    expect(shouldApplyLifecycleNotice(notice, NOVEL_ID, 7)).toBe(true);
    expect(shouldApplyLifecycleNotice(notice, NOVEL_ID, 8)).toBe(false);
    expect(shouldApplyLifecycleNotice(notice, "33333333-3333-4333-8333-333333333333", 1)).toBe(false);
  });
});
