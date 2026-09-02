import {
  NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS,
  NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS,
  NOVEL_ASSISTANT_CONTEXT_SCHEMA_VERSION,
  type EditableFieldSnapshot,
  type NovelAssistantContextEnvelope,
  type NovelAssistantContextV2,
  type NovelAssistantSelectionSnapshot,
  validateNovelAssistantContextV2,
} from "./assistant-context-schema";
import {
  EditableFieldRegistry,
  type EditableFieldAdapter,
  type EditableFieldRegistration,
} from "./assistant-fields";
import type { StoryLedgerAssistantContextV1 } from "./story-ledger/assistant-context";


const TRUNCATION_MARKER = "\n…[已截断]…\n";


export type NovelAssistantContextStoreChange =
  | "binding"
  | "location"
  | "field-register"
  | "field-dispose"
  | "field-focus"
  | "field-change"
  | "selection"
  | "selection-expired"
  | "revision-sync"
  | "dispose";


export interface NovelAssistantContextStoreStatus {
  contextRevision: number;
  agentId: string;
  sessionId?: string;
  fieldCount: number;
  focusedFieldId?: string;
  dirtyFieldCount: number;
  selectionCharacters: number;
  disposed: boolean;
}


export interface NovelAssistantContextCapture {
  context: NovelAssistantContextV2;
  serialized: string;
}


export interface NovelAssistantContextStoreOptions {
  agentId: string;
  sessionId?: string;
  envelope: NovelAssistantContextEnvelope;
  now?: () => number;
  ttlMs?: number;
}


export type NovelAssistantContextStoreListener = (
  status: NovelAssistantContextStoreStatus,
  change: NovelAssistantContextStoreChange,
) => void;


