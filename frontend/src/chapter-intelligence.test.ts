import { describe, expect, it } from "vitest";

import {
  groupIntelligenceItems,
  intelligenceCommitSummary,
  pendingIntelligenceItemIds,
  relationshipCandidateActionLabel,
  relationshipKindLabel,
  toggleIntelligenceItemSelection,
} from "./chapter-intelligence";

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

describe("relationship intelligence presentation", () => {
  it("distinguishes pending actions from completed writes", () => {
    expect(relationshipCandidateActionLabel(true, "pending")).toBe("将新建关系");
    expect(relationshipCandidateActionLabel(false, "pending")).toBe("更新已有关系");
    expect(relationshipCandidateActionLabel(true, "accepted")).toBe("已新建关系");
    expect(relationshipCandidateActionLabel(false, "accepted")).toBe("已更新关系");
  });

  it("uses readable Chinese labels for relationship kinds", () => {
    expect(relationshipKindLabel("ally")).toBe("盟友");
    expect(relationshipKindLabel(undefined)).toBe("其他");
    expect(relationshipKindLabel("custom")).toBe("custom");
  });

  it("does not report server-rejected candidates as written", () => {
    expect(intelligenceCommitSummary(["a", "b"], {
      rejected_invalid_item_ids: ["b"],
      relationship_sync: { created: 1, updated: 0, skipped: 0 },
    })).toEqual({ writtenCount: 1, rejectedCount: 1, relationshipTotal: 1 });
  });
});

describe("chapter intelligence review selection", () => {
  it("starts from pending items only and toggles without duplicates", () => {
    const pending = pendingIntelligenceItemIds([
      { id: "a", item_type: "relationship_state", review_state: "pending" },
      { id: "b", item_type: "general_fact", review_state: "accepted" },
      { id: "c", item_type: "storyline_event", review_state: "pending" },
    ]);

    expect(pending).toEqual(["a", "c"]);
    expect(toggleIntelligenceItemSelection([], "a", true)).toEqual(["a"]);
    expect(toggleIntelligenceItemSelection(["a"], "a", true)).toEqual(["a"]);
    expect(toggleIntelligenceItemSelection(["a", "c"], "a", false)).toEqual(["c"]);
  });
});
