import {
  applyNanoVoiceExperiment,
  cancelPrivateVoiceDeletionRequest,
  confirmPrivateVoiceDeletionRequest,
  createNanoVoiceExperiment,
  createPrivateVoiceDeletionRequest,
  getNanoVoiceExperiment,
  getPrivateVoiceLifecycle,
  listCharacterVoiceBindings,
  listNanoVoiceExperiments,
  listVoiceProfiles,
  retryPrivateVoiceDeletionRequest,
  selectOfficialVoice,
} from "./api";
import { apiErrorMessage } from "../api";
import type {
  CharacterVoiceBindingResource,
  NanoVoiceExperimentResource,
  NarrationOverviewResponse,
  OfficialPresetId,
  PrivateVoiceLifecycleResource,
  VoiceProfileResource,
  VoiceProfileVersionResource,
} from "./contracts";
import { OFFICIAL_PRESET_IDS } from "./contracts";
import {
  createNanoAdvancedTuningPanel,
  type NanoAdvancedExperimentCommand,
  type NanoAdvancedApplyCommand,
  type NanoAdvancedTuningBusyAction,
  type NanoAdvancedTuningReactRuntime,
  type NanoExperimentSnapshot,
  type NanoOfficialVoiceRestoreCommand,
} from "./nano-advanced-tuning";
import { createOfficialVoiceUseIdempotencyKey } from "./official-voice-use-state";
import { createNarrationIdempotencyKey } from "./idempotency-key";
import {
  createVoiceLifecyclePanel,
  type VoiceLifecycleReactRuntime,
} from "./voice-lifecycle-panel";
import {
  voiceDeletionRequestFromResource,
  voiceLifecycleProfileFromResource,
  type VoiceLifecycleBusyAction,
  type VoiceLifecycleConfirmCommand,
  type VoiceLifecycleProfileCommand,
} from "./voice-lifecycle-state";


export interface VoiceFeatureCharacter {
  readonly characterId: string;
  readonly characterName: string;
}


export interface NanoAdvancedWorkspaceProps {
  readonly novelId: string;
  readonly overview: NarrationOverviewResponse;
  readonly characters: readonly VoiceFeatureCharacter[];
  readonly onChanged: () => void;
  readonly fixedCharacter?: VoiceFeatureCharacter;
  readonly presentation?: "standalone" | "embedded";
}


export interface PrivateVoiceWorkspaceProps {
  readonly novelId: string;
  readonly overview: NarrationOverviewResponse;
  readonly onChanged: () => void;
}


export interface NanoAdvancedWorkspaceApi {
  listBindings: typeof listCharacterVoiceBindings;
  listProfiles: typeof listVoiceProfiles;
  listExperiments: typeof listNanoVoiceExperiments;
  createExperiment: typeof createNanoVoiceExperiment;
  getExperiment: typeof getNanoVoiceExperiment;
  applyExperiment: typeof applyNanoVoiceExperiment;
  selectOfficialVoice: typeof selectOfficialVoice;
}


export interface PrivateVoiceWorkspaceApi {
  getLifecycle: typeof getPrivateVoiceLifecycle;
  createDeletionRequest: typeof createPrivateVoiceDeletionRequest;
  confirmDeletionRequest: typeof confirmPrivateVoiceDeletionRequest;
  cancelDeletionRequest: typeof cancelPrivateVoiceDeletionRequest;
  retryDeletionRequest: typeof retryPrivateVoiceDeletionRequest;
}


type VoiceFeatureReactRuntime = NanoAdvancedTuningReactRuntime & VoiceLifecycleReactRuntime;


const DEFAULT_NANO_API: NanoAdvancedWorkspaceApi = {
  listBindings: listCharacterVoiceBindings,
  listProfiles: listVoiceProfiles,
  listExperiments: listNanoVoiceExperiments,
  createExperiment: createNanoVoiceExperiment,
  getExperiment: getNanoVoiceExperiment,
  applyExperiment: applyNanoVoiceExperiment,
  selectOfficialVoice,
};


