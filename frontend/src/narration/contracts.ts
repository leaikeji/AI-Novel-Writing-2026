export const NARRATION_SETTINGS_API_VERSION = "narration-settings-api/1" as const;
export const NARRATION_SETTINGS_SCHEMA_VERSION = "narration-settings/1" as const;
export const NARRATION_CAPABILITY_SCHEMA_VERSION = "narration-capabilities/3" as const;
export const NARRATION_VOICE_SCHEMA_VERSION = "narration-voice/2" as const;
export const NARRATION_CACHE_SCHEMA_VERSION = "narration-cache/1" as const;
export const OFFICIAL_PRESET_CATALOG_SCHEMA_VERSION = "moss-tts-official-preset-catalog/2.0" as const;
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
  "character_voice_matching",
  "character_cast_planning",
  "nano_advanced_tuning",
  "private_voice_deletion",
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

export interface UpdateNarrationPlaybackPreferencesRequest {
  readonly expected_version: number;
  readonly playback: NarrationPlaybackPreferences;
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
  readonly validation_tier: "canonical_chapter_verified" | "pinned_catalog_unreviewed";
  readonly language_scope: "zh-CN" | "en" | "ja-JP";
  readonly selectable_now: boolean;
  readonly previewable_now: boolean;
  readonly renderable_existing: boolean;
  readonly usage_notice: "private_local_writing_tool";
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
  readonly activation_basis: "preview_confirmed" | "explicit_official_preset_selection" | "character_one_click_generation" | "experimental_machine_validated";
  readonly validation_basis: "pending" | "human_accepted" | "machine_validated" | "not_required";
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
  if (version.activation_basis === "experimental_machine_validated") {
    const provenance = version.official_preset;
    return version.rights.source_kind === "official_preset"
      && provenance !== null
      && version.preset_key !== null
      && provenance.preset_id === version.preset_key
      && officialPresetProvenanceIsExact(provenance, version.preset_key);
  }
  return version.rights.source_kind === "voice_generator"
    && version.description_available;
}


