import { describe, expect, it, vi } from "vitest";

import {
  CAPABILITY_KEYS,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  PRODUCT_OFFICIAL_PRESET_EVIDENCE,
  PRODUCT_OFFICIAL_PRESET_IDS,
  type FeatureCapability,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type OfficialPresetCatalogItem,
  type OfficialPresetCatalogResponse,
  type VoicePreviewResource,
  type VoiceProfileResource,
  type VoiceProfileVersionResource,
  type VoiceSourceAvailability,
} from "./contracts";
import { VoiceSourcePanel } from "./voice-source-panel";
import {
  createVoiceSourceWorkspace,
  novelScopedVoiceProfiles,
  type VoiceSourceWorkspaceApi,
  type VoiceSourceWorkspaceReactRuntime,
} from "./voice-source-workspace";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  dependencies: readonly unknown[];
  cleanup?: () => void;
}


function isElement(value: unknown): value is FakeElement {
  return value !== null && typeof value === "object" && "type" in value && "props" in value;
}


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function sameDependencies(left: readonly unknown[] | undefined, right: readonly unknown[]): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pending: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const React: VoiceSourceWorkspaceReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      return [states[index] as T, (next: T | ((current: T) => T)) => {
        states[index] = typeof next === "function"
          ? (next as (current: T) => T)(states[index] as T)
          : next;
      }];
    },
    useRef<T>(initial: T) {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies) {
      const index = effectIndex++;
      if (!sameDependencies(effects[index]?.dependencies, dependencies)) {
        pending.push({ index, effect, dependencies: [...dependencies] });
      }
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pending = [];
      const tree = Component(props) as FakeElement;
      const current = pending;
      pending = [];
      for (const item of current) {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      }
      return tree;
    },
  };
}


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_NOVEL_ID = "21111111-1111-4111-8111-111111111111";
const PROFILE_ID = "31111111-1111-4111-8111-111111111111";
const VERSION_ID = "41111111-1111-4111-8111-111111111111";
const PREVIEW_ID = "51111111-1111-4111-8111-111111111111";
const JOB_ID = "61111111-1111-4111-8111-111111111111";
const ASSET_ID = "71111111-1111-4111-8111-111111111111";
const NOW = "2026-08-27T08:00:00Z";


function officialPresetItem(
  evidence: typeof OFFICIAL_PRESET_EVIDENCE[number],
): OfficialPresetCatalogItem {
  const manifestVoice = evidence.manifestVoice;
  return {
    preset_id: evidence.presetId,
    display_name: manifestVoice === "Xiaoyu" ? "CN 明星" : manifestVoice === "Trump" ? "EN Trump" : manifestVoice,
    group: ["Trump", "Adam", "Nathan"].includes(manifestVoice) ? "English Male" : "Chinese Female",
    language: ["Trump", "Ava", "Bella", "Adam", "Nathan"].includes(manifestVoice) ? "en" : "zh-CN",
    local_use_status: "available",
    commercial_distribution_status: "not_evaluated",
    provenance: {
      schema_version: "moss-tts-official-preset-provenance/1.0",
      repository: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
      revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
      manifest_path: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
      manifest_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestSha256,
      preset_id: evidence.presetId,
      manifest_voice: manifestVoice,
      prompt_codes_sha256: evidence.promptCodesSha256,
      prompt_frame_count: evidence.promptFrameCount,
      prompt_quantizer_count: evidence.promptQuantizerCount,
      model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
      provenance_fingerprint_sha256: evidence.provenanceFingerprintSha256,
    },
  };
}


const officialPresetCatalog: OfficialPresetCatalogResponse = {
  schema_version: "moss-tts-official-preset-catalog/1.0",
  items: PRODUCT_OFFICIAL_PRESET_EVIDENCE.map(officialPresetItem),
};


