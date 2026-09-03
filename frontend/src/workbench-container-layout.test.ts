// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { resolveAssistantWorkspaceLayout } from "./assistant-layout";

describe("workbench container responsive shell", () => {
  const styleSource = readFileSync(new URL("./styles.ts", import.meta.url), "utf8");
  const studioSource = readFileSync(new URL("./workbench-studio.ts", import.meta.url), "utf8");

  it("degrades from the measured PawApp container when the same viewport opens the assistant", () => {
    const expanded = resolveAssistantWorkspaceLayout({
      containerWidth: 1_267,
      preferredAssistantWidth: 520,
      pageKind: "studio",
    });
    const collapsed = resolveAssistantWorkspaceLayout({
      containerWidth: 1_267,
      assistantCollapsed: true,
      pageKind: "studio",
    });

    expect(expanded.mainWidth).toBe(747);
    expect(collapsed.mainWidth).toBe(1_215);
    expect(expanded.mainWidth).toBeLessThanOrEqual(760);
    expect(collapsed.mainWidth).toBeGreaterThan(1_040);
    expect(styleSource).toContain(".anw-workbench-main { min-width:0; min-height:0; flex:1 1 auto; overflow:hidden; container-type:inline-size;");
    expect(styleSource).toContain("@container (max-width:760px)");
    expect(styleSource).toContain("grid-template-columns:minmax(0,1fr);");
  });

  it("keeps the compact rail and all panel scrolling inside the workbench", () => {
    expect(styleSource).toMatch(/@container \(max-width:760px\)[\s\S]*?\.mb-book-nav \{[\s\S]*?overflow-x:auto;/);
    expect(styleSource).toMatch(/@container \(max-width:760px\)[\s\S]*?\.mb-workbench \.mb-panel-body,[\s\S]*?overflow-y:auto;[\s\S]*?overflow-x:hidden;/);
    expect(styleSource).toMatch(/@container \(max-width:520px\)[\s\S]*?\.mb-book-rail[\s\S]*?grid-template-columns:minmax\(0,1fr\);/);
    expect(styleSource).toMatch(/@media \(max-height:720px\) and \(min-width:721px\)[\s\S]*?\.mb-book-nav[\s\S]*?overflow-y:auto;/);
  });

  it("reserves the visible strip when the host switches the assistant to overlay mode", () => {
    expect(styleSource).toMatch(/\.anw-workbench-frame \.mb-workbench\[data-assistant-overlay="true"\] \{[\s\S]*?container-type:inline-size;[\s\S]*?grid-template-columns:minmax\(0,1fr\);/);
    expect(studioSource).toContain("studioOverlayVisibleWidth(assistantWorkspaceLayout)");
    expect(studioSource).toContain("width: `${overlayVisibleWidth}px`");
  });

  it("raises every full-workbench overlay above the host sticky sidebar without outranking host modals", () => {
    expect(styleSource).toContain(".anw-workbench-frame:has(.anw-character-workspace-backdrop)");
    expect(styleSource).toContain(".anw-workbench-frame:has(.anw-story-ledger-modal-layer)");
    expect(styleSource).toContain(".anw-workbench-frame:has(.anw-character-voice-drawer-layer:not([hidden])) { z-index:900;");
  });

  it("has a no-page-overflow path for every pre-ledger workbench section", () => {
    for (const section of ["chapters", "outline", "roles", "clues", "settings", "reading"]) {
      expect(studioSource).toContain(`"${section}"`);
    }
    expect(styleSource).toMatch(/@container \(max-width:1040px\)[\s\S]*?\.mb-workbench[\s\S]*?overflow-x:hidden;/);
    expect(styleSource).toContain(".mb-workbench .mb-panel-body > * { min-width:0; max-width:100%; }");
  });
});
