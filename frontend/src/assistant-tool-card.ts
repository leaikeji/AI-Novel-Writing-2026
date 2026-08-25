import {
  ASSISTANT_SELECTION_OPERATIONS,
  type AssistantSelectionOperation,
} from "./assistant-selection-controller";
import {
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantEditableFieldContext,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import {
  AssistantSelectionRegistry,
  type SelectionInvalidReason,
  type SelectionRegistryRecord,
} from "./assistant-selection-registry";
import {
  AIEditTransactionManager,
  applySelectionOperation,
  type AIEditTransaction,
} from "./assistant-transactions";


export const ASSISTANT_PROPOSAL_MAX_TEXT_CHARACTERS = 100_000;
export const ASSISTANT_PROPOSAL_MAX_SERIALIZED_CHARACTERS = 120_000;
export const ASSISTANT_PROPOSAL_MAX_SUMMARY_CHARACTERS = 500;

const MAX_WARNING_COUNT = 20;
const MAX_WARNING_CHARACTERS = 300;
const ASSISTANT_PROPOSAL_TOOL_NAME = "novel_prepare_selection_edit";
const SAFE_REFERENCE_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const OPERATION_LABELS: Readonly<Record<AssistantSelectionOperation, string>> = {
  polish: "润色",
  rewrite: "改写",
  expand: "扩写",
  shorten: "缩写",
  dialogue: "增强对白",
  review: "检查问题",
  custom: "自定义",
};

const INVALID_REASON_LABELS: Readonly<Record<SelectionInvalidReason, string>> = {
  "not-found": "选区不存在或已经被清理",
  expired: "选区已经过期，请重新框选",
  "agent-mismatch": "当前 Agent 已变化，只能复制候选",
  "novel-mismatch": "当前作品已变化，只能复制候选",
  "document-mismatch": "当前文档已变化，只能复制候选",
  "field-mismatch": "当前字段已变化，只能复制候选",
  "context-revision-mismatch": "页面内容版本已变化，只能复制候选",
  "session-unbound": "选区没有绑定本次会话，只能复制候选",
  "session-mismatch": "候选来自另一会话，只能复制候选",
  "source-value-changed": "字段内容已变化，只能复制候选",
};


interface ToolRenderExtensionPoint {
  (
    pluginId: string,
    toolName: string,
    renderer: (props: QwenPawToolRenderProps) => unknown,
  ): QwenPawDisposable;
}


interface AssistantToolReactRuntime {
  createElement: (type: unknown, props?: unknown, ...children: unknown[]) => unknown;
  useState: <T>(initial: T | (() => T)) => [T, (next: T | ((value: T) => T)) => void];
  useRef: <T>(initial: T) => { current: T };
  useEffect: (
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ) => void;
}


export interface AssistantToolCardModel {
  valid: boolean;
  selectionId?: string;
  operation?: AssistantSelectionOperation;
  operationLabel: string;
  summary: string;
  replacementText: string;
  replacementCharacterCount: number;
  warnings: string[];
  sessionId?: string;
  messageId?: string;
  error?: string;
}


export type AssistantProposalPhase =
  | "checking"
  | "ready"
  | "conflict"
  | "applied"
  | "undone"
  | "discarded"
  | "invalid"
  | "failed";


export interface AssistantProposalCardState {
  phase: AssistantProposalPhase;
  applicable: boolean;
  canUndo: boolean;
  statusMessage: string;
  fieldId?: string;
  fieldLabel?: string;
  originalCharacterCount?: number;
  persistence?: "autosave" | "explicit-save";
}


export interface AssistantProposalCoordinatorOptions {
  runtime: NovelAssistantContextRuntime;
  registry: AssistantSelectionRegistry;
  transactions: AIEditTransactionManager;
}


export interface AssistantToolRendererOptions {
  React: AssistantToolReactRuntime;
  coordinator: AssistantProposalCoordinator;
  copyText: (text: string) => void | Promise<void>;
  getCurrentSessionId?: () => string | null | undefined;
  onCopyError?: (error: unknown) => void;
  onStateChange?: (state: AssistantProposalCardState) => void;
}


export interface AssistantToolCardRegistrationOptions
  extends AssistantToolRendererOptions {
  pluginId: string;
  toolName: string;
  toolRender: ToolRenderExtensionPoint;
}


interface ResolvedProposal {
  context: AssistantEditableFieldContext;
  record: SelectionRegistryRecord;
}


type ProposalResolution =
  | { ok: true; value: ResolvedProposal }
  | { ok: false; message: string };


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}