function capability(key: FeatureCapability["key"]): FeatureCapability {
  if (["narration_product", "reading_settings", "reference_clone", "voice_preview"].includes(key)) {
    return { key, state: "enabled", visible: true, actionable: true, reason_code: null, required_gate: null };
  }
  if (key === "preset_voice_source") {
    return { key, state: "hold", visible: true, actionable: false, reason_code: "OFFICIAL_PRESET_RUNTIME_UNAVAILABLE", required_gate: "T5-GATE" };
  }
  if (key === "voice_generator") {
    return { key, state: "unavailable", visible: false, actionable: false, reason_code: "VOICE_GENERATOR_NO_GO", required_gate: "T5-GATE" };
  }
  return { key, state: "hold", visible: false, actionable: false, reason_code: "NOT_IN_T4_VOICE_SCOPE", required_gate: "T5-GATE" };
}


const capabilities: NarrationCapabilities = {
  schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
  items: CAPABILITY_KEYS.map(capability),
};


const authorization: NarrationAuthorizationState = {
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
};


const voiceSources: readonly VoiceSourceAvailability[] = [
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
    available: true,
    reason_code: null,
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


const officialCapabilities: NarrationCapabilities = {
  ...capabilities,
  items: capabilities.items.map((item) => item.key === "preset_voice_source"
    ? { ...item, state: "enabled", actionable: true, reason_code: null, required_gate: null }
    : item),
};


const officialVoiceSources: readonly VoiceSourceAvailability[] = voiceSources.map((source) => (
  source.source_type === "preset"
    ? { ...source, available: true, reason_code: null }
    : source
));


function rights() {
  return {
    rights_record_id: "81111111-1111-4111-8111-111111111111",
    state: "active" as const,
    notice_version: "voice-rights/1",
    source_kind: "user_upload" as const,
    source_identifier_sha256: "a".repeat(64),
    purpose: "private_novel_narration" as const,
    commercial_use: false,
    redistribution: false,
    voice_cloning: true,
    subject_consent_recorded: true,
    confirmed_at: NOW,
    expires_at: null,
    risk_flags: [],
  };
}


function version(
  state: VoiceProfileVersionResource["state"] = "draft",
): VoiceProfileVersionResource {
  const locked = state === "locked";
  const previewReady = state === "preview_ready" || locked;
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: VERSION_ID,
    profile_id: PROFILE_ID,
    version_number: 1,
    source_type: "uploaded",
    state,
    provider_id: previewReady ? "openmoss" : null,
    model_id: previewReady ? "MOSS-TTS-Nano" : null,
    model_revision: previewReady ? "rev-1" : null,
    preset_key: null,
    language: "zh-CN",
    fingerprint: "b".repeat(64),
    quality_state: locked ? "accepted" : "pending",
    rights: rights(),
    official_preset: null,
    reference_asset_id: ASSET_ID,
    preview_asset: previewReady ? {
      asset_id: ASSET_ID,
      content_path: `/media-assets/${ASSET_ID}/content`,
      mime_type: "audio/wav",
      byte_size: 4,
      duration_ms: 800,
      checksum_sha256: "c".repeat(64),
    } : null,
    description_available: false,
    locked_at: locked ? NOW : null,
    created_at: NOW,
  };
}


function officialVersion(
  state: VoiceProfileVersionResource["state"] = "draft",
  preset = officialPresetCatalog.items[0],
): VoiceProfileVersionResource {
  const locked = state === "locked";
  const previewReady = state === "preview_ready" || locked;
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: VERSION_ID,
    profile_id: PROFILE_ID,
    version_number: 1,
    source_type: "preset",
    state,
    provider_id: "moss-tts-nano-onnx",
    model_id: preset.provenance.repository,
    model_revision: preset.provenance.revision,
    preset_key: preset.preset_id,
    language: preset.language,
    fingerprint: "b".repeat(64),
    quality_state: locked ? "accepted" : "pending",
    rights: {
      ...rights(),
      notice_version: "official-preset-local-use/1",
      source_kind: "official_preset",
      voice_cloning: false,
      subject_consent_recorded: false,
    },
    official_preset: preset.provenance,
    reference_asset_id: null,
    preview_asset: previewReady ? {
      asset_id: ASSET_ID,
      content_path: `/media-assets/${ASSET_ID}/content`,
      mime_type: "audio/wav",
      byte_size: 4,
      duration_ms: 800,
      checksum_sha256: "c".repeat(64),
    } : null,
    description_available: false,
    locked_at: locked ? NOW : null,
    created_at: NOW,
  };
}


