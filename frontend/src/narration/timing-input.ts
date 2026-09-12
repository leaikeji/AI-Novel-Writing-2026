import type { NarrationTimingSettings } from "./contracts";

export const TIMING_INPUT_FIELDS = [
  ["sentence_gap_ms", "句间", 5_000],
  ["paragraph_gap_ms", "段间", 10_000],
  ["section_gap_ms", "分隔", 15_000],
] as const;

export type InvalidTimingInputs = Partial<Record<keyof NarrationTimingSettings, string>>;

/** Empty/incomplete input is not zero and must never become a saved duration. */
export function parseTimingInput(raw: string, maximum: number): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value <= maximum ? value : null;
}

export function updateInvalidTimingInputs(
  current: InvalidTimingInputs,
  key: keyof NarrationTimingSettings,
  raw: string,
  maximum: number,
): InvalidTimingInputs {
  const next = { ...current };
  if (parseTimingInput(raw, maximum) === null) next[key] = raw;
  else delete next[key];
  return next;
}
