/** Shared stable-action transport for managed creative helper buttons. */
import { ApiError, apiRequest } from "../api";
import type { CreativeGenerationRecord } from "../types";
import { createWritingAction } from "./api";
import {
  canAdvanceWritingMethodStatus,
  isWritingActionId,
  parseWritingMethodStatus,
  writingBindingKey,
  type WritingAction,
  type WritingActionBinding,
  type WritingMethodStatus,
} from "./contracts";

export type CreativeMethodRequest = <T>(
  path: string,
  init?: RequestInit,
) => Promise<T>;
export type CreativeMethodTicketStorage = Pick<Storage, "getItem" | "setItem">;

let pageTabId: string | null = null;

export function writingPageTabId(
  storage: CreativeMethodTicketStorage = sessionStorage,
): string {
  if (pageTabId) return pageTabId;
  const key = "anw-writing-tab/1";
  const navigation = performance.getEntriesByType("navigation")[0] as (
    PerformanceNavigationTiming | undefined
  );
  const previous = storage.getItem(key);
  const id = ["reload", "back_forward"].includes(navigation?.type ?? "")
    && isWritingActionId(previous)
    ? previous
    : crypto.randomUUID();
  storage.setItem(key, id);
  pageTabId = id;
  return id;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export interface ManagedCreativeCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly binding: WritingActionBinding;
}

export interface ManagedCreativeInput {
  readonly scope_type: string;
  readonly scope_id: string;
  readonly kind: string;
  readonly expected_scope_version?: number;
  readonly input_snapshot: Readonly<Record<string, unknown>>;
  readonly force_new: boolean;
  readonly novel_id?: string;
  readonly document_id?: string;
  readonly target_character_count?: number | null;
  readonly method_mode?: "auto" | "generic_only";
}

export type ManagedCreativeResult = (
  CreativeGenerationRecord | { readonly state: "method_pending" }
) & { readonly writing_method: WritingMethodStatus };

export interface ManagedCreativeClientOptions {
  readonly ticketNamespace: string;
  readonly allowedKinds: ReadonlySet<string>;
  readonly validateScope: (input: ManagedCreativeInput) => boolean;
  readonly validateResultScope: (result: Readonly<Record<string, unknown>>) => boolean;
  readonly recoveryPath: (
    binding: WritingActionBinding,
    actionId: string,
  ) => string;
  readonly requireExpectedScopeVersion?: boolean;
}

export class ManagedCreativeMethodClient {
  private action: WritingAction | null = null;
  private status: WritingMethodStatus | null = null;
  private jobState: string | null = null;
  private pending: Promise<ManagedCreativeResult> | null = null;
  private pendingInput = "";

  constructor(
    readonly catalog: ManagedCreativeCatalog,
    private readonly options: ManagedCreativeClientOptions,
    private readonly request: CreativeMethodRequest = apiRequest,
    private readonly storage?: CreativeMethodTicketStorage,
  ) {
    const saved = storage?.getItem(this.ticketKey());
    if (!saved) return;
    if (saved.length > 4096) throw new Error("原创作写作动作恢复记录无效");
    const value = record(JSON.parse(saved));
    const binding = record(value?.binding);
    if (!value || !binding || !isWritingActionId(value.action_id)
      || typeof value.inputFingerprint !== "string"
      || !/^[a-f0-9]{64}$/.test(value.inputFingerprint)
      || Object.entries(catalog.binding).some(
        ([key, expected]) => binding[key] !== expected
      )) {
      throw new Error("原创作写作动作恢复记录不属于当前范围");
    }
    this.action = Object.freeze({
      action_id: value.action_id,
      binding: catalog.binding,
      inputFingerprint: value.inputFingerprint,
    });
  }

  get managedAvailable(): boolean {
    return this.catalog.available && this.catalog.catalogAvailable;
  }

  get currentStatus(): WritingMethodStatus | null { return this.status; }

  get hasRecoveryTicket(): boolean { return this.action !== null; }

  clearRecovery(): void {
    this.action = null;
    this.status = null;
    this.jobState = null;
    this.storage?.setItem(this.ticketKey(), "");
  }

