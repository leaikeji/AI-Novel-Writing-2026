import { apiErrorMessage } from "../api";
import {
  applyCharacterVoiceGeneratorCommand,
  advanceCharacterCastPlan,
  cancelCharacterVoiceGeneratorCommand,
  createCharacterCastPlan,
  createCharacterVoiceGeneratorCommand,
  createOfficialVoicePreview,
  getCharacterVoiceGeneratorCommand,
  getCharacterVoiceBinding,
  getCharacterCastPlan,
  getVoicePreview,
  getNarrationOverview,
  listCharacterVoiceBindings,
  listCharacterCastPlans,
  listCharacterVoiceGeneratorCommands,
  listVoiceProfiles,
  listNanoVoiceExperiments,
  matchCharacterOfficialVoice,
  retryCharacterVoiceGeneratorCommand,
  retryCharacterCastPlan,
  selectOfficialVoice,
  buildGenericVoicePack,
  cancelGenericVoicePackBuild,
  cancelVoicePreparationCommand,
  createVoicePreparationCommand,
  getGenericVoicePack,
  getGenericVoicePackBuildCommand,
  getVoicePreparationCommand,
  listVoicePreparationCommands,
  regenerateGenericVoicePackSlot,
  rejectGenericVoicePackSlot,
  retryGenericVoicePackBuild,
  retryVoicePreparationCommand,
  resumeVoicePreparationCommand,
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
  activeCharacterCastPlan,
  characterCastUiStatus,
  continueCharacterCastPlan,
  primaryTimelineId,
} from "./character-cast-runner";
import {
  createCharacterVoiceGenerator,
  type CharacterVoiceGenerationSnapshot,
  type CharacterVoiceGeneratorReactRuntime,
} from "./character-voice-generator";
import type {
  CharacterVoiceBindingPolicy,
  CharacterVoiceGeneratorCommandResource,
  CharacterVoiceBindingResource,
  CharacterCastPlanResource,
  NarrationOverviewResponse,
  MediaAssetLink,
  OfficialPresetId,
  VoiceProfileResource,
} from "./contracts";
import { NarrationContractError } from "./contracts";
import { listStoryTimelines } from "../story-timeline/api";
import type { PronunciationPanelReactRuntime } from "./pronunciation-panel";
import {
  createOfficialVoiceSelectionPanel,
  createAndPlayOfficialVoicePreview,
  officialVoiceSelectionResult,
  type CharacterVoiceBindingProjection,
  type OfficialVoiceSelectionPanelApi,
  type OfficialVoiceSelectionPanelProjection,
} from "./official-voice-selection-panel";
import {
  OfficialVoiceUseConflictError,
  OfficialVoiceUseResponseError,
  createOfficialVoiceUseIdempotencyKey,
} from "./official-voice-use-state";
import { createNarrationIdempotencyKey } from "./idempotency-key";
import {
  assertOfficialVoiceSelectionResult,
  type OfficialVoiceSelectionTarget,
} from "./official-voice-library";
import {
  playGenericVoiceSlotPreview,
  playReadyVoicePreview,
} from "./voice-preview-playback";
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
import {
  createVoicePreparation,
  type VoicePreparationReactRuntime,
} from "./voice-preparation";
import {
  createGenericVoicePack,
  type GenericVoicePackReactRuntime,
} from "./generic-voice-pack";


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


export interface CharacterVoiceCardPanelDependencies {
  readonly matchCharacterOfficialVoice?: typeof matchCharacterOfficialVoice;
}


