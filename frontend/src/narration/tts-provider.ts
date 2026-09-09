export const TTS_PROVIDER_SELECTION_SCHEMA_VERSION =
  "narration-tts-provider-selection/1" as const;

export const TTS_PROVIDER_IDS = [
  "local_qwen3_tts",
  "aliyun_qwen_audio_tts",
] as const;

export type TTSProviderId = typeof TTS_PROVIDER_IDS[number];

export const ALIYUN_TTS_MODEL_IDS = [
  "qwen-audio-3.0-tts-plus",
  "qwen-audio-3.0-tts-flash",
] as const;

export type AliyunTTSModelId = typeof ALIYUN_TTS_MODEL_IDS[number];

export const DEFAULT_TTS_PROVIDER_ID: TTSProviderId = "local_qwen3_tts";
export const DEFAULT_ALIYUN_TTS_MODEL_ID: AliyunTTSModelId =
  "qwen-audio-3.0-tts-plus";

export type TTSProviderCapability =
  | "preset_voice"
  | "reference_clone"
  | "voice_design"
  | "natural_language_instruction";

export interface TTSProviderPresentation {
  readonly providerId: TTSProviderId;
  readonly label: string;
  readonly modelLabel: string;
  readonly executionLocation: "local_device" | "aliyun_beijing";
  readonly capabilities: readonly TTSProviderCapability[];
  readonly requiresCloudTTSConsent: boolean;
  readonly meteredUsage: boolean;
  readonly privacyNotice: string;
  readonly costNotice: string;
}

export const TTS_PROVIDER_PRESENTATIONS: Readonly<Record<TTSProviderId, TTSProviderPresentation>> =
  Object.freeze({
    local_qwen3_tts: Object.freeze({
      providerId: "local_qwen3_tts",
      label: "本地 Qwen3-TTS",
      modelLabel: "Qwen3-TTS 12Hz 1.7B（按需加载）",
      executionLocation: "local_device",
      capabilities: Object.freeze([
        "preset_voice",
        "reference_clone",
        "voice_design",
        "natural_language_instruction",
      ] as const),
      requiresCloudTTSConsent: false,
      meteredUsage: false,
      privacyNotice: "文本和参考音频保留在本机处理。",
      costNotice: "不产生云端调用费用，但会占用本机内存和算力。",
    }),
    aliyun_qwen_audio_tts: Object.freeze({
      providerId: "aliyun_qwen_audio_tts",
      label: "阿里云 Qwen-Audio 3.0",
      modelLabel: "Qwen-Audio 3.0 TTS Plus / Flash",
      executionLocation: "aliyun_beijing",
      capabilities: Object.freeze([
        "preset_voice",
        "reference_clone",
        "voice_design",
        "natural_language_instruction",
      ] as const),
      requiresCloudTTSConsent: true,
      meteredUsage: true,
      privacyNotice: "合成文本及所选参考音频会发送到阿里云北京地域。",
      costNotice: "按阿里云实际调用量计费；Plus 优先质量，Flash 优先延迟。",
    }),
  });

export interface TTSProviderSelection {
  readonly schemaVersion: typeof TTS_PROVIDER_SELECTION_SCHEMA_VERSION;
  readonly providerId: TTSProviderId;
  /** Remembered cloud preference; changing it never switches Provider. */
  readonly aliyunModelId: AliyunTTSModelId;
}

export function createDefaultTTSProviderSelection(): TTSProviderSelection {
  return Object.freeze({
    schemaVersion: TTS_PROVIDER_SELECTION_SCHEMA_VERSION,
    providerId: DEFAULT_TTS_PROVIDER_ID,
    aliyunModelId: DEFAULT_ALIYUN_TTS_MODEL_ID,
  });
}

export function selectTTSProvider(
  current: TTSProviderSelection,
  providerId: TTSProviderId,
): TTSProviderSelection {
  return Object.freeze({ ...current, providerId });
}

export function selectAliyunTTSModel(
  current: TTSProviderSelection,
  aliyunModelId: AliyunTTSModelId,
): TTSProviderSelection {
  return Object.freeze({ ...current, aliyunModelId });
}

export type TTSProviderRuntimeState =
  | "disabled"
  | "starting"
  | "ready"
  | "unavailable";

export interface TTSProviderRuntimeAvailability {
  readonly state: TTSProviderRuntimeState;
  readonly reasonCode: string | null;
}

export type CloudTTSConsentState =
  | "not_granted"
  | "active"
  | "revoked"
  | "expired";

export type TTSExecutionDecision =
  | {
      readonly kind: "ready";
      readonly providerId: TTSProviderId;
      readonly modelId: "Qwen3-TTS-12Hz-1.7B" | AliyunTTSModelId;
    }
  | {
      readonly kind: "blocked";
      readonly providerId: TTSProviderId;
      readonly modelId: "Qwen3-TTS-12Hz-1.7B" | AliyunTTSModelId;
      readonly code: "SELECTED_PROVIDER_NOT_READY" | "CLOUD_TTS_CONSENT_REQUIRED";
      readonly reasonCode: string | null;
      /** Informational only. Execution never changes Provider automatically. */
      readonly manualSwitchOptions: readonly TTSProviderId[];
    };

export function resolveTTSExecutionDecision(
  selection: TTSProviderSelection,
  availability: Readonly<Record<TTSProviderId, TTSProviderRuntimeAvailability>>,
  cloudConsentState: CloudTTSConsentState,
): TTSExecutionDecision {
  const providerId = selection.providerId;
  const modelId = providerId === "local_qwen3_tts"
    ? "Qwen3-TTS-12Hz-1.7B"
    : selection.aliyunModelId;
  const selectedRuntime = availability[providerId];
  const manualSwitchOptions = TTS_PROVIDER_IDS.filter(
    (candidate) => candidate !== providerId && availability[candidate].state === "ready",
  );

  if (selectedRuntime.state !== "ready") {
    return Object.freeze({
      kind: "blocked",
      providerId,
      modelId,
      code: "SELECTED_PROVIDER_NOT_READY",
      reasonCode: selectedRuntime.reasonCode,
      manualSwitchOptions: Object.freeze(manualSwitchOptions),
    });
  }

  if (providerId === "aliyun_qwen_audio_tts" && cloudConsentState !== "active") {
    return Object.freeze({
      kind: "blocked",
      providerId,
      modelId,
      code: "CLOUD_TTS_CONSENT_REQUIRED",
      reasonCode: cloudConsentState,
      manualSwitchOptions: Object.freeze(manualSwitchOptions),
    });
  }

  return Object.freeze({ kind: "ready", providerId, modelId });
}
