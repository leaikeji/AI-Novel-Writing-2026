export const NARRATION_SETTINGS_API_VERSION = "narration-settings-api/1" as const;
export const NARRATION_SETTINGS_SCHEMA_VERSION = "narration-settings/1" as const;
export const NARRATION_CAPABILITY_SCHEMA_VERSION = "narration-capabilities/1" as const;
export const NARRATION_VOICE_SCHEMA_VERSION = "narration-voice/1" as const;
export const NARRATION_CACHE_SCHEMA_VERSION = "narration-cache/1" as const;
export const OFFICIAL_PRESET_CATALOG_SCHEMA_VERSION = "moss-tts-official-preset-catalog/1.0" as const;
export const OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION = "moss-tts-official-preset-provenance/1.0" as const;
export const OFFICIAL_PRESET_MANIFEST_IDENTITY = Object.freeze({
  repository: "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
  revision: "f52645cb467506d8e18e746ddd59482685b74e58",
  manifestPath: "browser_poc_manifest.json",
  manifestSha256: "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee",
  modelFingerprintSha256: "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d",
} as const);
export const OFFICIAL_PRESET_EVIDENCE = Object.freeze([
  { presetId: "onnx.Junhao", manifestVoice: "Junhao", promptCodesSha256: "395976042d458c44977c43b9b20a9945100cbf0302381e5d25e46b43304aa6d4", promptFrameCount: 98, promptQuantizerCount: 16, provenanceFingerprintSha256: "326ab61540e48d53b7260ac26c9fdc9a614b0e637b786d8b98b5537c1630fbfc" },
  { presetId: "onnx.Zhiming", manifestVoice: "Zhiming", promptCodesSha256: "6574897aab814be3b155f073683e4f19a3e5f1ab92ddfa66bec5b7911cf4099e", promptFrameCount: 98, promptQuantizerCount: 16, provenanceFingerprintSha256: "ca76d9acb3f5dd8e016de3d343890377506a0b80a0a202e7fdcb41693a412165" },
  { presetId: "onnx.Weiguo", manifestVoice: "Weiguo", promptCodesSha256: "cbfa9212b4f8ec64172f7057c92dc8ec9a1731530b012bd9dfb3b1e297624ee6", promptFrameCount: 140, promptQuantizerCount: 16, provenanceFingerprintSha256: "c7c806879dc2c1297a064494968c65b2722ec9c01ed63011d2355452e7f869cb" },
  { presetId: "onnx.Xiaoyu", manifestVoice: "Xiaoyu", promptCodesSha256: "847277bcef201396ef1aa6adbc8e55a25c9b0b8e3cfa3c72ac306053224022be", promptFrameCount: 180, promptQuantizerCount: 16, provenanceFingerprintSha256: "a4596aa05d4e83fece97ebbede2448f461a1e72c052999b83a4e265d2424b1e1" },
  { presetId: "onnx.Yuewen", manifestVoice: "Yuewen", promptCodesSha256: "bed66ac01188f639b18f1a8cfd1520d6fbf0c319d27c282b1dc1cd3e9a8a888f", promptFrameCount: 102, promptQuantizerCount: 16, provenanceFingerprintSha256: "6f511f808df639459f2a19988373c467353d85f16ef1285c4dcd16d6a0388fd5" },
  { presetId: "onnx.Lingyu", manifestVoice: "Lingyu", promptCodesSha256: "761b4a0b0c3e0cec067c76b9a21560d8c8b0e302f67e16f0bf090e288c6fb3b0", promptFrameCount: 218, promptQuantizerCount: 16, provenanceFingerprintSha256: "bc58162f87697ee9cb392a41360aa2708cb113911a880b8b17bd1cab3336e4c4" },
  { presetId: "onnx.Trump", manifestVoice: "Trump", promptCodesSha256: "3055948dd0646a7d1a72de824d33ab069ca3a2a5489a78f22818314a3d2e9d27", promptFrameCount: 97, promptQuantizerCount: 16, provenanceFingerprintSha256: "9453af79dfc557e9694fe7b74c5d45aac5193976a46fc7bac0b0e5343f2a2df7" },
  { presetId: "onnx.Ava", manifestVoice: "Ava", promptCodesSha256: "892a532b562d79fe683640e98f2e061683e4ea7bc93929d0866a1f5dae30ba48", promptFrameCount: 98, promptQuantizerCount: 16, provenanceFingerprintSha256: "e239d4a89759565dc1b9bc0dec1076175b201ebd1c9a1fbdb309ee23cc2dfbca" },
  { presetId: "onnx.Bella", manifestVoice: "Bella", promptCodesSha256: "d4def268888ebb0575d3bb8b1428bdea252af26e68281c43218432ddc9b0cda4", promptFrameCount: 59, promptQuantizerCount: 16, provenanceFingerprintSha256: "e6aac49a5fc35da9ba16011d301bb0a4f123899662cf6e1c32059f06a54f315a" },
  { presetId: "onnx.Adam", manifestVoice: "Adam", promptCodesSha256: "14ffba3b57fdd50e16f431ba6631bf9b26d4c8ae1ec671ab73c1dea61e2835b7", promptFrameCount: 59, promptQuantizerCount: 16, provenanceFingerprintSha256: "bd1bc9c09392cd0dd91d51c84203b7ba47e867a2ebb96d30a30570e5afeb984b" },
  { presetId: "onnx.Nathan", manifestVoice: "Nathan", promptCodesSha256: "3e4bdb8ba9884ebf028efafb1535af784bb792a2695a25e571abc0a9cd18072e", promptFrameCount: 168, promptQuantizerCount: 16, provenanceFingerprintSha256: "fbff41f1ca65091452e1c1ea87977b1fcf3ab4b84349b571708782a6f10b089e" },
  { presetId: "onnx.Soyo", manifestVoice: "Soyo", promptCodesSha256: "d2079895cc7f2ec931a983e8f16150cc322c37bf0b62135507126736ee70e4e1", promptFrameCount: 125, promptQuantizerCount: 16, provenanceFingerprintSha256: "098d2be9b24966c33f02426fde42cd5dbe202af2cbbbab3a3d77620ea1f78d00" },
  { presetId: "onnx.Saki", manifestVoice: "Saki", promptCodesSha256: "85f916c338c1a26f5e91b90b71f7942bfb3c465e999d97a12b24644258de18bd", promptFrameCount: 32, promptQuantizerCount: 16, provenanceFingerprintSha256: "315c6209c41c42ca7bb1af0751abec5b485e797b523f2651213a2d13fece7e26" },
  { presetId: "onnx.Mortis", manifestVoice: "Mortis", promptCodesSha256: "9976030044c8746d488fa1cdf470e43760429bf73113819f9da15784bf4d4449", promptFrameCount: 60, promptQuantizerCount: 16, provenanceFingerprintSha256: "85fb4a3e306800a4ee149bf2ae61c48ed5fbda481cd6793b06f53ba2d5d6feeb" },
  { presetId: "onnx.Umiri", manifestVoice: "Umiri", promptCodesSha256: "72bdf9fb4dfcd4405ec216030a73bf004856b6cf66b100c040fe36bea6165d43", promptFrameCount: 77, promptQuantizerCount: 16, provenanceFingerprintSha256: "70b75b849369d4105f933c8ed0f1eaa95ef177831a54af3b7463c53876dfc6bc" },
  { presetId: "onnx.Mei", manifestVoice: "Mei", promptCodesSha256: "2068325ad43d3589bcffcb2f8a969eb7ff6570de4736aa3221553537c6232b1a", promptFrameCount: 49, promptQuantizerCount: 16, provenanceFingerprintSha256: "918b378414f000c70ec12c52ba855485ad91d203c5a9327ef89f4ad9e5fb4cf1" },
  { presetId: "onnx.Anon", manifestVoice: "Anon", promptCodesSha256: "566b5098c19390f178cba0e1d16961ff45a225677adbb6f0bc2315c20954a5ee", promptFrameCount: 47, promptQuantizerCount: 16, provenanceFingerprintSha256: "5fb427ac6ee3a3954b3e5f438eb088e8dca69b530cba9bda8e3251278a9b118c" },
  { presetId: "onnx.Arisa", manifestVoice: "Arisa", promptCodesSha256: "2cf65c28e3bb62c93195a1d0778578d10c0ef71a42a66dcbe613592efb17dd5f", promptFrameCount: 85, promptQuantizerCount: 16, provenanceFingerprintSha256: "e20733cefd52a2daa3e5ceb655c85d04ab93d8c312b485b63a7d59e408ff00d7" },
] as const);
export type OfficialPresetId = typeof OFFICIAL_PRESET_EVIDENCE[number]["presetId"];
export const OFFICIAL_PRESET_IDS: readonly OfficialPresetId[] = Object.freeze(
  OFFICIAL_PRESET_EVIDENCE.map((item) => item.presetId),
);
export const PRODUCT_OFFICIAL_PRESET_EVIDENCE = Object.freeze([
  OFFICIAL_PRESET_EVIDENCE[0],
  OFFICIAL_PRESET_EVIDENCE[1],
  OFFICIAL_PRESET_EVIDENCE[2],
  OFFICIAL_PRESET_EVIDENCE[3],
  OFFICIAL_PRESET_EVIDENCE[4],
  OFFICIAL_PRESET_EVIDENCE[5],
] as const);
export type ProductOfficialPresetId = typeof PRODUCT_OFFICIAL_PRESET_EVIDENCE[number]["presetId"];
export const PRODUCT_OFFICIAL_PRESET_IDS: readonly ProductOfficialPresetId[] = Object.freeze(
  PRODUCT_OFFICIAL_PRESET_EVIDENCE.map((item) => item.presetId),
);
export const REFERENCE_UPLOAD_MAX_BYTES = 16 * 1024 * 1024;
export const REFERENCE_UPLOAD_MIME_TYPES = ["audio/wav", "audio/flac"] as const;

