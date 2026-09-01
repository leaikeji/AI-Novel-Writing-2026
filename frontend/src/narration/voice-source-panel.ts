import {
  NarrationApiError,
  createUploadedVoiceVersion,
  getVoicePreview,
} from "./api";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationErrorCode,
  UploadedVoiceVersionMetadata,
  VoicePreviewResource,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceRightsDeclarationRequest,
  VoiceSourceAvailability,
  VoiceSourceType,
} from "./contracts";
import {
  REFERENCE_UPLOAD_MAX_BYTES,
  REFERENCE_UPLOAD_MIME_TYPES,
} from "./contracts";
export {
  T2_D_NARRATION_STYLE_ID,
  T2_D_NARRATION_STYLES,
} from "./styles/t2-d";


type PrivateVoiceSourceType = Exclude<VoiceSourceType, "preset">;


const SOURCE_DEFINITIONS: Readonly<Record<PrivateVoiceSourceType, {
  readonly capability: CapabilityKey;
  readonly label: string;
  readonly description: string;
}>> = Object.freeze({
  uploaded: {
    capability: "reference_clone",
    label: "上传参考录音",
    description: "仅处理作者有权用于声音克隆的 WAV 或 FLAC 私人录音。",
  },
  generated: {
    capability: "voice_generator",
    label: "文字描述生成",
    description: "需要独立 VoiceGenerator 能力；Nano 本身不提供文字造音色。",
  },
});

const SOURCE_ORDER: readonly PrivateVoiceSourceType[] = ["uploaded", "generated"];

export type VoiceSourceWorkflowStatus =
  | "idle"
  | "uploading"
  | "preview_queued"
  | "preview_running"
  | "preview_ready"
  | "preview_timeout"
  | "preview_unavailable"
  | "failed"
  | "cancelled";

export type VoiceSourceFailureKind =
  | "permission"
  | "rights"
  | "capability"
  | "unsupported_media_type"
  | "payload_too_large"
  | "validation"
  | "conflict"
  | "storage"
  | "preview"
  | "network"
  | "cancelled";

export interface VoiceSourceFailure {
  readonly kind: VoiceSourceFailureKind;
  readonly code: NarrationErrorCode | "NETWORK_ERROR" | "ACTION_NOT_ALLOWED" | "CANCELLED";
  readonly message: string;
  readonly retryable: boolean;
}

export interface VoiceSourceWorkflowState {
  readonly status: VoiceSourceWorkflowStatus;
  readonly preview: VoicePreviewResource | null;
  readonly failure: VoiceSourceFailure | null;
}

export interface VoiceSourceCardModel {
  readonly sourceType: VoiceSourceType;
  readonly capability: CapabilityKey;
  readonly label: string;
  readonly description: string;
  readonly visible: boolean;
  readonly enabled: boolean;
  readonly reasonCode: string | null;
  readonly acceptedMimeTypes: readonly string[];
  readonly maximumBytes: number | null;
}

export interface VoiceSourcePanelModel {
  readonly cards: readonly VoiceSourceCardModel[];
  readonly visibleCards: readonly VoiceSourceCardModel[];
  readonly profile: VoiceProfileResource | null;
  readonly selectedVersion: VoiceProfileVersionResource | null;
  readonly actions: {
    readonly canCreateProfile: boolean;
    readonly canPreview: boolean;
    readonly canLock: boolean;
    readonly canConfirmRights: boolean;
  };
  readonly permissionNotice: string | null;
}

export interface CreateVoiceSourcePanelModelInput {
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly voiceSources: readonly VoiceSourceAvailability[];
  readonly profile: VoiceProfileResource | null;
  readonly selectedVersionId: string | null;
}

