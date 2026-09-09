import {
  type CreatedAssistantContextRef,
  type CreationDraftAssistantContextV1,
  type CreationDraftCreateAssistantContextRefInput,
} from "./assistant-context-ref";
import { NOVEL_ASSISTANT_TARGET_AGENT_ID } from "./assistant-context-runtime";
import type { AssistantRequestContextPatch } from "./assistant-request-payload";
import type { NativeWritingActionBinding } from "./writing-skills/native";


const MAX_CHARACTERS = 24_000;
const FIELD_VALUE_LIMIT = 4_000;
const TTL_MS = 5 * 60 * 1_000;
const SETTLE_MS = 350;


const FIELD_META = [
  ["writing_type", "写作类型"],
  ["audience", "目标读者"],
  ["idea", "创作思路"],
  ["genre", "小说分类"],
  ["subgenre", "小说子类"],
  ["template_name", "模板名称"],
  ["template_data", "模板设定"],
  ["author_name", "作者名称"],
  ["title", "小说名称"],
] as const;


export interface CreationDraftContextInput {
  readonly id: string;
  readonly version: number;
  readonly step: number;
  readonly state: "draft";
  readonly data: Readonly<Record<string, unknown>>;
  readonly persistedData: Readonly<Record<string, unknown>>;
}


export interface CreationDraftContextStatus {
  readonly active: boolean;
  readonly supportedAgent: boolean;
  readonly selectedAgentId?: string;
  readonly sessionId?: string;
  readonly ownerToken?: string;
  readonly draftId?: string;
  readonly draftVersion?: number;
  readonly step?: number;
  readonly contextRevision: number;
  readonly fieldCount: number;
  readonly dirtyFieldCount: number;
  readonly preparation: "idle" | "settling" | "preparing" | "ready" | "failed" | "expired";
  readonly truncated: boolean;
}


export interface CreationDraftContextCapture {
  readonly context: CreationDraftAssistantContextV1;
  readonly serialized: string;
}


type Listener = (status: CreationDraftContextStatus) => void;


function normalized(value: string | null | undefined): string | undefined {
  const result = value?.trim();
  return result || undefined;
}


function stableText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}


function stableUsedCharacters(context: CreationDraftAssistantContextV1): string {
  let serialized = "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    serialized = JSON.stringify(context);
    if (context.budget.usedCharacters === serialized.length) return serialized;
    context.budget.usedCharacters = serialized.length;
  }
  return JSON.stringify(context);
}


export class CreationDraftAssistantContextRuntime {
  private readonly listeners = new Set<Listener>();
  private selectedAgentId: string | undefined;
  private sessionId: string | undefined;
  private ownerToken: string | undefined;
  private draft: CreationDraftContextInput | null = null;
  private revision = 0;
  private preparation: CreationDraftContextStatus["preparation"] = "idle";
  private truncated = false;
  private fingerprint = "";

  setHostBinding(input: {
    active: boolean;
    ownerToken?: string | null;
    selectedAgentId?: string | null;
    sessionId?: string | null;
  }): void {
    const nextOwner = input.active ? normalized(input.ownerToken) : undefined;
    const nextAgent = input.active ? normalized(input.selectedAgentId) : undefined;
    const nextSession = input.active ? normalized(input.sessionId) : undefined;
    if (
      nextOwner === this.ownerToken
      && nextAgent === this.selectedAgentId
      && nextSession === this.sessionId
    ) return;
    this.ownerToken = nextOwner;
    this.selectedAgentId = nextAgent;
    this.sessionId = nextSession;
    this.revision += 1;
    this.preparation = this.draft && nextOwner ? "settling" : "idle";
    this.emit();
  }

  setDraft(input: CreationDraftContextInput | null): void {
    let fingerprint = "";
    try { fingerprint = input ? JSON.stringify(input) : ""; } catch { fingerprint = ""; }
    if (fingerprint === this.fingerprint) return;
    this.fingerprint = fingerprint;
    this.draft = input ? {
      ...input,
      data: { ...input.data },
      persistedData: { ...input.persistedData },
    } : null;
    this.revision += 1;
    this.preparation = this.draft && this.ownerToken ? "settling" : "idle";
    this.truncated = false;
    this.emit();
  }

  setPreparation(
    value: CreationDraftContextStatus["preparation"],
    truncated = this.truncated,
  ): void {
    this.preparation = value;
    this.truncated = truncated;
    this.emit();
  }

