import { describe, expect, it } from "vitest";

import { outlineCompletionPatch } from "./outline-completion";

describe("outlineCompletionPatch", () => {
  it("persists stable character links together with the final highlight", () => {
    const characters = [{
      schema_version: "outline-character-draft/2" as const,
      draft_key: "draft-main",
      character_id: "character-main",
      name: "沈砚",
      role_type: "main" as const,
      description: "",
      details: {},
    }];

    expect(outlineCompletionPatch({ characters, highlight_text: "声音证据悬疑" })).toEqual({
      characters,
      highlight_text: "声音证据悬疑",
    });
  });
});