function capabilityByKey(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | null {
  return capabilities.items.find((item) => item.key === key) ?? null;
}

function sourceReason(
  sourceType: VoiceSourceType,
  capability: FeatureCapability | null,
  availability: VoiceSourceAvailability | null,
  authorization: NarrationAuthorizationState,
): string | null {
  if (capability === null || availability === null) return "VOICE_SOURCE_STATUS_MISSING";
  if (!authorization.can_manage_voice_assets) return "VOICE_ASSET_PERMISSION_REQUIRED";
  if (sourceType === "uploaded" && !authorization.can_confirm_voice_rights) {
    return "VOICE_RIGHTS_PERMISSION_REQUIRED";
  }
  if (capability.state !== "enabled" || !capability.actionable) {
    return capability.reason_code ?? "VOICE_SOURCE_CAPABILITY_DISABLED";
  }
  if (!availability.available) {
    return availability.reason_code ?? "VOICE_SOURCE_UNAVAILABLE";
  }
  return null;
}

export function createVoiceSourcePanelModel(
  input: CreateVoiceSourcePanelModelInput,
): VoiceSourcePanelModel {
  const cards = SOURCE_ORDER.map((sourceType): VoiceSourceCardModel => {
    const definition = SOURCE_DEFINITIONS[sourceType];
    const capability = capabilityByKey(input.capabilities, definition.capability);
    const availability = input.voiceSources.find((item) => item.source_type === sourceType) ?? null;
    const reasonCode = sourceReason(
      sourceType,
      capability,
      availability,
      input.authorization,
    );
    return Object.freeze({
      sourceType,
      capability: definition.capability,
      label: definition.label,
      description: definition.description,
      visible: capability?.visible ?? false,
      enabled: reasonCode === null,
      reasonCode,
      acceptedMimeTypes: Object.freeze([...(availability?.accepted_mime_types ?? [])]),
      maximumBytes: availability?.maximum_bytes ?? null,
    });
  });
  const profile = input.profile;
  const selectedVersion = profile?.versions.find(
    (version) => (
      version.version_id === input.selectedVersionId
      && version.profile_id === profile.profile_id
    ),
  ) ?? null;
  const previewCapability = capabilityByKey(input.capabilities, "voice_preview");
  const readingCapability = capabilityByKey(input.capabilities, "reading_settings");
  const rightsAreActive = selectedVersion?.rights.state === "active";
  const selectedVersionSourceIsValid = selectedVersion === null
    ? false
    : selectedVersion.source_type === "preset"
      ? selectedVersion.rights.source_kind === "official_preset"
        && selectedVersion.official_preset !== null
        && selectedVersion.official_preset.preset_id === selectedVersion.preset_key
      : selectedVersion.source_type === "uploaded"
        ? selectedVersion.rights.source_kind === "user_upload"
        : selectedVersion.rights.source_kind === "voice_generator";
  const profileCanChange = profile !== null
    && !["archived", "unavailable"].includes(profile.status);
  const selectedSourceCard = selectedVersion === null
    ? null
    : cards.find((card) => card.sourceType === selectedVersion.source_type) ?? null;
  const canPreview = Boolean(
    input.authorization.can_manage_voice_assets
    && previewCapability?.state === "enabled"
    && previewCapability.actionable
    && profileCanChange
    && selectedVersion !== null
    && rightsAreActive
    && selectedVersionSourceIsValid
    && selectedSourceCard?.visible === true
    && selectedSourceCard.enabled
  );
  const canLock = Boolean(
    input.authorization.can_manage_voice_assets
    && (selectedVersion?.source_type !== "uploaded" || input.authorization.can_confirm_voice_rights)
    && profileCanChange
    && selectedVersion?.state === "preview_ready"
    && rightsAreActive
    && selectedVersionSourceIsValid
    && selectedSourceCard?.enabled,
  );
  const canCreateProfile = Boolean(
    input.authorization.can_manage_voice_assets
    && readingCapability?.state === "enabled"
    && readingCapability.actionable,
  );
  let permissionNotice: string | null = null;
  if (!input.authorization.can_manage_voice_assets) {
    permissionNotice = "当前身份只能查看音色，不能新增、上传、试听或锁定。";
  } else if (!input.authorization.can_confirm_voice_rights) {
    permissionNotice = "当前身份不能确认参考录音权利；上传来源保持禁用。";
  }
  return Object.freeze({
    cards: Object.freeze(cards),
    visibleCards: Object.freeze(cards.filter((card) => card.visible)),
    profile: input.profile,
    selectedVersion,
    actions: Object.freeze({
      canCreateProfile,
      canPreview,
      canLock,
      canConfirmRights: input.authorization.can_confirm_voice_rights,
    }),
    permissionNotice,
  });
}


export interface VoiceUploadRightsDraft {
  readonly noticeVersion: string;
  readonly sourceIdentifier: string;
  readonly commercialUse: boolean;
  readonly redistribution: boolean;
  readonly voiceCloningConfirmed: boolean;
  readonly subjectConsentReference: string | null;
  readonly rightsConfirmed: boolean;
}

export interface AuthorizedVoiceUploadInput {
  readonly profileId: string;
  readonly expectedProfileVersion: number;
  readonly language: string;
  readonly originalFilename: string;
  readonly referenceAudio: Blob;
  readonly rights: VoiceUploadRightsDraft;
  readonly idempotencyKey: string;
  readonly signal?: AbortSignal;
}

export type BlobHasher = (blob: Blob) => Promise<string>;

export class VoiceSourcePanelActionError extends Error {
  readonly failure: VoiceSourceFailure;

  constructor(failure: VoiceSourceFailure) {
    super(failure.message);
    this.failure = failure;
  }
}

function panelFailure(
  kind: VoiceSourceFailureKind,
  code: VoiceSourceFailure["code"],
  message: string,
  retryable = false,
): VoiceSourceFailure {
  return Object.freeze({ kind, code, message, retryable });
}

function requireUploadInput(input: AuthorizedVoiceUploadInput): void {
  if (typeof Blob === "undefined" || !(input.referenceAudio instanceof Blob)) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "validation",
      "ACTION_NOT_ALLOWED",
      "参考录音不是浏览器文件对象。",
    ));
  }
  if (
    input.originalFilename.length < 1
    || input.originalFilename.length > 240
    || input.originalFilename.includes("/")
    || input.originalFilename.includes("\\")
    || [...input.originalFilename].some((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code < 32 || code === 127;
    })
  ) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "validation",
      "ACTION_NOT_ALLOWED",
      "参考录音文件名不能包含路径。",
    ));
  }
  if (!REFERENCE_UPLOAD_MIME_TYPES.includes(
    input.referenceAudio.type as typeof REFERENCE_UPLOAD_MIME_TYPES[number],
  )) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "unsupported_media_type",
      "UNSUPPORTED_MEDIA_TYPE",
      "参考录音只支持 WAV 或 FLAC。",
    ));
  }
  const expectedSuffix = input.referenceAudio.type === "audio/wav" ? ".wav" : ".flac";
  if (!input.originalFilename.toLowerCase().endsWith(expectedSuffix)) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "unsupported_media_type",
      "UNSUPPORTED_MEDIA_TYPE",
      "参考录音扩展名与 MIME 不一致。",
    ));
  }
  if (
    input.referenceAudio.size <= 0
    || input.referenceAudio.size > REFERENCE_UPLOAD_MAX_BYTES
  ) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "payload_too_large",
      "PAYLOAD_TOO_LARGE",
      `参考录音必须在 1 到 ${REFERENCE_UPLOAD_MAX_BYTES} 字节之间。`,
    ));
  }
  const rights = input.rights;
  if (
    !rights.rightsConfirmed
    || !rights.voiceCloningConfirmed
    || rights.noticeVersion.trim().length === 0
    || rights.noticeVersion.trim().length > 120
    || rights.sourceIdentifier.trim().length === 0
    || rights.sourceIdentifier.trim().length > 240
    || (rights.subjectConsentReference?.trim().length ?? 0) > 240
    || typeof rights.commercialUse !== "boolean"
    || typeof rights.redistribution !== "boolean"
    || !Number.isSafeInteger(input.expectedProfileVersion)
    || input.expectedProfileVersion < 1
    || !/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$/.test(input.language)
  ) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "rights",
      "VOICE_RIGHTS_REQUIRED",
      "上传前必须明确确认来源、授权声明和声音克隆许可。",
    ));
  }
}

