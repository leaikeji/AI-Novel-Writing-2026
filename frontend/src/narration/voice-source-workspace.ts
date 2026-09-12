import {
  NarrationApiError,
  createDesignedVoiceVersion,
  createUploadedVoiceVersion,
  createVoicePreview,
  createVoiceProfile,
  getVoicePreview,
  getVoiceProfile,
  listVoiceProfiles,
  lockVoiceProfile,
} from "./api";
import type {
  NarrationAuthorizationState,
  NarrationCapabilities,
  VoicePreviewResource,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceSourceAvailability,
  VoiceSourceType,
} from "./contracts";
import { voiceSourceEvidenceIsUsable } from "./contracts";
import { createNarrationIdempotencyKey } from "./idempotency-key";
import {
  IDLE_VOICE_SOURCE_WORKFLOW,
  VoiceSourcePanel,
  classifyVoiceSourceFailure,
  createVoiceSourcePanelModel,
  pollVoicePreview,
  submitAuthorizedVoiceUpload,
  submitDesignedVoiceVersion,
  type BlobHasher,
  type VoiceSourceFailure,
  type VoiceSourceWorkflowState,
  type VoiceUploadRightsDraft,
} from "./voice-source-panel";
import {
  createVoicePreviewPlayback,
  type VoicePreviewPlaybackReactRuntime,
} from "./voice-preview-playback";


const PREVIEW_TEXT_MAX_LENGTH = 500;


export const EMPTY_VOICE_UPLOAD_RIGHTS: VoiceUploadRightsDraft = Object.freeze({
  noticeVersion: "voice-rights/1",
  sourceIdentifier: "",
  commercialUse: false,
  redistribution: false,
  voiceCloningConfirmed: false,
  subjectConsentReference: null,
  rightsConfirmed: false,
});


export interface VoiceSourceWorkspaceReactRuntime extends VoicePreviewPlaybackReactRuntime {}


export interface VoiceSourceWorkspaceApi {
  listVoiceProfiles: typeof listVoiceProfiles;
  createVoiceProfile: typeof createVoiceProfile;
  getVoiceProfile: typeof getVoiceProfile;
  createDesignedVoiceVersion: typeof createDesignedVoiceVersion;
  createUploadedVoiceVersion: typeof createUploadedVoiceVersion;
  createVoicePreview: typeof createVoicePreview;
  getVoicePreview: typeof getVoicePreview;
  lockVoiceProfile: typeof lockVoiceProfile;
}


export interface VoiceSourceWorkspaceProps {
  readonly novelId: string;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly voiceSources: readonly VoiceSourceAvailability[];
  readonly suggestedProfileName?: string;
  readonly className?: string;
  readonly onProfileLocked?: (profile: VoiceProfileResource) => void;
}


export type VoiceSourceWorkspacePhase =
  | "loading"
  | "ready"
  | "creating-profile"
  | "designing"
  | "uploading"
  | "creating-preview"
  | "polling-preview"
  | "locking"
  | "conflict"
  | "error";


export interface VoiceSourceWorkspaceState {
  readonly scopeNovelId: string;
  readonly phase: VoiceSourceWorkspacePhase;
  readonly profiles: readonly VoiceProfileResource[];
  readonly selectedProfileId: string | null;
  readonly selectedVersionId: string | null;
  readonly selectedSource: VoiceSourceType | null;
  readonly profileName: string;
  readonly language: "zh-CN";
  readonly referenceAudio: File | null;
  readonly referenceText: string;
  readonly designDescription: string;
  readonly uploadRights: VoiceUploadRightsDraft;
  readonly previewText: string;
  readonly workflow: VoiceSourceWorkflowState;
  readonly previewPlayed: boolean;
  readonly qualityConfirmed: boolean;
  readonly message: string;
  readonly failure: VoiceSourceFailure | null;
}


interface InputEvent {
  readonly target: {
    readonly value: string;
    readonly checked: boolean;
  };
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
}


const DEFAULT_API: VoiceSourceWorkspaceApi = {
  listVoiceProfiles,
  createVoiceProfile,
  getVoiceProfile,
  createDesignedVoiceVersion,
  createUploadedVoiceVersion,
  createVoicePreview,
  getVoicePreview,
  lockVoiceProfile,
};


export function createVoiceWorkspaceIdempotencyKey(kind: string): string {
  return createNarrationIdempotencyKey(`voice-${kind}`);
}


function initialState(novelId: string, suggestedName: string): VoiceSourceWorkspaceState {
  return {
    scopeNovelId: novelId,
    phase: "loading",
    profiles: [],
    selectedProfileId: null,
    selectedVersionId: null,
    selectedSource: null,
    profileName: suggestedName,
    language: "zh-CN",
    referenceAudio: null,
    referenceText: "",
    designDescription: "",
    uploadRights: EMPTY_VOICE_UPLOAD_RIGHTS,
    previewText: "你好，这是当前音色的朗读试听。",
    workflow: IDLE_VOICE_SOURCE_WORKFLOW,
    previewPlayed: false,
    qualityConfirmed: false,
    message: "正在加载作品音色…",
    failure: null,
  };
}


