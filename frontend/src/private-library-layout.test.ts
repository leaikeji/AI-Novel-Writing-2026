// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("private library desktop container layout", () => {
  const styleSource = readFileSync(new URL("./styles.ts", import.meta.url), "utf8");

  it("wraps filters without shrinking the archive label into a vertical column", () => {
    expect(styleSource).toContain(".anw-private-library__filters { display:flex; min-width:0; flex-wrap:wrap;");
    expect(styleSource).toContain(".anw-private-library__filters > .qwenpaw-input-affix-wrapper { min-width:0; max-width:100%; flex:1 1 240px; }");
    expect(styleSource).toContain(".anw-private-library__filters > .qwenpaw-select { min-width:0; max-width:100%; flex:1 1 140px; }");
    expect(styleSource).toContain(".anw-private-library__filters > label { display:flex; flex:0 0 auto; align-items:center; gap:6px; white-space:nowrap; }");
    expect(styleSource).not.toContain("grid-template-columns:minmax(260px,1fr) 150px 150px auto;");
  });

  it("switches master and detail to stacked desktop panels using the library width", () => {
    // CSS contracts do not replace formal desktop screenshot and keyboard checks.
    expect(styleSource).toContain(".anw-private-library { display:grid; min-width:0; gap:18px; container-type:inline-size; }");
    const containerRules = [...styleSource.matchAll(/@container \(max-width:760px\) \{([^]*?)\n    \}/g)]
      .map((match) => match[1]);
    const libraryRules = containerRules.find((rules) => rules.includes(".anw-private-library__desktop-layout"));
    expect(libraryRules).toContain(".anw-private-library__desktop-layout { min-height:0; grid-template-columns:minmax(0,1fr); }");
    expect(libraryRules).toContain(".anw-private-library__master { max-height:320px; border-right:0; border-bottom:1px solid var(--anw-line); }");
    expect(libraryRules).toContain(".anw-private-library__detail-pane { padding:18px; }");
    expect(styleSource).toContain("grid-template-columns:minmax(280px,34%) minmax(0,1fr);");
    expect(styleSource).toContain(".anw-private-library__master { min-width:0; overflow:auto;");
  });

  it("keeps library and detail titles readable when their controls need another row", () => {
    expect(styleSource).toContain(".anw-private-library__header { display:flex; min-width:0; flex-wrap:wrap;");
    expect(styleSource).toContain(".anw-private-library__header > div { min-width:0; flex:1 1 260px; overflow-wrap:anywhere; }");
    expect(styleSource).toContain(".anw-private-library__detail-header { display:flex; min-width:0; flex-wrap:wrap;");
    expect(styleSource).toContain(".anw-private-library__detail-header > div:first-child { min-width:0; flex:1 1 220px; }");
    expect(styleSource).toContain(".anw-private-library__detail { display:grid; min-width:0; gap:22px; overflow-wrap:anywhere; }");
    expect(styleSource).toContain(".anw-private-library__detail-actions { display:flex; min-width:0; max-width:100%; flex:0 1 auto; flex-wrap:wrap;");
    expect(styleSource).toMatch(/\.anw-private-library__detail-actions > label \{[^}]*flex:0 0 auto;[^}]*white-space:nowrap;/);
    expect(styleSource).toContain(".anw-private-library__detail-actions > button { flex:0 0 auto; }");
  });

  it("allows long entries, history and their actions to wrap within the detail pane", () => {
    expect(styleSource).toContain(".anw-private-library__history li { display:flex; min-width:0; flex-wrap:wrap;");
    expect(styleSource).toContain(".anw-private-library__history li > span:first-child { min-width:0; flex:1 1 180px; }");
    expect(styleSource).toContain(".anw-private-library__section-title { display:flex; flex-wrap:wrap;");
    expect(styleSource).toContain(".anw-private-library__entry-list > li,.anw-private-library__hit-list > li { display:flex; min-width:0; flex-wrap:wrap;");
    expect(styleSource).toContain(".anw-private-library__entry-list > li > div,.anw-private-library__hit-list > li > div { display:flex; min-width:0; flex:1 1 200px; flex-wrap:wrap;");
  });
});