/** Mirror the P0 backend activation gate without treating “locked” as human acceptance. */
export function voiceActivationEvidenceIsUsable(
  version: VoiceProfileVersionResource,
): boolean {
  return version.state === "locked" && (
    (
      version.activation_basis === "preview_confirmed"
      && version.validation_basis === "human_accepted"
      && version.quality_state === "accepted"
    )
    || (
      version.source_type === "preset"
      && version.activation_basis === "explicit_official_preset_selection"
      && version.validation_basis === "not_required"
      && version.quality_state === "pending"
    )
    || (
      version.source_type === "generated"
      && version.rights.source_kind === "official_preset"
      && version.activation_basis === "experimental_machine_validated"
      && version.validation_basis === "machine_validated"
      && version.quality_state === "accepted"
    )
    || (
      version.source_type === "generated"
      && version.rights.source_kind === "voice_generator"
      && version.activation_basis === "character_one_click_generation"
      && version.validation_basis === "machine_validated"
      && version.quality_state === "accepted"
      && version.reference_asset_id !== null
      && version.description_available
    )
  );
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

export type OfficialVoiceSelectionTargetKind = "narrator" | "character";

export interface OfficialVoicePreviewRequest {
  readonly preset_id: OfficialPresetId;
}

export interface OfficialVoiceSelectionRequest {
  readonly preset_id: OfficialPresetId;
  readonly target_kind: OfficialVoiceSelectionTargetKind;
  readonly character_id: string | null;
  readonly expected_settings_version: number;
  readonly expected_binding_version: number | null;
}

export interface OfficialVoiceSelectionResult {
  readonly command_id: string;
  readonly preset_id: OfficialPresetId;
  readonly target_kind: OfficialVoiceSelectionTargetKind;
  readonly character_id: string | null;
  readonly profile_id: string;
  readonly version_id: string;
  readonly settings_version: number;
  readonly binding_version: number | null;
  readonly target_language: string;
  readonly language_mismatch: boolean;
  readonly completed_at: string;
}

export interface OfficialVoiceSelectionResponse {
  readonly contract_version: "official-voice-selection/1.0";
  readonly replayed: boolean;
  readonly selection_still_current: boolean;
  readonly frozen_result: OfficialVoiceSelectionResult;
  readonly profile: VoiceProfileResource;
  readonly current_settings: NarrationSettingsResource | null;
  readonly current_character_binding: CharacterVoiceBindingResource | null;
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

export const NANO_DECODE_PARAMETERS_SCHEMA_VERSION = "nano-decode-parameters/3" as const;
export const NANO_VOICE_EXPERIMENT_REQUEST_VERSION = "nano-voice-experiment-request/1" as const;
export const NANO_VOICE_EXPERIMENT_VERSION = "nano-voice-experiment/1" as const;
export const NANO_VOICE_EXPERIMENT_LIST_VERSION = "nano-voice-experiment-list/1" as const;
export const CHARACTER_VOICE_MATCH_REQUEST_VERSION = "character-voice-match-request/1" as const;
export const CHARACTER_VOICE_MATCH_VERSION = "character-voice-match/1" as const;
export const CHARACTER_VOICE_BRIEF_VERSION = "character-voice-brief/1" as const;
export const NARRATOR_VOICE_BRIEF_VERSION = "narrator-voice-brief/1" as const;
export const CHARACTER_CAST_PLAN_REQUEST_VERSION = "character-cast-plan-request/1" as const;
export const CHARACTER_CAST_PLAN_VERSION = "character-cast-plan/1" as const;
export const CHARACTER_CAST_PLAN_LIST_VERSION = "character-cast-plan-list/1" as const;
export const CHARACTER_VOICE_GENERATION_REQUEST_VERSION = "character-voice-generation-request/1" as const;
export const CHARACTER_VOICE_GENERATION_VERSION = "character-voice-generation/1" as const;
export const CHARACTER_VOICE_GENERATION_LIST_VERSION = "character-voice-generation-list/1" as const;
export const PRIVATE_VOICE_LIFECYCLE_VERSION = "private-voice-lifecycle/1" as const;
export const PRIVATE_VOICE_DELETION_VERSION = "private-voice-deletion/2" as const;
export const PRIVATE_VOICE_DELETION_IMPACT_VERSION = "private-voice-deletion-impact/2" as const;

export interface NanoDecodeParametersResource {
  readonly schema_version: typeof NANO_DECODE_PARAMETERS_SCHEMA_VERSION;
  /** Canonical decimal int64 string; JSON numbers cannot preserve this range. */
  readonly seed: string;
  readonly text_temperature_milli: number;
  readonly text_top_p_milli: number;
  readonly text_top_k: number;
  readonly audio_temperature_milli: number;
  readonly audio_top_p_milli: number;
  readonly audio_top_k: number;
  readonly audio_repetition_penalty_milli: number;
  readonly sample_mode: "full";
  readonly max_new_frames: 375;
}

export interface CreateNanoVoiceExperimentRequest {
  readonly contract_version: typeof NANO_VOICE_EXPERIMENT_REQUEST_VERSION;
  readonly base_preset_id: OfficialPresetId;
  readonly target_kind: "narrator" | "character";
  readonly character_id: string | null;
  readonly expected_settings_version: number;
  readonly expected_binding_version: number | null;
  readonly parameters: NanoDecodeParametersResource;
}

export interface ApplyNanoVoiceExperimentRequest {
  readonly expected_settings_version: number;
  readonly expected_binding_version: number | null;
}

export type NanoVoiceExperimentState =
  | "pending"
  | "running"
  | "ready_applied"
  | "ready_unapplied"
  | "failed";

export interface NanoVoiceExperimentResource {
  readonly contract_version: typeof NANO_VOICE_EXPERIMENT_VERSION;
  readonly command_id: string;
  readonly novel_id: string;
  readonly profile_id: string;
  readonly version_id: string;
  readonly background_job_id: string;
  readonly base_preset_id: OfficialPresetId;
  readonly target_kind: "narrator" | "character";
  readonly character_id: string | null;
  readonly expected_settings_version: number;
  readonly expected_binding_version: number | null;
  readonly parameters: NanoDecodeParametersResource;
  readonly parameters_digest: string;
  readonly fingerprint: string;
  readonly state: NanoVoiceExperimentState;
  readonly reused_version: boolean;
  readonly preview: VoicePreviewResource | null;
  readonly current_settings: NarrationSettingsResource | null;
  readonly current_character_binding: CharacterVoiceBindingResource | null;
  readonly failure_code: string | null;
  readonly retryable: boolean;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
}

export interface NanoVoiceExperimentListResource {
  readonly contract_version: typeof NANO_VOICE_EXPERIMENT_LIST_VERSION;
  readonly novel_id: string;
  readonly items: readonly NanoVoiceExperimentResource[];
}

export interface CharacterVoiceMatchRequest {
  readonly contract_version: typeof CHARACTER_VOICE_MATCH_REQUEST_VERSION;
  readonly timeline_id: string | null;
  readonly character_instance_id: string | null;
  readonly expected_binding_version: number;
}

export interface CharacterVoiceBriefResource {
  readonly schema_version: typeof CHARACTER_VOICE_BRIEF_VERSION;
  readonly language: "zh-CN" | "en" | "ja-JP" | null;
  readonly presentation: "masculine" | "feminine" | "androgynous" | null;
  readonly pitch: -2 | -1 | 0 | 1 | 2 | null;
  readonly pace: -2 | -1 | 0 | 1 | 2 | null;
  readonly energy: -2 | -1 | 0 | 1 | 2 | null;
  readonly texture: "clear" | "warm" | "airy" | "husky" | "firm" | "soft" | "bright" | "dark" | null;
  readonly evidence_fields: readonly string[];
}

export interface CharacterVoiceMatchResource {
  readonly contract_version: typeof CHARACTER_VOICE_MATCH_VERSION;
  readonly character_id: string;
  readonly brief: CharacterVoiceBriefResource;
  readonly selected_preset_id: OfficialPresetId;
  readonly score_milli: number;
  readonly state: "ready_applied" | "ready_unapplied";
  readonly selection_still_current: boolean;
  readonly current_character_binding: CharacterVoiceBindingResource;
  readonly model_evidence: Readonly<Record<string, unknown>>;
}

export interface NarratorVoiceBriefResource {
  readonly schema_version: typeof NARRATOR_VOICE_BRIEF_VERSION;
  readonly language: "zh-CN" | "en" | "ja-JP" | null;
  readonly presentation: "masculine" | "feminine" | "androgynous" | null;
  readonly pitch: -2 | -1 | 0 | 1 | 2 | null;
  readonly pace: -2 | -1 | 0 | 1 | 2 | null;
  readonly energy: -2 | -1 | 0 | 1 | 2 | null;
  readonly texture: "clear" | "warm" | "airy" | "husky" | "firm" | "soft" | "bright" | "dark" | null;
  readonly evidence_fields: readonly string[];
}

export interface CreateCharacterCastPlanRequest {
  readonly contract_version: typeof CHARACTER_CAST_PLAN_REQUEST_VERSION;
  readonly timeline_id: string;
  readonly mode: "fill_and_deduplicate";
}

export type CharacterCastPlanState =
  | "reserved"
  | "analyzing"
  | "ready_applied"
  | "ready_applied_with_warnings"
  | "ready_unapplied"
  | "failed"
  | "superseded";

export type CharacterCastPlanItemState =
  | "pending"
  | "analyzing"
  | "preserved"
  | "scored"
  | "assigned"
  | "blocked";

export interface CharacterCastTargetResource {
  readonly target_key: string;
  readonly target_kind: "narrator" | "character";
  readonly character_id: string | null;
  readonly character_name: string | null;
  readonly role_type: string | null;
}

export interface CharacterCastPlanItemResource {
  readonly item_id: string;
  readonly target: CharacterCastTargetResource;
  readonly state: CharacterCastPlanItemState;
  readonly attempt: number;
  readonly workspace_digest: string;
  readonly lease_expires_at: string | null;
  readonly brief: CharacterVoiceBriefResource | NarratorVoiceBriefResource | null;
  readonly selected_preset_id: OfficialPresetId | null;
  readonly score_milli: number | null;
  readonly profile_id: string | null;
  readonly version_id: string | null;
  readonly voice_action_command_id: string | null;
  readonly warning_code: string | null;
  readonly failure_code: string | null;
}

export interface CharacterCastAssignmentResource {
  readonly target: CharacterCastTargetResource;
  readonly preset_id: OfficialPresetId;
  readonly score_milli: number;
  readonly voice_action_command_id: string | null;
}

export interface CharacterCastPreservedResource {
  readonly target: CharacterCastTargetResource;
  readonly profile_id: string;
  readonly version_id: string;
  readonly preset_id: OfficialPresetId | null;
  readonly source_type: "preset" | "uploaded" | "generated";
}

export interface CharacterCastWarningResource {
  readonly code: string;
  readonly target_key: string | null;
  readonly message: string;
}

export interface CharacterCastPlanResource {
  readonly contract_version: typeof CHARACTER_CAST_PLAN_VERSION;
  readonly command_id: string;
  readonly novel_id: string;
  readonly timeline_id: string;
  readonly mode: "fill_and_deduplicate";
  readonly state: CharacterCastPlanState;
  readonly server_now: string;
  readonly progress_current: number;
  readonly progress_total: number;
  readonly terminal: boolean;
  readonly retryable: boolean;
  readonly current_target_key: string | null;
  readonly lease_expires_at: string | null;
  readonly assignments: readonly CharacterCastAssignmentResource[];
  readonly preserved: readonly CharacterCastPreservedResource[];
  readonly warnings: readonly CharacterCastWarningResource[];
  readonly items: readonly CharacterCastPlanItemResource[];
  readonly failure_code: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly completed_at: string | null;
}

export interface CharacterCastPlanListResource {
  readonly contract_version: typeof CHARACTER_CAST_PLAN_LIST_VERSION;
  readonly novel_id: string;
  readonly server_now: string;
  readonly items: readonly CharacterCastPlanResource[];
}

export interface CreateCharacterVoiceGeneratorCommandRequest {
  readonly contract_version: typeof CHARACTER_VOICE_GENERATION_REQUEST_VERSION;
  readonly timeline_id: string | null;
  readonly character_instance_id: string | null;
  readonly expected_binding_version: number;
  readonly seed: string | null;
}

export interface RetryCharacterVoiceGeneratorCommandRequest {
  readonly expected_binding_version: number;
}

export interface ApplyCharacterVoiceGeneratorCommandRequest {
  readonly expected_binding_version: number;
}

export type CharacterVoiceGeneratorState =
  | "queued"
  | "analyzing_character"
  | "waiting_for_heavy_runtime"
  | "generating_voice"
  | "unloading_voice_generator"
  | "validating_with_nano"
  | "ready_applied"
  | "ready_unapplied"
  | "failed_character_analysis"
  | "failed_runtime_unavailable"
  | "failed_memory_safety"
  | "failed_generation"
  | "failed_audio_validation"
  | "failed_nano_validation"
  | "failed_storage"
  | "cancelled"
  | "superseded";

export interface CharacterVoiceGeneratorCommandResource {
  readonly contract_version: typeof CHARACTER_VOICE_GENERATION_VERSION;
  readonly command_id: string;
  readonly novel_id: string;
  readonly character_id: string;
  readonly draft_id: string | null;
  readonly background_job_id: string | null;
  readonly state: CharacterVoiceGeneratorState;
  readonly progress_current: number;
  readonly progress_total: 6;
  readonly expected_binding_version: number;
  readonly applied_binding_version: number | null;
  readonly brief: CharacterVoiceBriefResource | null;
  readonly voice_profile_id: string | null;
  readonly voice_version_id: string | null;
  readonly result_version: VoiceProfileVersionResource | null;
  readonly current_character_binding: CharacterVoiceBindingResource;
  readonly selection_still_current: boolean;
  readonly cancellable: boolean;
  readonly retryable: boolean;
  readonly terminal: boolean;
  readonly failure_code: string | null;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly applied_at: string | null;
  readonly updated_at: string;
}

export interface CharacterVoiceGeneratorCommandListResource {
  readonly contract_version: typeof CHARACTER_VOICE_GENERATION_LIST_VERSION;
  readonly novel_id: string;
  readonly character_id: string;
  readonly items: readonly CharacterVoiceGeneratorCommandResource[];
}

export type PrivateVoiceDeletionState =
  | "grace_pending"
  | "requested"
  | "cancelled"
  | "live_deleting"
  | "live_deleted_backup_pending"
  | "completed"
  | "failed"
  | "superseded";

export interface PrivateVoiceDeletionImpactResource {
  readonly schema_version: typeof PRIVATE_VOICE_DELETION_IMPACT_VERSION;
  readonly profile_id: string;
  readonly novel_id: string;
  readonly profile_version: number;
  readonly voice_version_ids: readonly string[];
  readonly current_narrator_count: number;
  readonly character_binding_count: number;
  readonly anonymous_speaker_count: number;
  readonly generic_slot_count: number;
  readonly historical_edition_count: number;
  readonly render_count: number;
  readonly export_count: number;
  readonly current_reference_count: number;
  readonly historical_reference_count: number;
  readonly reference_count: number;
  readonly asset_count: number;
  readonly total_bytes: number;
  readonly active_job_count: number;
  readonly external_backup_status: "unmanaged" | "managed_pending" | "managed_expired";
  readonly historical_audio_consequence: "unavailable_private_voice_deleted" | null;
  readonly impact_summary: string;
}

export interface PrivateVoiceDeletionRequestResource {
  readonly contract_version: typeof PRIVATE_VOICE_DELETION_VERSION;
  readonly request_id: string;
  readonly profile_id: string;
  readonly novel_id: string;
  readonly command: "discard_unreferenced_private_voice" | "true_delete_private_voice";
  readonly state: PrivateVoiceDeletionState;
  readonly server_now: string;
  readonly expected_profile_version: number;
  readonly impact_digest: string;
  readonly impact: PrivateVoiceDeletionImpactResource;
  readonly eligibility: "unreferenced" | "referenced" | "blocked";
  readonly reference_count: number;
  readonly execute_after: string | null;
  readonly impact_expires_at: string | null;
  readonly asset_count: number;
  readonly total_bytes: number;
  readonly external_backup_status: "unmanaged" | "managed_pending" | "managed_expired";
  readonly confirmed_at: string | null;
  readonly cancelled_at: string | null;
  readonly completed_at: string | null;
  readonly superseded_at: string | null;
  readonly job_drain_started_at: string | null;
  readonly job_drain_deadline: string | null;
  readonly failure_code: string | null;
  readonly cancellable: boolean;
  readonly retryable: boolean;
  readonly terminal: boolean;
}

export interface PrivateVoiceLifecycleProfileResource {
  readonly profile_id: string;
  readonly novel_id: string;
  readonly current_version_id: string | null;
  readonly display_name: string;
  readonly source_type: "uploaded" | "generated";
  readonly profile_version: number;
  readonly eligibility: "unreferenced" | "referenced" | "blocked";
  readonly blocked_reason: string | null;
  readonly reference_count: number;
  readonly asset_count: number;
  readonly total_bytes: number;
  readonly impact: PrivateVoiceDeletionImpactResource;
  readonly impact_summary: string;
  readonly active_request: PrivateVoiceDeletionRequestResource | null;
}

export interface PrivateVoiceLifecycleResource {
  readonly schema_version: typeof PRIVATE_VOICE_LIFECYCLE_VERSION;
  readonly novel_id: string;
  readonly server_now: string;
  readonly items: readonly PrivateVoiceLifecycleProfileResource[];
}

export interface CreatePrivateVoiceDeletionRequest {
  readonly expected_profile_version: number;
}

export interface ConfirmPrivateVoiceDeletionRequest {
  readonly expected_profile_version: number;
  readonly impact_digest: string;
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
  if (items.length !== OFFICIAL_PRESET_IDS.length) {
    fail(`${path}.items`, "expected exact 18-item pinned catalog");
  }
  items.forEach((entry, index) => {
    const itemPath = `${path}.items[${index}]`;
    const preset = record(entry, itemPath);
    exact(preset, [
      "preset_id", "display_name", "group", "language", "local_use_status",
      "commercial_distribution_status", "validation_tier", "language_scope",
      "selectable_now", "previewable_now", "renderable_existing", "usage_notice",
      "provenance",
    ], itemPath);
    const presetId = string(preset.preset_id, `${itemPath}.preset_id`, 6, 85);
    if (!OFFICIAL_PRESET_ID_PATTERN.test(presetId)) fail(`${itemPath}.preset_id`, "expected exact ONNX preset id");
    const expectedPresetId = OFFICIAL_PRESET_IDS[index]!;
    if (presetId !== expectedPresetId) {
      fail(`${itemPath}.preset_id`, `expected pinned catalog order item ${expectedPresetId}`);
    }
    string(preset.display_name, `${itemPath}.display_name`, 1, 160);
    string(preset.group, `${itemPath}.group`, 1, 80);
    language(preset.language, `${itemPath}.language`);
    literal(preset.local_use_status, "available", `${itemPath}.local_use_status`);
    literal(preset.commercial_distribution_status, "not_evaluated", `${itemPath}.commercial_distribution_status`);
    const validationTier = oneOf(
      preset.validation_tier,
      ["canonical_chapter_verified", "pinned_catalog_unreviewed"] as const,
      `${itemPath}.validation_tier`,
    );
    const expectedValidationTier = (["onnx.Junhao", "onnx.Zhiming", "onnx.Xiaoyu"] as const)
      .includes(presetId as "onnx.Junhao" | "onnx.Zhiming" | "onnx.Xiaoyu")
      ? "canonical_chapter_verified"
      : "pinned_catalog_unreviewed";
    if (validationTier !== expectedValidationTier) {
      fail(`${itemPath}.validation_tier`, "official preset validation tier changed");
    }
    const languageScope = oneOf(
      preset.language_scope,
      ["zh-CN", "en", "ja-JP"] as const,
      `${itemPath}.language_scope`,
    );
    if (languageScope !== preset.language) fail(itemPath, "catalog language scope changed");
    boolean(preset.selectable_now, `${itemPath}.selectable_now`);
    boolean(preset.previewable_now, `${itemPath}.previewable_now`);
    boolean(preset.renderable_existing, `${itemPath}.renderable_existing`);
    literal(preset.usage_notice, "private_local_writing_tool", `${itemPath}.usage_notice`);
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
    "quality_state", "activation_basis", "validation_basis", "rights", "official_preset",
    "reference_asset_id", "preview_asset", "description_available",
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
  const activation = oneOf(
    item.activation_basis,
    ["preview_confirmed", "explicit_official_preset_selection", "character_one_click_generation", "experimental_machine_validated"] as const,
    `${path}.activation_basis`,
  );
  const validation = oneOf(
    item.validation_basis,
    ["pending", "human_accepted", "machine_validated", "not_required"] as const,
    `${path}.validation_basis`,
  );
  validateRights(item.rights, `${path}.rights`);
  if (item.official_preset !== null) validateOfficialPresetProvenance(item.official_preset, `${path}.official_preset`);
  const rights = record(item.rights, `${path}.rights`);
  const reference = nullableUuid(item.reference_asset_id, `${path}.reference_asset_id`);
  if (item.preview_asset !== null) validateMedia(item.preview_asset, `${path}.preview_asset`);
  const description = boolean(item.description_available, `${path}.description_available`);
  const lockedAt = nullableTimestamp(item.locked_at, `${path}.locked_at`);
  timestamp(item.created_at, `${path}.created_at`);
  const machineExperimental = source === "generated"
    && activation === "experimental_machine_validated"
    && validation === "machine_validated"
    && quality === "accepted"
    && lockedAt === null;
  const machineCharacter = source === "generated"
    && activation === "character_one_click_generation"
    && validation === "machine_validated"
    && quality === "accepted"
    && lockedAt === null
    && rights.source_kind === "voice_generator"
    && reference !== null
    && description;
  const carriesOfficialPreset = source === "preset" || machineExperimental;
  if (carriesOfficialPreset !== (preset !== null)) fail(path, "preset_key source mismatch");
  if (rights.source_kind === "official_preset") {
    if (!carriesOfficialPreset || item.official_preset === null) fail(path, "official preset lacks pinned provenance");
    const provenance = record(item.official_preset, `${path}.official_preset`);
    if (provenance.preset_id !== preset) fail(path, "official preset identity mismatch");
  } else if (item.official_preset !== null) fail(path, "non-official source published official provenance");
  if (source === "uploaded" && reference === null) fail(path, "uploaded voice lacks reference asset");
  if (source === "generated" && !machineExperimental && !description) {
    fail(path, "generated voice lacks description record");
  }
  const humanConfirmed = activation === "preview_confirmed"
    && validation === "human_accepted" && quality === "accepted" && lockedAt !== null;
  const officialDirect = source === "preset"
    && activation === "explicit_official_preset_selection"
    && validation === "not_required" && quality === "pending" && lockedAt === null;
  if (state === "locked" && !(
    humanConfirmed || officialDirect || machineExperimental || machineCharacter
  )) {
    fail(path, "invalid locked voice activation evidence");
  }
  if (state !== "locked" && lockedAt !== null) fail(path, "non-locked voice has locked_at");
  if (state !== "locked" && (activation !== "preview_confirmed" || validation !== "pending")) {
    fail(path, "non-locked voice has activation evidence");
  }
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

function validateOfficialVoiceSelection(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "replayed", "selection_still_current", "frozen_result", "profile",
    "current_settings", "current_character_binding",
  ], path);
  literal(item.contract_version, "official-voice-selection/1.0", `${path}.contract_version`);
  const replayed = boolean(item.replayed, `${path}.replayed`);
  const selectionStillCurrent = boolean(item.selection_still_current, `${path}.selection_still_current`);
  const result = record(item.frozen_result, `${path}.frozen_result`);
  exact(result, [
    "command_id", "preset_id", "target_kind", "character_id", "profile_id", "version_id",
    "settings_version", "binding_version", "target_language", "language_mismatch", "completed_at",
  ], `${path}.frozen_result`);
  uuid(result.command_id, `${path}.frozen_result.command_id`);
  const presetId = string(result.preset_id, `${path}.frozen_result.preset_id`, 6, 85);
  const presetIndex = OFFICIAL_PRESET_IDS.indexOf(presetId as OfficialPresetId);
  if (presetIndex < 0) fail(`${path}.frozen_result.preset_id`, "unknown pinned preset");
  const target = oneOf(result.target_kind, ["narrator", "character"] as const, `${path}.frozen_result.target_kind`);
  const characterId = nullableUuid(result.character_id, `${path}.frozen_result.character_id`);
  const profileId = uuid(result.profile_id, `${path}.frozen_result.profile_id`);
  const versionId = uuid(result.version_id, `${path}.frozen_result.version_id`);
  const settingsVersion = integer(result.settings_version, `${path}.frozen_result.settings_version`, 1);
  const bindingVersion = result.binding_version === null
    ? null
    : integer(result.binding_version, `${path}.frozen_result.binding_version`, 1);
  const targetLanguage = language(result.target_language, `${path}.frozen_result.target_language`);
  const languageMismatch = boolean(result.language_mismatch, `${path}.frozen_result.language_mismatch`);
  timestamp(result.completed_at, `${path}.frozen_result.completed_at`);
  if ((target === "character") !== (characterId !== null && bindingVersion !== null)) {
    fail(`${path}.frozen_result`, "selection target shape mismatch");
  }
  const presetLanguage = presetIndex < 6 ? "zh-CN" : presetIndex < 11 ? "en" : "ja-JP";
  const targetLanguageBase = targetLanguage.split("-", 1)[0]!.toLocaleLowerCase("en-US");
  const presetLanguageBase = presetLanguage.split("-", 1)[0]!.toLocaleLowerCase("en-US");
  if (languageMismatch !== (targetLanguageBase !== presetLanguageBase)) {
    fail(`${path}.frozen_result.language_mismatch`, "selection language mismatch evidence changed");
  }

  validateVoiceProfile(item.profile, `${path}.profile`);
  const profile = record(item.profile, `${path}.profile`);
  if (profile.profile_id !== profileId) fail(`${path}.profile`, "selection profile mismatch");
  const versions = array(profile.versions, `${path}.profile.versions`).map((entry) => record(entry, `${path}.profile.versions`));
  if (!versions.some((entry) => entry.version_id === versionId)) fail(`${path}.profile`, "selection version missing");

  let projectionIsCurrent: boolean;
  if (target === "narrator") {
    if (item.current_settings === null || item.current_character_binding !== null) {
      fail(path, "narrator selection projection mismatch");
    }
    validateSettings(item.current_settings, `${path}.current_settings`);
    const settings = record(item.current_settings, `${path}.current_settings`);
    const values = record(settings.values, `${path}.current_settings.values`);
    const narrator = values.narrator === null
      ? null
      : record(values.narrator, `${path}.current_settings.values.narrator`);
    projectionIsCurrent = narrator?.profile_id === profileId && narrator?.version_id === versionId;
    if (!replayed && settings.version !== settingsVersion) {
      fail(`${path}.current_settings.version`, "new selection settings version mismatch");
    }
  } else {
    if (item.current_settings !== null || item.current_character_binding === null) {
      fail(path, "character selection projection mismatch");
    }
    validateBinding(item.current_character_binding, `${path}.current_character_binding`);
    const binding = record(item.current_character_binding, `${path}.current_character_binding`);
    if (binding.character_id !== characterId) {
      fail(`${path}.current_character_binding`, "selection character projection mismatch");
    }
    projectionIsCurrent = binding.profile_id === profileId && binding.version_id === versionId;
    if (!replayed && binding.version !== bindingVersion) {
      fail(`${path}.current_character_binding.version`, "new selection binding version mismatch");
    }
  }
  if (selectionStillCurrent !== projectionIsCurrent) {
    fail(`${path}.selection_still_current`, "current projection truth value changed");
  }
  if (!replayed && !selectionStillCurrent) {
    fail(path, "new selection must be current when returned");
  }
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

function validateNanoDecodeParameters(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "schema_version", "seed", "text_temperature_milli", "text_top_p_milli",
    "text_top_k", "audio_temperature_milli", "audio_top_p_milli", "audio_top_k",
    "audio_repetition_penalty_milli", "sample_mode", "max_new_frames",
  ], path);
  literal(item.schema_version, NANO_DECODE_PARAMETERS_SCHEMA_VERSION, `${path}.schema_version`);
  const seed = string(item.seed, `${path}.seed`, 1, 19);
  if (!/^(0|[1-9]\d*)$/.test(seed) || BigInt(seed) > 9_223_372_036_854_775_807n) {
    fail(`${path}.seed`, "expected canonical signed-int64 decimal string");
  }
  integer(item.text_temperature_milli, `${path}.text_temperature_milli`, 100, 2_000);
  integer(item.text_top_p_milli, `${path}.text_top_p_milli`, 1, 1_000);
  integer(item.text_top_k, `${path}.text_top_k`, 1, 100);
  integer(item.audio_temperature_milli, `${path}.audio_temperature_milli`, 100, 2_000);
  integer(item.audio_top_p_milli, `${path}.audio_top_p_milli`, 1, 1_000);
  integer(item.audio_top_k, `${path}.audio_top_k`, 1, 100);
  integer(item.audio_repetition_penalty_milli, `${path}.audio_repetition_penalty_milli`, 1_000, 2_000);
  literal(item.sample_mode, "full", `${path}.sample_mode`);
  literal(item.max_new_frames, 375, `${path}.max_new_frames`);
}

function validateNanoVoiceExperiment(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "command_id", "novel_id", "profile_id", "version_id",
    "background_job_id", "base_preset_id", "target_kind", "character_id",
    "expected_settings_version", "expected_binding_version", "parameters",
    "parameters_digest", "fingerprint", "state", "reused_version", "preview",
    "current_settings", "current_character_binding", "failure_code", "retryable",
    "created_at", "started_at", "completed_at",
  ], path);
  literal(item.contract_version, NANO_VOICE_EXPERIMENT_VERSION, `${path}.contract_version`);
  uuid(item.command_id, `${path}.command_id`);
  uuid(item.novel_id, `${path}.novel_id`);
  uuid(item.profile_id, `${path}.profile_id`);
  uuid(item.version_id, `${path}.version_id`);
  uuid(item.background_job_id, `${path}.background_job_id`);
  const presetId = string(item.base_preset_id, `${path}.base_preset_id`, 6, 85);
  if (!OFFICIAL_PRESET_IDS.includes(presetId as OfficialPresetId)) {
    fail(`${path}.base_preset_id`, "unknown pinned official preset");
  }
  const target = oneOf(item.target_kind, ["narrator", "character"] as const, `${path}.target_kind`);
  const characterId = nullableUuid(item.character_id, `${path}.character_id`);
  integer(item.expected_settings_version, `${path}.expected_settings_version`);
  const bindingVersion = item.expected_binding_version === null
    ? null
    : integer(item.expected_binding_version, `${path}.expected_binding_version`);
  validateNanoDecodeParameters(item.parameters, `${path}.parameters`);
  sha256(item.parameters_digest, `${path}.parameters_digest`);
  sha256(item.fingerprint, `${path}.fingerprint`);
  const state = oneOf(item.state, ["pending", "running", "ready_applied", "ready_unapplied", "failed"] as const, `${path}.state`);
  boolean(item.reused_version, `${path}.reused_version`);
  if (item.preview !== null) validatePreview(item.preview, `${path}.preview`);
  if (item.current_settings !== null) validateSettings(item.current_settings, `${path}.current_settings`);
  if (item.current_character_binding !== null) validateBinding(item.current_character_binding, `${path}.current_character_binding`);
  const failure = nullableString(item.failure_code, `${path}.failure_code`, 96);
  const retryable = boolean(item.retryable, `${path}.retryable`);
  timestamp(item.created_at, `${path}.created_at`);
  nullableTimestamp(item.started_at, `${path}.started_at`);
  nullableTimestamp(item.completed_at, `${path}.completed_at`);
  if (target === "narrator") {
    if (characterId !== null || bindingVersion !== null || item.current_settings === null || item.current_character_binding !== null) {
      fail(path, "invalid narrator target projection");
    }
  } else if (characterId === null || bindingVersion === null || item.current_settings !== null || item.current_character_binding === null) {
    fail(path, "invalid character target projection");
  }
  if (["ready_applied", "ready_unapplied"].includes(state) && item.preview === null) {
    fail(path, "ready experiment requires validated preview");
  }
  if ((state === "failed") !== (failure !== null) || (retryable && state !== "failed")) {
    fail(path, "invalid experiment failure projection");
  }
}

