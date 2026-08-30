// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { characterModalTabFromKey } from "./character-modal-tabs";


describe("character modal tab keyboard navigation", () => {
  it("wraps arrow navigation across the profile and voice tabs", () => {
    expect(characterModalTabFromKey("profile", "ArrowRight")).toBe("voice");
    expect(characterModalTabFromKey("voice", "ArrowRight")).toBe("profile");
    expect(characterModalTabFromKey("profile", "ArrowLeft")).toBe("voice");
    expect(characterModalTabFromKey("voice", "ArrowLeft")).toBe("profile");
    expect(characterModalTabFromKey("profile", "ArrowDown")).toBe("voice");
    expect(characterModalTabFromKey("voice", "ArrowUp")).toBe("profile");
  });

  it("supports Home and End without consuming unrelated keys", () => {
    expect(characterModalTabFromKey("voice", "Home")).toBe("profile");
    expect(characterModalTabFromKey("profile", "End")).toBe("voice");
    expect(characterModalTabFromKey("profile", "Enter")).toBeNull();
    expect(characterModalTabFromKey("voice", "Tab")).toBeNull();
  });

  it("keeps the real character modal tabs and 390px host reflow wired", () => {
    const workspaceSource = readFileSync(
      new URL("../characters/character-workspace.ts", import.meta.url),
      "utf8",
    );
    for (const token of [
      '"aria-controls": `${baseId}-panel-${tab}`',
      'role: "tabpanel"',
      '"aria-labelledby": `${baseId}-tab-basic`',
      "characterWorkspaceTabFromKey",
      "props.voiceSlot({",
    ]) {
      expect(workspaceSource).toContain(token);
    }

    const studioSource = readFileSync(new URL("../workbench-studio.ts", import.meta.url), "utf8");
    expect(studioSource).toContain('"aria-current": section === item ? "page" : undefined');

    const styleSource = readFileSync(new URL("../styles.ts", import.meta.url), "utf8");
    expect(styleSource).toContain("@media (max-width: 720px)");
    expect(styleSource).toContain(".mb-workbench,");
    expect(styleSource).toContain("grid-template-columns:84px minmax(0,1fr)");
    expect(styleSource).toContain(".mb-book-nav {");
    expect(styleSource).toContain("overflow-x:auto");
  });
});