  capture(now = Date.now()): CreationDraftContextCapture | null {
    if (
      !this.draft
      || !this.ownerToken
      || this.selectedAgentId !== NOVEL_ASSISTANT_TARGET_AGENT_ID
    ) return null;
    const fields: NonNullable<CreationDraftAssistantContextV1["editing"]>["fields"] = [];
    const omittedFieldIds: string[] = [];
    for (const [key, label] of FIELD_META) {
      const original = stableText(this.draft.data[key]);
      if (!original) continue;
      const value = original.slice(0, FIELD_VALUE_LIMIT);
      fields.push({
        id: `creation.${key}`,
        label,
        value,
        dirty: stableText(this.draft.persistedData[key]) !== original,
        truncated: value.length !== original.length,
        characterCount: original.length,
        persistence: "explicit-save",
      });
      if (value.length !== original.length) omittedFieldIds.push(`creation.${key}`);
    }
    const capturedAt = new Date(now).toISOString();
    const context: CreationDraftAssistantContextV1 = {
      schemaVersion: "creation-draft-assistant-context/1",
      contextRevision: this.revision,
      capturedAt,
      expiresAt: new Date(now + TTL_MS).toISOString(),
      agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
      ...(this.sessionId ? { sessionId: this.sessionId } : {}),
      creationDraft: {
        id: this.draft.id,
        version: this.draft.version,
        step: this.draft.step,
        state: "draft",
      },
      page: {
        section: "creation",
        view: "novel-creation-wizard",
        step: this.draft.step,
      },
      ...(fields.length ? { editing: { fields } } : {}),
      budget: {
        maxCharacters: MAX_CHARACTERS,
        usedCharacters: 0,
        truncated: omittedFieldIds.length > 0,
        omittedFieldIds,
      },
    };
    while (JSON.stringify(context).length > MAX_CHARACTERS && context.editing?.fields.length) {
      const removed = context.editing.fields.pop();
      if (removed && !context.budget.omittedFieldIds.includes(removed.id)) {
        context.budget.omittedFieldIds.push(removed.id);
      }
      context.budget.truncated = true;
    }
    if (context.editing?.fields.length === 0) delete context.editing;
    const serialized = stableUsedCharacters(context);
    if (serialized.length > MAX_CHARACTERS) return null;
    this.truncated = context.budget.truncated;
    return { context, serialized };
  }

