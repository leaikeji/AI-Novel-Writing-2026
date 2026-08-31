import type { DocumentRecord } from "./types";


export function resolveSyncProgressDocument(
  current: DocumentRecord,
  preparedOverride?: unknown,
): DocumentRecord {
  if (
    typeof preparedOverride === "object"
    && preparedOverride !== null
    && typeof (preparedOverride as Partial<DocumentRecord>).id === "string"
    && typeof (preparedOverride as Partial<DocumentRecord>).draft_version === "number"
  ) {
    return preparedOverride as DocumentRecord;
  }
  return current;
}
