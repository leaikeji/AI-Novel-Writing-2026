import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "./api";
import type { QwenPawReactRuntime } from "./assistant-pane";
import type {
  AssistantSelectionController,
  AssistantSelectionToolbarState,
} from "./assistant-selection-controller";
import { createAssistantSelectionToolbar } from "./assistant-selection-toolbar";

vi.mock("./api", () => ({ apiRequest: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});


interface ToolbarTestNode {
  props: Record<string, unknown>;
  children: unknown[];
}


function findButton(node: unknown, label: string): ToolbarTestNode | undefined {
  if (!node || typeof node !== "object" || !("children" in node)) return;
  const element = node as ToolbarTestNode;
  if (element.children.includes(label) && typeof element.props.onClick === "function") return element;
  for (const child of element.children) {
    const result = findButton(child, label);
    if (result) return result;
  }
}


function createMeasurementHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<{ dependencies: readonly unknown[]; cleanup?: () => void }> = [];
  let pending: Array<() => void> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const React: QwenPawReactRuntime = {
    createElement: (type, props, ...children) => ({ type, props, children }),
    useState<T>(initial: T | (() => T)) {
      const index = stateIndex++;
      if (index >= states.length) states.push(typeof initial === "function" ? (initial as () => T)() : initial);
      return [states[index] as T, (next) => {
        states[index] = typeof next === "function"
          ? (next as (current: T) => T)(states[index] as T) : next;
      }];
    },
    useRef<T>(initial: T) {
      const index = refIndex++;
      if (index >= refs.length) refs.push({ current: initial });
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies) {
      const index = effectIndex++;
      const previous = effects[index];
      if (previous && dependencies.length === previous.dependencies.length
        && dependencies.every((value, offset) => Object.is(value, previous.dependencies[offset]))) return;
      pending.push(() => {
        previous?.cleanup?.();
        const cleanup = effect();
        effects[index] = { dependencies, cleanup: typeof cleanup === "function" ? cleanup : undefined };
      });
    },
  };
  let state: AssistantSelectionToolbarState = {
    phase: "ready", visible: true, selectionId: "selection-a",
    fieldId: "chapter.body", fieldLabel: "章节正文", selectedCharacters: 5,
    placement: {
      x: 700, y: 540, placement: "selection-below", strategy: "selection-mirror",
      precision: "verified-selection", fallbackReasons: [],
    },
  };
  let listener: ((next: AssistantSelectionToolbarState) => void) | undefined;
  const setToolbarSize = vi.fn();
  const unsubscribe = vi.fn(() => { listener = undefined; });
  const controller = {
    getState: () => state,
    subscribe: vi.fn((next) => { listener = next; return unsubscribe; }),
    setToolbarSize,
    getActiveSelectionRecord: () => ({ text: "检修签到表", novelId: "novel-a" }),
  } as unknown as AssistantSelectionController;
  const size = { width: 620, height: 80 };
  const element = { getBoundingClientRect: () => ({ ...size }) } as HTMLElement;
  const Toolbar = createAssistantSelectionToolbar(React, controller);
  return {
    size, element, setToolbarSize, unsubscribe,
    updateState(next: Partial<AssistantSelectionToolbarState>) {
      state = { ...state, ...next };
      listener?.(state);
    },
    render() {
      stateIndex = refIndex = effectIndex = 0;
      pending = [];
      const node = Toolbar() as ToolbarTestNode | null;
      if (node) (node.props.ref as { current: HTMLElement | null }).current = element;
      else refs[0].current = null;
      for (const effect of pending) effect();
      return node;
    },
    unmount() {
      for (const effect of effects) effect?.cleanup?.();
    },
  };
}


function enableCaptureHost() {
  vi.stubGlobal("window", { QwenPaw: { host: { antd: {
    Alert: "alert", Button: "button", Card: "card",
    Input: Object.assign("input", { TextArea: "textarea" }), Select: "select",
  } } } });
}


