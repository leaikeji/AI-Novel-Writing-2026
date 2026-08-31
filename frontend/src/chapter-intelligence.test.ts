import { describe, expect, it } from "vitest";

import { groupIntelligenceItems } from "./chapter-intelligence";

describe("groupIntelligenceItems", () => {
  it("shows every StoryFact v2 intelligence type", () => {
    const itemTypes = [
      "character_state",
      "relationship_state",
      "storyline_event",
      "foreshadow_event",
      "story_time",
      "knowledge_event",
      "world_state",
      "general_fact",
    ];

    const grouped = groupIntelligenceItems(itemTypes.map((item_type) => ({ item_type })));

    expect(grouped.flatMap((group) => group.items.map((item) => item.item_type)).sort())
      .toEqual([...itemTypes].sort());
  });
});