export const CAPABILITY_KEYS = [
  "narration_product",
  "reading_settings",
  "narration_synthesis",
  "product_player",
  "editor_production",
  "voice_preview",
  "preset_voice_source",
  "reference_clone",
  "generic_voice_pool",
  "automatic_generic_casting",
  "automatic_speaker_detection",
  "cloud_assisted_analysis",
  "voice_generator",
  "cache_cleanup",
] as const;

export type CapabilityKey = typeof CAPABILITY_KEYS[number];
export type CapabilityState = "enabled" | "disabled" | "unavailable" | "hold";

export const T4_PRODUCT_CAPABILITY_KEYS = [
  "narration_product",
  "reading_settings",
  "narration_synthesis",
  "product_player",
  "editor_production",
  "automatic_speaker_detection",
  "cache_cleanup",
] as const satisfies readonly CapabilityKey[];

export interface FeatureCapability {
  readonly key: CapabilityKey;
  readonly state: CapabilityState;
  readonly visible: boolean;
  readonly actionable: boolean;
  readonly reason_code: string | null;
  readonly required_gate: string | null;
}

export interface NarrationCapabilities {
  readonly schema_version: typeof NARRATION_CAPABILITY_SCHEMA_VERSION;
  readonly items: readonly FeatureCapability[];
}

export const NARRATION_ERROR_CODES = [
  "REQUEST_VALIDATION_FAILED",
  "RESPONSE_CONTRACT_VIOLATION",
  "SETTINGS_BACKEND_NOT_INSTALLED",
  "CAPABILITY_DISABLED",
  "MODEL_UNAVAILABLE",
  "STORAGE_UNAVAILABLE",
  "DISK_SPACE_INSUFFICIENT",
  "RESOURCE_NOT_FOUND",
  "SCOPE_VIOLATION",
  "VERSION_CONFLICT",
  "INVALID_STATE",
  "IDEMPOTENCY_CONFLICT",
  "VOICE_PROFILE_NOT_FOUND",
  "VOICE_VERSION_NOT_FOUND",
  "VOICE_VERSION_NOT_LOCKED",
  "VOICE_RIGHTS_REQUIRED",
  "VOICE_RIGHTS_UNAVAILABLE",
  "VOICE_SOURCE_UNAVAILABLE",
  "REFERENCE_AUDIO_INVALID",
  "PREVIEW_UNAVAILABLE",
  "PREVIEW_FAILED",
  "CLOUD_CONSENT_REQUIRED",
  "CLOUD_CONSENT_REVOKED",
  "GENERIC_VOICE_POOL_UNAVAILABLE",
  "UNSUPPORTED_MEDIA_TYPE",
  "PAYLOAD_TOO_LARGE",
  "VALIDATION_FAILED",
] as const;

export type NarrationErrorCode = typeof NARRATION_ERROR_CODES[number];

export interface NarrationApiErrorDetail {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly code: NarrationErrorCode;
  readonly message: string;
  readonly retryable: boolean;
  readonly field: string | null;
  readonly current_version: number | null;
  readonly capability: CapabilityKey | null;
}

export type RuntimeLifecycleStatus =
  | "disabled"
  | "starting"
  | "ready"
  | "unavailable"
  | "stopping";

export interface NarrationRuntimeStatus {
  readonly technical_enabled: boolean;
  readonly lifecycle_status: RuntimeLifecycleStatus;
  readonly sidecar_reachable: boolean;
  readonly model_ready: boolean;
  readonly product_visible: boolean;
  readonly protocol_version: string;
  readonly model_fingerprint_sha256: string | null;
  readonly reason_code: string | null;
}

export type CloudConsentState = "not_granted" | "active" | "revoked" | "expired";

export interface NarrationCloudConsent {
  readonly consent_id: string | null;
  readonly version: number;
  readonly state: CloudConsentState;
  readonly purpose: "narration_speaker_analysis";
  readonly data_scope: "uncertain_segments_with_minimal_context";
  readonly notice_version: string | null;
  readonly provider_id: string | null;
  readonly model_id: string | null;
  readonly confirmed_at: string | null;
  readonly revoked_at: string | null;
}

export interface NarrationAuthorizationState {
  readonly mode: "fixed_local_owner_workspace";
  readonly can_read: boolean;
  readonly can_configure: boolean;
  readonly can_manage_voice_assets: boolean;
  readonly can_confirm_voice_rights: boolean;
  readonly cloud_consent: NarrationCloudConsent;
}

export interface CreateNarrationCloudConsentRequest {
  readonly notice_version: string;
  readonly data_scope: "uncertain_segments_with_minimal_context";
  readonly provider_id: string | null;
  readonly model_id: string | null;
  readonly confirmed: true;
}

export interface RevokeNarrationCloudConsentRequest {
  readonly consent_id: string;
  readonly expected_version: number;
}

export type ScriptReviewPolicy = "blockers_only" | "always_review";
export type AnalysisMode = "local_rules_only" | "cloud_assisted";
export type FirstPersonVoiceMode = "narrator" | "character";
export type InnerMonologueVoiceMode = "character" | "narrator";
export type AnonymousReuseScope = "scene" | "chapter" | "novel";
export type UnknownSpeakerAction = "block" | "require_review";
export type OutputAudioFormat = "m4a_aac_lc";

export interface NarratorVoiceSelection {
  readonly profile_id: string;
  readonly version_id: string;
}

export interface NarrationTextRules {
  readonly read_chapter_title: boolean;
  readonly read_author_notes: boolean;
  readonly read_section_breaks: boolean;
  readonly first_person_mode: FirstPersonVoiceMode;
  readonly first_person_character_id: string | null;
  readonly inner_monologue_mode: InnerMonologueVoiceMode;
}

export interface NarrationTimingSettings {
  readonly sentence_gap_ms: number;
  readonly paragraph_gap_ms: number;
  readonly section_gap_ms: number;
}

export interface NarrationCastingSettings {
  readonly anonymous_reuse_scope: AnonymousReuseScope;
  readonly same_scene_voice_deduplication: boolean;
  readonly unknown_speaker_action: UnknownSpeakerAction;
}

export interface NarrationPlaybackPreferences {
  readonly playback_rate: number;
  readonly volume: number;
}

export interface NarrationSettingsValues {
  readonly narrator: NarratorVoiceSelection | null;
  readonly language: string;
  readonly output_format: OutputAudioFormat;
  readonly script_review_policy: ScriptReviewPolicy;
  readonly analysis_mode: AnalysisMode;
  readonly text_rules: NarrationTextRules;
  readonly timing: NarrationTimingSettings;
  readonly casting: NarrationCastingSettings;
  readonly playback: NarrationPlaybackPreferences;
}

export interface NarrationSettingsResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly schema_version: typeof NARRATION_SETTINGS_SCHEMA_VERSION;
  readonly novel_id: string;
  readonly settings_id: string | null;
  readonly exists: boolean;
  readonly version: number;
  readonly values: NarrationSettingsValues;
  readonly updated_at: string | null;
}

export interface UpdateNarrationSettingsRequest {
  readonly expected_version: number;
  readonly values: NarrationSettingsValues;
}

export type NarrationScopeKind = "volume" | "chapter";

export interface NarrationScopeOverrideValues {
  readonly narrator: NarratorVoiceSelection | null;
  readonly language: string | null;
  readonly text_rules: NarrationTextRules | null;
  readonly timing: NarrationTimingSettings | null;
}

export interface NarrationScopeOverrideResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly override_id: string | null;
  readonly novel_id: string;
  readonly scope_kind: NarrationScopeKind;
  readonly scope_id: string;
  readonly enabled: boolean;
  readonly version: number;
  readonly overrides: NarrationScopeOverrideValues;
}

export interface NarrationScopeOverrideListResponse {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly items: readonly NarrationScopeOverrideResource[];
}

export interface PutNarrationScopeOverrideRequest {
  readonly expected_version: number;
  readonly enabled: boolean;
  readonly overrides: NarrationScopeOverrideValues;
}

export type VoiceProfileStatus = "draft" | "active" | "archived" | "unavailable";
export type VoiceSourceType = "preset" | "uploaded" | "generated";
export type VoiceVersionState = "draft" | "preview_ready" | "locked" | "unavailable" | "deleted";
export type VoiceQualityState = "pending" | "accepted" | "rejected";
export type VoiceRightsState = "active" | "revoked" | "expired" | "review_blocked";

export interface VoiceRightsSummary {
  readonly rights_record_id: string;
  readonly state: VoiceRightsState;
  readonly notice_version: string;
  readonly source_kind: "official_preset" | "preset_catalog" | "user_upload" | "voice_generator";
  readonly source_identifier_sha256: string;
  readonly purpose: "private_novel_narration";
  readonly commercial_use: boolean;
  readonly redistribution: boolean;
  readonly voice_cloning: boolean;
  readonly subject_consent_recorded: boolean;
  readonly confirmed_at: string;
  readonly expires_at: string | null;
  readonly risk_flags: readonly string[];
}

export interface VoiceRightsDeclarationRequest {
  readonly notice_version: string;
  readonly source_identifier: string;
  readonly purpose: "private_novel_narration";
  readonly commercial_use: boolean;
  readonly redistribution: boolean;
  readonly voice_cloning: true;
  readonly subject_consent_reference: string | null;
  readonly confirmed: true;
}

export interface MediaAssetLink {
  readonly asset_id: string;
  readonly content_path: string;
  readonly mime_type: string;
  readonly byte_size: number;
  readonly duration_ms: number;
  readonly checksum_sha256: string;
}

export interface OfficialPresetProvenance {
  readonly schema_version: typeof OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION;
  readonly repository: string;
  readonly revision: string;
  readonly manifest_path: string;
  readonly manifest_sha256: string;
  readonly preset_id: string;
  readonly manifest_voice: string;
  readonly prompt_codes_sha256: string;
  readonly prompt_frame_count: number;
  readonly prompt_quantizer_count: number;
  readonly model_fingerprint_sha256: string;
  readonly provenance_fingerprint_sha256: string;
}

const OFFICIAL_PRESET_EVIDENCE_BY_ID = new Map(
  OFFICIAL_PRESET_EVIDENCE.map((item) => [item.presetId, item] as const),
);

