export const EMBEDDING_CONFIG_SCHEMA_VERSION = "embedding-config/1" as const;
export const NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION = "novel-embedding-consent/1" as const;
export const SUPPORTED_EMBEDDING_DIMENSIONS = [
  256, 512, 768, 1024, 1536, 2048, 2560,
] as const;
export const DEFAULT_EMBEDDING_DIMENSION = 2048;


export type EmbeddingConnectionState =
  | "unconfigured"
  | "untested"
  | "ready"
  | "failed";


export type EmbeddingGenerationState =
  | "draft"
  | "building"
  | "ready"
  | "active"
  | "failed"
  | "cancelled"
  | "stale"
  | "retired";


export type EmbeddingEvaluationState = "pending" | "passed" | "failed" | "not_run";


export interface EmbeddingGenerationSummary {
  readonly id: string;
  readonly generation_number: number;
  readonly state: EmbeddingGenerationState;
  readonly model_id: string;
  readonly actual_revision: string | null;
  readonly dimension: number;
  readonly index_fingerprint: string;
  readonly renderer_bundle_version: string;
  readonly authorized_novel_count: number;
  readonly ready_novel_count: number;
  readonly pending_novel_count: number;
  readonly failed_novel_count: number;
  readonly evaluation_state: EmbeddingEvaluationState;
  readonly activation_eligible: boolean;
}


export interface EmbeddingRequestEvidence {
  readonly request_id: string | null;
  readonly document_request_id: string | null;
  readonly token_count: number | null;
  readonly latency_ms: number | null;
  readonly error_summary: string | null;
  readonly observed_at: string | null;
}


export interface EmbeddingConfigResource {
  readonly version: number;
  readonly schema_version: typeof EMBEDDING_CONFIG_SCHEMA_VERSION;
  readonly provider_id: "aliyun-bailian";
  readonly provider_label: "阿里云百炼";
  readonly protocol: "dashscope-native-v1";
  readonly protocol_label: "DashScope Native";
  readonly base_url: string;
  readonly secret_store_ready: boolean;
  readonly api_key_configured: boolean;
  readonly api_key_masked: string | null;
  readonly credential_cleanup_warning: string | null;
  readonly connection_state: EmbeddingConnectionState;
  readonly requested_model_id: string;
  readonly requested_dimension: number;
  readonly active_generation: EmbeddingGenerationSummary | null;
  readonly candidate_generation: EmbeddingGenerationSummary | null;
  readonly previous_generation: EmbeddingGenerationSummary | null;
  readonly authorized_novel_count: number;
  readonly pending_rebuild_novel_count: number;
  readonly failed_novel_count: number;
  readonly last_request: EmbeddingRequestEvidence | null;
}


export interface SaveEmbeddingCandidateRequest {
  readonly expected_version: number;
  readonly base_url: string;
  readonly requested_model_id: string;
  readonly requested_dimension: number;
  readonly api_key_action: "keep" | "replace" | "clear";
  readonly api_key?: string;
}


export interface TestEmbeddingConnectionRequest {
  readonly base_url: string;
  readonly requested_model_id: string;
  readonly requested_dimension: number;
  readonly api_key?: string;
}


export interface EmbeddingConnectionTestResult {
  readonly connection_state: "ready" | "failed";
  readonly actual_model_id: string | null;
  readonly actual_revision: string | null;
  readonly actual_dimension: number | null;
  readonly request_id: string | null;
  readonly document_request_id: string | null;
  readonly token_count: number | null;
  readonly latency_ms: number | null;
  readonly error_summary: string | null;
}


export type NovelEmbeddingConsentState = "not_granted" | "granted" | "revoked";


export interface NovelEmbeddingConsentResource {
  readonly novel_id: string;
  readonly state: NovelEmbeddingConsentState;
  readonly consent_id: string | null;
  readonly version: number;
  readonly notice_version: string | null;
  readonly provider_id: string | null;
  readonly model_id: string | null;
  readonly confirmed_at: string | null;
  readonly revoked_at: string | null;
}


export interface PutNovelEmbeddingConsentRequest {
  readonly action: "grant" | "revoke";
  readonly expected_version: number;
  readonly notice_version: typeof NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION;
  readonly acknowledged_scopes: readonly [
    "formal_manuscript",
    "formal_planning",
    "author_secrets",
    "bound_private_assets",
  ];
}