function parseToolResult(
  value: unknown,
  depth = 0,
): Record<string, unknown> | undefined {
  if (depth > 5) return undefined;
  if (typeof value === "string") {
    if (value.length > ASSISTANT_PROPOSAL_MAX_SERIALIZED_CHARACTERS) {
      return undefined;
    }
    try {
      return parseToolResult(JSON.parse(value), depth + 1);
    } catch {
      return undefined;
    }
  }
  if (Array.isArray(value)) {
    if (value.length > 20) return undefined;
    for (let index = value.length - 1; index >= 0; index -= 1) {
      const parsed = parseToolResult(value[index], depth + 1);
      if (parsed) return parsed;
    }
    return undefined;
  }
  if (!isRecord(value)) return undefined;
  if (
    Object.prototype.hasOwnProperty.call(value, "schema_version")
    || Object.prototype.hasOwnProperty.call(value, "selection_id")
  ) {
    return value;
  }
  for (const key of ["output", "result", "content", "text", "data", "value"] as const) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
    const parsed = parseToolResult(value[key], depth + 1);
    if (parsed) return parsed;
  }
  return undefined;
}


function publicToolMessageBindings(props: QwenPawToolRenderProps): {
  result: unknown;
  messageId?: string;
} {
  if (props.result !== undefined) {
    return { result: props.result, messageId: props.messageId };
  }
  if (!isRecord(props.data)) return { result: undefined };
  const messageId = safeReference(props.data.id);
  if (!Array.isArray(props.data.content)) {
    return { result: undefined, messageId };
  }
  for (let index = props.data.content.length - 1; index >= 0; index -= 1) {
    const block = props.data.content[index];
    if (!isRecord(block) || !isRecord(block.data)) continue;
    if (
      block.data.name === ASSISTANT_PROPOSAL_TOOL_NAME
      && Object.prototype.hasOwnProperty.call(block.data, "output")
    ) {
      return { result: block.data.output, messageId };
    }
  }
  return { result: undefined, messageId };
}


function safeReference(value: unknown): string | undefined {
  return typeof value === "string" && SAFE_REFERENCE_PATTERN.test(value)
    ? value
    : undefined;
}


function safeSelectionId(value: unknown): string | undefined {
  return typeof value === "string" && UUID_PATTERN.test(value)
    ? value
    : undefined;
}


function boundedString(value: unknown, maximum: number): string | undefined {
  return typeof value === "string" && value.length <= maximum
    ? value
    : undefined;
}


function characterCount(value: string): number {
  return Array.from(value).length;
}


function supportedOperation(value: unknown): AssistantSelectionOperation | undefined {
  return typeof value === "string"
    && ASSISTANT_SELECTION_OPERATIONS.includes(value as AssistantSelectionOperation)
    ? value as AssistantSelectionOperation
    : undefined;
}


function invalidState(message: string): AssistantProposalCardState {
  return {
    phase: "invalid",
    applicable: false,
    canUndo: false,
    statusMessage: message,
  };
}


function conflictState(
  message: string,
  current: Partial<AssistantProposalCardState> = {},
): AssistantProposalCardState {
  return {
    phase: "conflict",
    applicable: false,
    canUndo: false,
    statusMessage: message,
    fieldId: current.fieldId,
    fieldLabel: current.fieldLabel,
    originalCharacterCount: current.originalCharacterCount,
    persistence: current.persistence,
  };
}


function failedState(
  message: string,
  current: Partial<AssistantProposalCardState> = {},
): AssistantProposalCardState {
  return {
    phase: "failed",
    applicable: false,
    canUndo: false,
    statusMessage: message,
    fieldId: current.fieldId,
    fieldLabel: current.fieldLabel,
    originalCharacterCount: current.originalCharacterCount,
    persistence: current.persistence,
  };
}


