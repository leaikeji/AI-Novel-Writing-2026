import {
  activateTtsCloudProfile,
  createTtsCloudProfile,
  deleteTtsCloudProfile,
  disableTtsCloudProfile,
  getTtsCloudProfiles,
  testTtsCloudProfile,
  updateTtsCloudProfile,
} from "./api";
import { TTS_CLOUD_PROTOCOL } from "./contracts";
import type {
  CreateTtsCloudProfileRequest,
  TestTtsCloudProfileRequest,
  TtsCloudLifecycleState,
  TtsCloudModelSlot,
  TtsCloudProfile,
  TtsCloudProfilesResource,
  TtsCloudProfileTestResponse,
  TtsCloudTestState,
  UpdateTtsCloudProfileRequest,
} from "./contracts";
import type {
  CheckedChangeEvent,
  CloudConfigAntdRuntime,
  CloudConfigReactRuntime,
  FocusableElement,
  InputChangeEvent,
  PasswordInputHandle,
} from "./ui-runtime";
import { ensureTtsCloudConfigStyles } from "./styles";


export interface TtsCloudConfigPageApi {
  getProfiles(signal?: AbortSignal): Promise<TtsCloudProfilesResource>;
  createProfile(
    payload: CreateTtsCloudProfileRequest,
    signal?: AbortSignal,
  ): Promise<TtsCloudProfilesResource>;
  updateProfile(
    profileId: string,
    payload: UpdateTtsCloudProfileRequest,
    signal?: AbortSignal,
  ): Promise<TtsCloudProfilesResource>;
  testProfile(
    profileId: string,
    payload: TestTtsCloudProfileRequest,
    signal?: AbortSignal,
  ): Promise<TtsCloudProfileTestResponse>;
  activateProfile(
    profileId: string,
    payload: { readonly expected_version: number; readonly idempotency_key: string },
    signal?: AbortSignal,
  ): Promise<TtsCloudProfilesResource>;
  disableProfile(
    profileId: string,
    payload: { readonly expected_version: number; readonly idempotency_key: string },
    signal?: AbortSignal,
  ): Promise<TtsCloudProfilesResource>;
  deleteProfile(
    profileId: string,
    payload: { readonly expected_version: number; readonly idempotency_key: string },
    signal?: AbortSignal,
  ): Promise<TtsCloudProfilesResource>;
}


export interface TtsCloudConfigPageProps {
  readonly className?: string;
  readonly onBack?: () => void;
  readonly onConfigurationChange?: (resource: TtsCloudProfilesResource) => void;
  readonly localRuntimeStatus?: {
    readonly state: "loading" | "ready" | "unavailable";
    readonly label: string;
    readonly detail?: string;
  };
}


type LoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | { readonly phase: "ready"; readonly resource: TtsCloudProfilesResource };


interface FormState {
  readonly name: string;
  readonly baseUrl: string;
  readonly qualityModelId: string;
  readonly speedModelId: string;
}


type EditorState =
  | { readonly mode: "create" }
  | { readonly mode: "edit"; readonly profileId: string };


type ConfirmationState =
  | { readonly kind: "test"; readonly profileId: string; readonly slot: TtsCloudModelSlot }
  | { readonly kind: "activate" | "disable" | "delete"; readonly profileId: string };


interface OperationState {
  readonly busy: boolean;
  readonly kind: "idle" | "success" | "error";
  readonly message: string;
}


interface LastTestEvidence {
  readonly profileId: string;
  readonly slot: TtsCloudModelSlot;
  readonly status: "passed" | "failed";
  readonly actualModelId: string | null;
  readonly sampleRateHz: number | null;
  readonly failureCode: string | null;
  readonly audioUrl: string | null;
}