export type SemanticCorpus =
  | "manuscript"
  | "planning"
  | "private_asset"
  | "character"
  | "relationship"
  | "story_event"
  | "storyline"
  | "foreshadow"
  | "timeline";


export type SemanticCorpusState =
  | "disabled"
  | "empty"
  | "pending"
  | "building"
  | "ready"
  | "failed"
  | "stale";


export interface SemanticCorpusStatus {
  readonly corpus: SemanticCorpus;
  readonly state: SemanticCorpusState;
  readonly source_count: number;
  readonly chunk_count: number;
  readonly failure_count: number;
  readonly reason_code: string | null;
}


export type NovelSemanticIndexState =
  | "not_authorized"
  | "empty"
  | "current"
  | "update_pending"
  | "building"
  | "partial_failure"
  | "stale";


export interface NovelSemanticIndexStatus {
  readonly novel_id: string;
  readonly state: NovelSemanticIndexState;
  readonly active_model_id: string | null;
  readonly active_dimension: number | null;
  readonly active_generation_number: number | null;
  readonly corpora: readonly SemanticCorpusStatus[];
  readonly source_count: number;
  readonly chunk_count: number;
  readonly failure_count: number;
  readonly last_indexed_at: string | null;
  readonly error_summary: string | null;
  readonly can_rebuild: boolean;
  readonly can_cancel: boolean;
  readonly can_retry_failed: boolean;
  readonly has_local_vectors: boolean;
}


export class EmbeddingContractError extends Error {
  constructor(readonly field: string, message: string) {
    super(`${field}: ${message}`);
  }
}


function record(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new EmbeddingContractError(field, "must be an object");
  }
  return value as Record<string, unknown>;
}


function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new EmbeddingContractError(field, "must be a non-empty string");
  }
  return value;
}


function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new EmbeddingContractError(field, "must be a string");
  }
  return value;
}


function nullableText(value: unknown, field: string): string | null {
  if (value === null) return null;
  return text(value, field);
}


function boolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new EmbeddingContractError(field, "must be boolean");
  return value;
}


function integer(value: unknown, field: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new EmbeddingContractError(field, `must be an integer >= ${minimum}`);
  }
  return value as number;
}


function nullableInteger(value: unknown, field: string, minimum = 0): number | null {
  if (value === null) return null;
  return integer(value, field, minimum);
}


function embeddingDimension(value: unknown, field: string): number {
  const parsed = integer(value, field, 1);
  if (!SUPPORTED_EMBEDDING_DIMENSIONS.includes(
    parsed as (typeof SUPPORTED_EMBEDDING_DIMENSIONS)[number],
  )) {
    throw new EmbeddingContractError(field, "is not supported by qwen3.7-text-embedding");
  }
  return parsed;
}


function enumValue<T extends string>(
  value: unknown,
  field: string,
  choices: readonly T[],
): T {
  if (typeof value !== "string" || !choices.includes(value as T)) {
    throw new EmbeddingContractError(field, `must be one of ${choices.join(", ")}`);
  }
  return value as T;
}


const GENERATION_STATES: readonly EmbeddingGenerationState[] = [
  "draft", "building", "ready", "active", "failed", "cancelled", "stale", "retired",
];
const EVALUATION_STATES: readonly EmbeddingEvaluationState[] = [
  "pending", "passed", "failed", "not_run",
];


function parseGeneration(value: unknown, field: string): EmbeddingGenerationSummary | null {
  if (value === null) return null;
  const item = record(value, field);
  const dimension = embeddingDimension(item.dimension, `${field}.dimension`);
  const state = enumValue(item.state, `${field}.state`, GENERATION_STATES);
  const failed = integer(item.failed_novel_count, `${field}.failed_novel_count`);
  const pending = integer(item.pending_novel_count, `${field}.pending_novel_count`);
  const evaluation = enumValue(
    item.evaluation_state,
    `${field}.evaluation_state`,
    EVALUATION_STATES,
  );
  const eligible = boolean(item.activation_eligible, `${field}.activation_eligible`);
  if (eligible && (state !== "ready" || failed !== 0 || pending !== 0 || evaluation !== "passed")) {
    throw new EmbeddingContractError(field, "activation eligibility violates readiness gates");
  }
  return {
    id: text(item.id, `${field}.id`),
    generation_number: integer(item.generation_number, `${field}.generation_number`, 1),
    state,
    model_id: text(item.model_id, `${field}.model_id`),
    actual_revision: nullableText(item.actual_revision, `${field}.actual_revision`),
    dimension,
    index_fingerprint: text(item.index_fingerprint, `${field}.index_fingerprint`),
    renderer_bundle_version: text(
      item.renderer_bundle_version,
      `${field}.renderer_bundle_version`,
    ),
    authorized_novel_count: integer(
      item.authorized_novel_count,
      `${field}.authorized_novel_count`,
    ),
    ready_novel_count: integer(item.ready_novel_count, `${field}.ready_novel_count`),
    pending_novel_count: pending,
    failed_novel_count: failed,
    evaluation_state: evaluation,
    activation_eligible: eligible,
  };
}