/** Match a metadata-only provenance object against the pinned backend manifest row. */
export function officialPresetProvenanceIsExact(
  provenance: OfficialPresetProvenance,
  expectedPresetId: string = provenance.preset_id,
): boolean {
  const expected = OFFICIAL_PRESET_EVIDENCE_BY_ID.get(expectedPresetId as OfficialPresetId);
  return expected !== undefined
    && provenance.schema_version === OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION
    && provenance.repository === OFFICIAL_PRESET_MANIFEST_IDENTITY.repository
    && provenance.revision === OFFICIAL_PRESET_MANIFEST_IDENTITY.revision
    && provenance.manifest_path === OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath
    && provenance.manifest_sha256 === OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestSha256
    && provenance.preset_id === expected.presetId
    && provenance.manifest_voice === expected.manifestVoice
    && provenance.prompt_codes_sha256 === expected.promptCodesSha256
    && provenance.prompt_frame_count === expected.promptFrameCount
    && provenance.prompt_quantizer_count === expected.promptQuantizerCount
    && provenance.model_fingerprint_sha256
      === OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256
    && provenance.provenance_fingerprint_sha256
      === expected.provenanceFingerprintSha256;
}

export interface OfficialPresetCatalogItem {
  readonly preset_id: string;
  readonly display_name: string;
  readonly group: string;
  readonly language: string;
  readonly local_use_status: "available";
  readonly commercial_distribution_status: "not_evaluated";
  readonly provenance: OfficialPresetProvenance;
}

export interface OfficialPresetCatalogResponse {
  readonly schema_version: typeof OFFICIAL_PRESET_CATALOG_SCHEMA_VERSION;
  readonly items: readonly OfficialPresetCatalogItem[];
}

export interface VoiceProfileVersionResource {
  readonly schema_version: typeof NARRATION_VOICE_SCHEMA_VERSION;
  readonly version_id: string;
  readonly profile_id: string;
  readonly version_number: number;
  readonly source_type: VoiceSourceType;
  readonly state: VoiceVersionState;
  readonly provider_id: string | null;
  readonly model_id: string | null;
  readonly model_revision: string | null;
  readonly preset_key: string | null;
  readonly language: string;
  readonly fingerprint: string;
  readonly quality_state: VoiceQualityState;
  readonly rights: VoiceRightsSummary;
  readonly official_preset: OfficialPresetProvenance | null;
  readonly reference_asset_id: string | null;
  readonly preview_asset: MediaAssetLink | null;
  readonly description_available: boolean;
  readonly locked_at: string | null;
  readonly created_at: string;
}

/**
 * Verify source-kind evidence before a voice version can become a new narrator
 * or character binding. Historical `preset_catalog` rows remain parseable for
 * read-only migration/history views, but cannot masquerade as an official ONNX
 * preset in a new binding.
 */
export function voiceSourceEvidenceIsUsable(
  version: VoiceProfileVersionResource,
): boolean {
  if (version.source_type === "preset") {
    const provenance = version.official_preset;
    return version.rights.source_kind === "official_preset"
      && provenance !== null
      && version.preset_key !== null
      && provenance.preset_id === version.preset_key
      && officialPresetProvenanceIsExact(provenance, version.preset_key);
  }
  if (version.source_type === "uploaded") {
    return version.rights.source_kind === "user_upload"
      && version.reference_asset_id !== null;
  }
  return version.rights.source_kind === "voice_generator"
    && version.description_available;
}

export interface VoiceProfileResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly schema_version: typeof NARRATION_VOICE_SCHEMA_VERSION;
  readonly profile_id: string;
  readonly novel_id: string | null;
  readonly name: string;
  readonly status: VoiceProfileStatus;
  readonly version: number;
  readonly current_version_id: string | null;
  readonly versions: readonly VoiceProfileVersionResource[];
  readonly created_at: string;
  readonly updated_at: string;
  readonly archived_at: string | null;
}

export interface VoiceProfileListResponse {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly items: readonly VoiceProfileResource[];
}

export interface CreateVoiceProfileRequest {
  readonly novel_id: string | null;
  readonly name: string;
}

export interface UpdateVoiceProfileRequest {
  readonly expected_version: number;
  readonly name: string;
}

export interface CreatePresetVoiceVersionRequest {
  readonly expected_profile_version: number;
  readonly preset_id: string;
}

export interface UploadedVoiceVersionMetadata {
  readonly expected_profile_version: number;
  readonly language: string;
  readonly original_filename: string;
  readonly reference_sha256: string;
  readonly rights: VoiceRightsDeclarationRequest;
}

export type VoicePreviewStatus = "queued" | "running" | "ready" | "failed" | "cancelled" | "unavailable";

export interface CreateVoicePreviewRequest {
  readonly version_id: string;
  readonly preview_text: string;
}

export interface VoicePreviewResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly preview_id: string;
  readonly profile_id: string;
  readonly version_id: string;
  readonly status: VoicePreviewStatus;
  readonly job_id: string | null;
  readonly asset: MediaAssetLink | null;
  readonly temporary: true;
  readonly expires_at: string | null;
  readonly failure_code: NarrationErrorCode | null;
}

export interface LockVoiceProfileRequest {
  readonly expected_profile_version: number;
  readonly version_id: string;
  readonly quality_confirmed: true;
}

export type CharacterVoiceBindingPolicy = "dedicated" | "inherited" | "unset";

export interface VoiceBindingImpact {
  readonly affected_chapter_count: number;
  readonly affected_segment_count: number;
  readonly historical_edition_count: number;
  readonly regeneration_required: boolean;
}

export interface CharacterVoiceBindingResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly binding_id: string | null;
  readonly novel_id: string;
  readonly character_id: string;
  readonly binding_policy: CharacterVoiceBindingPolicy;
  readonly profile_id: string | null;
  readonly version_id: string | null;
  readonly language: string;
  readonly version: number;
  readonly impact: VoiceBindingImpact;
  readonly updated_at: string | null;
}

export interface CharacterVoiceBindingListResponse {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly items: readonly CharacterVoiceBindingResource[];
}

export interface PutCharacterVoiceBindingRequest {
  readonly expected_version: number;
  readonly binding_policy: CharacterVoiceBindingPolicy;
  readonly profile_id: string | null;
  readonly version_id: string | null;
  readonly language: string;
}

export type CastingSpeakerKind = "character" | "anonymous" | "group";
export type CastingGender = "female" | "male" | "neutral" | "unknown";
export type CastingAgeBand = "child" | "teen" | "young_adult" | "middle_aged" | "elderly" | "unknown";
export type CastingContextKind = "dialogue" | "inner_monologue" | "letter" | "telephone" | "broadcast" | "group";

export interface VoiceCastingCondition {
  readonly speaker_kinds: readonly CastingSpeakerKind[];
  readonly genders: readonly CastingGender[];
  readonly age_bands: readonly CastingAgeBand[];
  readonly context_kinds: readonly CastingContextKind[];
  readonly role_tags: readonly string[];
}

export type VoiceCastingTargetKind = "generic_slot" | "voice_version" | "require_review";

export interface VoiceCastingTarget {
  readonly kind: VoiceCastingTargetKind;
  readonly pool_id: string | null;
  readonly slot_key: string | null;
  readonly profile_id: string | null;
  readonly version_id: string | null;
}

export interface VoiceCastingRuleInput {
  readonly priority: number;
  readonly enabled: boolean;
  readonly condition: VoiceCastingCondition;
  readonly target: VoiceCastingTarget;
}

export interface VoiceCastingRuleResource extends VoiceCastingRuleInput {
  readonly rule_id: string;
  readonly version_number: number;
  readonly source: "system" | "user";
}

export interface VoiceCastingRulesResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly version: number;
  readonly items: readonly VoiceCastingRuleResource[];
}

export interface PutVoiceCastingRulesRequest {
  readonly expected_version: number;
  readonly items: readonly VoiceCastingRuleInput[];
}

export interface VoiceSourceAvailability {
  readonly source_type: VoiceSourceType;
  readonly capability: CapabilityKey;
  readonly available: boolean;
  readonly reason_code: string | null;
  readonly accepted_mime_types: readonly string[];
  readonly maximum_bytes: number | null;
}

export type PronunciationAction = "replace" | "skip";

export interface PronunciationEntryResource {
  readonly entry_id: string | null;
  readonly source_text: string;
  readonly action: PronunciationAction;
  readonly spoken_text: string | null;
  readonly language: string;
  readonly scope_kind: "novel" | "volume" | "chapter";
  readonly scope_id: string;
  readonly priority: number;
}

export interface PronunciationProfileResource {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly profile_id: string | null;
  readonly version: number;
  readonly fingerprint: string | null;
  readonly entries: readonly PronunciationEntryResource[];
}

export interface PutPronunciationProfileRequest {
  readonly expected_version: number;
  readonly entries: readonly PronunciationEntryResource[];
}

export interface NarrationCacheStatus {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly schema_version: typeof NARRATION_CACHE_SCHEMA_VERSION;
  readonly novel_id: string;
  readonly snapshot_fingerprint: string;
  readonly source_asset_bytes: number;
  readonly locked_voice_bytes: number;
  readonly referenced_edition_bytes: number;
  readonly derived_cache_bytes: number;
  readonly reclaimable_bytes: number;
  readonly pending_job_count: number;
  readonly disk_free_bytes: number;
  readonly disk_total_bytes: number;
  readonly cleanup_capability: FeatureCapability;
}

export interface PreviewNarrationCacheCleanupRequest {
  readonly snapshot_fingerprint: string;
}

export interface NarrationCacheCleanupPreview {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly snapshot_fingerprint: string;
  readonly cleanup_token: string;
  readonly expires_at: string;
  readonly reclaimable_bytes: number;
  readonly protected_asset_count: number;
  readonly candidate_asset_count: number;
}

export interface ExecuteNarrationCacheCleanupRequest {
  readonly snapshot_fingerprint: string;
  readonly cleanup_token: string;
  readonly confirmed: true;
}

