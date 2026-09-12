import { describe, expect, it } from "vitest";

import {
  CAPABILITY_KEYS,
  NARRATION_CACHE_SCHEMA_VERSION,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_IDS,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  T4_PRODUCT_CAPABILITY_KEYS,
  NarrationContractError,
  parseOfficialPresetCatalogResponse,
  parseOfficialVoicePreviewAudioRequest,
  parseCharacterVoiceBindingListResponse,
  parseCharacterVoiceBindingResource,
  parseNarrationApiErrorDetail,
  parseNarrationCacheCleanupResult,
  parseNarrationOverviewResponse,
  parseNarrationScopeOverrideListResponse,
  parseNarrationSettingsResource,
  parseVoiceCastingRulesResource,
  parseVoiceProfileResource,
  voiceSourceEvidenceIsUsable,
} from "./contracts";

const NOVEL_ID = "10000000-0000-4000-8000-000000000001";
const PROFILE_ID = "10000000-0000-4000-8000-000000000002";
const VERSION_ID = "10000000-0000-4000-8000-000000000003";
const RIGHTS_ID = "10000000-0000-4000-8000-000000000004";
const CHARACTER_ID = "10000000-0000-4000-8000-000000000005";
const ASSET_ID = "10000000-0000-4000-8000-000000000006";
const NOW = "2026-08-26T12:00:00Z";
function officialCatalog(
  evidenceRows: readonly (typeof OFFICIAL_PRESET_EVIDENCE)[number][] = OFFICIAL_PRESET_EVIDENCE,
) {
  return {
    schema_version: "qwen-tts-preset-catalog/2",
    items: evidenceRows.map((evidence) => {
      const female = evidence.presetId === "qwen.WarmFemale";
      const providerVoiceIds: Record<string, string> = {
        local_qwen3_tts: evidence.localVoiceId,
      };
      if (evidence.aliyunPlusVoiceId) {
        providerVoiceIds["aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"] = evidence.aliyunPlusVoiceId;
      }
      if (evidence.aliyunFlashVoiceId) {
        providerVoiceIds["aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash"] = evidence.aliyunFlashVoiceId;
      }
      return {
        preset_id: evidence.presetId,
        display_name: `${evidence.localVoiceId}｜${female ? "温暖女声" : "官方音色"}`,
        official_speaker: evidence.localVoiceId,
        native_language: evidence.nativeLanguage,
        dialect: evidence.dialect,
        group: female ? "中文女声" : "中文男声",
        language: evidence.languageScope,
        local_use_status: "available",
        commercial_distribution_status: "not_evaluated",
        validation_tier: evidence.validationTier,
        language_scope: evidence.languageScope,
        selectable_now: true,
        previewable_now: false,
        renderable_existing: true,
        usage_notice: "private_local_writing_tool",
        provenance: {
          schema_version: "qwen-tts-preset-provenance/1",
          catalog_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
          preset_id: evidence.presetId,
          local_model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
          local_model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
          provider_voice_ids: providerVoiceIds,
          model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
          provenance_fingerprint_sha256: "a".repeat(64),
        },
      };
    }),
  };
}

function settingsValues() {
  return {
    narrator: null,
    language: "zh-CN",
    output_format: "m4a_aac_lc",
    script_review_policy: "blockers_only",
    analysis_mode: "local_rules_only",
    text_rules: {
      read_chapter_title: true,
      read_author_notes: false,
      read_section_breaks: false,
      first_person_mode: "narrator",
      first_person_character_id: null,
      inner_monologue_mode: "character",
    },
    timing: {
      sentence_gap_ms: 220,
      paragraph_gap_ms: 480,
      section_gap_ms: 850,
    },
    casting: {
      anonymous_reuse_scope: "scene",
      same_scene_voice_deduplication: true,
      unknown_speaker_action: "block",
    },
    playback: { playback_rate: 1, volume: 1 },
  };
}