function transactionMatches(
  transaction: AIEditTransaction | undefined,
  model: AssistantToolCardModel,
  context: AssistantEditableFieldContext,
): transaction is AIEditTransaction {
  return Boolean(
    transaction
    && transaction.selectionId === model.selectionId
    && transaction.agentId === context.agentId
    && transaction.sessionId === model.sessionId
    && transaction.novelId === context.novelId
    && transaction.documentId === context.documentId,
  );
}


export function createAssistantToolCardModel(
  props: QwenPawToolRenderProps,
  currentSessionId?: string,
): AssistantToolCardModel {
  const bindings = publicToolMessageBindings(props);
  const sessionId = safeReference(props.sessionId) ?? safeReference(currentSessionId);
  const messageId = safeReference(props.messageId) ?? bindings.messageId;
  const result = parseToolResult(bindings.result);
  if (!result) {
    return {
      valid: false,
      operationLabel: "未知操作",
      summary: "工具未返回可应用候选，页面内容没有修改。",
      replacementText: "",
      replacementCharacterCount: 0,
      warnings: [],
      sessionId,
      messageId,
      error: "结果不是对象",
    };
  }

  const replacementText = boundedString(
    result.replacement_text,
    ASSISTANT_PROPOSAL_MAX_TEXT_CHARACTERS,
  ) ?? "";
  const selectionId = safeSelectionId(result.selection_id);
  const operation = supportedOperation(result.operation);
  const summary = boundedString(
    result.short_summary,
    ASSISTANT_PROPOSAL_MAX_SUMMARY_CHARACTERS,
  ) ?? "AI 已生成一份候选文本。";
  const warnings = Array.isArray(result.warnings)
    ? result.warnings
      .slice(0, MAX_WARNING_COUNT)
      .map((item) => boundedString(item, MAX_WARNING_CHARACTERS))
      .filter((item): item is string => item !== undefined)
    : [];

  if (
    result.schema_version !== 1
    || !selectionId
    || !operation
    || !replacementText
  ) {
    return {
      valid: false,
      selectionId,
      operation,
      operationLabel: operation ? OPERATION_LABELS[operation] : "未知操作",
      summary: "工具结果缺少受支持的版本、选区、操作或替换文本。",
      replacementText,
      replacementCharacterCount: characterCount(replacementText),
      warnings,
      sessionId,
      messageId,
      error: "结果协议无效",
    };
  }

  return {
    valid: true,
    selectionId,
    operation,
    operationLabel: OPERATION_LABELS[operation],
    summary,
    replacementText,
    replacementCharacterCount: characterCount(replacementText),
    warnings,
    sessionId,
    messageId,
  };
}


/** Resolve a tool result back to the tab-local selection and controlled field. */
export class AssistantProposalCoordinator {
  private readonly runtime: NovelAssistantContextRuntime;
  private readonly registry: AssistantSelectionRegistry;
  private readonly transactions: AIEditTransactionManager;

  constructor(options: AssistantProposalCoordinatorOptions) {
    this.runtime = options.runtime;
    this.registry = options.registry;
    this.transactions = options.transactions;
  }

  currentSessionId(): string | undefined {
    const status = this.runtime.getStatus();
    return status.supportedAgent ? status.sessionId : undefined;
  }

  subscribe(listener: () => void): () => void {
    return this.runtime.subscribe(() => listener());
  }

  async inspect(model: AssistantToolCardModel): Promise<AssistantProposalCardState> {
    if (!model.valid) return invalidState(model.summary);
    let resolution: ProposalResolution;
    try {
      resolution = await this.resolve(model);
    } catch {
      return failedState("候选校验失败，未修改页面内容；仍可复制候选");
    }
    if (!resolution.ok) return conflictState(resolution.message);
    const { context, record } = resolution.value;
    const latest = this.transactions.latest(context.fieldId);
    return {
      phase: "ready",
      applicable: true,
      canUndo: transactionMatches(latest, model, context),
      statusMessage: "候选已校验，应用前还会再次检查当前字段",
      fieldId: context.fieldId,
      fieldLabel: context.adapter.label,
      originalCharacterCount: characterCount(record.text),
      persistence: context.adapter.persistence,
    };
  }

