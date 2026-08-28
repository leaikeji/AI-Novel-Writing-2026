import { describe, expect, it, vi } from "vitest";

import {
  ASSISTANT_PANE_COLLAPSED_WIDTH,
  ASSISTANT_PANE_DEFAULT_WIDTH,
  ASSISTANT_PANE_MAX_WIDTH,
  ASSISTANT_PANE_MIN_WIDTH,
  ASSISTANT_PANE_PREFERENCE_KEY,
  assistantPaneWidthFromKey,
  createAssistantPaneResizeController,
  createQwenPawAssistantPane,
  loadAssistantPanePreference,
  renderQwenPawAssistantPane,
  resolveAssistantPaneLayout,
  saveAssistantPanePreference,
  type AssistantPanePreferenceStorage,
  type QwenPawReactRuntime,
} from "./assistant-pane";


interface TestElement {
  type: unknown;
  props: Record<string, unknown>;
  children: unknown[];
}


const TestReact = {
  createElement(
    type: unknown,
    props: Record<string, unknown> | null = null,
    ...children: unknown[]
  ): TestElement {
    return { type, props: props || {}, children };
  },
};


class MemoryPreferenceStorage implements AssistantPanePreferenceStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}


function createHookTestRuntime(): {
  React: QwenPawReactRuntime;
  unmount: () => void;
} {
  const cleanups: Array<() => void> = [];
  const React: QwenPawReactRuntime = {
    createElement: TestReact.createElement,
    useState<T>(initial: T | (() => T)) {
      let current = typeof initial === "function"
        ? (initial as () => T)()
        : initial;
      return [
        current,
        (next: T | ((value: T) => T)) => {
          current = typeof next === "function"
            ? (next as (value: T) => T)(current)
            : next;
        },
      ];
    },
    useRef<T>(initial: T) {
      return { current: initial };
    },
    useEffect(effect) {
      const cleanup = effect();
      if (typeof cleanup === "function") cleanups.push(cleanup);
    },
  };
  return {
    React,
    unmount: () => {
      for (const cleanup of cleanups.reverse()) cleanup();
    },
  };
}


function elementChildren(element: TestElement): TestElement[] {
  return element.children.filter(
    (child): child is TestElement => Boolean(
      child
      && typeof child === "object"
      && "type" in child
      && "props" in child
      && "children" in child,
    ),
  );
}


describe("resolveAssistantPaneLayout", () => {
  it.each([320, 450, 750])("keeps the supported fixed width %ipx operable", (width) => {
    const layout = resolveAssistantPaneLayout({
      availableWidth: 1400,
      preferredWidth: width,
    });

    expect(layout.mode).toBe("inline");
    expect(layout.expandedWidth).toBe(width);
    expect(layout.renderedWidth).toBe(width);
  });

  it("uses the documented default and clamps invalid preferences", () => {
    expect(resolveAssistantPaneLayout({}).preferredWidth).toBe(ASSISTANT_PANE_DEFAULT_WIDTH);
    expect(resolveAssistantPaneLayout({ preferredWidth: 1 }).expandedWidth).toBe(
      ASSISTANT_PANE_MIN_WIDTH,
    );
    expect(resolveAssistantPaneLayout({ preferredWidth: 9999 }).expandedWidth).toBe(
      ASSISTANT_PANE_MAX_WIDTH,
    );
  });

  it("clamps the assistant to the dynamic maximum before shrinking the main area", () => {
    const layout = resolveAssistantPaneLayout({
      availableWidth: 1080,
      mainMinWidth: 640,
      preferredWidth: 520,
    });

    expect(layout.mode).toBe("inline");
    expect(layout.dynamicMaxWidth).toBe(440);
    expect(layout.expandedWidth).toBe(440);
  });

  it("falls back to an overlay instead of making the native Inner narrower than 320px", () => {
    const layout = resolveAssistantPaneLayout({
      availableWidth: 900,
      mainMinWidth: 640,
      preferredWidth: 380,
    });

    expect(layout.mode).toBe("overlay");
    expect(layout.expandedWidth).toBe(380);
  });

  it("collapses to a recoverable rail without changing the expanded width", () => {
    const layout = resolveAssistantPaneLayout({
      collapsed: true,
      preferredWidth: 520,
    });

    expect(layout.renderedWidth).toBe(ASSISTANT_PANE_COLLAPSED_WIDTH);
    expect(layout.expandedWidth).toBe(520);
  });

  it("keeps a narrow collapsed rail inline while an expanded pane overlays", () => {
    const collapsed = resolveAssistantPaneLayout({
      availableWidth: 324,
      collapsed: true,
      mainMinWidth: 272,
      preferredWidth: 380,
    });
    const expanded = resolveAssistantPaneLayout({
      availableWidth: 324,
      collapsed: false,
      mainMinWidth: 272,
      preferredWidth: 380,
    });

    expect(collapsed).toMatchObject({
      mode: "inline",
      expandedWidth: 380,
      renderedWidth: ASSISTANT_PANE_COLLAPSED_WIDTH,
    });
    expect(expanded).toMatchObject({
      mode: "overlay",
      expandedWidth: 380,
      renderedWidth: 380,
    });
  });
});


