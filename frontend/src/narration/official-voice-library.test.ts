import { describe, expect, it, vi } from "vitest";

import {
  OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION,
  OFFICIAL_VOICE_PRESET_IDS,
  assertOfficialVoiceSelectionResult,
  createOfficialVoiceLibrary,
  createOfficialVoiceLibraryModel,
  createOfficialVoiceSelectionRequest,
  filterOfficialVoiceLibraryGroups,
  officialVoiceCatalogFromWire,
  officialVoiceIsAvailableForProvider,
  type OfficialVoiceSelectionResult,
} from "./official-voice-library";
import {
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  type OfficialPresetCatalogResponse,
} from "./contracts";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function createComponentHarness() {
  const states: Array<{ value: unknown }> = [];
  const refs: Array<{ current: unknown }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  let effects: Array<() => void | (() => void)> = [];
  const effectSlots: Array<{ deps: readonly unknown[]; cleanup?: () => void }> = [];
  const React = {
    createElement(type: unknown, props?: Record<string, unknown> | null, ...children: unknown[]): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!states[index]) {
        states[index] = { value: typeof initial === "function" ? (initial as () => T)() : initial };
      }
      return [states[index].value as T, (next) => {
        const current = states[index]!.value as T;
        states[index]!.value = typeof next === "function"
          ? (next as (value: T) => T)(current)
          : next;
      }];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void {
      const index = effectIndex++;
      const previous = effectSlots[index];
      if (
        previous
        && dependencies.length === previous.deps.length
        && dependencies.every((value, dependencyIndex) => Object.is(value, previous.deps[dependencyIndex]))
      ) return;
      effects.push(() => {
        previous?.cleanup?.();
        const cleanup = effect();
        effectSlots[index] = {
          deps: dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
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
    flushEffects(): void {
      const pending = effects;
      effects = [];
      for (const effect of pending) effect();
    },
    unmount(): void {
      for (const slot of effectSlots) slot.cleanup?.();
    },
  };
}


function elements(root: unknown): FakeElement[] {
  if (root === null || typeof root !== "object" || !("props" in root) || !("children" in root)) return [];
  const element = root as FakeElement;
  return [element, ...element.children.flatMap(elements)];
}


function previewButton(tree: FakeElement, presetId: string): FakeElement {
  const article = elements(tree).find((element) => (
    element.props["data-official-preset-id"] === presetId
  ));
  const button = article && elements(article).find((element) => (
    element.props.className === "anw-official-voice-card__preview"
  ));
  if (!button) throw new Error(`preview button missing for ${presetId}`);
  return button;
}


function wireCatalog(): OfficialPresetCatalogResponse {
  return {
    schema_version: "qwen-tts-preset-catalog/2",
    items: OFFICIAL_PRESET_EVIDENCE.map((evidence) => {
      const female = evidence.presetId === "qwen.WarmFemale";
      const providerVoiceIds: Record<string, string> = {
        local_qwen3_tts: evidence.localVoiceId,
      };
      if (evidence.aliyunPlusVoiceId) {
        providerVoiceIds["aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"] = evidence.aliyunPlusVoiceId;
      }
      if (evidence.aliyunFlashVoiceId) {
        providerVoiceIds["aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash"] = evidence.aliyunFlashVoiceId;
      }
      return {
        preset_id: evidence.presetId,
        display_name: female ? "温暖女声" : `${evidence.localVoiceId} 官方音色`,
        official_speaker: evidence.localVoiceId,
        native_language: evidence.nativeLanguage,
        dialect: evidence.dialect,
        group: female ? "中文女声" : "中文男声",
        language: evidence.languageScope,
        local_use_status: "available",
        commercial_distribution_status: "not_evaluated",
        validation_tier: evidence.validationTier,
        language_scope: evidence.languageScope,
        selectable_now: true,
        previewable_now: true,
        renderable_existing: true,
        usage_notice: "private_local_writing_tool",
        provenance: {
          schema_version: "qwen-tts-preset-provenance/1",
          catalog_id: "qwen-provider-voice-map/1",
          preset_id: evidence.presetId,
          local_model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
          local_model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
          provider_voice_ids: providerVoiceIds,
          model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
          provenance_fingerprint_sha256: "a".repeat(64),
        },
      };
    }),
  };
}


describe("Qwen official voice library", () => {
  it("keeps the exact nine-voice provider-aware order", () => {
    const catalog = officialVoiceCatalogFromWire(wireCatalog());
    expect(catalog.schemaVersion).toBe(OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION);
    expect(catalog.items.map((item) => item.presetId)).toEqual(OFFICIAL_VOICE_PRESET_IDS);
    expect(catalog.items[0]?.provenance.providerVoiceIds.local_qwen3_tts).toBe("Serena");
    expect(catalog.items.find((item) => item.presetId === "qwen.ClearMale")?.provenance.providerVoiceIds[
      "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"
    ]).toBe("longanlufeng");
  });

  it("builds dynamic four-language groups and rejects reordered inventory", () => {
    const catalog = officialVoiceCatalogFromWire(wireCatalog());
    const model = createOfficialVoiceLibraryModel(catalog, "zh-CN");
    expect(model.status).toBe("ready");
    if (model.status !== "ready") throw new Error("expected ready Qwen catalog");
    expect(model.itemCount).toBe(9);
    expect(model.groups.map((group) => group.items.length)).toEqual([6, 1, 1, 1]);
    expect(model.groups.map((group) => group.label)).toEqual([
      "中文（6）", "English（1）", "日本語（1）", "한국어（1）",
    ]);
    const filtered = filterOfficialVoiceLibraryGroups(model.groups, "Aiden", "all");
    expect(filtered[0]?.items.map((item) => item.item.presetId)).toEqual([
      "qwen.ClearMale",
    ]);

    const invalid = {
      ...catalog,
      items: [...catalog.items].reverse(),
    };
    expect(createOfficialVoiceLibraryModel(invalid, "zh-CN").status).toBe("invalid");
  });

  it("blocks use for missing cloud mappings without changing local preview availability", () => {
    const catalog = officialVoiceCatalogFromWire(wireCatalog());
    const warm = catalog.items.find((item) => item.presetId === "qwen.WarmFemale")!;
    const vivian = catalog.items.find((item) => item.presetId === "qwen.Vivian")!;
    const cloud = {
      providerId: "aliyun_qwen_audio_tts" as const,
      aliyunModelId: "qwen-audio-3.0-tts-plus" as const,
    };
    expect(officialVoiceIsAvailableForProvider(warm, cloud)).toBe(true);
    expect(officialVoiceIsAvailableForProvider(vivian, cloud)).toBe(false);
    const model = createOfficialVoiceLibraryModel(catalog, "zh-CN", cloud);
    if (model.status !== "ready") throw new Error("expected ready Qwen catalog");
    const vivianCard = model.groups.flatMap((group) => group.items)
      .find(({ item }) => item.presetId === "qwen.Vivian");
    expect(vivianCard).toMatchObject({
      providerAvailable: false,
      providerAvailabilityLabel: "仅本地可用",
    });
    expect(vivian.previewableNow).toBe(true);
  });

  it("renders cloud-only use guards while keeping local preview keyboard reachable", () => {
    const harness = createComponentHarness();
    const Library = createOfficialVoiceLibrary(harness.React);
    const props = {
      novelId: "novel-1",
      catalog: officialVoiceCatalogFromWire(wireCatalog()),
      target: {
        kind: "narrator" as const,
        targetLanguage: "zh-CN",
        expectedSettingsVersion: 1,
      },
      providerSelection: {
        providerId: "aliyun_qwen_audio_tts" as const,
        aliyunModelId: "qwen-audio-3.0-tts-plus" as const,
      },
      onUse: vi.fn(),
      onPreview: vi.fn(),
    };
    harness.render(Library, props);
    harness.flushEffects();
    const tree = harness.render(Library, props);
    const all = elements(tree);
    const vivianUse = all.find((element) => (
      element.type === "input" && element.props.value === "qwen.Vivian"
    ));
    const warmUse = all.find((element) => (
      element.type === "input" && element.props.value === "qwen.WarmFemale"
    ));
    expect(vivianUse?.props.disabled).toBe(true);
    expect(vivianUse?.props["aria-describedby"]).toContain("availability");
    expect(warmUse?.props.disabled).toBe(false);
    const vivianPreview = previewButton(tree, "qwen.Vivian");
    expect(vivianPreview.type).toBe("button");
    expect(vivianPreview.props.type).toBe("button");
    expect(vivianPreview.props.disabled).toBe(false);
  });

  it("aborts the previous card preview on repeated or cross-card clicks and cleans up on unmount", async () => {
    const harness = createComponentHarness();
    const Library = createOfficialVoiceLibrary(harness.React);
    const pending: Array<{ signal: AbortSignal; resolve: () => void }> = [];
    const props = {
      novelId: "novel-1",
      catalog: officialVoiceCatalogFromWire(wireCatalog()),
      target: {
        kind: "narrator" as const,
        targetLanguage: "zh-CN",
        expectedSettingsVersion: 1,
      },
      onUse: vi.fn(),
      onPreview: vi.fn((_novelId: string, _item: unknown, signal: AbortSignal) => (
        new Promise<void>((resolve) => pending.push({ signal, resolve }))
      )),
    };
    harness.render(Library, props);
    harness.flushEffects();
    let tree = harness.render(Library, props);
    (previewButton(tree, "qwen.WarmFemale").props.onClick as () => void)();
    await Promise.resolve();
    expect(pending).toHaveLength(1);

    tree = harness.render(Library, props);
    (previewButton(tree, "qwen.Vivian").props.onClick as () => void)();
    await Promise.resolve();
    expect(pending).toHaveLength(2);
    expect(pending[0]!.signal.aborted).toBe(true);
    expect(pending[1]!.signal.aborted).toBe(false);
    tree = harness.render(Library, props);
    const cards = elements(tree).filter((element) => element.props["data-official-preset-id"]);
    expect(cards.find((card) => card.props["data-official-preset-id"] === "qwen.WarmFemale")?.props[
      "data-preview-phase"
    ]).toBe("idle");
    expect(cards.find((card) => card.props["data-official-preset-id"] === "qwen.Vivian")?.props[
      "data-preview-phase"
    ]).toBe("loading");

    pending[1]!.resolve();
    for (let index = 0; index < 3; index += 1) await Promise.resolve();
    tree = harness.render(Library, props);
    expect(elements(tree).find((element) => element.props["data-official-preset-id"] === "qwen.Vivian")?.props[
      "data-preview-phase"
    ]).toBe("ready");
    harness.unmount();
    expect(pending[1]!.signal.aborted).toBe(true);
  });

  it("keeps the current binding when a local preview fails", async () => {
    const harness = createComponentHarness();
    const Library = createOfficialVoiceLibrary(harness.React);
    const onUse = vi.fn();
    const props = {
      novelId: "novel-1",
      catalog: officialVoiceCatalogFromWire(wireCatalog()),
      activePresetId: "qwen.WarmFemale",
      target: {
        kind: "narrator" as const,
        targetLanguage: "zh-CN",
        expectedSettingsVersion: 1,
      },
      onUse,
      onPreview: vi.fn(async () => { throw new Error("local model unavailable"); }),
    };
    harness.render(Library, props);
    harness.flushEffects();
    let tree = harness.render(Library, props);
    (previewButton(tree, "qwen.Vivian").props.onClick as () => void)();
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
    tree = harness.render(Library, props);
    const all = elements(tree);
    expect(all.find((element) => element.props["data-official-preset-id"] === "qwen.Vivian")?.props[
      "data-preview-phase"
    ]).toBe("error");
    expect(all.find((element) => (
      element.type === "input" && element.props.value === "qwen.WarmFemale"
    ))?.props.checked).toBe(true);
    expect(onUse).not.toHaveBeenCalled();
  });

  it("creates narrator and character requests without hidden fields", () => {
    expect(createOfficialVoiceSelectionRequest("qwen.WarmFemale", {
      kind: "narrator",
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 3,
    })).toEqual({
      presetId: "qwen.WarmFemale",
      targetKind: "narrator",
      expectedSettingsVersion: 3,
    });
    expect(createOfficialVoiceSelectionRequest("qwen.ClearMale", {
      kind: "character",
      characterId: "character-1",
      characterName: "林岚",
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 4,
      expectedBindingVersion: 2,
    })).toEqual({
      presetId: "qwen.ClearMale",
      targetKind: "character",
      characterId: "character-1",
      expectedSettingsVersion: 4,
      expectedBindingVersion: 2,
    });
  });

  it("rejects stale or identity-drifted selection receipts", () => {
    const target = {
      kind: "narrator" as const,
      targetLanguage: "zh-CN",
      expectedSettingsVersion: 0,
    };
    const result: OfficialVoiceSelectionResult = {
      replayed: false,
      selectionStillCurrent: true,
      presetId: "qwen.WarmFemale",
      targetKind: "narrator",
      characterId: null,
      settingsVersion: 1,
      bindingVersion: null,
      languageMismatch: false,
    };
    expect(() => assertOfficialVoiceSelectionResult(
      result,
      "qwen.WarmFemale",
      target,
    )).not.toThrow();
    expect(() => assertOfficialVoiceSelectionResult(
      { ...result, selectionStillCurrent: false },
      "qwen.WarmFemale",
      target,
    )).toThrow();
    expect(() => assertOfficialVoiceSelectionResult(
      { ...result, presetId: "qwen.ClearMale" },
      "qwen.WarmFemale",
      target,
    )).toThrow();
  });
});