export interface NarrationCacheCleanupResult {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly deleted_asset_count: number;
  readonly reclaimed_bytes: number;
  readonly source_asset_deleted_count: 0;
  readonly locked_voice_deleted_count: 0;
  readonly referenced_asset_deleted_count: 0;
}

export interface NarrationCoverageSummary {
  readonly character_count: number;
  readonly configured_character_count: number;
  readonly locked_character_voice_count: number;
  readonly generic_required_slot_count: 24;
  readonly generic_ready_slot_count: number;
  readonly pending_review_script_count: number;
  readonly blocker_count: number;
  readonly warning_count: number;
  readonly generated_chapter_count: number;
  readonly failed_job_count: number;
}

export interface NarrationOverviewResponse {
  readonly contract_version: typeof NARRATION_SETTINGS_API_VERSION;
  readonly novel_id: string;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly runtime: NarrationRuntimeStatus;
  readonly settings: NarrationSettingsResource;
  readonly coverage: NarrationCoverageSummary;
  readonly voice_sources: readonly VoiceSourceAvailability[];
  readonly cache: NarrationCacheStatus;
}

export class NarrationContractError extends Error {
  readonly path: string;

  constructor(path: string, message: string) {
    super(`${path}: ${message}`);
    this.path = path;
  }
}

type JsonRecord = Record<string, unknown>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const GIT_REVISION_PATTERN = /^[a-f0-9]{40}$/;
const OFFICIAL_PRESET_ID_PATTERN = /^onnx\.[A-Za-z][A-Za-z0-9]{0,79}$/;
const MANIFEST_VOICE_PATTERN = /^[A-Za-z][A-Za-z0-9]{0,79}$/;
const SAFE_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,95}$/;
const LANGUAGE_PATTERN = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$/;

function fail(path: string, message: string): never {
  throw new NarrationContractError(path, message);
}

function record(value: unknown, path: string): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return fail(path, "expected object");
  }
  return value as JsonRecord;
}

function exact(value: JsonRecord, keys: readonly string[], path: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(path, `expected exact keys ${expected.join(",")}`);
  }
}

function array(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) return fail(path, "expected array");
  return value;
}

function string(value: unknown, path: string, minimum = 1, maximum = Number.MAX_SAFE_INTEGER): string {
  if (typeof value !== "string" || value.length < minimum || value.length > maximum) {
    return fail(path, "expected bounded string");
  }
  return value;
}

function nullableString(value: unknown, path: string, maximum = Number.MAX_SAFE_INTEGER): string | null {
  return value === null ? null : string(value, path, 1, maximum);
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") return fail(path, "expected boolean");
  return value;
}

function finiteNumber(value: unknown, path: string, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    return fail(path, "expected bounded finite number");
  }
  return value;
}

function integer(value: unknown, path: string, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number {
  const parsed = finiteNumber(value, path, minimum, maximum);
  if (!Number.isSafeInteger(parsed)) return fail(path, "expected safe integer");
  return parsed;
}

function uuid(value: unknown, path: string): string {
  const parsed = string(value, path, 36, 36);
  if (!UUID_PATTERN.test(parsed)) return fail(path, "expected UUID");
  return parsed;
}

function nullableUuid(value: unknown, path: string): string | null {
  return value === null ? null : uuid(value, path);
}

function sha256(value: unknown, path: string): string {
  const parsed = string(value, path, 64, 64);
  if (!SHA256_PATTERN.test(parsed)) return fail(path, "expected lowercase SHA-256");
  return parsed;
}

function nullableSha256(value: unknown, path: string): string | null {
  return value === null ? null : sha256(value, path);
}

function timestamp(value: unknown, path: string): string {
  const parsed = string(value, path, 10, 80);
  if (!parsed.includes("T") || !Number.isFinite(Date.parse(parsed))) {
    return fail(path, "expected ISO timestamp");
  }
  return parsed;
}

function nullableTimestamp(value: unknown, path: string): string | null {
  return value === null ? null : timestamp(value, path);
}

function oneOf<const T extends readonly string[]>(value: unknown, options: T, path: string): T[number] {
  if (typeof value !== "string" || !options.includes(value)) {
    return fail(path, `expected one of ${options.join(",")}`);
  }
  return value as T[number];
}

function literal(value: unknown, expected: string | number | boolean, path: string): void {
  if (value !== expected) fail(path, `expected literal ${String(expected)}`);
}

function language(value: unknown, path: string): string {
  const parsed = string(value, path, 2, 40);
  if (!LANGUAGE_PATTERN.test(parsed)) return fail(path, "expected conservative BCP-47 tag");
  return parsed;
}

function stringArray(value: unknown, path: string, maximum = Number.MAX_SAFE_INTEGER): readonly string[] {
  const values = array(value, path);
  if (values.length > maximum) fail(path, "too many items");
  values.forEach((item, index) => string(item, `${path}[${index}]`));
  return values as readonly string[];
}

function enumArray<const T extends readonly string[]>(
  value: unknown,
  options: T,
  path: string,
  maximum: number,
): readonly T[number][] {
  const values = array(value, path);
  if (values.length > maximum) fail(path, "too many items");
  const parsed = values.map((item, index) => oneOf(item, options, `${path}[${index}]`));
  if (new Set(parsed).size !== parsed.length) fail(path, "items must be unique");
  return parsed;
}

function validateCapability(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["key", "state", "visible", "actionable", "reason_code", "required_gate"], path);
  oneOf(item.key, CAPABILITY_KEYS, `${path}.key`);
  const state = oneOf(item.state, ["enabled", "disabled", "unavailable", "hold"] as const, `${path}.state`);
  const visible = boolean(item.visible, `${path}.visible`);
  const actionable = boolean(item.actionable, `${path}.actionable`);
  const reason = nullableString(item.reason_code, `${path}.reason_code`, 96);
  nullableString(item.required_gate, `${path}.required_gate`, 32);
  if (reason !== null && !SAFE_CODE_PATTERN.test(reason)) fail(`${path}.reason_code`, "unsafe reason code");
  if (state === "enabled") {
    if (!visible || !actionable || reason !== null) fail(path, "invalid enabled capability shape");
  } else if (actionable || reason === null) {
    fail(path, "invalid disabled capability shape");
  }
}

function validateCapabilities(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["schema_version", "items"], path);
  literal(item.schema_version, NARRATION_CAPABILITY_SCHEMA_VERSION, `${path}.schema_version`);
  const items = array(item.items, `${path}.items`);
  items.forEach((entry, index) => validateCapability(entry, `${path}.items[${index}]`));
  const keys = items.map((entry) => record(entry, path).key);
  if (keys.length !== CAPABILITY_KEYS.length || new Set(keys).size !== CAPABILITY_KEYS.length) {
    fail(`${path}.items`, "must contain every capability exactly once");
  }
  CAPABILITY_KEYS.forEach((key) => {
    if (!keys.includes(key)) fail(`${path}.items`, `missing capability ${key}`);
  });
}

function validateCloudConsent(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "consent_id", "version", "state", "purpose", "data_scope", "notice_version", "provider_id",
    "model_id", "confirmed_at", "revoked_at",
  ], path);
  const consentId = nullableUuid(item.consent_id, `${path}.consent_id`);
  const version = integer(item.version, `${path}.version`);
  const state = oneOf(item.state, ["not_granted", "active", "revoked", "expired"] as const, `${path}.state`);
  literal(item.purpose, "narration_speaker_analysis", `${path}.purpose`);
  literal(item.data_scope, "uncertain_segments_with_minimal_context", `${path}.data_scope`);
  const notice = nullableString(item.notice_version, `${path}.notice_version`, 120);
  const providerId = nullableString(item.provider_id, `${path}.provider_id`, 160);
  const modelId = nullableString(item.model_id, `${path}.model_id`, 160);
  const confirmedAt = nullableTimestamp(item.confirmed_at, `${path}.confirmed_at`);
  const revokedAt = nullableTimestamp(item.revoked_at, `${path}.revoked_at`);
  if ((providerId === null) !== (modelId === null)) fail(path, "provider/model consent pair mismatch");
  if (state === "not_granted") {
    if (version !== 0 || [consentId, notice, providerId, modelId, confirmedAt, revokedAt].some((entry) => entry !== null)) {
      fail(path, "not-granted consent must be an empty version-zero projection");
    }
    return;
  }
  if (consentId === null || version < 1 || notice === null || confirmedAt === null) {
    fail(path, "persisted consent lacks CAS evidence");
  }
  if (state === "active" && revokedAt !== null) fail(path, "active consent cannot be revoked");
  if (state === "revoked" && revokedAt === null) fail(path, "revoked consent lacks evidence");
  if (state === "expired" && revokedAt !== null) fail(path, "expired consent cannot claim revocation");
}

function validateAuthorization(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["mode", "can_read", "can_configure", "can_manage_voice_assets", "can_confirm_voice_rights", "cloud_consent"], path);
  literal(item.mode, "fixed_local_owner_workspace", `${path}.mode`);
  boolean(item.can_read, `${path}.can_read`);
  boolean(item.can_configure, `${path}.can_configure`);
  boolean(item.can_manage_voice_assets, `${path}.can_manage_voice_assets`);
  boolean(item.can_confirm_voice_rights, `${path}.can_confirm_voice_rights`);
  validateCloudConsent(item.cloud_consent, `${path}.cloud_consent`);
}

function validateRuntime(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "technical_enabled", "lifecycle_status", "sidecar_reachable", "model_ready",
    "product_visible", "protocol_version", "model_fingerprint_sha256", "reason_code",
  ], path);
  const technical = boolean(item.technical_enabled, `${path}.technical_enabled`);
  const lifecycle = oneOf(item.lifecycle_status, ["disabled", "starting", "ready", "unavailable", "stopping"] as const, `${path}.lifecycle_status`);
  const reachable = boolean(item.sidecar_reachable, `${path}.sidecar_reachable`);
  const ready = boolean(item.model_ready, `${path}.model_ready`);
  const visible = boolean(item.product_visible, `${path}.product_visible`);
  string(item.protocol_version, `${path}.protocol_version`, 1, 80);
  const fingerprint = nullableSha256(item.model_fingerprint_sha256, `${path}.model_fingerprint_sha256`);
  const reason = nullableString(item.reason_code, `${path}.reason_code`, 96);
  if (reason !== null && !SAFE_CODE_PATTERN.test(reason)) fail(`${path}.reason_code`, "unsafe reason code");
  if (lifecycle === "ready" && (!technical || !reachable || !ready || fingerprint === null)) fail(path, "invalid ready runtime");
  if ((lifecycle === "disabled" || lifecycle === "unavailable") && reason === null) fail(path, "missing runtime reason");
  if (visible && lifecycle !== "ready") fail(path, "product-visible runtime is not ready");
}

