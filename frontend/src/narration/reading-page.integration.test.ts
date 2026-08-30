import { describe, expect, it, vi } from "vitest";

import {
  createCachePanel,
  type CachePanelApi,
  type CachePanelReactRuntime,
} from "./cache-panel";
import {
  createCharacterVoicePanel,
  type CharacterVoicePanelReactRuntime,
} from "./character-voice-panel";
import {
  CAPABILITY_KEYS,
  NARRATION_CACHE_SCHEMA_VERSION,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type FeatureCapability,
  type NarrationAuthorizationState,
  type NarrationOverviewResponse,
  type NarrationScopeOverrideListResponse,
  type NarrationScopeOverrideResource,
  type NarrationSettingsResource,
} from "./contracts";
import {
  createPronunciationPanel,
  type PronunciationPanelApi,
  type PronunciationPanelReactRuntime,
} from "./pronunciation-panel";
import {
  createReadingRulesPanel,
  type ReadingRulesPanelApi,
  type ReadingRulesReactRuntime,
} from "./reading-rules-panel";
import { createReadingStatus } from "./reading-status";
import {
  createReadingPage,
  emptyScopeOverrideValues,
  type ReadingPageApi,
  type ReadingPageReactRuntime,
  type ReadingScopeTarget,
} from "./reading-page";
import {
  IDLE_VOICE_SOURCE_WORKFLOW,
  VoiceSourcePanel,
  createVoiceSourcePanelModel,
} from "./voice-source-panel";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function isFakeElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


type TestReactRuntime = ReadingPageReactRuntime
  & CharacterVoicePanelReactRuntime
  & PronunciationPanelReactRuntime
  & CachePanelReactRuntime
  & ReadingRulesReactRuntime;


function createReactHarness() {
  const stateSlots: Array<{ value: unknown }> = [];
  const refSlots: Array<{ current: unknown }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effects: Array<() => void | (() => void)> = [];
  const React: TestReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!stateSlots[index]) {
        stateSlots[index] = {
          value: typeof initial === "function" ? (initial as () => T)() : initial,
        };
      }
      return [
        stateSlots[index].value as T,
        (next) => {
          const current = stateSlots[index].value as T;
          stateSlots[index].value = typeof next === "function"
            ? (next as (value: T) => T)(current)
            : next;
        },
      ];
    },
    useEffect(effect, _dependencies): void {
      effects.push(effect);
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refSlots[index]) refSlots[index] = { current: initial };
      return refSlots[index] as { current: T };
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effects = [];
      return Component(props) as FakeElement;
    },
    flushEffects(): readonly (() => void)[] {
      const cleanups: Array<() => void> = [];
      const pending = effects;
      effects = [];
      for (const effect of pending) {
        const cleanup = effect();
        if (cleanup) cleanups.push(cleanup);
      }
      return cleanups;
    },
  };
}


function findAll(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): readonly FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isFakeElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isFakeElement(root)) return "";
  return root.children.map(textContent).join("");
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";
const OTHER_NOVEL_ID = "123e4567-e89b-42d3-a456-426614174001";
const VOLUME_ID = "123e4567-e89b-42d3-a456-426614174010";
const PROFILE_ID = "123e4567-e89b-42d3-a456-426614174020";
const VERSION_ID = "123e4567-e89b-42d3-a456-426614174021";
const CHARACTER_ID = "123e4567-e89b-42d3-a456-426614174022";
const ZERO_SHA = "0".repeat(64);


function capability(key: typeof CAPABILITY_KEYS[number], enabled = false): FeatureCapability {
  if (enabled && (key === "narration_product" || key === "reading_settings")) {
    return {
      key,
      state: "enabled",
      visible: true,
      actionable: true,
      reason_code: null,
      required_gate: null,
    };
  }
  if (key === "voice_generator") {
    return {
      key,
      state: "unavailable",
      visible: false,
      actionable: false,
      reason_code: "VOICE_GENERATOR_NO_GO",
      required_gate: "T5-GATE",
    };
  }
  const visible = key === "narration_product"
    || key === "reading_settings"
    || key === "generic_voice_pool"
    || key === "preset_voice_source"
    || key === "cache_cleanup";
  return {
    key,
    state: key === "narration_product" || key === "reading_settings" ? "hold" : "unavailable",
    visible,
    actionable: false,
    reason_code: key === "generic_voice_pool"
      ? "GENERIC_VOICE_ASSETS_UNAVAILABLE"
      : "T2_GATE_REQUIRED",
    required_gate: "T2-GATE",
  };
}