function settingsResource() {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    settings_id: null,
    exists: false,
    version: 0,
    values: settingsValues(),
    updated_at: null,
  };
}

function capabilities() {
  const reasons: Partial<Record<(typeof CAPABILITY_KEYS)[number], string>> = {
    cache_cleanup: "T2_GATE_REQUIRED",
    preset_voice_source: "OFFICIAL_PRESET_RUNTIME_UNAVAILABLE",
    reference_clone: "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
    voice_design: "QWEN_VOICE_DESIGN_NOT_RELEASED",
  };
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map((key) => ({
      key,
      state: "hold",
      visible: ![
        "narration_synthesis",
        "product_player",
        "editor_production",
        "reference_clone",
        "automatic_speaker_detection",
      ].includes(key),
      actionable: false,
      reason_code: reasons[key] ?? "GATE_REQUIRED",
      required_gate: "T2-GATE",
    })),
  };
}

function cacheStatus() {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_CACHE_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    snapshot_fingerprint: "a".repeat(64),
    source_asset_bytes: 0,
    locked_voice_bytes: 0,
    referenced_edition_bytes: 0,
    derived_cache_bytes: 20,
    reclaimable_bytes: 10,
    pending_job_count: 0,
    disk_free_bytes: 1_000,
    disk_total_bytes: 2_000,
    cleanup_capability: {
      key: "cache_cleanup",
      state: "hold",
      visible: true,
      actionable: false,
      reason_code: "T2_GATE_REQUIRED",
      required_gate: "T2-F",
    },
  };
}

function mediaAsset() {
  return {
    asset_id: ASSET_ID,
    content_path: `/media-assets/${ASSET_ID}/content`,
    mime_type: "audio/mp4",
    byte_size: 100,
    duration_ms: 500,
    checksum_sha256: "b".repeat(64),
  };
}

function rights() {
  return {
    rights_record_id: RIGHTS_ID,
    state: "active",
    notice_version: "voice-rights/1",
    source_kind: "user_upload",
    source_identifier_sha256: "d".repeat(64),
    purpose: "private_novel_narration",
    commercial_use: false,
    redistribution: false,
    voice_cloning: true,
    subject_consent_recorded: true,
    confirmed_at: NOW,
    expires_at: null,
    risk_flags: [],
  };
}

function lockedVersion() {
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: VERSION_ID,
    profile_id: PROFILE_ID,
    version_number: 1,
    source_type: "uploaded",
    state: "locked",
    provider_id: "qwen-tts",
    model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
    model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
    preset_key: null,
    language: "zh-CN" as const,
    fingerprint: "c".repeat(64),
    quality_state: "accepted",
    activation_basis: "preview_confirmed",
    validation_basis: "human_accepted",
    rights: rights(),
    official_preset: null,
    reference_asset_id: ASSET_ID,
    preview_asset: null,
    description_available: false,
    locked_at: NOW,
    created_at: NOW,
  };
}

function profile() {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: PROFILE_ID,
    novel_id: NOVEL_ID,
    name: "女主角",
    status: "active",
    version: 2,
    current_version_id: VERSION_ID,
    versions: [lockedVersion()],
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
  };
}

