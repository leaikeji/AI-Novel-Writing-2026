import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CAPABILITY_KEYS,
  NARRATION_CACHE_SCHEMA_VERSION,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  type CharacterVoiceBindingResource,
  type CharacterVoiceMatchResource,
  type FeatureCapability,
  type NarrationOverviewResponse,
  type OfficialPresetId,
  type OfficialVoiceSelectionResponse,
  type VoiceProfileResource,
} from "./contracts";
import {
  createCharacterVoiceCardPanel,
  createNarrationReadingPage,
} from "./index";
import type { OfficialVoiceSelectionPanelApi } from "./official-voice-selection-panel";
import type { ReadingPageApi } from "./reading-page";
import { narratorOptionsFromVoiceProfiles } from "./reading-page";
import {
  NARRATION_STYLES,
  NARRATION_STYLE_ID,
  ensureNarrationStyles,
} from "./styles";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
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


function componentName(element: FakeElement): string {
  return typeof element.type === "function" ? element.type.name : "";
}


function createReactHarness(options: { readonly dependencyAware?: boolean } = {}) {
  const states: Array<{ value: unknown }> = [];
  const refs: Array<{ current: unknown }> = [];
  const effectSlots: Array<{
    dependencies: readonly unknown[];
    effect: () => void | (() => void);
    cleanup?: () => void;
    pending: boolean;
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  let effects: Array<() => void | (() => void)> = [];
  const dependenciesChanged = (
    previous: readonly unknown[],
    next: readonly unknown[],
  ): boolean => previous.length !== next.length
    || previous.some((value, index) => !Object.is(value, next[index]));
  const React = {
    createElement(type: unknown, props?: Record<string, unknown> | null, ...children: unknown[]): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!states[index]) {
        states[index] = { value: typeof initial === "function" ? (initial as () => T)() : initial };
      }
      return [
        states[index].value as T,
        (next) => {
          const current = states[index].value as T;
          states[index].value = typeof next === "function"
            ? (next as (value: T) => T)(current)
            : next;
        },
      ];
    },
    useEffect(
      effect: () => void | (() => void),
      dependencies: readonly unknown[],
    ): void {
      if (options.dependencyAware === true) {
        const index = effectIndex++;
        const current = effectSlots[index];
        if (current === undefined) {
          effectSlots[index] = { dependencies, effect, pending: true };
          return;
        }
        if (!dependenciesChanged(current.dependencies, dependencies)) return;
        current.dependencies = dependencies;
        current.effect = effect;
        current.pending = true;
        return;
      }
      effects.push(effect);
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      effects = [];
      return Component(props) as FakeElement;
    },
    flushEffects(): Array<() => void> {
      if (options.dependencyAware === true) {
        const cleanups: Array<() => void> = [];
        for (const slot of effectSlots) {
          if (!slot.pending) continue;
          slot.cleanup?.();
          slot.pending = false;
          const cleanup = slot.effect();
          slot.cleanup = cleanup ?? undefined;
          if (cleanup) cleanups.push(cleanup);
        }
        return cleanups;
      }
      const cleanups: Array<() => void> = [];
      const pending = effects;
      effects = [];
      for (const effect of pending) {
        const cleanup = effect();
        if (cleanup) cleanups.push(cleanup);
      }
      return cleanups;
    },
    resetHooks(): void {
      states.length = 0;
      refs.length = 0;
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      effects = [];
      effectSlots.length = 0;
    },
  };
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";
const CHARACTER_ID = "123e4567-e89b-42d3-a456-426614174001";
const VOLUME_ID = "123e4567-e89b-42d3-a456-426614174002";
const ZERO_SHA = "0".repeat(64);
const RIGHTS_ID = "123e4567-e89b-42d3-a456-426614174003";
const VOICE_PROFILE_ID = "123e4567-e89b-42d3-a456-426614174004";
const VOICE_VERSION_ID = "123e4567-e89b-42d3-a456-426614174005";
const CREATED_AT = "2026-08-26T09:00:00.000Z";
const XIAOYU_EVIDENCE = OFFICIAL_PRESET_EVIDENCE.find(
  (item) => item.presetId === "onnx.Xiaoyu",
)!;