describe("assistantPaneWidthFromKey", () => {
  const layout = resolveAssistantPaneLayout({ preferredWidth: 380 });

  it("uses 10px arrows and 40px Shift+arrows", () => {
    expect(assistantPaneWidthFromKey(layout, "ArrowLeft")).toBe(390);
    expect(assistantPaneWidthFromKey(layout, "ArrowRight")).toBe(370);
    expect(assistantPaneWidthFromKey(layout, "ArrowLeft", true)).toBe(420);
    expect(assistantPaneWidthFromKey(layout, "ArrowRight", true)).toBe(340);
  });

  it("supports Home and End and ignores unrelated keys", () => {
    expect(assistantPaneWidthFromKey(layout, "Home")).toBe(320);
    expect(assistantPaneWidthFromKey(layout, "End")).toBe(750);
    expect(assistantPaneWidthFromKey(layout, "Escape")).toBeNull();
  });

  it("clamps both keyboard step sizes to the supported range", () => {
    const nearMaximum = resolveAssistantPaneLayout({ preferredWidth: 740 });
    const nearMinimum = resolveAssistantPaneLayout({ preferredWidth: 325 });

    expect(assistantPaneWidthFromKey(nearMaximum, "ArrowLeft", true)).toBe(750);
    expect(assistantPaneWidthFromKey(nearMinimum, "ArrowRight", true)).toBe(320);
  });
});


describe("assistant pane preference", () => {
  it("persists only validated workbench width and collapse state", () => {
    const storage = new MemoryPreferenceStorage();

    expect(saveAssistantPanePreference({
      preferredWidth: 999,
      collapsed: true,
    }, storage)).toBe(true);
    expect(storage.values.has(ASSISTANT_PANE_PREFERENCE_KEY)).toBe(true);
    expect(loadAssistantPanePreference(storage)).toEqual({
      schemaVersion: 1,
      preferredWidth: 750,
      collapsed: true,
    });
    expect(Object.keys(JSON.parse(
      storage.values.get(ASSISTANT_PANE_PREFERENCE_KEY) || "{}",
    )).sort()).toEqual(["collapsed", "preferredWidth", "schemaVersion"]);
  });

  it.each([
    "{",
    "null",
    "[]",
    JSON.stringify({ schemaVersion: 2, preferredWidth: 380, collapsed: false }),
    JSON.stringify({ schemaVersion: 1, preferredWidth: "380", collapsed: false }),
    JSON.stringify({ schemaVersion: 1, preferredWidth: 900, collapsed: false }),
    JSON.stringify({ schemaVersion: 1, preferredWidth: 380, collapsed: "false" }),
  ])("rejects malformed or untrusted stored JSON: %s", (serialized) => {
    const storage = new MemoryPreferenceStorage();
    storage.values.set(ASSISTANT_PANE_PREFERENCE_KEY, serialized);

    expect(loadAssistantPanePreference(storage)).toBeNull();
  });

  it("degrades safely when local preference access is unavailable", () => {
    const unavailable: AssistantPanePreferenceStorage = {
      getItem: () => { throw new Error("storage blocked"); },
      setItem: () => { throw new Error("storage blocked"); },
    };

    expect(loadAssistantPanePreference(unavailable)).toBeNull();
    expect(saveAssistantPanePreference({
      preferredWidth: 380,
      collapsed: false,
    }, unavailable)).toBe(false);
    expect(loadAssistantPanePreference(null)).toBeNull();
  });
});


