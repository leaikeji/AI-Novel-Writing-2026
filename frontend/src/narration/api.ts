import { ApiError, apiErrorMessage, apiRequest } from "../api";
import { APP_ID } from "../contracts";
import {
  ChapterNarrationContractError,
  normalizeChapterUuid,
  parseCreateNarrationWorkflowRequest,
  parseDocumentNarrationContext,
  parseFailedNarrationSegmentsProjection,
  parseNarrationEditionResource,
  parseNarrationEditionVoiceIdentitiesResource,
  parseNarrationProductionApiErrorDetail,
  parseNarrationWorkflowResource,
  parseRetryFailedNarrationSegmentsRequest,
  parseRetryFailedNarrationSegmentsResponse,
  parseSwitchNarrationEditionRequest,
  parseSwitchNarrationEditionResponse,
} from "./chapter-contracts";
import type {
  CreateNarrationWorkflowRequest,
  DocumentNarrationContext,
  FailedNarrationSegmentsProjection,
  NarrationEditionResource,
  NarrationEditionVoiceIdentitiesResource,
  NarrationProductionApiErrorDetail,
  NarrationWorkflowResource,
  RetryFailedNarrationSegmentsRequest,
  RetryFailedNarrationSegmentsResponse,
  SwitchNarrationEditionRequest,
  SwitchNarrationEditionResponse,
} from "./chapter-contracts";
import {
  NarrationContractError,
  REFERENCE_UPLOAD_MAX_BYTES,
  REFERENCE_UPLOAD_MIME_TYPES,
  parseCharacterVoiceBindingListResponse,
  parseCharacterVoiceBindingResource,
  parseCharacterCastPlanListResource,
  parseCharacterCastPlanResource,
  parseCharacterVoiceMatchResource,
  parseCharacterVoiceGeneratorCommandListResource,
  parseCharacterVoiceGeneratorCommandResource,
  parseNanoVoiceExperimentListResource,
  parseNanoVoiceExperimentResource,
  parseNarrationApiErrorDetail,
  parseNarrationCacheCleanupPreview,
  parseNarrationCacheCleanupResult,
  parseNarrationCacheStatus,
  parseNarrationCloudConsent,
  parseNarrationOverviewResponse,
  parseNarrationScopeOverrideListResponse,
  parseNarrationScopeOverrideResource,
  parseNarrationSettingsResource,
  parseOfficialPresetCatalogResponse,
  parseOfficialVoiceSelectionResponse,
  parsePrivateVoiceDeletionRequestResource,
  parsePrivateVoiceLifecycleResource,
  parseVoicePreparationListResource,
  parseVoicePreparationResource,
  parseGenericVoicePackLoadResource,
  parsePronunciationProfileResource,
  parseVoicePreviewResource,
  parseVoiceProfileListResponse,
  parseVoiceProfileResource,
  parseVoiceProfileVersionResource,
  parseVoiceCastingRulesResource,
} from "./contracts";
import type {
  CharacterVoiceBindingListResponse,
  CharacterVoiceBindingResource,
  CharacterCastPlanListResource,
  CharacterCastPlanResource,
  CharacterVoiceMatchRequest,
  CharacterVoiceMatchResource,
  ApplyCharacterVoiceGeneratorCommandRequest,
  CharacterVoiceGeneratorCommandListResource,
  CharacterVoiceGeneratorCommandResource,
  CreateCharacterVoiceGeneratorCommandRequest,
  CreateCharacterCastPlanRequest,
  RetryCharacterVoiceGeneratorCommandRequest,
  ApplyNanoVoiceExperimentRequest,
  CreateNanoVoiceExperimentRequest,
  NanoVoiceExperimentListResource,
  NanoVoiceExperimentResource,
  CreateNarrationCloudConsentRequest,
  CreatePresetVoiceVersionRequest,
  CreateVoicePreviewRequest,
  CreateVoiceProfileRequest,
  ExecuteNarrationCacheCleanupRequest,
  LockVoiceProfileRequest,
  NarrationApiErrorDetail,
  NarrationCacheCleanupPreview,
  NarrationCacheCleanupResult,
  NarrationCacheStatus,
  NarrationCloudConsent,
  NarrationOverviewResponse,
  NarrationScopeKind,
  NarrationScopeOverrideListResponse,
  NarrationScopeOverrideResource,
  NarrationSettingsResource,
  OfficialPresetCatalogResponse,
  OfficialVoicePreviewRequest,
  OfficialVoiceSelectionRequest,
  OfficialVoiceSelectionResponse,
  ConfirmPrivateVoiceDeletionRequest,
  CreatePrivateVoiceDeletionRequest,
  PrivateVoiceDeletionRequestResource,
  PrivateVoiceLifecycleResource,
  PreviewNarrationCacheCleanupRequest,
  PronunciationProfileResource,
  PutCharacterVoiceBindingRequest,
  PutNarrationScopeOverrideRequest,
  PutPronunciationProfileRequest,
  RevokeNarrationCloudConsentRequest,
  UpdateNarrationSettingsRequest,
  UpdateNarrationPlaybackPreferencesRequest,
  UpdateVoiceProfileRequest,
  UploadedVoiceVersionMetadata,
  VoicePreviewResource,
  VoiceProfileListResponse,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceCastingRulesResource,
  CreateVoicePreparationRequest,
  VoicePreparationSnapshot,
  GenericVoicePackLoadResult,
  RejectGenericVoiceSlotRequest,
} from "./contracts";