function validateNarrator(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["profile_id", "version_id"], path);
  uuid(item.profile_id, `${path}.profile_id`);
  uuid(item.version_id, `${path}.version_id`);
}

function validateTextRules(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "read_chapter_title", "read_author_notes", "read_section_breaks", "first_person_mode",
    "first_person_character_id", "inner_monologue_mode",
  ], path);
  boolean(item.read_chapter_title, `${path}.read_chapter_title`);
  boolean(item.read_author_notes, `${path}.read_author_notes`);
  boolean(item.read_section_breaks, `${path}.read_section_breaks`);
  const mode = oneOf(item.first_person_mode, ["narrator", "character"] as const, `${path}.first_person_mode`);
  const characterId = nullableUuid(item.first_person_character_id, `${path}.first_person_character_id`);
  oneOf(item.inner_monologue_mode, ["character", "narrator"] as const, `${path}.inner_monologue_mode`);
  if ((mode === "character") !== (characterId !== null)) fail(path, "first-person target mismatch");
}

function validateTiming(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["sentence_gap_ms", "paragraph_gap_ms", "section_gap_ms"], path);
  integer(item.sentence_gap_ms, `${path}.sentence_gap_ms`, 0, 5_000);
  integer(item.paragraph_gap_ms, `${path}.paragraph_gap_ms`, 0, 10_000);
  integer(item.section_gap_ms, `${path}.section_gap_ms`, 0, 15_000);
}

function validateCasting(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["anonymous_reuse_scope", "same_scene_voice_deduplication", "unknown_speaker_action"], path);
  oneOf(item.anonymous_reuse_scope, ["scene", "chapter", "novel"] as const, `${path}.anonymous_reuse_scope`);
  boolean(item.same_scene_voice_deduplication, `${path}.same_scene_voice_deduplication`);
  oneOf(item.unknown_speaker_action, ["block", "require_review"] as const, `${path}.unknown_speaker_action`);
}

function validatePlayback(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["playback_rate", "volume"], path);
  finiteNumber(item.playback_rate, `${path}.playback_rate`, 0.5, 3);
  finiteNumber(item.volume, `${path}.volume`, 0, 1);
}

function validateSettingsValues(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "narrator", "language", "output_format", "script_review_policy", "analysis_mode",
    "text_rules", "timing", "casting", "playback",
  ], path);
  if (item.narrator !== null) validateNarrator(item.narrator, `${path}.narrator`);
  language(item.language, `${path}.language`);
  literal(item.output_format, "m4a_aac_lc", `${path}.output_format`);
  oneOf(item.script_review_policy, ["blockers_only", "always_review"] as const, `${path}.script_review_policy`);
  oneOf(item.analysis_mode, ["local_rules_only", "cloud_assisted"] as const, `${path}.analysis_mode`);
  validateTextRules(item.text_rules, `${path}.text_rules`);
  validateTiming(item.timing, `${path}.timing`);
  validateCasting(item.casting, `${path}.casting`);
  validatePlayback(item.playback, `${path}.playback`);
}

function validateSettings(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["contract_version", "schema_version", "novel_id", "settings_id", "exists", "version", "values", "updated_at"], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  literal(item.schema_version, NARRATION_SETTINGS_SCHEMA_VERSION, `${path}.schema_version`);
  uuid(item.novel_id, `${path}.novel_id`);
  const settingsId = nullableUuid(item.settings_id, `${path}.settings_id`);
  const exists = boolean(item.exists, `${path}.exists`);
  const version = integer(item.version, `${path}.version`);
  validateSettingsValues(item.values, `${path}.values`);
  const updatedAt = nullableTimestamp(item.updated_at, `${path}.updated_at`);
  if (exists && (settingsId === null || version < 1)) fail(path, "invalid persisted settings identity");
  if (!exists && (settingsId !== null || version !== 0 || updatedAt !== null)) fail(path, "invalid default settings identity");
}

function validateOverrideValues(value: unknown, path: string): boolean {
  const item = record(value, path);
  exact(item, ["narrator", "language", "text_rules", "timing"], path);
  if (item.narrator !== null) validateNarrator(item.narrator, `${path}.narrator`);
  if (item.language !== null) language(item.language, `${path}.language`);
  if (item.text_rules !== null) validateTextRules(item.text_rules, `${path}.text_rules`);
  if (item.timing !== null) validateTiming(item.timing, `${path}.timing`);
  return [item.narrator, item.language, item.text_rules, item.timing].every((entry) => entry === null);
}

function validateOverride(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["contract_version", "override_id", "novel_id", "scope_kind", "scope_id", "enabled", "version", "overrides"], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  const overrideId = nullableUuid(item.override_id, `${path}.override_id`);
  uuid(item.novel_id, `${path}.novel_id`);
  oneOf(item.scope_kind, ["volume", "chapter"] as const, `${path}.scope_kind`);
  uuid(item.scope_id, `${path}.scope_id`);
  const enabled = boolean(item.enabled, `${path}.enabled`);
  const version = integer(item.version, `${path}.version`);
  const empty = validateOverrideValues(item.overrides, `${path}.overrides`);
  if (enabled && (overrideId === null || version < 1 || empty)) fail(path, "invalid enabled override");
  if (!enabled && (overrideId !== null || version !== 0 || !empty)) fail(path, "invalid disabled override");
}

function validateRights(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "rights_record_id", "state", "notice_version", "source_kind", "source_identifier_sha256", "purpose",
    "commercial_use", "redistribution", "voice_cloning", "subject_consent_recorded",
    "confirmed_at", "expires_at", "risk_flags",
  ], path);
  uuid(item.rights_record_id, `${path}.rights_record_id`);
  oneOf(item.state, ["active", "revoked", "expired", "review_blocked"] as const, `${path}.state`);
  string(item.notice_version, `${path}.notice_version`, 1, 120);
  oneOf(item.source_kind, ["official_preset", "preset_catalog", "user_upload", "voice_generator"] as const, `${path}.source_kind`);
  sha256(item.source_identifier_sha256, `${path}.source_identifier_sha256`);
  literal(item.purpose, "private_novel_narration", `${path}.purpose`);
  boolean(item.commercial_use, `${path}.commercial_use`);
  boolean(item.redistribution, `${path}.redistribution`);
  boolean(item.voice_cloning, `${path}.voice_cloning`);
  boolean(item.subject_consent_recorded, `${path}.subject_consent_recorded`);
  timestamp(item.confirmed_at, `${path}.confirmed_at`);
  nullableTimestamp(item.expires_at, `${path}.expires_at`);
  const riskFlags = stringArray(item.risk_flags, `${path}.risk_flags`, 32);
  if (new Set(riskFlags).size !== riskFlags.length || riskFlags.some((flag) => !SAFE_CODE_PATTERN.test(flag))) {
    fail(`${path}.risk_flags`, "expected unique stable risk codes");
  }
}

function validateOfficialPresetProvenance(
  value: unknown,
  path: string,
): OfficialPresetProvenance {
  const item = record(value, path);
  exact(item, [
    "schema_version", "repository", "revision", "manifest_path", "manifest_sha256",
    "preset_id", "manifest_voice", "prompt_codes_sha256", "prompt_frame_count",
    "prompt_quantizer_count", "model_fingerprint_sha256", "provenance_fingerprint_sha256",
  ], path);
  literal(item.schema_version, OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION, `${path}.schema_version`);
  string(item.repository, `${path}.repository`, 1, 200);
  const revision = string(item.revision, `${path}.revision`, 40, 40);
  if (!GIT_REVISION_PATTERN.test(revision)) fail(`${path}.revision`, "expected lowercase Git revision");
  string(item.manifest_path, `${path}.manifest_path`, 1, 200);
  sha256(item.manifest_sha256, `${path}.manifest_sha256`);
  const presetId = string(item.preset_id, `${path}.preset_id`, 6, 85);
  if (!OFFICIAL_PRESET_ID_PATTERN.test(presetId)) fail(`${path}.preset_id`, "expected exact ONNX preset id");
  const manifestVoice = string(item.manifest_voice, `${path}.manifest_voice`, 1, 80);
  if (!MANIFEST_VOICE_PATTERN.test(manifestVoice)) fail(`${path}.manifest_voice`, "expected manifest voice key");
  if (presetId !== `onnx.${manifestVoice}`) fail(path, "preset_id/manifest_voice mismatch");
  sha256(item.prompt_codes_sha256, `${path}.prompt_codes_sha256`);
  integer(item.prompt_frame_count, `${path}.prompt_frame_count`, 1, 1_000_000);
  integer(item.prompt_quantizer_count, `${path}.prompt_quantizer_count`, 1, 1_024);
  sha256(item.model_fingerprint_sha256, `${path}.model_fingerprint_sha256`);
  sha256(item.provenance_fingerprint_sha256, `${path}.provenance_fingerprint_sha256`);
  return item as unknown as OfficialPresetProvenance;
}

