import { describe, expect, it, vi } from "vitest";

import {
  CAPABILITY_KEYS,
  NARRATION_CACHE_SCHEMA_VERSION,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type FeatureCapability,
  type NarrationOverviewResponse,
  type NarrationScopeOverrideListResponse,
  type NarrationScopeOverrideResource,
  type NarrationSettingsResource,
} from "./contracts";
import {
  buildNarrationSettingsReplacement,
  buildScopeOverrideReplacement,
  createNarratorSettingsPanel,
  createReadingPage,
  createScopeOverridesPanel,
  emptyScopeOverrideValues,
  narratorOptionsForNovel,
  readingSectionFromSearch,
  readingSectionSearch,
  replaceScopeOverride,
  scopeTargetsForNovel,
  type ReadingPageApi,
  type ReadingPageReactRuntime,
  type ReadingSectionRenderContext,
  type ReadingScopeTarget,
} from "./reading-page";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function isFakeElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function createReactHarness() {
  const slots: Array<{ value: unknown }> = [];
  const refs: Array<{ current: unknown }> = [];
  let slotIndex = 0;
  let refIndex = 0;
  let effects: Array<() => void | (() => void)> = [];
  const React: ReadingPageReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return {
        type,
        props: (props ?? {}) as Record<string, unknown>,
        children,
      };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = slotIndex++;
      if (!slots[index]) {
        slots[index] = { value: typeof initial === "function" ? (initial as () => T)() : initial };
      }
      return [
        slots[index].value as T,
        (next) => {
          const current = slots[index].value as T;
          slots[index].value = typeof next === "function"
            ? (next as (value: T) => T)(current)
            : next;
        },
      ];
    },
    useEffect(effect): void {
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
      slotIndex = 0;
      refIndex = 0;
      effects = [];
      return Component(props) as FakeElement;
    },
    flushEffects(): readonly (() => void)[] {
      const cleanups: Array<() => void> = [];
      for (const effect of effects) {
        const cleanup = effect();
        if (cleanup) cleanups.push(cleanup);
      }
      effects = [];
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
const CHAPTER_ID = "123e4567-e89b-42d3-a456-426614174011";
const OVERRIDE_ID = "123e4567-e89b-42d3-a456-426614174012";
const PROFILE_ID = "123e4567-e89b-42d3-a456-426614174020";
const VERSION_ID = "123e4567-e89b-42d3-a456-426614174021";
const CHARACTER_ID = "123e4567-e89b-42d3-a456-426614174022";
const ZERO_SHA = "0".repeat(64);


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
  return {
    key,
    state: "unavailable",
    visible: false,
    actionable: false,
    reason_code: "T4_GATE_REQUIRED",
    required_gate: "T4-GATE",
  };
}


function enabledCapability(key: "narration_product" | "reading_settings"): FeatureCapability {
  return {
    key,
    state: "enabled",
    visible: true,
    actionable: true,
    reason_code: null,
    required_gate: null,
  };
}


