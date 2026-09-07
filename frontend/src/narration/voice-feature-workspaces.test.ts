import { afterEach, describe, expect, it, vi } from "vitest";

import type { NanoVoiceExperimentResource } from "./contracts";
import type { VoiceProfileResource } from "./contracts";
import type { NarrationOverviewResponse } from "./contracts";
import type { NanoAdvancedTuningPanelProps, NanoAdvancedTuningReactRuntime } from "./nano-advanced-tuning";
import {
  createNanoAdvancedWorkspace,
  officialPresetDisplayName,
  selectNanoExperimentForTarget,
  type NanoAdvancedWorkspaceApi,
  type NanoAdvancedWorkspaceProps,
} from "./voice-feature-workspaces";


const ADVANCED_VERSION_ID = "10000000-0000-4000-8000-000000000001";
const OFFICIAL_VERSION_ID = "10000000-0000-4000-8000-000000000002";


function experiment(
  state: NanoVoiceExperimentResource["state"],
  versionId = ADVANCED_VERSION_ID,
): NanoVoiceExperimentResource {
  return {
    base_preset_id: "onnx.Zhiming",
    target_kind: "narrator",
    character_id: null,
    state,
    version_id: versionId,
  } as NanoVoiceExperimentResource;
}


describe("Nano advanced workspace history selection", () => {
  it("shows the latest applied experiment only while that Version remains bound", () => {
    const latest = experiment("ready_applied");
    const older = experiment("ready_unapplied", OFFICIAL_VERSION_ID);
    expect(selectNanoExperimentForTarget([latest, older], {
      basePresetId: "onnx.Zhiming",
      targetKind: "narrator",
      characterId: null,
      currentVoiceVersionId: ADVANCED_VERSION_ID,
    })).toBe(latest);

    expect(selectNanoExperimentForTarget([latest, older], {
      basePresetId: "onnx.Zhiming",
      targetKind: "narrator",
      characterId: null,
      currentVoiceVersionId: OFFICIAL_VERSION_ID,
    })).toBeNull();
  });

  it("keeps a current running or unapplied result visible before binding", () => {
    for (const state of ["running", "ready_unapplied"] as const) {
      const current = experiment(state);
      expect(selectNanoExperimentForTarget([current], {
        basePresetId: "onnx.Zhiming",
        targetKind: "narrator",
        characterId: null,
        currentVoiceVersionId: OFFICIAL_VERSION_ID,
      })).toBe(current);
    }
  });
});

interface ElementNode {
  type: unknown;
  props: Record<string, unknown>;
  children: unknown[];
}

function nodes(tree: unknown): ElementNode[] {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (typeof tree !== "object" || tree === null || !("children" in tree)) return [];
  const node = tree as ElementNode;
  return [node, ...node.children.flatMap(nodes)];
}

function content(tree: unknown): string {
  if (typeof tree === "string") return tree;
  if (Array.isArray(tree)) return tree.map(content).join("");
  return typeof tree === "object" && tree !== null && "children" in tree
    ? (tree as ElementNode).children.map(content).join("") : "";
}

function panel(tree: unknown): ElementNode {
  const result = nodes(tree).find((node) => typeof node.type === "function");
  if (!result) throw new Error("panel missing");
  return result;
}

function button(tree: unknown, label: string): ElementNode {
  const result = nodes(tree).find((node) => node.type === "button" && content(node) === label);
  if (!result) throw new Error(`button missing: ${label}`);
  return result;
}