type ResponseParser<T> = (value: unknown) => T;

const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

export class NarrationApiError extends Error {
  readonly status: number;
  readonly detail: NarrationApiErrorDetail;

  constructor(status: number, detail: NarrationApiErrorDetail) {
    super(detail.message);
    this.status = status;
    this.detail = detail;
  }
}


export class NarrationProductionApiError extends Error {
  readonly status: number;
  readonly detail: NarrationProductionApiErrorDetail;

  constructor(status: number, detail: NarrationProductionApiErrorDetail) {
    super(detail.message);
    this.status = status;
    this.detail = detail;
  }
}

function pathSegment(value: string): string {
  return encodeURIComponent(value);
}

function jsonInit(method: "POST" | "PUT" | "PATCH" | "DELETE", payload: object, signal?: AbortSignal): RequestInit {
  return {
    method,
    body: JSON.stringify(payload),
    signal,
  };
}

function idempotencyHeaders(idempotencyKey: string): HeadersInit {
  if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
    throw new NarrationContractError(
      "idempotency_key",
      "must be 8-128 safe characters",
    );
  }
  return { "Idempotency-Key": idempotencyKey };
}

function normalizeNarrationError(reason: unknown): never {
  if (!(reason instanceof ApiError)) throw reason;
  try {
    throw new NarrationApiError(
      reason.status,
      parseNarrationApiErrorDetail(reason.detail),
    );
  } catch (error) {
    if (error instanceof NarrationApiError) throw error;
    throw reason;
  }
}


function normalizeProductionError(reason: unknown): never {
  if (!(reason instanceof ApiError)) throw reason;
  try {
    throw new NarrationProductionApiError(
      reason.status,
      parseNarrationProductionApiErrorDetail(reason.detail),
    );
  } catch (error) {
    if (error instanceof NarrationProductionApiError) throw error;
    throw reason;
  }
}

async function parsedRequest<T>(
  path: string,
  parser: ResponseParser<T>,
  init?: RequestInit,
): Promise<T> {
  try {
    const payload = await apiRequest<unknown>(path, init);
    return parser(payload);
  } catch (reason) {
    normalizeNarrationError(reason);
  }
}


async function parsedProductionRequest<T>(
  path: string,
  parser: ResponseParser<T>,
  init?: RequestInit,
): Promise<T> {
  try {
    const payload = await apiRequest<unknown>(path, init);
    return parser(payload);
  } catch (reason) {
    normalizeProductionError(reason);
  }
}

async function multipartRequest<T>(
  path: string,
  form: FormData,
  parser: ResponseParser<T>,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await window.QwenPaw.host.fetch(`/${APP_ID}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      ...idempotencyHeaders(idempotencyKey),
    },
    body: form,
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const responseRecord = payload !== null && typeof payload === "object"
      ? payload as Record<string, unknown>
      : null;
    const detail = responseRecord?.detail ?? payload;
    const provisional = new ApiError(response.status, `HTTP ${response.status}`, detail);
    const error = new ApiError(
      response.status,
      apiErrorMessage(provisional, `HTTP ${response.status}`),
      detail,
    );
    normalizeNarrationError(error);
  }
  return parser(payload);
}

export function getNarrationOverview(
  novelId: string,
  signal?: AbortSignal,
): Promise<NarrationOverviewResponse> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-overview`,
    parseNarrationOverviewResponse,
    { signal },
  );
}

export function getNarrationSettings(
  novelId: string,
  signal?: AbortSignal,
): Promise<NarrationSettingsResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-settings`,
    parseNarrationSettingsResource,
    { signal },
  );
}

export function putNarrationSettings(
  novelId: string,
  payload: UpdateNarrationSettingsRequest,
  signal?: AbortSignal,
): Promise<NarrationSettingsResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-settings`,
    parseNarrationSettingsResource,
    jsonInit("PUT", payload, signal),
  );
}

