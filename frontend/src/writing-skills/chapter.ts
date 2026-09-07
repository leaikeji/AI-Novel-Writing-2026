/** Chapter HTTP adapter. Recovery is GET-only; no model/config refresh on retry. */
import { apiRequest, ApiError } from "../api";
import type { GenerationJobRecord } from "../types";
import { createWritingAction, type WritingMethodSnapshot } from "./api";
import { isWritingActionId, parseWritingMethodStatus, writingBindingKey, canAdvanceWritingMethodStatus, type WritingActionBinding,
  type WritingAction } from "./contracts";

export interface ChapterMethodInput {
  readonly expected_brief_version: number;
  readonly force_new: boolean;
  readonly asset_ids: readonly string[];
  /** This action only; never a novel/Agent preference or a story fact. */
  readonly method_mode?: "auto" | "generic_only";
  /** Immediate prior managed action, only for a server-verified length retry. */
  readonly retry_of_action_id?: string;
}
export type ChapterMethodResult = (GenerationJobRecord | { state: "method_pending" }) & {
  writing_method: NonNullable<WritingMethodSnapshot["status"]>;
};
export type ChapterMethodRequest = <T>(path: string, init?: RequestInit) => Promise<T>;
export type ChapterTicketStorage = Pick<Storage, "getItem" | "setItem">;

let pageTabId: string | null = null;
class StaleMethodResponse extends Error {}
/** A duplicated/new tab must not inherit another tab's recovery ticket.
 * Reload/back-forward may resume this tab; ordinary SPA transitions reuse it.
 */