  getStatus(): CreationDraftContextStatus {
    const capture = this.draft;
    let fieldCount = 0;
    let dirtyFieldCount = 0;
    if (capture) {
      for (const [key] of FIELD_META) {
        const current = stableText(capture.data[key]);
        if (!current) continue;
        fieldCount += 1;
        if (stableText(capture.persistedData[key]) !== current) dirtyFieldCount += 1;
      }
    }
    return {
      active: Boolean(capture && this.ownerToken),
      supportedAgent: this.selectedAgentId === NOVEL_ASSISTANT_TARGET_AGENT_ID,
      selectedAgentId: this.selectedAgentId,
      sessionId: this.sessionId,
      ownerToken: this.ownerToken,
      draftId: capture?.id,
      draftVersion: capture?.version,
      step: capture?.step,
      contextRevision: this.revision,
      fieldCount,
      dirtyFieldCount,
      preparation: this.preparation,
      truncated: this.truncated,
    };
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  clear(): void {
    this.setDraft(null);
  }

  private emit(): void {
    const status = this.getStatus();
    for (const listener of this.listeners) listener(status);
  }
}


export interface CreationDraftContextRefCoordinator {
  start(): () => void;
  refresh(): void;
  requestPatch(input: {
    sessionId?: string;
    selectedAgent?: string;
  }): AssistantRequestContextPatch | null;
  dispose(): void;
}


export function createCreationDraftContextRefCoordinator(options: {
  runtime: CreationDraftAssistantContextRuntime;
  tabInstance: string;
  createRef: (
    input: CreationDraftCreateAssistantContextRefInput,
    signal: AbortSignal,
  ) => Promise<CreatedAssistantContextRef>;
  onWritingActionBound?: (input: NativeWritingActionBinding) => void;
  now?: () => number;
  settleMs?: number;
  setTimer?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  clearTimer?: (timer: ReturnType<typeof setTimeout>) => void;
}): CreationDraftContextRefCoordinator {
  const now = options.now ?? Date.now;
  const setTimer = options.setTimer ?? setTimeout;
  const clearTimer = options.clearTimer ?? clearTimeout;
  const settleMs = Math.max(0, Math.round(options.settleMs ?? SETTLE_MS));
  let ready: {
    created: CreatedAssistantContextRef;
    draftId: string;
    ownerToken: string;
    sessionId?: string;
    revision: number;
  } | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let abort: AbortController | null = null;
  let unsubscribe: (() => void) | null = null;
  let generation = 0;
  let observedRevision = -1;
  let disposed = false;

  const invalidate = () => {
    generation += 1;
    ready = null;
    if (timer !== null) clearTimer(timer);
    timer = null;
    abort?.abort();
    abort = null;
  };

  const prepare = async (token: number) => {
    timer = null;
    const status = options.runtime.getStatus();
    if (
      disposed
      || token !== generation
      || !status.active
      || !status.supportedAgent
      || !status.ownerToken
      || !status.draftId
    ) return;
    const capture = options.runtime.capture(now());
    if (!capture || capture.context.contextRevision !== status.contextRevision) return;
    options.runtime.setPreparation("preparing");
    const controller = new AbortController();
    abort = controller;
    try {
      const created = await options.createRef({
        binding: {
          ownerToken: status.ownerToken,
          tabInstance: options.tabInstance,
          agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
          scopeKind: "creation_draft",
          scopeId: status.draftId,
          ...(status.sessionId ? { sessionId: status.sessionId } : {}),
        },
        snapshot: capture.context,
        serialized: capture.serialized,
      }, controller.signal);
      const latest = options.runtime.getStatus();
      if (
        disposed
        || controller.signal.aborted
        || token !== generation
        || latest.contextRevision !== status.contextRevision
        || latest.draftId !== status.draftId
        || created.contextRevision !== status.contextRevision
        || Date.parse(created.expiresAt) <= now()
      ) return;
      ready = {
        created,
        draftId: status.draftId,
        ownerToken: status.ownerToken,
        sessionId: status.sessionId,
        revision: status.contextRevision,
      };
      options.runtime.setPreparation("ready", capture.context.budget.truncated);
    } catch {
      if (!controller.signal.aborted && token === generation && !disposed) {
        options.runtime.setPreparation("failed");
      }
    } finally {
      if (abort === controller) abort = null;
    }
  };

  const schedule = (force = false) => {
    const status = options.runtime.getStatus();
    if (!force && status.contextRevision === observedRevision) return;
    observedRevision = status.contextRevision;
    invalidate();
    if (!status.active || !status.supportedAgent) return;
    options.runtime.setPreparation("settling");
    const token = generation;
    timer = setTimer(() => { void prepare(token); }, settleMs);
  };

  return {
    start() {
      if (disposed) throw new Error("creation draft context coordinator is disposed");
      if (!unsubscribe) {
        unsubscribe = options.runtime.subscribe(() => schedule());
        schedule(true);
      }
      return () => {
        unsubscribe?.();
        unsubscribe = null;
        invalidate();
      };
    },
    refresh() {
      if (!disposed) schedule(true);
    },
    requestPatch(input) {
      if (!ready) return null;
      const status = options.runtime.getStatus();
      if (
        input.selectedAgent !== NOVEL_ASSISTANT_TARGET_AGENT_ID
        || (ready.sessionId !== undefined && input.sessionId !== ready.sessionId)
        || status.contextRevision !== ready.revision
        || status.draftId !== ready.draftId
        || status.ownerToken !== ready.ownerToken
        || Date.parse(ready.created.expiresAt) <= now()
      ) {
        invalidate();
        options.runtime.setPreparation("expired");
        return null;
      }
      const created = ready.created;
      options.onWritingActionBound?.({
        actionId: created.writingActionId,
        sessionId: input.sessionId ?? "",
        scopeKind: "creation_draft",
        scopeId: ready.draftId,
        creationDraftId: ready.draftId,
        tabInstance: options.tabInstance,
      });
      ready = null;
      options.runtime.setPreparation("settling");
      schedule(true);
      return { context_ref: created.contextRef };
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


export const creationDraftAssistantContextRuntime = (
  new CreationDraftAssistantContextRuntime()
);
