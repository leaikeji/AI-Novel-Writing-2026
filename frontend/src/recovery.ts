import { DBSchema, IDBPDatabase, openDB } from "idb";

export interface RecoveryDraft {
  documentId: string;
  draftVersion: number;
  contentMarkdown: string;
  updatedAt: number;
  draftId?: string;
  baseContentHash?: string;
}

export type RecoveryDraftIdentity = Pick<
  RecoveryDraft,
  "documentId" | "draftVersion" | "contentMarkdown"
> & Partial<Pick<RecoveryDraft, "draftId" | "baseContentHash">>;

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
): RecoveryDraft {
  const randomId = globalThis.crypto?.randomUUID?.();
  return {
    documentId,
    draftVersion,
    contentMarkdown,
    updatedAt: now,
    ...(randomId ? { draftId: randomId } : {}),
    ...(baseContentHash ? { baseContentHash } : {}),
  };
}