export function putNarrationPlaybackPreferences(
  novelId: string,
  payload: UpdateNarrationPlaybackPreferencesRequest,
  signal?: AbortSignal,
): Promise<NarrationSettingsResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-settings/playback-preferences`,
    parseNarrationSettingsResource,
    jsonInit("PATCH", payload, signal),
  );
}

export function listNarrationScopeOverrides(
  novelId: string,
  signal?: AbortSignal,
): Promise<NarrationScopeOverrideListResponse> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-scope-overrides`,
    parseNarrationScopeOverrideListResponse,
    { signal },
  );
}

export function putNarrationScopeOverride(
  novelId: string,
  scopeKind: NarrationScopeKind,
  scopeId: string,
  payload: PutNarrationScopeOverrideRequest,
  signal?: AbortSignal,
): Promise<NarrationScopeOverrideResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-scope-overrides/${scopeKind}/${pathSegment(scopeId)}`,
    parseNarrationScopeOverrideResource,
    jsonInit("PUT", payload, signal),
  );
}

export function createNarrationCloudConsent(
  novelId: string,
  payload: CreateNarrationCloudConsentRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<NarrationCloudConsent> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-cloud-consents`,
    parseNarrationCloudConsent,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export function revokeNarrationCloudConsent(
  novelId: string,
  payload: RevokeNarrationCloudConsentRequest,
  signal?: AbortSignal,
): Promise<NarrationCloudConsent> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-cloud-consents/current`,
    parseNarrationCloudConsent,
    jsonInit("DELETE", payload, signal),
  );
}

export function listVoiceProfiles(
  options: { readonly novelId?: string; readonly includeLibrary?: boolean; readonly signal?: AbortSignal } = {},
): Promise<VoiceProfileListResponse> {
  const query = new URLSearchParams();
  if (options.novelId) query.set("novel_id", options.novelId);
  query.set("include_library", String(options.includeLibrary ?? true));
  return parsedRequest(
    `/voice-profiles?${query.toString()}`,
    parseVoiceProfileListResponse,
    { signal: options.signal },
  );
}

export function createVoiceProfile(
  payload: CreateVoiceProfileRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<VoiceProfileResource> {
  return parsedRequest(
    "/voice-profiles",
    parseVoiceProfileResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export function getVoiceProfile(
  profileId: string,
  signal?: AbortSignal,
): Promise<VoiceProfileResource> {
  return parsedRequest(
    `/voice-profiles/${pathSegment(profileId)}`,
    parseVoiceProfileResource,
    { signal },
  );
}

export function updateVoiceProfile(
  profileId: string,
  payload: UpdateVoiceProfileRequest,
  signal?: AbortSignal,
): Promise<VoiceProfileResource> {
  return parsedRequest(
    `/voice-profiles/${pathSegment(profileId)}`,
    parseVoiceProfileResource,
    jsonInit("PUT", payload, signal),
  );
}

export function archiveVoiceProfile(
  profileId: string,
  expectedVersion: number,
  signal?: AbortSignal,
): Promise<VoiceProfileResource> {
  const query = new URLSearchParams({ expected_version: String(expectedVersion) });
  return parsedRequest(
    `/voice-profiles/${pathSegment(profileId)}?${query.toString()}`,
    parseVoiceProfileResource,
    { method: "DELETE", signal },
  );
}

export function createPresetVoiceVersion(
  profileId: string,
  payload: CreatePresetVoiceVersionRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<VoiceProfileVersionResource> {
  return parsedRequest(
    `/voice-profiles/${pathSegment(profileId)}/versions/preset`,
    parseVoiceProfileVersionResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export function listOfficialVoicePresets(
  signal?: AbortSignal,
): Promise<OfficialPresetCatalogResponse> {
  return parsedRequest(
    "/voice-presets",
    parseOfficialPresetCatalogResponse,
    { signal },
  );
}

export function selectOfficialVoice(
  novelId: string,
  payload: OfficialVoiceSelectionRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<OfficialVoiceSelectionResponse> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/official-voice-selections`,
    parseOfficialVoiceSelectionResponse,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export function createOfficialVoicePreview(
  novelId: string,
  payload: OfficialVoicePreviewRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<VoicePreviewResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/official-voice-previews`,
    parseVoicePreviewResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export async function listNanoVoiceExperiments(
  novelId: string,
  signal?: AbortSignal,
): Promise<NanoVoiceExperimentListResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/nano-voice-experiments`,
    parseNanoVoiceExperimentListResource,
    { signal },
  );
  if (result.novel_id !== novelId) {
    throw new NarrationContractError("nano_voice_experiments.novel_id", "response scope mismatch");
  }
  return result;
}

export async function createNanoVoiceExperiment(
  novelId: string,
  payload: CreateNanoVoiceExperimentRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<NanoVoiceExperimentResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/nano-voice-experiments`,
    parseNanoVoiceExperimentResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  if (result.novel_id !== novelId) {
    throw new NarrationContractError("nano_voice_experiment.novel_id", "response scope mismatch");
  }
  return result;
}

export async function getNanoVoiceExperiment(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<NanoVoiceExperimentResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/nano-voice-experiments/${pathSegment(commandId)}`,
    parseNanoVoiceExperimentResource,
    { signal },
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("nano_voice_experiment", "response scope mismatch");
  }
  return result;
}

