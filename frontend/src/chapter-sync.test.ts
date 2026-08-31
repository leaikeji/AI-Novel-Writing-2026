import { describe, expect, it } from "vitest";

import { resolveSyncProgressDocument } from "./chapter-sync";
import type { DocumentRecord } from "./types";


function documentRecord(id: string, draftVersion: number): DocumentRecord {
  return {
    id,
    draft_version: draftVersion,
  } as DocumentRecord;
}


describe("chapter sync progress source", () => {
  it("ignores the React click event passed by an onClick handler", () => {
    const current = documentRecord("chapter-1", 4);
    const clickEvent = { type: "click", currentTarget: { tagName: "BUTTON" } };

    expect(resolveSyncProgressDocument(current, clickEvent)).toBe(current);
  });

  it("keeps an explicitly prepared document after saving", () => {
    const current = documentRecord("chapter-1", 4);
    const prepared = documentRecord("chapter-1", 5);

    expect(resolveSyncProgressDocument(current, prepared)).toBe(prepared);
  });
});
