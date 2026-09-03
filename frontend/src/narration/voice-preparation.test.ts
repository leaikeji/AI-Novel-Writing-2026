import { describe, expect, it, vi } from "vitest";

import {
  VOICE_PREPARATION_CONTRACT_VERSION,
  createVoicePreparation,
  deriveVoicePreparationState,
  voicePreparationSnapshotIsValid,
  type VoicePreparationProps,
  type VoicePreparationReactRuntime,
  type VoicePreparationSnapshot,
} from "./voice-preparation";
import {
  VOICE_PREPARATION_STYLE_ID,
  VOICE_PREPARATION_STYLES,
} from "./styles/voice-preparation";

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

function findButton(root: unknown, label: string): FakeElement {
  const found = findAll(root, (element) => (
    element.type === "button" && textContent(element) === label
  ))[0];
  if (!found) throw new Error(`button not found: ${label}`);
  return found;
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
  let pending: Array<{
    readonly index: number;
    readonly effect: () => void | (() => void);
    readonly dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const React: VoicePreparationReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
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
    render<Props>(Component: (props: Props) => unknown, props: Props): unknown {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pending = [];
      const tree = Component(props);
      const current = pending;
      pending = [];
      for (const item of current) {
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

const COMMAND_ID = "11111111-1111-4111-8111-111111111111";
const NOW = "2026-09-03T08:00:00Z";

function snapshot(
  changes: Partial<VoicePreparationSnapshot> = {},
): VoicePreparationSnapshot {
  return {
    contractVersion: VOICE_PREPARATION_CONTRACT_VERSION,
    commandId: COMMAND_ID,
    state: "preparing",
    serverNow: NOW,
    progressCurrent: 2,
    progressTotal: 6,
    preflightRequestId: "21111111-1111-4111-8111-111111111111",
    preflightScriptVersionId: "31111111-1111-4111-8111-111111111111",
    chapterReady: false,
    backgroundRemaining: 4,
    continuationState: "pending",
    narrationRequestId: null,
    currentTarget: {
      characterId: "41111111-1111-4111-8111-111111111111",
      characterName: "许棠",
      state: "generating",
    },
    preserved: [],
    generated: [],
    fallback: [],
    failed: [],
    cancellable: true,
    retryable: false,
    terminal: false,
    failureCode: null,
    updatedAt: NOW,
    ...changes,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function baseProps(changes: Partial<VoicePreparationProps> = {}): VoicePreparationProps {
  return {
    capabilityEnabled: true,
    canConfigure: true,
    initialCommand: null,
    refreshIntervalMs: 0,
    onStart: vi.fn(async () => snapshot()),
    onRefresh: vi.fn(async () => snapshot()),
    onRetry: vi.fn(async () => snapshot()),
    onCancel: vi.fn(async () => snapshot({
      state: "cancelled",
      cancellable: false,
      terminal: true,
      progressCurrent: 2,
    })),
    ...changes,
  };
}

describe("voice preparation state", () => {
  it("validates authoritative progress and terminal invariants", () => {
    expect(voicePreparationSnapshotIsValid(snapshot())).toBe(true);
    expect(voicePreparationSnapshotIsValid(snapshot({ progressCurrent: 7 }))).toBe(false);
    expect(voicePreparationSnapshotIsValid(snapshot({ terminal: true }))).toBe(false);
    expect(voicePreparationSnapshotIsValid(snapshot({
      state: "ready",
      progressCurrent: 6,
      cancellable: false,
      terminal: true,
    }))).toBe(true);
  });

  it("keeps chapter readiness independent from remaining background work", () => {
    expect(deriveVoicePreparationState({
      capabilityEnabled: true,
      command: snapshot({ chapterReady: true, backgroundRemaining: 3 }),
    })).toMatchObject({
      statusLabel: "本章声音已就绪",
      detail: "另有 3 个人物在后台准备。",
      phase: "preparing",
    });
  });

  it("summarizes generated and fallback voices without technical noise", () => {
    const ready = snapshot({
      state: "ready_with_warnings",
      progressCurrent: 6,
      terminal: true,
      cancellable: false,
      chapterReady: true,
      generated: [
        { characterId: "a", characterName: "许棠", state: "ready_applied" },
        { characterId: "b", characterName: "沈砚", state: "ready_applied" },
      ],
      fallback: [{ characterId: "c", characterName: "罗岑", state: "fallback_official" }],
    });
    expect(deriveVoicePreparationState({ capabilityEnabled: true, command: ready })).toMatchObject({
      tone: "warning",
      detail: "2 个专属音色、1 个官方兜底",
    });
  });
});

describe("voice preparation component", () => {
  it("fails closed when the capability is omitted", () => {
    const harness = createHarness();
    const Component = createVoicePreparation(harness.React);
    expect(harness.render(Component, baseProps({ capabilityEnabled: undefined }))).toBeNull();
  });

  it("uses native keyboard controls and scoped focus-visible styles", () => {
    const harness = createHarness();
    const Component = createVoicePreparation(harness.React);
    const tree = harness.render(Component, baseProps());
    const action = findButton(tree, "准备专属音色");
    expect(action.props.type).toBe("button");
    expect(findAll(tree, (element) => element.type === "input")).toHaveLength(0);
    expect(VOICE_PREPARATION_STYLE_ID).toBe("anw-voice-preparation-styles");
    expect(VOICE_PREPARATION_STYLES).toContain(":focus-visible");
  });

  it("shows loading and restores the durable command after a page refresh", async () => {
    const harness = createHarness();
    const Component = createVoicePreparation(harness.React);
    const pending = deferred<VoicePreparationSnapshot | null>();
    const onLoadLatest = vi.fn(() => pending.promise);
    const onCommandChanged = vi.fn();
    const props = baseProps({ onLoadLatest, onCommandChanged });
    const loading = harness.render(Component, props);
    expect(textContent(loading)).toContain("正在恢复人物声音准备进度");
    pending.resolve(snapshot());
    await Promise.resolve();
    await Promise.resolve();
    const restored = harness.render(Component, props);
    expect(onLoadLatest).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(onCommandChanged).not.toHaveBeenCalled();
    expect(textContent(restored)).toContain("正在准备人物声音 2/6");
    expect(textContent(restored)).toContain("当前：许棠");
  });

  it("renders a recoverable load failure without losing the original command", async () => {
    const harness = createHarness();
    const Component = createVoicePreparation(harness.React);
    const props = baseProps({
      initialCommand: snapshot(),
      onLoadLatest: vi.fn(async () => { throw new Error("网络暂时不可用"); }),
    });
    harness.render(Component, props);
    await Promise.resolve();
    await Promise.resolve();
    const failed = harness.render(Component, props);
    expect(textContent(failed)).toContain("网络暂时不可用");
    expect(textContent(failed)).toContain("已完成的声音不会丢失");
    expect(findButton(failed, "重新加载").props.type).toBe("button");
  });

  it("blocks repeated clicks before the host can rerender", async () => {
    const harness = createHarness();
    const Component = createVoicePreparation(harness.React);
    const pending = deferred<VoicePreparationSnapshot>();
    const onStart = vi.fn(() => pending.promise);
    const onCommandChanged = vi.fn();
    const props = baseProps({ onStart, onCommandChanged });
    const tree = harness.render(Component, props);
    const action = findButton(tree, "准备专属音色");
    (action.props.onClick as () => void)();
    (action.props.onClick as () => void)();
    expect(onStart).toHaveBeenCalledTimes(1);
    pending.resolve(snapshot());
    await Promise.resolve();
    await Promise.resolve();
    expect(onCommandChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps technical identifiers folded outside the player-inline presentation", () => {
    const harness = createHarness();
    const Component = createVoicePreparation(harness.React);
    const card = harness.render(Component, baseProps({ initialCommand: snapshot() }));
    expect(findAll(card, (element) => element.type === "details")).toHaveLength(1);
    expect(textContent(card)).toContain("任务详情");

    const inlineHarness = createHarness();
    const Inline = createVoicePreparation(inlineHarness.React);
    const inline = inlineHarness.render(Inline, baseProps({
      presentation: "player-inline",
      initialCommand: snapshot(),
    }));
    expect(findAll(inline, (element) => element.type === "details")).toHaveLength(0);
    expect(textContent(inline)).not.toContain(COMMAND_ID);
  });
});
