import {
  NOVEL_ASSISTANT_CONTEXT_SETTLE_MS,
  type NovelAssistantContextV2,
} from "./assistant-context-schema";
import {
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantContextRuntimeStatus,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import type { AssistantRequestContextPatch } from "./assistant-request-payload";
import type { RouteSessionSnapshot } from "./workbench-route";
import { resolveSelectionDocumentId } from "./assistant-selection-registry";


export interface AssistantContextRefBinding {
  ownerToken: string;
  tabInstance: string;
  agentId: typeof NOVEL_ASSISTANT_TARGET_AGENT_ID;
  novelId: string;
  documentId?: string;
  sessionId?: string;
}


export interface CreationDraftAssistantContextV1 {
  schemaVersion: "creation-draft-assistant-context/1";
  contextRevision: number;
  capturedAt: string;
  expiresAt: string;
  agentId: typeof NOVEL_ASSISTANT_TARGET_AGENT_ID;
  sessionId?: string;
  creationDraft: {
    id: string;
    version: number;
    step: number;
    state: "draft";
  };
  page: {
    section: "creation";
    view: "novel-creation-wizard";
    step: number;
  };
  editing?: {
    focusedFieldId?: string;
    fields: Array<{
      id: string;
      label: string;
      value: string;
      dirty: boolean;
      truncated: boolean;
      characterCount: number;
      persistence: "explicit-save";
    }>;
  };
  budget: {
    maxCharacters: number;
    usedCharacters: number;
    truncated: boolean;
    omittedFieldIds: string[];
  };
}


export interface NovelCreateAssistantContextRefInput {
  binding: AssistantContextRefBinding;
  snapshot: NovelAssistantContextV2;
  serialized: string;
}


export interface CreationDraftCreateAssistantContextRefInput {
  binding: {
    ownerToken: string;
    tabInstance: string;
    agentId: typeof NOVEL_ASSISTANT_TARGET_AGENT_ID;
    scopeKind: "creation_draft";
    scopeId: string;
    sessionId?: string;
  };
  snapshot: CreationDraftAssistantContextV1;
  serialized: string;
}


export type CreateAssistantContextRefInput =
  | NovelCreateAssistantContextRefInput
  | CreationDraftCreateAssistantContextRefInput;


export interface CreatedAssistantContextRef {
  contextRef: string;
  writingActionId: string;
  expiresAt: string;
  contextRevision: number;
  payloadCharacters: number;
}


export interface AssistantContextRefCoordinatorOptions {
  runtime: NovelAssistantContextRuntime;
  getRouteSession: () => RouteSessionSnapshot;
  createRef: (
    input: CreateAssistantContextRefInput,
    signal: AbortSignal,
  ) => Promise<CreatedAssistantContextRef>;
  tabInstance?: string;
  now?: () => number;
  settleMs?: number;
  setTimer?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  clearTimer?: (timer: ReturnType<typeof setTimeout>) => void;
  bindSelectionForSend?: (input: {
    selectionId: string;
    sessionId: string;
    agentId: string;
    novelId: string;
    documentId: string;
    fieldId: string;
    contextRevision: number;
  }) => boolean;
  onWritingActionBound?: (input: {
    actionId: string;
    contextRef: string;
    sessionId: string;
    novelId: string;
    documentId?: string;
    tabInstance: string;
  }) => void;
}


export interface AssistantContextRefCoordinator {
  start(): () => void;
  refresh(): void;
  requestPatch(input: {
    sessionId?: string;
    selectedAgent?: string;
  }): AssistantRequestContextPatch | null;
  getReadyRef(): CreatedAssistantContextRef | null;
  getTabInstance(): string;
  dispose(): void;
}


export interface AssistantTabInstanceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}


const TAB_INSTANCE_STORAGE_KEY = "anw.assistant-context.tab-instance.v1";
const TAB_INSTANCE_PATTERN = /^anw-tab-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;


function browserNavigationType(): string | null {
  if (typeof performance === "undefined" || typeof performance.getEntriesByType !== "function") {
    return null;
  }
  const entry = performance.getEntriesByType("navigation")[0] as { type?: unknown } | undefined;
  return typeof entry?.type === "string" ? entry.type : null;
}


/**
 * Keep one tab identity across a hard refresh, while rotating it for a newly
 * opened or duplicated tab even when the browser copied sessionStorage.
 */
