import { describe, expect, it } from "vitest";

import {
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type NarrationSettingsResource,
  type OfficialVoiceSelectionResponse,
  type VoiceProfileResource,
} from "./contracts";
import {
  activeOfficialPresetId,
  officialVoiceSelectionDisabled,
  officialVoiceSelectionResult,
  officialVoiceSelectionWireRequest,
} from "./official-voice-selection-panel";


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const PROFILE_ID = "22222222-2222-4222-8222-222222222222";
const VERSION_ID = "33333333-3333-4333-8333-333333333333";
const CHARACTER_ID = "44444444-4444-4444-8444-444444444444";
const COMMAND_ID = "55555555-5555-4555-8555-555555555555";
const AT = "2026-08-29T00:00:00Z";
const EVIDENCE = OFFICIAL_PRESET_EVIDENCE[0];


function settings(): NarrationSettingsResource {
  return {
    version: 3,
    values: {
      narrator: { profile_id: PROFILE_ID, version_id: VERSION_ID },
      language: "zh-CN",
    },
  } as unknown as NarrationSettingsResource;
}


function officialProfile(
  activation: "preview_confirmed" | "explicit_official_preset_selection",
): VoiceProfileResource {
  const direct = activation === "explicit_official_preset_selection";
  return {
    profile_id: PROFILE_ID,
    versions: [{
      schema_version: NARRATION_VOICE_SCHEMA_VERSION,
      version_id: VERSION_ID,
      profile_id: PROFILE_ID,
      version_number: 1,
      source_type: "preset",
      state: "locked",
      provider_id: "moss-tts-nano-onnx",
      model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
      model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
      preset_key: EVIDENCE.presetId,
      language: "zh-CN",
      fingerprint: "a".repeat(64),
      quality_state: direct ? "pending" : "accepted",
      activation_basis: activation,
      validation_basis: direct ? "not_required" : "human_accepted",
      rights: {
        state: "active",
        source_kind: "official_preset",
      },
      official_preset: {
        schema_version: "moss-tts-official-preset-provenance/1.0",
        repository: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
        revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
        manifest_path: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
        manifest_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestSha256,
        preset_id: EVIDENCE.presetId,
        manifest_voice: EVIDENCE.manifestVoice,
        prompt_codes_sha256: EVIDENCE.promptCodesSha256,
        prompt_frame_count: EVIDENCE.promptFrameCount,
        prompt_quantizer_count: EVIDENCE.promptQuantizerCount,
        model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
        provenance_fingerprint_sha256: EVIDENCE.provenanceFingerprintSha256,
      },
    }],
  } as unknown as VoiceProfileResource;
}


describe("official voice selection panel adapters", () => {
  it("maps narrator and character commands to the exact snake-case CAS request", () => {
    expect(officialVoiceSelectionWireRequest({
      presetId: EVIDENCE.presetId,
      targetKind: "narrator",
      expectedSettingsVersion: 3,
    })).toEqual({
      preset_id: EVIDENCE.presetId,
      target_kind: "narrator",
      character_id: null,
      expected_settings_version: 3,
      expected_binding_version: null,
    });
    expect(officialVoiceSelectionWireRequest({
      presetId: EVIDENCE.presetId,
      targetKind: "character",
      characterId: CHARACTER_ID,
      expectedSettingsVersion: 3,
      expectedBindingVersion: 7,
    })).toEqual({
      preset_id: EVIDENCE.presetId,
      target_kind: "character",
      character_id: CHARACTER_ID,
      expected_settings_version: 3,
      expected_binding_version: 7,
    });
  });

  it("preserves frozen result identity separately from current projections", () => {
    const response = {
      replayed: true,
      selection_still_current: false,
      frozen_result: {
        command_id: COMMAND_ID,
        preset_id: EVIDENCE.presetId,
        target_kind: "character",
        character_id: CHARACTER_ID,
        profile_id: PROFILE_ID,
        version_id: VERSION_ID,
        settings_version: 3,
        binding_version: 8,
        target_language: "zh-CN",
        language_mismatch: false,
        completed_at: AT,
      },
    } as unknown as OfficialVoiceSelectionResponse;
    expect(officialVoiceSelectionResult(response)).toEqual({
      replayed: true,
      selectionStillCurrent: false,
      presetId: EVIDENCE.presetId,
      targetKind: "character",
      characterId: CHARACTER_ID,
      settingsVersion: 3,
      bindingVersion: 8,
      languageMismatch: false,
    });
  });

  it("recognizes both direct and legacy human-confirmed official bindings, but no draft", () => {
    expect(activeOfficialPresetId(settings(), null, { kind: "narrator" }, [
      officialProfile("explicit_official_preset_selection"),
    ])).toBe(EVIDENCE.presetId);
    expect(activeOfficialPresetId(settings(), null, { kind: "narrator" }, [
      officialProfile("preview_confirmed"),
    ])).toBe(EVIDENCE.presetId);
    const draft = officialProfile("explicit_official_preset_selection");
    const changed = {
      ...draft,
      versions: [{ ...draft.versions[0]!, state: "draft" as const }],
    };
    expect(activeOfficialPresetId(settings(), null, { kind: "narrator" }, [changed]))
      .toBeNull();
  });

  it("blocks mutation unless owner permissions and all three narrow capabilities are actionable", () => {
    const capabilities = {
      items: ["narration_product", "reading_settings", "preset_voice_source"].map((key) => ({
        key,
        state: "enabled",
        visible: true,
        actionable: true,
      })),
    } as unknown as NarrationCapabilities;
    const authorization = {
      can_read: true,
      can_configure: true,
      can_manage_voice_assets: true,
    } as unknown as NarrationAuthorizationState;
    expect(officialVoiceSelectionDisabled(capabilities, authorization)).toBe(false);
    expect(officialVoiceSelectionDisabled(capabilities, {
      ...authorization,
      can_configure: false,
    })).toBe(true);
  });
});
