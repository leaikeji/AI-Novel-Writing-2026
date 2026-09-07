/** Managed chapter-body selection edits with exact draft and action recovery. */
import {
  ApiError,
  apiRequest,
  startCreativeGeneration,
  type StartCreativeGenerationPayload,
} from "../api";
import type { CreativeGenerationRecord } from "../types";
import {
  isWritingActionId,
  type WritingActionBinding,
  type WritingMethodStatus,
} from "./contracts";
import {
  ManagedCreativeMethodClient,
  type CreativeMethodRequest,
  type CreativeMethodTicketStorage,
  type ManagedCreativeResult,
} from "./creative-client";
import { writingPageTabId } from "./creative-client";

type Operation = "polish" | "rewrite" | "expand" | "shorten" | "dialogue" | "review" | "custom";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function operation(value: unknown): Operation | null {
  return ["polish", "rewrite", "expand", "shorten", "dialogue", "review", "custom"]
    .includes(String(value)) ? value as Operation : null;
}

export interface SelectionMethodCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly binding: WritingActionBinding;
  readonly documentId: string;
  readonly draftVersion: number;
  readonly fieldValueHash: string;
  readonly selectionId: string;
  readonly operation: Operation;
}

export async function selectionMethodCatalog(
  novelId: string,
  documentId: string,
  draftVersion: number,
  fieldValueHash: string,
  selectionId: string,
  selectedOperation: Operation,
  tabId: string,
  request: CreativeMethodRequest = apiRequest,
): Promise<SelectionMethodCatalog> {
  if (!Number.isSafeInteger(draftVersion) || draftVersion < 1
    || !/^[a-f0-9]{64}$/.test(fieldValueHash)
    || !isWritingActionId(selectionId)) {
    throw new Error("选区正文版本、哈希或选区标识无效");
  }
  const query = new URLSearchParams({
    document_id: documentId,
    creative_kind: "selection_edit",
    selection_operation: selectedOperation,
    tab_id: tabId,
  });
  const data = record(await request<unknown>(`/writing-skills?${query}`));
  const scope = record(data?.scope);
  if (data?.schema_version !== "writing-skill-catalog/1"
    || data.agent_id !== "ai-novel-writer"
    || typeof data.document_creative_available !== "boolean"
    || data.semantic_available !== false
    || !Array.isArray(data.capabilities)
    || !scope
    || scope.kind !== "novel"
    || scope.scope_id !== novelId
    || scope.document_id !== documentId
    || scope.tab_id !== tabId
    || !isWritingActionId(scope.owner_id)
    || !isWritingActionId(scope.workspace_id)) {
    throw new Error("选区写作方法目录或正文范围无法确认");
  }
  if (data.catalog_available !== undefined
    && typeof data.catalog_available !== "boolean") {
    throw new Error("选区写作方法目录状态无效");
  }
  const catalogAvailable = data.catalog_available !== false;
  if (data.document_creative_available && !catalogAvailable) {
    throw new Error("选区写作方法目录状态矛盾");
  }
  return {
    available: data.document_creative_available,
    catalogAvailable,
    binding: Object.freeze({
      ownerKey: scope.owner_id,
      workspaceKey: scope.workspace_id,
      tabId,
      agentId: "ai-novel-writer",
      scopeKind: "novel",
      scopeId: novelId,
      documentId,
    }),
    documentId,
    draftVersion,
    fieldValueHash,
    selectionId,
    operation: selectedOperation,
  };
}

class SelectionMethodClient {
  private readonly core: ManagedCreativeMethodClient;

  constructor(
    readonly catalog: SelectionMethodCatalog,
    request: CreativeMethodRequest,
    storage?: CreativeMethodTicketStorage,
  ) {
    this.core = new ManagedCreativeMethodClient(
      catalog,
      {
        ticketNamespace: [
          "anw-selection-action/1",
          catalog.documentId,
          `v${catalog.draftVersion}`,
          catalog.fieldValueHash,
          catalog.selectionId,
          catalog.operation,
        ].join(":"),
        allowedKinds: new Set(["selection_edit"]),
        validateScope: input => (
          input.scope_type === "document"
          && input.scope_id === catalog.documentId
          && input.novel_id === catalog.binding.scopeId
          && input.document_id === catalog.documentId
          && input.kind === "selection_edit"
          && input.expected_scope_version === catalog.draftVersion
        ),
        validateResultScope: result => (
          result.scope_id === catalog.documentId
          && result.document_id === catalog.documentId
          && result.novel_id === catalog.binding.scopeId
          && result.kind === "selection_edit"
        ),
        recoveryPath: (_binding, actionId) => (
          `/documents/${catalog.documentId}/writing-method-actions/${actionId}`
        ),
      },
      request,
      storage,
    );
  }

  get currentStatus(): WritingMethodStatus | null { return this.core.currentStatus; }
  get hasRecoveryTicket(): boolean { return this.core.hasRecoveryTicket; }

