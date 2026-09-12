import { apiErrorMessage } from "../api";
import {
  getCharacterVoiceBinding,
  getNarrationOverview,
  listCharacterVoiceBindings,
  listVoiceProfiles,
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
  createCharacterVoiceConfigurator,
  type CharacterVoiceConfiguratorReactRuntime,
} from "./character-voice-configurator";
import {
  createCharacterVoiceRoster,
  type CharacterVoiceRosterReactRuntime,
} from "./character-voice-roster";
import {
  type CharacterVoiceBindingPolicy,
  type CharacterVoiceBindingResource,
  type NarrationOverviewResponse,
  type VoiceProfileResource,
} from "./contracts";
import { NarrationContractError } from "./contracts";
import { officialVoiceProfileDisplayName } from "./voice-display-name";
import type { PronunciationPanelReactRuntime } from "./pronunciation-panel";
import {
  createOfficialVoiceSelectionPanel,
  type CharacterVoiceBindingProjection,
  type OfficialVoiceSelectionPanelApi,
  type OfficialVoiceSelectionPanelProjection,
} from "./official-voice-selection-panel";
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
import {
  createVoiceSourceWorkspace,
  type VoiceSourceWorkspaceApi,
  type VoiceSourceWorkspaceReactRuntime,
} from "./voice-source-workspace";


export interface NarrationCharacterSummary {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly roleType?: "main" | "supporting" | string | null;
}


export interface NarrationReadingPageProps {
  readonly novelId: string;
  readonly novelTitle?: string;
  readonly initialSection?: ReadingSectionKey;
  readonly scopeTargets: readonly ReadingScopeTarget[];
  readonly characters: readonly NarrationCharacterSummary[];
  readonly onSectionChange?: (section: ReadingSectionKey) => void;
  readonly onStartBookNarration?: () => void;
}


export interface CharacterVoiceCardPanelProps {
  readonly novelId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly initialBinding?: CharacterVoiceCardInitialBinding | null;
  readonly initialOverview?: NarrationOverviewResponse;
  readonly initialProfiles?: readonly VoiceProfileResource[];
  readonly onReturnFocus?: () => void;
  readonly onChanged?: () => void;
}


export interface CharacterVoiceCardInitialBinding {
  readonly binding_id: string | null;
  readonly binding_policy: string;
  readonly profile_id: string | null;
  readonly voice_version_id: string | null;
  readonly language: string;
  readonly version: number;
}


export interface CharacterVoiceCardPanelDependencies {}


export interface NarrationReadingPageDependencies {
  readonly readingApi?: ReadingPageApi;
  readonly voiceWorkspaceApi?: VoiceSourceWorkspaceApi;
  readonly officialVoiceApi?: OfficialVoiceSelectionPanelApi;
  readonly characterRosterApi?: Readonly<{
    listBindings: typeof listCharacterVoiceBindings;
  }>;
}


type NarrationReactRuntime = ReadingPageReactRuntime
  & CharacterVoicePanelReactRuntime
  & VoiceSourceWorkspaceReactRuntime
  & PronunciationPanelReactRuntime
  & CachePanelReactRuntime
  & ReadingRulesReactRuntime
  & CharacterVoiceRosterReactRuntime
  & CharacterVoiceConfiguratorReactRuntime;


interface CharacterVoiceSectionProps {
  readonly novelId: string;
  readonly characters: readonly NarrationCharacterSummary[];
  readonly context: ReadingSectionRenderContext;
}


interface VoiceLibrarySectionProps {
  readonly novelId: string;
  readonly context: ReadingSectionRenderContext;
}


type OverviewLoadState =
  | { readonly phase: "loading"; readonly projectionKey: string }
  | { readonly phase: "error"; readonly projectionKey: string; readonly message: string }
  | {
    readonly phase: "ready";
    readonly overview: NarrationOverviewResponse;
    readonly projectionKey: string;
    readonly voiceBindingPhase: "loading" | "ready" | "error";
    readonly voiceProfilesPhase: "loading" | "ready" | "error";
    readonly binding: CharacterVoiceBindingProjection | null;
    readonly profiles: readonly VoiceProfileResource[];
  };


