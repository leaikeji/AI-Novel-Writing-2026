import { describe, expect, it } from "vitest";

import {
  PRIVATE_VOICE_DELETION_CONTRACT_VERSION,
  PRIVATE_VOICE_DELETION_IMPACT_VERSION,
  deriveVoiceLifecycleState,
  externalBackupStatusMessage,
  formatVoiceLifecycleBytes,
  voiceLifecycleConfirmCommand,
  voiceLifecycleProfileCommand,
  voiceLifecycleServerAlignedEpochMs,
  voiceLifecycleUndoRemainingSeconds,
  type PrivateVoiceDeletionRequestState,
  type VoiceDeletionRequestSnapshot,
  type VoiceLifecycleProfile,
} from "./voice-lifecycle-state";

const PROFILE_ID = "10000000-0000-4000-8000-000000000001";
const NOVEL_ID = "20000000-0000-4000-8000-000000000001";
const REQUEST_ID = "30000000-0000-4000-8000-000000000001";
const SERVER_NOW = "2026-08-29T10:00:00.000Z";

function profile(eligibility: VoiceLifecycleProfile["eligibility"]): VoiceLifecycleProfile {
  return Object.freeze({
    profileId: PROFILE_ID,
    displayName: "林晚的雨夜声线",
    expectedProfileVersion: 4,
    sourceType: "generated",
    eligibility,
  });
}

function request(
  state: PrivateVoiceDeletionRequestState,
  patch: Partial<VoiceDeletionRequestSnapshot> = {},
): VoiceDeletionRequestSnapshot {
  const terminal = ["cancelled", "completed", "superseded"].includes(state);
  const cancellable = state === "grace_pending" || state === "requested";
  const retryable = state === "failed";
  return Object.freeze({
    contractVersion: PRIVATE_VOICE_DELETION_CONTRACT_VERSION,
    requestId: REQUEST_ID,
    profileId: PROFILE_ID,
    novelId: NOVEL_ID,
    command: state === "grace_pending"
      ? "discard_unreferenced_private_voice"
      : "true_delete_private_voice",
    state,
    expectedProfileVersion: 4,
    impactDigest: "a".repeat(64),
    impact: Object.freeze({
      schemaVersion: PRIVATE_VOICE_DELETION_IMPACT_VERSION,
      profileId: PROFILE_ID,
      novelId: NOVEL_ID,
      profileVersion: 4,
      voiceVersionIds: [
        "40000000-0000-4000-8000-000000000001",
        "40000000-0000-4000-8000-000000000002",
      ],
      currentNarratorCount: 1,
      characterBindingCount: 2,
      anonymousSpeakerCount: 1,
      genericSlotCount: 1,
      historicalEditionCount: 3,
      renderCount: 8,
      exportCount: 1,
      currentReferenceCount: 5,
      historicalReferenceCount: 12,
      referenceCount: 17,
      assetCount: 5,
      totalBytes: 2_097_152,
      activeJobCount: 0,
      externalBackupStatus: "unmanaged",
      historicalAudioConsequence: "unavailable_private_voice_deleted",
      impactSummary: "将移除 2 个音色版本及 5 个媒体资产。",
    }),
    eligibility: "referenced",
    referenceCount: 17,
    serverNow: SERVER_NOW,
    executeAfter: state === "grace_pending" ? "2026-08-29T10:00:30.000Z" : null,
    impactExpiresAt: state === "requested" ? "2026-08-29T10:15:00.000Z" : null,
    assetCount: 5,
    totalBytes: 2_097_152,
    externalBackupStatus: "unmanaged",
    cancellable,
    retryable,
    terminal,
    confirmedAt: ["live_deleting", "live_deleted_backup_pending", "completed", "failed"]
      .includes(state) ? "2026-08-29T10:00:31.000Z" : null,
    cancelledAt: state === "cancelled" ? "2026-08-29T10:00:05.000Z" : null,
    completedAt: state === "completed" ? "2026-08-29T10:00:35.000Z" : null,
    supersededAt: state === "superseded" ? "2026-08-29T10:00:20.000Z" : null,
    jobDrainStartedAt: null,
    jobDrainDeadline: null,
    failureCode: state === "failed" ? "VOICE_DELETE_UNLINK_FAILED" : null,
    ...patch,
  });
}

