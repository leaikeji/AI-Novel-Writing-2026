import { describe, expect, it, vi } from "vitest";

import {
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type NarrationSettingsResource,
  type CharacterVoiceBindingResource,
  type OfficialVoiceSelectionResponse,
  type VoiceProfileResource,
  type OfficialPresetCatalogResponse,
} from "./contracts";
import {
  activeOfficialPresetId,
  createOfficialVoicePreviewPlayer,
  createOfficialVoiceSelectionPanel,
  getAndPlayOfficialVoicePreviewAudio,
  officialVoiceSelectionDisabled,
  officialVoiceSelectionResult,
  officialVoiceSelectionWireRequest,
  type OfficialVoiceSelectionPanelApi,
  type OfficialVoiceSelectionPanelProps,
} from "./official-voice-selection-panel";
import type { OfficialVoiceSelectionResult } from "./official-voice-library";


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const PROFILE_ID = "22222222-2222-4222-8222-222222222222";
const VERSION_ID = "33333333-3333-4333-8333-333333333333";
const CHARACTER_ID = "44444444-4444-4444-8444-444444444444";
const COMMAND_ID = "55555555-5555-4555-8555-555555555555";
const AT = "2026-08-29T00:00:00Z";
const EVIDENCE = OFFICIAL_PRESET_EVIDENCE[0];


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function createEffectHarness() {
  const states: Array<{ value: unknown }> = [];
  const refs: Array<{ current: unknown }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const effectSlots: Array<{ deps: readonly unknown[]; cleanup?: () => void }> = [];
  let effects: Array<() => void | (() => void)> = [];
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
    useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void {
      const index = effectIndex++;
      const previous = effectSlots[index];
      if (previous && dependencies.length === previous.deps.length
        && dependencies.every((value, i) => Object.is(value, previous.deps[i]))) return;
      effects.push(() => {
        previous?.cleanup?.();
        const cleanup = effect();
        effectSlots[index] = { deps: dependencies, cleanup: typeof cleanup === "function" ? cleanup : undefined };
      });
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
    flushEffects(): void {
      const pending = effects;
      effects = [];
      for (const effect of pending) effect();
    },
  };
}


function settings(): NarrationSettingsResource {
  return {
    version: 3,
    values: {
      narrator: { profile_id: PROFILE_ID, version_id: VERSION_ID },
      language: "zh-CN",
    },
  } as unknown as NarrationSettingsResource;
}


function officialProfile(
  activation: "preview_confirmed" | "explicit_official_preset_selection",
): VoiceProfileResource {
  const direct = activation === "explicit_official_preset_selection";
  return {
    profile_id: PROFILE_ID,
    versions: [{
      schema_version: NARRATION_VOICE_SCHEMA_VERSION,
      version_id: VERSION_ID,
      profile_id: PROFILE_ID,
      version_number: 1,
      source_type: "preset",
      state: "locked",
      provider_id: "qwen-tts",
      model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
      model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
      preset_key: EVIDENCE.presetId,
      language: "zh-CN",
      fingerprint: "a".repeat(64),
      quality_state: direct ? "pending" : "accepted",
      activation_basis: activation,
      validation_basis: direct ? "not_required" : "human_accepted",
      rights: {
        state: "active",
        source_kind: "official_preset",
      },
      official_preset: {
        schema_version: "qwen-tts-preset-provenance/1",
        catalog_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
        preset_id: EVIDENCE.presetId,
        local_model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
        local_model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
        provider_voice_ids: {
          local_qwen3_tts: EVIDENCE.localVoiceId,
          "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus": EVIDENCE.aliyunPlusVoiceId,
          "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash": EVIDENCE.aliyunFlashVoiceId,
        },
        model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
        provenance_fingerprint_sha256: "a".repeat(64),
      },
    }],
  } as unknown as VoiceProfileResource;
}


