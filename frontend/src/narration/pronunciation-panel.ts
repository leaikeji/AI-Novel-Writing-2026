import {
  NarrationApiError,
  getPronunciationProfile,
  putPronunciationProfile,
} from "./api";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationTimingSettings,
  PronunciationAction,
  PronunciationEntryResource,
  PronunciationProfileResource,
  PutPronunciationProfileRequest,
} from "./contracts";


const LANGUAGE_PATTERN = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$/;
const MUTATION_CAPABILITIES = ["narration_product", "reading_settings"] as const;


export interface PronunciationPanelReactRuntime {
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


export interface PronunciationPanelApi {
  getPronunciationProfile(
    novelId: string,
    signal?: AbortSignal,
  ): Promise<PronunciationProfileResource>;
  putPronunciationProfile(
    novelId: string,
    payload: PutPronunciationProfileRequest,
    signal?: AbortSignal,
  ): Promise<PronunciationProfileResource>;
}


export interface PronunciationScopeOption {
  readonly kind: "volume" | "chapter";
  readonly id: string;
  readonly label: string;
}


export interface PronunciationPanelProps {
  readonly novelId: string;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  /** Immutable scope identities supplied by the reading-page owner. */
  readonly scopeOptions: readonly PronunciationScopeOption[];
  /** Actual base reading settings; pause values are not duplicated in this API. */
  readonly timing: NarrationTimingSettings;
  readonly className?: string;
  readonly onOpenReadingSettings?: () => void;
  readonly onSaved?: (profile: PronunciationProfileResource) => void;
  readonly onReturnFocus?: () => void;
}


export interface PronunciationDraftEntry {
  readonly clientKey: string;
  readonly sourceText: string;
  readonly action: PronunciationAction;
  readonly spokenText: string;
  readonly language: string;
  readonly scopeKind: "novel" | "volume" | "chapter";
  readonly scopeId: string;
  readonly priorityText: string;
}


export interface PronunciationDraftValidation {
  readonly valid: boolean;
  readonly errors: Readonly<Record<string, string>>;
}


type PronunciationPanelPhase =
  | "blocked"
  | "loading"
  | "ready"
  | "saving"
  | "load-error"
  | "save-error"
  | "conflict";


interface PronunciationPanelState {
  readonly scopeKey: string;
  readonly phase: PronunciationPanelPhase;
  readonly profile: PronunciationProfileResource | null;
  readonly drafts: readonly PronunciationDraftEntry[];
  readonly message: string;
  readonly conflictVersion: number | null;
}


interface ValueChangeEvent {
  readonly target: { readonly value: string };
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
}


class PronunciationPanelDataError extends Error {}


const defaultApi: PronunciationPanelApi = {
  getPronunciationProfile,
  putPronunciationProfile,
};


function capability(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | undefined {
  return capabilities.items.find((item) => item.key === key);
}


function isActionable(item: FeatureCapability | undefined): boolean {
  return item?.state === "enabled" && item.visible && item.actionable;
}


export function canConfigurePronunciations(
  capabilities: NarrationCapabilities,
  authorization: NarrationAuthorizationState,
): boolean {
  return authorization.can_read
    && authorization.can_configure
    && MUTATION_CAPABILITIES.every((key) => isActionable(capability(capabilities, key)));
}


function blockedMessage(props: PronunciationPanelProps): string {
  if (!props.authorization.can_read) return "当前身份无权查看发音与停顿设置。";
  if (!props.authorization.can_configure) return "当前身份只能查看，不能修改发音配置。";
  for (const key of MUTATION_CAPABILITIES) {
    const item = capability(props.capabilities, key);
    if (!isActionable(item)) {
      const reason = item?.reason_code ? `（${item.reason_code}）` : "";
      return `朗读设置能力尚未开放，发音配置保持只读${reason}。`;
    }
  }
  return "";
}


function sourceKey(value: string): string {
  return value.trim().normalize("NFKC").toLowerCase().replace(/\s+/g, " ");
}


function scopeKey(kind: string, id: string): string {
  return `${kind}:${id}`;
}


export function pronunciationDraftsFromProfile(
  profile: PronunciationProfileResource,
): readonly PronunciationDraftEntry[] {
  return profile.entries.map((item, index) => ({
    clientKey: item.entry_id ?? `loaded-${index}`,
    sourceText: item.source_text,
    action: item.action,
    spokenText: item.spoken_text ?? "",
    language: item.language,
    scopeKind: item.scope_kind,
    scopeId: item.scope_id,
    priorityText: String(item.priority),
  }));
}


export function validatePronunciationDrafts(
  drafts: readonly PronunciationDraftEntry[],
  novelId: string,
  scopeOptions: readonly PronunciationScopeOption[],
): PronunciationDraftValidation {
  const errors: Record<string, string> = {};
  const allowedScopes = new Set([
    scopeKey("novel", novelId),
    ...scopeOptions.map((item) => scopeKey(item.kind, item.id)),
  ]);
  const seen = new Set<string>();
  drafts.forEach((draft) => {
    const prefix = draft.clientKey;
    const source = draft.sourceText.trim();
    if (!source || source.length > 160 || /[\u0000-\u001f\u007f]/.test(source)) {
      errors[`${prefix}:source`] = "原文必填，最多 160 字且不能含控制字符。";
    }
    if (!LANGUAGE_PATTERN.test(draft.language.trim())) {
      errors[`${prefix}:language`] = "请输入语言标签，例如 zh-CN。";
    }
    if (draft.action === "replace") {
      const spoken = draft.spokenText.trim();
      if (!spoken || spoken.length > 240 || /[\u0000-\u001f\u007f]/.test(spoken)) {
        errors[`${prefix}:spoken`] = "替换规则必须填写 1–240 字的朗读文本。";
      }
    } else if (draft.spokenText !== "") {
      errors[`${prefix}:spoken`] = "不朗读规则不能携带替换文本。";
    }
    const priority = Number(draft.priorityText);
    if (!Number.isInteger(priority) || priority < -10_000 || priority > 10_000) {
      errors[`${prefix}:priority`] = "优先级必须是 -10000 到 10000 的整数。";
    }
    if (!allowedScopes.has(scopeKey(draft.scopeKind, draft.scopeId))) {
      errors[`${prefix}:scope`] = "作用范围已不存在或不属于当前作品。";
    }
    const duplicateKey = [
      draft.scopeKind,
      draft.scopeId,
      sourceKey(draft.sourceText),
      draft.priorityText,
    ].join("|");
    if (seen.has(duplicateKey)) {
      errors[`${prefix}:duplicate`] = "同一范围、原文和优先级不能重复。";
    }
    seen.add(duplicateKey);
  });
  return { valid: Object.keys(errors).length === 0, errors };
}


export function buildPronunciationProfileRequest(
  profile: PronunciationProfileResource,
  drafts: readonly PronunciationDraftEntry[],
  novelId: string,
  scopeOptions: readonly PronunciationScopeOption[],
): PutPronunciationProfileRequest | null {
  const validation = validatePronunciationDrafts(drafts, novelId, scopeOptions);
  if (!validation.valid || profile.novel_id !== novelId) return null;
  return {
    expected_version: profile.version,
    entries: drafts.map((draft): PronunciationEntryResource => ({
      entry_id: null,
      source_text: draft.sourceText.trim(),
      action: draft.action,
      spoken_text: draft.action === "replace" ? draft.spokenText.trim() : null,
      language: draft.language.trim(),
      scope_kind: draft.scopeKind,
      scope_id: draft.scopeId,
      priority: Number(draft.priorityText),
    })),
  };
}


function comparableEntries(entries: readonly PronunciationEntryResource[]): string {
  return JSON.stringify(entries.map((item) => ({
    source_text: item.source_text.trim(),
    action: item.action,
    spoken_text: item.action === "replace" ? item.spoken_text?.trim() ?? null : null,
    language: item.language.trim(),
    scope_kind: item.scope_kind,
    scope_id: item.scope_id,
    priority: item.priority,
  })).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right))));
}


