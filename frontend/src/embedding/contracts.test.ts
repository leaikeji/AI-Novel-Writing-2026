import { describe, expect, it } from "vitest";

import {
  EmbeddingContractError,
  candidateCanActivate,
  parseEmbeddingConfigResource,
  parseEmbeddingConnectionTestResult,
  parseNovelEmbeddingConsentResource,
  parseNovelSemanticIndexStatus,
} from "./contracts";
import { config, consent, generation, novelStatus } from "./test-fixtures";


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

  it("freezes the qwen3.7 document space to read-only 2048 dimensions", () => {
    expect(config().requested_dimension).toBe(2048);
    expect(parseEmbeddingConfigResource(config()).requested_dimension).toBe(2048);
    expect(() => parseEmbeddingConfigResource(config({ requested_dimension: 1024 })))
      .toThrow(EmbeddingContractError);
  });

  it("accepts an empty Base URL only for the untouched initial configuration", () => {
    expect(parseEmbeddingConfigResource(config({
      version: 0,
      base_url: "",
      connection_state: "unconfigured",
      api_key_configured: false,
      api_key_masked: null,
      active_generation: null,
      candidate_generation: null,
    })).base_url).toBe("");
    expect(() => parseEmbeddingConfigResource(config({ base_url: "" })))
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

  it("parses consent v2 writing-query authority explicitly", () => {
    const upgraded = parseNovelEmbeddingConsentResource(consent({
      state: "granted",
      consent_id: "33333333-3333-4333-8333-333333333333",
      notice_version: "novel-embedding-consent/2",
      confirmed_at: "2026-08-29T09:00:00Z",
      writing_query_authorized: true,
    }));
    expect(upgraded.writing_query_authorized).toBe(true);
    expect(() => parseNovelEmbeddingConsentResource({
      ...upgraded,
      writing_query_authorized: "yes",
    })).toThrow(EmbeddingContractError);
    expect(() => parseNovelEmbeddingConsentResource({
      ...upgraded,
      notice_version: "novel-embedding-consent/1",
    })).toThrow(EmbeddingContractError);
  });

  it.each(["ready", "updating", "outdated", "partial_failed", "revoked"] as const)(
    "accepts the %s novel synchronization state",
    (state) => {
      const parsed = parseNovelSemanticIndexStatus(novelStatus({
        state,
        sync_state: state === "ready" ? "current" : state,
        index_version: 3,
        authority_digest: "authority-v3",
        published_digest: state === "outdated" ? "authority-v2" : "authority-v3",
      }));
      expect(parsed.state).toBe(state);
    },
  );
});
