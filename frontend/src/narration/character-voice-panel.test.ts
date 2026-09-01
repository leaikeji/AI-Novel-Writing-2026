import { describe, expect, it, vi } from "vitest";

import { NarrationApiError } from "./api";
import {
  buildCharacterVoiceBindingRequest,
  characterVoiceOptions,
  createCharacterVoicePanel,
  type CharacterVoicePanelApi,
  type CharacterVoicePanelProps,
  type CharacterVoicePanelReactRuntime,
} from "./character-voice-panel";
import {
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  type CharacterVoiceBindingResource,
  type FeatureCapability,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type VoiceProfileResource,
  type VoiceProfileVersionResource,
} from "./contracts";
import { T2_C_CHARACTER_VOICE_PANEL_STYLES } from "./styles/t2-c";


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
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function findAll(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(root, (element) => (
    element.type === "button" && textContent(element) === label
  ))[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pendingEffects: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;

  const React: CharacterVoicePanelReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
      return [
        states[index] as T,
        (next) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        },
      ];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
      pendingEffects.push({ index, effect, dependencies: [...dependencies] });
    },
  };

  return {
    React,
    beginRender(): void {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
    },
    commitEffects(): void {
      const pending = pendingEffects;
      pendingEffects = [];
      for (const item of pending) {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      }
    },
    unmount(): void {
      for (const effect of effects) effect?.cleanup?.();
      effects.length = 0;
    },
  };
}


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_NOVEL_ID = "22222222-2222-4222-8222-222222222222";
const CHARACTER_ID = "33333333-3333-4333-8333-333333333333";
const PROFILE_ID = "44444444-4444-4444-8444-444444444444";
const PROFILE_B_ID = "55555555-5555-4555-8555-555555555555";
const PROFILE_C_ID = "55555555-5555-4555-8555-555555555556";
const VERSION_ID = "66666666-6666-4666-8666-666666666666";
const VERSION_B_ID = "77777777-7777-4777-8777-777777777777";
const VERSION_C_ID = "77777777-7777-4777-8777-777777777778";
const BINDING_ID = "88888888-8888-4888-8888-888888888888";


function officialProvenance(presetId: string) {
  const evidence = OFFICIAL_PRESET_EVIDENCE.find((item) => item.presetId === presetId);
  if (!evidence) throw new Error(`missing official preset fixture: ${presetId}`);
  return {
    schema_version: "moss-tts-official-preset-provenance/1.0" as const,
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
  };
}


function capability(
  key: FeatureCapability["key"],
  actionable = true,
): FeatureCapability {
  return {
    key,
    state: actionable ? "enabled" : "hold",
    visible: true,
    actionable,
    reason_code: actionable ? null : "T2_GATE_REQUIRED",
    required_gate: actionable ? null : "T2-GATE",
  };
}


function capabilities(overrides: Partial<Record<FeatureCapability["key"], boolean>> = {}): NarrationCapabilities {
  const keys = [
    "narration_product",
    "reading_settings",
    "preset_voice_source",
    "reference_clone",
    "voice_generator",
  ] as const;
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: keys.map((key) => capability(key, overrides[key] ?? key !== "voice_generator")),
  };
}


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


function voiceVersion(
  changes: Partial<VoiceProfileVersionResource> = {},
): VoiceProfileVersionResource {
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: VERSION_ID,
    profile_id: PROFILE_ID,
    version_number: 3,
    source_type: "preset",
    state: "locked",
    provider_id: "moss",
    model_id: "nano",
    model_revision: "rev-1",
    preset_key: "onnx.Lingyu",
    language: "zh-CN",
    fingerprint: "a".repeat(64),
    quality_state: "accepted",
    activation_basis: "preview_confirmed",
    validation_basis: "human_accepted",
    rights: {
      rights_record_id: "99999999-9999-4999-8999-999999999999",
      state: "active",
      notice_version: "voice-rights/1",
      source_kind: "official_preset",
      source_identifier_sha256: "b".repeat(64),
      purpose: "private_novel_narration",
      commercial_use: false,
      redistribution: false,
      voice_cloning: false,
      subject_consent_recorded: false,
      confirmed_at: "2026-08-26T08:00:00Z",
      expires_at: null,
      risk_flags: [],
    },
    official_preset: officialProvenance("onnx.Lingyu"),
    reference_asset_id: null,
    preview_asset: null,
    description_available: false,
    locked_at: "2026-08-26T08:00:00Z",
    created_at: "2026-08-26T08:00:00Z",
    ...changes,
  };
}


