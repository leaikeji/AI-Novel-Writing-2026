import type {
  EditableFieldPersistence,
  EditableFieldSelectionDirection,
} from "./assistant-fields";
import {
  validateStoryLedgerAssistantContext,
  type StoryLedgerAssistantContextV1,
} from "./story-ledger/assistant-context";


export const NOVEL_ASSISTANT_CONTEXT_SCHEMA_VERSION = 2 as const;
export const NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS = 24_000;
export const NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS = 12_000;
export const NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS = 1_500;
export const NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS = 20 * 60 * 1_000;
export const NOVEL_ASSISTANT_CONTEXT_REF_MAX_TTL_MS = 5 * 60 * 1_000;
export const NOVEL_ASSISTANT_CONTEXT_SETTLE_MS = 400;


export const NOVEL_PAGE_SECTIONS = [
  "chapters",
  "outline",
  "roles",
  "clues",
  "settings",
  "ledger",
] as const;


export type NovelPageSection = typeof NOVEL_PAGE_SECTIONS[number];


export const NOVEL_PAGE_VIEWS = [
  "chapter-list",
  "chapter-editor",
  "title-editor",
  "chapter-outline-editor",
  "novel-outline",
  "character-list",
  "character-editor",
  "relationship-graph",
  "relationship-editor",
  "clue-list",
  "storyline-editor",
  "foreshadow-editor",
  "novel-settings",
  "story-ledger",
] as const;


export type NovelPageView = typeof NOVEL_PAGE_VIEWS[number];


export const NOVEL_ENTITY_TYPES = [
  "novel",
  "volume",
  "document",
  "outline",
  "character",
  "relationship",
  "storyline",
  "foreshadow",
  "setting",
] as const;


export type NovelEntityType = typeof NOVEL_ENTITY_TYPES[number];


export interface EditableFieldSnapshot {
  id: string;
  label: string;
  value: string;
  dirty: boolean;
  truncated: boolean;
  characterCount: number;
  persistence: EditableFieldPersistence;
}


export interface NovelAssistantSelectionSnapshot {
  id: string;
  fieldId: string;
  text: string;
  startUtf16: number;
  endUtf16: number;
  direction: EditableFieldSelectionDirection;
  before: string;
  after: string;
  sourceValueSha256: string;
  contextRevision: number;
  createdAt: string;
  expiresAt: string;
}


export interface NovelAssistantContextV2 {
  schemaVersion: typeof NOVEL_ASSISTANT_CONTEXT_SCHEMA_VERSION;
  contextRevision: number;
  capturedAt: string;
  expiresAt: string;
  agentId: string;
  sessionId?: string;
  novel: { id: string; title: string };
  page: {
    section: NovelPageSection;
    view: NovelPageView;
    modal?: NovelPageView;
  };
  entity?: {
    type: NovelEntityType;
    id?: string;
    title?: string;
  };
  document?: {
    id: string;
    volumeId?: string;
    kind: string;
    chapterNumber?: number;
    title: string;
    draftVersion: number;
    savedContentHash: string;
    dirty: boolean;
  };
  ledger?: StoryLedgerAssistantContextV1;
  editing?: {
    focusedFieldId?: string;
    fields: EditableFieldSnapshot[];
  };
  selection?: NovelAssistantSelectionSnapshot;
  budget: {
    maxCharacters: number;
    usedCharacters: number;
    truncated: boolean;
    omittedFieldIds: string[];
  };
}


export interface NovelAssistantContextEnvelope {
  agentId: string;
  novel: NovelAssistantContextV2["novel"];
  page: NovelAssistantContextV2["page"];
  entity?: NovelAssistantContextV2["entity"];
  document?: NovelAssistantContextV2["document"];
  ledger?: StoryLedgerAssistantContextV1;
}


export type NovelAssistantContextValidationReason =
  | "not-object"
  | "unsupported-schema"
  | "invalid-revision"
  | "invalid-time-window"
  | "invalid-agent"
  | "invalid-novel"
  | "invalid-page"
  | "invalid-entity"
  | "invalid-document"
  | "invalid-ledger"
  | "invalid-editing"
  | "invalid-selection"
  | "invalid-budget"
  | "oversized";


export type NovelAssistantContextValidationResult =
  | { ok: true; context: NovelAssistantContextV2; serialized: string }
  | { ok: false; reason: NovelAssistantContextValidationReason };


const SHA256_PATTERN = /^[0-9a-f]{64}$/i;


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}


function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}


function oneOf<T extends readonly string[]>(
  value: unknown,
  choices: T,
): value is T[number] {
  return typeof value === "string" && choices.includes(value as T[number]);
}


function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}


function safeNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}


function validateDocument(value: unknown): boolean {
  if (value === undefined) return true;
  if (!isRecord(value)) return false;
  return nonEmpty(value.id)
    && (value.volumeId === undefined || nonEmpty(value.volumeId))
    && nonEmpty(value.kind)
    && (value.chapterNumber === undefined || safeNonNegativeInteger(value.chapterNumber))
    && typeof value.title === "string"
    && safeNonNegativeInteger(value.draftVersion)
    && typeof value.savedContentHash === "string"
    && typeof value.dirty === "boolean";
}


function validateEntity(value: unknown): boolean {
  if (value === undefined) return true;
  if (!isRecord(value) || !oneOf(value.type, NOVEL_ENTITY_TYPES)) return false;
  return (value.id === undefined || nonEmpty(value.id))
    && (value.title === undefined || typeof value.title === "string");
}


