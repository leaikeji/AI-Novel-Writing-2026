import { describe, expect, it, vi } from "vitest";

import { NarrationApiError, createUploadedVoiceVersion } from "./api";
import {
  CAPABILITY_KEYS,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_VOICE_SCHEMA_VERSION,
} from "./contracts";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationApiErrorDetail,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationErrorCode,
  VoicePreviewResource,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceSourceAvailability,
} from "./contracts";
import {
  IDLE_VOICE_SOURCE_WORKFLOW,
  VoiceSourcePanel,
  VoiceSourcePanelActionError,
  buildAuthorizedUploadMetadata,
  classifyVoiceSourceFailure,
  createVoiceSourcePanelModel,
  pollVoicePreview,
  submitAuthorizedVoiceUpload,
} from "./voice-source-panel";
import type {
  AuthorizedVoiceUploadInput,
  VoiceSourcePanelModel,
} from "./voice-source-panel";
import {
  T2_D_NARRATION_STYLE_ID,
  T2_D_NARRATION_STYLES,
} from "./styles/t2-d";


const UUID_A = "00000000-0000-4000-8000-0000000000a1";
const UUID_B = "00000000-0000-4000-8000-0000000000b2";
const UUID_C = "00000000-0000-4000-8000-0000000000c3";
const UUID_D = "00000000-0000-4000-8000-0000000000d4";
const SHA_A = "a".repeat(64);
const NOW = "2026-08-26T08:00:00Z";


function capability(
  key: CapabilityKey,
  options: Partial<FeatureCapability> = {},
): FeatureCapability {
  return {
    key,
    state: "unavailable",
    visible: false,
    actionable: false,
    reason_code: "TEST_UNAVAILABLE",
    required_gate: "T2-D",
    ...options,
  };
}

function capabilities(
  overrides: Partial<Record<CapabilityKey, Partial<FeatureCapability>>> = {},
): NarrationCapabilities {
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map((key) => capability(key, overrides[key])),
  };
}

function authorization(
  overrides: Partial<NarrationAuthorizationState> = {},
): NarrationAuthorizationState {
  return {
    mode: "fixed_local_owner_workspace",
    can_read: true,
    can_configure: true,
    can_manage_voice_assets: true,
    can_confirm_voice_rights: true,
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
    ...overrides,
  };
}

function voiceSources(
  uploadedAvailable = false,
): readonly VoiceSourceAvailability[] {
  return [
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
      available: uploadedAvailable,
      reason_code: uploadedAvailable ? null : "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
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
  ];
}

function version(
  overrides: Partial<VoiceProfileVersionResource> = {},
): VoiceProfileVersionResource {
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: UUID_B,
    profile_id: UUID_A,
    version_number: 1,
    source_type: "uploaded",
    state: "preview_ready",
    provider_id: "moss",
    model_id: "moss-tts-nano",
    model_revision: "candidate-only",
    preset_key: null,
    language: "zh-CN",
    fingerprint: SHA_A,
    quality_state: "pending",
    activation_basis: "preview_confirmed",
    validation_basis: "pending",
    rights: {
      rights_record_id: UUID_C,
      state: "active",
      notice_version: "voice-rights/1",
      source_kind: "user_upload",
      source_identifier_sha256: SHA_A,
      purpose: "private_novel_narration",
      commercial_use: false,
      redistribution: false,
      voice_cloning: true,
      subject_consent_recorded: true,
      confirmed_at: NOW,
      expires_at: null,
      risk_flags: [],
    },
    official_preset: null,
    reference_asset_id: UUID_D,
    preview_asset: null,
    description_available: false,
    locked_at: null,
    created_at: NOW,
    ...overrides,
  };
}

function profile(
  voiceVersion = version(),
): VoiceProfileResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: UUID_A,
    novel_id: UUID_D,
    name: "林岚",
    status: "draft",
    version: 1,
    current_version_id: null,
    versions: [voiceVersion],
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
  };
}

function enabledModel(): VoiceSourcePanelModel {
  return createVoiceSourcePanelModel({
    capabilities: capabilities({
      reading_settings: {
        state: "enabled",
        visible: true,
        actionable: true,
        reason_code: null,
        required_gate: null,
      },
      voice_preview: {
        state: "enabled",
        visible: true,
        actionable: true,
        reason_code: null,
        required_gate: null,
      },
      reference_clone: {
        state: "enabled",
        visible: true,
        actionable: true,
        reason_code: null,
        required_gate: null,
      },
    }),
    authorization: authorization(),
    voiceSources: voiceSources(true),
    profile: profile(),
    selectedVersionId: UUID_B,
  });
}

