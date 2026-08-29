import {
  activateEmbeddingCandidate,
  cancelEmbeddingCandidate,
  evaluateEmbeddingCandidate,
  getEmbeddingConfig,
  rebuildEmbeddingCandidate,
  rollbackEmbeddingGeneration,
  saveEmbeddingCandidate,
  testEmbeddingConnection,
} from "./api";
import { candidateCanActivate } from "./contracts";
import type {
  EmbeddingConfigResource,
  EmbeddingConnectionTestResult,
  SaveEmbeddingCandidateRequest,
  TestEmbeddingConnectionRequest,
} from "./contracts";
import { CONNECTION_LABELS, GENERATION_LABELS, formatDateTime } from "./presentation";
import { ensureEmbeddingStyles } from "./styles";
import type {
  EmbeddingAntdRuntime,
  EmbeddingReactRuntime,
  FocusableElement,
  InputChangeEvent,
} from "./ui-runtime";


export interface EmbeddingConfigPageApi {
  getConfig(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
  testConnection(
    payload: TestEmbeddingConnectionRequest,
    signal?: AbortSignal,
  ): Promise<EmbeddingConnectionTestResult>;
  saveCandidate(
    payload: SaveEmbeddingCandidateRequest,
    signal?: AbortSignal,
  ): Promise<EmbeddingConfigResource>;
  rebuildCandidate(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
  cancelCandidate(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
  evaluateCandidate(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
  activateCandidate(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
  rollback(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
}


export interface EmbeddingConfigPageProps {
  readonly className?: string;
  readonly onConfigurationChange?: (resource: EmbeddingConfigResource) => void;
}


type LoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | { readonly phase: "ready"; readonly resource: EmbeddingConfigResource };


interface FormState {
  readonly baseUrl: string;
  readonly modelId: string;
  readonly dimension: number;
  readonly apiKey: string;
}


interface OperationState {
  readonly busy: boolean;
  readonly message: string;
  readonly kind: "idle" | "success" | "error";
  readonly connectionResult: EmbeddingConnectionTestResult | null;
}


const DEFAULT_API: EmbeddingConfigPageApi = {
  getConfig: getEmbeddingConfig,
  testConnection: testEmbeddingConnection,
  saveCandidate: saveEmbeddingCandidate,
  rebuildCandidate: rebuildEmbeddingCandidate,
  cancelCandidate: cancelEmbeddingCandidate,
  evaluateCandidate: evaluateEmbeddingCandidate,
  activateCandidate: activateEmbeddingCandidate,
  rollback: rollbackEmbeddingGeneration,
};


const EMPTY_OPERATION: OperationState = {
  busy: false,
  message: "",
  kind: "idle",
  connectionResult: null,
};


function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}


function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message.trim() ? reason.message : fallback;
}


function formFromResource(resource: EmbeddingConfigResource): FormState {
  return {
    baseUrl: resource.base_url,
    modelId: resource.requested_model_id,
    dimension: resource.requested_dimension,
    apiKey: "",
  };
}


function tagColor(state: string): string {
  if (["ready", "active", "passed"].includes(state)) return "success";
  if (["failed"].includes(state)) return "error";
  if (["building", "pending", "untested"].includes(state)) return "processing";
  return "default";
}


export function createEmbeddingConfigPage(
  React: EmbeddingReactRuntime,
  antd: EmbeddingAntdRuntime,
  api: EmbeddingConfigPageApi = DEFAULT_API,
): (props: EmbeddingConfigPageProps) => unknown {
  const h = React.createElement;

  return function EmbeddingConfigPage(props: EmbeddingConfigPageProps): unknown {
    const [load, setLoad] = React.useState<LoadState>({ phase: "loading" });
    const [form, setForm] = React.useState<FormState>({
      baseUrl: "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
      modelId: "qwen3.7-text-embedding",
      dimension: 1024,
      apiKey: "",
    });
    const [operation, setOperation] = React.useState<OperationState>(EMPTY_OPERATION);
    const [confirmClearKey, setConfirmClearKey] = React.useState(false);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const actionAbortRef = React.useRef<AbortController | null>(null);
    const sequenceRef = React.useRef(0);
    const alertRef = React.useRef<FocusableElement | null>(null);
    const confirmRef = React.useRef<FocusableElement | null>(null);

    const applyResource = (resource: EmbeddingConfigResource) => {
      setLoad({ phase: "ready", resource });
      setForm(formFromResource(resource));
      props.onConfigurationChange?.(resource);
    };

    const loadConfig = () => {
      loadAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      const sequence = ++sequenceRef.current;
      setLoad({ phase: "loading" });
      void api.getConfig(controller.signal).then((resource) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        applyResource(resource);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current || isAbortError(reason)) return;
        setLoad({ phase: "error", message: errorMessage(reason, "加载向量模型配置失败。") });
      });
      return controller;
    };

    React.useEffect(() => {
      ensureEmbeddingStyles();
      const controller = loadConfig();
      return () => controller.abort();
    }, []);

    React.useEffect(() => () => {
      actionAbortRef.current?.abort();
    }, []);

    React.useEffect(() => {
      if (operation.kind === "error") alertRef.current?.focus({ preventScroll: true });
      if (confirmClearKey) confirmRef.current?.focus({ preventScroll: true });
    }, [operation.kind, confirmClearKey]);

    const updateForm = (patch: Partial<FormState>) => {
      setForm((current) => ({ ...current, ...patch }));
    };

    const runConfigAction = (
      pendingMessage: string,
      successMessage: string,
      action: (signal: AbortSignal) => Promise<EmbeddingConfigResource>,
    ) => {
      if (operation.busy) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      setOperation({ busy: true, message: pendingMessage, kind: "idle", connectionResult: null });
      void action(controller.signal).then((resource) => {
        if (controller.signal.aborted) return;
        applyResource(resource);
        setOperation({ busy: false, message: successMessage, kind: "success", connectionResult: null });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        setOperation({
          busy: false,
          message: errorMessage(reason, `${successMessage.replace("已", "")}失败。`),
          kind: "error",
          connectionResult: null,
        });
      });
    };

    const testConnection = () => {
      if (operation.busy) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      const payload: TestEmbeddingConnectionRequest = {
        base_url: form.baseUrl.trim(),
        requested_model_id: form.modelId.trim(),
        requested_dimension: form.dimension,
        ...(form.apiKey ? { api_key: form.apiKey } : {}),
      };
      setOperation({ busy: true, message: "正在发送非敏感哨兵验证模型与维度…", kind: "idle", connectionResult: null });
      void api.testConnection(payload, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        setOperation({
          busy: false,
          message: result.connection_state === "ready" ? "连接验证通过。" : "连接验证未通过。",
          kind: result.connection_state === "ready" ? "success" : "error",
          connectionResult: result,
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        setOperation({
          busy: false,
          message: errorMessage(reason, "测试连接失败。"),
          kind: "error",
          connectionResult: null,
        });
      }).finally(() => {
        if (!controller.signal.aborted) updateForm({ apiKey: "" });
      });
    };

    const saveCandidate = (keyAction: SaveEmbeddingCandidateRequest["api_key_action"]) => {
      const key = form.apiKey;
      const payload: SaveEmbeddingCandidateRequest = {
        base_url: form.baseUrl.trim(),
        requested_model_id: form.modelId.trim(),
        requested_dimension: form.dimension,
        api_key_action: keyAction,
        ...(keyAction === "replace" ? { api_key: key } : {}),
      };
      runConfigAction(
        keyAction === "clear" ? "正在清除凭据引用…" : "正在保存候选配置…",
        keyAction === "clear" ? "API Key 已清除；本地向量未删除。" : "候选配置已保存。",
        (signal) => api.saveCandidate(payload, signal),
      );
      updateForm({ apiKey: "" });
      setConfirmClearKey(false);
    };

    const rootClassName = ["anw-embedding-page", props.className ?? ""].filter(Boolean).join(" ");

    if (load.phase === "loading") {
      return h("main", { className: rootClassName, "aria-busy": true },
        h(antd.Spin, { tip: "正在加载向量模型配置…" }),
      );
    }
    if (load.phase === "error") {
      return h("main", { className: rootClassName },
        h(antd.Alert, {
          type: "error",
          showIcon: true,
          message: "无法加载向量模型接入页",
          description: load.message,
          action: h(antd.Button, { onClick: loadConfig }, "重新加载"),
        }),
      );
    }

    const resource = load.resource;
    const candidate = resource.candidate_generation;
    const candidateBuilding = candidate?.state === "building";
    const canActivate = candidateCanActivate(candidate);

    return h("main", {
      className: rootClassName,
      "aria-labelledby": "anw-embedding-config-heading",
      "aria-busy": operation.busy,
    },
    h("header", { className: "anw-embedding-page__header" },
      h("div", null,
        h("p", { className: "anw-embedding-muted" }, "PawApp 设置"),
        h("h2", { id: "anw-embedding-config-heading", tabIndex: -1 }, "向量模型接入"),
      ),
      h(antd.Tag, { color: tagColor(resource.connection_state) }, CONNECTION_LABELS[resource.connection_state]),
    ),
    resource.connection_state === "unconfigured"
      ? h(antd.Empty, { description: "尚未配置向量模型。填写下方候选配置后先测试连接。" })
      : null,
    h(antd.Alert, {
      type: "info",
      showIcon: true,
      message: "与正文生成模型相互独立",
      description: "此页面只配置阿里云百炼文本向量模型，不修改 AI 小说作家 Agent，也不新增向量数据库。",
    }),
    operation.message
      ? h("div", {
        className: "anw-embedding-live",
        role: operation.kind === "error" ? "alert" : "status",
        "aria-live": "polite",
        tabIndex: operation.kind === "error" ? -1 : undefined,
        ref: operation.kind === "error" ? alertRef : undefined,
      }, operation.message)
      : null,
    h(antd.Card, { title: "连接与候选配置" },
      h("div", { className: "anw-embedding-grid" },
        h("div", { className: "anw-embedding-readonly" },
          h("strong", null, "服务商"), h("span", null, resource.provider_label),
        ),
        h("div", { className: "anw-embedding-readonly" },
          h("strong", null, "协议"), h("span", null, resource.protocol_label),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, "Base URL"),
          h(antd.Input, {
            value: form.baseUrl,
            disabled: operation.busy,
            autoComplete: "url",
            onChange: (event: InputChangeEvent) => updateForm({ baseUrl: event.target.value }),
          }),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, "候选模型 ID"),
          h(antd.Input, {
            value: form.modelId,
            disabled: operation.busy,
            onChange: (event: InputChangeEvent) => updateForm({ modelId: event.target.value }),
          }),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, "候选维度"),
          h(antd.InputNumber, {
            value: form.dimension,
            min: 1,
            precision: 0,
            disabled: operation.busy,
            onChange: (value: number | null) => updateForm({ dimension: value ?? 1024 }),
          }),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, resource.api_key_configured ? "替换 API Key（可选）" : "API Key"),
          h(antd.Input, {
            type: "password",
            value: form.apiKey,
            disabled: operation.busy,
            autoComplete: "new-password",
            spellCheck: false,
            placeholder: resource.api_key_configured ? "留空则保持现有 Key" : "仅用于本次写入，不会回显",
            "aria-describedby": "anw-embedding-secret-help",
            onChange: (event: InputChangeEvent) => updateForm({ apiKey: event.target.value }),
          }),
          h("span", { id: "anw-embedding-secret-help", className: "anw-embedding-secret-note" },
            "Key 为 write-only：页面不会读取或回填；测试或保存后输入框会立即清空。",
          ),
        ),
      ),
      h("div", { className: "anw-embedding-actions" },
        h(antd.Button, { onClick: testConnection, loading: operation.busy }, "测试连接"),
        h(antd.Button, {
          type: "primary",
          disabled: !form.baseUrl.trim() || !form.modelId.trim() || form.dimension < 1,
          loading: operation.busy,
          onClick: () => saveCandidate(form.apiKey ? "replace" : "keep"),
        }, form.apiKey ? "保存候选配置并替换 Key" : "保存候选配置"),
        h(antd.Button, {
          danger: true,
          disabled: !resource.api_key_configured || operation.busy,
          onClick: () => setConfirmClearKey(true),
        }, "清除 API Key"),
      ),
      confirmClearKey
        ? h("section", {
          className: "anw-embedding-confirm",
          role: "alertdialog",
          "aria-labelledby": "anw-clear-key-heading",
          "aria-describedby": "anw-clear-key-description",
          tabIndex: -1,
          ref: confirmRef,
        },
        h("h3", { id: "anw-clear-key-heading" }, "确认清除 API Key"),
        h("p", { id: "anw-clear-key-description" },
          "清除后立即停止新的云端向量请求，但不会删除正文、事实、授权记录或已经保存在 PostgreSQL 中的本地向量。",
        ),
        h("div", { className: "anw-embedding-inline-actions" },
          h(antd.Button, { onClick: () => setConfirmClearKey(false) }, "取消"),
          h(antd.Button, { danger: true, onClick: () => saveCandidate("clear") }, "确认只清除 Key"),
        ))
        : null,
    ),
    h(antd.Card, { title: "索引代次" },
      h("dl", { className: "anw-embedding-metrics" },
        h("div", null, h("dt", null, "当前 active"), h("dd", null,
          resource.active_generation
            ? `${resource.active_generation.model_id} · ${resource.active_generation.dimension} 维 · 第 ${resource.active_generation.generation_number} 代`
            : "暂无",
        )),
        h("div", null, h("dt", null, "active 实际 revision"), h("dd", null,
          resource.active_generation?.actual_revision ?? "暂无",
        )),
        h("div", null, h("dt", null, "候选 generation"), h("dd", null,
          candidate
            ? `${GENERATION_LABELS[candidate.state]} · ${candidate.model_id} · ${candidate.dimension} 维`
            : "暂无候选",
        )),
        h("div", null, h("dt", null, "候选 fingerprint"), h("dd", null,
          candidate?.index_fingerprint ?? "暂无",
        )),
        h("div", null, h("dt", null, "已授权小说"), h("dd", null, resource.authorized_novel_count)),
        h("div", null, h("dt", null, "待构建 / 失败"), h("dd", null,
          `${resource.pending_rebuild_novel_count} / ${resource.failed_novel_count}`,
        )),
      ),
      candidate
        ? h("p", { className: "anw-embedding-muted" },
          `候选门禁：ready ${candidate.ready_novel_count}/${candidate.authorized_novel_count}，待处理 ${candidate.pending_novel_count}，失败 ${candidate.failed_novel_count}，检索评测 ${candidate.evaluation_state}。`,
        )
        : null,
      !canActivate && candidate
        ? h(antd.Alert, {
          type: "warning",
          showIcon: true,
          message: "候选尚未满足激活门禁",
          description: "全部已授权小说 ready、固定检索评测通过且模型维度与 fingerprint 一致后才可激活；旧 active 继续服务。",
        })
        : null,
      h("div", { className: "anw-embedding-actions" },
        h(antd.Button, {
          type: "primary",
          disabled: !candidate || candidateBuilding || operation.busy,
          onClick: () => runConfigAction(
            "正在为全部已授权小说构建候选代次…",
            "候选构建任务已启动。",
            api.rebuildCandidate,
          ),
        }, "构建候选 generation"),
        h(antd.Button, {
          disabled: !candidateBuilding || operation.busy,
          onClick: () => runConfigAction(
            "正在取消候选构建…",
            "候选构建已取消；旧 active 继续服务。",
            api.cancelCandidate,
          ),
        }, "取消候选重建"),
        h(antd.Button, {
          disabled: !candidate
            || candidate.state !== "ready"
            || candidate.pending_novel_count !== 0
            || candidate.failed_novel_count !== 0
            || operation.busy,
          onClick: () => runConfigAction(
            "正在运行固定检索评测…",
            "固定检索评测已完成；通过后才能激活候选代次。",
            api.evaluateCandidate,
          ),
        }, "运行检索评测"),
        h(antd.Button, {
          type: "primary",
          disabled: !canActivate || operation.busy,
          title: canActivate ? undefined : "候选未 ready 或检索评测未通过",
          onClick: () => runConfigAction(
            "正在激活候选代次…",
            "候选代次已激活。",
            api.activateCandidate,
          ),
        }, "激活候选"),
        h(antd.Button, {
          disabled: !resource.previous_generation || operation.busy,
          onClick: () => runConfigAction(
            "正在回退上一代 active…",
            "已回退上一代 active。",
            api.rollback,
          ),
        }, "回退上一代 active"),
      ),
    ),
    h(antd.Card, { title: "最近连接证据" },
      resource.last_request
        ? h("dl", { className: "anw-embedding-metrics" },
          h("div", null, h("dt", null, "Request ID"), h("dd", null, resource.last_request.request_id ?? "暂无")),
          h("div", null, h("dt", null, "Token"), h("dd", null, resource.last_request.token_count ?? "暂无")),
          h("div", null, h("dt", null, "延迟"), h("dd", null,
            resource.last_request.latency_ms === null ? "暂无" : `${resource.last_request.latency_ms} ms`,
          )),
          h("div", null, h("dt", null, "观测时间"), h("dd", null, formatDateTime(resource.last_request.observed_at))),
          h("div", null, h("dt", null, "脱敏错误摘要"), h("dd", null, resource.last_request.error_summary ?? "无")),
        )
        : h(antd.Empty, { description: "尚无连接测试证据" }),
      operation.connectionResult
        ? h("p", { className: "anw-embedding-muted" },
          `本次实际模型 ${operation.connectionResult.actual_model_id ?? "未确认"}，实际维度 ${operation.connectionResult.actual_dimension ?? "未确认"}。`,
        )
        : null,
    ));
  };
}