function validateOfficialPresetCatalog(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["schema_version", "items"], path);
  literal(item.schema_version, OFFICIAL_PRESET_CATALOG_SCHEMA_VERSION, `${path}.schema_version`);
  const items = array(item.items, `${path}.items`);
  if (items.length !== PRODUCT_OFFICIAL_PRESET_IDS.length) {
    fail(`${path}.items`, "expected exact 6-item product catalog");
  }
  items.forEach((entry, index) => {
    const itemPath = `${path}.items[${index}]`;
    const preset = record(entry, itemPath);
    exact(preset, [
      "preset_id", "display_name", "group", "language", "local_use_status",
      "commercial_distribution_status", "provenance",
    ], itemPath);
    const presetId = string(preset.preset_id, `${itemPath}.preset_id`, 6, 85);
    if (!OFFICIAL_PRESET_ID_PATTERN.test(presetId)) fail(`${itemPath}.preset_id`, "expected exact ONNX preset id");
    const expectedPresetId = PRODUCT_OFFICIAL_PRESET_IDS[index]!;
    if (presetId !== expectedPresetId) {
      fail(`${itemPath}.preset_id`, `expected pinned catalog order item ${expectedPresetId}`);
    }
    string(preset.display_name, `${itemPath}.display_name`, 1, 160);
    string(preset.group, `${itemPath}.group`, 1, 80);
    language(preset.language, `${itemPath}.language`);
    literal(preset.local_use_status, "available", `${itemPath}.local_use_status`);
    literal(preset.commercial_distribution_status, "not_evaluated", `${itemPath}.commercial_distribution_status`);
    const provenance = validateOfficialPresetProvenance(preset.provenance, `${itemPath}.provenance`);
    if (provenance.preset_id !== presetId) fail(itemPath, "catalog/provenance preset mismatch");
    if (!officialPresetProvenanceIsExact(provenance, expectedPresetId)) {
      fail(`${itemPath}.provenance`, "official preset provenance disagrees with pinned evidence");
    }
  });
}

function validateMedia(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["asset_id", "content_path", "mime_type", "byte_size", "duration_ms", "checksum_sha256"], path);
  const assetId = uuid(item.asset_id, `${path}.asset_id`);
  const contentPath = string(item.content_path, `${path}.content_path`, 1, 300);
  if (contentPath !== `/media-assets/${assetId}/content`) fail(`${path}.content_path`, "asset path/id mismatch");
  string(item.mime_type, `${path}.mime_type`, 1, 120);
  integer(item.byte_size, `${path}.byte_size`, 1);
  integer(item.duration_ms, `${path}.duration_ms`, 1);
  sha256(item.checksum_sha256, `${path}.checksum_sha256`);
}

function validateVoiceVersion(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "schema_version", "version_id", "profile_id", "version_number", "source_type", "state",
    "provider_id", "model_id", "model_revision", "preset_key", "language", "fingerprint",
    "quality_state", "rights", "official_preset", "reference_asset_id", "preview_asset", "description_available",
    "locked_at", "created_at",
  ], path);
  literal(item.schema_version, NARRATION_VOICE_SCHEMA_VERSION, `${path}.schema_version`);
  uuid(item.version_id, `${path}.version_id`);
  uuid(item.profile_id, `${path}.profile_id`);
  integer(item.version_number, `${path}.version_number`, 1);
  const source = oneOf(item.source_type, ["preset", "uploaded", "generated"] as const, `${path}.source_type`);
  const state = oneOf(item.state, ["draft", "preview_ready", "locked", "unavailable", "deleted"] as const, `${path}.state`);
  nullableString(item.provider_id, `${path}.provider_id`, 160);
  nullableString(item.model_id, `${path}.model_id`, 160);
  nullableString(item.model_revision, `${path}.model_revision`, 160);
  const preset = nullableString(item.preset_key, `${path}.preset_key`, 160);
  language(item.language, `${path}.language`);
  sha256(item.fingerprint, `${path}.fingerprint`);
  const quality = oneOf(item.quality_state, ["pending", "accepted", "rejected"] as const, `${path}.quality_state`);
  validateRights(item.rights, `${path}.rights`);
  if (item.official_preset !== null) validateOfficialPresetProvenance(item.official_preset, `${path}.official_preset`);
  const rights = record(item.rights, `${path}.rights`);
  const reference = nullableUuid(item.reference_asset_id, `${path}.reference_asset_id`);
  if (item.preview_asset !== null) validateMedia(item.preview_asset, `${path}.preview_asset`);
  const description = boolean(item.description_available, `${path}.description_available`);
  const lockedAt = nullableTimestamp(item.locked_at, `${path}.locked_at`);
  timestamp(item.created_at, `${path}.created_at`);
  if ((source === "preset") !== (preset !== null)) fail(path, "preset_key source mismatch");
  if (rights.source_kind === "official_preset") {
    if (source !== "preset" || item.official_preset === null) fail(path, "official preset lacks pinned provenance");
    const provenance = record(item.official_preset, `${path}.official_preset`);
    if (provenance.preset_id !== preset) fail(path, "official preset identity mismatch");
  } else if (item.official_preset !== null) fail(path, "non-official source published official provenance");
  if (source === "uploaded" && reference === null) fail(path, "uploaded voice lacks reference asset");
  if (source === "generated" && !description) fail(path, "generated voice lacks description record");
  if (state === "locked" && (quality !== "accepted" || lockedAt === null)) fail(path, "invalid locked voice");
  if (state !== "locked" && lockedAt !== null) fail(path, "non-locked voice has locked_at");
}

function validateVoiceProfile(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "schema_version", "profile_id", "novel_id", "name", "status", "version",
    "current_version_id", "versions", "created_at", "updated_at", "archived_at",
  ], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  literal(item.schema_version, NARRATION_VOICE_SCHEMA_VERSION, `${path}.schema_version`);
  const profileId = uuid(item.profile_id, `${path}.profile_id`);
  nullableUuid(item.novel_id, `${path}.novel_id`);
  string(item.name, `${path}.name`, 1, 240);
  const state = oneOf(item.status, ["draft", "active", "archived", "unavailable"] as const, `${path}.status`);
  integer(item.version, `${path}.version`, 1);
  const current = nullableUuid(item.current_version_id, `${path}.current_version_id`);
  const versions = array(item.versions, `${path}.versions`);
  versions.forEach((entry, index) => validateVoiceVersion(entry, `${path}.versions[${index}]`));
  const versionRecords = versions.map((entry) => record(entry, path));
  if (new Set(versionRecords.map((entry) => entry.version_id)).size !== versions.length) fail(path, "duplicate voice version");
  if (versionRecords.some((entry) => entry.profile_id !== profileId)) fail(path, "voice version profile mismatch");
  if (current !== null) {
    const matches = versionRecords.filter((entry) => entry.version_id === current && entry.state === "locked");
    if (matches.length !== 1) fail(path, "current version is not exactly one locked version");
  }
  timestamp(item.created_at, `${path}.created_at`);
  timestamp(item.updated_at, `${path}.updated_at`);
  const archivedAt = nullableTimestamp(item.archived_at, `${path}.archived_at`);
  if (state === "archived" && archivedAt === null) fail(path, "archived profile lacks archived_at");
}

function validatePreview(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "preview_id", "profile_id", "version_id", "status", "job_id", "asset",
    "temporary", "expires_at", "failure_code",
  ], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  uuid(item.preview_id, `${path}.preview_id`);
  uuid(item.profile_id, `${path}.profile_id`);
  uuid(item.version_id, `${path}.version_id`);
  const state = oneOf(item.status, ["queued", "running", "ready", "failed", "cancelled", "unavailable"] as const, `${path}.status`);
  nullableUuid(item.job_id, `${path}.job_id`);
  if (item.asset !== null) validateMedia(item.asset, `${path}.asset`);
  literal(item.temporary, true, `${path}.temporary`);
  const expiresAt = nullableTimestamp(item.expires_at, `${path}.expires_at`);
  const failureCode = item.failure_code === null ? null : oneOf(item.failure_code, NARRATION_ERROR_CODES, `${path}.failure_code`);
  if (state === "ready" && (item.asset === null || expiresAt === null || failureCode !== null)) fail(path, "invalid ready preview");
  if (state !== "ready" && item.asset !== null) fail(path, "non-ready preview published asset");
  const failed = state === "failed" || state === "unavailable";
  if (failed !== (failureCode !== null)) fail(path, "preview failure code mismatch");
}

function validateImpact(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["affected_chapter_count", "affected_segment_count", "historical_edition_count", "regeneration_required"], path);
  integer(item.affected_chapter_count, `${path}.affected_chapter_count`);
  integer(item.affected_segment_count, `${path}.affected_segment_count`);
  integer(item.historical_edition_count, `${path}.historical_edition_count`);
  boolean(item.regeneration_required, `${path}.regeneration_required`);
}

function validateBinding(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "binding_id", "novel_id", "character_id", "binding_policy", "profile_id",
    "version_id", "language", "version", "impact", "updated_at",
  ], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  const binding = nullableUuid(item.binding_id, `${path}.binding_id`);
  uuid(item.novel_id, `${path}.novel_id`);
  uuid(item.character_id, `${path}.character_id`);
  const policy = oneOf(item.binding_policy, ["dedicated", "inherited", "unset"] as const, `${path}.binding_policy`);
  const profile = nullableUuid(item.profile_id, `${path}.profile_id`);
  const versionId = nullableUuid(item.version_id, `${path}.version_id`);
  language(item.language, `${path}.language`);
  const version = integer(item.version, `${path}.version`);
  validateImpact(item.impact, `${path}.impact`);
  const updatedAt = nullableTimestamp(item.updated_at, `${path}.updated_at`);
  if ((profile === null) !== (versionId === null)) fail(path, "voice binding pair mismatch");
  if (policy === "unset" && (binding !== null || profile !== null || version !== 0 || updatedAt !== null)) fail(path, "invalid unset binding");
  if (policy !== "unset" && (binding === null || profile === null || version < 1)) fail(path, "invalid configured binding");
}

function validateBindingList(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["contract_version", "novel_id", "items"], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  const novelId = uuid(item.novel_id, `${path}.novel_id`);
  const items = array(item.items, `${path}.items`);
  items.forEach((entry, index) => validateBinding(entry, `${path}.items[${index}]`));
  const records = items.map((entry) => record(entry, path));
  if (new Set(records.map((entry) => entry.character_id)).size !== items.length) fail(path, "duplicate character binding");
  if (records.some((entry) => entry.novel_id !== novelId)) fail(path, "character binding novel mismatch");
}