function validateCharacterVoiceBrief(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "schema_version", "language", "presentation", "pitch", "pace", "energy",
    "texture", "evidence_fields",
  ], path);
  literal(item.schema_version, CHARACTER_VOICE_BRIEF_VERSION, `${path}.schema_version`);
  if (item.language !== null) oneOf(item.language, ["zh-CN", "en", "ja-JP"] as const, `${path}.language`);
  if (item.presentation !== null) oneOf(item.presentation, ["masculine", "feminine", "androgynous"] as const, `${path}.presentation`);
  for (const key of ["pitch", "pace", "energy"] as const) {
    if (item[key] !== null) integer(item[key], `${path}.${key}`, -2, 2);
  }
  if (item.texture !== null) {
    oneOf(item.texture, ["clear", "warm", "airy", "husky", "firm", "soft", "bright", "dark"] as const, `${path}.texture`);
  }
  stringArray(item.evidence_fields, `${path}.evidence_fields`, 64);
}

function validateCharacterVoiceMatch(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "character_id", "brief", "selected_preset_id", "score_milli",
    "state", "selection_still_current", "current_character_binding", "model_evidence",
  ], path);
  literal(item.contract_version, CHARACTER_VOICE_MATCH_VERSION, `${path}.contract_version`);
  const characterId = uuid(item.character_id, `${path}.character_id`);
  validateCharacterVoiceBrief(item.brief, `${path}.brief`);
  const presetId = string(item.selected_preset_id, `${path}.selected_preset_id`, 6, 85);
  if (!OFFICIAL_PRESET_IDS.includes(presetId as OfficialPresetId)) {
    fail(`${path}.selected_preset_id`, "unknown pinned official preset");
  }
  integer(item.score_milli, `${path}.score_milli`, 0, 1_000);
  const state = oneOf(item.state, ["ready_applied", "ready_unapplied"] as const, `${path}.state`);
  const stillCurrent = boolean(item.selection_still_current, `${path}.selection_still_current`);
  validateBinding(item.current_character_binding, `${path}.current_character_binding`);
  if (record(item.current_character_binding, path).character_id !== characterId) {
    fail(`${path}.current_character_binding`, "character scope mismatch");
  }
  const evidence = record(item.model_evidence, `${path}.model_evidence`);
  literal(evidence.schema_version, "model-execution-evidence/2", `${path}.model_evidence.schema_version`);
  if ((state === "ready_applied") !== stillCurrent) fail(path, "match state/current flag mismatch");
}