function profile(
  changes: Partial<VoiceProfileResource> = {},
  versionChanges: Partial<VoiceProfileVersionResource> = {},
): VoiceProfileResource {
  const version = voiceVersion(versionChanges);
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: version.profile_id,
    novel_id: NOVEL_ID,
    name: "林夏专属音色",
    status: "active",
    version: 4,
    current_version_id: version.version_id,
    versions: [version],
    created_at: "2026-08-26T08:00:00Z",
    updated_at: "2026-08-26T08:00:00Z",
    archived_at: null,
    ...changes,
  };
}


function binding(
  changes: Partial<CharacterVoiceBindingResource> = {},
): CharacterVoiceBindingResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    binding_id: BINDING_ID,
    novel_id: NOVEL_ID,
    character_id: CHARACTER_ID,
    binding_policy: "dedicated",
    profile_id: PROFILE_ID,
    version_id: VERSION_ID,
    language: "zh-CN",
    version: 4,
    impact: {
      affected_chapter_count: 6,
      affected_segment_count: 23,
      historical_edition_count: 2,
      regeneration_required: true,
    },
    updated_at: "2026-08-26T08:00:00Z",
    ...changes,
  };
}


function unsetBinding(
  changes: Partial<CharacterVoiceBindingResource> = {},
): CharacterVoiceBindingResource {
  return binding({
    binding_id: null,
    binding_policy: "unset",
    profile_id: null,
    version_id: null,
    version: 0,
    updated_at: null,
    impact: {
      affected_chapter_count: 0,
      affected_segment_count: 0,
      historical_edition_count: 0,
      regeneration_required: false,
    },
    ...changes,
  });
}


function apiFor(
  selectedBinding: CharacterVoiceBindingResource = binding(),
  profiles: readonly VoiceProfileResource[] = [profile()],
): CharacterVoicePanelApi {
  return {
    getCharacterVoiceBinding: vi.fn(async () => selectedBinding),
    listVoiceProfiles: vi.fn(async () => ({ items: profiles })),
    putCharacterVoiceBinding: vi.fn(async () => selectedBinding),
  };
}


