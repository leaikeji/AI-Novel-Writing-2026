import { NarrationApiError } from "./api";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationErrorCode,
  NarrationPlaybackPreferences,
  NarrationSettingsResource,
  NarrationTextRules,
  NarrationTimingSettings,
  UpdateNarrationPlaybackPreferencesRequest,
  UpdateNarrationSettingsRequest,
} from "./contracts";


export const SUPPORTED_READING_LANGUAGES = ["zh-CN", "en", "ja-JP"] as const;
export type SupportedReadingLanguage = typeof SUPPORTED_READING_LANGUAGES[number];

export type ReadingPausePreset = "compact" | "natural" | "relaxed" | "custom";

export const READING_PAUSE_PRESETS: Readonly<Record<
  Exclude<ReadingPausePreset, "custom">,
  NarrationTimingSettings
>> = {
  compact: {
    sentence_gap_ms: 120,
    paragraph_gap_ms: 320,
    section_gap_ms: 620,
  },
  natural: {
    sentence_gap_ms: 220,
    paragraph_gap_ms: 480,
    section_gap_ms: 850,
  },
  relaxed: {
    sentence_gap_ms: 360,
    paragraph_gap_ms: 780,
    section_gap_ms: 1_300,
  },
};

const PAUSE_LABELS: Readonly<Record<Exclude<ReadingPausePreset, "custom">, string>> = {
  compact: "紧凑",
  natural: "自然",
  relaxed: "舒缓",
};

const PAUSE_DESCRIPTIONS: Readonly<Record<Exclude<ReadingPausePreset, "custom">, string>> = {
  compact: "句段衔接更快，适合信息密集章节。",
  natural: "接近日常朗读节奏，也是作品默认值。",
  relaxed: "留出更多呼吸，适合氛围和抒情段落。",
};

const MUTATION_CAPABILITIES = ["narration_product", "reading_settings"] as const;


export interface ReadingPreferencesReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
}


export interface ReadingBasePreferencesDraft {
  readonly language: string;
  readonly textRules: NarrationTextRules;
  readonly timing: NarrationTimingSettings;
}


export interface ReadingPreferencesPanelProps {
  readonly novelId: string;
  readonly settings: NarrationSettingsResource;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly characterOptions?: readonly Readonly<{
    novelId: string;
    characterId: string;
    label: string;
  }>[];
  readonly saveSettings: (
    novelId: string,
    request: UpdateNarrationSettingsRequest,
    signal?: AbortSignal,
  ) => Promise<NarrationSettingsResource>;
  readonly savePlaybackPreferences: (
    novelId: string,
    request: UpdateNarrationPlaybackPreferencesRequest,
    signal?: AbortSignal,
  ) => Promise<NarrationSettingsResource>;
  /** Applies unsaved rate/volume to the active player without claiming persistence. */
  readonly onImmediatePlaybackChange?: (playback: NarrationPlaybackPreferences) => void;
  readonly onSettingsSaved?: (settings: NarrationSettingsResource) => void;
  readonly onPlaybackPreferencesSaved?: (settings: NarrationSettingsResource) => void;
  readonly onRefresh?: () => void;
  readonly className?: string;
}


export interface ReadingPreferencesFailure {
  readonly code: NarrationErrorCode | "NETWORK_ERROR" | "CANCELLED" | "RESPONSE_SCOPE_MISMATCH";
  readonly message: string;
  readonly refreshRequired: boolean;
}


interface ReadingPreferencesOperation {
  readonly kind: "base" | "playback" | null;
  readonly message: string | null;
  readonly failure: ReadingPreferencesFailure | null;
}