function validateNarratorVoiceBrief(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "schema_version", "language", "presentation", "pitch", "pace", "energy",
    "texture", "evidence_fields",
  ], path);
  literal(item.schema_version, NARRATOR_VOICE_BRIEF_VERSION, `${path}.schema_version`);
  if (item.language !== null) oneOf(item.language, ["zh-CN", "en", "ja-JP"] as const, `${path}.language`);
  if (item.presentation !== null) oneOf(item.presentation, ["masculine", "feminine", "androgynous"] as const, `${path}.presentation`);
  for (const key of ["pitch", "pace", "energy"] as const) {
    if (item[key] !== null) integer(item[key], `${path}.${key}`, -2, 2);
  }
  if (item.texture !== null) {
    oneOf(item.texture, ["clear", "warm", "airy", "husky", "firm", "soft", "bright", "dark"] as const, `${path}.texture`);
  }
  const evidence = stringArray(item.evidence_fields, `${path}.evidence_fields`, 48);
  const pattern = /^(language|presentation|pitch|pace|energy|texture):(?:narration_settings\.language|novel\.(?:title|genre|subgenre|description|idea|highlight|background|main_plot))$/;
  if (new Set(evidence).size !== evidence.length || evidence.some((entry) => !pattern.test(entry))) {
    fail(`${path}.evidence_fields`, "narrator evidence escaped the saved metadata allowlist");
  }
  const evidenced = new Set(evidence.map((entry) => entry.split(":", 1)[0]));
  const populated = new Set<string>(
    (["language", "presentation", "pitch", "pace", "energy", "texture"] as const)
      .filter((key) => item[key] !== null),
  );
  if (
    evidenced.size !== populated.size
    || [...evidenced].some((dimension) => !populated.has(dimension))
  ) {
    fail(`${path}.evidence_fields`, "narrator evidence must exactly cover populated dimensions");
  }
}

