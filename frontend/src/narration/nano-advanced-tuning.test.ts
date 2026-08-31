import { describe, expect, it, vi } from "vitest";

import {
  NANO_ADVANCED_TUNING_DEFAULT_DRAFT,
  createNanoAdvancedTuningPanel,
  deriveNanoAdvancedTuningState,
  nanoAdvancedDraftFromParameters,
  nanoDecimalFromMilli,
  nanoMilliFromDecimal,
  validateNanoAdvancedTuningDraft,
  type NanoAdvancedTuningPanelProps,
  type NanoAdvancedTuningReactRuntime,
  type NanoAdvancedTuningTarget,
  type NanoExperimentSnapshot,
} from "./nano-advanced-tuning";
import {
  NANO_ADVANCED_TUNING_STYLE_ID,
  NANO_ADVANCED_TUNING_STYLES,
} from "./styles/nano-advanced-tuning";

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
  const found = findAll(root, (element) => element.type === "button" && textContent(element) === label)[0];
  if (!found) throw new Error(`button not found: ${label}`);
  return found;
}

function findInput(root: unknown, id: string): FakeElement {
  const found = findAll(root, (element) => element.type === "input" && element.props.id === id)[0];
  if (!found) throw new Error(`input not found: ${id}`);
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
  const effects: Array<EffectRecord | undefined> = [];
  let pending: Array<{
    readonly index: number;
    readonly effect: () => void | (() => void);
    readonly dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let effectIndex = 0;
  const React: NanoAdvancedTuningReactRuntime = {
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

const NARRATOR_TARGET: NanoAdvancedTuningTarget = Object.freeze({
  kind: "narrator",
  characterId: null,
  expectedSettingsVersion: 7,
  expectedBindingVersion: null,
});

function experiment(
  state: NanoExperimentSnapshot["state"],
  patch: Partial<NanoExperimentSnapshot> = {},
): NanoExperimentSnapshot {
  return {
    commandId: "40000000-0000-4000-8000-000000000001",
    state,
    reusedVersion: false,
    failureCode: state === "failed" ? "NANO_EXPERIMENT_SYNTHESIS_FAILED" : null,
    retryable: state === "failed",
    ...patch,
  };
}

function baseProps(
  overrides: Partial<NanoAdvancedTuningPanelProps> = {},
): NanoAdvancedTuningPanelProps {
  return {
    capabilityEnabled: true,
    basePresetId: "onnx.Junhao",
    basePresetDisplayName: "Junhao",
    target: NARRATOR_TARGET,
    onCreateExperiment: vi.fn(),
    onApplyExperiment: vi.fn(),
    onRestoreOfficialVoice: vi.fn(),
    ...overrides,
  };
}

describe("Nano advanced tuning state", () => {
  it("converts decimal fields to exact integer thousandths", () => {
    expect(nanoMilliFromDecimal("0.001")).toBe(1);
    expect(nanoMilliFromDecimal("0.95")).toBe(950);
    expect(nanoMilliFromDecimal("2.0")).toBe(2_000);
    expect(nanoMilliFromDecimal("0.0001")).toBeNull();
    expect(nanoMilliFromDecimal("1e-3")).toBeNull();
    expect(nanoDecimalFromMilli(1)).toBe("0.001");
    expect(nanoDecimalFromMilli(1_200)).toBe("1.2");
  });

  it("validates all real defaults and keeps int64 seed lossless as a decimal string", () => {
    const defaults = validateNanoAdvancedTuningDraft(NANO_ADVANCED_TUNING_DEFAULT_DRAFT);
    expect(defaults).toMatchObject({
      valid: true,
      parameters: {
        seed: "1234",
        textTemperatureMilli: 1_000,
        textTopPMilli: 1_000,
        textTopK: 50,
        audioTemperatureMilli: 800,
        audioTopPMilli: 950,
        audioTopK: 25,
        audioRepetitionPenaltyMilli: 1_200,
        sampleMode: "full",
        maxNewFrames: 375,
      },
    });
    const boundary = validateNanoAdvancedTuningDraft({
      seed: "9223372036854775807",
      textTemperature: "0.1",
      textTopP: "0.001",
      textTopK: "1",
      audioTemperature: "2.0",
      audioTopP: "1.0",
      audioTopK: "100",
      audioRepetitionPenalty: "2.0",
    });
    expect(boundary.valid).toBe(true);
    expect(boundary.parameters?.seed).toBe("9223372036854775807");
    expect(nanoAdvancedDraftFromParameters(boundary.parameters!)).toEqual({
      seed: "9223372036854775807",
      textTemperature: "0.1",
      textTopP: "0.001",
      textTopK: "1",
      audioTemperature: "2.0",
      audioTopP: "1.0",
      audioTopK: "100",
      audioRepetitionPenalty: "2.0",
    });
  });

  it("rejects unsafe seed, out-of-range values and non-integer top-k", () => {
    const invalid = validateNanoAdvancedTuningDraft({
      ...NANO_ADVANCED_TUNING_DEFAULT_DRAFT,
      seed: "9223372036854775808",
      textTopP: "0",
      audioTopK: "25.5",
    });
    expect(invalid.valid).toBe(false);
    expect(invalid.parameters).toBeNull();
    expect(invalid.fieldErrors).toMatchObject({
      seed: expect.any(String),
      textTopP: expect.any(String),
      audioTopK: expect.any(String),
    });
  });

  it("fails closed on invalid target CAS and preserves CAS drift as ready_unapplied", () => {
    expect(deriveNanoAdvancedTuningState({
      capabilityEnabled: true,
      basePresetId: "onnx.Junhao",
      target: { ...NARRATOR_TARGET, characterId: "unexpected" },
      draft: NANO_ADVANCED_TUNING_DEFAULT_DRAFT,
    })).toMatchObject({ phase: "invalid", canCreate: false, canRestoreOfficial: false });
    expect(deriveNanoAdvancedTuningState({
      capabilityEnabled: true,
      basePresetId: "onnx.Junhao",
      target: NARRATOR_TARGET,
      draft: NANO_ADVANCED_TUNING_DEFAULT_DRAFT,
      experiment: experiment("ready_unapplied"),
    })).toMatchObject({
      phase: "ready_unapplied",
      canCreate: true,
      canApply: true,
      tone: "warning",
    });
  });
});

describe("Nano advanced tuning panel", () => {
  it("renders nothing when capability is not explicitly enabled", () => {
    const harness = createHarness();
    const Panel = createNanoAdvancedTuningPanel(harness.React);
    expect(harness.render(Panel, baseProps({ capabilityEnabled: undefined }))).toBeNull();
  });

  it("renders exactly the eight real controls, fixed full/375 identity, and no templates", () => {
    const harness = createHarness();
    const Panel = createNanoAdvancedTuningPanel(harness.React);
    const tree = harness.render(Panel, baseProps());
    expect(findAll(tree, (element) => element.type === "input")).toHaveLength(8);
    expect(textContent(tree)).toContain("full · 375 帧");
    expect(textContent(tree)).toContain("模型真实采样参数");
    expect(textContent(tree)).not.toContain("自然模板");
    expect(textContent(tree)).not.toContain("试听确认");
  });

  it("submits one exact command and resets only to frozen defaults", () => {
    const harness = createHarness();
    const Panel = createNanoAdvancedTuningPanel(harness.React);
    const props = baseProps();
    let tree = harness.render(Panel, props);
    (findInput(tree, "anw-nano-tuning-seed").props.onChange as (event: ValueChangeEvent) => void)({
      target: { value: "9223372036854775807" },
    });
    tree = harness.render(Panel, props);
    (findInput(tree, "anw-nano-tuning-textTemperature").props.onChange as (event: ValueChangeEvent) => void)({
      target: { value: "1.125" },
    });
    tree = harness.render(Panel, props);
    (findButton(tree, "创建并使用").props.onClick as () => void)();
    expect(props.onCreateExperiment).toHaveBeenCalledWith(expect.objectContaining({
      basePresetId: "onnx.Junhao",
      kind: "narrator",
      characterId: null,
      expectedSettingsVersion: 7,
      expectedBindingVersion: null,
      parameters: expect.objectContaining({
        seed: "9223372036854775807",
        textTemperatureMilli: 1_125,
        sampleMode: "full",
        maxNewFrames: 375,
      }),
    }));

    (findButton(tree, "重置参数").props.onClick as () => void)();
    tree = harness.render(Panel, props);
    expect(findInput(tree, "anw-nano-tuning-seed").props.value).toBe("1234");
    expect(findInput(tree, "anw-nano-tuning-textTemperature").props.value).toBe("1.0");
  });

  it("keeps invalid input local and never dispatches a malformed request", () => {
    const harness = createHarness();
    const Panel = createNanoAdvancedTuningPanel(harness.React);
    const props = baseProps();
    let tree = harness.render(Panel, props);
    (findInput(tree, "anw-nano-tuning-audioTopP").props.onChange as (event: ValueChangeEvent) => void)({
      target: { value: "0.0001" },
    });
    tree = harness.render(Panel, props);
    expect(findInput(tree, "anw-nano-tuning-audioTopP").props["aria-invalid"]).toBe(true);
    expect(findButton(tree, "创建并使用").props.disabled).toBe(true);
    (findButton(tree, "创建并使用").props.onClick as () => void)();
    expect(props.onCreateExperiment).not.toHaveBeenCalled();
  });

  it("presents automatic apply success and CAS drift without extra confirmation", () => {
    const harness = createHarness();
    const Panel = createNanoAdvancedTuningPanel(harness.React);
    let tree = harness.render(Panel, baseProps({ experiment: experiment("ready_applied") }));
    expect(textContent(tree)).toContain("自动使用");
    expect(findAll(tree, (element) => textContent(element) === "使用此音色")).toHaveLength(0);

    const characterTarget: NanoAdvancedTuningTarget = {
      kind: "character",
      characterId: "50000000-0000-4000-8000-000000000001",
      expectedSettingsVersion: 9,
      expectedBindingVersion: 12,
    };
    const props = baseProps({
      target: characterTarget,
      experiment: experiment("ready_unapplied"),
    });
    tree = harness.render(Panel, props);
    expect(textContent(tree)).toContain("没有覆盖新选择");
    (findButton(tree, "使用此音色").props.onClick as () => void)();
    expect(props.onApplyExperiment).toHaveBeenCalledWith({
      commandId: "40000000-0000-4000-8000-000000000001",
      ...characterTarget,
    });
  });

  it("restores the official fixed voice in one click through the existing selection adapter", () => {
    const harness = createHarness();
    const Panel = createNanoAdvancedTuningPanel(harness.React);
    const props = baseProps();
    const tree = harness.render(Panel, props);
    (findButton(tree, "恢复官方音色").props.onClick as () => void)();
    expect(props.onRestoreOfficialVoice).toHaveBeenCalledWith({
      basePresetId: "onnx.Junhao",
      ...NARRATOR_TARGET,
    });
  });
});

describe("Nano advanced tuning styles", () => {
  it("provides touch-safe desktop/narrow/forced-color layouts", () => {
    expect(NANO_ADVANCED_TUNING_STYLE_ID).toBe("anw-nano-advanced-tuning-styles");
    expect(NANO_ADVANCED_TUNING_STYLES).toContain("min-height: 44px");
    expect(NANO_ADVANCED_TUNING_STYLES).toContain("@media (max-width: 720px)");
    expect(NANO_ADVANCED_TUNING_STYLES).toContain("@media (max-width: 390px)");
    expect(NANO_ADVANCED_TUNING_STYLES).toContain("@media (forced-colors: active)");
    expect(NANO_ADVANCED_TUNING_STYLES).not.toContain("min-width: 390px");
  });
});

interface ValueChangeEvent {
  readonly target: { readonly value: string };
}