function harness() {
  const states: unknown[] = [];
  const effects: Array<{ deps: readonly unknown[]; cleanup?: () => void }> = [];
  let stateIndex = 0;
  let effectIndex = 0;
  let dirty = false;
  let scheduled: Array<() => void> = [];
  const React: NanoAdvancedTuningReactRuntime = {
    createElement(type, props, ...children): ElementNode { return { type, props: props ?? {}, children }; },
    useState<T>(initial: T | (() => T)) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      return [states[index] as T, (value: T | ((current: T) => T)) => {
        const next = typeof value === "function" ? (value as (current: T) => T)(states[index] as T) : value;
        dirty ||= !Object.is(next, states[index]);
        states[index] = next;
      }];
    },
    useEffect(effect, deps) {
      const index = effectIndex++;
      const previous = effects[index];
      if (!previous || deps.length !== previous.deps.length || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
        scheduled.push(() => {
          previous?.cleanup?.();
          const cleanup = effect();
          effects[index] = { deps, cleanup: typeof cleanup === "function" ? cleanup : undefined };
        });
      }
    },
  };
  return {
    React,
    render<T>(Component: (props: T) => unknown, props: T): unknown {
      let tree: unknown;
      let passes = 0;
      do {
        if (++passes > 15) throw new Error("render did not settle");
        dirty = false;
        stateIndex = effectIndex = 0;
        scheduled = [];
        tree = Component(props);
        scheduled.forEach((run) => run());
      } while (dirty);
      return tree;
    },
    unmount() { effects.forEach((effect) => effect.cleanup?.()); },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function settle(): Promise<void> { for (let i = 0; i < 8; i++) await Promise.resolve(); }

const NOVEL = "novel-a";
const CHARACTER = "character-a";
const commandResource = (changes: Partial<NanoVoiceExperimentResource> = {}): NanoVoiceExperimentResource => ({
  ...experiment("running"), command_id: "command-a", novel_id: NOVEL,
  base_preset_id: "onnx.Junhao", target_kind: "character", character_id: CHARACTER,
  current_settings: null, current_character_binding: null, failure_code: null, retryable: false,
  reused_version: false, ...changes,
});

function setup(initialExperiments: NanoVoiceExperimentResource[] = []) {
  const profiles = [
    { profile_id: "profile-j", name: "CN 欢迎关注模思智能", versions: [{ version_id: "official-j", source_type: "preset", preset_key: "onnx.Junhao" }] },
    { profile_id: "profile-z", name: "CN 说书", versions: [{ version_id: "official-z", source_type: "preset", preset_key: "onnx.Zhiming" }] },
  ] as unknown as VoiceProfileResource[];
  const binding = { character_id: CHARACTER, profile_id: "profile-j", version_id: "official-j", version: 4 };
  const api = {
    listProfiles: vi.fn(async () => ({ items: profiles })),
    listBindings: vi.fn(async () => ({ novel_id: NOVEL, items: [binding] })),
    listExperiments: vi.fn(async () => ({ novel_id: NOVEL, items: initialExperiments })),
    getExperiment: vi.fn(async () => commandResource()),
    createExperiment: vi.fn(async () => commandResource()),
    applyExperiment: vi.fn(async () => commandResource({ state: "ready_applied" })),
    selectOfficialVoice: vi.fn(async () => ({ selection_still_current: true })),
  };
  const props: NanoAdvancedWorkspaceProps = {
    novelId: NOVEL, characters: [], fixedCharacter: { characterId: CHARACTER, characterName: "沈砚" },
    overview: { capabilities: { items: [{ key: "nano_advanced_tuning", state: "enabled", visible: true, actionable: true }] },
      settings: { version: 1, values: { narrator: null } } } as unknown as NarrationOverviewResponse,
    onChanged: vi.fn(), refreshVersion: 0,
  };
  const mount = harness();
  const Component = createNanoAdvancedWorkspace(mount.React, api as unknown as NanoAdvancedWorkspaceApi);
  return { api, props, mount, Component, binding, profiles, render: (next = props) => mount.render(Component, next) };
}

afterEach(() => vi.useRealTimers());

describe("Nano workspace refresh and request fencing", () => {
  it("refreshes the base voice without unmounting the same-target panel or discarding edited parameters", async () => {
    const f = setup();
    f.render(); await settle();
    const first = panel(f.render());
    const child = harness();
    const renderPanel = (node: ElementNode) => child.render(
      node.type as (props: NanoAdvancedTuningPanelProps) => unknown, node.props as unknown as NanoAdvancedTuningPanelProps,
    );
    let tree = renderPanel(first);
    const seed = nodes(tree).find((node) => node.props.id === "anw-nano-tuning-seed")!;
    (seed.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "987654321" } });
    const pending = deferred<{ novel_id: string; items: typeof f.binding[] }>();
    f.api.listBindings.mockImplementationOnce(() => pending.promise);
    const next = { ...f.props, refreshVersion: 1 };
    const during = panel(f.render(next));
    expect(during.type).toBe(first.type);
    expect(during.props.key).toBe(first.props.key);
    expect(nodes(renderPanel(during)).find((node) => node.props.id === seed.props.id)?.props.value).toBe("987654321");
    pending.resolve({ novel_id: NOVEL, items: [{ ...f.binding, profile_id: "profile-z", version_id: "official-z", version: 5 }] });
    await settle();
    const after = panel(f.render(next));
    expect(after.props.basePresetDisplayName).toBe("CN 说书");
    expect(after.props.basePresetId).toBe("onnx.Zhiming");
    tree = renderPanel(after);
    expect(nodes(tree).find((node) => node.props.id === seed.props.id)?.props.value).toBe("987654321");
    expect(f.api.listProfiles).toHaveBeenCalledTimes(2);
    expect(f.props.onChanged).not.toHaveBeenCalled();
  });

  it("keeps edits visible after a same-scope load error and retries locally", async () => {
    const f = setup(); f.render(); await settle();
    const first = panel(f.render());
    f.api.listBindings.mockRejectedValueOnce(new Error("offline"));
    const next = { ...f.props, refreshVersion: 1 };
    f.render(next); await settle();
    const tree = f.render(next);
    expect(panel(tree).props.key).toBe(first.props.key);
    expect(content(tree)).toContain("offline");
    (button(tree, "重试加载").props.onClick as () => void)();
    f.render(next); await settle();
    expect(content(f.render(next))).not.toContain("offline");
    expect(f.props.onChanged).not.toHaveBeenCalled();
  });

  it("fences pending loads and clears the old panel when novel/target changes", async () => {
    const f = setup();
    const pending = deferred<{ novel_id: string; items: typeof f.binding[] }>();
    f.api.listBindings.mockImplementationOnce(() => pending.promise);
    f.render(); await settle();
    const oldSignal = (f.api.listBindings.mock.calls as unknown[][])[0][1] as AbortSignal;
    f.api.listBindings.mockResolvedValue({ novel_id: "novel-b", items: [{ ...f.binding, character_id: "character-b" }] });
    f.api.listExperiments.mockResolvedValue({ novel_id: "novel-b", items: [] });
    const next = { ...f.props, novelId: "novel-b", fixedCharacter: { characterId: "character-b", characterName: "新人物" } };
    expect(nodes(f.render(next)).some((node) => typeof node.type === "function")).toBe(false);
    expect(oldSignal.aborted).toBe(true);
    pending.resolve({ novel_id: NOVEL, items: [f.binding] }); await settle();
    expect(panel(f.render(next)).props.draftScopeKey).toBe("novel-b:character-b");
    expect(f.props.onChanged).not.toHaveBeenCalled();
  });

  it("continues same-state polls without overlap and stops after completion", async () => {
    vi.useFakeTimers();
    const f = setup([commandResource()]); f.render(); await settle(); f.render();
    const first = deferred<NanoVoiceExperimentResource>();
    f.api.getExperiment.mockImplementationOnce(() => first.promise);
    await vi.advanceTimersByTimeAsync(1_000); f.render();
    const signal = (f.api.getExperiment.mock.calls as unknown[][])[0][2] as AbortSignal;
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(5_000); f.render();
    expect(f.api.getExperiment).toHaveBeenCalledTimes(1);
    first.resolve(commandResource()); await settle(); f.render();
    const second = deferred<NanoVoiceExperimentResource>();
    f.api.getExperiment.mockImplementationOnce(() => second.promise);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(f.api.getExperiment).toHaveBeenCalledTimes(2);
    second.resolve(commandResource({ state: "ready_unapplied" })); await settle(); f.render(); await settle(); f.render();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(f.api.getExperiment).toHaveBeenCalledTimes(2);
    expect(f.props.onChanged).toHaveBeenCalledTimes(1);
  });

  it("retries polling errors and ignores a late response after target change", async () => {
    vi.useFakeTimers();
    const f = setup([commandResource()]); f.render(); await settle(); f.render();
    f.api.getExperiment.mockRejectedValueOnce(new Error("offline"));
    await vi.advanceTimersByTimeAsync(1_000); let tree = f.render();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(f.api.getExperiment).toHaveBeenCalledTimes(1);
    (button(tree, "重试刷新状态").props.onClick as () => void)(); f.render();
    const pending = deferred<NanoVoiceExperimentResource>();
    f.api.getExperiment.mockImplementationOnce(() => pending.promise);
    await vi.advanceTimersByTimeAsync(1_000);
    const signal = (f.api.getExperiment.mock.calls as unknown[][])[1][2] as AbortSignal;
    const next = { ...f.props, fixedCharacter: { characterId: "character-b", characterName: "另一人" } };
    f.api.listBindings.mockResolvedValue({ novel_id: NOVEL, items: [{ ...f.binding, character_id: "character-b" }] });
    f.api.listExperiments.mockResolvedValue({ novel_id: NOVEL, items: [] });
    f.render(next); await settle();
    expect(signal.aborted).toBe(true);
    pending.resolve(commandResource({ state: "ready_applied" })); await settle();
    tree = f.render(next);
    expect(panel(tree).props.experiment).toBeNull();
    expect(f.props.onChanged).not.toHaveBeenCalled();
  });

  it("aborts a pending poll on unmount and ignores successful late completion", async () => {
    vi.useFakeTimers();
    const f = setup([commandResource()]); f.render(); await settle(); f.render();
    const pending = deferred<NanoVoiceExperimentResource>();
    f.api.getExperiment.mockImplementationOnce(() => pending.promise);
    await vi.advanceTimersByTimeAsync(1_000);
    const signal = (f.api.getExperiment.mock.calls as unknown[][])[0][2] as AbortSignal;
    f.mount.unmount();
    expect(signal.aborted).toBe(true);
    pending.resolve(commandResource({ state: "ready_applied" })); await settle();
    expect(f.props.onChanged).not.toHaveBeenCalled();
  });

  it("does not show an old target/base experiment after an external official selection", async () => {
    vi.useFakeTimers();
    const f = setup([commandResource()]); f.render(); await settle(); f.render();
    await vi.advanceTimersByTimeAsync(1_000); f.render();
    f.api.listBindings.mockResolvedValue({ novel_id: NOVEL, items: [{ ...f.binding, profile_id: "profile-z", version_id: "official-z", version: 6 }] });
    const next = { ...f.props, refreshVersion: 1 };
    f.render(next); await settle();
    expect(panel(f.render(next)).props.experiment).toBeNull();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(f.api.getExperiment).toHaveBeenCalledTimes(1);
  });

  it("prevents double submission and rejects late mutation results after switching scope", async () => {
    const f = setup(); f.render(); await settle();
    const p = panel(f.render()).props as unknown as NanoAdvancedTuningPanelProps;
    const pending = deferred<NanoVoiceExperimentResource>();
    f.api.createExperiment.mockImplementationOnce(() => pending.promise);
    const command = {
      basePresetId: "onnx.Junhao", ...p.target,
      parameters: { seed: "1234", textTemperatureMilli: 1000, textTopPMilli: 1000, textTopK: 50,
        audioTemperatureMilli: 800, audioTopPMilli: 950, audioTopK: 25, audioRepetitionPenaltyMilli: 1200,
        sampleMode: "full" as const, maxNewFrames: 375 as const },
    };
    p.onCreateExperiment(command); p.onCreateExperiment(command); f.render();
    expect(f.api.createExperiment).toHaveBeenCalledTimes(1);
    const signal = (f.api.createExperiment.mock.calls as unknown[][])[0][3] as AbortSignal;
    f.render({ ...f.props, fixedCharacter: { characterId: "character-b", characterName: "另一人" } });
    expect(signal.aborted).toBe(true);
    pending.resolve(commandResource({ state: "ready_applied" })); await settle();
    expect(f.props.onChanged).not.toHaveBeenCalled();
  });

  it("does not reuse historical command CAS after restoring the official version", async () => {
    const history = commandResource({ state: "ready_applied", version_id: ADVANCED_VERSION_ID,
      current_settings: { version: 99 } as NanoVoiceExperimentResource["current_settings"],
      current_character_binding: { character_id: CHARACTER, version: 99 } as NanoVoiceExperimentResource["current_character_binding"],
    });
    const f = setup([history]);
    f.profiles[0] = { ...f.profiles[0], versions: [
      ...f.profiles[0].versions,
      { ...f.profiles[0].versions[0], source_type: "generated", version_id: ADVANCED_VERSION_ID },
    ] };
    f.api.listBindings.mockResolvedValue({ novel_id: NOVEL, items: [{ ...f.binding, version_id: ADVANCED_VERSION_ID }] });
    f.render(); await settle();
    let p = panel(f.render()).props as unknown as NanoAdvancedTuningPanelProps;
    expect(p.experiment?.state).toBe("ready_applied");
    expect(p.target.expectedBindingVersion).toBe(4);
    expect(p.target.expectedSettingsVersion).toBe(1);
    const pending = deferred<{ selection_still_current: boolean }>();
    f.api.selectOfficialVoice.mockImplementationOnce(() => pending.promise);
    p.onRestoreOfficialVoice({ ...p.target, basePresetId: p.basePresetId }); f.render();
    f.api.listBindings.mockResolvedValue({ novel_id: NOVEL, items: [{ ...f.binding, version: 5 }] });
    pending.resolve({ selection_still_current: true }); await settle();
    f.render(); await settle();
    p = panel(f.render()).props as unknown as NanoAdvancedTuningPanelProps;
    expect(p.experiment).toBeNull();
    expect(p.target.expectedBindingVersion).toBe(5);
    expect(f.props.onChanged).toHaveBeenCalledTimes(1);
  });

  it("rejects mismatched poll identity without a parent refresh and permits local retry", async () => {
    vi.useFakeTimers();
    const f = setup([commandResource()]); f.render(); await settle(); f.render();
    f.api.getExperiment.mockResolvedValueOnce(commandResource({ character_id: "another-character" }));
    await vi.advanceTimersByTimeAsync(1_000);
    const tree = f.render();
    expect(content(tree)).toContain("不属于当前目标");
    expect(panel(tree).props.experiment).toEqual(expect.objectContaining({ state: "running" }));
    expect(f.props.onChanged).not.toHaveBeenCalled();
    expect(button(tree, "重试刷新状态")).toBeDefined();
  });
});


describe("Nano advanced workspace display names", () => {
  it("uses the official directory name instead of exposing the internal manifest voice", () => {
    const profiles = [{
      name: "CN 机车",
      versions: [{ source_type: "preset", preset_key: "onnx.Yuewen" }],
    }] as unknown as readonly VoiceProfileResource[];

    expect(officialPresetDisplayName(profiles, "onnx.Yuewen")).toBe("CN 机车");
    expect(officialPresetDisplayName([], "onnx.Yuewen")).toBe("官方音色");
  });
});
