import { describe, expect, it } from "vitest";

import {
  EmbeddingContractError,
  candidateCanActivate,
  parseEmbeddingConfigResource,
  parseNovelSemanticIndexStatus,
} from "./contracts";
import { config, generation, novelStatus } from "./test-fixtures";


describe("embedding wire contracts", () => {
  it("never exposes an API key field from a response", () => {
    const parsed = parseEmbeddingConfigResource({
      ...config(),
      api_key: "should-never-reach-ui",
      api_key_last4: "1234",
    });

    expect(parsed.api_key_configured).toBe(true);
    expect("api_key" in parsed).toBe(false);
    expect("api_key_last4" in parsed).toBe(false);
    expect(JSON.stringify(parsed)).not.toContain("should-never-reach-ui");
  });

  it("rejects an activation flag that bypasses readiness gates", () => {
    expect(() => parseEmbeddingConfigResource(config({
      candidate_generation: generation({
        state: "building",
        activation_eligible: true,
      }),
    }))).toThrow(EmbeddingContractError);

    expect(candidateCanActivate(generation({ pending_novel_count: 1 }))).toBe(false);
    expect(candidateCanActivate(generation())).toBe(true);
  });

  it("rejects cross-novel or malformed counters at the parser boundary", () => {
    expect(() => parseNovelSemanticIndexStatus({
      ...novelStatus(),
      chunk_count: -1,
    })).toThrow(EmbeddingContractError);
  });
});
