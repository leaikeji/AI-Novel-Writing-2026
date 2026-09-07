/** Managed, evidence-backed character profile completion adapter. */
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

export interface CharacterProfileMethodCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly displayNames: Readonly<Record<string, string>>;
  readonly binding: WritingActionBinding;
}

export async function characterProfileMethodCatalog(
  novelId: string,
  tabId: string,
  request: Request = apiRequest,
): Promise<CharacterProfileMethodCatalog> {
  const query = new URLSearchParams({
    novel_id: novelId,
    creative_kind: "character_profile_completion",
    tab_id: tabId,
  });
  const data = record(await request<unknown>(`/writing-skills?${query}`));
  const scope = record(data?.scope);
  if (data?.schema_version !== "writing-skill-catalog/1"
    || data.agent_id !== "ai-novel-writer"
    || typeof data.novel_creative_available !== "boolean"
    || data.semantic_available !== false
    || !Array.isArray(data.capabilities)
    || !scope
    || scope.kind !== "novel"
    || scope.scope_id !== novelId
    || scope.document_id !== null
    || scope.tab_id !== tabId
    || !isWritingActionId(scope.owner_id)
    || !isWritingActionId(scope.workspace_id)) {
    throw new Error("人物写作方法目录或小说范围无法确认");
  }
  const names: Record<string, string> = {};
  for (const raw of data.capabilities) {
    const item = record(raw);
    if (!item || typeof item.skill_id !== "string"
      || !/^[a-z][a-z0-9-]{0,63}$/.test(item.skill_id)
      || typeof item.display_name !== "string" || !item.display_name
      || item.display_name.length > 80
      || Object.prototype.hasOwnProperty.call(names, item.skill_id)) {
      throw new Error("人物写作方法目录格式错误");
    }
    names[item.skill_id] = item.display_name;
  }
  const catalogAvailable = data.catalog_available !== false;
  if (data.novel_creative_available && !catalogAvailable) {
    throw new Error("人物写作方法目录状态矛盾");
  }
  return {
    available: data.novel_creative_available,
    catalogAvailable,
    displayNames: Object.freeze(names),
    binding: Object.freeze({
      ownerKey: scope.owner_id,
      workspaceKey: scope.workspace_id,
      tabId,
      agentId: "ai-novel-writer",
      scopeKind: "novel",
      scopeId: novelId,
    }),
  };
}

export class CharacterProfileMethodClient {
  private readonly core: ManagedCreativeMethodClient;

  constructor(
    readonly catalog: CharacterProfileMethodCatalog,
    request: Request = apiRequest,
    storage?: TicketStorage,
  ) {
    this.core = new ManagedCreativeMethodClient(
      catalog,
      {
        ticketNamespace: "anw-character-profile-action/1",
        allowedKinds: new Set(["character_profile_completion"]),
        requireExpectedScopeVersion: false,
        validateScope: input => (
          input.scope_type === "novel"
          && input.scope_id === catalog.binding.scopeId
          && input.novel_id === catalog.binding.scopeId
          && input.document_id === undefined
          && input.kind === "character_profile_completion"
          && input.expected_scope_version === undefined
        ),
        validateResultScope: result => (
          result.scope_id === catalog.binding.scopeId
          && result.kind === "character_profile_completion"
        ),
        recoveryPath: (binding, actionId) => (
          `/novels/${binding.scopeId}/writing-method-actions/${actionId}`
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

  start(input: {
    readonly expectedSourceHash: string;
    readonly forceNew: boolean;
  }): Promise<ManagedCreativeResult> {
    if (!/^[a-f0-9]{64}$/.test(input.expectedSourceHash)) {
      return Promise.reject(new Error("人物资料来源摘要无效"));
    }
    return this.core.start({
      scope_type: "novel",
      scope_id: this.catalog.binding.scopeId,
      novel_id: this.catalog.binding.scopeId,
      kind: "character_profile_completion",
      input_snapshot: { expected_source_hash: input.expectedSourceHash },
      force_new: input.forceNew,
    });
  }

  recover(): Promise<ManagedCreativeResult> { return this.core.recover(); }
}
