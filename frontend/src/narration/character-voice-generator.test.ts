import { describe, expect, it, vi } from "vitest";

import {
  CHARACTER_VOICE_GENERATION_ACTIVE_STATES,
  CHARACTER_VOICE_GENERATION_CONTRACT_VERSION,
  CHARACTER_VOICE_GENERATION_FAILURE_STATES,
  CHARACTER_VOICE_GENERATION_READY_STATES,
  characterVoiceGenerationSnapshotIsValid,
  createCharacterVoiceGenerator,
  deriveCharacterVoiceGeneratorState,
  type CharacterVoiceGenerationSnapshot,
  type CharacterVoiceGenerationState,
  type CharacterVoiceGeneratorProps,
  type CharacterVoiceGeneratorReactRuntime,
} from "./character-voice-generator";
import {
  CHARACTER_VOICE_GENERATOR_STYLE_ID,
  CHARACTER_VOICE_GENERATOR_STYLES,
} from "./styles/character-voice-generator";

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
  return value !== null && typeof value === "object"
    && "type" in value && "props" in value && "children" in value;
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

function button(root: unknown): FakeElement | null {
  return findAll(root, (element) => element.type === "button")[0] ?? null;
}

function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}

function createHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  let pending: Array<{
    readonly index: number;
    readonly effect: () => void | (() => void);
    readonly dependencies: readonly unknown[];
  }> = [];
  const React: CharacterVoiceGeneratorReactRuntime = {
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
    useEffect(effect, dependencies) {
      const index = effectIndex++;
      if (!sameDependencies(effects[index]?.dependencies, dependencies)) {
        pending.push({ index, effect, dependencies: [...dependencies] });
      }
    },
    useRef<T>(initial: T) {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): unknown {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pending = [];
      const tree = Component(props);
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

const CHARACTER_ID = "10000000-0000-4000-8000-000000000001";
const COMMAND_ID = "20000000-0000-4000-8000-000000000001";
const DRAFT_ID = "30000000-0000-4000-8000-000000000001";
const VERSION_ID = "40000000-0000-4000-8000-000000000001";

function snapshot(
  state: CharacterVoiceGenerationState,
  patch: Partial<CharacterVoiceGenerationSnapshot> = {},
): CharacterVoiceGenerationSnapshot {
  const active = (CHARACTER_VOICE_GENERATION_ACTIVE_STATES as readonly string[]).includes(state);
  const ready = (CHARACTER_VOICE_GENERATION_READY_STATES as readonly string[]).includes(state);
  const failure = (CHARACTER_VOICE_GENERATION_FAILURE_STATES as readonly string[]).includes(state);
  return {
    contractVersion: CHARACTER_VOICE_GENERATION_CONTRACT_VERSION,
    commandId: COMMAND_ID,
    draftId: DRAFT_ID,
    characterId: CHARACTER_ID,
    state,
    progressPercent: ready ? 100 : active ? 42 : 61,
    cancellable: active,
    retryable: failure && state !== "cancelled" && state !== "superseded",
    terminal: !active,
    failureCode: failure ? `VOICE_GENERATOR_${state.toUpperCase()}` : null,
    generatedVersionId: ready ? VERSION_ID : null,
    selectionStillCurrent: state === "ready_applied",
    currentBindingVersion: 9,
    createdAt: "2026-08-30T10:00:00.000Z",
    updatedAt: "2026-08-30T10:01:00.000Z",
    ...patch,
  };
}

function baseProps(
  overrides: Partial<CharacterVoiceGeneratorProps> = {},
): CharacterVoiceGeneratorProps {
  return {
    capabilityEnabled: true,
    canConfigure: true,
    characterId: CHARACTER_ID,
    characterName: "顾临舟",
    expectedBindingVersion: 7,
    workspaceSelection: { timelineId: null, characterInstanceId: null },
    refreshIntervalMs: 0,
    onStartGeneration: vi.fn(async () => snapshot("queued")),
    onRefreshGeneration: vi.fn(async () => snapshot("generating_voice")),
    onCancelGeneration: vi.fn(async () => snapshot("cancelled", { retryable: false })),
    onRetryGeneration: vi.fn(async () => snapshot("queued")),
    onUseGeneratedVoice: vi.fn(async () => snapshot("ready_applied")),
    ...overrides,
  };
}

describe("character voice generator state", () => {
  it("covers every frozen active, ready and failure state", () => {
    for (const state of CHARACTER_VOICE_GENERATION_ACTIVE_STATES) {
      expect(deriveCharacterVoiceGeneratorState({
        capabilityEnabled: true,
        characterId: CHARACTER_ID,
        expectedBindingVersion: 1,
        command: snapshot(state),
      })).toMatchObject({ phase: state, tone: "progress", terminal: false });
    }
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: true,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("ready_applied"),
    })).toMatchObject({ phase: "ready_applied", tone: "success", terminal: true });
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: true,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("ready_unapplied"),
    })).toMatchObject({
      phase: "ready_unapplied",
      primaryAction: "apply",
      primaryLabel: "使用此音色",
      tone: "warning",
    });
    for (const state of CHARACTER_VOICE_GENERATION_FAILURE_STATES) {
      const derived = deriveCharacterVoiceGeneratorState({
        capabilityEnabled: true,
        characterId: CHARACTER_ID,
        expectedBindingVersion: 1,
        command: snapshot(state),
      });
      expect(derived).toMatchObject({ phase: state, terminal: true });
      expect(["retry", "start"]).toContain(derived.primaryAction);
    }
  });

  it("accepts the backend cancellation projection without a failure code", () => {
    const cancelled = snapshot("cancelled", {
      failureCode: null,
      retryable: false,
      progressPercent: 100,
    });

    expect(characterVoiceGenerationSnapshotIsValid(cancelled)).toBe(true);
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: true,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: cancelled,
    })).toMatchObject({
      phase: "cancelled",
      primaryAction: "start",
      primaryLabel: "重新生成",
      tone: "warning",
    });
  });

  it("fails closed on cross-character, contradictory terminal and incomplete ready projections", () => {
    expect(characterVoiceGenerationSnapshotIsValid(
      snapshot("queued", { characterId: "other" }),
      CHARACTER_ID,
    )).toBe(false);
    expect(characterVoiceGenerationSnapshotIsValid(
      snapshot("queued", { terminal: true, cancellable: false }),
      CHARACTER_ID,
    )).toBe(false);
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: true,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("ready_applied", { generatedVersionId: null }),
    })).toMatchObject({ phase: "invalid", primaryAction: "reload" });
  });

  it("uses authoritative cancellable and retryable flags without inventing confirmations", () => {
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: true,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("generating_voice", { cancellable: false }),
    })).toMatchObject({ primaryAction: null });
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: true,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("failed_generation", { retryable: true }),
    })).toMatchObject({ primaryAction: "retry", primaryLabel: "一键重试" });
  });

  it("keeps durable recovery actions available while new generation is offline", () => {
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: false,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("generating_voice"),
    })).toMatchObject({ visible: true, primaryAction: "cancel" });
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: false,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("ready_unapplied"),
    })).toMatchObject({ visible: true, primaryAction: "apply" });
    expect(deriveCharacterVoiceGeneratorState({
      capabilityEnabled: false,
      characterId: CHARACTER_ID,
      expectedBindingVersion: 1,
      command: snapshot("failed_generation", { retryable: true }),
    })).toMatchObject({ visible: true, primaryAction: null });
  });
});

