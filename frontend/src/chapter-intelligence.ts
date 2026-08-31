export interface ChapterIntelligenceItemLike {
  readonly item_type: string;
}

export const INTELLIGENCE_GROUPS: ReadonlyArray<{
  readonly key: string;
  readonly label: string;
  readonly types: readonly string[];
}> = [
  { key: "character", label: "角色状态与认知", types: ["character_state", "knowledge_event"] },
  { key: "relationship", label: "角色关系变化", types: ["relationship_state"] },
  { key: "storyline", label: "故事线进展", types: ["storyline_event"] },
  { key: "foreshadow", label: "伏笔进展", types: ["foreshadow_event"] },
  { key: "other", label: "时间、世界与其他事实", types: ["story_time", "world_state", "general_fact"] },
];

export function groupIntelligenceItems<T extends ChapterIntelligenceItemLike>(items: readonly T[]) {
  return INTELLIGENCE_GROUPS.map((group) => ({
    ...group,
    items: items.filter((item) => group.types.includes(item.item_type)),
  })).filter((group) => group.items.length > 0);
}
