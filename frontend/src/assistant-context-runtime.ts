import type {
  NovelAssistantContextEnvelope,
  NovelAssistantSelectionSnapshot,
  NovelPageSection,
  NovelPageView,
} from "./assistant-context-schema";
import {
  NovelAssistantContextStore,
  type NovelAssistantContextCapture,
  type NovelAssistantContextStoreStatus,
} from "./assistant-context-store";
import type {
  EditableFieldAdapter,
  EditableFieldRegistration,
} from "./assistant-fields";
import { resolveSelectionDocumentId } from "./assistant-selection-registry";


export const NOVEL_ASSISTANT_TARGET_AGENT_ID = "ai-novel-writer";


export type AssistantContextScopeKind = "page" | "modal";


export interface AssistantContextScopeInput {
  id: string;
  kind: AssistantContextScopeKind;
  envelope: NovelAssistantContextEnvelope;
}


export interface AssistantContextScopeHandle {
  readonly id: string;
  readonly kind: AssistantContextScopeKind;
  registerField(adapter: EditableFieldAdapter): EditableFieldRegistration;
  setFocusedField(fieldId: string | undefined): void;
  notifyFieldChanged(fieldId: string): void;
  setSelection(selection: NovelAssistantSelectionSnapshot | undefined): void;
  dispose(): void;
}


export interface AssistantEditableFieldContext {
  readonly adapter: EditableFieldAdapter;
  readonly scopeId: string;
  readonly scopeKind: AssistantContextScopeKind;
  readonly agentId: typeof NOVEL_ASSISTANT_TARGET_AGENT_ID;
  readonly sessionId?: string;
  readonly novelId: string;
  /** Document id or a namespaced identity for an entity/draft editor. */
  readonly documentId: string;
  readonly fieldId: string;
  readonly contextRevision: number;
}


export type AssistantContextPreparationState =
  | "idle"
  | "settling"
  | "preparing"
  | "ready"
  | "failed"
  | "expired";


export interface AssistantContextRuntimeStatus {
  active: boolean;
  supportedAgent: boolean;
  selectedAgentId?: string;
  sessionId?: string;
  scopeId?: string;
  scopeKind?: AssistantContextScopeKind;
  novelId?: string;
  novelTitle?: string;
  section?: NovelPageSection;
  view?: NovelPageView;
  modal?: NovelPageView;
  entityTitle?: string;
  contextRevision: number;
  fieldCount: number;
  dirtyFieldCount: number;
  selectionCharacters: number;
  preparation: AssistantContextPreparationState;
  truncated: boolean;
  disposed: boolean;
}


export type AssistantContextRuntimeListener = (
  status: AssistantContextRuntimeStatus,
) => void;


interface RuntimeScope {
  id: string;
  kind: AssistantContextScopeKind;
  envelope: NovelAssistantContextEnvelope;
  store: NovelAssistantContextStore;
  unsubscribe: () => void;
  active: boolean;
}


function nonEmpty(value: string | null | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized || undefined;
}


function emptyStatus(): NovelAssistantContextStoreStatus {
  return {
    contextRevision: 0,
    agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
    fieldCount: 0,
    dirtyFieldCount: 0,
    selectionCharacters: 0,
    disposed: false,
  };
}


/**
 * Tab-local coordinator for page/modal stores. Background page adapters remain
 * mounted while a modal scope is active, then become active again without DOM
 * re-querying or adapter recreation.
 */
export class NovelAssistantContextRuntime {
  private readonly listeners = new Set<AssistantContextRuntimeListener>();
  private readonly scopes = new Map<string, RuntimeScope>();
  private readonly stack: string[] = [];
  private selectedAgentId: string | undefined;
  private sessionId: string | undefined;
  private revisionFloor = 0;
  private preparation: AssistantContextPreparationState = "idle";
  private truncated = false;
  private disposed = false;

  setHostBinding(selectedAgentId?: string | null, sessionId?: string | null): void {
    this.assertActive();
    const nextAgentId = nonEmpty(selectedAgentId);
    const nextSessionId = nonEmpty(sessionId);
    if (nextAgentId === this.selectedAgentId && nextSessionId === this.sessionId) return;
    this.selectedAgentId = nextAgentId;
    this.sessionId = nextSessionId;
    this.revisionFloor += 1;
    for (const scope of this.scopes.values()) {
      scope.store.setBinding(NOVEL_ASSISTANT_TARGET_AGENT_ID, nextSessionId);
      scope.store.setRevisionFloor(this.revisionFloor);
    }
    this.preparation = "idle";
    this.emit();
  }

  mountScope(input: AssistantContextScopeInput): AssistantContextScopeHandle {
    this.assertActive();
    const id = input.id.trim();
    if (!id) throw new Error("assistant context scope id must not be empty");
    if (this.scopes.has(id)) throw new Error(`assistant context scope already mounted: ${id}`);
    if (input.envelope.agentId !== NOVEL_ASSISTANT_TARGET_AGENT_ID) {
      throw new Error("assistant context scope must target ai-novel-writer");
    }

    if (input.kind === "page") this.clearScopes();
    const store = new NovelAssistantContextStore({
      agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
      sessionId: this.sessionId,
      envelope: input.envelope,
    });
    this.revisionFloor += 1;
    store.setRevisionFloor(this.revisionFloor);
    const scope: RuntimeScope = {
      id,
      kind: input.kind,
      envelope: input.envelope,
      store,
      unsubscribe: () => undefined,
      active: true,
    };
    scope.unsubscribe = store.subscribe((status) => {
      this.revisionFloor = Math.max(this.revisionFloor, status.contextRevision);
      if (this.activeScope()?.id === scope.id) {
        this.preparation = "settling";
        this.truncated = false;
      }
      this.emit();
    });
    this.scopes.set(id, scope);
    this.stack.push(id);
    this.preparation = "settling";
    this.truncated = false;
    this.emit();

    let active = true;
    return {
      id,
      kind: input.kind,
      registerField: (adapter) => {
        if (!active) throw new Error(`assistant context scope is disposed: ${id}`);
        return store.registerField(adapter);
      },
      setFocusedField: (fieldId) => {
        if (!active) return;
        store.setFocusedField(fieldId);
      },
      notifyFieldChanged: (fieldId) => {
        if (!active) return;
        store.notifyFieldChanged(fieldId);
      },
      setSelection: (selection) => {
        if (!active) return;
        store.setSelection(selection);
      },
      dispose: () => {
        if (!active) return;
        active = false;
        this.disposeScope(id);
      },
    };
  }

