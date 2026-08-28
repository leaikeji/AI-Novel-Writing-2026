import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api";
import {
  ScriptApiError,
  analyzeNarrationScript,
  approveNarrationScriptVersion,
  getNarrationScript,
  getNarrationScriptVersion,
  getNarrationScriptVersionForEdition,
  patchNarrationScriptSegment,
  reanalyzeNarrationScriptSegments,
} from "./script-api";
import {
  NARRATION_REVIEW_TAXONOMY_VERSION,
  NARRATION_SCRIPT_REVIEW_API_VERSION,
  ScriptContractError,
  parseScriptReviewResource,
} from "./script-contracts";


const SCRIPT_ID = "b1000000-0000-4000-8000-000000000001";
const VERSION_ID = "b1000000-0000-4000-8000-000000000002";
const NEXT_VERSION_ID = "b1000000-0000-4000-8000-000000000012";
const NOVEL_ID = "b1000000-0000-4000-8000-000000000003";
const DOCUMENT_ID = "b1000000-0000-4000-8000-000000000004";
const REVISION_ID = "b1000000-0000-4000-8000-000000000005";
const SEGMENT_ID = "b1000000-0000-4000-8000-000000000006";
const REQUEST_ID = "b1000000-0000-4000-8000-000000000007";
const CHARACTER_ID = "b1000000-0000-4000-8000-000000000008";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);
const SOURCE_BLOCK_KEY = `sb1_${"d".repeat(64)}`;

const DOCUMENT_SCOPE = {
  novel_id: NOVEL_ID,
  document_id: DOCUMENT_ID,
  revision_id: REVISION_ID,
  source_content_hash: SHA_A,
} as const;

const SCRIPT_SCOPE = {
  ...DOCUMENT_SCOPE,
  script_id: SCRIPT_ID,
} as const;

