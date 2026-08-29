import {
  activateEmbeddingCandidate,
  cancelEmbeddingCandidate,
  evaluateEmbeddingCandidate,
  getEmbeddingConfig,
  initializeEmbeddingSecretStore,
  rebuildEmbeddingCandidate,
  rollbackEmbeddingGeneration,
  saveEmbeddingCandidate,
  testEmbeddingConnection,
} from "./api";
import {
  DEFAULT_EMBEDDING_DIMENSION,
  SUPPORTED_EMBEDDING_DIMENSIONS,
  candidateCanActivate,
} from "./contracts";
import type {
  EmbeddingConfigResource,
  EmbeddingConnectionTestResult,
  SaveEmbeddingCandidateRequest,
  TestEmbeddingConnectionRequest,
} from "./contracts";
import {
  CONNECTION_LABELS,
  EVALUATION_LABELS,
  GENERATION_LABELS,
  formatEmbeddingReason,
  formatDateTime,
} from "./presentation";
import { ensureEmbeddingStyles } from "./styles";
import type {
  EmbeddingAntdRuntime,
  EmbeddingReactRuntime,
  FocusableElement,
  InputChangeEvent,
} from "./ui-runtime";


export interface EmbeddingConfigPageApi {
  getConfig(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
  initializeSecretStore(signal?: AbortSignal): Promise<EmbeddingConfigResource>;
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
}


type CredentialDraftState = "empty" | "invalid" | "valid";


interface PasswordInputHandle {
  readonly input: { value: string } | null;
}


interface OperationState {
  readonly busy: boolean;
  readonly message: string;
  readonly kind: "idle" | "success" | "error";
  readonly connectionResult: EmbeddingConnectionTestResult | null;
}


const DEFAULT_API: EmbeddingConfigPageApi = {
  getConfig: getEmbeddingConfig,
  initializeSecretStore: initializeEmbeddingSecretStore,
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


function validBaseUrl(value: string): boolean {
  try {
    const parsed = new URL(value.trim());
    const labels = parsed.hostname.split(".");
    return parsed.protocol === "https:"
      && parsed.port === ""
      && labels.length >= 5
      && parsed.hostname.endsWith(".maas.aliyuncs.com")
      && /^[a-z0-9-]+$/.test(labels[0] ?? "")
      && parsed.pathname.replace(/\/$/, "") === "/api/v1"
      && !parsed.search
      && !parsed.hash;
  } catch {
    return false;
  }
}


function formFromResource(resource: EmbeddingConfigResource): FormState {
  return {
    baseUrl: resource.base_url,
    modelId: resource.requested_model_id,
    dimension: resource.requested_dimension,
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
      dimension: DEFAULT_EMBEDDING_DIMENSION,
    });
    const [credentialDraftState, setCredentialDraftState] = React.useState<CredentialDraftState>(
      "empty",
    );
    const [operation, setOperation] = React.useState<OperationState>(EMPTY_OPERATION);
    const [confirmClearKey, setConfirmClearKey] = React.useState(false);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const actionAbortRef = React.useRef<AbortController | null>(null);
    const sequenceRef = React.useRef(0);
    const alertRef = React.useRef<FocusableElement | null>(null);
    const confirmRef = React.useRef<FocusableElement | null>(null);
    const credentialInputRef = React.useRef<PasswordInputHandle | null>(null);

    const clearCredentialDraft = () => {
      if (credentialInputRef.current?.input) credentialInputRef.current.input.value = "";
      setCredentialDraftState("empty");
    };

    const applyResource = (resource: EmbeddingConfigResource) => {
      setLoad({ phase: "ready", resource });
      setForm(formFromResource(resource));
      clearCredentialDraft();
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
    }, [operation.kind, operation.message, confirmClearKey]);

    const updateForm = (patch: Partial<FormState>) => {
      setForm((current) => ({ ...current, ...patch }));
    };