export async function applyNanoVoiceExperiment(
  novelId: string,
  commandId: string,
  payload: ApplyNanoVoiceExperimentRequest,
  signal?: AbortSignal,
): Promise<NanoVoiceExperimentResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/nano-voice-experiments/${pathSegment(commandId)}/binding`,
    parseNanoVoiceExperimentResource,
    jsonInit("PUT", payload, signal),
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("nano_voice_experiment", "response scope mismatch");
  }
  return result;
}

export async function matchCharacterOfficialVoice(
  novelId: string,
  characterId: string,
  payload: CharacterVoiceMatchRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceMatchResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/characters/${pathSegment(characterId)}/official-voice-match`,
    parseCharacterVoiceMatchResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  if (
    result.character_id !== characterId
    || result.current_character_binding.character_id !== characterId
    || result.current_character_binding.novel_id !== novelId
  ) {
    throw new NarrationContractError("character_voice_match.character_id", "response scope mismatch");
  }
  return result;
}

export async function listCharacterCastPlans(
  novelId: string,
  signal?: AbortSignal,
): Promise<CharacterCastPlanListResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/character-cast-plans`,
    parseCharacterCastPlanListResource,
    { signal },
  );
  if (result.novel_id !== novelId) {
    throw new NarrationContractError("character_cast_plans.novel_id", "response scope mismatch");
  }
  return result;
}

export async function createCharacterCastPlan(
  novelId: string,
  payload: CreateCharacterCastPlanRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<CharacterCastPlanResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/character-cast-plans`,
    parseCharacterCastPlanResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  if (result.novel_id !== novelId || result.timeline_id !== payload.timeline_id) {
    throw new NarrationContractError("character_cast_plan", "response scope mismatch");
  }
  return result;
}

export async function getCharacterCastPlan(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<CharacterCastPlanResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/character-cast-plans/${pathSegment(commandId)}`,
    parseCharacterCastPlanResource,
    { signal },
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("character_cast_plan", "response scope mismatch");
  }
  return result;
}

export async function advanceCharacterCastPlan(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<CharacterCastPlanResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/character-cast-plans/${pathSegment(commandId)}/advance`,
    parseCharacterCastPlanResource,
    { method: "POST", signal },
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("character_cast_plan", "response scope mismatch");
  }
  return result;
}

export async function retryCharacterCastPlan(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<CharacterCastPlanResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/character-cast-plans/${pathSegment(commandId)}/retry`,
    parseCharacterCastPlanResource,
    { method: "POST", signal },
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("character_cast_plan", "response scope mismatch");
  }
  return result;
}

export async function listCharacterVoiceGeneratorCommands(
  novelId: string,
  characterId: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceGeneratorCommandListResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/characters/${pathSegment(characterId)}/voice-generator-commands`,
    parseCharacterVoiceGeneratorCommandListResource,
    { signal },
  );
  if (result.novel_id !== novelId || result.character_id !== characterId) {
    throw new NarrationContractError("character_voice_generations", "response scope mismatch");
  }
  return result;
}

export async function createCharacterVoiceGeneratorCommand(
  novelId: string,
  characterId: string,
  payload: CreateCharacterVoiceGeneratorCommandRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceGeneratorCommandResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/characters/${pathSegment(characterId)}/voice-generator-commands`,
    parseCharacterVoiceGeneratorCommandResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  if (result.novel_id !== novelId || result.character_id !== characterId) {
    throw new NarrationContractError("character_voice_generation", "response scope mismatch");
  }
  return result;
}

export async function getCharacterVoiceGeneratorCommand(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceGeneratorCommandResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-generator-commands/${pathSegment(commandId)}`,
    parseCharacterVoiceGeneratorCommandResource,
    { signal },
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("character_voice_generation", "response scope mismatch");
  }
  return result;
}

export async function cancelCharacterVoiceGeneratorCommand(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceGeneratorCommandResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-generator-commands/${pathSegment(commandId)}/cancel`,
    parseCharacterVoiceGeneratorCommandResource,
    { method: "POST", signal },
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("character_voice_generation", "response scope mismatch");
  }
  return result;
}

export async function retryCharacterVoiceGeneratorCommand(
  novelId: string,
  commandId: string,
  payload: RetryCharacterVoiceGeneratorCommandRequest,
  signal?: AbortSignal,
): Promise<CharacterVoiceGeneratorCommandResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-generator-commands/${pathSegment(commandId)}/retry`,
    parseCharacterVoiceGeneratorCommandResource,
    jsonInit("POST", payload, signal),
  );
  // Retry creates a new durable command with a fresh command ID. The source
  // command remains the path authority; only the novel scope is stable across
  // the response.
  if (result.novel_id !== novelId) {
    throw new NarrationContractError("character_voice_generation", "response scope mismatch");
  }
  return result;
}

