import type { OutlineCharacterDraft } from "./types";

export function outlineCharacterReferenceLabel(character: OutlineCharacterDraft): string {
  return character.character_id
    ? `${character.name} · 已关联正式人物卡`
    : `${character.name} · 规划草案`;
}

export function isLinkedOutlineCharacter(character: OutlineCharacterDraft | undefined): boolean {
  return Boolean(character?.character_id);
}