    const runConfigAction = (
      pendingMessage: string,
      successMessage: string,
      failureMessage: string,
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
          message: errorMessage(reason, failureMessage),
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
        ...(credentialDraftState === "valid"
          ? { api_key: credentialInputRef.current?.input?.value ?? "" }
          : {}),
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
      });
    };

    const saveCandidate = (keyAction: SaveEmbeddingCandidateRequest["api_key_action"]) => {
      const key = credentialInputRef.current?.input?.value ?? "";
      const payload: SaveEmbeddingCandidateRequest = {
        expected_version: resource.version,
        base_url: form.baseUrl.trim(),
        requested_model_id: form.modelId.trim(),
        requested_dimension: form.dimension,
        api_key_action: keyAction,
        ...(keyAction === "replace" ? { api_key: key } : {}),
      };
      runConfigAction(
        keyAction === "clear" ? "正在清除凭据引用…" : "正在验证并保存候选配置…",
        keyAction === "clear" ? "API Key 已清除；本地向量未删除。" : "候选配置已验证并保存。",
        keyAction === "clear" ? "清除 API Key 失败。" : "验证并保存候选配置失败。",
        (signal) => api.saveCandidate(payload, signal),
      );
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
    const baseUrlValid = validBaseUrl(form.baseUrl);
    const modelValid = form.modelId.trim().length > 0;
    const dimensionValid = SUPPORTED_EMBEDDING_DIMENSIONS.includes(
      form.dimension as (typeof SUPPORTED_EMBEDDING_DIMENSIONS)[number],
    );
    const credentialReady = credentialDraftState === "valid"
      || (credentialDraftState === "empty" && resource.api_key_configured);
    const formReady = resource.secret_store_ready
      && baseUrlValid
      && modelValid
      && dimensionValid
      && credentialReady;
    const hasUnsavedChanges = form.baseUrl.trim() !== resource.base_url
      || form.modelId.trim() !== resource.requested_model_id
      || form.dimension !== resource.requested_dimension
      || credentialDraftState !== "empty";
    const credentialDisplay = credentialDraftState !== "empty"
      ? (credentialDraftState === "valid" ? "API Key 待验证" : null)
      : resource.api_key_masked ?? (resource.api_key_configured ? "API Key 已配置" : null);

    return h("main", {
      className: rootClassName,
      "aria-labelledby": "anw-embedding-config-heading",
      "aria-busy": operation.busy,
    },
    h("header", { className: "anw-embedding-page__header anw-embedding-hero" },
      h("div", null,
        h("p", { className: "anw-embedding-eyebrow" }, "语义检索设置"),
        h("h2", { id: "anw-embedding-config-heading", tabIndex: -1 }, "向量模型接入"),
        h("p", { className: "anw-embedding-hero__summary" },
          "连接阿里云百炼文本向量模型，为长篇小说提供可恢复、可审计的语义检索。",
        ),
      ),
      h("div", { className: "anw-embedding-hero__tags", "aria-label": "当前接入状态" },
        h(antd.Tag, { color: tagColor(resource.connection_state) }, CONNECTION_LABELS[resource.connection_state]),
        h(antd.Tag, { color: resource.secret_store_ready ? "success" : "error" },
          resource.secret_store_ready ? "密钥保险箱正常" : "密钥保险箱未初始化",
        ),
      ),
    ),
    h("section", { className: "anw-embedding-steps", "aria-label": "向量模型接入进度" },
      h("div", { "data-state": resource.secret_store_ready ? "done" : "current" },
        h("span", { "aria-hidden": true }, "1"),
        h("strong", null, "部署密钥保险箱"),
        h("small", null, resource.secret_store_ready ? "部署已完成" : "部署项缺失"),
      ),
      h("div", { "data-state": resource.connection_state === "ready" ? "done" : "current" },
        h("span", { "aria-hidden": true }, "2"),
        h("strong", null, "验证模型连接"),
        h("small", null, resource.connection_state === "ready" ? "已通过" : "等待验证"),
      ),
      h("div", { "data-state": resource.active_generation ? "done" : "pending" },
        h("span", { "aria-hidden": true }, "3"),
        h("strong", null, "激活语义索引"),
        h("small", null, resource.active_generation ? "使用中" : "尚未激活"),
      ),
    ),
    !resource.secret_store_ready
      ? h(antd.Alert, {
        type: "error",
        showIcon: true,
        message: "向量密钥保险箱尚未初始化",
        description: "正常安装应由部署脚本完成此步骤。仅在本机单用户环境恢复时，才使用下方按钮按项目固定路径初始化。",
        action: h(antd.Button, {
          loading: operation.busy,
          onClick: () => runConfigAction(
            "正在初始化向量密钥保险箱…",
            "向量密钥保险箱已初始化。",
            "初始化向量密钥保险箱失败。",
            api.initializeSecretStore,
          ),
        }, "本机恢复初始化"),
      })
      : null,
    resource.credential_cleanup_warning
      ? h(antd.Alert, {
        type: "warning",
        showIcon: true,
        message: "旧凭据需要人工检查",
        description: resource.credential_cleanup_warning,
      })
      : null,
    resource.connection_state === "unconfigured"
      ? h(antd.Empty, { description: "尚未配置向量模型。填写下方候选配置后先测试连接。" })
      : null,
    h(antd.Alert, {
      type: "info",
      showIcon: true,
      message: "与正文生成模型相互独立",
      description: "此页面只配置阿里云百炼文本向量模型，不修改 AI 小说作家 Agent，也不新增向量数据库。",
    }),
    hasUnsavedChanges
      ? h(antd.Alert, {
        type: "warning",
        showIcon: true,
        message: "当前有尚未保存的配置",
        description: "请先验证并保存配置，再管理候选索引。",
      })
      : null,
    operation.message
      ? h("div", {
        className: "anw-embedding-live",
        role: operation.kind === "error" ? "alert" : "status",
        "aria-live": "polite",
        tabIndex: operation.kind === "error" ? -1 : undefined,
        ref: operation.kind === "error" ? alertRef : undefined,
      }, operation.message)
      : null,
    h(antd.Card, { title: "连接配置", className: "anw-embedding-card" },
      h("div", { className: "anw-embedding-grid" },
        h("div", { className: "anw-embedding-readonly" },
          h("strong", null, "服务商"), h("span", null, resource.provider_label),
        ),
        h("div", { className: "anw-embedding-readonly" },
          h("strong", null, "协议"), h("span", null, resource.protocol_label),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, "服务地址（Base URL）"),
          h(antd.Input, {
            value: form.baseUrl,
            disabled: operation.busy,
            autoComplete: "url",
            onChange: (event: InputChangeEvent) => updateForm({ baseUrl: event.target.value }),
          }),
          !baseUrlValid
            ? h("span", { className: "anw-embedding-field-error", role: "alert" },
              "请输入以 /api/v1 结尾的阿里云百炼工作空间 HTTPS 地址。",
            )
            : h("span", { className: "anw-embedding-secret-note" },
              "地域由服务地址决定，无需单独选择。",
            ),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, "模型名称"),
          h(antd.Input, {
            value: form.modelId,
            disabled: operation.busy,
            onChange: (event: InputChangeEvent) => updateForm({ modelId: event.target.value }),
          }),
          !modelValid
            ? h("span", { className: "anw-embedding-field-error", role: "alert" },
              "模型名称不能为空。",
            )
            : null,
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, "向量维度"),
          h(antd.Select, {
            value: form.dimension,
            options: SUPPORTED_EMBEDDING_DIMENSIONS.map((dimension) => ({
              value: dimension,
              label: `${dimension} 维`,
            })),
            disabled: operation.busy,
            onChange: (value: number) => updateForm({ dimension: value }),
          }),
          h("span", { className: "anw-embedding-secret-note" },
            "正式默认使用 2048 维；切换维度会创建新的候选索引空间。",
          ),
        ),
        h("label", { className: "anw-embedding-field" },
          h("span", null, resource.api_key_configured ? "替换 API Key（可选）" : "API Key"),
          h(antd.Input, {
            type: "password",
            defaultValue: "",
            ref: credentialInputRef,
            disabled: operation.busy || !resource.secret_store_ready,
            autoComplete: "new-password",
            spellCheck: false,
            placeholder: resource.api_key_configured ? "留空则保持现有 Key" : "仅用于本次写入，不会回显",
            "aria-describedby": "anw-embedding-secret-help",
            onChange: (event: InputChangeEvent) => {
              const length = event.target.value.trim().length;
              setCredentialDraftState(length === 0 ? "empty" : length >= 16 ? "valid" : "invalid");
            },
          }),
          h("span", { id: "anw-embedding-secret-help", className: "anw-embedding-secret-note" },
            "API Key 采用只写保护：完整内容不会从接口回显，保存后最多显示数据库记录的末 4 位。",
          ),
          credentialDraftState === "invalid"
            ? h("span", { className: "anw-embedding-field-error", role: "alert" },
              "API Key 至少需要 16 个字符。",
            )
            : null,
        ),
        h("div", { className: "anw-embedding-credential" },
          h("strong", null, credentialDraftState !== "empty" ? "待保存凭据" : "当前凭据"),
          h("code", {
            "aria-label": credentialDisplay
              ? "API Key 状态（已脱敏）"
              : "尚未保存 API Key",
          }, credentialDisplay ?? (resource.api_key_configured ? "凭据不可用" : "尚未保存")),
          h("small", null, "数据库仅保留末 4 位；完整 Key 只在服务端密钥保险箱中加密保存。"),
        ),
      ),
      h("div", { className: "anw-embedding-actions" },
        h(antd.Button, {
          disabled: !formReady || operation.busy,
          onClick: testConnection,
          loading: operation.busy,
        }, "仅测试连接（不保存）"),
        h(antd.Button, {
          type: "primary",
          disabled: !formReady || operation.busy,
          loading: operation.busy,
          onClick: () => saveCandidate(credentialDraftState === "valid" ? "replace" : "keep"),
        }, credentialDraftState !== "empty" ? "验证并保存新 API Key" : "验证并保存配置"),
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
    h(antd.Card, { title: "索引管理", className: "anw-embedding-card" },
      h("dl", { className: "anw-embedding-metrics" },
        h("div", null, h("dt", null, "当前生效索引"), h("dd", null,
          resource.active_generation
            ? `${resource.active_generation.model_id} · ${resource.active_generation.dimension} 维 · 第 ${resource.active_generation.generation_number} 代`
            : "暂无",
        )),
        h("div", null, h("dt", null, "生效模型实际版本"), h("dd", null,
          resource.active_generation?.actual_revision ?? "暂无",
        )),
        h("div", null, h("dt", null, "候选索引代次"), h("dd", null,
          candidate
            ? `${GENERATION_LABELS[candidate.state]} · ${candidate.model_id} · ${candidate.dimension} 维`
            : "暂无候选",
        )),
        h("div", null, h("dt", null, "候选索引指纹"), h("dd", null,
          candidate?.index_fingerprint ?? "暂无",
        )),
        h("div", null, h("dt", null, "已授权小说"), h("dd", null, resource.authorized_novel_count)),
        h("div", null, h("dt", null, "待构建 / 失败"), h("dd", null,
          `${resource.pending_rebuild_novel_count} / ${resource.failed_novel_count}`,
        )),
      ),
      candidate
        ? h("p", { className: "anw-embedding-muted" },
          `候选门禁：已就绪 ${candidate.ready_novel_count}/${candidate.authorized_novel_count}，待处理 ${candidate.pending_novel_count}，失败 ${candidate.failed_novel_count}，检索评测${EVALUATION_LABELS[candidate.evaluation_state]}。`,
        )
        : null,
      !canActivate && candidate
        ? h(antd.Alert, {
          type: "warning",
          showIcon: true,
          message: "候选尚未满足激活门禁",
          description: "全部已授权小说就绪、固定检索评测通过且模型维度与索引指纹一致后才可激活；当前生效索引继续服务。",
        })
        : null,
      h("div", { className: "anw-embedding-actions" },
        h(antd.Button, {
          type: "primary",
          disabled: !candidate || candidateBuilding || operation.busy || hasUnsavedChanges,
          onClick: () => runConfigAction(
            "正在为全部已授权小说构建候选代次…",
            "候选构建任务已启动。",
            "启动候选索引构建失败。",
            api.rebuildCandidate,
          ),
        }, "构建候选索引"),
        h(antd.Button, {
          disabled: !candidateBuilding || operation.busy || hasUnsavedChanges,
          onClick: () => runConfigAction(
            "正在取消候选构建…",
            "候选构建已取消；当前生效索引继续服务。",
            "取消候选索引构建失败。",
            api.cancelCandidate,
          ),
        }, "取消候选重建"),
        h(antd.Button, {
          disabled: !candidate
            || candidate.state !== "ready"
            || candidate.pending_novel_count !== 0
            || candidate.failed_novel_count !== 0
            || operation.busy
            || hasUnsavedChanges,
          onClick: () => runConfigAction(
            "正在运行固定检索评测…",
            "固定检索评测已完成；通过后才能激活候选代次。",
            "运行候选检索评测失败。",
            api.evaluateCandidate,
          ),
        }, "运行检索评测"),
        h(antd.Button, {
          type: "primary",
          disabled: !canActivate || operation.busy || hasUnsavedChanges,
          title: canActivate ? undefined : "候选尚未就绪或检索评测未通过",
          onClick: () => runConfigAction(
            "正在激活候选代次…",
            "候选代次已激活。",
            "激活候选索引失败。",
            api.activateCandidate,
          ),
        }, "激活候选"),
        h(antd.Button, {
          disabled: !resource.previous_generation || operation.busy || hasUnsavedChanges,
          onClick: () => runConfigAction(
            "正在回退上一代索引…",
            "已回退上一代索引。",
            "回退上一代索引失败。",
            api.rollback,
          ),
        }, "回退上一代索引"),
      ),
    ),
    h(antd.Card, { title: "最近连接记录", className: "anw-embedding-card anw-embedding-card--diagnostics" },
      resource.last_request
        ? h("dl", { className: "anw-embedding-metrics" },
          h("div", null, h("dt", null, "查询请求编号"), h("dd", null, resource.last_request.request_id ?? "暂无")),
          h("div", null, h("dt", null, "文档请求编号"), h("dd", null,
            resource.last_request.document_request_id ?? "暂无",
          )),
          h("div", null, h("dt", null, "输入令牌数"), h("dd", null, resource.last_request.token_count ?? "暂无")),
          h("div", null, h("dt", null, "耗时"), h("dd", null,
            resource.last_request.latency_ms === null ? "暂无" : `${resource.last_request.latency_ms} 毫秒`,
          )),
          h("div", null, h("dt", null, "观测时间"), h("dd", null, formatDateTime(resource.last_request.observed_at))),
          h("div", null, h("dt", null, "脱敏错误摘要"), h("dd", null,
            resource.last_request.error_summary
              ? formatEmbeddingReason(resource.last_request.error_summary)
              : "无",
          )),
        )
        : h(antd.Empty, { description: "尚无连接测试证据" }),
      operation.connectionResult
        ? h("div", { className: "anw-embedding-test-evidence" },
          h("p", { className: "anw-embedding-muted" },
            `本次验证模型 ${operation.connectionResult.actual_model_id ?? "未确认"}，实际维度 ${operation.connectionResult.actual_dimension ?? "未确认"}。`,
          ),
          h("small", null,
            `查询请求编号：${operation.connectionResult.request_id ?? "暂无"}；文档请求编号：${operation.connectionResult.document_request_id ?? "暂无"}。`,
          ),
        )
        : null,
    ));
  };
}
