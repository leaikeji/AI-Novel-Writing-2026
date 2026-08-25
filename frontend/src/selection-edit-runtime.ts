import {
  apiErrorMessage,
  startCreativeGeneration,
  type StartCreativeGenerationPayload,
} from "./api";
import {
  NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
  type NovelEntityType,
} from "./assistant-context-schema";
import {
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantEditableFieldContext,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import type {
  AssistantSelectionEditorTaskRequest,
  AssistantSelectionEditorTaskStartResult,
  AssistantSelectionOperation,
} from "./assistant-selection-controller";
import {
  AssistantSelectionRegistry,
  type SelectionRegistryRecord,
} from "./assistant-selection-registry";
import {
  AIEditTransactionManager,
  applySelectionOperation,
} from "./assistant-transactions";
import type { QwenPawReactRuntime } from "./assistant-pane";
import type { AssistantReviewBridgeCandidate } from "./assistant-tool-card";
import {
  createSelectionEditReviewCoordinator,
  type SelectionEditReviewEffect,
  type SelectionEditReviewSessionState,
} from "./selection-edit-review";
import {
  createSelectionEditReviewSurface,
  selectionEditReviewEventForSurfaceAction,
  type SelectionEditReviewSurfaceAction,
} from "./selection-edit-review-surface";
import type { CreativeGenerationRecord } from "./types";


const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MULTILINE_FIELD_PATTERN = /(body|outline|description|personality|identity|idea|content|progress|background|plot|highlight|expectation|forbidden)/i;


export interface SelectionEditGenerationClient {
  start(
    payload: StartCreativeGenerationPayload,
    signal?: AbortSignal,
  ): Promise<CreativeGenerationRecord>;
}


export interface SelectionEditRuntimeOptions {
  readonly contextRuntime: NovelAssistantContextRuntime;
  readonly registry: AssistantSelectionRegistry;
  readonly transactions: AIEditTransactionManager;
  readonly generationClient?: SelectionEditGenerationClient;
  readonly copyText?: (text: string) => void | Promise<void>;
  readonly confirmExit?: (message: string) => boolean;
  readonly onAssistantFallback?: (
    selectionId: string,
    operation: AssistantSelectionOperation,
  ) => void;
  readonly uuid?: () => string;
  readonly sha256?: (value: string) => Promise<string>;
}


interface ActiveSelectionEdit {
  record: SelectionRegistryRecord;
  readonly scopeId: string;
  readonly adapter: AssistantEditableFieldContext["adapter"];
  readonly operation: AssistantSelectionOperation;
  readonly customInstruction?: string;
  jobId?: string;
  abort?: AbortController;
  generation: number;
}


export interface SelectionEditReviewHostProps {
  readonly fieldIds: string | readonly string[];
  readonly className?: string;
  readonly children?: unknown;
}


function defaultUuid(): string {
  return globalThis.crypto.randomUUID();
}


async function defaultSha256(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


function activeIdentity(state: SelectionEditReviewSessionState) {
  return state.phase === "idle" ? undefined : state.identity;
}


function selectionEntityType(fieldId: string): Exclude<
  NovelEntityType,
  "novel" | "volume"
> {
  if (fieldId.startsWith("chapter.")) return "document";
  if (fieldId.startsWith("character.") || fieldId.startsWith("outline.character.")) {
    return "character";
  }
  if (fieldId.startsWith("relationship.")) return "relationship";
  if (fieldId.startsWith("storyline.")) return "storyline";
  if (fieldId.startsWith("foreshadow.")) return "foreshadow";
  if (fieldId.startsWith("settings.")) return "setting";
  return "outline";
}


function strictJobError(job: CreativeGenerationRecord): string | null {
  if (job.kind !== "selection_edit") return "服务返回了错误的任务类型";
  if (job.execution_agent_id !== NOVEL_ASSISTANT_TARGET_AGENT_ID) {
    return "任务没有由 AI 小说作家执行";
  }
  if (!job.requested_model_id || !job.actual_model_id || !job.requested_provider_id || !job.actual_provider_id) {
    return "任务缺少 requested/actual 模型证据";
  }
  if (job.requested_model_id !== job.actual_model_id
    || job.requested_provider_id !== job.actual_provider_id) {
    return "任务请求模型与实际模型不一致";
  }
  if (job.state === "failed") return job.failure_message || "选区编辑任务失败";
  if (job.state !== "ready") return "选区编辑任务尚未完成";
  return null;
}


function fieldMode(fieldId: string, value: string): "single-line" | "multiline" {
  return value.includes("\n") || MULTILINE_FIELD_PATTERN.test(fieldId)
    ? "multiline"
    : "single-line";
}


function sameContext(
  context: AssistantEditableFieldContext | null,
  active: ActiveSelectionEdit,
): context is AssistantEditableFieldContext {
  const record = active.record;
  return Boolean(context
    && context.adapter === active.adapter
    && context.scopeId === active.scopeId
    && context.agentId === record.agentId
    && context.novelId === record.novelId
    && context.documentId === record.documentId
    && context.fieldId === record.fieldId
    && context.contextRevision === record.contextRevision);
}


export class SelectionEditRuntime {
  private readonly contextRuntime: NovelAssistantContextRuntime;
  private readonly registry: AssistantSelectionRegistry;
  private readonly transactions: AIEditTransactionManager;
  private readonly generationClient: SelectionEditGenerationClient;
  private readonly copyText?: SelectionEditRuntimeOptions["copyText"];
  private readonly confirmExit: NonNullable<SelectionEditRuntimeOptions["confirmExit"]>;
  private readonly onAssistantFallback?: SelectionEditRuntimeOptions["onAssistantFallback"];
  private readonly uuid: () => string;
  private readonly sha256: (value: string) => Promise<string>;
  private readonly coordinator = createSelectionEditReviewCoordinator();
  private active?: ActiveSelectionEdit;
  private disposed = false;

  constructor(options: SelectionEditRuntimeOptions) {
    this.contextRuntime = options.contextRuntime;
    this.registry = options.registry;
    this.transactions = options.transactions;
    this.generationClient = options.generationClient ?? {
      start: (payload, signal) => startCreativeGeneration(payload, signal),
    };
    this.copyText = options.copyText;
    this.confirmExit = options.confirmExit ?? ((message) => globalThis.confirm?.(message) ?? false);
    this.onAssistantFallback = options.onAssistantFallback;
    this.uuid = options.uuid ?? defaultUuid;
    this.sha256 = options.sha256 ?? defaultSha256;
  }

  getState(): SelectionEditReviewSessionState {
    return this.coordinator.getState();
  }

  subscribe(listener: (state: SelectionEditReviewSessionState) => void): () => void {
    this.assertActive();
    return this.coordinator.subscribe(listener);
  }

  async start(
    request: AssistantSelectionEditorTaskRequest,
  ): Promise<void | AssistantSelectionEditorTaskStartResult> {
    this.assertActive();
    const current = this.coordinator.getState();
    if (!["idle", "applied", "discarded"].includes(current.phase)) {
      throw new Error("当前审阅尚未结束，请先处理现有候选");
    }
    const context = this.contextRuntime.getEditableFieldContext(request.record.fieldId);
    const active: ActiveSelectionEdit = {
      record: request.record,
      scopeId: context?.scopeId ?? "",
      adapter: context?.adapter ?? request.record as never,
      operation: request.operation,
      customInstruction: request.customInstruction,
      generation: 0,
    };
    if (!context || !sameContext(context, active)) {
      throw new Error("选区上下文已经变化，请重新框选");
    }
    this.active?.abort?.abort();
    this.active = active;
    if (current.phase !== "idle") this.coordinator.dispatch({ type: "reset" });
    const prepared = this.coordinator.dispatch({
      type: "prepare",
      identity: {
        reviewSessionId: this.uuid(),
        selectionId: request.record.selectionId,
        operation: request.operation,
        baseText: request.record.text,
        target: {
          fieldId: request.record.fieldId,
          fieldLabel: request.fieldLabel,
          mode: fieldMode(request.record.fieldId, request.record.text),
        },
      },
    });
    if (!prepared.ok) throw new Error(prepared.message);
    return this.execute(active, false);
  }

  async openBridgeCandidate(candidate: AssistantReviewBridgeCandidate): Promise<void> {
    this.assertActive();
    if (candidate.schemaVersion !== 2 || !candidate.generationResult) {
      throw new Error("历史 V1 候选只能复制，不能恢复为严格 Diff 审阅");
    }
    const record = this.registry.get(candidate.selectionId);
    const context = record
      ? this.contextRuntime.getEditableFieldContext(record.fieldId)
      : null;
    if (!record || !context || record.delivery.kind !== "chat-session") {
      throw new Error("聊天候选的选区或会话绑定已经失效");
    }
    const active: ActiveSelectionEdit = {
      record,
      scopeId: context.scopeId,
      adapter: context.adapter,
      operation: candidate.operation,
      generation: 0,
    };
    if (!sameContext(context, active) || !await this.validateCurrent(active)) {
      throw new Error("聊天候选不再匹配当前字段");
    }
    const current = this.coordinator.getState();
    if (!["idle", "applied", "discarded"].includes(current.phase)) {
      throw new Error("当前审阅尚未结束，请先处理现有候选");
    }
    if (current.phase !== "idle") this.coordinator.dispatch({ type: "reset" });
    this.active?.abort?.abort();
    this.active = active;
    const prepared = this.coordinator.dispatch({
      type: "prepare",
      identity: {
        reviewSessionId: this.uuid(),
        selectionId: record.selectionId,
        operation: candidate.operation,
        baseText: record.text,
        target: {
          fieldId: record.fieldId,
          fieldLabel: candidate.fieldLabel || context.adapter.label,
          mode: fieldMode(record.fieldId, record.text),
        },
      },
    });
    if (!prepared.ok) throw new Error(prepared.message);
    this.coordinator.dispatch({ type: "generation-started" });
    const ready = this.coordinator.dispatch({
      type: "generation-ready",
      result: candidate.generationResult,
    });
    if (!ready.ok || ready.state.phase !== "reviewing") {
      throw new Error(ready.ok ? "聊天候选无法通过严格 Diff 校验" : ready.message);
    }
  }

  handleSurfaceAction(action: SelectionEditReviewSurfaceAction): void {
    this.assertActive();
    if (action.type === "copy-candidate") {
      if (!this.copyText) return;
      void Promise.resolve(this.copyText(action.candidateText)).catch(() => undefined);
      return;
    }
    if (action.type === "send-to-assistant") {
      const active = this.active;
      if (active) this.onAssistantFallback?.(active.record.selectionId, active.operation);
      return;
    }
    if (action.type === "cancel-waiting") this.active?.abort?.abort();
    const event = selectionEditReviewEventForSurfaceAction(action);
    if (!event) return;
    const result = this.coordinator.dispatch(event);
    if (!result.ok) {
      if (result.reason === "exit-confirmation-required"
        && this.confirmExit(result.message)) {
        this.coordinator.dispatch({ type: "confirm-exit" });
      }
      return;
    }
    if (action.type === "retry") {
      const active = this.active;
      if (active) void this.retry(active);
      return;
    }
    if (result.effect) void this.runEffect(result.effect);
  }

  focusSource(fieldId: string): void {
    const context = this.contextRuntime.getEditableFieldContext(fieldId);
    context?.adapter.focus();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.active?.abort?.abort();
    this.active = undefined;
    this.coordinator.dispose();
  }

  private async execute(
    active: ActiveSelectionEdit,
    forceNew: boolean,
  ): Promise<void | AssistantSelectionEditorTaskStartResult> {
    const generation = ++active.generation;
    active.abort?.abort();
    const abort = new AbortController();
    active.abort = abort;
    this.coordinator.dispatch({ type: "generation-started", jobId: active.jobId });
    try {
      const payload = await this.buildPayload(active, forceNew);
      const job = await this.generationClient.start(payload, abort.signal);
      if (!this.isCurrent(active, generation)) return job.id ? { jobId: job.id } : undefined;
      active.jobId = job.id;
      const bound = this.registry.bindToEditorTask({
        selectionId: active.record.selectionId,
        jobId: job.id,
        agentId: active.record.agentId,
        novelId: active.record.novelId,
        documentId: active.record.documentId,
        fieldId: active.record.fieldId,
        contextRevision: active.record.contextRevision,
      });
      if (!bound.ok) {
        this.coordinator.dispatch({ type: "conflict", message: "编辑任务与选区绑定已经失效。" });
        return { jobId: job.id };
      }
      active.record = bound.record;
      const jobError = strictJobError(job);
      if (jobError) {
        this.coordinator.dispatch({ type: "generation-failed", message: jobError });
        return { jobId: job.id };
      }
      if (job.novel_id !== active.record.novelId
        || (selectionEntityType(active.record.fieldId) === "document"
          && job.document_id !== active.record.documentId)
        || job.input_snapshot.selection_id !== active.record.selectionId) {
        this.coordinator.dispatch({ type: "conflict", message: "返回任务不属于当前作品、文档或选区。" });
        return { jobId: job.id };
      }
      const valid = await this.validateCurrent(active);
      if (!valid) {
        this.coordinator.dispatch({ type: "conflict", message: "生成期间字段或页面已经变化，原文未被覆盖。" });
        return { jobId: job.id };
      }
      this.coordinator.dispatch({ type: "generation-ready", result: job.output_json });
      return { jobId: job.id };
    } catch (reason) {
      if (!this.isCurrent(active, generation)) return active.jobId ? { jobId: active.jobId } : undefined;
      if (abort.signal.aborted || this.coordinator.getState().phase === "discarded") {
        return active.jobId ? { jobId: active.jobId } : undefined;
      }
      this.coordinator.dispatch({
        type: "generation-failed",
        message: apiErrorMessage(reason, "选区编辑任务失败"),
      });
      return active.jobId ? { jobId: active.jobId } : undefined;
    }
  }

  private async buildPayload(
    active: ActiveSelectionEdit,
    forceNew: boolean,
  ): Promise<StartCreativeGenerationPayload> {
    const context = this.contextRuntime.getEditableFieldContext(active.record.fieldId);
    if (!sameContext(context, active)) throw new Error("选区上下文已经变化");
    const record = active.record;
    const entityType = selectionEntityType(record.fieldId);
    const documentId = entityType === "document" ? context.envelope.document?.id ?? null : null;
    const entityId = entityType === "document"
      ? documentId
      : entityType === "setting"
        ? context.novelId
        : context.persistenceBaseline.kind === "none"
          ? null
          : context.envelope.entity?.id ?? null;
    const fieldValue = context.adapter.getValue();
    if (fieldValue.slice(record.startUtf16, record.endUtf16) !== record.text) {
      throw new Error("选区原文已经变化");
    }
    const selectionTextSha256 = await this.sha256(record.text);
    if (!sameContext(this.contextRuntime.getEditableFieldContext(record.fieldId), active)
      || context.adapter.getValue() !== fieldValue) {
      throw new Error("建立任务期间字段已经变化");
    }
    const inputSnapshot: Record<string, unknown> = {
      schema_version: 1,
      selection_id: record.selectionId,
      operation: active.operation,
      custom_instruction: active.operation === "custom" ? active.customInstruction : null,
      target: {
        novel_id: context.novelId,
        document_id: documentId,
        entity_type: entityType,
        entity_id: entityId,
        field_id: record.fieldId,
        field_label: context.adapter.label,
        persistence: context.adapter.persistence,
        context_revision: record.contextRevision,
      },
      base: {
        field_value_sha256: record.sourceValueSha256,
        persistence_version_kind: context.persistenceBaseline.kind,
        persistence_version: context.persistenceBaseline.version,
        start_utf16: record.startUtf16,
        end_utf16: record.endUtf16,
        selection_text: record.text,
        selection_text_sha256: selectionTextSha256,
        before: fieldValue.slice(
          Math.max(0, record.startUtf16 - NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS),
          record.startUtf16,
        ),
        after: fieldValue.slice(
          record.endUtf16,
          record.endUtf16 + NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
        ),
      },
    };
    return {
      scope_type: entityType === "document" ? "document" : "novel",
      scope_id: entityType === "document" ? String(documentId) : context.novelId,
      kind: "selection_edit",
      input_snapshot: inputSnapshot,
      novel_id: context.novelId,
      document_id: documentId,
      target_character_count: null,
      force_new: forceNew,
    };
  }

  private async validateCurrent(active: ActiveSelectionEdit): Promise<boolean> {
    const context = this.contextRuntime.getEditableFieldContext(active.record.fieldId);
    if (!sameContext(context, active)) return false;
    if (context.adapter.getValue().slice(
      active.record.startUtf16,
      active.record.endUtf16,
    ) !== active.record.text) return false;
    const common = {
      selectionId: active.record.selectionId,
      agentId: active.record.agentId,
      novelId: active.record.novelId,
      documentId: active.record.documentId,
      fieldId: active.record.fieldId,
      contextRevision: active.record.contextRevision,
      fieldValue: context.adapter.getValue(),
    };
    const delivery = active.record.delivery;
    const validation = delivery.kind === "editor-task"
      ? await this.registry.validateForEditorTaskApply({ ...common, jobId: delivery.jobId })
      : delivery.kind === "chat-session"
        ? await this.registry.validateForApply({ ...common, sessionId: delivery.sessionId })
        : { ok: false as const, reason: "job-unbound" as const };
    return validation.ok
      && sameContext(this.contextRuntime.getEditableFieldContext(active.record.fieldId), active);
  }

  private async runEffect(effect: SelectionEditReviewEffect): Promise<void> {
    const active = this.active;
    const effectSelectionId = effect.type === "apply"
      ? effect.request.selectionId
      : effect.selectionId;
    if (!active || effectSelectionId !== active.record.selectionId) return;
    if (effect.type === "undo") {
      const context = this.contextRuntime.getEditableFieldContext(effect.fieldId);
      if (!context || context.adapter !== active.adapter) {
        this.coordinator.dispatch({ type: "undo-failed", message: "原字段已经离开，无法撤销。" });
        return;
      }
      const undone = await this.transactions.undo(context.adapter);
      this.coordinator.dispatch(undone.ok
        ? { type: "undo-succeeded", message: undone.persistenceWarning
          ? "已撤销本次 AI 修改；保存调度需要稍后重试。"
          : "已撤销整次 AI 修改。" }
        : { type: "undo-failed", message: "字段已继续编辑，无法安全撤销。" });
      return;
    }
    if (!await this.validateCurrent(active)) {
      this.coordinator.dispatch({ type: "apply-conflict", message: "应用前字段或页面已经变化，原文未被覆盖。" });
      return;
    }
    const context = this.contextRuntime.getEditableFieldContext(active.record.fieldId);
    if (!sameContext(context, active)) {
      this.coordinator.dispatch({ type: "apply-conflict", message: "应用前编辑目标已经变化。" });
      return;
    }
    const next = applySelectionOperation(
      context.adapter.getValue(),
      {
        startUtf16: active.record.startUtf16,
        endUtf16: active.record.endUtf16,
        direction: active.record.direction,
      },
      effect.request.replacementText,
      "replace-selection",
    );
    const applied = await this.transactions.apply({
      adapter: context.adapter,
      operation: "replace-selection",
      nextValue: next.value,
      sourceValueSha256: active.record.sourceValueSha256,
      agentId: active.record.agentId,
      selectionId: active.record.selectionId,
      novelId: active.record.novelId,
      documentId: selectionEntityType(active.record.fieldId) === "document"
        ? active.record.documentId
        : undefined,
      afterSelection: next.selection,
    });
    this.coordinator.dispatch(applied.ok
      ? {
        type: "apply-succeeded",
        message: applied.persistenceWarning
          ? "AI 修改已应用；保存调度失败，请保留当前页面并重试保存。"
          : context.adapter.persistence === "autosave"
            ? "AI 修改已应用，正在按原流程自动保存。"
            : "AI 修改已应用到草稿，请使用原保存按钮持久化。",
      }
      : { type: "apply-conflict", message: "字段在应用期间发生变化，未完成写回。" });
  }

  private async retry(active: ActiveSelectionEdit): Promise<void> {
    if (active.record.delivery.kind === "editor-task") {
      this.coordinator.dispatch({
        type: "generation-failed",
        message: "当前候选已形成独立审计任务；请重新框选后再次生成。",
        retryable: false,
      });
      return;
    }
    await this.execute(active, true);
  }

  private isCurrent(active: ActiveSelectionEdit, generation: number): boolean {
    return this.active === active && active.generation === generation && !this.disposed;
  }

  private assertActive(): void {
    if (this.disposed) throw new Error("selection edit runtime is disposed");
  }
}


export function createSelectionEditReviewHost(
  React: QwenPawReactRuntime,
  runtime: SelectionEditRuntime,
): (props: SelectionEditReviewHostProps) => unknown {
  const h = React.createElement;
  const Surface = createSelectionEditReviewSurface(React);
  return function SelectionEditReviewHost(props: SelectionEditReviewHostProps): unknown {
    const [state, setState] = React.useState(() => runtime.getState());
    React.useEffect(() => runtime.subscribe(setState), []);
    const identity = activeIdentity(state);
    const fieldIds = typeof props.fieldIds === "string" ? [props.fieldIds] : props.fieldIds;
    const active = Boolean(identity && fieldIds.includes(identity.target.fieldId)
      && state.phase !== "discarded");
    return h(
      "div",
      {
        className: [
          "anw-selection-edit-host",
          active ? "is-reviewing" : "is-editing",
          props.className ?? "",
        ].filter(Boolean).join(" "),
        "data-selection-edit-host": fieldIds.join(" "),
      },
      active
        ? h(Surface, {
          state,
          onAction: (action: SelectionEditReviewSurfaceAction) => runtime.handleSurfaceAction(action),
          onReturnFocus: (target: { fieldId: string }) => runtime.focusSource(target.fieldId),
        })
        : props.children,
    );
  };
}