type CurrentVoiceSummary =
  | { readonly kind: "unbound" }
  | { readonly kind: "unresolved" }
  | {
    readonly kind: "resolved";
    readonly name: string;
    readonly sourceLabel: string;
    readonly languageLabel: string;
  };


function voiceLanguageLabel(language: string): string {
  const normalized = language.trim().toLocaleLowerCase("en-US");
  if (normalized === "zh" || normalized.startsWith("zh-")) return "普通话";
  if (normalized === "ja" || normalized.startsWith("ja-")) return "日本語";
  if (normalized === "en" || normalized.startsWith("en-")) return "English";
  return language.trim() || "语言未设置";
}


export { officialVoiceProfileDisplayName } from "./voice-display-name";


function currentVoiceSummary(
  profileId: string | null,
  versionId: string | null,
  language: string,
  profiles: readonly VoiceProfileResource[],
): CurrentVoiceSummary {
  if (profileId === null || versionId === null) {
    return Object.freeze({ kind: "unresolved" });
  }
  const profile = profiles.find((item) => item.profile_id === profileId);
  const version = profile?.versions.find((item) => item.version_id === versionId);
  if (profile === undefined || version === undefined) {
    return Object.freeze({ kind: "unresolved" });
  }
  const sourceLabel = version.source_type === "preset"
    ? "官方音色"
    : version.source_type === "uploaded"
      ? "参考录音音色"
      : "文字设计音色";
  return Object.freeze({
    kind: "resolved",
    name: version.source_type === "preset"
      ? officialVoiceProfileDisplayName(profile.name, version.preset_key)
      : profile.name,
    sourceLabel,
    languageLabel: voiceLanguageLabel(version.language || language),
  });
}


function currentCharacterVoiceSummary(
  binding: CharacterVoiceBindingProjection | null,
  profiles: readonly VoiceProfileResource[],
): CurrentVoiceSummary {
  if (binding === null || binding.binding_policy === "unset") {
    return Object.freeze({ kind: "unbound" });
  }
  return currentVoiceSummary(
    binding.profile_id,
    binding.version_id,
    binding.language,
    profiles,
  );
}


function currentNarratorVoiceSummary(
  narrator: NarrationOverviewResponse["settings"]["values"]["narrator"],
  language: string,
  profiles: readonly VoiceProfileResource[],
): CurrentVoiceSummary {
  if (narrator === null) return Object.freeze({ kind: "unbound" });
  return currentVoiceSummary(
    narrator.profile_id,
    narrator.version_id,
    language,
    profiles,
  );
}


function characterVoiceBindingPolicy(
  value: string,
): CharacterVoiceBindingPolicy | null {
  return value === "dedicated" || value === "inherited" || value === "unset"
    ? value
    : null;
}


function initialCharacterVoiceBindingProjection(
  props: CharacterVoiceCardPanelProps,
  fallbackLanguage: "zh-CN",
): CharacterVoiceBindingProjection | undefined {
  const initial = props.initialBinding;
  if (initial === undefined) return undefined;
  if (initial === null) {
    return Object.freeze({
      binding_id: null,
      novel_id: props.novelId,
      character_id: props.characterId,
      binding_policy: "unset",
      profile_id: null,
      version_id: null,
      language: "zh-CN",
      version: 0,
    });
  }
  const policy = characterVoiceBindingPolicy(initial.binding_policy);
  const hasCompletePair = (initial.profile_id === null) === (initial.voice_version_id === null);
  const validVersion = Number.isSafeInteger(initial.version) && initial.version >= 0;
  const validConfigured = policy === "dedicated" || policy === "inherited"
    ? initial.profile_id !== null && initial.version >= 1
    : policy === "unset"
      ? initial.profile_id === null && initial.version === 0
      : false;
  if (
    policy === null
    || !hasCompletePair
    || !validVersion
    || !validConfigured
    || initial.language !== "zh-CN"
  ) return undefined;
  return Object.freeze({
    binding_id: policy === "unset" ? null : initial.binding_id,
    novel_id: props.novelId,
    character_id: props.characterId,
    binding_policy: policy,
    profile_id: initial.profile_id,
    version_id: initial.voice_version_id,
    language: "zh-CN",
    version: initial.version,
  });
}


