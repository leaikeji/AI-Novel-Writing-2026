/** Managed chapter review with exact working-copy recovery. */
import { apiRequest } from "../api";
import {
  isWritingActionId,
  type WritingActionBinding,
  type WritingMethodStatus,
} from "./contracts";
import {
  ManagedCreativeMethodClient,
  type CreativeMethodRequest as Request,
  type CreativeMethodTicketStorage as TicketStorage,
  type ManagedCreativeResult,
} from "./creative-client";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export interface ReviewMethodCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly displayNames: Readonly<Record<string, string>>;
  readonly binding: WritingActionBinding;
  readonly documentId: string;
  readonly draftVersion: number;
  readonly contentHash: string;
}

export async function reviewMethodCatalog(
  novelId: string,
  documentId: string,
  draftVersion: number,
  contentHash: string,
  tabId: string,
  request: Request = apiRequest,
): Promise<ReviewMethodCatalog> {
  if (!Number.isSafeInteger(draftVersion) || draftVersion < 1
    || !/^[a-f0-9]{64}$/.test(contentHash)) {
    throw new Error("审稿正文版本或哈希无效");
  }
  const query = new URLSearchParams({
    document_id: documentId,
    creative_kind: "review",
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
    throw new Error("审稿写作方法目录或正文范围无法确认");
  }
  const names: Record<string, string> = {};
  for (const raw of data.capabilities) {
    const item = record(raw);
    if (!item || typeof item.skill_id !== "string"
      || !/^[a-z][a-z0-9-]{0,63}$/.test(item.skill_id)
      || typeof item.display_name !== "string" || !item.display_name
      || item.display_name.length > 80
      || Object.prototype.hasOwnProperty.call(names, item.skill_id)) {
      throw new Error("审稿写作方法目录格式错误");
    }
    names[item.skill_id] = item.display_name;
  }
  if (data.catalog_available !== undefined
    && typeof data.catalog_available !== "boolean") {
    throw new Error("审稿写作方法目录状态无效");
  }
  const catalogAvailable = data.catalog_available !== false;
  if (data.document_creative_available && !catalogAvailable) {
    throw new Error("审稿写作方法目录状态矛盾");
  }
  return {
    available: data.document_creative_available,
    catalogAvailable,
    displayNames: Object.freeze(names),
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
    contentHash,
  };
}

export interface ReviewMethodInput {
  readonly expected_scope_version: number;
  readonly input_snapshot: Readonly<Record<string, unknown>>;
  readonly force_new: boolean;
  readonly method_mode?: "auto" | "generic_only";
}

export class ReviewMethodClient {
  private readonly core: ManagedCreativeMethodClient;

  constructor(
    readonly catalog: ReviewMethodCatalog,
    request: Request = apiRequest,
    storage?: TicketStorage,
  ) {
    this.core = new ManagedCreativeMethodClient(
      catalog,
      {
        ticketNamespace: `anw-review-action/1:${catalog.documentId}:v${catalog.draftVersion}:${catalog.contentHash}`,
        allowedKinds: new Set(["review"]),
        validateScope: input => (
          input.scope_type === "document"
          && input.scope_id === catalog.documentId
          && input.novel_id === catalog.binding.scopeId
          && input.document_id === catalog.documentId
          && input.kind === "review"
          && input.expected_scope_version === catalog.draftVersion
        ),
        validateResultScope: result => result.scope_id === catalog.documentId,
        recoveryPath: (_binding, actionId) => (
          `/documents/${catalog.documentId}/writing-method-actions/${actionId}`
        ),
      },
      request,
      storage,
    );
  }

  get managedAvailable(): boolean { return this.core.managedAvailable; }

  get currentStatus(): WritingMethodStatus | null { return this.core.currentStatus; }

  get hasRecoveryTicket(): boolean { return this.core.hasRecoveryTicket; }

  clearRecovery(): void { this.core.clearRecovery(); }

  start(input: ReviewMethodInput): Promise<ManagedCreativeResult> {
    return this.core.start({
      scope_type: "document",
      scope_id: this.catalog.documentId,
      novel_id: this.catalog.binding.scopeId,
      document_id: this.catalog.documentId,
      kind: "review",
      input_snapshot: input.input_snapshot,
      expected_scope_version: input.expected_scope_version,
      force_new: input.force_new,
      method_mode: input.method_mode,
    });
  }

  recover(): Promise<ManagedCreativeResult> { return this.core.recover(); }
}
