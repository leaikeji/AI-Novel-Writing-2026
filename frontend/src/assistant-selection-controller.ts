import {
  NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
  NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS,
  type NovelAssistantSelectionSnapshot,
} from "./assistant-context-schema";
import {
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantEditableFieldContext,
  type AssistantContextRuntimeStatus,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import {
  resolveSelectionToolbarPlacement,
  type GeometryRect,
  type SelectionToolbarPlacement,
} from "./assistant-selection-geometry";
import {
  AssistantSelectionRegistry,
  type SelectionRegistryRecord,
} from "./assistant-selection-registry";
import type { AssistantSuggestionRegistry } from "./assistant-suggestions";
import type { SelectionSnapshot } from "./assistant-fields";


export const ASSISTANT_SELECTION_OPERATIONS = [
  "polish",
  "rewrite",
  "expand",
  "shorten",
  "dialogue",
  "review",
  "custom",
] as const;


export type AssistantSelectionOperation =
  typeof ASSISTANT_SELECTION_OPERATIONS[number];


export const ASSISTANT_SELECTION_OPERATION_LABELS: Readonly<
  Record<AssistantSelectionOperation, string>
> = Object.freeze({
  polish: "润色",
  rewrite: "改写",
  expand: "扩写",
  shorten: "缩写",
  dialogue: "增强对白",
  review: "检查问题",
  custom: "自定义",
});


export const ASSISTANT_SELECTION_OPERATION_COMMANDS: Readonly<
  Record<AssistantSelectionOperation, string>
> = Object.freeze({
  polish: "/polish-selection",
  rewrite: "/rewrite-selection",
  expand: "/expand-selection",
  shorten: "/shorten-selection",
  dialogue: "/dialogue-selection",
  review: "/review-selection",
  custom: "/custom-selection",
});


export type AssistantSelectionPhase =
  | "idle"
  | "capturing"
  | "ready"
  | "customizing"
  | "starting"
  | "suggested"
  | "sent"
  | "invalid"
  | "failed";


export interface AssistantSelectionToolbarState {
  readonly phase: AssistantSelectionPhase;
  readonly visible: boolean;
  readonly selectionId?: string;
  readonly fieldId?: string;
  readonly fieldLabel?: string;
  readonly selectedCharacters: number;
  readonly selectedPreview?: string;
  readonly operation?: AssistantSelectionOperation;
  readonly message?: string;
  readonly placement?: SelectionToolbarPlacement;
}


export type AssistantSelectionToolbarListener = (
  state: AssistantSelectionToolbarState,
) => void;


export interface AssistantSelectionAnchor {
  readonly isConnected?: boolean;
  readonly tagName?: string;
  readonly isContentEditable?: boolean;
  readonly scrollLeft?: number;
  readonly scrollTop?: number;
  readonly scrollWidth?: number;
  readonly clientWidth?: number;
  getBoundingClientRect(): {
    left: number;
    top: number;
    width: number;
    height: number;
  };
  closest?(selector: string): unknown;
}


export interface AssistantSelectionEventTarget {
  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | AddEventListenerOptions,
  ): void;
  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | EventListenerOptions,
  ): void;
}


export interface AssistantSelectionControllerOptions {
  runtime: NovelAssistantContextRuntime;
  registry: AssistantSelectionRegistry;
  suggestions: AssistantSuggestionRegistry;
  onStartEditorTask?: (
    request: AssistantSelectionEditorTaskRequest,
  ) => void | AssistantSelectionEditorTaskStartResult | Promise<
    void | AssistantSelectionEditorTaskStartResult
  >;
  documentTarget?: AssistantSelectionEventTarget | null;
  windowTarget?: AssistantSelectionEventTarget | null;
  getViewportRect?: () => GeometryRect;
  getVisualViewportScale?: () => number;
  getDevicePixelRatio?: () => number;
  now?: () => number;
}


