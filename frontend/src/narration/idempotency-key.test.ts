import { describe, expect, it } from "vitest";

import {
  createNarrationActionUuid,
  createNarrationIdempotencyKey,
} from "./idempotency-key";


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;


describe("narration idempotency keys", () => {
  it("keeps author actions usable without requiring a browser crypto API", () => {
    expect(createNarrationActionUuid()).toMatch(UUID_PATTERN);
    expect(createNarrationIdempotencyKey("official-voice-selection"))
      .toMatch(/^official-voice-selection-[0-9a-f-]{36}$/u);
    expect(createNarrationIdempotencyKey("chapter-tts", ":"))
      .toMatch(/^chapter-tts:[0-9a-f-]{36}$/u);
  });

  it("does not reuse fallback identifiers", () => {
    expect(createNarrationActionUuid()).not.toBe(createNarrationActionUuid());
  });
});
