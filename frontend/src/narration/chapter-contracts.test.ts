import { describe, expect, it } from "vitest";

import {
  ChapterNarrationContractError,
  DOCUMENT_NARRATION_CONTEXT_VERSION,
  FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
  NARRATION_PRODUCTION_API_VERSION,
  parseCreateNarrationWorkflowRequest,
  parseDocumentNarrationContext,
  parseFailedNarrationSegmentsProjection,
  parseNarrationEditionResource,
  parseNarrationEditionVoiceIdentitiesResource,
  parseNarrationWorkflowResource,
  parseRetryFailedNarrationSegmentsRequest,
  parseRetryFailedNarrationSegmentsResponse,
  parseSwitchNarrationEditionRequest,
  parseSwitchNarrationEditionResponse,
} from "./chapter-contracts";
import { EDITION_HISTORY_CONTRACT_VERSION } from "./edition-history";


const DOCUMENT_ID = "e1000000-0000-4000-8000-000000000001";
const NOVEL_ID = "e1000000-0000-4000-8000-000000000002";
const CURRENT_EDITION_ID = "e1000000-0000-4000-8000-000000000003";
const HISTORICAL_EDITION_ID = "e1000000-0000-4000-8000-000000000004";
const REQUEST_ID = "e1000000-0000-4000-8000-000000000005";
const HISTORICAL_REQUEST_ID = "e1000000-0000-4000-8000-000000000006";
const REVISION_ID = "e1000000-0000-4000-8000-000000000007";
const HISTORICAL_REVISION_ID = "e1000000-0000-4000-8000-000000000008";
const SCRIPT_VERSION_ID = "e1000000-0000-4000-8000-000000000009";
const JOB_ID = "e1000000-0000-4000-8000-000000000010";
const START_SEGMENT_ID = "e1000000-0000-4000-8000-000000000011";
const PROGRESS_ID = "e1000000-0000-4000-8000-000000000012";
const FAILED_SEGMENT_ID = "e1000000-0000-4000-8000-000000000013";
const FANOUT_SEGMENT_ID = "e1000000-0000-4000-8000-000000000014";
const RETRY_COMMAND_ID = "e1000000-0000-4000-8000-000000000015";
const PROFILE_ID = "e1000000-0000-4000-8000-000000000016";
const VOICE_VERSION_ID = "e1000000-0000-4000-8000-000000000017";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_C = "c".repeat(64);


function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}


function editionVoiceIdentities(changes: Record<string, unknown> = {}) {
  return {
    contract_version: "narration-edition-voice-identities/1",
    edition_id: CURRENT_EDITION_ID,
    items: [{
      profile_id: PROFILE_ID,
      voice_version_id: VOICE_VERSION_ID,
      display_name: "小雨",
      source_type: "preset",
      preset_id: "onnx.Xiaoyu",
      resolution_contract_version: "narration-edition-resolution/2",
      legacy_fallback: false,
    }],
    ...changes,
  };
}


function historyItem(changes: Record<string, unknown> = {}) {
  return {
    edition_id: CURRENT_EDITION_ID,
    request_id: REQUEST_ID,
    source_revision_id: REVISION_ID,
    source_content_hash: SHA_B,
    edition_fingerprint: SHA_B,
    state: "ready",
    created_at: "2026-08-27T12:00:00Z",
    manifest_revision: 6,
    manifest_etag: `"${SHA_B}"`,
    ready_segment_count: 3,
    total_segment_count: 3,
    is_current: true,
    source_status: "working_copy_diverged",
    rights_available: true,
    playable: true,
    default_start_ready: true,
    resume_available: false,
    switch_allowed: false,
    ...changes,
  };
}


