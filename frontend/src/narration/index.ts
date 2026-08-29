import {
  getNarrationOverview,
  listCharacterVoiceBindings,
  listVoiceProfiles,
  selectOfficialVoice,
} from "./api";
import {
  createCachePanel,
  type CachePanelReactRuntime,
} from "./cache-panel";
import {
  createCharacterVoicePanel,
  type CharacterVoicePanelReactRuntime,
} from "./character-voice-panel";
import {
  createCharacterVoiceRoster,
  type CharacterVoiceRosterReactRuntime,
} from "./character-voice-roster";
import type {
  CharacterVoiceBindingResource,
  NarrationOverviewResponse,
  OfficialPresetId,
  VoiceProfileResource,
} from "./contracts";
import type { PronunciationPanelReactRuntime } from "./pronunciation-panel";
import {
  createOfficialVoiceSelectionPanel,
  type OfficialVoiceSelectionPanelApi,
} from "./official-voice-selection-panel";
import { createOfficialVoiceUseIdempotencyKey } from "./official-voice-use-state";
import {
  createReadingPage,
  type ReadingPageProps,
  type ReadingPageApi,
  type ReadingPageReactRuntime,
  type ReadingScopeTarget,
  type ReadingSectionRenderContext,
} from "./reading-page";
import type { ReadingRulesReactRuntime } from "./reading-rules-panel";
import { createReadingRulesWorkspace } from "./reading-rules-workspace";
import { createReadingStatus } from "./reading-status";
import type { ReadingSectionKey } from "./reading-overview";
import { capabilityFor } from "./reading-overview";
import {
  createVoiceSourceWorkspace,
  type VoiceSourceWorkspaceApi,
  type VoiceSourceWorkspaceReactRuntime,
} from "./voice-source-workspace";


export interface NarrationCharacterSummary {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
}


export interface NarrationReadingPageProps {
  readonly novelId: string;
  readonly novelTitle?: string;
  readonly initialSection?: ReadingSectionKey;
  readonly scopeTargets: readonly ReadingScopeTarget[];
  readonly characters: readonly NarrationCharacterSummary[];
  readonly onSectionChange?: (section: ReadingSectionKey) => void;
}


export interface CharacterVoiceCardPanelProps {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly onReturnFocus?: () => void;
}


export interface NarrationReadingPageDependencies {
  readonly readingApi?: ReadingPageApi;
  readonly voiceWorkspaceApi?: VoiceSourceWorkspaceApi;
  readonly officialVoiceApi?: OfficialVoiceSelectionPanelApi;
  readonly characterRosterApi?: Readonly<{
    listBindings: typeof listCharacterVoiceBindings;
    listProfiles: typeof listVoiceProfiles;
  }>;
}


type NarrationReactRuntime = ReadingPageReactRuntime
  & CharacterVoicePanelReactRuntime
  & VoiceSourceWorkspaceReactRuntime
  & PronunciationPanelReactRuntime
  & CachePanelReactRuntime
  & ReadingRulesReactRuntime
  & CharacterVoiceRosterReactRuntime;


interface CharacterVoiceSectionProps {
  readonly novelId: string;
  readonly characters: readonly NarrationCharacterSummary[];
  readonly context: ReadingSectionRenderContext;
}


interface VoiceLibrarySectionProps {
  readonly novelId: string;
  readonly characters: readonly NarrationCharacterSummary[];
  readonly context: ReadingSectionRenderContext;
}


type OverviewLoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | { readonly phase: "ready"; readonly overview: NarrationOverviewResponse };


function overviewErrorMessage(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "无法加载人物声音权限，请稍后重试。";
}