export async function sha256Blob(blob: Blob): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "validation",
      "ACTION_NOT_ALLOWED",
      "当前浏览器无法计算参考录音校验值。",
    ));
  }
  const digest = await subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

export async function buildAuthorizedUploadMetadata(
  input: AuthorizedVoiceUploadInput,
  hashBlob: BlobHasher = sha256Blob,
): Promise<UploadedVoiceVersionMetadata> {
  requireUploadInput(input);
  const referenceSha256 = await hashBlob(input.referenceAudio);
  if (!/^[a-f0-9]{64}$/.test(referenceSha256)) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "validation",
      "ACTION_NOT_ALLOWED",
      "参考录音校验值无效，未发起上传。",
    ));
  }
  const declaration: VoiceRightsDeclarationRequest = {
    notice_version: input.rights.noticeVersion.trim(),
    source_identifier: input.rights.sourceIdentifier.trim(),
    purpose: "private_novel_narration",
    commercial_use: input.rights.commercialUse,
    redistribution: input.rights.redistribution,
    voice_cloning: true,
    subject_consent_reference: input.rights.subjectConsentReference?.trim() || null,
    confirmed: true,
  };
  return {
    expected_profile_version: input.expectedProfileVersion,
    language: input.language,
    original_filename: input.originalFilename,
    reference_sha256: referenceSha256,
    rights: declaration,
  };
}