const DEFAULT_PRIVATE_API: PrivateVoiceWorkspaceApi = {
  getLifecycle: getPrivateVoiceLifecycle,
  createDeletionRequest: createPrivateVoiceDeletionRequest,
  confirmDeletionRequest: confirmPrivateVoiceDeletionRequest,
  cancelDeletionRequest: cancelPrivateVoiceDeletionRequest,
  retryDeletionRequest: retryPrivateVoiceDeletionRequest,
};


function createFeatureIdempotencyKey(prefix: "nano-experiment" | "private-voice-deletion"): string {
  return createNarrationIdempotencyKey(prefix);
}


function capabilityEnabled(
  overview: NarrationOverviewResponse,
  key: "nano_advanced_tuning" | "private_voice_deletion",
): boolean {
  const capability = overview.capabilities.items.find((item) => item.key === key);
  return capability?.state === "enabled" && capability.visible && capability.actionable;
}


function capabilityMessage(
  overview: NarrationOverviewResponse,
  key: "nano_advanced_tuning" | "private_voice_deletion",
): string {
  const capability = overview.capabilities.items.find((item) => item.key === key);
  return capability?.reason_code
    ? `当前能力尚未就绪（${capability.reason_code}）。`
    : "当前能力尚未就绪。";
}


function errorMessage(reason: unknown, fallback: string): string {
  return apiErrorMessage(reason, fallback);
}


function currentVersion(
  profiles: readonly VoiceProfileResource[],
  profileId: string | null,
  versionId: string | null,
): VoiceProfileVersionResource | null {
  if (profileId === null || versionId === null) return null;
  return profiles
    .find((profile) => profile.profile_id === profileId)
    ?.versions.find((version) => version.version_id === versionId) ?? null;
}


function officialBasePreset(
  version: VoiceProfileVersionResource | null,
): OfficialPresetId | null {
  const preset = version?.preset_key;
  return preset !== null
    && preset !== undefined
    && OFFICIAL_PRESET_IDS.includes(preset as OfficialPresetId)
    ? preset as OfficialPresetId
    : null;
}


export function officialPresetDisplayName(
  profiles: readonly VoiceProfileResource[],
  presetId: OfficialPresetId,
): string {
  return profiles.find((profile) => profile.versions.some((version) => (
    version.source_type === "preset" && version.preset_key === presetId
  )))?.name ?? "官方音色";
}


function experimentSnapshot(
  resource: NanoVoiceExperimentResource | null,
): NanoExperimentSnapshot | null {
  return resource === null ? null : Object.freeze({
    commandId: resource.command_id,
    state: resource.state,
    reusedVersion: resource.reused_version,
    failureCode: resource.failure_code,
    retryable: resource.retryable,
  });
}


export function selectNanoExperimentForTarget(
  experiments: readonly NanoVoiceExperimentResource[],
  options: Readonly<{
    basePresetId: OfficialPresetId;
    targetKind: "narrator" | "character";
    characterId: string | null;
    currentVoiceVersionId: string | null;
  }>,
): NanoVoiceExperimentResource | null {
  const {
    basePresetId,
    targetKind,
    characterId,
    currentVoiceVersionId,
  } = options;
  const latest = experiments.find((item) => (
    item.base_preset_id === basePresetId
    && item.target_kind === targetKind
    && item.character_id === characterId
  )) ?? null;
  if (
    latest?.state === "ready_applied"
    && latest.version_id !== currentVoiceVersionId
  ) {
    // “恢复官方音色” is an intentional binding change.  The immutable
    // historical command remains queryable, but must not claim it is still
    // applied after the target has moved back to the official Version.
    return null;
  }
  return latest;
}


type NanoLoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | {
    readonly phase: "ready";
    readonly profiles: readonly VoiceProfileResource[];
    readonly bindings: readonly CharacterVoiceBindingResource[];
    readonly experiments: readonly NanoVoiceExperimentResource[];
  };