describe("createAssistantPaneResizeController", () => {
  it("maps pointer movement from the left separator and clamps both bounds", () => {
    const setPointerCapture = vi.fn();
    const releasePointerCapture = vi.fn();
    const controller = createAssistantPaneResizeController();
    const captureTarget = {
      setPointerCapture,
      releasePointerCapture,
      hasPointerCapture: () => true,
    };

    expect(controller.start({
      pointerId: 7,
      clientX: 700,
      width: 380,
      dynamicMaxWidth: 440,
      captureTarget,
    })).toBe(true);
    expect(controller.move(7, 650)).toBe(430);
    expect(controller.move(7, 500)).toBe(440);
    expect(controller.move(7, 900)).toBe(320);
    expect(controller.move(99, 700)).toBeNull();
    expect(controller.finish(7)).toBe(320);
    expect(controller.snapshot()).toEqual({ active: false });
    expect(setPointerCapture).toHaveBeenCalledWith(7);
    expect(releasePointerCapture).toHaveBeenCalledWith(7);
  });

  it("releases capture on pointer cancel and terminal disposal", () => {
    const releasePointerCapture = vi.fn();
    const captureTarget = {
      setPointerCapture: vi.fn(),
      releasePointerCapture,
      hasPointerCapture: () => true,
    };
    const cancelled = createAssistantPaneResizeController();
    cancelled.start({
      pointerId: 1,
      clientX: 500,
      width: 380,
      dynamicMaxWidth: 520,
      captureTarget,
    });
    cancelled.move(1, 460);

    expect(cancelled.cancel(1)).toBe(420);
    expect(cancelled.move(1, 400)).toBeNull();

    const disposed = createAssistantPaneResizeController();
    disposed.start({
      pointerId: 2,
      clientX: 500,
      width: 380,
      dynamicMaxWidth: 520,
      captureTarget,
    });
    disposed.dispose();
    disposed.dispose();

    expect(disposed.snapshot()).toEqual({ active: false });
    expect(disposed.start({
      pointerId: 3,
      clientX: 500,
      width: 380,
      dynamicMaxWidth: 520,
    })).toBe(false);
    expect(releasePointerCapture).toHaveBeenCalledTimes(2);
  });
});