export interface AssistantSelectionEditorTaskRequest {
  readonly record: SelectionRegistryRecord;
  readonly fieldLabel: string;
  readonly operation: AssistantSelectionOperation;
  readonly customInstruction?: string;
  readonly useNovelContext?: boolean;
}


export interface AssistantSelectionEditorTaskStartResult {
  readonly jobId: string;
}


export interface AssistantSelectionSendBinding {
  selectionId: string;
  sessionId: string;
  agentId: string;
  novelId: string;
  documentId: string;
  fieldId: string;
  contextRevision: number;
}


interface ActiveSelection {
  record: SelectionRegistryRecord;
  readonly adapter: AssistantEditableFieldContext["adapter"];
  readonly scopeId: string;
  readonly fieldLabel: string;
  anchor?: AssistantSelectionAnchor;
  operation?: AssistantSelectionOperation;
}


const TOOLBAR_DEFAULT_SIZE = Object.freeze({ width: 636, height: 52 });
const TOOLBAR_SELECTOR = "[data-assistant-selection-toolbar]";
const ASSISTANT_PANE_SELECTOR = ".anw-assistant-pane";
const SELECTION_EDIT_HOST_SELECTOR = "[data-selection-edit-host]";


function defaultViewportRect(): GeometryRect {
  const visual = typeof window !== "undefined" ? window.visualViewport : null;
  // The workbench is rendered below QwenPaw's fixed 56px host header.  Treat
  // that occupied strip as outside the usable placement viewport so a tall
  // editor cannot pin the field-anchored toolbar over the host navigation.
  const hostHeaderInset = 56;
  const visualTop = visual?.offsetTop ?? 0;
  const visualHeight = visual?.height ?? (typeof window !== "undefined" ? window.innerHeight : 1);
  return {
    left: visual?.offsetLeft ?? 0,
    top: visualTop + hostHeaderInset,
    width: visual?.width ?? (typeof window !== "undefined" ? window.innerWidth : 1),
    height: Math.max(1, visualHeight - hostHeaderInset),
  };
}


function freezeState(
  state: AssistantSelectionToolbarState,
): AssistantSelectionToolbarState {
  return Object.freeze({ ...state });
}


function idleState(): AssistantSelectionToolbarState {
  return freezeState({
    phase: "idle",
    visible: false,
    selectedCharacters: 0,
  });
}


function sameRange(
  left: SelectionSnapshot,
  right: SelectionSnapshot,
): boolean {
  return left.startUtf16 === right.startUtf16
    && left.endUtf16 === right.endUtf16
    && left.direction === right.direction
    && left.text === right.text;
}


function selectionPreview(value: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length <= 24 ? compact : `${compact.slice(0, 24)}…`;
}


function isToolbarEventTarget(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Pick<AssistantSelectionAnchor, "closest">;
  return Boolean(candidate.closest?.(TOOLBAR_SELECTOR));
}


function isAssistantPaneEventTarget(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Pick<AssistantSelectionAnchor, "closest">;
  return Boolean(candidate.closest?.(ASSISTANT_PANE_SELECTOR));
}


function sharesSelectionEditHost(left: unknown, right: unknown): boolean {
  if (!left || typeof left !== "object" || !right || typeof right !== "object") return false;
  const leftHost = (left as Pick<AssistantSelectionAnchor, "closest">)
    .closest?.(SELECTION_EDIT_HOST_SELECTOR);
  const rightHost = (right as Pick<AssistantSelectionAnchor, "closest">)
    .closest?.(SELECTION_EDIT_HOST_SELECTOR);
  return Boolean(leftHost && leftHost === rightHost);
}


function isTextSelectionAnchor(value: unknown): value is AssistantSelectionAnchor {
  if (!value || typeof value !== "object") return false;
  const candidate = value as AssistantSelectionAnchor;
  if (typeof candidate.getBoundingClientRect !== "function") return false;
  if (isToolbarEventTarget(candidate)) return false;
  const tagName = candidate.tagName?.toUpperCase();
  return tagName === "INPUT"
    || tagName === "TEXTAREA"
    || candidate.isContentEditable === true;
}