export function novelScopedVoiceProfiles(
  novelId: string,
  profiles: readonly VoiceProfileResource[],
): readonly VoiceProfileResource[] {
  const seen = new Set<string>();
  const scoped: VoiceProfileResource[] = [];
  for (const profile of profiles) {
    if (profile.novel_id !== novelId) {
      throw new Error("音色列表包含当前作品范围之外的数据，已拒绝显示。");
    }
    if (seen.has(profile.profile_id)) {
      throw new Error("音色列表包含重复档案，已拒绝显示。");
    }
    seen.add(profile.profile_id);
    const onlyOfficialPresets = profile.versions.length > 0 && profile.versions.every((version) => (
      version.profile_id === profile.profile_id
      && version.source_type === "preset"
      && voiceSourceEvidenceIsUsable(version)
    ));
    // This is a view filter, never deletion: empty drafts and mixed/private histories remain editable.
    if (profile.status !== "archived" && profile.status !== "unavailable" && !onlyOfficialPresets) {
      scoped.push(profile);
    }
  }
  return scoped.sort((left, right) => (
    left.name.localeCompare(right.name, "zh-CN")
      || left.profile_id.localeCompare(right.profile_id)
  ));
}


function replaceProfile(
  profiles: readonly VoiceProfileResource[],
  profile: VoiceProfileResource,
): readonly VoiceProfileResource[] {
  return [...profiles.filter((item) => item.profile_id !== profile.profile_id), profile]
    .sort((left, right) => (
      left.name.localeCompare(right.name, "zh-CN")
        || left.profile_id.localeCompare(right.profile_id)
    ));
}


function isWorkspaceSelectableVersion(version: VoiceProfileVersionResource): boolean {
  if (
    version.source_type === "generated"
    && version.rights.source_kind === "qwen_synthetic_design"
    && version.description_available
  ) return true;
  return voiceSourceEvidenceIsUsable(version);
}


function selectableVersions(profile: VoiceProfileResource | null): readonly VoiceProfileVersionResource[] {
  if (profile === null) return [];
  return [...profile.versions]
    .filter((version) => (
      version.profile_id === profile.profile_id
      && isWorkspaceSelectableVersion(version)
      && version.state !== "deleted"
      && version.state !== "unavailable"
      && version.rights.state === "active"
    ))
    .sort((left, right) => right.version_number - left.version_number);
}


function defaultVersionId(profile: VoiceProfileResource | null): string | null {
  const versions = selectableVersions(profile);
  if (profile?.current_version_id && versions.some((item) => item.version_id === profile.current_version_id)) {
    return profile.current_version_id;
  }
  return versions[0]?.version_id ?? null;
}


