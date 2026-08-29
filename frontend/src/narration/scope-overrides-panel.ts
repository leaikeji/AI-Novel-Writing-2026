import { NarrationApiError } from "./api";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationScopeKind,
  NarrationScopeOverrideResource,
  NarrationScopeOverrideValues,
  NarrationSettingsResource,
  NarratorVoiceSelection,
  PutNarrationScopeOverrideRequest,
} from "./contracts";
import {
  READING_PAUSE_PRESETS,
  SUPPORTED_READING_LANGUAGES,
  pausePresetForTiming,
  type SupportedReadingLanguage,
} from "./reading-preferences-panel";


const MUTATION_CAPABILITIES = ["narration_product", "reading_settings"] as const;


export interface ScopeOverridesReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
}


export interface ReadingScopeTarget {
  readonly novelId: string;
  readonly scopeKind: NarrationScopeKind;
  readonly scopeId: string;
  readonly label: string;
  readonly parentVolumeId?: string;
  readonly parentVolumeLabel?: string;
  readonly affectedChapterCount?: number;
}


export interface ReadingScopeNarratorOption {
  readonly novelId: string | null;
  readonly profileId: string;
  readonly versionId: string;
  readonly label: string;
  readonly usable: boolean;
}


export interface ScopeOverridesPanelProps {
  readonly novelId: string;
  readonly settings: NarrationSettingsResource;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly targets: readonly ReadingScopeTarget[];
  readonly overrides: readonly NarrationScopeOverrideResource[];
  readonly narratorOptions?: readonly ReadingScopeNarratorOption[];
  readonly characterOptions?: readonly Readonly<{
    novelId: string;
    characterId: string;
    label: string;
  }>[];
  readonly saveOverride: (
    novelId: string,
    scopeKind: NarrationScopeKind,
    scopeId: string,
    request: PutNarrationScopeOverrideRequest,
    signal?: AbortSignal,
  ) => Promise<NarrationScopeOverrideResource>;
  readonly onSaved?: (resource: NarrationScopeOverrideResource) => void;
  readonly onRefresh?: () => void;
  readonly className?: string;
}


interface ScopeOperation {
  readonly saving: boolean;
  readonly message: string | null;
  readonly conflict: boolean;
}


const IDLE_OPERATION: ScopeOperation = { saving: false, message: null, conflict: false };


interface ValueChangeEvent {
  readonly target: { readonly value: string; readonly checked: boolean };
}


function capability(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | undefined {
  return capabilities.items.find((item) => item.key === key);
}


function actionable(item: FeatureCapability | undefined): boolean {
  return item?.state === "enabled" && item.visible && item.actionable;
}


export function canConfigureScopeOverrides(
  capabilities: NarrationCapabilities,
  authorization: NarrationAuthorizationState,
): boolean {
  return authorization.can_read
    && authorization.can_configure
    && MUTATION_CAPABILITIES.every((key) => actionable(capability(capabilities, key)));
}


function blockedReason(props: ScopeOverridesPanelProps): string | null {
  if (!props.authorization.can_read) return "当前身份无权查看范围覆盖。";
  if (!props.authorization.can_configure) return "当前身份只能查看，不能修改范围覆盖。";
  for (const key of MUTATION_CAPABILITIES) {
    const item = capability(props.capabilities, key);
    if (!actionable(item)) {
      return `范围覆盖当前只读${item?.reason_code ? `（${item.reason_code}）` : ""}。`;
    }
  }
  return null;
}


export function scopeTargetKey(
  target: Pick<ReadingScopeTarget, "scopeKind" | "scopeId">,
): string {
  return `${target.scopeKind}:${target.scopeId}`;
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
  return overrides.find((item) => (
    item.novel_id === target.novelId
    && item.scope_kind === target.scopeKind
    && item.scope_id === target.scopeId
  ));
}


export function buildScopeOverrideRequest(
  novelId: string,
  target: ReadingScopeTarget,
  current: NarrationScopeOverrideResource | undefined,
  enabled: boolean,
  values: NarrationScopeOverrideValues,
): PutNarrationScopeOverrideRequest {
  if (target.novelId !== novelId) throw new Error("范围覆盖目标不属于当前作品");
  if (current && (
    current.novel_id !== novelId
    || current.scope_kind !== target.scopeKind
    || current.scope_id !== target.scopeId
  )) throw new Error("范围覆盖版本与目标不匹配");
  return {
    expected_version: current?.version ?? 0,
    enabled,
    overrides: enabled ? values : emptyScopeOverrideValues(),
  };
}


export function scopeInheritanceLabels(target: ReadingScopeTarget): readonly string[] {
  if (target.scopeKind === "volume") return ["作品设置", `分卷 · ${target.label}`];
  return [
    "作品设置",
    ...(target.parentVolumeLabel ? [`分卷 · ${target.parentVolumeLabel}`] : []),
    `章节 · ${target.label}`,
  ];
}


export function scopeAffectedDescription(target: ReadingScopeTarget): string {
  if (target.scopeKind === "chapter") return "只影响这个章节以后新建的朗读版本";
  if (target.affectedChapterCount !== undefined) {
    return `影响该卷 ${target.affectedChapterCount} 个章节以后新建的朗读版本`;
  }
  return "影响该卷内章节以后新建的朗读版本";
}


export function countEnabledScopeOverrides(
  novelId: string,
  overrides: readonly NarrationScopeOverrideResource[],
): number {
  return overrides.filter((item) => item.novel_id === novelId && item.enabled).length;
}


function valuesEqual(left: NarrationScopeOverrideValues, right: NarrationScopeOverrideValues): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}