export interface VoiceSourceUploadApi {
  createUploadedVoiceVersion: typeof createUploadedVoiceVersion;
}

export async function submitAuthorizedVoiceUpload(
  model: VoiceSourcePanelModel,
  input: AuthorizedVoiceUploadInput,
  options: {
    readonly api?: VoiceSourceUploadApi;
    readonly hashBlob?: BlobHasher;
  } = {},
): Promise<VoiceProfileVersionResource> {
  const uploaded = model.cards.find((card) => card.sourceType === "uploaded");
  if (uploaded?.visible !== true || uploaded.enabled !== true) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "capability",
      "ACTION_NOT_ALLOWED",
      "上传参考录音当前不可用。",
    ));
  }
  if (
    model.profile === null
    || input.profileId !== model.profile.profile_id
    || input.expectedProfileVersion !== model.profile.version
  ) {
    throw new VoiceSourcePanelActionError(panelFailure(
      "conflict",
      "ACTION_NOT_ALLOWED",
      "音色档案已切换或版本已变化，请刷新后重试。",
    ));
  }
  if (input.signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const metadata = await buildAuthorizedUploadMetadata(input, options.hashBlob);
  if (input.signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const api = options.api ?? { createUploadedVoiceVersion };
  return api.createUploadedVoiceVersion(
    input.profileId,
    metadata,
    input.referenceAudio,
    input.idempotencyKey,
    input.signal,
  );
}


function abortLike(reason: unknown): boolean {
  if (typeof DOMException !== "undefined" && reason instanceof DOMException) {
    return reason.name === "AbortError";
  }
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}

export function classifyVoiceSourceFailure(reason: unknown): VoiceSourceFailure {
  if (reason instanceof VoiceSourcePanelActionError) return reason.failure;
  if (abortLike(reason)) {
    return panelFailure("cancelled", "CANCELLED", "操作已取消。", false);
  }
  if (!(reason instanceof NarrationApiError)) {
    return panelFailure("network", "NETWORK_ERROR", "音色服务连接失败，请稍后重试。", true);
  }
  const code = reason.detail.code;
  const retryable = reason.detail.retryable;
  if (["VOICE_RIGHTS_REQUIRED", "VOICE_RIGHTS_UNAVAILABLE"].includes(code)) {
    return panelFailure("rights", code, "音色授权当前不允许新的试听、上传或锁定。", retryable);
  }
  if (["CAPABILITY_DISABLED", "VOICE_SOURCE_UNAVAILABLE", "MODEL_UNAVAILABLE", "PREVIEW_UNAVAILABLE"].includes(code)) {
    return panelFailure("capability", code, "该音色能力尚未通过当前产品门禁。", retryable);
  }
  if (code === "UNSUPPORTED_MEDIA_TYPE") {
    return panelFailure("unsupported_media_type", code, "参考录音只支持 WAV 或 FLAC。", retryable);
  }
  if (code === "PAYLOAD_TOO_LARGE") {
    return panelFailure("payload_too_large", code, "参考录音超过 16 MiB 上限。", retryable);
  }
  if (["REQUEST_VALIDATION_FAILED", "REFERENCE_AUDIO_INVALID", "VALIDATION_FAILED"].includes(code)) {
    return panelFailure("validation", code, "音色请求未通过安全校验。", retryable);
  }
  if (["VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT", "INVALID_STATE", "VOICE_VERSION_NOT_LOCKED"].includes(code)) {
    return panelFailure("conflict", code, "音色状态已变化，请刷新后重试。", retryable);
  }
  if (["STORAGE_UNAVAILABLE", "DISK_SPACE_INSUFFICIENT"].includes(code)) {
    return panelFailure("storage", code, "音色存储当前不可用或空间不足。", retryable);
  }
  if (code === "PREVIEW_FAILED") {
    return panelFailure("preview", code, "试听生成失败，未产生可播放音频。", retryable);
  }
  if (["SCOPE_VIOLATION", "VOICE_PROFILE_NOT_FOUND", "VOICE_VERSION_NOT_FOUND", "RESOURCE_NOT_FOUND"].includes(code)) {
    return panelFailure("permission", code, "找不到该音色资源，或当前身份无权访问。", retryable);
  }
  return panelFailure("network", code, "音色服务暂时无法完成请求。", retryable);
}


function workflowFromPreview(preview: VoicePreviewResource): VoiceSourceWorkflowState {
  if (preview.status === "queued") {
    return { status: "preview_queued", preview, failure: null };
  }
  if (preview.status === "running") {
    return { status: "preview_running", preview, failure: null };
  }
  if (preview.status === "ready") {
    return { status: "preview_ready", preview, failure: null };
  }
  if (preview.status === "cancelled") {
    return {
      status: "cancelled",
      preview,
      failure: panelFailure("cancelled", "CANCELLED", "试听已取消。"),
    };
  }
  if (preview.status === "unavailable") {
    return {
      status: "preview_unavailable",
      preview,
      failure: panelFailure(
        "capability",
        preview.failure_code ?? "PREVIEW_UNAVAILABLE",
        "试听能力当前不可用，未生成音频。",
      ),
    };
  }
  return {
    status: "failed",
    preview,
    failure: panelFailure(
      "preview",
      preview.failure_code ?? "PREVIEW_FAILED",
      "试听生成失败，未产生可播放音频。",
    ),
  };
}

export interface VoicePreviewPollingApi {
  getVoicePreview: typeof getVoicePreview;
}

export interface VoicePreviewPollOptions {
  readonly api?: VoicePreviewPollingApi;
  readonly signal?: AbortSignal;
  readonly delayMs?: number;
  readonly maximumPolls?: number;
  readonly delay?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
  readonly onState?: (state: VoiceSourceWorkflowState) => void;
}

function defaultDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal?.addEventListener("abort", onAbort, { once: true });
    if (signal?.aborted) onAbort();
  });
}

