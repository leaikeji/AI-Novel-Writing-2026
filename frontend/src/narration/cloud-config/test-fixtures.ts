import { TTS_CLOUD_PROFILES_SCHEMA_VERSION, TTS_CLOUD_PROTOCOL } from "./contracts";
import type {
  TtsCloudProfile,
  TtsCloudProfilesResource,
  TtsCloudProfileTestResponse,
} from "./contracts";


export function cloudProfile(
  patch: Partial<TtsCloudProfile> = {},
): TtsCloudProfile {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    name: "会员渠道 A",
    protocol: TTS_CLOUD_PROTOCOL,
    base_url: "https://voice.example.com/qwen",
    credential_configured: true,
    api_key_masked: "********1234",
    api_key_updated_at: "2026-09-08T10:00:00Z",
    quality_model_id: "qwen-audio-3.0-tts-plus",
    speed_model_id: "qwen-audio-3.0-tts-flash",
    quality_test_state: "passed",
    speed_test_state: "passed",
    lifecycle_state: "verified",
    version: 3,
    last_tested_at: "2026-09-08T10:01:00Z",
    failure_code: null,
    created_at: "2026-09-08T09:00:00Z",
    updated_at: "2026-09-08T10:01:00Z",
    ...patch,
  };
}


export function cloudProfiles(
  patch: Partial<TtsCloudProfilesResource> = {},
): TtsCloudProfilesResource {
  return {
    schema_version: TTS_CLOUD_PROFILES_SCHEMA_VERSION,
    items: [cloudProfile()],
    active_profile_id: null,
    ...patch,
  };
}


export function cloudTestResponse(
  patch: Partial<TtsCloudProfileTestResponse> = {},
): TtsCloudProfileTestResponse {
  return {
    schema_version: TTS_CLOUD_PROFILES_SCHEMA_VERSION,
    profile: cloudProfile({ version: 4 }),
    slot: "quality",
    status: "passed",
    actual_model_id: "qwen-audio-3.0-tts-plus",
    audio_base64: null,
    content_type: null,
    sample_rate_hz: 24_000,
    failure_code: null,
    ...patch,
  };
}