function assertCharacterVoiceBindingScope(
  binding: CharacterVoiceBindingProjection,
  novelId: string,
  characterId: string,
): void {
  if (binding.novel_id !== novelId || binding.character_id !== characterId) {
    throw new NarrationContractError(
      "character_voice_binding",
      "response scope mismatch",
    );
  }
}


function overviewErrorMessage(reason: unknown): string {
  return apiErrorMessage(reason, "无法加载人物声音权限，请稍后重试。");
}


export function createNarrationReadingPage(
  React: NarrationReactRuntime,
  dependencies: NarrationReadingPageDependencies = {},
): (props: NarrationReadingPageProps) => unknown {
  const h = React.createElement;
  const ReadingPage = createReadingPage(React, dependencies.readingApi);
  const CharacterVoiceRoster = createCharacterVoiceRoster(React);
  const CharacterVoiceCardPanel = createCharacterVoiceCardPanel(
    React,
    getNarrationOverview,
    dependencies.voiceWorkspaceApi,
    dependencies.officialVoiceApi,
  );
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
  };
  function CharacterVoiceSection(props: CharacterVoiceSectionProps): unknown {
    const scopedCharacters = props.characters.filter(
      (character) => character.novelId === props.novelId,
    );
    const [rosterState, setRosterState] = React.useState<Readonly<{
      phase: "loading" | "ready" | "error";
      bindings: readonly CharacterVoiceBindingResource[];
      message: string | null;
    }>>({ phase: "loading", bindings: [], message: null });
    const overview = props.context.overview;

    React.useEffect(() => {
      const controller = new AbortController();
      setRosterState((current) => current.phase === "ready"
        ? { ...current, message: null }
        : { phase: "loading", bindings: [], message: null });
      void characterRosterApi.listBindings(props.novelId, controller.signal).then((bindings) => {
        if (controller.signal.aborted) return;
        if (bindings.novel_id !== props.novelId) {
          setRosterState({
            phase: "error",
            bindings: [],
            message: "人物配音返回了其他作品范围，已阻止显示。",
          });
          return;
        }
        setRosterState({
          phase: "ready",
          bindings: bindings.items,
          message: null,
        });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setRosterState((current) => ({
            phase: current.phase === "ready" ? "ready" : "error",
            bindings: current.phase === "ready" ? current.bindings : [],
            message: overviewErrorMessage(reason),
          }));
        }
      });
      return () => controller.abort();
    }, [props.novelId, props.context.overview]);

    return h(
      "div",
      { className: "anw-narration-character-section" },
      rosterState.phase === "loading"
        ? h("p", { role: "status" }, "正在读取人物声音覆盖…")
        : rosterState.phase === "error"
          ? h("p", { role: "alert" }, rosterState.message)
          : h(
            "div",
            null,
            rosterState.message
              ? h("p", { role: "alert" }, rosterState.message)
              : null,
            props.context.voiceProfilesError
              ? h("p", { role: "alert" }, props.context.voiceProfilesError)
              : null,
            h(CharacterVoiceRoster, {
            novelId: props.novelId,
            characters: scopedCharacters,
            bindings: rosterState.bindings,
            profiles: props.context.voiceProfiles,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            onConfigureCharacter: () => undefined,
            renderConfigurator: (character: {
              readonly characterId: string;
              readonly characterName: string;
            }) => {
              const binding = rosterState.bindings.find((item) => (
                item.character_id === character.characterId
              ));
              return h(CharacterVoiceCardPanel, {
                key: `character-configurator:${character.characterId}`,
                novelId: props.novelId,
                characterId: character.characterId,
                characterName: character.characterName,
                initialOverview: overview,
                initialProfiles: props.context.voiceProfiles,
                initialBinding: binding === undefined
                  ? undefined
                  : {
                    binding_id: binding.binding_id,
                    binding_policy: binding.binding_policy,
                    profile_id: binding.profile_id,
                    voice_version_id: binding.version_id,
                    language: binding.language,
                    version: binding.version,
                  },
                onChanged: props.context.onRefresh,
              });
            },
            }),
          ),
    );
  }

  function VoiceLibrarySection(props: VoiceLibrarySectionProps): unknown {
    const overview = props.context.overview;
    const editorId = `anw-narrator-voice-library-${props.novelId}`;
    const currentVoice = props.context.voiceProfilesError === null
      ? currentNarratorVoiceSummary(
          overview.settings.values.narrator,
          overview.settings.values.language,
          props.context.voiceProfiles,
        )
      : null;
    const profileProjection: OfficialVoiceSelectionPanelProjection | undefined =
      props.context.voiceProfilesError === null
        ? { phase: "ready", binding: null, profiles: props.context.voiceProfiles }
        : undefined;
    const publishChanged = (): void => {
      props.context.onRefresh();
    };

    return h(
      "section",
      { className: "anw-narration-voice-library-section", "aria-label": "旁白官方音色" },
      h(
        "article",
        { className: "anw-narrator-current-voice" },
        h(
          "div",
          { className: "anw-narrator-current-voice__copy" },
          h("span", null, "当前旁白"),
          props.context.voiceProfilesError !== null
            ? h("strong", null, "当前声音暂不可用")
            : currentVoice?.kind === "resolved"
                ? h("strong", null, currentVoice.name)
                : currentVoice?.kind === "unbound"
                  ? h("strong", null, "尚未配置")
                  : h("strong", null, "已绑定，详情待恢复"),
          props.context.voiceProfilesError === null && currentVoice?.kind === "resolved"
            ? h("small", null, `${currentVoice.sourceLabel} · ${currentVoice.languageLabel}`)
            : props.context.voiceProfilesError !== null
              ? h("small", { role: "alert" }, props.context.voiceProfilesError)
              : h("small", null, "尚未选择时，将在下方直接设置。"),
        ),
        props.context.voiceProfilesError !== null
          ? h(
            "div",
            { className: "anw-narrator-current-voice__actions" },
            h("button", {
              type: "button",
              className: "anw-narration-secondary-action",
              onClick: props.context.onRefresh,
            }, "重新读取")
          )
          : null,
      ),
      h("div", { id: editorId, className: "anw-narrator-voice-library-editor" },
        h(OfficialVoiceSelectionPanel, {
          key: "narrator",
          novelId: props.novelId,
          settings: overview.settings,
          target: { kind: "narrator" },
          capabilities: overview.capabilities,
          authorization: overview.authorization,
          projection: profileProjection,
          onChanged: publishChanged,
        }),
      ),
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
          context,
        });
      }
      if (section === "private-voices") {
        const privateSourceCreationAvailable = overview.voice_sources.some((source) => (
          source.available && (source.source_type === "uploaded" || source.source_type === "generated")
        ));
        return h(
          "div",
          { className: "anw-narration-private-stack" },
          privateSourceCreationAvailable
            ? h(VoiceSourceWorkspace, {
              novelId: props.novelId,
              capabilities: overview.capabilities,
              authorization: overview.authorization,
              voiceSources: overview.voice_sources,
              suggestedProfileName: "我的朗读音色",
              onProfileLocked: context.onRefresh,
            })
            : h("p", { role: "status", className: "anw-reading-empty" },
              "私人音色暂不可用，请在运行与存储中检查本地语音服务。"),
        );
      }
      if (section === "reading-rules" || section === "casting-rules" || section === "pronunciation") {
        return h(
          "div",
          { className: "anw-reading-rules-stack" },
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
      return h("div", { className: "anw-narration-private-stack" },
      h(ReadingStatus, { overview, onOpenSection: context.onNavigate }),
      h(CachePanel, {
        novelId: props.novelId,
        capabilities: overview.capabilities,
        authorization: overview.authorization,
        onCleaned: context.onRefresh,
      }));
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
      renderNarratorVoiceWorkspace: (context) => {
        const voice = context.voiceProfilesError === null
          ? currentNarratorVoiceSummary(context.overview.settings.values.narrator,
            context.overview.settings.values.language, context.voiceProfiles)
          : null;
        return h("section", { className: "anw-narrator-current-voice", "aria-label": "当前旁白" },
          h("div", { className: "anw-narrator-current-voice__copy" },
            h("span", null, "当前旁白"),
            h("strong", null, voice?.kind === "resolved" ? voice.name
              : voice?.kind === "unbound" ? "尚未选择旁白" : "声音详情暂不可用"),
            h("small", null, "更换声音后，请在章节页更新朗读。")),
          h("div", { className: "anw-narrator-current-voice__actions" },
            h("button", { type: "button", onClick: () => context.onNavigate("voice-library") }, "选择旁白音色")),
        );
      },
      renderSectionContent,
      onSectionChange: props.onSectionChange,
      onStartBookNarration: props.onStartBookNarration,
    };
    return h(ReadingPage, { ...readingProps });
  };
}