function validateCastingCondition(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["speaker_kinds", "genders", "age_bands", "context_kinds", "role_tags"], path);
  const speakerKinds = enumArray(item.speaker_kinds, ["character", "anonymous", "group"] as const, `${path}.speaker_kinds`, 3);
  const genders = enumArray(item.genders, ["female", "male", "neutral", "unknown"] as const, `${path}.genders`, 4);
  const ageBands = enumArray(item.age_bands, ["child", "teen", "young_adult", "middle_aged", "elderly", "unknown"] as const, `${path}.age_bands`, 6);
  const contexts = enumArray(item.context_kinds, ["dialogue", "inner_monologue", "letter", "telephone", "broadcast", "group"] as const, `${path}.context_kinds`, 6);
  const tags = stringArray(item.role_tags, `${path}.role_tags`, 32);
  if (tags.some((tag) => tag.length > 80 || !tag.trim())) fail(`${path}.role_tags`, "tags must be non-empty and bounded");
  if (new Set(tags).size !== tags.length) fail(`${path}.role_tags`, "items must be unique");
  if (speakerKinds.length + genders.length + ageBands.length + contexts.length + tags.length === 0) {
    fail(path, "casting condition must constrain at least one field");
  }
}

function validateCastingTarget(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["kind", "pool_id", "slot_key", "profile_id", "version_id"], path);
  const kind = oneOf(item.kind, ["generic_slot", "voice_version", "require_review"] as const, `${path}.kind`);
  const poolId = nullableUuid(item.pool_id, `${path}.pool_id`);
  const slotKey = nullableString(item.slot_key, `${path}.slot_key`, 80);
  const profileId = nullableUuid(item.profile_id, `${path}.profile_id`);
  const versionId = nullableUuid(item.version_id, `${path}.version_id`);
  const genericComplete = poolId !== null && slotKey !== null;
  const voiceComplete = profileId !== null && versionId !== null;
  if ((poolId === null) !== (slotKey === null)) fail(path, "generic casting target pair mismatch");
  if ((profileId === null) !== (versionId === null)) fail(path, "voice casting target pair mismatch");
  if (kind === "generic_slot" && (!genericComplete || voiceComplete)) fail(path, "invalid generic_slot target");
  if (kind === "voice_version" && (genericComplete || !voiceComplete)) fail(path, "invalid voice_version target");
  if (kind === "require_review" && (genericComplete || voiceComplete)) fail(path, "require_review cannot carry a voice");
}

function validateCastingRuleInput(value: unknown, path: string, resource: boolean): void {
  const item = record(value, path);
  const keys = resource
    ? ["priority", "enabled", "condition", "target", "rule_id", "version_number", "source"]
    : ["priority", "enabled", "condition", "target"];
  exact(item, keys, path);
  integer(item.priority, `${path}.priority`, -10_000, 10_000);
  boolean(item.enabled, `${path}.enabled`);
  validateCastingCondition(item.condition, `${path}.condition`);
  validateCastingTarget(item.target, `${path}.target`);
  if (resource) {
    uuid(item.rule_id, `${path}.rule_id`);
    integer(item.version_number, `${path}.version_number`, 1);
    oneOf(item.source, ["system", "user"] as const, `${path}.source`);
  }
}

function validateCastingRules(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["contract_version", "novel_id", "version", "items"], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  uuid(item.novel_id, `${path}.novel_id`);
  const version = integer(item.version, `${path}.version`);
  const items = array(item.items, `${path}.items`);
  items.forEach((entry, index) => validateCastingRuleInput(entry, `${path}.items[${index}]`, true));
  const records = items.map((entry) => record(entry, path));
  if (new Set(records.map((entry) => entry.rule_id)).size !== items.length) fail(path, "duplicate casting rule id");
  if (new Set(records.map((entry) => entry.priority)).size !== items.length) fail(path, "duplicate casting rule priority");
  if ((items.length === 0) !== (version === 0)) fail(path, "casting rule set version mismatch");
}

function validateSourceAvailability(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["source_type", "capability", "available", "reason_code", "accepted_mime_types", "maximum_bytes"], path);
  const source = oneOf(item.source_type, ["preset", "uploaded", "generated"] as const, `${path}.source_type`);
  const capability = oneOf(item.capability, CAPABILITY_KEYS, `${path}.capability`);
  const available = boolean(item.available, `${path}.available`);
  const reason = nullableString(item.reason_code, `${path}.reason_code`, 96);
  const mimes = stringArray(item.accepted_mime_types, `${path}.accepted_mime_types`);
  const maximum = item.maximum_bytes === null ? null : integer(item.maximum_bytes, `${path}.maximum_bytes`, 1);
  const expectedCapability: Record<VoiceSourceType, CapabilityKey> = {
    preset: "preset_voice_source",
    uploaded: "reference_clone",
    generated: "voice_generator",
  };
  if (capability !== expectedCapability[source]) fail(path, "voice source capability mismatch");
  if (reason !== null && !SAFE_CODE_PATTERN.test(reason)) fail(`${path}.reason_code`, "unsafe reason code");
  if (available === (reason !== null)) fail(path, "source availability/reason mismatch");
  if (source === "uploaded") {
    if (mimes.length !== REFERENCE_UPLOAD_MIME_TYPES.length
      || mimes.some((mime, index) => mime !== REFERENCE_UPLOAD_MIME_TYPES[index])
      || maximum !== REFERENCE_UPLOAD_MAX_BYTES) fail(path, "invalid uploaded source limits");
  } else if (mimes.length !== 0 || maximum !== null) fail(path, "non-upload source published media limits");
}

function validatePronunciationEntry(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["entry_id", "source_text", "action", "spoken_text", "language", "scope_kind", "scope_id", "priority"], path);
  nullableUuid(item.entry_id, `${path}.entry_id`);
  string(item.source_text, `${path}.source_text`, 1, 160);
  const action = oneOf(item.action, ["replace", "skip"] as const, `${path}.action`);
  const spoken = nullableString(item.spoken_text, `${path}.spoken_text`, 240);
  language(item.language, `${path}.language`);
  oneOf(item.scope_kind, ["novel", "volume", "chapter"] as const, `${path}.scope_kind`);
  uuid(item.scope_id, `${path}.scope_id`);
  integer(item.priority, `${path}.priority`, -10_000, 10_000);
  if ((action === "replace") !== (spoken !== null)) fail(path, "pronunciation action/spoken_text mismatch");
}

function validatePronunciationProfile(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["contract_version", "novel_id", "profile_id", "version", "fingerprint", "entries"], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  uuid(item.novel_id, `${path}.novel_id`);
  const profileId = nullableUuid(item.profile_id, `${path}.profile_id`);
  const version = integer(item.version, `${path}.version`);
  const fingerprint = nullableSha256(item.fingerprint, `${path}.fingerprint`);
  const entries = array(item.entries, `${path}.entries`);
  entries.forEach((entry, index) => validatePronunciationEntry(entry, `${path}.entries[${index}]`));
  if (profileId === null && (version !== 0 || fingerprint !== null || entries.length !== 0)) fail(path, "invalid missing pronunciation profile");
  if (profileId !== null && (version < 1 || fingerprint === null)) fail(path, "invalid persisted pronunciation profile");
}

function validateCache(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "schema_version", "novel_id", "snapshot_fingerprint", "source_asset_bytes",
    "locked_voice_bytes", "referenced_edition_bytes", "derived_cache_bytes", "reclaimable_bytes",
    "pending_job_count", "disk_free_bytes", "disk_total_bytes", "cleanup_capability",
  ], path);
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, `${path}.contract_version`);
  literal(item.schema_version, NARRATION_CACHE_SCHEMA_VERSION, `${path}.schema_version`);
  uuid(item.novel_id, `${path}.novel_id`);
  sha256(item.snapshot_fingerprint, `${path}.snapshot_fingerprint`);
  integer(item.source_asset_bytes, `${path}.source_asset_bytes`);
  integer(item.locked_voice_bytes, `${path}.locked_voice_bytes`);
  integer(item.referenced_edition_bytes, `${path}.referenced_edition_bytes`);
  const derived = integer(item.derived_cache_bytes, `${path}.derived_cache_bytes`);
  const reclaimable = integer(item.reclaimable_bytes, `${path}.reclaimable_bytes`);
  integer(item.pending_job_count, `${path}.pending_job_count`);
  const free = integer(item.disk_free_bytes, `${path}.disk_free_bytes`);
  const total = integer(item.disk_total_bytes, `${path}.disk_total_bytes`, 1);
  validateCapability(item.cleanup_capability, `${path}.cleanup_capability`);
  if (record(item.cleanup_capability, path).key !== "cache_cleanup") fail(path, "wrong cleanup capability");
  if (reclaimable > derived || free > total) fail(path, "invalid cache byte totals");
}

function validateCoverage(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "character_count", "configured_character_count", "locked_character_voice_count",
    "generic_required_slot_count", "generic_ready_slot_count", "pending_review_script_count",
    "blocker_count", "warning_count", "generated_chapter_count", "failed_job_count",
  ], path);
  const characters = integer(item.character_count, `${path}.character_count`);
  const configured = integer(item.configured_character_count, `${path}.configured_character_count`);
  const locked = integer(item.locked_character_voice_count, `${path}.locked_character_voice_count`);
  literal(item.generic_required_slot_count, 24, `${path}.generic_required_slot_count`);
  integer(item.generic_ready_slot_count, `${path}.generic_ready_slot_count`, 0, 24);
  integer(item.pending_review_script_count, `${path}.pending_review_script_count`);
  integer(item.blocker_count, `${path}.blocker_count`);
  integer(item.warning_count, `${path}.warning_count`);
  integer(item.generated_chapter_count, `${path}.generated_chapter_count`);
  integer(item.failed_job_count, `${path}.failed_job_count`);
  if (configured > characters || locked > configured) fail(path, "invalid character coverage totals");
}

function validated<T>(value: unknown, validator: (value: unknown, path: string) => void, path: string): T {
  validator(value, path);
  return value as T;
}