function settingsResource(): NarrationSettingsResource {
  return {
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
    },
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
    settings: settingsResource(),
    coverage: {
      character_count: 0,
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
        reason_code: "T4_GATE_REQUIRED",
        accepted_mime_types: [],
        maximum_bytes: null,
      },
      {
        source_type: "uploaded",
        capability: "reference_clone",
        available: false,
        reason_code: "T4_GATE_REQUIRED",
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


function overrideFixture(): NarrationScopeOverrideResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    override_id: OVERRIDE_ID,
    novel_id: NOVEL_ID,
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


function scopeList(items: readonly NarrationScopeOverrideResource[] = []): NarrationScopeOverrideListResponse {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    items,
  };
}


function target(
  scopeKind: "volume" | "chapter" = "volume",
  scopeId = VOLUME_ID,
  novelId = NOVEL_ID,
): ReadingScopeTarget {
  return {
    novelId,
    scopeKind,
    scopeId,
    label: scopeKind === "volume" ? "第一卷" : "第一章",
  };
}


describe("reading route and replacement contracts", () => {
  it("keeps the stable workbench section and one bounded reading panel query", () => {
    expect(readingSectionFromSearch("?reading_panel=narrator")).toBe("narrator");
    expect(readingSectionFromSearch("?reading_panel=voice-generator")).toBe("overview");
    expect(readingSectionSearch("?novel_id=novel-1&section=roles&x=1", "audio-cache"))
      .toBe("?novel_id=novel-1&section=reading&x=1&reading_panel=audio-cache");
    expect(readingSectionSearch("?novel_id=novel-1&reading_panel=narrator", "overview"))
      .toBe("?novel_id=novel-1&section=reading");
  });

  it("drops cross-novel and duplicate scope targets before they can reach a PUT path", () => {
    const targets = scopeTargetsForNovel(NOVEL_ID, [
      target(),
      target(),
      target("chapter", CHAPTER_ID),
      target("chapter", "123e4567-e89b-42d3-a456-426614174099", OTHER_NOVEL_ID),
    ]);

    expect(targets.map((item) => `${item.scopeKind}:${item.scopeId}`)).toEqual([
      `volume:${VOLUME_ID}`,
      `chapter:${CHAPTER_ID}`,
    ]);
  });

  it("rejects narrator options whose runtime rights or lock claims are not exact true", () => {
    const unsafe = {
      novelId: NOVEL_ID,
      profileId: PROFILE_ID,
      versionId: VERSION_ID,
      label: "未授权旁白",
      locked: false,
      rightsActive: true,
    } as unknown as Parameters<typeof narratorOptionsForNovel>[1][number];

    expect(narratorOptionsForNovel(NOVEL_ID, [unsafe])).toEqual([]);
  });

  it("uses the current server version and full values for every replacement", () => {
    const settings = { ...settingsResource(), version: 7 };
    const changed = {
      ...settings.values,
      playback: { ...settings.values.playback, volume: 0.45 },
    };
    expect(buildNarrationSettingsReplacement(settings, changed)).toEqual({
      expected_version: 7,
      values: changed,
    });

    const current = overrideFixture();
    expect(buildScopeOverrideReplacement(
      NOVEL_ID,
      target(),
      current,
      false,
      current.overrides,
    )).toEqual({
      expected_version: 4,
      enabled: false,
      overrides: emptyScopeOverrideValues(),
    });
    expect(() => buildScopeOverrideReplacement(
      NOVEL_ID,
      target("volume", VOLUME_ID, OTHER_NOVEL_ID),
      undefined,
      true,
      current.overrides,
    )).toThrow("不属于当前作品");
  });

  it("rejects a saved override that drifts to another scope", () => {
    const saved = { ...overrideFixture(), scope_id: CHAPTER_ID };
    expect(() => replaceScopeOverride(NOVEL_ID, target(), [], saved))
      .toThrow("其他作品或范围");
  });
});


describe("reading page controller and navigation", () => {
  it("loads overview and overrides together, then exposes seven semantic navigation items", async () => {
    const harness = createReactHarness();
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => overviewFixture()),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const onSectionChange = vi.fn();
    const ReadingPage = createReadingPage(harness.React, api);
    let tree = harness.render(ReadingPage, { novelId: NOVEL_ID, onSectionChange });

    expect(tree.props.className).toContain("is-loading");
    harness.flushEffects();
    await Promise.resolve();
    await Promise.resolve();
    tree = harness.render(ReadingPage, { novelId: NOVEL_ID, onSectionChange });

    expect(api.getOverview).toHaveBeenCalledWith(NOVEL_ID, expect.any(AbortSignal));
    expect(api.listScopeOverrides).toHaveBeenCalledWith(NOVEL_ID, expect.any(AbortSignal));
    expect(tree.props["data-active-section"]).toBe("overview");
    const nav = findAll(tree, (element) => element.type === "nav")[0];
    const buttons = findAll(nav, (element) => element.type === "button");
    expect(buttons).toHaveLength(6);
    expect(buttons.filter((button) => button.props["aria-current"] === "page"))
      .toHaveLength(1);

    const narrator = buttons.find((button) => textContent(button) === "旁白");
    expect(narrator).toBeDefined();
    (narrator?.props.onClick as () => void)();
    tree = harness.render(ReadingPage, { novelId: NOVEL_ID, onSectionChange });
    expect(tree.props["data-active-section"]).toBe("narrator");
    expect(onSectionChange).toHaveBeenCalledWith("narrator");
  });

  it("fails closed when either response belongs to another novel", async () => {
    const harness = createReactHarness();
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => ({ ...overviewFixture(), novel_id: OTHER_NOVEL_ID })),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const ReadingPage = createReadingPage(harness.React, api);
    harness.render(ReadingPage, { novelId: NOVEL_ID });
    harness.flushEffects();
    await Promise.resolve();
    await Promise.resolve();
    const tree = harness.render(ReadingPage, { novelId: NOVEL_ID });
    const overviewElement = tree.children[0] as FakeElement;
    const state = overviewElement.props.state as { phase: string; message: string };

    expect(tree.props.className).toContain("is-error");
    expect(state.phase).toBe("error");
    expect(state.message).toContain("其他作品");
  });

  it("accepts other T2 modules only through the explicit local integration slot", async () => {
    const harness = createReactHarness();
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => overviewFixture()),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const ReadingPage = createReadingPage(harness.React, api);
    harness.render(ReadingPage, {
      novelId: NOVEL_ID,
      initialSection: "characters",
      sectionContent: { characters: "人物声音模块" },
    });
    harness.flushEffects();
    await Promise.resolve();
    await Promise.resolve();
    const tree = harness.render(ReadingPage, {
      novelId: NOVEL_ID,
      initialSection: "characters",
      sectionContent: { characters: "人物声音模块" },
    });

    expect(tree.props["data-active-section"]).toBe("characters");
    expect(textContent(tree)).toContain("人物声音模块");
    expect(textContent(tree)).not.toContain("不可用的演示按钮");
  });

  it("replaces the fixed T4 unavailable copy when chapter playback capabilities are enabled", async () => {
    const harness = createReactHarness();
    const enabledKeys = new Set([
      "narration_product",
      "reading_settings",
      "narration_synthesis",
      "product_player",
      "editor_production",
    ]);
    const overview = overviewFixture();
    const readyOverview: NarrationOverviewResponse = {
      ...overview,
      capabilities: {
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
      },
    };
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => readyOverview),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const ReadingPage = createReadingPage(harness.React, api);
    harness.render(ReadingPage, { novelId: NOVEL_ID });
    harness.flushEffects();
    await Promise.resolve();
    await Promise.resolve();
    const tree = harness.render(ReadingPage, { novelId: NOVEL_ID });

    expect(textContent(tree)).toContain("章节播放与校听已在章节写作页开放");
    expect(textContent(tree)).not.toContain("T4 完成后接入，目前不可用");
  });

  it("renders integrated panels from the exact loaded overview and shared navigation", async () => {
    const harness = createReactHarness();
    const overview = overviewFixture();
    const api: ReadingPageApi = {
      getOverview: vi.fn(async () => overview),
      listScopeOverrides: vi.fn(async () => scopeList()),
      putSettings: vi.fn(),
      putScopeOverride: vi.fn(),
    };
    const sharedContexts: ReadingSectionRenderContext[] = [];
    const renderSectionContent = vi.fn((
      section: "characters" | "casting-rules" | "pronunciation" | "audio-cache",
      context: ReadingSectionRenderContext,
    ) => {
      sharedContexts.push(context);
      return `已汇合：${section}`;
    });
    const ReadingPage = createReadingPage(harness.React, api);
    const props = {
      novelId: NOVEL_ID,
      initialSection: "characters" as const,
      renderSectionContent,
    };
    harness.render(ReadingPage, props);
    harness.flushEffects();
    await Promise.resolve();
    await Promise.resolve();
    let tree = harness.render(ReadingPage, props);

    expect(textContent(tree)).toContain("已汇合：characters");
    expect(renderSectionContent).toHaveBeenCalledWith("characters", expect.any(Object));
    expect(sharedContexts[0]?.overview).toBe(overview);

    sharedContexts[0]?.onNavigate("audio-cache");
    tree = harness.render(ReadingPage, props);
    expect(tree.props["data-active-section"]).toBe("audio-cache");
    expect(textContent(tree)).toContain("已汇合：audio-cache");
  });
});


