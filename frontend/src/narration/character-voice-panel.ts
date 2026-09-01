import {
  NarrationApiError,
  getCharacterVoiceBinding,
  listVoiceProfiles,
  putCharacterVoiceBinding,
} from "./api";
import type {
  CapabilityKey,
  CharacterVoiceBindingPolicy,
  CharacterVoiceBindingResource,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  PutCharacterVoiceBindingRequest,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceSourceType,
} from "./contracts";
import {
  voiceActivationEvidenceIsUsable,
  voiceSourceEvidenceIsUsable,
} from "./contracts";


const LANGUAGE_PATTERN = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$/;
const MUTATION_CAPABILITY_KEYS = ["narration_product", "reading_settings"] as const;


export interface CharacterVoicePanelReactRuntime {
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


export interface CharacterVoicePanelApi {
  getCharacterVoiceBinding(
    novelId: string,
    characterId: string,
    signal?: AbortSignal,
  ): Promise<CharacterVoiceBindingResource>;
  listVoiceProfiles(options?: {
    readonly novelId?: string;
    readonly includeLibrary?: boolean;
    readonly signal?: AbortSignal;
  }): Promise<{ readonly items: readonly VoiceProfileResource[] }>;
  putCharacterVoiceBinding(
    novelId: string,
    characterId: string,
    payload: PutCharacterVoiceBindingRequest,
    signal?: AbortSignal,
  ): Promise<CharacterVoiceBindingResource>;
}


export interface CharacterVoicePanelProps {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly className?: string;
  readonly presentation?: "standalone" | "embedded";
  /** Limit the manual selector when official presets already have a dedicated picker. */
  readonly allowedSourceTypes?: readonly VoiceSourceType[];
  /** Reload locked voice choices after the shared source workspace changes a profile. */
  readonly profileRefreshVersion?: number;
  readonly onSaved?: (binding: CharacterVoiceBindingResource) => void;
  /** Called when the panel unmounts so its host can restore the opening control's focus. */
  readonly onReturnFocus?: () => void;
}


export interface CharacterVoiceOption {
  readonly key: string;
  readonly profileId: string;
  readonly versionId: string;
  readonly profileName: string;
  readonly versionNumber: number;
  readonly language: string;
  readonly sourceType: VoiceSourceType;
}


export interface CharacterVoiceDraft {
  readonly bindingPolicy: CharacterVoiceBindingPolicy;
  readonly profileId: string | null;
  readonly versionId: string | null;
  readonly language: string;
}


type CharacterVoicePanelPhase =
  | "blocked"
  | "loading"
  | "ready"
  | "saving"
  | "load-error"
  | "save-error"
  | "conflict";


interface CharacterVoicePanelState {
  readonly phase: CharacterVoicePanelPhase;
  readonly binding: CharacterVoiceBindingResource | null;
  readonly profiles: readonly VoiceProfileResource[];
  readonly draft: CharacterVoiceDraft;
  readonly message: string;
  readonly conflictVersion: number | null;
}


interface ValueChangeEvent {
  readonly target: { readonly value: string };
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
}


class CharacterVoicePanelDataError extends Error {}


const defaultApi: CharacterVoicePanelApi = {
  getCharacterVoiceBinding,
  listVoiceProfiles,
  putCharacterVoiceBinding,
};


const POLICY_LABELS: Readonly<Record<CharacterVoiceBindingPolicy, string>> = {
  dedicated: "使用专属声音",
  inherited: "明确继承声音",
  unset: "暂不配置声音",
};


const SOURCE_LABELS: Readonly<Record<VoiceSourceType, string>> = {
  preset: "官方预设音色",
  uploaded: "参考录音音色",
  generated: "描述生成音色",
};


const SOURCE_CAPABILITIES: Readonly<Record<VoiceSourceType, CapabilityKey>> = {
  preset: "preset_voice_source",
  uploaded: "reference_clone",
  generated: "voice_generator",
};


function capabilityByKey(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | undefined {
  return capabilities.items.find((item) => item.key === key);
}


export function isCharacterVoiceCapabilityActionable(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): boolean {
  const capability = capabilityByKey(capabilities, key);
  return capability?.state === "enabled"
    && capability.visible
    && capability.actionable;
}


function canConfigureCharacterVoice(props: CharacterVoicePanelProps): boolean {
  return props.authorization.can_read
    && props.authorization.can_configure
    && MUTATION_CAPABILITY_KEYS.every((key) => (
      isCharacterVoiceCapabilityActionable(props.capabilities, key)
    ));
}


function capabilityBlockMessage(props: CharacterVoicePanelProps): string {
  if (!props.authorization.can_read) return "当前身份无权查看人物声音设置。";
  if (!props.authorization.can_configure) return "当前身份只能查看，不能修改人物声音。";
  for (const key of MUTATION_CAPABILITY_KEYS) {
    const capability = capabilityByKey(props.capabilities, key);
    if (!capability || !isCharacterVoiceCapabilityActionable(props.capabilities, key)) {
      const reason = capability?.reason_code ? `（${capability.reason_code}）` : "";
      return `朗读产品能力尚未开放，人物声音保持只读${reason}。`;
    }
  }
  return "";
}


function currentVersion(profile: VoiceProfileResource): VoiceProfileVersionResource | null {
  if (profile.current_version_id === null) return null;
  return profile.versions.find((version) => (
    version.version_id === profile.current_version_id
  )) ?? null;
}


function voiceOptionKey(profileId: string, versionId: string): string {
  return `${profileId}:${versionId}`;
}


/**
 * Produce only server-locked, quality-accepted and currently rights-valid choices.
 * Source capabilities are checked again here so a healthy model or stale profile
 * can never turn a held product feature into an actionable option.
 */
export function characterVoiceOptions(
  profiles: readonly VoiceProfileResource[],
  novelId: string,
  capabilities: NarrationCapabilities,
  allowedSourceTypes?: readonly VoiceSourceType[],
): readonly CharacterVoiceOption[] {
  const options: CharacterVoiceOption[] = [];
  for (const profile of profiles) {
    if (profile.novel_id !== null && profile.novel_id !== novelId) continue;
    if (profile.status !== "active") continue;
    const version = currentVersion(profile);
    if (!version
      || (allowedSourceTypes !== undefined && !allowedSourceTypes.includes(version.source_type))
      || version.state !== "locked"
      || !voiceActivationEvidenceIsUsable(version)
      || version.rights.state !== "active"
      || !voiceSourceEvidenceIsUsable(version)
      || !isCharacterVoiceCapabilityActionable(
        capabilities,
        SOURCE_CAPABILITIES[version.source_type],
      )) continue;
    options.push({
      key: voiceOptionKey(profile.profile_id, version.version_id),
      profileId: profile.profile_id,
      versionId: version.version_id,
      profileName: profile.name,
      versionNumber: version.version_number,
      language: version.language,
      sourceType: version.source_type,
    });
  }
  return options.sort((left, right) => (
    left.profileName.localeCompare(right.profileName, "zh-CN")
      || left.versionNumber - right.versionNumber
      || left.key.localeCompare(right.key)
  ));
}


export function characterVoiceDraftFromBinding(
  binding: CharacterVoiceBindingResource,
): CharacterVoiceDraft {
  return {
    bindingPolicy: binding.binding_policy,
    profileId: binding.profile_id,
    versionId: binding.version_id,
    language: binding.language,
  };
}


export function buildCharacterVoiceBindingRequest(
  binding: CharacterVoiceBindingResource,
  draft: CharacterVoiceDraft,
  options: readonly CharacterVoiceOption[],
): PutCharacterVoiceBindingRequest | null {
  if (!LANGUAGE_PATTERN.test(draft.language)) return null;
  if (draft.bindingPolicy === "unset") {
    if (draft.profileId !== null || draft.versionId !== null) return null;
    return {
      expected_version: binding.version,
      binding_policy: "unset",
      profile_id: null,
      version_id: null,
      language: draft.language,
    };
  }
  const option = options.find((item) => (
    item.profileId === draft.profileId && item.versionId === draft.versionId
  ));
  if (!option) return null;
  return {
    expected_version: binding.version,
    binding_policy: draft.bindingPolicy,
    profile_id: option.profileId,
    version_id: option.versionId,
    language: draft.language,
  };
}


function draftEqualsBinding(
  draft: CharacterVoiceDraft,
  binding: CharacterVoiceBindingResource,
): boolean {
  return draft.bindingPolicy === binding.binding_policy
    && draft.profileId === binding.profile_id
    && draft.versionId === binding.version_id
    && draft.language === binding.language;
}


function initialState(canRead: boolean): CharacterVoicePanelState {
  return {
    phase: canRead ? "loading" : "blocked",
    binding: null,
    profiles: [],
    draft: {
      bindingPolicy: "unset",
      profileId: null,
      versionId: null,
      language: "zh-CN",
    },
    message: "",
    conflictVersion: null,
  };
}


function assertLoadedScope(
  novelId: string,
  characterId: string,
  binding: CharacterVoiceBindingResource,
  profiles: readonly VoiceProfileResource[],
): void {
  if (binding.novel_id !== novelId || binding.character_id !== characterId) {
    throw new CharacterVoicePanelDataError("人物声音响应与当前作品或人物不一致。");
  }
  if (profiles.some((profile) => profile.novel_id !== null && profile.novel_id !== novelId)) {
    throw new CharacterVoicePanelDataError("音色列表包含其他作品的数据，已拒绝显示。");
  }
  const profileIds = profiles.map((profile) => profile.profile_id);
  if (new Set(profileIds).size !== profileIds.length) {
    throw new CharacterVoicePanelDataError("音色列表包含重复身份，已拒绝显示。");
  }
}


function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}


function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof CharacterVoicePanelDataError) return reason.message;
  if (reason instanceof NarrationApiError) {
    const labels: Partial<Record<typeof reason.detail.code, string>> = {
      CAPABILITY_DISABLED: "朗读能力尚未开放，无法修改人物声音。",
      VOICE_VERSION_NOT_LOCKED: "所选音色版本尚未锁定，请重新选择。",
      VOICE_RIGHTS_REQUIRED: "所选音色缺少有效的本地使用或上传权利记录，无法绑定。",
      VOICE_RIGHTS_UNAVAILABLE: "所选音色的本地使用状态或上传权利已失效，无法绑定。",
      VOICE_SOURCE_UNAVAILABLE: "所选音色来源当前不可用。",
      SCOPE_VIOLATION: "人物或音色不属于当前作品。",
      RESOURCE_NOT_FOUND: "人物或音色已不存在，请刷新。",
      STORAGE_UNAVAILABLE: "朗读设置存储暂不可用，请稍后重试。",
      SETTINGS_BACKEND_NOT_INSTALLED: "朗读设置服务尚未接入。",
    };
    return labels[reason.detail.code] ?? `${fallback}（${reason.detail.code}）`;
  }
  return fallback;
}