export function pronunciationDraftsEqualProfile(
  profile: PronunciationProfileResource,
  drafts: readonly PronunciationDraftEntry[],
  novelId: string,
  scopeOptions: readonly PronunciationScopeOption[],
): boolean {
  const payload = buildPronunciationProfileRequest(profile, drafts, novelId, scopeOptions);
  return payload !== null
    && comparableEntries(payload.entries) === comparableEntries(profile.entries);
}


function initialState(props: PronunciationPanelProps): PronunciationPanelState {
  return {
    scopeKey: props.novelId,
    phase: props.authorization.can_read ? "loading" : "blocked",
    profile: null,
    drafts: [],
    message: props.authorization.can_read ? "正在加载发音配置…" : blockedMessage(props),
    conflictVersion: null,
  };
}


function assertProfileScope(novelId: string, profile: PronunciationProfileResource): void {
  if (profile.novel_id !== novelId) {
    throw new PronunciationPanelDataError("发音配置返回了其他作品的数据，已拒绝显示。");
  }
  const entryIds = profile.entries
    .map((item) => item.entry_id)
    .filter((item): item is string => item !== null);
  if (entryIds.length !== new Set(entryIds).size) {
    throw new PronunciationPanelDataError("发音配置包含重复条目身份，已拒绝显示。");
  }
}


