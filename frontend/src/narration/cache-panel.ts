import {
  NarrationApiError,
  executeNarrationCacheCleanup,
  getNarrationCacheStatus,
  previewNarrationCacheCleanup,
} from "./api";
import type {
  CapabilityKey,
  ExecuteNarrationCacheCleanupRequest,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCacheCleanupPreview,
  NarrationCacheCleanupResult,
  NarrationCacheStatus,
  NarrationCapabilities,
  PreviewNarrationCacheCleanupRequest,
} from "./contracts";


const CACHE_CAPABILITIES = [
  "narration_product",
  "reading_settings",
  "cache_cleanup",
] as const;
const MINIMUM_NARRATION_MEDIA_FREE_BYTES = 1024 ** 3;


function diskSpaceWarning(status: NarrationCacheStatus): string | null {
  if (status.disk_free_bytes >= MINIMUM_NARRATION_MEDIA_FREE_BYTES) return null;
  if (status.disk_free_bytes === 0) {
    return "媒体盘可用空间为 0，已处于空间不足状态。";
  }
  return "媒体盘可用空间低于 1 GiB 安全余量；新朗读任务已暂停，已有音频仍可播放。";
}


export interface CachePanelReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ): void;
}


export interface CachePanelApi {
  getNarrationCacheStatus(
    novelId: string,
    signal?: AbortSignal,
  ): Promise<NarrationCacheStatus>;
  previewNarrationCacheCleanup(
    novelId: string,
    payload: PreviewNarrationCacheCleanupRequest,
    signal?: AbortSignal,
  ): Promise<NarrationCacheCleanupPreview>;
  executeNarrationCacheCleanup(
    novelId: string,
    payload: ExecuteNarrationCacheCleanupRequest,
    signal?: AbortSignal,
  ): Promise<NarrationCacheCleanupResult>;
}


export interface CachePanelProps {
  readonly novelId: string;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly className?: string;
  readonly onCleaned?: (result: NarrationCacheCleanupResult) => void;
  readonly onReturnFocus?: () => void;
}


type CachePanelPhase =
  | "blocked"
  | "loading"
  | "ready"
  | "previewing"
  | "preview-ready"
  | "executing"
  | "success"
  | "load-error"
  | "action-error";


interface CachePanelState {
  readonly scopeKey: string;
  readonly phase: CachePanelPhase;
  readonly status: NarrationCacheStatus | null;
  readonly preview: NarrationCacheCleanupPreview | null;
  readonly result: NarrationCacheCleanupResult | null;
  readonly confirmed: boolean;
  readonly message: string;
}


interface CheckedChangeEvent {
  readonly target: { readonly checked: boolean };
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
}


class CachePanelDataError extends Error {}


const defaultApi: CachePanelApi = {
  getNarrationCacheStatus,
  previewNarrationCacheCleanup,
  executeNarrationCacheCleanup,
};


