import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  approveNarrationScriptVersion,
  getNarrationScriptVersion,
  reanalyzeNarrationScriptSegments,
} from "./script-api";
import {
  NARRATION_REVIEW_TAXONOMY_VERSION,
  NARRATION_SCRIPT_REVIEW_API_VERSION,
  ScriptContractError,
  parseScriptReviewResource,
} from "./script-contracts";
import { buildScriptReviewPanelModel } from "./script-review-panel";


const SCRIPT_ID = "c1000000-0000-4000-8000-000000000001";
const VERSION_ID = "c1000000-0000-4000-8000-000000000002";
const NEXT_VERSION_ID = "c1000000-0000-4000-8000-000000000012";
const NOVEL_ID = "c1000000-0000-4000-8000-000000000003";
const DOCUMENT_ID = "c1000000-0000-4000-8000-000000000004";
const REVISION_ID = "c1000000-0000-4000-8000-000000000005";
const SEGMENT_ID = "c1000000-0000-4000-8000-000000000006";
const REQUEST_ID = "c1000000-0000-4000-8000-000000000007";
const CHARACTER_ID = "c1000000-0000-4000-8000-000000000008";
const SOURCE_HASH = "a".repeat(64);
const IMMUTABLE_HASH = "b".repeat(64);
const LOCAL_HASH = "c".repeat(64);
const SOURCE_BLOCK_KEY = `sb1_${"d".repeat(64)}`;

const VERSION_SCOPE = {
  novel_id: NOVEL_ID,
  document_id: DOCUMENT_ID,
  revision_id: REVISION_ID,
  source_content_hash: SOURCE_HASH,
  script_id: SCRIPT_ID,
  script_version_id: VERSION_ID,
} as const;


function segment(changes: Record<string, unknown> = {}) {
  return {
    segment_id: SEGMENT_ID,
    ordinal: 0,
    segment_kind: "dialogue",
    source_block_key: SOURCE_BLOCK_KEY,
    source_start_utf16: 0,
    source_end_utf16: 4,
    source_text: "“你好”",
    spoken_text: "你好",
    local_hash: LOCAL_HASH,
    speaker_kind: "character",
    speaker_label: "林晚",
    character_id: CHARACTER_ID,
    anonymous_speaker_id: null,
    confidence: "high",
    casting_state: "resolved",
    issue_codes: [],
    editable: true,
    ...changes,
  };
}


function reviewPayload(changes: Record<string, unknown> = {}) {
  return {
    contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
    taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
    script_id: SCRIPT_ID,
    script_version_id: VERSION_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    revision_id: REVISION_ID,
    source_content_hash: SOURCE_HASH,
    immutable_hash: IMMUTABLE_HASH,
    version_number: 1,
    state: "review_required",
    effective_policy: "always_review",
    source_status: "current",
    warning_count: 0,
    blocker_count: 0,
    allowed_actions: ["approve", "edit_segment", "reanalyze_segments"],
    segments: [segment()],
    issues: [],
    approval: null,
    ...changes,
  };
}


function blockerPayload() {
  return reviewPayload({
    effective_policy: "blockers_only",
    blocker_count: 3,
    allowed_actions: ["edit_segment", "reanalyze_segments"],
    segments: [segment({
      speaker_kind: "unknown",
      speaker_label: "待确认人物",
      character_id: null,
      confidence: "unknown",
      casting_state: "unresolved",
      issue_codes: [
        "B_CASTING_TARGET_UNRESOLVED",
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_SPEAKER_UNKNOWN",
      ],
    })],
    issues: [
      {
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code: "B_CASTING_TARGET_UNRESOLVED",
        severity: "blocker",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      },
      {
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code: "B_SPEAKER_LOW_CONFIDENCE",
        severity: "blocker",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      },
      {
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code: "B_SPEAKER_UNKNOWN",
        severity: "blocker",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      },
    ],
  });
}


function autoApprovedPayload() {
  return reviewPayload({
    state: "approved",
    effective_policy: "blockers_only",
    allowed_actions: [],
    approval: {
      kind: "auto_no_blockers",
      request_id: REQUEST_ID,
      actor_type: "service",
      actor_id: "narration-request-orchestrator",
      approved_at: "2026-08-26T16:00:00Z",
    },
  });
}


function manualApprovedPayload() {
  return reviewPayload({
    state: "approved",
    allowed_actions: [],
    approval: {
      kind: "manual_after_review",
      request_id: REQUEST_ID,
      actor_type: "owner",
      actor_id: "local-owner",
      approved_at: "2026-08-26T16:01:00Z",
    },
  });
}


function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();


beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("window", {
    QwenPaw: { host: { fetch: fetchMock } },
  });
});


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("T3-I script review integration", () => {
  it("keeps every blocker visible and disables the author approval boundary", () => {
    const review = parseScriptReviewResource(blockerPayload());
    const model = buildScriptReviewPanelModel({
      review,
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });

    expect(review.blocker_count).toBe(3);
    expect(model.visibleIssues.map((issue) => issue.code)).toEqual([
      "B_CASTING_TARGET_UNRESOLVED",
      "B_SPEAKER_LOW_CONFIDENCE",
      "B_SPEAKER_UNKNOWN",
    ]);
    expect(model.canApprove).toBe(false);
    expect(model.primaryLabel).toBe("仍有 3 个阻塞");
  });

  it("represents both review policies without turning automatic approval into a button", () => {
    const alwaysReview = parseScriptReviewResource(reviewPayload());
    const manualModel = buildScriptReviewPanelModel({
      review: alwaysReview,
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });
    const autoApproved = parseScriptReviewResource(autoApprovedPayload());
    const autoModel = buildScriptReviewPanelModel({
      review: autoApproved,
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });

    expect(alwaysReview.effective_policy).toBe("always_review");
    expect(manualModel.canApprove).toBe(true);
    expect(manualModel.primaryLabel).toBe("确认并冻结脚本");
    expect(autoApproved.effective_policy).toBe("blockers_only");
    expect(autoApproved.approval?.kind).toBe("auto_no_blockers");
    expect(autoModel.canApprove).toBe(false);
    expect(autoModel.primaryLabel).toBe("脚本已冻结");

    expect(() => parseScriptReviewResource(reviewPayload({
      state: "approved",
      effective_policy: "blockers_only",
      allowed_actions: [],
      approval: {
        kind: "auto_no_blockers",
        request_id: REQUEST_ID,
        actor_type: "owner",
        actor_id: "forged-owner",
        approved_at: "2026-08-26T16:00:00Z",
      },
    }))).toThrow(/system\/service/);
  });

  it("requires an explicit old-snapshot choice when the working copy diverged", () => {
    const review = parseScriptReviewResource(reviewPayload({
      source_status: "working_copy_diverged",
      allowed_actions: [
        "approve",
        "edit_segment",
        "reanalyze_segments",
        "continue_snapshot",
        "reanalyze_latest",
      ],
    }));

    expect(buildScriptReviewPanelModel({
      review,
      showAllIssues: false,
      snapshotConfirmed: false,
      busy: false,
    }).canApprove).toBe(false);
    expect(buildScriptReviewPanelModel({
      review,
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    }).canApprove).toBe(true);
  });

  it("sends owner confirmation with immutable guards and no client actor authority", async () => {
    const review = parseScriptReviewResource(reviewPayload());
    const model = buildScriptReviewPanelModel({
      review,
      showAllIssues: false,
      snapshotConfirmed: true,
      busy: false,
    });
    expect(model.canApprove).toBe(true);
    fetchMock.mockResolvedValue(response(manualApprovedPayload()));

    const approved = await approveNarrationScriptVersion(
      VERSION_ID,
      {
        request_id: REQUEST_ID,
        expected_request_version: 7,
        expected_version_number: review.version_number,
        expected_immutable_hash: review.immutable_hash,
        source_revision_id: review.revision_id,
        confirmed: true,
      },
      VERSION_SCOPE,
      "t3-i-approve-0001",
    );

    expect(approved.approval?.kind).toBe("manual_after_review");
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toEqual(expect.objectContaining({
      "Idempotency-Key": "t3-i-approve-0001",
    }));
    const body = JSON.parse(String(init?.body));
    expect(body).toEqual({
      request_id: REQUEST_ID,
      expected_request_version: 7,
      expected_version_number: 1,
      expected_immutable_hash: IMMUTABLE_HASH,
      source_revision_id: REVISION_ID,
      confirmed: true,
    });
    expect(body).not.toHaveProperty("actor_id");
    expect(body).not.toHaveProperty("owner_id");
    expect(body).not.toHaveProperty("workspace_id");
  });

  it("replays repeated reanalysis with byte-identical guards and idempotency key", async () => {
    const next = reviewPayload({
      script_version_id: NEXT_VERSION_ID,
      version_number: 2,
    });
    fetchMock.mockImplementation(async () => response(next));
    const payload = {
      request_id: REQUEST_ID,
      expected_request_version: 7,
      expected_version_number: 1,
      expected_immutable_hash: IMMUTABLE_HASH,
      segment_ids: [SEGMENT_ID],
    } as const;

    await reanalyzeNarrationScriptSegments(
      VERSION_ID,
      payload,
      VERSION_SCOPE,
      "t3-i-reanalyze-0001",
    );
    await reanalyzeNarrationScriptSegments(
      VERSION_ID,
      payload,
      VERSION_SCOPE,
      "t3-i-reanalyze-0001",
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const first = fetchMock.mock.calls[0];
    const second = fetchMock.mock.calls[1];
    expect(first[0]).toBe(second[0]);
    expect(first[1]?.body).toBe(second[1]?.body);
    expect(first[1]?.headers).toEqual(second[1]?.headers);
    expect(first[1]?.headers).toEqual(expect.objectContaining({
      "Idempotency-Key": "t3-i-reanalyze-0001",
    }));
  });

  it("rejects illegal version IDs before any PawApp host request", async () => {
    await expect(getNarrationScriptVersion("../other-workspace", VERSION_SCOPE))
      .rejects.toBeInstanceOf(ScriptContractError);
    await expect(getNarrationScriptVersion(
      "c1000000-0000-4000-0000-000000000002",
      VERSION_SCOPE,
    ))
      .rejects.toBeInstanceOf(ScriptContractError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