  async apply(
    model: AssistantToolCardModel,
    operation: "replace-selection" | "insert-after-selection",
  ): Promise<AssistantProposalCardState> {
    if (!model.valid) return invalidState(model.summary);
    let resolution: ProposalResolution;
    try {
      resolution = await this.resolve(model);
    } catch {
      return failedState("应用前校验失败，未修改页面内容；仍可复制候选");
    }
    if (!resolution.ok) return conflictState(resolution.message);
    const { context, record } = resolution.value;
    const fieldValue = context.adapter.getValue();
    const next = applySelectionOperation(
      fieldValue,
      {
        startUtf16: record.startUtf16,
        endUtf16: record.endUtf16,
        direction: record.direction,
      },
      model.replacementText,
      operation,
    );

    try {
      const applied = await this.transactions.apply({
        adapter: context.adapter,
        operation,
        nextValue: next.value,
        sourceValueSha256: record.sourceValueSha256,
        agentId: context.agentId,
        sessionId: model.sessionId,
        selectionId: record.selectionId,
        novelId: context.novelId,
        documentId: context.documentId,
        afterSelection: next.selection,
      });
      if (!applied.ok) {
        return conflictState(
          applied.reason === "source-conflict" || applied.reason === "concurrent-change"
            ? "字段内容已变化，只能复制候选"
            : "受控字段没有接受候选，未应用",
          {
            fieldId: context.fieldId,
            fieldLabel: context.adapter.label,
            originalCharacterCount: characterCount(record.text),
            persistence: context.adapter.persistence,
          },
        );
      }
      this.registry.delete(record.selectionId);
      return {
        phase: "applied",
        applicable: false,
        canUndo: true,
        statusMessage: applied.persistenceWarning
          ? context.adapter.persistence === "autosave"
            ? "已应用到恢复草稿，但自动保存请求失败；可撤销或手动保存"
            : `已应用到${context.adapter.label}草稿，但保存状态更新失败；可撤销`
          : context.adapter.persistence === "autosave"
            ? "已应用，正在自动保存"
            : `已应用到${context.adapter.label}草稿，尚未保存`,
        fieldId: context.fieldId,
        fieldLabel: context.adapter.label,
        originalCharacterCount: characterCount(record.text),
        persistence: context.adapter.persistence,
      };
    } catch {
      return conflictState("应用期间字段发生变化，未修改当前内容", {
        fieldId: context.fieldId,
        fieldLabel: context.adapter.label,
        originalCharacterCount: characterCount(record.text),
        persistence: context.adapter.persistence,
      });
    }
  }

  async undo(
    model: AssistantToolCardModel,
    current: AssistantProposalCardState,
  ): Promise<AssistantProposalCardState> {
    if (!model.valid || !current.fieldId) return invalidState(model.summary);
    const context = this.runtime.getEditableFieldContext(current.fieldId);
    if (!context) return conflictState("当前字段已经离开页面，不能撤销", current);
    const latest = this.transactions.latest(current.fieldId);
    if (!transactionMatches(latest, model, context)) {
      return conflictState("最近一次 AI 修改不属于这张卡片，不能撤销", current);
    }
    try {
      const result = await this.transactions.undo(context.adapter);
      if (!result.ok) {
        return conflictState(
          result.reason === "field-changed"
            ? "作者已继续修改当前字段，不能自动撤销"
            : "撤销失败，当前字段未被覆盖",
          current,
        );
      }
      return {
        ...current,
        phase: "undone",
        applicable: false,
        canUndo: false,
        statusMessage: result.persistenceWarning
          ? result.transaction.persistence === "autosave"
            ? "已撤销到恢复草稿，但自动保存请求失败；请手动确认保存"
            : `已撤销到${context.adapter.label}草稿，但保存状态更新失败`
          : result.transaction.persistence === "autosave"
            ? "已撤销 AI 修改，正在自动保存"
            : `已撤销到${context.adapter.label}草稿，尚未保存`,
      };
    } catch {
      return conflictState("撤销期间字段发生变化，当前内容未被覆盖", current);
    }
  }

  discard(
    model: AssistantToolCardModel,
    current: AssistantProposalCardState,
  ): AssistantProposalCardState {
    if (model.selectionId) this.registry.delete(model.selectionId);
    return {
      ...current,
      phase: "discarded",
      applicable: false,
      canUndo: false,
      statusMessage: "已放弃这份候选，未修改页面内容",
    };
  }

