import { describe, expect, it } from "vitest";

import { CHARACTER_WORKSPACE_CSS } from "./styles";

describe("character workspace desktop layout contract", () => {
  it("uses the approved 1240px writing dialog without a mobile redesign", () => {
    expect(CHARACTER_WORKSPACE_CSS).toContain("width: min(1240px, calc(100vw - 64px))");
    expect(CHARACTER_WORKSPACE_CSS).toContain("grid-template-columns: repeat(12");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-state-layout");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-fact-table-row");
    expect(CHARACTER_WORKSPACE_CSS).not.toContain("@media (max-width: 720px)");
    expect(CHARACTER_WORKSPACE_CSS).toContain("max-height: calc(100dvh - 48px)");
    expect(CHARACTER_WORKSPACE_CSS).toContain("position: sticky");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-workspace-tabs { display: flex; flex: 0 0 auto");
    expect(CHARACTER_WORKSPACE_CSS).toContain(":focus-visible");
    expect(CHARACTER_WORKSPACE_CSS).toContain("grid-column:1 / -1");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-accent: #ff7043");
  });
});
