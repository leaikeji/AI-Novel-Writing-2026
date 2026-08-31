import { describe, expect, it } from "vitest";

import { CHARACTER_WORKSPACE_CSS } from "./styles";

describe("character workspace responsive contract", () => {
  it("uses a wider desktop dialog and a true mobile full-screen layout", () => {
    expect(CHARACTER_WORKSPACE_CSS).toContain("width: min(1120px");
    expect(CHARACTER_WORKSPACE_CSS).toContain("grid-template-columns:repeat(3");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-workspace-fact-grid");
    expect(CHARACTER_WORKSPACE_CSS).toContain("@media (max-width: 720px)");
    expect(CHARACTER_WORKSPACE_CSS).toContain("position: fixed; inset: 0");
    expect(CHARACTER_WORKSPACE_CSS).toContain("height: 100dvh");
    expect(CHARACTER_WORKSPACE_CSS).toContain("position: sticky");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-workspace-tabs { display: flex; flex: 0 0 auto");
    expect(CHARACTER_WORKSPACE_CSS).toContain(":focus-visible");
    expect(CHARACTER_WORKSPACE_CSS).toContain("grid-column:1 / -1");
  });
});