const DEFAULT_API: TtsCloudConfigPageApi = {
  getProfiles: getTtsCloudProfiles,
  createProfile: createTtsCloudProfile,
  updateProfile: updateTtsCloudProfile,
  testProfile: testTtsCloudProfile,
  activateProfile: activateTtsCloudProfile,
  disableProfile: disableTtsCloudProfile,
  deleteProfile: deleteTtsCloudProfile,
};


const EMPTY_FORM: FormState = {
  name: "",
  baseUrl: "",
  qualityModelId: "",
  speedModelId: "",
};


const EMPTY_OPERATION: OperationState = { busy: false, kind: "idle", message: "" };


function normalizeHttpsBaseUrl(value: string): string {
  const normalized = value.trim();
  if (!normalized || /^[a-z][a-z\d+.-]*:\/\//i.test(normalized)) return normalized;
  return `https://${normalized}`;
}


const LIFECYCLE_LABELS: Readonly<Record<TtsCloudLifecycleState, string>> = {
  draft: "未验证",
  verified: "已验证",
  active: "使用中",
  disabled: "已停用",
};


const TEST_LABELS: Readonly<Record<TtsCloudTestState, string>> = {
  untested: "未测试",
  testing: "验证中",
  passed: "已通过",
  failed: "不可用",
};


function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}


function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message.trim() ? reason.message : fallback;
}


function formFromProfile(profile: TtsCloudProfile): FormState {
  return {
    name: profile.name,
    baseUrl: profile.base_url,
    qualityModelId: profile.quality_model_id,
    speedModelId: profile.speed_model_id ?? "",
  };
}


function lifecycleColor(state: TtsCloudLifecycleState): string {
  if (state === "active") return "success";
  if (state === "verified") return "processing";
  if (state === "disabled") return "default";
  return "warning";
}


function testColor(state: TtsCloudTestState): string {
  if (state === "passed") return "success";
  if (state === "failed") return "error";
  if (state === "testing") return "processing";
  return "default";
}


function formatDateTime(value: string | null): string {
  if (!value) return "尚未测试";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间不可用" : date.toLocaleString("zh-CN");
}


export function createTtsCloudIdempotencyKey(kind: "create" | "update" | "test" | "mutate"): string {
  const randomId = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `tts-cloud-${kind}-${randomId}`;
}


