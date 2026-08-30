import type {
  PrivateVoiceDeletionImpactResource,
  PrivateVoiceDeletionRequestResource,
  PrivateVoiceLifecycleProfileResource,
} from "./contracts";

export const PRIVATE_VOICE_DELETION_CONTRACT_VERSION = "private-voice-deletion/2" as const;
export const PRIVATE_VOICE_DELETION_IMPACT_VERSION = "private-voice-deletion-impact/2" as const;
export const UNREFERENCED_VOICE_UNDO_SECONDS = 30 as const;

export type PrivateVoiceDeletionCommand =
  | "discard_unreferenced_private_voice"
  | "true_delete_private_voice";

export type PrivateVoiceDeletionRequestState =
  | "grace_pending"
  | "requested"
  | "cancelled"
  | "live_deleting"
  | "live_deleted_backup_pending"
  | "completed"
  | "failed"
  | "superseded";

export type ExternalBackupStatus = "unmanaged" | "managed_pending" | "managed_expired";
export type VoiceLifecycleEligibility = "unreferenced" | "referenced" | "blocked";
export type VoiceLifecycleBusyAction = "create" | "confirm" | "cancel" | "retry";

export interface VoiceLifecycleProfile {
  readonly profileId: string;
  readonly displayName: string;
  readonly expectedProfileVersion: number;
  readonly sourceType: "uploaded" | "generated";
  readonly eligibility: VoiceLifecycleEligibility;
  readonly blockedReason?: string | null;
}

export interface VoiceDeletionImpactSnapshot {
  readonly schemaVersion: typeof PRIVATE_VOICE_DELETION_IMPACT_VERSION;
  readonly profileId: string;
  readonly novelId: string;
  readonly profileVersion: number;
  readonly voiceVersionIds: readonly string[];
  readonly currentNarratorCount: number;
  readonly characterBindingCount: number;
  readonly anonymousSpeakerCount: number;
  readonly genericSlotCount: number;
  readonly historicalEditionCount: number;
  readonly renderCount: number;
  readonly exportCount: number;
  readonly currentReferenceCount: number;
  readonly historicalReferenceCount: number;
  readonly referenceCount: number;
  readonly assetCount: number;
  readonly totalBytes: number;
  readonly activeJobCount: number;
  readonly externalBackupStatus: ExternalBackupStatus;
  readonly historicalAudioConsequence: "unavailable_private_voice_deleted" | null;
  readonly impactSummary: string;
}

export interface VoiceDeletionRequestSnapshot {
  readonly contractVersion: typeof PRIVATE_VOICE_DELETION_CONTRACT_VERSION;
  readonly requestId: string;
  readonly profileId: string;
  readonly novelId: string;
  readonly command: PrivateVoiceDeletionCommand;
  readonly state: PrivateVoiceDeletionRequestState;
  readonly expectedProfileVersion: number;
  readonly impactDigest: string;
  readonly impact: VoiceDeletionImpactSnapshot;
  readonly eligibility: VoiceLifecycleEligibility;
  readonly referenceCount: number;
  readonly serverNow: string;
  readonly executeAfter: string | null;
  readonly impactExpiresAt: string | null;
  readonly assetCount: number;
  readonly totalBytes: number;
  readonly externalBackupStatus: ExternalBackupStatus;
  readonly cancellable: boolean;
  readonly retryable: boolean;
  readonly terminal: boolean;
  readonly confirmedAt: string | null;
  readonly cancelledAt: string | null;
  readonly completedAt: string | null;
  readonly supersededAt: string | null;
  readonly jobDrainStartedAt: string | null;
  readonly jobDrainDeadline: string | null;
  readonly failureCode: string | null;
}

export type VoiceLifecyclePhase =
  | "hidden"
  | "idle-unreferenced"
  | "idle-referenced"
  | "blocked"
  | PrivateVoiceDeletionRequestState
  | "invalid";

export type VoiceLifecycleTone = "neutral" | "warning" | "danger" | "success";

export interface VoiceLifecycleViewState {
  readonly phase: VoiceLifecyclePhase;
  readonly visible: boolean;
  readonly valid: boolean;
  readonly tone: VoiceLifecycleTone;
  readonly statusLabel: string;
  readonly undoRemainingSeconds: number | null;
  readonly jobDrainRemainingSeconds: number | null;
  readonly impactExpired: boolean;
  readonly canCreateDeletionRequest: boolean;
  readonly canConfirm: boolean;
  readonly canCancel: boolean;
  readonly canRetry: boolean;
  readonly terminal: boolean;
  readonly busy: boolean;
}

