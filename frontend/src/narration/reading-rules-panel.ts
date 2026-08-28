import type { QwenPawReactRuntime } from "../assistant-pane";
import {
  NarrationApiError,
  createNarrationCloudConsent,
  putNarrationSettings,
  revokeNarrationCloudConsent,
} from "./api";
import type {
  AnalysisMode,
  CapabilityKey,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationCloudConsent,
  NarrationErrorCode,
  NarrationSettingsResource,
  ScriptReviewPolicy,
  UpdateNarrationSettingsRequest,
} from "./contracts";


export const NARRATION_CLOUD_CONSENT_NOTICE_VERSION = "narration-cloud-consent/1";
export const NARRATION_CLOUD_DATA_SCOPE = "uncertain_segments_with_minimal_context" as const;


export type ReadingRulesReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useState" | "useEffect" | "useRef"
>;


export interface ReadingRulesPanelApi {
  putSettings(
    novelId: string,
    payload: UpdateNarrationSettingsRequest,
    signal?: AbortSignal,
  ): Promise<NarrationSettingsResource>;
  createCloudConsent(
    novelId: string,
    payload: {
      readonly notice_version: string;
      readonly data_scope: typeof NARRATION_CLOUD_DATA_SCOPE;
      readonly provider_id: null;
      readonly model_id: null;
      readonly confirmed: true;
    },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<NarrationCloudConsent>;
  revokeCloudConsent(
    novelId: string,
    payload: { readonly consent_id: string; readonly expected_version: number },
    signal?: AbortSignal,
  ): Promise<NarrationCloudConsent>;
}


export interface ReadingRulesPanelProps {
  readonly novelId: string;
  readonly settings: NarrationSettingsResource;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly onSettingsSaved?: (settings: NarrationSettingsResource) => void;
  readonly onConsentChanged?: (consent: NarrationCloudConsent) => void;
  readonly onRefresh?: () => void;
  readonly createIdempotencyKey?: () => string;
}


export interface ReadingRulesDraft {
  readonly scriptReviewPolicy: ScriptReviewPolicy;
  readonly analysisMode: AnalysisMode;
}


export interface ReadingRulesPanelModel {
  readonly canRead: boolean;
  readonly canEditSettings: boolean;
  readonly canSave: boolean;
  readonly canGrantConsent: boolean;
  readonly canRevokeConsent: boolean;
  readonly cloudVisible: boolean;
  readonly cloudActionable: boolean;
  readonly productReason: string | null;
  readonly cloudReason: string | null;
  readonly consentState: NarrationCloudConsent["state"];
  readonly cloudConsentUsable: boolean;
  readonly needsConsentForDraft: boolean;
  readonly savedCloudModeBlocked: boolean;
}


export interface ReadingRulesFailure {
  readonly code: NarrationErrorCode | "NETWORK_ERROR" | "CANCELLED" | "RESPONSE_SCOPE_MISMATCH";
  readonly message: string;
  readonly retryable: boolean;
  readonly refreshRequired: boolean;
}


interface ReadingRulesOperationState {
  readonly busy: boolean;
  readonly message: string | null;
  readonly failure: ReadingRulesFailure | null;
}


const IDLE_OPERATION: ReadingRulesOperationState = {
  busy: false,
  message: null,
  failure: null,
};


const DEFAULT_API: ReadingRulesPanelApi = {
  putSettings: putNarrationSettings,
  createCloudConsent: createNarrationCloudConsent,
  revokeCloudConsent: revokeNarrationCloudConsent,
};


function capability(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | null {
  return capabilities.items.find((item) => item.key === key) ?? null;
}


function actionable(item: FeatureCapability | null): boolean {
  return item?.state === "enabled" && item.visible && item.actionable;
}


export function readingRulesDraftFromSettings(
  settings: NarrationSettingsResource,
): ReadingRulesDraft {
  return {
    scriptReviewPolicy: settings.values.script_review_policy,
    analysisMode: settings.values.analysis_mode,
  };
}


export function isNarrationCloudConsentUsable(
  consent: NarrationCloudConsent,
): boolean {
  return consent.state === "active"
    && consent.consent_id !== null
    && consent.version >= 1
    && consent.purpose === "narration_speaker_analysis"
    && consent.data_scope === NARRATION_CLOUD_DATA_SCOPE
    && consent.notice_version === NARRATION_CLOUD_CONSENT_NOTICE_VERSION
    && consent.confirmed_at !== null
    && consent.revoked_at === null;
}


function safeDraftFromInputs(
  settings: NarrationSettingsResource,
  consent: NarrationCloudConsent,
): ReadingRulesDraft {
  const draft = readingRulesDraftFromSettings(settings);
  return draft.analysisMode === "cloud_assisted" && !isNarrationCloudConsentUsable(consent)
    ? { ...draft, analysisMode: "local_rules_only" }
    : draft;
}


export function buildReadingRulesPanelModel(input: {
  readonly draft: ReadingRulesDraft;
  readonly saved: ReadingRulesDraft;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly consent: NarrationCloudConsent;
  readonly busy: boolean;
  readonly consentConfirmed: boolean;
}): ReadingRulesPanelModel {
  const product = capability(input.capabilities, "narration_product");
  const settings = capability(input.capabilities, "reading_settings");
  const cloud = capability(input.capabilities, "cloud_assisted_analysis");
  const baseActionable = input.authorization.can_read
    && input.authorization.can_configure
    && actionable(product)
    && actionable(settings);
  const cloudActionable = actionable(cloud);
  const consentActive = input.consent.state === "active";
  const consentUsable = isNarrationCloudConsentUsable(input.consent);
  const changed = input.draft.scriptReviewPolicy !== input.saved.scriptReviewPolicy
    || input.draft.analysisMode !== input.saved.analysisMode;
  const draftAllowed = input.draft.analysisMode !== "cloud_assisted"
    || (cloudActionable && consentUsable);
  return {
    canRead: input.authorization.can_read,
    canEditSettings: baseActionable && !input.busy,
    canSave: baseActionable && changed && draftAllowed && !input.busy,
    canGrantConsent: baseActionable
      && cloudActionable
      && !consentActive
      && input.consentConfirmed
      && !input.busy,
    // Withdrawal is intentionally independent of the cloud product gate.
    canRevokeConsent: input.authorization.can_read
      && input.authorization.can_configure
      && consentActive
      && !input.busy,
    cloudVisible: cloud?.visible === true || consentActive || input.draft.analysisMode === "cloud_assisted",
    cloudActionable,
    productReason: !actionable(product)
      ? product?.reason_code ?? "NARRATION_PRODUCT_STATUS_MISSING"
      : !actionable(settings)
        ? settings?.reason_code ?? "READING_SETTINGS_STATUS_MISSING"
        : null,
    cloudReason: cloudActionable
      ? null
      : cloud?.reason_code ?? "CLOUD_ASSISTED_STATUS_MISSING",
    consentState: input.consent.state,
    cloudConsentUsable: consentUsable,
    needsConsentForDraft: input.draft.analysisMode === "cloud_assisted" && !consentUsable,
    savedCloudModeBlocked: input.saved.analysisMode === "cloud_assisted" && !consentUsable,
  };
}


export function buildReadingRulesSettingsRequest(
  settings: NarrationSettingsResource,
  draft: ReadingRulesDraft,
): UpdateNarrationSettingsRequest {
  return {
    expected_version: settings.version,
    values: {
      ...settings.values,
      script_review_policy: draft.scriptReviewPolicy,
      analysis_mode: draft.analysisMode,
    },
  };
}


function abortLike(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


export function classifyReadingRulesFailure(reason: unknown): ReadingRulesFailure {
  if (abortLike(reason)) {
    return {
      code: "CANCELLED",
      message: "操作已取消。",
      retryable: false,
      refreshRequired: false,
    };
  }
  if (!(reason instanceof NarrationApiError)) {
    return {
      code: "NETWORK_ERROR",
      message: "朗读规则服务连接失败，请稍后重试。",
      retryable: true,
      refreshRequired: false,
    };
  }
  const code = reason.detail.code;
  if (code === "VERSION_CONFLICT") {
    return {
      code,
      message: "设置已被其他操作更新，请刷新后重新确认。",
      retryable: false,
      refreshRequired: true,
    };
  }
  if (["CLOUD_CONSENT_REQUIRED", "CLOUD_CONSENT_REVOKED"].includes(code)) {
    return {
      code,
      message: "云端最小上下文授权无效；当前不会外发正文。",
      retryable: false,
      refreshRequired: true,
    };
  }
  if (["CAPABILITY_DISABLED", "MODEL_UNAVAILABLE"].includes(code)) {
    return {
      code,
      message: "该朗读能力尚未通过当前产品门禁。",
      retryable: false,
      refreshRequired: false,
    };
  }
  if (["SCOPE_VIOLATION", "RESOURCE_NOT_FOUND"].includes(code)) {
    return {
      code,
      message: "找不到当前作品的朗读规则，或访问范围已经变化。",
      retryable: false,
      refreshRequired: true,
    };
  }
  return {
    code,
    message: "朗读规则操作未完成，正式设置没有被静默覆盖。",
    retryable: reason.detail.retryable,
    refreshRequired: false,
  };
}


function scopeMismatchFailure(): ReadingRulesFailure {
  return {
    code: "RESPONSE_SCOPE_MISMATCH",
    message: "服务返回了其他作品的设置，已拒绝应用。",
    retryable: false,
    refreshRequired: true,
  };
}


function defaultIdempotencyKey(): string {
  const value = globalThis.crypto?.randomUUID?.();
  if (!value) throw new Error("secure random UUID is unavailable");
  return `cloud:${value}`;
}


interface ChangeEvent {
  readonly target: { readonly value: string; readonly checked: boolean };
}


export function createReadingRulesPanel(
  React: ReadingRulesReactRuntime,
  api: ReadingRulesPanelApi = DEFAULT_API,
): (props: ReadingRulesPanelProps) => unknown {
  const h = React.createElement;
  return function ReadingRulesPanel(props: ReadingRulesPanelProps): unknown {
    const savedDraft = readingRulesDraftFromSettings(props.settings);
    const [draft, setDraft] = React.useState<ReadingRulesDraft>(() => safeDraftFromInputs(
      props.settings,
      props.authorization.cloud_consent,
    ));
    const [consent, setConsent] = React.useState<NarrationCloudConsent>(
      props.authorization.cloud_consent,
    );
    const [consentConfirmed, setConsentConfirmed] = React.useState(false);
    const [operation, setOperation] = React.useState<ReadingRulesOperationState>(IDLE_OPERATION);
    const controllers = React.useRef<Set<AbortController>>(new Set());
    const novelRef = React.useRef(props.novelId);
    const consentKey = React.useRef<{ novelId: string; key: string } | null>(null);

    React.useEffect(() => {
      novelRef.current = props.novelId;
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
      consentKey.current = null;
      setDraft(safeDraftFromInputs(props.settings, props.authorization.cloud_consent));
      setConsent(props.authorization.cloud_consent);
      setConsentConfirmed(false);
      setOperation(IDLE_OPERATION);
      return () => {
        for (const controller of controllers.current) controller.abort();
        controllers.current.clear();
      };
    }, [
      props.novelId,
      props.settings.novel_id,
      props.settings.version,
      props.settings.values.script_review_policy,
      props.settings.values.analysis_mode,
      props.authorization.cloud_consent.consent_id,
      props.authorization.cloud_consent.version,
      props.authorization.cloud_consent.state,
      props.authorization.cloud_consent.notice_version,
    ]);

    const model = buildReadingRulesPanelModel({
      draft,
      saved: savedDraft,
      capabilities: props.capabilities,
      authorization: props.authorization,
      consent,
      busy: operation.busy,
      consentConfirmed,
    });

    const begin = (): AbortController => {
      const controller = new AbortController();
      controllers.current.add(controller);
      setOperation({ busy: true, message: null, failure: null });
      return controller;
    };
    const finish = (controller: AbortController): boolean => {
      controllers.current.delete(controller);
      return !controller.signal.aborted && novelRef.current === props.novelId;
    };
    const fail = (controller: AbortController, reason: unknown): void => {
      if (!finish(controller)) return;
      const failure = classifyReadingRulesFailure(reason);
      if (failure.code === "CANCELLED") return;
      setOperation({ busy: false, message: null, failure });
    };

    const save = (): void => {
      if (!model.canSave) return;
      const controller = begin();
      const request = buildReadingRulesSettingsRequest(props.settings, draft);
      void api.putSettings(props.novelId, request, controller.signal).then((resource) => {
        if (!finish(controller)) return;
        if (
          resource.novel_id !== props.novelId
          || resource.version <= props.settings.version
          || resource.values.script_review_policy !== draft.scriptReviewPolicy
          || resource.values.analysis_mode !== draft.analysisMode
        ) {
          setOperation({ busy: false, message: null, failure: scopeMismatchFailure() });
          return;
        }
        setDraft(readingRulesDraftFromSettings(resource));
        setOperation({ busy: false, message: "朗读识别与复核规则已保存。", failure: null });
        props.onSettingsSaved?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    const grant = (): void => {
      if (!model.canGrantConsent) return;
      let key = consentKey.current;
      if (key === null || key.novelId !== props.novelId) {
        try {
          key = {
            novelId: props.novelId,
            key: (props.createIdempotencyKey ?? defaultIdempotencyKey)(),
          };
        } catch (reason) {
          setOperation({
            busy: false,
            message: null,
            failure: classifyReadingRulesFailure(reason),
          });
          return;
        }
        consentKey.current = key;
      }
      const controller = begin();
      void api.createCloudConsent(
        props.novelId,
        {
          notice_version: NARRATION_CLOUD_CONSENT_NOTICE_VERSION,
          data_scope: NARRATION_CLOUD_DATA_SCOPE,
          provider_id: null,
          model_id: null,
          confirmed: true,
        },
        key.key,
        controller.signal,
      ).then((resource) => {
        if (!finish(controller)) return;
        if (
          resource.state !== "active"
          || resource.consent_id === null
          || resource.notice_version !== NARRATION_CLOUD_CONSENT_NOTICE_VERSION
        ) {
          setOperation({ busy: false, message: null, failure: scopeMismatchFailure() });
          return;
        }
        consentKey.current = null;
        setConsent(resource);
        setConsentConfirmed(false);
        setOperation({ busy: false, message: "作品级云端最小上下文授权已记录。", failure: null });
        props.onConsentChanged?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    const revoke = (): void => {
      if (!model.canRevokeConsent || consent.consent_id === null) return;
      const controller = begin();
      const expectedId = consent.consent_id;
      void api.revokeCloudConsent(
        props.novelId,
        { consent_id: expectedId, expected_version: consent.version },
        controller.signal,
      ).then((resource) => {
        if (!finish(controller)) return;
        if (
          resource.consent_id !== expectedId
          || resource.state !== "revoked"
          || resource.version <= consent.version
        ) {
          setOperation({ busy: false, message: null, failure: scopeMismatchFailure() });
          return;
        }
        setConsent(resource);
        if (draft.analysisMode === "cloud_assisted") {
          setDraft((current) => ({ ...current, analysisMode: "local_rules_only" }));
        }
        setOperation({
          busy: false,
          message: "授权已撤销；后续分析不会外发。请保存本地规则模式。",
          failure: null,
        });
        props.onConsentChanged?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    if (props.settings.novel_id !== props.novelId) {
      return h(
        "section",
        { className: "anw-reading-rules-panel", "aria-labelledby": "anw-reading-rules-title" },
        h("h2", { id: "anw-reading-rules-title" }, "识别、选角与复核规则"),
        h("p", { role: "alert" }, "朗读设置与当前作品不一致，已拒绝显示。"),
      );
    }

    if (!model.canRead) {
      return h(
        "section",
        { className: "anw-reading-rules-panel", "aria-labelledby": "anw-reading-rules-title" },
        h("h2", { id: "anw-reading-rules-title" }, "识别、选角与复核规则"),
        h("p", { role: "alert" }, "当前身份无权查看本作品的朗读规则。"),
      );
    }

    const operationNode = operation.failure !== null
      ? h(
        "div",
        { className: "anw-reading-rules-panel__error", role: "alert" },
        h("p", null, operation.failure.message),
        operation.failure.refreshRequired
          ? h("button", { type: "button", onClick: props.onRefresh }, "刷新最新配置")
          : null,
      )
      : operation.message === null
        ? null
        : h("p", { className: "anw-reading-rules-panel__status", role: "status" }, operation.message);

    return h(
      "section",
      {
        className: "anw-reading-rules-panel",
        "aria-labelledby": "anw-reading-rules-title",
        "aria-busy": operation.busy || undefined,
      },
      h("header", null,
        h("div", null,
          h("p", { className: "anw-reading-rules-panel__eyebrow" }, "作品级朗读设置"),
          h("h2", { id: "anw-reading-rules-title" }, "识别、选角与复核规则"),
        ),
        h("span", null, `设置版本 ${props.settings.version}`),
      ),
      model.productReason === null
        ? null
        : h("p", { className: "anw-reading-rules-panel__notice", role: "note" },
          `当前只读：${model.productReason}`,
        ),
      h(
        "fieldset",
        { disabled: !model.canEditSettings },
        h("legend", null, "脚本复核策略"),
        h("label", null,
          h("input", {
            type: "radio",
            name: "narration-review-policy",
            value: "blockers_only",
            checked: draft.scriptReviewPolicy === "blockers_only",
            onChange: (event: ChangeEvent) => setDraft((current) => ({
              ...current,
              scriptReviewPolicy: event.target.value as ScriptReviewPolicy,
            })),
          }),
          h("span", null, "仅阻断项必须复核"),
          h("small", null, "没有 blocker 时可自动冻结脚本；warning 仍保留证据。"),
        ),
        h("label", null,
          h("input", {
            type: "radio",
            name: "narration-review-policy",
            value: "always_review",
            checked: draft.scriptReviewPolicy === "always_review",
            onChange: (event: ChangeEvent) => setDraft((current) => ({
              ...current,
              scriptReviewPolicy: event.target.value as ScriptReviewPolicy,
            })),
          }),
          h("span", null, "每次都由作者复核"),
          h("small", null, "分析完成后暂停，确认人物、匿名说话人和选角再生成。"),
        ),
      ),
      h(
        "fieldset",
        { disabled: !model.canEditSettings },
        h("legend", null, "正文分析隐私模式"),
        h("label", null,
          h("input", {
            type: "radio",
            name: "narration-analysis-mode",
            value: "local_rules_only",
            checked: draft.analysisMode === "local_rules_only",
            onChange: () => setDraft((current) => ({
              ...current,
              analysisMode: "local_rules_only",
            })),
          }),
          h("span", null, "仅本地规则（默认）"),
          h("small", null, "正文不发送给云端模型；不确定片段按复核策略处理。"),
        ),
        model.cloudVisible
          ? h("label", null,
            h("input", {
              type: "radio",
              name: "narration-analysis-mode",
              value: "cloud_assisted",
              checked: draft.analysisMode === "cloud_assisted",
              disabled: !model.cloudActionable || !model.cloudConsentUsable,
              "aria-describedby": "anw-reading-cloud-mode-help",
              onChange: () => setDraft((current) => ({
                ...current,
                analysisMode: "cloud_assisted",
              })),
            }),
            h("span", null, "云端辅助识别"),
            h("small", { id: "anw-reading-cloud-mode-help" },
              model.cloudActionable
                ? "只发送不确定句段及最小上下文；不发送参考录音或整章。"
                : `当前不可用：${model.cloudReason}`,
            ),
          )
          : null,
      ),
      model.cloudVisible || consent.state === "active"
        ? h(
          "section",
          { className: "anw-reading-rules-panel__consent", "aria-labelledby": "anw-reading-consent-title" },
          h("h3", { id: "anw-reading-consent-title" }, "作品级云端授权"),
          h("p", null,
            "用途仅限说话人不确定性分析；数据范围固定为不确定句段与必要的最小上下文。",
          ),
          consent.state === "active"
            ? h("div", null,
              h("p", { role: "status" }, model.cloudConsentUsable
                ? `授权有效 · ${consent.notice_version}`
                : `授权记录需重新确认 · ${consent.notice_version ?? "未知声明版本"}`,
              ),
              h("button", {
                type: "button",
                disabled: !model.canRevokeConsent,
                onClick: revoke,
              }, "撤销云端授权"),
            )
            : h("div", null,
              h("label", null,
                h("input", {
                  type: "checkbox",
                  checked: consentConfirmed,
                  disabled: !model.canEditSettings || !model.cloudActionable,
                  onChange: (event: ChangeEvent) => setConsentConfirmed(event.target.checked),
                }),
                `我已阅读并同意 ${NARRATION_CLOUD_CONSENT_NOTICE_VERSION}，仅发送上述最小数据范围。`,
              ),
              h("button", {
                type: "button",
                disabled: !model.canGrantConsent,
                onClick: grant,
              }, "确认作品级授权"),
            ),
        )
        : null,
      model.needsConsentForDraft
        ? h("p", { className: "anw-reading-rules-panel__notice", role: "note" },
          "云端授权无效，当前草稿不能保存为云端模式。",
        )
        : null,
      model.savedCloudModeBlocked
        ? h("p", { className: "anw-reading-rules-panel__notice", role: "note" },
          "已保存的云端模式因授权无效而阻断；当前已准备切回本地模式，保存后生效。",
        )
        : null,
      operationNode,
      h("footer", null,
        h("p", null, "规则变更只影响后续脚本/Edition；历史 Edition 不会被改写。"),
        h("button", {
          type: "button",
          className: "anw-reading-rules-panel__save",
          disabled: !model.canSave,
          onClick: save,
        }, operation.busy ? "处理中…" : "保存识别与复核规则"),
      ),
    );
  };
}