function valuesEmpty(values: NarrationScopeOverrideValues): boolean {
  return values.narrator === null
    && values.language === null
    && values.text_rules === null
    && values.timing === null;
}


function selectionKey(selection: NarratorVoiceSelection): string {
  return `${selection.profile_id}:${selection.version_id}`;
}


function replaceOverride(
  current: readonly NarrationScopeOverrideResource[],
  saved: NarrationScopeOverrideResource,
): readonly NarrationScopeOverrideResource[] {
  const key = `${saved.scope_kind}:${saved.scope_id}`;
  return [...current.filter((item) => `${item.scope_kind}:${item.scope_id}` !== key), saved];
}


function isAbortError(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


function mutationError(reason: unknown): { message: string; conflict: boolean } {
  if (reason instanceof NarrationApiError && reason.detail.code === "VERSION_CONFLICT") {
    return { message: "范围覆盖已在其他位置更新；本地草稿仍保留。", conflict: true };
  }
  if (reason instanceof NarrationApiError && ["SCOPE_VIOLATION", "RESOURCE_NOT_FOUND"].includes(reason.detail.code)) {
    return { message: "分卷或章节范围已经变化，请刷新后重试。", conflict: true };
  }
  return { message: "范围覆盖未保存，本地草稿仍保留。", conflict: false };
}


export function createScopeOverridesPanel(
  React: ScopeOverridesReactRuntime,
): (props: ScopeOverridesPanelProps) => unknown {
  const h = React.createElement;

  return function ScopeOverridesPanel(props: ScopeOverridesPanelProps): unknown {
    const targets = props.targets.filter((target) => target.novelId === props.novelId);
    const firstKey = targets[0] ? scopeTargetKey(targets[0]) : "";
    const [selectedKey, setSelectedKey] = React.useState(firstKey);
    const [localOverrides, setLocalOverrides] = React.useState(props.overrides);
    const selected = targets.find((target) => scopeTargetKey(target) === selectedKey) ?? targets[0];
    const current = selected ? scopeOverrideForTarget(selected, localOverrides) : undefined;
    const [draftScopeKey, setDraftScopeKey] = React.useState(firstKey);
    const [enabled, setEnabled] = React.useState(current?.enabled ?? false);
    const [draft, setDraft] = React.useState<NarrationScopeOverrideValues>(
      current?.overrides ?? emptyScopeOverrideValues(),
    );
    const [operation, setOperation] = React.useState<ScopeOperation>(IDLE_OPERATION);
    const controllerRef = React.useRef<AbortController | null>(null);
    const novelRef = React.useRef(props.novelId);
    const selectedRef = React.useRef("");
    const selectedIdentity = selected ? scopeTargetKey(selected) : "";
    novelRef.current = props.novelId;
    selectedRef.current = selectedIdentity;

    React.useEffect(() => {
      controllerRef.current?.abort();
      setLocalOverrides(props.overrides);
      const nextTargets = props.targets.filter((target) => target.novelId === props.novelId);
      setSelectedKey(nextTargets[0] ? scopeTargetKey(nextTargets[0]) : "");
      setOperation(IDLE_OPERATION);
      return () => controllerRef.current?.abort();
    }, [props.novelId]);

    React.useEffect(() => {
      setLocalOverrides(props.overrides);
    }, [props.overrides]);

    React.useEffect(() => {
      if (!selected) {
        setDraftScopeKey("");
        setEnabled(false);
        setDraft(emptyScopeOverrideValues());
        return;
      }
      const active = scopeOverrideForTarget(selected, localOverrides);
      setDraftScopeKey(selectedIdentity);
      setEnabled(active?.enabled ?? false);
      setDraft(active?.overrides ?? emptyScopeOverrideValues());
      setOperation(IDLE_OPERATION);
    }, [selectedIdentity, current?.version]);

    const canConfigure = canConfigureScopeOverrides(props.capabilities, props.authorization);
    const scopeChanging = selectedIdentity !== draftScopeKey;
    const baselineEnabled = current?.enabled ?? false;
    const baselineValues = current?.overrides ?? emptyScopeOverrideValues();
    const dirty = enabled !== baselineEnabled || !valuesEqual(draft, baselineValues);
    const languageValid = draft.language === null || SUPPORTED_READING_LANGUAGES.includes(
      draft.language as SupportedReadingLanguage,
    );
    const narratorOptions = (props.narratorOptions ?? []).filter((option) => (
      option.novelId === null || option.novelId === props.novelId
    ));
    const narratorValue = draft.narrator ? selectionKey(draft.narrator) : "";
    const narratorValid = draft.narrator === null || narratorOptions.some((option) => (
      option.usable
      && option.profileId === draft.narrator?.profile_id
      && option.versionId === draft.narrator?.version_id
    ));
    const characters = (props.characterOptions ?? []).filter(
      (character) => character.novelId === props.novelId,
    );
    const selectedFirstPersonCharacter = draft.text_rules?.first_person_character_id ?? null;
    const firstPersonCharacterValid = draft.text_rules === null
      || draft.text_rules.first_person_mode === "narrator"
      || characters.some((character) => character.characterId === selectedFirstPersonCharacter);
    const invalidEnabled = enabled && valuesEmpty(draft);
    const disabled = !canConfigure || operation.saving || scopeChanging;
    const saveDisabled = disabled
      || !dirty
      || invalidEnabled
      || !languageValid
      || !narratorValid
      || !firstPersonCharacterValid;
    const prefix = `anw-scope-overrides-${props.novelId}`;

    const save = (): void => {
      if (!selected || saveDisabled) return;
      const request = buildScopeOverrideRequest(
        props.novelId,
        selected,
        current,
        enabled,
        draft,
      );
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const expectedNovelId = props.novelId;
      const expectedKey = selectedIdentity;
      const expectedVersion = current?.version ?? 0;
      setOperation({ saving: true, message: "正在保存范围覆盖…", conflict: false });
      void props.saveOverride(
        props.novelId,
        selected.scopeKind,
        selected.scopeId,
        request,
        controller.signal,
      ).then((saved) => {
        if (
          controller.signal.aborted
          || novelRef.current !== expectedNovelId
          || selectedRef.current !== expectedKey
        ) return;
        const identityMatches = saved.novel_id === expectedNovelId
          && `${saved.scope_kind}:${saved.scope_id}` === expectedKey;
        const stateMatches = saved.enabled === request.enabled
          && valuesEqual(saved.overrides, request.overrides)
          && (request.enabled ? saved.version > expectedVersion : saved.version === 0);
        if (!identityMatches || !stateMatches) {
          setOperation({
            saving: false,
            message: "服务返回了不匹配的范围配置，已拒绝应用。",
            conflict: true,
          });
          return;
        }
        setLocalOverrides((items) => replaceOverride(items, saved));
        setEnabled(saved.enabled);
        setDraft(saved.overrides);
        setOperation({
          saving: false,
          message: saved.enabled ? "范围覆盖已保存。" : "范围覆盖已关闭并清空。",
          conflict: false,
        });
        props.onSaved?.(saved);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        const failure = mutationError(reason);
        setOperation({ saving: false, ...failure });
      });
    };

    if (!props.authorization.can_read) {
      return h("section", {
        className: "anw-scope-overrides-panel",
        role: "region",
        "aria-labelledby": `${prefix}-heading`,
      },
      h("h2", { id: `${prefix}-heading` }, "范围覆盖"),
      h("p", { role: "alert" }, "当前身份无权查看范围覆盖。"),
      );
    }

    if (!selected) {
      return h("section", {
        className: "anw-scope-overrides-panel is-empty",
        role: "region",
        "aria-labelledby": `${prefix}-heading`,
      },
      h("h2", { id: `${prefix}-heading` }, "范围覆盖"),
      h("p", null, "当前作品还没有可配置的分卷或章节。"),
      );
    }

    const reason = blockedReason(props);
    const inheritance = scopeInheritanceLabels(selected);
    const timingPreset = draft.timing ? pausePresetForTiming(draft.timing) : null;

    return h("details", {
      className: ["anw-scope-overrides-panel", props.className ?? ""].filter(Boolean).join(" "),
      "data-reading-panel": "scope-overrides",
    },
    h("summary", null,
      h("span", null, "范围覆盖"),
      h("small", null, `${countEnabledScopeOverrides(props.novelId, localOverrides)} 个已启用 · 默认继承作品设置`),
    ),
    h("div", {
      className: "anw-scope-overrides-panel__body",
      role: "region",
      "aria-labelledby": `${prefix}-heading`,
      "aria-busy": operation.saving || undefined,
    },
    h("header", null,
      h("div", null,
        h("h2", { id: `${prefix}-heading`, tabIndex: -1 }, "分卷与章节范围覆盖"),
        h("p", null, "只在某一范围确实需要不同设置时启用；关闭后恢复继承。"),
      ),
      h("span", null, `覆盖版本 ${current?.version ?? 0}`),
    ),
    reason ? h("p", { className: "anw-scope-overrides-panel__notice", role: "note" }, reason) : null,
    h("fieldset", { disabled },
      h("legend", null, "选择范围"),
      h("label", null,
        h("span", null, "分卷或章节"),
        h("select", {
          value: selectedIdentity,
          onChange: (event: ValueChangeEvent) => setSelectedKey(event.target.value),
        },
        ...targets.map((target) => h("option", {
          key: scopeTargetKey(target),
          value: scopeTargetKey(target),
        }, `${target.scopeKind === "volume" ? "分卷" : "章节"} · ${target.label}`)),
        ),
      ),
      h("label", { className: "anw-scope-overrides-panel__check" },
        h("input", {
          type: "checkbox",
          checked: enabled,
          onChange: (event: ValueChangeEvent) => setEnabled(event.target.checked),
        }),
        h("span", null, "为这个范围启用覆盖"),
      ),
    ),
    h("section", {
      className: "anw-scope-overrides-panel__inheritance",
      "aria-labelledby": `${prefix}-inheritance-heading`,
    },
    h("h3", { id: `${prefix}-inheritance-heading` }, "生效顺序"),
    h("ol", null, ...inheritance.map((label, index) => h("li", {
      key: label,
      "aria-current": index === inheritance.length - 1 ? "step" : undefined,
    }, label))),
    h("p", null, scopeAffectedDescription(selected)),
    ),
    enabled
      ? h("fieldset", { disabled },
        h("legend", null, "覆盖内容"),
        h("label", null,
          h("span", null, "旁白音色"),
          h("select", {
            value: narratorValue,
            "aria-invalid": !narratorValid,
            onChange: (event: ValueChangeEvent) => {
              const option = narratorOptions.find((item) => (
                `${item.profileId}:${item.versionId}` === event.target.value && item.usable
              ));
              setDraft((currentDraft) => ({
                ...currentDraft,
                narrator: option
                  ? { profile_id: option.profileId, version_id: option.versionId }
                  : null,
              }));
            },
          },
          h("option", { value: "" }, "继承上一级旁白"),
          !narratorValid && draft.narrator
            ? h("option", { value: narratorValue, disabled: true }, "旧旁白已不可用（请重新选择）")
            : null,
          ...narratorOptions.filter((item) => item.usable).map((item) => h("option", {
            key: `${item.profileId}:${item.versionId}`,
            value: `${item.profileId}:${item.versionId}`,
          }, item.label)),
          ),
        ),
        h("label", null,
          h("span", null, "朗读语言"),
          h("select", {
            value: draft.language ?? "",
            "aria-invalid": !languageValid,
            onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
              ...currentDraft,
              language: event.target.value || null,
            })),
          },
          h("option", { value: "" }, `继承作品语言（${props.settings.values.language}）`),
          !languageValid && draft.language
            ? h("option", { value: draft.language, disabled: true }, `旧值 ${draft.language}（请重新选择）`)
            : null,
          h("option", { value: "zh-CN" }, "中文（简体）"),
          h("option", { value: "en" }, "英语"),
          h("option", { value: "ja-JP" }, "日语"),
          ),
        ),
        h("label", { className: "anw-scope-overrides-panel__check" },
          h("input", {
            type: "checkbox",
            checked: draft.text_rules !== null,
            onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
              ...currentDraft,
              text_rules: event.target.checked ? props.settings.values.text_rules : null,
            })),
          }),
          h("span", null, "覆盖正文朗读规则（从作品当前值开始）"),
        ),
        draft.text_rules
          ? h("div", { className: "anw-scope-overrides-panel__checks" },
            ...([
              ["read_chapter_title", "朗读章节标题"],
              ["read_author_notes", "朗读作者的话"],
              ["read_section_breaks", "朗读分隔内容"],
            ] as const).map(([key, label]) => h("label", { key },
              h("input", {
                type: "checkbox",
                checked: draft.text_rules?.[key] ?? false,
                onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
                  ...currentDraft,
                  text_rules: currentDraft.text_rules
                    ? { ...currentDraft.text_rules, [key]: event.target.checked }
                    : null,
                })),
              }),
              h("span", null, label),
            )),
            h("details", { className: "anw-scope-overrides-panel__advanced" },
              h("summary", null, "高级：叙述与内心独白声音"),
              h("div", null,
                h("label", null,
                  h("span", null, "第一人称叙述"),
                  h("select", {
                    value: draft.text_rules.first_person_mode,
                    onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
                      ...currentDraft,
                      text_rules: currentDraft.text_rules
                        ? event.target.value === "character" && characters.length > 0
                          ? {
                            ...currentDraft.text_rules,
                            first_person_mode: "character",
                            first_person_character_id: currentDraft.text_rules.first_person_character_id
                              ?? characters[0]!.characterId,
                          }
                          : {
                            ...currentDraft.text_rules,
                            first_person_mode: "narrator",
                            first_person_character_id: null,
                          }
                        : null,
                    })),
                  },
                  h("option", { value: "narrator" }, "使用旁白"),
                  h("option", { value: "character", disabled: characters.length === 0 }, "使用指定人物"),
                  ),
                ),
                draft.text_rules.first_person_mode === "character"
                  ? h("label", null,
                    h("span", null, "第一人称人物"),
                    h("select", {
                      value: selectedFirstPersonCharacter ?? "",
                      "aria-invalid": !firstPersonCharacterValid,
                      onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
                        ...currentDraft,
                        text_rules: currentDraft.text_rules
                          ? {
                            ...currentDraft.text_rules,
                            first_person_character_id: event.target.value || null,
                          }
                          : null,
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
                    value: draft.text_rules.inner_monologue_mode,
                    onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
                      ...currentDraft,
                      text_rules: currentDraft.text_rules
                        ? {
                          ...currentDraft.text_rules,
                          inner_monologue_mode: event.target.value === "narrator" ? "narrator" : "character",
                        }
                        : null,
                    })),
                  },
                  h("option", { value: "character" }, "使用人物声音"),
                  h("option", { value: "narrator" }, "使用旁白"),
                  ),
                ),
              ),
            ),
          )
          : null,
        h("label", { className: "anw-scope-overrides-panel__check" },
          h("input", {
            type: "checkbox",
            checked: draft.timing !== null,
            onChange: (event: ValueChangeEvent) => setDraft((currentDraft) => ({
              ...currentDraft,
              timing: event.target.checked ? props.settings.values.timing : null,
            })),
          }),
          h("span", null, "覆盖停顿节奏（从作品当前值开始）"),
        ),
        draft.timing
          ? h("div", { className: "anw-scope-overrides-panel__pause-presets" },
            ...(["compact", "natural", "relaxed"] as const).map((preset) => h("label", {
              key: preset,
              className: timingPreset === preset ? "is-selected" : "",
            },
            h("input", {
              type: "radio",
              name: `${prefix}-timing-preset`,
              value: preset,
              checked: timingPreset === preset,
              onChange: () => setDraft((currentDraft) => ({
                ...currentDraft,
                timing: READING_PAUSE_PRESETS[preset],
              })),
            }),
            h("span", null, preset === "compact" ? "紧凑" : preset === "natural" ? "自然" : "舒缓"),
            )),
            timingPreset === "custom" ? h("span", null, "自定义毫秒") : null,
          )
          : null,
        draft.timing
          ? h("details", { className: "anw-scope-overrides-panel__advanced" },
            h("summary", null, "高级：精确停顿毫秒"),
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
                  value: draft.timing?.[key] ?? 0,
                  onChange: (event: ValueChangeEvent) => {
                    const value = Number(event.target.value);
                    if (!Number.isInteger(value) || value < 0 || value > maximum) return;
                    setDraft((currentDraft) => ({
                      ...currentDraft,
                      timing: currentDraft.timing
                        ? { ...currentDraft.timing, [key]: value }
                        : null,
                    }));
                  },
                }),
              )),
            ),
          )
          : null,
      )
      : h("p", { className: "anw-scope-overrides-panel__inherited" },
        "该范围完全继承上一级设置。保存关闭后，服务端会清空旧覆盖值。",
      ),
    invalidEnabled
      ? h("p", { className: "anw-scope-overrides-panel__error", role: "alert" },
        "启用覆盖前，至少选择旁白、语言、正文规则或停顿节奏中的一项。",
      )
      : null,
    !languageValid
      ? h("p", { className: "anw-scope-overrides-panel__error", role: "alert" },
        "范围语言必须从中文、英语或日语中选择。",
      )
      : null,
    !narratorValid
      ? h("p", { className: "anw-scope-overrides-panel__error", role: "alert" },
        "该范围的旧旁白已不可用，请重新选择或改为继承。",
      )
      : null,
    !firstPersonCharacterValid
      ? h("p", { className: "anw-scope-overrides-panel__error", role: "alert" },
        "该范围的第一人称人物已不在当前作品中，请重新选择或改用旁白。",
      )
      : null,
    operation.message
      ? h("div", {
        className: operation.conflict
          ? "anw-scope-overrides-panel__error"
          : "anw-scope-overrides-panel__status",
        role: operation.conflict ? "alert" : "status",
        tabIndex: operation.conflict ? -1 : undefined,
      },
      h("p", null, operation.message),
      operation.conflict && props.onRefresh
        ? h("button", { type: "button", onClick: props.onRefresh }, "刷新最新覆盖")
        : null,
      )
      : null,
    h("footer", null,
      h("span", null, dirty ? "有未保存更改" : "覆盖配置已同步"),
      h("button", {
        type: "button",
        className: "anw-scope-overrides-panel__save",
        disabled: saveDisabled,
        onClick: save,
      }, operation.saving ? "保存中…" : enabled ? "保存范围覆盖" : "关闭并清空覆盖"),
    ),
    ),
    );
  };
}