  capture(): NovelAssistantContextCapture | null {
    this.assertActive();
    if (this.selectedAgentId !== NOVEL_ASSISTANT_TARGET_AGENT_ID) return null;
    const scope = this.activeScope();
    if (!scope) return null;
    scope.store.setRevisionFloor(this.revisionFloor);
    const capture = scope.store.capture();
    this.revisionFloor = Math.max(
      this.revisionFloor,
      capture.context.contextRevision,
    );
    this.truncated = capture.context.budget.truncated;
    this.emit();
    return capture;
  }

  /**
   * Resolve an adapter from the active page/modal scope without querying DOM.
   * A supplied field id is used by proposal cards after focus has moved to the
   * native assistant; otherwise the store's logical focused field is used.
   */
  getEditableFieldContext(
    fieldId?: string,
  ): AssistantEditableFieldContext | null {
    this.assertActive();
    if (this.selectedAgentId !== NOVEL_ASSISTANT_TARGET_AGENT_ID) return null;
    const scope = this.activeScope();
    if (!scope) return null;
    const resolvedFieldId = fieldId ?? scope.store.getStatus().focusedFieldId;
    if (!resolvedFieldId) return null;
    const adapter = scope.store.fields.get(resolvedFieldId);
    if (!adapter) return null;
    return {
      adapter,
      scopeId: scope.id,
      scopeKind: scope.kind,
      agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
      sessionId: this.sessionId,
      novelId: scope.envelope.novel.id,
      documentId: resolveSelectionDocumentId(scope.envelope),
      fieldId: resolvedFieldId,
      contextRevision: scope.store.getStatus().contextRevision,
    };
  }

  setActiveSelection(selection: NovelAssistantSelectionSnapshot | undefined): void {
    this.assertActive();
    const scope = this.activeScope();
    if (!scope) throw new Error("assistant context has no active scope");
    scope.store.setSelection(selection);
  }

  setPreparation(
    preparation: AssistantContextPreparationState,
    truncated = this.truncated,
  ): void {
    this.assertActive();
    this.preparation = preparation;
    this.truncated = truncated;
    this.emit();
  }

  getStatus(): AssistantContextRuntimeStatus {
    const scope = this.activeScope();
    const store = scope?.store.getStatus() ?? emptyStatus();
    return {
      active: Boolean(scope),
      supportedAgent: this.selectedAgentId === NOVEL_ASSISTANT_TARGET_AGENT_ID,
      selectedAgentId: this.selectedAgentId,
      sessionId: this.sessionId,
      scopeId: scope?.id,
      scopeKind: scope?.kind,
      novelId: scope?.envelope.novel.id,
      novelTitle: scope?.envelope.novel.title,
      section: scope?.envelope.page.section,
      view: scope?.envelope.page.view,
      modal: scope?.envelope.page.modal,
      entityTitle: scope?.envelope.entity?.title,
      contextRevision: store.contextRevision,
      fieldCount: store.fieldCount,
      dirtyFieldCount: store.dirtyFieldCount,
      selectionCharacters: store.selectionCharacters,
      preparation: this.preparation,
      truncated: this.truncated,
      disposed: this.disposed,
    };
  }

  subscribe(listener: AssistantContextRuntimeListener): () => void {
    this.assertActive();
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  clear(): void {
    this.assertActive();
    this.clearScopes();
    this.preparation = "idle";
    this.truncated = false;
    this.revisionFloor += 1;
    this.emit();
  }

  dispose(): void {
    if (this.disposed) return;
    this.clearScopes();
    this.disposed = true;
    this.preparation = "idle";
    this.emit();
    this.listeners.clear();
  }

  private activeScope(): RuntimeScope | undefined {
    while (this.stack.length > 0) {
      const id = this.stack[this.stack.length - 1];
      const scope = this.scopes.get(id);
      if (scope) return scope;
      this.stack.pop();
    }
    return undefined;
  }

  private disposeScope(id: string): void {
    const scope = this.scopes.get(id);
    if (!scope) return;
    scope.unsubscribe();
    scope.store.dispose();
    this.scopes.delete(id);
    const index = this.stack.lastIndexOf(id);
    if (index >= 0) this.stack.splice(index, 1);
    this.revisionFloor += 1;
    const active = this.activeScope();
    active?.store.setRevisionFloor(this.revisionFloor);
    this.preparation = active ? "settling" : "idle";
    this.truncated = false;
    this.emit();
  }

  private clearScopes(): void {
    const scopes = [...this.scopes.values()];
    this.scopes.clear();
    this.stack.length = 0;
    for (const scope of scopes) {
      scope.unsubscribe();
      scope.store.dispose();
    }
  }

  private emit(): void {
    const status = this.getStatus();
    for (const listener of this.listeners) listener(status);
  }

  private assertActive(): void {
    if (this.disposed) throw new Error("assistant context runtime is disposed");
  }
}


export const assistantContextRuntime = new NovelAssistantContextRuntime();