  start(payload: StartCreativeGenerationPayload): Promise<ManagedCreativeResult> {
    return this.core.start({
      scope_type: "document",
      scope_id: this.catalog.documentId,
      kind: "selection_edit",
      input_snapshot: payload.input_snapshot,
      novel_id: this.catalog.binding.scopeId,
      document_id: this.catalog.documentId,
      target_character_count: null,
      force_new: payload.force_new,
      expected_scope_version: this.catalog.draftVersion,
    });
  }

  recover(): Promise<ManagedCreativeResult> { return this.core.recover(); }
}

function managedSnapshot(payload: StartCreativeGenerationPayload) {
  const target = record(payload.input_snapshot.target);
  const base = record(payload.input_snapshot.base);
  const selectedOperation = operation(payload.input_snapshot.operation);
  if (target?.entity_type !== "document" || target.field_id !== "chapter.body"
    || target.persistence !== "autosave" || !base || !selectedOperation
    || base.persistence_version_kind !== "draft"
    || !Number.isSafeInteger(base.persistence_version)
    || typeof base.field_value_sha256 !== "string"
    || !/^[a-f0-9]{64}$/.test(base.field_value_sha256)
    || !isWritingActionId(payload.input_snapshot.selection_id)
    || !payload.document_id) return null;
  return {
    draftVersion: Number(base.persistence_version),
    fieldValueHash: base.field_value_sha256,
    selectionId: payload.input_snapshot.selection_id,
    operation: selectedOperation,
  } as const;
}

export interface SelectionEditMethodGenerationClientOptions {
  readonly tabId?: string;
  readonly request?: CreativeMethodRequest;
  readonly storage?: CreativeMethodTicketStorage;
}

/** Preserve legacy entity selections; release managed routing only for body text. */
export class SelectionEditMethodGenerationClient {
  private readonly clients = new Map<string, SelectionMethodClient>();
  private readonly pending = new Map<string, Promise<CreativeGenerationRecord>>();
  private readonly tabId: string;
  private readonly request: CreativeMethodRequest;
  private readonly storage?: CreativeMethodTicketStorage;
  private status: WritingMethodStatus | null = null;

  constructor(options: SelectionEditMethodGenerationClientOptions = {}) {
    this.storage = options.storage ?? globalThis.sessionStorage;
    this.tabId = options.tabId ?? writingPageTabId(this.storage);
    this.request = options.request ?? apiRequest;
  }

  get currentStatus(): WritingMethodStatus | null { return this.status; }

  start(
    payload: StartCreativeGenerationPayload,
    signal?: AbortSignal,
  ): Promise<CreativeGenerationRecord> {
    const frozen = managedSnapshot(payload);
    if (!frozen) return startCreativeGeneration(payload, signal);
    const key = JSON.stringify([
      payload.novel_id,
      payload.document_id,
      frozen.draftVersion,
      frozen.fieldValueHash,
      frozen.selectionId,
      frozen.operation,
      payload.force_new,
    ]);
    const current = this.pending.get(key);
    if (current) return current;
    const running = this.startManaged(payload, frozen).finally(() => {
      if (this.pending.get(key) === running) this.pending.delete(key);
    });
    this.pending.set(key, running);
    return running;
  }

  private async startManaged(
    payload: StartCreativeGenerationPayload,
    frozen: NonNullable<ReturnType<typeof managedSnapshot>>,
  ): Promise<CreativeGenerationRecord> {
    const catalog = await selectionMethodCatalog(
      payload.novel_id,
      String(payload.document_id),
      frozen.draftVersion,
      frozen.fieldValueHash,
      frozen.selectionId,
      frozen.operation,
      this.tabId,
      this.request,
    );
    const clientKey = JSON.stringify([
      payload.novel_id,
      payload.document_id,
      frozen.draftVersion,
      frozen.fieldValueHash,
      frozen.selectionId,
      frozen.operation,
    ]);
    let client = this.clients.get(clientKey);
    if (!client) {
      client = new SelectionMethodClient(catalog, this.request, this.storage);
      this.clients.set(clientKey, client);
    }
    this.status = null;
    let result: ManagedCreativeResult;
    try {
      if (client.hasRecoveryTicket && client.currentStatus === null) {
        result = await client.recover();
      } else {
        result = await client.start(payload);
      }
    } catch (error) {
      this.status = client.currentStatus;
      const shouldRecover = client.hasRecoveryTicket
        && (!(error instanceof ApiError) || error.status >= 500);
      if (!shouldRecover) throw error;
      try {
        result = await client.recover();
      } catch {
        throw error;
      }
    }
    this.status = result.writing_method;
    if (result.state === "method_pending" || !("id" in result)) {
      throw new Error("选区写作任务尚未关联生成结果，请稍后只读恢复");
    }
    return result as CreativeGenerationRecord;
  }
}
