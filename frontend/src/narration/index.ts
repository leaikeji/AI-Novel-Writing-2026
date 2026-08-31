import { apiErrorMessage } from "../api";
import {
  applyCharacterVoiceGeneratorCommand,
  cancelCharacterVoiceGeneratorCommand,
  createCharacterVoiceGeneratorCommand,
  createOfficialVoicePreview,
  getCharacterVoiceGeneratorCommand,
  getCharacterVoiceBinding,
  getVoicePreview,
  getNarrationOverview,
  listCharacterVoiceBindings,
  listCharacterVoiceGeneratorCommands,
  listVoiceProfiles,
  listNanoVoiceExperiments,
  matchCharacterOfficialVoice,
  retryCharacterVoiceGeneratorCommand,
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
import {
  createCharacterVoiceGenerator,
  type CharacterVoiceGenerationSnapshot,
  type CharacterVoiceGeneratorReactRuntime,
} from "./character-voice-generator";
import type {
  CharacterVoiceGeneratorCommandResource,
  CharacterVoiceBindingResource,
  NarrationOverviewResponse,
  OfficialPresetId,
  VoiceProfileResource,
} from "./contracts";
import type { PronunciationPanelReactRuntime } from "./pronunciation-panel";
import {
  createOfficialVoiceSelectionPanel,
  createAndPlayOfficialVoicePreview,
  type OfficialVoiceSelectionPanelApi,
} from "./official-voice-selection-panel";
import { createOfficialVoiceUseIdempotencyKey } from "./official-voice-use-state";
import { playReadyVoicePreview } from "./voice-preview-playback";
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
import {
  createNanoAdvancedWorkspace,
  createPrivateVoiceLifecycleWorkspace,
} from "./voice-feature-workspaces";


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
  readonly matchCharacterOfficialVoice?: typeof matchCharacterOfficialVoice;
  readonly listNanoVoiceExperiments?: typeof listNanoVoiceExperiments;
}


type NarrationReactRuntime = ReadingPageReactRuntime
  & CharacterVoicePanelReactRuntime
  & VoiceSourceWorkspaceReactRuntime
  & PronunciationPanelReactRuntime
  & CachePanelReactRuntime
  & ReadingRulesReactRuntime
  & CharacterVoiceRosterReactRuntime
  & CharacterVoiceGeneratorReactRuntime;


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
  | {
    readonly phase: "ready";
    readonly overview: NarrationOverviewResponse;
    readonly bindingVersion: number | null;
  };


