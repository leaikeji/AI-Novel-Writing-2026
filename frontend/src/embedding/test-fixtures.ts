import type {
  EmbeddingConfigResource,
  EmbeddingGenerationSummary,
  NovelEmbeddingConsentResource,
  NovelSemanticIndexStatus,
} from "./contracts";


export const TEST_NOVEL_ID = "11111111-1111-4111-8111-111111111111";


export function generation(
  changes: Partial<EmbeddingGenerationSummary> = {},
): EmbeddingGenerationSummary {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    generation_number: 2,
    state: "ready",
    model_id: "qwen3.7-text-embedding",
    actual_revision: "2026-08-01",
    dimension: 1024,
    index_fingerprint: "a".repeat(64),
    renderer_bundle_version: "renderers/1",
    authorized_novel_count: 1,
    ready_novel_count: 1,
    pending_novel_count: 0,
    failed_novel_count: 0,
    evaluation_state: "passed",
    activation_eligible: true,
    ...changes,
  };
}


export function config(
  changes: Partial<EmbeddingConfigResource> = {},
): EmbeddingConfigResource {
  return {
    schema_version: "embedding-config/1",
    provider_id: "aliyun-bailian",
    provider_label: "阿里云百炼",
    protocol: "dashscope-native-v1",
    protocol_label: "DashScope Native",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    api_key_configured: true,
    connection_state: "ready",
    requested_model_id: "qwen3.7-text-embedding",
    requested_dimension: 1024,
    active_generation: generation({
      state: "active",
      generation_number: 1,
      activation_eligible: false,
    }),
    candidate_generation: generation(),
    previous_generation: null,
    authorized_novel_count: 1,
    pending_rebuild_novel_count: 0,
    failed_novel_count: 0,
    last_request: null,
    ...changes,
  };
}


export function consent(
  changes: Partial<NovelEmbeddingConsentResource> = {},
): NovelEmbeddingConsentResource {
  return {
    novel_id: TEST_NOVEL_ID,
    state: "not_granted",
    consent_id: null,
    version: 0,
    notice_version: null,
    provider_id: null,
    model_id: null,
    confirmed_at: null,
    revoked_at: null,
    ...changes,
  };
}


export function novelStatus(
  changes: Partial<NovelSemanticIndexStatus> = {},
): NovelSemanticIndexStatus {
  return {
    novel_id: TEST_NOVEL_ID,
    state: "not_authorized",
    active_model_id: null,
    active_dimension: null,
    active_generation_number: null,
    corpora: [],
    source_count: 0,
    chunk_count: 0,
    failure_count: 0,
    last_indexed_at: null,
    error_summary: null,
    can_rebuild: false,
    can_cancel: false,
    can_retry_failed: false,
    has_local_vectors: false,
    ...changes,
  };
}