const VERSION_SCOPE = {
  ...SCRIPT_SCOPE,
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
    local_hash: SHA_C,
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


function resource(changes: Record<string, unknown> = {}) {
  return {
    contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
    taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
    script_id: SCRIPT_ID,
    script_version_id: VERSION_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    revision_id: REVISION_ID,
    source_content_hash: SHA_A,
    immutable_hash: SHA_B,
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


describe("script review wire contract", () => {
  it("parses a zero-blocker review resource and freezes returned collections", () => {
    const parsed = parseScriptReviewResource(resource());
    expect(parsed.blocker_count).toBe(0);
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.segments)).toBe(true);
  });

  it("rejects extra fields, count drift, spoofed severity and unknown without blocker", () => {
    expect(() => parseScriptReviewResource(resource({ extra: true }))).toThrow(/unexpected or missing/);
    expect(() => parseScriptReviewResource(resource({ warning_count: 1 }))).toThrow(/counts differ/);
    expect(() => parseScriptReviewResource(resource({
      warning_count: 1,
      issues: [{
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code: "B_VOICE_MISSING",
        severity: "warning",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      }],
    }))).toThrow(/server-owned severity/);
    expect(() => parseScriptReviewResource(resource({
      segments: [segment({ speaker_kind: "unknown", character_id: null })],
    }))).toThrow(/B_SPEAKER_UNKNOWN/);
    expect(() => parseScriptReviewResource(resource({
      segments: [segment({ confidence: "medium" })],
    }))).toThrow(/medium confidence/);
    expect(() => parseScriptReviewResource(resource({
      source_status: "superseded",
    }))).toThrow(/superseded script/);
  });

  it("accepts the complete frozen state vocabulary for a non-materialized draft", () => {
    const parsed = parseScriptReviewResource(resource({
      state: "draft",
      effective_policy: "blockers_only",
      allowed_actions: [],
      segments: [],
    }));
    expect(parsed.state).toBe("draft");
  });

  it("accepts unknown speaker only with both required blocker rows and matching counts", () => {
    const parsed = parseScriptReviewResource(resource({
      effective_policy: "blockers_only",
      blocker_count: 2,
      allowed_actions: ["edit_segment", "reanalyze_segments"],
      segments: [segment({
        speaker_kind: "unknown",
        speaker_label: "待确认人物",
        character_id: null,
        confidence: "unknown",
        issue_codes: ["B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"],
      })],
      issues: ["B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"].map((code) => ({
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code,
        severity: "blocker",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      })),
    }));
    expect(parsed.blocker_count).toBe(2);
    expect(() => parseScriptReviewResource(resource({
      blocker_count: 1,
      allowed_actions: ["edit_segment", "reanalyze_segments"],
      segments: [segment({
        speaker_kind: "unknown",
        speaker_label: "待确认人物",
        character_id: null,
        confidence: "unknown",
        issue_codes: ["B_SPEAKER_UNKNOWN"],
      })],
      issues: [{
        taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
        code: "B_SPEAKER_UNKNOWN",
        severity: "blocker",
        segment_id: SEGMENT_ID,
        evidence_summary: null,
        evidence_digest: null,
      }],
    }))).toThrow(/B_SPEAKER_LOW_CONFIDENCE/);
  });

  it("requires both explicit choices when the working copy diverged", () => {
    expect(() => parseScriptReviewResource(resource({
      source_status: "working_copy_diverged",
      allowed_actions: ["approve", "reanalyze_latest"],
    }))).toThrow(/both snapshot choices/);
  });

  it("preserves authoritative source whitespace and enforces the current action matrix", () => {
    const parsed = parseScriptReviewResource(resource({
      segments: [segment({ source_text: "  “你好”\n", spoken_text: "  你好  " })],
    }));
    expect(parsed.segments[0].source_text).toBe("  “你好”\n");
    expect(parsed.segments[0].spoken_text).toBe("  你好  ");
    expect(() => parseScriptReviewResource(resource({
      allowed_actions: ["approve", "continue_snapshot"],
    }))).toThrow(/current source/);
    expect(parseScriptReviewResource(resource({
      state: "approved",
      source_status: "working_copy_diverged",
      allowed_actions: [],
      approval: {
        kind: "manual_after_review",
        request_id: REQUEST_ID,
        actor_type: "owner",
        actor_id: "local-owner",
        approved_at: "2026-08-26T12:00:00Z",
      },
    })).allowed_actions).toEqual([]);
  });
});


describe("script review API client", () => {
  it("uses the PawApp namespace, exact version path, and validates JSON", async () => {
    fetchMock.mockResolvedValue(response(resource()));

    const result = await getNarrationScriptVersion(VERSION_ID, VERSION_SCOPE);

    expect(result.script_version_id).toBe(VERSION_ID);
    expect(fetchMock).toHaveBeenCalledWith(
      `/ai-novel-world-2026/narration-script-versions/${VERSION_ID}`,
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("rejects a valid-looking response from another version scope", async () => {
    fetchMock.mockResolvedValue(response(resource({
      script_version_id: "c1000000-0000-4000-8000-000000000002",
    })));

    await expect(getNarrationScriptVersion(VERSION_ID, VERSION_SCOPE)).rejects.toThrow(/scope mismatch/);
  });

  it("loads an Edition-owned ScriptVersion without trusting or pre-knowing script_id", async () => {
    fetchMock.mockResolvedValue(response(resource()));

    const result = await getNarrationScriptVersionForEdition(
      VERSION_ID,
      DOCUMENT_SCOPE,
    );

    expect(result.script_id).toBe(SCRIPT_ID);
    expect(result.script_version_id).toBe(VERSION_ID);
    expect(fetchMock).toHaveBeenCalledWith(
      `/ai-novel-world-2026/narration-script-versions/${VERSION_ID}`,
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it.each([
    ["novel_id", "c1000000-0000-4000-8000-000000000003"],
    ["document_id", "c1000000-0000-4000-8000-000000000004"],
    ["revision_id", "c1000000-0000-4000-8000-000000000005"],
    ["source_content_hash", "e".repeat(64)],
    ["script_version_id", "c1000000-0000-4000-8000-000000000002"],
  ])("rejects Edition ScriptVersion cross-scope drift in %s", async (field, value) => {
    fetchMock.mockResolvedValue(response(resource({ [field]: value })));

    await expect(getNarrationScriptVersionForEdition(
      VERSION_ID,
      DOCUMENT_SCOPE,
    )).rejects.toThrow(/scope mismatch/u);
  });

  it("keeps malformed server errors as generic ApiError", async () => {
    fetchMock.mockResolvedValue(response({ detail: "legacy" }, 500));
    await expect(getNarrationScriptVersion(VERSION_ID, VERSION_SCOPE)).rejects.toBeInstanceOf(ApiError);
  });

  it("turns only a strict script failure into ScriptApiError", async () => {
    fetchMock.mockResolvedValue(response({
      detail: {
        contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
        code: "STALE_INPUT",
        message: "正文快照已经变化。",
        retryable: false,
        field: null,
        current_version: 2,
      },
    }, 409));

    await expect(getNarrationScriptVersion(VERSION_ID, VERSION_SCOPE)).rejects.toMatchObject({
      status: 409,
      detail: { code: "STALE_INPUT", current_version: 2 },
    });
    await expect(Promise.reject(new ScriptApiError(409, {
      contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
      code: "STALE_INPUT",
      message: "stale",
      retryable: false,
      field: null,
      current_version: 2,
    }))).rejects.toBeInstanceOf(ScriptApiError);
  });

  it("sends explicit approval evidence without client actor or scope fields", async () => {
    fetchMock.mockResolvedValue(response(resource({
      state: "approved",
      allowed_actions: [],
      approval: {
        kind: "manual_after_review",
        request_id: REQUEST_ID,
        actor_type: "owner",
        actor_id: "local-owner",
        approved_at: "2026-08-26T12:00:00Z",
      },
    })));

    await approveNarrationScriptVersion(
      VERSION_ID,
      {
        request_id: REQUEST_ID,
        expected_request_version: 5,
        expected_version_number: 1,
        expected_immutable_hash: SHA_B,
        source_revision_id: REVISION_ID,
        confirmed: true,
      },
      VERSION_SCOPE,
      "script-approve-0001",
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.headers).toEqual(expect.objectContaining({
      "Idempotency-Key": "script-approve-0001",
    }));
    const body = JSON.parse(String(init?.body));
    expect(body.confirmed).toBe(true);
    expect(body).not.toHaveProperty("actor_id");
    expect(body).not.toHaveProperty("owner_id");
    expect(body).not.toHaveProperty("workspace_id");
  });

  it("validates analyze scope and rejects unsafe ids or idempotency keys", async () => {
    fetchMock.mockResolvedValue(response(resource()));
    await expect(analyzeNarrationScript(
      DOCUMENT_ID,
      {
        request_id: REQUEST_ID,
        source_revision_id: REVISION_ID,
        source_content_hash: SHA_A,
      },
      DOCUMENT_SCOPE,
      "script-analyze-0001",
    )).resolves.toMatchObject({ document_id: DOCUMENT_ID });

    await expect(getNarrationScriptVersion("../escape", VERSION_SCOPE)).rejects.toBeInstanceOf(ScriptContractError);
    await expect(analyzeNarrationScript(
      DOCUMENT_ID,
      {
        request_id: REQUEST_ID,
        source_revision_id: REVISION_ID,
        source_content_hash: SHA_A,
      },
      DOCUMENT_SCOPE,
      "short",
    )).rejects.toThrow(/idempotency_key/);
  });

  it("sends segment correction and bounded reanalysis to their exact endpoints", async () => {
    fetchMock.mockResolvedValue(response(resource({
      script_version_id: NEXT_VERSION_ID,
      version_number: 2,
    })));
    await patchNarrationScriptSegment(
      VERSION_ID,
      SEGMENT_ID,
      {
        expected_request_version: 5,
        expected_version_number: 1,
        expected_immutable_hash: SHA_B,
        expected_local_hash: SHA_C,
        request_id: REQUEST_ID,
        speaker_kind: "character",
        speaker_label: "林晚",
        character_id: CHARACTER_ID,
        anonymous_speaker_id: null,
        group_key: null,
        spoken_text: "你好",
        reason: "作者确认人物卡映射",
      },
      VERSION_SCOPE,
      "script-patch-0001",
    );
    expect(fetchMock.mock.calls[0][0]).toContain(`/segments/${SEGMENT_ID}`);
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PATCH");
    const patchBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(patchBody).toMatchObject({
      expected_request_version: 5,
      request_id: REQUEST_ID,
      speaker_kind: "character",
      character_id: CHARACTER_ID,
      anonymous_speaker_id: null,
      group_key: null,
    });
    expect(patchBody).not.toHaveProperty("profile_id");
    expect(patchBody).not.toHaveProperty("voice_version_id");
    expect(patchBody).not.toHaveProperty("binding_id");
    expect(patchBody).not.toHaveProperty("casting");

    fetchMock.mockResolvedValue(response(resource({
      script_version_id: NEXT_VERSION_ID,
      version_number: 2,
    })));
    await reanalyzeNarrationScriptSegments(
      VERSION_ID,
      {
        request_id: REQUEST_ID,
        expected_request_version: 5,
        expected_version_number: 1,
        expected_immutable_hash: SHA_B,
        segment_ids: [SEGMENT_ID],
      },
      VERSION_SCOPE,
      "script-reanalyze-0001",
    );
    expect(fetchMock.mock.calls[1][0]).toContain("/reanalyze-segments");
  });

  it("rejects cross-scope responses for every read and write operation", async () => {
    const otherId = "d1000000-0000-4000-8000-000000000099";
    const otherHash = "e".repeat(64);

    fetchMock.mockResolvedValueOnce(response(resource({ novel_id: otherId })));
    await expect(analyzeNarrationScript(
      DOCUMENT_ID,
      {
        request_id: REQUEST_ID,
        source_revision_id: REVISION_ID,
        source_content_hash: SHA_A,
      },
      DOCUMENT_SCOPE,
      "script-analyze-cross-scope",
    )).rejects.toThrow(/scope mismatch/);

    fetchMock.mockResolvedValueOnce(response(resource({ document_id: otherId })));
    await expect(getNarrationScript(SCRIPT_ID, SCRIPT_SCOPE)).rejects.toThrow(/scope mismatch/);

    fetchMock.mockResolvedValueOnce(response(resource({ revision_id: otherId })));
    await expect(getNarrationScriptVersion(VERSION_ID, VERSION_SCOPE)).rejects.toThrow(/scope mismatch/);

    fetchMock.mockResolvedValueOnce(response(resource({
      state: "approved",
      allowed_actions: [],
      source_content_hash: otherHash,
      approval: {
        kind: "manual_after_review",
        request_id: REQUEST_ID,
        actor_type: "owner",
        actor_id: "local-owner",
        approved_at: "2026-08-26T12:00:00Z",
      },
    })));
    await expect(approveNarrationScriptVersion(
      VERSION_ID,
      {
        request_id: REQUEST_ID,
        expected_request_version: 5,
        expected_version_number: 1,
        expected_immutable_hash: SHA_B,
        source_revision_id: REVISION_ID,
        confirmed: true,
      },
      VERSION_SCOPE,
      "script-approve-cross-scope",
    )).rejects.toThrow(/scope mismatch/);

    const patch = {
      expected_request_version: 5,
      expected_version_number: 1,
      expected_immutable_hash: SHA_B,
      expected_local_hash: SHA_C,
      request_id: REQUEST_ID,
      speaker_kind: "character" as const,
      speaker_label: "林晚",
      character_id: CHARACTER_ID,
      anonymous_speaker_id: null,
      group_key: null,
      spoken_text: "你好",
      reason: "作者确认人物卡映射",
    };
    fetchMock.mockResolvedValueOnce(response(resource({
      script_version_id: NEXT_VERSION_ID,
      version_number: 2,
      novel_id: otherId,
    })));
    await expect(patchNarrationScriptSegment(
      VERSION_ID,
      SEGMENT_ID,
      patch,
      VERSION_SCOPE,
      "script-patch-cross-scope",
    )).rejects.toThrow(/scope mismatch/);

    fetchMock.mockResolvedValueOnce(response(resource({
      script_version_id: NEXT_VERSION_ID,
      version_number: 2,
      revision_id: otherId,
    })));
    await expect(reanalyzeNarrationScriptSegments(
      VERSION_ID,
      {
        request_id: REQUEST_ID,
        expected_request_version: 5,
        expected_version_number: 1,
        expected_immutable_hash: SHA_B,
        segment_ids: [SEGMENT_ID],
      },
      VERSION_SCOPE,
      "script-reanalyze-cross-scope",
    )).rejects.toThrow(/scope mismatch/);
  });
});