const IDLE_OPERATION: ReadingPreferencesOperation = {
  kind: null,
  message: null,
  failure: null,
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


export function canConfigureReadingPreferences(
  capabilities: NarrationCapabilities,
  authorization: NarrationAuthorizationState,
): boolean {
  return authorization.can_read
    && authorization.can_configure
    && MUTATION_CAPABILITIES.every((key) => actionable(capability(capabilities, key)));
}


function blockedReason(props: ReadingPreferencesPanelProps): string | null {
  if (!props.authorization.can_read) return "当前身份无权查看本作品的朗读偏好。";
  if (!props.authorization.can_configure) return "当前身份只能查看，不能修改朗读偏好。";
  for (const key of MUTATION_CAPABILITIES) {
    const item = capability(props.capabilities, key);
    if (!actionable(item)) {
      return `朗读设置能力尚未开放${item?.reason_code ? `（${item.reason_code}）` : ""}。`;
    }
  }
  return null;
}


export function readingBasePreferencesFromSettings(
  settings: NarrationSettingsResource,
): ReadingBasePreferencesDraft {
  return {
    language: settings.values.language,
    textRules: settings.values.text_rules,
    timing: settings.values.timing,
  };
}


export function pausePresetForTiming(timing: NarrationTimingSettings): ReadingPausePreset {
  for (const preset of ["compact", "natural", "relaxed"] as const) {
    const value = READING_PAUSE_PRESETS[preset];
    if (
      value.sentence_gap_ms === timing.sentence_gap_ms
      && value.paragraph_gap_ms === timing.paragraph_gap_ms
      && value.section_gap_ms === timing.section_gap_ms
    ) return preset;
  }
  return "custom";
}


export function normalizePlaybackPreferences(input: {
  readonly playback_rate: number;
  readonly volume: number;
}): NarrationPlaybackPreferences {
  const rate = Number.isFinite(input.playback_rate) ? input.playback_rate : 1;
  const volume = Number.isFinite(input.volume) ? input.volume : 1;
  return {
    playback_rate: Math.min(3, Math.max(0.5, Math.round(rate * 100) / 100)),
    volume: Math.min(1, Math.max(0, Math.round(volume * 100) / 100)),
  };
}


export function buildReadingBaseSettingsRequest(
  settings: NarrationSettingsResource,
  draft: ReadingBasePreferencesDraft,
): UpdateNarrationSettingsRequest {
  return {
    expected_version: settings.version,
    values: {
      ...settings.values,
      language: draft.language,
      text_rules: draft.textRules,
      timing: draft.timing,
    },
  };
}


export function buildReadingPlaybackPreferencesRequest(
  settings: NarrationSettingsResource,
  playback: NarrationPlaybackPreferences,
): UpdateNarrationPlaybackPreferencesRequest {
  return {
    expected_version: settings.version,
    playback: normalizePlaybackPreferences(playback),
  };
}


function baseDraftEqual(left: ReadingBasePreferencesDraft, right: ReadingBasePreferencesDraft): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}


function playbackEqual(
  left: NarrationPlaybackPreferences,
  right: NarrationPlaybackPreferences,
): boolean {
  return left.playback_rate === right.playback_rate && left.volume === right.volume;
}