const CHARACTER_CAST_PLAN_STATES = [
  "reserved", "analyzing", "ready_applied", "ready_applied_with_warnings",
  "ready_unapplied", "failed", "superseded",
] as const;
const CHARACTER_CAST_ITEM_STATES = [
  "pending", "analyzing", "preserved", "scored", "assigned", "blocked",
] as const;
const CAST_TARGET_KEY_PATTERN = /^(?:narrator|character:[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i;

function validateCharacterCastTarget(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "target_key", "target_kind", "character_id", "character_name", "role_type",
  ], path);
  const targetKey = string(item.target_key, `${path}.target_key`, 1, 64);
  if (!CAST_TARGET_KEY_PATTERN.test(targetKey)) fail(`${path}.target_key`, "invalid cast target key");
  const targetKind = oneOf(item.target_kind, ["narrator", "character"] as const, `${path}.target_kind`);
  const characterId = nullableUuid(item.character_id, `${path}.character_id`);
  const characterName = nullableString(item.character_name, `${path}.character_name`, 240);
  const roleType = nullableString(item.role_type, `${path}.role_type`, 30);
  if (targetKind === "narrator") {
    if (targetKey !== "narrator" || characterId !== null || characterName !== null || roleType !== null) {
      fail(path, "narrator target carries character identity");
    }
  } else if (
    characterId === null
    || characterName === null
    || roleType === null
    || targetKey !== `character:${characterId}`
  ) {
    fail(path, "character target identity is incomplete");
  }
}

function validateCharacterCastPlanItem(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "item_id", "target", "state", "attempt", "workspace_digest",
    "lease_expires_at", "brief", "selected_preset_id", "score_milli",
    "profile_id", "version_id", "voice_action_command_id", "warning_code",
    "failure_code",
  ], path);
  uuid(item.item_id, `${path}.item_id`);
  validateCharacterCastTarget(item.target, `${path}.target`);
  const target = record(item.target, `${path}.target`);
  const state = oneOf(item.state, CHARACTER_CAST_ITEM_STATES, `${path}.state`);
  integer(item.attempt, `${path}.attempt`, 0);
  sha256(item.workspace_digest, `${path}.workspace_digest`);
  const lease = nullableTimestamp(item.lease_expires_at, `${path}.lease_expires_at`);
  if ((state === "analyzing") !== (lease !== null)) fail(path, "cast item lease/state mismatch");
  if (item.brief !== null) {
    const brief = record(item.brief, `${path}.brief`);
    if (target.target_kind === "narrator") {
      validateNarratorVoiceBrief(brief, `${path}.brief`);
    } else {
      validateCharacterVoiceBrief(brief, `${path}.brief`);
    }
  }
  const presetId = item.selected_preset_id === null
    ? null
    : string(item.selected_preset_id, `${path}.selected_preset_id`, 6, 85);
  if (presetId !== null && !OFFICIAL_PRESET_IDS.includes(presetId as OfficialPresetId)) {
    fail(`${path}.selected_preset_id`, "unknown pinned official preset");
  }
  const score = item.score_milli === null
    ? null
    : integer(item.score_milli, `${path}.score_milli`, 0, 1_000);
  const profileId = nullableUuid(item.profile_id, `${path}.profile_id`);
  const versionId = nullableUuid(item.version_id, `${path}.version_id`);
  if ((profileId === null) !== (versionId === null)) fail(path, "incomplete cast voice identity");
  nullableUuid(item.voice_action_command_id, `${path}.voice_action_command_id`);
  for (const key of ["warning_code", "failure_code"] as const) {
    const code = nullableString(item[key], `${path}.${key}`, 96);
    if (code !== null && !SAFE_CODE_PATTERN.test(code)) fail(`${path}.${key}`, "unsafe cast code");
  }
  if (["scored", "assigned"].includes(state) && (item.brief === null || presetId === null || score === null)) {
    fail(path, "scored cast item lacks brief, preset, or score");
  }
  if (state === "preserved" && versionId === null) fail(path, "preserved cast item lacks voice identity");
}

