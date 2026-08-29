export const PRIVATE_VOICE_DELETION_CONTRACT_VERSION = "private-voice-deletion/1" as const;
export const PRIVATE_VOICE_DELETION_IMPACT_VERSION = (
  "private-voice-deletion-impact/1"
) as const;
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
  | "failed";


export type ExternalBackupStatus = "unmanaged" | "managed_pending" | "managed_expired";


export type VoiceLifecycleEligibility = "unreferenced" | "referenced" | "blocked";


export type VoiceLifecycleBusyAction =
  | "discard"
  | "request"
  | "confirm"
  | "cancel"
  | "retry";


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
  readonly voiceVersionCount: number;
  readonly currentNarratorCount: number;
  readonly characterBindingCount: number;
  readonly anonymousSpeakerCount: number;
  readonly genericSlotCount: number;
  readonly historicalEditionCount: number;
  readonly renderCount: number;
  readonly exportCount: number;
  readonly assetCount: number;
  readonly totalBytes: number;
  readonly activeJobCount: number;
  readonly externalBackupStatus: ExternalBackupStatus;
  readonly historicalAudioConsequence: "unavailable_private_voice_deleted" | null;
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
  readonly executeAfter: string | null;
  readonly impactExpiresAt: string | null;
  readonly assetCount: number;
  readonly totalBytes: number;
  readonly externalBackupStatus: ExternalBackupStatus;
  readonly confirmedAt: string | null;
  readonly cancelledAt: string | null;
  readonly completedAt: string | null;
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
  readonly impactExpired: boolean;
  readonly confirmationMatches: boolean;
  readonly canDiscardUnreferenced: boolean;
  readonly canRequestReferencedDeletion: boolean;
  readonly canConfirm: boolean;
  readonly canCancel: boolean;
  readonly canRetry: boolean;
  readonly busy: boolean;
}


