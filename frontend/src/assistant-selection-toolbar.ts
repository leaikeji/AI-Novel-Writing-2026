import {
  ASSISTANT_SELECTION_OPERATIONS,
  ASSISTANT_SELECTION_OPERATION_LABELS,
  type AssistantSelectionController,
  type AssistantSelectionOperation,
  type AssistantSelectionToolbarState,
} from "./assistant-selection-controller";
import type { QwenPawReactRuntime } from "./assistant-pane";


export interface AssistantSelectionToolbarProps {
}


export interface AssistantSelectionPortalRuntime {
  createPortal(node: unknown, container: Element): unknown;
  getContainer(): Element | null;
}


export function createAssistantSelectionToolbar(
  React: QwenPawReactRuntime,
  controller: AssistantSelectionController,
  portal?: AssistantSelectionPortalRuntime,
): (props?: AssistantSelectionToolbarProps) => unknown {
  const h = React.createElement;

  return function AssistantSelectionToolbar(
    props: AssistantSelectionToolbarProps = {},
  ) {
    const [state, setState] = React.useState<AssistantSelectionToolbarState>(
      () => controller.getState(),
    );
    const [customInstruction, setCustomInstruction] = React.useState("");
    const [useNovelContext, setUseNovelContext] = React.useState(false);
    const toolbarRef = React.useRef<HTMLElement | null>(null);

    React.useEffect(() => controller.subscribe(setState), []);
    React.useEffect(() => {
      const toolbar = toolbarRef.current;
      if (!state.visible || !toolbar) return;
      const rect = toolbar.getBoundingClientRect();
      controller.setToolbarSize(rect.width, rect.height);
    }, [state.visible, state.selectionId]);
    React.useEffect(() => {
      if (state.phase !== "customizing") {
        setCustomInstruction("");
        setUseNovelContext(false);
      }
    }, [state.phase, state.selectionId]);

    if (!state.visible || !state.placement) return null;

    const choose = (operation: AssistantSelectionOperation) => {
      if (!controller.selectOperation(operation)) return;
    };
    const onToolbarKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      controller.hideToolbar();
    };

    const toolbar = h(
      "section",
      {
        ref: toolbarRef,
        className: `anw-assistant-selection-toolbar is-${state.phase}`,
        "data-assistant-selection-toolbar": "true",
        "data-selection-strategy": state.placement.strategy,
        "data-selection-placement": state.placement.placement,
        "aria-label": `${state.fieldLabel ?? "当前字段"}选区助手`,
        "aria-describedby": "anw-assistant-selection-status",
        onKeyDown: onToolbarKeyDown,
        style: {
          left: `${Math.round(state.placement.x)}px`,
          top: `${Math.round(state.placement.y)}px`,
        },
      },
      h(
        "div",
        { className: "anw-assistant-selection-actions", role: "toolbar", "aria-label": "选区操作" },
        ...ASSISTANT_SELECTION_OPERATIONS.map((operation) => h(
          "button",
          {
            key: operation,
            type: "button",
            className: state.operation === operation ? "is-active" : "",
            "aria-label": `${ASSISTANT_SELECTION_OPERATION_LABELS[operation]}选中文字`,
            "aria-pressed": state.operation === operation,
            disabled: state.phase === "capturing" || state.phase === "failed",
            onClick: () => choose(operation),
          },
          ASSISTANT_SELECTION_OPERATION_LABELS[operation],
        )),
        h(
          "button",
          {
            type: "button",
            className: "anw-assistant-selection-close",
            "aria-label": "收起选区工具条",
            onClick: () => controller.hideToolbar(),
          },
          "×",
        ),
      ),
      state.phase === "customizing"
        ? h(
          "form",
          {
            className: "anw-assistant-selection-custom",
            onSubmit: (event: Event) => {
              event.preventDefault();
              controller.submitCustomInstruction(customInstruction, useNovelContext);
            },
          },
          h("label", { htmlFor: "anw-assistant-selection-custom-input" }, "自定义修改要求"),
          h("textarea", {
            id: "anw-assistant-selection-custom-input",
            value: customInstruction,
            maxLength: 2_000,
            rows: 2,
            autoFocus: true,
            placeholder: "例如：保持事实不变，改成更克制的第一人称表达",
            onChange: (event: { target: { value: string } }) => {
              setCustomInstruction(event.target.value);
            },
          }),
          h(
            "label",
            { className: "anw-assistant-selection-context-opt-in" },
            h("input", {
              type: "checkbox",
              checked: useNovelContext,
              onChange: (event: { target: { checked: boolean } }) => {
                setUseNovelContext(event.target.checked);
              },
            }),
            "参考全书资料（可能向已授权的向量模型发送本次选区和自定义指令）",
          ),
          h(
            "div",
            { className: "anw-assistant-selection-custom-actions" },
            h("span", null, `${customInstruction.length}/2000`),
            h(
              "button",
              { type: "button", onClick: () => controller.hideToolbar() },
              "取消",
            ),
            h(
              "button",
              { type: "submit", disabled: !customInstruction.trim() },
              "开始修改",
            ),
          ),
        )
        : null,
      h(
        "div",
        {
          id: "anw-assistant-selection-status",
          className: "anw-assistant-selection-status",
          "aria-live": "polite",
        },
        h("strong", null, state.fieldLabel ?? "当前字段"),
        h("span", null, `${state.selectedCharacters} 字`),
        state.message ? h("span", null, state.message) : null,
      ),
    );
    const portalContainer = portal?.getContainer();
    return portal && portalContainer
      ? portal.createPortal(toolbar, portalContainer)
      : toolbar;
  };
}
