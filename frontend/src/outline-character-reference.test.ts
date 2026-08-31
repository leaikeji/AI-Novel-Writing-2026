import { describe, expect, it } from "vitest";

import {
  isLinkedOutlineCharacter,
  outlineCharacterReferenceLabel,
} from "./outline-character-reference";

describe("outline character references", () => {
  it("marks a planning-only character as a draft", () => {
    const character = { name: "沈砚", role_type: "main" as const, description: "", details: {} };
    expect(outlineCharacterReferenceLabel(character)).toBe("沈砚 · 规划草案");
    expect(isLinkedOutlineCharacter(character)).toBe(false);
  });

  it("marks a character with a stable id as linked to the formal card", () => {
    const character = {
      name: "沈砚",
      role_type: "main" as const,
      description: "",
      details: {},
      character_id: "character-1",
    };
    expect(outlineCharacterReferenceLabel(character)).toBe("沈砚 · 已关联正式人物卡");
    expect(isLinkedOutlineCharacter(character)).toBe(true);
  });
});
