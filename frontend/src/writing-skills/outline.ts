/** Managed outline generation adapter with novel-scoped recovery. */
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

export const OUTLINE_METHOD_KINDS = [
  "outline_background",
  "outline_characters",
  "outline_plot",
  "outline_highlight",
] as const;
export type OutlineMethodKind = typeof OUTLINE_METHOD_KINDS[number];

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export interface OutlineMethodCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly displayNames: Readonly<Record<string, string>>;
  readonly binding: WritingActionBinding;
  readonly outlineDraftId: string;
  readonly outlineDraftVersion: number;
  readonly kind: OutlineMethodKind;
}

export async function outlineMethodCatalog(
  novelId: string,
  outlineDraftId: string,
  outlineDraftVersion: number,
  kind: OutlineMethodKind,
  tabId: string,
  request: Request = apiRequest,
): Promise<OutlineMethodCatalog> {
  if (!Number.isSafeInteger(outlineDraftVersion) || outlineDraftVersion < 1) {
    throw new Error("大纲草稿版本无效");
  }
  const query = new URLSearchParams({
    novel_id: novelId,
    creative_kind: kind,
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
    throw new Error("大纲写作方法目录或小说范围无法确认");
  }
  const names: Record<string, string> = {};
  for (const raw of data.capabilities) {
    const item = record(raw);
    if (!item || typeof item.skill_id !== "string"
      || !/^[a-z][a-z0-9-]{0,63}$/.test(item.skill_id)
      || typeof item.display_name !== "string" || !item.display_name
      || item.display_name.length > 80
      || Object.prototype.hasOwnProperty.call(names, item.skill_id)) {
      throw new Error("大纲写作方法目录格式错误");
    }
    names[item.skill_id] = item.display_name;
  }
  if (data.catalog_available !== undefined
    && typeof data.catalog_available !== "boolean") {
    throw new Error("大纲写作方法目录状态无效");
  }
  const catalogAvailable = data.catalog_available !== false;
  if (data.novel_creative_available && !catalogAvailable) {
    throw new Error("大纲写作方法目录状态矛盾");
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
    outlineDraftId,
    outlineDraftVersion,
    kind,
  };
}

export interface OutlineMethodInput {
  readonly kind: OutlineMethodKind;
  readonly expected_scope_version: number;
  readonly input_snapshot: Readonly<Record<string, unknown>>;
  readonly force_new: boolean;
  readonly method_mode?: "auto" | "generic_only";
}

export type OutlineMethodResult = ManagedCreativeResult;

export class OutlineMethodClient {
  private readonly core: ManagedCreativeMethodClient;

  constructor(
    readonly catalog: OutlineMethodCatalog,
    request: Request = apiRequest,
    storage?: TicketStorage,
  ) {
    this.core = new ManagedCreativeMethodClient(
      catalog,
      {
        ticketNamespace: `anw-outline-action/1:${catalog.kind}:v${catalog.outlineDraftVersion}`,
        allowedKinds: new Set(OUTLINE_METHOD_KINDS),
        validateScope: input => (
          input.scope_type === "outline"
          && input.scope_id === catalog.outlineDraftId
          && input.novel_id === catalog.binding.scopeId
          && input.document_id === undefined
          && input.kind === catalog.kind
          && input.expected_scope_version === catalog.outlineDraftVersion
        ),
        validateResultScope: result => (
          result.scope_id === catalog.outlineDraftId
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

  start(input: OutlineMethodInput): Promise<OutlineMethodResult> {
    return this.core.start({
      scope_type: "outline",
      scope_id: this.catalog.outlineDraftId,
      novel_id: this.catalog.binding.scopeId,
      kind: input.kind,
      input_snapshot: input.input_snapshot,
      expected_scope_version: input.expected_scope_version,
      force_new: input.force_new,
      method_mode: input.method_mode,
    });
  }

  recover(): Promise<OutlineMethodResult> { return this.core.recover(); }
}
