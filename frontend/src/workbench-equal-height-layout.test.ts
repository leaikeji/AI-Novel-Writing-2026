// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


describe("workbench equal-height layout styles", () => {
  const styleSource = readFileSync(new URL("./styles.ts", import.meta.url), "utf8");
  const studioSource = readFileSync(new URL("./workbench-studio.ts", import.meta.url), "utf8");

  it("stretches the desktop rail and main panel to the workbench row", () => {
    expect(styleSource).toMatch(/\.mb-workbench \{[\s\S]*?align-items:stretch;/);
    expect(styleSource).toMatch(/\.mb-book-rail \{[\s\S]*?align-self:stretch;/);
    expect(styleSource).toContain(".mb-back-center-wrap { margin-top:auto;");
    expect(styleSource).toMatch(/\.mb-workbench-main \{[^}]*align-self:stretch;[^}]*flex-direction:column;/);
  });

  it("lets the outline step body absorb the remaining panel height", () => {
    expect(styleSource).toMatch(/\.mb-panel-body \{[^}]*min-height:0;[^}]*flex:1;[^}]*overflow:auto;/);
    expect(styleSource).toMatch(/\.mb-outline-workspace \{[^}]*flex:1;[^}]*grid-template-rows:minmax\(0,1fr\);/);
    expect(styleSource).toContain(".mb-outline-wizard { display:grid; min-height:0; grid-template-rows:auto minmax(0,1fr);");
    expect(styleSource).toMatch(/\.mb-outline-step-body \{[^}]*height:100%;[^}]*min-height:260px;/);
  });

  it("uses one full-height editor layout for every outline text step", () => {
    expect(studioSource.match(/mb-outline-step-body is-text-editor/g)).toHaveLength(3);
    expect(styleSource).toContain(".mb-outline-step-body.is-text-editor { grid-template-rows:auto minmax(240px,1fr) auto;");
    expect(styleSource).toContain(".mb-outline-step-body.is-text-editor>textarea.qwenpaw-input { height:100%; resize:none;");
    expect(styleSource).not.toContain(".mb-outline-step-body.is-highlight>textarea.qwenpaw-input");
  });

  it("shows the same raw character counts enforced by textarea maxLength", () => {
    expect(studioSource).toContain("${draft.background_text.length} / 2000 字符");
    expect(studioSource).toContain("${draft.plot_text.length} / 5000 字符");
    expect(studioSource).toContain("${draft.highlight_text.length} / 200 字符");
  });

  it("keeps outline footer gutters equal and unifies the chapter-count corners", () => {
    expect(studioSource).toContain('studioSection === "outline" ? " is-outline" : ""');
    expect(styleSource).toContain(".mb-panel-body.is-outline { padding-bottom:28px;");
    expect(styleSource).toContain(".anw-workbench-frame[data-assistant-density=\"constrained\"] .mb-panel-body.is-outline { padding-bottom:16px;");
    expect(styleSource).toContain(".mb-panel-body.is-outline { padding-bottom:14px;");
    expect(styleSource).toMatch(/\.mb-outline-step-body\.is-count>\.qwenpaw-input-number \{[^}]*overflow:hidden;[^}]*border-radius:12px;/);
    expect(styleSource).toMatch(/\.qwenpaw-input-number-input \{[^}]*border-radius:11px;[^}]*background:transparent!important;/);
  });

  it("renders completed outline anchors as accessible direct navigation", () => {
    expect(studioSource).toContain("const navigateToStep = async (targetStep: number)");
    expect(studioSource).toContain("const isStepComplete = (current: OutlineDraftRecord, targetStep: number)");
    expect(studioSource).toContain("const stepReachable = number === step || stepIsComplete;");
    expect(studioSource).toContain('"aria-current": number === step ? "step" : undefined');
    expect(studioSource).toContain("onClick: () => void navigateToStep(number)");
    expect(styleSource).toContain(".mb-outline-step:not(:disabled):hover .mb-outline-step-dot");
    expect(styleSource).toContain(".mb-outline-step:focus-visible .mb-outline-step-dot");
  });

  it("keeps the existing mobile stacked layout override", () => {
    expect(styleSource).toMatch(/@media \(max-width: 720px\)[\s\S]*?\.mb-workbench,[\s\S]*?display:block;[\s\S]*?height:auto;/);
    expect(styleSource).toMatch(/@media \(max-width: 720px\)[\s\S]*?\.anw-workbench-main \{[\s\S]*?overflow-y:auto;/);
    expect(styleSource).toContain(".mb-back-center-wrap { grid-column:1/-1; margin:10px 0 0;");
  });
});