function capability(key: typeof CAPABILITY_KEYS[number]): FeatureCapability {
  if (key === "narration_product" || key === "reading_settings" || key === "cache_cleanup") {
    return {
      key,
      state: "hold",
      visible: true,
      actionable: false,
      reason_code: "T2_GATE_REQUIRED",
      required_gate: "T2-GATE",
    };
  }
  const sourceVisible = key === "preset_voice_source" || key === "reference_clone";
  return {
    key,
    state: "unavailable",
    visible: sourceVisible,
    actionable: false,
    reason_code: key === "voice_generator" ? "VOICE_GENERATOR_NO_GO" : "T4_GATE_REQUIRED",
    required_gate: key === "voice_generator" ? "T5-GATE" : "T4-GATE",
  };
}


function overviewFixture(): NarrationOverviewResponse {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    capabilities: {
      schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
      items: CAPABILITY_KEYS.map(capability),
    },
    authorization: {
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
    },
    runtime: {
      technical_enabled: false,
      lifecycle_status: "disabled",
      sidecar_reachable: false,
      model_ready: false,
      product_visible: false,
      protocol_version: "moss-tts-sidecar/1.1",
      model_fingerprint_sha256: null,
      reason_code: "TTS_RUNTIME_DISABLED",
    },
    settings: {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
      novel_id: NOVEL_ID,
      settings_id: null,
      exists: false,
      version: 0,
      values: {
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
        timing: { sentence_gap_ms: 220, paragraph_gap_ms: 480, section_gap_ms: 850 },
        casting: {
          anonymous_reuse_scope: "scene",
          same_scene_voice_deduplication: true,
          unknown_speaker_action: "block",
        },
        playback: { playback_rate: 1, volume: 1 },
      },
      updated_at: null,
    },
    coverage: {
      character_count: 1,
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
      { source_type: "preset", capability: "preset_voice_source", available: false, reason_code: "T4_GATE_REQUIRED", accepted_mime_types: [], maximum_bytes: null },
      { source_type: "uploaded", capability: "reference_clone", available: false, reason_code: "T4_GATE_REQUIRED", accepted_mime_types: ["audio/wav", "audio/flac"], maximum_bytes: 16 * 1024 * 1024 },
      { source_type: "generated", capability: "voice_generator", available: false, reason_code: "VOICE_GENERATOR_NO_GO", accepted_mime_types: [], maximum_bytes: null },
    ],
    cache: {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      schema_version: NARRATION_CACHE_SCHEMA_VERSION,
      novel_id: NOVEL_ID,
      snapshot_fingerprint: ZERO_SHA,
      source_asset_bytes: 0,
      locked_voice_bytes: 0,
      referenced_edition_bytes: 0,
      derived_cache_bytes: 0,
      reclaimable_bytes: 0,
      pending_job_count: 0,
      disk_free_bytes: 1,
      disk_total_bytes: 1,
      cleanup_capability: capability("cache_cleanup"),
    },
  };
}


function overviewWithVoiceActions(): NarrationOverviewResponse {
  const base = overviewFixture();
  return {
    ...base,
    capabilities: {
      ...base.capabilities,
      items: base.capabilities.items.map((item) => (
        item.key === "character_voice_matching" || item.key === "voice_generator"
          ? {
            ...item,
            state: "enabled" as const,
            visible: true,
            actionable: true,
            reason_code: null,
            required_gate: null,
          }
          : item
      )),
    },
  };
}


function readingApi(overview: NarrationOverviewResponse): ReadingPageApi {
  return {
    getOverview: vi.fn(async () => overview),
    listScopeOverrides: vi.fn(async () => ({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      novel_id: NOVEL_ID,
      items: [],
    })),
    listVoiceProfiles: vi.fn(async () => ({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      items: [],
    })),
    putSettings: vi.fn(),
    putScopeOverride: vi.fn(),
  };
}