function validateEditing(value: unknown): boolean {
  if (value === undefined) return true;
  if (!isRecord(value) || !Array.isArray(value.fields)) return false;
  if (value.focusedFieldId !== undefined && !nonEmpty(value.focusedFieldId)) {
    return false;
  }
  const ids = new Set<string>();
  for (const field of value.fields) {
    if (!isRecord(field)
      || !nonEmpty(field.id)
      || ids.has(field.id)
      || !nonEmpty(field.label)
      || typeof field.value !== "string"
      || typeof field.dirty !== "boolean"
      || typeof field.truncated !== "boolean"
      || !safeNonNegativeInteger(field.characterCount)
      || (field.persistence !== "autosave" && field.persistence !== "explicit-save")) {
      return false;
    }
    ids.add(field.id);
  }
  return value.focusedFieldId === undefined || ids.has(value.focusedFieldId as string);
}


function validateSelection(value: unknown, revision: number): boolean {
  if (value === undefined) return true;
  if (!isRecord(value)) return false;
  if (!nonEmpty(value.id)
    || !nonEmpty(value.fieldId)
    || typeof value.text !== "string"
    || value.text.length > NOVEL_ASSISTANT_SELECTION_MAX_CHARACTERS
    || !safeNonNegativeInteger(value.startUtf16)
    || !safeNonNegativeInteger(value.endUtf16)
    || (value.endUtf16 as number) <= (value.startUtf16 as number)
    || !oneOf(value.direction, ["forward", "backward", "none"] as const)
    || typeof value.before !== "string"
    || typeof value.after !== "string"
    || value.before.length > NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS
    || value.after.length > NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS
    || typeof value.sourceValueSha256 !== "string"
    || !SHA256_PATTERN.test(value.sourceValueSha256)
    || value.contextRevision !== revision
    || !validTimestamp(value.createdAt)
    || !validTimestamp(value.expiresAt)) {
    return false;
  }
  const createdAt = Date.parse(value.createdAt as string);
  const expiresAt = Date.parse(value.expiresAt as string);
  return expiresAt > createdAt
    && expiresAt - createdAt <= NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS;
}


function validateBudget(value: unknown): boolean {
  if (!isRecord(value)
    || value.maxCharacters !== NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS
    || !safeNonNegativeInteger(value.usedCharacters)
    || (value.usedCharacters as number) > NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS
    || typeof value.truncated !== "boolean"
    || !Array.isArray(value.omittedFieldIds)) {
    return false;
  }
  const ids = value.omittedFieldIds;
  return ids.every(nonEmpty) && new Set(ids).size === ids.length;
}


/** Validate the frozen V2 wire schema without coercing or silently repairing it. */
export function validateNovelAssistantContextV2(
  value: unknown,
): NovelAssistantContextValidationResult {
  if (!isRecord(value)) return { ok: false, reason: "not-object" };
  if (value.schemaVersion !== NOVEL_ASSISTANT_CONTEXT_SCHEMA_VERSION) {
    return { ok: false, reason: "unsupported-schema" };
  }
  if (!safeNonNegativeInteger(value.contextRevision)) {
    return { ok: false, reason: "invalid-revision" };
  }
  if (!validTimestamp(value.capturedAt) || !validTimestamp(value.expiresAt)) {
    return { ok: false, reason: "invalid-time-window" };
  }
  const capturedAt = Date.parse(value.capturedAt as string);
  const expiresAt = Date.parse(value.expiresAt as string);
  if (expiresAt <= capturedAt
    || expiresAt - capturedAt > NOVEL_ASSISTANT_CONTEXT_MAX_TTL_MS) {
    return { ok: false, reason: "invalid-time-window" };
  }
  if (!nonEmpty(value.agentId)
    || (value.sessionId !== undefined && !nonEmpty(value.sessionId))) {
    return { ok: false, reason: "invalid-agent" };
  }
  if (!isRecord(value.novel)
    || !nonEmpty(value.novel.id)
    || !nonEmpty(value.novel.title)) {
    return { ok: false, reason: "invalid-novel" };
  }
  if (!isRecord(value.page)
    || !oneOf(value.page.section, NOVEL_PAGE_SECTIONS)
    || !oneOf(value.page.view, NOVEL_PAGE_VIEWS)
    || (value.page.modal !== undefined && !oneOf(value.page.modal, NOVEL_PAGE_VIEWS))
    || ((value.page.section === "ledger") !== (value.page.view === "story-ledger"))) {
    return { ok: false, reason: "invalid-page" };
  }
  if (!validateEntity(value.entity)) {
    return { ok: false, reason: "invalid-entity" };
  }
  if (!validateDocument(value.document)) {
    return { ok: false, reason: "invalid-document" };
  }
  const isLedgerPage = value.page.section === "ledger"
    && value.page.view === "story-ledger";
  if (isLedgerPage !== (value.ledger !== undefined)
    || (value.ledger !== undefined
      && (!validateStoryLedgerAssistantContext(value.ledger)
        || value.ledger.novel.id !== value.novel.id
        || value.ledger.novel.title !== value.novel.title))) {
    return { ok: false, reason: "invalid-ledger" };
  }
  if (!validateEditing(value.editing)) {
    return { ok: false, reason: "invalid-editing" };
  }
  if (!validateSelection(value.selection, value.contextRevision as number)) {
    return { ok: false, reason: "invalid-selection" };
  }
  if (!validateBudget(value.budget)) {
    return { ok: false, reason: "invalid-budget" };
  }

  let serialized: string;
  try {
    serialized = JSON.stringify(value);
  } catch {
    return { ok: false, reason: "not-object" };
  }
  if (serialized.length > NOVEL_ASSISTANT_CONTEXT_MAX_CHARACTERS) {
    return { ok: false, reason: "oversized" };
  }
  return {
    ok: true,
    context: value as unknown as NovelAssistantContextV2,
    serialized,
  };
}
