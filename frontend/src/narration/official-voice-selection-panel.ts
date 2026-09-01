import {
  createOfficialVoicePreview,
  getCharacterVoiceBinding,
  getVoicePreview,
  listOfficialVoicePresets,
  listVoiceProfiles,
  selectOfficialVoice,
} from "./api";
import type {
  CharacterVoiceBindingResource,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationSettingsResource,
  OfficialPresetCatalogResponse,
  OfficialPresetId,
  OfficialVoicePreviewRequest,
  OfficialVoiceSelectionRequest as OfficialVoiceSelectionWireRequest,
  OfficialVoiceSelectionResponse,
  VoiceProfileResource,
  VoicePreviewResource,
} from "./contracts";
import {
  voiceActivationEvidenceIsUsable,
  voiceSourceEvidenceIsUsable,
} from "./contracts";
import {
  createOfficialVoiceLibrary,
  officialVoiceCatalogFromWire,
  type OfficialVoiceLibraryReactRuntime,
  type OfficialVoiceSelectionRequest,
  type OfficialVoiceSelectionResult,
} from "./official-voice-library";
import { createNarrationIdempotencyKey } from "./idempotency-key";
import { pollVoicePreview } from "./voice-source-panel";
import { playReadyVoicePreview } from "./voice-preview-playback";