export function parseEmbeddingConfigResource(value: unknown): EmbeddingConfigResource {
  const item = record(value, "embedding_config");
  if (item.schema_version !== EMBEDDING_CONFIG_SCHEMA_VERSION) {
    throw new EmbeddingContractError("schema_version", "is unsupported");
  }
  if (item.provider_id !== "aliyun-bailian" || item.provider_label !== "阿里云百炼") {
    throw new EmbeddingContractError("provider_id", "is unsupported");
  }
  if (item.protocol !== "dashscope-native-v1" || item.protocol_label !== "DashScope Native") {
    throw new EmbeddingContractError("protocol", "is unsupported");
  }
  const apiKeyConfigured = boolean(item.api_key_configured, "api_key_configured");
  const secretStoreReady = boolean(item.secret_store_ready, "secret_store_ready");
  const apiKeyMasked = nullableText(item.api_key_masked, "api_key_masked");
  if (apiKeyMasked !== null && (
    apiKeyMasked.length !== 12
    || !apiKeyMasked.startsWith("********")
  )) {
    throw new EmbeddingContractError("api_key_masked", "is not a safe masked credential hint");
  }
  if (!apiKeyConfigured && apiKeyMasked !== null) {
    throw new EmbeddingContractError("api_key_masked", "must match credential state");
  }
  const version = integer(item.version, "version");
  const connectionState = enumValue(
    item.connection_state,
    "connection_state",
    ["unconfigured", "untested", "ready", "failed"],
  );
  const baseUrl = stringValue(item.base_url, "base_url");
  if (!baseUrl.trim() && (version !== 0 || connectionState !== "unconfigured")) {
    throw new EmbeddingContractError(
      "base_url",
      "may be blank only before the first configuration",
    );
  }
  return {
    version,
    schema_version: EMBEDDING_CONFIG_SCHEMA_VERSION,
    provider_id: "aliyun-bailian",
    provider_label: "阿里云百炼",
    protocol: "dashscope-native-v1",
    protocol_label: "DashScope Native",
    base_url: baseUrl,
    secret_store_ready: secretStoreReady,
    api_key_configured: apiKeyConfigured,
    api_key_masked: apiKeyMasked,
    credential_cleanup_warning: nullableText(
      item.credential_cleanup_warning,
      "credential_cleanup_warning",
    ),
    connection_state: connectionState,
    requested_model_id: text(item.requested_model_id, "requested_model_id"),
    requested_dimension: embeddingDimension(item.requested_dimension, "requested_dimension"),
    active_generation: parseGeneration(item.active_generation, "active_generation"),
    candidate_generation: parseGeneration(item.candidate_generation, "candidate_generation"),
    previous_generation: parseGeneration(item.previous_generation, "previous_generation"),
    authorized_novel_count: integer(item.authorized_novel_count, "authorized_novel_count"),
    pending_rebuild_novel_count: integer(
      item.pending_rebuild_novel_count,
      "pending_rebuild_novel_count",
    ),
    failed_novel_count: integer(item.failed_novel_count, "failed_novel_count"),
    last_request: parseRequestEvidence(item.last_request),
  };
}


function parseRequestEvidence(value: unknown): EmbeddingRequestEvidence | null {
  if (value === null) return null;
  const item = record(value, "last_request");
  return {
    request_id: nullableText(item.request_id, "last_request.request_id"),
    document_request_id: nullableText(
      item.document_request_id,
      "last_request.document_request_id",
    ),
    token_count: nullableInteger(item.token_count, "last_request.token_count"),
    latency_ms: nullableInteger(item.latency_ms, "last_request.latency_ms"),
    error_summary: nullableText(item.error_summary, "last_request.error_summary"),
    observed_at: nullableText(item.observed_at, "last_request.observed_at"),
  };
}


