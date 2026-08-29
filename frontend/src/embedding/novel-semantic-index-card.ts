import {
  cancelNovelSemanticIndex,
  clearNovelSemanticIndex,
  getNovelEmbeddingConsent,
  getNovelSemanticIndexStatus,
  putNovelEmbeddingConsent,
  rebuildNovelSemanticIndex,
  retryFailedNovelSemanticIndex,
} from "./api";
import {
  NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
} from "./contracts";
import type {
  NovelEmbeddingConsentResource,
  NovelSemanticIndexStatus,
  PutNovelEmbeddingConsentRequest,
} from "./contracts";
import {
  CORPUS_LABELS,
  CORPUS_STATE_LABELS,
  INDEX_STATE_LABELS,
  formatEmbeddingReason,
  formatDateTime,
} from "./presentation";
import { ensureEmbeddingStyles } from "./styles";
import type {
  CheckedChangeEvent,
  EmbeddingAntdRuntime,
  EmbeddingReactRuntime,
  FocusableElement,
} from "./ui-runtime";


export const EMBEDDING_DISCLOSED_SCOPES = [
  "formal_manuscript",
  "formal_planning",
  "author_secrets",
  "bound_private_assets",
] as const;


export interface NovelSemanticIndexCardApi {
  getConsent(novelId: string, signal?: AbortSignal): Promise<NovelEmbeddingConsentResource>;
  putConsent(
    novelId: string,
    request: PutNovelEmbeddingConsentRequest,
    signal?: AbortSignal,
  ): Promise<NovelEmbeddingConsentResource>;
  getStatus(novelId: string, signal?: AbortSignal): Promise<NovelSemanticIndexStatus>;
  rebuild(novelId: string, signal?: AbortSignal): Promise<NovelSemanticIndexStatus>;
  cancel(novelId: string, signal?: AbortSignal): Promise<NovelSemanticIndexStatus>;
  retryFailed(novelId: string, signal?: AbortSignal): Promise<NovelSemanticIndexStatus>;
  clear(novelId: string, signal?: AbortSignal): Promise<NovelSemanticIndexStatus>;
}


export interface NovelSemanticIndexCardProps {
  readonly novelId: string;
  readonly novelTitle?: string;
  readonly className?: string;
  readonly onStatusChange?: (
    consent: NovelEmbeddingConsentResource,
    status: NovelSemanticIndexStatus,
  ) => void;
}


type LoadState =
  | { readonly phase: "loading"; readonly novelId: string }
  | { readonly phase: "error"; readonly novelId: string; readonly message: string }
  | {
      readonly phase: "ready";
      readonly novelId: string;
      readonly consent: NovelEmbeddingConsentResource;
      readonly status: NovelSemanticIndexStatus;
    };


interface OperationState {
  readonly busy: boolean;
  readonly message: string;
  readonly kind: "idle" | "success" | "error";
}


type Confirmation = "revoke" | "clear" | null;


const DEFAULT_API: NovelSemanticIndexCardApi = {
  getConsent: getNovelEmbeddingConsent,
  putConsent: putNovelEmbeddingConsent,
  getStatus: getNovelSemanticIndexStatus,
  rebuild: rebuildNovelSemanticIndex,
  cancel: cancelNovelSemanticIndex,
  retryFailed: retryFailedNovelSemanticIndex,
  clear: clearNovelSemanticIndex,
};


const EMPTY_OPERATION: OperationState = { busy: false, message: "", kind: "idle" };


function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}


function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message.trim() ? reason.message : fallback;
}


function statusColor(state: NovelSemanticIndexStatus["state"]): string {
  if (state === "ready") return "success";
  if (state === "partial_failed") return "error";
  if (state === "updating") return "processing";
  if (state === "not_authorized") return "default";
  return "warning";
}


