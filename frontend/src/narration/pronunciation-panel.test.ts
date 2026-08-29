import { describe, expect, it, vi } from "vitest";

import { NarrationApiError } from "./api";
import {
  buildPronunciationHitPreview,
  buildPronunciationProfileRequest,
  createPronunciationPanel,
  pronunciationDraftsFromProfile,
  pronunciationPriorityBand,
  pronunciationPriorityForBand,
  validatePronunciationDrafts,
  type PronunciationPanelApi,
  type PronunciationPanelProps,
  type PronunciationPanelReactRuntime,
} from "./pronunciation-panel";
import {
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  type FeatureCapability,
  type NarrationApiErrorDetail,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type PronunciationProfileResource,
} from "./contracts";
import { T2_F_NARRATION_SETTINGS_PANEL_STYLES } from "./styles/t2-f";


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


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const item = findAll(root, (element) => element.type === "button" && textContent(element) === label)[0];
  if (!item) throw new Error(`button not found: ${label}`);
  return item;
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

  const React: PronunciationPanelReactRuntime = {
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
      pending.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
    },
    unmount(): void {
      effects.forEach((effect) => effect?.cleanup?.());
    },
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_NOVEL_ID = "22222222-2222-4222-8222-222222222222";
const PROFILE_ID = "33333333-3333-4333-8333-333333333333";
const ENTRY_ID = "44444444-4444-4444-8444-444444444444";
const VOLUME_ID = "55555555-5555-4555-8555-555555555555";


function feature(key: FeatureCapability["key"], enabled = true): FeatureCapability {
  return {
    key,
    state: enabled ? "enabled" : "hold",
    visible: true,
    actionable: enabled,
    reason_code: enabled ? null : "T2_GATE_REQUIRED",
    required_gate: enabled ? null : "T2-GATE",
  };
}


function capabilities(readingEnabled = true): NarrationCapabilities {
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: [
      feature("narration_product"),
      feature("reading_settings", readingEnabled),
    ],
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


function profile(
  novelId = NOVEL_ID,
  version = 1,
  sourceText = "MOSS",
): PronunciationProfileResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: novelId,
    profile_id: PROFILE_ID,
    version,
    fingerprint: "a".repeat(64),
    entries: [{
      entry_id: ENTRY_ID,
      source_text: sourceText,
      action: "replace",
      spoken_text: "摩斯",
      language: "zh-CN",
      scope_kind: "novel",
      scope_id: novelId,
      priority: 0,
    }],
  };
}


function props(changes: Partial<PronunciationPanelProps> = {}): PronunciationPanelProps {
  return {
    novelId: NOVEL_ID,
    capabilities: capabilities(),
    authorization,
    scopeOptions: [{ kind: "volume", id: VOLUME_ID, label: "第一卷" }],
    timing: {
      sentence_gap_ms: 180,
      paragraph_gap_ms: 480,
      section_gap_ms: 900,
    },
    ...changes,
  };
}


function apiError(code: NarrationApiErrorDetail["code"], currentVersion: number | null = null): NarrationApiError {
  return new NarrationApiError(409, {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    code,
    message: "fault",
    retryable: false,
    field: null,
    current_version: currentVersion,
    capability: null,
  });
}