  private async resolve(model: AssistantToolCardModel): Promise<ProposalResolution> {
    if (!model.selectionId || !model.sessionId) {
      return { ok: false, message: "候选缺少选区或会话绑定，只能复制" };
    }
    const runtimeStatus = this.runtime.getStatus();
    if (
      !runtimeStatus.supportedAgent
      || runtimeStatus.selectedAgentId !== NOVEL_ASSISTANT_TARGET_AGENT_ID
      || runtimeStatus.sessionId !== model.sessionId
    ) {
      return { ok: false, message: "当前 Agent 或会话已变化，只能复制候选" };
    }
    const record = this.registry.get(model.selectionId);
    if (!record) {
      return { ok: false, message: "选区不存在或已经过期，请重新框选" };
    }
    const context = this.runtime.getEditableFieldContext(record.fieldId);
    if (!context) {
      return { ok: false, message: "目标字段已经离开页面，只能复制候选" };
    }
    const validation = await this.registry.validateForApply({
      selectionId: record.selectionId,
      sessionId: model.sessionId,
      agentId: context.agentId,
      novelId: context.novelId,
      documentId: context.documentId,
      fieldId: context.fieldId,
      contextRevision: context.contextRevision,
      fieldValue: context.adapter.getValue(),
    });
    if (!validation.ok) {
      return { ok: false, message: INVALID_REASON_LABELS[validation.reason] };
    }
    const value = context.adapter.getValue();
    if (
      record.startUtf16 < 0
      || record.endUtf16 > value.length
      || record.endUtf16 <= record.startUtf16
      || value.slice(record.startUtf16, record.endUtf16) !== record.text
    ) {
      return { ok: false, message: "原选区范围已经变化，只能复制候选" };
    }
    return { ok: true, value: { context, record } };
  }
}


function createInitialCardState(model: AssistantToolCardModel): AssistantProposalCardState {
  return model.valid
    ? {
      phase: "checking",
      applicable: false,
      canUndo: false,
      statusMessage: "正在校验选区与当前字段…",
    }
    : invalidState(model.summary);
}


