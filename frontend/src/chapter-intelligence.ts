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

export function pendingIntelligenceItemIds<T extends ChapterIntelligenceItemLike & {
  readonly id: string;
  readonly review_state: string;
}>(items: readonly T[]): string[] {
  return items.filter((item) => item.review_state === "pending").map((item) => item.id);
}

export function toggleIntelligenceItemSelection(
  selectedIds: readonly string[],
  itemId: string,
  selected: boolean,
): string[] {
  const next = new Set(selectedIds);
  if (selected) next.add(itemId);
  else next.delete(itemId);
  return [...next];
}

const RELATIONSHIP_KIND_LABELS: Readonly<Record<string, string>> = {
  family: "家人",
  colleague: "同事",
  mentor: "师生",
  ally: "盟友",
  enemy: "对立",
  romance: "情感",
  other: "其他",
};

export function relationshipCandidateActionLabel(
  isNew: boolean,
  reviewState: string,
): string {
  if (reviewState === "accepted") return isNew ? "已新建关系" : "已更新关系";
  return isNew ? "将新建关系" : "更新已有关系";
}

export function relationshipKindLabel(kind: string | null | undefined): string {
  const normalized = (kind || "other").trim().toLowerCase();
  return RELATIONSHIP_KIND_LABELS[normalized] || normalized;
}

export function intelligenceCommitSummary(
  selectedIds: readonly string[],
  result: {
    readonly rejected_invalid_item_ids?: readonly string[];
    readonly relationship_sync?: {
      readonly created: number;
      readonly updated: number;
      readonly skipped: number;
    };
  },
): {
  writtenCount: number;
  rejectedCount: number;
  relationshipTotal: number;
} {
  const rejectedIds = new Set(result.rejected_invalid_item_ids ?? []);
  const rejectedCount = selectedIds.filter((id) => rejectedIds.has(id)).length;
  return {
    writtenCount: Math.max(0, selectedIds.length - rejectedCount),
    rejectedCount,
    relationshipTotal: (result.relationship_sync?.created ?? 0)
      + (result.relationship_sync?.updated ?? 0),
  };
}
