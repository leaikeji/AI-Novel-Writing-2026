export const RETRIEVAL_SUMMARY_SCHEMA_VERSION = "retrieval-summary/1" as const;


export const RETRIEVAL_OUTCOMES = [
  "used",
  "degraded",
  "no_hit",
  "not_run",
  "failed",
] as const;


export const RETRIEVAL_MODES = [
  "hybrid",
  "lexical_only",
  "context_only",
] as const;


export const RETRIEVAL_REASON_CODES = [
  "ready",
  "not_authorized",
  "index_building",
  "index_outdated",
  "partial_failed",
  "provider_unavailable",
  "no_hit",
  "not_applicable",
] as const;


export const RETRIEVAL_INDEX_STATES = [
  "not_authorized",
  "building",
  "ready",
  "outdated",
  "partial_failed",
] as const;


export type RetrievalOutcome = typeof RETRIEVAL_OUTCOMES[number];
export type RetrievalMode = typeof RETRIEVAL_MODES[number];
export type RetrievalReasonCode = typeof RETRIEVAL_REASON_CODES[number];
export type RetrievalIndexState = typeof RETRIEVAL_INDEX_STATES[number];


export interface RetrievalSummaryV1 {
  readonly schema_version: typeof RETRIEVAL_SUMMARY_SCHEMA_VERSION;
  readonly outcome: RetrievalOutcome;
  readonly mode: RetrievalMode;
  readonly reason_code: RetrievalReasonCode;
  readonly hit_count: number;
  readonly index_state: RetrievalIndexState | null;
}


export interface RetrievalSummaryCarrier {
  readonly retrieval_summary?: unknown;
}


function isChoice<const Choices extends readonly string[]>(
  value: unknown,
  choices: Choices,
): value is Choices[number] {
  return typeof value === "string" && choices.includes(value as Choices[number]);
}


/**
 * Parse only the public, redacted projection. Unknown fields are deliberately
 * discarded so query text, snippets or prompt internals can never reach the UI.
 */
export function parseRetrievalSummary(value: unknown): RetrievalSummaryV1 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (candidate.schema_version !== RETRIEVAL_SUMMARY_SCHEMA_VERSION
    || !isChoice(candidate.outcome, RETRIEVAL_OUTCOMES)
    || !isChoice(candidate.mode, RETRIEVAL_MODES)
    || !isChoice(candidate.reason_code, RETRIEVAL_REASON_CODES)
    || !Number.isInteger(candidate.hit_count)
    || Number(candidate.hit_count) < 0
    || Number(candidate.hit_count) > 10_000
    || !(candidate.index_state === null
      || isChoice(candidate.index_state, RETRIEVAL_INDEX_STATES))) {
    return null;
  }
  return {
    schema_version: RETRIEVAL_SUMMARY_SCHEMA_VERSION,
    outcome: candidate.outcome,
    mode: candidate.mode,
    reason_code: candidate.reason_code,
    hit_count: Number(candidate.hit_count),
    index_state: candidate.index_state,
  };
}


export function retrievalSummaryFromJob(job: unknown): RetrievalSummaryV1 | null {
  if (!job || typeof job !== "object" || Array.isArray(job)) return null;
  return parseRetrievalSummary((job as RetrievalSummaryCarrier).retrieval_summary);
}