function buildSelectionSuggestion(
  _record: SelectionRegistryRecord,
  _fieldLabel: string,
  operation: AssistantSelectionOperation,
): QwenPawSuggestionItem {
  const label = ASSISTANT_SELECTION_OPERATION_LABELS[operation];
  const command = ASSISTANT_SELECTION_OPERATION_COMMANDS[operation];
  return {
    // QwenPaw's public sender suggestions are slash-triggered.  Keep the
    // filter token ASCII/stable (matching native commands and skills) and put
    // the Chinese action label after it.  The selected preview stays on the
    // field toolbar instead of making the native menu item oversized.
    label: `${command} · ${label}选区`,
    // Sender suggestion values are slash-command tokens, not arbitrary prompt
    // bodies.  The selected text/UUID travels separately in the leased
    // context_ref, while this short token carries only the user's operation.
    value: command.slice(1),
  };
}


function recordSnapshot(
  record: SelectionRegistryRecord,
  fieldValue: string,
): NovelAssistantSelectionSnapshot {
  return {
    id: record.selectionId,
    fieldId: record.fieldId,
    text: record.text,
    startUtf16: record.startUtf16,
    endUtf16: record.endUtf16,
    direction: record.direction,
    before: fieldValue.slice(
      Math.max(0, record.startUtf16 - NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS),
      record.startUtf16,
    ),
    after: fieldValue.slice(
      record.endUtf16,
      record.endUtf16 + NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
    ),
    sourceValueSha256: record.sourceValueSha256,
    contextRevision: record.contextRevision,
    createdAt: new Date(record.createdAtMs).toISOString(),
    expiresAt: new Date(record.expiresAtMs).toISOString(),
  };
}


function scopeMatches(
  context: AssistantEditableFieldContext,
  record: SelectionRegistryRecord,
): boolean {
  return context.agentId === record.agentId
    && context.novelId === record.novelId
    && context.documentId === record.documentId
    && context.fieldId === record.fieldId
    && context.contextRevision === record.contextRevision;
}


/**
 * Tab-local selection coordinator. It freezes a controlled-field selection,
 * starts the project-owned editor task in one click, and retains the public
 * slash suggestion path only when the author explicitly chooses the fallback.
 * It never writes a field and never writes to the Clipboard.
 */
export class AssistantSelectionController {
  private readonly listeners = new Set<AssistantSelectionToolbarListener>();
  private readonly runtime: NovelAssistantContextRuntime;
  private readonly registry: AssistantSelectionRegistry;
  private readonly suggestions: AssistantSuggestionRegistry;
  private readonly onStartEditorTask?: AssistantSelectionControllerOptions["onStartEditorTask"];
  private readonly documentTarget: AssistantSelectionEventTarget | null;
  private readonly windowTarget: AssistantSelectionEventTarget | null;
  private readonly getViewportRect: () => GeometryRect;
  private readonly getVisualViewportScale: () => number;
  private readonly getDevicePixelRatio: () => number;
  private readonly now: () => number;
  private state = idleState();
  private active: ActiveSelection | undefined;
  private toolbarSize: { width: number; height: number } = TOOLBAR_DEFAULT_SIZE;
  private captureGeneration = 0;
  private composing = false;
  private started = false;
  private unsubscribeRuntime: (() => void) | null = null;
  private lastRuntimeStatus: AssistantContextRuntimeStatus | null = null;

