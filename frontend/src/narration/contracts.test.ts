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
  PRODUCT_OFFICIAL_PRESET_EVIDENCE,
  PRODUCT_OFFICIAL_PRESET_IDS,
  T4_PRODUCT_CAPABILITY_KEYS,
  NarrationContractError,
  parseOfficialPresetCatalogResponse,
  parseCharacterVoiceBindingListResponse,
  parseCharacterVoiceBindingResource,
  parseNarrationApiErrorDetail,
  parseNarrationCacheCleanupResult,
  parseNarrationOverviewResponse,
  parseNarrationScopeOverrideListResponse,
  parseNarrationSettingsResource,
  parseVoicePreviewResource,
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
  evidenceRows: readonly (typeof OFFICIAL_PRESET_EVIDENCE)[number][] = PRODUCT_OFFICIAL_PRESET_EVIDENCE,
) {
  return {
    schema_version: "moss-tts-official-preset-catalog/1.0",
    items: evidenceRows.map((evidence) => {
      return {
        preset_id: evidence.presetId,
        display_name: evidence.manifestVoice,
        group: "Official",
        language: "zh-CN",
        local_use_status: "available",
        commercial_distribution_status: "not_evaluated",
        provenance: {
          schema_version: "moss-tts-official-preset-provenance/1.0",
          repository: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
          revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
          manifest_path: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
          manifest_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestSha256,
          preset_id: evidence.presetId,
          manifest_voice: evidence.manifestVoice,
          prompt_codes_sha256: evidence.promptCodesSha256,
          prompt_frame_count: evidence.promptFrameCount,
          prompt_quantizer_count: evidence.promptQuantizerCount,
          model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
          provenance_fingerprint_sha256: evidence.provenanceFingerprintSha256,
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
    voice_generator: "VOICE_GENERATOR_NO_GO",
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
        "automatic_generic_casting",
        "automatic_speaker_detection",
        "voice_generator",
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
    provider_id: "moss-nano",
    model_id: "MOSS-TTS-Nano-100M-ONNX",
    model_revision: "frozen-revision",
    preset_key: null,
    language: "zh-CN",
    fingerprint: "c".repeat(64),
    quality_state: "accepted",
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
  it("accepts exactly the six product presets and rejects outer catalog drift", () => {
    const parsed = parseOfficialPresetCatalogResponse(officialCatalog());
    expect(parsed.items).toHaveLength(6);
    expect(parsed.items.map((item) => item.preset_id)).toEqual(PRODUCT_OFFICIAL_PRESET_IDS);
    expect(parsed.items.map((item) => item.preset_id)).toContain("onnx.Xiaoyu");
    expect(parsed.items.map((item) => item.preset_id)).not.toContain("onnx.Trump");
    expect(OFFICIAL_PRESET_IDS).toHaveLength(18);
    expect(OFFICIAL_PRESET_IDS).toContain("onnx.Trump");
    expect(parsed.items.every((item) => item.local_use_status === "available")).toBe(true);
    expect(parsed.items.every((item) => item.commercial_distribution_status === "not_evaluated")).toBe(true);

    const incomplete = officialCatalog();
    incomplete.items.pop();
    expect(() => parseOfficialPresetCatalogResponse(incomplete)).toThrow(/exact 6-item/);

    expect(() => parseOfficialPresetCatalogResponse(
      officialCatalog(OFFICIAL_PRESET_EVIDENCE),
    )).toThrow(/exact 6-item/);

    const leakedCodes = officialCatalog();
    Object.assign(leakedCodes.items[0].provenance, { prompt_audio_codes: [[1, 2]] });
    expect(() => parseOfficialPresetCatalogResponse(leakedCodes)).toThrow(/expected exact keys/);

    const replaced = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{
        preset_id: string;
        provenance: { preset_id: string; manifest_voice: string };
      }>;
    };
    replaced.items[3]!.preset_id = "onnx.FilteredReplacement";
    replaced.items[3]!.provenance.preset_id = "onnx.FilteredReplacement";
    replaced.items[3]!.provenance.manifest_voice = "FilteredReplacement";
    expect(() => parseOfficialPresetCatalogResponse(replaced)).toThrow(/pinned catalog order/);

    const wrongManifest = JSON.parse(JSON.stringify(officialCatalog())) as {
      items: Array<{ provenance: { manifest_sha256: string } }>;
    };
    for (const item of wrongManifest.items) item.provenance.manifest_sha256 = "9".repeat(64);
    expect(() => parseOfficialPresetCatalogResponse(wrongManifest)).toThrow(/pinned evidence/);

    const wrongOrder = officialCatalog();
    [wrongOrder.items[0], wrongOrder.items[1]] = [wrongOrder.items[1]!, wrongOrder.items[0]!];
    expect(() => parseOfficialPresetCatalogResponse(wrongOrder)).toThrow(/pinned catalog order/);

    const evidenceFields = [
      "prompt_codes_sha256",
      "prompt_frame_count",
      "prompt_quantizer_count",
      "model_fingerprint_sha256",
      "provenance_fingerprint_sha256",
    ] as const;
    for (const field of evidenceFields) {
      const drifted = JSON.parse(JSON.stringify(officialCatalog())) as {
        items: Array<{ provenance: Record<string, unknown> }>;
      };
      drifted.items[3]!.provenance[field] = field.includes("count") ? 999 : "8".repeat(64);
      expect(() => parseOfficialPresetCatalogResponse(drifted), field).toThrow(/pinned evidence/);
    }

    for (const [field, value] of [
      ["repository", "Wrong/Repository"],
      ["revision", "9".repeat(40)],
      ["manifest_path", "wrong_manifest.json"],
    ] as const) {
      const drifted = JSON.parse(JSON.stringify(officialCatalog())) as {
        items: Array<{ provenance: Record<string, unknown> }>;
      };
      drifted.items[4]!.provenance[field] = value;
      expect(() => parseOfficialPresetCatalogResponse(drifted), field).toThrow(/pinned evidence/);
    }

    const xiaoyu = parsed.items.find((item) => item.preset_id === "onnx.Xiaoyu")!;
    expect(xiaoyu.preset_id).toBe("onnx.Xiaoyu");
    for (const preset of parsed.items) {
      expect(voiceSourceEvidenceIsUsable({
        ...lockedVersion(),
        source_type: "preset",
        state: "locked" as const,
        quality_state: "accepted" as const,
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
      preset_key: xiaoyu.preset_id,
      rights: {
        ...rights(),
        state: "active" as const,
        source_kind: "official_preset" as const,
        purpose: "private_novel_narration" as const,
      },
      official_preset: { ...xiaoyu.provenance, prompt_frame_count: 999 },
      reference_asset_id: null,
    })).toBe(false);
  });
  it("accepts exact default settings and rejects response drift", () => {
    expect(parseNarrationSettingsResource(settingsResource()).version).toBe(0);
    expect(() => parseNarrationSettingsResource({
      ...settingsResource(),
      owner_id: "client-must-not-see-this",
    })).toThrow(NarrationContractError);
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
        sidecar_reachable: false,
        model_ready: false,
        product_visible: false,
        protocol_version: "moss-tts-sidecar/1.1",
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
          capability: "voice_generator",
          available: false,
          reason_code: "VOICE_GENERATOR_NO_GO",
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
      sidecar_reachable: boolean;
      model_ready: boolean;
      product_visible: boolean;
      model_fingerprint_sha256: string | null;
      reason_code: string | null;
    };
    runtime.technical_enabled = true;
    runtime.lifecycle_status = "ready";
    runtime.sidecar_reachable = true;
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

  it("publishes preview audio only in ready state", () => {
    const ready = {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      preview_id: CHARACTER_ID,
      profile_id: PROFILE_ID,
      version_id: VERSION_ID,
      status: "ready",
      job_id: null,
      asset: mediaAsset(),
      temporary: true,
      expires_at: "2026-08-26T12:10:00Z",
      failure_code: null,
    };
    expect(parseVoicePreviewResource(ready).temporary).toBe(true);
    expect(() => parseVoicePreviewResource({ ...ready, status: "running" })).toThrow(/non-ready preview/);
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
          pool_id: null,
          slot_key: null,
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
      capability: "voice_generator",
    }).capability).toBe("voice_generator");

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