describe("official voice selection panel adapters", () => {
  function setupRefresh() {
    const harness = createEffectHarness();
    const reads: Array<{ resolve: (value: OfficialPresetCatalogResponse) => void; signal?: AbortSignal }> = [];
    const api = {
      listOfficialVoicePresets: vi.fn((signal?: AbortSignal) => new Promise<OfficialPresetCatalogResponse>((resolve) => {
        reads.push({ resolve, signal });
      })),
      listVoiceProfiles: vi.fn(), getCharacterVoiceBinding: vi.fn(), selectOfficialVoice: vi.fn(),
      getOfficialVoicePreviewAudio: vi.fn(),
    } satisfies OfficialVoiceSelectionPanelApi;
    const Panel = createOfficialVoiceSelectionPanel(harness.React, api);
    const binding = { novel_id: NOVEL_ID, character_id: CHARACTER_ID, version: 7,
      profile_id: PROFILE_ID, version_id: VERSION_ID, language: "zh-CN" } as CharacterVoiceBindingResource;
    const profiles = [officialProfile("explicit_official_preset_selection")];
    const props: OfficialVoiceSelectionPanelProps = {
      novelId: NOVEL_ID, settings: settings(),
      target: { kind: "character", characterId: CHARACTER_ID, characterName: "林岚" },
      capabilities: { items: [] } as unknown as NarrationCapabilities,
      authorization: {} as NarrationAuthorizationState,
      projection: { phase: "ready", binding, profiles },
    };
    const resolve = async (index: number) => {
      reads[index].resolve({ schema_version: "qwen-tts-preset-catalog/2", items: [] } as unknown as OfficialPresetCatalogResponse);
      for (let i = 0; i < 5; i++) await Promise.resolve();
    };
    return { harness, Panel, props, reads, resolve, binding, profiles };
  }

  it("keeps the same catalog subtree while a character projection refreshes", async () => {
    const { harness, Panel, props, reads, resolve, binding, profiles } = setupRefresh();
    harness.render(Panel, props);
    harness.flushEffects();
    await resolve(0);
    const ready = harness.render(Panel, props);
    const pendingProps = { ...props, projection: { phase: "loading" as const } };
    harness.render(Panel, pendingProps);
    harness.flushEffects();
    const pending = harness.render(Panel, pendingProps);
    expect(pending.type).toBe(ready.type);
    expect(pending.props.catalog).toBe(ready.props.catalog);
    expect(pending.props.loading).toBe(false);
    const refreshedProps = { ...props, projection: { phase: "ready" as const, binding: { ...binding, version: 8 }, profiles } };
    harness.render(Panel, refreshedProps);
    harness.flushEffects();
    expect(reads).toHaveLength(2);
    expect(harness.render(Panel, refreshedProps).props.catalog).toBe(ready.props.catalog);
    await resolve(1);
    expect(harness.render(Panel, refreshedProps).props.target).toMatchObject({ expectedBindingVersion: 8 });
  });

  it("does not roll back a successful receipt with an older in-flight or parent projection", async () => {
    const { harness, Panel, props, reads, resolve, binding, profiles } = setupRefresh();
    harness.render(Panel, props); harness.flushEffects(); await resolve(0);
    const changed = { ...props, projection: { phase: "ready" as const, binding, profiles: [...profiles] } };
    const panel = harness.render(Panel, changed); harness.flushEffects();
    (panel.props.onApplied as (result: OfficialVoiceSelectionResult) => void)({
      presetId: "qwen.ClearMale", settingsVersion: 3, bindingVersion: 8,
    } as OfficialVoiceSelectionResult);
    expect(reads[1].signal?.aborted).toBe(true);
    await resolve(1);
    const olderParent = { ...changed, projection: { phase: "ready" as const, binding, profiles: [...profiles] } };
    harness.render(Panel, olderParent); harness.flushEffects(); await resolve(2);
    const current = harness.render(Panel, olderParent);
    expect(current.props.activePresetId).toBe("qwen.ClearMale");
    expect(current.props.target).toMatchObject({ expectedBindingVersion: 8 });
  });

  it("hides old target data before effects and ignores late responses and callbacks", async () => {
    const { harness, Panel, props, resolve } = setupRefresh();
    harness.render(Panel, props); harness.flushEffects(); await resolve(0);
    const old = harness.render(Panel, props);
    const next = { ...props, novelId: COMMAND_ID };
    expect(harness.render(Panel, next).props.catalog).toBeNull();
    (old.props.onApplied as (result: OfficialVoiceSelectionResult) => void)({
      presetId: "qwen.ClearMale", settingsVersion: 99, bindingVersion: 99,
    } as OfficialVoiceSelectionResult);
    harness.flushEffects();
    const third = { ...next, novelId: VERSION_ID };
    harness.render(Panel, third); harness.flushEffects();
    await resolve(1);
    expect(harness.render(Panel, third).props.catalog).toBeNull();
    await resolve(2);
    expect(harness.render(Panel, third).props.target).toMatchObject({ expectedBindingVersion: 7 });
  });

  it("gets and plays one stateless local WAV without applying a binding", async () => {
    const ready = {
      audio: new Blob([new Uint8Array([82, 73, 70, 70])], { type: "audio/wav" }),
      content_type: "audio/wav",
      provider_id: "local_qwen3_tts",
      model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
      model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
      official_speaker: EVIDENCE.localVoiceId,
    } as const;
    const get = vi.fn(async () => ready);
    const play = vi.fn(async () => undefined);
    const signal = new AbortController().signal;
    await getAndPlayOfficialVoicePreviewAudio(
      { getOfficialVoicePreviewAudio: get },
      { play },
      NOVEL_ID,
      EVIDENCE.presetId,
      "zh-CN",
      signal,
    );

    expect(get).toHaveBeenCalledWith(
      NOVEL_ID,
      { preset_id: EVIDENCE.presetId, language: "zh-CN" },
      signal,
    );
    expect(play).toHaveBeenCalledWith(ready, signal);
  });

  it("stops audio and revokes its Blob URL when a preview is aborted", async () => {
    const listeners = new Map<string, () => void>();
    const audio = {
      pause: vi.fn(),
      play: vi.fn(async () => undefined),
      load: vi.fn(),
      removeAttribute: vi.fn(),
      addEventListener: vi.fn((type: string, listener: () => void) => listeners.set(type, listener)),
    };
    const runtime = {
      createObjectURL: vi.fn(() => "blob:qwen-preview"),
      revokeObjectURL: vi.fn(),
      createAudio: vi.fn(() => audio),
    };
    const controller = new AbortController();
    const player = createOfficialVoicePreviewPlayer(runtime);
    await player.play({
      audio: new Blob([new Uint8Array([1])], { type: "audio/wav" }),
      content_type: "audio/wav",
      provider_id: "local_qwen3_tts",
      model_id: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
      model_revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
      official_speaker: EVIDENCE.localVoiceId,
    }, controller.signal);

    controller.abort();
    expect(audio.pause).toHaveBeenCalledTimes(1);
    expect(audio.removeAttribute).toHaveBeenCalledWith("src");
    expect(audio.load).toHaveBeenCalledTimes(1);
    expect(runtime.revokeObjectURL).toHaveBeenCalledWith("blob:qwen-preview");
    listeners.get("ended")?.();
    expect(runtime.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("maps narrator and character commands to the exact snake-case CAS request", () => {
    expect(officialVoiceSelectionWireRequest({
      presetId: EVIDENCE.presetId,
      targetKind: "narrator",
      expectedSettingsVersion: 3,
    })).toEqual({
      preset_id: EVIDENCE.presetId,
      target_kind: "narrator",
      character_id: null,
      expected_settings_version: 3,
      expected_binding_version: null,
    });
    expect(officialVoiceSelectionWireRequest({
      presetId: EVIDENCE.presetId,
      targetKind: "character",
      characterId: CHARACTER_ID,
      expectedSettingsVersion: 3,
      expectedBindingVersion: 7,
    })).toEqual({
      preset_id: EVIDENCE.presetId,
      target_kind: "character",
      character_id: CHARACTER_ID,
      expected_settings_version: 3,
      expected_binding_version: 7,
    });
  });

  it("preserves frozen result identity separately from current projections", () => {
    const response = {
      replayed: true,
      selection_still_current: false,
      frozen_result: {
        command_id: COMMAND_ID,
        preset_id: EVIDENCE.presetId,
        target_kind: "character",
        character_id: CHARACTER_ID,
        profile_id: PROFILE_ID,
        version_id: VERSION_ID,
        settings_version: 3,
        binding_version: 8,
        target_language: "zh-CN",
        language_mismatch: false,
        completed_at: AT,
      },
    } as unknown as OfficialVoiceSelectionResponse;
    expect(officialVoiceSelectionResult(response)).toEqual({
      replayed: true,
      selectionStillCurrent: false,
      presetId: EVIDENCE.presetId,
      targetKind: "character",
      characterId: CHARACTER_ID,
      settingsVersion: 3,
      bindingVersion: 8,
      languageMismatch: false,
    });
  });

  it("recognizes both direct and legacy human-confirmed official bindings, but no draft", () => {
    expect(activeOfficialPresetId(settings(), null, { kind: "narrator" }, [
      officialProfile("explicit_official_preset_selection"),
    ])).toBe(EVIDENCE.presetId);
    expect(activeOfficialPresetId(settings(), null, { kind: "narrator" }, [
      officialProfile("preview_confirmed"),
    ])).toBe(EVIDENCE.presetId);
    const draft = officialProfile("explicit_official_preset_selection");
    const changed = {
      ...draft,
      versions: [{ ...draft.versions[0]!, state: "draft" as const }],
    };
    expect(activeOfficialPresetId(settings(), null, { kind: "narrator" }, [changed]))
      .toBeNull();
  });

  it("blocks mutation unless owner permissions and all three narrow capabilities are actionable", () => {
    const capabilities = {
      items: ["narration_product", "reading_settings", "preset_voice_source"].map((key) => ({
        key,
        state: "enabled",
        visible: true,
        actionable: true,
      })),
    } as unknown as NarrationCapabilities;
    const authorization = {
      can_read: true,
      can_configure: true,
      can_manage_voice_assets: true,
    } as unknown as NarrationAuthorizationState;
    expect(officialVoiceSelectionDisabled(capabilities, authorization)).toBe(false);
    expect(officialVoiceSelectionDisabled(capabilities, {
      ...authorization,
      can_configure: false,
    })).toBe(true);
  });

  it("uses a controlled character projection without duplicate binding or profile reads", () => {
    const harness = createEffectHarness();
    const api = {
      listOfficialVoicePresets: vi.fn(async () => ({ items: [] })),
      listVoiceProfiles: vi.fn(),
      getCharacterVoiceBinding: vi.fn(),
      selectOfficialVoice: vi.fn(),
      getOfficialVoicePreviewAudio: vi.fn(),
    } as unknown as OfficialVoiceSelectionPanelApi;
    const binding = {
      novel_id: NOVEL_ID,
      character_id: CHARACTER_ID,
      binding_policy: "dedicated",
      profile_id: PROFILE_ID,
      version_id: VERSION_ID,
      language: "zh-CN",
      version: 7,
    } as unknown as CharacterVoiceBindingResource;
    const Panel = createOfficialVoiceSelectionPanel(harness.React, api);

    harness.render(Panel, {
      novelId: NOVEL_ID,
      settings: settings(),
      target: { kind: "character", characterId: CHARACTER_ID, characterName: "林岚" },
      capabilities: { items: [] } as unknown as NarrationCapabilities,
      authorization: {} as unknown as NarrationAuthorizationState,
      projection: {
        phase: "ready",
        binding,
        profiles: [officialProfile("explicit_official_preset_selection")],
      },
    });
    harness.flushEffects();

    expect(api.listOfficialVoicePresets).toHaveBeenCalledTimes(1);
    expect(api.listVoiceProfiles).not.toHaveBeenCalled();
    expect(api.getCharacterVoiceBinding).not.toHaveBeenCalled();
  });
});