export function createAssistantTabInstance(options: {
  storage?: AssistantTabInstanceStorage | null;
  navigationType?: string | null;
  createId?: () => string;
} = {}): string {
  const storage = options.storage === undefined
    ? (typeof sessionStorage === "undefined" ? null : sessionStorage)
    : options.storage;
  const navigationType = options.navigationType === undefined
    ? browserNavigationType()
    : options.navigationType;
  if (navigationType === "reload") {
    try {
      const stored = storage?.getItem(TAB_INSTANCE_STORAGE_KEY);
      if (stored && TAB_INSTANCE_PATTERN.test(stored)) return stored;
    } catch {
      // Storage is only a refresh aid; a fresh scoped identity is safe.
    }
  }
  const createId = options.createId ?? (() => {
    if (typeof globalThis.crypto?.randomUUID !== "function") {
      throw new Error("crypto.randomUUID is required for the workbench tab instance");
    }
    return `anw-tab-${globalThis.crypto.randomUUID()}`;
  });
  const created = createId();
  if (!TAB_INSTANCE_PATTERN.test(created)) {
    throw new Error("invalid workbench tab instance");
  }
  try { storage?.setItem(TAB_INSTANCE_STORAGE_KEY, created); } catch { /* best-effort */ }
  return created;
}


interface ReadyAssistantContextRef extends CreatedAssistantContextRef {
  binding: AssistantContextRefBinding;
  selection?: {
    selectionId: string;
    agentId: string;
    novelId: string;
    documentId: string;
    fieldId: string;
    contextRevision: number;
  };
}


function defaultTabInstance(): string {
  return createAssistantTabInstance();
}


function routeBinding(
  status: AssistantContextRuntimeStatus,
  route: RouteSessionSnapshot,
  tabInstance: string,
): AssistantContextRefBinding | null {
  if (!status.active
    || !status.supportedAgent
    || !status.novelId
    || !route.route
    || !route.ownerToken
    || (route.state !== "workbench-no-session" && route.state !== "workbench-session")
    || route.route.novelId !== status.novelId) {
    return null;
  }
  return {
    ownerToken: route.ownerToken,
    tabInstance,
    agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
    novelId: status.novelId,
    documentId: route.route.documentId,
    sessionId: status.sessionId,
  };
}


function sameBinding(
  left: AssistantContextRefBinding,
  right: AssistantContextRefBinding,
): boolean {
  return left.ownerToken === right.ownerToken
    && left.tabInstance === right.tabInstance
    && left.agentId === right.agentId
    && left.novelId === right.novelId
    && left.documentId === right.documentId
    && left.sessionId === right.sessionId;
}


/**
 * Prepares asynchronous context refs, then exposes a synchronous one-shot
 * getter for QwenPaw's public requestPayload extension point.
 */
