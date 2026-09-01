import { describe, expect, it, vi } from "vitest";

import {
  createCharacterVoiceConfigurator,
  type CharacterVoiceConfiguratorProps,
  type CharacterVoiceConfiguratorReactRuntime,
} from "./character-voice-configurator";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function isElement(value: unknown): value is FakeElement {
  return value !== null && typeof value === "object" && "type" in value && "props" in value;
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function findAll(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(root, (element) => (
    element.type === "button" && textContent(element) === label
  ))[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}


function createHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  const React: CharacterVoiceConfiguratorReactRuntime = {
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
    useEffect(): void {},
  };
  return {
    React,
    render(Component: (props: CharacterVoiceConfiguratorProps) => unknown, props: CharacterVoiceConfiguratorProps): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      return Component(props) as FakeElement;
    },
  };
}


function props(changes: Partial<CharacterVoiceConfiguratorProps> = {}): CharacterVoiceConfiguratorProps {
  return {
    scopeId: "novel:character:1",
    characterId: "character-1",
    characterName: "许棠",
    currentVoice: {
      phase: "resolved",
      name: "CN 机车",
      sourceLabel: "官方音色",
      languageLabel: "中文",
    },
    canConfigure: true,
    matchEnabled: true,
    onMatchOfficialVoice: vi.fn(async () => ({
      voiceName: "CN 机车",
      presetId: "onnx.Yuewen",
      selectionStillCurrent: true,
    })),
    generatorContent: {
      type: "section",
      props: {},
      children: ["生成专属音色", "GENERATOR"],
    },
    officialVoiceContent: "OFFICIAL_LIBRARY",
    advancedContent: "ADVANCED_PRIVATE",
    ...changes,
  };
}


describe("CharacterVoiceConfigurator", () => {
  it("keeps the same five-level hierarchy for card and drawer consumers", () => {
    const harness = createHarness();
    const Configurator = createCharacterVoiceConfigurator(harness.React);
    const tree = harness.render(Configurator, props());
    const copy = textContent(tree);

    const order = [
      copy.indexOf("当前声音"),
      copy.indexOf("智能匹配官方音色"),
      copy.indexOf("生成专属音色"),
      copy.indexOf("浏览全部官方音色"),
      copy.indexOf("私人音色与高级调音"),
    ];
    expect(order.every((value) => value >= 0)).toBe(true);
    expect([...order].sort((left, right) => left - right)).toEqual(order);
    expect(copy).toContain("CN 机车 · 官方音色 · 中文");
    expect(findAll(tree, (element) => element.type === "details")).toHaveLength(2);
  });

  it("owns one cancellable smart-match action and does not require a preview confirmation", async () => {
    const onMatchOfficialVoice = vi.fn(async (signal: AbortSignal) => {
      expect(signal).toBeInstanceOf(AbortSignal);
      return {
        voiceName: "CN 说书",
        presetId: "onnx.Weiguo",
        selectionStillCurrent: true,
      };
    });
    const harness = createHarness();
    const Configurator = createCharacterVoiceConfigurator(harness.React);
    const tree = harness.render(Configurator, props({ onMatchOfficialVoice }));

    (findButton(tree, "立即智能匹配").props.onClick as () => void)();
    await Promise.resolve();
    await Promise.resolve();

    expect(onMatchOfficialVoice).toHaveBeenCalledTimes(1);
    expect(textContent(tree)).not.toContain("确认试听");
  });

  it("fails closed when matching is unavailable while leaving manual browsing visible", () => {
    const harness = createHarness();
    const Configurator = createCharacterVoiceConfigurator(harness.React);
    const tree = harness.render(Configurator, props({
      matchEnabled: false,
      matchDisabledReason: "人物卡尚未保存。",
    }));

    expect(findButton(tree, "立即智能匹配").props.disabled).toBe(true);
    expect(textContent(tree)).toContain("人物卡尚未保存。");
    expect(textContent(tree)).toContain("浏览全部官方音色");
  });

  it("does not create an empty dedicated-voice section when the generator is hidden", () => {
    const harness = createHarness();
    const Configurator = createCharacterVoiceConfigurator(harness.React);
    const tree = harness.render(Configurator, props({ generatorContent: null }));

    expect(textContent(tree)).not.toContain("生成专属音色");
    expect(findAll(tree, (element) => (
      element.props["aria-labelledby"] === "anw-character-voice-novel-character-1-generator"
    ))).toHaveLength(0);
  });
});
