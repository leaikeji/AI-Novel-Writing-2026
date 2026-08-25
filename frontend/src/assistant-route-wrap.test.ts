import { describe, expect, it, vi } from "vitest";

import {
  AssistantRouteEventTarget,
  AssistantRouteReactRuntime,
  AssistantRouteResizeObserverEntry,
  createAssistantRouteWrap,
  registerAssistantRouteWrap,
  resolveAssistantRoutePageKind,
} from "./assistant-route-wrap";
import { RouteSessionSnapshot } from "./workbench-route";
import {
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  NovelAssistantContextRuntime,
} from "./assistant-context-runtime";


interface TestElement {
  type: unknown;
  props: Record<string, unknown>;
  children: unknown[];
}


interface EffectSlot {
  cleanup?: () => void;
  dependencies?: readonly unknown[];
}


interface PendingEffect {
  index: number;
  effect: () => void | (() => void);
  dependencies?: readonly unknown[];
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[] | undefined,
): boolean {
  if (left === undefined || right === undefined) return false;
  return left.length === right.length
    && left.every((value, index) => Object.is(value, right[index]));
}


class HookTestReact implements AssistantRouteReactRuntime {
  private stateCursor = 0;
  private refCursor = 0;
  private effectCursor = 0;
  private readonly states: unknown[] = [];
  private readonly refs: Array<{ current: unknown }> = [];
  private readonly effects: EffectSlot[] = [];
  private pendingEffects: PendingEffect[] = [];
  updates = 0;

  createElement(
    type: unknown,
    props: Record<string, unknown> | null = null,
    ...children: unknown[]
  ): TestElement {
    return { type, props: props || {}, children };
  }

  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void] {
    const index = this.stateCursor;
    this.stateCursor += 1;
    if (index >= this.states.length) {
      this.states.push(typeof initial === "function"
        ? (initial as () => T)()
        : initial);
    }
    return [this.states[index] as T, (next) => {
      const current = this.states[index] as T;
      this.states[index] = typeof next === "function"
        ? (next as (value: T) => T)(current)
        : next;
      this.updates += 1;
    }];
  }

  useRef<T>(initial: T): { current: T } {
    const index = this.refCursor;
    this.refCursor += 1;
    if (index >= this.refs.length) this.refs.push({ current: initial });
    return this.refs[index] as { current: T };
  }

  useEffect(
    effect: () => void | (() => void),
    dependencies?: readonly unknown[],
  ): void {
    const index = this.effectCursor;
    this.effectCursor += 1;
    const current = this.effects[index];
    if (current && sameDependencies(current.dependencies, dependencies)) return;
    this.pendingEffects.push({ index, effect, dependencies });
  }

  render(component: () => unknown): TestElement {
    this.stateCursor = 0;
    this.refCursor = 0;
    this.effectCursor = 0;
    this.pendingEffects = [];
    return component() as TestElement;
  }

  flushEffects(): void {
    const pending = this.pendingEffects;
    this.pendingEffects = [];
    for (const item of pending) {
      this.effects[item.index]?.cleanup?.();
      const cleanup = item.effect();
      this.effects[item.index] = {
        cleanup: typeof cleanup === "function" ? cleanup : undefined,
        dependencies: item.dependencies,
      };
    }
  }

  unmount(): void {
    for (const effect of this.effects) effect?.cleanup?.();
    this.effects.length = 0;
  }
}


class TestEventTarget implements AssistantRouteEventTarget {
  private readonly listeners = new Map<string, Set<() => void>>();

  addEventListener(type: "popstate" | "resize", listener: () => void): void {
    const registered = this.listeners.get(type) ?? new Set<() => void>();
    registered.add(listener);
    this.listeners.set(type, registered);
  }

  removeEventListener(type: "popstate" | "resize", listener: () => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: "popstate" | "resize"): void {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }

  count(type: "popstate" | "resize"): number {
    return this.listeners.get(type)?.size ?? 0;
  }
}


const ORDINARY_ROUTE: RouteSessionSnapshot = {
  state: "ordinary-chat",
  route: null,
  ownerToken: null,
};