function capability(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | undefined {
  return capabilities.items.find((item) => item.key === key);
}


function actionable(item: FeatureCapability | undefined): boolean {
  return item?.state === "enabled" && item.visible && item.actionable;
}


export function isCacheCleanupActionable(
  capabilities: NarrationCapabilities,
  authorization: NarrationAuthorizationState,
  status: NarrationCacheStatus | null,
): boolean {
  return authorization.can_read
    && authorization.can_configure
    && CACHE_CAPABILITIES.every((key) => actionable(capability(capabilities, key)))
    && actionable(status?.cleanup_capability);
}


function cleanupBlockMessage(
  props: CachePanelProps,
  status: NarrationCacheStatus | null,
): string {
  if (!props.authorization.can_read) return "当前身份无权查看音频与缓存。";
  if (!props.authorization.can_configure) return "当前身份只能查看缓存状态，不能执行清理。";
  for (const key of CACHE_CAPABILITIES) {
    const item = capability(props.capabilities, key);
    if (!actionable(item)) {
      const reason = item?.reason_code ? `（${item.reason_code}）` : "";
      return `缓存清理尚未开放${reason}；状态可查看，不会执行删除。`;
    }
  }
  if (status && !actionable(status.cleanup_capability)) {
    const reason = status.cleanup_capability.reason_code
      ? `（${status.cleanup_capability.reason_code}）`
      : "";
    return `服务端缓存清理门禁尚未开放${reason}。`;
  }
  return "";
}


export function formatExactBytes(value: number): string {
  if (!Number.isSafeInteger(value) || value < 0) return "无效字节数";
  const exact = `${value.toLocaleString("zh-CN")} B`;
  if (value < 1024) return exact;
  const units = ["KiB", "MiB", "GiB", "TiB"] as const;
  let scaled = value;
  let unit: typeof units[number] = units[0];
  for (const candidate of units) {
    scaled /= 1024;
    unit = candidate;
    if (scaled < 1024) break;
  }
  return `${exact}（${scaled.toFixed(2)} ${unit}）`;
}


function safeCacheBytes(status: NarrationCacheStatus): boolean {
  return [
    status.source_asset_bytes,
    status.locked_voice_bytes,
    status.referenced_edition_bytes,
    status.derived_cache_bytes,
    status.reclaimable_bytes,
    status.pending_job_count,
    status.disk_free_bytes,
    status.disk_total_bytes,
  ].every((value) => Number.isSafeInteger(value) && value >= 0)
    && status.disk_total_bytes > 0
    && status.disk_free_bytes <= status.disk_total_bytes
    && status.reclaimable_bytes <= status.derived_cache_bytes;
}


function assertStatusScope(novelId: string, status: NarrationCacheStatus): void {
  if (status.novel_id !== novelId) {
    throw new CachePanelDataError("缓存状态返回了其他作品的数据，已拒绝显示。");
  }
  if (!safeCacheBytes(status)) {
    throw new CachePanelDataError("缓存状态包含无法精确显示的字节数，已拒绝显示。");
  }
}


function assertPreviewScope(
  novelId: string,
  status: NarrationCacheStatus,
  preview: NarrationCacheCleanupPreview,
): void {
  if (preview.novel_id !== novelId
    || preview.snapshot_fingerprint !== status.snapshot_fingerprint
    || !Number.isSafeInteger(preview.reclaimable_bytes)
    || preview.reclaimable_bytes < 0
    || preview.reclaimable_bytes > status.reclaimable_bytes
    || !Number.isSafeInteger(preview.protected_asset_count)
    || preview.protected_asset_count < 0
    || !Number.isSafeInteger(preview.candidate_asset_count)
    || preview.candidate_asset_count < 0) {
    throw new CachePanelDataError("缓存预览与当前快照不一致，已拒绝执行。");
  }
}


function assertResultScope(
  novelId: string,
  preview: NarrationCacheCleanupPreview,
  result: NarrationCacheCleanupResult,
): void {
  if (result.novel_id !== novelId
    || result.source_asset_deleted_count !== 0
    || result.locked_voice_deleted_count !== 0
    || result.referenced_asset_deleted_count !== 0
    || !Number.isSafeInteger(result.deleted_asset_count)
    || !Number.isSafeInteger(result.reclaimed_bytes)
    || result.deleted_asset_count < 0
    || result.reclaimed_bytes < 0
    || result.deleted_asset_count > preview.candidate_asset_count
    || result.reclaimed_bytes > preview.reclaimable_bytes) {
    throw new CachePanelDataError("缓存清理结果违反保护契约，已拒绝将其显示为成功。");
  }
}


function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}


function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof CachePanelDataError) return reason.message;
  if (reason instanceof NarrationApiError) {
    const labels: Partial<Record<typeof reason.detail.code, string>> = {
      CAPABILITY_DISABLED: "缓存清理能力尚未开放，未执行删除。",
      VERSION_CONFLICT: "缓存快照已变化，请刷新后重新预览。",
      INVALID_STATE: "清理确认已失效，请重新预览。",
      DISK_SPACE_INSUFFICIENT: "媒体盘可用空间不足，请先处理存储状态。",
      STORAGE_UNAVAILABLE: "媒体存储暂不可用，未执行清理。",
      SCOPE_VIOLATION: "缓存资产不属于当前作品，未执行清理。",
      SETTINGS_BACKEND_NOT_INSTALLED: "朗读缓存服务尚未接入。",
    };
    return labels[reason.detail.code] ?? `${fallback}（${reason.detail.code}）`;
  }
  return fallback;
}


function initialState(props: CachePanelProps): CachePanelState {
  return {
    scopeKey: props.novelId,
    phase: props.authorization.can_read ? "loading" : "blocked",
    status: null,
    preview: null,
    result: null,
    confirmed: false,
    message: props.authorization.can_read ? "正在加载缓存状态…" : cleanupBlockMessage(props, null),
  };
}