const OFFICIAL_PRESETS_BY_LANGUAGE = Object.freeze({
  zh: Object.freeze([
    { presetId: "onnx.Junhao", voiceName: "Junhao" },
    { presetId: "onnx.Zhiming", voiceName: "Zhiming" },
    { presetId: "onnx.Weiguo", voiceName: "Weiguo" },
    { presetId: "onnx.Xiaoyu", voiceName: "Xiaoyu" },
    { presetId: "onnx.Yuewen", voiceName: "Yuewen" },
    { presetId: "onnx.Lingyu", voiceName: "Lingyu" },
  ]),
  en: Object.freeze([
    { presetId: "onnx.Trump", voiceName: "Trump" },
    { presetId: "onnx.Ava", voiceName: "Ava" },
    { presetId: "onnx.Bella", voiceName: "Bella" },
    { presetId: "onnx.Adam", voiceName: "Adam" },
    { presetId: "onnx.Nathan", voiceName: "Nathan" },
  ]),
  ja: Object.freeze([
    { presetId: "onnx.Soyo", voiceName: "Soyo" },
    { presetId: "onnx.Saki", voiceName: "Saki" },
    { presetId: "onnx.Mortis", voiceName: "Mortis" },
    { presetId: "onnx.Umiri", voiceName: "Umiri" },
    { presetId: "onnx.Mei", voiceName: "Mei" },
    { presetId: "onnx.Anon", voiceName: "Anon" },
    { presetId: "onnx.Arisa", voiceName: "Arisa" },
  ]),
});


