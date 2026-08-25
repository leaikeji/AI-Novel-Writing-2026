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


export interface CreateAssistantContextRefInput {
  binding: AssistantContextRefBinding;
  snapshot: NovelAssistantContextV2;
  serialized: string;
}


export interface CreatedAssistantContextRef {
  contextRef: string;
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
  if (typeof globalThis.crypto?.randomUUID !== "function") {
    throw new Error("crypto.randomUUID is required for the workbench tab instance");
  }
  return `anw-tab-${globalThis.crypto.randomUUID()}`;
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
      ready = null;
      options.runtime.setPreparation("settling");
      schedule(options.runtime.getStatus(), true);
      return { context_ref: contextRef };
    },
    getReadyRef() {
      return ready ? {
        contextRef: ready.contextRef,
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
