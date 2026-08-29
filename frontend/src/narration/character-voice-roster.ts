import type {
  CapabilityKey,
  CharacterVoiceBindingResource,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceSourceType,
} from "./contracts";
import {
  voiceActivationEvidenceIsUsable,
  voiceSourceEvidenceIsUsable,
} from "./contracts";


export interface CharacterVoiceRosterReactRuntime {
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


export interface CharacterVoiceRosterCharacter {
  readonly characterId: string;
  readonly characterName: string;
}


export type CharacterVoiceSourceGroup = "official" | "private" | "unresolved";


export interface CharacterVoiceRosterRow {
  readonly characterId: string;
  readonly characterName: string;
  readonly binding: CharacterVoiceBindingResource | null;
  readonly configured: boolean;
  readonly profile: VoiceProfileResource | null;
  readonly version: VoiceProfileVersionResource | null;
  readonly voiceName: string | null;
  readonly sourceGroup: CharacterVoiceSourceGroup;
  readonly sourceType: VoiceSourceType | null;
  readonly previewAvailable: boolean;
}


export interface CharacterVoiceOfficialMatchResult {
  readonly voiceName: string;
}


export interface CharacterVoiceRosterProps {
  readonly novelId: string;
  readonly characters: readonly CharacterVoiceRosterCharacter[];
  readonly bindings: readonly CharacterVoiceBindingResource[];
  readonly profiles: readonly VoiceProfileResource[];
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly className?: string;
  readonly onConfigureCharacter: (characterId: string) => void;
  /** Preview stays unavailable until the host injects the existing preview controller. */
  readonly onPreviewVoice?: (
    character: CharacterVoiceRosterCharacter,
    profile: VoiceProfileResource,
    version: VoiceProfileVersionResource,
  ) => void | Promise<void>;
  /** One call must select and bind an official preset for the exact character. */
  readonly onMatchOfficialVoice?: (
    character: CharacterVoiceRosterCharacter,
  ) => Promise<CharacterVoiceOfficialMatchResult>;
  /** Reserved for the separately gated VoiceGenerator package. */
  readonly onGenerateAndUse?: (
    character: CharacterVoiceRosterCharacter,
  ) => void | Promise<void>;
  readonly onBatchCompleted?: () => void;
}


type RowActionPhase = "idle" | "running" | "success" | "error";


interface RowActionState {
  readonly phase: RowActionPhase;
  readonly message: string;
}


const SOURCE_LABELS: Readonly<Record<CharacterVoiceSourceGroup, string>> = {
  official: "官方音色",
  private: "私人音色",
  unresolved: "来源待恢复",
};


const REQUIRED_BATCH_CAPABILITIES = [
  "narration_product",
  "reading_settings",
  "preset_voice_source",
] as const satisfies readonly CapabilityKey[];


function capabilityByKey(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | undefined {
  return capabilities.items.find((item) => item.key === key);
}


function capabilityIsActionable(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): boolean {
  const capability = capabilityByKey(capabilities, key);
  return capability?.state === "enabled"
    && capability.visible
    && capability.actionable;
}


function sourceGroup(version: VoiceProfileVersionResource | null): CharacterVoiceSourceGroup {
  if (version === null) return "unresolved";
  if (version.source_type === "preset"
    && voiceSourceEvidenceIsUsable(version)
    && voiceActivationEvidenceIsUsable(version)) return "official";
  if (version.source_type === "uploaded" || version.source_type === "generated") return "private";
  return "unresolved";
}


function currentProfileVersion(
  profile: VoiceProfileResource | null,
  versionId: string | null,
): VoiceProfileVersionResource | null {
  if (profile === null || versionId === null) return null;
  return profile.versions.find((version) => version.version_id === versionId) ?? null;
}


export function buildCharacterVoiceRosterRows(
  novelId: string,
  characters: readonly CharacterVoiceRosterCharacter[],
  bindings: readonly CharacterVoiceBindingResource[],
  profiles: readonly VoiceProfileResource[],
): readonly CharacterVoiceRosterRow[] {
  const characterIds = new Set(characters.map((character) => character.characterId));
  const bindingByCharacter = new Map<string, CharacterVoiceBindingResource>();
  for (const binding of bindings) {
    if (binding.novel_id !== novelId || !characterIds.has(binding.character_id)) continue;
    if (!bindingByCharacter.has(binding.character_id)) {
      bindingByCharacter.set(binding.character_id, binding);
    }
  }
  const profileById = new Map(
    profiles
      .filter((profile) => profile.novel_id === null || profile.novel_id === novelId)
      .map((profile) => [profile.profile_id, profile] as const),
  );
  return characters.map((character) => {
    const binding = bindingByCharacter.get(character.characterId) ?? null;
    const configured = Boolean(
      binding
      && binding.binding_policy !== "unset"
      && binding.profile_id
      && binding.version_id,
    );
    const profile = configured && binding?.profile_id
      ? profileById.get(binding.profile_id) ?? null
      : null;
    const version = currentProfileVersion(profile, binding?.version_id ?? null);
    return {
      characterId: character.characterId,
      characterName: character.characterName,
      binding,
      configured,
      profile,
      version,
      voiceName: configured ? profile?.name ?? "绑定音色不可用" : null,
      sourceGroup: configured ? sourceGroup(version) : "unresolved",
      sourceType: version?.source_type ?? null,
      previewAvailable: Boolean(version?.preview_asset),
    };
  });
}


export function characterVoiceBatchAvailability(
  props: Pick<
    CharacterVoiceRosterProps,
    "authorization" | "capabilities" | "onMatchOfficialVoice"
  >,
  unconfiguredCount: number,
): { readonly enabled: boolean; readonly reason: string } {
  if (!props.authorization.can_read) return { enabled: false, reason: "当前身份无权查看人物配音。" };
  if (!props.authorization.can_configure) return { enabled: false, reason: "当前身份只能查看，不能批量修改人物配音。" };
  const blocked = REQUIRED_BATCH_CAPABILITIES.find((key) => (
    !capabilityIsActionable(props.capabilities, key)
  ));
  if (blocked) {
    const reasonCode = capabilityByKey(props.capabilities, blocked)?.reason_code;
    return {
      enabled: false,
      reason: `官方音色批量匹配当前不可用${reasonCode ? `（${reasonCode}）` : ""}。`,
    };
  }
  if (!props.onMatchOfficialVoice) {
    return { enabled: false, reason: "官方音色批量分配服务尚未接入。" };
  }
  if (unconfiguredCount === 0) return { enabled: false, reason: "所有人物均已配置声音。" };
  return { enabled: true, reason: `将为 ${unconfiguredCount} 位未配置人物稳定分配并直接使用官方音色；这不是新音色生成。` };
}


function generatorAvailability(
  props: Pick<
    CharacterVoiceRosterProps,
    "authorization" | "capabilities" | "onGenerateAndUse"
  >,
): { readonly enabled: boolean; readonly reason: string } {
  if (!props.authorization.can_configure) return { enabled: false, reason: "当前身份只能查看。" };
  const capability = capabilityByKey(props.capabilities, "voice_generator");
  if (!capabilityIsActionable(props.capabilities, "voice_generator")) {
    return {
      enabled: false,
      reason: `人物专属音色生成暂不可用${capability?.reason_code ? `（${capability.reason_code}）` : ""}。`,
    };
  }
  if (!props.onGenerateAndUse) return { enabled: false, reason: "人物专属音色生成服务待接入。" };
  return { enabled: true, reason: "根据人物卡生成专属音色并直接使用。" };
}


function configurationIsActionable(
  props: Pick<CharacterVoiceRosterProps, "authorization" | "capabilities">,
): boolean {
  return props.authorization.can_read
    && props.authorization.can_configure
    && capabilityIsActionable(props.capabilities, "narration_product")
    && capabilityIsActionable(props.capabilities, "reading_settings");
}


function actionError(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "操作失败，请稍后重试。";
}


export function createCharacterVoiceRoster(
  React: CharacterVoiceRosterReactRuntime,
): (props: CharacterVoiceRosterProps) => unknown {
  const h = React.createElement;

  return function CharacterVoiceRoster(props: CharacterVoiceRosterProps): unknown {
    const rows = buildCharacterVoiceRosterRows(
      props.novelId,
      props.characters,
      props.bindings,
      props.profiles,
    );
    const [batchRunning, setBatchRunning] = React.useState(false);
    const [results, setResults] = React.useState<Readonly<Record<string, RowActionState>>>({});
    const mountedRef = React.useRef(true);
    React.useEffect(() => {
      mountedRef.current = true;
      return () => { mountedRef.current = false; };
    }, []);
    const unconfigured = rows.filter((row) => !row.configured);
    const batchAvailability = characterVoiceBatchAvailability(props, unconfigured.length);
    const generateAvailability = generatorAvailability(props);
    const statusId = `anw-character-voice-roster-${props.novelId}-status`;
    const configureEnabled = configurationIsActionable(props);

    const updateResult = (characterId: string, state: RowActionState) => {
      if (!mountedRef.current) return;
      setResults((current) => ({ ...current, [characterId]: state }));
    };

    const runBatch = async () => {
      if (batchRunning || !batchAvailability.enabled || !props.onMatchOfficialVoice) return;
      setBatchRunning(true);
      setResults(Object.fromEntries(unconfigured.map((row) => [
        row.characterId,
        { phase: "running", message: "正在分配官方音色…" } satisfies RowActionState,
      ])));
      await Promise.all(unconfigured.map(async (row) => {
        const character = { characterId: row.characterId, characterName: row.characterName };
        try {
          const result = await props.onMatchOfficialVoice?.(character);
          updateResult(row.characterId, {
            phase: "success",
            message: result ? `已使用 ${result.voiceName}` : "已分配并使用官方音色",
          });
        } catch (reason: unknown) {
          updateResult(row.characterId, { phase: "error", message: actionError(reason) });
        }
      }));
      if (!mountedRef.current) return;
      setBatchRunning(false);
      props.onBatchCompleted?.();
    };

    const rootClassName = ["anw-character-voice-roster", props.className ?? ""]
      .filter(Boolean)
      .join(" ");
    if (!props.authorization.can_read) {
      return h(
        "section",
        { className: rootClassName, role: "status" },
        h("h2", null, "人物配音"),
        h("p", { className: "anw-character-voice-roster__empty" }, "当前身份无权查看人物配音。"),
      );
    }
    return h(
      "section",
      {
        className: rootClassName,
        "aria-labelledby": `${statusId}-heading`,
        "aria-describedby": statusId,
      },
      h("header", { className: "anw-character-voice-roster__header" },
        h("div", null,
          h("p", { className: "anw-character-voice-roster__eyebrow" }, "人物声音覆盖"),
          h("h2", { id: `${statusId}-heading` }, "人物配音"),
          h("p", null, `${rows.length} 位人物 · ${unconfigured.length} 位未配置`),
        ),
        h("button", {
          type: "button",
          className: "anw-character-voice-roster__batch",
          disabled: batchRunning || !batchAvailability.enabled,
          onClick: () => { void runBatch(); },
          "aria-describedby": statusId,
        }, batchRunning ? "正在批量分配…" : "为未配置人物自动分配官方音色"),
      ),
      h("p", { id: statusId, className: "anw-character-voice-roster__status", role: "status", "aria-live": "polite" },
        batchRunning ? "正在逐一处理；成功人物将直接使用匹配结果，失败人物不会影响其他人物。" : batchAvailability.reason,
      ),
      !generateAvailability.enabled
        ? h("p", { className: "anw-character-voice-roster__generator-note" },
          `根据人物生成专属音色：${generateAvailability.reason} 可改用下方“自动分配官方音色”，该操作不会冒充生成新音色。`,
        )
        : null,
      rows.length === 0
        ? h("p", { className: "anw-character-voice-roster__empty", role: "status" },
          "当前作品还没有可配置声音的人物。请先在人物卡中新建人物。",
        )
        : h("ul", { className: "anw-character-voice-roster__list" },
          ...rows.map((row) => {
            const result = results[row.characterId];
            const character = { characterId: row.characterId, characterName: row.characterName };
            const fallbackEnabled = configureEnabled
              && Boolean(props.onMatchOfficialVoice)
              && capabilityIsActionable(props.capabilities, "preset_voice_source")
              && result?.phase !== "running";
            const previewEnabled = Boolean(
              row.profile && row.version && row.previewAvailable && props.onPreviewVoice,
            );
            return h("li", {
              key: row.characterId,
              className: `anw-character-voice-roster__card is-${row.configured ? "configured" : "unconfigured"}`,
              "data-character-id": row.characterId,
            },
            h("div", { className: "anw-character-voice-roster__identity" },
              h("strong", null, row.characterName),
              h("span", { className: `anw-character-voice-roster__coverage is-${row.configured ? "configured" : "missing"}` },
                row.configured ? "已配置" : "未配置",
              ),
            ),
            h("div", { className: "anw-character-voice-roster__binding" },
              h("span", { className: `anw-character-voice-roster__source is-${row.sourceGroup}` },
                row.configured ? SOURCE_LABELS[row.sourceGroup] : "等待配置",
              ),
              h("span", null, row.voiceName ?? "尚未绑定声音"),
              row.version
                ? h("span", { className: "anw-character-voice-roster__version" }, `v${row.version.version_number} · ${row.version.language}`)
                : null,
            ),
            result
              ? h("p", {
                className: `anw-character-voice-roster__result is-${result.phase}`,
                role: result.phase === "error" ? "alert" : "status",
              }, result.message)
              : null,
            h("div", { className: "anw-character-voice-roster__actions" },
              h("button", {
                type: "button",
                disabled: !previewEnabled,
                title: previewEnabled ? "试听当前绑定音色" : "当前绑定暂无可试听音频",
                onClick: () => {
                  if (row.profile && row.version && previewEnabled) {
                    void props.onPreviewVoice?.(character, row.profile, row.version);
                  }
                },
              }, "试听"),
              h("button", {
                type: "button",
                disabled: !configureEnabled,
                title: configureEnabled ? undefined : "当前人物声音设置为只读。",
                onClick: () => {
                  if (configureEnabled) props.onConfigureCharacter(row.characterId);
                },
              },
                row.configured ? "更换音色" : "选择官方音色",
              ),
              h("button", {
                type: "button",
                className: "anw-character-voice-roster__generate",
                disabled: generateAvailability.enabled ? false : !fallbackEnabled,
                title: generateAvailability.enabled
                  ? generateAvailability.reason
                  : fallbackEnabled
                    ? "稳定分配一个官方音色并直接使用；不会声称生成了专属新音色。"
                    : generateAvailability.reason,
                onClick: () => {
                  if (generateAvailability.enabled) {
                    void props.onGenerateAndUse?.(character);
                    return;
                  }
                  if (!fallbackEnabled || !props.onMatchOfficialVoice) return;
                  updateResult(row.characterId, {
                    phase: "running",
                    message: "正在分配官方音色…",
                  });
                  void props.onMatchOfficialVoice(character).then((matched) => {
                    updateResult(row.characterId, {
                      phase: "success",
                      message: `已使用 ${matched.voiceName}`,
                    });
                    props.onBatchCompleted?.();
                  }).catch((reason: unknown) => {
                    updateResult(row.characterId, {
                      phase: "error",
                      message: actionError(reason),
                    });
                  });
                },
              }, generateAvailability.enabled ? "根据人物生成并使用" : "自动分配官方音色"),
            ));
          }),
        ),
    );
  };
}