export function createNanoAdvancedWorkspace(
  React: VoiceFeatureReactRuntime,
  api: NanoAdvancedWorkspaceApi = DEFAULT_NANO_API,
): (props: NanoAdvancedWorkspaceProps) => unknown {
  const h = React.createElement;
  const Panel = createNanoAdvancedTuningPanel(React);

  return function NanoAdvancedWorkspace(props: NanoAdvancedWorkspaceProps): unknown {
    const enabled = capabilityEnabled(props.overview, "nano_advanced_tuning");
    const [selectedTargetKey, setTargetKey] = React.useState("narrator");
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [state, setState] = React.useState<NanoLoadState>({ phase: "loading" });
    const [experiment, setExperiment] = React.useState<NanoVoiceExperimentResource | null>(null);
    const [busyAction, setBusyAction] = React.useState<NanoAdvancedTuningBusyAction | null>(null);
    const [operationError, setOperationError] = React.useState<string | null>(null);

    React.useEffect(() => {
      if (!enabled) {
        setState({ phase: "error", message: capabilityMessage(props.overview, "nano_advanced_tuning") });
        return;
      }
      const controller = new AbortController();
      setState({ phase: "loading" });
      void Promise.all([
        api.listProfiles({ novelId: props.novelId, includeLibrary: true, signal: controller.signal }),
        api.listBindings(props.novelId, controller.signal),
        api.listExperiments(props.novelId, controller.signal),
      ]).then(([profiles, bindings, experiments]) => {
        if (controller.signal.aborted) return;
        if (bindings.novel_id !== props.novelId || experiments.novel_id !== props.novelId) {
          throw new Error("高级调音返回了其他作品范围，已停止显示。");
        }
        setState({
          phase: "ready",
          profiles: profiles.items,
          bindings: bindings.items,
          experiments: experiments.items,
        });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setState({ phase: "error", message: errorMessage(reason, "无法加载高级调音。") });
        }
      });
      return () => controller.abort();
    }, [
      enabled,
      props.novelId,
      props.overview.settings.version,
      props.fixedCharacter?.characterId ?? null,
      reloadVersion,
    ]);

    const targetKey = props.fixedCharacter?.characterId ?? selectedTargetKey;
    const selectedCharacter = props.fixedCharacter ?? (
      targetKey === "narrator"
        ? null
        : props.characters.find((character) => character.characterId === targetKey) ?? null
    );
    const selectedBinding = state.phase === "ready" && selectedCharacter !== null
      ? state.bindings.find((binding) => binding.character_id === selectedCharacter.characterId) ?? null
      : null;
    const selectedVoice = state.phase === "ready"
      ? selectedCharacter === null
        ? currentVersion(
          state.profiles,
          props.overview.settings.values.narrator?.profile_id ?? null,
          props.overview.settings.values.narrator?.version_id ?? null,
        )
        : currentVersion(
          state.profiles,
          selectedBinding?.profile_id ?? null,
          selectedBinding?.version_id ?? null,
        )
      : null;
    const basePresetId = officialBasePreset(selectedVoice);
    const matchingExperiment = experiment ?? (
      state.phase === "ready" && basePresetId !== null
        ? selectNanoExperimentForTarget(
          state.experiments,
          {
            basePresetId,
            targetKind: selectedCharacter === null ? "narrator" : "character",
            characterId: selectedCharacter?.characterId ?? null,
            currentVoiceVersionId: selectedVoice?.version_id ?? null,
          },
        )
        : null
    );
    const currentSettingsVersion = matchingExperiment?.current_settings?.version
      ?? props.overview.settings.version;
    const currentBindingVersion = selectedCharacter === null
      ? null
      : matchingExperiment?.current_character_binding?.version ?? selectedBinding?.version ?? null;
    const target = {
      kind: selectedCharacter === null ? "narrator" as const : "character" as const,
      characterId: selectedCharacter?.characterId ?? null,
      expectedSettingsVersion: currentSettingsVersion,
      expectedBindingVersion: currentBindingVersion,
    };

    React.useEffect(() => {
      if (
        matchingExperiment === null
        || !["pending", "running"].includes(matchingExperiment.state)
      ) return;
      const controller = new AbortController();
      const timer = globalThis.setTimeout(() => {
        void api.getExperiment(
          props.novelId,
          matchingExperiment.command_id,
          controller.signal,
        ).then((next) => {
          if (controller.signal.aborted) return;
          setExperiment(next);
          if (!["pending", "running"].includes(next.state)) props.onChanged();
        }).catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setOperationError(errorMessage(reason, "无法刷新高级调音状态。"));
          }
        });
      }, 1_000);
      return () => {
        controller.abort();
        globalThis.clearTimeout(timer);
      };
    }, [props.novelId, matchingExperiment?.command_id, matchingExperiment?.state]);

    const run = async (
      action: NanoAdvancedTuningBusyAction,
      operation: () => Promise<NanoVoiceExperimentResource | void>,
    ): Promise<void> => {
      setBusyAction(action);
      setOperationError(null);
      try {
        const result = await operation();
        if (result) setExperiment(result);
        props.onChanged();
      } catch (reason: unknown) {
        setOperationError(errorMessage(reason, "高级调音操作失败，原音色未改变。"));
      } finally {
        setBusyAction(null);
      }
    };

    const create = (command: NanoAdvancedExperimentCommand): void => {
      void run("create", () => api.createExperiment(
        props.novelId,
        {
          contract_version: "nano-voice-experiment-request/1",
          base_preset_id: command.basePresetId as OfficialPresetId,
          target_kind: command.kind,
          character_id: command.characterId,
          expected_settings_version: command.expectedSettingsVersion,
          expected_binding_version: command.expectedBindingVersion,
          parameters: {
            schema_version: "nano-decode-parameters/3",
            seed: command.parameters.seed,
            text_temperature_milli: command.parameters.textTemperatureMilli,
            text_top_p_milli: command.parameters.textTopPMilli,
            text_top_k: command.parameters.textTopK,
            audio_temperature_milli: command.parameters.audioTemperatureMilli,
            audio_top_p_milli: command.parameters.audioTopPMilli,
            audio_top_k: command.parameters.audioTopK,
            audio_repetition_penalty_milli: command.parameters.audioRepetitionPenaltyMilli,
            sample_mode: "full",
            max_new_frames: 375,
          },
        },
        createFeatureIdempotencyKey("nano-experiment"),
      ));
    };

    const apply = (command: NanoAdvancedApplyCommand): void => {
      void run("apply", () => api.applyExperiment(
        props.novelId,
        command.commandId,
        {
          expected_settings_version: command.expectedSettingsVersion,
          expected_binding_version: command.expectedBindingVersion,
        },
      ));
    };

    const restore = (command: NanoOfficialVoiceRestoreCommand): void => {
      void run("restore", async () => {
        const result = await api.selectOfficialVoice(
          props.novelId,
          {
            preset_id: command.basePresetId as OfficialPresetId,
            target_kind: command.kind,
            character_id: command.characterId,
            expected_settings_version: command.expectedSettingsVersion,
            expected_binding_version: command.expectedBindingVersion,
          },
          createOfficialVoiceUseIdempotencyKey(),
        );
        if (!result.selection_still_current) {
          throw new Error("音色已在其他位置更新；官方音色没有覆盖你的新选择。");
        }
        setExperiment(null);
      });
    };

    const headingId = `anw-nano-workspace-${(props.fixedCharacter?.characterId ?? "global")
      .replace(/[^A-Za-z0-9_-]/gu, "-")}-heading`;
    const embedded = props.presentation === "embedded";
    return h(
      "section",
      {
        className: "anw-narration-feature-workspace",
        "aria-labelledby": embedded ? undefined : headingId,
        "aria-label": embedded ? `${selectedCharacter?.characterName ?? "旁白"}的 Nano 高级调音` : undefined,
      },
      embedded
        ? null
        : h("header", { className: "anw-reading-section-heading" },
          h("div", null,
            h("h2", { id: headingId }, "高级调音"),
            h("p", null, "选择当前旁白或人物的官方基础音色，后台验证成功后自动使用。"),
          ),
        ),
      !enabled
        ? h("p", { className: "anw-reading-gate-notice", role: "status" }, capabilityMessage(props.overview, "nano_advanced_tuning"))
        : props.fixedCharacter === undefined
          ? h(
          "label",
          { className: "anw-narration-feature-target" },
          h("span", null, "调音目标"),
          h("select", {
            value: selectedCharacter?.characterId ?? "narrator",
            onChange: (event: { target: { value: string } }) => {
              setTargetKey(event.target.value);
              setExperiment(null);
              setOperationError(null);
            },
          },
          h("option", { value: "narrator" }, "作品旁白"),
          ...props.characters.map((character) => h(
            "option",
            { key: character.characterId, value: character.characterId },
            `人物 · ${character.characterName}`,
          )),
          ),
          )
          : null,
      enabled && state.phase === "loading"
        ? h("p", { role: "status" }, "正在加载当前音色和实验记录…")
        : null,
      enabled && state.phase === "error"
        ? h("div", { className: "anw-reading-inline-error", role: "alert" },
          h("p", null, state.message),
          h("button", { type: "button", onClick: () => setReloadVersion((value) => value + 1) }, "重试"),
        )
        : null,
      enabled && state.phase === "ready" && basePresetId === null
        ? h("p", { className: "anw-reading-gate-notice", role: "status" },
          "当前目标还没有可识别的官方基础音色。请先在“官方音色”或“人物配音”区域选择一个官方音色。",
        )
        : null,
      enabled && state.phase === "ready" && basePresetId !== null
        ? h(Panel, {
          capabilityEnabled: true,
          basePresetId,
          basePresetDisplayName: officialPresetDisplayName(state.profiles, basePresetId),
          target,
          experiment: experimentSnapshot(matchingExperiment),
          busyAction,
          errorMessage: operationError,
          onCreateExperiment: create,
          onApplyExperiment: apply,
          onRestoreOfficialVoice: restore,
        })
        : null,
    );
  };
}


type PrivateLoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | {
    readonly phase: "ready";
    readonly resource: PrivateVoiceLifecycleResource;
    readonly observedAtEpochMs: number;
  };


export function createPrivateVoiceLifecycleWorkspace(
  React: VoiceFeatureReactRuntime,
  api: PrivateVoiceWorkspaceApi = DEFAULT_PRIVATE_API,
): (props: PrivateVoiceWorkspaceProps) => unknown {
  const h = React.createElement;
  const Panel = createVoiceLifecyclePanel(React);

  return function PrivateVoiceLifecycleWorkspace(props: PrivateVoiceWorkspaceProps): unknown {
    const enabled = capabilityEnabled(props.overview, "private_voice_deletion");
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [state, setState] = React.useState<PrivateLoadState>({ phase: "loading" });
    const [busy, setBusy] = React.useState<Readonly<{
      profileId: string;
      action: VoiceLifecycleBusyAction;
    }> | null>(null);
    const [operationError, setOperationError] = React.useState<Readonly<{
      profileId: string;
      message: string;
    }> | null>(null);

    const reload = (): void => setReloadVersion((value) => value + 1);
    React.useEffect(() => {
      if (!enabled) {
        setState({ phase: "error", message: capabilityMessage(props.overview, "private_voice_deletion") });
        return;
      }
      const controller = new AbortController();
      setState({ phase: "loading" });
      void api.getLifecycle(props.novelId, controller.signal).then((resource) => {
        if (controller.signal.aborted) return;
        if (resource.novel_id !== props.novelId) throw new Error("私人音色返回了其他作品范围。");
        setState({ phase: "ready", resource, observedAtEpochMs: Date.now() });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setState({ phase: "error", message: errorMessage(reason, "无法加载私人音色。") });
        }
      });
      return () => controller.abort();
    }, [enabled, props.novelId, reloadVersion]);

    const activeSignature = state.phase === "ready"
      ? state.resource.items
        .filter((item) => item.active_request !== null && !item.active_request.terminal)
        .map((item) => `${item.profile_id}:${item.active_request?.request_id}:${item.active_request?.state}`)
        .join("|")
      : "";
    React.useEffect(() => {
      if (!enabled || activeSignature === "") return;
      const timer = globalThis.setTimeout(reload, 2_000);
      return () => globalThis.clearTimeout(timer);
    }, [enabled, activeSignature, reloadVersion]);

    const run = async (
      profileId: string,
      action: VoiceLifecycleBusyAction,
      operation: () => Promise<unknown>,
    ): Promise<void> => {
      setBusy({ profileId, action });
      setOperationError(null);
      try {
        await operation();
        props.onChanged();
        reload();
      } catch (reason: unknown) {
        setOperationError({
          profileId,
          message: errorMessage(reason, "私人音色操作失败，现有音色未被改变。"),
        });
      } finally {
        setBusy(null);
      }
    };

    const create = (command: VoiceLifecycleProfileCommand): void => {
      void run(command.profileId, "create", () => api.createDeletionRequest(
        props.novelId,
        command.profileId,
        { expected_profile_version: command.expectedProfileVersion },
        createFeatureIdempotencyKey("private-voice-deletion"),
      ));
    };
    const confirm = (profileId: string, command: VoiceLifecycleConfirmCommand): void => {
      void run(profileId, "confirm", () => api.confirmDeletionRequest(
        props.novelId,
        command.requestId,
        {
          expected_profile_version: command.expectedProfileVersion,
          impact_digest: command.impactDigest,
        },
      ));
    };
    const cancel = (profileId: string, requestId: string): void => {
      void run(profileId, "cancel", () => api.cancelDeletionRequest(props.novelId, requestId));
    };
    const retry = (profileId: string, requestId: string): void => {
      void run(profileId, "retry", () => api.retryDeletionRequest(props.novelId, requestId));
    };

    return h(
      "section",
      { className: "anw-narration-feature-workspace", "aria-labelledby": "anw-private-voice-heading" },
      h("header", { className: "anw-reading-section-heading" },
        h("div", null,
          h("h2", { id: "anw-private-voice-heading" }, "私人音色"),
          h("p", null, "这里只列出当前作品的上传或生成音色；官方音色没有删除入口。"),
        ),
      ),
      !enabled
        ? h("p", { className: "anw-reading-gate-notice", role: "status" }, capabilityMessage(props.overview, "private_voice_deletion"))
        : state.phase === "loading"
          ? h("p", { role: "status" }, "正在加载私人音色…")
          : state.phase === "error"
            ? h("div", { className: "anw-reading-inline-error", role: "alert" },
              h("p", null, state.message),
              h("button", { type: "button", onClick: reload }, "重试"),
            )
            : state.resource.items.length === 0
              ? h("p", { className: "anw-narration-private-empty", role: "status" }, "当前作品还没有私人音色。")
              : h(
                "div",
                { className: "anw-narration-private-list" },
                ...state.resource.items.map((item) => h(Panel, {
                  key: item.profile_id,
                  capabilityEnabled: true,
                  profile: voiceLifecycleProfileFromResource(item),
                  request: item.active_request
                    ? voiceDeletionRequestFromResource(item.active_request)
                    : null,
                  busyAction: busy?.profileId === item.profile_id ? busy.action : null,
                  errorMessage: operationError?.profileId === item.profile_id
                    ? operationError.message
                    : null,
                  serverNowObservedAtEpochMs: state.observedAtEpochMs,
                  onCreateDeletionRequest: create,
                  onConfirmDeletion: (command: VoiceLifecycleConfirmCommand) => confirm(item.profile_id, command),
                  onCancelDeletion: (requestId: string) => cancel(item.profile_id, requestId),
                  onRetryDeletion: (requestId: string) => retry(item.profile_id, requestId),
                  onReloadLifecycle: reload,
                })),
              ),
    );
  };
}