export async function pollVoicePreview(
  initial: VoicePreviewResource,
  options: VoicePreviewPollOptions = {},
): Promise<VoiceSourceWorkflowState> {
  const api = options.api ?? { getVoicePreview };
  const delay = options.delay ?? defaultDelay;
  const requestedDelay = options.delayMs ?? 800;
  const delayMs = Number.isFinite(requestedDelay) ? Math.max(100, requestedDelay) : 800;
  const requestedPolls = options.maximumPolls ?? 60;
  const maximumPolls = Number.isSafeInteger(requestedPolls)
    ? Math.max(1, Math.min(120, requestedPolls))
    : 60;
  let current = workflowFromPreview(initial);
  options.onState?.(current);
  if (!["preview_queued", "preview_running"].includes(current.status)) return current;
  try {
    for (let attempt = 0; attempt < maximumPolls; attempt += 1) {
      if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      await delay(delayMs, options.signal);
      if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const preview = await api.getVoicePreview(initial.preview_id, options.signal);
      if (
        preview.preview_id !== initial.preview_id
        || preview.profile_id !== initial.profile_id
        || preview.version_id !== initial.version_id
      ) {
        throw new VoiceSourcePanelActionError(panelFailure(
          "validation",
          "ACTION_NOT_ALLOWED",
          "试听轮询返回了不匹配的资源，已停止播放。",
        ));
      }
      current = workflowFromPreview(preview);
      options.onState?.(current);
      if (!["preview_queued", "preview_running"].includes(current.status)) return current;
    }
    const timeoutState: VoiceSourceWorkflowState = {
      status: "preview_timeout",
      preview: current.preview,
      failure: panelFailure(
        "preview",
        "PREVIEW_UNAVAILABLE",
        "试听等待超时，未产生可播放音频。",
        true,
      ),
    };
    options.onState?.(timeoutState);
    return timeoutState;
  } catch (reason) {
    const failure = classifyVoiceSourceFailure(reason);
    const state: VoiceSourceWorkflowState = {
      status: failure.kind === "cancelled" ? "cancelled" : "failed",
      preview: current.preview,
      failure,
    };
    options.onState?.(state);
    return state;
  }
}