function characterVoiceGeneratorSnapshot(
  command: CharacterVoiceGeneratorCommandResource,
): CharacterVoiceGenerationSnapshot {
  return {
    contractVersion: command.contract_version,
    commandId: command.command_id,
    draftId: command.draft_id,
    characterId: command.character_id,
    state: command.state,
    progressPercent: Math.round(
      (command.progress_current / command.progress_total) * 100,
    ),
    cancellable: command.cancellable,
    retryable: command.retryable,
    terminal: command.terminal,
    failureCode: command.failure_code,
    generatedVersionId: command.voice_version_id,
    selectionStillCurrent: command.selection_still_current,
    currentBindingVersion: command.current_character_binding.version,
    createdAt: command.created_at,
    updatedAt: command.updated_at,
  };
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
  const NanoAdvancedWorkspace = createNanoAdvancedWorkspace(React);
  const PrivateVoiceLifecycleWorkspace = createPrivateVoiceLifecycleWorkspace(React);
  const characterRosterApi = dependencies.characterRosterApi ?? {
    listBindings: listCharacterVoiceBindings,
    listProfiles: listVoiceProfiles,
  };
  const selectOfficialVoiceApi = dependencies.officialVoiceApi?.selectOfficialVoice
    ?? selectOfficialVoice;
  const matchCharacterOfficialVoiceApi = dependencies.matchCharacterOfficialVoice
    ?? matchCharacterOfficialVoice;
  const listNanoVoiceExperimentsApi = dependencies.listNanoVoiceExperiments
    ?? listNanoVoiceExperiments;
  const officialPreviewApi = {
    createOfficialVoicePreview: dependencies.officialVoiceApi?.createOfficialVoicePreview
      ?? createOfficialVoicePreview,
    getVoicePreview: dependencies.officialVoiceApi?.getVoicePreview ?? getVoicePreview,
  };

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
            onPreviewVoice: async (
              _character: { readonly characterId: string; readonly characterName: string },
              _profile: VoiceProfileResource,
              version: VoiceProfileResource["versions"][number],
            ) => {
              if (version.source_type === "preset" && version.preset_key) {
                await createAndPlayOfficialVoicePreview(
                  officialPreviewApi,
                  { play: playReadyVoicePreview },
                  props.novelId,
                  version.preset_key as OfficialPresetId,
                  new AbortController().signal,
                );
                return;
              }
              if (version.source_type === "generated") {
                const experiments = await listNanoVoiceExperimentsApi(props.novelId);
                const ready = experiments.items.find((item) => (
                  item.version_id === version.version_id
                  && item.preview?.status === "ready"
                ));
                if (ready?.preview === null || ready?.preview === undefined) {
                  throw new Error("当前高级调音试听已过期，请重新创建并使用。");
                }
                await playReadyVoicePreview(
                  ready.preview,
                  new AbortController().signal,
                );
                return;
              }
              throw new Error("当前人物音色没有可播放的临时试听。");
            },
            onMatchOfficialVoice: async (character: {
              readonly characterId: string;
              readonly characterName: string;
            }) => {
              const bindingVersion = rosterState.bindings.find((binding) => (
                binding.character_id === character.characterId
              ))?.version ?? 0;
              const response = await matchCharacterOfficialVoiceApi(
                props.novelId,
                character.characterId,
                {
                  contract_version: "character-voice-match-request/1",
                  timeline_id: null,
                  character_instance_id: null,
                  expected_binding_version: bindingVersion,
                },
                createOfficialVoiceUseIdempotencyKey(),
              );
              return {
                voiceName: response.selected_preset_id.replace(/^onnx\./, ""),
                presetId: response.selected_preset_id,
                selectionStillCurrent: response.selection_still_current,
              };
            },
            onUseMatchedOfficialVoice: async (
              character: { readonly characterId: string; readonly characterName: string },
              presetId: string,
            ) => {
              const [latestOverview, latestBinding] = await Promise.all([
                getNarrationOverview(props.novelId),
                getCharacterVoiceBinding(props.novelId, character.characterId),
              ]);
              const response = await selectOfficialVoiceApi(
                props.novelId,
                {
                  preset_id: presetId as OfficialPresetId,
                  target_kind: "character",
                  character_id: character.characterId,
                  expected_settings_version: latestOverview.settings.version,
                  expected_binding_version: latestBinding.version,
                },
                createOfficialVoiceUseIdempotencyKey(),
              );
              return {
                voiceName: response.profile.name || presetId.replace(/^onnx\./, ""),
                presetId,
                selectionStillCurrent: response.selection_still_current,
              };
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
      if (section === "advanced-tuning") {
        return h(NanoAdvancedWorkspace, {
          novelId: props.novelId,
          overview,
          characters: props.characters
            .filter((character) => character.novelId === props.novelId),
          onChanged: context.onRefresh,
        });
      }
      if (section === "private-voices") {
        const privateSourceCreationAvailable = overview.voice_sources.some((source) => (
          source.available && source.source_type === "uploaded"
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
            : null,
          h(PrivateVoiceLifecycleWorkspace, {
            novelId: props.novelId,
            overview,
            onChanged: context.onRefresh,
          }),
          h(CachePanel, {
            novelId: props.novelId,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            onCleaned: context.onRefresh,
          }),
        );
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
        h(ReadingStatus, {
          overview: context.overview,
          onOpenSection: context.onNavigate,
        }),
        h(ReadingRulesWorkspace, {
          novelId: props.novelId,
          settings: context.overview.settings,
          capabilities: context.overview.capabilities,
          authorization: context.overview.authorization,
          pronunciationScopeOptions: props.scopeTargets
            .filter((target) => target.novelId === props.novelId)
            .map((target) => ({
              kind: target.scopeKind,
              id: target.scopeId,
              label: target.label,
            })),
          initialSection: "recognition",
          onSettingsSaved: context.onRefresh,
          onConsentChanged: context.onRefresh,
          onPronunciationSaved: context.onRefresh,
          onRefresh: context.onRefresh,
          onOpenReadingPreferences: () => undefined,
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
  const CharacterVoiceGenerator = createCharacterVoiceGenerator(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(React, voiceWorkspaceApi);
  const OfficialVoiceSelectionPanel = createOfficialVoiceSelectionPanel(React, officialVoiceApi);

  return function CharacterVoiceCardPanel(props: CharacterVoiceCardPanelProps): unknown {
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [profileRefreshVersion, setProfileRefreshVersion] = React.useState(0);
    const [state, setState] = React.useState<OverviewLoadState>({ phase: "loading" });
    const [matchBusy, setMatchBusy] = React.useState(false);
    const [matchMessage, setMatchMessage] = React.useState<string | null>(null);
    const [matchFailed, setMatchFailed] = React.useState(false);
    const [unappliedPresetId, setUnappliedPresetId] = React.useState<OfficialPresetId | null>(null);

    React.useEffect(() => {
      const controller = new AbortController();
      setState({ phase: "loading" });
      void loadOverview(props.novelId, controller.signal).then((overview) => {
        if (controller.signal.aborted) return;
        if (overview.novel_id !== props.novelId) {
          setState({ phase: "error", message: "服务端返回了其他作品的声音权限，已阻止显示。" });
          return;
        }
        setState({ phase: "ready", overview, bindingVersion: null });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setState({ phase: "error", message: overviewErrorMessage(reason) });
        }
      });
      return () => controller.abort();
    }, [props.novelId, props.characterId, reloadVersion]);

    React.useEffect(() => {
      if (state.phase !== "ready" || state.bindingVersion !== null) return;
      const controller = new AbortController();
      void getCharacterVoiceBinding(
        props.novelId,
        props.characterId,
        controller.signal,
      ).then((binding) => {
        if (
          controller.signal.aborted
          || binding.novel_id !== props.novelId
          || binding.character_id !== props.characterId
        ) return;
        setState((current) => current.phase === "ready"
          ? { ...current, bindingVersion: binding.version }
          : current);
      }).catch(() => {
        // VoiceGenerator stays fail-closed; official and existing private
        // voice controls remain usable when this optional projection fails.
      });
      return () => controller.abort();
    }, [props.novelId, props.characterId, state.phase, state.phase === "ready" ? state.bindingVersion : null]);

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
    const matchCapability = capabilityFor(state.overview, "character_voice_matching");
    const matchEnabled = matchCapability.state === "enabled"
      && matchCapability.visible
      && matchCapability.actionable
      && state.overview.authorization.can_configure;
    const generatorCapability = capabilityFor(state.overview, "voice_generator");
    const generatorEnabled = generatorCapability.state === "enabled"
      && generatorCapability.visible
      && generatorCapability.actionable;
    const matchAndUse = async (): Promise<void> => {
      if (!matchEnabled || matchBusy) return;
      setMatchBusy(true);
      setMatchFailed(false);
      setMatchMessage("正在分析已保存的人物卡并匹配官方音色…");
      try {
        const binding = await getCharacterVoiceBinding(props.novelId, props.characterId);
        const matched = await matchCharacterOfficialVoice(
          props.novelId,
          props.characterId,
          {
            contract_version: "character-voice-match-request/1",
            timeline_id: null,
            character_instance_id: null,
            expected_binding_version: binding.version,
          },
          createOfficialVoiceUseIdempotencyKey(),
        );
        setUnappliedPresetId(
          matched.selection_still_current ? null : matched.selected_preset_id,
        );
        setMatchMessage(matched.selection_still_current
          ? `已匹配并使用 ${matched.selected_preset_id.replace(/^onnx\./, "")}。`
          : `已匹配 ${matched.selected_preset_id.replace(/^onnx\./, "")}，但没有覆盖你刚修改的音色。`);
        setProfileRefreshVersion((value) => value + 1);
        setReloadVersion((value) => value + 1);
      } catch (reason: unknown) {
        setMatchFailed(true);
        setMatchMessage(overviewErrorMessage(reason));
      } finally {
        setMatchBusy(false);
      }
    };
    const useMatched = async (): Promise<void> => {
      if (unappliedPresetId === null || matchBusy) return;
      setMatchBusy(true);
      setMatchMessage("正在使用已匹配的官方音色…");
      try {
        const [latestOverview, latestBinding] = await Promise.all([
          loadOverview(props.novelId),
          getCharacterVoiceBinding(props.novelId, props.characterId),
        ]);
        const selected = await selectOfficialVoice(
          props.novelId,
          {
            preset_id: unappliedPresetId,
            target_kind: "character",
            character_id: props.characterId,
            expected_settings_version: latestOverview.settings.version,
            expected_binding_version: latestBinding.version,
          },
          createOfficialVoiceUseIdempotencyKey(),
        );
        if (!selected.selection_still_current) throw new Error("人物声音又发生了变化，请刷新后重试。");
        setMatchMessage(`已使用 ${unappliedPresetId.replace(/^onnx\./, "")}。`);
        setUnappliedPresetId(null);
        setProfileRefreshVersion((value) => value + 1);
        setReloadVersion((value) => value + 1);
      } catch (reason: unknown) {
        setMatchMessage(overviewErrorMessage(reason));
      } finally {
        setMatchBusy(false);
      }
    };
    return h(
      "div",
      { className: "anw-narration-character-card-panel" },
      matchEnabled
        ? h(
          "section",
          { className: "anw-character-card-voice-match", "aria-label": "人物卡一键配音" },
          h("button", {
            type: "button",
            disabled: matchBusy,
            onClick: () => { void matchAndUse(); },
          }, matchBusy
            ? "正在匹配…"
            : matchFailed
              ? "一键重试"
              : "根据人物卡匹配并使用官方音色"),
          unappliedPresetId !== null
            ? h("button", {
              type: "button",
              disabled: matchBusy,
              onClick: () => { void useMatched(); },
            }, "使用此音色")
            : null,
          matchMessage
            ? h("p", { role: "status", "aria-live": "polite" }, matchMessage)
            : null,
        )
        : null,
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
      state.bindingVersion === null ? null : h(CharacterVoiceGenerator, {
        capabilityEnabled: generatorEnabled,
        canConfigure: state.overview.authorization.can_configure,
        characterId: props.characterId,
        characterName: props.characterName,
        expectedBindingVersion: state.bindingVersion,
        workspaceSelection: {
          timelineId: null,
          characterInstanceId: null,
        },
        onLoadLatest: async (
          characterId: string,
          signal: AbortSignal,
        ) => {
          const commands = await listCharacterVoiceGeneratorCommands(
            props.novelId,
            characterId,
            signal,
          );
          return commands.items[0]
            ? characterVoiceGeneratorSnapshot(commands.items[0])
            : null;
        },
        onStartGeneration: async (command: {
          readonly characterId: string;
          readonly workspaceSelection: {
            readonly timelineId: string | null;
            readonly characterInstanceId: string | null;
          };
          readonly expectedBindingVersion: number;
        }) => characterVoiceGeneratorSnapshot(
          await createCharacterVoiceGeneratorCommand(
            props.novelId,
            command.characterId,
            {
              contract_version: "character-voice-generation-request/1",
              timeline_id: command.workspaceSelection.timelineId,
              character_instance_id: command.workspaceSelection.characterInstanceId,
              expected_binding_version: command.expectedBindingVersion,
              seed: null,
            },
            createOfficialVoiceUseIdempotencyKey(),
          ),
        ),
        onRefreshGeneration: async (
          commandId: string,
          signal: AbortSignal,
        ) => characterVoiceGeneratorSnapshot(
          await getCharacterVoiceGeneratorCommand(
            props.novelId,
            commandId,
            signal,
          ),
        ),
        onCancelGeneration: async (commandId: string) => (
          characterVoiceGeneratorSnapshot(
            await cancelCharacterVoiceGeneratorCommand(
              props.novelId,
              commandId,
            ),
          )
        ),
        onRetryGeneration: async (commandId: string) => {
          const binding = await getCharacterVoiceBinding(
            props.novelId,
            props.characterId,
          );
          return characterVoiceGeneratorSnapshot(
            await retryCharacterVoiceGeneratorCommand(
              props.novelId,
              commandId,
              { expected_binding_version: binding.version },
            ),
          );
        },
        onUseGeneratedVoice: async (command: {
          readonly commandId: string;
          readonly expectedBindingVersion: number;
        }) => characterVoiceGeneratorSnapshot(
          await applyCharacterVoiceGeneratorCommand(
            props.novelId,
            command.commandId,
            { expected_binding_version: command.expectedBindingVersion },
          ),
        ),
        onCommandChanged: (command: CharacterVoiceGenerationSnapshot) => {
          if (command.state === "ready_applied") {
            setProfileRefreshVersion((value) => value + 1);
          }
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
