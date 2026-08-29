import { describe, expect, it, vi } from "vitest";

import { NarrationApiError } from "./api";
import {
  CAPABILITY_KEYS,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type FeatureCapability,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type NarrationSettingsResource,
} from "./contracts";
import {
  READING_PAUSE_PRESETS,
  buildReadingBaseSettingsRequest,
  buildReadingPlaybackPreferencesRequest,
  classifyReadingPreferencesFailure,
  createReadingPreferencesPanel,
  normalizePlaybackPreferences,
  pausePresetForTiming,
  type ReadingPreferencesPanelProps,
  type ReadingPreferencesReactRuntime,
} from "./reading-preferences-panel";


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


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((item) => findAll(item, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((item) => findAll(item, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const item = findAll(root, (element) => element.type === "button" && textContent(element) === label)[0];
  if (!item) throw new Error(`button not found: ${label}`);
  return item;
}


function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<{ dependencies: readonly unknown[]; cleanup?: () => void } | undefined> = [];
  let pending: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const same = (left: readonly unknown[] | undefined, right: readonly unknown[]) => Boolean(
    left && left.length === right.length && left.every((item, index) => Object.is(item, right[index])),
  );
  const React: ReadingPreferencesReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      return [states[index] as T, (next) => {
        states[index] = typeof next === "function"
          ? (next as (current: T) => T)(states[index] as T)
          : next;
      }];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (!same(effects[index]?.dependencies, dependencies)) {
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
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const items = pending;
      pending = [];
      items.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
    },
    unmount(): void {
      effects.forEach((item) => item?.cleanup?.());
    },
  };
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";


function feature(key: typeof CAPABILITY_KEYS[number], enabled: ReadonlySet<string>): FeatureCapability {
  return enabled.has(key)
    ? { key, state: "enabled", visible: true, actionable: true, reason_code: null, required_gate: null }
    : { key, state: "hold", visible: key === "narration_product" || key === "reading_settings", actionable: false, reason_code: "P1_GATE_REQUIRED", required_gate: "P1-GATE" };
}


function capabilities(...keys: readonly string[]): NarrationCapabilities {
  const enabled = new Set(keys);
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map((key) => feature(key, enabled)),
  };
}


function authorization(): NarrationAuthorizationState {
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
  };
}


function settings(input: {
  readonly version?: number;
  readonly language?: string;
  readonly rate?: number;
  readonly volume?: number;
} = {}): NarrationSettingsResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    settings_id: "223e4567-e89b-42d3-a456-426614174000",
    exists: true,
    version: input.version ?? 3,
    values: {
      narrator: null,
      language: input.language ?? "zh-CN",
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
      timing: READING_PAUSE_PRESETS.natural,
      casting: {
        anonymous_reuse_scope: "scene",
        same_scene_voice_deduplication: true,
        unknown_speaker_action: "block",
      },
      playback: {
        playback_rate: input.rate ?? 1,
        volume: input.volume ?? 1,
      },
    },
    updated_at: "2026-08-29T10:00:00Z",
  };
}


