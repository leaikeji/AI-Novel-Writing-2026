// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


describe("character role card layout", () => {
  const styleSource = readFileSync(new URL("./styles.ts", import.meta.url), "utf8");

  it("replaces the native inner focus outline with a branded outer focus state", () => {
    expect(styleSource).toMatch(/\.mb-role-card-main \{[^}]*outline:0;/);
    expect(styleSource).toContain(".mb-role-card-main:focus { outline:0;");
    expect(styleSource).toContain(".mb-role-card:has(.mb-role-card-main:focus-visible)");
    expect(styleSource).toContain(".mb-role-section.is-supporting .mb-role-card:has(.mb-role-card-main:focus-visible)");
  });

  it("stretches the copy to the card height and keeps compact symmetric gutters", () => {
    expect(styleSource).toMatch(/\.mb-role-card \{[^}]*min-height:156px;[^}]*padding:14px 15px;/);
    expect(styleSource).toMatch(/\.mb-role-card-main \{[^}]*align-items:stretch;/);
    expect(styleSource).toMatch(/\.mb-role-copy \{[^}]*min-height:100%;/);
    expect(styleSource).not.toMatch(/\.mb-role-card-main \{[^}]*align-items:flex-start;/);
  });
});
