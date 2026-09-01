import { describe, expect, it, vi } from "vitest";

import {
  buildCharacterVoiceRosterRows,
  characterVoiceBatchAvailability,
  createCharacterVoiceRoster,
  type CharacterVoiceRosterProps,
  type CharacterVoiceRosterReactRuntime,
} from "./character-voice-roster";
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


function createHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  const React: CharacterVoiceRosterReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
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
    useEffect(effect): void { effect(); },
  };
  return {
    React,
    render(Component: (props: CharacterVoiceRosterProps) => unknown, props: CharacterVoiceRosterProps): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      return Component(props) as FakeElement;
    },
  };
}


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const CHARACTER_A = "22222222-2222-4222-8222-222222222222";
const CHARACTER_B = "33333333-3333-4333-8333-333333333333";
const PROFILE_ID = "44444444-4444-4444-8444-444444444444";
const VERSION_ID = "55555555-5555-4555-8555-555555555555";


function feature(key: FeatureCapability["key"], enabled = true): FeatureCapability {
  return {
    key,
    state: enabled ? "enabled" : "hold",
    visible: true,
    actionable: enabled,
    reason_code: enabled ? null : "FEATURE_NOT_RELEASED",
    required_gate: enabled ? null : "P1.5",
  };
}


function capabilities(overrides: Partial<Record<FeatureCapability["key"], boolean>> = {}): NarrationCapabilities {
  const keys = [
    "narration_product",
    "reading_settings",
    "preset_voice_source",
    "character_voice_matching",
    "character_cast_planning",
    "reference_clone",
    "voice_generator",
  ] as const;
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: keys.map((key) => feature(key, overrides[key] ?? key !== "voice_generator")),
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


function officialVersion(changes: Partial<VoiceProfileVersionResource> = {}): VoiceProfileVersionResource {
  const evidence = OFFICIAL_PRESET_EVIDENCE.find((item) => item.presetId === "onnx.Lingyu");
  if (!evidence) throw new Error("official fixture missing");
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: VERSION_ID,
    profile_id: PROFILE_ID,
    version_number: 1,
    source_type: "preset",
    state: "locked",
    provider_id: "moss",
    model_id: "nano",
    model_revision: "rev-1",
    preset_key: evidence.presetId,
    language: "zh-CN",
    fingerprint: "a".repeat(64),
    quality_state: "pending",
    activation_basis: "explicit_official_preset_selection",
    validation_basis: "not_required",
    rights: {
      rights_record_id: "66666666-6666-4666-8666-666666666666",
      state: "active",
      notice_version: "official/1",
      source_kind: "official_preset",
      source_identifier_sha256: "b".repeat(64),
      purpose: "private_novel_narration",
      commercial_use: false,
      redistribution: false,
      voice_cloning: false,
      subject_consent_recorded: false,
      confirmed_at: "2026-08-29T00:00:00Z",
      expires_at: null,
      risk_flags: [],
    },
    official_preset: {
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
    reference_asset_id: null,
    preview_asset: {
      asset_id: "77777777-7777-4777-8777-777777777777",
      content_path: "/preview.wav",
      mime_type: "audio/wav",
      byte_size: 100,
      duration_ms: 1_000,
      checksum_sha256: "c".repeat(64),
    },
    description_available: false,
    locked_at: "2026-08-29T00:00:00Z",
    created_at: "2026-08-29T00:00:00Z",
    ...changes,
  };
}


function profile(version = officialVersion()): VoiceProfileResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: version.profile_id,
    novel_id: NOVEL_ID,
    name: "Lingyu",
    status: "active",
    version: 1,
    current_version_id: version.version_id,
    versions: [version],
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
    archived_at: null,
  };
}


function binding(characterId: string, configured = true): CharacterVoiceBindingResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    binding_id: configured ? "88888888-8888-4888-8888-888888888888" : null,
    novel_id: NOVEL_ID,
    character_id: characterId,
    binding_policy: configured ? "dedicated" : "unset",
    profile_id: configured ? PROFILE_ID : null,
    version_id: configured ? VERSION_ID : null,
    language: "zh-CN",
    version: configured ? 1 : 0,
    impact: {
      affected_chapter_count: 0,
      affected_segment_count: 0,
      historical_edition_count: 0,
      regeneration_required: false,
    },
    updated_at: configured ? "2026-08-29T00:00:00Z" : null,
  };
}