function requireNonEmpty(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} must not be empty`);
  return normalized;
}


function boundedTtl(ttlMs: number | undefined): number {
  if (ttlMs === undefined) return NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS;
  if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
    throw new Error("context ttl must be positive");
  }
  return Math.min(Math.round(ttlMs), NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS);
}


function stableUsedCharacters(context: NovelAssistantContextV2): string {
  let serialized = "";
  for (let attempt = 0; attempt < 4; attempt += 1) {
    serialized = JSON.stringify(context);
    if (context.budget.usedCharacters === serialized.length) return serialized;
    context.budget.usedCharacters = serialized.length;
  }
  return JSON.stringify(context);
}


function serializedUpperBound(context: NovelAssistantContextV2): number {
  const previous = context.budget.usedCharacters;
  context.budget.usedCharacters = NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS;
  const length = JSON.stringify(context).length;
  context.budget.usedCharacters = previous;
  return length;
}


function truncateMiddle(value: string, maximum: number): string {
  if (value.length <= maximum) return value;
  if (maximum <= 0) return "";
  if (maximum <= TRUNCATION_MARKER.length) return value.slice(0, maximum);
  const available = maximum - TRUNCATION_MARKER.length;
  const head = Math.ceil(available / 2);
  const tail = Math.floor(available / 2);
  return `${value.slice(0, head)}${TRUNCATION_MARKER}${value.slice(value.length - tail)}`;
}


function cloneEnvelope(envelope: NovelAssistantContextEnvelope): NovelAssistantContextEnvelope {
  return {
    agentId: envelope.agentId,
    novel: { ...envelope.novel },
    page: { ...envelope.page },
    entity: envelope.entity ? { ...envelope.entity } : undefined,
    document: envelope.document ? { ...envelope.document } : undefined,
    ledger: envelope.ledger ? cloneLedgerContext(envelope.ledger) : undefined,
  };
}


function cloneLedgerContext(
  context: StoryLedgerAssistantContextV1,
): StoryLedgerAssistantContextV1 {
  return {
    ...context,
    novel: { ...context.novel },
    timeline: { ...context.timeline },
    filters: {
      ...context.filters,
      fact_types: [...context.filters.fact_types],
    },
    summary: {
      ...context.summary,
      by_fact_type: { ...context.summary.by_fact_type },
      by_effective_state: { ...context.summary.by_effective_state },
      by_health: { ...context.summary.by_health },
    },
    selected_fact: context.selected_fact
      ? {
          ...context.selected_fact,
          entity_labels: [...context.selected_fact.entity_labels],
          effective_reason_codes: [...context.selected_fact.effective_reason_codes],
          health_reason_codes: [...context.selected_fact.health_reason_codes],
          source: context.selected_fact.source
            ? { ...context.selected_fact.source }
            : null,
        }
      : null,
    budget: { ...context.budget },
  };
}


/**
 * Page-scoped registry for the frozen V2 context protocol.
 *
 * The live store keeps field adapters/getters rather than copies of long text.
 * `capture()` is the only point that materialises an immutable, budgeted wire
 * snapshot for one user send.
 */
export class NovelAssistantContextStore {
  readonly fields = new EditableFieldRegistry();

  private readonly listeners = new Set<NovelAssistantContextStoreListener>();
  private readonly now: () => number;
  private readonly ttlMs: number;
  private envelope: NovelAssistantContextEnvelope;
  private agentId: string;
  private sessionId: string | undefined;
  private selection: NovelAssistantSelectionSnapshot | undefined;
  private revision = 0;
  private disposed = false;

  constructor(options: NovelAssistantContextStoreOptions) {
    this.agentId = requireNonEmpty(options.agentId, "agent id");
    this.sessionId = options.sessionId
      ? requireNonEmpty(options.sessionId, "session id")
      : undefined;
    this.envelope = cloneEnvelope(options.envelope);
    if (this.envelope.agentId !== this.agentId) {
      throw new Error("context envelope agent does not match store binding");
    }
    this.now = options.now ?? Date.now;
    this.ttlMs = boundedTtl(options.ttlMs);
  }

  subscribe(listener: NovelAssistantContextStoreListener): () => void {
    this.assertActive();
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getStatus(): NovelAssistantContextStoreStatus {
    const adapters = this.fields.list();
    const activeSelection = this.activeSelection(false);
    return {
      contextRevision: this.revision,
      agentId: this.agentId,
      sessionId: this.sessionId,
      fieldCount: adapters.length,
      focusedFieldId: this.fields.snapshot().focusedFieldId,
      dirtyFieldCount: adapters.filter((adapter) => adapter.getDirty()).length,
      selectionCharacters: activeSelection?.text.length ?? 0,
      disposed: this.disposed,
    };
  }

  setBinding(agentId: string, sessionId?: string): void {
    this.assertActive();
    const nextAgentId = requireNonEmpty(agentId, "agent id");
    const nextSessionId = sessionId
      ? requireNonEmpty(sessionId, "session id")
      : undefined;
    if (nextAgentId === this.agentId && nextSessionId === this.sessionId) return;
    this.agentId = nextAgentId;
    this.sessionId = nextSessionId;
    this.envelope = { ...this.envelope, agentId: nextAgentId };
    this.selection = undefined;
    this.bump("binding");
  }

  /** Replace the page/entity/document scope and destroy all old field adapters. */
  replaceLocation(envelope: NovelAssistantContextEnvelope): void {
    this.assertActive();
    if (envelope.agentId !== this.agentId) {
      throw new Error("context envelope agent does not match store binding");
    }
    this.fields.clear();
    this.selection = undefined;
    this.envelope = cloneEnvelope(envelope);
    this.bump("location");
  }

  registerField(adapter: EditableFieldAdapter): EditableFieldRegistration {
    this.assertActive();
    const registration = this.fields.register(adapter);
    this.bump("field-register");
    let active = true;
    return {
      dispose: () => {
        if (!active) return;
        active = false;
        const wasRegistered = this.fields.get(adapter.id) === adapter;
        if (this.selection?.fieldId === adapter.id) this.selection = undefined;
        registration.dispose();
        if (wasRegistered && !this.disposed) this.bump("field-dispose");
      },
    };
  }

  setFocusedField(fieldId: string | undefined): void {
    this.assertActive();
    const currentFocusedFieldId = this.fields.snapshot().focusedFieldId;
    const selection = this.activeSelection(false);
    // Clicking the field-anchored toolbar or native assistant moves DOM focus,
    // but the selected editor remains the logical target until the selection
    // is changed, invalidated or applied.  Suppressing this blur transition
    // prevents the selection's frozen context revision from self-invalidating.
    if (
      fieldId === undefined
      && selection
      && currentFocusedFieldId === selection.fieldId
    ) {
      return;
    }
    if (currentFocusedFieldId === fieldId) return;
    this.fields.setFocused(fieldId);
    this.bump("field-focus");
  }

  notifyFieldChanged(fieldId: string): void {
    this.assertActive();
    if (!this.fields.get(fieldId)) {
      throw new Error(`editable field is not registered: ${fieldId}`);
    }
    if (this.selection?.fieldId === fieldId) this.selection = undefined;
    this.bump("field-change");
  }

  setSelection(selection: NovelAssistantSelectionSnapshot | undefined): void {
    this.assertActive();
    if (selection && !this.fields.get(selection.fieldId)) {
      throw new Error(`selection field is not registered: ${selection.fieldId}`);
    }
    if (selection && Date.parse(selection.expiresAt) <= this.now()) {
      throw new Error("selection is already expired");
    }
    this.revision += 1;
    this.selection = selection
      ? { ...selection, contextRevision: this.revision }
      : undefined;
    this.emit("selection");
  }

  expireSelection(): boolean {
    this.assertActive();
    if (!this.selection || Date.parse(this.selection.expiresAt) > this.now()) return false;
    this.selection = undefined;
    this.bump("selection-expired");
    return true;
  }

  setRevisionFloor(minimumRevision: number): void {
    this.assertActive();
    if (!Number.isSafeInteger(minimumRevision) || minimumRevision < 0) {
      throw new Error("context revision floor must be a non-negative safe integer");
    }
    if (this.revision >= minimumRevision) return;
    this.revision = minimumRevision;
    if (this.selection) {
      this.selection = { ...this.selection, contextRevision: this.revision };
    }
    this.emit("revision-sync");
  }

  capture(): NovelAssistantContextCapture {
    this.assertActive();
    const capturedAtMs = this.now();
    const capturedAt = new Date(capturedAtMs).toISOString();
    const expiresAt = new Date(capturedAtMs + this.ttlMs).toISOString();
    const adapters = this.fields.list();
    const focusedFieldId = this.fields.snapshot().focusedFieldId;
    const selection = this.activeSelection(true);

    const context: NovelAssistantContextV2 = {
      schemaVersion: NOVEL_ASSISTANT_CONTEXT_SCHEMA_VERSION,
      contextRevision: this.revision,
      capturedAt,
      expiresAt,
      agentId: this.agentId,
      sessionId: this.sessionId,
      novel: { ...this.envelope.novel },
      page: { ...this.envelope.page },
      entity: this.envelope.entity ? { ...this.envelope.entity } : undefined,
      document: this.envelope.document ? { ...this.envelope.document } : undefined,
      ledger: this.envelope.ledger
        ? cloneLedgerContext(this.envelope.ledger)
        : undefined,
      editing: adapters.length
        ? { focusedFieldId, fields: [] }
        : undefined,
      selection: selection ? { ...selection, contextRevision: this.revision } : undefined,
      budget: {
        maxCharacters: NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS,
        usedCharacters: 0,
        truncated: adapters.length > 0,
        omittedFieldIds: adapters.map((adapter) => adapter.id),
      },
    };

    if (serializedUpperBound(context) > NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS) {
      throw new Error("context location envelope exceeds the global budget");
    }

    const priority = [...adapters].sort((left, right) => {
      const rank = (adapter: EditableFieldAdapter): number => {
        if (adapter.id === selection?.fieldId) return 0;
        if (adapter.id === focusedFieldId && adapter.getDirty()) return 1;
        if (adapter.getDirty()) return 2;
        if (adapter.id === focusedFieldId) return 3;
        return 4;
      };
      return rank(left) - rank(right);
    });

    for (const adapter of priority) {
      const originalValue = adapter.getValue();
      const deduplicated = selection?.fieldId === adapter.id;
      const baseField: EditableFieldSnapshot = {
        id: adapter.id,
        label: adapter.label,
        value: deduplicated ? "" : originalValue,
        dirty: adapter.getDirty(),
        truncated: deduplicated,
        characterCount: originalValue.length,
        persistence: adapter.persistence,
      };

      const omittedIndex = context.budget.omittedFieldIds.indexOf(adapter.id);
      const tryCandidate = (value: string, truncated: boolean): boolean => {
        const candidate = { ...baseField, value, truncated };
        context.editing!.fields.push(candidate);
        if (omittedIndex >= 0) context.budget.omittedFieldIds.splice(omittedIndex, 1);
        const fits = serializedUpperBound(context) <= NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS;
        if (!fits) {
          context.editing!.fields.pop();
          if (omittedIndex >= 0) context.budget.omittedFieldIds.splice(omittedIndex, 0, adapter.id);
        }
        return fits;
      };

      if (tryCandidate(baseField.value, baseField.truncated)) continue;

      let low = 0;
      let high = deduplicated ? 0 : originalValue.length;
      let accepted = -1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        if (tryCandidate(truncateMiddle(originalValue, middle), true)) {
          accepted = middle;
          context.editing!.fields.pop();
          context.budget.omittedFieldIds.splice(omittedIndex, 0, adapter.id);
          low = middle + 1;
        } else {
          high = middle - 1;
        }
      }
      if (accepted >= 0) {
        tryCandidate(truncateMiddle(originalValue, accepted), true);
      }
    }

    context.budget.truncated = context.budget.omittedFieldIds.length > 0
      || context.editing?.fields.some((field) => field.truncated) === true;
    if (context.editing?.focusedFieldId
      && !context.editing.fields.some((field) => field.id === context.editing!.focusedFieldId)) {
      context.editing.focusedFieldId = undefined;
    }
    const serialized = stableUsedCharacters(context);
    const validation = validateNovelAssistantContextV2(context);
    if (!validation.ok) {
      throw new Error(`captured context failed validation: ${validation.reason}`);
    }
    return { context, serialized };
  }

  dispose(): void {
    if (this.disposed) return;
    this.fields.clear();
    this.selection = undefined;
    this.disposed = true;
    this.emit("dispose");
    this.listeners.clear();
  }

  private activeSelection(expire: boolean): NovelAssistantSelectionSnapshot | undefined {
    if (!this.selection) return undefined;
    if (Date.parse(this.selection.expiresAt) > this.now()) return this.selection;
    if (expire && !this.disposed) {
      this.selection = undefined;
      this.bump("selection-expired");
    }
    return undefined;
  }

  private bump(change: NovelAssistantContextStoreChange): void {
    this.revision += 1;
    this.emit(change);
  }

  private emit(change: NovelAssistantContextStoreChange): void {
    const status = this.getStatus();
    for (const listener of this.listeners) listener(status, change);
  }

  private assertActive(): void {
    if (this.disposed) throw new Error("context store is disposed");
  }
}