function profile(
  profileVersion = 1,
  voiceVersion?: VoiceProfileVersionResource,
): VoiceProfileResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: PROFILE_ID,
    novel_id: NOVEL_ID,
    name: "林夏专属声音",
    status: voiceVersion?.state === "locked" ? "active" : "draft",
    version: profileVersion,
    current_version_id: voiceVersion?.state === "locked" ? VERSION_ID : null,
    versions: voiceVersion ? [voiceVersion] : [],
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
  };
}


function preview(status: VoicePreviewResource["status"]): VoicePreviewResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    preview_id: PREVIEW_ID,
    profile_id: PROFILE_ID,
    version_id: VERSION_ID,
    status,
    job_id: ["queued", "running"].includes(status) ? JOB_ID : null,
    asset: status === "ready" ? {
      asset_id: ASSET_ID,
      content_path: `/media-assets/${ASSET_ID}/content`,
      mime_type: "audio/wav",
      byte_size: 4,
      duration_ms: 800,
      checksum_sha256: "c".repeat(64),
    } : null,
    temporary: true,
    expires_at: status === "ready" ? "2026-08-27T10:00:00Z" : null,
    failure_code: null,
  };
}


async function settle(): Promise<void> {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}


function sourcePanel(tree: FakeElement): FakeElement {
  const panel = findAll(tree, (element) => element.type === VoiceSourcePanel)[0];
  if (!panel) throw new Error("VoiceSourcePanel not found");
  return panel;
}