describe("pronunciation draft contract", () => {
  it("builds a strict full CAS replacement and never forwards entry identities", () => {
    const current = profile();
    const drafts = pronunciationDraftsFromProfile(current).map((item) => ({
      ...item,
      sourceText: " MOSS Nano ",
    }));

    const request = buildPronunciationProfileRequest(current, drafts, NOVEL_ID, []);

    expect(request).toEqual({
      expected_version: 1,
      entries: [{
        entry_id: null,
        source_text: "MOSS Nano",
        action: "replace",
        spoken_text: "摩斯",
        language: "zh-CN",
        scope_kind: "novel",
        scope_id: NOVEL_ID,
        priority: 0,
      }],
    });
  });

  it("rejects normalized duplicates, invalid scope and skip text before PUT", () => {
    const current = profile();
    const first = pronunciationDraftsFromProfile(current)[0];
    if (!first) throw new Error("fixture entry missing");
    const drafts = [
      { ...first, clientKey: "one", sourceText: "ＡＩ", spokenText: "AI" },
      {
        ...first,
        clientKey: "two",
        sourceText: "ai",
        action: "skip" as const,
        spokenText: "must-not-exist",
      },
      {
        ...first,
        clientKey: "three",
        sourceText: "scope-only",
        scopeKind: "volume" as const,
        scopeId: VOLUME_ID,
      },
    ];

    const validation = validatePronunciationDrafts(drafts, NOVEL_ID, []);

    expect(validation.valid).toBe(false);
    expect(validation.errors["two:duplicate"]).toContain("不能重复");
    expect(validation.errors["two:spoken"]).toContain("不能携带");
    expect(validation.errors["three:scope"]).toContain("不属于");
    expect(buildPronunciationProfileRequest(current, drafts, NOVEL_ID, [])).toBeNull();
  });

  it("maps author-friendly priority bands while retaining exact advanced values", () => {
    expect(pronunciationPriorityForBand("high")).toBe("100");
    expect(pronunciationPriorityForBand("normal")).toBe("0");
    expect(pronunciationPriorityForBand("low")).toBe("-100");
    expect(pronunciationPriorityBand("37")).toBe("custom");
  });

  it("previews current-scope hits locally in priority order", () => {
    const base = pronunciationDraftsFromProfile(profile())[0];
    if (!base) throw new Error("fixture entry missing");
    const preview = buildPronunciationHitPreview("MOSS 与 AI", [
      { ...base, clientKey: "moss", priorityText: "0" },
      {
        ...base,
        clientKey: "ai",
        sourceText: "AI",
        spokenText: "人工智能",
        scopeKind: "volume",
        scopeId: VOLUME_ID,
        priorityText: "100",
      },
    ], { scopeKind: "volume", scopeId: VOLUME_ID });
    expect(preview.hits.map((item) => item.clientKey)).toEqual(["ai", "moss"]);
    expect(preview.normalizedText).toBe("摩斯 与 人工智能");
  });
});