export async function applyCharacterVoiceGeneratorCommand(
  novelId: string,
  commandId: string,
  payload: ApplyCharacterVoiceGeneratorCommandRequest,
  signal?: AbortSignal,
): Promise<CharacterVoiceGeneratorCommandResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-generator-commands/${pathSegment(commandId)}/binding`,
    parseCharacterVoiceGeneratorCommandResource,
    jsonInit("PUT", payload, signal),
  );
  if (result.novel_id !== novelId || result.command_id !== commandId) {
    throw new NarrationContractError("character_voice_generation", "response scope mismatch");
  }
  return result;
}

export async function listVoicePreparationCommands(
  novelId: string,
  signal?: AbortSignal,
): Promise<readonly VoicePreparationSnapshot[]> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-preparation-commands`,
    parseVoicePreparationListResource,
    { signal },
  );
}

export async function createVoicePreparationCommand(
  novelId: string,
  payload: CreateVoicePreparationRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<VoicePreparationSnapshot> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-preparation-commands`,
    parseVoicePreparationResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export async function getVoicePreparationCommand(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<VoicePreparationSnapshot> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-preparation-commands/${pathSegment(commandId)}`,
    parseVoicePreparationResource,
    { signal },
  );
}

export async function resumeVoicePreparationCommand(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<VoicePreparationSnapshot> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-preparation-commands/${pathSegment(commandId)}/resume`,
    parseVoicePreparationResource,
    { method: "POST", signal },
  );
}

export async function retryVoicePreparationCommand(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<VoicePreparationSnapshot> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-preparation-commands/${pathSegment(commandId)}/retry`,
    parseVoicePreparationResource,
    { method: "POST", signal },
  );
}

export async function cancelVoicePreparationCommand(
  novelId: string,
  commandId: string,
  signal?: AbortSignal,
): Promise<VoicePreparationSnapshot> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-preparation-commands/${pathSegment(commandId)}/cancel`,
    parseVoicePreparationResource,
    { method: "POST", signal },
  );
}

export async function getGenericVoicePack(
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    "/voice-library/generic-pack",
    parseGenericVoicePackLoadResource,
    { signal },
  );
}

export async function buildGenericVoicePack(
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    "/voice-library/generic-pack/build-commands",
    parseGenericVoicePackLoadResource,
    { method: "POST", headers: idempotencyHeaders(idempotencyKey), signal },
  );
}

export async function getGenericVoicePackBuildCommand(
  commandId: string,
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    `/voice-library/generic-pack/build-commands/${pathSegment(commandId)}`,
    parseGenericVoicePackLoadResource,
    { signal },
  );
}

export async function retryGenericVoicePackBuild(
  commandId: string,
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    `/voice-library/generic-pack/build-commands/${pathSegment(commandId)}/retry`,
    parseGenericVoicePackLoadResource,
    { method: "POST", signal },
  );
}

export async function cancelGenericVoicePackBuild(
  commandId: string,
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    `/voice-library/generic-pack/build-commands/${pathSegment(commandId)}/cancel`,
    parseGenericVoicePackLoadResource,
    { method: "POST", signal },
  );
}

export async function regenerateGenericVoicePackSlot(
  slotKey: string,
  payload: RejectGenericVoiceSlotRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    `/voice-library/generic-pack/slots/${pathSegment(slotKey)}/regenerate`,
    parseGenericVoicePackLoadResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export async function rejectGenericVoicePackSlot(
  slotKey: string,
  payload: RejectGenericVoiceSlotRequest,
  signal?: AbortSignal,
): Promise<GenericVoicePackLoadResult> {
  return parsedRequest(
    `/voice-library/generic-pack/slots/${pathSegment(slotKey)}/reject`,
    parseGenericVoicePackLoadResource,
    jsonInit("POST", payload, signal),
  );
}

export async function getPrivateVoiceLifecycle(
  novelId: string,
  signal?: AbortSignal,
): Promise<PrivateVoiceLifecycleResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/private-voice-lifecycle`,
    parsePrivateVoiceLifecycleResource,
    { signal },
  );
  if (result.novel_id !== novelId) {
    throw new NarrationContractError("private_voice_lifecycle.novel_id", "response scope mismatch");
  }
  return result;
}