describe("voice source workspace", () => {
  it("rejects cross-novel profile drift", () => {
    expect(() => novelScopedVoiceProfiles(NOVEL_ID, [{ ...profile(), novel_id: OTHER_NOVEL_ID }]))
      .toThrow("范围之外");
  });

  it("runs create → explicit uploaded source → rights upload → poll/get → quality confirm → lock", async () => {
    const empty = { contract_version: NARRATION_SETTINGS_API_VERSION, items: [] } as const;
    const uploaded = profile(2, version("draft"));
    const previewReady = profile(3, version("preview_ready"));
    const locked = profile(4, version("locked"));
    const api: VoiceSourceWorkspaceApi = {
      listVoiceProfiles: vi.fn(async () => empty),
      listOfficialVoicePresets: vi.fn(async () => officialPresetCatalog),
      createVoiceProfile: vi.fn(async () => profile()),
      getVoiceProfile: vi.fn()
        .mockResolvedValueOnce(uploaded)
        .mockResolvedValueOnce(previewReady)
        .mockResolvedValueOnce(locked),
      createUploadedVoiceVersion: vi.fn(async () => version("draft")),
      createPresetVoiceVersion: vi.fn(async () => officialVersion("draft")),
      createVoicePreview: vi.fn(async () => preview("queued")),
      getVoicePreview: vi.fn()
        .mockResolvedValueOnce(preview("running"))
        .mockResolvedValueOnce(preview("ready")),
      lockVoiceProfile: vi.fn(async () => locked),
    };
    const onProfileLocked = vi.fn();
    const harness = createHarness();
    const Workspace = createVoiceSourceWorkspace(harness.React, api, {
      delay: async () => undefined,
      delayMs: 100,
      maximumPolls: 4,
      hashBlob: async () => "d".repeat(64),
    });
    const props = {
      novelId: NOVEL_ID,
      capabilities,
      authorization,
      voiceSources,
      suggestedProfileName: "林夏专属声音",
      onProfileLocked,
    };

    let tree = harness.render(Workspace, props);
    await settle();
    tree = harness.render(Workspace, props);
    const createButton = findAll(tree, (element) => (
      element.type === "button" && textContent(element) === "创建作品音色档案"
    ))[0];
    (createButton.props.onClick as () => void)();
    await settle();
    tree = harness.render(Workspace, props);
    expect(api.createVoiceProfile).toHaveBeenCalledWith(
      { novel_id: NOVEL_ID, name: "林夏专属声音" },
      expect.stringMatching(/^voice-profile-/),
      expect.any(AbortSignal),
    );
    expect(textContent(tree)).toContain("下一步选择官方预设或上传有权使用的参考录音");

    let panel = sourcePanel(tree);
    expect(panel.props.selectedSource).toBeNull();
    (panel.props.onSelectSource as (source: string) => void)("uploaded");
    tree = harness.render(Workspace, props);
    panel = sourcePanel(tree);
    const reference = Object.assign(
      new Blob(["WAVE"], { type: "audio/wav" }),
      { name: "authorized.wav", lastModified: 1 },
    ) as File;
    (panel.props.onReferenceAudioChange as (file: File) => void)(reference);
    (panel.props.onUploadRightsChange as (patch: Record<string, unknown>) => void)({
      sourceIdentifier: "owner-recording-2026-08",
      subjectConsentReference: "consent-record-1",
      commercialUse: false,
      redistribution: false,
      voiceCloningConfirmed: true,
      rightsConfirmed: true,
    });
    tree = harness.render(Workspace, props);
    panel = sourcePanel(tree);
    (panel.props.onUpload as () => void)();
    await settle();
    tree = harness.render(Workspace, props);
    expect(api.createUploadedVoiceVersion).toHaveBeenCalledTimes(1);
    expect(textContent(tree)).toContain("候选音色版本已上传");

    panel = sourcePanel(tree);
    (panel.props.onPreview as () => void)();
    await settle();
    await settle();
    tree = harness.render(Workspace, props);
    expect(api.createVoicePreview).toHaveBeenCalledWith(
      PROFILE_ID,
      { version_id: VERSION_ID, preview_text: "你好，这是当前音色的朗读试听。" },
      expect.stringMatching(/^voice-preview-/),
      expect.any(AbortSignal),
    );
    expect(api.getVoicePreview).toHaveBeenCalledTimes(2);
    expect(textContent(tree)).toContain("请播放检查后显式确认质量");

    panel = sourcePanel(tree);
    expect(panel.props.qualityConfirmed).toBe(false);
    expect(panel.props.qualityConfirmationAllowed).toBe(false);
    const playback = findAll(tree, (element) => (
      typeof element.props.onPlayed === "function" && "preview" in element.props
    ))[0];
    (playback.props.onPlayed as () => void)();
    tree = harness.render(Workspace, props);
    panel = sourcePanel(tree);
    expect(panel.props.qualityConfirmationAllowed).toBe(true);
    (panel.props.onQualityConfirmationChange as (confirmed: boolean) => void)(true);
    tree = harness.render(Workspace, props);
    panel = sourcePanel(tree);
    expect(panel.props.qualityConfirmed).toBe(true);
    (panel.props.onLock as () => void)();
    await settle();
    tree = harness.render(Workspace, props);
    expect(api.lockVoiceProfile).toHaveBeenCalledWith(
      PROFILE_ID,
      {
        expected_profile_version: 3,
        version_id: VERSION_ID,
        quality_confirmed: true,
      },
      expect.any(AbortSignal),
    );
    expect(onProfileLocked).toHaveBeenCalledWith(locked);
    expect(textContent(tree)).toContain("旁白和人物绑定尚未改变");
  });

  it("shows exactly the six Chinese product presets and creates an exact preset candidate", async () => {
    const draft = profile();
    const created = officialVersion("draft", officialPresetCatalog.items[3]);
    const withPreset = profile(2, created);
    const api: VoiceSourceWorkspaceApi = {
      listVoiceProfiles: vi.fn(async () => ({ contract_version: NARRATION_SETTINGS_API_VERSION, items: [draft] })),
      listOfficialVoicePresets: vi.fn(async () => officialPresetCatalog),
      createVoiceProfile: vi.fn(),
      getVoiceProfile: vi.fn(async () => withPreset),
      createUploadedVoiceVersion: vi.fn(),
      createPresetVoiceVersion: vi.fn(async () => created),
      createVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
      lockVoiceProfile: vi.fn(),
    };
    const harness = createHarness();
    const Workspace = createVoiceSourceWorkspace(harness.React, api);
    const props = {
      novelId: NOVEL_ID,
      capabilities: officialCapabilities,
      authorization,
      voiceSources: officialVoiceSources,
    };
    let tree = harness.render(Workspace, props);
    await settle();
    tree = harness.render(Workspace, props);
    let panel = sourcePanel(tree);
    (panel.props.onSelectSource as (source: string) => void)("preset");
    tree = harness.render(Workspace, props);

    expect(textContent(tree)).toContain("当前 6 项中文官方预设均会如实展示");
    expect(textContent(tree)).not.toContain("onnx.Trump");
    expect(textContent(tree)).toContain("onnx.Xiaoyu · CN 明星");
    expect(textContent(tree)).toContain("官方中文预设（6 项）");
    expect(textContent(tree)).toContain("当前产品目录固定为官方 manifest 中的 6 个中文预设");
    expect(textContent(tree)).not.toContain("18 项");
    expect(textContent(tree)).not.toContain("18 个预设");
    expect(textContent(tree)).toContain("商业发布／再分发尚未评估，但不影响本机个人使用");
    const presetOptions = findAll(tree, (element) => (
      element.type === "option"
      && typeof element.props.value === "string"
      && (element.props.value as string).startsWith("onnx.")
    ));
    expect(presetOptions).toHaveLength(6);
    expect(presetOptions.map((option) => option.props.value)).toEqual(
      PRODUCT_OFFICIAL_PRESET_IDS,
    );
    const presetSelect = findAll(tree, (element) => (
      element.type === "select" && element.props.value === "onnx.Junhao"
    ))[0];
    (presetSelect.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "onnx.Xiaoyu" },
    });
    tree = harness.render(Workspace, props);
    const createPreset = findAll(tree, (element) => (
      element.type === "button" && textContent(element) === "创建官方预设候选版本"
    ))[0];
    (createPreset.props.onClick as () => void)();
    await settle();
    tree = harness.render(Workspace, props);

    expect(api.createPresetVoiceVersion).toHaveBeenCalledWith(
      PROFILE_ID,
      { expected_profile_version: 1, preset_id: "onnx.Xiaoyu" },
      expect.stringMatching(/^voice-preset-/),
      expect.any(AbortSignal),
    );
    expect(textContent(tree)).toContain("官方预设候选版本已创建");
    panel = sourcePanel(tree);
    expect((panel.props.model as { actions: { canPreview: boolean } }).actions.canPreview).toBe(true);
  });

  it("returns a resumable timeout with the last preview identity", async () => {
    const uploaded = profile(2, version("draft"));
    const api: VoiceSourceWorkspaceApi = {
      listVoiceProfiles: vi.fn(async () => ({ contract_version: NARRATION_SETTINGS_API_VERSION, items: [uploaded] })),
      listOfficialVoicePresets: vi.fn(async () => officialPresetCatalog),
      createVoiceProfile: vi.fn(),
      getVoiceProfile: vi.fn(async () => uploaded),
      createUploadedVoiceVersion: vi.fn(),
      createPresetVoiceVersion: vi.fn(),
      createVoicePreview: vi.fn(async () => preview("queued")),
      getVoicePreview: vi.fn(async () => preview("running")),
      lockVoiceProfile: vi.fn(),
    };
    const harness = createHarness();
    const Workspace = createVoiceSourceWorkspace(harness.React, api, {
      delay: async () => undefined,
      maximumPolls: 1,
    });
    const props = { novelId: NOVEL_ID, capabilities, authorization, voiceSources };
    let tree = harness.render(Workspace, props);
    await settle();
    tree = harness.render(Workspace, props);
    const panel = sourcePanel(tree);
    (panel.props.onSelectSource as (source: string) => void)("uploaded");
    tree = harness.render(Workspace, props);
    (sourcePanel(tree).props.onPreview as () => void)();
    await settle();
    tree = harness.render(Workspace, props);
    expect(tree.props["data-voice-workspace-phase"]).toBe("error");
    expect(textContent(tree)).toContain("继续等待试听");
    expect(findAll(tree, (element) => textContent(element) === "继续等待试听")).not.toHaveLength(0);
  });

  it("replays a lost upload once with the exact same idempotency key", async () => {
    const draft = profile();
    const upload = vi.fn().mockRejectedValue(new Error("connection lost after send"));
    const api: VoiceSourceWorkspaceApi = {
      listVoiceProfiles: vi.fn(async () => ({ contract_version: NARRATION_SETTINGS_API_VERSION, items: [draft] })),
      listOfficialVoicePresets: vi.fn(async () => officialPresetCatalog),
      createVoiceProfile: vi.fn(),
      getVoiceProfile: vi.fn(async () => draft),
      createUploadedVoiceVersion: upload,
      createPresetVoiceVersion: vi.fn(),
      createVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
      lockVoiceProfile: vi.fn(),
    };
    const harness = createHarness();
    const Workspace = createVoiceSourceWorkspace(harness.React, api, {
      hashBlob: async () => "d".repeat(64),
    });
    const props = { novelId: NOVEL_ID, capabilities, authorization, voiceSources };
    let tree = harness.render(Workspace, props);
    await settle();
    tree = harness.render(Workspace, props);
    (sourcePanel(tree).props.onSelectSource as (source: string) => void)("uploaded");
    tree = harness.render(Workspace, props);
    const reference = Object.assign(
      new Blob(["WAVE"], { type: "audio/wav" }),
      { name: "authorized.wav", lastModified: 1 },
    ) as File;
    (sourcePanel(tree).props.onReferenceAudioChange as (file: File) => void)(reference);
    (sourcePanel(tree).props.onUploadRightsChange as (patch: Record<string, unknown>) => void)({
      sourceIdentifier: "owner-recording-2026-08",
      voiceCloningConfirmed: true,
      rightsConfirmed: true,
    });
    tree = harness.render(Workspace, props);
    (sourcePanel(tree).props.onUpload as () => void)();
    await settle();
    tree = harness.render(Workspace, props);
    expect(api.getVoiceProfile).not.toHaveBeenCalled();
    expect(upload).toHaveBeenCalledTimes(2);
    expect(upload.mock.calls[0][3]).toBe(upload.mock.calls[1][3]);
    expect(textContent(tree)).toContain("重试会复用同一幂等键");
  });

  it("fences a late profile response after the workspace switches novels", async () => {
    type ListResponse = Awaited<ReturnType<VoiceSourceWorkspaceApi["listVoiceProfiles"]>>;
    let resolveFirst!: (value: ListResponse) => void;
    let resolveSecond!: (value: ListResponse) => void;
    const first = new Promise<ListResponse>((resolve) => { resolveFirst = resolve; });
    const second = new Promise<ListResponse>((resolve) => { resolveSecond = resolve; });
    const secondProfile = {
      ...profile(),
      profile_id: "91111111-1111-4111-8111-111111111111",
      novel_id: OTHER_NOVEL_ID,
      name: "另一个作品的声音",
    };
    const api: VoiceSourceWorkspaceApi = {
      listVoiceProfiles: vi.fn((options = {}) => options.novelId === NOVEL_ID ? first : second),
      listOfficialVoicePresets: vi.fn(async () => officialPresetCatalog),
      createVoiceProfile: vi.fn(),
      getVoiceProfile: vi.fn(),
      createUploadedVoiceVersion: vi.fn(),
      createPresetVoiceVersion: vi.fn(),
      createVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
      lockVoiceProfile: vi.fn(),
    };
    const harness = createHarness();
    const Workspace = createVoiceSourceWorkspace(harness.React, api);
    const firstProps = { novelId: NOVEL_ID, capabilities, authorization, voiceSources };
    const secondProps = { ...firstProps, novelId: OTHER_NOVEL_ID };
    harness.render(Workspace, firstProps);
    harness.render(Workspace, secondProps);
    resolveSecond({ contract_version: NARRATION_SETTINGS_API_VERSION, items: [secondProfile] });
    await settle();
    let tree = harness.render(Workspace, secondProps);
    expect(textContent(tree)).toContain("另一个作品的声音");

    resolveFirst({ contract_version: NARRATION_SETTINGS_API_VERSION, items: [profile()] });
    await settle();
    tree = harness.render(Workspace, secondProps);
    expect(textContent(tree)).toContain("另一个作品的声音");
    expect(textContent(tree)).not.toContain("林夏专属声音");
  });
});
