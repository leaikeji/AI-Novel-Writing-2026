import { DBSchema, IDBPDatabase, openDB } from "idb";
import type { SelectionLibraryApplication } from "./types";

/** Keep the AI snapshot separate from later typing until its guarded save is acknowledged. */
export interface PendingLibrarySave {
  contentMarkdown: string;
  application: SelectionLibraryApplication;
}

export interface RecoveryDraft {
  documentId: string;
  draftVersion: number;
  contentMarkdown: string;
  updatedAt: number;
  draftId?: string;
  baseContentHash?: string;
  pendingLibrarySave?: PendingLibrarySave;
}

export type RecoveryDraftIdentity = Pick<
  RecoveryDraft,
  "documentId" | "draftVersion" | "contentMarkdown"
> & Partial<Pick<RecoveryDraft, "draftId" | "baseContentHash" | "pendingLibrarySave">>;

interface RecoveryDatabase extends DBSchema {
  drafts: {
    key: string;
    value: RecoveryDraft;
  };
}

let databasePromise: Promise<IDBPDatabase<RecoveryDatabase>> | null = null;

function recoveryDatabase(): Promise<IDBPDatabase<RecoveryDatabase>> {
  if (!databasePromise) {
    databasePromise = openDB<RecoveryDatabase>("ai-novel-world-2026-recovery", 1, {
      upgrade(database) {
        database.createObjectStore("drafts", { keyPath: "documentId" });
      },
    });
  }
  return databasePromise;
}

export async function loadRecoveryDraft(documentId: string): Promise<RecoveryDraft | undefined> {
  return (await recoveryDatabase()).get("drafts", documentId);
}

export async function saveRecoveryDraft(draft: RecoveryDraft): Promise<void> {
  await (await recoveryDatabase()).put("drafts", draft);
}

export async function clearRecoveryDraft(documentId: string): Promise<void> {
  await (await recoveryDatabase()).delete("drafts", documentId);
}

/** Remove only the document keys returned by the completed server-side purge. */
export async function clearPurgedRecoveryDrafts(
  documentIds: readonly string[],
): Promise<number> {
  const exactIds = [...new Set(documentIds.filter((value) => typeof value === "string" && value))];
  if (!exactIds.length) return 0;
  const database = await recoveryDatabase();
  const transaction = database.transaction("drafts", "readwrite");
  let removed = 0;
  for (const documentId of exactIds) {
    if (await transaction.store.getKey(documentId) !== undefined) {
      await transaction.store.delete(documentId);
      removed += 1;
    }
  }
  await transaction.done;
  return removed;
}

export function isCurrentRecoveryDraft(
  current: RecoveryDraft,
  expected: RecoveryDraftIdentity,
): boolean {
  if (
    current.documentId !== expected.documentId
    || current.draftVersion !== expected.draftVersion
    || current.contentMarkdown !== expected.contentMarkdown
  ) return false;
  if (expected.draftId !== undefined && current.draftId !== expected.draftId) return false;
  if (
    expected.baseContentHash !== undefined
    && current.baseContentHash !== expected.baseContentHash
  ) return false;
  // A legacy acknowledgement must never delete a pending controlled application.
  if (!samePendingLibrarySave(current.pendingLibrarySave, expected.pendingLibrarySave)) return false;
  return true;
}

export function samePendingLibrarySave(
  left: PendingLibrarySave | undefined,
  right: PendingLibrarySave | undefined,
): boolean {
  if (!left || !right) return left === right;
  return left.contentMarkdown === right.contentMarkdown
    && JSON.stringify(left.application) === JSON.stringify(right.application);
}

export function clonePendingLibrarySave(pending: PendingLibrarySave): PendingLibrarySave {
  return {
    contentMarkdown: pending.contentMarkdown,
    application: {
      ...pending.application,
      accepted_segment_ids: pending.application.accepted_segment_ids
        ? [...pending.application.accepted_segment_ids] : pending.application.accepted_segment_ids,
    },
  };
}

/** Rebase only the acknowledged local record, retaining all later author text. */
export function acknowledgePendingLibrarySave(
  current: RecoveryDraft,
  acknowledged: PendingLibrarySave,
  saved: { draft_version: number; content_hash: string },
): RecoveryDraft {
  if (!samePendingLibrarySave(current.pendingLibrarySave, acknowledged)) return current;
  return createRecoveryDraft(
    current.documentId, saved.draft_version, current.contentMarkdown, saved.content_hash,
  );
}

/** CAS update protects a newer recovery record written by another browser tab. */
export async function replaceRecoveryDraftIfCurrent(
  expected: RecoveryDraftIdentity,
  replacement: RecoveryDraft,
): Promise<boolean> {
  if (expected.documentId !== replacement.documentId) return false;
  const database = await recoveryDatabase();
  const transaction = database.transaction("drafts", "readwrite");
  const current = await transaction.store.get(expected.documentId);
  if (!current || !isCurrentRecoveryDraft(current, expected)) {
    await transaction.done;
    return false;
  }
  await transaction.store.put(replacement);
  await transaction.done;
  return true;
}

/** Delete only the exact local draft acknowledged by a successful save. */
export async function clearRecoveryDraftIfCurrent(
  expected: RecoveryDraftIdentity,
): Promise<boolean> {
  const database = await recoveryDatabase();
  const transaction = database.transaction("drafts", "readwrite");
  const current = await transaction.store.get(expected.documentId);
  if (!current || !isCurrentRecoveryDraft(current, expected)) {
    await transaction.done;
    return false;
  }
  await transaction.store.delete(expected.documentId);
  await transaction.done;
  return true;
}

export function createRecoveryDraft(
  documentId: string,
  draftVersion: number,
  contentMarkdown: string,
  baseContentHash: string,
  now = Date.now(),
  pendingLibrarySave?: PendingLibrarySave,
): RecoveryDraft {
  const randomId = globalThis.crypto?.randomUUID?.();
  return {
    documentId,
    draftVersion,
    contentMarkdown,
    updatedAt: now,
    ...(randomId ? { draftId: randomId } : {}),
    ...(baseContentHash ? { baseContentHash } : {}),
    ...(pendingLibrarySave ? { pendingLibrarySave: clonePendingLibrarySave(pendingLibrarySave) } : {}),
  };
}