describe("narration T2 wire contract", () => {
  it("rejects retired MOSS rights and activation evidence", () => {
    for (const sourceKind of ["voice_generator", "preset_catalog"] as const) {
      expect(() => parseVoiceProfileResource({
        ...profile(),
        versions: [{
          ...lockedVersion(),
          rights: { ...rights(), source_kind: sourceKind },
        }],
      })).toThrow(NarrationContractError);
    }
    for (const activationBasis of [
      "character_one_click_generation",
      "generic_voice_pack_generation",
      "experimental_machine_validated",
    ] as const) {
      expect(() => parseVoiceProfileResource({
        ...profile(),
        versions: [{ ...lockedVersion(), activation_basis: activationBasis }],
      })).toThrow(NarrationContractError);
    }
  });

  it("accepts the exact Qwen catalog and rejects outer catalog drift", () => {
    const parsed = parseOfficialPresetCatalogResponse(officialCatalog());
    expect(parsed.items).toHaveLength(9);
    expect(parsed.items.map((item) => item.preset_id)).toEqual(OFFICIAL_PRESET_IDS);
    expect(OFFICIAL_PRESET_IDS).toEqual([
      "qwen.WarmFemale", "qwen.Vivian", "qwen.UncleFu", "qwen.Dylan", "qwen.Eric",
      "qwen.ClearMale", "qwen.Ryan", "qwen.OnoAnna", "qwen.Sohee",
    ]);
    expect(parsed.items.every((item) => item.local_use_status === "available")).toBe(true);
    expect(parsed.items.every((item) => item.commercial_distribution_status === "not_evaluated")).toBe(true);

    const incomplete = officialCatalog();
    incomplete.items.pop();
    expect(() => parseOfficialPresetCatalogResponse(incomplete)).toThrow(/complete pinned Qwen catalog/);

    const leakedCodes = officialCatalog();
    Object.assign(leakedCodes.items[0].provenance, { prompt_audio_codes: [[1, 2]] });
    expect(() => parseOfficialPresetCatalogResponse(leakedCodes)).toThrow(/expected exact keys/);

    const replaced = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{
        preset_id: string;
        provenance: { preset_id: string };
      }>;
    };
    replaced.items[1]!.preset_id = "qwen.FilteredReplacement";
    replaced.items[1]!.provenance.preset_id = "qwen.FilteredReplacement";
    expect(() => parseOfficialPresetCatalogResponse(replaced)).toThrow(/exact Qwen preset id/);

    const wrongManifest = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{ provenance: { local_model_id: string } }>;
    };
    for (const item of wrongManifest.items) item.provenance.local_model_id = "Wrong/Repository";
    expect(() => parseOfficialPresetCatalogResponse(wrongManifest)).toThrow(/pinned evidence/);

    const wrongOrder = officialCatalog();
    [wrongOrder.items[0], wrongOrder.items[1]] = [wrongOrder.items[1]!, wrongOrder.items[0]!];
    expect(() => parseOfficialPresetCatalogResponse(wrongOrder)).toThrow(/pinned catalog order/);

    const evidenceFields = [
      "local_model_id",
      "local_model_revision",
      "model_fingerprint_sha256",
    ] as const;
    for (const field of evidenceFields) {
      const drifted = JSON.parse(JSON.stringify(officialCatalog())) as {
        items: Array<{ provenance: Record<string, unknown> }>;
      };
      drifted.items[1]!.provenance[field] = field === "local_model_id"
        ? "Wrong/Repository"
        : field === "local_model_revision"
          ? "9".repeat(40)
          : "8".repeat(64);
      expect(() => parseOfficialPresetCatalogResponse(drifted), field).toThrow(/pinned evidence/);
    }

    for (const [field, value] of [
      ["catalog_id", "wrong-provider-map/1"],
      ["provider_voice_ids", {}],
    ] as const) {
      const drifted = JSON.parse(JSON.stringify(officialCatalog())) as {
        items: Array<{ provenance: Record<string, unknown> }>;
      };
      drifted.items[0]!.provenance[field] = value;
      expect(() => parseOfficialPresetCatalogResponse(drifted), field).toThrow();
    }

    const unknownProvider = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{ provenance: { provider_voice_ids: Record<string, string> } }>;
    };
    unknownProvider.items[1]!.provenance.provider_voice_ids.third_party = "guessed-voice";
    expect(() => parseOfficialPresetCatalogResponse(unknownProvider)).toThrow(/known Provider keys/u);

    const inventedCloudMapping = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{ provenance: { provider_voice_ids: Record<string, string> } }>;
    };
    inventedCloudMapping.items[1]!.provenance.provider_voice_ids[
      "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"
    ] = "invented-cloud-voice";
    expect(() => parseOfficialPresetCatalogResponse(inventedCloudMapping)).toThrow(/pinned evidence/u);

    const driftedDialect = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{ dialect: string | null }>;
    };
    driftedDialect.items[3]!.dialect = "四川口音";
    expect(() => parseOfficialPresetCatalogResponse(driftedDialect)).toThrow(/dialect changed/u);

    const driftedLegacyMapping = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{ provenance: { provider_voice_ids: Record<string, string> } }>;
    };
    driftedLegacyMapping.items[0]!.provenance.provider_voice_ids[
      "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"
    ] = "not-the-pinned-legacy-id";
    expect(() => parseOfficialPresetCatalogResponse(driftedLegacyMapping)).toThrow(/pinned evidence/u);

    const warm = parsed.items.find((item) => item.preset_id === "qwen.WarmFemale")!;
    expect(warm.preset_id).toBe("qwen.WarmFemale");
    for (const preset of parsed.items) {
      expect(voiceSourceEvidenceIsUsable({
        ...lockedVersion(),
        source_type: "preset",
        state: "locked" as const,
        quality_state: "accepted" as const,
        activation_basis: "preview_confirmed" as const,
        validation_basis: "human_accepted" as const,
        preset_key: preset.preset_id,
        rights: {
          ...rights(),
          state: "active" as const,
          source_kind: "official_preset" as const,
          purpose: "private_novel_narration" as const,
        },
        official_preset: preset.provenance,
        reference_asset_id: null,
      })).toBe(true);
    }
    expect(voiceSourceEvidenceIsUsable({
      ...lockedVersion(),
      source_type: "preset",
      state: "locked" as const,
      quality_state: "accepted" as const,
      activation_basis: "preview_confirmed" as const,
      validation_basis: "human_accepted" as const,
      preset_key: warm.preset_id,
      rights: {
        ...rights(),
        state: "active" as const,
        source_kind: "official_preset" as const,
        purpose: "private_novel_narration" as const,
      },
      official_preset: { ...warm.provenance, provider_voice_ids: {} },
      reference_asset_id: null,
    })).toBe(false);
  });

  it("keeps the stateless preview request narrow and Mandarin-only", () => {
    expect(parseOfficialVoicePreviewAudioRequest({
      preset_id: "qwen.Sohee",
      language: "zh-CN",
    })).toEqual({ preset_id: "qwen.Sohee", language: "zh-CN" });
    expect(() => parseOfficialVoicePreviewAudioRequest({
      preset_id: "qwen.Sohee",
      language: "ko-KR",
    })).toThrow(/expected literal/u);
    expect(() => parseOfficialVoicePreviewAudioRequest({
      preset_id: "qwen.Sohee",
      language: "zh-CN",
      text: "must never accept article text",
    })).toThrow(/expected exact keys/u);
  });
  it("accepts exact default settings and rejects response drift", () => {
    expect(parseNarrationSettingsResource(settingsResource()).version).toBe(0);
    expect(() => parseNarrationSettingsResource({
      ...settingsResource(),
      owner_id: "client-must-not-see-this",
    })).toThrow(NarrationContractError);
  });

  it("accepts server-owned cloud channel evidence without breaking local settings", () => {
    const base = settingsResource();
    const local = {
      ...base,
      values: {
        ...base.values,
        tts_provider: {
          provider_id: "local_qwen3_tts",
          aliyun_model_id: "qwen-audio-3.0-tts-plus",
          cloud_profile_id: null as string | null,
          cloud_profile_version: null as number | null,
          cloud_protocol: null as "qwen_audio_native_http/1" | null,
          cloud_actual_model_id: null as string | null,
          cloud_base_url_fingerprint: null as string | null,
          cloud_verification_fingerprint: null as string | null,
        },
      },
    };
    expect(
      parseNarrationSettingsResource(local).values.tts_provider?.provider_id,
    ).toBe("local_qwen3_tts");

    const partial = structuredClone(local);
    partial.values.tts_provider.cloud_profile_id = PROFILE_ID;
    expect(() => parseNarrationSettingsResource(partial)).toThrow(
      /local TTS selection cannot carry a cloud profile binding/,
    );
  });

  it("keeps scope override lists inside one novel and unique scope", () => {
    const override = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      override_id: ASSET_ID,
      novel_id: NOVEL_ID,
      scope_kind: "chapter",
      scope_id: CHARACTER_ID,
      enabled: true,
      version: 1,
      overrides: {
        narrator: null,
        language: "zh-CN",
        text_rules: null,
        timing: null,
      },
    };
    const response = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      novel_id: NOVEL_ID,
      items: [override],
    };
    expect(parseNarrationScopeOverrideListResponse(response).items).toHaveLength(1);
    expect(() => parseNarrationScopeOverrideListResponse({
      ...response,
      novel_id: PROFILE_ID,
    })).toThrow(/override novel mismatch/);
    expect(() => parseNarrationScopeOverrideListResponse({
      ...response,
      items: [override, { ...override, override_id: VERSION_ID }],
    })).toThrow(/duplicate scope override/);
  });

  it("rejects contradictory first-person targets and loose booleans", () => {
    const contradictory = settingsResource();
    contradictory.values.text_rules.first_person_mode = "character";
    expect(() => parseNarrationSettingsResource(contradictory)).toThrow(/first-person target mismatch/);

    const loose = settingsResource() as unknown as Record<string, unknown>;
    const values = loose.values as Record<string, unknown>;
    const rules = values.text_rules as Record<string, unknown>;
    rules.read_chapter_title = 1;
    expect(() => parseNarrationSettingsResource(loose)).toThrow(/expected boolean/);
  });

  it("requires the complete capability matrix and never infers operability", () => {
    expect(T4_PRODUCT_CAPABILITY_KEYS).toEqual([
      "narration_product",
      "reading_settings",
      "narration_synthesis",
      "product_player",
      "editor_production",
      "automatic_speaker_detection",
      "cache_cleanup",
    ]);
    const overview = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      novel_id: NOVEL_ID,
      capabilities: capabilities(),
      authorization: {
        mode: "fixed_local_owner_workspace",
        can_read: true,
        can_configure: false,
        can_manage_voice_assets: false,
        can_confirm_voice_rights: false,
        cloud_consent: {
          consent_id: null,
          version: 0,
          state: "not_granted",
          purpose: "narration_speaker_analysis",
          data_scope: "uncertain_segments_with_minimal_context",
          notice_version: null,
          provider_id: null,
          model_id: null,
          confirmed_at: null,
          revoked_at: null,
        },
      },
      runtime: {
        technical_enabled: false,
        lifecycle_status: "disabled",
        provider_reachable: false,
        model_ready: false,
        product_visible: false,
        protocol_version: "qwen-tts-local-runtime/1",
        model_fingerprint_sha256: null,
        reason_code: "RUNTIME_DISABLED",
      },
      settings: settingsResource(),
      coverage: {
        character_count: 0,
        configured_character_count: 0,
        locked_character_voice_count: 0,
        generic_required_slot_count: 24,
        generic_ready_slot_count: 0,
        pending_review_script_count: 0,
        blocker_count: 0,
        warning_count: 0,
        generated_chapter_count: 0,
        failed_job_count: 0,
      },
      voice_sources: [
        {
          source_type: "preset",
          capability: "preset_voice_source",
          available: false,
          reason_code: "OFFICIAL_PRESET_RUNTIME_UNAVAILABLE",
          accepted_mime_types: [],
          maximum_bytes: null,
        },
        {
          source_type: "uploaded",
          capability: "reference_clone",
          available: false,
          reason_code: "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
          accepted_mime_types: ["audio/wav", "audio/flac"],
          maximum_bytes: 16 * 1024 * 1024,
        },
        {
          source_type: "generated",
          capability: "voice_design",
          available: false,
          reason_code: "QWEN_VOICE_DESIGN_NOT_RELEASED",
          accepted_mime_types: [],
          maximum_bytes: null,
        },
      ],
      cache: cacheStatus(),
    };
    const parsed = parseNarrationOverviewResponse(overview);
    expect(parsed.capabilities.items).toHaveLength(CAPABILITY_KEYS.length);
    expect(parsed.voice_sources.every((source) => !source.available)).toBe(true);

    const missing = structuredClone(overview);
    missing.capabilities.items.pop();
    expect(() => parseNarrationOverviewResponse(missing)).toThrow(/every capability/);

    const falseGenerator = structuredClone(overview);
    const generatedSource = falseGenerator.voice_sources[2] as {
      available: boolean;
      reason_code: string | null;
    };
    generatedSource.available = true;
    generatedSource.reason_code = null;
    expect(() => parseNarrationOverviewResponse(falseGenerator)).toThrow(/availability\/capability mismatch/);

    const falseRuntime = structuredClone(overview);
    const runtime = falseRuntime.runtime as {
      technical_enabled: boolean;
      lifecycle_status: string;
      provider_reachable: boolean;
      model_ready: boolean;
      product_visible: boolean;
      model_fingerprint_sha256: string | null;
      reason_code: string | null;
    };
    runtime.technical_enabled = true;
    runtime.lifecycle_status = "ready";
    runtime.provider_reachable = true;
    runtime.model_ready = true;
    runtime.product_visible = true;
    runtime.model_fingerprint_sha256 = "e".repeat(64);
    runtime.reason_code = null;
    expect(() => parseNarrationOverviewResponse(falseRuntime)).toThrow(/T4 product chain is gated/);

    const shellOnly = structuredClone(falseRuntime);
    for (const key of ["narration_product", "reading_settings"]) {
      const capability = shellOnly.capabilities.items.find((entry) => entry.key === key);
      if (!capability) throw new Error(`missing capability ${key}`);
      Object.assign(capability, {
        state: "enabled",
        visible: true,
        actionable: true,
        reason_code: null,
        required_gate: null,
      });
    }
    expect(() => parseNarrationOverviewResponse(shellOnly)).toThrow(/T4 product chain is gated/);

    const released = structuredClone(falseRuntime);
    for (const key of [
      "narration_product",
      "reading_settings",
      "narration_synthesis",
      "product_player",
      "editor_production",
      "automatic_speaker_detection",
      "cache_cleanup",
    ]) {
      const capability = released.capabilities.items.find((entry) => entry.key === key);
      if (!capability) throw new Error(`missing capability ${key}`);
      Object.assign(capability, {
        state: "enabled",
        visible: true,
        actionable: true,
        reason_code: null,
        required_gate: null,
      });
    }
    expect(parseNarrationOverviewResponse(released).runtime.product_visible).toBe(true);

    const falseCache = structuredClone(overview);
    const nestedCleanup = falseCache.cache.cleanup_capability as {
      state: string;
      visible: boolean;
      actionable: boolean;
      reason_code: string | null;
      required_gate: string | null;
    };
    nestedCleanup.state = "enabled";
    nestedCleanup.visible = true;
    nestedCleanup.actionable = true;
    nestedCleanup.reason_code = null;
    nestedCleanup.required_gate = null;
    expect(() => parseNarrationOverviewResponse(falseCache)).toThrow(/exceeds global cache gate/);
  });

  it("freezes immutable locked voice identity and private media paths", () => {
    expect(parseVoiceProfileResource(profile()).current_version_id).toBe(VERSION_ID);

    const wrongCurrent = profile();
    wrongCurrent.current_version_id = CHARACTER_ID;
    expect(() => parseVoiceProfileResource(wrongCurrent)).toThrow(/current version/);

    const wrongParent = profile();
    wrongParent.versions[0].profile_id = CHARACTER_ID;
    expect(() => parseVoiceProfileResource(wrongParent)).toThrow(/profile mismatch/);

    const leaked = profile() as unknown as Record<string, unknown>;
    const versions = leaked.versions as Array<Record<string, unknown>>;
    versions[0].preview_asset = {
      ...mediaAsset(),
      content_path: "file:///tmp/private.wav",
    };
    expect(() => parseVoiceProfileResource(leaked)).toThrow(/asset path\/id mismatch/);

    const crossed = profile() as unknown as Record<string, unknown>;
    const crossedVersions = crossed.versions as Array<Record<string, unknown>>;
    crossedVersions[0].preview_asset = {
      ...mediaAsset(),
      content_path: `/media-assets/${CHARACTER_ID}/content`,
    };
    expect(() => parseVoiceProfileResource(crossed)).toThrow(/asset path\/id mismatch/);
  });

  it("keeps unset character bindings empty and version zero", () => {
    const unset = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      binding_id: null,
      novel_id: NOVEL_ID,
      character_id: CHARACTER_ID,
      binding_policy: "unset",
      profile_id: null,
      version_id: null,
      language: "zh-CN",
      version: 0,
      impact: {
        affected_chapter_count: 0,
        affected_segment_count: 0,
        historical_edition_count: 0,
        regeneration_required: false,
      },
      updated_at: null,
    };
    expect(parseCharacterVoiceBindingResource(unset).binding_policy).toBe("unset");
    expect(() => parseCharacterVoiceBindingResource({
      ...unset,
      profile_id: PROFILE_ID,
      version_id: VERSION_ID,
    })).toThrow(/invalid unset binding/);
    expect(() => parseCharacterVoiceBindingResource({
      ...unset,
      updated_at: NOW,
    })).toThrow(/invalid unset binding/);

    expect(parseCharacterVoiceBindingListResponse({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      novel_id: NOVEL_ID,
      items: [unset],
    }).items).toHaveLength(1);
  });

  it("validates structured casting conditions and server-owned rule identity", () => {
    const rules = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      novel_id: NOVEL_ID,
      version: 1,
      items: [{
        rule_id: ASSET_ID,
        version_number: 1,
        source: "user",
        priority: 10,
        enabled: true,
        condition: {
          speaker_kinds: ["anonymous"],
          genders: ["female"],
          age_bands: ["elderly"],
          context_kinds: ["dialogue"],
          role_tags: ["路人"],
        },
        target: {
          kind: "require_review",
          profile_id: null,
          version_id: null,
        },
      }],
    };
    expect(parseVoiceCastingRulesResource(rules).items[0].target.kind).toBe("require_review");
    const invalid = structuredClone(rules) as unknown as Record<string, unknown>;
    const invalidItems = invalid.items as Array<Record<string, unknown>>;
    const invalidTarget = invalidItems[0].target as Record<string, unknown>;
    invalidTarget.profile_id = PROFILE_ID;
    invalidTarget.version_id = VERSION_ID;
    expect(() => parseVoiceCastingRulesResource(invalid)).toThrow(/cannot carry a voice/);
  });

  it("requires structured error codes and forbids silent cache source deletion", () => {
    expect(parseNarrationApiErrorDetail({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      code: "CAPABILITY_DISABLED",
      message: "功能未开放",
      retryable: false,
      field: null,
      current_version: null,
      capability: "voice_design",
    }).capability).toBe("voice_design");

    const cleanup = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      novel_id: NOVEL_ID,
      deleted_asset_count: 1,
      reclaimed_bytes: 20,
      source_asset_deleted_count: 0,
      locked_voice_deleted_count: 0,
      referenced_asset_deleted_count: 0,
    };
    expect(parseNarrationCacheCleanupResult(cleanup).source_asset_deleted_count).toBe(0);
    expect(() => parseNarrationCacheCleanupResult({
      ...cleanup,
      source_asset_deleted_count: 1,
    })).toThrow(/expected literal 0/);
  });
});
