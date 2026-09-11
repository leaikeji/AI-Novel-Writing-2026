// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


describe("manual-template novel creation route", () => {
  const source = readFileSync(new URL("./creative-center.ts", import.meta.url), "utf8");

  it("marks the explicit no-AI route without inventing an idea", () => {
    expect(source).toContain('await persist(3, { ...data, manual_template_entry: true })');
    expect(source).toContain('updateData({ idea: event.target.value, manual_template_entry: false })');
  });
});