function defaultProps(changes: Partial<CharacterVoicePanelProps> = {}): CharacterVoicePanelProps {
  return {
    novelId: NOVEL_ID,
    characterId: CHARACTER_ID,
    characterName: "林夏",
    capabilities: capabilities(),
    authorization,
    ...changes,
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


function setup(
  api: CharacterVoicePanelApi,
  props: CharacterVoicePanelProps = defaultProps(),
) {
  const harness = createReactHarness();
  const Panel = createCharacterVoicePanel(harness.React, api);
  let currentProps = props;
  let tree: FakeElement;
  const render = () => {
    harness.beginRender();
    tree = Panel(currentProps) as FakeElement;
    harness.commitEffects();
    return tree;
  };
  const load = async () => {
    render();
    await settle();
    return render();
  };
  return {
    harness,
    render,
    load,
    setProps(next: CharacterVoicePanelProps): void { currentProps = next; },
    get tree() { return tree; },
  };
}


describe("character voice eligibility", () => {
  it("only exposes current locked, accepted, rights-active and capability-enabled versions", () => {
    const accepted = profile();
    const revoked = profile(
      { profile_id: PROFILE_B_ID, current_version_id: VERSION_B_ID, name: "已撤销" },
      {
        profile_id: PROFILE_B_ID,
        version_id: VERSION_B_ID,
        rights: { ...voiceVersion().rights, state: "revoked" },
      },
    );
    const pending = profile(
      { profile_id: PROFILE_B_ID, current_version_id: VERSION_B_ID, name: "待确认" },
      { profile_id: PROFILE_B_ID, version_id: VERSION_B_ID, quality_state: "pending" },
    );
    const otherNovel = profile({ novel_id: OTHER_NOVEL_ID, name: "其他作品" });

    expect(characterVoiceOptions(
      [accepted, revoked, pending, otherNovel],
      NOVEL_ID,
      capabilities(),
    ).map((item) => item.profileName)).toEqual(["林夏专属音色"]);
    expect(characterVoiceOptions(
      [accepted],
      NOVEL_ID,
      capabilities({ preset_voice_source: false }),
    )).toEqual([]);
  });

  it("keeps Trump and Xiaoyu official presets bindable while rejecting legacy preset_catalog evidence", () => {
    const trump = profile(
      {
        profile_id: PROFILE_B_ID,
        current_version_id: VERSION_B_ID,
        name: "Trump 官方预设",
      },
      {
        profile_id: PROFILE_B_ID,
        version_id: VERSION_B_ID,
        preset_key: "onnx.Trump",
        language: "en",
        official_preset: officialProvenance("onnx.Trump"),
      },
    );
    const xiaoyu = profile(
      {
        profile_id: PROFILE_C_ID,
        current_version_id: VERSION_C_ID,
        name: "Xiaoyu 官方预设",
      },
      {
        profile_id: PROFILE_C_ID,
        version_id: VERSION_C_ID,
        preset_key: "onnx.Xiaoyu",
        official_preset: officialProvenance("onnx.Xiaoyu"),
      },
    );
    const legacy = profile(
      { name: "历史 preset_catalog 记录" },
      {
        preset_key: "warm-young-female",
        rights: { ...voiceVersion().rights, source_kind: "preset_catalog" },
        official_preset: null,
      },
    );
    const wrongFixedIdentity = profile(
      {
        profile_id: "55555555-5555-4555-8555-555555555557",
        current_version_id: "77777777-7777-4777-8777-777777777779",
        name: "非固定 manifest 记录",
      },
      {
        profile_id: "55555555-5555-4555-8555-555555555557",
        version_id: "77777777-7777-4777-8777-777777777779",
        official_preset: {
          ...officialProvenance("onnx.Lingyu"),
          model_fingerprint_sha256: "9".repeat(64),
        },
      },
    );

    expect(characterVoiceOptions(
      [trump, xiaoyu, legacy, wrongFixedIdentity],
      NOVEL_ID,
      capabilities(),
    ).map((item) => item.profileName)).toEqual([
      "Trump 官方预设",
      "Xiaoyu 官方预设",
    ]);
  });

  it("builds CAS requests only for an eligible immutable version and exact unset shape", () => {
    const current = binding();
    const options = characterVoiceOptions([profile()], NOVEL_ID, capabilities());
    expect(buildCharacterVoiceBindingRequest(current, {
      bindingPolicy: "inherited",
      profileId: PROFILE_ID,
      versionId: VERSION_ID,
      language: "zh-CN",
    }, options)).toEqual({
      expected_version: 4,
      binding_policy: "inherited",
      profile_id: PROFILE_ID,
      version_id: VERSION_ID,
      language: "zh-CN",
    });
    expect(buildCharacterVoiceBindingRequest(current, {
      bindingPolicy: "dedicated",
      profileId: PROFILE_B_ID,
      versionId: VERSION_B_ID,
      language: "zh-CN",
    }, options)).toBeNull();
    expect(buildCharacterVoiceBindingRequest(current, {
      bindingPolicy: "unset",
      profileId: null,
      versionId: null,
      language: "zh-CN",
    }, options)).toEqual({
      expected_version: 4,
      binding_policy: "unset",
      profile_id: null,
      version_id: null,
      language: "zh-CN",
    });
  });
});


describe("CharacterVoicePanel", () => {
  it("renders native keyboard controls, live status and honest historical impact", async () => {
    const runtime = setup(apiFor());
    const tree = await runtime.load();

    expect(tree.props.role).toBe("region");
    expect(findAll(tree, (element) => element.type === "fieldset")).toHaveLength(1);
    expect(findAll(tree, (element) => element.type === "legend").map(textContent))
      .toEqual(["声音策略"]);
    expect(findAll(tree, (element) => element.type === "input" && element.props.type === "radio"))
      .toHaveLength(3);
    expect(findAll(tree, (element) => element.type === "select")).toHaveLength(1);
    expect(findAll(tree, (element) => element.props.role === "status")).toHaveLength(1);
    expect(textContent(tree)).toContain("影响章节6");
    expect(textContent(tree)).toContain("影响句段23");
    expect(textContent(tree)).toContain("已有 2 个历史 Edition 不会被改写或替换");
    expect(textContent(tree)).toContain("作者主动更新朗读时重生成受影响句段");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain(":focus-visible");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain("repeat(4, minmax(0, 1fr))");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain("@media (max-width: 768px)");
  });

  it("fails closed without read authorization and makes no API request", async () => {
    const api = apiFor();
    const runtime = setup(api, defaultProps({
      authorization: { ...authorization, can_read: false, can_configure: false },
    }));
    const tree = await runtime.load();

    expect(api.getCharacterVoiceBinding).not.toHaveBeenCalled();
    expect(api.listVoiceProfiles).not.toHaveBeenCalled();
    expect(findAll(tree, (element) => element.type === "fieldset")).toHaveLength(0);
    expect(textContent(tree)).toContain("无权查看人物声音设置");
  });

  it("hides already loaded data synchronously when read access or scope changes", async () => {
    const api = apiFor();
    const runtime = setup(api);
    let tree = await runtime.load();
    expect(findAll(tree, (element) => element.type === "fieldset")).toHaveLength(1);

    runtime.setProps(defaultProps({
      authorization: { ...authorization, can_read: false },
    }));
    tree = runtime.render();
    expect(findAll(tree, (element) => element.type === "fieldset")).toHaveLength(0);
    expect(textContent(tree)).not.toContain("影响章节6");

    runtime.setProps(defaultProps({ characterId: PROFILE_B_ID }));
    tree = runtime.render();
    expect(findAll(tree, (element) => element.type === "fieldset")).toHaveLength(0);
    expect(textContent(tree)).not.toContain("影响章节6");
  });

  it("loads held capabilities for truthful read-only display but disables every mutation", async () => {
    const api = apiFor();
    const runtime = setup(api, defaultProps({
      capabilities: capabilities({ reading_settings: false }),
    }));
    const tree = await runtime.load();
    const fieldset = findAll(tree, (element) => element.type === "fieldset")[0];
    const save = findButton(tree, "保存人物声音");

    expect(api.getCharacterVoiceBinding).toHaveBeenCalledTimes(1);
    expect(fieldset.props.disabled).toBe(true);
    expect(save.props.disabled).toBe(true);
    expect(textContent(tree)).toContain("人物声音保持只读（T2_GATE_REQUIRED）");
  });

  it("saves inherited and unset policies with the currently loaded CAS version", async () => {
    const initial = binding();
    const inherited = binding({ binding_policy: "inherited", version: 5 });
    const api = apiFor(initial);
    vi.mocked(api.putCharacterVoiceBinding).mockResolvedValueOnce(inherited);
    const runtime = setup(api);
    let tree = await runtime.load();
    const inheritedRadio = findAll(tree, (element) => (
      element.type === "input" && element.props.value === "inherited"
    ))[0];

    (inheritedRadio.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "inherited" },
    });
    tree = runtime.render();
    expect(findButton(tree, "保存人物声音").props.disabled).toBe(false);
    (findButton(tree, "保存人物声音").props.onClick as () => void)();
    await settle();
    tree = runtime.render();

    expect(api.putCharacterVoiceBinding).toHaveBeenNthCalledWith(1,
      NOVEL_ID,
      CHARACTER_ID,
      {
        expected_version: 4,
        binding_policy: "inherited",
        profile_id: PROFILE_ID,
        version_id: VERSION_ID,
        language: "zh-CN",
      },
      expect.any(AbortSignal),
    );
    expect(textContent(tree)).toContain("历史 Edition 保持不变");

    const unset = unsetBinding();
    vi.mocked(api.putCharacterVoiceBinding).mockResolvedValueOnce(unset);
    const unsetRadio = findAll(tree, (element) => (
      element.type === "input" && element.props.value === "unset"
    ))[0];
    (unsetRadio.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "unset" },
    });
    tree = runtime.render();
    (findButton(tree, "保存人物声音").props.onClick as () => void)();
    await settle();
    runtime.render();

    expect(api.putCharacterVoiceBinding).toHaveBeenNthCalledWith(2,
      NOVEL_ID,
      CHARACTER_ID,
      {
        expected_version: 5,
        binding_policy: "unset",
        profile_id: null,
        version_id: null,
        language: "zh-CN",
      },
      expect.any(AbortSignal),
    );
  });

  it("preserves the user's selection across a CAS conflict and retries from the refreshed version", async () => {
    const initial = unsetBinding();
    const serverChanged = binding({
      binding_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      profile_id: PROFILE_B_ID,
      version_id: VERSION_B_ID,
      version: 2,
    });
    const saved = binding({ version: 3 });
    const api = apiFor(initial);
    vi.mocked(api.getCharacterVoiceBinding)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(serverChanged);
    vi.mocked(api.putCharacterVoiceBinding)
      .mockRejectedValueOnce(new NarrationApiError(409, {
        contract_version: NARRATION_SETTINGS_API_VERSION,
        code: "VERSION_CONFLICT",
        message: "conflict",
        retryable: true,
        field: null,
        current_version: 2,
        capability: null,
      }))
      .mockResolvedValueOnce(saved);
    const runtime = setup(api);
    let tree = await runtime.load();

    const dedicatedRadio = findAll(tree, (element) => (
      element.type === "input" && element.props.value === "dedicated"
    ))[0];
    (dedicatedRadio.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "dedicated" },
    });
    tree = runtime.render();
    (findButton(tree, "保存人物声音").props.onClick as () => void)();
    await settle();
    tree = runtime.render();

    expect(textContent(tree)).toContain("你的声音选择仍保留");
    expect(textContent(tree)).toContain("服务端当前版本为 2");
    expect(findAll(tree, (element) => element.type === "select")[0].props.value)
      .toBe(`${PROFILE_ID}:${VERSION_ID}`);

    (findButton(tree, "刷新最新绑定").props.onClick as () => void)();
    await settle();
    tree = runtime.render();
    expect(textContent(tree)).toContain("你的声音选择已保留");
    expect(findAll(tree, (element) => element.type === "select")[0].props.value)
      .toBe(`${PROFILE_ID}:${VERSION_ID}`);

    (findButton(tree, "保存人物声音").props.onClick as () => void)();
    await settle();
    runtime.render();
    expect(api.putCharacterVoiceBinding).toHaveBeenNthCalledWith(2,
      NOVEL_ID,
      CHARACTER_ID,
      expect.objectContaining({
        expected_version: 2,
        profile_id: PROFILE_ID,
        version_id: VERSION_ID,
      }),
      expect.any(AbortSignal),
    );
  });

  it("rejects cross-novel response drift before rendering any binding controls", async () => {
    const api = apiFor(binding({ novel_id: OTHER_NOVEL_ID }));
    const runtime = setup(api);
    const tree = await runtime.load();

    expect(tree.props["data-voice-panel-phase"]).toBe("load-error");
    expect(textContent(tree)).toContain("响应与当前作品或人物不一致");
    expect(findAll(tree, (element) => element.type === "fieldset")).toHaveLength(0);
  });

  it("restores host focus and aborts in-flight work when unmounted", () => {
    const onReturnFocus = vi.fn();
    const never = new Promise<CharacterVoiceBindingResource>(() => undefined);
    const api = apiFor();
    vi.mocked(api.getCharacterVoiceBinding).mockReturnValue(never);
    const runtime = setup(api, defaultProps({ onReturnFocus }));
    runtime.render();
    const signal = vi.mocked(api.getCharacterVoiceBinding).mock.calls[0][2];

    expect(signal?.aborted).toBe(false);
    runtime.harness.unmount();
    expect(signal?.aborted).toBe(true);
    expect(onReturnFocus).toHaveBeenCalledTimes(1);
  });
});