function uploadInput(
  overrides: Partial<AuthorizedVoiceUploadInput> = {},
): AuthorizedVoiceUploadInput {
  return {
    profileId: UUID_A,
    expectedProfileVersion: 1,
    language: "zh-CN",
    originalFilename: "authorized.wav",
    referenceAudio: new Blob(["RIFF0000WAVEfmt "], { type: "audio/wav" }),
    rights: {
      noticeVersion: "voice-rights/1",
      sourceIdentifier: "owner-recording-2026-08",
      commercialUse: false,
      redistribution: false,
      voiceCloningConfirmed: true,
      subjectConsentReference: "consent-1",
      rightsConfirmed: true,
    },
    idempotencyKey: "upload-key-0001",
    ...overrides,
  };
}

function preview(
  status: VoicePreviewResource["status"],
  failureCode: NarrationErrorCode | null = null,
): VoicePreviewResource {
  const ready = status === "ready";
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    preview_id: UUID_D,
    profile_id: UUID_A,
    version_id: UUID_B,
    status,
    job_id: ["queued", "running"].includes(status) ? UUID_C : null,
    asset: ready ? {
      asset_id: UUID_C,
      content_path: `/media-assets/${UUID_C}/content`,
      mime_type: "audio/wav",
      byte_size: 128,
      duration_ms: 900,
      checksum_sha256: SHA_A,
    } : null,
    temporary: true,
    expires_at: ready ? "2026-08-26T09:00:00Z" : null,
    failure_code: failureCode,
  };
}

function apiError(code: NarrationErrorCode, retryable = false): NarrationApiError {
  const detail: NarrationApiErrorDetail = {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    code,
    message: "server-private-message-not-for-ui",
    retryable,
    field: null,
    current_version: null,
    capability: null,
  };
  return new NarrationApiError(409, detail);
}


