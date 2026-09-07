/** Managed pre-novel template/naming adapter with read-only lost-response recovery. */
import { apiRequest } from "../api";
import {
  isWritingActionId,
  type WritingActionBinding,
  type WritingMethodStatus,
} from "./contracts";
import {
  ManagedCreativeMethodClient,
  writingPageTabId,
  type CreativeMethodRequest as Request,
  type CreativeMethodTicketStorage as TicketStorage,
  type ManagedCreativeResult,
} from "./creative-client";

export function creationPageTabId(
  storage: TicketStorage = sessionStorage,
): string {
  return writingPageTabId(storage);
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export interface CreationMethodCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly displayNames: Readonly<Record<string, string>>;
  readonly binding: WritingActionBinding;
}

export async function creationMethodCatalog(
  draftId: string,
  tabId: string,
  request: Request = apiRequest,
): Promise<CreationMethodCatalog> {
  const query = new URLSearchParams({ creation_draft_id: draftId, tab_id: tabId });
  const data = record(await request<unknown>(`/writing-skills?${query}`));
  const scope = record(data?.scope);
  if (data?.schema_version !== "writing-skill-catalog/1"
    || data.agent_id !== "ai-novel-writer"
    || typeof data.creation_helper_available !== "boolean"
    || data.semantic_available !== false
    || !Array.isArray(data.capabilities)
    || !scope
    || scope.kind !== "creation_draft"
    || scope.scope_id !== draftId
    || scope.document_id !== null
    || scope.tab_id !== tabId
    || !isWritingActionId(scope.owner_id)
    || !isWritingActionId(scope.workspace_id)) {
    throw new Error("建书写作方法目录或草稿范围无法确认");
  }
  const names: Record<string, string> = {};
  for (const raw of data.capabilities) {
    const item = record(raw);
    if (!item || typeof item.skill_id !== "string"
      || !/^[a-z][a-z0-9-]{0,63}$/.test(item.skill_id)
      || typeof item.display_name !== "string" || !item.display_name
      || item.display_name.length > 80
      || Object.prototype.hasOwnProperty.call(names, item.skill_id)) {
      throw new Error("建书写作方法目录格式错误");
    }
    names[item.skill_id] = item.display_name;
  }
  if (data.catalog_available !== undefined
    && typeof data.catalog_available !== "boolean") {
    throw new Error("建书写作方法目录状态无效");
  }
  const catalogAvailable = data.catalog_available !== false;
  if (data.creation_helper_available && !catalogAvailable) {
    throw new Error("建书写作方法目录状态矛盾");
  }
  return {
    available: data.creation_helper_available,
    catalogAvailable,
    displayNames: Object.freeze(names),
    binding: Object.freeze({
      ownerKey: scope.owner_id,
      workspaceKey: scope.workspace_id,
      tabId,
      agentId: "ai-novel-writer",
      scopeKind: "creation_draft",
      scopeId: draftId,
    }),
  };
}

export interface CreationMethodInput {
  readonly kind: "novel_template" | "novel_naming";
  readonly expected_scope_version: number;
  readonly input_snapshot: Readonly<Record<string, unknown>>;
  readonly force_new: boolean;
  readonly method_mode?: "auto" | "generic_only";
}

export type CreationMethodResult = ManagedCreativeResult;

export class CreationMethodClient {
  private readonly core: ManagedCreativeMethodClient;

  constructor(
    readonly catalog: CreationMethodCatalog,
    request: Request = apiRequest,
    storage?: TicketStorage,
  ) {
    this.core = new ManagedCreativeMethodClient(
      catalog,
      {
        ticketNamespace: "anw-creation-action/1",
        allowedKinds: new Set(["novel_template", "novel_naming"]),
        validateScope: input => (
          input.scope_type === "novel_creation"
          && input.scope_id === catalog.binding.scopeId
          && input.novel_id === undefined
          && input.document_id === undefined
        ),
        validateResultScope: result => (
          result.scope_id === catalog.binding.scopeId
        ),
        recoveryPath: (binding, actionId) => (
          `/creation-drafts/${binding.scopeId}/writing-method-actions/${actionId}`
        ),
      },
      request,
      storage,
    );
  }

  get managedAvailable(): boolean {
    return this.core.managedAvailable;
  }

  get currentStatus(): WritingMethodStatus | null { return this.core.currentStatus; }

  get hasRecoveryTicket(): boolean { return this.core.hasRecoveryTicket; }

  clearRecovery(): void {
    this.core.clearRecovery();
  }

  start(input: CreationMethodInput): Promise<CreationMethodResult> {
    return this.core.start({
      scope_type: "novel_creation",
      scope_id: this.catalog.binding.scopeId,
      kind: input.kind,
      input_snapshot: input.input_snapshot,
      expected_scope_version: input.expected_scope_version,
      force_new: input.force_new,
      method_mode: input.method_mode,
    });
  }

  recover(): Promise<CreationMethodResult> {
    return this.core.recover();
  }
}
