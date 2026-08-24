import type { CharacterRelationshipRecord } from "./types";


function laneSequence(index: number): number {
  if (index === 0) return 0;
  const distance = Math.ceil(index / 2);
  return index % 2 === 1 ? distance : -distance;
}


function stableCurveHash(value: string): number {
  let hash = 2166136261;
  for (const character of value) {
    hash ^= character.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}


export interface RelationshipCurveSpec {
  type: "curvedCW" | "curvedCCW";
  roundness: number;
}


export function relationshipCurveSpec(
  relationship: CharacterRelationshipRecord,
  lane: number,
): RelationshipCurveSpec {
  if (lane !== 0) {
    return {
      type: lane > 0 ? "curvedCW" : "curvedCCW",
      roundness: Math.min(0.48, 0.22 + Math.abs(lane) * 0.1),
    };
  }
  const hash = stableCurveHash(
    `${relationship.relation_pair_key}:${relationship.directionality}:${relationship.id}`,
  );
  return {
    type: hash % 2 === 0 ? "curvedCW" : "curvedCCW",
    roundness: 0.12 + ((hash >>> 1) % 3) * 0.03,
  };
}


export function compactRelationshipGraphLabel(
  label: string,
  fallback: string,
  maxCharacters = 5,
): string {
  const value = (label || fallback).trim();
  const characters = Array.from(value);
  if (characters.length <= maxCharacters) return value;
  return `${characters.slice(0, maxCharacters).join("")}…`;
}


export function relationshipLaneMap(
  relationships: CharacterRelationshipRecord[],
): Map<string, number> {
  const groups = new Map<string, CharacterRelationshipRecord[]>();
  for (const relationship of relationships) {
    const rows = groups.get(relationship.relation_pair_key) ?? [];
    rows.push(relationship);
    groups.set(relationship.relation_pair_key, rows);
  }
  const lanes = new Map<string, number>();
  for (const rows of groups.values()) {
    rows
      .sort((left, right) => {
        const leftKey = `${left.directionality}:${left.source_character_id}:${left.relation_kind}:${left.label}:${left.id}`;
        const rightKey = `${right.directionality}:${right.source_character_id}:${right.relation_kind}:${right.label}:${right.id}`;
        return leftKey.localeCompare(rightKey, "zh-CN");
      })
      .forEach((relationship, index) => lanes.set(relationship.id, laneSequence(index)));
  }
  return lanes;
}