describe("voice lifecycle state v2", () => {
  it("fails closed and exposes no action when capability is absent by default", () => {
    expect(deriveVoiceLifecycleState({ profile: profile("unreferenced") })).toMatchObject({
      phase: "hidden",
      visible: false,
      canCreateDeletionRequest: false,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
    });
  });

  it("uses one create endpoint for zero-confirm unreferenced and one-summary referenced deletion", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("unreferenced"),
    })).toMatchObject({
      phase: "idle-unreferenced",
      canCreateDeletionRequest: true,
    });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
    })).toMatchObject({
      phase: "idle-referenced",
      canCreateDeletionRequest: true,
    });
  });

  it("derives countdown from server_now plus local elapsed time", () => {
    expect(voiceLifecycleServerAlignedEpochMs(SERVER_NOW, 15_001)).toBe(
      Date.parse(SERVER_NOW) + 15_001,
    );
    expect(voiceLifecycleUndoRemainingSeconds(
      "2026-08-29T10:00:30.000Z",
      SERVER_NOW,
      15_001,
    )).toBe(15);
    const pending = request("grace_pending");
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("unreferenced"),
      request: pending,
      elapsedSinceServerNowMs: 15_001,
    })).toMatchObject({ undoRemainingSeconds: 15, canCancel: true });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("unreferenced"),
      request: pending,
      elapsedSinceServerNowMs: 30_000,
    })).toMatchObject({
      undoRemainingSeconds: 0,
      canCancel: false,
      statusLabel: "撤销时间已结束，正在等待进入删除阶段。",
    });
  });

  it("allows the single impact confirmation without a name-input gate", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("requested"),
    })).toMatchObject({
      phase: "requested",
      canConfirm: true,
      canCancel: true,
      impactExpired: false,
    });
  });

  it("fails closed when a frozen impact expires according to server time", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("requested"),
      elapsedSinceServerNowMs: 15 * 60_000,
    })).toMatchObject({
      impactExpired: true,
      canConfirm: false,
      canCancel: true,
      statusLabel: "冻结的删除影响已过期；请取消后重新查看最新影响。",
    });
  });

  it("uses authoritative cancellable/retryable/terminal flags for waiting and fenced failures", () => {
    const waiting = request("failed", {
      failureCode: "VOICE_DELETE_WAITING_FOR_JOBS",
      confirmedAt: null,
      cancellable: true,
      retryable: true,
      jobDrainStartedAt: "2026-08-29T10:00:00.000Z",
      jobDrainDeadline: "2026-08-29T10:01:00.000Z",
    });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: waiting,
      elapsedSinceServerNowMs: 10_000,
    })).toMatchObject({
      canCancel: true,
      canRetry: true,
      jobDrainRemainingSeconds: 50,
    });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("failed", { cancellable: false, retryable: true }),
    })).toMatchObject({ canCancel: false, canRetry: true, terminal: false });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("failed", {
        failureCode: "VOICE_DELETE_FILE_IDENTITY_INVALID",
        cancellable: false,
        retryable: false,
        terminal: true,
      }),
    })).toMatchObject({ canCancel: false, canRetry: false, terminal: true });
  });

  it("accepts superseded as a terminal drift result and releases client actions", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: { ...profile("referenced"), expectedProfileVersion: 5 },
      request: request("superseded", { failureCode: "VOICE_DELETE_PROFILE_CHANGED" }),
    })).toMatchObject({
      phase: "superseded",
      valid: true,
      terminal: true,
      canCancel: false,
      canRetry: false,
    });
  });

  it("fails closed on contradictory server action flags", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("completed", { cancellable: true }),
    })).toMatchObject({ phase: "invalid", valid: false, canCancel: false });
  });

  it("builds narrow commands without mutable impact data", () => {
    expect(voiceLifecycleProfileCommand(profile("unreferenced"))).toEqual({
      profileId: PROFILE_ID,
      expectedProfileVersion: 4,
    });
    expect(voiceLifecycleConfirmCommand(request("requested"))).toEqual({
      requestId: REQUEST_ID,
      expectedProfileVersion: 4,
      impactDigest: "a".repeat(64),
    });
  });

  it("describes unmanaged backups without claiming global permanent deletion", () => {
    expect(externalBackupStatusMessage("unmanaged")).toContain("不受本项目管理");
    expect(externalBackupStatusMessage("unmanaged")).not.toContain("永久删除");
    expect(formatVoiceLifecycleBytes(2_097_152)).toBe("2.0 MiB");
  });
});
