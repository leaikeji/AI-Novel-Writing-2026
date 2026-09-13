import { describe, expect, it, vi } from "vitest";

import type { QwenPawReactRuntime } from "./assistant-pane";
import type { AssistantSelectionController } from "./assistant-selection-controller";
import { createAssistantSelectionToolbar } from "./assistant-selection-toolbar";


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