function createAudioUrl(result: TtsCloudProfileTestResponse): string | null {
  if (!result.audio_base64 || !result.content_type || typeof atob !== "function") return null;
  try {
    const binary = atob(result.audio_base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return URL.createObjectURL(new Blob([bytes], { type: result.content_type }));
  } catch {
    return null;
  }
}


export function createTtsCloudConfigPage(
  React: CloudConfigReactRuntime,
  antd: CloudConfigAntdRuntime,
  api: TtsCloudConfigPageApi = DEFAULT_API,
): (props: TtsCloudConfigPageProps) => unknown {
  const h = React.createElement;

  return function TtsCloudConfigPage(props: TtsCloudConfigPageProps): unknown {
    const [load, setLoad] = React.useState<LoadState>({ phase: "loading" });
    const [editor, setEditor] = React.useState<EditorState | null>(null);
    const [form, setForm] = React.useState<FormState>(EMPTY_FORM);
    const [keyDraftState, setKeyDraftState] = React.useState<"empty" | "invalid" | "valid">("empty");
    const [confirmation, setConfirmation] = React.useState<ConfirmationState | null>(null);
    const [billingAcknowledged, setBillingAcknowledged] = React.useState(false);
    const [operation, setOperation] = React.useState<OperationState>(EMPTY_OPERATION);
    const [lastTest, setLastTest] = React.useState<LastTestEvidence | null>(null);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const actionAbortRef = React.useRef<AbortController | null>(null);
    const credentialInputRef = React.useRef<PasswordInputHandle | null>(null);
    const dialogRef = React.useRef<FocusableElement | null>(null);
    const alertRef = React.useRef<FocusableElement | null>(null);
    const audioUrlRef = React.useRef<string | null>(null);
    const sequenceRef = React.useRef(0);

    const clearCredentialDraft = () => {
      if (credentialInputRef.current?.input) credentialInputRef.current.input.value = "";
      setKeyDraftState("empty");
    };

    const applyResource = (resource: TtsCloudProfilesResource) => {
      setLoad({ phase: "ready", resource });
      props.onConfigurationChange?.(resource);
    };

    const loadProfiles = () => {
      loadAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      const sequence = ++sequenceRef.current;
      setLoad({ phase: "loading" });
      void api.getProfiles(controller.signal).then((resource) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        applyResource(resource);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current || isAbortError(reason)) return;
        setLoad({ phase: "error", message: errorMessage(reason, "加载语音模型渠道失败。") });
      });
      return controller;
    };

    React.useEffect(() => {
      ensureTtsCloudConfigStyles();
      const controller = loadProfiles();
      return () => controller.abort();
    }, []);

    React.useEffect(() => () => {
      actionAbortRef.current?.abort();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    }, []);

    React.useEffect(() => {
      if (confirmation) dialogRef.current?.focus({ preventScroll: true });
      if (operation.kind === "error") alertRef.current?.focus({ preventScroll: true });
    }, [confirmation, operation.kind, operation.message]);

    const closeEditor = () => {
      setEditor(null);
      setForm(EMPTY_FORM);
      clearCredentialDraft();
    };

    const beginCreate = () => {
      setForm(EMPTY_FORM);
      clearCredentialDraft();
      setEditor({ mode: "create" });
    };

    const beginEdit = (profile: TtsCloudProfile) => {
      setForm(formFromProfile(profile));
      clearCredentialDraft();
      setEditor({ mode: "edit", profileId: profile.id });
    };

    const beginConfirmation = (next: ConfirmationState) => {
      setBillingAcknowledged(false);
      setConfirmation(next);
    };

    const runCollectionAction = (
      pending: string,
      success: string,
      failure: string,
      action: (signal: AbortSignal) => Promise<TtsCloudProfilesResource>,
      afterSuccess?: () => void,
    ) => {
      if (operation.busy) return;
      actionAbortRef.current?.abort();
      const controller = new AbortController();
      actionAbortRef.current = controller;
      setOperation({ busy: true, kind: "idle", message: pending });
      void action(controller.signal).then((resource) => {
        if (controller.signal.aborted) return;
        applyResource(resource);
        setOperation({ busy: false, kind: "success", message: success });
        afterSuccess?.();
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        setOperation({ busy: false, kind: "error", message: errorMessage(reason, failure) });
      });
    };

    if (load.phase === "loading") {
      return h("main", { className: props.className, "aria-busy": true },
        h(antd.Spin, { tip: "正在加载语音模型渠道…" }),
      );
    }
    if (load.phase === "error") {
      return h("main", { className: props.className },
        h(antd.Alert, {
          type: "error",
          showIcon: true,
          message: "无法加载语音模型接入页",
          description: load.message,
          action: h(antd.Button, { htmlType: "button", onClick: loadProfiles }, "重新加载"),
        }),
      );
    }

    const resource = load.resource;
    const editingProfile = editor?.mode === "edit"
      ? resource.items.find((item) => item.id === editor.profileId) ?? null
      : null;
    const formReady = Boolean(form.name.trim() && form.baseUrl.trim() && form.qualityModelId.trim());

    const saveProfile = () => {
      if (!editor || !formReady || keyDraftState === "invalid" || operation.busy) return;
      const apiKey = credentialInputRef.current?.input?.value.trim() ?? "";
      const fields = {
        name: form.name.trim(),
        protocol: TTS_CLOUD_PROTOCOL,
        base_url: normalizeHttpsBaseUrl(form.baseUrl),
        quality_model_id: form.qualityModelId.trim(),
        speed_model_id: form.speedModelId.trim() || null,
        ...(apiKey ? { api_key: apiKey } : {}),
      } as const;
      if (editor.mode === "create") {
        runCollectionAction(
          "正在保存语音渠道…",
          "语音渠道已保存；尚未发起任何付费测试。",
          "新增语音渠道失败。",
          (signal) => api.createProfile({
            ...fields,
            expected_version: 0,
            idempotency_key: createTtsCloudIdempotencyKey("create"),
          }, signal),
          closeEditor,
        );
        return;
      }
      if (!editingProfile) return;
      runCollectionAction(
        "正在保存语音渠道…",
        "语音渠道已保存；尚未发起任何付费测试。",
        "保存语音渠道失败。",
        (signal) => api.updateProfile(editingProfile.id, {
          ...fields,
          expected_version: editingProfile.version,
          idempotency_key: createTtsCloudIdempotencyKey("update"),
        }, signal),
        closeEditor,
      );
    };

    const confirmAction = () => {
      if (!confirmation || operation.busy) return;
      const profile = resource.items.find((item) => item.id === confirmation.profileId);
      if (!profile) return;
      if (confirmation.kind === "test") {
        if (!billingAcknowledged) return;
        const slot = confirmation.slot;
        const payload: TestTtsCloudProfileRequest = {
          expected_version: profile.version,
          slot,
          billing_confirmed: true,
          idempotency_key: createTtsCloudIdempotencyKey("test"),
        };
        actionAbortRef.current?.abort();
        const controller = new AbortController();
        actionAbortRef.current = controller;
        setConfirmation(null);
        setOperation({ busy: true, kind: "idle", message: `正在测试${slot === "quality" ? "质量" : "速度"}模型…` });
        void api.testProfile(profile.id, payload, controller.signal).then((result) => {
          if (controller.signal.aborted) return;
          if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
          const audioUrl = createAudioUrl(result);
          audioUrlRef.current = audioUrl;
          const items = resource.items.map((item) => item.id === result.profile.id ? result.profile : item);
          applyResource({ ...resource, items });
          setLastTest({
            profileId: result.profile.id,
            slot: result.slot,
            status: result.status,
            actualModelId: result.actual_model_id,
            sampleRateHz: result.sample_rate_hz,
            failureCode: result.failure_code,
            audioUrl,
          });
          setOperation({
            busy: false,
            kind: result.status === "passed" ? "success" : "error",
            message: result.status === "passed" ? "模型测试通过，可试听固定短句。" : "模型测试未通过。",
          });
        }).catch((reason: unknown) => {
          if (controller.signal.aborted || isAbortError(reason)) return;
          setOperation({ busy: false, kind: "error", message: errorMessage(reason, "测试语音模型失败。") });
        });
        return;
      }
      setConfirmation(null);
      if (confirmation.kind === "activate") {
        runCollectionAction(
          "正在启用语音渠道…",
          "语音渠道已启用，只影响之后新建的朗读任务。",
          "启用语音渠道失败。",
          (signal) => api.activateProfile(profile.id, {
            expected_version: profile.version,
            idempotency_key: createTtsCloudIdempotencyKey("mutate"),
          }, signal),
        );
      } else if (confirmation.kind === "disable") {
        runCollectionAction(
          "正在停用语音渠道…",
          "语音渠道已停用；本地朗读和历史音频不受影响。",
          "停用语音渠道失败。",
          (signal) => api.disableProfile(profile.id, {
            expected_version: profile.version,
            idempotency_key: createTtsCloudIdempotencyKey("mutate"),
          }, signal),
        );
      } else {
        runCollectionAction(
          "正在删除语音渠道…",
          "语音渠道已删除。",
          "删除语音渠道失败。",
          (signal) => api.deleteProfile(profile.id, {
            expected_version: profile.version,
            idempotency_key: createTtsCloudIdempotencyKey("mutate"),
          }, signal),
        );
      }
    };

    const rootClassName = ["anw-tts-cloud-config", props.className ?? ""].filter(Boolean).join(" ");

    return h("main", {
      className: rootClassName,
      "aria-labelledby": "anw-tts-cloud-config-heading",
      "aria-busy": operation.busy,
    },
    h("header", { className: "anw-tts-cloud-config__header" },
      props.onBack
        ? h(antd.Button, { htmlType: "button", onClick: props.onBack }, "返回创作中心")
        : null,
      h("div", null,
        h("p", null, "全局语音设置"),
        h("h2", { id: "anw-tts-cloud-config-heading", tabIndex: -1 }, "语音模型接入"),
        h("p", null, "集中管理云端 Qwen TTS 渠道；每次只有一个渠道可以用于新的朗读任务。"),
      ),
      h(antd.Button, {
        type: "primary",
        htmlType: "button",
        disabled: operation.busy || Boolean(editor),
        onClick: beginCreate,
      }, "新增渠道"),
    ),
    props.localRuntimeStatus
      ? h(antd.Card, { title: "本地 Qwen3-TTS" },
        h(antd.Tag, {
          color: props.localRuntimeStatus.state === "ready"
            ? "green"
            : props.localRuntimeStatus.state === "loading" ? "default" : "orange",
        }, props.localRuntimeStatus.label),
        h("p", null, props.localRuntimeStatus.detail
          ?? "本地模型无需在此页填写域名或 API Key，作品仍可单独选择本地朗读。"),
      )
      : null,
    h(antd.Alert, {
      type: "warning",
      showIcon: true,
      message: "第三方渠道会接收待合成文本和所选参考音频",
      description: "保存配置不会联网测试或产生费用。模型测试使用服务端固定短句，只有确认可能计费后才会调用渠道。",
    }),
    operation.message
      ? h("div", {
        role: operation.kind === "error" ? "alert" : "status",
        "aria-live": "polite",
        tabIndex: operation.kind === "error" ? -1 : undefined,
        ref: operation.kind === "error" ? alertRef : undefined,
      }, operation.message)
      : null,
    editor
      ? h(antd.Card, {
        title: editor.mode === "create" ? "新增语音渠道" : `编辑：${editingProfile?.name ?? "语音渠道"}`,
      },
      h("div", { className: "anw-tts-cloud-config__form" },
        h("label", null,
          h("span", null, "渠道名称"),
          h(antd.Input, {
            value: form.name,
            disabled: operation.busy,
            onChange: (event: InputChangeEvent) => setForm((current) => ({ ...current, name: event.target.value })),
          }),
        ),
        h("div", null, h("strong", null, "接口协议"), h("p", null, "Qwen-Audio 原生 HTTP v1（首期只读）")),
        h("label", null,
          h("span", null, "Base URL"),
          h(antd.Input, {
            value: form.baseUrl,
            disabled: operation.busy,
            autoComplete: "url",
            placeholder: "https://会员渠道域名/可选路径前缀",
            onChange: (event: InputChangeEvent) => setForm((current) => ({ ...current, baseUrl: event.target.value })),
            onBlur: () => setForm((current) => ({
              ...current,
              baseUrl: normalizeHttpsBaseUrl(current.baseUrl),
            })),
          }),
        ),
        h("label", null,
          h("span", null, "质量模型 ID"),
          h(antd.Input, {
            value: form.qualityModelId,
            disabled: operation.busy,
            placeholder: "例如 qwen-audio-3.0-tts-plus（以渠道文档为准）",
            onChange: (event: InputChangeEvent) => setForm((current) => ({ ...current, qualityModelId: event.target.value })),
          }),
        ),
        h("label", null,
          h("span", null, "速度模型 ID（可选）"),
          h(antd.Input, {
            value: form.speedModelId,
            disabled: operation.busy,
            placeholder: "例如 qwen-audio-3.0-tts-flash（可留空）",
            onChange: (event: InputChangeEvent) => setForm((current) => ({ ...current, speedModelId: event.target.value })),
          }),
        ),
        h("label", null,
          h("span", null, editingProfile?.credential_configured ? "替换 API Key（可选）" : "API Key（可选）"),
          h(antd.Input, {
            type: "password",
            defaultValue: "",
            ref: credentialInputRef,
            disabled: operation.busy,
            autoComplete: "new-password",
            spellCheck: false,
            placeholder: editingProfile?.credential_configured ? "留空则保持现有 Key" : "只写入，不会回显",
            onChange: (event: InputChangeEvent) => {
              const length = event.target.value.trim().length;
              setKeyDraftState(length === 0 ? "empty" : length >= 16 ? "valid" : "invalid");
            },
          }),
          h("small", null,
            keyDraftState === "valid"
              ? "新 Key 将随保存请求一次性提交。"
              : keyDraftState === "invalid"
                ? h("span", { role: "alert" }, "API Key 至少需要 16 个字符。")
                : editingProfile?.api_key_masked ?? "尚未填写 Key，可先保存草稿。",
          ),
        ),
      ),
      h("div", { className: "anw-tts-cloud-config__actions" },
        h(antd.Button, { htmlType: "button", disabled: operation.busy, onClick: closeEditor }, "取消"),
        h(antd.Button, {
          type: "primary",
          htmlType: "button",
          disabled: operation.busy || !formReady || keyDraftState === "invalid",
          loading: operation.busy,
          onClick: saveProfile,
        }, "保存配置（不测试）"),
      ))
      : null,
    h("section", { "aria-labelledby": "anw-tts-cloud-list-heading" },
      h("h3", { id: "anw-tts-cloud-list-heading" }, "云端渠道"),
      resource.items.length === 0
        ? h(antd.Empty, { description: "尚未配置云端语音渠道" })
        : resource.items.map((profile) => {
          const canActivate = profile.credential_configured
            && profile.quality_test_state === "passed"
            && (!profile.speed_model_id || profile.speed_test_state === "passed")
            && profile.lifecycle_state !== "active";
          return h(antd.Card, {
            key: profile.id,
            title: profile.name,
            extra: h(antd.Tag, { color: lifecycleColor(profile.lifecycle_state) }, LIFECYCLE_LABELS[profile.lifecycle_state]),
          },
          h("dl", null,
            h("div", null, h("dt", null, "Base URL"), h("dd", null, profile.base_url)),
            h("div", null, h("dt", null, "凭据"), h("dd", null,
              profile.credential_configured ? profile.api_key_masked ?? "已配置" : "未配置",
            )),
            h("div", null, h("dt", null, "质量模型"), h("dd", null,
              profile.quality_model_id,
              " ", h(antd.Tag, { color: testColor(profile.quality_test_state) }, TEST_LABELS[profile.quality_test_state]),
            )),
            h("div", null, h("dt", null, "速度模型"), h("dd", null,
              profile.speed_model_id ?? "未配置",
              profile.speed_model_id
                ? [" ", h(antd.Tag, { key: "speed-state", color: testColor(profile.speed_test_state) }, TEST_LABELS[profile.speed_test_state])]
                : null,
            )),
            h("div", null, h("dt", null, "最近测试"), h("dd", null, formatDateTime(profile.last_tested_at))),
          ),
          profile.failure_code
            ? h(antd.Alert, { type: "error", showIcon: true, message: "最近测试不可用", description: profile.failure_code })
            : null,
          h("div", { className: "anw-tts-cloud-config__actions" },
            h(antd.Button, { htmlType: "button", disabled: operation.busy, onClick: () => beginEdit(profile) }, "编辑"),
            h(antd.Button, {
              htmlType: "button",
              disabled: operation.busy || !profile.credential_configured,
              onClick: () => beginConfirmation({ kind: "test", profileId: profile.id, slot: "quality" }),
            }, "测试质量模型"),
            profile.speed_model_id
              ? h(antd.Button, {
                htmlType: "button",
                disabled: operation.busy || !profile.credential_configured,
                onClick: () => beginConfirmation({ kind: "test", profileId: profile.id, slot: "speed" }),
              }, "测试速度模型")
              : null,
            profile.lifecycle_state === "active"
              ? h(antd.Button, {
                htmlType: "button",
                disabled: operation.busy,
                onClick: () => beginConfirmation({ kind: "disable", profileId: profile.id }),
              }, "停用")
              : h(antd.Button, {
                type: "primary",
                htmlType: "button",
                disabled: operation.busy || !canActivate,
                title: canActivate ? undefined : "请先验证所有已配置的模型",
                onClick: () => beginConfirmation({ kind: "activate", profileId: profile.id }),
              }, "启用"),
            profile.lifecycle_state !== "active"
              ? h(antd.Button, {
                htmlType: "button",
                danger: true,
                disabled: operation.busy,
                onClick: () => beginConfirmation({ kind: "delete", profileId: profile.id }),
              }, "删除")
              : null,
          ));
        }),
    ),
    lastTest
      ? h(antd.Card, { title: "最近模型测试" },
        h("p", null, `${lastTest.slot === "quality" ? "质量" : "速度"}模型：${lastTest.status === "passed" ? "已通过" : "未通过"}`),
        h("p", null, `实际模型：${lastTest.actualModelId ?? "未返回"}`),
        lastTest.sampleRateHz ? h("p", null, `采样率：${lastTest.sampleRateHz} Hz`) : null,
        lastTest.failureCode ? h("p", null, `错误码：${lastTest.failureCode}`) : null,
        lastTest.audioUrl
          ? h("audio", { controls: true, preload: "metadata", src: lastTest.audioUrl, "aria-label": "固定短句测试音频" })
          : null,
      )
      : null,
    confirmation
      ? h("section", {
        role: "alertdialog",
        "aria-modal": true,
        "aria-labelledby": "anw-tts-cloud-confirm-heading",
        "aria-describedby": "anw-tts-cloud-confirm-description",
        tabIndex: -1,
        ref: dialogRef,
      },
      h("h3", { id: "anw-tts-cloud-confirm-heading" },
        confirmation.kind === "test"
          ? `确认测试${confirmation.slot === "quality" ? "质量" : "速度"}模型`
          : confirmation.kind === "activate"
            ? "确认启用渠道"
            : confirmation.kind === "disable"
              ? "确认停用渠道"
              : "确认删除渠道",
      ),
      h("p", { id: "anw-tts-cloud-confirm-description" },
        confirmation.kind === "test"
          ? "本次会使用服务端固定、非小说短句调用一次云端 TTS，可能产生渠道费用；不会自动启用渠道。"
          : confirmation.kind === "activate"
            ? "启用后仅影响之后新建的云端朗读任务，历史 Edition 不会改变。"
            : confirmation.kind === "disable"
              ? "停用后不会自动切换其他云端渠道，本地朗读和历史音频不受影响。"
              : "删除操作仅适用于非使用中且没有在途任务引用的配置。",
      ),
      confirmation.kind === "test"
        ? h(antd.Checkbox, {
          checked: billingAcknowledged,
          onChange: (event: CheckedChangeEvent) => setBillingAcknowledged(event.target.checked),
        }, "我确认本次测试可能产生一次云端调用费用")
        : null,
      h("div", { className: "anw-tts-cloud-config__actions" },
        h(antd.Button, { htmlType: "button", onClick: () => setConfirmation(null) }, "取消"),
        h(antd.Button, {
          type: confirmation.kind === "delete" ? "default" : "primary",
          htmlType: "button",
          danger: confirmation.kind === "delete",
          disabled: operation.busy || (confirmation.kind === "test" && !billingAcknowledged),
          onClick: confirmAction,
        }, confirmation.kind === "test" ? "确认计费并测试" : "确认操作"),
      ))
      : null,
    );
  };
}
