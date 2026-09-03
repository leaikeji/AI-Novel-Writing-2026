import { describe, expect, it, vi } from "vitest";

import {
  GENERIC_VOICE_GENERATION_COMMAND_CONTRACT_VERSION,
  GENERIC_VOICE_PACK_CONTRACT_VERSION,
  GENERIC_VOICE_PACK_SLOT_COUNT,
  createGenericVoicePack,
  genericVoiceGenerationCommandIsValid,
  genericVoicePackSnapshotIsValid,
  genericVoicePackSlotDisplayLabel,
  genericVoicePackStatusLabel,
  type GenericVoiceGenerationCommandSnapshot,
  type GenericVoicePackLoadResult,
  type GenericVoicePackProps,
  type GenericVoicePackReactRuntime,
  type GenericVoicePackSlotSnapshot,
  type GenericVoicePackSnapshot,
} from "./generic-voice-pack";
import { VOICE_PREPARATION_STYLES } from "./styles/voice-preparation";

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
  const React: GenericVoicePackReactRuntime = {
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

const PACK_ID = "11111111-1111-4111-8111-111111111111";
const COMMAND_ID = "21111111-1111-4111-8111-111111111111";
const NOW = "2026-09-03T08:00:00Z";

const CATEGORIES = ["child", "youth", "middle_age", "older", "neutral_group"] as const;

function slot(index: number, state: GenericVoicePackSlotSnapshot["state"] = "validated"):
GenericVoicePackSlotSnapshot {
  const available = state === "validated" || state === "reused";
  const slotId = `50000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
  const assetId = `60000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
  return {
    slotId,
    slotKey: `slot_${String(index).padStart(2, "0")}`,
    label: `通用音色 ${index + 1}`,
    category: CATEGORIES[index % CATEGORIES.length],
    state,
    previewAvailable: available,
    previewAsset: available ? {
      asset_id: assetId,
      content_path: `/media-assets/${assetId}/content`,
      mime_type: "audio/wav",
      byte_size: 4,
      duration_ms: 900,
      checksum_sha256: "a".repeat(64),
    } : null,
    voiceProfileId: available ? PACK_ID : null,
    voiceVersionId: available ? COMMAND_ID : null,
    failureCode: state === "failed" ? "GENERIC_VOICE_PACK_GENERATION_FAILED" : null,
  };
}

function missingPack(): GenericVoicePackSnapshot {
  return {
    contractVersion: GENERIC_VOICE_PACK_CONTRACT_VERSION,
    language: "zh-CN",
    packVersionId: null,
    state: "missing",
    preparedSlots: 0,
    totalSlots: GENERIC_VOICE_PACK_SLOT_COUNT,
    slots: [],
    failureCode: null,
    updatedAt: NOW,
  };
}

function pack(
  changes: Partial<GenericVoicePackSnapshot> = {},
): GenericVoicePackSnapshot {
  const slots = [slot(0), slot(1, "generating"), slot(2, "pending")];
  return {
    contractVersion: GENERIC_VOICE_PACK_CONTRACT_VERSION,
    language: "zh-CN",
    packVersionId: PACK_ID,
    state: "building",
    preparedSlots: 1,
    totalSlots: GENERIC_VOICE_PACK_SLOT_COUNT,
    slots,
    failureCode: null,
    updatedAt: NOW,
    ...changes,
  };
}

function command(
  changes: Partial<GenericVoiceGenerationCommandSnapshot> = {},
): GenericVoiceGenerationCommandSnapshot {
  return {
    contractVersion: GENERIC_VOICE_GENERATION_COMMAND_CONTRACT_VERSION,
    commandId: COMMAND_ID,
    packVersionId: PACK_ID,
    state: "building",
    progressCurrent: 1,
    progressTotal: GENERIC_VOICE_PACK_SLOT_COUNT,
    currentSlotKey: "slot_01",
    cancellable: true,
    retryable: false,
    terminal: false,
    failureCode: null,
    updatedAt: NOW,
    ...changes,
  };
}

function result(
  currentPack: GenericVoicePackSnapshot = pack(),
  currentCommand: GenericVoiceGenerationCommandSnapshot | null = command(),
): GenericVoicePackLoadResult {
  return { pack: currentPack, command: currentCommand };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function baseProps(changes: Partial<GenericVoicePackProps> = {}): GenericVoicePackProps {
  return {
    capabilityEnabled: true,
    canConfigure: true,
    initialPack: missingPack(),
    initialCommand: null,
    refreshIntervalMs: 0,
    onRefreshCommand: vi.fn(async () => result()),
    onBuild: vi.fn(async () => result()),
    onRetry: vi.fn(async () => result()),
    onCancel: vi.fn(async () => result(pack(), command({
      state: "cancelled",
      cancellable: false,
      terminal: true,
    }))),
    onRegenerateSlot: vi.fn(async () => result()),
    onRejectSlot: vi.fn(async () => result()),
    onPreviewSlot: vi.fn(),
    ...changes,
  };
}

describe("generic voice pack projections", () => {
  it("labels group-dialogue fallbacks as one voice instead of a chorus", () => {
    expect(genericVoicePackSlotDisplayLabel({
      slotKey: "crowd_male",
      label: "群体·男性",
    })).toBe("未具名男性对白（单声线）");
    expect(genericVoicePackSlotDisplayLabel({
      slotKey: "male_young_warm",
      label: "青年男性·温和",
    })).toBe("青年男性·温和");
  });

  it("validates missing, partial and complete pack invariants", () => {
    expect(genericVoicePackSnapshotIsValid(missingPack())).toBe(true);
    expect(genericVoicePackSnapshotIsValid(pack())).toBe(true);
    expect(genericVoicePackSnapshotIsValid(pack({ preparedSlots: 2 }))).toBe(false);
    const completeSlots = Array.from({ length: GENERIC_VOICE_PACK_SLOT_COUNT }, (_, index) => slot(index));
    expect(genericVoicePackSnapshotIsValid(pack({
      state: "active",
      preparedSlots: GENERIC_VOICE_PACK_SLOT_COUNT,
      slots: completeSlots,
    }))).toBe(true);
    expect(genericVoicePackSnapshotIsValid(pack({ state: "active" }))).toBe(false);
  });

  it("rejects contradictory generation command states", () => {
    expect(genericVoiceGenerationCommandIsValid(command())).toBe(true);
    expect(genericVoiceGenerationCommandIsValid(command({ terminal: true }))).toBe(false);
    expect(genericVoiceGenerationCommandIsValid(command({
      state: "failed",
      terminal: true,
      cancellable: false,
      retryable: true,
      failureCode: "GENERIC_VOICE_PACK_GENERATION_FAILED",
    }))).toBe(true);
  });

  it("uses product language instead of model terminology", () => {
    expect(genericVoicePackStatusLabel(missingPack())).toBe("尚未开始准备");
    expect(genericVoicePackStatusLabel(pack())).toBe("正在后台准备");
    expect(genericVoicePackStatusLabel(pack({ state: "retired_for_new_use" })))
      .toBe("已停止用于新的朗读");
  });
});

describe("generic voice pack component", () => {
  it("is a default-collapsed native keyboard disclosure", () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const tree = harness.render(Component, baseProps());
    expect((tree as FakeElement).type).toBe("details");
    expect((tree as FakeElement).props.open).toBeUndefined();
    const summary = findAll(tree, (element) => element.type === "summary")[0];
    expect(textContent(summary)).toContain("中文通用角色音色");
    expect(textContent(summary)).toContain("已准备 0/24");
    expect(findButton(tree, "开始准备").props.type).toBe("button");
    expect(VOICE_PREPARATION_STYLES).toContain(".anw-generic-voice-pack summary:focus-visible");
  });

  it("fails closed when capability and durable state are both absent", () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    expect(harness.render(Component, baseProps({
      capabilityEnabled: undefined,
      initialPack: null,
    }))).toBeNull();
  });

  it("shows loading and restores pack progress after a page refresh", async () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const pending = deferred<GenericVoicePackLoadResult>();
    const onLoadLatest = vi.fn(() => pending.promise);
    const props = baseProps({ initialPack: null, onLoadLatest });
    const loading = harness.render(Component, props);
    expect(textContent(loading)).toContain("正在恢复最新进度");
    pending.resolve(result());
    await Promise.resolve();
    await Promise.resolve();
    const restored = harness.render(Component, props);
    expect(onLoadLatest).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(textContent(restored)).toContain("已准备 1/24");
    expect(textContent(restored)).toContain("正在后台准备");
  });

  it("keeps load failure recoverable and visible", async () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const props = baseProps({
      initialPack: null,
      onLoadLatest: vi.fn(async () => { throw new Error("无法读取音色包"); }),
    });
    harness.render(Component, props);
    await Promise.resolve();
    await Promise.resolve();
    const failed = harness.render(Component, props);
    expect(textContent(failed)).toContain("无法读取音色包");
    expect(findButton(failed, "重新加载").props.type).toBe("button");
  });

  it("offers retry for a server-authorized failure", async () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const failedPack = pack({
      state: "failed",
      slots: [slot(0, "failed")],
      preparedSlots: 0,
      failureCode: "GENERIC_VOICE_PACK_GENERATION_FAILED",
    });
    const failedCommand = command({
      state: "failed",
      progressCurrent: 0,
      terminal: true,
      cancellable: false,
      retryable: true,
      failureCode: "GENERIC_VOICE_PACK_GENERATION_FAILED",
    });
    const onRetry = vi.fn(async () => result());
    const tree = harness.render(Component, baseProps({
      initialPack: failedPack,
      initialCommand: failedCommand,
      onRetry,
    }));
    (findButton(tree, "重试").props.onClick as () => void)();
    await Promise.resolve();
    expect(onRetry).toHaveBeenCalledWith(COMMAND_ID);
  });

  it("blocks repeated build clicks before rerender", async () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const pending = deferred<GenericVoicePackLoadResult>();
    const onBuild = vi.fn(() => pending.promise);
    const tree = harness.render(Component, baseProps({ onBuild }));
    const build = findButton(tree, "开始准备");
    (build.props.onClick as () => void)();
    (build.props.onClick as () => void)();
    expect(onBuild).toHaveBeenCalledTimes(1);
    pending.resolve(result());
    await Promise.resolve();
    await Promise.resolve();
  });

  it("groups slots and blocks repeated destructive slot clicks", async () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const pending = deferred<GenericVoicePackLoadResult>();
    const onRejectSlot = vi.fn(() => pending.promise);
    const tree = harness.render(Component, baseProps({
      initialPack: pack(),
      initialCommand: null,
      onRejectSlot,
    }));
    expect(textContent(tree)).toContain("小孩");
    expect(textContent(tree)).toContain("青年");
    const reject = findButton(tree, "拒绝此候选");
    (reject.props.onClick as () => void)();
    (reject.props.onClick as () => void)();
    expect(onRejectSlot).toHaveBeenCalledTimes(1);
    expect(onRejectSlot).toHaveBeenCalledWith("slot_00", PACK_ID);
    pending.resolve(result());
    await Promise.resolve();
    await Promise.resolve();
  });

  it("passes the validated slot scope and asset to the preview action", async () => {
    const harness = createHarness();
    const Component = createGenericVoicePack(harness.React);
    const onPreviewSlot = vi.fn(async () => undefined);
    const tree = harness.render(Component, baseProps({
      initialPack: pack(),
      initialCommand: null,
      onPreviewSlot,
    }));

    (findButton(tree, "试听").props.onClick as () => void)();
    await Promise.resolve();

    const expected = slot(0);
    expect(onPreviewSlot).toHaveBeenCalledWith(expected.slotId, expected.previewAsset);
  });
});