function documentContext(changes: Record<string, unknown> = {}) {
  return {
    contract_version: DOCUMENT_NARRATION_CONTEXT_VERSION,
    document_id: DOCUMENT_ID,
    novel_id: NOVEL_ID,
    pointer_version: 4,
    current_script_version_id: SCRIPT_VERSION_ID,
    current_edition_id: CURRENT_EDITION_ID,
    active_edition_id: HISTORICAL_EDITION_ID,
    active_is_current: false,
    working_copy_draft_version: 7,
    working_copy_content_hash: SHA_A,
    source_snapshot: {
      revision_id: HISTORICAL_REVISION_ID,
      content_hash: SHA_A,
      matches_working_copy: true,
    },
    compatibility: "superseded",
    source_notice_code: "HISTORICAL_EDITION",
    editor_timeline_mode: "exact_working_copy",
    old_draft_subtitle_required: false,
    explicit_update_required: true,
    can_request_update: true,
    available_current_source_edition_ids: [HISTORICAL_EDITION_ID],
    edition_history: {
      contract_version: EDITION_HISTORY_CONTRACT_VERSION,
      document_id: DOCUMENT_ID,
      pointer_version: 4,
      current_edition_id: CURRENT_EDITION_ID,
      working_copy_content_hash: SHA_A,
      working_copy_draft_version: 7,
      editions: [
        historyItem(),
        historyItem({
          edition_id: HISTORICAL_EDITION_ID,
          request_id: HISTORICAL_REQUEST_ID,
          source_revision_id: HISTORICAL_REVISION_ID,
          source_content_hash: SHA_A,
          edition_fingerprint: SHA_C,
          manifest_revision: 7,
          manifest_etag: `"${SHA_C}"`,
          ready_segment_count: 4,
          total_segment_count: 4,
          is_current: false,
          source_status: "superseded",
          resume_available: true,
          switch_allowed: true,
        }),
      ],
    },
    ...changes,
  };
}


function workflow(changes: Record<string, unknown> = {}) {
  return {
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    request_id: REQUEST_ID,
    intent: "create",
    request_version: 4,
    workflow_state: "queued",
    source_revision_id: REVISION_ID,
    source_content_hash: SHA_A,
    settings_fingerprint: SHA_B,
    warning_count: 0,
    blocker_count: 0,
    script_version_id: SCRIPT_VERSION_ID,
    edition_id: CURRENT_EDITION_ID,
    current_manifest_revision: null,
    job_ids: [JOB_ID],
    replayed: false,
    ...changes,
  };
}


function edition(changes: Record<string, unknown> = {}) {
  return {
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    edition_id: CURRENT_EDITION_ID,
    request_id: REQUEST_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    script_version_id: SCRIPT_VERSION_ID,
    settings_fingerprint: SHA_B,
    edition_fingerprint: SHA_C,
    state: "rendering",
    segment_count: 3,
    pending_segment_count: 0,
    queued_segment_count: 2,
    rendering_segment_count: 1,
    ready_segment_count: 0,
    failed_segment_count: 0,
    current_manifest_revision: null,
    job_ids: [JOB_ID],
    ...changes,
  };
}


function switchRequest(changes: Record<string, unknown> = {}) {
  return {
    target_edition_id: HISTORICAL_EDITION_ID,
    expected_version: 4,
    switch_mode: "immediate",
    start_segment_id: START_SEGMENT_ID,
    playback_rate_millis: 1000,
    confirmed: true,
    ...changes,
  };
}


function switchResponse(changes: Record<string, unknown> = {}) {
  return {
    contract_version: DOCUMENT_NARRATION_CONTEXT_VERSION,
    document_id: DOCUMENT_ID,
    current_edition_id: HISTORICAL_EDITION_ID,
    pointer_version: 5,
    switch_mode: "immediate",
    start_segment_id: START_SEGMENT_ID,
    manifest_revision: 7,
    playback_progress_id: PROGRESS_ID,
    ...changes,
  };
}


function failedSegments(changes: Record<string, unknown> = {}) {
  return {
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: CURRENT_EDITION_ID,
    request_id: REQUEST_ID,
    request_version: 4,
    manifest_revision: 7,
    request_state: "partial_ready",
    edition_state: "partial_ready",
    items: [{
      segment_id: FAILED_SEGMENT_ID,
      ordinal: 1,
      failure_code: "LEASE_EXPIRED",
      retryable: true,
      retry_reason_code: null,
      job_id: JOB_ID,
      fanout_segment_ids: [FAILED_SEGMENT_ID, FANOUT_SEGMENT_ID],
    }],
    ...changes,
  };
}