export interface OfficialVoiceSelectionPanelApi {
  listOfficialVoicePresets(signal?: AbortSignal): Promise<OfficialPresetCatalogResponse>;
  listVoiceProfiles(options?: {
    readonly novelId?: string;
    readonly includeLibrary?: boolean;
    readonly signal?: AbortSignal;
  }): Promise<{ readonly items: readonly VoiceProfileResource[] }>;
  getCharacterVoiceBinding(
    novelId: string,
    characterId: string,
    signal?: AbortSignal,
  ): Promise<CharacterVoiceBindingResource>;
  selectOfficialVoice(
    novelId: string,
    payload: OfficialVoiceSelectionWireRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<OfficialVoiceSelectionResponse>;
  createOfficialVoicePreview(
    novelId: string,
    payload: OfficialVoicePreviewRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<VoicePreviewResource>;
  getVoicePreview(
    previewId: string,
    signal?: AbortSignal,
  ): Promise<VoicePreviewResource>;
}


export interface OfficialVoicePreviewPlayer {
  play(preview: VoicePreviewResource, signal: AbortSignal): Promise<void>;
}


export type OfficialVoiceSelectionPanelTarget =
  | { readonly kind: "narrator" }
  | {
    readonly kind: "character";
    readonly characterId: string;
    readonly characterName: string;
  };


export interface OfficialVoiceSelectionPanelProps {
  readonly novelId: string;
  readonly settings: NarrationSettingsResource;
  readonly target: OfficialVoiceSelectionPanelTarget;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly projection?: OfficialVoiceSelectionPanelProjection;
  readonly headerAction?: unknown;
  readonly presentation?: "standalone" | "embedded";
  readonly onChanged?: () => void;
}


export type CharacterVoiceBindingProjection = Pick<
  CharacterVoiceBindingResource,
  | "binding_id"
  | "novel_id"
  | "character_id"
  | "binding_policy"
  | "profile_id"
  | "version_id"
  | "language"
  | "version"
>;


export type OfficialVoiceSelectionPanelProjection =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | {
    readonly phase: "ready";
    readonly binding: CharacterVoiceBindingProjection | null;
    readonly profiles: readonly VoiceProfileResource[];
  };


interface ReadyState {
  readonly phase: "ready";
  readonly catalog: ReturnType<typeof officialVoiceCatalogFromWire>;
  readonly profiles: readonly VoiceProfileResource[];
  readonly binding: CharacterVoiceBindingProjection | null;
  readonly activePresetId: string | null;
  readonly settingsVersion: number;
  readonly targetLanguage: string;
  readonly bindingVersion: number | null;
}


type LoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | ReadyState;


const DEFAULT_API: OfficialVoiceSelectionPanelApi = {
  createOfficialVoicePreview,
  listOfficialVoicePresets,
  listVoiceProfiles,
  getCharacterVoiceBinding,
  selectOfficialVoice,
  getVoicePreview,
};


const DEFAULT_PREVIEW_PLAYER: OfficialVoicePreviewPlayer = {
  play: playReadyVoicePreview,
};


export async function createAndPlayOfficialVoicePreview(
  api: Pick<
    OfficialVoiceSelectionPanelApi,
    "createOfficialVoicePreview" | "getVoicePreview"
  >,
  player: OfficialVoicePreviewPlayer,
  novelId: string,
  presetId: OfficialPresetId,
  signal: AbortSignal,
): Promise<void> {
  const initial = await api.createOfficialVoicePreview(
    novelId,
    { preset_id: presetId },
    createNarrationIdempotencyKey("official-voice-preview"),
    signal,
  );
  const final = await pollVoicePreview(initial, {
    api: { getVoicePreview: api.getVoicePreview },
    signal,
    delayMs: 800,
    maximumPolls: 120,
  });
  if (final.status !== "preview_ready" || final.preview === null) {
    throw new Error(final.failure?.message ?? "官方音色试听未能完成。");
  }
  await player.play(final.preview, signal);
}


function errorMessage(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "无法加载官方音色库，请稍后重试。";
}


function currentSelection(
  settings: NarrationSettingsResource,
  binding: CharacterVoiceBindingProjection | null,
  target: OfficialVoiceSelectionPanelTarget,
): { readonly profileId: string | null; readonly versionId: string | null } {
  if (target.kind === "narrator") {
    return {
      profileId: settings.values.narrator?.profile_id ?? null,
      versionId: settings.values.narrator?.version_id ?? null,
    };
  }
  return {
    profileId: binding?.profile_id ?? null,
    versionId: binding?.version_id ?? null,
  };
}


export function activeOfficialPresetId(
  settings: NarrationSettingsResource,
  binding: CharacterVoiceBindingProjection | null,
  target: OfficialVoiceSelectionPanelTarget,
  profiles: readonly VoiceProfileResource[],
): string | null {
  const selected = currentSelection(settings, binding, target);
  if (selected.profileId === null || selected.versionId === null) return null;
  const profile = profiles.find((item) => item.profile_id === selected.profileId);
  const version = profile?.versions.find((item) => item.version_id === selected.versionId);
  return version?.source_type === "preset"
    && voiceActivationEvidenceIsUsable(version)
    && voiceSourceEvidenceIsUsable(version)
    ? version.preset_key
    : null;
}


function capabilityEnabled(capabilities: NarrationCapabilities, key: string): boolean {
  const capability = capabilities.items.find((item) => item.key === key);
  return capability?.state === "enabled"
    && capability.visible
    && capability.actionable;
}


export function officialVoiceSelectionDisabled(
  capabilities: NarrationCapabilities,
  authorization: NarrationAuthorizationState,
): boolean {
  return !authorization.can_read
    || !authorization.can_configure
    || !authorization.can_manage_voice_assets
    || !capabilityEnabled(capabilities, "narration_product")
    || !capabilityEnabled(capabilities, "reading_settings")
    || !capabilityEnabled(capabilities, "preset_voice_source");
}


export function officialVoiceSelectionWireRequest(
  request: OfficialVoiceSelectionRequest,
): OfficialVoiceSelectionWireRequest {
  return request.targetKind === "narrator"
    ? {
      preset_id: request.presetId as OfficialPresetId,
      target_kind: "narrator",
      character_id: null,
      expected_settings_version: request.expectedSettingsVersion,
      expected_binding_version: null,
    }
    : {
      preset_id: request.presetId as OfficialPresetId,
      target_kind: "character",
      character_id: request.characterId,
      expected_settings_version: request.expectedSettingsVersion,
      expected_binding_version: request.expectedBindingVersion,
    };
}


export function officialVoiceSelectionResult(
  response: OfficialVoiceSelectionResponse,
): OfficialVoiceSelectionResult {
  const frozen = response.frozen_result;
  return Object.freeze({
    replayed: response.replayed,
    selectionStillCurrent: response.selection_still_current,
    presetId: frozen.preset_id,
    targetKind: frozen.target_kind,
    characterId: frozen.character_id,
    settingsVersion: frozen.settings_version,
    bindingVersion: frozen.binding_version,
    languageMismatch: frozen.language_mismatch,
  });
}


export function createOfficialVoiceSelectionPanel(
  React: OfficialVoiceLibraryReactRuntime,
  api: OfficialVoiceSelectionPanelApi = DEFAULT_API,
  previewPlayer: OfficialVoicePreviewPlayer = DEFAULT_PREVIEW_PLAYER,
): (props: OfficialVoiceSelectionPanelProps) => unknown {
  const h = React.createElement;
  const Library = createOfficialVoiceLibrary(React);

  return function OfficialVoiceSelectionPanel(
    props: OfficialVoiceSelectionPanelProps,
  ): unknown {
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [state, setState] = React.useState<LoadState>({ phase: "loading" });
    const scope = props.target.kind === "character"
      ? `${props.novelId}:character:${props.target.characterId}`
      : `${props.novelId}:narrator`;
    const projectionBindingVersion = props.projection?.phase === "ready"
      ? props.projection.binding?.version ?? null
      : null;
    const projectionProfiles = props.projection?.phase === "ready"
      ? props.projection.profiles
      : null;
    const projectionErrorMessage = props.projection?.phase === "error"
      ? props.projection.message
      : null;

    React.useEffect(() => {
      const controller = new AbortController();
      setState({ phase: "loading" });
      if (props.projection?.phase === "loading") {
        return () => controller.abort();
      }
      if (props.projection?.phase === "error") {
        setState({ phase: "error", message: props.projection.message });
        return () => controller.abort();
      }
      const bindingRequest = props.projection?.phase === "ready"
        ? Promise.resolve(props.projection.binding)
        : props.target.kind === "character"
          ? api.getCharacterVoiceBinding(
            props.novelId,
            props.target.characterId,
            controller.signal,
          )
          : Promise.resolve(null);
      const profilesRequest = props.projection?.phase === "ready"
        ? Promise.resolve({ items: props.projection.profiles })
        : api.listVoiceProfiles({
          novelId: props.novelId,
          includeLibrary: false,
          signal: controller.signal,
        });
      void Promise.all([
        api.listOfficialVoicePresets(controller.signal),
        profilesRequest,
        bindingRequest,
      ]).then(([catalogWire, profileList, binding]) => {
        if (controller.signal.aborted) return;
        const catalog = officialVoiceCatalogFromWire(catalogWire);
        setState({
          phase: "ready",
          catalog,
          profiles: profileList.items,
          binding,
          activePresetId: activeOfficialPresetId(
            props.settings,
            binding,
            props.target,
            profileList.items,
          ),
          settingsVersion: props.settings.version,
          targetLanguage: binding?.language ?? props.settings.values.language,
          bindingVersion: binding?.version ?? null,
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setState({ phase: "error", message: errorMessage(reason) });
      });
      return () => controller.abort();
    }, [
      scope,
      props.settings.version,
      reloadVersion,
      props.projection?.phase,
      projectionBindingVersion,
      projectionProfiles,
      projectionErrorMessage,
    ]);

    const binding = state.phase === "ready" ? state.binding : null;
    const settingsVersion = state.phase === "ready"
      ? state.settingsVersion
      : props.settings.version;
    const targetLanguage = state.phase === "ready"
      ? state.targetLanguage
      : props.settings.values.language;
    const target = props.target.kind === "narrator"
      ? {
        kind: "narrator" as const,
        targetLanguage,
        expectedSettingsVersion: settingsVersion,
      }
      : {
        kind: "character" as const,
        characterId: props.target.characterId,
        characterName: props.target.characterName,
        targetLanguage,
        expectedSettingsVersion: settingsVersion,
        expectedBindingVersion: state.phase === "ready"
          ? state.bindingVersion ?? -1
          : binding?.version ?? -1,
      };

    return h(Library, {
      novelId: props.novelId,
      catalog: state.phase === "ready" ? state.catalog : null,
      target,
      activePresetId: state.phase === "ready" ? state.activePresetId : null,
      loading: state.phase === "loading",
      loadError: state.phase === "error" ? state.message : null,
      disabled: officialVoiceSelectionDisabled(props.capabilities, props.authorization),
      headerAction: props.headerAction,
      presentation: props.presentation,
      onUse: async (
        novelId: string,
        request: OfficialVoiceSelectionRequest,
        idempotencyKey: string,
        signal: AbortSignal,
      ) => officialVoiceSelectionResult(await api.selectOfficialVoice(
        novelId,
        officialVoiceSelectionWireRequest(request),
        idempotencyKey,
        signal,
      )),
      onPreview: async (
        novelId: string,
        item: { readonly presetId: string },
        signal: AbortSignal,
      ) => createAndPlayOfficialVoicePreview(
        api,
        previewPlayer,
        novelId,
        item.presetId as OfficialPresetId,
        signal,
      ),
      onApplied: (result: OfficialVoiceSelectionResult) => {
        setState((current) => current.phase === "ready"
          ? {
            ...current,
            activePresetId: result.presetId,
            settingsVersion: result.settingsVersion,
            bindingVersion: result.bindingVersion,
          }
          : current);
        props.onChanged?.();
      },
      onConflictRefresh: () => {
        props.onChanged?.();
        setReloadVersion((value) => value + 1);
      },
    });
  };
}