export function createNovelSemanticIndexCard(
  React: EmbeddingReactRuntime,
  antd: EmbeddingAntdRuntime,
  api: NovelSemanticIndexCardApi = DEFAULT_API,
): (props: NovelSemanticIndexCardProps) => unknown {
  const h = React.createElement;

  return function NovelSemanticIndexCard(props: NovelSemanticIndexCardProps): unknown {
    const [load, setLoad] = React.useState<LoadState>({
      phase: "loading",
      novelId: props.novelId,
    });
    const [operation, setOperation] = React.useState<OperationState>(EMPTY_OPERATION);
    const [acknowledged, setAcknowledged] = React.useState(false);
    const [confirmation, setConfirmation] = React.useState<Confirmation>(null);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const actionAbortRef = React.useRef<AbortController | null>(null);
    const sequenceRef = React.useRef(0);
    const alertRef = React.useRef<FocusableElement | null>(null);
    const confirmationRef = React.useRef<FocusableElement | null>(null);

    const applyReady = (
      novelId: string,
      consent: NovelEmbeddingConsentResource,
      status: NovelSemanticIndexStatus,
    ) => {
      if (consent.novel_id !== novelId || status.novel_id !== novelId) {
        throw new Error("语义索引接口返回了其他小说的数据，已拒绝显示。");
      }
      setLoad({ phase: "ready", novelId, consent, status });
      props.onStatusChange?.(consent, status);
    };

    const loadStatus = () => {
      loadAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      const sequence = ++sequenceRef.current;
      const novelId = props.novelId;
      setLoad({ phase: "loading", novelId });
      setAcknowledged(false);
      setConfirmation(null);
      void Promise.all([
        api.getConsent(novelId, controller.signal),
        api.getStatus(novelId, controller.signal),
      ]).then(([consent, status]) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        applyReady(novelId, consent, status);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current || isAbortError(reason)) return;
        setLoad({
          phase: "error",
          novelId,
          message: errorMessage(reason, "加载小说语义索引状态失败。"),
        });
      });
      return controller;
    };

    React.useEffect(() => {
      ensureEmbeddingStyles();
      const controller = loadStatus();
      return () => controller.abort();
    }, [props.novelId]);

    React.useEffect(() => () => actionAbortRef.current?.abort(), []);

    React.useEffect(() => {
      if (operation.kind === "error") alertRef.current?.focus({ preventScroll: true });
      if (confirmation !== null) confirmationRef.current?.focus({ preventScroll: true });
    }, [operation.kind, confirmation]);

    const runStatusAction = (
      pending: string,
      success: string,
      action: (novelId: string, signal: AbortSignal) => Promise<NovelSemanticIndexStatus>,
    ) => {
      if (operation.busy || load.phase !== "ready" || load.novelId !== props.novelId) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      const novelId = props.novelId;
      const consent = load.consent;
      setOperation({ busy: true, message: pending, kind: "idle" });
      void action(novelId, controller.signal).then((status) => {
        if (controller.signal.aborted || status.novel_id !== novelId) return;
        applyReady(novelId, consent, status);
        setOperation({ busy: false, message: success, kind: "success" });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        setOperation({
          busy: false,
          message: errorMessage(reason, `${success}失败。`),
          kind: "error",
        });
      });
    };

    const changeConsent = (action: "grant" | "revoke") => {
      if (operation.busy || load.phase !== "ready" || load.novelId !== props.novelId) return;
      if (action === "grant" && !acknowledged) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      const novelId = props.novelId;
      const upgradingWritingQueries = action === "grant" && load.consent.state === "granted";
      const request: PutNovelEmbeddingConsentRequest = {
        action,
        expected_version: load.consent.version,
        notice_version: NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
        acknowledged_scopes: EMBEDDING_DISCLOSED_SCOPES,
      };
      setOperation({
        busy: true,
        message: action === "grant"
          ? upgradingWritingQueries
            ? "正在升级写作检索授权…"
            : "正在保存小说云端向量授权…"
          : "正在撤销小说云端向量授权…",
        kind: "idle",
      });
      void api.putConsent(novelId, request, controller.signal).then(async (consent) => {
        if (controller.signal.aborted) return;
        const status = await api.getStatus(novelId, controller.signal);
        if (controller.signal.aborted) return;
        applyReady(novelId, consent, status);
        setAcknowledged(false);
        setConfirmation(null);
        setOperation({
          busy: false,
          message: action === "grant"
            ? upgradingWritingQueries
              ? "授权已升级；写作触发可以按策略发送查询并使用当前生效索引。"
              : "授权已保存。后续新增正式内容与新绑定素材会进入该小说的后续索引。"
            : "授权已撤销，新的云端请求已停止；本地向量未自动清理。",
          kind: "success",
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        setOperation({
          busy: false,
          message: errorMessage(reason, action === "grant" ? "保存授权失败。" : "撤销授权失败。"),
          kind: "error",
        });
      });
    };

    const rootClassName = ["anw-semantic-index-card", props.className ?? ""]
      .filter(Boolean).join(" ");
    const scoped = load.novelId === props.novelId;

    if (!scoped || load.phase === "loading") {
      return h(antd.Card, { className: rootClassName },
        h(antd.Spin, { tip: "正在加载语义索引状态…" }),
      );
    }
    if (load.phase === "error") {
      return h(antd.Card, { className: rootClassName },
        h(antd.Alert, {
          type: "error",
          showIcon: true,
          message: "无法加载语义索引",
          description: load.message,
          action: h(antd.Button, { onClick: loadStatus }, "重新加载"),
        }),
      );
    }

    const { consent, status } = load;
    const granted = consent.state === "granted";
    const writingQueryAuthorized = granted && consent.writing_query_authorized;
    const needsWritingQueryUpgrade = granted && !writingQueryAuthorized;
    const titleId = `anw-semantic-index-${props.novelId}-heading`;

    return h(antd.Card, { className: rootClassName },
      h("section", {
        className: "anw-semantic-index-card__body",
        role: "region",
        "aria-labelledby": titleId,
        "aria-busy": operation.busy,
      },
      h("header", { className: "anw-semantic-index-card__header" },
        h("div", null,
          h("p", { className: "anw-embedding-muted" }, props.novelTitle ?? "当前小说"),
          h("h3", { id: titleId, tabIndex: -1 }, "语义索引"),
        ),
        h(antd.Tag, { color: statusColor(status.state) }, INDEX_STATE_LABELS[status.state]),
      ),
      operation.message
        ? h("div", {
          className: "anw-embedding-live",
          role: operation.kind === "error" ? "alert" : "status",
          "aria-live": "polite",
          tabIndex: operation.kind === "error" ? -1 : undefined,
          ref: operation.kind === "error" ? alertRef : undefined,
        }, operation.message)
        : null,
      h(antd.Alert, {
        type: needsWritingQueryUpgrade ? "warning" : granted ? "warning" : "info",
        showIcon: true,
        message: needsWritingQueryUpgrade
          ? "现有授权不包含写作查询，请升级告知版本"
          : granted
            ? "本小说已授权云端向量处理"
            : "授权前不会发起云端向量请求",
        description: "授权会把本小说的正式正文、正式大纲与故事设定、作者秘密，以及已绑定的私有素材发送给阿里云百炼生成向量。写作时，章纲要求、工作稿选区和自定义指令也可能作为查询发送。未绑定的全局私有素材不会发送。",
      }),
      !granted
        ? h("section", { className: "anw-embedding-confirm" },
          h("h4", null, "一次性小说授权"),
          h("p", { className: "anw-embedding-disclosure" },
            "授权仅用于本小说的语义索引与已说明的写作检索；之后新增的正式内容和新绑定素材无需重复弹窗，但页面会持续显示云端状态。",
          ),
          h("label", null,
            h("input", {
              type: "checkbox",
              checked: acknowledged,
              disabled: operation.busy,
              onChange: (event: CheckedChangeEvent) => setAcknowledged(event.target.checked),
            }),
            h("span", null, "我已了解上述正式内容会用于建索引，章纲要求、工作稿选区和自定义指令可能作为查询发送到阿里云百炼。"),
          ),
          h(antd.Button, {
            type: "primary",
            disabled: !acknowledged || operation.busy,
            onClick: () => changeConsent("grant"),
          }, "授权并允许后续索引"),
        )
        : h("dl", { className: "anw-embedding-metrics" },
          h("div", null, h("dt", null, "授权时间"), h("dd", null, formatDateTime(consent.confirmed_at))),
          h("div", null, h("dt", null, "告知版本"), h("dd", null, consent.notice_version ?? "未记录")),
          h("div", null, h("dt", null, "写作查询"), h("dd", null,
            writingQueryAuthorized ? "已授权" : "未授权，自动写作仅使用本地降级",
          )),
          h("div", null, h("dt", null, "当前模型"), h("dd", null, status.active_model_id ?? "尚未激活")),
          h("div", null, h("dt", null, "向量维度 / 索引代次"), h("dd", null,
            status.active_dimension && status.active_generation_number
              ? `${status.active_dimension} / ${status.active_generation_number}`
              : "暂无",
          )),
          h("div", null, h("dt", null, "来源 / 分块 / 失败"), h("dd", null,
            `${status.source_count} / ${status.chunk_count} / ${status.failure_count}`,
          )),
          h("div", null, h("dt", null, "同步版本"), h("dd", null,
            status.index_version === null ? "暂无" : `第 ${status.index_version} 版`,
          )),
          h("div", null, h("dt", null, "待刷新来源"), h("dd", null,
            status.pending_refresh_count,
          )),
          h("div", null, h("dt", null, "最近索引"), h("dd", null, formatDateTime(status.last_indexed_at))),
        ),
      needsWritingQueryUpgrade
        ? h("section", { className: "anw-embedding-confirm" },
          h("h4", null, "升级至 novel-embedding-consent/2"),
          h("p", { className: "anw-embedding-disclosure" },
            "旧授权仍可维护已经披露的正式语料索引，但不会把章纲要求、工作稿选区或自定义指令作为云端查询。升级后才会启用自动写作 Dense 检索。",
          ),
          h("label", null,
            h("input", {
              type: "checkbox",
              checked: acknowledged,
              disabled: operation.busy,
              onChange: (event: CheckedChangeEvent) => setAcknowledged(event.target.checked),
            }),
            h("span", null, "我已了解写作查询的发送范围，并同意升级本小说授权。"),
          ),
          h(antd.Button, {
            type: "primary",
            disabled: !acknowledged || operation.busy,
            onClick: () => changeConsent("grant"),
          }, "升级授权并启用写作检索"),
        )
        : null,
      granted && status.corpora.length === 0
        ? h(antd.Empty, { description: "尚无可显示的语料索引状态" })
        : null,
      granted && status.corpora.length > 0
        ? h("ul", { className: "anw-semantic-corpora", "aria-label": "各语料索引状态" },
          ...status.corpora.map((corpus) => h("li", { key: corpus.corpus },
            h("strong", null, CORPUS_LABELS[corpus.corpus]),
            h("span", null, CORPUS_STATE_LABELS[corpus.state]),
            h("span", { className: "anw-embedding-muted" },
              `来源 ${corpus.source_count} · 分块 ${corpus.chunk_count} · 失败 ${corpus.failure_count}`,
            ),
            corpus.reason_code
              ? h("span", { className: "anw-embedding-muted" },
                `未索引原因：${formatEmbeddingReason(corpus.reason_code)}`,
              )
              : null,
          )))
        : null,
      status.error_summary
        ? h(antd.Alert, {
          type: "error",
          showIcon: true,
          message: "最近索引错误",
          description: formatEmbeddingReason(status.error_summary),
        })
        : null,
      granted
        ? h("div", { className: "anw-embedding-actions" },
          h(antd.Button, {
            type: "primary",
            disabled: !status.can_rebuild || operation.busy,
            onClick: () => runStatusAction(
              "正在按当前生效代次重建本小说索引…",
              "已按当前生效代次启动本小说索引重建。",
              api.rebuild,
            ),
          }, "按当前生效代次重建"),
          h(antd.Button, {
            disabled: !status.can_cancel || operation.busy,
            onClick: () => runStatusAction(
              "正在取消本小说索引构建…",
              "本小说索引构建已取消。",
              api.cancel,
            ),
          }, "取消构建"),
          h(antd.Button, {
            disabled: !status.can_retry_failed || operation.busy,
            onClick: () => runStatusAction(
              "正在重试失败索引批次…",
              "失败索引批次已重新排队。",
              api.retryFailed,
            ),
          }, "重试失败批次"),
          h(antd.Button, {
            danger: true,
            disabled: !status.has_local_vectors || operation.busy,
            onClick: () => setConfirmation("clear"),
          }, "清理本地派生向量"),
          h(antd.Button, {
            danger: true,
            disabled: operation.busy,
            onClick: () => setConfirmation("revoke"),
          }, "撤销云端授权"),
        )
        : status.has_local_vectors
          ? h(antd.Button, {
            danger: true,
            disabled: operation.busy,
            onClick: () => setConfirmation("clear"),
          }, "单独清理本地派生向量")
          : null,
      confirmation === "revoke"
        ? h("section", {
          className: "anw-embedding-confirm",
          role: "alertdialog",
          "aria-labelledby": `${titleId}-revoke-title`,
          tabIndex: -1,
          ref: confirmationRef,
        },
        h("h4", { id: `${titleId}-revoke-title` }, "确认撤销云端授权"),
        h("p", null, "撤销会立即停止本小说新的云端向量请求，但不会自动删除 PostgreSQL 中已有的本地向量。"),
        h("div", { className: "anw-embedding-inline-actions" },
          h(antd.Button, { onClick: () => setConfirmation(null) }, "取消"),
          h(antd.Button, { danger: true, onClick: () => changeConsent("revoke") }, "确认撤销授权"),
        ))
        : null,
      confirmation === "clear"
        ? h("section", {
          className: "anw-embedding-confirm",
          role: "alertdialog",
          "aria-labelledby": `${titleId}-clear-title`,
          tabIndex: -1,
          ref: confirmationRef,
        },
        h("h4", { id: `${titleId}-clear-title` }, "确认清理本地派生向量"),
        h("p", null, "此操作只清理本小说可重建的本地派生向量，不删除正文、事实、私有素材或授权记录。"),
        h("div", { className: "anw-embedding-inline-actions" },
          h(antd.Button, { onClick: () => setConfirmation(null) }, "取消"),
          h(antd.Button, {
            danger: true,
            onClick: () => {
              setConfirmation(null);
              runStatusAction(
                "正在清理本小说本地派生向量…",
                "本小说本地派生向量已清理；授权状态未改变。",
                api.clear,
              );
            },
          }, "确认只清理本地向量"),
        ))
        : null,
      ));
  };
}
