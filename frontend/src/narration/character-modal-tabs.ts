export type CharacterModalTab = "profile" | "voice";


/**
 * Resolve the WAI-ARIA keyboard movement for the two character-card tabs.
 * Returning null leaves unrelated keys to the focused control.
 */
export function characterModalTabFromKey(
  current: CharacterModalTab,
  key: string,
): CharacterModalTab | null {
  if (key === "Home") return "profile";
  if (key === "End") return "voice";
  if (key === "ArrowLeft" || key === "ArrowUp") {
    return current === "profile" ? "voice" : "profile";
  }
  if (key === "ArrowRight" || key === "ArrowDown") {
    return current === "profile" ? "voice" : "profile";
  }
  return null;
}