export const IDLE_VOICE_SOURCE_WORKFLOW: VoiceSourceWorkflowState = Object.freeze({
  status: "idle",
  preview: null,
  failure: null,
});

interface VoiceSourcePanelBaseProps {
  readonly model: VoiceSourcePanelModel;
  readonly selectedSource: VoiceSourceType | null;
  readonly workflow: VoiceSourceWorkflowState;
  readonly uploadRights: VoiceUploadRightsDraft;
  readonly busy?: boolean;
  readonly cancelAllowed?: boolean;
  readonly referenceAudioSelected?: boolean;
  readonly previewTextValid?: boolean;
  readonly qualityConfirmationAllowed?: boolean;
  readonly qualityConfirmed?: boolean;
  readonly onSelectSource?: (source: VoiceSourceType) => void;
  readonly onUploadRightsChange?: (patch: Partial<VoiceUploadRightsDraft>) => void;
  readonly onReferenceAudioChange?: (file: File | null) => void;
  readonly onUpload?: () => void;
  readonly onPreview?: () => void;
  readonly onQualityConfirmationChange?: (confirmed: boolean) => void;
  readonly onLock?: () => void;
  readonly onCancel?: () => void;
}


export type VoiceSourcePanelProps = VoiceSourcePanelBaseProps & (
  | {
    readonly embedded: true;
    readonly ariaLabelledBy: string;
  }
  | {
    readonly embedded?: false;
    readonly ariaLabelledBy?: never;
  }
);

interface VoiceInputEvent {
  readonly target: {
    readonly checked: boolean;
    readonly value: string;
    readonly files: FileList | null;
  };
}

interface ReactElementRuntime {
  createElement: (
    type: unknown,
    props: Record<string, unknown> | null,
    ...children: unknown[]
  ) => unknown;
}