export async function createPrivateVoiceDeletionRequest(
  novelId: string,
  profileId: string,
  payload: CreatePrivateVoiceDeletionRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<PrivateVoiceDeletionRequestResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-profiles/${pathSegment(profileId)}/deletion-requests`,
    parsePrivateVoiceDeletionRequestResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  if (result.novel_id !== novelId || result.profile_id !== profileId) {
    throw new NarrationContractError("private_voice_deletion", "response scope mismatch");
  }
  return result;
}

export async function getPrivateVoiceDeletionRequest(
  novelId: string,
  requestId: string,
  signal?: AbortSignal,
): Promise<PrivateVoiceDeletionRequestResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-deletion-requests/${pathSegment(requestId)}`,
    parsePrivateVoiceDeletionRequestResource,
    { signal },
  );
  if (result.novel_id !== novelId || result.request_id !== requestId) {
    throw new NarrationContractError("private_voice_deletion", "response scope mismatch");
  }
  return result;
}

export async function confirmPrivateVoiceDeletionRequest(
  novelId: string,
  requestId: string,
  payload: ConfirmPrivateVoiceDeletionRequest,
  signal?: AbortSignal,
): Promise<PrivateVoiceDeletionRequestResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-deletion-requests/${pathSegment(requestId)}/confirm`,
    parsePrivateVoiceDeletionRequestResource,
    jsonInit("POST", payload, signal),
  );
  if (result.novel_id !== novelId || result.request_id !== requestId) {
    throw new NarrationContractError("private_voice_deletion", "response scope mismatch");
  }
  return result;
}

export async function cancelPrivateVoiceDeletionRequest(
  novelId: string,
  requestId: string,
  signal?: AbortSignal,
): Promise<PrivateVoiceDeletionRequestResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-deletion-requests/${pathSegment(requestId)}/cancel`,
    parsePrivateVoiceDeletionRequestResource,
    { method: "POST", signal },
  );
  if (result.novel_id !== novelId || result.request_id !== requestId) {
    throw new NarrationContractError("private_voice_deletion", "response scope mismatch");
  }
  return result;
}

export async function retryPrivateVoiceDeletionRequest(
  novelId: string,
  requestId: string,
  signal?: AbortSignal,
): Promise<PrivateVoiceDeletionRequestResource> {
  const result = await parsedRequest(
    `/novels/${pathSegment(novelId)}/voice-deletion-requests/${pathSegment(requestId)}/retry`,
    parsePrivateVoiceDeletionRequestResource,
    { method: "POST", signal },
  );
  if (result.novel_id !== novelId || result.request_id !== requestId) {
    throw new NarrationContractError("private_voice_deletion", "response scope mismatch");
  }
  return result;
}

export function buildUploadedVoiceVersionFormData(
  metadata: UploadedVoiceVersionMetadata,
  referenceAudio: Blob,
): FormData {
  if (!REFERENCE_UPLOAD_MIME_TYPES.includes(referenceAudio.type as typeof REFERENCE_UPLOAD_MIME_TYPES[number])) {
    throw new NarrationContractError(
      "reference_audio.type",
      `must be one of ${REFERENCE_UPLOAD_MIME_TYPES.join(",")}`,
    );
  }
  if (referenceAudio.size <= 0 || referenceAudio.size > REFERENCE_UPLOAD_MAX_BYTES) {
    throw new NarrationContractError(
      "reference_audio.size",
      `must be 1-${REFERENCE_UPLOAD_MAX_BYTES} bytes`,
    );
  }
  if (metadata.original_filename.includes("/") || metadata.original_filename.includes("\\")) {
    throw new NarrationContractError("metadata.original_filename", "must not contain a path");
  }
  const form = new FormData();
  form.append("metadata", JSON.stringify(metadata));
  form.append("reference_audio", referenceAudio, metadata.original_filename);
  return form;
}

