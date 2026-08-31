import type { OutlineDraftRecord } from "./types";

export function outlineCompletionPatch(
  draft: Pick<OutlineDraftRecord, "characters" | "highlight_text">,
) {
  return {
    characters: draft.characters,
    highlight_text: draft.highlight_text,
  };
}