  constructor(options: AssistantSelectionControllerOptions) {
    this.runtime = options.runtime;
    this.registry = options.registry;
    this.suggestions = options.suggestions;
    this.onStartEditorTask = options.onStartEditorTask;
    this.documentTarget = options.documentTarget === undefined
      ? (typeof document !== "undefined" ? document : null)
      : options.documentTarget;
    this.windowTarget = options.windowTarget === undefined
      ? (typeof window !== "undefined" ? window : null)
      : options.windowTarget;
    this.getViewportRect = options.getViewportRect ?? defaultViewportRect;
    this.getVisualViewportScale = options.getVisualViewportScale
      ?? (() => typeof window !== "undefined" ? window.visualViewport?.scale ?? 1 : 1);
    this.getDevicePixelRatio = options.getDevicePixelRatio
      ?? (() => typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1);
    this.now = options.now ?? Date.now;
  }

  start(): () => void {
    if (this.started) return () => this.stop();
    this.started = true;
    this.lastRuntimeStatus = this.runtime.getStatus();
    this.unsubscribeRuntime = this.runtime.subscribe((status) => this.reconcile(status));
    this.documentTarget?.addEventListener("mouseup", this.onSelectionEvent, true);
    this.documentTarget?.addEventListener("keyup", this.onSelectionEvent, true);
    this.documentTarget?.addEventListener("select", this.onSelectionEvent, true);
    this.documentTarget?.addEventListener("focusin", this.onFocusIn, true);
    this.documentTarget?.addEventListener("compositionstart", this.onCompositionStart, true);
    this.documentTarget?.addEventListener("compositionend", this.onCompositionEnd, true);
    this.documentTarget?.addEventListener("scroll", this.onGeometryChange, true);
    this.windowTarget?.addEventListener("resize", this.onGeometryChange);
    return () => this.stop();
  }

  /**
   * Temporarily detach browser/runtime listeners without destroying a selection
   * that has already been bound to an in-flight native-chat request.
   *
   * QwenPaw may remount a wrapped chat route while it appends streaming/tool
   * messages.  Treating that host lifecycle event as a real route exit used to
   * clear the registry before the tool card could resolve the returned
   * selection_id.  The route wrapper uses suspend() for component cleanup and
   * calls stop() explicitly only after the workbench route is actually gone.
   */
  suspend(): void {
    if (!this.started) return;
    this.started = false;
    this.documentTarget?.removeEventListener("mouseup", this.onSelectionEvent, true);
    this.documentTarget?.removeEventListener("keyup", this.onSelectionEvent, true);
    this.documentTarget?.removeEventListener("select", this.onSelectionEvent, true);
    this.documentTarget?.removeEventListener("focusin", this.onFocusIn, true);
    this.documentTarget?.removeEventListener("compositionstart", this.onCompositionStart, true);
    this.documentTarget?.removeEventListener("compositionend", this.onCompositionEnd, true);
    this.documentTarget?.removeEventListener("scroll", this.onGeometryChange, true);
    this.windowTarget?.removeEventListener("resize", this.onGeometryChange);
    this.unsubscribeRuntime?.();
    this.unsubscribeRuntime = null;
    this.captureGeneration += 1;
  }

  stop(): void {
    this.suspend();
    this.removeActiveSuggestion();
    this.active = undefined;
    this.registry.clear();
    this.publish(idleState());
  }

  getState(): AssistantSelectionToolbarState {
    return this.state;
  }

