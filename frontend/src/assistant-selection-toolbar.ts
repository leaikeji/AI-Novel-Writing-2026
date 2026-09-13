import {
  ASSISTANT_SELECTION_OPERATIONS,
  ASSISTANT_SELECTION_OPERATION_LABELS,
  type AssistantSelectionController,
  type AssistantSelectionOperation,
  type AssistantSelectionToolbarState,
} from "./assistant-selection-controller";
import type { QwenPawReactRuntime } from "./assistant-pane";
import { apiRequest } from "./api";
import {
  createSelectionQuickCapture,
  type SelectionCaptureInput,
  type SelectionCaptureTarget,
} from "./private-library";


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
  const SelectionQuickCapture = typeof window !== "undefined"
    && window.QwenPaw?.host?.antd
    ? createSelectionQuickCapture(React, window.QwenPaw.host.antd)
    : null;

  const sha256 = async (value: string): Promise<string> => {
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(value),
    );
    return [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  };

  return function AssistantSelectionToolbar(
    props: AssistantSelectionToolbarProps = {},
  ) {
    const [state, setState] = React.useState<AssistantSelectionToolbarState>(
      () => controller.getState(),
    );
    const [customInstruction, setCustomInstruction] = React.useState("");
    const [useNovelContext, setUseNovelContext] = React.useState(false);
    const [captureOpen, setCaptureOpen] = React.useState(false);
    const [captureTargets, setCaptureTargets] = React.useState<SelectionCaptureTarget[]>([]);
    const [captureNovelTitle, setCaptureNovelTitle] = React.useState("");
    const [captureError, setCaptureError] = React.useState("");
    const toolbarRef = React.useRef<HTMLElement | null>(null);

    React.useEffect(() => controller.subscribe(setState), []);
    React.useEffect(() => {
      const toolbar = toolbarRef.current;
      if (!state.visible || !toolbar) return;
      let active = true;
      let measuredWidth = 0;
      let measuredHeight = 0;
      const measure = () => {
        if (!active || toolbarRef.current !== toolbar) return;
        // Measure the whole border box: capture fields, asynchronous labels and
        // child-owned errors can grow without changing the frozen selection.
        const { width, height } = toolbar.getBoundingClientRect();
        if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
        if (width === measuredWidth && height === measuredHeight) return;
        measuredWidth = width;
        measuredHeight = height;
        controller.setToolbarSize(width, height);
      };
      measure();
      const observer = typeof ResizeObserver === "undefined"
        ? null : new ResizeObserver(measure);
      observer?.observe(toolbar, { box: "border-box" });
      return () => {
        active = false;
        observer?.disconnect();
      };
    }, [
      state.visible, state.selectionId, state.phase, state.message,
      captureOpen, captureTargets, captureNovelTitle, captureError,
    ]);
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
    const openCapture = () => {
      const record = controller.getActiveSelectionRecord();
      if (!record) return;
      setCaptureOpen(true);
      setCaptureError("");
      void Promise.all([
        apiRequest<{ items: Array<Record<string, unknown>> }>(
          `/private-library/assets?novel_id=${encodeURIComponent(record.novelId)}&limit=100`,
        ),
        apiRequest<{ title?: unknown }>(`/novels/${encodeURIComponent(record.novelId)}`),
      ]).then(([page, novel]) => {
        setCaptureNovelTitle(typeof novel.title === "string" ? novel.title : "当前作品");
        setCaptureTargets(page.items.flatMap((item) => {
          const category = item.asset_type;
          const scopeKind = item.scope_kind;
          if (
            typeof item.id !== "string"
            || typeof item.title !== "string"
            || !["vocabulary", "writing_style", "plot", "idea"].includes(String(category))
            || !["library", "novel"].includes(String(scopeKind))
          ) return [];
          return [{
            assetId: item.id,
            title: item.title,
            category: category as SelectionCaptureTarget["category"],
            scopeKind: scopeKind as SelectionCaptureTarget["scopeKind"],
            scopeNovelId: typeof item.scope_novel_id === "string"
              ? item.scope_novel_id : undefined,
          }];
        }));
      }).catch((reason: unknown) => {
        setCaptureError(reason instanceof Error ? reason.message : "读取私有库目标失败");
      });
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
        SelectionQuickCapture ? h(
          "button",
          {
            type: "button",
            className: captureOpen ? "is-active" : "",
            disabled: state.phase === "capturing" || state.phase === "failed",
            onClick: openCapture,
          },
          "加入私有库",
        ) : null,
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
      captureOpen && SelectionQuickCapture && controller.getActiveSelectionRecord()
        ? h(SelectionQuickCapture, {
            selectedText: controller.getActiveSelectionRecord()!.text,
            activeNovel: {
              id: controller.getActiveSelectionRecord()!.novelId,
              title: captureNovelTitle || "当前作品",
            },
            targets: captureTargets,
            onCancel: () => setCaptureOpen(false),
            onSave: async (input: SelectionCaptureInput) => {
              const record = controller.getActiveSelectionRecord();
              if (!record) throw new Error("选区已失效，请重新选择。");
              await apiRequest("/private-library/captures", {
                method: "POST",
                body: JSON.stringify({
                  selection_id: record.selectionId,
                  selected_text: record.text,
                  selected_text_sha256: await sha256(record.text),
                  source_value_sha256: record.sourceValueSha256,
                  source_document_id: record.documentId,
                  field_id: record.fieldId,
                  category: input.category,
                  action: input.action,
                  destination: input.destination,
                  novel_id: input.novelId ?? null,
                  target_asset_id: input.targetAssetId ?? null,
                  operation_key: `selection-capture:${record.selectionId}`,
                }),
              });
              setCaptureOpen(false);
              controller.hideToolbar();
            },
          })
        : null,
      captureError ? h("p", { className: "anw-assistant-selection-error" }, captureError) : null,
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