function policyFromValue(value: string): CharacterVoiceBindingPolicy | null {
  return value === "dedicated" || value === "inherited" || value === "unset"
    ? value
    : null;
}


export function createCharacterVoicePanel(
  React: CharacterVoicePanelReactRuntime,
  api: CharacterVoicePanelApi = defaultApi,
): (props: CharacterVoicePanelProps) => unknown {
  const h = React.createElement;

  return function CharacterVoicePanel(props: CharacterVoicePanelProps): unknown {
    const [state, setState] = React.useState(() => initialState(props.authorization.can_read));
    const stateRef = React.useRef(state);
    stateRef.current = state;
    const requestSequenceRef = React.useRef(0);
    const loadAbortRef = React.useRef<AbortController | null>(null);
    const saveAbortRef = React.useRef<AbortController | null>(null);
    const conflictRef = React.useRef<FocusableElement | null>(null);
    const saveButtonRef = React.useRef<FocusableElement | null>(null);
    const returnFocusRef = React.useRef(props.onReturnFocus);
    returnFocusRef.current = props.onReturnFocus;

    const commit = (
      update: CharacterVoicePanelState
        | ((current: CharacterVoicePanelState) => CharacterVoicePanelState),
    ) => {
      setState((current) => {
        const next = typeof update === "function" ? update(current) : update;
        stateRef.current = next;
        return next;
      });
    };

    const startLoad = (preserveDraft: boolean, restoreSaveFocus: boolean): AbortController | null => {
      if (!props.authorization.can_read) {
        commit({ ...initialState(false), message: capabilityBlockMessage(props) });
        return null;
      }
      loadAbortRef.current?.abort();
      const controller = new AbortController();
      loadAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      const preserved = preserveDraft ? stateRef.current.draft : null;
      commit((current) => ({
        ...current,
        phase: "loading",
        message: preserveDraft ? "正在刷新服务端版本，已保留你的选择…" : "正在加载人物声音…",
        conflictVersion: null,
      }));
      void Promise.all([
        api.getCharacterVoiceBinding(props.novelId, props.characterId, controller.signal),
        api.listVoiceProfiles({
          novelId: props.novelId,
          includeLibrary: true,
          signal: controller.signal,
        }),
      ]).then(([binding, profileList]) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertLoadedScope(props.novelId, props.characterId, binding, profileList.items);
        commit({
          phase: "ready",
          binding,
          profiles: profileList.items,
          draft: preserved ?? characterVoiceDraftFromBinding(binding),
          message: preserveDraft
            ? "已刷新服务端版本；你的声音选择已保留，请核对后重新保存。"
            : "人物声音已加载。",
          conflictVersion: null,
        });
        if (restoreSaveFocus) {
          queueMicrotask(() => saveButtonRef.current?.focus({ preventScroll: true }));
        }
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        commit((current) => ({
          ...current,
          phase: "load-error",
          message: errorMessage(reason, preserveDraft ? "刷新人物声音失败。" : "加载人物声音失败。"),
          conflictVersion: null,
        }));
      });
      return controller;
    };

    React.useEffect(() => {
      if (!props.authorization.can_read) {
        loadAbortRef.current?.abort();
        saveAbortRef.current?.abort();
        commit({ ...initialState(false), message: capabilityBlockMessage(props) });
        return undefined;
      }
      const controller = startLoad(false, false);
      return () => controller?.abort();
    }, [
      props.novelId,
      props.characterId,
      props.authorization.can_read,
      props.profileRefreshVersion ?? 0,
    ]);

    React.useEffect(() => () => {
      loadAbortRef.current?.abort();
      saveAbortRef.current?.abort();
      returnFocusRef.current?.();
    }, []);

    React.useEffect(() => {
      if (state.phase === "conflict") {
        conflictRef.current?.focus({ preventScroll: true });
      }
    }, [state.phase]);

    const binding = props.authorization.can_read
      && state.binding?.novel_id === props.novelId
      && state.binding.character_id === props.characterId
      ? state.binding
      : null;
    const options = characterVoiceOptions(
      state.profiles,
      props.novelId,
      props.capabilities,
      props.allowedSourceTypes,
    );
    const selectedKey = state.draft.profileId && state.draft.versionId
      ? voiceOptionKey(state.draft.profileId, state.draft.versionId)
      : "";
    const selectedIsEligible = selectedKey === ""
      || options.some((option) => option.key === selectedKey);
    const configureAllowed = canConfigureCharacterVoice(props);
    const editablePhase = state.phase === "ready" || state.phase === "save-error";
    const fieldsDisabled = !configureAllowed || !editablePhase;
    const payload = binding
      ? buildCharacterVoiceBindingRequest(binding, state.draft, options)
      : null;
    const dirty = Boolean(binding && !draftEqualsBinding(state.draft, binding));
    const saveDisabled = fieldsDisabled || !dirty || payload === null;
    const prefix = `anw-character-voice-${props.characterId}`;
    const headingId = `${prefix}-heading`;
    const statusId = `${prefix}-status`;
    const voiceSelectId = `${prefix}-voice`;
    const languageId = `${prefix}-language`;

    const updateDraft = (draft: CharacterVoiceDraft) => {
      if (fieldsDisabled) return;
      commit((current) => ({ ...current, draft, phase: "ready", message: "声音设置有未保存的更改。" }));
    };

    const onPolicyChange = (event: ValueChangeEvent) => {
      const policy = policyFromValue(event.target.value);
      if (!policy || fieldsDisabled) return;
      if (policy === "unset") {
        updateDraft({
          ...stateRef.current.draft,
          bindingPolicy: "unset",
          profileId: null,
          versionId: null,
        });
        return;
      }
      const currentDraft = stateRef.current.draft;
      const retained = options.find((option) => (
        option.profileId === currentDraft.profileId
          && option.versionId === currentDraft.versionId
      ));
      const selected = retained ?? options[0];
      updateDraft({
        ...currentDraft,
        bindingPolicy: policy,
        profileId: selected?.profileId ?? null,
        versionId: selected?.versionId ?? null,
        language: selected?.language ?? currentDraft.language,
      });
    };

    const onVoiceChange = (event: ValueChangeEvent) => {
      if (fieldsDisabled) return;
      const option = options.find((item) => item.key === event.target.value);
      if (!option) return;
      updateDraft({
        ...stateRef.current.draft,
        profileId: option.profileId,
        versionId: option.versionId,
        language: option.language,
      });
    };

    const onLanguageChange = (event: ValueChangeEvent) => {
      if (fieldsDisabled) return;
      updateDraft({ ...stateRef.current.draft, language: event.target.value.trim() });
    };

    const save = () => {
      const current = stateRef.current;
      const currentOptions = characterVoiceOptions(
        current.profiles,
        props.novelId,
        props.capabilities,
        props.allowedSourceTypes,
      );
      const request = current.binding
        ? buildCharacterVoiceBindingRequest(current.binding, current.draft, currentOptions)
        : null;
      if (!canConfigureCharacterVoice(props)
        || (current.phase !== "ready" && current.phase !== "save-error")
        || !request
        || !current.binding
        || current.binding.novel_id !== props.novelId
        || current.binding.character_id !== props.characterId
        || draftEqualsBinding(current.draft, current.binding)) return;
      saveAbortRef.current?.abort();
      const controller = new AbortController();
      saveAbortRef.current = controller;
      const sequence = ++requestSequenceRef.current;
      commit({ ...current, phase: "saving", message: "正在保存人物声音…", conflictVersion: null });
      void api.putCharacterVoiceBinding(
        props.novelId,
        props.characterId,
        request,
        controller.signal,
      ).then((binding) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current) return;
        assertLoadedScope(props.novelId, props.characterId, binding, current.profiles);
        commit({
          ...current,
          phase: "ready",
          binding,
          draft: characterVoiceDraftFromBinding(binding),
          message: "人物声音已保存；历史 Edition 保持不变。",
          conflictVersion: null,
        });
        props.onSaved?.(binding);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequenceRef.current || isAbortError(reason)) return;
        if (reason instanceof NarrationApiError && reason.detail.code === "VERSION_CONFLICT") {
          commit((latest) => ({
            ...latest,
            phase: "conflict",
            message: "服务端绑定已变化。你的声音选择仍保留；请先刷新，再重新保存。",
            conflictVersion: reason.detail.current_version,
          }));
          return;
        }
        commit((latest) => ({
          ...latest,
          phase: "save-error",
          message: errorMessage(reason, "保存人物声音失败。你的选择已保留。"),
          conflictVersion: null,
        }));
      });
    };

    const statusText = state.message || capabilityBlockMessage(props);
    const rootClassName = [
      "anw-character-voice-panel",
      `is-${state.phase}`,
      props.className ?? "",
    ].filter(Boolean).join(" ");
    const impact = binding?.impact;
    const currentUnavailable = selectedKey !== "" && !selectedIsEligible;
    const currentProfile = currentUnavailable
      ? state.profiles.find((profile) => profile.profile_id === state.draft.profileId)
      : undefined;
    const blockMessage = capabilityBlockMessage(props);

    return h(
      "section",
      {
        className: rootClassName,
        role: "region",
        "aria-labelledby": props.presentation === "embedded" ? undefined : headingId,
        "aria-label": props.presentation === "embedded"
          ? `${props.characterName}的私人音色手动设置`
          : undefined,
        "aria-describedby": statusId,
        "aria-busy": state.phase === "loading" || state.phase === "saving",
        "data-character-id": props.characterId,
        "data-voice-panel-phase": state.phase,
      },
      props.presentation === "embedded"
        ? null
        : h("header", { className: "anw-character-voice-panel__header" },
          h("div", null,
            h("span", { className: "anw-character-voice-panel__eyebrow" }, "人物卡 · 声音"),
            h("h3", { id: headingId, tabIndex: -1 }, `${props.characterName}的声音`),
          ),
          binding
            ? h("span", { className: "anw-character-voice-panel__version" }, `绑定版本 ${binding.version}`)
            : null,
        ),
      h(
        "div",
        {
          id: statusId,
          className: "anw-character-voice-panel__live",
          role: "status",
          "aria-live": "polite",
          "aria-atomic": "true",
        },
        statusText,
      ),
      blockMessage
        ? h("p", { className: "anw-character-voice-panel__notice" }, blockMessage)
        : null,
      state.phase === "load-error"
        ? h("div", { className: "anw-character-voice-panel__error", role: "alert" },
          h("strong", null, state.message),
          props.authorization.can_read
            ? h("button", {
              type: "button",
              onClick: () => startLoad(state.binding !== null, state.binding !== null),
            }, state.binding ? "重试刷新" : "重新加载")
            : null,
        )
        : null,
      state.phase === "conflict"
        ? h("div", {
          className: "anw-character-voice-panel__error",
          role: "alert",
          tabIndex: -1,
          ref: conflictRef,
        },
        h("strong", null, "检测到版本冲突"),
        h("span", null, state.conflictVersion === null
          ? state.message
          : `${state.message} 服务端当前版本为 ${state.conflictVersion}。`),
        h("button", {
          type: "button",
          onClick: () => startLoad(true, true),
        }, "刷新最新绑定"),
        )
        : null,
      binding
        ? h("div", { className: "anw-character-voice-panel__body" },
          h("fieldset", { disabled: fieldsDisabled },
            h("legend", null, "声音策略"),
            ...(["dedicated", "inherited", "unset"] as const).map((policy) => h(
              "label",
              { key: policy, className: "anw-character-voice-panel__radio" },
              h("input", {
                type: "radio",
                name: `${prefix}-policy`,
                value: policy,
                checked: state.draft.bindingPolicy === policy,
                onChange: onPolicyChange,
              }),
              h("span", null, POLICY_LABELS[policy]),
            )),
          ),
          state.draft.bindingPolicy !== "unset"
            ? h("div", { className: "anw-character-voice-panel__field" },
              h("label", { htmlFor: voiceSelectId }, "锁定音色版本"),
              h("select", {
                id: voiceSelectId,
                value: selectedKey,
                disabled: fieldsDisabled || options.length === 0,
                onChange: onVoiceChange,
                "aria-invalid": currentUnavailable || selectedKey === "",
              },
              selectedKey === ""
                ? h("option", { value: "", disabled: true }, "请选择可用音色")
                : null,
              currentUnavailable
                ? h("option", { value: selectedKey, disabled: true },
                  `${currentProfile?.name ?? "当前音色"}（来源身份、本地可用、锁定、质量或来源能力已不可用）`,
                )
                : null,
              ...options.map((option) => h(
                "option",
                { key: option.key, value: option.key },
                `${option.profileName} · v${option.versionNumber} · ${SOURCE_LABELS[option.sourceType]}`,
              )),
              ),
              h("p", { className: "anw-character-voice-panel__hint" },
                options.length
                  ? "这里只列出来源身份已核验、本地可用、已锁定、质量已接受且来源能力已开放的不可变版本。"
                  : "当前没有满足来源身份、本地可用、锁定、质量与来源能力门禁的可选音色。",
              ),
            )
            : h("p", { className: "anw-character-voice-panel__hint" },
              "暂不配置不会删除任何音色资产，也不会改写历史朗读。",
            ),
          h("div", { className: "anw-character-voice-panel__field" },
            h("label", { htmlFor: languageId }, "默认语言"),
            h("input", {
              id: languageId,
              type: "text",
              value: state.draft.language,
              pattern: "[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}",
              maxLength: 40,
              disabled: fieldsDisabled,
              "aria-invalid": !LANGUAGE_PATTERN.test(state.draft.language),
              onChange: onLanguageChange,
            }),
            !LANGUAGE_PATTERN.test(state.draft.language)
              ? h("span", { className: "anw-character-voice-panel__validation", role: "alert" },
                "请输入受支持的语言标签，例如 zh-CN。",
              )
              : null,
          ),
          impact
            ? h("aside", {
              className: "anw-character-voice-panel__impact",
              "aria-labelledby": `${prefix}-impact-heading`,
            },
            h("h4", { id: `${prefix}-impact-heading` }, "保存影响预览（服务端基线）"),
            h("dl", null,
              h("div", null, h("dt", null, "影响章节"), h("dd", null, impact.affected_chapter_count)),
              h("div", null, h("dt", null, "影响句段"), h("dd", null, impact.affected_segment_count)),
              h("div", null, h("dt", null, "历史 Edition"), h("dd", null, impact.historical_edition_count)),
              h("div", null, h("dt", null, "需重新生成"), h("dd", null, impact.regeneration_required ? "是" : "否")),
            ),
            h("p", null,
              `已有 ${impact.historical_edition_count} 个历史 Edition 不会被改写或替换。`,
              impact.regeneration_required
                ? "保存后，也只会在作者主动更新朗读时重生成受影响句段。"
                : "本次基线未标记必须重生成。",
            ),
            dirty
              ? h("p", { className: "anw-character-voice-panel__hint" },
                "当前候选尚未保存；最终影响数量以 CAS 保存响应的重新计算结果为准。",
              )
              : null,
            )
            : null,
          state.phase === "save-error"
            ? h("div", { className: "anw-character-voice-panel__error", role: "alert" }, state.message)
            : null,
          h("footer", { className: "anw-character-voice-panel__footer" },
            h("span", null, dirty ? "有未保存更改" : "设置已同步"),
            h("button", {
              ref: saveButtonRef,
              type: "button",
              className: "anw-character-voice-panel__save",
              disabled: saveDisabled,
              onClick: save,
            }, state.phase === "saving" ? "保存中…" : "保存人物声音"),
          ),
        )
        : state.phase !== "load-error" && state.phase !== "blocked"
          ? h("p", { className: "anw-character-voice-panel__loading" }, "正在读取绑定和可用音色…")
          : null,
    );
  };
}