function voiceProfile(
  changes: Partial<VoiceProfileResource> = {},
): VoiceProfileResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: VOICE_PROFILE_ID,
    novel_id: NOVEL_ID,
    name: "温暖青年女声",
    status: "active",
    version: 1,
    current_version_id: VOICE_VERSION_ID,
    versions: [{
      schema_version: NARRATION_VOICE_SCHEMA_VERSION,
      version_id: VOICE_VERSION_ID,
      profile_id: VOICE_PROFILE_ID,
      version_number: 1,
      source_type: "preset",
      state: "locked",
      provider_id: "moss-tts-nano-onnx",
      model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
      model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
      preset_key: XIAOYU_EVIDENCE.presetId,
      language: "zh-CN",
      fingerprint: "a".repeat(64),
      quality_state: "accepted",
      activation_basis: "preview_confirmed",
      validation_basis: "human_accepted",
      rights: {
        rights_record_id: RIGHTS_ID,
        state: "active",
        notice_version: "official-preset-local-use/1",
        source_kind: "official_preset",
        source_identifier_sha256: "b".repeat(64),
        purpose: "private_novel_narration",
        commercial_use: false,
        redistribution: false,
        voice_cloning: false,
        subject_consent_recorded: false,
        confirmed_at: CREATED_AT,
        expires_at: null,
        risk_flags: [],
      },
      official_preset: {
        schema_version: "moss-tts-official-preset-provenance/1.0",
        repository: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
        revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
        manifest_path: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
        manifest_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestSha256,
        preset_id: XIAOYU_EVIDENCE.presetId,
        manifest_voice: XIAOYU_EVIDENCE.manifestVoice,
        prompt_codes_sha256: XIAOYU_EVIDENCE.promptCodesSha256,
        prompt_frame_count: XIAOYU_EVIDENCE.promptFrameCount,
        prompt_quantizer_count: XIAOYU_EVIDENCE.promptQuantizerCount,
        model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
        provenance_fingerprint_sha256: XIAOYU_EVIDENCE.provenanceFingerprintSha256,
      },
      reference_asset_id: null,
      preview_asset: null,
      description_available: false,
      locked_at: CREATED_AT,
      created_at: CREATED_AT,
    }],
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
    archived_at: null,
    ...changes,
  };
}


function characterBinding(
  changes: Partial<CharacterVoiceBindingResource> = {},
): CharacterVoiceBindingResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    binding_id: "123e4567-e89b-42d3-a456-426614174006",
    novel_id: NOVEL_ID,
    character_id: CHARACTER_ID,
    binding_policy: "dedicated",
    profile_id: VOICE_PROFILE_ID,
    version_id: VOICE_VERSION_ID,
    language: "zh-CN",
    version: 3,
    impact: {
      affected_chapter_count: 0,
      affected_segment_count: 0,
      historical_edition_count: 0,
      regeneration_required: false,
    },
    updated_at: CREATED_AT,
    ...changes,
  };
}


function characterVoiceMatch(
  characterId = CHARACTER_ID,
  changes: Partial<CharacterVoiceMatchResource> = {},
): CharacterVoiceMatchResource {
  return {
    contract_version: "character-voice-match/1",
    character_id: characterId,
    brief: {
      schema_version: "character-voice-brief/1",
      language: "zh-CN",
      presentation: "feminine",
      pitch: 0,
      pace: 0,
      energy: 0,
      texture: "warm",
      evidence_fields: ["name"],
    },
    selected_preset_id: "onnx.Xiaoyu",
    score_milli: 900,
    state: "ready_unapplied",
    selection_still_current: false,
    current_character_binding: characterBinding({ character_id: characterId }),
    model_evidence: {},
    ...changes,
  };
}


function officialVoiceSelectionResponse(
  presetId: OfficialPresetId,
  characterId = CHARACTER_ID,
): OfficialVoiceSelectionResponse {
  const profile = voiceProfile();
  return {
    contract_version: "official-voice-selection/1.0",
    replayed: false,
    selection_still_current: true,
    frozen_result: {
      command_id: "123e4567-e89b-42d3-a456-426614174011",
      preset_id: presetId,
      target_kind: "character",
      character_id: characterId,
      profile_id: profile.profile_id,
      version_id: profile.current_version_id!,
      settings_version: 2,
      binding_version: 4,
      target_language: "zh-CN",
      language_mismatch: false,
      completed_at: CREATED_AT,
    },
    profile,
    current_settings: null,
    current_character_binding: characterBinding({
      character_id: characterId,
      version: 4,
    }),
  };
}


async function settle(): Promise<void> {
  for (let turn = 0; turn < 6; turn += 1) await Promise.resolve();
}


afterEach(() => {
  vi.restoreAllMocks();
});


