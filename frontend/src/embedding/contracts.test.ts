import { describe, expect, it } from "vitest";

import {
  EmbeddingContractError,
  candidateCanActivate,
  parseEmbeddingConfigResource,
  parseEmbeddingConnectionTestResult,
  parseNovelSemanticIndexStatus,
} from "./contracts";
import { config, generation, novelStatus } from "./test-fixtures";


describe("embedding wire contracts", () => {
  it("never exposes an API key field from a response", () => {
    const parsed = parseEmbeddingConfigResource({
      ...config(),
      api_key: "should-never-reach-ui",
      api_key_last4: "1234",
      api_key_last8: "12345678",
    });

    expect(parsed.api_key_configured).toBe(true);
    expect("api_key" in parsed).toBe(false);
    expect("api_key_last4" in parsed).toBe(false);
    expect("api_key_last8" in parsed).toBe(false);
    expect(parsed.api_key_masked).toBe("********cret");
    expect(JSON.stringify(parsed)).not.toContain("should-never-reach-ui");
    expect(JSON.stringify(parsed)).not.toContain("12345678");
  });

  it("rejects a credential hint that is not masked", () => {
    expect(() => parseEmbeddingConfigResource(config({
      api_key_masked: "sk-raw-secret-value",
    }))).toThrow(EmbeddingContractError);
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

  it("uses 2048 by default while accepting only documented dimensions", () => {
    expect(config().requested_dimension).toBe(2048);
    expect(parseEmbeddingConfigResource(config({ requested_dimension: 1024 })).requested_dimension)
      .toBe(1024);
    expect(() => parseEmbeddingConfigResource(config({ requested_dimension: 1234 })))
      .toThrow(EmbeddingContractError);
  });

  it("keeps separate query and document sentinel request evidence", () => {
    const parsed = parseEmbeddingConnectionTestResult({
      connection_state: "ready",
      actual_model_id: "qwen3.7-text-embedding",
      actual_revision: null,
      actual_dimension: 2048,
      request_id: "query-request",
      document_request_id: "document-request",
      token_count: 8,
      latency_ms: 12,
      error_summary: null,
    });
    expect(parsed.request_id).toBe("query-request");
    expect(parsed.document_request_id).toBe("document-request");
    expect(() => parseEmbeddingConnectionTestResult({
      ...parsed,
      actual_dimension: 1234,
    })).toThrow(EmbeddingContractError);
  });

  it("rejects cross-novel or malformed counters at the parser boundary", () => {
    expect(() => parseNovelSemanticIndexStatus({
      ...novelStatus(),
      chunk_count: -1,
    })).toThrow(EmbeddingContractError);
  });
});