function retryRequest(changes: Record<string, unknown> = {}) {
  return {
    segment_ids: [FAILED_SEGMENT_ID],
    expected_request_version: 4,
    expected_manifest_revision: 7,
    ...changes,
  };
}


function retryResponse(changes: Record<string, unknown> = {}) {
  return {
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: CURRENT_EDITION_ID,
    request_id: REQUEST_ID,
    accepted_segment_ids: [FAILED_SEGMENT_ID],
    affected_segment_ids: [FAILED_SEGMENT_ID, FANOUT_SEGMENT_ID],
    commands: [{
      command_id: RETRY_COMMAND_ID,
      job_id: JOB_ID,
      affected_segment_ids: [FAILED_SEGMENT_ID, FANOUT_SEGMENT_ID],
    }],
    request_version: 5,
    request_state: "rendering",
    edition_state: "rendering",
    replayed: false,
    ...changes,
  };
}


describe("chapter narration production wire contracts", () => {
  it("strictly parses and freezes Workflow and Edition resources", () => {
    const parsedWorkflow = parseNarrationWorkflowResource(workflow());
    const parsedEdition = parseNarrationEditionResource(edition());

    expect(parsedWorkflow.request_id).toBe(REQUEST_ID);
    expect(parsedEdition.document_id).toBe(DOCUMENT_ID);
    expect(Object.isFrozen(parsedWorkflow)).toBe(true);
    expect(Object.isFrozen(parsedWorkflow.job_ids)).toBe(true);
    expect(Object.isFrozen(parsedEdition)).toBe(true);
    expect(Object.isFrozen(parsedEdition.job_ids)).toBe(true);
  });

  it("parses frozen Edition voice identity and a truthful legacy fallback", () => {
    const current = parseNarrationEditionVoiceIdentitiesResource(editionVoiceIdentities());
    expect(current.items[0]?.display_name).toBe("小雨");
    expect(Object.isFrozen(current.items)).toBe(true);

    const legacy = parseNarrationEditionVoiceIdentitiesResource(editionVoiceIdentities({
      items: [{
        profile_id: PROFILE_ID,
        voice_version_id: VOICE_VERSION_ID,
        display_name: "旧版未保存名称",
        source_type: null,
        preset_id: null,
        resolution_contract_version: "narration-edition-resolution/1",
        legacy_fallback: true,
      }],
    }));
    expect(legacy.items[0]?.legacy_fallback).toBe(true);
    expect(() => parseNarrationEditionVoiceIdentitiesResource(editionVoiceIdentities({
      items: [{
        ...legacy.items[0],
        display_name: "现在的可变名称",
      }],
    }))).toThrow(/legacy voice identity shape/u);
  });

  it.each([
    [parseNarrationWorkflowResource, workflow()],
    [parseNarrationEditionResource, edition()],
    [parseDocumentNarrationContext, documentContext()],
    [parseSwitchNarrationEditionResponse, switchResponse()],
  ] as const)("rejects missing and extra response fields", (parser, fixture) => {
    const missing = clone(fixture) as Record<string, unknown>;
    delete missing.contract_version;
    expect(() => parser(missing)).toThrow(/unexpected or missing fields/u);
    expect(() => parser({ ...fixture, private_path: "/secret" })).toThrow(
      /unexpected or missing fields/u,
    );
  });

  it("enforces Workflow production separation and Edition count integrity", () => {
    expect(() => parseNarrationWorkflowResource(workflow({
      intent: "analyze_only",
      workflow_state: "analyzed",
    }))).toThrow(/analyze_only/u);
    expect(() => parseNarrationWorkflowResource(workflow({
      job_ids: [JOB_ID, JOB_ID],
    }))).toThrow(/unique/u);
    expect(() => parseNarrationEditionResource(edition({
      ready_segment_count: 3,
    }))).toThrow(/segment-state counts/u);
  });

  it("reuses strict Edition history and verifies every outer/nested source relation", () => {
    const parsed = parseDocumentNarrationContext(documentContext());
    expect(parsed.active_edition_id).toBe(HISTORICAL_EDITION_ID);
    expect(parsed.edition_history.editions).toHaveLength(2);
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.available_current_source_edition_ids)).toBe(true);
    expect(Object.isFrozen(parsed.source_snapshot)).toBe(true);

    const nestedPointer = clone(documentContext());
    nestedPointer.edition_history.pointer_version = 5;
    expect(() => parseDocumentNarrationContext(nestedPointer)).toThrow(/outer document state/u);

    expect(() => parseDocumentNarrationContext(documentContext({
      source_snapshot: {
        revision_id: HISTORICAL_REVISION_ID,
        content_hash: SHA_B,
        matches_working_copy: true,
      },
    }))).toThrow(/active Edition source/u);
    expect(() => parseDocumentNarrationContext(documentContext({
      active_is_current: true,
    }))).toThrow(/active\/current Edition/u);
    expect(() => parseDocumentNarrationContext(documentContext({
      compatibility: "current",
    }))).toThrow(/active Edition/u);
    expect(() => parseDocumentNarrationContext(documentContext({
      available_current_source_edition_ids: [],
    }))).toThrow(/playable current-source history/u);
  });

  it("accepts a strictly unbound chapter without silently selecting history", () => {
    const parsed = parseDocumentNarrationContext(documentContext({
      pointer_version: 0,
      current_script_version_id: null,
      current_edition_id: null,
      active_edition_id: null,
      active_is_current: false,
      source_snapshot: null,
      compatibility: "no_current_edition",
      source_notice_code: "NO_CURRENT_EDITION",
      editor_timeline_mode: "none",
      old_draft_subtitle_required: false,
      explicit_update_required: false,
      can_request_update: false,
      available_current_source_edition_ids: [],
      edition_history: {
        contract_version: EDITION_HISTORY_CONTRACT_VERSION,
        document_id: DOCUMENT_ID,
        pointer_version: 0,
        current_edition_id: null,
        working_copy_content_hash: SHA_A,
        working_copy_draft_version: 7,
        editions: [],
      },
    }));

    expect(parsed.current_edition_id).toBeNull();
    expect(parsed.active_edition_id).toBeNull();
    expect(parsed.compatibility).toBe("no_current_edition");
  });

  it("requires exact request fields and exact explicit switch confirmation", () => {
    const create = {
      intent: "update",
      expected_draft_version: 7,
      expected_content_hash: SHA_A,
      expected_settings_version: 3,
      force_review: false,
    };
    expect(parseCreateNarrationWorkflowRequest(create)).toEqual(create);
    expect(() => parseCreateNarrationWorkflowRequest({
      ...create,
      idempotency_key: "must-not-be-in-body",
    })).toThrow(/unexpected or missing fields/u);

    expect(parseSwitchNarrationEditionRequest(switchRequest()).confirmed).toBe(true);
    for (const confirmed of [false, 1, "true", null]) {
      expect(() => parseSwitchNarrationEditionRequest(switchRequest({ confirmed }))).toThrow(
        ChapterNarrationContractError,
      );
    }
    expect(() => parseSwitchNarrationEditionRequest(switchRequest({
      switch_mode: "next_playback",
    }))).toThrow(/next_playback/u);
    const missing = switchRequest() as Record<string, unknown>;
    delete missing.playback_rate_millis;
    expect(() => parseSwitchNarrationEditionRequest(missing)).toThrow(/unexpected or missing/u);
    expect(() => parseSwitchNarrationEditionRequest(switchRequest({ extra: true }))).toThrow(
      /unexpected or missing/u,
    );
  });

  it("strictly parses the switch response without assuming request scope", () => {
    const parsed = parseSwitchNarrationEditionResponse(switchResponse());
    expect(parsed.current_edition_id).toBe(HISTORICAL_EDITION_ID);
    expect(parsed.start_segment_id).toBe(START_SEGMENT_ID);
    expect(Object.isFrozen(parsed)).toBe(true);
  });

  it("strictly parses and freezes the failed-segment projection", () => {
    const parsed = parseFailedNarrationSegmentsProjection(failedSegments());

    expect(parsed.contract_version).toBe(FAILED_SEGMENT_RETRY_CONTRACT_VERSION);
    expect(parsed.items[0]?.failure_code).toBe("LEASE_EXPIRED");
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.items)).toBe(true);
    expect(Object.isFrozen(parsed.items[0])).toBe(true);
    expect(Object.isFrozen(parsed.items[0]?.fanout_segment_ids)).toBe(true);

    expect(() => parseFailedNarrationSegmentsProjection(failedSegments({
      request_state: "invented",
    }))).toThrow(/request_state/u);
    expect(() => parseFailedNarrationSegmentsProjection(failedSegments({
      items: [{ ...failedSegments().items[0], failure_code: "lowercase" }],
    }))).toThrow(/failure_code/u);
    expect(() => parseFailedNarrationSegmentsProjection(failedSegments({
      items: [{
        ...failedSegments().items[0],
        fanout_segment_ids: [FANOUT_SEGMENT_ID],
      }],
    }))).toThrow(/must contain segment_id/u);
    expect(() => parseFailedNarrationSegmentsProjection(failedSegments({
      items: [{
        ...failedSegments().items[0],
        retryable: false,
        retry_reason_code: null,
      }],
    }))).toThrow(/does not match retryable/u);
    expect(() => parseFailedNarrationSegmentsProjection({
      ...failedSegments(),
      private_scope: "spoofed",
    })).toThrow(/unexpected or missing fields/u);
  });

  it("enforces the exact bounded retry request", () => {
    const parsed = parseRetryFailedNarrationSegmentsRequest(retryRequest());
    expect(parsed.segment_ids).toEqual([FAILED_SEGMENT_ID]);
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.segment_ids)).toBe(true);

    for (const invalid of [
      retryRequest({ segment_ids: [] }),
      retryRequest({ segment_ids: [FAILED_SEGMENT_ID, FAILED_SEGMENT_ID] }),
      retryRequest({ segment_ids: Array.from({ length: 101 }, (_, index) => (
        `e1000000-0000-4000-8000-${String(index + 100).padStart(12, "0")}`
      )) }),
      retryRequest({ expected_request_version: true }),
      retryRequest({ expected_manifest_revision: 0 }),
      { ...retryRequest(), owner_id: NOVEL_ID },
    ]) {
      expect(() => parseRetryFailedNarrationSegmentsRequest(invalid)).toThrow(
        ChapterNarrationContractError,
      );
    }
  });

  it("rejects incoherent retry commands while accepting a strict replay response", () => {
    const parsed = parseRetryFailedNarrationSegmentsResponse(retryResponse({ replayed: true }));
    expect(parsed.replayed).toBe(true);
    expect(Object.isFrozen(parsed.commands)).toBe(true);
    expect(Object.isFrozen(parsed.commands[0])).toBe(true);

    expect(() => parseRetryFailedNarrationSegmentsResponse(retryResponse({
      accepted_segment_ids: [START_SEGMENT_ID],
    }))).toThrow(/subset/u);
    expect(() => parseRetryFailedNarrationSegmentsResponse(retryResponse({
      commands: [{
        command_id: RETRY_COMMAND_ID,
        job_id: JOB_ID,
        affected_segment_ids: [FAILED_SEGMENT_ID],
      }],
    }))).toThrow(/cover exactly/u);
    expect(() => parseRetryFailedNarrationSegmentsResponse(retryResponse({
      commands: [
        retryResponse().commands[0],
        {
          ...retryResponse().commands[0],
          affected_segment_ids: [FANOUT_SEGMENT_ID],
        },
      ],
    }))).toThrow(/unique command_id/u);
    expect(() => parseRetryFailedNarrationSegmentsResponse({
      ...retryResponse(),
      contract_version: "narration-failed-segment-retry/2",
    })).toThrow(/unsupported/u);
  });
});