function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}


function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof PronunciationPanelDataError) return reason.message;
  if (reason instanceof NarrationApiError) {
    const labels: Partial<Record<typeof reason.detail.code, string>> = {
      CAPABILITY_DISABLED: "朗读设置能力尚未开放。",
      SCOPE_VIOLATION: "发音作用范围不属于当前作品。",
      RESOURCE_NOT_FOUND: "作品或作用范围已不存在。",
      VALIDATION_FAILED: "发音配置未通过服务端校验。",
      STORAGE_UNAVAILABLE: "朗读设置存储暂不可用。",
      SETTINGS_BACKEND_NOT_INSTALLED: "朗读设置服务尚未接入。",
    };
    return labels[reason.detail.code] ?? `${fallback}（${reason.detail.code}）`;
  }
  return fallback;
}


function parseScope(value: string): { kind: PronunciationDraftEntry["scopeKind"]; id: string } | null {
  const separator = value.indexOf(":");
  if (separator < 1) return null;
  const kind = value.slice(0, separator);
  const id = value.slice(separator + 1);
  if ((kind !== "novel" && kind !== "volume" && kind !== "chapter") || !id) return null;
  return { kind, id };
}


export function createPronunciationPanel(
  React: PronunciationPanelReactRuntime,
  api: PronunciationPanelApi = defaultApi,
): (props: PronunciationPanelProps) => unknown {
  const h = React.createElement;

  return function PronunciationPanel(props: PronunciationPanelProps): unknown {
    const [state, setState] = React.useState(() => initialState(props));
    const stateRef = React.useRef(state);
    stateRef.current = state;
    const requestSequenceRef = React.useRef(0);
    const localKeyRef = React.useRef(0);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const saveAbortRef = React.useRef<AbortController | null>(null);
    const conflictRef = React.useRef<FocusableElement | null>(null);
    const saveButtonRef = React.useRef<FocusableElement | null>(null);
    const returnFocusRef = React.useRef(props.onReturnFocus);
    returnFocusRef.current = props.onReturnFocus;

    const commit = (
      update: PronunciationPanelState
        | ((current: PronunciationPanelState) => PronunciationPanelState),
    ) => {
      setState((current) => {
        const next = typeof update === "function" ? update(current) : update;
        stateRef.current = next;
        return next;
      });
    };

    const startLoad = (preserveDraft: boolean): AbortController | null => {
      if (!props.authorization.can_read) {
        commit(initialState(props));
        return null;
      }
      loadAbortRef.current?.abort();
      saveAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      const scopedNovelId = props.novelId;
      const preserved = preserveDraft && stateRef.current.scopeKey === scopedNovelId
        ? stateRef.current.drafts
        : null;
      commit((current) => ({
        ...current,
        scopeKey: scopedNovelId,
        phase: "loading",
        profile: current.scopeKey === scopedNovelId ? current.profile : null,
        drafts: preserved ?? (current.scopeKey === scopedNovelId ? current.drafts : []),
        message: preserveDraft
          ? "正在读取最新版本，已保留本地草稿…"
          : "正在加载发音配置…",
        conflictVersion: null,
      }));
      void api.getPronunciationProfile(scopedNovelId, controller.signal).then((profile) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertProfileScope(scopedNovelId, profile);
        commit({
          scopeKey: scopedNovelId,
          phase: "ready",
          profile,
          drafts: preserved ?? pronunciationDraftsFromProfile(profile),
          message: preserveDraft
            ? "已读取最新版本；本地草稿仍保留，请核对后重新保存。"
            : "发音配置已加载。",
          conflictVersion: null,
        });
        if (preserveDraft) queueMicrotask(() => saveButtonRef.current?.focus({ preventScroll: true }));
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        commit((current) => ({
          ...current,
          scopeKey: scopedNovelId,
          phase: "load-error",
          message: errorMessage(reason, preserveDraft ? "刷新发音配置失败。" : "加载发音配置失败。"),
          conflictVersion: null,
        }));
      });
      return controller;
    };

    React.useEffect(() => {
      const controller = startLoad(false);
      return () => controller?.abort();
    }, [props.novelId, props.authorization.can_read]);

    React.useEffect(() => () => {
      loadAbortRef.current?.abort();
      saveAbortRef.current?.abort();
      returnFocusRef.current?.();
    }, []);

    React.useEffect(() => {
      if (state.phase === "conflict") conflictRef.current?.focus({ preventScroll: true });
    }, [state.phase]);

    const scoped = props.authorization.can_read && state.scopeKey === props.novelId;
    const profile = scoped ? state.profile : null;
    const drafts = scoped ? state.drafts : [];
    const validation = validatePronunciationDrafts(drafts, props.novelId, props.scopeOptions);
    const configureAllowed = canConfigurePronunciations(props.capabilities, props.authorization);
    const editablePhase = state.phase === "ready" || state.phase === "save-error";
    const fieldsDisabled = !scoped || !configureAllowed || !editablePhase;
    const dirty = Boolean(profile && !pronunciationDraftsEqualProfile(
      profile,
      drafts,
      props.novelId,
      props.scopeOptions,
    ));
    const saveDisabled = fieldsDisabled || !dirty || !validation.valid;
    const prefix = `anw-pronunciation-${props.novelId}`;
    const statusId = `${prefix}-status`;
    const headingId = `${prefix}-heading`;

    const updateDraft = (index: number, patch: Partial<PronunciationDraftEntry>) => {
      if (fieldsDisabled) return;
      commit((current) => ({
        ...current,
        phase: "ready",
        drafts: current.drafts.map((item, itemIndex) => (
          itemIndex === index ? { ...item, ...patch } : item
        )),
        message: "发音草稿有未保存的更改。",
      }));
    };

    const addDraft = () => {
      if (fieldsDisabled) return;
      const key = `local-${++localKeyRef.current}`;
      commit((current) => ({
        ...current,
        phase: "ready",
        drafts: [...current.drafts, {
          clientKey: key,
          sourceText: "",
          action: "replace",
          spokenText: "",
          language: "zh-CN",
          scopeKind: "novel",
          scopeId: props.novelId,
          priorityText: "0",
        }],
        message: "已新增未保存的发音规则。",
      }));
    };

    const removeDraft = (index: number) => {
      if (fieldsDisabled) return;
      commit((current) => ({
        ...current,
        phase: "ready",
        drafts: current.drafts.filter((_item, itemIndex) => itemIndex !== index),
        message: "已从本地草稿移除发音规则；保存前服务端不会变化。",
      }));
    };

    const save = () => {
      const current = stateRef.current;
      const currentProfile = current.scopeKey === props.novelId ? current.profile : null;
      const payload = currentProfile
        ? buildPronunciationProfileRequest(
          currentProfile,
          current.drafts,
          props.novelId,
          props.scopeOptions,
        )
        : null;
      if (!payload
        || !currentProfile
        || !canConfigurePronunciations(props.capabilities, props.authorization)
        || (current.phase !== "ready" && current.phase !== "save-error")
        || pronunciationDraftsEqualProfile(
          currentProfile,
          current.drafts,
          props.novelId,
          props.scopeOptions,
        )) return;
      saveAbortRef.current?.abort();
      const controller = new AbortController();
      saveAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      const scopedNovelId = props.novelId;
      commit({ ...current, phase: "saving", message: "正在保存发音配置…", conflictVersion: null });
      void api.putPronunciationProfile(scopedNovelId, payload, controller.signal).then((saved) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertProfileScope(scopedNovelId, saved);
        commit({
          scopeKey: scopedNovelId,
          phase: "ready",
          profile: saved,
          drafts: pronunciationDraftsFromProfile(saved),
          message: "发音配置已保存。它只影响以后新建的脚本/版本，不改正文，也不改写历史 Edition。",
          conflictVersion: null,
        });
        props.onSaved?.(saved);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        if (reason instanceof NarrationApiError && reason.detail.code === "VERSION_CONFLICT") {
          commit((latest) => ({
            ...latest,
            phase: "conflict",
            message: "服务端发音版本已变化。本地草稿已保留，请读取最新版本后核对。",
            conflictVersion: reason.detail.current_version,
          }));
          return;
        }
        commit((latest) => ({
          ...latest,
          phase: "save-error",
          message: errorMessage(reason, "保存发音配置失败。本地草稿已保留。"),
          conflictVersion: null,
        }));
      });
    };

    const block = blockedMessage(props);
    const statusText = scoped ? state.message : "正在切换作品范围…";
    const rootClassName = [
      "anw-pronunciation-panel",
      `is-${scoped ? state.phase : "loading"}`,
      props.className ?? "",
    ].filter(Boolean).join(" ");
    const scopeOptions = [
      { key: scopeKey("novel", props.novelId), label: "整本作品" },
      ...props.scopeOptions.map((item) => ({
        key: scopeKey(item.kind, item.id),
        label: `${item.kind === "volume" ? "分卷" : "章节"} · ${item.label}`,
      })),
    ];

    return h(
      "section",
      {
        className: rootClassName,
        role: "region",
        "aria-labelledby": headingId,
        "aria-describedby": statusId,
        "aria-busy": !scoped || state.phase === "loading" || state.phase === "saving",
        "data-pronunciation-panel-phase": scoped ? state.phase : "loading",
      },
      h("header", { className: "anw-pronunciation-panel__header" },
        h("div", null,
          h("span", { className: "anw-pronunciation-panel__eyebrow" }, "朗读设置"),
          h("h3", { id: headingId, tabIndex: -1 }, "发音与停顿"),
        ),
        profile
          ? h("span", { className: "anw-pronunciation-panel__version" }, `发音版本 ${profile.version}`)
          : null,
      ),
      h("div", {
        id: statusId,
        className: "anw-pronunciation-panel__live",
        role: "status",
        "aria-live": "polite",
        "aria-atomic": "true",
      }, statusText),
      block ? h("p", { className: "anw-pronunciation-panel__notice" }, block) : null,
      state.phase === "load-error" && scoped
        ? h("div", { className: "anw-pronunciation-panel__error", role: "alert" },
          h("strong", null, state.message),
          props.authorization.can_read
            ? h("button", { type: "button", onClick: () => startLoad(false) }, "重新加载")
            : null,
        )
        : null,
      state.phase === "conflict" && scoped
        ? h("div", {
          className: "anw-pronunciation-panel__error",
          role: "alert",
          tabIndex: -1,
          ref: conflictRef,
        },
        h("strong", null, "检测到版本冲突"),
        h("span", null, state.conflictVersion === null
          ? state.message
          : `${state.message} 服务端当前版本为 ${state.conflictVersion}。`),
        h("button", { type: "button", onClick: () => startLoad(true) }, "读取最新版本并保留草稿"),
        )
        : null,
      profile && scoped
        ? h("div", { className: "anw-pronunciation-panel__body" },
          h("section", {
            className: "anw-pronunciation-panel__pauses",
            "aria-labelledby": `${prefix}-pause-heading`,
          },
          h("div", { className: "anw-pronunciation-panel__section-heading" },
            h("div", null,
              h("h4", { id: `${prefix}-pause-heading` }, "基础停顿"),
              h("p", null, "停顿属于作品基础朗读设置；本面板只显示真实值，不另存一份。"),
            ),
            props.onOpenReadingSettings
              ? h("button", {
                type: "button",
                disabled: !configureAllowed,
                onClick: props.onOpenReadingSettings,
              }, "前往基础朗读设置")
              : null,
          ),
          h("dl", null,
            h("div", null, h("dt", null, "句间"), h("dd", null, `${props.timing.sentence_gap_ms} ms`)),
            h("div", null, h("dt", null, "段间"), h("dd", null, `${props.timing.paragraph_gap_ms} ms`)),
            h("div", null, h("dt", null, "分隔"), h("dd", null, `${props.timing.section_gap_ms} ms`)),
          ),
          ),
          h("section", {
            className: "anw-pronunciation-panel__rules",
            "aria-labelledby": `${prefix}-rules-heading`,
          },
          h("div", { className: "anw-pronunciation-panel__section-heading" },
            h("div", null,
              h("h4", { id: `${prefix}-rules-heading` }, "发音与不朗读规则"),
              h("p", null, "替换只改变 spoken_text，不会修改正文。"),
            ),
            h("button", { type: "button", disabled: fieldsDisabled, onClick: addDraft }, "新增规则"),
          ),
          drafts.length === 0
            ? h("p", { className: "anw-pronunciation-panel__empty" }, "还没有发音规则。空表是有效的作品级配置。")
            : h("div", { className: "anw-pronunciation-panel__rule-list" },
              ...drafts.map((draft, index) => {
                const itemPrefix = `${prefix}-${draft.clientKey}`;
                const itemErrors = Object.entries(validation.errors)
                  .filter(([key]) => key.startsWith(`${draft.clientKey}:`))
                  .map(([, message]) => message);
                return h("fieldset", {
                  key: draft.clientKey,
                  className: "anw-pronunciation-panel__rule",
                  disabled: fieldsDisabled,
                },
                h("legend", null, `规则 ${index + 1}`),
                h("div", { className: "anw-pronunciation-panel__grid" },
                  h("label", null,
                    h("span", null, "原文"),
                    h("input", {
                      id: `${itemPrefix}-source`,
                      type: "text",
                      maxLength: 160,
                      value: draft.sourceText,
                      "aria-invalid": Boolean(validation.errors[`${draft.clientKey}:source`]),
                      onChange: (event: ValueChangeEvent) => updateDraft(index, { sourceText: event.target.value }),
                    }),
                  ),
                  h("label", null,
                    h("span", null, "动作"),
                    h("select", {
                      value: draft.action,
                      onChange: (event: ValueChangeEvent) => {
                        const action = event.target.value === "skip" ? "skip" : "replace";
                        updateDraft(index, {
                          action,
                          spokenText: action === "skip" ? "" : draft.spokenText,
                        });
                      },
                    },
                    h("option", { value: "replace" }, "替换朗读"),
                    h("option", { value: "skip" }, "不朗读"),
                    ),
                  ),
                  h("label", null,
                    h("span", null, "朗读文本"),
                    h("input", {
                      type: "text",
                      maxLength: 240,
                      value: draft.spokenText,
                      disabled: fieldsDisabled || draft.action === "skip",
                      "aria-invalid": Boolean(validation.errors[`${draft.clientKey}:spoken`]),
                      onChange: (event: ValueChangeEvent) => updateDraft(index, { spokenText: event.target.value }),
                    }),
                  ),
                  h("label", null,
                    h("span", null, "语言"),
                    h("input", {
                      type: "text",
                      maxLength: 40,
                      value: draft.language,
                      "aria-invalid": Boolean(validation.errors[`${draft.clientKey}:language`]),
                      onChange: (event: ValueChangeEvent) => updateDraft(index, { language: event.target.value }),
                    }),
                  ),
                  h("label", null,
                    h("span", null, "作用范围"),
                    h("select", {
                      value: scopeKey(draft.scopeKind, draft.scopeId),
                      "aria-invalid": Boolean(validation.errors[`${draft.clientKey}:scope`]),
                      onChange: (event: ValueChangeEvent) => {
                        const parsed = parseScope(event.target.value);
                        if (parsed) updateDraft(index, { scopeKind: parsed.kind, scopeId: parsed.id });
                      },
                    },
                    !scopeOptions.some((option) => option.key === scopeKey(draft.scopeKind, draft.scopeId))
                      ? h("option", { value: scopeKey(draft.scopeKind, draft.scopeId) }, "当前范围已不可用")
                      : null,
                    ...scopeOptions.map((option) => h("option", { key: option.key, value: option.key }, option.label)),
                    ),
                  ),
                  h("label", null,
                    h("span", null, "优先级"),
                    h("input", {
                      type: "number",
                      min: -10_000,
                      max: 10_000,
                      step: 1,
                      value: draft.priorityText,
                      "aria-invalid": Boolean(validation.errors[`${draft.clientKey}:priority`]),
                      onChange: (event: ValueChangeEvent) => updateDraft(index, { priorityText: event.target.value }),
                    }),
                  ),
                ),
                itemErrors.length
                  ? h("ul", { className: "anw-pronunciation-panel__validation", role: "alert" },
                    ...itemErrors.map((message) => h("li", { key: message }, message)),
                  )
                  : null,
                h("button", {
                  type: "button",
                  className: "anw-pronunciation-panel__remove",
                  onClick: () => removeDraft(index),
                }, `移除规则 ${index + 1}`),
                );
              }),
            ),
          ),
          state.phase === "save-error"
            ? h("div", { className: "anw-pronunciation-panel__error", role: "alert" }, state.message)
            : null,
          h("aside", { className: "anw-pronunciation-panel__history" },
            h("strong", null, "版本与历史安全"),
            h("p", null, "保存采用 CAS 并创建全量不可变发音版本。历史 Edition 继续引用原版本；只有作者主动重新生成时，新配置才进入新脚本。"),
          ),
          h("footer", { className: "anw-pronunciation-panel__footer" },
            h("span", null, dirty ? "有未保存更改" : "配置已同步"),
            h("button", {
              ref: saveButtonRef,
              type: "button",
              className: "anw-pronunciation-panel__save",
              disabled: saveDisabled,
              onClick: save,
            }, state.phase === "saving" ? "保存中…" : "保存发音配置"),
          ),
        )
        : state.phase !== "load-error" && state.phase !== "blocked"
          ? h("p", { className: "anw-pronunciation-panel__loading" }, "正在读取发音与停顿设置…")
          : null,
    );
  };
}