export function writingPageTabId(storage: ChapterTicketStorage = sessionStorage): string {
  if (pageTabId) return pageTabId;
  const key = "anw-writing-tab/1";
  const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
  const previous = storage.getItem(key);
  const id = ["reload", "back_forward"].includes(navigation?.type ?? "") && isWritingActionId(previous)
    ? previous : crypto.randomUUID();
  storage.setItem(key, id); // If unavailable, fail BEFORE sending any generation.
  pageTabId = id;
  return id;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export interface ChapterMethodCatalog {
  readonly available: boolean;
  readonly catalogAvailable: boolean;
  readonly displayNames: Readonly<Record<string, string>>;
  readonly binding: WritingActionBinding;
}

export async function chapterMethodCatalog(documentId: string, novelId: string, tabId: string,
  request: ChapterMethodRequest = apiRequest): Promise<ChapterMethodCatalog> {
  const query = new URLSearchParams({ document_id: documentId, tab_id: tabId });
  const data = record(await request<unknown>(`/writing-skills?${query}`));
  const scope = record(data?.scope);
  if (data?.schema_version !== "writing-skill-catalog/1" || data.agent_id !== "ai-novel-writer"
    || typeof data.chapter_body_available !== "boolean" || data.semantic_available !== false
    || !Array.isArray(data.capabilities) || !scope || scope.kind !== "novel"
    || scope.scope_id !== novelId || scope.document_id !== documentId || scope.tab_id !== tabId
    || !isWritingActionId(scope.owner_id) || !isWritingActionId(scope.workspace_id)) {
    throw new Error("写作方法目录或作品范围无法确认");
  }
  const names: Record<string, string> = {};
  for (const raw of data.capabilities) {
    const item = record(raw);
    if (!item || typeof item.skill_id !== "string" || !/^[a-z][a-z0-9-]{0,63}$/.test(item.skill_id)
      || typeof item.display_name !== "string" || !item.display_name || item.display_name.length > 80
      || Object.prototype.hasOwnProperty.call(names, item.skill_id)) throw new Error("写作方法目录格式错误");
    names[item.skill_id] = item.display_name;
  }
  if (data.catalog_available !== undefined && typeof data.catalog_available !== "boolean") {
    throw new Error("写作方法目录状态无效");
  }
  const catalogAvailable = data.catalog_available !== false;
  if (data.chapter_body_available && !catalogAvailable) throw new Error("写作方法目录状态矛盾");
  return { available: data.chapter_body_available, catalogAvailable, displayNames: names,
    binding: { ownerKey: scope.owner_id, workspaceKey: scope.workspace_id, scopeKind: "novel",
      scopeId: novelId, documentId, tabId, agentId: "ai-novel-writer" } };
}

export class ChapterMethodClient {
  private snapshot: WritingMethodSnapshot = { action: null, status: null, connected: true, loading: false, error: null };
  private pending: Promise<ChapterMethodResult> | null = null;
  private pendingInput = "";
  private disposed = false;
  private jobState: string | null = null;

  constructor(readonly binding: WritingActionBinding,
    private readonly onChange: (snapshot: WritingMethodSnapshot) => void,
    private readonly request: ChapterMethodRequest = apiRequest,
    private readonly storage?: ChapterTicketStorage,
    private readonly availability = { managed: true, catalog: true }) {
    const saved = storage?.getItem(this.ticketKey());
    if (saved) {
      if (saved.length > 4096) throw new Error("原写作动作恢复记录无效，请先核查历史任务");
      const value = record(JSON.parse(saved));
      const storedBinding = record(value?.binding);
      if (!value || !storedBinding || !isWritingActionId(value.action_id)
        || typeof value.inputFingerprint !== "string" || !/^[a-f0-9]{64}$/.test(value.inputFingerprint)
        || Object.entries(binding).some(([key, expected]) => storedBinding[key] !== expected)) {
        throw new Error("原写作动作恢复记录不属于当前范围");
      }
      const action: WritingAction = { action_id: value.action_id, binding: Object.freeze({ ...binding }),
        inputFingerprint: value.inputFingerprint };
      this.snapshot = { ...this.snapshot, action: Object.freeze(action) };
      this.onChange(this.snapshot);
    }
  }

  getSnapshot(): WritingMethodSnapshot { return this.snapshot; }
  get managedAvailable(): boolean { return this.availability.managed && this.availability.catalog; }

  private canBeginNextAction(): boolean {
    if (!this.snapshot.action) return true;
    const state = this.snapshot.status?.state;
    return state === "failed" || state === "cancelled" || state === "stale"
      || (state === "dispatched" && (this.jobState === "ready" || this.jobState === "failed"));
  }

  /** Called only by an explicit new author submission on the legacy branch. */
  beginLegacyGeneration(): void {
    if (this.disposed) throw new Error("当前章节已切换，请查询原任务");
    if (this.managedAvailable || !this.availability.catalog) throw new Error("目录不可用或入口已切换，不能降级生成");
    if (!this.canBeginNextAction()) throw new Error("原任务结果尚未确认，请先查询原任务；不会自动重新生成。");
    if (this.snapshot.action) {
      // Only the completed local display ticket is replaced. Server evidence remains.
      this.storage?.setItem(this.ticketKey(), "");
      this.jobState = null;
      this.update({ action: null, status: null, connected: true, loading: false, error: null });
    }
  }

  start(input: ChapterMethodInput): Promise<ChapterMethodResult> {
    if (this.disposed) return Promise.reject(new Error("当前章节已切换，请查询原任务"));
    if (!this.managedAvailable) return Promise.reject(new Error("受管生成入口未开放，仍可查询原任务"));
    const mode = input.method_mode ?? "auto";
    if (mode !== "auto" && mode !== "generic_only") return Promise.reject(new Error("本次写作方法模式无效"));
    if (input.retry_of_action_id !== undefined && !isWritingActionId(input.retry_of_action_id)) {
      return Promise.reject(new Error("字数重写的原任务标识无效"));
    }
    const encoded = JSON.stringify({ ...input, method_mode: mode });
    if (this.pending) return encoded === this.pendingInput ? this.pending
      : Promise.reject(new Error("原操作仍在处理中，不能替换本次输入"));
    if (!this.canBeginNextAction()) {
      return Promise.reject(new Error("原任务结果尚未确认，请先查询原任务；不会自动重新生成。"));
    }
    this.pendingInput = encoded;
    // Freeze the exact serialized input before hashing or other async work.
    this.pending = this.send(JSON.parse(encoded) as ChapterMethodInput, encoded)
      .finally(() => { this.pending = null; this.pendingInput = ""; });
    return this.pending;
  }

  private async send(input: ChapterMethodInput, encoded: string): Promise<ChapterMethodResult> {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(encoded));
    if (this.disposed) throw new Error("当前章节已切换，未发送生成请求");
    const fingerprint = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
    const action = createWritingAction(this.binding, fingerprint);
    this.storage?.setItem(this.ticketKey(), JSON.stringify(action));
    this.jobState = null;
    this.update({ action, status: null, connected: true, loading: true, error: null });
    const { method_mode, retry_of_action_id, ...chapterInput } = input;
    const body = JSON.stringify({ ...chapterInput, writing_action: { action_id: action.action_id,
      tab_id: this.binding.tabId, ...(retry_of_action_id ? { retry_of_action_id } : {}),
      preferences: { mode: method_mode ?? "auto", semantic_mode: "off" } } });
    return this.execute(`/documents/${this.binding.documentId}/generation-jobs/body`,
      { method: "POST", body }, action.action_id);
  }

  /** An explicit query cannot re-send generation, including after a lost reply. */
  async recover(): Promise<ChapterMethodResult> {
    const action = this.snapshot.action;
    if (!action || this.disposed) throw new Error("当前章节没有可查询的写作动作");
    this.update({ ...this.snapshot, loading: true, error: null });
    const query = new URLSearchParams({ tab_id: this.binding.tabId });
    return this.execute(`/documents/${this.binding.documentId}/writing-method-actions/${action.action_id}?${query}`,
      { method: "GET" }, action.action_id);
  }

  dispose(): void { this.disposed = true; }

  private async execute(path: string, init: RequestInit, actionId: string): Promise<ChapterMethodResult> {
    try {
      const raw = await this.request<unknown>(path, init);
      const data = record(raw);
      const status = parseWritingMethodStatus(data?.writing_method);
      if (!data || !status || status.action_id !== actionId
        || (data.state !== "method_pending" && (!isWritingActionId(data.id)
          || data.document_id !== this.binding.documentId || !["running", "ready", "failed"].includes(String(data.state))))) {
        throw new Error("写作结果与当前动作不匹配");
      }
      if (this.disposed || this.snapshot.action?.action_id !== actionId) throw new Error("原章节响应已隔离");
      if (this.snapshot.status && !canAdvanceWritingMethodStatus(this.snapshot.status, status)) {
        throw new StaleMethodResponse("忽略迟到的方法状态；当前记录保持不变");
      }
      this.jobState = String(data.state);
      this.update({ ...this.snapshot, status, loading: false, error: null });
      return { ...data, writing_method: status } as ChapterMethodResult;
    } catch (error) {
      if (!(error instanceof StaleMethodResponse) && !this.disposed && this.snapshot.action?.action_id === actionId) {
        const status = parseWritingMethodStatus(error instanceof ApiError ? record(error.detail)?.writing_method : null);
        if (this.snapshot.status && ((status && !canAdvanceWritingMethodStatus(this.snapshot.status, status))
          || (!status && this.snapshot.status.state === "dispatched"))) throw error;
        const failedJob = error instanceof ApiError ? record(record(error.detail)?.job) : null;
        if (status?.action_id === actionId && failedJob && failedJob.document_id === this.binding.documentId
          && failedJob.state === "failed") this.jobState = "failed";
        this.update({ ...this.snapshot, status: status?.action_id === actionId ? status : this.snapshot.status,
          loading: false, error: status?.action_id === actionId ? null : "status_unavailable" });
      }
      throw error;
    }
  }

  private update(snapshot: WritingMethodSnapshot): void {
    if (this.disposed) return;
    this.snapshot = Object.freeze(snapshot);
    this.onChange(this.snapshot);
  }

  private ticketKey(): string { return `anw-chapter-action/1:${writingBindingKey(this.binding)}`; }
}