export function createUploadedVoiceVersion(
  profileId: string,
  metadata: UploadedVoiceVersionMetadata,
  referenceAudio: Blob,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<VoiceProfileVersionResource> {
  return multipartRequest(
    `/voice-profiles/${pathSegment(profileId)}/versions/uploaded`,
    buildUploadedVoiceVersionFormData(metadata, referenceAudio),
    parseVoiceProfileVersionResource,
    idempotencyKey,
    signal,
  );
}

export function createVoicePreview(
  profileId: string,
  payload: CreateVoicePreviewRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<VoicePreviewResource> {
  return parsedRequest(
    `/voice-profiles/${pathSegment(profileId)}/previews`,
    parseVoicePreviewResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
}

export function getVoicePreview(
  previewId: string,
  signal?: AbortSignal,
): Promise<VoicePreviewResource> {
  return parsedRequest(
    `/voice-previews/${pathSegment(previewId)}`,
    parseVoicePreviewResource,
    { signal },
  );
}

export function lockVoiceProfile(
  profileId: string,
  payload: LockVoiceProfileRequest,
  signal?: AbortSignal,
): Promise<VoiceProfileResource> {
  return parsedRequest(
    `/voice-profiles/${pathSegment(profileId)}/lock`,
    parseVoiceProfileResource,
    jsonInit("POST", payload, signal),
  );
}

export function getCharacterVoiceBinding(
  novelId: string,
  characterId: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceBindingResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/characters/${pathSegment(characterId)}/voice-binding`,
    parseCharacterVoiceBindingResource,
    { signal },
  );
}

export function listCharacterVoiceBindings(
  novelId: string,
  signal?: AbortSignal,
): Promise<CharacterVoiceBindingListResponse> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/character-voice-bindings`,
    parseCharacterVoiceBindingListResponse,
    { signal },
  );
}

export function putCharacterVoiceBinding(
  novelId: string,
  characterId: string,
  payload: PutCharacterVoiceBindingRequest,
  signal?: AbortSignal,
): Promise<CharacterVoiceBindingResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/characters/${pathSegment(characterId)}/voice-binding`,
    parseCharacterVoiceBindingResource,
    jsonInit("PUT", payload, signal),
  );
}

export function getVoiceCastingRules(
  novelId: string,
  signal?: AbortSignal,
): Promise<VoiceCastingRulesResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/casting-rules`,
    parseVoiceCastingRulesResource,
    { signal },
  );
}

export function getPronunciationProfile(
  novelId: string,
  signal?: AbortSignal,
): Promise<PronunciationProfileResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/pronunciation-profile`,
    parsePronunciationProfileResource,
    { signal },
  );
}

export function putPronunciationProfile(
  novelId: string,
  payload: PutPronunciationProfileRequest,
  signal?: AbortSignal,
): Promise<PronunciationProfileResource> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/pronunciation-profile`,
    parsePronunciationProfileResource,
    jsonInit("PUT", payload, signal),
  );
}

export function getNarrationCacheStatus(
  novelId: string,
  signal?: AbortSignal,
): Promise<NarrationCacheStatus> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-cache`,
    parseNarrationCacheStatus,
    { signal },
  );
}

export function previewNarrationCacheCleanup(
  novelId: string,
  payload: PreviewNarrationCacheCleanupRequest,
  signal?: AbortSignal,
): Promise<NarrationCacheCleanupPreview> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-cache/cleanup-preview`,
    parseNarrationCacheCleanupPreview,
    jsonInit("POST", payload, signal),
  );
}

export function executeNarrationCacheCleanup(
  novelId: string,
  payload: ExecuteNarrationCacheCleanupRequest,
  signal?: AbortSignal,
): Promise<NarrationCacheCleanupResult> {
  return parsedRequest(
    `/novels/${pathSegment(novelId)}/narration-cache/cleanup`,
    parseNarrationCacheCleanupResult,
    jsonInit("POST", payload, signal),
  );
}


function chapterPathId(value: string, field: string): string {
  return pathSegment(normalizeChapterUuid(value, field));
}


function requireChapterIdentity(
  actual: string | null,
  expected: string | null,
  field: string,
): void {
  if (actual !== expected) {
    throw new ChapterNarrationContractError(field, "response scope mismatch");
  }
}


export async function getDocumentNarrationContext(
  documentId: string,
  activeEditionId?: string,
  signal?: AbortSignal,
): Promise<DocumentNarrationContext> {
  const normalizedDocumentId = normalizeChapterUuid(documentId, "document_id");
  const normalizedActiveId = activeEditionId === undefined
    ? undefined
    : normalizeChapterUuid(activeEditionId, "active_edition_id");
  const query = normalizedActiveId === undefined
    ? ""
    : `?${new URLSearchParams({ active_edition_id: normalizedActiveId }).toString()}`;
  const resource = await parsedProductionRequest(
    `/documents/${chapterPathId(normalizedDocumentId, "document_id")}/narration-playback-context${query}`,
    parseDocumentNarrationContext,
    { signal },
  );
  requireChapterIdentity(resource.document_id, normalizedDocumentId, "document_id");
  requireChapterIdentity(
    resource.active_edition_id,
    normalizedActiveId ?? resource.current_edition_id,
    "active_edition_id",
  );
  return resource;
}


export async function getNarrationEdition(
  editionId: string,
  signal?: AbortSignal,
): Promise<NarrationEditionResource> {
  const normalizedEditionId = normalizeChapterUuid(editionId, "edition_id");
  const resource = await parsedProductionRequest(
    `/narration-editions/${chapterPathId(normalizedEditionId, "edition_id")}`,
    parseNarrationEditionResource,
    { signal },
  );
  requireChapterIdentity(resource.edition_id, normalizedEditionId, "edition_id");
  return resource;
}