describe("character voice generator panel", () => {
  it("is fail-closed when capability is omitted", () => {
    const harness = createHarness();
    const Panel = createCharacterVoiceGenerator(harness.React);
    expect(harness.render(Panel, baseProps({ capabilityEnabled: undefined }))).toBeNull();
  });

  it("shows one primary operation and no preview, rights or naming gate", () => {
    const harness = createHarness();
    const Panel = createCharacterVoiceGenerator(harness.React);
    const props = baseProps();
    const tree = harness.render(Panel, props);
    const buttons = findAll(tree, (element) => element.type === "button");
    expect(buttons).toHaveLength(1);
    expect(textContent(buttons[0])).toBe("为顾临舟生成并使用专属音色");
    expect(textContent(tree)).toContain("原声音会保持到生成和 Nano 验证全部完成");
    expect(findAll(tree, (element) => element.type === "input")).toHaveLength(0);
    expect(textContent(tree)).not.toContain("版权");
    expect(textContent(tree)).not.toContain("试听");
    expect(textContent(tree)).not.toContain("名称");
  });

  it("owns the embedded section heading only while the generator is visible", () => {
    const harness = createHarness();
    const Panel = createCharacterVoiceGenerator(harness.React);
    const tree = harness.render(Panel, baseProps({ presentation: "embedded" }));

    expect(textContent(tree)).toContain("生成专属音色");
    expect(findAll(tree, (element) => (
      element.type === "h3" && textContent(element) === "生成专属音色"
    ))).toHaveLength(1);

    const hiddenHarness = createHarness();
    const HiddenPanel = createCharacterVoiceGenerator(hiddenHarness.React);
    expect(hiddenHarness.render(HiddenPanel, baseProps({
      presentation: "embedded",
      capabilityEnabled: false,
    }))).toBeNull();
  });

  it("restores the latest durable command after a page refresh", async () => {
    const harness = createHarness();
    const Panel = createCharacterVoiceGenerator(harness.React);
    const onCommandChanged = vi.fn();
    const onLoadLatest = vi.fn(async () => snapshot("validating_with_nano", {
      progressPercent: 84,
      cancellable: false,
    }));
    const props = baseProps({ onLoadLatest, onCommandChanged });
    harness.render(Panel, props);
    await Promise.resolve();
    await Promise.resolve();
    const restored = harness.render(Panel, props);
    expect(onLoadLatest).toHaveBeenCalledWith(CHARACTER_ID, expect.any(AbortSignal));
    expect(onCommandChanged).not.toHaveBeenCalled();
    expect(textContent(restored)).toContain("正在验证生成结果");
    expect(textContent(restored)).toContain("84%");
  });

  it("loads an existing durable command even while the host capability is down", async () => {
    const harness = createHarness();
    const Panel = createCharacterVoiceGenerator(harness.React);
    const onLoadLatest = vi.fn(async () => snapshot("ready_unapplied"));
    const props = baseProps({ capabilityEnabled: false, onLoadLatest });
    expect(harness.render(Panel, props)).toBeNull();
    await Promise.resolve();
    await Promise.resolve();
    const restored = harness.render(Panel, props);
    expect(onLoadLatest).toHaveBeenCalled();
    expect(textContent(restored)).toContain("专属音色已生成");
    expect(textContent(button(restored))).toBe("使用此音色");
  });

  it("uses the server-projected binding version for ready_unapplied CAS", async () => {
    const harness = createHarness();
    const Panel = createCharacterVoiceGenerator(harness.React);
    const onUseGeneratedVoice = vi.fn(async () => snapshot("ready_applied"));
    const onCommandChanged = vi.fn();
    const props = baseProps({
      expectedBindingVersion: 7,
      initialCommand: snapshot("ready_unapplied", { currentBindingVersion: 12 }),
      onUseGeneratedVoice,
      onCommandChanged,
    });
    const tree = harness.render(Panel, props);
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(1);
    expect(textContent(button(tree))).toBe("使用此音色");
    (button(tree)?.props.onClick as () => void)();
    await Promise.resolve();
    expect(onUseGeneratedVoice).toHaveBeenCalledWith({
      commandId: COMMAND_ID,
      expectedBindingVersion: 12,
    });
    expect(onCommandChanged).toHaveBeenCalledWith(expect.objectContaining({ state: "ready_applied" }));
  });

  it("exposes cancellation only during the server-authorized window and retry after failure", async () => {
    const cancelHarness = createHarness();
    const CancelPanel = createCharacterVoiceGenerator(cancelHarness.React);
    const cancelProps = baseProps({ initialCommand: snapshot("generating_voice") });
    const cancelTree = cancelHarness.render(CancelPanel, cancelProps);
    expect(textContent(button(cancelTree))).toBe("取消生成");
    (button(cancelTree)?.props.onClick as () => void)();
    await Promise.resolve();
    expect(cancelProps.onCancelGeneration).toHaveBeenCalledWith(COMMAND_ID);

    const retryHarness = createHarness();
    const RetryPanel = createCharacterVoiceGenerator(retryHarness.React);
    const retryProps = baseProps({ initialCommand: snapshot("failed_nano_validation") });
    const retryTree = retryHarness.render(RetryPanel, retryProps);
    expect(textContent(button(retryTree))).toBe("一键重试");
    (button(retryTree)?.props.onClick as () => void)();
    await Promise.resolve();
    expect(retryProps.onRetryGeneration).toHaveBeenCalledWith(COMMAND_ID);
  });

  it("ships scoped responsive and keyboard-visible styles", () => {
    expect(CHARACTER_VOICE_GENERATOR_STYLE_ID).toBe("anw-character-voice-generator-styles");
    expect(CHARACTER_VOICE_GENERATOR_STYLES).toContain(".anw-character-voice-generator");
    expect(CHARACTER_VOICE_GENERATOR_STYLES).toContain(":focus-visible");
    expect(CHARACTER_VOICE_GENERATOR_STYLES).toContain("@media (max-width: 640px)");
  });
});
