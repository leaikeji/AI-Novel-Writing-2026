import { describe, expect, it, vi } from "vitest";

import {
  OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION,
  OFFICIAL_VOICE_PRESET_IDS,
  createOfficialVoiceLibrary,
  createOfficialVoiceLibraryModel,
  filterOfficialVoiceLibraryGroups,
  officialVoiceCatalogFromWire,
  officialVoiceLanguageMatches,
  type OfficialVoiceCatalog,
  type OfficialVoiceCatalogItem,
  type OfficialVoiceCatalogWireLike,
  type OfficialVoiceLibraryProps,
  type OfficialVoiceLibraryReactRuntime,
  type OfficialVoiceSelectionResult,
} from "./official-voice-library";
import {
  OFFICIAL_VOICE_LIBRARY_STYLE_ID,
  OFFICIAL_VOICE_LIBRARY_STYLES,
} from "./styles/voice-library";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  readonly dependencies: readonly unknown[];
  readonly cleanup?: () => void;
}


function isElement(value: unknown): value is FakeElement {
  return value !== null
    && typeof value === "object"
    && "type" in value
    && "props" in value
    && "children" in value;
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


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pending: Array<{
    readonly index: number;
    readonly effect: () => void | (() => void);
    readonly dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const React: OfficialVoiceLibraryReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)) {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
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
      const scheduled = pending;
      pending = [];
      for (const item of scheduled) {
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


const ROWS = [
  ["onnx.Junhao", "CN 欢迎关注模思智能", "Chinese Male", "zh-CN"],
  ["onnx.Zhiming", "CN 京味胡同闲聊", "Chinese Male", "zh-CN"],
  ["onnx.Weiguo", "CN 说书", "Chinese Male", "zh-CN"],
  ["onnx.Xiaoyu", "CN 明星", "Chinese Female", "zh-CN"],
  ["onnx.Yuewen", "CN 机车", "Chinese Female", "zh-CN"],
  ["onnx.Lingyu", "CN 深夜电台", "Chinese Female", "zh-CN"],
  ["onnx.Trump", "EN Trump", "English Male", "en"],
  ["onnx.Ava", "EN The Bitter Lesson", "English Female", "en"],
  ["onnx.Bella", "EN A Gentle Reminder", "English Female", "en"],
  ["onnx.Adam", "EN English News", "English Male", "en"],
  ["onnx.Nathan", "EN The Quiet Motion of the World", "English Male", "en"],
  ["onnx.Soyo", "JP Soyo", "Japanese Female", "ja-JP"],
  ["onnx.Saki", "JP Saki", "Japanese Female", "ja-JP"],
  ["onnx.Mortis", "JP Mortis", "Japanese Female", "ja-JP"],
  ["onnx.Umiri", "JP Umiri", "Japanese Female", "ja-JP"],
  ["onnx.Mei", "JP Togawa", "Japanese Female", "ja-JP"],
  ["onnx.Anon", "JP Anon", "Japanese Female", "ja-JP"],
  ["onnx.Arisa", "JP Arisa", "Japanese Female", "ja-JP"],
] as const;


const REVISION = "a".repeat(40);
const SHA = "b".repeat(64);
const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const IDEMPOTENCY_KEY = "official-voice-selection-test-key";


function catalogItem(
  row: typeof ROWS[number],
  overrides: Partial<OfficialVoiceCatalogItem> = {},
): OfficialVoiceCatalogItem {
  const [presetId, displayName, group, language] = row;
  return {
    presetId,
    displayName,
    group,
    language,
    localUseStatus: "available",
    commercialDistributionStatus: "not_evaluated",
    validationTier: ["onnx.Junhao", "onnx.Zhiming", "onnx.Xiaoyu"].includes(presetId)
      ? "canonical_chapter_verified"
      : "pinned_catalog_unreviewed",
    languageScope: language,
    selectableNow: true,
    previewableNow: true,
    renderableExisting: true,
    usageNotice: "private_local_writing_tool",
    provenance: {
      schemaVersion: "moss-tts-official-preset-provenance/1.0",
      repository: "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
      revision: REVISION,
      manifestPath: "browser_poc_manifest.json",
      manifestSha256: SHA,
      presetId,
      manifestVoice: presetId.slice("onnx.".length),
      promptCodesSha256: SHA,
      promptFrameCount: 98,
      promptQuantizerCount: 16,
      modelFingerprintSha256: SHA,
      provenanceFingerprintSha256: SHA,
    },
    ...overrides,
  };
}


function catalog(
  overrides: Readonly<Record<string, Partial<OfficialVoiceCatalogItem>>> = {},
): OfficialVoiceCatalog {
  return {
    schemaVersion: OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION,
    items: ROWS.map((row) => catalogItem(row, overrides[row[0]])),
  };
}


function result(
  presetId: string,
  overrides: Partial<OfficialVoiceSelectionResult> = {},
): OfficialVoiceSelectionResult {
  return {
    replayed: false,
    selectionStillCurrent: true,
    presetId,
    targetKind: "narrator",
    characterId: null,
    settingsVersion: 4,
    bindingVersion: null,
    languageMismatch: !presetId.startsWith("onnx.J"),
    ...overrides,
  };
}


function baseProps(
  overrides: Partial<OfficialVoiceLibraryProps> = {},
): OfficialVoiceLibraryProps {
  return {
    novelId: NOVEL_ID,
    catalog: catalog(),
    target: {
      kind: "narrator",
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 3,
    },
    createIdempotencyKey: () => IDEMPOTENCY_KEY,
    onUse: async (_novelId, request) => result(request.presetId),
    onPreview: async () => undefined,
    ...overrides,
  };
}


function classIncludes(element: FakeElement, className: string): boolean {
  const value = element.props.className;
  return typeof value === "string" && value.split(" ").includes(className);
}


function findPresetCard(tree: FakeElement, presetId: string): FakeElement {
  const card = findAll(tree, (element) => (
    element.props["data-official-preset-id"] === presetId
  ))[0];
  if (!card) throw new Error(`missing card ${presetId}`);
  return card;
}


async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


describe("official voice library model", () => {
  it("keeps the exact pinned order and groups all 18 official names as 6/5/7", () => {
    const source = catalog();
    const model = createOfficialVoiceLibraryModel(source, "zh-CN");
    expect(model.status).toBe("ready");
    if (model.status !== "ready") throw new Error("expected a ready model");
    expect(model.groups.map((group) => group.items.length)).toEqual([6, 5, 7]);
    expect(model.groups.flatMap((group) => group.items.map((item) => item.item.presetId)))
      .toEqual(OFFICIAL_VOICE_PRESET_IDS);
    expect(model.groups.flatMap((group) => group.items.map((item) => item.item.displayName)))
      .toEqual(ROWS.map((row) => row[1]));
    expect(model.groups.flatMap((group) => group.items).filter((item) => item.languageMismatch))
      .toHaveLength(12);
    expect(source.items).toHaveLength(18);
    expect(officialVoiceLanguageMatches("en", "en")).toBe(true);
    expect(officialVoiceLanguageMatches("en", "en-US")).toBe(true);
  });

  it("fails closed for missing, duplicate, reordered, or false validation evidence", () => {
    const missing: OfficialVoiceCatalog = { ...catalog(), items: catalog().items.slice(0, 17) };
    expect(createOfficialVoiceLibraryModel(missing, "zh-CN").status).toBe("invalid");

    const duplicatedItems = [...catalog().items];
    duplicatedItems[1] = duplicatedItems[0];
    expect(createOfficialVoiceLibraryModel(
      { ...catalog(), items: duplicatedItems },
      "zh-CN",
    ).status).toBe("invalid");

    const reorderedItems = [...catalog().items];
    [reorderedItems[0], reorderedItems[1]] = [reorderedItems[1], reorderedItems[0]];
    expect(createOfficialVoiceLibraryModel(
      { ...catalog(), items: reorderedItems },
      "zh-CN",
    ).status).toBe("invalid");

    const falseTier = catalog({
      "onnx.Junhao": { validationTier: "pinned_catalog_unreviewed" },
    });
    expect(createOfficialVoiceLibraryModel(falseTier, "zh-CN").status).toBe("invalid");
  });

  it("searches display metadata and filters the fixed language groups", () => {
    const model = createOfficialVoiceLibraryModel(catalog(), "zh-CN");
    if (model.status !== "ready") throw new Error("expected a ready model");

    expect(filterOfficialVoiceLibraryGroups(model.groups, "Ava", "all")
      .flatMap((group) => group.items.map((item) => item.item.presetId)))
      .toEqual(["onnx.Ava"]);
    expect(filterOfficialVoiceLibraryGroups(model.groups, "female", "en")
      .flatMap((group) => group.items.map((item) => item.item.presetId)))
      .toEqual(["onnx.Ava", "onnx.Bella"]);
    expect(filterOfficialVoiceLibraryGroups(model.groups, "不存在", "ja-JP"))
      .toEqual([]);
  });

  it("adapts the frozen shared snake_case wire contract", () => {
    const source = catalog();
    const wire: OfficialVoiceCatalogWireLike = {
      schema_version: OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION,
      items: source.items.map((item) => ({
        preset_id: item.presetId,
        display_name: item.displayName,
        group: item.group,
        language: item.language,
        local_use_status: item.localUseStatus,
        commercial_distribution_status: item.commercialDistributionStatus,
        validation_tier: item.validationTier,
        language_scope: item.languageScope,
        selectable_now: item.selectableNow,
        previewable_now: item.previewableNow,
        renderable_existing: item.renderableExisting,
        usage_notice: item.usageNotice,
        provenance: {
          schema_version: "moss-tts-official-preset-provenance/1.0" as const,
          repository: item.provenance.repository,
          revision: item.provenance.revision,
          manifest_path: item.provenance.manifestPath,
          manifest_sha256: item.provenance.manifestSha256,
          preset_id: item.provenance.presetId,
          manifest_voice: item.provenance.manifestVoice,
          prompt_codes_sha256: item.provenance.promptCodesSha256,
          prompt_frame_count: item.provenance.promptFrameCount,
          prompt_quantizer_count: item.provenance.promptQuantizerCount,
          model_fingerprint_sha256: item.provenance.modelFingerprintSha256,
          provenance_fingerprint_sha256: item.provenance.provenanceFingerprintSha256,
        },
      })),
    };
    const adapted = officialVoiceCatalogFromWire(wire);
    expect(adapted.items).toHaveLength(18);
    expect(adapted.items[7]).toMatchObject({
      presetId: "onnx.Ava",
      displayName: "EN The Bitter Lesson",
      languageScope: "en",
    });
    expect(Object.isFrozen(adapted.items)).toBe(true);
  });
});


describe("official voice library component", () => {
  it("renders 18 native-keyboard cards, folded provenance, and no confirmation controls", () => {
    const harness = createHarness();
    const Library = createOfficialVoiceLibrary(harness.React);
    let tree = harness.render(Library, baseProps());
    tree = harness.render(Library, baseProps());

    const cards = findAll(tree, (element) => classIncludes(element, "anw-official-voice-card"));
    const buttons = findAll(tree, (element) => element.type === "button");
    const details = findAll(tree, (element) => element.type === "details");
    const summaries = findAll(tree, (element) => element.type === "summary");
    expect(cards).toHaveLength(18);
    expect(buttons).toHaveLength(36);
    expect(buttons.every((button) => button.props.type === "button")).toBe(true);
    expect(details).toHaveLength(18);
    expect(summaries).toHaveLength(18);
    expect(details.every((item) => item.props.open === undefined)).toBe(true);
    const inputs = findAll(tree, (element) => element.type === "input");
    expect(inputs).toHaveLength(1);
    expect(inputs[0]?.props.type).toBe("search");
    expect(findAll(tree, (element) => element.type === "select")).toHaveLength(1);
    expect(findAll(tree, (element) => element.type === "input"
      && ["checkbox", "radio"].includes(String(element.props.type)))).toHaveLength(0);
    for (const [, displayName] of ROWS) expect(textContent(tree)).toContain(displayName);
    expect(textContent(tree)).toContain("Preset ID");
    expect(textContent(tree)).toContain("商业发布/再分发未评估");
  });

  it("keeps cross-language guidance non-blocking and sends one direct-use request", async () => {
    const harness = createHarness();
    const onUse = vi.fn(async (_novelId, request) => result(request.presetId));
    const onApplied = vi.fn();
    const props = baseProps({ onUse, onApplied });
    const Library = createOfficialVoiceLibrary(harness.React);
    harness.render(Library, props);
    let tree = harness.render(Library, props);
    const ava = findPresetCard(tree, "onnx.Ava");
    expect(textContent(ava)).toContain("跨语言 · 本项目未专项听检");
    expect(textContent(ava)).toContain("仍可直接使用");
    const useButton = findAll(ava, (element) => classIncludes(
      element,
      "anw-official-voice-card__use",
    ))[0];
    expect(useButton?.props.disabled).toBe(false);

    (useButton?.props.onClick as (() => void))();
    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onUse).toHaveBeenCalledWith(
      NOVEL_ID,
      {
        presetId: "onnx.Ava",
        targetKind: "narrator",
        expectedSettingsVersion: 3,
      },
      IDEMPOTENCY_KEY,
      expect.any(AbortSignal),
    );
    tree = harness.render(Library, props);
    expect(tree.props["data-official-voice-use-phase"]).toBe("applying");
    expect(textContent(tree)).toContain("正在设为旁白");

    await flushPromises();
    tree = harness.render(Library, props);
    expect(tree.props["data-official-voice-use-phase"]).toBe("applied");
    expect(textContent(findPresetCard(tree, "onnx.Ava"))).toContain("当前使用");
    expect(onApplied).toHaveBeenCalledTimes(1);
  });

  it("builds the frozen character target request without exposing CAS fields to the author", () => {
    const harness = createHarness();
    const characterId = "22222222-2222-4222-8222-222222222222";
    const onUse = vi.fn(async (_novelId, request) => result(request.presetId, {
      targetKind: "character",
      characterId,
      settingsVersion: 8,
      bindingVersion: 5,
      languageMismatch: false,
    }));
    const props = baseProps({
      target: {
        kind: "character",
        characterId,
        characterName: "林岚",
        targetLanguage: "zh-CN",
        expectedSettingsVersion: 7,
        expectedBindingVersion: 4,
      },
      onUse,
    });
    const Library = createOfficialVoiceLibrary(harness.React);
    harness.render(Library, props);
    const tree = harness.render(Library, props);
    const card = findPresetCard(tree, "onnx.Xiaoyu");
    expect(textContent(card)).toContain("用于林岚");
    expect(textContent(card)).not.toContain("expectedSettingsVersion");
    const useButton = findAll(card, (element) => classIncludes(
      element,
      "anw-official-voice-card__use",
    ))[0];
    (useButton?.props.onClick as (() => void))();
    expect(onUse).toHaveBeenCalledWith(
      NOVEL_ID,
      {
        presetId: "onnx.Xiaoyu",
        targetKind: "character",
        characterId,
        expectedSettingsVersion: 7,
        expectedBindingVersion: 4,
      },
      IDEMPOTENCY_KEY,
      expect.any(AbortSignal),
    );
  });

  it("does not make preview availability a prerequisite for using a voice", () => {
    const harness = createHarness();
    const props = baseProps({
      catalog: catalog({ "onnx.Trump": { previewableNow: false } }),
    });
    const Library = createOfficialVoiceLibrary(harness.React);
    harness.render(Library, props);
    const tree = harness.render(Library, props);
    const trump = findPresetCard(tree, "onnx.Trump");
    const previewButton = findAll(trump, (element) => classIncludes(
      element,
      "anw-official-voice-card__preview",
    ))[0];
    const useButton = findAll(trump, (element) => classIncludes(
      element,
      "anw-official-voice-card__use",
    ))[0];
    expect(previewButton?.props.disabled).toBe(true);
    expect(textContent(previewButton)).toBe("试听暂不可用");
    expect(useButton?.props.disabled).toBe(false);
  });

  it("announces conflicts, blocks stale retries, and resets after refreshed CAS props", async () => {
    const harness = createHarness();
    const onConflictRefresh = vi.fn();
    const onUse = vi.fn(async (_novelId, request) => result(request.presetId, {
      replayed: true,
      selectionStillCurrent: false,
    }));
    let props = baseProps({ onUse, onConflictRefresh });
    const Library = createOfficialVoiceLibrary(harness.React);
    harness.render(Library, props);
    let tree = harness.render(Library, props);
    const useButton = findAll(findPresetCard(tree, "onnx.Junhao"), (element) => classIncludes(
      element,
      "anw-official-voice-card__use",
    ))[0];
    (useButton?.props.onClick as (() => void))();
    await flushPromises();
    tree = harness.render(Library, props);
    expect(tree.props["data-official-voice-use-phase"]).toBe("conflict");
    const live = findAll(tree, (element) => classIncludes(
      element,
      "anw-official-voice-library__live-status",
    ))[0];
    expect(live?.props).toMatchObject({ role: "status", "aria-live": "polite" });
    expect(textContent(live)).toContain("刷新当前设置后重试");
    expect(findAll(tree, (element) => classIncludes(
      element,
      "anw-official-voice-card__use",
    )).every((button) => button.props.disabled === true)).toBe(true);
    const refresh = findAll(tree, (element) => classIncludes(
      element,
      "anw-official-voice-library__refresh",
    ))[0];
    (refresh?.props.onClick as (() => void))();
    expect(onConflictRefresh).toHaveBeenCalledTimes(1);

    props = baseProps({
      onUse,
      onConflictRefresh,
      target: {
        kind: "narrator",
        targetLanguage: "zh-CN",
        expectedSettingsVersion: 4,
      },
    });
    harness.render(Library, props);
    tree = harness.render(Library, props);
    expect(tree.props["data-official-voice-use-phase"]).toBe("idle");
  });

  it("renders explicit loading, empty, invalid, and error states", () => {
    const cases: Array<[Partial<OfficialVoiceLibraryProps>, string, string]> = [
      [{ loading: true, catalog: null }, "loading", "正在加载 18 个官方音色"],
      [{ catalog: null }, "empty", "当前没有可显示的官方音色"],
      [{ catalog: { ...catalog(), items: catalog().items.slice(0, 3) } }, "invalid", "目录不完整"],
      [{ loadError: "目录服务暂不可用" }, "error", "目录服务暂不可用"],
    ];
    for (const [overrides, status, message] of cases) {
      const harness = createHarness();
      const Library = createOfficialVoiceLibrary(harness.React);
      const props = baseProps(overrides);
      harness.render(Library, props);
      const tree = harness.render(Library, props);
      expect(tree.props["data-catalog-status"]).toBe(status);
      expect(textContent(tree)).toContain(message);
    }
  });

  it("ships 44px touch targets, narrow-screen stacking, focus, and reduced-motion rules", () => {
    expect(OFFICIAL_VOICE_LIBRARY_STYLE_ID).toBe("anw-official-voice-library-styles");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toMatch(/min-height:\s*44px/u);
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("repeat(auto-fit");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("button:focus-visible");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("@media (max-width: 680px)");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("@media (max-width: 390px)");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("@media (prefers-reduced-motion: reduce)");
    expect(OFFICIAL_VOICE_LIBRARY_STYLES).toContain("@media (forced-colors: active)");
  });
});