export function stableOfficialVoiceAssignment(
  characterId: string,
  targetLanguage: string,
): { readonly presetId: OfficialPresetId; readonly voiceName: string } {
  const language = targetLanguage.toLowerCase();
  const candidates = language.startsWith("ja")
    ? OFFICIAL_PRESETS_BY_LANGUAGE.ja
    : language.startsWith("en")
      ? OFFICIAL_PRESETS_BY_LANGUAGE.en
      : OFFICIAL_PRESETS_BY_LANGUAGE.zh;
  let hash = 0x811c9dc5;
  for (let index = 0; index < characterId.length; index += 1) {
    hash ^= characterId.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return candidates[(hash >>> 0) % candidates.length] as {
    readonly presetId: OfficialPresetId;
    readonly voiceName: string;
  };
}


export function createNarrationReadingPage(
  React: NarrationReactRuntime,
  dependencies: NarrationReadingPageDependencies = {},
): (props: NarrationReadingPageProps) => unknown {
  const h = React.createElement;
  const ReadingPage = createReadingPage(React, dependencies.readingApi);
  const CharacterVoicePanel = createCharacterVoicePanel(React);
  const CharacterVoiceRoster = createCharacterVoiceRoster(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(
    React,
    dependencies.voiceWorkspaceApi,
  );
  const OfficialVoiceSelectionPanel = createOfficialVoiceSelectionPanel(
    React,
    dependencies.officialVoiceApi,
  );
  const CachePanel = createCachePanel(React);
  const ReadingRulesWorkspace = createReadingRulesWorkspace(React);
  const ReadingStatus = createReadingStatus(React);
  const characterRosterApi = dependencies.characterRosterApi ?? {
    listBindings: listCharacterVoiceBindings,
    listProfiles: listVoiceProfiles,
  };
  const selectOfficialVoiceApi = dependencies.officialVoiceApi?.selectOfficialVoice
    ?? selectOfficialVoice;

  function CharacterVoiceSection(props: CharacterVoiceSectionProps): unknown {
    const scopedCharacters = props.characters.filter(
      (character) => character.novelId === props.novelId,
    );
    const [selectedCharacterId, setSelectedCharacterId] = React.useState(
      scopedCharacters[0]?.characterId ?? "",
    );
    const [profileRefreshVersion, setProfileRefreshVersion] = React.useState(0);
    const [rosterState, setRosterState] = React.useState<Readonly<{
      phase: "loading" | "ready" | "error";
      bindings: readonly CharacterVoiceBindingResource[];
      profiles: readonly VoiceProfileResource[];
      message: string | null;
    }>>({ phase: "loading", bindings: [], profiles: [], message: null });
    const selected = scopedCharacters.find(
      (character) => character.characterId === selectedCharacterId,
    ) ?? scopedCharacters[0] ?? null;
    const overview = props.context.overview;
    React.useEffect(() => {
      const controller = new AbortController();
      setRosterState({ phase: "loading", bindings: [], profiles: [], message: null });
      void Promise.all([
        characterRosterApi.listBindings(props.novelId, controller.signal),
        characterRosterApi.listProfiles({
          novelId: props.novelId,
          includeLibrary: true,
          signal: controller.signal,
        }),
      ]).then(([bindings, profiles]) => {
        if (controller.signal.aborted) return;
        if (bindings.novel_id !== props.novelId) {
          setRosterState({
            phase: "error",
            bindings: [],
            profiles: [],
            message: "人物配音返回了其他作品范围，已阻止显示。",
          });
          return;
        }
        setRosterState({
          phase: "ready",
          bindings: bindings.items,
          profiles: profiles.items,
          message: null,
        });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setRosterState({
            phase: "error",
            bindings: [],
            profiles: [],
            message: overviewErrorMessage(reason),
          });
        }
      });
      return () => controller.abort();
    }, [props.novelId, profileRefreshVersion, overview.settings.version]);
    if (selected === null) {
      return h(
        "section",
        { className: "anw-narration-empty-characters", role: "status" },
        h("h2", null, "人物配音"),
        h("p", null, "当前作品还没有可配置声音的人物。请先在人物卡中新建人物。"),
      );
    }

    return h(
      "section",
      { className: "anw-narration-character-section", "aria-label": "人物配音" },
      rosterState.phase === "loading"
        ? h("p", { role: "status" }, "正在读取人物声音覆盖…")
        : rosterState.phase === "error"
          ? h("p", { role: "alert" }, rosterState.message)
          : h(CharacterVoiceRoster, {
            novelId: props.novelId,
            characters: scopedCharacters,
            bindings: rosterState.bindings,
            profiles: rosterState.profiles,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            onConfigureCharacter: setSelectedCharacterId,
            onMatchOfficialVoice: async (character: {
              readonly characterId: string;
              readonly characterName: string;
            }) => {
              const bindingVersion = rosterState.bindings.find((binding) => (
                binding.character_id === character.characterId
              ))?.version ?? 0;
              const assigned = stableOfficialVoiceAssignment(
                character.characterId,
                overview.settings.values.language,
              );
              const response = await selectOfficialVoiceApi(
                props.novelId,
                {
                  preset_id: assigned.presetId,
                  target_kind: "character",
                  character_id: character.characterId,
                  expected_settings_version: overview.settings.version,
                  expected_binding_version: bindingVersion,
                },
                createOfficialVoiceUseIdempotencyKey(),
              );
              if (!response.selection_still_current) {
                throw new Error("人物声音已被其他操作更新，请刷新后重试。");
              }
              return { voiceName: response.profile.name || assigned.voiceName };
            },
            onBatchCompleted: () => {
              setProfileRefreshVersion((value) => value + 1);
              props.context.onRefresh();
            },
          }),
      h(
        "div",
        { className: "anw-narration-source-summary" },
        h(OfficialVoiceSelectionPanel, {
          key: `official-${selected.characterId}`,
          novelId: props.novelId,
          settings: overview.settings,
          target: {
            kind: "character",
            characterId: selected.characterId,
            characterName: selected.characterName,
          },
          capabilities: overview.capabilities,
          authorization: overview.authorization,
          onChanged: () => {
            setProfileRefreshVersion((value) => value + 1);
            props.context.onRefresh();
          },
        }),
        h(VoiceSourceWorkspace, {
          key: selected.characterId,
          novelId: props.novelId,
          capabilities: overview.capabilities,
          authorization: overview.authorization,
          voiceSources: overview.voice_sources,
          suggestedProfileName: `${selected.characterName}专属声音`,
          onProfileLocked: () => {
            setProfileRefreshVersion((value) => value + 1);
            props.context.onRefresh();
          },
        }),
      ),
      h(CharacterVoicePanel, {
        novelId: props.novelId,
        characterId: selected.characterId,
        characterName: selected.characterName,
        capabilities: overview.capabilities,
        authorization: overview.authorization,
        profileRefreshVersion,
        onSaved: () => {
          setProfileRefreshVersion((value) => value + 1);
          props.context.onRefresh();
        },
      }),
    );
  }

  function VoiceLibrarySection(props: VoiceLibrarySectionProps): unknown {
    const scopedCharacters = props.characters.filter(
      (character) => character.novelId === props.novelId,
    );
    const [targetKey, setTargetKey] = React.useState("narrator");
    const selectedCharacter = targetKey === "narrator"
      ? null
      : scopedCharacters.find((character) => character.characterId === targetKey) ?? null;
    const target = selectedCharacter === null
      ? { kind: "narrator" as const }
      : {
        kind: "character" as const,
        characterId: selectedCharacter.characterId,
        characterName: selectedCharacter.characterName,
      };
    return h(
      "section",
      { className: "anw-narration-voice-library-section", "aria-label": "音色库" },
      h(
        "label",
        { className: "anw-narration-voice-library-target" },
        h("span", null, "使用目标"),
        h(
          "select",
          {
            value: selectedCharacter?.characterId ?? "narrator",
            onChange: (event: { target: { value: string } }) => setTargetKey(event.target.value),
          },
          h("option", { value: "narrator" }, "作品旁白"),
          ...scopedCharacters.map((character) => h(
            "option",
            { key: character.characterId, value: character.characterId },
            `人物 · ${character.characterName}`,
          )),
        ),
      ),
      h(OfficialVoiceSelectionPanel, {
        key: targetKey,
        novelId: props.novelId,
        settings: props.context.overview.settings,
        target,
        capabilities: props.context.overview.capabilities,
        authorization: props.context.overview.authorization,
        onChanged: props.context.onRefresh,
      }),
      h(VoiceSourceWorkspace, {
        novelId: props.novelId,
        capabilities: props.context.overview.capabilities,
        authorization: props.context.overview.authorization,
        voiceSources: props.context.overview.voice_sources,
        suggestedProfileName: "我的朗读音色",
        onProfileLocked: props.context.onRefresh,
      }),
    );
  }

  return function NarrationReadingPage(props: NarrationReadingPageProps): unknown {
    const renderSectionContent = (
      section: Exclude<ReadingSectionKey, "overview" | "narrator">,
      context: ReadingSectionRenderContext,
    ): unknown => {
      const overview = context.overview;
      if (section === "characters") {
        return h(CharacterVoiceSection, {
          novelId: props.novelId,
          characters: props.characters,
          context,
        });
      }
      if (section === "voice-library") {
        return h(VoiceLibrarySection, {
          novelId: props.novelId,
          characters: props.characters,
          context,
        });
      }
      if (section === "reading-rules" || section === "casting-rules" || section === "pronunciation") {
        return h(
          "div",
          { className: "anw-reading-rules-stack" },
          h(ReadingStatus, { overview, onOpenSection: context.onNavigate }),
          h(ReadingRulesWorkspace, {
            novelId: props.novelId,
            settings: overview.settings,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            pronunciationScopeOptions: props.scopeTargets
              .filter((target) => target.novelId === props.novelId)
              .map((target) => ({
                kind: target.scopeKind,
                id: target.scopeId,
                label: target.label,
              })),
            initialSection: props.initialSection === "pronunciation"
              ? "pronunciation"
              : "recognition",
            onSettingsSaved: context.onRefresh,
            onConsentChanged: context.onRefresh,
            onPronunciationSaved: context.onRefresh,
            onRefresh: context.onRefresh,
            onOpenReadingPreferences: () => context.onNavigate("narrator"),
          }),
        );
      }
      if (section !== "storage-privacy" && section !== "audio-cache") return null;
      return h(CachePanel, {
        novelId: props.novelId,
        capabilities: overview.capabilities,
        authorization: overview.authorization,
        onCleaned: context.onRefresh,
      });
    };

    const readingProps: ReadingPageProps = {
      novelId: props.novelId,
      novelTitle: props.novelTitle,
      initialSection: props.initialSection,
      scopeTargets: props.scopeTargets,
      characterOptions: props.characters
        .filter((character) => character.novelId === props.novelId)
        .map((character) => ({
          novelId: character.novelId,
          characterId: character.characterId,
          label: character.characterName,
        })),
      renderNarratorVoiceWorkspace: (context) => h(
        "div",
        { className: "anw-narration-narrator-voice-stack" },
        h(OfficialVoiceSelectionPanel, {
          novelId: props.novelId,
          settings: context.overview.settings,
          target: { kind: "narrator" },
          capabilities: context.overview.capabilities,
          authorization: context.overview.authorization,
          onChanged: context.onRefresh,
        }),
        h(VoiceSourceWorkspace, {
          novelId: props.novelId,
          capabilities: context.overview.capabilities,
          authorization: context.overview.authorization,
          voiceSources: context.overview.voice_sources,
          suggestedProfileName: "作品旁白声音",
          onProfileLocked: context.onRefresh,
        }),
      ),
      renderSectionContent,
      onSectionChange: props.onSectionChange,
    };
    return h(ReadingPage, { ...readingProps });
  };
}


export function createCharacterVoiceCardPanel(
  React: NarrationReactRuntime,
  loadOverview: typeof getNarrationOverview = getNarrationOverview,
  voiceWorkspaceApi?: VoiceSourceWorkspaceApi,
  officialVoiceApi?: OfficialVoiceSelectionPanelApi,
): (props: CharacterVoiceCardPanelProps) => unknown {
  const h = React.createElement;
  const CharacterVoicePanel = createCharacterVoicePanel(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(React, voiceWorkspaceApi);
  const OfficialVoiceSelectionPanel = createOfficialVoiceSelectionPanel(React, officialVoiceApi);

  return function CharacterVoiceCardPanel(props: CharacterVoiceCardPanelProps): unknown {
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [profileRefreshVersion, setProfileRefreshVersion] = React.useState(0);
    const [state, setState] = React.useState<OverviewLoadState>({ phase: "loading" });

    React.useEffect(() => {
      const controller = new AbortController();
      setState({ phase: "loading" });
      void loadOverview(props.novelId, controller.signal).then((overview) => {
        if (controller.signal.aborted) return;
        if (overview.novel_id !== props.novelId) {
          setState({ phase: "error", message: "服务端返回了其他作品的声音权限，已阻止显示。" });
          return;
        }
        setState({ phase: "ready", overview });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setState({ phase: "error", message: overviewErrorMessage(reason) });
        }
      });
      return () => controller.abort();
    }, [props.novelId, props.characterId, reloadVersion]);

    if (state.phase === "loading") {
      return h(
        "div",
        { className: "anw-narration-card-loading", role: "status" },
        "正在加载人物声音…",
      );
    }
    if (state.phase === "error") {
      return h(
        "div",
        { className: "anw-narration-card-error", role: "alert" },
        h("p", null, state.message),
        h(
          "button",
          { type: "button", onClick: () => setReloadVersion((value) => value + 1) },
          "重试",
        ),
      );
    }
    return h(
      "div",
      { className: "anw-narration-character-card-panel" },
      h(OfficialVoiceSelectionPanel, {
        novelId: props.novelId,
        settings: state.overview.settings,
        target: {
          kind: "character",
          characterId: props.characterId,
          characterName: props.characterName,
        },
        capabilities: state.overview.capabilities,
        authorization: state.overview.authorization,
        onChanged: () => {
          setProfileRefreshVersion((value) => value + 1);
          setReloadVersion((value) => value + 1);
        },
      }),
      h(VoiceSourceWorkspace, {
        novelId: props.novelId,
        capabilities: state.overview.capabilities,
        authorization: state.overview.authorization,
        voiceSources: state.overview.voice_sources,
        suggestedProfileName: `${props.characterName}专属声音`,
        onProfileLocked: () => {
          setProfileRefreshVersion((value) => value + 1);
          setReloadVersion((value) => value + 1);
        },
      }),
      h(CharacterVoicePanel, {
        novelId: props.novelId,
        characterId: props.characterId,
        characterName: props.characterName,
        capabilities: state.overview.capabilities,
        authorization: state.overview.authorization,
        profileRefreshVersion,
        onSaved: () => setReloadVersion((value) => value + 1),
        onReturnFocus: props.onReturnFocus,
      }),
    );
  };
}


export type { ReadingScopeTarget, ReadingSectionKey, VoiceProfileResource };
export { createVoiceSourceWorkspace } from "./voice-source-workspace";
export { createOfficialVoiceSelectionPanel } from "./official-voice-selection-panel";
export { createVoicePreviewPlayback } from "./voice-preview-playback";