function validateCharacterCastPlan(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "command_id", "novel_id", "timeline_id", "mode", "state",
    "server_now", "progress_current", "progress_total", "terminal", "retryable",
    "current_target_key", "lease_expires_at", "assignments", "preserved", "warnings",
    "items", "failure_code", "created_at", "updated_at", "completed_at",
  ], path);
  literal(item.contract_version, CHARACTER_CAST_PLAN_VERSION, `${path}.contract_version`);
  uuid(item.command_id, `${path}.command_id`);
  uuid(item.novel_id, `${path}.novel_id`);
  uuid(item.timeline_id, `${path}.timeline_id`);
  literal(item.mode, "fill_and_deduplicate", `${path}.mode`);
  const state = oneOf(item.state, CHARACTER_CAST_PLAN_STATES, `${path}.state`);
  timestamp(item.server_now, `${path}.server_now`);
  const progressCurrent = integer(item.progress_current, `${path}.progress_current`, 0);
  const progressTotal = integer(item.progress_total, `${path}.progress_total`, 1);
  if (progressCurrent > progressTotal) fail(path, "cast progress exceeds total");
  const terminal = boolean(item.terminal, `${path}.terminal`);
  boolean(item.retryable, `${path}.retryable`);
  const targetKey = nullableString(item.current_target_key, `${path}.current_target_key`, 64);
  if (targetKey !== null && !CAST_TARGET_KEY_PATTERN.test(targetKey)) fail(`${path}.current_target_key`, "invalid active target");
  const lease = nullableTimestamp(item.lease_expires_at, `${path}.lease_expires_at`);
  if ((targetKey === null) !== (lease === null)) fail(path, "active target/lease mismatch");

  const assignments = array(item.assignments, `${path}.assignments`);
  assignments.forEach((entry, index) => {
    const entryPath = `${path}.assignments[${index}]`;
    const assignment = record(entry, entryPath);
    exact(assignment, ["target", "preset_id", "score_milli", "voice_action_command_id"], entryPath);
    validateCharacterCastTarget(assignment.target, `${entryPath}.target`);
    const preset = string(assignment.preset_id, `${entryPath}.preset_id`, 6, 85);
    if (!OFFICIAL_PRESET_IDS.includes(preset as OfficialPresetId)) fail(`${entryPath}.preset_id`, "unknown official preset");
    integer(assignment.score_milli, `${entryPath}.score_milli`, 0, 1_000);
    nullableUuid(assignment.voice_action_command_id, `${entryPath}.voice_action_command_id`);
  });
  const preserved = array(item.preserved, `${path}.preserved`);
  preserved.forEach((entry, index) => {
    const entryPath = `${path}.preserved[${index}]`;
    const projection = record(entry, entryPath);
    exact(projection, ["target", "profile_id", "version_id", "preset_id", "source_type"], entryPath);
    validateCharacterCastTarget(projection.target, `${entryPath}.target`);
    uuid(projection.profile_id, `${entryPath}.profile_id`);
    uuid(projection.version_id, `${entryPath}.version_id`);
    if (projection.preset_id !== null) {
      const preset = string(projection.preset_id, `${entryPath}.preset_id`, 6, 85);
      if (!OFFICIAL_PRESET_IDS.includes(preset as OfficialPresetId)) fail(`${entryPath}.preset_id`, "unknown official preset");
    }
    oneOf(projection.source_type, ["preset", "uploaded", "generated"] as const, `${entryPath}.source_type`);
  });
  const warnings = array(item.warnings, `${path}.warnings`);
  warnings.forEach((entry, index) => {
    const entryPath = `${path}.warnings[${index}]`;
    const warning = record(entry, entryPath);
    exact(warning, ["code", "target_key", "message"], entryPath);
    const code = string(warning.code, `${entryPath}.code`, 1, 96);
    if (!SAFE_CODE_PATTERN.test(code)) fail(`${entryPath}.code`, "unsafe warning code");
    const warningTarget = nullableString(warning.target_key, `${entryPath}.target_key`, 64);
    if (warningTarget !== null && !CAST_TARGET_KEY_PATTERN.test(warningTarget)) fail(`${entryPath}.target_key`, "invalid warning target");
    string(warning.message, `${entryPath}.message`, 1, 400);
  });
  const items = array(item.items, `${path}.items`);
  items.forEach((entry, index) => validateCharacterCastPlanItem(entry, `${path}.items[${index}]`));
  if (items.length !== progressTotal) fail(`${path}.items`, "cast item count differs from progress total");
  const failure = nullableString(item.failure_code, `${path}.failure_code`, 96);
  if (failure !== null && !SAFE_CODE_PATTERN.test(failure)) fail(`${path}.failure_code`, "unsafe failure code");
  timestamp(item.created_at, `${path}.created_at`);
  timestamp(item.updated_at, `${path}.updated_at`);
  const completedAt = nullableTimestamp(item.completed_at, `${path}.completed_at`);
  const terminalStates = new Set(["ready_applied", "ready_applied_with_warnings", "ready_unapplied", "failed", "superseded"]);
  if (terminal !== terminalStates.has(state) || terminal !== (completedAt !== null)) fail(path, "cast terminal projection mismatch");
  if ((state === "failed") !== (failure !== null)) fail(path, "cast failure projection mismatch");
}

const CHARACTER_VOICE_GENERATOR_STATES = [
  "queued", "analyzing_character", "waiting_for_heavy_runtime",
  "generating_voice", "unloading_voice_generator", "validating_with_nano",
  "ready_applied", "ready_unapplied", "failed_character_analysis",
  "failed_runtime_unavailable", "failed_memory_safety", "failed_generation",
  "failed_audio_validation", "failed_nano_validation", "failed_storage",
  "cancelled", "superseded",
] as const;