export interface DeriveVoiceLifecycleStateInput {
  readonly capabilityEnabled?: boolean;
  readonly profile: VoiceLifecycleProfile;
  readonly request?: VoiceDeletionRequestSnapshot | null;
  readonly nowEpochMs: number;
  readonly confirmationText?: string;
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


function frozenView(
  state: VoiceLifecycleViewState,
): VoiceLifecycleViewState {
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


function validProfile(profile: VoiceLifecycleProfile): boolean {
  return profile.profileId.trim().length > 0
    && profile.displayName.trim().length > 0
    && finiteNonNegative(profile.expectedProfileVersion)
    && profile.expectedProfileVersion >= 1;
}


function validRequestForProfile(
  profile: VoiceLifecycleProfile,
  request: VoiceDeletionRequestSnapshot,
): boolean {
  const requiresCurrentProfileVersion = request.state === "grace_pending"
    || request.state === "requested";
  const impactCounts = [
    request.impact.voiceVersionCount,
    request.impact.currentNarratorCount,
    request.impact.characterBindingCount,
    request.impact.anonymousSpeakerCount,
    request.impact.genericSlotCount,
    request.impact.historicalEditionCount,
    request.impact.renderCount,
    request.impact.exportCount,
    request.impact.assetCount,
    request.impact.totalBytes,
    request.impact.activeJobCount,
  ];
  return request.contractVersion === PRIVATE_VOICE_DELETION_CONTRACT_VERSION
    && request.requestId.trim().length > 0
    && request.profileId === profile.profileId
    && request.impact.profileId === profile.profileId
    && request.novelId === request.impact.novelId
    && finiteNonNegative(request.expectedProfileVersion)
    && request.expectedProfileVersion >= 1
    && request.impact.profileVersion === request.expectedProfileVersion
    && (
      !requiresCurrentProfileVersion
      || request.expectedProfileVersion === profile.expectedProfileVersion
    )
    && request.impact.schemaVersion === PRIVATE_VOICE_DELETION_IMPACT_VERSION
    && /^[a-f0-9]{64}$/.test(request.impactDigest)
    && request.externalBackupStatus === request.impact.externalBackupStatus
    && finiteNonNegative(request.assetCount)
    && finiteNonNegative(request.totalBytes)
    && impactCounts.every(finiteNonNegative)
    && request.assetCount === request.impact.assetCount
    && request.totalBytes === request.impact.totalBytes
    && (
      request.state !== "grace_pending"
      || validTimestamp(request.executeAfter) !== null
    )
    && (
      request.state !== "requested"
      || validTimestamp(request.impactExpiresAt) !== null
    )
    && (
      request.state !== "grace_pending"
      || request.command === "discard_unreferenced_private_voice"
    )
    && (
      request.state !== "requested"
      || request.command === "true_delete_private_voice"
    );
}


function requestStatusLabel(
  request: VoiceDeletionRequestSnapshot,
  undoRemainingSeconds: number | null,
): Readonly<{ label: string; tone: VoiceLifecycleTone }> {
  if (request.state === "grace_pending") {
    return undoRemainingSeconds !== null && undoRemainingSeconds > 0
      ? {
        label: `${undoRemainingSeconds} 秒后开始删除；在此之前可以撤销。`,
        tone: "warning",
      }
      : {
        label: "撤销时间已结束，正在等待进入删除阶段。",
        tone: "warning",
      };
  }
  if (request.state === "requested") {
    return { label: "请核对影响并输入音色名称，确认后才会开始删除。", tone: "danger" };
  }
  if (request.state === "cancelled") {
    return { label: "删除已经撤销，音色仍然保留。", tone: "success" };
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
  if (request.confirmedAt === null) {
    return { label: "删除请求失败；请重新发起删除。", tone: "danger" };
  }
  return {
    label: request.failureCode
      ? `删除失败（${request.failureCode}），可以按原删除计划重试。`
      : "删除失败，可以按原删除计划重试。",
    tone: "danger",
  };
}


export function voiceLifecycleUndoRemainingSeconds(
  executeAfter: string | null,
  nowEpochMs: number,
): number | null {
  const deadline = validTimestamp(executeAfter);
  if (deadline === null || !Number.isFinite(nowEpochMs)) return null;
  return Math.max(0, Math.ceil((deadline - nowEpochMs) / 1_000));
}


export function deriveVoiceLifecycleState(
  input: DeriveVoiceLifecycleStateInput,
): VoiceLifecycleViewState {
  const capabilityEnabled = input.capabilityEnabled === true;
  const busy = input.busyAction !== null && input.busyAction !== undefined;
  if (!capabilityEnabled) {
    return frozenView({
      phase: "hidden",
      visible: false,
      valid: true,
      tone: "neutral",
      statusLabel: "",
      undoRemainingSeconds: null,
      impactExpired: false,
      confirmationMatches: false,
      canDiscardUnreferenced: false,
      canRequestReferencedDeletion: false,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
      busy,
    });
  }

  const request = input.request ?? null;
  if (!validProfile(input.profile) || (request !== null && !Number.isFinite(input.nowEpochMs))) {
    return frozenView({
      phase: "invalid",
      visible: true,
      valid: false,
      tone: "danger",
      statusLabel: "当前音色资料无效，已停止所有删除操作。",
      undoRemainingSeconds: null,
      impactExpired: false,
      confirmationMatches: false,
      canDiscardUnreferenced: false,
      canRequestReferencedDeletion: false,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
      busy,
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
        ? "此私人音色没有当前或历史引用；删除后有 30 秒撤销时间。"
        : "此音色仍被使用；删除前必须先查看冻结的影响摘要。",
      undoRemainingSeconds: null,
      impactExpired: false,
      confirmationMatches: false,
      canDiscardUnreferenced: unreferenced && !busy,
      canRequestReferencedDeletion: !blocked && !unreferenced && !busy,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
      busy,
    });
  }

  if (!validRequestForProfile(input.profile, request)) {
    return frozenView({
      phase: "invalid",
      visible: true,
      valid: false,
      tone: "danger",
      statusLabel: "删除请求与当前音色或影响摘要不一致，已停止所有删除操作。",
      undoRemainingSeconds: null,
      impactExpired: false,
      confirmationMatches: false,
      canDiscardUnreferenced: false,
      canRequestReferencedDeletion: false,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
      busy,
    });
  }

  const undoRemainingSeconds = request.state === "grace_pending"
    ? voiceLifecycleUndoRemainingSeconds(request.executeAfter, input.nowEpochMs)
    : null;
  const confirmationMatches = request.state === "requested"
    && input.confirmationText === input.profile.displayName;
  const expiry = request.state === "requested"
    ? validTimestamp(request.impactExpiresAt)
    : null;
  const impactExpired = expiry !== null && input.nowEpochMs >= expiry;
  const status = impactExpired
    ? {
      label: "冻结的删除影响已过期；请取消后重新查看最新影响。",
      tone: "danger" as const,
    }
    : requestStatusLabel(request, undoRemainingSeconds);
  return frozenView({
    phase: request.state,
    visible: true,
    valid: true,
    tone: status.tone,
    statusLabel: status.label,
    undoRemainingSeconds,
    impactExpired,
    confirmationMatches,
    canDiscardUnreferenced: false,
    canRequestReferencedDeletion: false,
    canConfirm: request.state === "requested"
      && !impactExpired
      && confirmationMatches
      && !busy,
    canCancel: (
      request.state === "requested"
      || (
        request.state === "grace_pending"
        && undoRemainingSeconds !== null
        && undoRemainingSeconds > 0
      )
    ) && !busy,
    canRetry: request.state === "failed" && request.confirmedAt !== null && !busy,
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
