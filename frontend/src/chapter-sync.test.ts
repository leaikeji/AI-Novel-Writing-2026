import { describe, expect, it } from "vitest";

import {
  resolveSyncProgressDocument,
  reusableSyncProgressProposal,
  reusableSyncProgressRevisionId,
} from "./chapter-sync";
import type { DocumentRecord, IntelligenceProposalRecord } from "./types";


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

  it("reuses the current base revision when the saved body is unchanged", () => {
    const current = {
      ...documentRecord("chapter-1", 4),
      base_revision_id: "revision-3",
      content_hash: "same-hash",
      revisions: [
        { id: "revision-3", content_hash: "same-hash" },
      ],
    } as DocumentRecord;

    expect(reusableSyncProgressRevisionId(current)).toBe("revision-3");
  });

  it("requires a checkpoint when the working copy differs from its base revision", () => {
    const current = {
      ...documentRecord("chapter-1", 5),
      base_revision_id: "revision-3",
      content_hash: "working-hash",
      revisions: [
        { id: "revision-3", content_hash: "base-hash" },
      ],
    } as DocumentRecord;

    expect(reusableSyncProgressRevisionId(current)).toBeNull();
  });

  it("reopens the completed proposal for the unchanged revision", () => {
    const reusable = {
      id: "proposal-ready",
      chapter_revision_id: "revision-3",
      source_current: true,
      state: "accepted",
    } as IntelligenceProposalRecord;
    const running = {
      id: "proposal-running",
      chapter_revision_id: "revision-3",
      source_current: true,
      state: "running",
    } as IntelligenceProposalRecord;

    expect(reusableSyncProgressProposal([running, reusable], "revision-3")).toBe(reusable);
    expect(reusableSyncProgressProposal([running], "revision-3")).toBeNull();
  });
});