function authorization(canRead = true): NarrationAuthorizationState {
  return {
    mode: "fixed_local_owner_workspace",
    can_read: canRead,
    can_configure: canRead,
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
  };
}


function settingsResource(novelId = NOVEL_ID): NarrationSettingsResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: novelId,
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
      timing: {
        sentence_gap_ms: 250,
        paragraph_gap_ms: 650,
        section_gap_ms: 1_000,
      },
      casting: {
        anonymous_reuse_scope: "scene",
        same_scene_voice_deduplication: true,
        unknown_speaker_action: "block",
      },
      playback: { playback_rate: 1, volume: 0.8 },
    },
    updated_at: null,
  };
}


function overviewFixture(options: {
  readonly enabled?: boolean;
  readonly novelId?: string;
  readonly canRead?: boolean;
} = {}): NarrationOverviewResponse {
  const novelId = options.novelId ?? NOVEL_ID;
  const capabilities = {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map((key) => capability(key, options.enabled ?? false)),
  } as const;
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: novelId,
    capabilities,
    authorization: authorization(options.canRead ?? true),
    runtime: {
      technical_enabled: false,
      lifecycle_status: "disabled",
      sidecar_reachable: false,
      model_ready: false,
      product_visible: false,
      protocol_version: "1.1",
      model_fingerprint_sha256: null,
      reason_code: "T2_GATE_REQUIRED",
    },
    settings: settingsResource(novelId),
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
    cache: {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      schema_version: NARRATION_CACHE_SCHEMA_VERSION,
      novel_id: novelId,
      snapshot_fingerprint: ZERO_SHA,
      source_asset_bytes: 0,
      locked_voice_bytes: 0,
      referenced_edition_bytes: 0,
      derived_cache_bytes: 0,
      reclaimable_bytes: 0,
      pending_job_count: 0,
      disk_free_bytes: 1024,
      disk_total_bytes: 2048,
      cleanup_capability: capability("cache_cleanup"),
    },
  };
}


function scopeList(
  items: readonly NarrationScopeOverrideResource[] = [],
  novelId = NOVEL_ID,
): NarrationScopeOverrideListResponse {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: novelId,
    items,
  };
}


function target(): ReadingScopeTarget {
  return {
    novelId: NOVEL_ID,
    scopeKind: "volume",
    scopeId: VOLUME_ID,
    label: "第一卷",
  };
}


function overrideFixture(novelId = NOVEL_ID): NarrationScopeOverrideResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    override_id: "123e4567-e89b-42d3-a456-426614174030",
    novel_id: novelId,
    scope_kind: "volume",
    scope_id: VOLUME_ID,
    enabled: true,
    version: 4,
    overrides: {
      narrator: { profile_id: PROFILE_ID, version_id: VERSION_ID },
      language: null,
      text_rules: null,
      timing: null,
    },
  };
}


function renderVoiceSourcePanel(
  overview: NarrationOverviewResponse,
  React: TestReactRuntime,
): FakeElement {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { QwenPaw: { host: { React } } },
  });
  try {
    const model = createVoiceSourcePanelModel({
      capabilities: overview.capabilities,
      authorization: overview.authorization,
      voiceSources: overview.voice_sources,
      profile: null,
      selectedVersionId: null,
    });
    return VoiceSourcePanel({
      model,
      selectedSource: null,
      workflow: IDLE_VOICE_SOURCE_WORKFLOW,
      uploadRights: {
        noticeVersion: "voice-rights/1",
        sourceIdentifier: "",
        commercialUse: false,
        redistribution: false,
        voiceCloningConfirmed: false,
        subjectConsentReference: null,
        rightsConfirmed: false,
      },
    }) as FakeElement;
  } finally {
    if (descriptor === undefined) delete (globalThis as { window?: unknown }).window;
    else Object.defineProperty(globalThis, "window", descriptor);
  }
}