function workbenchRoute(documentId?: string): RouteSessionSnapshot {
  return {
    state: "workbench-session",
    route: {
      novelId: "novel-1",
      documentId,
      chatPath: "/chat/session-1",
      ownerToken: "owner_token_0000000000000001",
    },
    ownerToken: "owner_token_0000000000000001",
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


describe("assistant route wrap", () => {
  it("returns the public route.wrap disposer without registering at module import", () => {
    const React = new HookTestReact();
    const dispose = vi.fn();
    const wrap = vi.fn(() => ({ dispose }));

    const registration = registerAssistantRouteWrap({
      pluginId: "ai-novel-world-2026",
      targetRouteId: "core.chat",
      route: { wrap },
      React,
      Workbench: () => "workbench",
    });

    expect(wrap).toHaveBeenCalledWith(
      "ai-novel-world-2026",
      "core.chat",
      expect.any(Function),
    );
    registration.dispose();
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("returns only Inner for ordinary chat and recomposes on browser navigation", () => {
    const React = new HookTestReact();
    const events = new TestEventTarget();
    const Inner = () => "native-chat";
    const Workbench = () => "workbench";
    const AssistantPane = () => "assistant";
    let route = ORDINARY_ROUTE;
    let location = { pathname: "/chat", search: "" };
    const wrap = createAssistantRouteWrap({
      React,
      Workbench,
      getRouteSession: () => route,
      getLocation: () => location,
      eventTarget: events,
      createResizeObserver: () => null,
      createAssistantPane: () => AssistantPane,
    });
    const Component = wrap(Inner) as () => unknown;

    const ordinary = React.render(Component);
    React.flushEffects();
    expect(ordinary.type).toBe(Inner);
    expect(ordinary.props).toEqual({});
    expect(events.count("popstate")).toBe(1);

    route = workbenchRoute();
    location = { pathname: "/chat/session-1", search: "" };
    events.emit("popstate");
    const workbench = React.render(Component);
    const [main, pane] = elementChildren(workbench);

    expect(React.updates).toBeGreaterThan(0);
    expect(workbench.type).toBe("div");
    expect(workbench.props["data-ai-novel-workbench"]).toBe("active");
    expect(elementChildren(main)[0].type).toBe(Workbench);
    expect(pane.type).toBe(AssistantPane);

    route = ORDINARY_ROUTE;
    location = { pathname: "/chat", search: "" };
    events.emit("popstate");
    expect(React.render(Component).type).toBe(Inner);
  });

  it("starts context preparation only inside workbench and stops it on exit", () => {
    const React = new HookTestReact();
    const events = new TestEventTarget();
    const stop = vi.fn();
    const start = vi.fn(() => stop);
    let route = ORDINARY_ROUTE;
    const wrap = createAssistantRouteWrap({
      React,
      Workbench: () => "workbench",
      getRouteSession: () => route,
      getLocation: () => ({ pathname: "/chat/session-1", search: "" }),
      eventTarget: events,
      createResizeObserver: () => null,
      createAssistantPane: () => () => "assistant",
      contextRefCoordinator: {
        start,
        refresh: vi.fn(),
        requestPatch: vi.fn(() => null),
        getReadyRef: vi.fn(() => null),
        getTabInstance: vi.fn(() => "tab-instance"),
        dispose: vi.fn(),
      },
    });
    const Component = wrap(() => "native-chat") as () => unknown;

    React.render(Component);
    React.flushEffects();
    expect(start).not.toHaveBeenCalled();

    route = workbenchRoute("document-1");
    React.render(Component);
    React.flushEffects();
    expect(start).toHaveBeenCalledOnce();

    route = ORDINARY_ROUTE;
    React.render(Component);
    React.flushEffects();
    expect(stop).toHaveBeenCalledOnce();
    React.unmount();
  });

  it("uses the public session getter when the host session hook is temporarily null", () => {
    const React = new HookTestReact();
    const runtime = new NovelAssistantContextRuntime();
    const wrap = createAssistantRouteWrap({
      React,
      Workbench: () => "workbench",
      getRouteSession: () => workbenchRoute("document-1"),
      getLocation: () => ({ pathname: "/chat/session-fallback", search: "" }),
      eventTarget: null,
      createResizeObserver: () => null,
      createAssistantPane: () => () => "assistant",
      contextRuntime: runtime,
      useSelectedAgent: () => ({ id: NOVEL_ASSISTANT_TARGET_AGENT_ID }),
      useCurrentSession: () => null,
      getCurrentSessionId: () => "session-fallback",
    });
    const Component = wrap(() => "native-chat") as () => unknown;

    React.render(Component);
    React.flushEffects();

    expect(runtime.getStatus()).toMatchObject({
      supportedAgent: true,
      selectedAgentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
      sessionId: "session-fallback",
    });
  });

  it("uses ResizeObserver content width and the chapter page layout", () => {
    const React = new HookTestReact();
    const events = new TestEventTarget();
    const observe = vi.fn();
    const disconnect = vi.fn();
    let observerCallback: ((entries: readonly AssistantRouteResizeObserverEntry[]) => void)
      | undefined;
    const createResizeObserver = vi.fn((callback) => {
      observerCallback = callback;
      return { observe, disconnect };
    });
    let measuredWidth = 1_500;
    const container = {
      getBoundingClientRect: () => ({ width: measuredWidth }),
    };
    const AssistantPane = () => "assistant";
    const wrap = createAssistantRouteWrap({
      React,
      Workbench: () => "workbench",
      getRouteSession: () => workbenchRoute("document-1"),
      getLocation: () => ({ pathname: "/chat/session-1", search: "" }),
      eventTarget: events,
      createResizeObserver,
      createAssistantPane: () => AssistantPane,
      defaultAssistantWidth: 520,
    });
    const Component = wrap(() => "native-chat") as () => unknown;

    const initial = React.render(Component);
    (initial.props.ref as { current: unknown }).current = container;
    React.flushEffects();
    expect(observe).toHaveBeenCalledWith(container);

    const measured = React.render(Component);
    expect(measured.props["data-container-width"]).toBe("1500");
    expect(measured.props["data-assistant-page-kind"]).toBe("chapter-editor");
    expect(measured.props["data-assistant-width"]).toBe("520");
    expect(elementChildren(measured)[0].props["data-main-width"]).toBe("980");

    measuredWidth = 1_180;
    observerCallback?.([{ target: container, contentRect: { width: 1_180 } }]);
    const resized = React.render(Component);
    const [, pane] = elementChildren(resized);
    expect(resized.props["data-assistant-width"]).toBe("420");
    expect(elementChildren(resized)[0].props["data-main-width"]).toBe("760");
    expect(pane.props.availableWidth).toBe(1_180);
    expect(pane.props.mainMinWidth).toBe(760);

    React.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(events.count("popstate")).toBe(0);
  });

  it("falls back to real element measurement when ResizeObserver is unavailable", () => {
    const React = new HookTestReact();
    const events = new TestEventTarget();
    let measuredWidth = 1_300;
    const container = {
      getBoundingClientRect: () => ({ width: measuredWidth }),
    };
    const wrap = createAssistantRouteWrap({
      React,
      Workbench: () => "workbench",
      getRouteSession: () => workbenchRoute(),
      getLocation: () => ({ pathname: "/chat/session-1", search: "?section=roles" }),
      eventTarget: events,
      createResizeObserver: () => null,
      createAssistantPane: () => () => "assistant",
    });
    const Component = wrap(() => "native-chat") as () => unknown;

    const initial = React.render(Component);
    (initial.props.ref as { current: unknown }).current = container;
    React.flushEffects();
    expect(events.count("resize")).toBe(1);

    expect(React.render(Component).props).toMatchObject({
      "data-container-width": "1300",
      "data-assistant-page-kind": "studio",
    });
    measuredWidth = 1_100;
    events.emit("resize");
    expect(React.render(Component).props["data-container-width"]).toBe("1100");

    React.unmount();
    expect(events.count("resize")).toBe(0);
    expect(events.count("popstate")).toBe(0);
  });

  it("derives both frozen workspace page types from public route data", () => {
    const route = workbenchRoute("document-1").route;
    if (!route) throw new Error("fixture must contain a workbench route");

    expect(resolveAssistantRoutePageKind(
      { pathname: "/chat/session-1", search: "" },
      route,
    )).toBe("chapter-editor");
    expect(resolveAssistantRoutePageKind(
      { pathname: "/chat/session-1", search: "?section=settings" },
      route,
    )).toBe("studio");
  });
});
