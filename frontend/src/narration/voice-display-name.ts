import { OFFICIAL_PRESET_EVIDENCE } from "./contracts";

/** Display-only normalization; never rename stored or author-defined voices. */
export function officialVoiceProfileDisplayName(profileName: string, presetId: string | null): string {
  const name = profileName.trim();
  const evidence = OFFICIAL_PRESET_EVIDENCE.find((item) => item.presetId === presetId);
  if (!evidence || name.startsWith(`${evidence.localVoiceId}｜`)) return name;
  return `${evidence.localVoiceId}｜${name}`;
}