describe("narrator and scope panels", () => {
  it("disables every narrator setting and exposes the stable gate reason", () => {
    const harness = createReactHarness();
    const Panel = createNarratorSettingsPanel(harness.React);
    const onSave = vi.fn();
    const tree = harness.render(Panel, {
      novelId: NOVEL_ID,
      resource: settingsResource(),
      capability: capability("reading_settings"),
      canConfigure: true,
      saving: false,
      narratorOptions: [],
      characterOptions: [],
      onSave,
    });

    const fieldsets = findAll(tree, (element) => element.type === "fieldset");
    expect(fieldsets.length).toBeGreaterThan(0);
    expect(fieldsets.every((item) => item.props.disabled === true)).toBe(true);
    const save = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "保存作品旁白")[0];
    expect(save.props.disabled).toBe(true);
    expect(String(save.props.title)).toContain("T2_GATE_REQUIRED");
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders a real empty scope state instead of inventing cross-novel targets", () => {
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const tree = harness.render(Panel, {
      novelId: NOVEL_ID,
      settings: settingsResource(),
      capability: capability("reading_settings"),
      canConfigure: true,
      saving: false,
      targets: [target("chapter", CHAPTER_ID, OTHER_NOVEL_ID)],
      overrides: [],
      narratorOptions: [],
      onSave: vi.fn(),
    });

    expect(tree.props["data-reading-state"]).toBe("empty");
    expect(textContent(tree)).toContain("没有可配置的分卷或章节");
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);
  });

  it("submits one complete narrator value object only after an approved option is selected", () => {
    const harness = createReactHarness();
    const Panel = createNarratorSettingsPanel(harness.React);
    const onSave = vi.fn();
    const props = {
      novelId: NOVEL_ID,
      resource: settingsResource(),
      capability: enabledCapability("reading_settings"),
      canConfigure: true,
      saving: false,
      narratorOptions: [{
        novelId: NOVEL_ID,
        profileId: PROFILE_ID,
        versionId: VERSION_ID,
        label: "已锁定旁白 A",
        locked: true,
        rightsActive: true,
      }] as const,
      characterOptions: [],
      onSave,
    };
    let tree = harness.render(Panel, props);
    const voiceSelect = findAll(tree, (element) => element.type === "select")[0];
    const languageInput = findAll(tree, (element) => element.type === "input"
      && element.props.type === "text")[0];
    (voiceSelect.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: `${PROFILE_ID}:${VERSION_ID}` },
    });
    (languageInput.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "zh-Hans" },
    });
    tree = harness.render(Panel, props);
    const save = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "保存作品旁白")[0];
    (save.props.onClick as () => void)();

    expect(save.props.disabled).toBe(false);
    expect(onSave).toHaveBeenCalledOnce();
    const values = onSave.mock.calls[0][0];
    expect(values.narrator).toEqual({ profile_id: PROFILE_ID, version_id: VERSION_ID });
    expect(values.language).toBe("zh-Hans");
    expect(values.output_format).toBe("m4a_aac_lc");
    expect(values.casting).toEqual(settingsResource().values.casting);
  });

  it("does not write a no-op or silently re-approve an unverified current narrator", () => {
    const harness = createReactHarness();
    const Panel = createNarratorSettingsPanel(harness.React);
    const onSave = vi.fn();
    const base = settingsResource();
    const resource = {
      ...base,
      values: {
        ...base.values,
        narrator: { profile_id: PROFILE_ID, version_id: VERSION_ID },
      },
    };
    const props = {
      novelId: NOVEL_ID,
      resource,
      capability: enabledCapability("reading_settings"),
      canConfigure: true,
      saving: false,
      narratorOptions: [],
      characterOptions: [],
      onSave,
    };
    let tree = harness.render(Panel, props);
    let save = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "保存作品旁白")[0];

    expect(save.props.disabled).toBe(true);
    expect(textContent(tree)).toContain("资格待重新核验");
    const voiceSelect = findAll(tree, (element) => element.type === "select")[0];
    (voiceSelect.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "" },
    });
    tree = harness.render(Panel, props);
    save = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "保存作品旁白")[0];
    expect(save.props.disabled).toBe(false);
  });

  it("disables a no-op scope write and fences old draft values while switching targets", () => {
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const props = {
      novelId: NOVEL_ID,
      settings: settingsResource(),
      capability: enabledCapability("reading_settings"),
      canConfigure: true,
      saving: false,
      targets: [target(), target("chapter", CHAPTER_ID)],
      overrides: [overrideFixture()],
      narratorOptions: [{
        novelId: NOVEL_ID,
        profileId: PROFILE_ID,
        versionId: VERSION_ID,
        label: "已核验旁白",
        locked: true,
        rightsActive: true,
      }] as const,
      characterOptions: [],
      onSave: vi.fn(),
    };
    let tree = harness.render(Panel, props);
    let save = findAll(tree, (element) => element.type === "button"
      && textContent(element).includes("保存范围覆盖"))[0];
    expect(save.props.disabled).toBe(true);

    const targetSelect = findAll(tree, (element) => element.type === "select")[0];
    (targetSelect.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: `chapter:${CHAPTER_ID}` },
    });
    tree = harness.render(Panel, props);
    save = findAll(tree, (element) => element.type === "button")[0];
    expect(save.props.disabled).toBe(true);
  });

  it("edits complete scope text rules instead of merely copying a frozen global value", () => {
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const onSave = vi.fn();
    const props = {
      novelId: NOVEL_ID,
      settings: settingsResource(),
      capability: enabledCapability("reading_settings"),
      canConfigure: true,
      saving: false,
      targets: [target()],
      overrides: [overrideFixture()],
      narratorOptions: [{
        novelId: NOVEL_ID,
        profileId: PROFILE_ID,
        versionId: VERSION_ID,
        label: "已核验旁白",
        locked: true,
        rightsActive: true,
      }] as const,
      characterOptions: [{
        novelId: NOVEL_ID,
        characterId: CHARACTER_ID,
        label: "林夏",
      }],
      onSave,
    };
    let tree = harness.render(Panel, props);
    const ruleToggle = findAll(tree, (element) => element.type === "input"
      && element.props.type === "checkbox")[1];
    (ruleToggle.props.onChange as (event: { target: { checked: boolean } }) => void)({
      target: { checked: true },
    });
    tree = harness.render(Panel, props);

    expect(textContent(tree)).toContain("朗读章节标题");
    expect(textContent(tree)).toContain("内心独白");
    const save = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "保存范围覆盖")[0];
    expect(save.props.disabled).toBe(false);
  });

  it("closes an existing scope override with its current CAS version and an empty replacement", () => {
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const onSave = vi.fn();
    const props = {
      novelId: NOVEL_ID,
      settings: settingsResource(),
      capability: enabledCapability("reading_settings"),
      canConfigure: true,
      saving: false,
      targets: [target()],
      overrides: [overrideFixture()],
      narratorOptions: [],
      onSave,
    };
    let tree = harness.render(Panel, props);
    const enabledCheckbox = findAll(tree, (element) => element.type === "input"
      && element.props.type === "checkbox")[0];
    (enabledCheckbox.props.onChange as (event: { target: { checked: boolean } }) => void)({
      target: { checked: false },
    });
    tree = harness.render(Panel, props);
    const save = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "关闭并清空覆盖")[0];
    (save.props.onClick as () => void)();

    expect(onSave).toHaveBeenCalledWith(target(), {
      expected_version: 4,
      enabled: false,
      overrides: emptyScopeOverrideValues(),
    });
  });
});
