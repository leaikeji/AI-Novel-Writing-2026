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

export interface BoundedSourceHighlight {
  readonly before: string;
  readonly highlighted: string;
  readonly after: string;
}

/** Split the server-bounded excerpt using its Unicode code-point offsets. */
export function splitBoundedSourceExcerpt(
  excerpt: string,
  highlightStart: number | null,
  highlightEnd: number | null,
): BoundedSourceHighlight | null {
  if (
    highlightStart === null
    || highlightEnd === null
    || highlightEnd <= highlightStart
  ) return null;
  const startUtf16 = unicodeCodePointOffsetToUtf16(excerpt, highlightStart);
  const endUtf16 = unicodeCodePointOffsetToUtf16(excerpt, highlightEnd);
  if (startUtf16 === null || endUtf16 === null || endUtf16 <= startUtf16) return null;
  return {
    before: excerpt.slice(0, startUtf16),
    highlighted: excerpt.slice(startUtf16, endUtf16),
    after: excerpt.slice(endUtf16),
  };
}