export function createAssistantToolRenderer(
  options: AssistantToolRendererOptions,
): (props: QwenPawToolRenderProps) => unknown {
  const React = options.React;
  const h = React.createElement;

  function AssistantSelectionProposalCard(props: QwenPawToolRenderProps) {
    const currentSessionId = options.coordinator.currentSessionId()
      ?? options.getCurrentSessionId?.()
      ?? undefined;
    const model = createAssistantToolCardModel(
      props,
      currentSessionId,
    );
    const [state, setState] = React.useState<AssistantProposalCardState>(
      () => createInitialCardState(model),
    );
    const phaseRef = React.useRef(state.phase);
    const busyRef = React.useRef(false);
    phaseRef.current = state.phase;

    React.useEffect(() => {
      let mounted = true;
      if (!model.valid) {
        const invalid = invalidState(model.summary);
        phaseRef.current = invalid.phase;
        setState(invalid);
        return () => { mounted = false; };
      }

      // QwenPaw may mount the renderer while a tool call is still streaming,
      // then update the same component with the completed public result.  A
      // state value initialized from the empty result must be reset here;
      // otherwise a valid proposal keeps the stale "format unrecognized"
      // phase and can never be inspected or applied.
      const checking = createInitialCardState(model);
      phaseRef.current = checking.phase;
      setState(checking);
      const refresh = () => {
        if (
          !mounted
          || busyRef.current
          || !["checking", "ready", "conflict"].includes(phaseRef.current)
        ) {
          return;
        }
        void options.coordinator.inspect(model).then((next) => {
          if (!mounted || busyRef.current) return;
          setState(next);
          options.onStateChange?.(next);
        }).catch(() => {
          if (!mounted || busyRef.current) return;
          const next = failedState("候选审阅器校验异常，未修改页面内容；仍可复制候选");
          setState(next);
          options.onStateChange?.(next);
        });
      };
      const unsubscribe = options.coordinator.subscribe(refresh);
      refresh();
      return () => {
        mounted = false;
        unsubscribe();
      };
    }, [model.selectionId, model.sessionId, model.messageId]);

    const run = (action: () => Promise<AssistantProposalCardState>) => {
      busyRef.current = true;
      const checking: AssistantProposalCardState = {
        ...state,
        phase: "checking",
        applicable: false,
        canUndo: false,
        statusMessage: "正在重新校验并执行…",
      };
      setState(checking);
      void action().then((next) => {
        busyRef.current = false;
        setState(next);
        options.onStateChange?.(next);
      }).catch(() => {
        busyRef.current = false;
        const next = failedState(
          "候选审阅器操作异常，未执行新的页面写入；仍可复制候选",
          state,
        );
        setState(next);
        options.onStateChange?.(next);
      });
    };

    const handleCopy = () => {
      if (!model.replacementText) return;
      try {
        const result = options.copyText(model.replacementText);
        if (result && typeof (result as Promise<void>).catch === "function") {
          void (result as Promise<void>).catch((error) => {
            options.onCopyError?.(error);
          });
        }
      } catch (error) {
        options.onCopyError?.(error);
      }
    };

    const actionButton = (
      label: string,
      ariaLabel: string,
      onClick: () => void,
      disabled: boolean,
      className = "",
    ) => h(
      "button",
      {
        type: "button",
        className,
        onClick,
        disabled,
        "aria-label": ariaLabel,
      },
      label,
    );

    const copyOnly = !state.applicable;
    return h(
      "article",
      {
        className: `anw-assistant-review-editor is-${state.phase}${model.valid ? "" : " is-invalid"}`,
        role: "region",
        "aria-label": "AI 修改审阅器",
        "data-session-id": model.sessionId,
        "data-message-id": model.messageId,
        "data-proposal-phase": state.phase,
      },
      h(
        "header",
        null,
        h("div", null,
          h("strong", null, model.valid ? `${model.operationLabel} · ${state.fieldLabel ?? "选区"}` : "未生成可应用候选"),
          h("span", null, model.summary),
        ),
        h(
          "span",
          null,
          state.originalCharacterCount === undefined
            ? `${model.replacementCharacterCount} 字`
            : `${state.originalCharacterCount} → ${model.replacementCharacterCount} 字`,
        ),
      ),
      model.replacementText
        ? h(
          "pre",
          {
            className: "anw-assistant-review-text",
            tabIndex: 0,
            "aria-label": `AI 候选文本，${model.replacementCharacterCount} 字`,
          },
          model.replacementText,
        )
        : null,
      model.warnings.length > 0
        ? h(
          "ul",
          { className: "anw-assistant-review-warnings" },
          ...model.warnings.map((warning, index) => (
            h("li", { key: `${index}-${warning}` }, warning)
          )),
        )
        : null,
      h(
        "p",
        {
          className: `anw-assistant-review-status is-${state.phase}`,
          role: "status",
          "aria-live": "polite",
        },
        state.statusMessage,
      ),
      h(
        "footer",
        null,
        actionButton(
          "替换选中文字",
          "用 AI 候选替换选中文字",
          () => run(() => options.coordinator.apply(model, "replace-selection")),
          !state.applicable,
          "is-primary",
        ),
        actionButton(
          "插入到选区后",
          "将 AI 候选插入到选区后",
          () => run(() => options.coordinator.apply(model, "insert-after-selection")),
          !state.applicable,
        ),
        actionButton(
          "复制",
          "复制 AI 候选文本",
          handleCopy,
          !model.replacementText,
        ),
        actionButton(
          "撤销 AI 修改",
          "撤销当前字段最近一次 AI 修改",
          () => run(() => options.coordinator.undo(model, state)),
          !state.canUndo,
        ),
        actionButton(
          "放弃",
          "放弃这份 AI 候选",
          () => {
            const next = options.coordinator.discard(model, state);
            setState(next);
            options.onStateChange?.(next);
          },
          state.phase === "discarded" || state.phase === "checking",
          "is-quiet",
        ),
      ),
      h(
        "small",
        null,
        copyOnly
          ? "只读预览 · 冲突或过期时仍可复制"
          : "未写入页面 · 点击应用按钮后才会修改当前字段",
      ),
    );
  }

  return (props) => h(AssistantSelectionProposalCard, props);
}


export function registerAssistantToolCard(
  options: AssistantToolCardRegistrationOptions,
): QwenPawDisposable {
  return options.toolRender(
    options.pluginId,
    options.toolName,
    createAssistantToolRenderer(options),
  );
}