describe("T2-GATE narration composition", () => {
  it("maps only scoped, locked, rights-active profiles after every required gate opens", () => {
    const overview = overviewFixture();
    expect(narratorOptionsFromVoiceProfiles(
      NOVEL_ID,
      [voiceProfile()],
      overview.capabilities,
    )).toEqual([]);

    const enabledKeys = new Set([
      "narration_product",
      "reading_settings",
      "preset_voice_source",
    ]);
    const enabledCapabilities = {
      ...overview.capabilities,
      items: overview.capabilities.items.map((item) => enabledKeys.has(item.key)
        ? {
            ...item,
            state: "enabled" as const,
            visible: true,
            actionable: true,
            reason_code: null,
            required_gate: null,
          }
        : item),
    };
    const invalid = voiceProfile({
      profile_id: CHARACTER_ID,
      novel_id: CHARACTER_ID,
      current_version_id: VOICE_VERSION_ID,
    });
    expect(narratorOptionsFromVoiceProfiles(
      NOVEL_ID,
      [invalid, voiceProfile()],
      enabledCapabilities,
    )).toEqual([{
      novelId: NOVEL_ID,
      profileId: VOICE_PROFILE_ID,
      versionId: VOICE_VERSION_ID,
      label: "温暖青年女声 · v1",
      locked: true,
      rightsActive: true,
    }]);
    expect(voiceProfile().versions[0]?.preset_key).toBe("onnx.Xiaoyu");

    const official = voiceProfile();
    const officialVersion = official.versions[0]!;
    const legacyPresetCatalog = voiceProfile({
      name: "历史 preset_catalog 记录",
      versions: [{
        ...officialVersion,
        preset_key: "warm-young-female",
        rights: { ...officialVersion.rights, source_kind: "preset_catalog" },
        official_preset: null,
      }],
    });
    expect(narratorOptionsFromVoiceProfiles(
      NOVEL_ID,
      [legacyPresetCatalog],
      enabledCapabilities,
    )).toEqual([]);
  });

  it("feeds the same verified overview into the character and pronunciation panels", async () => {
    const overview = overviewFixture();
    const harness = createReactHarness();
    const Page = createNarrationReadingPage(harness.React, { readingApi: readingApi(overview) });
    const common = {
      novelId: NOVEL_ID,
      scopeTargets: [{ novelId: NOVEL_ID, scopeKind: "volume" as const, scopeId: VOLUME_ID, label: "第一卷" }],
      characters: [{ novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" }],
    };
    const characterPageProps = { ...common, initialSection: "characters" as const };
    let pageHost = harness.render(Page, characterPageProps);
    let tree = harness.render(
      pageHost.type as (props: typeof pageHost.props) => unknown,
      pageHost.props,
    );
    harness.flushEffects();
    await settle();
    pageHost = harness.render(Page, characterPageProps);
    const renderNarratorWorkspace = pageHost.props.renderNarratorVoiceWorkspace as (
      context: { overview: typeof overview; onRefresh: () => void; onNavigate: () => void },
    ) => FakeElement;
    const narratorWorkspace = renderNarratorWorkspace({
      overview,
      onRefresh: vi.fn(),
      onNavigate: vi.fn(),
    });
    const narratorStatus = findAll(
      narratorWorkspace,
      (element) => componentName(element) === "ReadingStatus",
    )[0];
    const narratorRules = findAll(
      narratorWorkspace,
      (element) => componentName(element) === "ReadingRulesWorkspace",
    )[0];
    expect(narratorStatus.props.overview).toBe(overview);
    expect(narratorRules.props.settings).toBe(overview.settings);
    tree = harness.render(
      pageHost.type as (props: typeof pageHost.props) => unknown,
      pageHost.props,
    );

    const sectionHost = findAll(tree, (element) => (
      typeof element.type === "function"
      && element.props.novelId === NOVEL_ID
      && Array.isArray(element.props.characters)
      && typeof element.props.context === "object"
    ))[0];
    expect(sectionHost).toBeDefined();
    const characterTree = harness.render(
      sectionHost.type as (props: typeof sectionHost.props) => unknown,
      sectionHost.props,
    );
    const characterRoster = findAll(
      characterTree,
      (element) => componentName(element) === "CharacterVoiceRoster",
    )[0];
    expect(characterRoster.props.capabilities).toBe(overview.capabilities);
    expect(characterRoster.props.authorization).toBe(overview.authorization);
    expect(characterRoster.props.renderConfigurator).toEqual(expect.any(Function));
    const characterWorkspace = findAll(
      characterTree,
      (element) => componentName(element) === "VoiceSourceWorkspace",
    )[0];
    expect(characterWorkspace).toBeUndefined();
    const characterOfficial = findAll(
      characterTree,
      (element) => componentName(element) === "OfficialVoiceSelectionPanel",
    )[0];
    expect(characterOfficial).toBeUndefined();

    const renderSectionContent = pageHost.props.renderSectionContent as (
      section: "voice-library",
      context: { overview: typeof overview; onRefresh: () => void; onNavigate: () => void },
    ) => FakeElement;
    const voiceLibraryHost = renderSectionContent("voice-library", {
      overview,
      onRefresh: vi.fn(),
      onNavigate: vi.fn(),
    });
    harness.resetHooks();
    let voiceLibraryTree = harness.render(
      voiceLibraryHost.type as (props: typeof voiceLibraryHost.props) => unknown,
      voiceLibraryHost.props,
    );
    let sharedOfficial = findAll(
      voiceLibraryTree,
      (element) => componentName(element) === "OfficialVoiceSelectionPanel",
    )[0];
    expect(sharedOfficial).toBeUndefined();
    expect(findAll(voiceLibraryTree, (element) => element.type === "select")).toHaveLength(0);
    expect(textContent(voiceLibraryTree)).toContain("作品旁白");
    expect(textContent(voiceLibraryTree)).not.toContain("使用目标");
    const changeNarrator = findAll(
      voiceLibraryTree,
      (element) => element.type === "button" && textContent(element) === "更换旁白音色",
    )[0];
    expect(changeNarrator.props["aria-expanded"]).toBe(false);
    (changeNarrator.props.onClick as (() => void))();
    voiceLibraryTree = harness.render(
      voiceLibraryHost.type as (props: typeof voiceLibraryHost.props) => unknown,
      voiceLibraryHost.props,
    );
    sharedOfficial = findAll(
      voiceLibraryTree,
      (element) => componentName(element) === "OfficialVoiceSelectionPanel",
    )[0];
    expect(sharedOfficial.props.target).toEqual({ kind: "narrator" });
    expect(sharedOfficial.props.projection).toEqual({ phase: "loading" });
    expect(textContent(voiceLibraryTree)).toContain("收起音色列表");

    const pronunciationHarness = createReactHarness();
    const PronunciationPage = createNarrationReadingPage(pronunciationHarness.React, { readingApi: readingApi(overview) });
    const pronunciationProps = { ...common, initialSection: "pronunciation" as const };
    let pronunciationHost = pronunciationHarness.render(
      PronunciationPage,
      pronunciationProps,
    );
    let pronunciationTree = pronunciationHarness.render(
      pronunciationHost.type as (props: typeof pronunciationHost.props) => unknown,
      pronunciationHost.props,
    );
    pronunciationHarness.flushEffects();
    await settle();
    pronunciationHost = pronunciationHarness.render(
      PronunciationPage,
      pronunciationProps,
    );
    pronunciationTree = pronunciationHarness.render(
      pronunciationHost.type as (props: typeof pronunciationHost.props) => unknown,
      pronunciationHost.props,
    );
    const rulesWorkspace = findAll(
      pronunciationTree,
      (element) => (
        typeof element.type === "function"
        && Array.isArray(element.props.pronunciationScopeOptions)
        && element.props.settings === overview.settings
      ),
    )[0];
    expect(rulesWorkspace.props.capabilities).toBe(overview.capabilities);
    expect(rulesWorkspace.props.settings).toBe(overview.settings);
    expect(rulesWorkspace.props.initialSection).toBe("recognition");
    expect(rulesWorkspace.props.pronunciationScopeOptions).toEqual([
      { kind: "volume", id: VOLUME_ID, label: "第一卷" },
    ]);
  });

  it("loads the character-card sound tab with scope-drift protection", async () => {
    const overview = overviewWithVoiceActions();
    const harness = createReactHarness();
    const loadOverview = vi.fn(async () => overview);
    const binding = characterBinding();
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn(async () => binding),
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile()],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      loadOverview,
      undefined,
      officialVoiceApi,
    );
    const props = { novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" };
    let tree = harness.render(Card, props);
    expect(tree.props.role).toBe("status");
    harness.flushEffects();
    await settle();
    tree = harness.render(Card, props);
    harness.flushEffects();
    await settle();
    tree = harness.render(Card, props);
    expect(componentName(tree)).toBe("CharacterVoiceConfigurator");
    const official = tree.props.officialVoiceContent as FakeElement;
    const advancedHost = tree.props.advancedContent as FakeElement;
    const generator = tree.props.generatorContent as FakeElement;
    expect(findAll(tree, (element) => componentName(element) === "CharacterVoicePanel"))
      .toHaveLength(0);
    expect(findAll(tree, (element) => componentName(element) === "VoiceSourceWorkspace"))
      .toHaveLength(0);
    expect(advancedHost.props.key).toBe(`character-voice-advanced:${NOVEL_ID}:${CHARACTER_ID}`);
    expect(official.props.settings).toBe(overview.settings);
    expect(official.props.headerAction).toBeUndefined();
    expect(official.props.presentation).toBe("embedded");
    expect(componentName(generator)).toBe("CharacterVoiceGenerator");
    expect(generator.props.presentation).toBe("embedded");
    expect(officialVoiceApi.getCharacterVoiceBinding).toHaveBeenCalledWith(
      NOVEL_ID,
      CHARACTER_ID,
      expect.any(AbortSignal),
    );
    expect(officialVoiceApi.listVoiceProfiles).toHaveBeenCalledWith(expect.objectContaining({
      novelId: NOVEL_ID,
      includeLibrary: true,
    }));
    expect(tree.props.currentVoice).toMatchObject({
      phase: "resolved",
      name: "温暖青年女声",
      sourceLabel: "官方音色",
      languageLabel: "中文",
    });
    expect(loadOverview).toHaveBeenCalledWith(NOVEL_ID, expect.any(AbortSignal));

    harness.resetHooks();
    const advancedTree = harness.render(
      advancedHost.type as (props: typeof advancedHost.props) => unknown,
      advancedHost.props,
    );
    expect(advancedTree.props).toMatchObject({
      className: "anw-character-voice-advanced-stack",
      "data-character-voice-scope": `${NOVEL_ID}:${CHARACTER_ID}`,
    });
    const panel = findAll(
      advancedTree,
      (element) => componentName(element) === "CharacterVoicePanel",
    )[0];
    const workspace = findAll(
      advancedTree,
      (element) => componentName(element) === "VoiceSourceWorkspace",
    )[0];
    expect(panel.props.capabilities).toBe(overview.capabilities);
    expect(panel.props.presentation).toBe("embedded");
    expect(panel.props.allowedSourceTypes).toEqual(["uploaded", "generated"]);
    expect(workspace.props.novelId).toBe(NOVEL_ID);
    expect(workspace.props.voiceSources).toBe(overview.voice_sources);

    const driftHarness = createReactHarness();
    const DriftCard = createCharacterVoiceCardPanel(
      driftHarness.React,
      vi.fn(async () => ({ ...overview, novel_id: CHARACTER_ID })),
    );
    driftHarness.render(DriftCard, props);
    driftHarness.flushEffects();
    await settle();
    const drift = driftHarness.render(DriftCard, props);
    expect(drift.props.role).toBe("alert");
  });

  it("uses the workspace binding only for the initial projection, then refreshes after a write", async () => {
    const overview = overviewWithVoiceActions();
    const harness = createReactHarness({ dependencyAware: true });
    const getBinding = vi.fn(async () => characterBinding({ version: 4 }));
    const officialVoiceApi = {
      getCharacterVoiceBinding: getBinding,
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile()],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overview),
      undefined,
      officialVoiceApi,
    );
    const props = {
      novelId: NOVEL_ID,
      characterId: CHARACTER_ID,
      characterName: "林岚",
      initialBinding: {
        binding_id: characterBinding().binding_id!,
        binding_policy: "dedicated",
        profile_id: VOICE_PROFILE_ID,
        voice_version_id: VOICE_VERSION_ID,
        language: "zh-CN",
        version: 3,
      },
    };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    let tree = harness.render(Card, props);
    expect(getBinding).not.toHaveBeenCalled();
    expect(tree.props.currentVoice).toMatchObject({
      phase: "resolved",
      name: "温暖青年女声",
    });

    const official = tree.props.officialVoiceContent as FakeElement;
    (official.props.onChanged as () => void)();
    tree = harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    tree = harness.render(Card, props);
    expect(getBinding).toHaveBeenCalledTimes(1);
    expect(tree.props.currentVoice).toMatchObject({
      phase: "resolved",
      name: "温暖青年女声",
    });
  });

  it("projects a missing workspace binding as version-zero unset without another read", async () => {
    const harness = createReactHarness({ dependencyAware: true });
    const getBinding = vi.fn(async () => characterBinding());
    const officialVoiceApi = {
      getCharacterVoiceBinding: getBinding,
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile()],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overviewWithVoiceActions()),
      undefined,
      officialVoiceApi,
    );
    const props = {
      novelId: NOVEL_ID,
      characterId: CHARACTER_ID,
      characterName: "林岚",
      initialBinding: null,
    };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    const tree = harness.render(Card, props);
    const official = tree.props.officialVoiceContent as FakeElement;

    expect(getBinding).not.toHaveBeenCalled();
    expect(tree.props.currentVoice).toMatchObject({
      phase: "unbound",
      message: "尚未单独绑定，将按当前朗读规则选择声音。",
    });
    expect(official.props.projection).toMatchObject({
      phase: "ready",
      binding: {
        binding_id: null,
        novel_id: NOVEL_ID,
        character_id: CHARACTER_ID,
        binding_policy: "unset",
        version: 0,
      },
    });
  });

  it("fails closed instead of hanging when the binding response has another character scope", async () => {
    const nextCharacterId = "123e4567-e89b-42d3-a456-426614174007";
    const harness = createReactHarness({ dependencyAware: true });
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn(async () => characterBinding({
        character_id: nextCharacterId,
      })),
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile()],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overviewWithVoiceActions()),
      undefined,
      officialVoiceApi,
    );
    const props = { novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    const tree = harness.render(Card, props);

    expect(tree.props.currentVoice).toMatchObject({
      phase: "error",
      message: expect.stringContaining("直接选择已暂停"),
    });
    const official = tree.props.officialVoiceContent as FakeElement;
    expect(official.props.projection).toEqual({
      phase: "error",
      message: "无法读取当前人物的声音绑定，请刷新后重试。",
    });
  });

  it("exposes one scoped official-match adapter to the shared configurator", async () => {
    const matchApi = vi.fn(async () => characterVoiceMatch());
    const harness = createReactHarness({ dependencyAware: true });
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn(async (_novelId: string, characterId: string) => (
        characterBinding({ character_id: characterId })
      )),
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile()],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overviewWithVoiceActions()),
      undefined,
      officialVoiceApi,
      { matchCharacterOfficialVoice: matchApi as typeof import("./api").matchCharacterOfficialVoice },
    );
    const props = { novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    const tree = harness.render(Card, props);
    const controller = new AbortController();
    const result = await (tree.props.onMatchOfficialVoice as (
      signal: AbortSignal,
    ) => Promise<{ voiceName: string; presetId: string; selectionStillCurrent: boolean }>)(
      controller.signal,
    );
    expect(matchApi).toHaveBeenCalledWith(
      NOVEL_ID,
      CHARACTER_ID,
      expect.any(Object),
      expect.any(String),
      expect.any(AbortSignal),
    );
    expect(result).toEqual({
      voiceName: "Xiaoyu",
      presetId: "onnx.Xiaoyu",
      selectionStillCurrent: false,
    });
  });

  it("rejects a matched-voice response whose preset identity changed", async () => {
    const harness = createReactHarness({ dependencyAware: true });
    const selectOfficial = vi.fn(async () => officialVoiceSelectionResponse("onnx.Junhao"));
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn(async () => characterBinding()),
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile()],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: selectOfficial,
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overviewWithVoiceActions()),
      undefined,
      officialVoiceApi,
      { matchCharacterOfficialVoice: vi.fn(async () => characterVoiceMatch()) },
    );
    const props = { novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    const tree = harness.render(Card, props);
    const useMatched = tree.props.onUseMatchedOfficialVoice as (
      presetId: string,
      signal: AbortSignal,
    ) => Promise<unknown>;

    await expect(useMatched("onnx.Xiaoyu", new AbortController().signal))
      .rejects.toThrow("声音身份与当前人物不一致");
    expect(selectOfficial).toHaveBeenCalledTimes(1);
  });

  it("keeps VoiceGenerator available when only voice-profile projection fails", async () => {
    const overview = overviewWithVoiceActions();
    const harness = createReactHarness();
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn(async () => characterBinding()),
      listVoiceProfiles: vi.fn(async () => {
        throw new Error("profile projection unavailable");
      }),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overview),
      undefined,
      officialVoiceApi,
    );
    const props = { novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    const tree = harness.render(Card, props);

    expect(componentName(tree.props.generatorContent as FakeElement))
      .toBe("CharacterVoiceGenerator");
    expect(tree.props.currentVoice).toMatchObject({
      phase: "unresolved",
      message: "已保存人物声音绑定，但音色详情暂时不可用。",
    });
    const official = tree.props.officialVoiceContent as FakeElement;
    expect(official.props.projection).toEqual({
      phase: "ready",
      binding: characterBinding(),
      profiles: [],
    });
  });

  it("does not describe a dedicated unresolved binding as following rules", async () => {
    const harness = createReactHarness();
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn(async () => characterBinding()),
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overviewWithVoiceActions()),
      undefined,
      officialVoiceApi,
    );
    const props = { novelId: NOVEL_ID, characterId: CHARACTER_ID, characterName: "林岚" };

    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    harness.render(Card, props);
    harness.flushEffects();
    await settle();
    const tree = harness.render(Card, props);

    expect(tree.props.currentVoice).toMatchObject({
      phase: "unresolved",
      message: "已保存人物声音绑定，但音色详情暂时不可用。",
    });
  });

  it("ignores a late rejected projection after switching characters", async () => {
    const nextCharacterId = "123e4567-e89b-42d3-a456-426614174007";
    const nextProfileId = "123e4567-e89b-42d3-a456-426614174008";
    const nextVersionId = "123e4567-e89b-42d3-a456-426614174009";
    const baseNextProfile = voiceProfile();
    const nextProfile: VoiceProfileResource = {
      ...baseNextProfile,
      profile_id: nextProfileId,
      name: "冷静青年男声",
      current_version_id: nextVersionId,
      versions: baseNextProfile.versions.map((version) => ({
        ...version,
        profile_id: nextProfileId,
        version_id: nextVersionId,
      })),
    };
    const nextBinding = characterBinding({
      binding_id: "123e4567-e89b-42d3-a456-426614174010",
      character_id: nextCharacterId,
      profile_id: nextProfileId,
      version_id: nextVersionId,
      version: 4,
    });
    let rejectOldBinding: (reason: unknown) => void = () => undefined;
    const oldBinding = new Promise<CharacterVoiceBindingResource>((_resolve, reject) => {
      rejectOldBinding = reject;
    });
    const officialVoiceApi = {
      getCharacterVoiceBinding: vi.fn((_novelId: string, characterId: string) => (
        characterId === CHARACTER_ID ? oldBinding : Promise.resolve(nextBinding)
      )),
      listVoiceProfiles: vi.fn(async () => ({
        contract_version: NARRATION_SETTINGS_API_VERSION,
        items: [voiceProfile(), nextProfile],
      })),
      listOfficialVoicePresets: vi.fn(),
      selectOfficialVoice: vi.fn(),
      createOfficialVoicePreview: vi.fn(),
      getVoicePreview: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const harness = createReactHarness({ dependencyAware: true });
    const Card = createCharacterVoiceCardPanel(
      harness.React,
      vi.fn(async () => overviewWithVoiceActions()),
      undefined,
      officialVoiceApi,
    );
    const oldProps = {
      novelId: NOVEL_ID,
      characterId: CHARACTER_ID,
      characterName: "林岚",
    };
    const nextProps = {
      novelId: NOVEL_ID,
      characterId: nextCharacterId,
      characterName: "沈川",
    };

    harness.render(Card, oldProps);
    harness.flushEffects();
    await settle();
    harness.render(Card, oldProps);
    harness.flushEffects();
    await settle();
    harness.render(Card, nextProps);
    harness.flushEffects();
    await settle();
    harness.render(Card, nextProps);
    harness.flushEffects();
    await settle();
    let tree = harness.render(Card, nextProps);
    expect(tree.props.currentVoice).toMatchObject({
      phase: "resolved",
      name: "冷静青年男声",
    });

    rejectOldBinding(new Error("old scope failed late"));
    await settle();
    tree = harness.render(Card, nextProps);
    expect(tree.props.currentVoice).toMatchObject({
      phase: "resolved",
      name: "冷静青年男声",
    });
  });

  it("combines all six local style fragments and injects only once", () => {
    for (const selector of [
      ".anw-reading-page",
      ".anw-character-voice-panel",
      ".anw-narration-voice-source-panel",
      ".anw-voice-workspace",
      ".anw-narration-voice-preview-playback",
      ".anw-pronunciation-panel",
      ".anw-reading-rules-panel",
    ]) {
      expect(NARRATION_STYLES).toContain(selector);
    }
    expect(NARRATION_STYLES).toContain(".anw-character-voice-configurator__disclosure-body");
    expect(NARRATION_STYLES).toContain(".anw-character-voice-configurator__disclosure:not([open])");
    expect(NARRATION_STYLES).not.toContain(".anw-character-card-voice-match");

    const nodes = new Map<string, { id: string; dataset: Record<string, string>; textContent: string }>();
    const appended: unknown[] = [];
    const fakeDocument = {
      getElementById: (id: string) => nodes.get(id) ?? null,
      createElement: () => ({ id: "", dataset: {}, textContent: "" }),
      head: {
        appendChild: (node: { id: string; dataset: Record<string, string>; textContent: string }) => {
          nodes.set(node.id, node);
          appended.push(node);
        },
      },
    } as unknown as Document;
    const original = globalThis.document;
    Object.defineProperty(globalThis, "document", { configurable: true, value: fakeDocument });
    try {
      ensureNarrationStyles();
      ensureNarrationStyles();
      expect(appended).toHaveLength(1);
      expect(nodes.get(NARRATION_STYLE_ID)?.textContent).toBe(NARRATION_STYLES);
    } finally {
      Object.defineProperty(globalThis, "document", { configurable: true, value: original });
    }
  });
});