function validateCharacterVoiceGeneratorCommand(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "command_id", "novel_id", "character_id", "draft_id",
    "background_job_id", "state", "progress_current", "progress_total",
    "expected_binding_version", "applied_binding_version", "brief",
    "voice_profile_id", "voice_version_id", "result_version",
    "current_character_binding", "selection_still_current", "cancellable",
    "retryable", "terminal", "failure_code", "created_at", "started_at",
    "completed_at", "applied_at", "updated_at",
  ], path);
  literal(item.contract_version, CHARACTER_VOICE_GENERATION_VERSION, `${path}.contract_version`);
  uuid(item.command_id, `${path}.command_id`);
  const novelId = uuid(item.novel_id, `${path}.novel_id`);
  const characterId = uuid(item.character_id, `${path}.character_id`);
  const draftId = nullableUuid(item.draft_id, `${path}.draft_id`);
  nullableUuid(item.background_job_id, `${path}.background_job_id`);
  const state = oneOf(item.state, CHARACTER_VOICE_GENERATOR_STATES, `${path}.state`);
  integer(item.progress_current, `${path}.progress_current`, 0, 6);
  literal(item.progress_total, 6, `${path}.progress_total`);
  integer(item.expected_binding_version, `${path}.expected_binding_version`);
  const appliedBinding = item.applied_binding_version === null
    ? null
    : integer(item.applied_binding_version, `${path}.applied_binding_version`, 1);
  if (item.brief !== null) validateCharacterVoiceBrief(item.brief, `${path}.brief`);
  const profileId = nullableUuid(item.voice_profile_id, `${path}.voice_profile_id`);
  const versionId = nullableUuid(item.voice_version_id, `${path}.voice_version_id`);
  if ((profileId === null) !== (versionId === null)) fail(path, "incomplete result voice identity");
  if (item.result_version !== null) {
    validateVoiceVersion(item.result_version, `${path}.result_version`);
    const result = record(item.result_version, `${path}.result_version`);
    if (result.profile_id !== profileId || result.version_id !== versionId) {
      fail(`${path}.result_version`, "result voice identity mismatch");
    }
  }
  validateBinding(item.current_character_binding, `${path}.current_character_binding`);
  const binding = record(item.current_character_binding, `${path}.current_character_binding`);
  if (binding.character_id !== characterId || binding.novel_id !== novelId) {
    fail(`${path}.current_character_binding`, "character scope mismatch");
  }
  const stillCurrent = boolean(item.selection_still_current, `${path}.selection_still_current`);
  const cancellable = boolean(item.cancellable, `${path}.cancellable`);
  const retryable = boolean(item.retryable, `${path}.retryable`);
  const terminal = boolean(item.terminal, `${path}.terminal`);
  const failure = nullableString(item.failure_code, `${path}.failure_code`, 96);
  if (failure !== null && !SAFE_CODE_PATTERN.test(failure)) fail(`${path}.failure_code`, "unsafe failure code");
  timestamp(item.created_at, `${path}.created_at`);
  nullableTimestamp(item.started_at, `${path}.started_at`);
  const completedAt = nullableTimestamp(item.completed_at, `${path}.completed_at`);
  const appliedAt = nullableTimestamp(item.applied_at, `${path}.applied_at`);
  timestamp(item.updated_at, `${path}.updated_at`);
  const active = [
    "queued", "analyzing_character", "waiting_for_heavy_runtime",
    "generating_voice", "unloading_voice_generator", "validating_with_nano",
  ].includes(state);
  const failed = state.startsWith("failed_");
  const ready = state === "ready_applied" || state === "ready_unapplied";
  if (terminal === active) fail(path, "terminal flag mismatch");
  if (failed !== (failure !== null)) fail(path, "failure evidence mismatch");
  if (draftId === null && !["queued", "analyzing_character", "failed_character_analysis", "cancelled", "superseded"].includes(state)) {
    fail(path, "state requires a design draft");
  }
  if (ready && (versionId === null || item.result_version === null || completedAt === null)) {
    fail(path, "ready command lacks result evidence");
  }
  if (state === "ready_applied") {
    if (appliedBinding === null || appliedAt === null) fail(path, "applied command lacks CAS evidence");
  } else if (appliedBinding !== null || appliedAt !== null) {
    fail(path, "non-applied command carries CAS evidence");
  }
  if (state === "ready_unapplied" && stillCurrent) fail(path, "unapplied command cannot be current");
  if (terminal && cancellable) fail(path, "terminal command cannot be cancelled");
  if (retryable && !(failed || state === "superseded")) fail(path, "invalid retry projection");
}

function validatePrivateVoiceDeletionImpact(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "schema_version", "profile_id", "novel_id", "profile_version", "voice_version_ids",
    "current_narrator_count", "character_binding_count", "anonymous_speaker_count",
    "generic_slot_count", "historical_edition_count", "render_count", "export_count",
    "current_reference_count", "historical_reference_count", "reference_count",
    "asset_count", "total_bytes", "active_job_count", "external_backup_status",
    "historical_audio_consequence", "impact_summary",
  ], path);
  literal(item.schema_version, PRIVATE_VOICE_DELETION_IMPACT_VERSION, `${path}.schema_version`);
  uuid(item.profile_id, `${path}.profile_id`);
  uuid(item.novel_id, `${path}.novel_id`);
  integer(item.profile_version, `${path}.profile_version`, 1);
  const versionIds = array(item.voice_version_ids, `${path}.voice_version_ids`);
  versionIds.forEach((entry, index) => uuid(entry, `${path}.voice_version_ids[${index}]`));
  const currentNarrator = integer(item.current_narrator_count, `${path}.current_narrator_count`);
  const characterBindings = integer(item.character_binding_count, `${path}.character_binding_count`);
  const anonymous = integer(item.anonymous_speaker_count, `${path}.anonymous_speaker_count`);
  const generic = integer(item.generic_slot_count, `${path}.generic_slot_count`);
  const editions = integer(item.historical_edition_count, `${path}.historical_edition_count`);
  const renders = integer(item.render_count, `${path}.render_count`);
  const exports = integer(item.export_count, `${path}.export_count`);
  const currentReferences = integer(item.current_reference_count, `${path}.current_reference_count`);
  const historicalReferences = integer(item.historical_reference_count, `${path}.historical_reference_count`);
  const references = integer(item.reference_count, `${path}.reference_count`);
  integer(item.asset_count, `${path}.asset_count`);
  integer(item.total_bytes, `${path}.total_bytes`);
  integer(item.active_job_count, `${path}.active_job_count`);
  oneOf(item.external_backup_status, ["unmanaged", "managed_pending", "managed_expired"] as const, `${path}.external_backup_status`);
  if (item.historical_audio_consequence !== null) {
    literal(item.historical_audio_consequence, "unavailable_private_voice_deleted", `${path}.historical_audio_consequence`);
  }
  string(item.impact_summary, `${path}.impact_summary`, 1, 800);
  if (
    currentReferences !== currentNarrator + characterBindings + anonymous + generic
    || historicalReferences !== editions + renders + exports
    || references !== currentReferences + historicalReferences
  ) fail(path, "deletion impact reference totals mismatch");
}

function validatePrivateVoiceDeletionRequest(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, [
    "contract_version", "request_id", "profile_id", "novel_id", "command", "state",
    "server_now", "expected_profile_version", "impact_digest", "impact", "eligibility",
    "reference_count", "execute_after", "impact_expires_at", "asset_count", "total_bytes",
    "external_backup_status", "confirmed_at", "cancelled_at", "completed_at", "superseded_at",
    "job_drain_started_at", "job_drain_deadline", "failure_code", "cancellable", "retryable", "terminal",
  ], path);
  literal(item.contract_version, PRIVATE_VOICE_DELETION_VERSION, `${path}.contract_version`);
  uuid(item.request_id, `${path}.request_id`);
  const profileId = uuid(item.profile_id, `${path}.profile_id`);
  const novelId = uuid(item.novel_id, `${path}.novel_id`);
  oneOf(item.command, ["discard_unreferenced_private_voice", "true_delete_private_voice"] as const, `${path}.command`);
  const state = oneOf(item.state, ["grace_pending", "requested", "cancelled", "live_deleting", "live_deleted_backup_pending", "completed", "failed", "superseded"] as const, `${path}.state`);
  timestamp(item.server_now, `${path}.server_now`);
  const profileVersion = integer(item.expected_profile_version, `${path}.expected_profile_version`, 1);
  sha256(item.impact_digest, `${path}.impact_digest`);
  validatePrivateVoiceDeletionImpact(item.impact, `${path}.impact`);
  const impact = record(item.impact, `${path}.impact`);
  oneOf(item.eligibility, ["unreferenced", "referenced", "blocked"] as const, `${path}.eligibility`);
  const references = integer(item.reference_count, `${path}.reference_count`);
  nullableTimestamp(item.execute_after, `${path}.execute_after`);
  nullableTimestamp(item.impact_expires_at, `${path}.impact_expires_at`);
  const assets = integer(item.asset_count, `${path}.asset_count`);
  const bytes = integer(item.total_bytes, `${path}.total_bytes`);
  const backup = oneOf(item.external_backup_status, ["unmanaged", "managed_pending", "managed_expired"] as const, `${path}.external_backup_status`);
  nullableTimestamp(item.confirmed_at, `${path}.confirmed_at`);
  nullableTimestamp(item.cancelled_at, `${path}.cancelled_at`);
  nullableTimestamp(item.completed_at, `${path}.completed_at`);
  nullableTimestamp(item.superseded_at, `${path}.superseded_at`);
  nullableTimestamp(item.job_drain_started_at, `${path}.job_drain_started_at`);
  nullableTimestamp(item.job_drain_deadline, `${path}.job_drain_deadline`);
  const failure = nullableString(item.failure_code, `${path}.failure_code`, 96);
  if (failure !== null && !SAFE_CODE_PATTERN.test(failure)) fail(`${path}.failure_code`, "unsafe reason code");
  const cancellable = boolean(item.cancellable, `${path}.cancellable`);
  const retryable = boolean(item.retryable, `${path}.retryable`);
  const terminal = boolean(item.terminal, `${path}.terminal`);
  if (
    impact.profile_id !== profileId || impact.novel_id !== novelId
    || impact.profile_version !== profileVersion || impact.reference_count !== references
    || impact.asset_count !== assets || impact.total_bytes !== bytes
    || impact.external_backup_status !== backup
  ) fail(path, "deletion request/impact projection mismatch");
  if (["completed", "cancelled", "superseded"].includes(state) !== terminal) {
    if (!(state === "failed" && terminal)) fail(path, "invalid terminal deletion state");
  }
  if (terminal && (cancellable || retryable)) fail(path, "terminal request exposes actions");
}

