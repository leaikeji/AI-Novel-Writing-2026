export const TTS_CLOUD_PROFILES_SCHEMA_VERSION = "tts-cloud-profiles/1" as const;
export const TTS_CLOUD_PROTOCOL = "qwen_audio_native_http/1" as const;


export type TtsCloudTestState = "untested" | "testing" | "passed" | "failed";
export type TtsCloudLifecycleState = "draft" | "verified" | "active" | "disabled";
export type TtsCloudModelSlot = "quality" | "speed";


export interface TtsCloudProfile {
  readonly id: string;
  readonly name: string;
  readonly protocol: typeof TTS_CLOUD_PROTOCOL;
  readonly base_url: string;
  readonly credential_configured: boolean;
  readonly api_key_masked: string | null;
  readonly api_key_updated_at: string | null;
  readonly quality_model_id: string;
  readonly speed_model_id: string | null;
  readonly quality_test_state: TtsCloudTestState;
  readonly speed_test_state: TtsCloudTestState;
  readonly lifecycle_state: TtsCloudLifecycleState;
  readonly version: number;
  readonly last_tested_at: string | null;
  readonly failure_code: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}


export interface TtsCloudProfilesResource {
  readonly schema_version: typeof TTS_CLOUD_PROFILES_SCHEMA_VERSION;
  readonly items: readonly TtsCloudProfile[];
  readonly active_profile_id: string | null;
}


export interface TtsCloudProfileFields {
  readonly name: string;
  readonly protocol: typeof TTS_CLOUD_PROTOCOL;
  readonly base_url: string;
  readonly quality_model_id: string;
  readonly speed_model_id: string | null;
  readonly api_key?: string;
}


export interface CreateTtsCloudProfileRequest extends TtsCloudProfileFields {
  readonly expected_version: 0;
  readonly idempotency_key: string;
}


export interface UpdateTtsCloudProfileRequest extends TtsCloudProfileFields {
  readonly expected_version: number;
  readonly idempotency_key: string;
}


export interface TtsCloudProfileVersionRequest {
  readonly expected_version: number;
  readonly idempotency_key: string;
}


export interface TestTtsCloudProfileRequest extends TtsCloudProfileVersionRequest {
  readonly slot: TtsCloudModelSlot;
  readonly billing_confirmed: true;
}


export interface TtsCloudProfileTestResponse {
  readonly schema_version: typeof TTS_CLOUD_PROFILES_SCHEMA_VERSION;
  readonly profile: TtsCloudProfile;
  readonly slot: TtsCloudModelSlot;
  readonly status: "passed" | "failed";
  readonly actual_model_id: string | null;
  readonly audio_base64: string | null;
  readonly content_type: string | null;
  readonly sample_rate_hz: number | null;
  readonly failure_code: string | null;
}


export class TtsCloudProfileContractError extends Error {
  constructor(readonly field: string, message: string) {
    super(`${field}: ${message}`);
  }
}


function fail(field: string, message: string): never {
  throw new TtsCloudProfileContractError(field, message);
}


function record(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(field, "must be an object");
  }
  return value as Record<string, unknown>;
}


function text(value: unknown, field: string, maxLength = 2048): string {
  if (typeof value !== "string" || !value.trim() || value.length > maxLength) {
    fail(field, "must be a non-empty string");
  }
  return value;
}


function nullableText(value: unknown, field: string, maxLength = 2048): string | null {
  if (value === null) return null;
  return text(value, field, maxLength);
}


function nullableFailureCode(value: unknown, field: string): string | null {
  const parsed = nullableText(value, field, 96);
  if (parsed !== null && !/^[A-Z][A-Z0-9_]{0,95}$/.test(parsed)) {
    fail(field, "must be a stable failure code");
  }
  return parsed;
}


function timestamp(value: unknown, field: string): string {
  const parsed = text(value, field, 64);
  if (Number.isNaN(Date.parse(parsed))) fail(field, "must be an ISO timestamp");
  return parsed;
}


function nullableTimestamp(value: unknown, field: string): string | null {
  if (value === null) return null;
  return timestamp(value, field);
}


function bool(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") fail(field, "must be boolean");
  return value;
}


function integer(value: unknown, field: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) fail(field, "must be a non-negative integer");
  return value as number;
}


function enumeration<T extends string>(
  value: unknown,
  field: string,
  choices: readonly T[],
): T {
  if (typeof value !== "string" || !choices.includes(value as T)) {
    fail(field, `must be one of ${choices.join(", ")}`);
  }
  return value as T;
}


function maskedKey(value: unknown, configured: boolean, field: string): string | null {
  if (value === null) {
    if (configured) fail(field, "must be present when a credential is configured");
    return null;
  }
  const parsed = text(value, field, 32);
  if (!configured || !/^(?:\*{4,}|•{4,})[^*•\s]{1,8}$/.test(parsed)) {
    fail(field, "must be a masked credential hint");
  }
  return parsed;
}


