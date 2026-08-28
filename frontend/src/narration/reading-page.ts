import type { QwenPawReactRuntime } from "../assistant-pane";
import {
  getNarrationOverview,
  listVoiceProfiles,
  listNarrationScopeOverrides,
  putNarrationScopeOverride,
  putNarrationSettings,
  NarrationApiError,
} from "./api";
import type {
  FeatureCapability,
  NarrationOverviewResponse,
  NarrationScopeKind,
  NarrationScopeOverrideListResponse,
  NarrationScopeOverrideResource,
  NarrationScopeOverrideValues,
  NarrationSettingsResource,
  NarrationSettingsValues,
  NarrationCapabilities,
  NarratorVoiceSelection,
  PutNarrationScopeOverrideRequest,
  UpdateNarrationSettingsRequest,
  VoiceProfileListResponse,
  VoiceProfileResource,
  VoiceSourceType,
} from "./contracts";
import { voiceSourceEvidenceIsUsable } from "./contracts";
import {
  capabilityFor,
  capabilityStatusText,
  createReadingOverview,
  isReadingSectionKey,
  READING_SECTIONS,
  type ReadingOverviewReactRuntime,
  type ReadingSectionKey,
} from "./reading-overview";


export const READING_WORKBENCH_SECTION = "reading" as const;
export const READING_PANEL_QUERY_KEY = "reading_panel" as const;


export type ReadingPageReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useState" | "useEffect" | "useRef"
>;


export interface ReadingPageApi {
  getOverview(novelId: string, signal?: AbortSignal): Promise<NarrationOverviewResponse>;
  listScopeOverrides(
    novelId: string,
    signal?: AbortSignal,
  ): Promise<NarrationScopeOverrideListResponse>;
  listVoiceProfiles?(
    novelId: string,
    signal?: AbortSignal,
  ): Promise<VoiceProfileListResponse>;
  putSettings(
    novelId: string,
    request: UpdateNarrationSettingsRequest,
    signal?: AbortSignal,
  ): Promise<NarrationSettingsResource>;
  putScopeOverride(
    novelId: string,
    scopeKind: NarrationScopeKind,
    scopeId: string,
    request: PutNarrationScopeOverrideRequest,
    signal?: AbortSignal,
  ): Promise<NarrationScopeOverrideResource>;
}


export interface ReadingScopeTarget {
  readonly novelId: string;
  readonly scopeKind: NarrationScopeKind;
  readonly scopeId: string;
  readonly label: string;
}


export interface ReadingNarratorOption {
  readonly novelId: string | null;
  readonly profileId: string;
  readonly versionId: string;
  readonly label: string;
  readonly locked: true;
  readonly rightsActive: true;
}


export interface ReadingCharacterOption {
  readonly novelId: string;
  readonly characterId: string;
  readonly label: string;
}


type ExternalReadingSection = Exclude<ReadingSectionKey, "overview" | "narrator">;


export interface ReadingSectionRenderContext {
  readonly overview: NarrationOverviewResponse;
  readonly onRefresh: () => void;
  readonly onNavigate: (section: ReadingSectionKey) => void;
}


export interface ReadingPageProps {
  readonly novelId: string;
  readonly novelTitle?: string;
  readonly initialSection?: ReadingSectionKey;
  readonly scopeTargets?: readonly ReadingScopeTarget[];
  readonly narratorOptions?: readonly ReadingNarratorOption[];
  readonly characterOptions?: readonly ReadingCharacterOption[];
  readonly sectionContent?: Readonly<Partial<Record<ExternalReadingSection, unknown>>>;
  readonly renderSectionContent?: (
    section: ExternalReadingSection,
    context: ReadingSectionRenderContext,
  ) => unknown;
  readonly renderNarratorVoiceWorkspace?: (
    context: ReadingSectionRenderContext,
  ) => unknown;
  readonly onSectionChange?: (section: ReadingSectionKey) => void;
}


interface NarratorSettingsPanelProps {
  readonly novelId: string;
  readonly resource: NarrationSettingsResource;
  readonly capability: FeatureCapability;
  readonly canConfigure: boolean;
  readonly saving: boolean;
  readonly narratorOptions: readonly ReadingNarratorOption[];
  readonly characterOptions: readonly ReadingCharacterOption[];
  readonly onSave: (values: NarrationSettingsValues) => void;
}


interface ScopeOverridesPanelProps {
  readonly novelId: string;
  readonly settings: NarrationSettingsResource;
  readonly capability: FeatureCapability;
  readonly canConfigure: boolean;
  readonly saving: boolean;
  readonly targets: readonly ReadingScopeTarget[];
  readonly overrides: readonly NarrationScopeOverrideResource[];
  readonly narratorOptions: readonly ReadingNarratorOption[];
  readonly characterOptions?: readonly ReadingCharacterOption[];
  readonly onSave: (
    target: ReadingScopeTarget,
    request: PutNarrationScopeOverrideRequest,
  ) => void;
}


type ReadingPageLoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | {
      readonly phase: "ready";
      readonly overview: NarrationOverviewResponse;
      readonly overrides: readonly NarrationScopeOverrideResource[];
      readonly voiceProfiles: readonly VoiceProfileResource[];
      readonly voiceProfilesError: string | null;
    };


interface OperationState {
  readonly saving: boolean;
  readonly message: string | null;
  readonly kind: "success" | "error" | null;
}


const EMPTY_OPERATION: OperationState = {
  saving: false,
  message: null,
  kind: null,
};


const DEFAULT_API: ReadingPageApi = {
  getOverview: getNarrationOverview,
  listScopeOverrides: listNarrationScopeOverrides,
  listVoiceProfiles: (novelId, signal) => listVoiceProfiles({
    novelId,
    includeLibrary: true,
    signal,
  }),
  putSettings: putNarrationSettings,
  putScopeOverride: putNarrationScopeOverride,
};


function scopeTargetKey(target: Pick<ReadingScopeTarget, "scopeKind" | "scopeId">): string {
  return `${target.scopeKind}:${target.scopeId}`;
}


function narratorSelectionKey(selection: NarratorVoiceSelection): string {
  return `${selection.profile_id}:${selection.version_id}`;
}


