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
  type NarrationScopeOverrideResource,
  type NarrationSettingsResource,
} from "./contracts";
import {
  buildScopeOverrideRequest,
  createScopeOverridesPanel,
  emptyScopeOverrideValues,
  scopeAffectedDescription,
  scopeInheritanceLabels,
  type ReadingScopeTarget,
  type ScopeOverridesPanelProps,
  type ScopeOverridesReactRuntime,
} from "./scope-overrides-panel";


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
  let pending: Array<{ index: number; effect: () => void | (() => void); dependencies: readonly unknown[] }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const same = (left: readonly unknown[] | undefined, right: readonly unknown[]) => Boolean(
    left && left.length === right.length && left.every((item, index) => Object.is(item, right[index])),
  );
  const React: ScopeOverridesReactRuntime = {
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
const VOLUME_ID = "223e4567-e89b-42d3-a456-426614174000";
const CHAPTER_ID = "323e4567-e89b-42d3-a456-426614174000";


const volumeTarget: ReadingScopeTarget = {
  novelId: NOVEL_ID,
  scopeKind: "volume",
  scopeId: VOLUME_ID,
  label: "第一卷",
  affectedChapterCount: 12,
};


const chapterTarget: ReadingScopeTarget = {
  novelId: NOVEL_ID,
  scopeKind: "chapter",
  scopeId: CHAPTER_ID,
  label: "雨夜",
  parentVolumeId: VOLUME_ID,
  parentVolumeLabel: "第一卷",
};


function feature(key: typeof CAPABILITY_KEYS[number], enabled: ReadonlySet<string>): FeatureCapability {
  return enabled.has(key)
    ? { key, state: "enabled", visible: true, actionable: true, reason_code: null, required_gate: null }
    : { key, state: "hold", visible: true, actionable: false, reason_code: "P1_GATE_REQUIRED", required_gate: "P1-GATE" };
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


function settings(): NarrationSettingsResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    settings_id: "423e4567-e89b-42d3-a456-426614174000",
    exists: true,
    version: 5,
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
    updated_at: "2026-08-29T10:00:00Z",
  };
}


function enabledOverride(): NarrationScopeOverrideResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    override_id: "523e4567-e89b-42d3-a456-426614174000",
    novel_id: NOVEL_ID,
    scope_kind: "volume",
    scope_id: VOLUME_ID,
    enabled: true,
    version: 1,
    overrides: { ...emptyScopeOverrideValues(), language: "en" },
  };
}


function props(input: Partial<ScopeOverridesPanelProps> = {}): ScopeOverridesPanelProps {
  return {
    novelId: NOVEL_ID,
    settings: settings(),
    capabilities: capabilities("narration_product", "reading_settings"),
    authorization: authorization(),
    targets: [volumeTarget, chapterTarget],
    overrides: [],
    saveOverride: async () => { throw new Error("unexpected save"); },
    ...input,
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


describe("scope override helpers", () => {
  it("builds exact CAS replacements and clears disabled overrides", () => {
    expect(buildScopeOverrideRequest(NOVEL_ID, volumeTarget, undefined, true, {
      ...emptyScopeOverrideValues(),
      language: "en",
    })).toEqual({
      expected_version: 0,
      enabled: true,
      overrides: { ...emptyScopeOverrideValues(), language: "en" },
    });
    expect(buildScopeOverrideRequest(NOVEL_ID, volumeTarget, enabledOverride(), false, enabledOverride().overrides)).toEqual({
      expected_version: 1,
      enabled: false,
      overrides: emptyScopeOverrideValues(),
    });
  });

  it("explains the inheritance chain and affected range", () => {
    expect(scopeInheritanceLabels(chapterTarget)).toEqual([
      "作品设置",
      "分卷 · 第一卷",
      "章节 · 雨夜",
    ]);
    expect(scopeAffectedDescription(volumeTarget)).toContain("12 个章节");
  });
});


describe("scope overrides panel", () => {
  it("is folded by default and saves a controlled-language override", async () => {
    const response = enabledOverride();
    const saveOverride = vi.fn(async () => response);
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const panelProps = props({ saveOverride });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    expect(tree.type).toBe("details");
    expect(tree.props.open).toBeUndefined();
    const enabled = findAll(tree, (item) => item.type === "input" && item.props.type === "checkbox")[0]!;
    (enabled.props.onChange as (event: unknown) => void)({ target: { checked: true, value: "" } });
    tree = harness.render(Panel, panelProps);
    const language = findAll(tree, (item) => (
      item.type === "select" && findAll(item, (option) => option.type === "option" && option.props.value === "ja-JP").length > 0
    ))[0]!;
    (language.props.onChange as (event: unknown) => void)({ target: { value: "en", checked: false } });
    tree = harness.render(Panel, panelProps);
    (findButton(tree, "保存范围覆盖").props.onClick as () => void)();
    await settle();
    expect(saveOverride).toHaveBeenCalledWith(
      NOVEL_ID,
      "volume",
      VOLUME_ID,
      {
        expected_version: 0,
        enabled: true,
        overrides: { ...emptyScopeOverrideValues(), language: "en" },
      },
      expect.any(AbortSignal),
    );
  });

  it("keeps a draft on CAS conflict and exposes a refresh action", async () => {
    const onRefresh = vi.fn();
    const saveOverride = vi.fn(async () => {
      throw new NarrationApiError(409, {
        contract_version: NARRATION_SETTINGS_API_VERSION,
        code: "VERSION_CONFLICT",
        message: "detail",
        retryable: false,
        field: null,
        current_version: 2,
        capability: null,
      });
    });
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const panelProps = props({ overrides: [enabledOverride()], saveOverride, onRefresh });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const language = findAll(tree, (item) => (
      item.type === "select" && findAll(item, (option) => option.type === "option" && option.props.value === "ja-JP").length > 0
    ))[0]!;
    (language.props.onChange as (event: unknown) => void)({ target: { value: "ja-JP", checked: false } });
    tree = harness.render(Panel, panelProps);
    (findButton(tree, "保存范围覆盖").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);
    expect(textContent(tree)).toContain("本地草稿仍保留");
    (findButton(tree, "刷新最新覆盖").props.onClick as () => void)();
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("aborts a pending scoped save when the panel unmounts", () => {
    let signal: AbortSignal | undefined;
    const saveOverride = (
      _novelId: string,
      _scopeKind: "volume" | "chapter",
      _scopeId: string,
      _request: unknown,
      currentSignal?: AbortSignal,
    ) => {
      signal = currentSignal;
      return new Promise<NarrationScopeOverrideResource>(() => undefined);
    };
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const panelProps = props({ overrides: [enabledOverride()], saveOverride });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const language = findAll(tree, (item) => (
      item.type === "select"
      && findAll(item, (option) => option.type === "option" && option.props.value === "ja-JP").length > 0
    ))[0]!;
    (language.props.onChange as (event: unknown) => void)({ target: { value: "ja-JP", checked: false } });
    tree = harness.render(Panel, panelProps);
    (findButton(tree, "保存范围覆盖").props.onClick as () => void)();
    expect(signal?.aborted).toBe(false);
    harness.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("renders a truthful empty state without actionable fields", () => {
    const harness = createReactHarness();
    const Panel = createScopeOverridesPanel(harness.React);
    const tree = harness.render(Panel, props({ targets: [] }));
    expect(textContent(tree)).toContain("还没有可配置");
    expect(findAll(tree, (item) => item.type === "button")).toHaveLength(0);
  });
});