function props(input: Partial<ReadingPreferencesPanelProps> = {}): ReadingPreferencesPanelProps {
  return {
    novelId: NOVEL_ID,
    settings: settings(),
    capabilities: capabilities("narration_product", "reading_settings"),
    authorization: authorization(),
    saveSettings: async () => { throw new Error("unexpected settings save"); },
    savePlaybackPreferences: async () => { throw new Error("unexpected playback save"); },
    ...input,
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


describe("reading preferences requests", () => {
  it("keeps playback out of the base mutation and emits an exact narrow PATCH", () => {
    const resource = settings();
    const base = buildReadingBaseSettingsRequest(resource, {
      language: "en",
      textRules: { ...resource.values.text_rules, read_author_notes: true },
      timing: READING_PAUSE_PRESETS.compact,
    });
    expect(base.values.playback).toEqual(resource.values.playback);
    expect(base.values.language).toBe("en");
    expect(buildReadingPlaybackPreferencesRequest(resource, {
      playback_rate: 2.25,
      volume: 0.42,
    })).toEqual({
      expected_version: 3,
      playback: { playback_rate: 2.25, volume: 0.42 },
    });
  });

  it("normalizes playback bounds and recognizes natural-language pause presets", () => {
    expect(normalizePlaybackPreferences({ playback_rate: 4, volume: -1 })).toEqual({
      playback_rate: 3,
      volume: 0,
    });
    expect(pausePresetForTiming(READING_PAUSE_PRESETS.natural)).toBe("natural");
    expect(pausePresetForTiming({ ...READING_PAUSE_PRESETS.natural, sentence_gap_ms: 221 })).toBe("custom");
  });

  it("classifies CAS conflicts without exposing server detail", () => {
    const failure = classifyReadingPreferencesFailure(new NarrationApiError(409, {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      code: "VERSION_CONFLICT",
      message: "private server detail",
      retryable: false,
      field: null,
      current_version: 4,
      capability: null,
    }));
    expect(failure.refreshRequired).toBe(true);
    expect(failure.message).not.toContain("private server detail");
  });
});


describe("reading preferences panel", () => {
  it("applies playback immediately and persists only the narrow playback payload", async () => {
    const onImmediatePlaybackChange = vi.fn();
    const response = settings({ version: 4, rate: 1.5, volume: 1 });
    const savePlaybackPreferences = vi.fn(async () => response);
    const harness = createReactHarness();
    const Panel = createReadingPreferencesPanel(harness.React);
    const panelProps = props({ onImmediatePlaybackChange, savePlaybackPreferences });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const rate = findAll(tree, (item) => item.type === "input" && item.props["aria-label"] === "播放倍速")[0]!;
    (rate.props.onChange as (event: unknown) => void)({ target: { value: "1.5", checked: false } });
    tree = harness.render(Panel, panelProps);
    expect(onImmediatePlaybackChange).toHaveBeenCalledWith({ playback_rate: 1.5, volume: 1 });
    (findButton(tree, "保存播放偏好").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);
    expect(savePlaybackPreferences).toHaveBeenCalledWith(
      NOVEL_ID,
      { expected_version: 3, playback: { playback_rate: 1.5, volume: 1 } },
      expect.any(AbortSignal),
    );
    expect(textContent(tree)).toContain("无需重新合成");
  });

  it("uses a controlled language select and keeps exact milliseconds folded", async () => {
    const response = settings({ version: 4, language: "en" });
    const saveSettings = vi.fn(async () => response);
    const harness = createReactHarness();
    const Panel = createReadingPreferencesPanel(harness.React);
    const panelProps = props({ saveSettings });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const language = findAll(tree, (item) => (
      item.type === "select" && findAll(item, (option) => option.type === "option" && option.props.value === "ja-JP").length > 0
    ))[0]!;
    (language.props.onChange as (event: unknown) => void)({ target: { value: "en", checked: false } });
    tree = harness.render(Panel, panelProps);
    const advanced = findAll(tree, (item) => item.type === "details" && textContent(item).includes("精确停顿毫秒"))[0]!;
    expect(advanced.props.open).toBeUndefined();
    (findButton(tree, "保存基础朗读设置").props.onClick as () => void)();
    await settle();
    expect(saveSettings).toHaveBeenCalledWith(
      NOVEL_ID,
      {
        expected_version: 3,
        values: { ...settings().values, language: "en" },
      },
      expect.any(AbortSignal),
    );
  });

  it("keeps a local playback draft on conflict and offers refresh", async () => {
    const onRefresh = vi.fn();
    const savePlaybackPreferences = vi.fn(async () => {
      throw new NarrationApiError(409, {
        contract_version: NARRATION_SETTINGS_API_VERSION,
        code: "VERSION_CONFLICT",
        message: "server detail",
        retryable: false,
        field: null,
        current_version: 7,
        capability: null,
      });
    });
    const harness = createReactHarness();
    const Panel = createReadingPreferencesPanel(harness.React);
    const panelProps = props({ savePlaybackPreferences, onRefresh });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const volume = findAll(tree, (item) => item.type === "input" && item.props["aria-label"] === "播放器音量")[0]!;
    (volume.props.onChange as (event: unknown) => void)({ target: { value: "0.4", checked: false } });
    tree = harness.render(Panel, panelProps);
    (findButton(tree, "保存播放偏好").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);
    expect(textContent(tree)).toContain("本地偏好");
    expect((findAll(tree, (item) => item.props["aria-label"] === "播放器音量")[0]?.props.value)).toBe(0.4);
    (findButton(tree, "刷新最新设置").props.onClick as () => void)();
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
