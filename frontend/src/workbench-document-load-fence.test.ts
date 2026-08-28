import { describe, expect, it } from "vitest";

import { canReuseActiveDocumentLoad } from "./workbench-document-load-fence";


describe("workbench document load fence", () => {
  it("reuses only the exact active document and current editor generation", () => {
    expect(canReuseActiveDocumentLoad({
      requestedDocumentId: "chapter-a",
      activeDocumentId: "chapter-a",
      activeGeneration: 7,
      surfaceLease: { documentId: "chapter-a", generation: 7 },
    })).toBe(true);
    expect(canReuseActiveDocumentLoad({
      requestedDocumentId: "chapter-b",
      activeDocumentId: "chapter-a",
      activeGeneration: 7,
      surfaceLease: { documentId: "chapter-a", generation: 7 },
    })).toBe(false);
    expect(canReuseActiveDocumentLoad({
      requestedDocumentId: "chapter-a",
      activeDocumentId: "chapter-a",
      activeGeneration: 8,
      surfaceLease: { documentId: "chapter-a", generation: 7 },
    })).toBe(false);
  });

  it("does not reuse a closed or not-yet-mounted editor", () => {
    expect(canReuseActiveDocumentLoad({
      requestedDocumentId: "chapter-a",
      activeDocumentId: "chapter-a",
      activeGeneration: 7,
      surfaceLease: null,
    })).toBe(false);
  });
});
