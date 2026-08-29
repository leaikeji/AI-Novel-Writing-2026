import { describe, expect, it } from "vitest";

import {
  PRIVATE_VOICE_DELETION_CONTRACT_VERSION,
  PRIVATE_VOICE_DELETION_IMPACT_VERSION,
  deriveVoiceLifecycleState,
  externalBackupStatusMessage,
  formatVoiceLifecycleBytes,
  voiceLifecycleConfirmCommand,
  voiceLifecycleProfileCommand,
  voiceLifecycleUndoRemainingSeconds,
  type PrivateVoiceDeletionRequestState,
  type VoiceDeletionRequestSnapshot,
  type VoiceLifecycleProfile,
} from "./voice-lifecycle-state";


const PROFILE_ID = "10000000-0000-4000-8000-000000000001";
const NOVEL_ID = "20000000-0000-4000-8000-000000000001";
const REQUEST_ID = "30000000-0000-4000-8000-000000000001";
const NOW = Date.parse("2026-08-29T10:00:00.000Z");


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
  const command = state === "grace_pending"
    ? "discard_unreferenced_private_voice" as const
    : "true_delete_private_voice" as const;
  return Object.freeze({
    contractVersion: PRIVATE_VOICE_DELETION_CONTRACT_VERSION,
    requestId: REQUEST_ID,
    profileId: PROFILE_ID,
    novelId: NOVEL_ID,
    command,
    state,
    expectedProfileVersion: 4,
    impactDigest: "a".repeat(64),
    impact: Object.freeze({
      schemaVersion: PRIVATE_VOICE_DELETION_IMPACT_VERSION,
      profileId: PROFILE_ID,
      novelId: NOVEL_ID,
      profileVersion: 4,
      voiceVersionCount: 2,
      currentNarratorCount: 1,
      characterBindingCount: 2,
      anonymousSpeakerCount: 1,
      genericSlotCount: 1,
      historicalEditionCount: 3,
      renderCount: 8,
      exportCount: 1,
      assetCount: 5,
      totalBytes: 2_097_152,
      activeJobCount: 0,
      externalBackupStatus: "unmanaged",
      historicalAudioConsequence: "unavailable_private_voice_deleted",
    }),
    executeAfter: state === "grace_pending" ? "2026-08-29T10:00:30.000Z" : null,
    impactExpiresAt: "2026-08-29T10:15:00.000Z",
    assetCount: 5,
    totalBytes: 2_097_152,
    externalBackupStatus: "unmanaged",
    confirmedAt: ["live_deleting", "live_deleted_backup_pending", "completed", "failed"].includes(state)
      ? "2026-08-29T10:00:31.000Z"
      : null,
    cancelledAt: state === "cancelled" ? "2026-08-29T10:00:05.000Z" : null,
    completedAt: state === "completed" ? "2026-08-29T10:00:35.000Z" : null,
    failureCode: state === "failed" ? "VOICE_DELETE_IO_FAILED" : null,
    ...patch,
  });
}


describe("voice lifecycle state", () => {
  it("fails closed and exposes no action when capability is absent by default", () => {
    const state = deriveVoiceLifecycleState({
      profile: profile("unreferenced"),
      nowEpochMs: NOW,
    });
    expect(state).toMatchObject({
      phase: "hidden",
      visible: false,
      canDiscardUnreferenced: false,
      canRequestReferencedDeletion: false,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
    });
  });

  it("separates one-click unreferenced deletion from referenced impact review", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("unreferenced"),
      nowEpochMs: NOW,
    })).toMatchObject({
      phase: "idle-unreferenced",
      canDiscardUnreferenced: true,
      canRequestReferencedDeletion: false,
    });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      nowEpochMs: NOW,
    })).toMatchObject({
      phase: "idle-referenced",
      canDiscardUnreferenced: false,
      canRequestReferencedDeletion: true,
    });
  });

  it("uses the server deadline for a 30-second undo window and closes it exactly at expiry", () => {
    expect(voiceLifecycleUndoRemainingSeconds(
      "2026-08-29T10:00:30.000Z",
      NOW,
    )).toBe(30);
    const pending = request("grace_pending");
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("unreferenced"),
      request: pending,
      nowEpochMs: NOW + 15_001,
    })).toMatchObject({
      phase: "grace_pending",
      undoRemainingSeconds: 15,
      canCancel: true,
    });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("unreferenced"),
      request: pending,
      nowEpochMs: NOW + 30_000,
    })).toMatchObject({
      undoRemainingSeconds: 0,
      canCancel: false,
      statusLabel: "撤销时间已结束，正在等待进入删除阶段。",
    });
  });

  it("requires an exact voice-name match before confirming a referenced request", () => {
    const pending = request("requested");
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: pending,
      nowEpochMs: NOW,
      confirmationText: "林晚",
    })).toMatchObject({ phase: "requested", canConfirm: false, canCancel: true });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: pending,
      nowEpochMs: NOW,
      confirmationText: "林晚的雨夜声线",
    })).toMatchObject({ confirmationMatches: true, canConfirm: true, canCancel: true });
  });

  it("fails closed when the frozen referenced impact expires", () => {
    const pending = request("requested");
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: pending,
      nowEpochMs: Date.parse("2026-08-29T10:15:00.000Z"),
      confirmationText: "林晚的雨夜声线",
    })).toMatchObject({
      phase: "requested",
      impactExpired: true,
      canConfirm: false,
      canCancel: true,
      statusLabel: "冻结的删除影响已过期；请取消后重新查看最新影响。",
    });
  });

  it("does not offer cancellation after physical deletion starts and only retries confirmed failures", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("live_deleting"),
      nowEpochMs: NOW,
    })).toMatchObject({ phase: "live_deleting", canCancel: false, canRetry: false });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("failed"),
      nowEpochMs: NOW,
    })).toMatchObject({ phase: "failed", canRetry: true, canCancel: false });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: request("failed", { confirmedAt: null }),
      nowEpochMs: NOW,
    }).canRetry).toBe(false);
  });

  it("keeps post-fence states valid when the service advances the current profile version", () => {
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: { ...profile("referenced"), expectedProfileVersion: 5 },
      request: request("completed"),
      nowEpochMs: NOW,
    })).toMatchObject({ phase: "completed", valid: true });
  });

  it("fails closed on request/profile drift instead of dispatching a stale destructive action", () => {
    const mismatched = request("requested", {
      profileId: "90000000-0000-4000-8000-000000000009",
    });
    expect(deriveVoiceLifecycleState({
      capabilityEnabled: true,
      profile: profile("referenced"),
      request: mismatched,
      nowEpochMs: NOW,
      confirmationText: "林晚的雨夜声线",
    })).toMatchObject({
      phase: "invalid",
      valid: false,
      canConfirm: false,
      canCancel: false,
      canRetry: false,
    });
  });

  it("builds narrow CAS commands without mutable impact data", () => {
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
    const message = externalBackupStatusMessage("unmanaged");
    expect(message).toContain("不受本项目管理");
    expect(message).not.toContain("永久删除");
    expect(formatVoiceLifecycleBytes(2_097_152)).toBe("2.0 MiB");
  });
});