const characters = [
  { characterId: CHARACTER_A, characterName: "林夏", roleType: "main" },
  { characterId: CHARACTER_B, characterName: "周野", roleType: "supporting" },
] as const;


function props(changes: Partial<CharacterVoiceRosterProps> = {}): CharacterVoiceRosterProps {
  return {
    novelId: NOVEL_ID,
    characters,
    bindings: [binding(CHARACTER_A), binding(CHARACTER_B, false)],
    profiles: [profile()],
    capabilities: capabilities(),
    authorization,
    onConfigureCharacter: vi.fn(),
    onSmartCast: vi.fn(),
    ...changes,
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


describe("character voice roster projection", () => {
  it("shows configured gaps and exact official/private source groups without leaking another novel", () => {
    const generated = officialVersion({
      version_id: "99999999-9999-4999-8999-999999999999",
      profile_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      source_type: "generated",
      preset_key: null,
      official_preset: null,
      activation_basis: "character_one_click_generation",
      validation_basis: "machine_validated",
      quality_state: "accepted",
      rights: { ...officialVersion().rights, source_kind: "voice_generator" },
      preview_asset: null,
    });
    const privateProfile = {
      ...profile(generated),
      profile_id: generated.profile_id,
      name: "林夏专属",
    };
    const rows = buildCharacterVoiceRosterRows(
      NOVEL_ID,
      characters,
      [binding(CHARACTER_A), { ...binding(CHARACTER_B), profile_id: generated.profile_id, version_id: generated.version_id }],
      [profile(), privateProfile, { ...profile(), profile_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", novel_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" }],
    );

    expect(rows.map((row) => [row.characterName, row.configured, row.sourceGroup]))
      .toEqual([["林夏", true, "official"], ["周野", true, "private"]]);
  });

  it("keeps unresolved historical bindings visible instead of calling them unconfigured", () => {
    const rows = buildCharacterVoiceRosterRows(NOVEL_ID, characters, [binding(CHARACTER_A)], []);
    expect(rows[0]).toMatchObject({
      configured: true,
      voiceName: "绑定音色不可用",
      sourceGroup: "unresolved",
      sourceLabel: "来源待恢复",
      statusLabel: "需要处理",
    });
    expect(rows[1]).toMatchObject({
      configured: false,
      voiceName: "尚未配置",
      sourceLabel: null,
      statusLabel: null,
    });
  });
});


describe("CharacterVoiceRoster", () => {
  it("renders the compact roster with one global action and two row actions", () => {
    const onPreviewVoice = vi.fn();
    const harness = createHarness();
    const Roster = createCharacterVoiceRoster(harness.React);
    const tree = harness.render(Roster, props({ onPreviewVoice }));

    expect(textContent(tree)).toContain("2 位人物 · 1 位待配置");
    expect(textContent(tree)).toContain("主角");
    expect(textContent(tree)).toContain("配角");
    expect(textContent(tree)).toContain("官方音色");
    expect(textContent(tree).match(/尚未配置/g)).toHaveLength(1);
    expect(textContent(tree)).not.toContain("尚未绑定声音");
    expect(findAll(tree, (element) => textContent(element) === "未配置")).toHaveLength(0);
    expect(findAll(tree, (element) => textContent(element) === "已配置")).toHaveLength(0);
    expect(findButton(tree, "智能配音全书")).toBeDefined();
    expect(findAll(tree, (element) => (
      element.type === "button" && textContent(element) === "更换"
    ))).toHaveLength(2);
    expect(textContent(tree)).not.toContain("根据人物生成并使用");
    expect(textContent(tree)).not.toContain("根据人物卡匹配并使用");
    const preview = findButton(tree, "试听");
    expect(preview.props.disabled).toBe(false);
    (preview.props.onClick as () => void)();
    expect(onPreviewVoice).toHaveBeenCalledWith(
      characters[0],
      expect.objectContaining({ profile_id: PROFILE_ID }),
      expect.objectContaining({ version_id: VERSION_ID }),
    );
    expect(findAll(tree, (element) => element.type === "button")
      .every((button) => button.props.type === "button")).toBe(true);
  });

  it("starts one persistent whole-book command instead of looping character writes", async () => {
    const onSmartCast = vi.fn(async () => undefined);
    const harness = createHarness();
    const Roster = createCharacterVoiceRoster(harness.React);
    const tree = harness.render(Roster, props({ onSmartCast }));

    const start = findButton(tree, "智能配音全书").props.onClick as () => void;
    start();
    start();
    await settle();

    expect(onSmartCast).toHaveBeenCalledTimes(1);
  });

  it("shows durable cast progress and disables duplicate starts", () => {
    const onSmartCast = vi.fn();
    const harness = createHarness();
    const Roster = createCharacterVoiceRoster(harness.React);
    const tree = harness.render(Roster, props({
      onSmartCast,
      castStatus: {
        phase: "analyzing",
        progressCurrent: 2,
        progressTotal: 7,
        message: "正在分析第 3 位目标",
      },
    }));

    const action = findButton(tree, "智能配音 2/7");
    expect(action.props.disabled).toBe(true);
    expect(textContent(tree)).toContain("正在分析第 3 位目标");
  });

  it("fails closed for permission/capability gaps", () => {
    expect(characterVoiceBatchAvailability(props({
      authorization: { ...authorization, can_configure: false },
    }), 1)).toEqual({ enabled: false, reason: "当前身份只能查看，不能修改人物配音。" });

    const harness = createHarness();
    const Roster = createCharacterVoiceRoster(harness.React);
    const tree = harness.render(Roster, props({
      capabilities: capabilities({ character_cast_planning: false }),
    }));

    expect(findButton(tree, "智能配音全书").props.disabled).toBe(true);
    expect(textContent(tree)).toContain("智能配音当前不可用（FEATURE_NOT_RELEASED）");
  });

  it("opens an accessible drawer, keeps it mounted when closed and restores focus", async () => {
    const onConfigureCharacter = vi.fn();
    const trigger = { focus: vi.fn() };
    const harness = createHarness();
    const Roster = createCharacterVoiceRoster(harness.React);
    const drawerProps = props({
      onConfigureCharacter,
      renderConfigurator: (character) => `配置：${character.characterName}`,
    });
    let tree = harness.render(Roster, drawerProps);
    const change = findButton(tree, "更换");
    (change.props.onClick as (event: { currentTarget: typeof trigger }) => void)({ currentTarget: trigger });
    tree = harness.render(Roster, drawerProps);

    const dialog = findAll(tree, (element) => element.props.role === "dialog")[0];
    expect(dialog).toBeDefined();
    expect(textContent(dialog)).toContain("配置：林夏");
    expect(onConfigureCharacter).toHaveBeenCalledWith(CHARACTER_A);
    (findButton(dialog, "关闭").props.onClick as () => void)();
    tree = harness.render(Roster, drawerProps);

    const layer = findAll(tree, (element) => (
      typeof element.props.className === "string"
      && element.props.className.includes("anw-character-voice-drawer-layer")
    ))[0];
    expect(layer?.props.hidden).toBe(true);
    expect(layer?.props.inert).toBe(true);
    await settle();
    expect(trigger.focus).toHaveBeenCalled();
  });

  it("does not reveal roster data or call configuration when read access is absent", () => {
    const onConfigureCharacter = vi.fn();
    const harness = createHarness();
    const Roster = createCharacterVoiceRoster(harness.React);
    const tree = harness.render(Roster, props({
      authorization: { ...authorization, can_read: false, can_configure: false },
      onConfigureCharacter,
    }));

    expect(textContent(tree)).toContain("无权查看人物配音");
    expect(textContent(tree)).not.toContain("林夏");
    expect(textContent(tree)).not.toContain("Lingyu");
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);
    expect(onConfigureCharacter).not.toHaveBeenCalled();
  });

  it("has narrow-screen wrapping, 44px targets and visible keyboard focus", () => {
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain("@media (max-width: 768px)");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain(".anw-workbench-frame:has(");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain("z-index: 1200");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain("min-height: 44px");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain(".anw-character-voice-roster button:focus-visible");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain(".anw-character-voice-drawer");
    expect(T2_C_CHARACTER_VOICE_PANEL_STYLES).toContain("width: 100vw");
  });
});