export async function getNarrationEditionVoiceIdentities(
  editionId: string,
  signal?: AbortSignal,
): Promise<NarrationEditionVoiceIdentitiesResource> {
  const normalizedEditionId = normalizeChapterUuid(editionId, "edition_id");
  const resource = await parsedProductionRequest(
    `/narration-editions/${chapterPathId(normalizedEditionId, "edition_id")}/voice-identities`,
    parseNarrationEditionVoiceIdentitiesResource,
    { signal },
  );
  requireChapterIdentity(resource.edition_id, normalizedEditionId, "edition_id");
  return resource;
}


export async function getFailedNarrationSegments(
  editionId: string,
  signal?: AbortSignal,
): Promise<FailedNarrationSegmentsProjection> {
  const normalizedEditionId = normalizeChapterUuid(editionId, "edition_id");
  const resource = await parsedProductionRequest(
    `/narration-editions/${chapterPathId(normalizedEditionId, "edition_id")}/failed-segments`,
    parseFailedNarrationSegmentsProjection,
    { signal },
  );
  requireChapterIdentity(resource.edition_id, normalizedEditionId, "edition_id");
  return resource;
}


export async function retryFailedNarrationSegments(
  editionId: string,
  request: RetryFailedNarrationSegmentsRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<RetryFailedNarrationSegmentsResponse> {
  const normalizedEditionId = normalizeChapterUuid(editionId, "edition_id");
  const payload = parseRetryFailedNarrationSegmentsRequest(request);
  const resource = await parsedProductionRequest(
    `/narration-editions/${chapterPathId(normalizedEditionId, "edition_id")}/retry-failed-segments`,
    parseRetryFailedNarrationSegmentsResponse,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  requireChapterIdentity(resource.edition_id, normalizedEditionId, "edition_id");
  const accepted = new Set(resource.accepted_segment_ids);
  if (
    accepted.size !== payload.segment_ids.length
    || payload.segment_ids.some((segmentId) => !accepted.has(segmentId))
  ) {
    throw new ChapterNarrationContractError(
      "retry_response.accepted_segment_ids",
      "response does not match the requested selection",
    );
  }
  return resource;
}


export async function createNarrationWorkflow(
  documentId: string,
  request: CreateNarrationWorkflowRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<NarrationWorkflowResource> {
  const normalizedDocumentId = normalizeChapterUuid(documentId, "document_id");
  const payload = parseCreateNarrationWorkflowRequest(request);
  const resource = await parsedProductionRequest(
    `/documents/${chapterPathId(normalizedDocumentId, "document_id")}/narration-requests`,
    parseNarrationWorkflowResource,
    {
      ...jsonInit("POST", payload, signal),
      headers: idempotencyHeaders(idempotencyKey),
    },
  );
  if (
    resource.intent !== payload.intent
    || resource.source_content_hash !== payload.expected_content_hash
  ) {
    throw new ChapterNarrationContractError(
      "workflow",
      "response does not match the requested intent and saved source",
    );
  }
  return resource;
}


export async function getNarrationWorkflow(
  requestId: string,
  signal?: AbortSignal,
): Promise<NarrationWorkflowResource> {
  const normalizedRequestId = normalizeChapterUuid(requestId, "request_id");
  const resource = await parsedProductionRequest(
    `/narration-requests/${chapterPathId(normalizedRequestId, "request_id")}`,
    parseNarrationWorkflowResource,
    { signal },
  );
  requireChapterIdentity(resource.request_id, normalizedRequestId, "request_id");
  return resource;
}


export async function switchNarrationEdition(
  documentId: string,
  request: SwitchNarrationEditionRequest,
  signal?: AbortSignal,
): Promise<SwitchNarrationEditionResponse> {
  const normalizedDocumentId = normalizeChapterUuid(documentId, "document_id");
  const payload = parseSwitchNarrationEditionRequest(request);
  const resource = await parsedProductionRequest(
    `/documents/${chapterPathId(normalizedDocumentId, "document_id")}/current-narration-edition`,
    parseSwitchNarrationEditionResponse,
    jsonInit("PUT", payload, signal),
  );
  if (
    resource.document_id !== normalizedDocumentId
    || resource.current_edition_id !== payload.target_edition_id
    || resource.pointer_version !== payload.expected_version + 1
    || resource.switch_mode !== payload.switch_mode
    || (
      payload.start_segment_id !== null
      && resource.start_segment_id !== payload.start_segment_id
    )
    || (
      payload.switch_mode === "immediate"
      && (resource.start_segment_id === null || resource.playback_progress_id === null)
    )
    || (
      payload.switch_mode === "next_playback"
      && (resource.start_segment_id !== null || resource.playback_progress_id !== null)
    )
  ) {
    throw new ChapterNarrationContractError(
      "switch_response",
      "response does not match target, CAS, mode, or start guards",
    );
  }
  return resource;
}