describe("pronunciation panel", () => {
  it("shows local hit preview and only exposes试听 when a real callback is wired", async () => {
    const onPreviewHits = vi.fn();
    const api: PronunciationPanelApi = {
      getPronunciationProfile: vi.fn().mockResolvedValue(profile()),
      putPronunciationProfile: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createPronunciationPanel(harness.React, api);
    const panelProps = props({ onPreviewHits });
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    let tree = Panel(panelProps);
    harness.commitEffects();
    const previewText = findAll(tree, (element) => element.type === "textarea")[0];
    if (!previewText) throw new Error("preview textarea missing");
    (previewText.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "MOSS 正在朗读" },
    });
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    expect(textContent(tree)).toContain("命中 1 条规则");
    (findButton(tree, "试听命中结果").props.onClick as () => void)();
    expect(onPreviewHits).toHaveBeenCalledWith(expect.objectContaining({
      sourceText: "MOSS 正在朗读",
      normalizedText: "摩斯 正在朗读",
    }));

    const noPreviewHarness = createReactHarness();
    const NoPreviewPanel = createPronunciationPanel(noPreviewHarness.React, api);
    noPreviewHarness.beginRender();
    NoPreviewPanel(props());
    noPreviewHarness.commitEffects();
    await settle();
    noPreviewHarness.beginRender();
    const noPreviewTree = NoPreviewPanel(props());
    expect(findAll(noPreviewTree, (element) => element.type === "button" && textContent(element) === "试听命中结果")).toHaveLength(0);
    expect(textContent(noPreviewTree)).toContain("接入真实试听能力后");
  });

  it("loads actual pause values and saves edited pronunciation with current CAS", async () => {
    const saved = profile(NOVEL_ID, 2, "MOSS Nano");
    const api: PronunciationPanelApi = {
      getPronunciationProfile: vi.fn().mockResolvedValue(profile()),
      putPronunciationProfile: vi.fn().mockResolvedValue(saved),
    };
    const harness = createReactHarness();
    const Panel = createPronunciationPanel(harness.React, api);
    const panelProps = props();

    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    let tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("句间180 ms");
    expect(textContent(tree)).toContain("停顿属于作品基础朗读设置");
    const source = findAll(tree, (element) => (
      element.type === "input" && String(element.props.id).endsWith("-source")
    ))[0];
    if (!source) throw new Error("source input missing");
    (source.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "MOSS Nano" },
    });

    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    const save = findButton(tree, "保存发音配置");
    expect(save.props.disabled).toBe(false);
    (save.props.onClick as () => void)();
    await settle();

    expect(api.putPronunciationProfile).toHaveBeenCalledWith(
      NOVEL_ID,
      expect.objectContaining({ expected_version: 1 }),
      expect.any(AbortSignal),
    );
    const payload = vi.mocked(api.putPronunciationProfile).mock.calls[0]?.[1];
    expect(payload?.entries[0]?.entry_id).toBeNull();
    expect(payload?.entries[0]?.source_text).toBe("MOSS Nano");

    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    expect(textContent(tree)).toContain("发音版本 2");
    expect(textContent(tree)).toContain("不改写历史 Edition");
  });

  it("keeps the local draft through a CAS conflict and refresh", async () => {
    const get = vi.fn()
      .mockResolvedValueOnce(profile())
      .mockResolvedValueOnce(profile(NOVEL_ID, 2, "server edit"));
    const api: PronunciationPanelApi = {
      getPronunciationProfile: get,
      putPronunciationProfile: vi.fn().mockRejectedValue(apiError("VERSION_CONFLICT", 2)),
    };
    const harness = createReactHarness();
    const Panel = createPronunciationPanel(harness.React, api);
    const panelProps = props();

    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    let tree = Panel(panelProps);
    harness.commitEffects();
    const source = findAll(tree, (element) => element.type === "input" && String(element.props.id).endsWith("-source"))[0];
    if (!source) throw new Error("source input missing");
    (source.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "local edit" } });
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    (findButton(tree, "保存发音配置").props.onClick as () => void)();
    await settle();
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    expect(textContent(tree)).toContain("服务端当前版本为 2");

    (findButton(tree, "读取最新版本并保留草稿").props.onClick as () => void)();
    await settle();
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    const refreshedSource = findAll(tree, (element) => element.type === "input" && String(element.props.id).endsWith("-source"))[0];
    expect(refreshedSource?.props.value).toBe("local edit");
    expect(textContent(tree)).toContain("本地草稿仍保留");
  });

  it("loads read-only under HOLD and never exposes an enabled mutation", async () => {
    const api: PronunciationPanelApi = {
      getPronunciationProfile: vi.fn().mockResolvedValue(profile()),
      putPronunciationProfile: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createPronunciationPanel(harness.React, api);
    const panelProps = props({ capabilities: capabilities(false) });
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    const tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("T2_GATE_REQUIRED");
    expect(findButton(tree, "新增规则").props.disabled).toBe(true);
    expect(findButton(tree, "保存发音配置").props.disabled).toBe(true);
    expect(api.putPronunciationProfile).not.toHaveBeenCalled();
  });

  it("aborts an old novel load and fences its response", async () => {
    let resolveFirst: ((value: PronunciationProfileResource) => void) | undefined;
    const first = new Promise<PronunciationProfileResource>((resolve) => { resolveFirst = resolve; });
    const signals: AbortSignal[] = [];
    const api: PronunciationPanelApi = {
      getPronunciationProfile: vi.fn((novelId, signal) => {
        if (signal) signals.push(signal);
        return novelId === NOVEL_ID ? first : Promise.resolve(profile(OTHER_NOVEL_ID, 1, "other scope"));
      }),
      putPronunciationProfile: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createPronunciationPanel(harness.React, api);
    harness.beginRender();
    Panel(props());
    harness.commitEffects();
    harness.beginRender();
    Panel(props({ novelId: OTHER_NOVEL_ID, scopeOptions: [] }));
    harness.commitEffects();
    expect(signals[0]?.aborted).toBe(true);
    resolveFirst?.(profile());
    await settle();
    harness.beginRender();
    const tree = Panel(props({ novelId: OTHER_NOVEL_ID, scopeOptions: [] }));
    harness.commitEffects();
    expect((tree as FakeElement).props["data-pronunciation-panel-phase"]).toBe("ready");
    const source = findAll(tree, (element) => (
      element.type === "input" && String(element.props.id).endsWith("-source")
    ))[0];
    expect(source?.props.value).toBe("other scope");
    expect(source?.props.value).not.toBe("MOSS");
  });

  it("restores host focus on destroy and exports only a local responsive style fragment", () => {
    const onReturnFocus = vi.fn();
    const api: PronunciationPanelApi = {
      getPronunciationProfile: vi.fn(() => (
        new Promise<PronunciationProfileResource>(() => undefined)
      )),
      putPronunciationProfile: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createPronunciationPanel(harness.React, api);
    harness.beginRender();
    Panel(props({ onReturnFocus }));
    harness.commitEffects();
    harness.unmount();

    expect(onReturnFocus).toHaveBeenCalledTimes(1);
    expect(T2_F_NARRATION_SETTINGS_PANEL_STYLES).toContain("@media (max-width: 560px)");
    expect(T2_F_NARRATION_SETTINGS_PANEL_STYLES).toContain(".anw-pronunciation-panel");
    expect(T2_F_NARRATION_SETTINGS_PANEL_STYLES).not.toContain(".anw-workbench");
  });
});
