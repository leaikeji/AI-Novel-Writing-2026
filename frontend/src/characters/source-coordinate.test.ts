import { describe, expect, it } from "vitest";

import {
  MAX_SOURCE_EXCERPT_CODE_POINTS,
  resolveCharacterSourceRange,
  unicodeCodePointOffsetToUtf16,
  type CharacterSourceLocator,
  type Sha256Text,
} from "./source-coordinate";

const REVISION_HASH = "a".repeat(64);

async function sha256(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function locator(
  content: string,
  start: number,
  end: number,
  overrides: Partial<CharacterSourceLocator> = {},
): Promise<CharacterSourceLocator> {
  const range = [...content].slice(start, end).join("");
  return {
    source_content_hash: REVISION_HASH,
    source_coordinate: "unicode-codepoint-v1",
    source_start: start,
    source_end: end,
    source_range_hash: await sha256(range),
    source_excerpt: range,
    source_excerpt_truncated: false,
    ...overrides,
  };
}

describe("character source coordinates", () => {
  it("converts Unicode code-point offsets to JavaScript UTF-16 offsets", () => {
    const content = "甲🌊乙𠮷丙";
    expect([...content]).toEqual(["甲", "🌊", "乙", "𠮷", "丙"]);
    expect(unicodeCodePointOffsetToUtf16(content, 0)).toBe(0);
    expect(unicodeCodePointOffsetToUtf16(content, 1)).toBe(1);
    expect(unicodeCodePointOffsetToUtf16(content, 2)).toBe(3);
    expect(unicodeCodePointOffsetToUtf16(content, 4)).toBe(6);
    expect(unicodeCodePointOffsetToUtf16(content, 5)).toBe(7);
    expect(unicodeCodePointOffsetToUtf16(content, 6)).toBeNull();
    expect(unicodeCodePointOffsetToUtf16(content, 1.5)).toBeNull();
  });

  it("returns exact UTF-16 selection only after all checks pass", async () => {
    const content = "潮汐🌊升起，许安走进灯塔。";
    const source = await locator(content, 2, 8);

    await expect(resolveCharacterSourceRange(content, REVISION_HASH, source)).resolves.toEqual({
      status: "verified",
      startUtf16: 2,
      endUtf16: 9,
      text: "🌊升起，许安",
    });
  });

  it("falls back instead of locating when revision content hash differs", async () => {
    const content = "甲🌊乙";
    const source = await locator(content, 1, 2);
    const result = await resolveCharacterSourceRange(content, "b".repeat(64), source);

    expect(result).toEqual({
      status: "fallback",
      reason: "revision_content_hash_mismatch",
      excerpt: "🌊",
      excerptTruncated: false,
    });
    expect(result).not.toHaveProperty("startUtf16");
  });

  it("falls back when exact range hash differs even if excerpt appears elsewhere", async () => {
    const content = "灯塔旁是码头，远处还有灯塔。";
    const source = await locator(content, 5, 7, {
      source_range_hash: await sha256("灯塔"),
      source_excerpt: "灯塔",
    });
    const result = await resolveCharacterSourceRange(content, REVISION_HASH, source);

    expect(result.status).toBe("fallback");
    expect(result).toMatchObject({ reason: "range_hash_mismatch" });
    expect(result).not.toHaveProperty("startUtf16");
  });

  it("falls back on excerpt mismatch and never searches for the duplicate excerpt", async () => {
    const content = "灯塔旁是码头，远处还有灯塔。";
    const source = await locator(content, 0, 2, { source_excerpt: "码头" });
    const result = await resolveCharacterSourceRange(content, REVISION_HASH, source);

    expect(result).toMatchObject({
      status: "fallback",
      reason: "excerpt_mismatch",
      excerpt: "码头",
    });
    expect(result).not.toHaveProperty("startUtf16");
  });

  it("rejects unsupported coordinates, reversed ranges, and malformed hashes", async () => {
    const content = "甲乙丙";
    const source = await locator(content, 0, 1);

    await expect(resolveCharacterSourceRange(content, REVISION_HASH, {
      ...source,
      source_coordinate: "utf16-v1",
    })).resolves.toMatchObject({ status: "fallback", reason: "unsupported_coordinate" });
    await expect(resolveCharacterSourceRange(content, REVISION_HASH, {
      ...source,
      source_start: 2,
      source_end: 1,
    })).resolves.toMatchObject({ status: "fallback", reason: "invalid_range" });
    await expect(resolveCharacterSourceRange(content, REVISION_HASH, {
      ...source,
      source_range_hash: "not-a-hash",
    })).resolves.toMatchObject({ status: "fallback", reason: "invalid_range_hash" });
  });

  it("accepts a bounded exact fragment for a hash-verified long range", async () => {
    const content = "潮".repeat(700);
    const excerpt = "潮".repeat(MAX_SOURCE_EXCERPT_CODE_POINTS);
    const source = await locator(content, 0, 700, {
      source_excerpt: excerpt,
      source_excerpt_truncated: true,
    });

    const result = await resolveCharacterSourceRange(content, REVISION_HASH, source);
    expect(result.status).toBe("verified");
    if (result.status === "verified") {
      expect(result.startUtf16).toBe(0);
      expect(result.endUtf16).toBe(700);
    }
  });

  it("bounds unsafe fallback excerpts and reports hash provider failure", async () => {
    const content = "甲".repeat(600);
    const source = await locator(content, 0, 600, {
      source_excerpt: "甲".repeat(600),
      source_excerpt_truncated: true,
    });
    const unavailable: Sha256Text = async () => {
      throw new Error("crypto unavailable");
    };
    const hashFailure = await resolveCharacterSourceRange(content, REVISION_HASH, source, unavailable);
    expect(hashFailure).toMatchObject({ status: "fallback", reason: "hash_unavailable" });
    if (hashFailure.status === "fallback") {
      expect([...hashFailure.excerpt]).toHaveLength(MAX_SOURCE_EXCERPT_CODE_POINTS);
      expect(hashFailure.excerptTruncated).toBe(true);
    }

    const tooLong = await resolveCharacterSourceRange(content, REVISION_HASH, source);
    expect(tooLong).toMatchObject({ status: "fallback", reason: "excerpt_too_long" });
  });
});