  subscribe(listener: AssistantSelectionToolbarListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async capture(anchor?: AssistantSelectionAnchor): Promise<boolean> {
    if (this.composing) return false;
    const initial = this.runtime.getEditableFieldContext();
    if (!initial) return false;
    const selection = initial.adapter.getSelection();
    if (!selection || selection.endUtf16 <= selection.startUtf16 || !selection.text) {
      this.cancelActiveSelection();
      return false;
    }
    if (selection.text.length > NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS) {
      this.publish(freezeState({
        phase: "failed",
        visible: true,
        fieldId: initial.fieldId,
        fieldLabel: initial.adapter.label,
        selectedCharacters: selection.text.length,
        message: `选区超过 ${NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS} 字，请缩小范围`,
        placement: anchor ? this.resolvePlacement(anchor) : undefined,
      }));
      return false;
    }

    const generation = ++this.captureGeneration;
    const initialRevision = initial.contextRevision;
    const expectedRevision = initialRevision + 1;
    const fieldValue = initial.adapter.getValue();
    this.publish(freezeState({
      phase: "capturing",
      visible: true,
      fieldId: initial.fieldId,
      fieldLabel: initial.adapter.label,
      selectedCharacters: selection.text.length,
      selectedPreview: selectionPreview(selection.text),
      message: "正在建立安全选区…",
      placement: anchor ? this.resolvePlacement(anchor) : undefined,
    }));

    let record: SelectionRegistryRecord;
    try {
      record = await this.registry.create({
        agentId: initial.agentId,
        novelId: initial.novelId,
        documentId: initial.documentId,
        fieldId: initial.fieldId,
        contextRevision: expectedRevision,
        fieldValue,
        startUtf16: selection.startUtf16,
        endUtf16: selection.endUtf16,
        direction: selection.direction,
      });
    } catch (reason) {
      if (generation !== this.captureGeneration) return false;
      this.publish(freezeState({
        phase: "failed",
        visible: true,
        fieldId: initial.fieldId,
        fieldLabel: initial.adapter.label,
        selectedCharacters: selection.text.length,
        selectedPreview: selectionPreview(selection.text),
        message: reason instanceof Error ? reason.message : "选区建立失败",
        placement: anchor ? this.resolvePlacement(anchor) : undefined,
      }));
      return false;
    }

    const latest = this.runtime.getEditableFieldContext(initial.fieldId);
    const latestSelection = latest?.adapter.getSelection();
    if (
      generation !== this.captureGeneration
      || !latest
      || latest.adapter !== initial.adapter
      || latest.scopeId !== initial.scopeId
      || latest.contextRevision !== initialRevision
      || latest.adapter.getValue() !== fieldValue
      || !latestSelection
      || !sameRange(selection, latestSelection)
    ) {
      this.registry.delete(record.selectionId);
      return false;
    }

    this.runtime.setActiveSelection(recordSnapshot(record, fieldValue));
    const committed = this.runtime.getEditableFieldContext(initial.fieldId);
    if (
      !committed
      || committed.adapter !== initial.adapter
      || committed.scopeId !== initial.scopeId
      || !scopeMatches(committed, record)
    ) {
      this.registry.delete(record.selectionId);
      return false;
    }

    this.removeActiveSuggestion();
    this.active = {
      record,
      adapter: initial.adapter,
      scopeId: initial.scopeId,
      fieldLabel: initial.adapter.label,
      anchor,
    };
    this.publish(this.readyState(this.active, "请选择操作"));
    return true;
  }

  selectOperation(operation: AssistantSelectionOperation): boolean {
    if (!ASSISTANT_SELECTION_OPERATIONS.includes(operation)) return false;
    const active = this.validActive();
    if (!active) return false;
    active.operation = operation;
    if (operation === "custom") {
      this.publish(freezeState({
        ...this.readyState(active, "输入本次修改要求（最多 2000 字）"),
        phase: "customizing",
        operation,
      }));
      return true;
    }
    this.startEditorTask(active, operation);
    return true;
  }

  submitCustomInstruction(instruction: string, useNovelContext = false): boolean {
    const active = this.validActive();
    const normalized = instruction.trim();
    if (!active || active.operation !== "custom") return false;
    if (!normalized || normalized.length > 2_000) {
      this.publish(freezeState({
        ...this.readyState(active, normalized
          ? "自定义要求不能超过 2000 字"
          : "请输入本次修改要求"),
        phase: "customizing",
        operation: "custom",
      }));
      return false;
    }
    this.startEditorTask(active, "custom", normalized, useNovelContext);
    return true;
  }

  /** Explicit compatibility path. It registers a public suggestion only. */
  prepareAssistantFallback(
    selectionId: string,
    operation: AssistantSelectionOperation,
  ): boolean {
    const record = this.registry.get(selectionId);
    if (!record || record.delivery.kind === "editor-task") return false;
    const active = this.active?.record.selectionId === selectionId
      ? this.active
      : undefined;
    const fieldLabel = active?.fieldLabel ?? record.fieldId;
    this.suggestions.upsert({
      id: this.suggestionId(selectionId),
      items: [buildSelectionSuggestion(record, fieldLabel, operation)],
    });
    if (active) {
      active.operation = operation;
      this.publish(freezeState({
        ...this.readyState(active, `已准备 ${ASSISTANT_SELECTION_OPERATION_COMMANDS[operation]}，请在右侧助手中明确发送`),
        phase: "suggested",
        visible: false,
        operation,
      }));
    }
    return true;
  }

  hideToolbar(): void {
    if (!this.state.visible) return;
    // If the author dismisses the toolbar while hashing a fresh range, make
    // that asynchronous capture stale so it cannot reopen the toolbar later.
    if (this.state.phase === "capturing") this.captureGeneration += 1;
    this.publish(freezeState({ ...this.state, visible: false }));
  }

  setToolbarSize(width: number, height: number): void {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
    this.toolbarSize = { width, height };
    this.reposition();
  }

  bindSelectionForSend(input: AssistantSelectionSendBinding): boolean {
    const record = this.registry.get(input.selectionId);
    if (!record || !input.sessionId.trim()) return false;
    const context = this.runtime.getEditableFieldContext(record.fieldId);
    if (!context
      || context.adapter.getValue().slice(record.startUtf16, record.endUtf16) !== record.text
      || input.agentId !== record.agentId
      || input.novelId !== record.novelId
      || input.documentId !== record.documentId
      || input.fieldId !== record.fieldId
      || input.contextRevision !== record.contextRevision) {
      return false;
    }
    const bound = this.registry.bindToSession({
      selectionId: record.selectionId,
      sessionId: input.sessionId,
      agentId: record.agentId,
      novelId: record.novelId,
      documentId: record.documentId,
      fieldId: record.fieldId,
      contextRevision: record.contextRevision,
    });
    if (!bound.ok) return false;
    if (this.active?.record.selectionId === record.selectionId) {
      this.active.record = bound.record;
    }
    this.suggestions.remove(this.suggestionId(record.selectionId));
    if (this.active?.record.selectionId === record.selectionId) {
      this.publish(freezeState({
        ...this.state,
        phase: "sent",
        visible: false,
        message: "选区请求已发送，等待结构化候选",
      }));
    }
    return true;
  }

  private startEditorTask(
    active: ActiveSelection,
    operation: AssistantSelectionOperation,
    customInstruction?: string,
    useNovelContext = false,
  ): void {
    this.removeActiveSuggestion();
    const selectionId = active.record.selectionId;
    this.publish(freezeState({
      ...this.readyState(active, `正在开始${ASSISTANT_SELECTION_OPERATION_LABELS[operation]}任务…`),
      phase: "starting",
      visible: false,
      operation,
    }));
    if (!this.onStartEditorTask) {
      this.publish(freezeState({
        ...this.readyState(active, "当前安装未提供选区编辑任务能力"),
        phase: "failed",
        operation,
      }));
      return;
    }
    let result: ReturnType<NonNullable<typeof this.onStartEditorTask>>;
    try {
      result = this.onStartEditorTask({
        record: active.record,
        fieldLabel: active.fieldLabel,
        operation,
        customInstruction,
        useNovelContext,
      });
    } catch (reason) {
      this.publishStartFailure(selectionId, operation, reason);
      return;
    }
    void Promise.resolve(result).then((started) => {
      const current = this.active?.record.selectionId === selectionId
        ? this.active
        : undefined;
      if (!current) return;
      if (started?.jobId) {
        const bound = this.registry.bindToEditorTask({
          selectionId,
          jobId: started.jobId,
          agentId: current.record.agentId,
          novelId: current.record.novelId,
          documentId: current.record.documentId,
          fieldId: current.record.fieldId,
          contextRevision: current.record.contextRevision,
        });
        if (!bound.ok) {
          this.publishStartFailure(selectionId, operation, new Error("编辑任务绑定已失效"));
          return;
        }
        current.record = bound.record;
      }
      this.publish(freezeState({
        ...this.state,
        phase: "sent",
        visible: false,
        message: "候选已在当前编辑工作面打开",
      }));
    }).catch((reason) => this.publishStartFailure(selectionId, operation, reason));
  }

  private publishStartFailure(
    selectionId: string,
    operation: AssistantSelectionOperation,
    reason: unknown,
  ): void {
    const active = this.active?.record.selectionId === selectionId
      ? this.active
      : undefined;
    if (!active) return;
    this.publish(freezeState({
      ...this.readyState(active, reason instanceof Error ? reason.message : "选区编辑任务启动失败"),
      phase: "failed",
      operation,
    }));
  }

  private readonly onSelectionEvent = (event: Event) => {
    if (this.composing) return;
    // Tab moves focus before keyup is delivered in browsers.  Treating that
    // keyup as a fresh text-selection event would discard the frozen range
    // before keyboard users can reach the toolbar.  The subsequent focusin
    // event still cancels when focus actually leaves the editor host.
    if (event.type === "keyup" && (event as KeyboardEvent).key === "Tab") return;
    if (isToolbarEventTarget(event.target)) return;
    if (isAssistantPaneEventTarget(event.target)) {
      this.hideToolbar();
      return;
    }
    const anchor = isTextSelectionAnchor(event.target) ? event.target : undefined;
    if (!anchor) {
      this.cancelActiveSelection();
      return;
    }
    const context = this.runtime.getEditableFieldContext();
    // Blurring a controlled field to operate QwenPaw's native sender must not
    // recapture the still-retained textarea range and dispose its suggestion.
    // A real move to another registered field changes the focused adapter
    // before mouseup/select, so that transition remains capturable.
    if (
      this.active
      && context?.adapter === this.active.adapter
      && anchor !== this.active.anchor
    ) {
      this.cancelActiveSelection();
      return;
    }
    // The document listeners run in capture phase.  For pointer selections the
    // browser updates selectionStart/selectionEnd as the event's default action,
    // after capture listeners have already run.  Reading the range immediately
    // therefore keeps a stale selection alive when the author simply clicks to
    // collapse it.  Mouseup needs the next task (not merely a microtask) because
    // the default action may run after the event-dispatch microtask checkpoint.
    if (event.type === "mouseup") {
      setTimeout(() => {
        if (this.started) void this.capture(anchor);
      }, 0);
      return;
    }
    void this.capture(anchor);
  };

  private readonly onFocusIn = (event: Event) => {
    if (isToolbarEventTarget(event.target)) return;
    if (this.active?.anchor && (event.target as unknown) === this.active.anchor) return;
    // Keep a keyboard-created selection available while Tab traverses sibling
    // controls inside the same editor host (for example title Cancel/Save)
    // before focus reaches the selection toolbar.  Pointer clicks still run
    // through onSelectionEvent and cancel a collapsed range immediately.
    if (this.active?.anchor && sharesSelectionEditHost(event.target, this.active.anchor)) return;
    if (isAssistantPaneEventTarget(event.target)) {
      this.hideToolbar();
      return;
    }
    this.cancelActiveSelection();
  };

  private readonly onCompositionStart = () => {
    this.composing = true;
  };

  private readonly onCompositionEnd = (event: Event) => {
    this.composing = false;
    const anchor = isTextSelectionAnchor(event.target) ? event.target : undefined;
    if (anchor) void this.capture(anchor);
  };

  private readonly onGeometryChange = () => this.reposition();

  private cancelActiveSelection(): void {
    // Once a native request has been sent, its structure card still needs the
    // registry record even if the author moves the caret.  The sent phase is
    // already visually hidden, so leave that in-flight binding untouched.
    if (this.state.phase === "starting" || this.state.phase === "sent") {
      this.hideToolbar();
      return;
    }
    this.captureGeneration += 1;
    const active = this.active;
    if (active) {
      this.suggestions.remove(this.suggestionId(active.record.selectionId));
      this.registry.delete(active.record.selectionId);
    }
    this.active = undefined;
    if (this.runtime.getStatus().active
      && this.runtime.getStatus().selectionCharacters > 0) {
      this.runtime.setActiveSelection(undefined);
    }
    this.publish(idleState());
  }

  private reconcile(status: AssistantContextRuntimeStatus): void {
    const previous = this.lastRuntimeStatus;
    this.lastRuntimeStatus = status;
    if (previous && (
      previous.selectedAgentId !== status.selectedAgentId
      || previous.novelId !== status.novelId
    )) {
      this.registry.clear();
    }
    if (!this.active) return;
    const current = this.validActive(false);
    if (current) return;
    this.removeActiveSuggestion();
    this.active = undefined;
    this.publish(freezeState({
      ...this.state,
      phase: "invalid",
      visible: false,
      message: "选区已因页面、字段或内容变化失效",
    }));
  }

  private validActive(publishInvalid = true): ActiveSelection | undefined {
    const active = this.active;
    if (!active) return undefined;
    const record = this.registry.get(active.record.selectionId);
    const context = record
      ? this.runtime.getEditableFieldContext(record.fieldId)
      : null;
    const valid = Boolean(
      record
      && context
      && context.adapter === active.adapter
      && context.scopeId === active.scopeId
      && scopeMatches(context, record)
      && active.adapter.getValue().slice(record.startUtf16, record.endUtf16) === record.text
      && record.expiresAtMs > this.now(),
    );
    if (valid) return active;
    if (publishInvalid) this.reconcile(this.runtime.getStatus());
    return undefined;
  }

  private readyState(
    active: ActiveSelection,
    message: string,
  ): AssistantSelectionToolbarState {
    return freezeState({
      phase: "ready",
      visible: true,
      selectionId: active.record.selectionId,
      fieldId: active.record.fieldId,
      fieldLabel: active.fieldLabel,
      selectedCharacters: active.record.text.length,
      selectedPreview: selectionPreview(active.record.text),
      operation: active.operation,
      message,
      placement: active.anchor ? this.resolvePlacement(active.anchor) : undefined,
    });
  }

  private resolvePlacement(anchor: AssistantSelectionAnchor): SelectionToolbarPlacement | undefined {
    if (anchor.isConnected === false) return undefined;
    const rect = anchor.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return undefined;
    return resolveSelectionToolbarPlacement({
      viewportRect: this.getViewportRect(),
      fieldRect: rect,
      toolbarSize: this.toolbarSize,
      environment: {
        fieldScrollLeft: anchor.scrollLeft ?? 0,
        fieldScrollTop: anchor.scrollTop ?? 0,
        visualViewportScale: this.getVisualViewportScale(),
        devicePixelRatio: this.getDevicePixelRatio(),
        hasLongVisualLine: (anchor.scrollWidth ?? 0) > (anchor.clientWidth ?? Number.POSITIVE_INFINITY),
        selectionWraps: false,
        isComposing: this.composing,
      },
    });
  }

  private reposition(): void {
    if (!this.active?.anchor || !this.state.visible) return;
    const placement = this.resolvePlacement(this.active.anchor);
    if (!placement) {
      this.hideToolbar();
      return;
    }
    this.publish(freezeState({ ...this.state, placement }));
  }

  private suggestionId(selectionId: string): string {
    return `anw.selection.${selectionId}`;
  }

  private removeActiveSuggestion(): void {
    if (!this.active) return;
    this.suggestions.remove(this.suggestionId(this.active.record.selectionId));
  }

  private publish(state: AssistantSelectionToolbarState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }
}
