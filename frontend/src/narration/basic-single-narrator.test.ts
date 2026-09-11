import { describe, expect, it, vi } from "vitest";

import { prepareBasicSingleNarrator } from "./basic-single-narrator";
import type { ScriptReviewResource } from "./script-contracts";


const ids = {
  script: "11111111-1111-4111-8111-111111111111",
  version1: "22222222-2222-4222-8222-222222222221",
  version2: "22222222-2222-4222-8222-222222222222",
  version3: "22222222-2222-4222-8222-222222222223",
  novel: "33333333-3333-4333-8333-333333333333",
  document: "44444444-4444-4444-8444-444444444444",
  revision: "55555555-5555-4555-8555-555555555555",
  request: "66666666-6666-4666-8666-666666666666",
  segment1: "77777777-7777-4777-8777-777777777771",
  segment2: "77777777-7777-4777-8777-777777777772",
} as const;


function review(version = 1, remaining = [0, 1], approved = false): ScriptReviewResource {
  const versionIds = [ids.version1, ids.version2, ids.version3];
  const segmentIds = [ids.segment1, ids.segment2];
  const segments = segmentIds.map((segmentId, ordinal) => ({
    segment_id: segmentId,
    ordinal,
    segment_kind: "dialogue" as const,
    source_block_key: `block-${ordinal}`,
    source_start_utf16: ordinal * 10,
    source_end_utf16: ordinal * 10 + 5,
    source_text: `台词${ordinal + 1}`,
    spoken_text: `台词${ordinal + 1}`,
    local_hash: `${ordinal + 1}`.repeat(64),
    speaker_kind: remaining.includes(ordinal) ? "unknown" as const : "narrator" as const,
    speaker_label: remaining.includes(ordinal) ? "待确认说话人" : "旁白",
    character_id: null,
    anonymous_speaker_id: null,
    confidence: remaining.includes(ordinal) ? "unknown" as const : "high" as const,
    casting_state: remaining.includes(ordinal) ? "unresolved" as const : "resolved" as const,
    issue_codes: remaining.includes(ordinal)
      ? ["B_CASTING_TARGET_UNRESOLVED" as const, "B_VOICE_MISSING" as const]
      : [],
    editable: true,
  }));
  const issues = remaining.flatMap((ordinal) => [
    {
      taxonomy_version: "narration-review-taxonomy/1" as const,
      code: "B_CASTING_TARGET_UNRESOLVED" as const,
      severity: "blocker" as const,
      segment_id: segmentIds[ordinal] ?? null,
      evidence_summary: null,
      evidence_digest: null,
    },
    {
      taxonomy_version: "narration-review-taxonomy/1" as const,
      code: "B_VOICE_MISSING" as const,
      severity: "blocker" as const,
      segment_id: segmentIds[ordinal] ?? null,
      evidence_summary: null,
      evidence_digest: null,
    },
  ]);
  return {
    contract_version: "narration-script-review-api/1",
    taxonomy_version: "narration-review-taxonomy/1",
    script_id: ids.script,
    script_version_id: versionIds[version - 1] ?? ids.version3,
    novel_id: ids.novel,
    document_id: ids.document,
    revision_id: ids.revision,
    source_content_hash: "a".repeat(64),
    immutable_hash: `${version}`.repeat(64),
    version_number: version,
    state: approved ? "approved" : "review_required",
    effective_policy: "blockers_only",
    source_status: "current",
    warning_count: 0,
    blocker_count: issues.length,
    allowed_actions: approved ? [] : remaining.length ? ["edit_segment"] : ["approve"],
    segments,
    issues,
    approval: approved ? {
      kind: "manual_after_review",
      request_id: ids.request,
      actor_type: "owner",
      actor_id: "local-owner",
      approved_at: "2026-09-11T00:00:00Z",
    } : null,
  };
}


describe("basic single narrator", () => {
  it("converts every review-authorized casting blocker then approves with CAS", async () => {
    const patchSegment = vi.fn()
      .mockResolvedValueOnce(review(2, [1]))
      .mockResolvedValueOnce(review(3, []));
    const approve = vi.fn().mockResolvedValue(review(3, [], true));
    const progress = vi.fn();
    const result = await prepareBasicSingleNarrator({
      review: review(),
      requestId: ids.request,
      requestVersion: 4,
      dependencies: {
        patchSegment,
        approve,
        createIdempotencyKey: (prefix) => `${prefix}:action-0001`,
      },
      onProgress: progress,
    });
    expect(result.correctedSegmentCount).toBe(2);
    expect(result.requestVersion).toBe(7);
    expect(patchSegment).toHaveBeenCalledTimes(2);
    expect(patchSegment.mock.calls[0]?.[2]).toMatchObject({
      expected_request_version: 4,
      speaker_kind: "narrator",
      spoken_text: "台词1",
    });
    expect(patchSegment.mock.calls[1]?.[2]).toMatchObject({ expected_request_version: 5 });
    expect(approve.mock.calls[0]?.[1]).toMatchObject({ expected_request_version: 6, confirmed: true });
    expect(progress).toHaveBeenCalled();
    expect(result.approvedReview.state).toBe("approved");
  });

  it("fails closed for a non-speaker blocker", async () => {
    const blocked = review();
    const unsafe = {
      ...blocked,
      issues: [{
        ...blocked.issues[0]!,
        code: "B_PRONUNCIATION_HARD_CONFLICT" as const,
      }],
      blocker_count: 1,
    };
    await expect(prepareBasicSingleNarrator({
      review: unsafe,
      requestId: ids.request,
      requestVersion: 1,
      dependencies: {
        patchSegment: vi.fn(),
        approve: vi.fn(),
        createIdempotencyKey: () => "basic:test-0001",
      },
    })).rejects.toThrow("B_PRONUNCIATION_HARD_CONFLICT");
  });
});