function validatePrivateVoiceLifecycle(value: unknown, path: string): void {
  const item = record(value, path);
  exact(item, ["schema_version", "novel_id", "server_now", "items"], path);
  literal(item.schema_version, PRIVATE_VOICE_LIFECYCLE_VERSION, `${path}.schema_version`);
  const novelId = uuid(item.novel_id, `${path}.novel_id`);
  timestamp(item.server_now, `${path}.server_now`);
  const items = array(item.items, `${path}.items`);
  const seen = new Set<string>();
  items.forEach((value, index) => {
    const itemPath = `${path}.items[${index}]`;
    const profile = record(value, itemPath);
    exact(profile, [
      "profile_id", "novel_id", "current_version_id", "display_name", "source_type",
      "profile_version", "eligibility", "blocked_reason", "reference_count", "asset_count",
      "total_bytes", "impact", "impact_summary", "active_request",
    ], itemPath);
    const profileId = uuid(profile.profile_id, `${itemPath}.profile_id`);
    if (seen.has(profileId)) fail(`${path}.items`, "duplicate private voice profile");
    seen.add(profileId);
    if (uuid(profile.novel_id, `${itemPath}.novel_id`) !== novelId) fail(itemPath, "novel scope mismatch");
    nullableUuid(profile.current_version_id, `${itemPath}.current_version_id`);
    string(profile.display_name, `${itemPath}.display_name`, 1, 200);
    oneOf(profile.source_type, ["uploaded", "generated"] as const, `${itemPath}.source_type`);
    const profileVersion = integer(profile.profile_version, `${itemPath}.profile_version`, 1);
    oneOf(profile.eligibility, ["unreferenced", "referenced", "blocked"] as const, `${itemPath}.eligibility`);
    nullableString(profile.blocked_reason, `${itemPath}.blocked_reason`, 160);
    const references = integer(profile.reference_count, `${itemPath}.reference_count`);
    const assets = integer(profile.asset_count, `${itemPath}.asset_count`);
    const bytes = integer(profile.total_bytes, `${itemPath}.total_bytes`);
    validatePrivateVoiceDeletionImpact(profile.impact, `${itemPath}.impact`);
    const impact = record(profile.impact, `${itemPath}.impact`);
    string(profile.impact_summary, `${itemPath}.impact_summary`, 1, 800);
    if (
      impact.profile_id !== profileId || impact.novel_id !== novelId
      || impact.profile_version !== profileVersion || impact.reference_count !== references
      || impact.asset_count !== assets || impact.total_bytes !== bytes
    ) fail(itemPath, "lifecycle/impact projection mismatch");
    if (profile.active_request !== null) {
      validatePrivateVoiceDeletionRequest(profile.active_request, `${itemPath}.active_request`);
      if (record(profile.active_request, itemPath).profile_id !== profileId) fail(itemPath, "active request profile mismatch");
    }
  });
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

export function parseOfficialVoiceSelectionResponse(value: unknown): OfficialVoiceSelectionResponse {
  return validated(value, validateOfficialVoiceSelection, "official_voice_selection");
}

export function parseNanoVoiceExperimentResource(value: unknown): NanoVoiceExperimentResource {
  return validated(value, validateNanoVoiceExperiment, "nano_voice_experiment");
}

export function parseNanoVoiceExperimentListResource(value: unknown): NanoVoiceExperimentListResource {
  const item = record(value, "nano_voice_experiments");
  exact(item, ["contract_version", "novel_id", "items"], "nano_voice_experiments");
  literal(item.contract_version, NANO_VOICE_EXPERIMENT_LIST_VERSION, "nano_voice_experiments.contract_version");
  const novelId = uuid(item.novel_id, "nano_voice_experiments.novel_id");
  const items = array(item.items, "nano_voice_experiments.items");
  items.forEach((entry, index) => {
    validateNanoVoiceExperiment(entry, `nano_voice_experiments.items[${index}]`);
    if (record(entry, "nano_voice_experiments.items").novel_id !== novelId) {
      fail(`nano_voice_experiments.items[${index}]`, "novel scope mismatch");
    }
  });
  return item as unknown as NanoVoiceExperimentListResource;
}

export function parseCharacterVoiceMatchResource(value: unknown): CharacterVoiceMatchResource {
  return validated(value, validateCharacterVoiceMatch, "character_voice_match");
}

export function parseCharacterCastPlanResource(
  value: unknown,
): CharacterCastPlanResource {
  return validated(value, validateCharacterCastPlan, "character_cast_plan");
}

export function parseCharacterCastPlanListResource(
  value: unknown,
): CharacterCastPlanListResource {
  const item = record(value, "character_cast_plans");
  exact(
    item,
    ["contract_version", "novel_id", "server_now", "items"],
    "character_cast_plans",
  );
  literal(
    item.contract_version,
    CHARACTER_CAST_PLAN_LIST_VERSION,
    "character_cast_plans.contract_version",
  );
  const novelId = uuid(item.novel_id, "character_cast_plans.novel_id");
  timestamp(item.server_now, "character_cast_plans.server_now");
  const items = array(item.items, "character_cast_plans.items");
  const commandIds: string[] = [];
  items.forEach((entry, index) => {
    const path = `character_cast_plans.items[${index}]`;
    validateCharacterCastPlan(entry, path);
    const command = record(entry, path);
    if (command.novel_id !== novelId) fail(path, "cast plan novel scope mismatch");
    commandIds.push(uuid(command.command_id, `${path}.command_id`));
  });
  if (new Set(commandIds).size !== commandIds.length) {
    fail("character_cast_plans.items", "cast plan command IDs must be unique");
  }
  return item as unknown as CharacterCastPlanListResource;
}

export function parseCharacterVoiceGeneratorCommandResource(
  value: unknown,
): CharacterVoiceGeneratorCommandResource {
  return validated(
    value,
    validateCharacterVoiceGeneratorCommand,
    "character_voice_generation",
  );
}

export function parseCharacterVoiceGeneratorCommandListResource(
  value: unknown,
): CharacterVoiceGeneratorCommandListResource {
  const item = record(value, "character_voice_generations");
  exact(
    item,
    ["contract_version", "novel_id", "character_id", "items"],
    "character_voice_generations",
  );
  literal(
    item.contract_version,
    CHARACTER_VOICE_GENERATION_LIST_VERSION,
    "character_voice_generations.contract_version",
  );
  const novelId = uuid(item.novel_id, "character_voice_generations.novel_id");
  const characterId = uuid(
    item.character_id,
    "character_voice_generations.character_id",
  );
  const items = array(item.items, "character_voice_generations.items");
  const commandIds: string[] = [];
  items.forEach((entry, index) => {
    const path = `character_voice_generations.items[${index}]`;
    validateCharacterVoiceGeneratorCommand(entry, path);
    const command = record(entry, path);
    if (command.novel_id !== novelId || command.character_id !== characterId) {
      fail(path, "target scope mismatch");
    }
    commandIds.push(uuid(command.command_id, `${path}.command_id`));
  });
  if (new Set(commandIds).size !== commandIds.length) {
    fail("character_voice_generations.items", "command IDs must be unique");
  }
  return item as unknown as CharacterVoiceGeneratorCommandListResource;
}

export function parsePrivateVoiceDeletionRequestResource(
  value: unknown,
): PrivateVoiceDeletionRequestResource {
  return validated(value, validatePrivateVoiceDeletionRequest, "private_voice_deletion");
}

export function parsePrivateVoiceLifecycleResource(value: unknown): PrivateVoiceLifecycleResource {
  return validated(value, validatePrivateVoiceLifecycle, "private_voice_lifecycle");
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