function abortLike(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


export function classifyReadingPreferencesFailure(reason: unknown): ReadingPreferencesFailure {
  if (abortLike(reason)) {
    return {
      code: "CANCELLED",
      message: "操作已取消。",
      refreshRequired: false,
    };
  }
  if (!(reason instanceof NarrationApiError)) {
    return {
      code: "NETWORK_ERROR",
      message: "朗读设置服务连接失败，本地调整仍保留。",
      refreshRequired: false,
    };
  }
  if (reason.detail.code === "VERSION_CONFLICT") {
    return {
      code: reason.detail.code,
      message: "设置已在其他位置更新。请刷新后重新应用本地偏好。",
      refreshRequired: true,
    };
  }
  if (["SCOPE_VIOLATION", "RESOURCE_NOT_FOUND"].includes(reason.detail.code)) {
    return {
      code: reason.detail.code,
      message: "当前作品范围已经变化，已拒绝应用设置。",
      refreshRequired: true,
    };
  }
  return {
    code: reason.detail.code,
    message: "朗读偏好未保存，其他作品设置没有被覆盖。",
    refreshRequired: false,
  };
}


function scopeMismatchFailure(): ReadingPreferencesFailure {
  return {
    code: "RESPONSE_SCOPE_MISMATCH",
    message: "服务返回了其他作品或不匹配的设置版本，已拒绝应用。",
    refreshRequired: true,
  };
}


function responseMatchesBase(
  resource: NarrationSettingsResource,
  novelId: string,
  baselineVersion: number,
  draft: ReadingBasePreferencesDraft,
): boolean {
  return resource.novel_id === novelId
    && resource.version > baselineVersion
    && resource.values.language === draft.language
    && JSON.stringify(resource.values.text_rules) === JSON.stringify(draft.textRules)
    && JSON.stringify(resource.values.timing) === JSON.stringify(draft.timing);
}


function responseMatchesPlayback(
  resource: NarrationSettingsResource,
  novelId: string,
  baselineVersion: number,
  playback: NarrationPlaybackPreferences,
): boolean {
  return resource.novel_id === novelId
    && resource.version > baselineVersion
    && playbackEqual(resource.values.playback, playback);
}


interface ValueChangeEvent {
  readonly target: { readonly value: string; readonly checked: boolean };
}


export function createReadingPreferencesPanel(
  React: ReadingPreferencesReactRuntime,
): (props: ReadingPreferencesPanelProps) => unknown {
  const h = React.createElement;

  return function ReadingPreferencesPanel(props: ReadingPreferencesPanelProps): unknown {
    const [baseline, setBaseline] = React.useState(props.settings);
    const [baseDraft, setBaseDraft] = React.useState<ReadingBasePreferencesDraft>(() => (
      readingBasePreferencesFromSettings(props.settings)
    ));
    const [playbackDraft, setPlaybackDraft] = React.useState<NarrationPlaybackPreferences>(
      props.settings.values.playback,
    );
    const [operation, setOperation] = React.useState<ReadingPreferencesOperation>(IDLE_OPERATION);
    const controllers = React.useRef<Set<AbortController>>(new Set());
    const novelRef = React.useRef(props.novelId);
    novelRef.current = props.novelId;

    React.useEffect(() => {
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
      const sameScope = baseline.novel_id === props.novelId;
      const previousBase = readingBasePreferencesFromSettings(baseline);
      const nextBase = readingBasePreferencesFromSettings(props.settings);
      setBaseline(props.settings);
      setBaseDraft((current) => (
        sameScope && !baseDraftEqual(current, previousBase) ? current : nextBase
      ));
      setPlaybackDraft((current) => (
        sameScope && !playbackEqual(current, baseline.values.playback)
          ? current
          : props.settings.values.playback
      ));
      setOperation(IDLE_OPERATION);
      return () => {
        for (const controller of controllers.current) controller.abort();
        controllers.current.clear();
      };
    }, [props.novelId, props.settings.settings_id, props.settings.version, props.settings.updated_at]);

    const canConfigure = canConfigureReadingPreferences(props.capabilities, props.authorization);
    const busy = operation.kind !== null;
    const scopeMatches = baseline.novel_id === props.novelId && props.settings.novel_id === props.novelId;
    const languageSupported = SUPPORTED_READING_LANGUAGES.includes(
      baseDraft.language as SupportedReadingLanguage,
    );
    const characters = (props.characterOptions ?? []).filter(
      (character) => character.novelId === props.novelId,
    );
    const selectedFirstPersonCharacter = baseDraft.textRules.first_person_character_id;
    const firstPersonCharacterValid = baseDraft.textRules.first_person_mode === "narrator"
      || characters.some((character) => character.characterId === selectedFirstPersonCharacter);
    const baseDirty = !baseDraftEqual(baseDraft, readingBasePreferencesFromSettings(baseline));
    const playbackDirty = !playbackEqual(playbackDraft, baseline.values.playback);
    const disabled = !scopeMatches || !canConfigure || busy;
    const prefix = `anw-reading-preferences-${props.novelId}`;

    const begin = (kind: "base" | "playback"): AbortController => {
      const controller = new AbortController();
      controllers.current.add(controller);
      setOperation({ kind, message: null, failure: null });
      return controller;
    };
    const finish = (controller: AbortController): boolean => {
      controllers.current.delete(controller);
      return !controller.signal.aborted && novelRef.current === props.novelId;
    };
    const fail = (controller: AbortController, reason: unknown): void => {
      if (!finish(controller)) return;
      const failure = classifyReadingPreferencesFailure(reason);
      if (failure.code === "CANCELLED") return;
      setOperation({ kind: null, message: null, failure });
    };

    const updatePlayback = (next: NarrationPlaybackPreferences): void => {
      if (disabled) return;
      const normalized = normalizePlaybackPreferences(next);
      setPlaybackDraft(normalized);
      setOperation(IDLE_OPERATION);
      props.onImmediatePlaybackChange?.(normalized);
    };

    const saveBase = (): void => {
      if (disabled || !baseDirty || !languageSupported) return;
      const controller = begin("base");
      const snapshot = baseDraft;
      const baselineVersion = baseline.version;
      const request = buildReadingBaseSettingsRequest(baseline, snapshot);
      void props.saveSettings(props.novelId, request, controller.signal).then((resource) => {
        if (!finish(controller)) return;
        if (!responseMatchesBase(resource, props.novelId, baselineVersion, snapshot)) {
          setOperation({ kind: null, message: null, failure: scopeMismatchFailure() });
          return;
        }
        setBaseline(resource);
        setBaseDraft(readingBasePreferencesFromSettings(resource));
        setOperation({ kind: null, message: "基础朗读设置已保存。", failure: null });
        props.onSettingsSaved?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    const savePlayback = (): void => {
      if (disabled || !playbackDirty) return;
      const controller = begin("playback");
      const snapshot = normalizePlaybackPreferences(playbackDraft);
      const baselineVersion = baseline.version;
      const request = buildReadingPlaybackPreferencesRequest(baseline, snapshot);
      void props.savePlaybackPreferences(props.novelId, request, controller.signal).then((resource) => {
        if (!finish(controller)) return;
        if (!responseMatchesPlayback(resource, props.novelId, baselineVersion, snapshot)) {
          setOperation({ kind: null, message: null, failure: scopeMismatchFailure() });
          return;
        }
        setBaseline(resource);
        setPlaybackDraft(resource.values.playback);
        setOperation({ kind: null, message: "播放偏好已同步；无需重新合成。", failure: null });
        props.onPlaybackPreferencesSaved?.(resource);
      }).catch((reason: unknown) => fail(controller, reason));
    };

    if (!scopeMatches) {
      return h("section", {
        className: "anw-reading-preferences-panel",
        role: "region",
        "aria-labelledby": `${prefix}-heading`,
      },
      h("h2", { id: `${prefix}-heading` }, "旁白与朗读偏好"),
      h("p", { role: "alert" }, "朗读设置与当前作品不一致，已拒绝显示。"),
      );
    }

    const reason = blockedReason(props);
    const pausePreset = pausePresetForTiming(baseDraft.timing);
    const operationNode = operation.failure
      ? h("div", { className: "anw-reading-preferences-panel__error", role: "alert" },
        h("p", null, operation.failure.message),
        operation.failure.refreshRequired && props.onRefresh
          ? h("button", { type: "button", onClick: props.onRefresh }, "刷新最新设置")
          : null,
      )
      : operation.message
        ? h("p", {
          className: "anw-reading-preferences-panel__status",
          role: "status",
          "aria-live": "polite",
        }, operation.message)
        : null;

    return h("section", {
      className: ["anw-reading-preferences-panel", props.className ?? ""].filter(Boolean).join(" "),
      role: "region",
      "aria-labelledby": `${prefix}-heading`,
      "aria-busy": busy || undefined,
      "data-reading-preferences-state": busy ? `saving-${operation.kind}` : "ready",
    },
    h("header", { className: "anw-reading-preferences-panel__header" },
      h("div", null,
        h("p", { className: "anw-reading-preferences-panel__eyebrow" }, "作品级设置"),
        h("h2", { id: `${prefix}-heading`, tabIndex: -1 }, "旁白与朗读偏好"),
      ),
      h("span", { className: "anw-reading-preferences-panel__version" }, `设置版本 ${baseline.version}`),
    ),
    h("p", { className: "anw-reading-preferences-panel__intro" },
      "倍速和音量只改变播放器；语言、正文规则和停顿只影响以后生成的新脚本与 Edition。",
    ),
    reason
      ? h("p", { className: "anw-reading-preferences-panel__notice", role: "note" }, reason)
      : null,
    h("section", {
      className: "anw-reading-preferences-panel__section",
      "aria-labelledby": `${prefix}-playback-heading`,
    },
    h("div", { className: "anw-reading-preferences-panel__section-heading" },
      h("div", null,
        h("h3", { id: `${prefix}-playback-heading` }, "播放偏好"),
        h("p", null, "调整后立即作用于当前播放器，保存使用独立窄 PATCH，不会覆盖旁白和规则。"),
      ),
      h("span", { className: playbackDirty ? "is-unsaved" : "" }, playbackDirty ? "本地未同步" : "已同步"),
    ),
    h("fieldset", { disabled },
      h("legend", { className: "anw-reading-preferences-panel__sr-only" }, "播放器倍速与音量"),
      h("label", null,
        h("span", null, "播放倍速"),
        h("output", { htmlFor: `${prefix}-rate` }, `${playbackDraft.playback_rate.toFixed(2)}×`),
        h("input", {
          id: `${prefix}-rate`,
          type: "range",
          min: 0.5,
          max: 3,
          step: 0.05,
          value: playbackDraft.playback_rate,
          "aria-label": "播放倍速",
          onChange: (event: ValueChangeEvent) => updatePlayback({
            ...playbackDraft,
            playback_rate: Number(event.target.value),
          }),
        }),
      ),
      h("label", null,
        h("span", null, "播放器音量"),
        h("output", { htmlFor: `${prefix}-volume` }, `${Math.round(playbackDraft.volume * 100)}%`),
        h("input", {
          id: `${prefix}-volume`,
          type: "range",
          min: 0,
          max: 1,
          step: 0.01,
          value: playbackDraft.volume,
          "aria-label": "播放器音量",
          onChange: (event: ValueChangeEvent) => updatePlayback({
            ...playbackDraft,
            volume: Number(event.target.value),
          }),
        }),
      ),
    ),
    h("button", {
      type: "button",
      className: "anw-reading-preferences-panel__save",
      disabled: disabled || !playbackDirty,
      onClick: savePlayback,
    }, operation.kind === "playback" ? "同步中…" : "保存播放偏好"),
    ),
    h("section", {
      className: "anw-reading-preferences-panel__section",
      "aria-labelledby": `${prefix}-base-heading`,
    },
    h("div", { className: "anw-reading-preferences-panel__section-heading" },
      h("div", null,
        h("h3", { id: `${prefix}-base-heading` }, "新朗读版本的基础规则"),
        h("p", null, "这些选项不会改写正文或历史 Edition。"),
      ),
      h("span", { className: baseDirty ? "is-unsaved" : "" }, baseDirty ? "有未保存更改" : "已同步"),
    ),
    h("fieldset", { disabled },
      h("legend", null, "语言与正文"),
      h("label", { className: "anw-reading-preferences-panel__select" },
        h("span", null, "作品朗读语言"),
        h("select", {
          value: baseDraft.language,
          "aria-invalid": !languageSupported,
          onChange: (event: ValueChangeEvent) => setBaseDraft((current) => ({
            ...current,
            language: event.target.value,
          })),
        },
        !languageSupported
          ? h("option", { value: baseDraft.language, disabled: true }, `旧值 ${baseDraft.language}（请重新选择）`)
          : null,
        h("option", { value: "zh-CN" }, "中文（简体）"),
        h("option", { value: "en" }, "英语"),
        h("option", { value: "ja-JP" }, "日语"),
        ),
      ),
      ...([
        ["read_chapter_title", "朗读章节标题"],
        ["read_author_notes", "朗读作者的话"],
        ["read_section_breaks", "朗读分隔内容"],
      ] as const).map(([key, label]) => h("label", {
        key,
        className: "anw-reading-preferences-panel__check",
      },
      h("input", {
        type: "checkbox",
        checked: baseDraft.textRules[key],
        onChange: (event: ValueChangeEvent) => setBaseDraft((current) => ({
          ...current,
          textRules: { ...current.textRules, [key]: event.target.checked },
        })),
      }),
      h("span", null, label),
      )),
      h("details", { className: "anw-reading-preferences-panel__advanced" },
        h("summary", null, "高级：叙述与内心独白声音"),
        h("div", null,
          h("label", null,
            h("span", null, "第一人称叙述"),
            h("select", {
              value: baseDraft.textRules.first_person_mode,
              onChange: (event: ValueChangeEvent) => setBaseDraft((current) => ({
                ...current,
                textRules: event.target.value === "character" && characters.length > 0
                  ? {
                    ...current.textRules,
                    first_person_mode: "character",
                    first_person_character_id: current.textRules.first_person_character_id
                      ?? characters[0]!.characterId,
                  }
                  : {
                    ...current.textRules,
                    first_person_mode: "narrator",
                    first_person_character_id: null,
                  },
              })),
            },
            h("option", { value: "narrator" }, "使用旁白"),
            h("option", { value: "character", disabled: characters.length === 0 }, "使用指定人物"),
            ),
          ),
          baseDraft.textRules.first_person_mode === "character"
            ? h("label", null,
              h("span", null, "第一人称人物"),
              h("select", {
                value: selectedFirstPersonCharacter ?? "",
                "aria-invalid": !firstPersonCharacterValid,
                onChange: (event: ValueChangeEvent) => setBaseDraft((current) => ({
                  ...current,
                  textRules: {
                    ...current.textRules,
                    first_person_character_id: event.target.value || null,
                  },
                })),
              },
              !firstPersonCharacterValid && selectedFirstPersonCharacter
                ? h("option", { value: selectedFirstPersonCharacter, disabled: true }, "旧人物已不可用（请重新选择）")
                : null,
              ...characters.map((character) => h("option", {
                key: character.characterId,
                value: character.characterId,
              }, character.label)),
              ),
            )
            : null,
          h("label", null,
            h("span", null, "内心独白"),
            h("select", {
              value: baseDraft.textRules.inner_monologue_mode,
              onChange: (event: ValueChangeEvent) => setBaseDraft((current) => ({
                ...current,
                textRules: {
                  ...current.textRules,
                  inner_monologue_mode: event.target.value === "narrator" ? "narrator" : "character",
                },
              })),
            },
            h("option", { value: "character" }, "使用人物声音"),
            h("option", { value: "narrator" }, "使用旁白"),
            ),
          ),
        ),
      ),
    ),
    h("fieldset", { disabled, className: "anw-reading-preferences-panel__pause-presets" },
      h("legend", null, "停顿节奏"),
      ...(["compact", "natural", "relaxed"] as const).map((preset) => h("label", {
        key: preset,
        className: pausePreset === preset ? "is-selected" : "",
      },
      h("input", {
        type: "radio",
        name: `${prefix}-pause-preset`,
        value: preset,
        checked: pausePreset === preset,
        onChange: () => setBaseDraft((current) => ({
          ...current,
          timing: READING_PAUSE_PRESETS[preset],
        })),
      }),
      h("span", null, PAUSE_LABELS[preset]),
      h("small", null, PAUSE_DESCRIPTIONS[preset]),
      )),
      pausePreset === "custom"
        ? h("p", { className: "anw-reading-preferences-panel__custom" }, "当前使用自定义毫秒值。")
        : null,
    ),
    h("details", { className: "anw-reading-preferences-panel__advanced" },
      h("summary", null, "高级：精确停顿毫秒"),
      h("p", null, "仅在预设不能满足时调整；保存后会显示为“自定义”。"),
      h("div", null,
        ...([
          ["sentence_gap_ms", "句间", 5_000],
          ["paragraph_gap_ms", "段间", 10_000],
          ["section_gap_ms", "分隔", 15_000],
        ] as const).map(([key, label, maximum]) => h("label", { key },
          h("span", null, `${label}（毫秒）`),
          h("input", {
            type: "number",
            min: 0,
            max: maximum,
            step: 10,
            value: baseDraft.timing[key],
            disabled,
            onChange: (event: ValueChangeEvent) => {
              const parsed = Number(event.target.value);
              if (!Number.isInteger(parsed) || parsed < 0 || parsed > maximum) return;
              setBaseDraft((current) => ({
                ...current,
                timing: { ...current.timing, [key]: parsed },
              }));
            },
          }),
        )),
      ),
    ),
    !languageSupported
      ? h("p", { className: "anw-reading-preferences-panel__error", role: "alert" },
        "当前旧语言值不在受控列表中；请选择中文、英语或日语后再保存。",
      )
      : null,
    !firstPersonCharacterValid
      ? h("p", { className: "anw-reading-preferences-panel__error", role: "alert" },
        "第一人称人物已不在当前作品中，请重新选择或改用旁白。",
      )
      : null,
    h("button", {
      type: "button",
      className: "anw-reading-preferences-panel__save",
      disabled: disabled || !baseDirty || !languageSupported || !firstPersonCharacterValid,
      onClick: saveBase,
    }, operation.kind === "base" ? "保存中…" : "保存基础朗读设置"),
    ),
    operationNode,
    );
  };
}