export function parseTtsCloudProfile(value: unknown, field = "profile"): TtsCloudProfile {
  const item = record(value, field);
  const credentialConfigured = bool(item.credential_configured, `${field}.credential_configured`);
  return {
    id: text(item.id, `${field}.id`, 128),
    name: text(item.name, `${field}.name`, 120),
    protocol: enumeration(item.protocol, `${field}.protocol`, [TTS_CLOUD_PROTOCOL]),
    base_url: text(item.base_url, `${field}.base_url`, 2048),
    credential_configured: credentialConfigured,
    api_key_masked: maskedKey(item.api_key_masked, credentialConfigured, `${field}.api_key_masked`),
    api_key_updated_at: nullableTimestamp(item.api_key_updated_at, `${field}.api_key_updated_at`),
    quality_model_id: text(item.quality_model_id, `${field}.quality_model_id`, 256),
    speed_model_id: nullableText(item.speed_model_id, `${field}.speed_model_id`, 256),
    quality_test_state: enumeration(item.quality_test_state, `${field}.quality_test_state`, [
      "untested", "testing", "passed", "failed",
    ]),
    speed_test_state: enumeration(item.speed_test_state, `${field}.speed_test_state`, [
      "untested", "testing", "passed", "failed",
    ]),
    lifecycle_state: enumeration(item.lifecycle_state, `${field}.lifecycle_state`, [
      "draft", "verified", "active", "disabled",
    ]),
    version: integer(item.version, `${field}.version`),
    last_tested_at: nullableTimestamp(item.last_tested_at, `${field}.last_tested_at`),
    failure_code: nullableFailureCode(item.failure_code, `${field}.failure_code`),
    created_at: timestamp(item.created_at, `${field}.created_at`),
    updated_at: timestamp(item.updated_at, `${field}.updated_at`),
  };
}


export function parseTtsCloudProfilesResource(value: unknown): TtsCloudProfilesResource {
  const resource = record(value, "tts_cloud_profiles");
  if (resource.schema_version !== TTS_CLOUD_PROFILES_SCHEMA_VERSION) {
    fail("tts_cloud_profiles.schema_version", `must equal ${TTS_CLOUD_PROFILES_SCHEMA_VERSION}`);
  }
  if (!Array.isArray(resource.items)) fail("tts_cloud_profiles.items", "must be an array");
  const items = resource.items.map((item, index) => parseTtsCloudProfile(item, `tts_cloud_profiles.items[${index}]`));
  if (new Set(items.map((item) => item.id)).size !== items.length) {
    fail("tts_cloud_profiles.items", "must not contain duplicate ids");
  }
  const activeProfileId = resource.active_profile_id === null
    ? null
    : text(resource.active_profile_id, "tts_cloud_profiles.active_profile_id", 128);
  const activeItems = items.filter((item) => item.lifecycle_state === "active");
  if (activeItems.length > 1
    || (activeProfileId === null && activeItems.length !== 0)
    || (activeProfileId !== null && (activeItems.length !== 1 || activeItems[0].id !== activeProfileId))) {
    fail("tts_cloud_profiles.active_profile_id", "must identify the only active profile");
  }
  return {
    schema_version: TTS_CLOUD_PROFILES_SCHEMA_VERSION,
    items,
    active_profile_id: activeProfileId,
  };
}


export function parseTtsCloudProfileTestResponse(value: unknown): TtsCloudProfileTestResponse {
  const result = record(value, "tts_cloud_profile_test");
  if (result.schema_version !== TTS_CLOUD_PROFILES_SCHEMA_VERSION) {
    fail("tts_cloud_profile_test.schema_version", `must equal ${TTS_CLOUD_PROFILES_SCHEMA_VERSION}`);
  }
  const contentType = nullableText(result.content_type, "tts_cloud_profile_test.content_type", 128);
  if (contentType !== null && !contentType.toLowerCase().startsWith("audio/")) {
    fail("tts_cloud_profile_test.content_type", "must be an audio media type");
  }
  const sampleRate = result.sample_rate_hz === null
    ? null
    : integer(result.sample_rate_hz, "tts_cloud_profile_test.sample_rate_hz");
  if (sampleRate !== null && sampleRate > 384_000) {
    fail("tts_cloud_profile_test.sample_rate_hz", "must not exceed 384000");
  }
  return {
    schema_version: TTS_CLOUD_PROFILES_SCHEMA_VERSION,
    profile: parseTtsCloudProfile(result.profile, "tts_cloud_profile_test.profile"),
    slot: enumeration(result.slot, "tts_cloud_profile_test.slot", ["quality", "speed"]),
    status: enumeration(result.status, "tts_cloud_profile_test.status", ["passed", "failed"]),
    actual_model_id: nullableText(result.actual_model_id, "tts_cloud_profile_test.actual_model_id", 256),
    audio_base64: nullableText(result.audio_base64, "tts_cloud_profile_test.audio_base64", 4_000_000),
    content_type: contentType,
    sample_rate_hz: sampleRate,
    failure_code: nullableFailureCode(result.failure_code, "tts_cloud_profile_test.failure_code"),
  };
}
