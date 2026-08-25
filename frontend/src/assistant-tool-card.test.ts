import { describe, expect, it, vi } from "vitest";

import {
  createAssistantToolCardModel,
  createAssistantToolRenderer,
  registerAssistantToolCard,
  type AssistantProposalCardState,
  type AssistantProposalCoordinator,
} from "./assistant-tool-card";


interface FakeElement {
  type: unknown;
  props: Record<string, unknown>;
  children: unknown[];
}


const FakeReact = {
  createElement(type: unknown, props?: unknown, ...children: unknown[]): FakeElement {
    return {
      type,
      props: (props ?? {}) as Record<string, unknown>,
      children,
    };
  },
  useState<T>(initial: T | (() => T)): [T, (next: T | ((value: T) => T)) => void] {
    return [typeof initial === "function" ? (initial as () => T)() : initial, vi.fn()];
  },
  useRef<T>(initial: T): { current: T } {
    return { current: initial };
  },
  useEffect(effect: () => void | (() => void)): void {
    effect();
  },
};


function createStatefulReactHarness() {
  const state: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<{ dependencies?: readonly unknown[]; cleanup?: () => void }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;

  const sameDependencies = (
    left: readonly unknown[] | undefined,
    right: readonly unknown[] | undefined,
  ) => Boolean(left && right
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));

  return {
    beginRender() {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
    },
    React: {
      createElement: FakeReact.createElement,
      useState<T>(initial: T | (() => T)): [T, (next: T | ((value: T) => T)) => void] {
        const index = stateIndex++;
        if (!(index in state)) {
          state[index] = typeof initial === "function" ? (initial as () => T)() : initial;
        }
        return [
          state[index] as T,
          (next) => {
            state[index] = typeof next === "function"
              ? (next as (value: T) => T)(state[index] as T)
              : next;
          },
        ];
      },
      useRef<T>(initial: T): { current: T } {
        const index = refIndex++;
        if (!refs[index]) refs[index] = { current: initial };
        return refs[index] as { current: T };
      },
      useEffect(
        effect: () => void | (() => void),
        dependencies: readonly unknown[],
      ): void {
        const index = effectIndex++;
        if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
        effects[index]?.cleanup?.();
        const cleanup = effect();
        effects[index] = {
          dependencies: [...dependencies],
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      },
    },
  };
}


function findElement(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): FakeElement | undefined {
  if (!root || typeof root !== "object" || !("type" in root)) return undefined;
  const element = root as FakeElement;
  if (predicate(element)) return element;
  for (const child of element.children) {
    const found = findElement(child, predicate);
    if (found) return found;
  }
  return undefined;
}


function renderRegisteredComponent(root: FakeElement): FakeElement {
  expect(typeof root.type).toBe("function");
  return (root.type as (props: QwenPawToolRenderProps) => FakeElement)(
    root.props as unknown as QwenPawToolRenderProps,
  );
}


const SELECTION_ID = "123e4567-e89b-42d3-a456-426614174000";
const readyState: AssistantProposalCardState = {
  phase: "ready",
  applicable: true,
  canUndo: false,
  statusMessage: "候选已校验",
  fieldId: "chapter.body",
  fieldLabel: "正文",
  originalCharacterCount: 6,
  persistence: "autosave",
};
const coordinator = {
  currentSessionId: vi.fn(() => "session-1"),
  subscribe: vi.fn(() => () => undefined),
  inspect: vi.fn(async () => readyState),
  apply: vi.fn(async () => readyState),
  undo: vi.fn(async () => readyState),
  discard: vi.fn((_model, state) => ({ ...state, phase: "discarded" })),
} as unknown as AssistantProposalCoordinator;


const validProps: QwenPawToolRenderProps = {
  sessionId: "session-1",
  messageId: "message-2",
  result: {
    schema_version: 1,
    selection_id: SELECTION_ID,
    operation: "polish",
    replacement_text: "海风吹过旧窗。",
    short_summary: "收紧句子",
    replacement_character_count: 999,
    warnings: ["请作者确认语气。"],
  },
};


