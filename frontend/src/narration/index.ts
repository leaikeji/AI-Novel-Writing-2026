import { getNarrationOverview } from "./api";
import {
  createCachePanel,
  type CachePanelReactRuntime,
} from "./cache-panel";
import {
  createCharacterVoicePanel,
  type CharacterVoicePanelReactRuntime,
} from "./character-voice-panel";
import type {
  NarrationOverviewResponse,
  VoiceProfileResource,
} from "./contracts";
import {
  createPronunciationPanel,
  type PronunciationPanelReactRuntime,
} from "./pronunciation-panel";
import {
  createReadingPage,
  type ReadingPageProps,
  type ReadingPageApi,
  type ReadingPageReactRuntime,
  type ReadingScopeTarget,
  type ReadingSectionRenderContext,
} from "./reading-page";
import {
  createReadingRulesPanel,
  type ReadingRulesReactRuntime,
} from "./reading-rules-panel";
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
}


type NarrationReactRuntime = ReadingPageReactRuntime
  & CharacterVoicePanelReactRuntime
  & VoiceSourceWorkspaceReactRuntime
  & PronunciationPanelReactRuntime
  & CachePanelReactRuntime
  & ReadingRulesReactRuntime;


interface CharacterVoiceSectionProps {
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


export function createNarrationReadingPage(
  React: NarrationReactRuntime,
  dependencies: NarrationReadingPageDependencies = {},
): (props: NarrationReadingPageProps) => unknown {
  const h = React.createElement;
  const ReadingPage = createReadingPage(React, dependencies.readingApi);
  const CharacterVoicePanel = createCharacterVoicePanel(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(
    React,
    dependencies.voiceWorkspaceApi,
  );
  const PronunciationPanel = createPronunciationPanel(React);
  const CachePanel = createCachePanel(React);
  const ReadingRulesPanel = createReadingRulesPanel(React);
  const ReadingStatus = createReadingStatus(React);

  function CharacterVoiceSection(props: CharacterVoiceSectionProps): unknown {
    const scopedCharacters = props.characters.filter(
      (character) => character.novelId === props.novelId,
    );
    const [selectedCharacterId, setSelectedCharacterId] = React.useState(
      scopedCharacters[0]?.characterId ?? "",
    );
    const [profileRefreshVersion, setProfileRefreshVersion] = React.useState(0);
    const selected = scopedCharacters.find(
      (character) => character.characterId === selectedCharacterId,
    ) ?? scopedCharacters[0] ?? null;
    const overview = props.context.overview;
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
      h(
        "ul",
        { className: "anw-narration-character-picker", "aria-label": "选择人物" },
        ...scopedCharacters.map((character) => h(
          "li",
          { key: character.characterId },
          h(
            "button",
            {
              type: "button",
              className: character.characterId === selected.characterId ? "is-active" : "",
              "aria-pressed": character.characterId === selected.characterId,
              onClick: () => setSelectedCharacterId(character.characterId),
            },
            character.characterName,
          ),
        )),
      ),
      h(
        "div",
        { className: "anw-narration-source-summary" },
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
        onSaved: props.context.onRefresh,
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
      if (section === "casting-rules") {
        return h(
          "div",
          { className: "anw-reading-rules-stack" },
          h(ReadingStatus, { overview, onOpenSection: context.onNavigate }),
          h(ReadingRulesPanel, {
            novelId: props.novelId,
            settings: overview.settings,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            onSettingsSaved: context.onRefresh,
            onConsentChanged: context.onRefresh,
            onRefresh: context.onRefresh,
          }),
        );
      }
      if (section === "pronunciation") {
        return h(PronunciationPanel, {
          novelId: props.novelId,
          capabilities: overview.capabilities,
          authorization: overview.authorization,
          scopeOptions: props.scopeTargets
            .filter((target) => target.novelId === props.novelId)
            .map((target) => ({
              kind: target.scopeKind,
              id: target.scopeId,
              label: target.label,
            })),
          timing: overview.settings.values.timing,
          onOpenReadingSettings: () => context.onNavigate("narrator"),
          onSaved: context.onRefresh,
        });
      }
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
      renderNarratorVoiceWorkspace: (context) => h(VoiceSourceWorkspace, {
        novelId: props.novelId,
        capabilities: context.overview.capabilities,
        authorization: context.overview.authorization,
        voiceSources: context.overview.voice_sources,
        suggestedProfileName: "作品旁白声音",
        onProfileLocked: context.onRefresh,
      }),
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
): (props: CharacterVoiceCardPanelProps) => unknown {
  const h = React.createElement;
  const CharacterVoicePanel = createCharacterVoicePanel(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(React, voiceWorkspaceApi);

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
export { createVoicePreviewPlayback } from "./voice-preview-playback";