export interface NarrationReadingPageDependencies {
  readonly readingApi?: ReadingPageApi;
  readonly voiceWorkspaceApi?: VoiceSourceWorkspaceApi;
  readonly officialVoiceApi?: OfficialVoiceSelectionPanelApi;
  readonly characterRosterApi?: Readonly<{
    listBindings: typeof listCharacterVoiceBindings;
  }>;
  readonly matchCharacterOfficialVoice?: typeof matchCharacterOfficialVoice;
  readonly listNanoVoiceExperiments?: typeof listNanoVoiceExperiments;
  readonly characterCastApi?: Readonly<{
    listPlans: typeof listCharacterCastPlans;
    createPlan: typeof createCharacterCastPlan;
    getPlan: typeof getCharacterCastPlan;
    advancePlan: typeof advanceCharacterCastPlan;
    retryPlan: typeof retryCharacterCastPlan;
    listTimelines: typeof listStoryTimelines;
  }>;
  readonly voicePreparationApi?: Readonly<{
    list: typeof listVoicePreparationCommands;
    create: typeof createVoicePreparationCommand;
    get: typeof getVoicePreparationCommand;
    resume: typeof resumeVoicePreparationCommand;
    retry: typeof retryVoicePreparationCommand;
    cancel: typeof cancelVoicePreparationCommand;
  }>;
  readonly genericVoicePackApi?: Readonly<{
    get: typeof getGenericVoicePack;
    build: typeof buildGenericVoicePack;
    getCommand: typeof getGenericVoicePackBuildCommand;
    retry: typeof retryGenericVoicePackBuild;
    cancel: typeof cancelGenericVoicePackBuild;
    regenerate: typeof regenerateGenericVoicePackSlot;
    reject: typeof rejectGenericVoicePackSlot;
  }>;
}


