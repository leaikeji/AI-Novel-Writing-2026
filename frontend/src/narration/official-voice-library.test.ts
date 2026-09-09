import { describe, expect, it } from "vitest";

import {
  OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION,
  OFFICIAL_VOICE_PRESET_IDS,
  assertOfficialVoiceSelectionResult,
  createOfficialVoiceLibraryModel,
  createOfficialVoiceSelectionRequest,
  filterOfficialVoiceLibraryGroups,
  officialVoiceCatalogFromWire,
  type OfficialVoiceSelectionResult,
} from "./official-voice-library";
import {
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  type OfficialPresetCatalogResponse,
} from "./contracts";


function wireCatalog(): OfficialPresetCatalogResponse {
  return {
    schema_version: "qwen-tts-preset-catalog/1",
    items: OFFICIAL_PRESET_EVIDENCE.map((evidence) => {
      const female = evidence.presetId === "qwen.WarmFemale";
      return {
        preset_id: evidence.presetId,
        display_name: female ? "温暖女声" : "明亮男声",
        group: female ? "中文女声" : "中文男声",
        language: "zh-CN",
        local_use_status: "available",
        commercial_distribution_status: "not_evaluated",
        validation_tier: "canonical_chapter_verified",
        language_scope: "zh-CN",
        selectable_now: true,
        previewable_now: false,
        renderable_existing: true,
        usage_notice: "private_local_writing_tool",
        provenance: {
          schema_version: "qwen-tts-preset-provenance/1",
          catalog_id: "qwen-provider-voice-map/1",
          preset_id: evidence.presetId,
          local_model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
          local_model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
          provider_voice_ids: {
            local_qwen3_tts: evidence.localVoiceId,
            "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus": evidence.aliyunPlusVoiceId,
            "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash": evidence.aliyunFlashVoiceId,
          },
          model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
          provenance_fingerprint_sha256: "a".repeat(64),
        },
      };
    }),
  };
}


describe("Qwen official voice library", () => {
  it("keeps the exact two-voice provider-aware order", () => {
    const catalog = officialVoiceCatalogFromWire(wireCatalog());
    expect(catalog.schemaVersion).toBe(OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION);
    expect(catalog.items.map((item) => item.presetId)).toEqual(OFFICIAL_VOICE_PRESET_IDS);
    expect(catalog.items[0]?.provenance.providerVoiceIds.local_qwen3_tts).toBe("Serena");
    expect(catalog.items[1]?.provenance.providerVoiceIds[
      "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"
    ]).toBe("longanlufeng");
  });

  it("builds one Chinese group and rejects reordered inventory", () => {
    const catalog = officialVoiceCatalogFromWire(wireCatalog());
    const model = createOfficialVoiceLibraryModel(catalog, "zh-CN");
    expect(model.status).toBe("ready");
    if (model.status !== "ready") throw new Error("expected ready Qwen catalog");
    expect(model.itemCount).toBe(2);
    expect(model.groups.map((group) => group.items.length)).toEqual([2]);
    const filtered = filterOfficialVoiceLibraryGroups(model.groups, "明亮", "all");
    expect(filtered[0]?.items.map((item) => item.item.presetId)).toEqual([
      "qwen.ClearMale",
    ]);

    const invalid = {
      ...catalog,
      items: [...catalog.items].reverse(),
    };
    expect(createOfficialVoiceLibraryModel(invalid, "zh-CN").status).toBe("invalid");
  });

  it("creates narrator and character requests without hidden fields", () => {
    expect(createOfficialVoiceSelectionRequest("qwen.WarmFemale", {
      kind: "narrator",
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 3,
    })).toEqual({
      presetId: "qwen.WarmFemale",
      targetKind: "narrator",
      expectedSettingsVersion: 3,
    });
    expect(createOfficialVoiceSelectionRequest("qwen.ClearMale", {
      kind: "character",
      characterId: "character-1",
      characterName: "林岚",
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 4,
      expectedBindingVersion: 2,
    })).toEqual({
      presetId: "qwen.ClearMale",
      targetKind: "character",
      characterId: "character-1",
      expectedSettingsVersion: 4,
      expectedBindingVersion: 2,
    });
  });

  it("rejects stale or identity-drifted selection receipts", () => {
    const target = {
      kind: "narrator" as const,
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 0,
    };
    const result: OfficialVoiceSelectionResult = {
      replayed: false,
      selectionStillCurrent: true,
      presetId: "qwen.WarmFemale",
      targetKind: "narrator",
      characterId: null,
      settingsVersion: 1,
      bindingVersion: null,
      languageMismatch: false,
    };
    expect(() => assertOfficialVoiceSelectionResult(
      result,
      "qwen.WarmFemale",
      target,
    )).not.toThrow();
    expect(() => assertOfficialVoiceSelectionResult(
      { ...result, selectionStillCurrent: false },
      "qwen.WarmFemale",
      target,
    )).toThrow();
    expect(() => assertOfficialVoiceSelectionResult(
      { ...result, presetId: "qwen.ClearMale" },
      "qwen.WarmFemale",
      target,
    )).toThrow();
  });
});