describe("assistant tool card", () => {
  it("builds a strict bounded model and computes text length", () => {
    expect(createAssistantToolCardModel(validProps)).toEqual({
      valid: true,
      selectionId: SELECTION_ID,
      operation: "polish",
      operationLabel: "润色",
      summary: "收紧句子",
      replacementText: "海风吹过旧窗。",
      replacementCharacterCount: 7,
      warnings: ["请作者确认语气。"],
      sessionId: "session-1",
      messageId: "message-2",
    });
  });

  it("safely parses a bounded JSON string returned by the public renderer API", () => {
    expect(createAssistantToolCardModel({
      sessionId: "session-1",
      messageId: "message-2",
      result: JSON.stringify(validProps.result),
    })).toMatchObject({
      valid: true,
      selectionId: SELECTION_ID,
      operation: "polish",
      replacementText: "海风吹过旧窗。",
    });
  });

  it("parses the real QwenPaw 2.1 tool-message envelope and binds the current session", () => {
    expect(createAssistantToolCardModel({
      data: {
        id: "c".repeat(32),
        type: "tool_result_message",
        role: "assistant",
        status: "completed",
        metadata: {
          original_id: "d".repeat(32),
          original_name: "QwenPaw",
        },
        content: [
          {
            type: "tool",
            data: {
              name: "novel_prepare_selection_edit",
              call_id: "call-1",
              arguments: {},
            },
          },
          {
            type: "tool",
            data: {
              name: "novel_prepare_selection_edit",
              call_id: "call-1",
              state: "success",
              output: JSON.stringify(validProps.result),
            },
          },
        ],
      },
    }, "session-1")).toMatchObject({
      valid: true,
      selectionId: SELECTION_ID,
      operation: "polish",
      replacementText: "海风吹过旧窗。",
      sessionId: "session-1",
      messageId: "c".repeat(32),
    });
  });

  it("unwraps the bounded AgentScope text-content result inside QwenPaw output", () => {
    expect(createAssistantToolCardModel({
      data: {
        id: "e".repeat(32),
        content: [{
          data: {
            name: "novel_prepare_selection_edit",
            output: {
              content: [{
                type: "text",
                text: JSON.stringify(validProps.result),
              }],
            },
          },
        }],
      },
    }, "session-1")).toMatchObject({
      valid: true,
      selectionId: SELECTION_ID,
      replacementText: "海风吹过旧窗。",
      sessionId: "session-1",
      messageId: "e".repeat(32),
    });
  });

  it("does not unwrap a result block registered for another tool", () => {
    expect(createAssistantToolCardModel({
      data: {
        id: "c".repeat(32),
        content: [{
          data: {
            name: "unrelated_tool",
            output: JSON.stringify(validProps.result),
          },
        }],
      },
    }, "session-1")).toMatchObject({
      valid: false,
      error: "结果不是对象",
      sessionId: "session-1",
      messageId: "c".repeat(32),
    });
  });

  it("renders untrusted text as React children and keeps copy available", () => {
    const copyText = vi.fn();
    const renderer = createAssistantToolRenderer({
      React: FakeReact,
      coordinator,
      copyText,
    });
    const wrapper = renderer({
      ...validProps,
      result: {
        ...(validProps.result as Record<string, unknown>),
        replacement_text: "<img src=x onerror=alert(1)>",
      },
    }) as FakeElement;
    const tree = renderRegisteredComponent(wrapper);

    expect(tree.props).toMatchObject({
      "data-session-id": "session-1",
      "data-message-id": "message-2",
    });
    expect(findElement(tree, (element) => (
      Object.prototype.hasOwnProperty.call(element.props, "dangerouslySetInnerHTML")
    ))).toBeUndefined();
    const copyButton = findElement(tree, (element) => (
      element.type === "button" && element.children.includes("复制")
    ));
    expect(copyButton?.props["aria-label"]).toBe("复制 AI 候选文本");
    (copyButton?.props.onClick as () => void)();
    expect(copyText).toHaveBeenCalledWith("<img src=x onerror=alert(1)>");
  });

  it("recovers when the host mounts during streaming and supplies the result later", async () => {
    const harness = createStatefulReactHarness();
    const streamingCoordinator = {
      ...coordinator,
      subscribe: vi.fn(() => () => undefined),
      inspect: vi.fn(async () => readyState),
    } as unknown as AssistantProposalCoordinator;
    const renderer = createAssistantToolRenderer({
      React: harness.React,
      coordinator: streamingCoordinator,
      copyText: vi.fn(),
    });
    const pending = renderer({
      sessionId: "session-1",
      messageId: "message-streaming",
    }) as FakeElement;
    const Component = pending.type as (props: QwenPawToolRenderProps) => FakeElement;

    harness.beginRender();
    const pendingTree = Component(pending.props as unknown as QwenPawToolRenderProps);
    expect(pendingTree.props["data-proposal-phase"]).toBe("invalid");

    const completed = renderer({
      ...validProps,
      messageId: "message-streaming",
    }) as FakeElement;
    harness.beginRender();
    Component(completed.props as unknown as QwenPawToolRenderProps);
    await Promise.resolve();
    await Promise.resolve();

    harness.beginRender();
    const completedTree = Component(completed.props as unknown as QwenPawToolRenderProps);
    expect(streamingCoordinator.inspect).toHaveBeenCalledOnce();
    expect(completedTree.props["data-proposal-phase"]).toBe("ready");
    expect(findElement(completedTree, (element) => element.props.role === "status")?.children)
      .toContain("候选已校验");
  });

  it("fails closed for malformed bindings but preserves bounded literal copy", () => {
    expect(createAssistantToolCardModel({
      result: {
        schema_version: 1,
        selection_id: "not-a-uuid",
        operation: "polish",
        replacement_text: "只供复制",
      },
      sessionId: "bad id with spaces",
      messageId: "message-1",
    })).toMatchObject({
      valid: false,
      replacementText: "只供复制",
      sessionId: undefined,
      messageId: "message-1",
      error: "结果协议无效",
    });
    expect(createAssistantToolCardModel({ result: "{not-json" })).toMatchObject({
      valid: false,
      summary: "工具未返回可应用候选，页面内容没有修改。",
      error: "结果不是对象",
    });
  });

  it("explains a rejected or missing tool result without implying a page write", () => {
    const renderer = createAssistantToolRenderer({
      React: FakeReact,
      coordinator,
      copyText: vi.fn(),
    });
    const wrapper = renderer({
      sessionId: "session-1",
      messageId: "message-rejected",
    }) as FakeElement;
    const tree = renderRegisteredComponent(wrapper);

    expect(findElement(tree, (element) => element.type === "strong")?.children)
      .toContain("未生成可应用候选");
    expect(findElement(tree, (element) => element.props.role === "status")?.children)
      .toContain("工具未返回可应用候选，页面内容没有修改。");
  });

  it("registers the public renderer and returns its disposer", () => {
    let renderer: ((props: QwenPawToolRenderProps) => unknown) | undefined;
    const dispose = vi.fn();
    const toolRender = vi.fn((_pluginId, _toolName, nextRenderer) => {
      renderer = nextRenderer;
      return { dispose };
    });

    const registration = registerAssistantToolCard({
      pluginId: "ai-novel-world-2026",
      toolName: "novel_prepare_selection_edit",
      toolRender,
      React: FakeReact,
      coordinator,
      copyText: vi.fn(),
    });

    expect(toolRender).toHaveBeenCalledWith(
      "ai-novel-world-2026",
      "novel_prepare_selection_edit",
      expect.any(Function),
    );
    expect(renderer?.(validProps)).toBeTruthy();
    registration.dispose();
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("fails closed when the host-side coordinator rejects", async () => {
    const onStateChange = vi.fn();
    const rejectedCoordinator = {
      currentSessionId: vi.fn(() => "session-1"),
      subscribe: vi.fn(() => () => undefined),
      inspect: vi.fn(async () => { throw new Error("hash unavailable"); }),
      apply: vi.fn(async () => { throw new Error("apply unavailable"); }),
      undo: vi.fn(async () => { throw new Error("undo unavailable"); }),
      discard: vi.fn((_model, state) => ({ ...state, phase: "discarded" })),
    } as unknown as AssistantProposalCoordinator;
    const renderer = createAssistantToolRenderer({
      React: FakeReact,
      coordinator: rejectedCoordinator,
      copyText: vi.fn(),
      onStateChange,
    });
    const wrapper = renderer(validProps) as FakeElement;

    renderRegisteredComponent(wrapper);
    await Promise.resolve();
    await Promise.resolve();

    expect(onStateChange).toHaveBeenCalledWith(expect.objectContaining({
      phase: "failed",
      applicable: false,
      canUndo: false,
      statusMessage: "候选审阅器校验异常，未修改页面内容；仍可复制候选",
    }));
  });
});