export interface DeriveVoiceLifecycleStateInput {
  readonly capabilityEnabled?: boolean;
  readonly profile: VoiceLifecycleProfile;
  readonly request?: VoiceDeletionRequestSnapshot | null;
  /** Milliseconds elapsed locally since this response's server_now was observed. */
  readonly elapsedSinceServerNowMs?: number;
  readonly busyAction?: VoiceLifecycleBusyAction | null;
}

export interface VoiceLifecycleProfileCommand {
  readonly profileId: string;
  readonly expectedProfileVersion: number;
}

export interface VoiceLifecycleConfirmCommand {
  readonly requestId: string;
  readonly expectedProfileVersion: number;
  readonly impactDigest: string;
}

function frozenView(state: VoiceLifecycleViewState): VoiceLifecycleViewState {
  return Object.freeze(state);
}

function finiteNonNegative(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0;
}

function validTimestamp(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function validOptionalTimestamp(value: string | null): boolean {
  return value === null || validTimestamp(value) !== null;
}

function validProfile(profile: VoiceLifecycleProfile): boolean {
  return profile.profileId.trim().length > 0
    && profile.displayName.trim().length > 0
    && finiteNonNegative(profile.expectedProfileVersion)
    && profile.expectedProfileVersion >= 1;
}

function isWaitingForJobs(request: VoiceDeletionRequestSnapshot): boolean {
  return request.state === "failed"
    && request.failureCode === "VOICE_DELETE_WAITING_FOR_JOBS";
}

function validAuthoritativeFlags(request: VoiceDeletionRequestSnapshot): boolean {
  if (
    typeof request.cancellable !== "boolean"
    || typeof request.retryable !== "boolean"
    || typeof request.terminal !== "boolean"
  ) return false;
  if (request.terminal && (request.cancellable || request.retryable)) return false;
  if (["completed", "cancelled", "superseded"].includes(request.state)) {
    return request.terminal;
  }
  if (request.state !== "failed" && request.terminal) return false;
  if (request.cancellable && !["grace_pending", "requested", "failed"].includes(request.state)) {
    return false;
  }
  if (request.retryable && request.state !== "failed") return false;
  return true;
}

function validRequestForProfile(
  profile: VoiceLifecycleProfile,
  request: VoiceDeletionRequestSnapshot,
): boolean {
  const requiresCurrentProfileVersion = request.state === "grace_pending"
    || request.state === "requested"
    || isWaitingForJobs(request);
  const impactCounts = [
    request.impact.currentNarratorCount,
    request.impact.characterBindingCount,
    request.impact.anonymousSpeakerCount,
    request.impact.genericSlotCount,
    request.impact.historicalEditionCount,
    request.impact.renderCount,
    request.impact.exportCount,
    request.impact.currentReferenceCount,
    request.impact.historicalReferenceCount,
    request.impact.referenceCount,
    request.impact.assetCount,
    request.impact.totalBytes,
    request.impact.activeJobCount,
  ];
  const timestamps = [
    request.executeAfter,
    request.impactExpiresAt,
    request.confirmedAt,
    request.cancelledAt,
    request.completedAt,
    request.supersededAt,
    request.jobDrainStartedAt,
    request.jobDrainDeadline,
  ];
  return request.contractVersion === PRIVATE_VOICE_DELETION_CONTRACT_VERSION
    && request.requestId.trim().length > 0
    && request.profileId === profile.profileId
    && request.impact.profileId === profile.profileId
    && request.novelId === request.impact.novelId
    && finiteNonNegative(request.expectedProfileVersion)
    && request.expectedProfileVersion >= 1
    && request.impact.profileVersion === request.expectedProfileVersion
    && (!requiresCurrentProfileVersion
      || request.expectedProfileVersion === profile.expectedProfileVersion)
    && request.impact.schemaVersion === PRIVATE_VOICE_DELETION_IMPACT_VERSION
    && request.impact.voiceVersionIds.every((value) => value.trim().length > 0)
    && new Set(request.impact.voiceVersionIds).size === request.impact.voiceVersionIds.length
    && request.impact.impactSummary.trim().length > 0
    && /^[a-f0-9]{64}$/.test(request.impactDigest)
    && ["unreferenced", "referenced", "blocked"].includes(request.eligibility)
    && request.referenceCount === request.impact.referenceCount
    && request.impact.currentReferenceCount === (
      request.impact.currentNarratorCount
      + request.impact.characterBindingCount
      + request.impact.anonymousSpeakerCount
      + request.impact.genericSlotCount
    )
    && request.impact.historicalReferenceCount === (
      request.impact.historicalEditionCount
      + request.impact.renderCount
      + request.impact.exportCount
    )
    && request.impact.referenceCount === (
      request.impact.currentReferenceCount + request.impact.historicalReferenceCount
    )
    && request.externalBackupStatus === request.impact.externalBackupStatus
    && finiteNonNegative(request.assetCount)
    && finiteNonNegative(request.totalBytes)
    && impactCounts.every(finiteNonNegative)
    && request.assetCount === request.impact.assetCount
    && request.totalBytes === request.impact.totalBytes
    && validTimestamp(request.serverNow) !== null
    && timestamps.every(validOptionalTimestamp)
    && (request.state !== "grace_pending" || (
      validTimestamp(request.executeAfter) !== null
      && request.command === "discard_unreferenced_private_voice"
    ))
    && (request.state !== "requested" || (
      validTimestamp(request.impactExpiresAt) !== null
      && request.command === "true_delete_private_voice"
    ))
    && (request.state !== "superseded" || validTimestamp(request.supersededAt) !== null)
    && (!isWaitingForJobs(request) || (
      validTimestamp(request.jobDrainStartedAt) !== null
      && validTimestamp(request.jobDrainDeadline) !== null
    ))
    && validAuthoritativeFlags(request);
}

function requestStatusLabel(
  request: VoiceDeletionRequestSnapshot,
  undoRemainingSeconds: number | null,
  jobDrainRemainingSeconds: number | null,
): Readonly<{ label: string; tone: VoiceLifecycleTone }> {
  if (request.state === "grace_pending") {
    return undoRemainingSeconds !== null && undoRemainingSeconds > 0
      ? { label: `${undoRemainingSeconds} 秒后开始删除；在此之前可以撤销。`, tone: "warning" }
      : { label: "撤销时间已结束，正在等待进入删除阶段。", tone: "warning" };
  }
  if (request.state === "requested") {
    return { label: "请核对一次冻结的影响摘要，确认后才会开始删除。", tone: "danger" };
  }
  if (request.state === "cancelled") {
    return { label: "删除已经撤销，音色仍然保留。", tone: "success" };
  }
  if (request.state === "superseded") {
    return { label: "删除计划因音色或影响发生变化而失效，请重新加载最新影响。", tone: "warning" };
  }
  if (request.state === "live_deleting") {
    return { label: "正在删除项目管理的在线音色数据；此阶段不能撤销。", tone: "warning" };
  }
  if (request.state === "live_deleted_backup_pending") {
    return { label: "在线数据已删除，受管备份仍在等待到期。", tone: "warning" };
  }
  if (request.state === "completed") {
    return { label: "项目管理的在线音色数据已删除。", tone: "success" };
  }
  if (isWaitingForJobs(request)) {
    return {
      label: jobDrainRemainingSeconds !== null
        ? `仍有朗读任务使用该音色；可撤销或重试，任务排空窗口剩余 ${jobDrainRemainingSeconds} 秒。`
        : "仍有朗读任务使用该音色；可撤销或重试。",
      tone: "warning",
    };
  }
  if (request.retryable) {
    return {
      label: request.failureCode
        ? `删除暂时失败（${request.failureCode}），可以按原精确删除计划重试。`
        : "删除暂时失败，可以按原精确删除计划重试。",
      tone: "danger",
    };
  }
  return {
    label: request.failureCode
      ? `删除已安全停止（${request.failureCode}），未继续修改音色资产。`
      : "删除已安全停止，未继续修改音色资产。",
    tone: "danger",
  };
}

export function voiceLifecycleServerAlignedEpochMs(
  serverNow: string,
  elapsedSinceServerNowMs: number,
): number | null {
  const baseline = validTimestamp(serverNow);
  if (baseline === null || !Number.isFinite(elapsedSinceServerNowMs) || elapsedSinceServerNowMs < 0) {
    return null;
  }
  return baseline + elapsedSinceServerNowMs;
}

export function voiceLifecycleRemainingSeconds(
  deadlineValue: string | null,
  serverNow: string,
  elapsedSinceServerNowMs: number,
): number | null {
  const deadline = validTimestamp(deadlineValue);
  const alignedNow = voiceLifecycleServerAlignedEpochMs(serverNow, elapsedSinceServerNowMs);
  if (deadline === null || alignedNow === null) return null;
  return Math.max(0, Math.ceil((deadline - alignedNow) / 1_000));
}

export function voiceLifecycleUndoRemainingSeconds(
  executeAfter: string | null,
  serverNow: string,
  elapsedSinceServerNowMs: number,
): number | null {
  return voiceLifecycleRemainingSeconds(executeAfter, serverNow, elapsedSinceServerNowMs);
}

export function deriveVoiceLifecycleState(
  input: DeriveVoiceLifecycleStateInput,
): VoiceLifecycleViewState {
  const capabilityEnabled = input.capabilityEnabled === true;
  const busy = input.busyAction !== null && input.busyAction !== undefined;
  const empty = {
    undoRemainingSeconds: null,
    jobDrainRemainingSeconds: null,
    impactExpired: false,
    canCreateDeletionRequest: false,
    canConfirm: false,
    canCancel: false,
    canRetry: false,
    terminal: false,
    busy,
  } as const;
  if (!capabilityEnabled) {
    return frozenView({ phase: "hidden", visible: false, valid: true, tone: "neutral", statusLabel: "", ...empty });
  }

  const request = input.request ?? null;
  const elapsed = input.elapsedSinceServerNowMs ?? 0;
  if (!validProfile(input.profile) || !Number.isFinite(elapsed) || elapsed < 0) {
    return frozenView({
      phase: "invalid", visible: true, valid: false, tone: "danger",
      statusLabel: "当前音色资料或服务端时间无效，已停止所有删除操作。",
      ...empty,
    });
  }
  if (request === null) {
    const blocked = input.profile.eligibility === "blocked";
    const unreferenced = input.profile.eligibility === "unreferenced";
    return frozenView({
      phase: blocked ? "blocked" : unreferenced ? "idle-unreferenced" : "idle-referenced",
      visible: true,
      valid: true,
      tone: blocked ? "warning" : unreferenced ? "neutral" : "danger",
      statusLabel: blocked
        ? input.profile.blockedReason?.trim() || "此音色当前不能删除。"
        : unreferenced
        ? "此私人音色没有当前或历史引用；点击后直接进入 30 秒可撤销期。"
        : "此音色仍被使用；删除前只需核对一次服务端冻结的影响摘要。",
      ...empty,
      canCreateDeletionRequest: !blocked && !busy,
    });
  }

  if (!validRequestForProfile(input.profile, request)) {
    return frozenView({
      phase: "invalid", visible: true, valid: false, tone: "danger",
      statusLabel: "删除请求与当前音色、服务端时间或影响摘要不一致，已停止所有删除操作。",
      ...empty,
    });
  }

  const undoRemainingSeconds = request.state === "grace_pending"
    ? voiceLifecycleUndoRemainingSeconds(request.executeAfter, request.serverNow, elapsed)
    : null;
  const jobDrainRemainingSeconds = isWaitingForJobs(request)
    ? voiceLifecycleRemainingSeconds(request.jobDrainDeadline, request.serverNow, elapsed)
    : null;
  const alignedNow = voiceLifecycleServerAlignedEpochMs(request.serverNow, elapsed);
  const expiry = request.state === "requested" ? validTimestamp(request.impactExpiresAt) : null;
  const impactExpired = expiry !== null && alignedNow !== null && alignedNow >= expiry;
  const status = impactExpired
    ? { label: "冻结的删除影响已过期；请取消后重新查看最新影响。", tone: "danger" as const }
    : requestStatusLabel(request, undoRemainingSeconds, jobDrainRemainingSeconds);
  const graceStillOpen = request.state !== "grace_pending"
    || (undoRemainingSeconds !== null && undoRemainingSeconds > 0);
  return frozenView({
    phase: request.state,
    visible: true,
    valid: true,
    tone: status.tone,
    statusLabel: status.label,
    undoRemainingSeconds,
    jobDrainRemainingSeconds,
    impactExpired,
    canCreateDeletionRequest: false,
    canConfirm: request.state === "requested" && !impactExpired && !request.terminal && !busy,
    canCancel: request.cancellable && graceStillOpen && !request.terminal && !busy,
    canRetry: request.retryable && !request.terminal && !busy,
    terminal: request.terminal,
    busy,
  });
}

export function voiceLifecycleProfileCommand(
  profile: VoiceLifecycleProfile,
): VoiceLifecycleProfileCommand {
  return Object.freeze({
    profileId: profile.profileId,
    expectedProfileVersion: profile.expectedProfileVersion,
  });
}

export function voiceLifecycleConfirmCommand(
  request: VoiceDeletionRequestSnapshot,
): VoiceLifecycleConfirmCommand {
  return Object.freeze({
    requestId: request.requestId,
    expectedProfileVersion: request.expectedProfileVersion,
    impactDigest: request.impactDigest,
  });
}

export function formatVoiceLifecycleBytes(totalBytes: number): string {
  const value = Number.isFinite(totalBytes) && totalBytes > 0 ? totalBytes : 0;
  if (value < 1_024) return `${Math.round(value)} B`;
  if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KiB`;
  if (value < 1_073_741_824) return `${(value / 1_048_576).toFixed(1)} MiB`;
  return `${(value / 1_073_741_824).toFixed(1)} GiB`;
}

export function externalBackupStatusMessage(status: ExternalBackupStatus): string {
  if (status === "managed_pending") {
    return "在线数据已删除，项目管理的备份仍在等待到期。";
  }
  if (status === "managed_expired") {
    return "项目管理的在线副本与受管备份均已按证据到期。";
  }
  return "Time Machine、用户自建快照或其他外部备份不受本项目管理，无法承诺同步删除。";
}

export function voiceDeletionImpactFromResource(
  resource: PrivateVoiceDeletionImpactResource,
): VoiceDeletionImpactSnapshot {
  return Object.freeze({
    schemaVersion: resource.schema_version,
    profileId: resource.profile_id,
    novelId: resource.novel_id,
    profileVersion: resource.profile_version,
    voiceVersionIds: Object.freeze([...resource.voice_version_ids]),
    currentNarratorCount: resource.current_narrator_count,
    characterBindingCount: resource.character_binding_count,
    anonymousSpeakerCount: resource.anonymous_speaker_count,
    genericSlotCount: resource.generic_slot_count,
    historicalEditionCount: resource.historical_edition_count,
    renderCount: resource.render_count,
    exportCount: resource.export_count,
    currentReferenceCount: resource.current_reference_count,
    historicalReferenceCount: resource.historical_reference_count,
    referenceCount: resource.reference_count,
    assetCount: resource.asset_count,
    totalBytes: resource.total_bytes,
    activeJobCount: resource.active_job_count,
    externalBackupStatus: resource.external_backup_status,
    historicalAudioConsequence: resource.historical_audio_consequence,
    impactSummary: resource.impact_summary,
  });
}

export function voiceDeletionRequestFromResource(
  resource: PrivateVoiceDeletionRequestResource,
): VoiceDeletionRequestSnapshot {
  return Object.freeze({
    contractVersion: resource.contract_version,
    requestId: resource.request_id,
    profileId: resource.profile_id,
    novelId: resource.novel_id,
    command: resource.command,
    state: resource.state,
    expectedProfileVersion: resource.expected_profile_version,
    impactDigest: resource.impact_digest,
    impact: voiceDeletionImpactFromResource(resource.impact),
    eligibility: resource.eligibility,
    referenceCount: resource.reference_count,
    serverNow: resource.server_now,
    executeAfter: resource.execute_after,
    impactExpiresAt: resource.impact_expires_at,
    assetCount: resource.asset_count,
    totalBytes: resource.total_bytes,
    externalBackupStatus: resource.external_backup_status,
    cancellable: resource.cancellable,
    retryable: resource.retryable,
    terminal: resource.terminal,
    confirmedAt: resource.confirmed_at,
    cancelledAt: resource.cancelled_at,
    completedAt: resource.completed_at,
    supersededAt: resource.superseded_at,
    jobDrainStartedAt: resource.job_drain_started_at,
    jobDrainDeadline: resource.job_drain_deadline,
    failureCode: resource.failure_code,
  });
}

export function voiceLifecycleProfileFromResource(
  resource: PrivateVoiceLifecycleProfileResource,
): VoiceLifecycleProfile {
  return Object.freeze({
    profileId: resource.profile_id,
    displayName: resource.display_name,
    expectedProfileVersion: resource.profile_version,
    sourceType: resource.source_type,
    eligibility: resource.eligibility,
    blockedReason: resource.blocked_reason,
  });
}