describe("T2-D voice source panel", () => {
  it("keeps the retired preset source out while hidden private sources stay absent", () => {
    const model = createVoiceSourcePanelModel({
      capabilities: capabilities({
        reading_settings: {
          state: "hold",
          visible: true,
          actionable: false,
          reason_code: "T2_GATE_REQUIRED",
        },
        voice_preview: {
          state: "unavailable",
          visible: true,
          actionable: false,
          reason_code: "VOICE_SOURCE_NOT_APPROVED",
        },
        preset_voice_source: {
          state: "unavailable",
          visible: true,
          actionable: false,
          reason_code: "OFFICIAL_PRESET_RUNTIME_UNAVAILABLE",
        },
        reference_clone: {
          state: "hold",
          visible: false,
          actionable: false,
          reason_code: "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
        },
        voice_generator: {
          state: "unavailable",
          visible: false,
          actionable: false,
          reason_code: "VOICE_GENERATOR_NO_GO",
        },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(false),
      profile: null,
      selectedVersionId: null,
    });
    expect(model.visibleCards).toEqual([]);
    expect(model.cards.map((card) => card.sourceType)).toEqual(["uploaded", "generated"]);
    expect(model.actions).toEqual({
      canCreateProfile: false,
      canPreview: false,
      canLock: false,
      canConfirmRights: true,
    });
  });

  it("requires both asset management and rights-confirmation authorization", () => {
    const model = createVoiceSourcePanelModel({
      capabilities: capabilities({
        reference_clone: {
          state: "enabled",
          visible: true,
          actionable: true,
          reason_code: null,
          required_gate: null,
        },
      }),
      authorization: authorization({ can_confirm_voice_rights: false }),
      voiceSources: voiceSources(true),
      profile: profile(),
      selectedVersionId: UUID_B,
    });
    expect(model.cards.find((card) => card.sourceType === "uploaded")).toMatchObject({
      visible: true,
      enabled: false,
      reasonCode: "VOICE_RIGHTS_PERMISSION_REQUIRED",
    });
    expect(model.permissionNotice).toContain("不能确认");
    expect(model.actions.canLock).toBe(false);
  });

  it("enables preview and lock only for active rights, preview-ready source, and enabled gates", () => {
    expect(enabledModel().actions).toMatchObject({
      canCreateProfile: true,
      canPreview: true,
      canLock: true,
    });
    const revoked = createVoiceSourcePanelModel({
      capabilities: capabilities({
        reading_settings: { state: "enabled", visible: true, actionable: true, reason_code: null },
        voice_preview: { state: "enabled", visible: true, actionable: true, reason_code: null },
        reference_clone: { state: "enabled", visible: true, actionable: true, reason_code: null },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(true),
      profile: profile(version({ rights: { ...version().rights, state: "revoked" } })),
      selectedVersionId: UUID_B,
    });
    expect(revoked.actions.canPreview).toBe(false);
    expect(revoked.actions.canLock).toBe(false);
  });

  it("requires the selected source card to be visible and enabled before preview", () => {
    const hiddenSource = createVoiceSourcePanelModel({
      capabilities: capabilities({
        voice_preview: { state: "enabled", visible: true, actionable: true, reason_code: null },
        reference_clone: { state: "enabled", visible: false, actionable: true, reason_code: null },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(true),
      profile: profile(),
      selectedVersionId: UUID_B,
    });
    expect(hiddenSource.cards.find((card) => card.sourceType === "uploaded")).toMatchObject({
      visible: false,
      enabled: true,
    });
    expect(hiddenSource.actions.canPreview).toBe(false);

    const unavailableSource = createVoiceSourcePanelModel({
      capabilities: capabilities({
        voice_preview: { state: "enabled", visible: true, actionable: true, reason_code: null },
        reference_clone: { state: "enabled", visible: true, actionable: true, reason_code: null },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(false),
      profile: profile(),
      selectedVersionId: UUID_B,
    });
    expect(unavailableSource.cards.find((card) => card.sourceType === "uploaded")).toMatchObject({
      visible: true,
      enabled: false,
    });
    expect(unavailableSource.actions.canPreview).toBe(false);
  });

  it("does not select a version projected under a different profile", () => {
    const model = createVoiceSourcePanelModel({
      capabilities: capabilities({
        voice_preview: { state: "enabled", visible: true, actionable: true, reason_code: null },
        reference_clone: { state: "enabled", visible: true, actionable: true, reason_code: null },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(true),
      profile: profile(version({ profile_id: UUID_C })),
      selectedVersionId: UUID_B,
    });
    expect(model.selectedVersion).toBeNull();
    expect(model.actions.canPreview).toBe(false);
    expect(model.actions.canLock).toBe(false);
  });

  it("validates explicit rights, MIME, path, and size before hashing or calling an API", async () => {
    const hashBlob = vi.fn(async () => SHA_A);
    await expect(buildAuthorizedUploadMetadata(
      uploadInput({ rights: { ...uploadInput().rights, rightsConfirmed: false } }),
      hashBlob,
    )).rejects.toBeInstanceOf(VoiceSourcePanelActionError);
    expect(hashBlob).not.toHaveBeenCalled();
    await expect(buildAuthorizedUploadMetadata(
      uploadInput({ originalFilename: "../voice.wav" }),
      hashBlob,
    )).rejects.toMatchObject({ failure: { kind: "validation" } });
    await expect(buildAuthorizedUploadMetadata(
      uploadInput({ referenceAudio: new Blob(["mp3"], { type: "audio/mpeg" }) }),
      hashBlob,
    )).rejects.toMatchObject({ failure: { kind: "unsupported_media_type" } });
    await expect(buildAuthorizedUploadMetadata(
      uploadInput({ referenceAudio: new Blob([], { type: "audio/wav" }) }),
      hashBlob,
    )).rejects.toMatchObject({ failure: { kind: "payload_too_large" } });
    expect(hashBlob).not.toHaveBeenCalled();
    await expect(buildAuthorizedUploadMetadata(
      uploadInput(),
      async () => "not-a-sha",
    )).rejects.toMatchObject({ failure: { kind: "validation" } });
  });

  it("never calls hash or upload while the server capability is unavailable", async () => {
    const baseline = createVoiceSourcePanelModel({
      capabilities: capabilities({
        reference_clone: {
          state: "hold",
          visible: false,
          actionable: false,
          reason_code: "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
        },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(false),
      profile: profile(),
      selectedVersionId: UUID_B,
    });
    const hashBlob = vi.fn(async () => SHA_A);
    const create = vi.fn<(...args: Parameters<typeof createUploadedVoiceVersion>) => ReturnType<typeof createUploadedVoiceVersion>>();
    await expect(submitAuthorizedVoiceUpload(baseline, uploadInput(), {
      hashBlob,
      api: { createUploadedVoiceVersion: create },
    })).rejects.toMatchObject({ failure: { kind: "capability" } });
    expect(hashBlob).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects missing, switched, or stale profiles before hashing or upload", async () => {
    const missingProfileModel = createVoiceSourcePanelModel({
      capabilities: capabilities({
        reference_clone: {
          state: "enabled",
          visible: true,
          actionable: true,
          reason_code: null,
          required_gate: null,
        },
      }),
      authorization: authorization(),
      voiceSources: voiceSources(true),
      profile: null,
      selectedVersionId: null,
    });
    const cases: readonly [VoiceSourcePanelModel, AuthorizedVoiceUploadInput][] = [
      [missingProfileModel, uploadInput()],
      [enabledModel(), uploadInput({ profileId: UUID_C })],
      [enabledModel(), uploadInput({ expectedProfileVersion: 2 })],
    ];
    for (const [model, input] of cases) {
      const hashBlob = vi.fn(async () => SHA_A);
      const create = vi.fn<(...args: Parameters<typeof createUploadedVoiceVersion>) => ReturnType<typeof createUploadedVoiceVersion>>();
      await expect(submitAuthorizedVoiceUpload(model, input, {
        hashBlob,
        api: { createUploadedVoiceVersion: create },
      })).rejects.toMatchObject({ failure: { kind: "conflict" } });
      expect(hashBlob).not.toHaveBeenCalled();
      expect(create).not.toHaveBeenCalled();
    }
  });

  it("builds exact authorized metadata and delegates one bounded multipart call when enabled", async () => {
    const calls: Parameters<typeof createUploadedVoiceVersion>[] = [];
    const create = vi.fn(async (...args: Parameters<typeof createUploadedVoiceVersion>) => {
      calls.push(args);
      return version({ version_id: UUID_C, version_number: 2 });
    });
    const input = uploadInput();
    const result = await submitAuthorizedVoiceUpload(enabledModel(), input, {
      hashBlob: async () => SHA_A,
      api: { createUploadedVoiceVersion: create },
    });
    expect(result.version_id).toBe(UUID_C);
    expect(create).toHaveBeenCalledTimes(1);
    expect(calls[0][0]).toBe(UUID_A);
    expect(calls[0][1]).toEqual({
      expected_profile_version: 1,
      language: "zh-CN",
      original_filename: "authorized.wav",
      reference_sha256: SHA_A,
      rights: {
        notice_version: "voice-rights/1",
        source_identifier: "owner-recording-2026-08",
        purpose: "private_novel_narration",
        commercial_use: false,
        redistribution: false,
        voice_cloning: true,
        subject_consent_reference: "consent-1",
        confirmed: true,
      },
    });
    expect(calls[0][2]).toBe(input.referenceAudio);
    expect(calls[0][3]).toBe("upload-key-0001");
  });

  it("classifies permission, rights, format, limit, capability, conflict, storage, and abort safely", () => {
    expect(classifyVoiceSourceFailure(apiError("VOICE_RIGHTS_UNAVAILABLE"))).toMatchObject({ kind: "rights" });
    expect(classifyVoiceSourceFailure(apiError("UNSUPPORTED_MEDIA_TYPE"))).toMatchObject({ kind: "unsupported_media_type" });
    expect(classifyVoiceSourceFailure(apiError("PAYLOAD_TOO_LARGE"))).toMatchObject({ kind: "payload_too_large" });
    expect(classifyVoiceSourceFailure(apiError("VOICE_SOURCE_UNAVAILABLE"))).toMatchObject({ kind: "capability" });
    expect(classifyVoiceSourceFailure(apiError("VERSION_CONFLICT"))).toMatchObject({ kind: "conflict" });
    expect(classifyVoiceSourceFailure(apiError("DISK_SPACE_INSUFFICIENT"))).toMatchObject({ kind: "storage" });
    expect(classifyVoiceSourceFailure(apiError("SCOPE_VIOLATION"))).toMatchObject({ kind: "permission" });
    expect(classifyVoiceSourceFailure(Object.assign(new Error("private"), { name: "AbortError" }))).toEqual({
      kind: "cancelled",
      code: "CANCELLED",
      message: "操作已取消。",
      retryable: false,
    });
  });

  it("does not poll a terminal unavailable 202 resource and never exposes an asset", async () => {
    const get = vi.fn(async () => preview("ready"));
    const result = await pollVoicePreview(preview("unavailable", "PREVIEW_UNAVAILABLE"), {
      api: { getVoicePreview: get },
      delay: async () => undefined,
    });
    expect(get).not.toHaveBeenCalled();
    expect(result).toMatchObject({ status: "preview_unavailable" });
    expect(result.preview?.asset).toBeNull();
  });

  it("polls queued and running preview resources until a strict ready asset arrives", async () => {
    const states: string[] = [];
    const get = vi.fn()
      .mockResolvedValueOnce(preview("running"))
      .mockResolvedValueOnce(preview("ready"));
    const result = await pollVoicePreview(preview("queued"), {
      api: { getVoicePreview: get },
      delay: async () => undefined,
      delayMs: 100,
      maximumPolls: 4,
      onState: (state) => states.push(state.status),
    });
    expect(result.status).toBe("preview_ready");
    expect(result.preview?.asset?.content_path).toBe(`/media-assets/${UUID_C}/content`);
    expect(states).toEqual(["preview_queued", "preview_running", "preview_ready"]);
  });

  it("rejects a poll response that switches preview identity before exposing its asset", async () => {
    const switched = {
      ...preview("ready"),
      preview_id: UUID_C,
    };
    const result = await pollVoicePreview(preview("queued"), {
      api: { getVoicePreview: async () => switched },
      delay: async () => undefined,
    });
    expect(result).toMatchObject({
      status: "failed",
      failure: { kind: "validation" },
    });
    expect(result.preview?.asset).toBeNull();
  });

  it("turns cancellation into a terminal cancelled state without a server error leak", async () => {
    const controller = new AbortController();
    controller.abort();
    const get = vi.fn(async () => preview("ready"));
    const result = await pollVoicePreview(preview("queued"), {
      api: { getVoicePreview: get },
      signal: controller.signal,
      delay: async () => undefined,
    });
    expect(result).toMatchObject({
      status: "cancelled",
      failure: { code: "CANCELLED" },
    });
    expect(get).not.toHaveBeenCalled();
  });

  it("renders an accessible disabled baseline panel without hidden no-go source buttons", () => {
    interface FakeElement {
      readonly type: unknown;
      readonly props: Record<string, unknown>;
      readonly children: readonly unknown[];
    }
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "window");
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        QwenPaw: {
          host: {
            React: {
              createElement: (
                type: unknown,
                props: Record<string, unknown> | null,
                ...children: unknown[]
              ): FakeElement => ({ type, props: props ?? {}, children }),
            },
          },
        },
      },
    });
    try {
      const model = createVoiceSourcePanelModel({
        capabilities: capabilities({
          preset_voice_source: {
            state: "unavailable",
            visible: true,
            actionable: false,
            reason_code: "OFFICIAL_PRESET_RUNTIME_UNAVAILABLE",
          },
          reference_clone: {
            state: "hold",
            visible: false,
            actionable: false,
            reason_code: "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
          },
          voice_generator: {
            state: "unavailable",
            visible: false,
            actionable: false,
            reason_code: "VOICE_GENERATOR_NO_GO",
          },
        }),
        authorization: authorization(),
        voiceSources: voiceSources(false),
        profile: null,
        selectedVersionId: null,
      });
      const tree = VoiceSourcePanel({
        model,
        selectedSource: null,
        workflow: IDLE_VOICE_SOURCE_WORKFLOW,
        uploadRights: uploadInput().rights,
      }) as FakeElement;
      const serialized = JSON.stringify(tree);
      expect(tree.props["aria-labelledby"]).toBe("anw-narration-voice-source-title");
      expect(serialized).toContain("官方音色请在上方音色库直接使用");
      expect(serialized).not.toContain("系统预设");
      expect(serialized).not.toContain("上传参考录音");
      expect(serialized).not.toContain("文字描述生成");
      expect(serialized).toContain("aria-live");
    } finally {
      if (descriptor === undefined) delete (globalThis as { window?: unknown }).window;
      else Object.defineProperty(globalThis, "window", descriptor);
    }
  });

  it("exports desktop-only and keyboard-visible styles for T4 product injection", () => {
    expect(T2_D_NARRATION_STYLE_ID).toBe("anw-narration-t2-d-styles");
    expect(T2_D_NARRATION_STYLES).toContain(".anw-narration-voice-source-panel");
    expect(T2_D_NARRATION_STYLES).toContain("min-height: 44px");
    expect(T2_D_NARRATION_STYLES).toContain(":focus-visible");
    expect(T2_D_NARRATION_STYLES).toContain("minmax(0, 1fr) max-content");
    expect(T2_D_NARRATION_STYLES).toContain("minmax(0, .8fr) minmax(0, 1.2fr)");
    expect(T2_D_NARRATION_STYLES).toMatch(
      /\.anw-voice-workspace__profiles,[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/,
    );
    expect(T2_D_NARRATION_STYLES).toMatch(
      /\.anw-voice-workspace__create-row,[\s\S]*?width: 100%;[\s\S]*?min-width: 0;/,
    );
    expect(T2_D_NARRATION_STYLES).toContain(".anw-voice-workspace__field > input");
    expect(T2_D_NARRATION_STYLES).toContain("max-width: 100%");
    expect(T2_D_NARRATION_STYLES).not.toContain("minmax(420px, 1fr)");
    expect(T2_D_NARRATION_STYLES).not.toContain("@media (max-width:");
    expect(T2_D_NARRATION_STYLES).toContain("prefers-reduced-motion");
  });
});
