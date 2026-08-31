import { describe, expect, it, vi } from "vitest";

import { createCachePanel, type CachePanelReactRuntime } from "./cache-panel";
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
} from "./contracts";
import {
  createPronunciationPanel,
  type PronunciationPanelReactRuntime,
} from "./pronunciation-panel";
import { createReadingOverview } from "./reading-overview";
import {
  createReadingRulesPanel,
  type ReadingRulesReactRuntime,
} from "./reading-rules-panel";
import { createReadingStatus } from "./reading-status";
import {
  createReadingPage,
  type ReadingPageApi,
  type ReadingPageReactRuntime,
} from "./reading-page";
import { T2_B_READING_STYLES } from "./styles/t2-b";
import {
  T2_G_NARRATION_READING_RULES_STYLES,
  T2_G_NARRATION_STYLE_ID,
} from "./styles/t2-g";
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
    flushEffects(): void {
      const pending = effects;
      effects = [];
      pending.forEach((effect) => effect());
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


function elementById(root: unknown, id: unknown): FakeElement | undefined {
  if (typeof id !== "string") return undefined;
  return findAll(root, (element) => element.props.id === id)[0];
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";
const CHARACTER_ID = "123e4567-e89b-42d3-a456-426614174022";
const ZERO_SHA = "0".repeat(64);


function capability(key: typeof CAPABILITY_KEYS[number]): FeatureCapability {
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


function overviewFixture(): NarrationOverviewResponse {
  const capabilities = {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map(capability),
  } as const;
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    capabilities,
    authorization: authorization(),
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
      novel_id: NOVEL_ID,
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


function scopeList(): NarrationScopeOverrideListResponse {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    items: [],
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


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}


describe("reading page accessibility contract", () => {
  it("announces loading and errors, then exposes the stable gated reason", () => {
    const harness = createReactHarness();
    const Overview = createReadingOverview(harness.React);
    const loading = harness.render(Overview, { state: { phase: "loading" } });
    expect(loading.props.role).toBe("status");
    expect(loading.props["aria-live"]).toBe("polite");
    expect(loading.props["aria-busy"]).toBe(true);

    const retry = vi.fn();
    const error = harness.render(Overview, {
      state: { phase: "error", message: "网络不可用", onRetry: retry },
    });
    expect(error.props.role).toBe("alert");
    const retryButton = findAll(error, (element) => element.type === "button")[0];
    expect(retryButton.props.type).toBe("button");
    (retryButton.props.onClick as () => void)();
    expect(retry).toHaveBeenCalledOnce();

    const gated = harness.render(Overview, {
      state: { phase: "ready", overview: overviewFixture() },
    });
    expect(gated.props.role).toBe("region");
    expect(gated.props["aria-labelledby"]).toBe("anw-reading-overview-heading");
    expect(gated.props["data-reading-state"]).toBe("gated");
    const gate = findAll(gated, (element) => element.props["data-reason-code"] === "T2_GATE_REQUIRED")[0];
    expect(gate.props.role).toBe("status");
    const actions = findAll(gated, (element) => element.type === "button");
    expect(actions.length).toBeGreaterThan(0);
    expect(actions.every((button) => button.props.type === "button")).toBe(true);
    expect(actions.every((button) => button.props.disabled === true)).toBe(true);
    expect(actions.every((button) => String(button.props.title).includes("T2_GATE_REQUIRED"))).toBe(true);
  });

  it("uses native keyboard navigation and stable responsive hook classes", async () => {
    const harness = createReactHarness();
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => overviewFixture()),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const ReadingPage = createReadingPage(harness.React, api);
    harness.render(ReadingPage, { novelId: NOVEL_ID });
    harness.flushEffects();
    await settle();
    const tree = harness.render(ReadingPage, { novelId: NOVEL_ID });

    expect(tree.props.className).toBe("anw-reading-page");
    const layout = findAll(tree, (element) => element.props.className === "anw-reading-layout")[0];
    const nav = findAll(layout, (element) => element.type === "nav")[0];
    expect(nav.props.className).toBe("anw-reading-nav");
    expect(nav.props["aria-label"]).toBe("朗读设置");
    const buttons = findAll(nav, (element) => element.type === "button");
    expect(buttons).toHaveLength(5);
    expect(buttons.every((button) => button.props.type === "button")).toBe(true);
    expect(buttons.every((button) => button.props.role === undefined)).toBe(true);
    expect(buttons.every((button) => button.props.tabIndex !== -1)).toBe(true);
    expect(buttons.filter((button) => button.props["aria-current"] === "page")).toHaveLength(1);
    expect(findAll(tree, (element) => element.props.role === "button")).toHaveLength(0);

    expect(T2_B_READING_STYLES).toContain("@media (max-width: 760px)");
    expect(T2_B_READING_STYLES).toContain("@container (max-width: 900px)");
    expect(T2_B_READING_STYLES).toContain(".anw-reading-layout");
    expect(T2_B_READING_STYLES).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(T2_B_READING_STYLES).toContain(".anw-reading-nav");
    expect(T2_B_READING_STYLES).toContain("@container (max-width: 520px)");
    expect(T2_B_READING_STYLES).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(T2_B_READING_STYLES).toContain("overflow-x: auto");
    expect(T2_B_READING_STYLES).toContain(":focus-visible");
    expect(T2_B_READING_STYLES).toContain("prefers-reduced-motion");
    expect(T2_G_NARRATION_STYLE_ID).toBe("ai-novel-world-narration-t2-g-styles");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain(".anw-reading-rules-panel");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain(".anw-reading-status");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain(":focus-visible");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain("@media (max-width: 560px)");
  });

  it("keeps every existing local panel labelled while disabled controls explain why", () => {
    const overview = overviewFixture();
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
    expect(character.props.role).toBe("region");
    expect(elementById(character, character.props["aria-labelledby"])).toBeDefined();
    const characterStatus = elementById(character, character.props["aria-describedby"]);
    expect(characterStatus?.props.role).toBe("status");
    expect(characterStatus?.props["aria-live"]).toBe("polite");

    const voiceHarness = createReactHarness();
    const voiceSource = renderVoiceSourcePanel(overview, voiceHarness.React);
    expect(elementById(voiceSource, voiceSource.props["aria-labelledby"])).toBeDefined();
    expect(textContent(voiceSource)).not.toContain("文字描述生成");
    const sourceButtons = findAll(voiceSource, (element) => (
      element.type === "button" && textContent(element) === "选择来源"
    ));
    expect(sourceButtons).toHaveLength(0);
    expect(textContent(voiceSource)).toContain("官方音色请在上方音色库直接使用");

    const pronunciationHarness = createReactHarness();
    const PronunciationPanel = createPronunciationPanel(pronunciationHarness.React);
    const pronunciation = pronunciationHarness.render(PronunciationPanel, {
      novelId: NOVEL_ID,
      capabilities: overview.capabilities,
      authorization: blockedAuthorization,
      scopeOptions: [],
      timing: overview.settings.values.timing,
    });
    expect(pronunciation.props.role).toBe("region");
    expect(elementById(pronunciation, pronunciation.props["aria-labelledby"])).toBeDefined();
    expect(elementById(pronunciation, pronunciation.props["aria-describedby"])?.props.role)
      .toBe("status");

    const cacheHarness = createReactHarness();
    const CachePanel = createCachePanel(cacheHarness.React);
    const cache = cacheHarness.render(CachePanel, {
      novelId: NOVEL_ID,
      capabilities: overview.capabilities,
      authorization: blockedAuthorization,
    });
    expect(cache.props.role).toBe("region");
    expect(elementById(cache, cache.props["aria-labelledby"])).toBeDefined();
    expect(elementById(cache, cache.props["aria-describedby"])?.props.role).toBe("status");

    const rulesHarness = createReactHarness();
    const ReadingRulesPanel = createReadingRulesPanel(rulesHarness.React);
    const rules = rulesHarness.render(ReadingRulesPanel, {
      novelId: NOVEL_ID,
      settings: overview.settings,
      capabilities: overview.capabilities,
      authorization: overview.authorization,
    });
    expect(elementById(rules, rules.props["aria-labelledby"])).toBeDefined();
    expect(findAll(rules, (element) => element.props.role === "note")).toHaveLength(1);
    const ruleFieldsets = findAll(rules, (element) => element.type === "fieldset");
    expect(ruleFieldsets).toHaveLength(2);
    expect(ruleFieldsets.every((fieldset) => fieldset.props.disabled === true)).toBe(true);
    const ruleButtons = findAll(rules, (element) => element.type === "button");
    expect(ruleButtons.length).toBeGreaterThan(0);
    expect(ruleButtons.every((button) => button.props.disabled === true)).toBe(true);

    const statusHarness = createReactHarness();
    const ReadingStatus = createReadingStatus(statusHarness.React);
    const status = statusHarness.render(ReadingStatus, {
      overview,
      onOpenSection: vi.fn(),
    });
    expect(elementById(status, status.props["aria-labelledby"])).toBeDefined();
    expect(findAll(status, (element) => element.props["data-severity"] === "blocker").length)
      .toBeGreaterThan(0);

    const localTrees = [character, voiceSource, pronunciation, cache, rules, status];
    const nativeButtons = localTrees.flatMap((root) => findAll(root, (element) => (
      element.type === "button"
    )));
    expect(nativeButtons.every((button) => button.props.type === "button")).toBe(true);
    expect(localTrees.flatMap((root) => findAll(root, (element) => element.props.role === "button")))
      .toHaveLength(0);
  });
});