export function parseNarrationApiErrorDetail(value: unknown): NarrationApiErrorDetail {
  const item = record(value, "error");
  exact(item, ["contract_version", "code", "message", "retryable", "field", "current_version", "capability"], "error");
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, "error.contract_version");
  oneOf(item.code, NARRATION_ERROR_CODES, "error.code");
  string(item.message, "error.message", 1, 400);
  boolean(item.retryable, "error.retryable");
  nullableString(item.field, "error.field", 160);
  if (item.current_version !== null) integer(item.current_version, "error.current_version");
  if (item.capability !== null) oneOf(item.capability, CAPABILITY_KEYS, "error.capability");
  return item as unknown as NarrationApiErrorDetail;
}

export function parseNarrationCloudConsent(value: unknown): NarrationCloudConsent {
  return validated(value, validateCloudConsent, "cloud_consent");
}

export function parseNarrationSettingsResource(value: unknown): NarrationSettingsResource {
  return validated(value, validateSettings, "settings");
}

export function parseNarrationScopeOverrideResource(value: unknown): NarrationScopeOverrideResource {
  return validated(value, validateOverride, "scope_override");
}

export function parseNarrationScopeOverrideListResponse(value: unknown): NarrationScopeOverrideListResponse {
  const item = record(value, "scope_overrides");
  exact(item, ["contract_version", "novel_id", "items"], "scope_overrides");
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, "scope_overrides.contract_version");
  const novelId = uuid(item.novel_id, "scope_overrides.novel_id");
  const items = array(item.items, "scope_overrides.items");
  items.forEach((entry, index) => validateOverride(entry, `scope_overrides.items[${index}]`));
  const records = items.map((entry) => record(entry, "scope_overrides.items"));
  if (records.some((entry) => entry.novel_id !== novelId)) fail("scope_overrides.items", "override novel mismatch");
  const keys = records.map((entry) => `${String(entry.scope_kind)}:${String(entry.scope_id)}`);
  if (new Set(keys).size !== keys.length) fail("scope_overrides.items", "duplicate scope override");
  return item as unknown as NarrationScopeOverrideListResponse;
}

export function parseVoiceProfileResource(value: unknown): VoiceProfileResource {
  return validated(value, validateVoiceProfile, "voice_profile");
}

export function parseVoiceProfileListResponse(value: unknown): VoiceProfileListResponse {
  const item = record(value, "voice_profiles");
  exact(item, ["contract_version", "items"], "voice_profiles");
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, "voice_profiles.contract_version");
  const items = array(item.items, "voice_profiles.items");
  items.forEach((entry, index) => validateVoiceProfile(entry, `voice_profiles.items[${index}]`));
  return item as unknown as VoiceProfileListResponse;
}

export function parseVoiceProfileVersionResource(value: unknown): VoiceProfileVersionResource {
  return validated(value, validateVoiceVersion, "voice_version");
}

export function parseOfficialPresetCatalogResponse(value: unknown): OfficialPresetCatalogResponse {
  return validated(value, validateOfficialPresetCatalog, "official_preset_catalog");
}

export function parseVoicePreviewResource(value: unknown): VoicePreviewResource {
  return validated(value, validatePreview, "voice_preview");
}

export function parseCharacterVoiceBindingResource(value: unknown): CharacterVoiceBindingResource {
  return validated(value, validateBinding, "character_voice_binding");
}

export function parseCharacterVoiceBindingListResponse(value: unknown): CharacterVoiceBindingListResponse {
  return validated(value, validateBindingList, "character_voice_bindings");
}

export function parseVoiceCastingRulesResource(value: unknown): VoiceCastingRulesResource {
  return validated(value, validateCastingRules, "voice_casting_rules");
}

export function parsePronunciationProfileResource(value: unknown): PronunciationProfileResource {
  return validated(value, validatePronunciationProfile, "pronunciation_profile");
}

export function parseNarrationCacheStatus(value: unknown): NarrationCacheStatus {
  return validated(value, validateCache, "narration_cache");
}

export function parseNarrationCacheCleanupPreview(value: unknown): NarrationCacheCleanupPreview {
  const item = record(value, "cache_cleanup_preview");
  exact(item, [
    "contract_version", "novel_id", "snapshot_fingerprint", "cleanup_token", "expires_at",
    "reclaimable_bytes", "protected_asset_count", "candidate_asset_count",
  ], "cache_cleanup_preview");
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, "cache_cleanup_preview.contract_version");
  uuid(item.novel_id, "cache_cleanup_preview.novel_id");
  sha256(item.snapshot_fingerprint, "cache_cleanup_preview.snapshot_fingerprint");
  string(item.cleanup_token, "cache_cleanup_preview.cleanup_token", 32, 256);
  timestamp(item.expires_at, "cache_cleanup_preview.expires_at");
  integer(item.reclaimable_bytes, "cache_cleanup_preview.reclaimable_bytes");
  integer(item.protected_asset_count, "cache_cleanup_preview.protected_asset_count");
  integer(item.candidate_asset_count, "cache_cleanup_preview.candidate_asset_count");
  return item as unknown as NarrationCacheCleanupPreview;
}

export function parseNarrationCacheCleanupResult(value: unknown): NarrationCacheCleanupResult {
  const item = record(value, "cache_cleanup_result");
  exact(item, [
    "contract_version", "novel_id", "deleted_asset_count", "reclaimed_bytes",
    "source_asset_deleted_count", "locked_voice_deleted_count", "referenced_asset_deleted_count",
  ], "cache_cleanup_result");
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, "cache_cleanup_result.contract_version");
  uuid(item.novel_id, "cache_cleanup_result.novel_id");
  integer(item.deleted_asset_count, "cache_cleanup_result.deleted_asset_count");
  integer(item.reclaimed_bytes, "cache_cleanup_result.reclaimed_bytes");
  literal(item.source_asset_deleted_count, 0, "cache_cleanup_result.source_asset_deleted_count");
  literal(item.locked_voice_deleted_count, 0, "cache_cleanup_result.locked_voice_deleted_count");
  literal(item.referenced_asset_deleted_count, 0, "cache_cleanup_result.referenced_asset_deleted_count");
  return item as unknown as NarrationCacheCleanupResult;
}

export function parseNarrationOverviewResponse(value: unknown): NarrationOverviewResponse {
  const item = record(value, "overview");
  exact(item, ["contract_version", "novel_id", "capabilities", "authorization", "runtime", "settings", "coverage", "voice_sources", "cache"], "overview");
  literal(item.contract_version, NARRATION_SETTINGS_API_VERSION, "overview.contract_version");
  const novelId = uuid(item.novel_id, "overview.novel_id");
  validateCapabilities(item.capabilities, "overview.capabilities");
  validateAuthorization(item.authorization, "overview.authorization");
  validateRuntime(item.runtime, "overview.runtime");
  validateSettings(item.settings, "overview.settings");
  validateCoverage(item.coverage, "overview.coverage");
  const sources = array(item.voice_sources, "overview.voice_sources");
  sources.forEach((entry, index) => validateSourceAvailability(entry, `overview.voice_sources[${index}]`));
  const sourceNames = sources.map((entry) => record(entry, "overview.voice_sources").source_type);
  if (sourceNames.length !== 3 || new Set(sourceNames).size !== 3 || !["preset", "uploaded", "generated"].every((source) => sourceNames.includes(source))) {
    fail("overview.voice_sources", "must report every voice source exactly once");
  }
  const capabilityItems = array(record(item.capabilities, "overview.capabilities").items, "overview.capabilities.items")
    .map((entry) => record(entry, "overview.capabilities.items"));
  const capabilityByKey = new Map(capabilityItems.map((entry) => [entry.key, entry]));
  sources.forEach((entry, index) => {
    const source = record(entry, `overview.voice_sources[${index}]`);
    const capability = capabilityByKey.get(source.capability);
    if (!capability) fail(`overview.voice_sources[${index}]`, "missing source capability");
    const capabilityAvailable = capability.state === "enabled" && capability.actionable === true;
    if (source.available !== capabilityAvailable) fail(`overview.voice_sources[${index}]`, "availability/capability mismatch");
    if (!capabilityAvailable && source.reason_code !== capability.reason_code) fail(`overview.voice_sources[${index}]`, "reason/capability mismatch");
  });
  const runtime = record(item.runtime, "overview.runtime");
  const productBlocker = T4_PRODUCT_CAPABILITY_KEYS.find((key) => {
    const capability = capabilityByKey.get(key);
    return capability?.state !== "enabled"
      || capability.visible !== true
      || capability.actionable !== true;
  });
  if (runtime.product_visible === true && productBlocker !== undefined) {
    fail("overview.runtime.product_visible", "T4 product chain is gated");
  }
  const globalCleanup = capabilityByKey.get("cache_cleanup");
  const nestedCleanup = record(record(item.cache, "overview.cache").cleanup_capability, "overview.cache.cleanup_capability");
  if (!globalCleanup) fail("overview.capabilities", "missing cache cleanup capability");
  const restrictiveness: Record<CapabilityState, number> = {
    disabled: 0,
    unavailable: 1,
    hold: 2,
    enabled: 3,
  };
  const globalState = oneOf(globalCleanup.state, ["enabled", "disabled", "unavailable", "hold"] as const, "overview.capabilities.cache_cleanup.state");
  const nestedState = oneOf(nestedCleanup.state, ["enabled", "disabled", "unavailable", "hold"] as const, "overview.cache.cleanup_capability.state");
  if (restrictiveness[nestedState] > restrictiveness[globalState]) fail("overview.cache.cleanup_capability", "exceeds global cache gate");
  if (nestedState === globalState && nestedCleanup.reason_code !== globalCleanup.reason_code) {
    fail("overview.cache.cleanup_capability", "cache gate reason mismatch");
  }
  validateCache(item.cache, "overview.cache");
  if (record(item.settings, "overview.settings").novel_id !== novelId || record(item.cache, "overview.cache").novel_id !== novelId) {
    fail("overview", "child resource novel mismatch");
  }
  return item as unknown as NarrationOverviewResponse;
}
