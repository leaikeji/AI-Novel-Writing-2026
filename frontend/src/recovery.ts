import { DBSchema, openDB } from "idb";

export interface RecoveryDraft {
  documentId: string;
  draftVersion: number;
  contentMarkdown: string;
  updatedAt: number;
}

interface RecoveryDatabase extends DBSchema {
  drafts: {
    key: string;
    value: RecoveryDraft;
  };
}

const databasePromise = openDB<RecoveryDatabase>("ai-novel-world-2026-recovery", 1, {
  upgrade(database) {
    database.createObjectStore("drafts", { keyPath: "documentId" });
  },
});

export async function loadRecoveryDraft(documentId: string): Promise<RecoveryDraft | undefined> {
  return (await databasePromise).get("drafts", documentId);
}

export async function saveRecoveryDraft(draft: RecoveryDraft): Promise<void> {
  await (await databasePromise).put("drafts", draft);
}

export async function clearRecoveryDraft(documentId: string): Promise<void> {
  await (await databasePromise).delete("drafts", documentId);
}
