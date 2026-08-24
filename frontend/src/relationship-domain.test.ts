import { describe, expect, it } from "vitest";

import {
  compactRelationshipGraphLabel,
  relationshipCurveSpec,
  relationshipLaneMap,
} from "./relationship-domain";
import type { CharacterRelationshipRecord } from "./types";


function relationship(
  id: string,
  overrides: Partial<CharacterRelationshipRecord> = {},
): CharacterRelationshipRecord {
  return {
    id,
    novel_id: "novel-1",
    source_character_id: "character-a",
    target_character_id: "character-b",
    directionality: "undirected",
    relation_kind: "other",
    label: id,
    relation_type: id,
    description: "",
    status: "active",
    created_by: "manual",
    manual_override: true,
    confidence: null,
    evidence: [],
    source_generation_job_id: null,
    relation_pair_key: "character-a:character-b",
    source_chapter_revision_id: null,
    proposal_item_id: null,
    current_revision_id: null,
    archived_at: null,
    version: 1,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}


describe("relationshipLaneMap", () => {
  it("为同一对角色的多条关系分配稳定且不重叠的弧线", () => {
    const rows = [relationship("同事"), relationship("旧友"), relationship("对手")];
    const first = relationshipLaneMap(rows);
    const second = relationshipLaneMap([...rows].reverse());

    expect([...first.values()].sort()).toEqual([-1, 0, 1]);
    expect(Object.fromEntries(first)).toEqual(Object.fromEntries(second));
  });

  it("不同角色对分别从直线轨道开始", () => {
    const lanes = relationshipLaneMap([
      relationship("ab"),
      relationship("cd", {
        source_character_id: "character-c",
        target_character_id: "character-d",
        relation_pair_key: "character-c:character-d",
      }),
    ]);

    expect(lanes.get("ab")).toBe(0);
    expect(lanes.get("cd")).toBe(0);
  });
});


describe("compactRelationshipGraphLabel", () => {
  it("保留短关系名，避免画布信息损失", () => {
    expect(compactRelationshipGraphLabel("同盟与青梅", "盟友")).toBe("同盟与青梅");
  });

  it("压缩长关系名，完整说明仍由悬浮提示和关系列表承载", () => {
    expect(compactRelationshipGraphLabel("少年军师与街道办主任", "其他")).toBe("少年军师与…");
    expect(compactRelationshipGraphLabel("", "暗中博弈的对手")).toBe("暗中博弈的…");
  });
});


describe("relationshipCurveSpec", () => {
  it("为单条关系生成刷新后不翻转的轻曲线", () => {
    const row = relationship("relationship-1");
    const first = relationshipCurveSpec(row, 0);
    const second = relationshipCurveSpec(row, 0);

    expect(first).toEqual(second);
    expect(["curvedCW", "curvedCCW"]).toContain(first.type);
    expect(first.roundness).toBeGreaterThanOrEqual(0.12);
    expect(first.roundness).toBeLessThanOrEqual(0.18);
  });

  it("同一人物对的并行关系使用方向相反且更明显的曲线", () => {
    const row = relationship("relationship-2");
    const clockwise = relationshipCurveSpec(row, 1);
    const counterClockwise = relationshipCurveSpec(row, -1);

    expect(clockwise.type).toBe("curvedCW");
    expect(counterClockwise.type).toBe("curvedCCW");
    expect(clockwise.roundness).toBeGreaterThan(0.2);
    expect(counterClockwise.roundness).toBe(clockwise.roundness);
  });
});
