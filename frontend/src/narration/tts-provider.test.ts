import { describe, expect, it } from "vitest";

import {
  DEFAULT_ALIYUN_TTS_MODEL_ID,
  DEFAULT_TTS_PROVIDER_ID,
  TTS_PROVIDER_PRESENTATIONS,
  createDefaultTTSProviderSelection,
  resolveTTSExecutionDecision,
  selectAliyunTTSModel,
  selectTTSProvider,
  type TTSProviderRuntimeAvailability,
} from "./tts-provider";

const localReady: TTSProviderRuntimeAvailability = {
  state: "ready",
  reasonCode: null,
};
const cloudReady: TTSProviderRuntimeAvailability = {
  state: "ready",
  reasonCode: null,
};

describe("TTS Provider selection", () => {
  it("defaults to local and remembers Plus as the cloud default", () => {
    const selection = createDefaultTTSProviderSelection();

    expect(selection.providerId).toBe(DEFAULT_TTS_PROVIDER_ID);
    expect(selection.providerId).toBe("local_qwen3_tts");
    expect(selection.aliyunModelId).toBe(DEFAULT_ALIYUN_TTS_MODEL_ID);
    expect(selection.aliyunModelId).toBe("qwen-audio-3.0-tts-plus");
  });

  it("switches Provider only through an explicit Provider selection", () => {
    const local = createDefaultTTSProviderSelection();
    const flashPreference = selectAliyunTTSModel(
      local,
      "qwen-audio-3.0-tts-flash",
    );

    expect(flashPreference.providerId).toBe("local_qwen3_tts");
    expect(flashPreference.aliyunModelId).toBe("qwen-audio-3.0-tts-flash");

    const cloud = selectTTSProvider(flashPreference, "aliyun_qwen_audio_tts");
    expect(cloud.providerId).toBe("aliyun_qwen_audio_tts");
    expect(cloud.aliyunModelId).toBe("qwen-audio-3.0-tts-flash");
  });

  it("does not silently fall back when the selected local Provider is unavailable", () => {
    const decision = resolveTTSExecutionDecision(
      createDefaultTTSProviderSelection(),
      {
        local_qwen3_tts: { state: "unavailable", reasonCode: "MODEL_NOT_LOADED" },
        aliyun_qwen_audio_tts: cloudReady,
      },
      "active",
    );

    expect(decision).toEqual({
      kind: "blocked",
      providerId: "local_qwen3_tts",
      modelId: "Qwen3-TTS-12Hz-1.7B",
      code: "SELECTED_PROVIDER_NOT_READY",
      reasonCode: "MODEL_NOT_LOADED",
      manualSwitchOptions: ["aliyun_qwen_audio_tts"],
    });
  });

  it.each(["not_granted", "revoked", "expired"] as const)(
    "blocks cloud execution when cloud TTS consent is %s",
    (consentState) => {
      const selection = selectTTSProvider(
        createDefaultTTSProviderSelection(),
        "aliyun_qwen_audio_tts",
      );

      const decision = resolveTTSExecutionDecision(
        selection,
        {
          local_qwen3_tts: localReady,
          aliyun_qwen_audio_tts: cloudReady,
        },
        consentState,
      );

      expect(decision.kind).toBe("blocked");
      expect(decision.providerId).toBe("aliyun_qwen_audio_tts");
      if (decision.kind === "blocked") {
        expect(decision.code).toBe("CLOUD_TTS_CONSENT_REQUIRED");
        expect(decision.manualSwitchOptions).toEqual(["local_qwen3_tts"]);
      }
    },
  );

  it("executes the explicitly selected cloud model after consent", () => {
    const selection = selectAliyunTTSModel(
      selectTTSProvider(
        createDefaultTTSProviderSelection(),
        "aliyun_qwen_audio_tts",
      ),
      "qwen-audio-3.0-tts-flash",
    );

    expect(resolveTTSExecutionDecision(
      selection,
      {
        local_qwen3_tts: localReady,
        aliyun_qwen_audio_tts: cloudReady,
      },
      "active",
    )).toEqual({
      kind: "ready",
      providerId: "aliyun_qwen_audio_tts",
      modelId: "qwen-audio-3.0-tts-flash",
    });
  });
});

describe("TTS Provider presentation", () => {
  it("makes privacy, billing, and capabilities visible for both Providers", () => {
    const local = TTS_PROVIDER_PRESENTATIONS.local_qwen3_tts;
    const cloud = TTS_PROVIDER_PRESENTATIONS.aliyun_qwen_audio_tts;

    expect(local.requiresCloudTTSConsent).toBe(false);
    expect(local.meteredUsage).toBe(false);
    expect(local.privacyNotice).toContain("本机");
    expect(local.capabilities).toEqual([
      "preset_voice",
      "reference_clone",
      "voice_design",
      "natural_language_instruction",
    ]);

    expect(cloud.requiresCloudTTSConsent).toBe(true);
    expect(cloud.meteredUsage).toBe(true);
    expect(cloud.privacyNotice).toContain("阿里云北京地域");
    expect(cloud.costNotice).toContain("Plus");
    expect(cloud.costNotice).toContain("Flash");
    expect(cloud.capabilities).toEqual([
      "preset_voice",
      "reference_clone",
      "voice_design",
      "natural_language_instruction",
    ]);
  });
});