function installResizeObserver() {
  const observers: Array<{ notify: () => void; observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = [];
  vi.stubGlobal("ResizeObserver", class {
    observe = vi.fn();
    disconnect = vi.fn();
    constructor(readonly notify: () => void) { observers.push(this); }
  });
  return observers;
}


function findText(node: unknown, value: string): boolean {
  if (node === value) return true;
  if (!node || typeof node !== "object") return false;
  const candidate = node as { children?: unknown[] };
  return (candidate.children ?? []).some((child) => findText(child, value));
}


describe("assistant selection toolbar portal", () => {
  it("portals the toolbar above host modal stacking contexts when a public target is available", () => {
    const React: QwenPawReactRuntime = {
      createElement: (type, props, ...children) => ({ type, props, children }),
      useState: (initial) => [
        typeof initial === "function" ? (initial as () => unknown)() : initial,
        () => undefined,
      ] as never,
      useRef: (initial) => ({ current: initial }),
      useEffect: (effect) => { effect(); },
    };
    const controller = {
      getState: () => ({
        phase: "ready",
        visible: true,
        selectionId: "00000000-0000-4000-8000-000000000001",
        fieldId: "chapter.title",
        fieldLabel: "章节标题",
        selectedCharacters: 6,
        placement: {
          x: 320,
          y: 240,
          placement: "below",
          strategy: "field-anchor",
          precision: "field-level",
        },
      }),
      subscribe: vi.fn(() => () => undefined),
      setToolbarSize: vi.fn(),
      selectOperation: vi.fn(() => true),
      hideToolbar: vi.fn(),
    } as unknown as AssistantSelectionController;
    const container = {} as Element;
    const createPortal = vi.fn((node: unknown, target: Element) => ({
      portal: true,
      node,
      target,
    }));

    const Toolbar = createAssistantSelectionToolbar(React, controller, {
      createPortal,
      getContainer: () => container,
    });
    const rendered = Toolbar();

    expect(createPortal).toHaveBeenCalledTimes(1);
    expect(createPortal).toHaveBeenCalledWith(expect.any(Object), container);
    expect(rendered).toMatchObject({ portal: true, target: container });
  });

  it("shows one private-library entry action for an active frozen selection", () => {
    vi.stubGlobal("window", {
      QwenPaw: {
        host: {
          antd: {
            Alert: "alert",
            Button: "button",
            Card: "card",
            Input: Object.assign("input", { TextArea: "textarea" }),
            Select: "select",
          },
        },
      },
    });
    const React: QwenPawReactRuntime = {
      createElement: (type, props, ...children) => ({ type, props, children }),
      useState: (initial) => [
        typeof initial === "function" ? (initial as () => unknown)() : initial,
        () => undefined,
      ] as never,
      useRef: (initial) => ({ current: initial }),
      useEffect: (effect) => { effect(); },
    };
    const controller = {
      getState: () => ({
        phase: "ready",
        visible: true,
        selectionId: "00000000-0000-4000-8000-000000000001",
        fieldId: "chapter.body",
        fieldLabel: "章节正文",
        selectedCharacters: 4,
        placement: {
          x: 100,
          y: 100,
          placement: "below",
          strategy: "selection-range",
          precision: "exact",
        },
      }),
      subscribe: vi.fn(() => () => undefined),
      setToolbarSize: vi.fn(),
      selectOperation: vi.fn(() => true),
      hideToolbar: vi.fn(),
      getActiveSelectionRecord: vi.fn(() => ({ text: "排水坡度" })),
    } as unknown as AssistantSelectionController;

    const Toolbar = createAssistantSelectionToolbar(React, controller);

    expect(findText(Toolbar(), "加入私有库")).toBe(true);
    vi.unstubAllGlobals();
  });
});


describe("assistant selection toolbar measurement", () => {
  it("repositions for child-owned capture/error growth without a new selection and deduplicates size notifications", () => {
    const observers = installResizeObserver();
    const harness = createMeasurementHarness();
    harness.render();
    expect(observers).toHaveLength(1);
    expect(observers[0].observe).toHaveBeenCalledWith(harness.element, { box: "border-box" });
    expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, 80);

    for (const height of [620, 740, 580]) {
      harness.size.height = height;
      observers[0].notify();
      expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, height);
    }
    observers[0].notify();
    observers[0].notify();
    expect(harness.setToolbarSize).toHaveBeenCalledTimes(4);

    // Reposition publishes a new placement, which must not recreate the observer
    // or publish an identical measurement back to the controller indefinitely.
    harness.updateState({ placement: {
      x: 700, y: 350, placement: "selection-above", strategy: "selection-mirror",
      precision: "verified-selection", fallbackReasons: [],
    } });
    harness.render();
    observers[0].notify();
    expect(observers).toHaveLength(1);
    expect(harness.setToolbarSize).toHaveBeenCalledTimes(4);
    harness.unmount();
  });

  it("measures capture opening and asynchronous target labels even without ResizeObserver", async () => {
    enableCaptureHost();
    vi.stubGlobal("ResizeObserver", undefined);
    let resolveTargets!: (value: unknown) => void;
    let resolveNovel!: (value: unknown) => void;
    vi.mocked(apiRequest)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveTargets = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNovel = resolve; }));
    const harness = createMeasurementHarness();
    const initial = harness.render();
    const button = findButton(initial, "加入私有库");
    expect(button).toBeDefined();
    (button!.props.onClick as () => void)();
    harness.size.height = 620;
    harness.render();
    expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, 620);

    resolveTargets({ items: [{ id: "asset-a", title: "灾后设施抢修词", asset_type: "vocabulary", scope_kind: "library" }] });
    resolveNovel({ title: "缺氧：末日地下世界" });
    await Promise.resolve();
    await Promise.resolve();
    harness.size.height = 680;
    harness.render();
    expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, 680);
    expect(harness.setToolbarSize).toHaveBeenCalledTimes(3);
    harness.unmount();
  });

  it("remeasures loading errors and customization changes in the fallback path", async () => {
    enableCaptureHost();
    vi.stubGlobal("ResizeObserver", undefined);
    vi.mocked(apiRequest).mockRejectedValue(new Error("读取私有库目标失败"));
    const harness = createMeasurementHarness();
    const button = findButton(harness.render(), "加入私有库")!;
    (button.props.onClick as () => void)();
    harness.size.height = 620;
    harness.render();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    harness.size.height = 710;
    expect(findText(harness.render(), "读取私有库目标失败")).toBe(true);
    expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, 710);

    harness.updateState({ phase: "customizing" });
    harness.size.height = 900;
    harness.render();
    expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, 900);
    harness.unmount();
  });

  it("disconnects on hiding, selection replacement and unmount, ignoring stale callbacks and empty measurements", () => {
    const observers = installResizeObserver();
    const harness = createMeasurementHarness();
    harness.render();
    harness.size.height = 0;
    observers[0].notify();
    harness.size.height = Number.NaN;
    observers[0].notify();
    expect(harness.setToolbarSize).toHaveBeenCalledTimes(1);

    harness.updateState({ visible: false });
    expect(harness.render()).toBeNull();
    expect(observers[0].disconnect).toHaveBeenCalledTimes(1);
    harness.size.height = 640;
    observers[0].notify();
    expect(harness.setToolbarSize).toHaveBeenCalledTimes(1);

    harness.updateState({ visible: true });
    harness.render();
    expect(observers).toHaveLength(2);
    expect(harness.setToolbarSize).toHaveBeenLastCalledWith(620, 640);
    harness.updateState({ selectionId: "selection-b" });
    harness.render();
    expect(observers[1].disconnect).toHaveBeenCalledTimes(1);
    expect(observers).toHaveLength(3);
    const count = harness.setToolbarSize.mock.calls.length;
    harness.unmount();
    expect(observers[2].disconnect).toHaveBeenCalledTimes(1);
    expect(harness.unsubscribe).toHaveBeenCalledTimes(1);
    harness.size.height = 760;
    for (const observer of observers) observer.notify();
    expect(harness.setToolbarSize).toHaveBeenCalledTimes(count);
  });
});
