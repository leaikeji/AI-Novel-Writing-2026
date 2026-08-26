import { describe, expect, it } from "vitest";

import { creativeCenterEntryTarget } from "./creative-center-entry";


describe("creative center shell entry", () => {
  it("moves the public PawApp entry into the wrapped native chat route", () => {
    expect(creativeCenterEntryTarget("")).toBe("/chat?novel_center=1");
  });

  it("preserves only the supported private-library view", () => {
    expect(creativeCenterEntryTarget("?view=private-library&novel_id=stale"))
      .toBe("/chat?novel_center=1&view=private-library");
    expect(creativeCenterEntryTarget("?view=unknown&novel_workbench=1"))
      .toBe("/chat?novel_center=1");
  });
});