export function parseEmbeddingConnectionTestResult(
  value: unknown,
): EmbeddingConnectionTestResult {
  const item = record(value, "connection_test");
  const actualDimension = item.actual_dimension === null
    ? null
    : embeddingDimension(item.actual_dimension, "actual_dimension");
  return {
    connection_state: enumValue(item.connection_state, "connection_state", ["ready", "failed"]),
    actual_model_id: nullableText(item.actual_model_id, "actual_model_id"),
    actual_revision: nullableText(item.actual_revision, "actual_revision"),
    actual_dimension: actualDimension,
    request_id: nullableText(item.request_id, "request_id"),
    document_request_id: nullableText(item.document_request_id, "document_request_id"),
    token_count: nullableInteger(item.token_count, "token_count"),
    latency_ms: nullableInteger(item.latency_ms, "latency_ms"),
    error_summary: nullableText(item.error_summary, "error_summary"),
  };
}


export function parseNovelEmbeddingConsentResource(
  value: unknown,
): NovelEmbeddingConsentResource {
  const item = record(value, "embedding_consent");
  return {
    novel_id: text(item.novel_id, "novel_id"),
    state: enumValue(item.state, "state", ["not_granted", "granted", "revoked"]),
    consent_id: nullableText(item.consent_id, "consent_id"),
    version: integer(item.version, "version"),
    notice_version: nullableText(item.notice_version, "notice_version"),
    provider_id: nullableText(item.provider_id, "provider_id"),
    model_id: nullableText(item.model_id, "model_id"),
    confirmed_at: nullableText(item.confirmed_at, "confirmed_at"),
    revoked_at: nullableText(item.revoked_at, "revoked_at"),
  };
}


const CORPORA: readonly SemanticCorpus[] = [
  "manuscript", "planning", "private_asset", "character", "relationship",
  "story_event", "storyline", "foreshadow", "timeline",
];
const CORPUS_STATES: readonly SemanticCorpusState[] = [
  "disabled", "empty", "pending", "building", "ready", "failed", "stale",
];


function parseCorpus(value: unknown, index: number): SemanticCorpusStatus {
  const item = record(value, `corpora.${index}`);
  return {
    corpus: enumValue(item.corpus, `corpora.${index}.corpus`, CORPORA),
    state: enumValue(item.state, `corpora.${index}.state`, CORPUS_STATES),
    source_count: integer(item.source_count, `corpora.${index}.source_count`),
    chunk_count: integer(item.chunk_count, `corpora.${index}.chunk_count`),
    failure_count: integer(item.failure_count, `corpora.${index}.failure_count`),
    reason_code: nullableText(item.reason_code, `corpora.${index}.reason_code`),
  };
}


export function parseNovelSemanticIndexStatus(value: unknown): NovelSemanticIndexStatus {
  const item = record(value, "semantic_index_status");
  if (!Array.isArray(item.corpora)) {
    throw new EmbeddingContractError("corpora", "must be an array");
  }
  return {
    novel_id: text(item.novel_id, "novel_id"),
    state: enumValue(
      item.state,
      "state",
      [
        "not_authorized", "empty", "current", "update_pending", "building",
        "partial_failure", "stale",
      ],
    ),
    active_model_id: nullableText(item.active_model_id, "active_model_id"),
    active_dimension: nullableInteger(item.active_dimension, "active_dimension", 1),
    active_generation_number: nullableInteger(
      item.active_generation_number,
      "active_generation_number",
      1,
    ),
    corpora: item.corpora.map(parseCorpus),
    source_count: integer(item.source_count, "source_count"),
    chunk_count: integer(item.chunk_count, "chunk_count"),
    failure_count: integer(item.failure_count, "failure_count"),
    last_indexed_at: nullableText(item.last_indexed_at, "last_indexed_at"),
    error_summary: nullableText(item.error_summary, "error_summary"),
    can_rebuild: boolean(item.can_rebuild, "can_rebuild"),
    can_cancel: boolean(item.can_cancel, "can_cancel"),
    can_retry_failed: boolean(item.can_retry_failed, "can_retry_failed"),
    has_local_vectors: boolean(item.has_local_vectors, "has_local_vectors"),
  };
}


export function candidateCanActivate(
  candidate: EmbeddingGenerationSummary | null,
): boolean {
  return candidate !== null
    && candidate.state === "ready"
    && candidate.pending_novel_count === 0
    && candidate.failed_novel_count === 0
    && candidate.evaluation_state === "passed"
    && candidate.activation_eligible;
}
