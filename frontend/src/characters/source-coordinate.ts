export const SOURCE_COORDINATE_VERSION = "unicode-codepoint-v1" as const;
export const MAX_SOURCE_EXCERPT_CODE_POINTS = 500;

export interface CharacterSourceLocator {
  readonly source_content_hash: string;
  readonly source_coordinate: string;
  readonly source_start: number;
  readonly source_end: number;
  readonly source_range_hash: string;
  readonly source_excerpt: string;
  readonly source_excerpt_truncated: boolean;
}

export type SourceCoordinateFallbackReason =
  | "unsupported_coordinate"
  | "invalid_content_hash"
  | "revision_content_hash_mismatch"
  | "invalid_range_hash"
  | "invalid_range"
  | "range_hash_mismatch"
  | "excerpt_too_long"
  | "excerpt_mismatch"
  | "hash_unavailable";

export interface VerifiedSourceRange {
  readonly status: "verified";
  readonly startUtf16: number;
  readonly endUtf16: number;
  readonly text: string;
}

export interface SourceRangeFallback {
  readonly status: "fallback";
  readonly reason: SourceCoordinateFallbackReason;
  readonly excerpt: string;
  readonly excerptTruncated: boolean;
}

export type SourceRangeResolution = VerifiedSourceRange | SourceRangeFallback;
export type Sha256Text = (value: string) => Promise<string>;

/** Convert a Python Unicode code-point offset to a JavaScript UTF-16 offset. */
export function unicodeCodePointOffsetToUtf16(
  contentText: string,
  codePointOffset: number,
): number | null {
  if (!Number.isSafeInteger(codePointOffset) || codePointOffset < 0) return null;
  let codePoints = 0;
  let utf16 = 0;
  for (const value of contentText) {
    if (codePoints === codePointOffset) return utf16;
    codePoints += 1;
    utf16 += value.length;
  }
  return codePoints === codePointOffset ? utf16 : null;
}

/**
 * Resolve an immutable revision locator. No fallback path searches the document
 * for similar text; callers must render the returned excerpt without a guessed
 * selection whenever any identity, range, hash, or excerpt check fails.
 */
export async function resolveCharacterSourceRange(
  contentText: string,
  revisionContentHash: string,
  locator: CharacterSourceLocator,
  sha256: Sha256Text = defaultSha256,
): Promise<SourceRangeResolution> {
  const fallback = (reason: SourceCoordinateFallbackReason): SourceRangeFallback => ({
    status: "fallback",
    reason,
    excerpt: boundedExcerpt(locator.source_excerpt),
    excerptTruncated: locator.source_excerpt_truncated
      || codePointLength(locator.source_excerpt) > MAX_SOURCE_EXCERPT_CODE_POINTS,
  });

  if (locator.source_coordinate !== SOURCE_COORDINATE_VERSION) {
    return fallback("unsupported_coordinate");
  }
  if (!isSha256(locator.source_content_hash) || !isSha256(revisionContentHash)) {
    return fallback("invalid_content_hash");
  }
  if (locator.source_content_hash.toLowerCase() !== revisionContentHash.toLowerCase()) {
    return fallback("revision_content_hash_mismatch");
  }
  if (!isSha256(locator.source_range_hash)) return fallback("invalid_range_hash");

  const startUtf16 = unicodeCodePointOffsetToUtf16(contentText, locator.source_start);
  const endUtf16 = unicodeCodePointOffsetToUtf16(contentText, locator.source_end);
  if (
    startUtf16 === null
    || endUtf16 === null
    || locator.source_end <= locator.source_start
    || endUtf16 <= startUtf16
  ) {
    return fallback("invalid_range");
  }

  const rangeText = contentText.slice(startUtf16, endUtf16);
  let actualRangeHash: string;
  try {
    actualRangeHash = (await sha256(rangeText)).toLowerCase();
  } catch {
    return fallback("hash_unavailable");
  }
  if (!isSha256(actualRangeHash) || actualRangeHash !== locator.source_range_hash.toLowerCase()) {
    return fallback("range_hash_mismatch");
  }

  const excerptLength = codePointLength(locator.source_excerpt);
  if (excerptLength > MAX_SOURCE_EXCERPT_CODE_POINTS) {
    return fallback("excerpt_too_long");
  }
  if (!excerptMatchesExactRange(rangeText, locator)) {
    return fallback("excerpt_mismatch");
  }

  return { status: "verified", startUtf16, endUtf16, text: rangeText };
}

function excerptMatchesExactRange(
  rangeText: string,
  locator: CharacterSourceLocator,
): boolean {
  if (!locator.source_excerpt_truncated) return locator.source_excerpt === rangeText;
  if (!locator.source_excerpt) return false;
  // A bounded long-range excerpt can be any exact fragment of the already
  // hash-verified range. It is validation only and never changes the offsets.
  return rangeText.includes(locator.source_excerpt);
}

function codePointLength(value: string): number {
  return [...value].length;
}

function boundedExcerpt(value: string): string {
  return [...value].slice(0, MAX_SOURCE_EXCERPT_CODE_POINTS).join("");
}

function isSha256(value: string): boolean {
  return /^[0-9a-f]{64}$/i.test(value);
}

async function defaultSha256(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is required for source verification");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