export function createCharacterVoiceCardPanel(
  React: NarrationReactRuntime,
  loadOverview: typeof getNarrationOverview = getNarrationOverview,
  voiceWorkspaceApi?: VoiceSourceWorkspaceApi,
  officialVoiceApi?: OfficialVoiceSelectionPanelApi,
  _dependencies: CharacterVoiceCardPanelDependencies = {},
): (props: CharacterVoiceCardPanelProps) => unknown {
  const h = React.createElement;
  const CharacterVoiceConfigurator = createCharacterVoiceConfigurator(React);
  const CharacterVoicePanel = createCharacterVoicePanel(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(React, voiceWorkspaceApi);
  const OfficialVoiceSelectionPanel = createOfficialVoiceSelectionPanel(React, officialVoiceApi);
  const getBinding = officialVoiceApi?.getCharacterVoiceBinding ?? getCharacterVoiceBinding;
  const getProfiles = officialVoiceApi?.listVoiceProfiles ?? listVoiceProfiles;

  interface CharacterVoiceAdvancedPanelProps {
    readonly novelId: string;
    readonly characterId: string;
    readonly characterName: string;
    readonly overview: NarrationOverviewResponse;
    readonly profileRefreshVersion: number;
    readonly onProfileChanged: () => void;
    readonly onVoiceSaved: () => void;
    readonly onReturnFocus?: () => void;
  }

  function CharacterVoiceAdvancedPanel(
    advancedProps: CharacterVoiceAdvancedPanelProps,
  ): unknown {
    const scopeKey = `${advancedProps.novelId}:${advancedProps.characterId}`;
    return h(
      "div",
      {
        className: "anw-character-voice-advanced-stack",
        "data-character-voice-scope": scopeKey,
      },
      h(VoiceSourceWorkspace, {
        novelId: advancedProps.novelId,
        capabilities: advancedProps.overview.capabilities,
        authorization: advancedProps.overview.authorization,
        voiceSources: advancedProps.overview.voice_sources,
        suggestedProfileName: `${advancedProps.characterName}专属声音`,
        onProfileLocked: advancedProps.onProfileChanged,
      }),
      h(CharacterVoicePanel, {
        novelId: advancedProps.novelId,
        characterId: advancedProps.characterId,
        characterName: advancedProps.characterName,
        capabilities: advancedProps.overview.capabilities,
        authorization: advancedProps.overview.authorization,
        presentation: "embedded",
        allowedSourceTypes: ["uploaded"],
        profileRefreshVersion: advancedProps.profileRefreshVersion,
        onSaved: advancedProps.onVoiceSaved,
        onReturnFocus: advancedProps.onReturnFocus,
      }),
    );
  }

  return function CharacterVoiceCardPanel(props: CharacterVoiceCardPanelProps): unknown {
    const scopeKey = `${props.novelId}:${props.characterId}`;
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [profileRefreshVersion, setProfileRefreshVersion] = React.useState(0);
    const projectionKey = `${scopeKey}:${reloadVersion}`;
    const [state, setState] = React.useState<OverviewLoadState>(() => ({
      phase: "loading",
      projectionKey,
    }));
    const currentScopeRef = React.useRef(scopeKey);
    const initialBindingScopeRef = React.useRef<string | null>(null);
    currentScopeRef.current = scopeKey;

    React.useEffect(() => {
      const controller = new AbortController();
      setState({ phase: "loading", projectionKey });
      if (reloadVersion === 0 && props.initialOverview !== undefined) {
        if (props.initialOverview.novel_id !== props.novelId) {
          setState({
            phase: "error",
            projectionKey,
            message: "页面缓存了其他作品的声音权限，已阻止显示。",
          });
          return () => controller.abort();
        }
        const initialBinding = initialCharacterVoiceBindingProjection(
          props,
          props.initialOverview.settings.values.language,
        );
        if (initialBinding !== undefined) initialBindingScopeRef.current = scopeKey;
        setState({
          phase: "ready",
          overview: props.initialOverview,
          projectionKey,
          voiceBindingPhase: initialBinding === undefined ? "loading" : "ready",
          voiceProfilesPhase: props.initialProfiles === undefined ? "loading" : "ready",
          binding: initialBinding ?? null,
          profiles: props.initialProfiles ?? [],
        });
        return () => controller.abort();
      }
      void loadOverview(props.novelId, controller.signal).then((overview) => {
        if (controller.signal.aborted || currentScopeRef.current !== scopeKey) return;
        if (overview.novel_id !== props.novelId) {
          setState({
            phase: "error",
            projectionKey,
            message: "服务端返回了其他作品的声音权限，已阻止显示。",
          });
          return;
        }
        const initialBinding = initialCharacterVoiceBindingProjection(
          props,
          overview.settings.values.language,
        );
        const useInitialBinding = initialBinding !== undefined
          && initialBindingScopeRef.current !== scopeKey;
        if (useInitialBinding) initialBindingScopeRef.current = scopeKey;
        setState({
          phase: "ready",
          overview,
          projectionKey,
          voiceBindingPhase: useInitialBinding ? "ready" : "loading",
          voiceProfilesPhase: "loading",
          binding: useInitialBinding ? initialBinding : null,
          profiles: [],
        });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && currentScopeRef.current === scopeKey) {
          setState({
            phase: "error",
            projectionKey,
            message: overviewErrorMessage(reason),
          });
        }
      });
      return () => controller.abort();
    }, [props.novelId, props.characterId, reloadVersion]);

    React.useEffect(() => {
      if (state.phase !== "ready") return;
      if (profileRefreshVersion === 0
        && state.voiceBindingPhase !== "loading" && state.voiceProfilesPhase !== "loading") return;
      const controller = new AbortController();
      const projectionKey = state.projectionKey;
      if (state.voiceBindingPhase === "loading" || profileRefreshVersion > 0) {
        void getBinding(
          props.novelId,
          props.characterId,
          controller.signal,
        ).then((binding) => {
          if (controller.signal.aborted) return;
          assertCharacterVoiceBindingScope(binding, props.novelId, props.characterId);
          setState((current) => current.phase === "ready"
            && current.projectionKey === projectionKey
            ? {
              ...current,
              voiceBindingPhase: "ready",
              binding,
            }
            : current);
        }).catch(() => {
          if (controller.signal.aborted) return;
          setState((current) => current.phase === "ready"
            && current.projectionKey === projectionKey
            ? { ...current, voiceBindingPhase: "error", binding: null }
            : current);
        });
      }
      if (state.voiceProfilesPhase === "loading" || profileRefreshVersion > 0) {
        void getProfiles({
          novelId: props.novelId,
          includeLibrary: true,
          signal: controller.signal,
        }).then((profileList) => {
          if (controller.signal.aborted) return;
          setState((current) => current.phase === "ready"
            && current.projectionKey === projectionKey
            ? {
              ...current,
              voiceProfilesPhase: "ready",
              profiles: profileList.items,
            }
            : current);
        }).catch(() => {
          if (controller.signal.aborted) return;
          setState((current) => current.phase === "ready"
            && current.projectionKey === projectionKey
            ? { ...current, voiceProfilesPhase: "error", profiles: [] }
            : current);
        });
      }
      return () => controller.abort();
    }, [state.phase === "ready" ? state.projectionKey : null, profileRefreshVersion]);

    if (state.projectionKey !== projectionKey) {
      return h(
        "div",
        { className: "anw-narration-card-loading", role: "status" },
        "正在加载人物声音…",
      );
    }

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
    const currentVoice = state.voiceBindingPhase === "ready"
      ? currentCharacterVoiceSummary(state.binding, state.profiles)
      : null;
    const currentVoicePhase = state.voiceBindingPhase === "loading"
      ? "loading" as const
      : state.voiceBindingPhase === "error"
        ? "error" as const
        : currentVoice?.kind === "unbound"
          ? "unbound" as const
          : state.voiceProfilesPhase === "loading"
            ? "loading" as const
            : state.voiceProfilesPhase === "error" || currentVoice?.kind === "unresolved"
              ? "unresolved" as const
              : "resolved" as const;
    const officialVoiceProjection: OfficialVoiceSelectionPanelProjection =
      state.voiceBindingPhase === "error"
        ? {
          phase: "error",
          message: "无法读取当前人物的声音绑定，请刷新后重试。",
        }
        : state.voiceBindingPhase === "loading" || state.voiceProfilesPhase === "loading"
          ? { phase: "loading" }
          : {
            phase: "ready",
            binding: state.binding,
            profiles: state.voiceProfilesPhase === "ready" ? state.profiles : [],
          };
    const publishChanged = (): void => {
      setProfileRefreshVersion((value) => value + 1);
      props.onChanged?.();
    };
    const officialVoiceContent = h(OfficialVoiceSelectionPanel, {
        novelId: props.novelId,
        settings: state.overview.settings,
        target: {
          kind: "character",
          characterId: props.characterId,
          characterName: props.characterName,
        },
        capabilities: state.overview.capabilities,
        authorization: state.overview.authorization,
        projection: officialVoiceProjection,
        presentation: "embedded",
        onChanged: publishChanged,
      });
    const advancedContent = h(CharacterVoiceAdvancedPanel, {
        key: `character-voice-advanced:${props.novelId}:${props.characterId}`,
        novelId: props.novelId,
        characterId: props.characterId,
        characterName: props.characterName,
        overview: state.overview,
        profileRefreshVersion,
        onProfileChanged: publishChanged,
        onVoiceSaved: publishChanged,
        onReturnFocus: props.onReturnFocus,
      });
    return h(CharacterVoiceConfigurator, {
      scopeId: scopeKey,
      characterId: props.characterId,
      characterName: props.characterName,
      currentVoice: {
        phase: currentVoicePhase,
        name: currentVoice?.kind === "resolved" ? currentVoice.name : null,
        sourceLabel: currentVoice?.kind === "resolved" ? currentVoice.sourceLabel : null,
        languageLabel: currentVoice?.kind === "resolved" ? currentVoice.languageLabel : null,
        message: currentVoicePhase === "error"
          ? "当前声音绑定暂时无法读取；为避免覆盖并发修改，直接选择已暂停。"
          : currentVoicePhase === "unbound"
            ? "尚未单独绑定，将按当前朗读规则选择声音。"
            : currentVoicePhase === "unresolved"
              ? "已保存人物声音绑定，但音色详情暂时不可用。"
              : undefined,
      },
      canConfigure: state.overview.authorization.can_configure,
      showMatch: false,
      matchEnabled: false,
      matchDisabledReason: "Qwen 轻量版本只保留手动选择官方音色。",
      officialVoiceContent,
      advancedContent,
      className: "anw-narration-character-card-panel",
      onChanged: publishChanged,
    });
  };
}


export type { ReadingScopeTarget, ReadingSectionKey, VoiceProfileResource };
export { createVoiceSourceWorkspace } from "./voice-source-workspace";
export { createOfficialVoiceSelectionPanel } from "./official-voice-selection-panel";
export { createVoicePreviewPlayback } from "./voice-preview-playback";