export function createCachePanel(
  React: CachePanelReactRuntime,
  api: CachePanelApi = defaultApi,
): (props: CachePanelProps) => unknown {
  const h = React.createElement;

  return function CachePanel(props: CachePanelProps): unknown {
    const [state, setState] = React.useState(() => initialState(props));
    const stateRef = React.useRef(state);
    stateRef.current = state;
    const requestSequenceRef = React.useRef(0);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const actionAbortRef = React.useRef<AbortController | null>(null);
    const previewRef = React.useRef<FocusableElement | null>(null);
    const errorRef = React.useRef<FocusableElement | null>(null);
    const returnFocusRef = React.useRef(props.onReturnFocus);
    returnFocusRef.current = props.onReturnFocus;

    const commit = (
      update: CachePanelState | ((current: CachePanelState) => CachePanelState),
    ) => {
      setState((current) => {
        const next = typeof update === "function" ? update(current) : update;
        stateRef.current = next;
        return next;
      });
    };

    const startLoad = (): AbortController | null => {
      if (!props.authorization.can_read) {
        commit(initialState(props));
        return null;
      }
      loadAbortRef.current?.abort();
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      const scopedNovelId = props.novelId;
      commit({
        scopeKey: scopedNovelId,
        phase: "loading",
        status: null,
        preview: null,
        result: null,
        confirmed: false,
        message: "正在加载缓存状态…",
      });
      void api.getNarrationCacheStatus(scopedNovelId, controller.signal).then((status) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertStatusScope(scopedNovelId, status);
        commit({
          scopeKey: scopedNovelId,
          phase: "ready",
          status,
          preview: null,
          result: null,
          confirmed: false,
          message: diskSpaceWarning(status) ?? "缓存状态已加载。",
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        commit({
          scopeKey: scopedNovelId,
          phase: "load-error",
          status: null,
          preview: null,
          result: null,
          confirmed: false,
          message: errorMessage(reason, "加载缓存状态失败。"),
        });
      });
      return controller;
    };

    React.useEffect(() => {
      const controller = startLoad();
      return () => controller?.abort();
    }, [props.novelId, props.authorization.can_read]);

    React.useEffect(() => () => {
      loadAbortRef.current?.abort();
      actionAbortRef.current?.abort();
      returnFocusRef.current?.();
    }, []);

    React.useEffect(() => {
      if (state.phase === "action-error") errorRef.current?.focus({ preventScroll: true });
      if (state.phase === "preview-ready") previewRef.current?.focus({ preventScroll: true });
    }, [state.phase]);

    const scoped = props.authorization.can_read && state.scopeKey === props.novelId;
    const status = scoped ? state.status : null;
    const preview = scoped ? state.preview : null;
    const result = scoped ? state.result : null;
    const cleanupAllowed = isCacheCleanupActionable(
      props.capabilities,
      props.authorization,
      status,
    );
    const previewExpired = preview !== null && Date.parse(preview.expires_at) <= Date.now();
    const canPreview = status !== null
      && cleanupAllowed
      && status.reclaimable_bytes > 0
      && (state.phase === "ready" || state.phase === "action-error");
    const canExecute = preview !== null
      && cleanupAllowed
      && state.phase === "preview-ready"
      && state.confirmed
      && !previewExpired
      && preview.snapshot_fingerprint === status?.snapshot_fingerprint;

    const previewCleanup = () => {
      const current = stateRef.current;
      const currentStatus = current.scopeKey === props.novelId ? current.status : null;
      if (!currentStatus
        || !isCacheCleanupActionable(props.capabilities, props.authorization, currentStatus)
        || currentStatus.reclaimable_bytes === 0
        || !["ready", "action-error"].includes(current.phase)) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      const scopedNovelId = props.novelId;
      commit({
        ...current,
        phase: "previewing",
        preview: null,
        result: null,
        confirmed: false,
        message: "正在用当前快照预览可清理派生缓存…",
      });
      void api.previewNarrationCacheCleanup(
        scopedNovelId,
        { snapshot_fingerprint: currentStatus.snapshot_fingerprint },
        controller.signal,
      ).then((nextPreview) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertPreviewScope(scopedNovelId, currentStatus, nextPreview);
        commit({
          ...current,
          phase: "preview-ready",
          preview: nextPreview,
          result: null,
          confirmed: false,
          message: "预览已就绪。请核对精确字节数并显式确认；此时尚未删除任何资产。",
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        commit({
          ...current,
          phase: "action-error",
          preview: null,
          result: null,
          confirmed: false,
          message: errorMessage(reason, "预览缓存清理失败，未执行删除。"),
        });
      });
    };

    const executeCleanup = () => {
      const current = stateRef.current;
      const currentStatus = current.scopeKey === props.novelId ? current.status : null;
      const currentPreview = current.scopeKey === props.novelId ? current.preview : null;
      if (!currentStatus
        || !currentPreview
        || current.phase !== "preview-ready"
        || !current.confirmed
        || Date.parse(currentPreview.expires_at) <= Date.now()
        || currentPreview.snapshot_fingerprint !== currentStatus.snapshot_fingerprint
        || !isCacheCleanupActionable(props.capabilities, props.authorization, currentStatus)) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      const scopedNovelId = props.novelId;
      commit({ ...current, phase: "executing", message: "正在清理预览中的未引用派生缓存…" });
      void api.executeNarrationCacheCleanup(
        scopedNovelId,
        {
          snapshot_fingerprint: currentPreview.snapshot_fingerprint,
          cleanup_token: currentPreview.cleanup_token,
          confirmed: true,
        },
        controller.signal,
      ).then((nextResult) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertResultScope(scopedNovelId, currentPreview, nextResult);
        commit({
          ...current,
          phase: "success",
          preview: null,
          result: nextResult,
          confirmed: false,
          message: `清理完成：服务端确认删除 ${nextResult.deleted_asset_count} 个派生资产，实际回收 ${formatExactBytes(nextResult.reclaimed_bytes)}。`,
        });
        props.onCleaned?.(nextResult);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        commit({
          ...current,
          phase: "action-error",
          preview: null,
          result: null,
          confirmed: false,
          message: errorMessage(reason, "缓存清理失败，不会报告未确认的回收字节。"),
        });
      });
    };

    const block = cleanupBlockMessage(props, status);
    const rootClassName = [
      "anw-cache-panel",
      `is-${scoped ? state.phase : "loading"}`,
      props.className ?? "",
    ].filter(Boolean).join(" ");
    const prefix = `anw-cache-${props.novelId}`;
    const headingId = `${prefix}-heading`;
    const statusId = `${prefix}-status`;

    return h(
      "section",
      {
        className: rootClassName,
        role: "region",
        "aria-labelledby": headingId,
        "aria-describedby": statusId,
        "aria-busy": !scoped
          || state.phase === "loading"
          || state.phase === "previewing"
          || state.phase === "executing",
        "data-cache-panel-phase": scoped ? state.phase : "loading",
      },
      h("header", { className: "anw-cache-panel__header" },
        h("div", null,
          h("span", { className: "anw-cache-panel__eyebrow" }, "朗读设置"),
          h("h3", { id: headingId, tabIndex: -1 }, "音频与缓存"),
        ),
        status ? h("button", {
          type: "button",
          disabled: state.phase === "previewing" || state.phase === "executing",
          onClick: startLoad,
        }, "刷新状态") : null,
      ),
      h("div", {
        id: statusId,
        className: "anw-cache-panel__live",
        role: "status",
        "aria-live": "polite",
        "aria-atomic": "true",
      }, scoped ? state.message : "正在切换作品范围…"),
      block ? h("p", { className: "anw-cache-panel__notice" }, block) : null,
      state.phase === "load-error" && scoped
        ? h("div", { className: "anw-cache-panel__error", role: "alert" },
          h("strong", null, state.message),
          props.authorization.can_read
            ? h("button", { type: "button", onClick: startLoad }, "重新加载")
            : null,
        )
        : null,
      state.phase === "action-error" && scoped
        ? h("div", {
          className: "anw-cache-panel__error",
          role: "alert",
          tabIndex: -1,
          ref: errorRef,
        },
        h("strong", null, state.message),
        h("button", { type: "button", onClick: startLoad }, "刷新快照"),
        )
        : null,
      status && scoped
        ? h("div", { className: "anw-cache-panel__body" },
          diskSpaceWarning(status) !== null
            ? h("div", { className: "anw-cache-panel__disk-warning", role: "alert" },
              diskSpaceWarning(status),
            )
            : null,
          h("dl", { className: "anw-cache-panel__metrics" },
            h("div", null, h("dt", null, "源资产（不可清理）"), h("dd", null, formatExactBytes(status.source_asset_bytes))),
            h("div", null, h("dt", null, "锁定音色（不可清理）"), h("dd", null, formatExactBytes(status.locked_voice_bytes))),
            h("div", null, h("dt", null, "历史 Edition 引用（不可清理）"), h("dd", null, formatExactBytes(status.referenced_edition_bytes))),
            h("div", null, h("dt", null, "派生缓存"), h("dd", null, formatExactBytes(status.derived_cache_bytes))),
            h("div", { className: "is-reclaimable" }, h("dt", null, "当前可回收"), h("dd", null, formatExactBytes(status.reclaimable_bytes))),
            h("div", null, h("dt", null, "待处理任务"), h("dd", null, status.pending_job_count)),
            h("div", null, h("dt", null, "媒体盘可用 / 总量"), h("dd", null,
              `${formatExactBytes(status.disk_free_bytes)} / ${formatExactBytes(status.disk_total_bytes)}`,
            )),
          ),
          h("aside", { className: "anw-cache-panel__guard" },
            h("strong", null, "清理保护线"),
            h("p", null, "清理只允许处理派生且未引用的缓存。源资产、锁定音色和被历史 Edition 引用的资产，删除数在服务契约中永远为 0。"),
          ),
          preview && state.phase === "preview-ready"
            ? h("section", {
              className: "anw-cache-panel__preview",
              "aria-labelledby": `${prefix}-preview-heading`,
              tabIndex: -1,
              ref: previewRef,
            },
            h("h4", { id: `${prefix}-preview-heading` }, "二阶段清理确认"),
            h("p", null, "以下是服务端对当前快照的预览；尚未删除任何数据。"),
            h("dl", null,
              h("div", null, h("dt", null, "精确可回收"), h("dd", null, formatExactBytes(preview.reclaimable_bytes))),
              h("div", null, h("dt", null, "候选资产"), h("dd", null, preview.candidate_asset_count)),
              h("div", null, h("dt", null, "受保护资产"), h("dd", null, preview.protected_asset_count)),
              h("div", null, h("dt", null, "确认过期时间"), h("dd", null, new Date(preview.expires_at).toLocaleString("zh-CN"))),
            ),
            previewExpired
              ? h("p", { className: "anw-cache-panel__validation", role: "alert" }, "此预览已过期，请刷新快照并重新预览。")
              : h("label", { className: "anw-cache-panel__confirm" },
                h("input", {
                  type: "checkbox",
                  checked: state.confirmed,
                  onChange: (event: CheckedChangeEvent) => commit((current) => ({
                    ...current,
                    confirmed: event.target.checked,
                    message: event.target.checked
                      ? "已在本地确认；只有点击最终执行按钮才会请求删除。"
                      : "已取消本地确认，不会执行删除。",
                  })),
                }),
                h("span", null, `我确认只清理预览快照中的 ${formatExactBytes(preview.reclaimable_bytes)} 未引用派生缓存`),
              ),
            h("div", { className: "anw-cache-panel__preview-actions" },
              h("button", {
                type: "button",
                onClick: () => commit((current) => ({
                  ...current,
                  phase: "ready",
                  preview: null,
                  confirmed: false,
                  message: "已取消清理预览，未删除任何资产。",
                })),
              }, "取消预览"),
              h("button", {
                type: "button",
                className: "anw-cache-panel__execute",
                disabled: !canExecute,
                onClick: executeCleanup,
              }, "确认清理派生缓存"),
            ),
            )
            : h("div", { className: "anw-cache-panel__actions" },
              h("button", {
                type: "button",
                disabled: !canPreview,
                onClick: previewCleanup,
              }, state.phase === "previewing" ? "预览中…" : "预览可清理项"),
              status.reclaimable_bytes === 0
                ? h("span", null, "当前没有经服务端确认可回收的派生缓存。")
                : null,
            ),
          result && state.phase === "success"
            ? h("div", { className: "anw-cache-panel__success", role: "status" },
              h("strong", null, "清理结果（服务端实际值）"),
              h("p", null, `删除 ${result.deleted_asset_count} 个派生资产，回收 ${formatExactBytes(result.reclaimed_bytes)}。`),
              h("p", null, "源资产 0 个、锁定音色 0 个、历史 Edition 引用资产 0 个。上方快照已过期，请刷新状态。"),
            )
            : null,
        )
        : state.phase !== "load-error" && state.phase !== "blocked"
          ? h("p", { className: "anw-cache-panel__loading" }, "正在读取媒体盘与缓存快照…")
          : null,
    );
  };
}
