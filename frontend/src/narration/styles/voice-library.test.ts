import { describe, expect, it } from "vitest";
import { OFFICIAL_VOICE_LIBRARY_STYLES } from "./voice-library";

describe("official voice library layout contract", () => {
  it("responds to its own width inside a wide desktop drawer", () => {
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("container: anw-voice-library / inline-size");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toMatch(
      /@container anw-voice-library \(max-width: 960px\)[\s\S]*?\.anw-official-voice-library__grid\s*\{\s*grid-template-columns: minmax\(0, 1fr\)/,
    );
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).not.toMatch(/@media \(max-width:/);
  });

  it("keeps preview and details inside cards with shrinkable text and a narrow-panel action row", () => {
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("grid-template-columns: minmax(0, 1fr) minmax(76px, auto) minmax(76px, auto)");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toMatch(
      /@container anw-voice-library \(max-width: 560px\)[\s\S]*?\.anw-official-voice-card__selection\s*\{\s*grid-column: 1 \/ -1/,
    );
  });
});