function localSectionContent(overview: NarrationOverviewResponse) {
  const blockedAuthorization = authorization(false);
  const characterHarness = createReactHarness();
  const CharacterPanel = createCharacterVoicePanel(characterHarness.React);
  const character = characterHarness.render(CharacterPanel, {
    novelId: NOVEL_ID,
    characterId: CHARACTER_ID,
    characterName: "林夏",
    capabilities: overview.capabilities,
    authorization: blockedAuthorization,
  });
  const pronunciationHarness = createReactHarness();
  const PronunciationPanel = createPronunciationPanel(pronunciationHarness.React);
  const pronunciation = pronunciationHarness.render(PronunciationPanel, {
    novelId: NOVEL_ID,
    capabilities: overview.capabilities,
    authorization: blockedAuthorization,
    scopeOptions: [],
    timing: overview.settings.values.timing,
  });
  const cacheHarness = createReactHarness();
  const CachePanel = createCachePanel(cacheHarness.React);
  const cache = cacheHarness.render(CachePanel, {
    novelId: NOVEL_ID,
    capabilities: overview.capabilities,
    authorization: blockedAuthorization,
  });
  const rulesHarness = createReactHarness();
  const ReadingRulesPanel = createReadingRulesPanel(rulesHarness.React);
  const rules = rulesHarness.render(ReadingRulesPanel, {
    novelId: NOVEL_ID,
    settings: overview.settings,
    capabilities: overview.capabilities,
    authorization: overview.authorization,
  });
  const statusHarness = createReactHarness();
  const ReadingStatus = createReadingStatus(statusHarness.React);
  const status = statusHarness.render(ReadingStatus, { overview });
  const voiceHarness = createReactHarness();
  return {
    characters: [character, renderVoiceSourcePanel(overview, voiceHarness.React)],
    narrator: [status, rules, pronunciation],
    "private-voices": cache,
  } as const;
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}