  start(input: ManagedCreativeInput): Promise<ManagedCreativeResult> {
    if (!this.managedAvailable) {
      return Promise.reject(new Error("受管创作写作入口尚未开放"));
    }
    if (!this.options.allowedKinds.has(input.kind)) {
      return Promise.reject(new Error("当前创作任务未获准受管执行"));
    }
    if ((this.options.requireExpectedScopeVersion ?? true)
      && (!Number.isSafeInteger(input.expected_scope_version)
        || (input.expected_scope_version ?? 0) < 1)) {
      return Promise.reject(new Error("创作范围版本无效"));
    }
    if (!(this.options.requireExpectedScopeVersion ?? true)
      && input.expected_scope_version !== undefined) {
      return Promise.reject(new Error("当前创作范围不接受整数版本"));
    }
    if (!this.options.validateScope(input)) {
      return Promise.reject(new Error("创作请求不属于当前写作范围"));
    }
    const mode = input.method_mode ?? "auto";
    if (!["auto", "generic_only"].includes(mode)) {
      return Promise.reject(new Error("本次写作方法模式无效"));
    }
    const encoded = JSON.stringify({ ...input, method_mode: mode });
    if (this.pending) {
      return encoded === this.pendingInput
        ? this.pending
        : Promise.reject(new Error("原创作操作仍在处理中"));
    }
    if (this.action && !["failed", "cancelled", "stale"].includes(
      this.status?.state ?? "",
    ) && !(this.status?.state === "dispatched"
      && ["ready", "failed"].includes(this.jobState ?? ""))) {
      return Promise.reject(new Error("原创作任务结果尚未确认，请先查询原任务"));
    }
    this.pendingInput = encoded;
    this.pending = this.send(input, mode, encoded).finally(() => {
      this.pending = null;
      this.pendingInput = "";
    });
    return this.pending;
  }

  private async send(
    input: ManagedCreativeInput,
    mode: "auto" | "generic_only",
    encoded: string,
  ): Promise<ManagedCreativeResult> {
    const digest = await crypto.subtle.digest(
      "SHA-256", new TextEncoder().encode(encoded),
    );
    const fingerprint = Array.from(new Uint8Array(digest), value => (
      value.toString(16).padStart(2, "0")
    )).join("");
    const action = createWritingAction(this.catalog.binding, fingerprint);
    this.action = action;
    this.status = null;
    this.jobState = null;
    this.storage?.setItem(this.ticketKey(), JSON.stringify(action));
    return this.execute("/creative-generations", {
      method: "POST",
      body: JSON.stringify({
        ...input,
        method_mode: undefined,
        writing_action: {
          action_id: action.action_id,
          tab_id: this.catalog.binding.tabId,
          preferences: { mode, semantic_mode: "off" },
        },
      }),
    }, action.action_id);
  }

  recover(): Promise<ManagedCreativeResult> {
    if (!this.action) {
      return Promise.reject(new Error("当前范围没有可查询的写作动作"));
    }
    const query = new URLSearchParams({ tab_id: this.catalog.binding.tabId });
    return this.execute(
      `${this.options.recoveryPath(
        this.catalog.binding,
        this.action.action_id,
      )}?${query}`,
      { method: "GET" },
      this.action.action_id,
    );
  }

  private async execute(
    path: string,
    init: RequestInit,
    actionId: string,
  ): Promise<ManagedCreativeResult> {
    try {
      const data = record(await this.request<unknown>(path, init));
      const next = parseWritingMethodStatus(data?.writing_method);
      if (!data || !next || next.action_id !== actionId
        || (data.state !== "method_pending"
          && (!isWritingActionId(data.id)
            || typeof data.scope_id !== "string"
            || !this.options.validateResultScope(data)
            || !["running", "ready", "failed"].includes(String(data.state))))) {
        throw new Error("创作结果与当前写作动作不匹配");
      }
      if (this.action?.action_id !== actionId) {
        throw new Error("原创作响应已隔离");
      }
      if (this.status && !canAdvanceWritingMethodStatus(this.status, next)) {
        throw new Error("创作写作方法状态发生倒退");
      }
      this.status = next;
      this.jobState = String(data.state);
      return { ...data, writing_method: next } as ManagedCreativeResult;
    } catch (error) {
      const next = parseWritingMethodStatus(
        error instanceof ApiError ? record(error.detail)?.writing_method : null,
      );
      if (next?.action_id === actionId
        && (!this.status || canAdvanceWritingMethodStatus(this.status, next))) {
        this.status = next;
      }
      throw error;
    }
  }

  private ticketKey(): string {
    return `${this.options.ticketNamespace}:${writingBindingKey(
      this.catalog.binding,
    )}`;
  }
}