type NarrationReactRuntime = ReadingPageReactRuntime
  & CharacterVoicePanelReactRuntime
  & VoiceSourceWorkspaceReactRuntime
  & PronunciationPanelReactRuntime
  & CachePanelReactRuntime
  & ReadingRulesReactRuntime
  & CharacterVoiceRosterReactRuntime
  & CharacterVoiceConfiguratorReactRuntime
  & CharacterVoiceGeneratorReactRuntime
  & VoicePreparationReactRuntime
  & GenericVoicePackReactRuntime;


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
  if (normalized === "zh" || normalized.startsWith("zh-")) return "中文";
  if (normalized === "ja" || normalized.startsWith("ja-")) return "日本語";
  if (normalized === "en" || normalized.startsWith("en-")) return "English";
  return language.trim() || "语言未设置";
}


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
    : version.activation_basis === "character_one_click_generation"
      ? "人物专属音色"
      : version.activation_basis === "experimental_machine_validated"
        ? "Nano 高级调音"
        : version.source_type === "uploaded"
          ? "参考录音音色"
          : "生成音色";
  return Object.freeze({
    kind: "resolved",
    name: profile.name,
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
  fallbackLanguage: string,
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
      language: fallbackLanguage,
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
    || !initial.language.trim()
  ) return undefined;
  return Object.freeze({
    binding_id: policy === "unset" ? null : initial.binding_id,
    novel_id: props.novelId,
    character_id: props.characterId,
    binding_policy: policy,
    profile_id: initial.profile_id,
    version_id: initial.voice_version_id,
    language: initial.language,
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


function isAbortLike(reason: unknown): boolean {
  return typeof reason === "object"
    && reason !== null
    && "name" in reason
    && reason.name === "AbortError";
}


function matchedVoiceErrorMessage(reason: unknown): string {
  if (reason instanceof OfficialVoiceUseConflictError) {
    return "人物声音又发生了变化，请刷新后重试。";
  }
  if (reason instanceof OfficialVoiceUseResponseError || reason instanceof NarrationContractError) {
    return "服务端返回的声音身份与当前人物不一致，已停止应用。";
  }
  return overviewErrorMessage(reason);
}


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
  const CharacterVoiceRoster = createCharacterVoiceRoster(React);
  const CharacterVoiceCardPanel = createCharacterVoiceCardPanel(
    React,
    getNarrationOverview,
    dependencies.voiceWorkspaceApi,
    dependencies.officialVoiceApi,
    { matchCharacterOfficialVoice: dependencies.matchCharacterOfficialVoice },
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
  const NanoAdvancedWorkspace = createNanoAdvancedWorkspace(React);
  const PrivateVoiceLifecycleWorkspace = createPrivateVoiceLifecycleWorkspace(React);
  const VoicePreparation = createVoicePreparation(React);
  const GenericVoicePack = createGenericVoicePack(React);
  const characterRosterApi = dependencies.characterRosterApi ?? {
    listBindings: listCharacterVoiceBindings,
  };
  const listNanoVoiceExperimentsApi = dependencies.listNanoVoiceExperiments
    ?? listNanoVoiceExperiments;
  const characterCastApi = dependencies.characterCastApi ?? {
    listPlans: listCharacterCastPlans,
    createPlan: createCharacterCastPlan,
    getPlan: getCharacterCastPlan,
    advancePlan: advanceCharacterCastPlan,
    retryPlan: retryCharacterCastPlan,
    listTimelines: listStoryTimelines,
  };
  const voicePreparationApi = dependencies.voicePreparationApi ?? {
    list: listVoicePreparationCommands,
    create: createVoicePreparationCommand,
    get: getVoicePreparationCommand,
    resume: resumeVoicePreparationCommand,
    retry: retryVoicePreparationCommand,
    cancel: cancelVoicePreparationCommand,
  };
  const genericVoicePackApi = dependencies.genericVoicePackApi ?? {
    get: getGenericVoicePack,
    build: buildGenericVoicePack,
    getCommand: getGenericVoicePackBuildCommand,
    retry: retryGenericVoicePackBuild,
    cancel: cancelGenericVoicePackBuild,
    regenerate: regenerateGenericVoicePackSlot,
    reject: rejectGenericVoicePackSlot,
  };
  const officialPreviewApi = {
    createOfficialVoicePreview: dependencies.officialVoiceApi?.createOfficialVoicePreview
      ?? createOfficialVoicePreview,
    getVoicePreview: dependencies.officialVoiceApi?.getVoicePreview ?? getVoicePreview,
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
    const [castPlan, setCastPlan] = React.useState<CharacterCastPlanResource | null>(null);
    const [castRestoreError, setCastRestoreError] = React.useState<string | null>(null);
    const castRunnerRef = React.useRef<AbortController | null>(null);
    const overview = props.context.overview;
    const castCapability = capabilityFor(overview, "character_cast_planning");
    const castAvailable = castCapability.state === "enabled"
      && castCapability.visible
      && castCapability.actionable
      && overview.authorization.can_configure;
    const preparationCapability = capabilityFor(
      overview,
      "automatic_character_voice_generation",
    );
    const preparationAvailable = preparationCapability.state === "enabled"
      && preparationCapability.visible
      && preparationCapability.actionable;

    const refreshRoster = (): void => {
      props.context.onRefresh();
    };

    const continueCastPlan = async (
      initial: CharacterCastPlanResource,
      controller: AbortController,
    ): Promise<CharacterCastPlanResource> => {
      const current = await continueCharacterCastPlan({
        novelId: props.novelId,
        initial,
        api: characterCastApi,
        signal: controller.signal,
        onUpdate: setCastPlan,
      });
      if (
        !controller.signal.aborted
        && (current.state === "ready_applied" || current.state === "ready_applied_with_warnings")
      ) refreshRoster();
      return current;
    };

    React.useEffect(() => {
      const controller = new AbortController();
      setRosterState({ phase: "loading", bindings: [], message: null });
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
          setRosterState({
            phase: "error",
            bindings: [],
            message: overviewErrorMessage(reason),
          });
        }
      });
      return () => controller.abort();
    }, [props.novelId]);

    React.useEffect(() => {
      castRunnerRef.current?.abort();
      if (!castAvailable) {
        setCastPlan(null);
        setCastRestoreError(null);
        return undefined;
      }
      const controller = new AbortController();
      castRunnerRef.current = controller;
      setCastRestoreError(null);
      void characterCastApi.listPlans(props.novelId, controller.signal)
        .then(async (plans) => {
          if (controller.signal.aborted) return;
          const restored = activeCharacterCastPlan(plans.items) ?? plans.items[0] ?? null;
          setCastPlan(restored);
          if (restored !== null && !restored.terminal) {
            await continueCastPlan(restored, controller);
          }
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted || isAbortLike(reason)) return;
          setCastPlan(null);
          setCastRestoreError(apiErrorMessage(
            reason,
            "无法恢复上次的智能配音进度；可重新点击“智能配音全书”继续。",
          ));
        });
      return () => {
        controller.abort();
        if (castRunnerRef.current === controller) castRunnerRef.current = null;
      };
    }, [props.novelId, castAvailable]);

    const runSmartCast = async (): Promise<void> => {
      castRunnerRef.current?.abort();
      const controller = new AbortController();
      castRunnerRef.current = controller;
      setCastRestoreError(null);
      try {
        let initial: CharacterCastPlanResource;
        if (castPlan !== null && !castPlan.terminal) {
          initial = castPlan;
        } else if (castPlan?.state === "failed" && castPlan.retryable) {
          initial = await characterCastApi.retryPlan(
            props.novelId,
            castPlan.command_id,
            controller.signal,
          );
        } else {
          const timelines = await characterCastApi.listTimelines(
            props.novelId,
            controller.signal,
          );
          initial = await characterCastApi.createPlan(
            props.novelId,
            {
              contract_version: "character-cast-plan-request/1",
              timeline_id: primaryTimelineId(timelines, props.novelId),
              mode: "fill_and_deduplicate",
            },
            createNarrationIdempotencyKey("character-cast-plan"),
            controller.signal,
          );
        }
        if (controller.signal.aborted) return;
        setCastPlan(initial);
        await continueCastPlan(initial, controller);
      } finally {
        if (castRunnerRef.current === controller) castRunnerRef.current = null;
      }
    };

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
            props.context.voiceProfilesError
              ? h("p", { role: "alert" }, props.context.voiceProfilesError)
              : null,
            h(VoicePreparation, {
              key: `voice-preparation:${props.novelId}`,
              capabilityEnabled: preparationAvailable,
              canConfigure: overview.authorization.can_configure,
              presentation: "card",
              onLoadLatest: async (signal: AbortSignal) => {
                const commands = await voicePreparationApi.list(
                  props.novelId,
                  signal,
                );
                const current = commands.find((command) => !command.terminal)
                  ?? commands[0]
                  ?? null;
                if (current === null || current.terminal || !preparationAvailable) {
                  return current;
                }
                const resumed = await voicePreparationApi.resume(
                  props.novelId,
                  current.commandId,
                  signal,
                );
                if (resumed.terminal && !signal.aborted) {
                  queueMicrotask(refreshRoster);
                }
                return resumed;
              },
              onStart: () => voicePreparationApi.create(
                props.novelId,
                {
                  contract_version: "narration-voice-preparation-request/1",
                  mode: "prepare_missing_dedicated",
                  document_id: null,
                  expected_draft_version: null,
                  expected_content_hash: null,
                  expected_settings_version: null,
                },
                createNarrationIdempotencyKey("voice-preparation"),
              ),
              onRefresh: (commandId: string, signal: AbortSignal) => (
                voicePreparationApi.get(props.novelId, commandId, signal)
              ),
              onRetry: (commandId: string) => (
                voicePreparationApi.retry(props.novelId, commandId)
              ),
              onCancel: (commandId: string) => (
                voicePreparationApi.cancel(props.novelId, commandId)
              ),
              onCommandChanged: (command: { readonly terminal: boolean }) => {
                if (command.terminal) refreshRoster();
              },
            }),
            h(CharacterVoiceRoster, {
            novelId: props.novelId,
            characters: scopedCharacters,
            bindings: rosterState.bindings,
            profiles: props.context.voiceProfiles,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            castStatus: characterCastUiStatus(castPlan) ?? (castRestoreError === null
              ? null
              : {
                phase: "failed" as const,
                progressCurrent: 0,
                progressTotal: 0,
                message: castRestoreError,
                retryable: false,
              }),
            onSmartCast: runSmartCast,
            onConfigureCharacter: () => undefined,
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
                onChanged: refreshRoster,
              });
            },
            }),
          ),
    );
  }

  function VoiceLibrarySection(props: VoiceLibrarySectionProps): unknown {
    const [editorOpen, setEditorOpen] = React.useState(false);
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
          h("span", null, "作品旁白"),
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
              : h("small", null, "从 18 个官方音色中直接选择，不需要先试听。"),
        ),
        h(
          "div",
          { className: "anw-narrator-current-voice__actions" },
          props.context.voiceProfilesError !== null
            ? h("button", {
              type: "button",
              className: "anw-narration-secondary-action",
              onClick: props.context.onRefresh,
            }, "重新读取")
            : null,
          h("button", {
            type: "button",
            className: "anw-narration-primary-action",
            "aria-expanded": editorOpen,
            "aria-controls": editorId,
            onClick: () => setEditorOpen((value) => !value),
          }, editorOpen ? "收起音色列表" : "更换旁白音色"),
        ),
      ),
      editorOpen
        ? h("div", { id: editorId, className: "anw-narrator-voice-library-editor" },
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
        )
        : null,
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
        const genericPoolCapability = capabilityFor(overview, "generic_voice_pool");
        const genericPoolAvailable = genericPoolCapability.state === "enabled"
          && genericPoolCapability.visible
          && genericPoolCapability.actionable;
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
          h(GenericVoicePack, {
            capabilityEnabled: genericPoolAvailable,
            canConfigure: overview.authorization.can_configure,
            onLoadLatest: (signal: AbortSignal) => genericVoicePackApi.get(signal),
            onRefreshCommand: (
              commandId: string,
              signal: AbortSignal,
            ) => genericVoicePackApi.getCommand(commandId, signal),
            onBuild: () => genericVoicePackApi.build(
              createNarrationIdempotencyKey("generic-voice-pack"),
            ),
            onRetry: (commandId: string) => genericVoicePackApi.retry(commandId),
            onCancel: (commandId: string) => genericVoicePackApi.cancel(commandId),
            onRegenerateSlot: (slotKey: string, expectedPackVersionId: string | null) => {
              if (expectedPackVersionId === null) {
                return Promise.reject(new Error("通用音色包版本尚未建立。"));
              }
              return genericVoicePackApi.regenerate(
                slotKey,
                { expected_pack_version_id: expectedPackVersionId },
                createNarrationIdempotencyKey("generic-voice-regenerate"),
              );
            },
            onRejectSlot: (slotKey: string, expectedPackVersionId: string) => (
              genericVoicePackApi.reject(
                slotKey,
                { expected_pack_version_id: expectedPackVersionId },
              )
            ),
            onPreviewSlot: async (slotId: string, previewAsset: MediaAssetLink) => {
              const controller = new AbortController();
              await playGenericVoiceSlotPreview(
                slotId,
                previewAsset,
                controller.signal,
              );
            },
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
  dependencies: CharacterVoiceCardPanelDependencies = {},
): (props: CharacterVoiceCardPanelProps) => unknown {
  const h = React.createElement;
  const CharacterVoiceConfigurator = createCharacterVoiceConfigurator(React);
  const CharacterVoicePanel = createCharacterVoicePanel(React);
  const CharacterVoiceGenerator = createCharacterVoiceGenerator(React);
  const VoiceSourceWorkspace = createVoiceSourceWorkspace(React, voiceWorkspaceApi);
  const OfficialVoiceSelectionPanel = createOfficialVoiceSelectionPanel(React, officialVoiceApi);
  const NanoAdvancedWorkspace = createNanoAdvancedWorkspace(React);
  const getBinding = officialVoiceApi?.getCharacterVoiceBinding ?? getCharacterVoiceBinding;
  const getProfiles = officialVoiceApi?.listVoiceProfiles ?? listVoiceProfiles;
  const selectOfficialVoiceApi = officialVoiceApi?.selectOfficialVoice ?? selectOfficialVoice;
  const matchCharacterOfficialVoiceApi = dependencies.matchCharacterOfficialVoice
    ?? matchCharacterOfficialVoice;

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
      h(NanoAdvancedWorkspace, {
        novelId: advancedProps.novelId,
        overview: advancedProps.overview,
        characters: [{
          characterId: advancedProps.characterId,
          characterName: advancedProps.characterName,
        }],
        fixedCharacter: {
          characterId: advancedProps.characterId,
          characterName: advancedProps.characterName,
        },
        presentation: "embedded",
        onChanged: advancedProps.onProfileChanged,
      }),
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
        allowedSourceTypes: ["uploaded", "generated"],
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
      if (state.voiceBindingPhase !== "loading" && state.voiceProfilesPhase !== "loading") return;
      const controller = new AbortController();
      const projectionKey = state.projectionKey;
      if (state.voiceBindingPhase === "loading") {
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
      if (state.voiceProfilesPhase === "loading") {
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
    }, [state.phase === "ready" ? state.projectionKey : null]);

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
    const matchCapability = capabilityFor(state.overview, "character_voice_matching");
    const matchEnabled = matchCapability.state === "enabled"
      && matchCapability.visible
      && matchCapability.actionable
      && state.overview.authorization.can_configure;
    const generatorCapability = capabilityFor(state.overview, "voice_generator");
    const generatorEnabled = generatorCapability.state === "enabled"
      && generatorCapability.visible
      && generatorCapability.actionable;
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
      setReloadVersion((value) => value + 1);
      props.onChanged?.();
    };
    const matchAndUse = async (signal: AbortSignal) => {
      try {
        const binding = await getBinding(props.novelId, props.characterId, signal);
        assertCharacterVoiceBindingScope(binding, props.novelId, props.characterId);
        const matched = await matchCharacterOfficialVoiceApi(
          props.novelId,
          props.characterId,
          {
            contract_version: "character-voice-match-request/1",
            timeline_id: null,
            character_instance_id: null,
            expected_binding_version: binding.version,
          },
          createOfficialVoiceUseIdempotencyKey(),
          signal,
        );
        if (
          matched.character_id !== props.characterId
          || matched.current_character_binding.novel_id !== props.novelId
          || matched.current_character_binding.character_id !== props.characterId
        ) {
          throw new NarrationContractError("character_voice_match", "response scope mismatch");
        }
        return {
          voiceName: matched.selected_preset_id.replace(/^onnx\./, ""),
          presetId: matched.selected_preset_id,
          selectionStillCurrent: matched.selection_still_current,
        };
      } catch (reason: unknown) {
        if (isAbortLike(reason)) throw reason;
        throw new Error(matchedVoiceErrorMessage(reason));
      }
    };
    const useMatched = async (presetId: string, signal: AbortSignal) => {
      try {
        const [latestOverview, latestBinding] = await Promise.all([
          loadOverview(props.novelId, signal),
          getBinding(props.novelId, props.characterId, signal),
        ]);
        if (latestOverview.novel_id !== props.novelId) {
          throw new NarrationContractError("narration_overview", "response scope mismatch");
        }
        assertCharacterVoiceBindingScope(latestBinding, props.novelId, props.characterId);
        const officialPresetId = presetId as OfficialPresetId;
        const target: OfficialVoiceSelectionTarget = {
          kind: "character",
          characterId: props.characterId,
          characterName: props.characterName,
          targetLanguage: latestBinding.language,
          expectedSettingsVersion: latestOverview.settings.version,
          expectedBindingVersion: latestBinding.version,
        };
        const response = await selectOfficialVoiceApi(
          props.novelId,
          {
            preset_id: officialPresetId,
            target_kind: "character",
            character_id: props.characterId,
            expected_settings_version: latestOverview.settings.version,
            expected_binding_version: latestBinding.version,
          },
          createOfficialVoiceUseIdempotencyKey(),
          signal,
        );
        const selection = officialVoiceSelectionResult(response);
        assertOfficialVoiceSelectionResult(selection, officialPresetId, target);
        return {
          voiceName: response.profile.name || presetId.replace(/^onnx\./, ""),
          presetId,
          selectionStillCurrent: selection.selectionStillCurrent,
        };
      } catch (reason: unknown) {
        if (isAbortLike(reason)) throw reason;
        throw new Error(matchedVoiceErrorMessage(reason));
      }
    };
    const generatorContent = state.voiceBindingPhase !== "ready" || state.binding === null
      ? undefined
      : h(CharacterVoiceGenerator, {
        presentation: "embedded",
        capabilityEnabled: generatorEnabled,
        canConfigure: state.overview.authorization.can_configure,
        characterId: props.characterId,
        characterName: props.characterName,
        expectedBindingVersion: state.binding.version,
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
            publishChanged();
          }
        },
      });
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
      matchEnabled,
      matchDisabledReason: matchEnabled
        ? null
        : matchCapability.reason_code
          ? `智能匹配暂不可用（${matchCapability.reason_code}）。`
          : "智能匹配暂不可用。",
      onMatchOfficialVoice: matchAndUse,
      onUseMatchedOfficialVoice: useMatched,
      generatorContent,
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