function workflowLabel(workflow: VoiceSourceWorkflowState): string {
  const labels: Readonly<Record<VoiceSourceWorkflowStatus, string>> = {
    idle: "请选择可用音色来源。",
    uploading: "正在校验并上传参考录音……",
    preview_queued: "试听已排队，正在等待本地资源。",
    preview_running: "正在生成临时试听。",
    preview_ready: "试听已就绪；临时音频会按保留策略过期。",
    preview_timeout: "本轮等待已超时；服务端任务可继续查询。",
    preview_unavailable: "试听当前不可用，未生成音频。",
    failed: "音色操作失败，未改变已锁定版本。",
    cancelled: "音色操作已取消。",
  };
  return workflow.failure?.message ?? labels[workflow.status];
}

export function VoiceSourcePanel(props: VoiceSourcePanelProps): unknown {
  const React = window.QwenPaw.host.React as ReactElementRuntime;
  const h = React.createElement;
  const busy = props.busy === true || [
    "uploading",
    "preview_queued",
    "preview_running",
  ].includes(props.workflow.status);
  const statusClass = props.workflow.status === "preview_ready"
    ? "anw-narration-voice-status is-ready"
    : props.workflow.failure !== null
      ? "anw-narration-voice-status is-error"
      : "anw-narration-voice-status";
  const sourceCards = props.model.visibleCards.map((card) => {
    const reasonId = `voice-source-${card.sourceType}-reason`;
    return h(
      "li",
      {
        key: card.sourceType,
        className: [
          "anw-narration-voice-source-card",
          props.selectedSource === card.sourceType ? "is-selected" : "",
          card.enabled ? "" : "is-disabled",
        ].filter(Boolean).join(" "),
        "data-voice-source": card.sourceType,
        "data-voice-source-enabled": String(card.enabled),
      },
      h("h3", null, card.label),
      h("p", null, card.description),
      card.reasonCode === null
        ? null
        : h("p", { id: reasonId }, `当前不可用：${card.reasonCode}`),
      h(
        "button",
        {
          type: "button",
          disabled: !card.enabled || busy,
          "aria-disabled": !card.enabled || busy ? true : undefined,
          "aria-describedby": card.reasonCode === null ? undefined : reasonId,
          onClick: () => props.onSelectSource?.(card.sourceType),
        },
        props.selectedSource === card.sourceType ? "已选择" : "选择来源",
      ),
    );
  });
  const uploaded = props.model.cards.find((card) => card.sourceType === "uploaded");
  const showRights = props.selectedSource === "uploaded" && uploaded?.visible === true;
  const rights = props.uploadRights;
  const canUpload = Boolean(
    showRights
    && uploaded?.enabled
    && props.referenceAudioSelected
    && rights.voiceCloningConfirmed
    && rights.rightsConfirmed
    && rights.noticeVersion.trim().length > 0
    && rights.sourceIdentifier.trim().length > 0
    && !busy,
  );
  const labelledBy = props.embedded
    ? props.ariaLabelledBy
    : "anw-narration-voice-source-title";
  return h(
    "section",
    {
      className: "anw-narration-voice-source-panel",
      "aria-labelledby": labelledBy,
    },
    props.embedded
      ? null
      : h(
        "header",
        { className: "anw-narration-voice-source-heading" },
        h(
          "div",
          null,
          h("h2", { id: "anw-narration-voice-source-title" }, "音色来源"),
          h("p", null, "官方音色请在上方音色库直接使用；这里仅管理私人音色来源。"),
        ),
      ),
    props.model.permissionNotice === null
      ? null
      : h("p", { role: "note" }, props.model.permissionNotice),
    h("ul", { className: "anw-narration-voice-source-grid" }, ...sourceCards),
    showRights
      ? h(
        "fieldset",
        { className: "anw-narration-voice-rights", disabled: !uploaded?.enabled || busy },
        h("legend", null, "参考录音与授权确认"),
        h("label", null,
          "授权声明版本",
          h("input", {
            type: "text",
            value: rights.noticeVersion,
            readOnly: true,
            "aria-readonly": "true",
          }),
        ),
        h("label", null,
          "来源说明",
          h("input", {
            type: "text",
            value: rights.sourceIdentifier,
            maxLength: 240,
            onChange: (event: VoiceInputEvent) => props.onUploadRightsChange?.({
              sourceIdentifier: event.target.value,
            }),
          }),
        ),
        h("label", null,
          "主体同意记录（可选）",
          h("input", {
            type: "text",
            value: rights.subjectConsentReference ?? "",
            maxLength: 240,
            onChange: (event: VoiceInputEvent) => props.onUploadRightsChange?.({
              subjectConsentReference: event.target.value.trim() || null,
            }),
          }),
        ),
        h("label", { className: "anw-narration-voice-rights-check" },
          h("input", {
            type: "checkbox",
            checked: rights.commercialUse,
            onChange: (event: VoiceInputEvent) => props.onUploadRightsChange?.({
              commercialUse: event.target.checked,
            }),
          }),
          "授权允许本作品用于商业用途。",
        ),
        h("label", { className: "anw-narration-voice-rights-check" },
          h("input", {
            type: "checkbox",
            checked: rights.redistribution,
            onChange: (event: VoiceInputEvent) => props.onUploadRightsChange?.({
              redistribution: event.target.checked,
            }),
          }),
          "授权允许再分发该参考声音资产。",
        ),
        h("label", { className: "anw-narration-voice-rights-check" },
          h("input", {
            type: "checkbox",
            checked: rights.voiceCloningConfirmed,
            onChange: (event: VoiceInputEvent) => props.onUploadRightsChange?.({
              voiceCloningConfirmed: event.target.checked,
            }),
          }),
          "我确认有权将该声音用于本作品的声音克隆。",
        ),
        h("label", { className: "anw-narration-voice-rights-check" },
          h("input", {
            type: "checkbox",
            checked: rights.rightsConfirmed,
            onChange: (event: VoiceInputEvent) => props.onUploadRightsChange?.({
              rightsConfirmed: event.target.checked,
            }),
          }),
          "我已阅读并确认当前版本的音色授权声明。",
        ),
        h("label", null,
          "WAV / FLAC（最大 16 MiB）",
          h("input", {
            type: "file",
            accept: ".wav,.flac,audio/wav,audio/flac",
            onChange: (event: VoiceInputEvent) => props.onReferenceAudioChange?.(
              event.target.files?.item(0) ?? null,
            ),
          }),
        ),
        h("button", {
          type: "button",
          disabled: !canUpload,
          onClick: props.onUpload,
        }, "上传并创建候选版本"),
      )
      : null,
    h(
      "div",
      { className: "anw-narration-voice-actions" },
      h("button", {
        type: "button",
        disabled: !props.model.actions.canPreview || props.previewTextValid === false || busy,
        onClick: props.onPreview,
      }, "生成试听"),
      props.workflow.status === "preview_ready"
        ? h("label", { className: "anw-narration-voice-quality-confirmation" },
          h("input", {
            type: "checkbox",
            checked: props.qualityConfirmed === true,
            disabled: props.qualityConfirmationAllowed !== true || busy,
            onChange: (event: VoiceInputEvent) => props.onQualityConfirmationChange?.(
              event.target.checked,
            ),
          }),
          props.qualityConfirmationAllowed === true
            ? "我已播放并确认当前试听的音质、清晰度和人物适配度。"
            : "请先播放当前试听，再确认音质、清晰度和人物适配度。",
        )
        : null,
      h("button", {
        type: "button",
        disabled: !props.model.actions.canLock || props.qualityConfirmed !== true || busy,
        onClick: props.onLock,
      }, "确认并锁定版本"),
      h("button", {
        type: "button",
        disabled: !busy || props.cancelAllowed === false,
        onClick: props.onCancel,
      }, "取消"),
    ),
    h(
      "div",
      {
        className: statusClass,
        role: props.workflow.failure === null ? "status" : "alert",
        "aria-live": "polite",
      },
      workflowLabel(props.workflow),
    ),
  );
}