describe("renderQwenPawAssistantPane", () => {
  const Inner = () => "native-chat";

  it("keeps Inner mounted while the pane is collapsed", () => {
    const pane = renderQwenPawAssistantPane(TestReact, Inner, {
      collapsed: true,
      preferredWidth: 380,
    }) as TestElement;
    const [separator, toggle, innerContainer] = elementChildren(pane);

    expect(pane.props["data-assistant-pane-width"]).toBe("52");
    expect(separator.props.tabIndex).toBe(-1);
    expect(toggle.props["aria-label"]).toBe("展开 QwenPaw 助手");
    expect(innerContainer.props["aria-hidden"]).toBe(true);
    expect(elementChildren(innerContainer)[0].type).toBe(Inner);
  });

  it("renders the narrow collapsed rail in flow and the expanded pane as an overlay", () => {
    const common = {
      availableWidth: 324,
      mainMinWidth: 272,
      preferredWidth: 380,
    };
    const collapsed = renderQwenPawAssistantPane(TestReact, Inner, {
      ...common,
      collapsed: true,
    }) as TestElement;
    const expanded = renderQwenPawAssistantPane(TestReact, Inner, {
      ...common,
      collapsed: false,
    }) as TestElement;
    const collapsedStyle = collapsed.props.style as Record<string, unknown>;
    const expandedStyle = expanded.props.style as Record<string, unknown>;

    expect(collapsed.props.className).toBe("anw-assistant-pane is-collapsed");
    expect(collapsed.props["data-assistant-pane-mode"]).toBe("inline");
    expect(collapsedStyle).toMatchObject({
      flex: `0 0 ${ASSISTANT_PANE_COLLAPSED_WIDTH}px`,
      position: "relative",
      width: `${ASSISTANT_PANE_COLLAPSED_WIDTH}px`,
    });
    expect(expanded.props.className).toBe("anw-assistant-pane is-overlay");
    expect(expanded.props["data-assistant-pane-mode"]).toBe("overlay");
    expect(expandedStyle).toMatchObject({
      position: "absolute",
      right: 0,
      top: 0,
      width: "380px",
    });
  });

  it("exposes an accessible collapse action and keyboard width control", () => {
    const onCollapsedChange = vi.fn();
    const onPreferredWidthChange = vi.fn();
    const preventDefault = vi.fn();
    const pane = renderQwenPawAssistantPane(TestReact, Inner, {
      onCollapsedChange,
      onPreferredWidthChange,
      preferredWidth: 380,
    }) as TestElement;
    const [separator, toggle] = elementChildren(pane);

    expect(separator.props.role).toBe("separator");
    expect(separator.props["aria-valuemin"]).toBe(320);
    expect(separator.props["aria-valuemax"]).toBe(750);
    expect(separator.props["aria-valuenow"]).toBe(380);
    expect(separator.props["aria-controls"]).toBe("anw-qwenpaw-assistant-inner");
    expect(separator.props["aria-orientation"]).toBe("vertical");
    expect((separator.props.style as Record<string, unknown>).touchAction).toBe("none");
    expect(toggle.props["aria-controls"]).toBe("anw-qwenpaw-assistant-inner");
    expect((toggle.props.style as Record<string, unknown>).zIndex).toBe(5);
    (separator.props.onKeyDown as (event: unknown) => void)({
      key: "ArrowLeft",
      shiftKey: true,
      preventDefault,
    });
    (toggle.props.onClick as () => void)();

    expect(preventDefault).toHaveBeenCalledOnce();
    expect(onPreferredWidthChange).toHaveBeenCalledWith(420);
    expect(toggle.props["aria-label"]).toBe("折叠 QwenPaw 助手");
    expect(onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("drags through pointer callbacks and commits a dynamically clamped width", () => {
    const onPreferredWidthChange = vi.fn();
    const onPreferredWidthCommit = vi.fn();
    const preventDefault = vi.fn();
    const setPointerCapture = vi.fn();
    const releasePointerCapture = vi.fn();
    const pane = renderQwenPawAssistantPane(TestReact, Inner, {
      availableWidth: 1080,
      mainMinWidth: 640,
      preferredWidth: 380,
      onPreferredWidthChange,
      onPreferredWidthCommit,
      resizeController: createAssistantPaneResizeController(),
    }) as TestElement;
    const [separator] = elementChildren(pane);
    const captureTarget = {
      setPointerCapture,
      releasePointerCapture,
      hasPointerCapture: () => true,
    };

    expect(separator.props["aria-valuemax"]).toBe(440);
    (separator.props.onPointerDown as (event: unknown) => void)({
      pointerId: 4,
      clientX: 700,
      currentTarget: captureTarget,
      preventDefault,
    });
    (separator.props.onPointerMove as (event: unknown) => void)({
      pointerId: 4,
      clientX: 600,
      currentTarget: captureTarget,
      preventDefault,
    });
    (separator.props.onPointerUp as (event: unknown) => void)({
      pointerId: 4,
      clientX: 500,
      currentTarget: captureTarget,
      preventDefault,
    });

    expect(onPreferredWidthChange).toHaveBeenNthCalledWith(1, 440);
    expect(onPreferredWidthChange).toHaveBeenLastCalledWith(440);
    expect(onPreferredWidthCommit).toHaveBeenCalledWith(440);
    expect(setPointerCapture).toHaveBeenCalledWith(4);
    expect(releasePointerCapture).toHaveBeenCalledWith(4);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("commits and cleans up a cancelled pointer without accepting later moves", () => {
    const onPreferredWidthChange = vi.fn();
    const onPreferredWidthCommit = vi.fn();
    const pane = renderQwenPawAssistantPane(TestReact, Inner, {
      preferredWidth: 380,
      onPreferredWidthChange,
      onPreferredWidthCommit,
      resizeController: createAssistantPaneResizeController(),
    }) as TestElement;
    const [separator] = elementChildren(pane);
    const captureTarget = {
      setPointerCapture: vi.fn(),
      releasePointerCapture: vi.fn(),
      hasPointerCapture: () => true,
    };

    (separator.props.onPointerDown as (event: unknown) => void)({
      pointerId: 8,
      clientX: 700,
      currentTarget: captureTarget,
    });
    (separator.props.onPointerMove as (event: unknown) => void)({
      pointerId: 8,
      clientX: 660,
      currentTarget: captureTarget,
    });
    (separator.props.onPointerCancel as (event: unknown) => void)({
      pointerId: 8,
      clientX: 660,
      currentTarget: captureTarget,
    });
    (separator.props.onPointerMove as (event: unknown) => void)({
      pointerId: 8,
      clientX: 600,
      currentTarget: captureTarget,
    });

    expect(onPreferredWidthChange).toHaveBeenCalledTimes(1);
    expect(onPreferredWidthChange).toHaveBeenCalledWith(420);
    expect(onPreferredWidthCommit).toHaveBeenCalledWith(420);
    expect(captureTarget.releasePointerCapture).toHaveBeenCalledWith(8);
  });
});


describe("createQwenPawAssistantPane", () => {
  const Inner = () => "native-chat";

  it("restores workbench preference while keeping the native Inner mounted", () => {
    const storage = new MemoryPreferenceStorage();
    saveAssistantPanePreference({
      preferredWidth: 410,
      collapsed: true,
    }, storage);
    const runtime = createHookTestRuntime();
    const AssistantPane = createQwenPawAssistantPane(runtime.React, Inner);

    const pane = AssistantPane({ preferenceStorage: storage }) as TestElement;
    const [, toggle, innerContainer] = elementChildren(pane);

    expect(pane.props["data-assistant-pane-width"]).toBe("52");
    expect(toggle.props["aria-label"]).toBe("展开 QwenPaw 助手");
    expect(elementChildren(innerContainer)[0].type).toBe(Inner);

    (toggle.props.onClick as () => void)();
    expect(loadAssistantPanePreference(storage)).toEqual({
      schemaVersion: 1,
      preferredWidth: 410,
      collapsed: false,
    });
    runtime.unmount();
  });

  it("releases an active pointer and persists its final width on unmount", () => {
    const storage = new MemoryPreferenceStorage();
    saveAssistantPanePreference({
      preferredWidth: 410,
      collapsed: false,
    }, storage);
    const runtime = createHookTestRuntime();
    const AssistantPane = createQwenPawAssistantPane(runtime.React, Inner);
    const pane = AssistantPane({ preferenceStorage: storage }) as TestElement;
    const [separator] = elementChildren(pane);
    const releasePointerCapture = vi.fn();
    const captureTarget = {
      setPointerCapture: vi.fn(),
      releasePointerCapture,
      hasPointerCapture: () => true,
    };

    (separator.props.onPointerDown as (event: unknown) => void)({
      pointerId: 12,
      clientX: 700,
      currentTarget: captureTarget,
    });
    (separator.props.onPointerMove as (event: unknown) => void)({
      pointerId: 12,
      clientX: 670,
      currentTarget: captureTarget,
    });
    runtime.unmount();

    expect(releasePointerCapture).toHaveBeenCalledWith(12);
    expect(loadAssistantPanePreference(storage)).toEqual({
      schemaVersion: 1,
      preferredWidth: 440,
      collapsed: false,
    });
  });

  it("can disable preference access without affecting the pane", () => {
    const getItem = vi.fn(() => { throw new Error("must not read"); });
    const setItem = vi.fn(() => { throw new Error("must not write"); });
    const runtime = createHookTestRuntime();
    const AssistantPane = createQwenPawAssistantPane(runtime.React, Inner);
    const pane = AssistantPane({
      persistPreference: false,
      preferenceStorage: { getItem, setItem },
    }) as TestElement;
    const [, toggle, innerContainer] = elementChildren(pane);

    expect(pane.props["data-assistant-pane-width"]).toBe("450");
    expect(elementChildren(innerContainer)[0].type).toBe(Inner);
    (toggle.props.onClick as () => void)();
    runtime.unmount();

    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });
});