describe("reading page local-module integration", () => {
  it("composes the existing T2-B–T2-G panels without making gated capabilities actionable", async () => {
    const harness = createReactHarness();
    const overview = overviewFixture();
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => overview),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const ReadingPage = createReadingPage(harness.React, api);
    const sectionContent = localSectionContent(overview);
    const props = {
      novelId: NOVEL_ID,
      initialSection: "characters" as const,
      sectionContent,
      renderNarratorVoiceWorkspace: () => sectionContent.narrator,
    };
    let tree = harness.render(ReadingPage, props);

    expect(tree.props.className).toContain("is-loading");
    harness.flushEffects();
    await settle();
    tree = harness.render(ReadingPage, props);

    expect(textContent(tree)).toContain("人物卡 · 声音");
    expect(textContent(tree)).toContain("音色来源");
    expect(textContent(tree)).not.toContain("文字描述生成");
    const sourceButtons = findAll(tree, (element) => (
      element.type === "button" && textContent(element) === "选择来源"
    ));
    expect(sourceButtons).toHaveLength(0);
    expect(textContent(tree)).toContain("官方音色请在上方音色库直接使用");

    const navButtons = findAll(tree, (element) => element.type === "button"
      && typeof element.props["data-reading-section"] === "string");
    const open = (key: string) => {
      const button = navButtons.find((item) => item.props["data-reading-section"] === key);
      expect(button).toBeDefined();
      (button?.props.onClick as () => void)();
      tree = harness.render(ReadingPage, props);
    };

    open("narrator");
    expect(textContent(tree)).toContain("发音与停顿");
    expect(textContent(tree)).toContain("无权查看发音与停顿设置");
    expect(textContent(tree)).toContain("朗读运行状态");
    expect(textContent(tree)).toContain("识别、选角与复核规则");
    expect(textContent(tree)).toContain("当前只读：T2_GATE_REQUIRED");
    const ruleFieldsets = findAll(tree, (element) => element.type === "fieldset");
    expect(ruleFieldsets).toHaveLength(2);
    expect(ruleFieldsets.every((fieldset) => fieldset.props.disabled === true)).toBe(true);

    open("private-voices");
    expect(textContent(tree)).toContain("音频与缓存");
    expect(textContent(tree)).toContain("无权查看音频与缓存");
  });

  it("wires the compact scope editor to the scoped CAS API and refresh action", async () => {
    const harness = createReactHarness();
    const overview = overviewFixture({ enabled: true });
    const putScopeOverride = vi.fn(async () => overrideFixture(OTHER_NOVEL_ID));
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => overview),
      listScopeOverrides: vi.fn(async () => scopeList([overrideFixture()])),
      putSettings: vi.fn(),
      putScopeOverride,
    };
    const ReadingPage = createReadingPage(harness.React, api);
    const props = {
      novelId: NOVEL_ID,
      initialSection: "narrator" as const,
      scopeTargets: [target()],
    };
    harness.render(ReadingPage, props);
    harness.flushEffects();
    await settle();
    let tree = harness.render(ReadingPage, props);
    const scopeElement = findAll(tree, (element) => (
      typeof element.type === "function" && "targets" in element.props && "saveOverride" in element.props
    ))[0];
    expect(scopeElement).toBeDefined();
    expect(scopeElement.props.saveOverride).toBe(putScopeOverride);
    expect(scopeElement.props.targets).toEqual([target()]);
    (scopeElement.props.onRefresh as () => void)();

    harness.render(ReadingPage, props);
    harness.flushEffects();
    await settle();
    tree = harness.render(ReadingPage, props);
    expect(api.getOverview).toHaveBeenCalledTimes(2);
    expect(textContent(tree)).not.toContain("不匹配的范围配置");
  });

  it("retries a real load error and never reuses a response from another novel", async () => {
    const harness = createReactHarness();
    const getOverview = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(overviewFixture());
    const api: ReadingPageApi = {
      getOverview,
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const ReadingPage = createReadingPage(harness.React, api);
    const props = { novelId: NOVEL_ID };
    harness.render(ReadingPage, props);
    harness.flushEffects();
    await settle();
    let tree = harness.render(ReadingPage, props);

    expect(tree.props.className).toContain("is-error");
    const overviewElement = tree.children[0] as FakeElement;
    const ErrorOverview = overviewElement.type as (
      props: { readonly state: { readonly onRetry?: () => void } },
    ) => unknown;
    const errorTree = ErrorOverview(overviewElement.props as {
      readonly state: { readonly onRetry?: () => void };
    });
    const retry = findAll(errorTree, (element) => (
      element.type === "button" && textContent(element) === "重新加载"
    ))[0];
    (retry.props.onClick as () => void)();

    harness.render(ReadingPage, props);
    harness.flushEffects();
    await settle();
    tree = harness.render(ReadingPage, props);
    expect(getOverview).toHaveBeenCalledTimes(2);
    expect(tree.props.className).toBe("anw-reading-page");

    const driftApi: ReadingPageApi = {
      ...api,
      getOverview: vi.fn(async () => overviewFixture({ novelId: OTHER_NOVEL_ID })),
    };
    const driftHarness = createReactHarness();
    const DriftPage = createReadingPage(driftHarness.React, driftApi);
    driftHarness.render(DriftPage, props);
    driftHarness.flushEffects();
    await settle();
    const driftTree = driftHarness.render(DriftPage, props);
    expect(driftTree.props.className).toContain("is-error");
    const state = (driftTree.children[0] as FakeElement).props.state as {
      readonly phase: string;
      readonly message: string;
    };
    expect(state.message).toContain("其他作品");
  });

  it("aborts both page loading requests on unmount", async () => {
    const loadHarness = createReactHarness();
    const loadSignals: AbortSignal[] = [];
    const neverOverview = (_novelId: string, signal?: AbortSignal) => {
      if (signal) loadSignals.push(signal);
      return new Promise<NarrationOverviewResponse>(() => undefined);
    };
    const neverScopes = (_novelId: string, signal?: AbortSignal) => {
      if (signal) loadSignals.push(signal);
      return new Promise<NarrationScopeOverrideListResponse>(() => undefined);
    };
    const loadApi: ReadingPageApi = {
      getOverview: neverOverview,
      listScopeOverrides: neverScopes,
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const LoadingPage = createReadingPage(loadHarness.React, loadApi);
    loadHarness.render(LoadingPage, { novelId: NOVEL_ID });
    const loadingCleanups = loadHarness.flushEffects();
    expect(loadSignals).toHaveLength(2);
    loadingCleanups.forEach((cleanup) => cleanup());
    expect(loadSignals.every((signal) => signal.aborted)).toBe(true);

  });

  it("aborts pending T2-F loads and a pending T2-G rules save on unmount", () => {
    let pronunciationSignal: AbortSignal | undefined;
    const pronunciationFocus = vi.fn();
    const pronunciationApi: PronunciationPanelApi = {
      getPronunciationProfile: (_novelId, signal) => {
        pronunciationSignal = signal;
        return new Promise<never>(() => undefined);
      },
      putPronunciationProfile: async () => {
        throw new Error("unused pronunciation write");
      },
    };
    const pronunciationHarness = createReactHarness();
    const PronunciationPanel = createPronunciationPanel(
      pronunciationHarness.React,
      pronunciationApi,
    );
    pronunciationHarness.render(PronunciationPanel, {
      novelId: NOVEL_ID,
      capabilities: overviewFixture().capabilities,
      authorization: authorization(),
      scopeOptions: [],
      timing: settingsResource().values.timing,
      onReturnFocus: pronunciationFocus,
    });
    const pronunciationCleanups = pronunciationHarness.flushEffects();
    expect(pronunciationSignal?.aborted).toBe(false);
    pronunciationCleanups.forEach((cleanup) => cleanup());
    expect(pronunciationSignal?.aborted).toBe(true);
    expect(pronunciationFocus).toHaveBeenCalledOnce();

    let cacheSignal: AbortSignal | undefined;
    const cacheFocus = vi.fn();
    const cacheApi: CachePanelApi = {
      getNarrationCacheStatus: (_novelId, signal) => {
        cacheSignal = signal;
        return new Promise<never>(() => undefined);
      },
      previewNarrationCacheCleanup: async () => {
        throw new Error("unused cache preview");
      },
      executeNarrationCacheCleanup: async () => {
        throw new Error("unused cache cleanup");
      },
    };
    const cacheHarness = createReactHarness();
    const CachePanel = createCachePanel(cacheHarness.React, cacheApi);
    cacheHarness.render(CachePanel, {
      novelId: NOVEL_ID,
      capabilities: overviewFixture().capabilities,
      authorization: authorization(),
      onReturnFocus: cacheFocus,
    });
    const cacheCleanups = cacheHarness.flushEffects();
    expect(cacheSignal?.aborted).toBe(false);
    cacheCleanups.forEach((cleanup) => cleanup());
    expect(cacheSignal?.aborted).toBe(true);
    expect(cacheFocus).toHaveBeenCalledOnce();

    let rulesSignal: AbortSignal | undefined;
    const rulesApi: ReadingRulesPanelApi = {
      putSettings: (_novelId, _payload, signal) => {
        rulesSignal = signal;
        return new Promise<never>(() => undefined);
      },
      createCloudConsent: async () => {
        throw new Error("unused cloud consent create");
      },
      revokeCloudConsent: async () => {
        throw new Error("unused cloud consent revoke");
      },
    };
    const enabled = overviewFixture({ enabled: true });
    const rulesHarness = createReactHarness();
    const ReadingRulesPanel = createReadingRulesPanel(rulesHarness.React, rulesApi);
    const rulesProps = {
      novelId: NOVEL_ID,
      settings: enabled.settings,
      capabilities: enabled.capabilities,
      authorization: enabled.authorization,
    };
    let rulesTree = rulesHarness.render(ReadingRulesPanel, rulesProps);
    const rulesCleanups = rulesHarness.flushEffects();
    const reviewRadios = findAll(rulesTree, (element) => (
      element.type === "input" && element.props.name === "narration-review-policy"
    ));
    const alwaysReview = reviewRadios.find((radio) => radio.props.value === "always_review");
    expect(alwaysReview).toBeDefined();
    (alwaysReview?.props.onChange as (
      event: { readonly target: { readonly value: string; readonly checked: boolean } },
    ) => void)({ target: { value: "always_review", checked: true } });
    rulesTree = rulesHarness.render(ReadingRulesPanel, rulesProps);
    const save = findAll(rulesTree, (element) => (
      element.type === "button" && textContent(element) === "保存识别与复核规则"
    ))[0];
    expect(save.props.disabled).toBe(false);
    (save.props.onClick as () => void)();
    expect(rulesSignal?.aborted).toBe(false);
    rulesCleanups.forEach((cleanup) => cleanup());
    expect(rulesSignal?.aborted).toBe(true);
  });
});