export function createAssistantContextRefCoordinator(
  options: AssistantContextRefCoordinatorOptions,
): AssistantContextRefCoordinator {
  const now = options.now ?? Date.now;
  const settleMs = Math.max(0, Math.round(
    options.settleMs ?? NOVEL_ASSISTANT_CONTEXT_SETTLE_MS,
  ));
  const setTimer = options.setTimer ?? setTimeout;
  const clearTimer = options.clearTimer ?? clearTimeout;
  const tabInstance = options.tabInstance?.trim() || defaultTabInstance();
  let ready: ReadyAssistantContextRef | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let inFlight: AbortController | null = null;
  let unsubscribe: (() => void) | null = null;
  let observedRevision = -1;
  let generation = 0;
  let disposed = false;

  const clearPending = () => {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
    inFlight?.abort();
    inFlight = null;
  };

  const invalidate = () => {
    ready = null;
    generation += 1;
    clearPending();
  };

  const prepare = async (expectedRevision: number, expectedGeneration: number) => {
    timer = null;
    if (disposed || generation !== expectedGeneration) return;
    const status = options.runtime.getStatus();
    const binding = routeBinding(status, options.getRouteSession(), tabInstance);
    if (!binding || status.contextRevision !== expectedRevision) return;
    options.runtime.setPreparation("preparing");
    const capture = options.runtime.capture();
    if (!capture || capture.context.contextRevision !== expectedRevision) {
      options.runtime.setPreparation("failed");
      return;
    }

    const controller = new AbortController();
    inFlight = controller;
    try {
      const created = await options.createRef({
        binding,
        snapshot: capture.context,
        serialized: capture.serialized,
      }, controller.signal);
      if (disposed || controller.signal.aborted || generation !== expectedGeneration) return;
      const latestStatus = options.runtime.getStatus();
      const latestBinding = routeBinding(
        latestStatus,
        options.getRouteSession(),
        tabInstance,
      );
      if (!latestBinding
        || !sameBinding(binding, latestBinding)
        || latestStatus.contextRevision !== expectedRevision
        || created.contextRevision !== expectedRevision
        || !created.contextRef.trim()
        || !Number.isFinite(Date.parse(created.expiresAt))
        || Date.parse(created.expiresAt) <= now()) {
        options.runtime.setPreparation("failed");
        return;
      }
      ready = {
        ...created,
        binding,
        selection: capture.context.selection ? {
          selectionId: capture.context.selection.id,
          agentId: capture.context.agentId,
          novelId: capture.context.novel.id,
          documentId: resolveSelectionDocumentId(capture.context),
          fieldId: capture.context.selection.fieldId,
          contextRevision: capture.context.contextRevision,
        } : undefined,
      };
      options.runtime.setPreparation("ready", capture.context.budget.truncated);
    } catch (reason) {
      if (!controller.signal.aborted && !disposed && generation === expectedGeneration) {
        options.runtime.setPreparation("failed");
      }
    } finally {
      if (inFlight === controller) inFlight = null;
    }
  };

  const schedule = (status: AssistantContextRuntimeStatus, force = false) => {
    if (disposed) return;
    const binding = routeBinding(status, options.getRouteSession(), tabInstance);
    if (!binding) {
      observedRevision = status.contextRevision;
      invalidate();
      if (status.active && status.preparation !== "idle") {
        options.runtime.setPreparation("idle");
      }
      return;
    }
    if (!force && observedRevision === status.contextRevision) return;
    observedRevision = status.contextRevision;
    invalidate();
    const expectedGeneration = generation;
    options.runtime.setPreparation("settling");
    timer = setTimer(() => {
      void prepare(status.contextRevision, expectedGeneration);
    }, settleMs);
  };

  return {
    start() {
      if (disposed) throw new Error("assistant context ref coordinator is disposed");
      if (!unsubscribe) {
        unsubscribe = options.runtime.subscribe((status) => schedule(status));
        schedule(options.runtime.getStatus(), true);
      }
      return () => {
        unsubscribe?.();
        unsubscribe = null;
        invalidate();
      };
    },
    refresh() {
      if (disposed) return;
      schedule(options.runtime.getStatus(), true);
    },
    requestPatch(input) {
      if (disposed || !ready) return null;
      const status = options.runtime.getStatus();
      const currentBinding = routeBinding(status, options.getRouteSession(), tabInstance);
      if (!currentBinding
        || !sameBinding(ready.binding, currentBinding)
        || status.contextRevision !== ready.contextRevision
        || input.selectedAgent !== NOVEL_ASSISTANT_TARGET_AGENT_ID
        || (ready.binding.sessionId !== undefined
          && input.sessionId !== ready.binding.sessionId)
        || Date.parse(ready.expiresAt) <= now()) {
        ready = null;
        options.runtime.setPreparation("expired");
        return null;
      }
      if (ready.selection && (
        !input.sessionId
        || !options.bindSelectionForSend?.({
          ...ready.selection,
          sessionId: input.sessionId,
        })
      )) {
        ready = null;
        options.runtime.setPreparation("expired");
        return null;
      }
      const contextRef = ready.contextRef;
      options.onWritingActionBound?.({
        actionId: ready.writingActionId,
        contextRef,
        sessionId: input.sessionId ?? "",
        novelId: ready.binding.novelId,
        documentId: ready.binding.documentId,
        tabInstance,
      });
      ready = null;
      options.runtime.setPreparation("settling");
      schedule(options.runtime.getStatus(), true);
      return { context_ref: contextRef };
    },
    getReadyRef() {
      return ready ? {
        contextRef: ready.contextRef,
        writingActionId: ready.writingActionId,
        expiresAt: ready.expiresAt,
        contextRevision: ready.contextRevision,
        payloadCharacters: ready.payloadCharacters,
      } : null;
    },
    getTabInstance() {
      return tabInstance;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      unsubscribe?.();
      unsubscribe = null;
      invalidate();
    },
  };
}