function isAbortLike(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


function workspaceFailure(reason: unknown): VoiceSourceFailure {
  return classifyVoiceSourceFailure(reason);
}


function networkFailure(reason: unknown): boolean {
  return !isAbortLike(reason) && !(reason instanceof NarrationApiError);
}


function operationIntent(...parts: readonly unknown[]): string {
  return JSON.stringify(parts);
}


function assertProfileScope(novelId: string, profile: VoiceProfileResource): VoiceProfileResource {
  if (profile.novel_id !== novelId) {
    throw new Error("音色档案响应与当前作品不一致，已停止操作。");
  }
  return profile;
}


function previewMatches(
  preview: VoicePreviewResource,
  profileId: string,
  versionId: string,
): boolean {
  return preview.profile_id === profileId && preview.version_id === versionId;
}


export function createVoiceSourceWorkspace(
  React: VoiceSourceWorkspaceReactRuntime,
  api: VoiceSourceWorkspaceApi = DEFAULT_API,
  polling: {
    readonly delayMs?: number;
    readonly maximumPolls?: number;
    readonly delay?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
    readonly hashBlob?: BlobHasher;
  } = {},
): (props: VoiceSourceWorkspaceProps) => unknown {
  const h = React.createElement;
  const PreviewPlayback = createVoicePreviewPlayback(React);

  return function VoiceSourceWorkspace(props: VoiceSourceWorkspaceProps): unknown {
    const suggestedName = props.suggestedProfileName?.trim() || "自定义朗读音色";
    const [state, setState] = React.useState<VoiceSourceWorkspaceState>(() => (
      initialState(props.novelId, suggestedName)
    ));
    const stateRef = React.useRef(state);
    stateRef.current = state;
    const scopeGenerationRef = React.useRef(0);
    const operationSequenceRef = React.useRef(0);
    const operationAbortRef = React.useRef<AbortController | null>(null);
    const idempotencyRef = React.useRef(new Map<string, string>());
    const statusRef = React.useRef<FocusableElement | null>(null);
    const conflictRef = React.useRef<FocusableElement | null>(null);

    const commit = (
      update: VoiceSourceWorkspaceState
        | ((current: VoiceSourceWorkspaceState) => VoiceSourceWorkspaceState),
    ) => {
      setState((current) => {
        const next = typeof update === "function" ? update(current) : update;
        stateRef.current = next;
        return next;
      });
    };

    const ownsScope = (generation: number, sequence: number, controller: AbortController) => (
      !controller.signal.aborted
      && generation === scopeGenerationRef.current
      && sequence === operationSequenceRef.current
      && stateRef.current.scopeNovelId === props.novelId
    );

    const focusStatus = () => queueMicrotask(() => statusRef.current?.focus({ preventScroll: true }));

    const idempotencyKey = (intent: string, kind: string): string => {
      const existing = idempotencyRef.current.get(intent);
      if (existing) return existing;
      if (idempotencyRef.current.size >= 32) {
        const oldest = idempotencyRef.current.keys().next().value as string | undefined;
        if (oldest) idempotencyRef.current.delete(oldest);
      }
      const created = createVoiceWorkspaceIdempotencyKey(kind);
      idempotencyRef.current.set(intent, created);
      return created;
    };

    const applyProfiles = (
      profiles: readonly VoiceProfileResource[],
      preferredProfileId: string | null,
      message: string,
    ) => {
      const current = stateRef.current;
      const selectedProfile = profiles.find((item) => item.profile_id === preferredProfileId)
        ?? profiles.find((item) => item.profile_id === current.selectedProfileId)
        ?? profiles[0]
        ?? null;
      const currentVersionStillExists = selectedProfile?.versions.some((version) => (
        version.version_id === current.selectedVersionId
      )) ?? false;
      commit({
        ...current,
        scopeNovelId: props.novelId,
        phase: "ready",
        profiles,
        selectedProfileId: selectedProfile?.profile_id ?? null,
        selectedVersionId: currentVersionStillExists
          ? current.selectedVersionId
          : defaultVersionId(selectedProfile),
        message,
        failure: null,
      });
    };

    const loadProfiles = (
      generation: number,
      sequence: number,
      controller: AbortController,
      preferredProfileId: string | null,
      message: string,
    ): Promise<readonly VoiceProfileResource[]> => api.listVoiceProfiles({
        novelId: props.novelId,
        includeLibrary: false,
        signal: controller.signal,
      }).then((response) => {
      const profiles = novelScopedVoiceProfiles(props.novelId, response.items);
      if (ownsScope(generation, sequence, controller)) {
        applyProfiles(profiles, preferredProfileId, message);
      }
      return profiles;
    });

    React.useEffect(() => {
      operationAbortRef.current?.abort();
      idempotencyRef.current.clear();
      const generation = ++scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      commit(initialState(props.novelId, suggestedName));
      void loadProfiles(
        generation,
        sequence,
        controller,
        null,
        "",
      ).catch((reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
        commit((current) => ({
          ...current,
          phase: "error",
          message: "加载作品音色失败。",
          failure: workspaceFailure(reason),
        }));
      });
      return () => controller.abort();
    }, [props.novelId]);

    React.useEffect(() => () => {
      operationAbortRef.current?.abort();
      scopeGenerationRef.current += 1;
    }, []);

    React.useEffect(() => {
      if (state.phase === "conflict") conflictRef.current?.focus({ preventScroll: true });
    }, [state.phase]);

    const scopedState = state.scopeNovelId === props.novelId
      ? state
      : initialState(props.novelId, suggestedName);
    const selectedProfile = scopedState.profiles.find((profile) => (
      profile.profile_id === scopedState.selectedProfileId
    )) ?? null;
    const versions = selectableVersions(selectedProfile);
    const sourceVersions = scopedState.selectedSource === null
      ? versions
      : versions.filter((version) => version.source_type === scopedState.selectedSource);
    const selectedVersion = sourceVersions.find((version) => (
      version.version_id === scopedState.selectedVersionId
    )) ?? null;
    const panelModel = createVoiceSourcePanelModel({
      capabilities: props.capabilities,
      authorization: props.authorization,
      voiceSources: props.voiceSources,
      profile: selectedProfile,
      selectedVersionId: selectedVersion?.version_id ?? null,
    });
    const busy = [
      "creating-profile",
      "designing",
      "uploading",
      "creating-preview",
      "polling-preview",
      "locking",
    ].includes(scopedState.phase);
    const actionsBlocked = busy
      || scopedState.phase === "loading"
      || scopedState.phase === "conflict";
    const previewText = scopedState.previewText.trim();
    const previewTextValid = previewText.length > 0 && previewText.length <= PREVIEW_TEXT_MAX_LENGTH;
    const prefix = `anw-voice-workspace-${props.novelId}`;

    const refreshOneProfile = async (
      profileId: string,
      generation: number,
      sequence: number,
      controller: AbortController,
      message: string,
    ): Promise<VoiceProfileResource> => {
      const refreshed = assertProfileScope(
        props.novelId,
        await api.getVoiceProfile(profileId, controller.signal),
      );
      if (ownsScope(generation, sequence, controller)) {
        commit((current) => ({
          ...current,
          phase: "ready",
          profiles: replaceProfile(current.profiles, refreshed),
          selectedProfileId: refreshed.profile_id,
          selectedVersionId: refreshed.versions.some((item) => item.version_id === current.selectedVersionId)
            ? current.selectedVersionId
            : defaultVersionId(refreshed),
          message,
          failure: null,
        }));
      }
      return refreshed;
    };

    const retryLoad = () => {
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      commit((current) => ({ ...current, phase: "loading", message: "正在重新加载作品音色…", failure: null }));
      void loadProfiles(generation, sequence, controller, scopedState.selectedProfileId, "作品音色已刷新。")
        .catch((reason: unknown) => {
          if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
          commit((current) => ({ ...current, phase: "error", message: "刷新作品音色失败。", failure: workspaceFailure(reason) }));
        });
    };

    const createProfileAction = () => {
      const name = stateRef.current.profileName.trim();
      if (!panelModel.actions.canCreateProfile || name.length < 1 || name.length > 240 || actionsBlocked) return;
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      const intent = operationIntent("create-profile", props.novelId, name);
      const key = idempotencyKey(intent, "profile");
      commit((current) => ({ ...current, phase: "creating-profile", message: "正在创建作品专属音色档案…", failure: null }));
      const requestProfile = () => api.createVoiceProfile(
        { novel_id: props.novelId, name },
        key,
        controller.signal,
      );
      void requestProfile().catch(async (reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || !networkFailure(reason)) throw reason;
        return requestProfile();
      })
        .then((profile) => {
          if (!ownsScope(generation, sequence, controller)) return;
          const scoped = assertProfileScope(props.novelId, profile);
          idempotencyRef.current.delete(intent);
          commit((current) => ({
            ...current,
            phase: "ready",
            profiles: replaceProfile(current.profiles, scoped),
            selectedProfileId: scoped.profile_id,
            selectedVersionId: defaultVersionId(scoped),
            selectedSource: null,
            message: "作品专属音色档案已创建。下一步选择文字设计或上传有权使用的参考录音。",
            failure: null,
          }));
          focusStatus();
        })
        .catch((reason: unknown) => {
          if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
          commit((current) => ({
            ...current,
            phase: reason instanceof NarrationApiError && reason.detail.code === "VERSION_CONFLICT" ? "conflict" : "error",
            message: "创建音色档案失败；重试会复用同一幂等键。",
            failure: workspaceFailure(reason),
          }));
          focusStatus();
        });
    };

    const selectProfile = (profileId: string) => {
      if (actionsBlocked) return;
      const profile = scopedState.profiles.find((item) => item.profile_id === profileId);
      if (!profile) return;
      operationAbortRef.current?.abort();
      operationSequenceRef.current += 1;
      idempotencyRef.current.clear();
      commit((current) => ({
        ...current,
        phase: "ready",
        selectedProfileId: profile.profile_id,
        selectedVersionId: defaultVersionId(profile),
        selectedSource: null,
        referenceAudio: null,
        referenceText: "",
        designDescription: "",
        workflow: IDLE_VOICE_SOURCE_WORKFLOW,
        previewPlayed: false,
        qualityConfirmed: false,
        message: "已切换音色档案。尚未改变旁白或人物绑定。",
        failure: null,
      }));
    };

    const createDesignedAction = () => {
      const current = stateRef.current;
      const profile = current.profiles.find((item) => item.profile_id === current.selectedProfileId) ?? null;
      const currentModel = createVoiceSourcePanelModel({
        capabilities: props.capabilities,
        authorization: props.authorization,
        voiceSources: props.voiceSources,
        profile,
        selectedVersionId: current.selectedVersionId,
      });
      const description = current.designDescription.trim();
      if (
        profile === null
        || current.selectedSource !== "generated"
        || description.length < 1
        || description.length > 500
        || !previewTextValid
        || actionsBlocked
      ) return;
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      const intent = operationIntent(
        "designed",
        profile.profile_id,
        profile.version,
        description,
        "zh-CN",
        null,
      );
      const key = idempotencyKey(intent, "designed");
      commit((latest) => ({
        ...latest,
        phase: "designing",
        workflow: IDLE_VOICE_SOURCE_WORKFLOW,
        previewPlayed: false,
        qualityConfirmed: false,
        message: "正在创建普通话设计候选…",
        failure: null,
      }));
      const requestDesigned = () => submitDesignedVoiceVersion(currentModel, {
        profileId: profile.profile_id,
        expectedProfileVersion: profile.version,
        description,
        language: "zh-CN",
        seed: null,
        idempotencyKey: key,
        signal: controller.signal,
      }, { createDesignedVoiceVersion: api.createDesignedVoiceVersion });
      void requestDesigned().catch(async (reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || !networkFailure(reason)) throw reason;
        return requestDesigned();
      }).then(async (created) => {
        if (!ownsScope(generation, sequence, controller)) return;
        const refreshed = await refreshOneProfile(
          profile.profile_id,
          generation,
          sequence,
          controller,
          "普通话设计候选已创建。下一步生成试听。",
        );
        if (!ownsScope(generation, sequence, controller)) return;
        if (!refreshed.versions.some((item) => item.version_id === created.version_id)) {
          throw new Error("设计响应未出现在刷新后的音色档案中。");
        }
        idempotencyRef.current.delete(intent);
        commit((latest) => ({
          ...latest,
          phase: "ready",
          selectedVersionId: created.version_id,
          workflow: IDLE_VOICE_SOURCE_WORKFLOW,
          previewPlayed: false,
          qualityConfirmed: false,
          message: "普通话设计候选已创建。点击“生成试听”后将由本地模型生成试听。",
          failure: null,
        }));
        focusStatus();
      }).catch((reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
        const failure = workspaceFailure(reason);
        commit((latest) => ({
          ...latest,
          phase: failure.kind === "conflict" ? "conflict" : "error",
          workflow: { status: "failed", preview: null, failure },
          message: failure.kind === "conflict"
            ? "音色档案版本已变化。请刷新后重新创建设计候选。"
            : "创建设计候选失败；描述和试听文本已保留。",
          failure,
        }));
        focusStatus();
      });
    };

    const uploadAction = () => {
      const current = stateRef.current;
      const profile = current.profiles.find((item) => item.profile_id === current.selectedProfileId) ?? null;
      const file = current.referenceAudio;
      const currentModel = createVoiceSourcePanelModel({
        capabilities: props.capabilities,
        authorization: props.authorization,
        voiceSources: props.voiceSources,
        profile,
        selectedVersionId: current.selectedVersionId,
      });
      if (profile === null || file === null || current.selectedSource !== "uploaded" || actionsBlocked) return;
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      const intent = operationIntent(
        "upload",
        profile.profile_id,
        profile.version,
        file.name,
        file.size,
        file.lastModified,
        current.language,
        current.referenceText.trim(),
        current.uploadRights,
      );
      const key = idempotencyKey(intent, "upload");
      commit((latest) => ({
        ...latest,
        phase: "uploading",
        workflow: { status: "uploading", preview: null, failure: null },
        previewPlayed: false,
        qualityConfirmed: false,
        message: "正在校验并上传参考录音…",
        failure: null,
      }));
      const requestUpload = () => submitAuthorizedVoiceUpload(currentModel, {
        profileId: profile.profile_id,
        expectedProfileVersion: profile.version,
        language: current.language,
        originalFilename: file.name,
        referenceAudio: file,
        referenceText: current.referenceText,
        rights: current.uploadRights,
        idempotencyKey: key,
        signal: controller.signal,
      }, {
        api: { createUploadedVoiceVersion: api.createUploadedVoiceVersion },
        hashBlob: polling.hashBlob,
      });
      void requestUpload().catch(async (reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || !networkFailure(reason)) throw reason;
        return requestUpload();
      })
        .then(async (created) => {
          if (!ownsScope(generation, sequence, controller)) return;
          const refreshed = await refreshOneProfile(
            profile.profile_id,
            generation,
            sequence,
            controller,
            "候选音色版本已上传。请选择版本并生成试听。",
          );
          if (!ownsScope(generation, sequence, controller)) return;
          if (!refreshed.versions.some((item) => item.version_id === created.version_id)) {
            throw new Error("上传响应未出现在刷新后的音色档案中。");
          }
          idempotencyRef.current.delete(intent);
          commit((latest) => ({
            ...latest,
            selectedVersionId: created.version_id,
            referenceAudio: null,
            referenceText: "",
            workflow: IDLE_VOICE_SOURCE_WORKFLOW,
            previewPlayed: false,
            message: "候选音色版本已上传。请选择版本并生成试听。",
          }));
          focusStatus();
        })
        .catch((reason: unknown) => {
          if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
          const failure = workspaceFailure(reason);
          commit((latest) => ({
            ...latest,
            phase: failure.kind === "conflict" ? "conflict" : "error",
            workflow: { status: "failed", preview: null, failure },
            message: failure.kind === "conflict"
              ? "音色档案版本已变化。请刷新后核对，再重新上传。"
              : "上传失败；文件和权利表单已保留，重试会复用同一幂等键。",
            failure,
          }));
          focusStatus();
        });
    };

    const pollPreview = async (
      initial: VoicePreviewResource,
      generation: number,
      sequence: number,
      controller: AbortController,
    ): Promise<void> => {
      if (!previewMatches(initial, initial.profile_id, initial.version_id)) return;
      const final = await pollVoicePreview(initial, {
        api: { getVoicePreview: api.getVoicePreview },
        signal: controller.signal,
        delayMs: polling.delayMs,
        maximumPolls: polling.maximumPolls,
        delay: polling.delay,
        onState: (workflow) => {
          if (!ownsScope(generation, sequence, controller)) return;
          commit((current) => ({
            ...current,
            phase: ["preview_queued", "preview_running"].includes(workflow.status)
              ? "polling-preview"
              : current.phase,
            workflow,
            message: workflow.status === "preview_running"
              ? "Qwen TTS 正在生成临时试听…"
              : workflow.status === "preview_queued"
                ? "试听已排队，正在等待本地模型资源…"
                : current.message,
          }));
        },
      });
      if (!ownsScope(generation, sequence, controller)) return;
      if (final.status === "preview_ready" && final.preview !== null) {
        await refreshOneProfile(
          final.preview.profile_id,
          generation,
          sequence,
          controller,
          "试听已就绪。请播放检查后显式确认质量，再锁定版本。",
        );
        if (!ownsScope(generation, sequence, controller)) return;
        commit((current) => ({
          ...current,
          phase: "ready",
          workflow: final,
          previewPlayed: false,
          qualityConfirmed: false,
          message: "试听已就绪。请播放检查后显式确认质量，再锁定版本。",
          failure: null,
        }));
        focusStatus();
        return;
      }
      const timedOut = final.status === "preview_timeout";
      commit((current) => ({
        ...current,
        phase: final.status === "cancelled" ? "ready" : "error",
        workflow: final,
        message: timedOut
          ? "本轮等待已超时，但任务仍可继续查询；点击“继续等待试听”。"
          : final.failure?.message ?? "试听未能完成。",
        failure: final.failure,
      }));
      focusStatus();
    };

    const createPreviewAction = () => {
      const current = stateRef.current;
      const profile = current.profiles.find((item) => item.profile_id === current.selectedProfileId) ?? null;
      const version = profile?.versions.find((item) => item.version_id === current.selectedVersionId) ?? null;
      const currentModel = createVoiceSourcePanelModel({
        capabilities: props.capabilities,
        authorization: props.authorization,
        voiceSources: props.voiceSources,
        profile,
        selectedVersionId: version?.version_id ?? null,
      });
      const text = current.previewText.trim();
      if (profile === null || version === null || !currentModel.actions.canPreview || !previewTextValid || actionsBlocked) return;
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      const intent = operationIntent("preview", profile.profile_id, version.version_id, text);
      const key = idempotencyKey(intent, "preview");
      commit((latest) => ({
        ...latest,
        phase: "creating-preview",
        workflow: IDLE_VOICE_SOURCE_WORKFLOW,
        previewPlayed: false,
        qualityConfirmed: false,
        message: "正在创建试听任务…",
        failure: null,
      }));
      const requestPreview = () => api.createVoicePreview(
        profile.profile_id,
        { version_id: version.version_id, preview_text: text },
        key,
        controller.signal,
      );
      void requestPreview().catch(async (reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || !networkFailure(reason)) throw reason;
        await refreshOneProfile(
          profile.profile_id,
          generation,
          sequence,
          controller,
          "创建试听响应中断，已先刷新档案并使用原幂等键恢复。",
        );
        if (!ownsScope(generation, sequence, controller)) throw new DOMException("Aborted", "AbortError");
        return requestPreview();
      }).then(async (preview) => {
        if (!ownsScope(generation, sequence, controller)) return;
        if (!previewMatches(preview, profile.profile_id, version.version_id)) {
          throw new Error("试听响应与当前音色版本不一致。");
        }
        idempotencyRef.current.delete(intent);
        await pollPreview(preview, generation, sequence, controller);
      }).catch((reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
        const failure = workspaceFailure(reason);
        commit((latest) => ({
          ...latest,
          phase: failure.kind === "conflict" ? "conflict" : "error",
          workflow: { status: "failed", preview: null, failure },
          message: "创建试听失败；重试会复用同一幂等键。",
          failure,
        }));
        focusStatus();
      });
    };

    const continuePreviewAction = () => {
      const preview = stateRef.current.workflow.preview;
      if (
        preview === null
        || !["queued", "running"].includes(preview.status)
        || !["preview_timeout", "preview_queued", "preview_running"].includes(stateRef.current.workflow.status)
        || actionsBlocked
      ) return;
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      commit((current) => ({ ...current, phase: "polling-preview", message: "继续等待试听任务…", failure: null }));
      void pollPreview(preview, generation, sequence, controller);
    };

    const lockAction = () => {
      const current = stateRef.current;
      const profile = current.profiles.find((item) => item.profile_id === current.selectedProfileId) ?? null;
      const version = profile?.versions.find((item) => item.version_id === current.selectedVersionId) ?? null;
      const currentModel = createVoiceSourcePanelModel({
        capabilities: props.capabilities,
        authorization: props.authorization,
        voiceSources: props.voiceSources,
        profile,
        selectedVersionId: version?.version_id ?? null,
      });
      if (
        profile === null
        || version === null
        || !current.previewPlayed
        || !current.qualityConfirmed
        || !currentModel.actions.canLock
        || actionsBlocked
      ) return;
      operationAbortRef.current?.abort();
      const generation = scopeGenerationRef.current;
      const sequence = ++operationSequenceRef.current;
      const controller = new AbortController();
      operationAbortRef.current = controller;
      commit((latest) => ({ ...latest, phase: "locking", message: "正在锁定不可变音色版本…", failure: null }));
      void api.lockVoiceProfile(profile.profile_id, {
        expected_profile_version: profile.version,
        version_id: version.version_id,
        quality_confirmed: true,
      }, controller.signal).catch(async (reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || !networkFailure(reason)) throw reason;
        const recovered = await refreshOneProfile(
          profile.profile_id,
          generation,
          sequence,
          controller,
          "锁定响应中断，已刷新服务端状态。",
        );
        const locked = recovered.current_version_id === version.version_id
          && recovered.versions.some((item) => (
            item.version_id === version.version_id
            && item.state === "locked"
            && item.quality_state === "accepted"
          ));
        if (locked) return recovered;
        throw reason;
      }).then(async (saved) => {
        if (!ownsScope(generation, sequence, controller)) return;
        const scoped = assertProfileScope(props.novelId, saved);
        const refreshed = await refreshOneProfile(
          scoped.profile_id,
          generation,
          sequence,
          controller,
          "音色版本已锁定。旁白和人物绑定尚未改变，请在对应面板显式保存。",
        );
        if (!ownsScope(generation, sequence, controller)) return;
        commit((latest) => ({
          ...latest,
          phase: "ready",
          selectedVersionId: refreshed.current_version_id,
          previewPlayed: false,
          qualityConfirmed: false,
          message: "音色版本已锁定。旁白和人物绑定尚未改变，请在对应面板显式保存。",
          failure: null,
        }));
        props.onProfileLocked?.(refreshed);
        focusStatus();
      }).catch(async (reason: unknown) => {
        if (!ownsScope(generation, sequence, controller) || isAbortLike(reason)) return;
        const failure = workspaceFailure(reason);
        if (failure.kind === "conflict") {
          try {
            await refreshOneProfile(
              profile.profile_id,
              generation,
              sequence,
              controller,
              "服务端音色版本已变化。已刷新，请重新试听和确认。",
            );
          } catch {
            // Keep the conflict visible even when refresh also fails.
          }
        }
        if (!ownsScope(generation, sequence, controller)) return;
        commit((latest) => ({
          ...latest,
          phase: failure.kind === "conflict" ? "conflict" : "error",
          previewPlayed: false,
          qualityConfirmed: false,
          message: failure.kind === "conflict"
            ? "服务端音色版本已变化。请核对刷新结果，重新试听后再确认。"
            : "锁定音色失败，未改变任何旁白或人物绑定。",
          failure,
        }));
        focusStatus();
      });
    };

    const cancelAction = () => {
      operationAbortRef.current?.abort();
      operationSequenceRef.current += 1;
      commit((current) => ({
        ...current,
        phase: "ready",
        workflow: current.workflow.preview === null
          ? IDLE_VOICE_SOURCE_WORKFLOW
          : {
            status: "cancelled",
            preview: current.workflow.preview,
            failure: {
              kind: "cancelled",
              code: "CANCELLED",
              message: "本地等待已取消；服务端任务如已提交可能继续执行。",
              retryable: false,
            },
          },
        message: "本地等待已取消；未改变已锁定版本或任何绑定。",
        failure: null,
      }));
      focusStatus();
    };

    const createProfileControls = h("div", { className: "anw-voice-workspace__create-row" },
      h("label", { className: "anw-voice-workspace__field" },
        h("span", null, "音色名称"),
        h("input", {
          type: "text",
          value: scopedState.profileName,
          maxLength: 240,
          placeholder: "例如：温柔女旁白、陈屿的声音",
          disabled: actionsBlocked || !panelModel.actions.canCreateProfile,
          onChange: (event: InputEvent) => commit((current) => ({
            ...current,
            profileName: event.target.value,
            failure: null,
          })),
        }),
      ),
      h("button", {
        type: "button",
        disabled: actionsBlocked
          || !panelModel.actions.canCreateProfile
          || scopedState.profileName.trim().length < 1
          || scopedState.profileName.trim().length > 240,
        onClick: createProfileAction,
      }, scopedState.phase === "creating-profile" ? "创建中…" : "创建音色档案"),
    );

    const renderProfileControls = () => h(
      "section",
      { className: "anw-voice-workspace__profiles", "aria-labelledby": `${prefix}-profile-heading` },
      h("div", { className: "anw-voice-workspace__section-heading" },
        h("div", null,
          h("h3", { id: `${prefix}-profile-heading` }, "1. 选择或新建音色"),
          h("p", null, "先取名建立档案，再设计声音或上传录音；创建档案不会启动语音模型。"),
        ),
      ),
      scopedState.profiles.length > 0
        ? h("label", { className: "anw-voice-workspace__field" },
          h("span", null, "当前音色"),
          h("select", {
            value: scopedState.selectedProfileId ?? "",
            disabled: actionsBlocked,
            onChange: (event: InputEvent) => selectProfile(event.target.value),
          },
          ...scopedState.profiles.map((profile) => h(
            "option",
            { key: profile.profile_id, value: profile.profile_id },
            `${profile.name}${profile.current_version_id ? " · 已锁定" : " · 待完成"}`,
          )),
          ),
        )
        : h("p", { className: "anw-voice-workspace__empty", role: "status" },
          "还没有私人音色。你可以用文字设计，也可以上传有权使用的录音。",
        ),
      scopedState.profiles.length > 0
        ? h("details", { className: "anw-voice-workspace__new-profile" },
          h("summary", null, "新建另一个音色"),
          createProfileControls,
        )
        : createProfileControls,
    );

    const versionControls = selectedProfile === null || scopedState.selectedSource === null || sourceVersions.length === 0
      ? null
      : h(
        "section",
        { className: "anw-voice-workspace__preview", "aria-labelledby": `${prefix}-preview-heading` },
        h("div", { className: "anw-voice-workspace__section-heading" },
          h("div", null,
            h("h3", { id: `${prefix}-preview-heading` }, "3. 试听并确认"),
            h("p", null, selectedVersion?.state === "locked"
              ? "这个音色已锁定。请到旁白或人物配音中选择使用，不会自动替换现有声音。"
              : "生成试听，听过满意后确认锁定。创建和试听不会改变已有配音。"),
          ),
        ),
        h("div", { className: "anw-voice-workspace__preview-grid" },
            h("label", { className: "anw-voice-workspace__field" },
              h("span", null, "候选音色版本"),
              h("select", {
                value: selectedVersion?.version_id ?? "",
                disabled: actionsBlocked,
                onChange: (event: InputEvent) => commit((current) => ({
                  ...current,
                  selectedVersionId: event.target.value || null,
                  workflow: IDLE_VOICE_SOURCE_WORKFLOW,
                  previewPlayed: false,
                  qualityConfirmed: false,
                  message: "已切换候选版本，请重新生成试听。",
                  failure: null,
                })),
              },
              ...sourceVersions.map((version) => h(
                "option",
                { key: version.version_id, value: version.version_id },
                `版本 ${version.version_number} · 普通话 · ${version.state === "locked" ? "已锁定" : "待确认"}`,
              )),
              ),
            ),
            scopedState.selectedSource === "generated"
              ? null
              : h("label", { className: "anw-voice-workspace__field" },
                h("span", null, "试听文本（1–500 字）"),
                h("textarea", {
                  value: scopedState.previewText,
                  maxLength: PREVIEW_TEXT_MAX_LENGTH,
                  rows: 3,
                  disabled: actionsBlocked,
                  "aria-invalid": !previewTextValid,
                  onChange: (event: InputEvent) => commit((current) => ({
                    ...current,
                    previewText: event.target.value,
                    workflow: IDLE_VOICE_SOURCE_WORKFLOW,
                    previewPlayed: false,
                    qualityConfirmed: false,
                    failure: null,
                  })),
                }),
              ),
          ),
        h(PreviewPlayback, {
          preview: scopedState.workflow.status === "preview_ready"
            ? scopedState.workflow.preview
            : null,
          onPlayed: () => commit((current) => ({
            ...current,
            previewPlayed: true,
            message: "试听已开始播放。听检后请显式确认质量，再锁定版本。",
          })),
        }),
        scopedState.workflow.status === "preview_timeout"
          ? h("button", {
            type: "button",
            className: "anw-voice-workspace__continue",
            disabled: actionsBlocked,
            onClick: continuePreviewAction,
          }, "继续等待试听")
          : null,
      );

    return h(
      "section",
      {
        className: ["anw-voice-workspace", props.className ?? ""].filter(Boolean).join(" "),
        role: "region",
        "aria-labelledby": `${prefix}-heading`,
        "aria-describedby": `${prefix}-status`,
        "aria-busy": busy || scopedState.phase === "loading",
        "data-voice-workspace-phase": scopedState.phase,
        "data-voice-workspace-novel-id": props.novelId,
      },
      h("header", { className: "anw-voice-workspace__header" },
        h("div", null,
          h("p", { className: "anw-voice-workspace__eyebrow" }, "我的声音 · 普通话"),
          h("h2", { id: `${prefix}-heading`, tabIndex: -1 }, "私人音色"),
          h("p", null, "为这部作品定制声音。官方声音请在“旁白音色”中选择。"),
        ),
        h("span", { className: "anw-voice-workspace__scope" }, "当前作品专属"),
      ),
      h("div", {
        id: `${prefix}-status`,
        ref: statusRef,
        className: [
          "anw-voice-workspace__status",
          scopedState.failure ? "is-error" : "",
        ].filter(Boolean).join(" "),
        role: scopedState.failure ? "alert" : "status",
        "aria-live": "polite",
        "aria-atomic": "true",
        tabIndex: -1,
        hidden: !scopedState.failure && !scopedState.message,
      }, scopedState.failure?.message ?? scopedState.message),
      scopedState.phase === "loading"
        ? h("p", { className: "anw-voice-workspace__loading" }, "正在读取作品音色档案…")
        : null,
      scopedState.phase === "error"
        ? h("div", { className: "anw-voice-workspace__error" },
          h("strong", null, scopedState.message),
          h("button", { type: "button", onClick: retryLoad }, "刷新服务端状态"),
        )
        : null,
      scopedState.phase === "conflict"
        ? h("div", {
          ref: conflictRef,
          className: "anw-voice-workspace__error",
          role: "alert",
          tabIndex: -1,
        },
        h("strong", null, "服务端版本已变化"),
        h("p", null, scopedState.message),
        h("button", { type: "button", onClick: retryLoad }, "刷新并核对"),
        )
        : null,
      scopedState.phase !== "loading" ? renderProfileControls() : null,
      selectedProfile === null
        ? null
        : h("div", { className: "anw-voice-workspace__source" },
          h("h3", { id: `${prefix}-source-heading` }, "2. 选择音色来源"),
          h(VoiceSourcePanel, {
            embedded: true,
            ariaLabelledBy: `${prefix}-source-heading`,
            model: panelModel,
            selectedSource: scopedState.selectedSource,
            workflow: scopedState.workflow,
            uploadRights: scopedState.uploadRights,
            referenceText: scopedState.referenceText,
            designDescription: scopedState.designDescription,
            previewText: scopedState.previewText,
            busy: actionsBlocked,
            cancelAllowed: busy && scopedState.phase !== "locking",
            referenceAudioSelected: scopedState.referenceAudio !== null,
            previewTextValid: previewTextValid
              && scopedState.workflow.status !== "preview_timeout",
            qualityConfirmationAllowed: scopedState.previewPlayed,
            qualityConfirmed: scopedState.qualityConfirmed,
            previewContent: versionControls,
            onSelectSource: (source: VoiceSourceType) => {
              if (!["generated", "uploaded"].includes(source) || actionsBlocked) return;
              commit((current) => ({
                ...current,
                selectedSource: source,
                selectedVersionId: selectableVersions(selectedProfile)
                  .find((version) => version.source_type === source)?.version_id ?? null,
                workflow: IDLE_VOICE_SOURCE_WORKFLOW,
                previewPlayed: false,
                qualityConfirmed: false,
                message: source === "generated"
                  ? "已选择文字设计。语言固定为普通话，请填写描述和试听文本。"
                  : "已选择上传参考录音。语言固定为普通话，请完整填写录音文字和权利表单。",
                failure: null,
              }));
            },
            onDesignDescriptionChange: (description: string) => commit((current) => ({
              ...current,
              designDescription: description,
              workflow: IDLE_VOICE_SOURCE_WORKFLOW,
              previewPlayed: false,
              qualityConfirmed: false,
              failure: null,
            })),
            onPreviewTextChange: (text: string) => commit((current) => ({
              ...current,
              previewText: text,
              workflow: IDLE_VOICE_SOURCE_WORKFLOW,
              previewPlayed: false,
              qualityConfirmed: false,
              failure: null,
            })),
            onReferenceTextChange: (referenceText: string) => commit((current) => ({
              ...current,
              referenceText,
              failure: null,
            })),
            onUploadRightsChange: (patch: Partial<VoiceUploadRightsDraft>) => commit((current) => ({
              ...current,
              uploadRights: { ...current.uploadRights, ...patch },
              failure: null,
            })),
            onReferenceAudioChange: (file: File | null) => commit((current) => ({
              ...current,
              referenceAudio: file,
              failure: null,
            })),
            onUpload: uploadAction,
            onCreateDesigned: createDesignedAction,
            onPreview: createPreviewAction,
            onQualityConfirmationChange: (confirmed: boolean) => commit((current) => ({
              ...current,
              qualityConfirmed: current.previewPlayed && confirmed,
              message: confirmed
                ? "已记录本次试听质量确认；仍需点击锁定，且不会自动绑定。"
                : "已取消质量确认。",
            })),
            onLock: lockAction,
            onCancel: cancelAction,
          }),
        ),
    );
  };
}