const LANGUAGE_TAG_PATTERN = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$/;


export function readingSectionFromSearch(search: string): ReadingSectionKey {
  const value = new URLSearchParams(search).get(READING_PANEL_QUERY_KEY);
  return isReadingSectionKey(value) ? value : "overview";
}


export function readingSectionSearch(
  search: string,
  section: ReadingSectionKey,
): string {
  const query = new URLSearchParams(search);
  query.set("section", READING_WORKBENCH_SECTION);
  if (section === "overview") query.delete(READING_PANEL_QUERY_KEY);
  else query.set(READING_PANEL_QUERY_KEY, section);
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}


export function scopeTargetsForNovel(
  novelId: string,
  targets: readonly ReadingScopeTarget[],
): readonly ReadingScopeTarget[] {
  const seen = new Set<string>();
  return targets.filter((target) => {
    const key = scopeTargetKey(target);
    if (target.novelId !== novelId || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


export function narratorOptionsForNovel(
  novelId: string,
  options: readonly ReadingNarratorOption[],
): readonly ReadingNarratorOption[] {
  const seen = new Set<string>();
  return options.filter((option) => {
    const key = narratorSelectionKey({
      profile_id: option.profileId,
      version_id: option.versionId,
    });
    if (
      option.locked !== true
      || option.rightsActive !== true
      || (option.novelId !== null && option.novelId !== novelId)
      || seen.has(key)
    ) return false;
    seen.add(key);
    return true;
  });
}


const NARRATOR_SOURCE_CAPABILITIES: Readonly<Record<VoiceSourceType, FeatureCapability["key"]>> = {
  preset: "preset_voice_source",
  uploaded: "reference_clone",
  generated: "voice_generator",
};


function narrationCapabilityActionable(
  capabilities: NarrationCapabilities,
  key: FeatureCapability["key"],
): boolean {
  const capability = capabilities.items.find((item) => item.key === key);
  if (!capability) throw new Error(`缺少朗读能力状态：${key}`);
  return capability.state === "enabled"
    && capability.visible
    && capability.actionable;
}


/**
 * Map only the current, production-eligible version of a scoped voice profile.
 * The server remains authoritative; this projection prevents stale or held
 * profiles from becoming selectable while the user is editing settings.
 */
export function narratorOptionsFromVoiceProfiles(
  novelId: string,
  profiles: readonly VoiceProfileResource[],
  capabilities: NarrationCapabilities,
): readonly ReadingNarratorOption[] {
  if (!narrationCapabilityActionable(capabilities, "narration_product")
    || !narrationCapabilityActionable(capabilities, "reading_settings")) return [];
  const options: ReadingNarratorOption[] = [];
  for (const profile of profiles) {
    if (profile.novel_id !== null && profile.novel_id !== novelId) continue;
    if (profile.status !== "active" || profile.current_version_id === null) continue;
    const version = profile.versions.find((item) => (
      item.version_id === profile.current_version_id
    ));
    if (!version
      || version.state !== "locked"
      || version.quality_state !== "accepted"
      || version.rights.state !== "active"
      || !voiceSourceEvidenceIsUsable(version)) continue;
    if (!narrationCapabilityActionable(
      capabilities,
      NARRATOR_SOURCE_CAPABILITIES[version.source_type],
    )) continue;
    options.push({
      novelId: profile.novel_id,
      profileId: profile.profile_id,
      versionId: version.version_id,
      label: `${profile.name} · v${version.version_number}`,
      locked: true,
      rightsActive: true,
    });
  }
  return [...narratorOptionsForNovel(novelId, options)].sort((left, right) => (
    left.label.localeCompare(right.label, "zh-CN")
      || left.profileId.localeCompare(right.profileId)
      || left.versionId.localeCompare(right.versionId)
  ));
}


export function characterOptionsForNovel(
  novelId: string,
  options: readonly ReadingCharacterOption[],
): readonly ReadingCharacterOption[] {
  const seen = new Set<string>();
  return options.filter((option) => {
    if (option.novelId !== novelId || seen.has(option.characterId)) return false;
    seen.add(option.characterId);
    return true;
  });
}


export function buildNarrationSettingsReplacement(
  resource: NarrationSettingsResource,
  values: NarrationSettingsValues,
): UpdateNarrationSettingsRequest {
  return {
    expected_version: resource.version,
    values,
  };
}


export function emptyScopeOverrideValues(): NarrationScopeOverrideValues {
  return {
    narrator: null,
    language: null,
    text_rules: null,
    timing: null,
  };
}


export function scopeOverrideForTarget(
  target: ReadingScopeTarget,
  overrides: readonly NarrationScopeOverrideResource[],
): NarrationScopeOverrideResource | undefined {
  return overrides.find((override) => (
    override.novel_id === target.novelId
    && override.scope_kind === target.scopeKind
    && override.scope_id === target.scopeId
  ));
}


export function buildScopeOverrideReplacement(
  novelId: string,
  target: ReadingScopeTarget,
  current: NarrationScopeOverrideResource | undefined,
  enabled: boolean,
  overrides: NarrationScopeOverrideValues,
): PutNarrationScopeOverrideRequest {
  if (target.novelId !== novelId) {
    throw new Error("范围覆盖目标不属于当前作品");
  }
  if (current && (
    current.novel_id !== novelId
    || current.scope_kind !== target.scopeKind
    || current.scope_id !== target.scopeId
  )) {
    throw new Error("范围覆盖版本与目标不匹配");
  }
  return {
    expected_version: current?.version ?? 0,
    enabled,
    overrides: enabled ? overrides : emptyScopeOverrideValues(),
  };
}


export function replaceScopeOverride(
  novelId: string,
  target: ReadingScopeTarget,
  current: readonly NarrationScopeOverrideResource[],
  saved: NarrationScopeOverrideResource,
): readonly NarrationScopeOverrideResource[] {
  if (
    target.novelId !== novelId
    || saved.novel_id !== novelId
    || saved.scope_kind !== target.scopeKind
    || saved.scope_id !== target.scopeId
  ) {
    throw new Error("服务端返回了其他作品或范围的覆盖配置");
  }
  const key = scopeTargetKey(target);
  return [
    ...current.filter((item) => `${item.scope_kind}:${item.scope_id}` !== key),
    saved,
  ];
}


function mutationBlockReason(
  capability: FeatureCapability,
  canConfigure: boolean,
): string | null {
  if (!capability.actionable) return capabilityStatusText(capability);
  if (!canConfigure) return "当前作品授权不允许修改朗读配置（AUTHORIZATION_READ_ONLY）";
  return null;
}


function readNumber(value: string, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}


function isEmptyScopeValues(values: NarrationScopeOverrideValues): boolean {
  return values.narrator === null
    && values.language === null
    && values.text_rules === null
    && values.timing === null;
}


function isLanguageTag(value: string): boolean {
  return LANGUAGE_TAG_PATTERN.test(value);
}


function apiErrorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof NarrationApiError) {
    if (reason.detail.code === "VERSION_CONFLICT") {
      return "配置已在其他位置更新，请刷新后再保存（VERSION_CONFLICT）";
    }
    return `${reason.detail.message}（${reason.detail.code}）`;
  }
  return fallback;
}


interface ReadingNarratorChoice {
  readonly profileId: string;
  readonly versionId: string;
  readonly label: string;
  readonly verified: boolean;
}


interface ReadingCharacterChoice extends ReadingCharacterOption {
  readonly verified: boolean;
}


function currentNarratorOptions(
  selection: NarratorVoiceSelection | null,
  options: readonly ReadingNarratorOption[],
): readonly ReadingNarratorChoice[] {
  const verified = options.map((option) => ({
    profileId: option.profileId,
    versionId: option.versionId,
    label: option.label,
    verified: true,
  }));
  if (selection === null) return verified;
  const key = narratorSelectionKey(selection);
  if (verified.some((option) => narratorSelectionKey({
    profile_id: option.profileId,
    version_id: option.versionId,
  }) === key)) return verified;
  return [
    ...verified,
    {
      profileId: selection.profile_id,
      versionId: selection.version_id,
      label: "当前旁白（资格待重新核验）",
      verified: false,
    },
  ];
}


function currentCharacterOptions(
  novelId: string,
  characterId: string | null,
  options: readonly ReadingCharacterOption[],
): readonly ReadingCharacterChoice[] {
  const verified = options.map((option) => ({ ...option, verified: true }));
  if (characterId === null || verified.some((option) => option.characterId === characterId)) {
    return verified;
  }
  return [
    ...verified,
    { novelId, characterId, label: "当前指定人物（资格待重新核验）", verified: false },
  ];
}


export function narrationSettingsValuesEqual(
  left: NarrationSettingsValues,
  right: NarrationSettingsValues,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}


export function scopeOverrideValuesEqual(
  left: NarrationScopeOverrideValues,
  right: NarrationScopeOverrideValues,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}


export function createNarratorSettingsPanel(
  React: ReadingPageReactRuntime,
): (props: NarratorSettingsPanelProps) => unknown {
  const h = React.createElement;

  return function NarratorSettingsPanel(props) {
    const [draft, setDraft] = React.useState<NarrationSettingsValues>(props.resource.values);
    React.useEffect(() => {
      setDraft(props.resource.values);
    }, [props.novelId, props.resource.settings_id, props.resource.version, props.resource.updated_at]);

    const blockedReason = mutationBlockReason(props.capability, props.canConfigure);
    const disabled = blockedReason !== null || props.saving;
    const narratorOptions = currentNarratorOptions(
      draft.narrator,
      narratorOptionsForNovel(props.novelId, props.narratorOptions),
    );
    const characters = currentCharacterOptions(
      props.novelId,
      draft.text_rules.first_person_character_id,
      characterOptionsForNovel(props.novelId, props.characterOptions),
    );
    const narratorValue = draft.narrator === null ? "" : narratorSelectionKey(draft.narrator);
    const invalidLanguage = !isLanguageTag(draft.language);
    const narratorVerified = draft.narrator === null || narratorOptions.some((option) => (
      option.verified
      && narratorSelectionKey({
        profile_id: option.profileId,
        version_id: option.versionId,
      }) === narratorValue
    ));
    const characterVerified = draft.text_rules.first_person_mode === "narrator"
      || characters.some((character) => (
        character.verified
        && character.characterId === draft.text_rules.first_person_character_id
      ));
    const dirty = !narrationSettingsValuesEqual(draft, props.resource.values);

    const selectNarrator = (value: string) => {
      const selected = narratorOptions.find((option) => narratorSelectionKey({
        profile_id: option.profileId,
        version_id: option.versionId,
      }) === value);
      setDraft((current) => ({
        ...current,
        narrator: selected
          ? { profile_id: selected.profileId, version_id: selected.versionId }
          : null,
      }));
    };

    return h(
      "section",
      {
        className: "anw-reading-narrator-panel",
        role: "region",
        "aria-labelledby": "anw-reading-narrator-heading",
        "data-reading-panel": "narrator",
      },
      h(
        "header",
        { className: "anw-reading-section-heading" },
        h("div", null,
          h("h2", { id: "anw-reading-narrator-heading" }, "作品旁白"),
          h("p", null, "旁白只引用当前作品内已锁定且质量已接受的中文官方预设版本；播放倍速和音量不会触发重新合成。"),
        ),
        h("span", { className: "anw-reading-version" }, `设置版本 ${props.resource.version}`),
      ),
      blockedReason
        ? h(
          "div",
          {
            className: "anw-reading-gate-notice",
            role: "status",
            "data-reason-code": props.capability.reason_code ?? undefined,
          },
          h("strong", null, "配置已锁定"),
          h("span", null, blockedReason),
        )
        : null,
      h(
        "fieldset",
        { disabled, className: "anw-reading-form-grid" },
        h("legend", null, "默认旁白和语言"),
        h(
          "label",
          null,
          h("span", null, "旁白音色"),
          h(
            "select",
            {
              value: narratorValue,
              onChange: (event: { target: { value: string } }) => selectNarrator(event.target.value),
            },
            h("option", { value: "" }, narratorOptions.length === 0 ? "没有可用的锁定音色" : "未配置"),
            ...narratorOptions.map((option) => h(
              "option",
              {
                key: narratorSelectionKey({ profile_id: option.profileId, version_id: option.versionId }),
                value: narratorSelectionKey({ profile_id: option.profileId, version_id: option.versionId }),
                disabled: !option.verified,
              },
              option.label,
            )),
          ),
        ),
        h(
          "label",
          null,
          h("span", null, "语言"),
          h("input", {
            type: "text",
            value: draft.language,
            maxLength: 24,
            inputMode: "text",
            onChange: (event: { target: { value: string } }) => setDraft((current) => ({
              ...current,
              language: event.target.value,
            })),
          }),
        ),
        h(
          "div",
          { className: "anw-reading-readonly-field" },
          h("span", null, "输出格式"),
          h("strong", null, "M4A · AAC-LC"),
          h("small", null, "首版固定格式"),
        ),
      ),
      h(
        "fieldset",
        { disabled, className: "anw-reading-form-grid" },
        h("legend", null, "正文朗读方式"),
        ...([
          ["read_chapter_title", "朗读章节标题"],
          ["read_author_notes", "朗读作者的话"],
          ["read_section_breaks", "朗读分隔内容"],
        ] as const).map(([key, label]) => h(
          "label",
          { key, className: "anw-reading-check" },
          h("input", {
            type: "checkbox",
            checked: draft.text_rules[key],
            onChange: (event: { target: { checked: boolean } }) => setDraft((current) => ({
              ...current,
              text_rules: { ...current.text_rules, [key]: event.target.checked },
            })),
          }),
          h("span", null, label),
        )),
        h(
          "label",
          null,
          h("span", null, "第一人称叙述"),
          h(
            "select",
            {
              value: draft.text_rules.first_person_mode,
              onChange: (event: { target: { value: string } }) => setDraft((current) => ({
                ...current,
                text_rules: event.target.value === "character" && characters.length > 0
                  ? {
                    ...current.text_rules,
                    first_person_mode: "character",
                    first_person_character_id: current.text_rules.first_person_character_id ?? characters[0].characterId,
                  }
                  : {
                    ...current.text_rules,
                    first_person_mode: "narrator",
                    first_person_character_id: null,
                  },
              })),
            },
            h("option", { value: "narrator" }, "使用旁白"),
            h("option", { value: "character", disabled: characters.length === 0 }, "使用指定人物"),
          ),
        ),
        draft.text_rules.first_person_mode === "character"
          ? h(
            "label",
            null,
            h("span", null, "第一人称人物"),
            h(
              "select",
              {
                value: draft.text_rules.first_person_character_id ?? "",
                onChange: (event: { target: { value: string } }) => setDraft((current) => ({
                  ...current,
                  text_rules: {
                    ...current.text_rules,
                    first_person_character_id: event.target.value || null,
                  },
                })),
              },
              ...characters.map((character) => h(
                "option",
                {
                  key: character.characterId,
                  value: character.characterId,
                  disabled: !character.verified,
                },
                character.label,
              )),
            ),
          )
          : null,
        h(
          "label",
          null,
          h("span", null, "内心独白"),
          h(
            "select",
            {
              value: draft.text_rules.inner_monologue_mode,
              onChange: (event: { target: { value: string } }) => setDraft((current) => ({
                ...current,
                text_rules: {
                  ...current.text_rules,
                  inner_monologue_mode: event.target.value === "narrator" ? "narrator" : "character",
                },
              })),
            },
            h("option", { value: "character" }, "使用人物声音"),
            h("option", { value: "narrator" }, "使用旁白"),
          ),
        ),
      ),
      h(
        "fieldset",
        { disabled, className: "anw-reading-form-grid" },
        h("legend", null, "停顿与播放偏好"),
        ...([
          ["sentence_gap_ms", "句间停顿", 5_000],
          ["paragraph_gap_ms", "段间停顿", 10_000],
          ["section_gap_ms", "分隔停顿", 15_000],
        ] as const).map(([key, label, maximum]) => h(
          "label",
          { key },
          h("span", null, `${label}（毫秒）`),
          h("input", {
            type: "number",
            min: 0,
            max: maximum,
            step: 50,
            value: draft.timing[key],
            onChange: (event: { target: { value: string } }) => setDraft((current) => ({
              ...current,
              timing: {
                ...current.timing,
                [key]: Math.round(readNumber(event.target.value, current.timing[key], 0, maximum)),
              },
            })),
          }),
        )),
        h(
          "label",
          null,
          h("span", null, `播放倍速 ${draft.playback.playback_rate.toFixed(2)}×`),
          h("input", {
            type: "range",
            min: 0.5,
            max: 3,
            step: 0.05,
            value: draft.playback.playback_rate,
            onChange: (event: { target: { value: string } }) => setDraft((current) => ({
              ...current,
              playback: {
                ...current.playback,
                playback_rate: readNumber(event.target.value, current.playback.playback_rate, 0.5, 3),
              },
            })),
          }),
        ),
        h(
          "label",
          null,
          h("span", null, `播放器音量 ${Math.round(draft.playback.volume * 100)}%`),
          h("input", {
            type: "range",
            min: 0,
            max: 1,
            step: 0.01,
            value: draft.playback.volume,
            onChange: (event: { target: { value: string } }) => setDraft((current) => ({
              ...current,
              playback: {
                ...current.playback,
                volume: readNumber(event.target.value, current.playback.volume, 0, 1),
              },
            })),
          }),
        ),
      ),
      h(
        "div",
        { className: "anw-reading-form-actions" },
        invalidLanguage
          ? h("p", { className: "anw-reading-field-error", role: "alert" }, "语言必须使用受支持的 BCP 47 短标签，例如 zh-CN。")
          : null,
        !narratorVerified
          ? h("p", { className: "anw-reading-field-error", role: "alert" }, "当前旁白的来源身份、本地可用、锁定或质量状态尚未重新核验，请重新选择或清空。")
          : null,
        !characterVerified
          ? h("p", { className: "anw-reading-field-error", role: "alert" }, "第一人称指定人物不在当前作品的可核验列表中。")
          : null,
        h(
          "button",
          {
            type: "button",
            disabled: disabled
              || invalidLanguage
              || !narratorVerified
              || !characterVerified
              || !dirty,
            title: blockedReason ?? undefined,
            onClick: () => {
              if (
                disabled
                || invalidLanguage
                || !narratorVerified
                || !characterVerified
                || !dirty
              ) return;
              props.onSave(draft);
            },
          },
          props.saving ? "正在保存…" : "保存作品旁白",
        ),
      ),
    );
  };
}


export function createScopeOverridesPanel(
  React: ReadingPageReactRuntime,
): (props: ScopeOverridesPanelProps) => unknown {
  const h = React.createElement;

  return function ScopeOverridesPanel(props) {
    const targets = scopeTargetsForNovel(props.novelId, props.targets);
    const firstKey = targets[0] ? scopeTargetKey(targets[0]) : "";
    const [selectedKey, setSelectedKey] = React.useState(firstKey);
    const selected = targets.find((target) => scopeTargetKey(target) === selectedKey) ?? targets[0];
    const current = selected ? scopeOverrideForTarget(selected, props.overrides) : undefined;
    const [enabled, setEnabled] = React.useState(current?.enabled ?? false);
    const [draft, setDraft] = React.useState<NarrationScopeOverrideValues>(
      current?.overrides ?? emptyScopeOverrideValues(),
    );
    const [draftScopeKey, setDraftScopeKey] = React.useState(firstKey);

    const selectedIdentity = selected ? scopeTargetKey(selected) : "";
    React.useEffect(() => {
      if (!selected) {
        setDraftScopeKey("");
        return;
      }
      const active = scopeOverrideForTarget(selected, props.overrides);
      setEnabled(active?.enabled ?? false);
      setDraft(active?.overrides ?? emptyScopeOverrideValues());
      setDraftScopeKey(selectedIdentity);
    }, [props.novelId, selectedIdentity, current?.version]);

    const blockedReason = mutationBlockReason(props.capability, props.canConfigure);
    const narratorOptions = currentNarratorOptions(
      draft.narrator,
      narratorOptionsForNovel(props.novelId, props.narratorOptions),
    );
    const characters = currentCharacterOptions(
      props.novelId,
      draft.text_rules?.first_person_character_id ?? null,
      characterOptionsForNovel(props.novelId, props.characterOptions ?? []),
    );
    const narratorValue = draft.narrator === null ? "" : narratorSelectionKey(draft.narrator);
    const scopeChanging = draftScopeKey !== selectedIdentity;
    const invalidEnabled = enabled && isEmptyScopeValues(draft);
    const invalidLanguage = enabled && draft.language !== null && !isLanguageTag(draft.language);
    const narratorVerified = !enabled || draft.narrator === null || narratorOptions.some((option) => (
      option.verified
      && narratorSelectionKey({
        profile_id: option.profileId,
        version_id: option.versionId,
      }) === narratorValue
    ));
    const characterVerified = !enabled
      || draft.text_rules === null
      || draft.text_rules.first_person_mode === "narrator"
      || characters.some((character) => (
        character.verified
        && character.characterId === draft.text_rules?.first_person_character_id
      ));
    const baselineEnabled = current?.enabled ?? false;
    const baselineValues = current?.overrides ?? emptyScopeOverrideValues();
    const dirty = enabled !== baselineEnabled
      || !scopeOverrideValuesEqual(draft, baselineValues);
    const disabled = blockedReason !== null || props.saving || scopeChanging;
    const saveDisabled = disabled
      || invalidEnabled
      || invalidLanguage
      || !narratorVerified
      || !characterVerified
      || !dirty;

    if (!selected) {
      return h(
        "section",
        {
          className: "anw-reading-scope-panel is-empty",
          role: "region",
          "aria-labelledby": "anw-reading-scope-heading",
          "data-reading-state": "empty",
        },
        h("h2", { id: "anw-reading-scope-heading" }, "分卷与章节覆盖"),
        h("p", null, "当前作品没有可配置的分卷或章节。新增分卷或章节后可在这里设置局部旁白。"),
      );
    }

    return h(
      "section",
      {
        className: "anw-reading-scope-panel",
        role: "region",
        "aria-labelledby": "anw-reading-scope-heading",
        "data-reading-panel": "scope-overrides",
      },
      h(
        "header",
        { className: "anw-reading-section-heading" },
        h("div", null,
          h("h2", { id: "anw-reading-scope-heading" }, "分卷与章节覆盖"),
          h("p", null, "解析顺序固定为章节 > 分卷 > 作品；关闭覆盖会完整清空这个范围的覆盖值。"),
        ),
        h("span", { className: "anw-reading-version" }, `覆盖版本 ${current?.version ?? 0}`),
      ),
      h(
        "fieldset",
        { disabled, className: "anw-reading-form-grid" },
        h("legend", null, "选择范围"),
        h(
          "label",
          null,
          h("span", null, "分卷或章节"),
          h(
            "select",
            {
              value: scopeTargetKey(selected),
              onChange: (event: { target: { value: string } }) => setSelectedKey(event.target.value),
            },
            ...targets.map((target) => h(
              "option",
              { key: scopeTargetKey(target), value: scopeTargetKey(target) },
              `${target.scopeKind === "volume" ? "分卷" : "章节"} · ${target.label}`,
            )),
          ),
        ),
        h(
          "label",
          { className: "anw-reading-check" },
          h("input", {
            type: "checkbox",
            checked: enabled,
            onChange: (event: { target: { checked: boolean } }) => setEnabled(event.target.checked),
          }),
          h("span", null, "启用这个范围的朗读覆盖"),
        ),
      ),
      enabled
        ? h(
          "fieldset",
          { disabled, className: "anw-reading-form-grid" },
          h("legend", null, "完整覆盖值"),
          h(
            "label",
            null,
            h("span", null, "旁白音色（留空则不覆盖）"),
            h(
              "select",
              {
                value: narratorValue,
                onChange: (event: { target: { value: string } }) => {
                  const option = narratorOptions.find((candidate) => narratorSelectionKey({
                    profile_id: candidate.profileId,
                    version_id: candidate.versionId,
                  }) === event.target.value);
                  setDraft((value) => ({
                    ...value,
                    narrator: option
                      ? { profile_id: option.profileId, version_id: option.versionId }
                      : null,
                  }));
                },
              },
              h("option", { value: "" }, "继承作品旁白"),
              ...narratorOptions.map((option) => h(
                "option",
                {
                  key: narratorSelectionKey({ profile_id: option.profileId, version_id: option.versionId }),
                  value: narratorSelectionKey({ profile_id: option.profileId, version_id: option.versionId }),
                  disabled: !option.verified,
                },
                option.label,
              )),
            ),
          ),
          h(
            "label",
            null,
            h("span", null, "语言（留空则继承）"),
            h("input", {
              type: "text",
              maxLength: 24,
              value: draft.language ?? "",
              placeholder: props.settings.values.language,
              onChange: (event: { target: { value: string } }) => setDraft((value) => ({
                ...value,
                language: event.target.value.trim() || null,
              })),
            }),
          ),
          h(
            "label",
            { className: "anw-reading-check" },
            h("input", {
              type: "checkbox",
              checked: draft.text_rules !== null,
              onChange: (event: { target: { checked: boolean } }) => setDraft((value) => ({
                ...value,
                text_rules: event.target.checked ? props.settings.values.text_rules : null,
              })),
            }),
            h("span", null, "覆盖正文朗读规则（初始复制作品当前值）"),
          ),
          draft.text_rules
            ? h(
              "div",
              { className: "anw-reading-scope-rules" },
              ...([
                ["read_chapter_title", "朗读章节标题"],
                ["read_author_notes", "朗读作者的话"],
                ["read_section_breaks", "朗读分隔内容"],
              ] as const).map(([key, label]) => h(
                "label",
                { key, className: "anw-reading-check" },
                h("input", {
                  type: "checkbox",
                  checked: draft.text_rules?.[key] ?? false,
                  onChange: (event: { target: { checked: boolean } }) => setDraft((value) => ({
                    ...value,
                    text_rules: value.text_rules
                      ? { ...value.text_rules, [key]: event.target.checked }
                      : null,
                  })),
                }),
                h("span", null, label),
              )),
              h(
                "label",
                null,
                h("span", null, "第一人称叙述"),
                h(
                  "select",
                  {
                    value: draft.text_rules.first_person_mode,
                    onChange: (event: { target: { value: string } }) => setDraft((value) => ({
                      ...value,
                      text_rules: value.text_rules === null
                        ? null
                        : event.target.value === "character" && characters.some((item) => item.verified)
                          ? {
                            ...value.text_rules,
                            first_person_mode: "character",
                            first_person_character_id:
                              characters.find((item) => item.verified)?.characterId ?? null,
                          }
                          : {
                            ...value.text_rules,
                            first_person_mode: "narrator",
                            first_person_character_id: null,
                          },
                    })),
                  },
                  h("option", { value: "narrator" }, "使用旁白"),
                  h(
                    "option",
                    { value: "character", disabled: !characters.some((item) => item.verified) },
                    "使用指定人物",
                  ),
                ),
              ),
              draft.text_rules.first_person_mode === "character"
                ? h(
                  "label",
                  null,
                  h("span", null, "第一人称人物"),
                  h(
                    "select",
                    {
                      value: draft.text_rules.first_person_character_id ?? "",
                      onChange: (event: { target: { value: string } }) => setDraft((value) => ({
                        ...value,
                        text_rules: value.text_rules
                          ? {
                            ...value.text_rules,
                            first_person_character_id: event.target.value || null,
                          }
                          : null,
                      })),
                    },
                    ...characters.map((character) => h(
                      "option",
                      {
                        key: character.characterId,
                        value: character.characterId,
                        disabled: !character.verified,
                      },
                      character.label,
                    )),
                  ),
                )
                : null,
              h(
                "label",
                null,
                h("span", null, "内心独白"),
                h(
                  "select",
                  {
                    value: draft.text_rules.inner_monologue_mode,
                    onChange: (event: { target: { value: string } }) => setDraft((value) => ({
                      ...value,
                      text_rules: value.text_rules
                        ? {
                          ...value.text_rules,
                          inner_monologue_mode:
                            event.target.value === "narrator" ? "narrator" : "character",
                        }
                        : null,
                    })),
                  },
                  h("option", { value: "character" }, "使用人物声音"),
                  h("option", { value: "narrator" }, "使用旁白"),
                ),
              ),
            )
            : null,
          h(
            "label",
            { className: "anw-reading-check" },
            h("input", {
              type: "checkbox",
              checked: draft.timing !== null,
              onChange: (event: { target: { checked: boolean } }) => setDraft((value) => ({
                ...value,
                timing: event.target.checked ? props.settings.values.timing : null,
              })),
            }),
            h("span", null, "覆盖停顿参数（初始复制作品当前值）"),
          ),
          draft.timing
            ? h(
              "div",
              { className: "anw-reading-inline-fields" },
              ...([
                ["sentence_gap_ms", "句间", 5_000],
                ["paragraph_gap_ms", "段间", 10_000],
                ["section_gap_ms", "分隔", 15_000],
              ] as const).map(([key, label, maximum]) => h(
                "label",
                { key },
                h("span", null, `${label} ms`),
                h("input", {
                  type: "number",
                  min: 0,
                  max: maximum,
                  step: 50,
                  value: draft.timing?.[key] ?? 0,
                  onChange: (event: { target: { value: string } }) => setDraft((value) => ({
                    ...value,
                    timing: value.timing
                      ? {
                        ...value.timing,
                        [key]: Math.round(readNumber(event.target.value, value.timing[key], 0, maximum)),
                      }
                      : null,
                  })),
                }),
              )),
            )
            : null,
        )
        : null,
      invalidEnabled
        ? h("p", { className: "anw-reading-field-error", role: "alert" }, "启用覆盖前，至少选择一项旁白、语言、正文规则或停顿参数。")
        : null,
      invalidLanguage
        ? h("p", { className: "anw-reading-field-error", role: "alert" }, "范围语言必须使用受支持的 BCP 47 短标签，例如 zh-CN。")
        : null,
      !narratorVerified
        ? h("p", { className: "anw-reading-field-error", role: "alert" }, "该范围的旁白资格尚未重新核验，请重新选择或改为继承作品旁白。")
        : null,
      !characterVerified
        ? h("p", { className: "anw-reading-field-error", role: "alert" }, "该范围的第一人称人物不在当前作品可核验列表中。")
        : null,
      blockedReason
        ? h(
          "p",
          { className: "anw-reading-gate-inline", "data-reason-code": props.capability.reason_code ?? undefined },
          blockedReason,
        )
        : null,
      h(
        "div",
        { className: "anw-reading-form-actions" },
        h(
          "button",
          {
            type: "button",
            disabled: saveDisabled,
            title: blockedReason ?? undefined,
            onClick: () => {
              if (saveDisabled) return;
              props.onSave(
                selected,
                buildScopeOverrideReplacement(
                  props.novelId,
                  selected,
                  current,
                  enabled,
                  draft,
                ),
              );
            },
          },
          props.saving ? "正在保存…" : enabled ? "保存范围覆盖" : "关闭并清空覆盖",
        ),
      ),
    );
  };
}


export function createReadingPage(
  React: ReadingPageReactRuntime,
  api: ReadingPageApi = DEFAULT_API,
): (props: ReadingPageProps) => unknown {
  const h = React.createElement;
  const ReadingOverview = createReadingOverview(React as ReadingOverviewReactRuntime);
  const NarratorSettingsPanel = createNarratorSettingsPanel(React);
  const ScopeOverridesPanel = createScopeOverridesPanel(React);

  return function ReadingPage(props) {
    const [activeSection, setActiveSection] = React.useState<ReadingSectionKey>(
      props.initialSection ?? "overview",
    );
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [loadState, setLoadState] = React.useState<ReadingPageLoadState>({ phase: "loading" });
    const [operation, setOperation] = React.useState<OperationState>(EMPTY_OPERATION);
    const currentNovelRef = React.useRef(props.novelId);
    const mutationAbortRef = React.useRef<AbortController | null>(null);
    currentNovelRef.current = props.novelId;

    React.useEffect(() => {
      setActiveSection(props.initialSection ?? "overview");
    }, [props.novelId, props.initialSection]);

    React.useEffect(() => {
      const controller = new AbortController();
      setLoadState({ phase: "loading" });
      setOperation(EMPTY_OPERATION);
      const profilesRequest = api.listVoiceProfiles
        ? api.listVoiceProfiles(props.novelId, controller.signal)
          .then((response) => ({ response, error: null as string | null }))
          .catch((reason: unknown) => ({
            response: null,
            error: apiErrorMessage(reason, "无法核验旁白音色，已保持音色选项为空。"),
          }))
        : Promise.resolve({ response: null, error: null as string | null });
      void Promise.all([
        api.getOverview(props.novelId, controller.signal),
        api.listScopeOverrides(props.novelId, controller.signal),
        profilesRequest,
      ]).then(([overview, overrides, profilesResult]) => {
        if (controller.signal.aborted) return;
        if (overview.novel_id !== props.novelId || overrides.novel_id !== props.novelId) {
          setLoadState({ phase: "error", message: "服务端返回了其他作品的朗读配置，已阻止显示。" });
          return;
        }
        const voiceProfiles = profilesResult.response?.items ?? [];
        if (voiceProfiles.some((profile) => (
          profile.novel_id !== null && profile.novel_id !== props.novelId
        ))) {
          setLoadState({ phase: "error", message: "服务端返回了其他作品的旁白音色，已阻止显示。" });
          return;
        }
        setLoadState({
          phase: "ready",
          overview,
          overrides: overrides.items,
          voiceProfiles,
          voiceProfilesError: profilesResult.error,
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setLoadState({
          phase: "error",
          message: apiErrorMessage(reason, "无法加载朗读设置，请稍后重试。"),
        });
      });
      return () => controller.abort();
    }, [props.novelId, reloadVersion]);

    React.useEffect(() => () => {
      mutationAbortRef.current?.abort();
      mutationAbortRef.current = null;
    }, [props.novelId]);

    const reload = () => setReloadVersion((version) => version + 1);
    const navigate = (section: ReadingSectionKey) => {
      setActiveSection(section);
      props.onSectionChange?.(section);
    };

    if (loadState.phase === "loading") {
      return h(
        "main",
        {
          className: "anw-reading-page is-loading",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h(ReadingOverview, { state: { phase: "loading" } }),
      );
    }

    if (loadState.phase === "error") {
      return h(
        "main",
        {
          className: "anw-reading-page is-error",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h(ReadingOverview, {
          state: { phase: "error", message: loadState.message, onRetry: reload },
        }),
      );
    }

    if (loadState.overview.novel_id !== props.novelId) {
      return h(
        "main",
        {
          className: "anw-reading-page is-loading",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h(ReadingOverview, { state: { phase: "loading" } }),
      );
    }

    const overview = loadState.overview;
    const productCapability = capabilityFor(overview, "narration_product");
    if (!overview.authorization.can_read || !productCapability.visible) {
      return h(
        "main",
        {
          className: "anw-reading-page is-unavailable",
          role: "alert",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h("h1", null, "朗读设置不可见"),
        h("p", null, !overview.authorization.can_read
          ? "当前作品授权不允许读取朗读配置。"
          : capabilityStatusText(productCapability)),
      );
    }

    const settingsCapability = capabilityFor(overview, "reading_settings");
    const configurationCapability = productCapability.actionable
      ? settingsCapability
      : productCapability;
    const chapterPlaybackReady = [
      "narration_synthesis",
      "product_player",
      "editor_production",
    ].every((key) => narrationCapabilityActionable(
      overview.capabilities,
      key as FeatureCapability["key"],
    ));
    const narratorOptions = narratorOptionsForNovel(props.novelId, [
      ...(props.narratorOptions ?? []),
      ...narratorOptionsFromVoiceProfiles(
        props.novelId,
        loadState.voiceProfiles,
        overview.capabilities,
      ),
    ]);
    const saveSettings = (values: NarrationSettingsValues) => {
      if (mutationBlockReason(configurationCapability, overview.authorization.can_configure)) return;
      mutationAbortRef.current?.abort();
      const controller = new AbortController();
      mutationAbortRef.current = controller;
      setOperation({ saving: true, message: null, kind: null });
      void api.putSettings(
        props.novelId,
        buildNarrationSettingsReplacement(overview.settings, values),
        controller.signal,
      ).then((saved) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        if (saved.novel_id !== props.novelId) {
          throw new Error("settings scope mismatch");
        }
        setLoadState((current) => current.phase === "ready"
          && current.overview.novel_id === props.novelId
          ? { ...current, overview: { ...current.overview, settings: saved } }
          : current);
        setOperation({ saving: false, message: "作品旁白设置已保存。", kind: "success" });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        setOperation({
          saving: false,
          message: apiErrorMessage(reason, "保存作品旁白失败，请刷新后重试。"),
          kind: "error",
        });
      });
    };
    const saveScopeOverride = (
      target: ReadingScopeTarget,
      request: PutNarrationScopeOverrideRequest,
    ) => {
      if (mutationBlockReason(configurationCapability, overview.authorization.can_configure)) return;
      mutationAbortRef.current?.abort();
      const controller = new AbortController();
      mutationAbortRef.current = controller;
      setOperation({ saving: true, message: null, kind: null });
      void api.putScopeOverride(
        props.novelId,
        target.scopeKind,
        target.scopeId,
        request,
        controller.signal,
      ).then((saved) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        const nextOverrides = replaceScopeOverride(
          props.novelId,
          target,
          loadState.overrides,
          saved,
        );
        setLoadState((current) => current.phase === "ready"
          && current.overview.novel_id === props.novelId
          ? {
            ...current,
            overrides: nextOverrides,
          }
          : current);
        setOperation({ saving: false, message: "范围覆盖已保存。", kind: "success" });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        setOperation({
          saving: false,
          message: apiErrorMessage(reason, "保存范围覆盖失败，请刷新后重试。"),
          kind: "error",
        });
      });
    };

    const externalContent = activeSection !== "overview" && activeSection !== "narrator"
      ? props.renderSectionContent?.(
        activeSection,
        { overview, onRefresh: reload, onNavigate: navigate },
      ) ?? props.sectionContent?.[activeSection]
      : undefined;
    const sectionBody = activeSection === "overview"
      ? h(ReadingOverview, {
        state: {
          phase: "ready",
          overview,
          onRetry: reload,
          onNavigate: navigate,
        },
      })
      : activeSection === "narrator"
        ? h(
          "div",
          { className: "anw-reading-narrator-stack" },
          loadState.voiceProfilesError
            ? h(
                "p",
                { className: "anw-reading-inline-error", role: "alert" },
                loadState.voiceProfilesError,
              )
            : null,
          h(NarratorSettingsPanel, {
            novelId: props.novelId,
            resource: overview.settings,
            capability: configurationCapability,
            canConfigure: overview.authorization.can_configure,
            saving: operation.saving,
            narratorOptions,
            characterOptions: props.characterOptions ?? [],
            onSave: saveSettings,
          }),
          props.renderNarratorVoiceWorkspace?.({
            overview,
            onRefresh: reload,
            onNavigate: navigate,
          }) ?? null,
          h(ScopeOverridesPanel, {
            novelId: props.novelId,
            settings: overview.settings,
            capability: configurationCapability,
            canConfigure: overview.authorization.can_configure,
            saving: operation.saving,
            targets: props.scopeTargets ?? [],
            overrides: loadState.overrides,
            narratorOptions,
            characterOptions: props.characterOptions ?? [],
            onSave: saveScopeOverride,
          }),
        )
        : externalContent ?? h(
          "section",
          {
            className: "anw-reading-integration-slot",
            role: "status",
            "data-reading-integration-slot": activeSection,
          },
          h("h2", null, READING_SECTIONS.find((item) => item.key === activeSection)?.label ?? "朗读设置"),
          h("p", null, "该局部模块将在 T2-GATE 汇合后接入；这里不会提供不可用的演示按钮。"),
        );

    return h(
      "main",
      {
        className: "anw-reading-page",
        "data-narration-reading-page": "v1",
        "data-novel-id": props.novelId,
        "data-active-section": activeSection,
      },
      h(
        "header",
        { className: "anw-reading-page-header" },
        h("div", null,
          h("p", { className: "anw-reading-eyebrow" }, props.novelTitle ?? "当前作品"),
          h("h1", null, "朗读"),
          h("p", null, chapterPlaybackReady
            ? "管理作品旁白、人物声音和朗读规则；章节播放与校听已在章节写作页开放。"
            : "管理作品旁白、人物声音和朗读规则；章节播放与校听将在对应产品能力通过门禁后开放。"),
        ),
        h(
          "span",
          {
            className: `anw-reading-product-state is-${productCapability.state}`,
            "data-reason-code": productCapability.reason_code ?? undefined,
          },
          productCapability.actionable ? "朗读设置可用" : capabilityStatusText(productCapability),
        ),
      ),
      h(
        "div",
        { className: "anw-reading-layout" },
        h(
          "nav",
          { className: "anw-reading-nav", "aria-label": "朗读设置" },
          ...READING_SECTIONS.map((section) => h(
            "button",
            {
              key: section.key,
              type: "button",
              className: activeSection === section.key ? "is-active" : "",
              "aria-current": activeSection === section.key ? "page" : undefined,
              "data-reading-section": section.key,
              onClick: () => navigate(section.key),
            },
            section.label,
          )),
        ),
        h(
          "div",
          { className: "anw-reading-content" },
          operation.message
            ? h(
              "div",
              {
                className: `anw-reading-operation is-${operation.kind ?? "idle"}`,
                role: operation.kind === "error" ? "alert" : "status",
                "aria-live": "polite",
              },
              h("span", null, operation.message),
              operation.kind === "error"
                ? h("button", { type: "button", onClick: reload }, "刷新最新配置")
                : null,
            )
            : null,
          sectionBody,
        ),
      ),
    );
  };
}
