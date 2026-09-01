import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyCharacterVoiceGeneratorCommand,
  applyNanoVoiceExperiment,
  advanceCharacterCastPlan,
  cancelCharacterVoiceGeneratorCommand,
  cancelPrivateVoiceDeletionRequest,
  confirmPrivateVoiceDeletionRequest,
  createCharacterCastPlan,
  createCharacterVoiceGeneratorCommand,
  createNanoVoiceExperiment,
  createPrivateVoiceDeletionRequest,
  getCharacterCastPlan,
  getCharacterVoiceGeneratorCommand,
  listCharacterCastPlans,
  listCharacterVoiceGeneratorCommands,
  matchCharacterOfficialVoice,
  retryCharacterCastPlan,
  retryCharacterVoiceGeneratorCommand,
  retryPrivateVoiceDeletionRequest,
} from "./api";
import {
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type NanoDecodeParametersResource,
} from "./contracts";

const NOVEL_ID = "10000000-0000-4000-8000-000000000001";
const OTHER_NOVEL_ID = "10000000-0000-4000-8000-000000000002";
const CHARACTER_ID = "10000000-0000-4000-8000-000000000003";
const PROFILE_ID = "10000000-0000-4000-8000-000000000004";
const VERSION_ID = "10000000-0000-4000-8000-000000000005";
const COMMAND_ID = "10000000-0000-4000-8000-000000000006";
const JOB_ID = "10000000-0000-4000-8000-000000000007";
const REQUEST_ID = "10000000-0000-4000-8000-000000000008";
const BINDING_ID = "10000000-0000-4000-8000-000000000009";
const TIMELINE_ID = "10000000-0000-4000-8000-000000000010";
const ITEM_ID = "10000000-0000-4000-8000-000000000011";
const NOW = "2026-08-30T00:00:00Z";
const SHA = "a".repeat(64);

const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function settings() {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    settings_id: null,
    exists: false,
    version: 0,
    values: {
      narrator: null,
      language: "zh-CN",
      output_format: "m4a_aac_lc",
      script_review_policy: "blockers_only",
      analysis_mode: "local_rules_only",
      text_rules: {
        read_chapter_title: true,
        read_author_notes: false,
        read_section_breaks: false,
        first_person_mode: "narrator",
        first_person_character_id: null,
        inner_monologue_mode: "character",
      },
      timing: { sentence_gap_ms: 220, paragraph_gap_ms: 480, section_gap_ms: 850 },
      casting: {
        anonymous_reuse_scope: "scene",
        same_scene_voice_deduplication: true,
        unknown_speaker_action: "block",
      },
      playback: { playback_rate: 1, volume: 1 },
    },
    updated_at: null,
  };
}

const parameters: NanoDecodeParametersResource = {
  schema_version: "nano-decode-parameters/3",
  seed: "9223372036854775807",
  text_temperature_milli: 1_000,
  text_top_p_milli: 1_000,
  text_top_k: 50,
  audio_temperature_milli: 800,
  audio_top_p_milli: 950,
  audio_top_k: 25,
  audio_repetition_penalty_milli: 1_200,
  sample_mode: "full",
  max_new_frames: 375,
};

function nanoExperiment(novelId = NOVEL_ID) {
  return {
    contract_version: "nano-voice-experiment/1",
    command_id: COMMAND_ID,
    novel_id: novelId,
    profile_id: PROFILE_ID,
    version_id: VERSION_ID,
    background_job_id: JOB_ID,
    base_preset_id: "onnx.Junhao",
    target_kind: "narrator",
    character_id: null,
    expected_settings_version: 0,
    expected_binding_version: null,
    parameters,
    parameters_digest: SHA,
    fingerprint: "b".repeat(64),
    state: "pending",
    reused_version: false,
    preview: null,
    current_settings: { ...settings(), novel_id: novelId },
    current_character_binding: null,
    failure_code: null,
    retryable: false,
    created_at: NOW,
    started_at: null,
    completed_at: null,
  };
}

function binding(novelId = NOVEL_ID) {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    binding_id: BINDING_ID,
    novel_id: novelId,
    character_id: CHARACTER_ID,
    binding_policy: "dedicated",
    profile_id: PROFILE_ID,
    version_id: VERSION_ID,
    language: "zh-CN",
    version: 1,
    impact: {
      affected_chapter_count: 0,
      affected_segment_count: 0,
      historical_edition_count: 0,
      regeneration_required: false,
    },
    updated_at: NOW,
  };
}

function matchResource(novelId = NOVEL_ID) {
  return {
    contract_version: "character-voice-match/1",
    character_id: CHARACTER_ID,
    brief: {
      schema_version: "character-voice-brief/1",
      language: null,
      presentation: null,
      pitch: null,
      pace: null,
      energy: null,
      texture: null,
      evidence_fields: [],
    },
    selected_preset_id: "onnx.Junhao",
    score_milli: 500,
    state: "ready_applied",
    selection_still_current: true,
    current_character_binding: binding(novelId),
    model_evidence: { schema_version: "model-execution-evidence/2" },
  };
}

function castPlan(
  novelId = NOVEL_ID,
  commandId = COMMAND_ID,
  timelineId = TIMELINE_ID,
) {
  return {
    contract_version: "character-cast-plan/1",
    command_id: commandId,
    novel_id: novelId,
    timeline_id: timelineId,
    mode: "fill_and_deduplicate",
    state: "reserved",
    server_now: NOW,
    progress_current: 0,
    progress_total: 1,
    terminal: false,
    retryable: false,
    current_target_key: null,
    lease_expires_at: null,
    assignments: [],
    preserved: [],
    warnings: [],
    items: [{
      item_id: ITEM_ID,
      target: {
        target_key: "narrator",
        target_kind: "narrator",
        character_id: null,
        character_name: null,
        role_type: null,
      },
      state: "pending",
      attempt: 0,
      workspace_digest: SHA,
      lease_expires_at: null,
      brief: null,
      selected_preset_id: null,
      score_milli: null,
      profile_id: null,
      version_id: null,
      voice_action_command_id: null,
      warning_code: null,
      failure_code: null,
    }],
    failure_code: null,
    created_at: NOW,
    updated_at: NOW,
    completed_at: null,
  };
}

function voiceGeneratorCommand(
  novelId = NOVEL_ID,
  commandId = COMMAND_ID,
) {
  return {
    contract_version: "character-voice-generation/1",
    command_id: commandId,
    novel_id: novelId,
    character_id: CHARACTER_ID,
    draft_id: null,
    background_job_id: null,
    state: "queued",
    progress_current: 0,
    progress_total: 6,
    expected_binding_version: 0,
    applied_binding_version: null,
    brief: null,
    voice_profile_id: null,
    voice_version_id: null,
    result_version: null,
    current_character_binding: binding(novelId),
    selection_still_current: true,
    cancellable: true,
    retryable: false,
    terminal: false,
    failure_code: null,
    created_at: NOW,
    started_at: null,
    completed_at: null,
    applied_at: null,
    updated_at: NOW,
  };
}

function deletionImpact() {
  return {
    schema_version: "private-voice-deletion-impact/2",
    profile_id: PROFILE_ID,
    novel_id: NOVEL_ID,
    profile_version: 3,
    voice_version_ids: [VERSION_ID],
    current_narrator_count: 1,
    character_binding_count: 0,
    anonymous_speaker_count: 0,
    generic_slot_count: 0,
    historical_edition_count: 1,
    render_count: 0,
    export_count: 0,
    current_reference_count: 1,
    historical_reference_count: 1,
    reference_count: 2,
    asset_count: 1,
    total_bytes: 1024,
    active_job_count: 0,
    external_backup_status: "unmanaged",
    historical_audio_consequence: "unavailable_private_voice_deleted",
    impact_summary: "将解除 1 处当前引用，并使 1 项历史朗读证据不可播放；将删除 1 个资产。",
  };
}

function deletionRequest(
  state: "requested" | "live_deleting" | "cancelled" = "requested",
) {
  const terminal = state === "cancelled";
  return {
    contract_version: "private-voice-deletion/2",
    request_id: REQUEST_ID,
    profile_id: PROFILE_ID,
    novel_id: NOVEL_ID,
    command: "true_delete_private_voice",
    state,
    server_now: NOW,
    expected_profile_version: 3,
    impact_digest: SHA,
    impact: deletionImpact(),
    eligibility: "referenced",
    reference_count: 2,
    execute_after: null,
    impact_expires_at: state === "requested" ? "2026-08-30T00:15:00Z" : null,
    asset_count: 1,
    total_bytes: 1024,
    external_backup_status: "unmanaged",
    confirmed_at: state === "live_deleting" ? NOW : null,
    cancelled_at: state === "cancelled" ? NOW : null,
    completed_at: null,
    superseded_at: null,
    job_drain_started_at: null,
    job_drain_deadline: null,
    failure_code: null,
    cancellable: state === "requested",
    retryable: false,
    terminal,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
});

afterEach(() => vi.unstubAllGlobals());

describe("Plan35 narration feature API", () => {
  it("keeps the full int64 seed lossless and uses idempotency only for creation", async () => {
    fetchMock.mockResolvedValueOnce(response(nanoExperiment(), 202));
    await createNanoVoiceExperiment(
      NOVEL_ID,
      {
        contract_version: "nano-voice-experiment-request/1",
        base_preset_id: "onnx.Junhao",
        target_kind: "narrator",
        character_id: null,
        expected_settings_version: 0,
        expected_binding_version: null,
        parameters,
      },
      "nano-experiment-0001",
    );
    let [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe(`/ai-novel-world-2026/novels/${NOVEL_ID}/nano-voice-experiments`);
    expect((init?.headers as Record<string, string>)["Idempotency-Key"])
      .toBe("nano-experiment-0001");
    expect(JSON.parse(String(init?.body)).parameters.seed).toBe("9223372036854775807");

    fetchMock.mockResolvedValueOnce(response(nanoExperiment()));
    await applyNanoVoiceExperiment(NOVEL_ID, COMMAND_ID, {
      expected_settings_version: 0,
      expected_binding_version: null,
    });
    [path, init] = fetchMock.mock.calls[1]!;
    expect(path).toContain(`/${COMMAND_ID}/binding`);
    expect(init?.method).toBe("PUT");
    expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBeUndefined();

    fetchMock.mockResolvedValueOnce(response(nanoExperiment(OTHER_NOVEL_ID)));
    await expect(applyNanoVoiceExperiment(NOVEL_ID, COMMAND_ID, {
      expected_settings_version: 0,
      expected_binding_version: null,
    })).rejects.toThrow(/response scope mismatch/);
  });

  it("posts one character-card match and rejects cross-novel binding drift", async () => {
    fetchMock.mockResolvedValueOnce(response(matchResource()));
    await matchCharacterOfficialVoice(
      NOVEL_ID,
      CHARACTER_ID,
      {
        contract_version: "character-voice-match-request/1",
        timeline_id: null,
        character_instance_id: null,
        expected_binding_version: 0,
      },
      "character-match-0001",
    );
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toContain(`/characters/${CHARACTER_ID}/official-voice-match`);
    expect((init?.headers as Record<string, string>)["Idempotency-Key"])
      .toBe("character-match-0001");

    fetchMock.mockResolvedValueOnce(response(matchResource(OTHER_NOVEL_ID)));
    await expect(matchCharacterOfficialVoice(
      NOVEL_ID,
      CHARACTER_ID,
      {
        contract_version: "character-voice-match-request/1",
        timeline_id: null,
        character_instance_id: null,
        expected_binding_version: 0,
      },
      "character-match-0002",
    )).rejects.toThrow(/response scope mismatch/);
  });

  it("recovers one durable whole-book cast command and reserves idempotency for creation", async () => {
    fetchMock.mockResolvedValueOnce(response({
      contract_version: "character-cast-plan-list/1",
      novel_id: NOVEL_ID,
      server_now: NOW,
      items: [castPlan()],
    }));
    await expect(listCharacterCastPlans(NOVEL_ID)).resolves.toMatchObject({
      items: [{ command_id: COMMAND_ID }],
    });

    fetchMock.mockResolvedValueOnce(response(castPlan(), 202));
    await createCharacterCastPlan(
      NOVEL_ID,
      {
        contract_version: "character-cast-plan-request/1",
        timeline_id: TIMELINE_ID,
        mode: "fill_and_deduplicate",
      },
      "character-cast-plan-0001",
    );
    let [path, init] = fetchMock.mock.calls[1]!;
    expect(path).toBe(`/ai-novel-world-2026/novels/${NOVEL_ID}/character-cast-plans`);
    expect((init?.headers as Record<string, string>)["Idempotency-Key"])
      .toBe("character-cast-plan-0001");

    for (const operation of [
      () => getCharacterCastPlan(NOVEL_ID, COMMAND_ID),
      () => advanceCharacterCastPlan(NOVEL_ID, COMMAND_ID),
      () => retryCharacterCastPlan(NOVEL_ID, COMMAND_ID),
    ]) {
      fetchMock.mockResolvedValueOnce(response(castPlan()));
      await expect(operation()).resolves.toMatchObject({ command_id: COMMAND_ID });
    }
    for (const [, request] of fetchMock.mock.calls.slice(2)) {
      expect((request?.headers as Record<string, string> | undefined)?.["Idempotency-Key"])
        .toBeUndefined();
    }
    expect(fetchMock.mock.calls[2]![1]?.method).toBeUndefined();
    expect(fetchMock.mock.calls[3]![1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[4]![1]?.method).toBe("POST");
  });

  it("rejects cast-list, command, and timeline scope drift", async () => {
    fetchMock.mockResolvedValueOnce(response({
      contract_version: "character-cast-plan-list/1",
      novel_id: OTHER_NOVEL_ID,
      server_now: NOW,
      items: [],
    }));
    await expect(listCharacterCastPlans(NOVEL_ID)).rejects.toThrow(/scope mismatch/);

    fetchMock.mockResolvedValueOnce(response(castPlan(OTHER_NOVEL_ID)));
    await expect(getCharacterCastPlan(NOVEL_ID, COMMAND_ID)).rejects.toThrow(/scope mismatch/);

    fetchMock.mockResolvedValueOnce(response(castPlan(NOVEL_ID, COMMAND_ID, CHARACTER_ID)));
    await expect(createCharacterCastPlan(
      NOVEL_ID,
      {
        contract_version: "character-cast-plan-request/1",
        timeline_id: TIMELINE_ID,
        mode: "fill_and_deduplicate",
      },
      "character-cast-plan-0002",
    )).rejects.toThrow(/scope mismatch/);
  });

  it("closes every VoiceGenerator response to the requested public scope", async () => {
    fetchMock.mockResolvedValueOnce(response({
      contract_version: "character-voice-generation-list/1",
      novel_id: NOVEL_ID,
      character_id: CHARACTER_ID,
      items: [voiceGeneratorCommand()],
    }));
    await listCharacterVoiceGeneratorCommands(NOVEL_ID, CHARACTER_ID);

    fetchMock.mockResolvedValueOnce(response(voiceGeneratorCommand(), 202));
    await createCharacterVoiceGeneratorCommand(
      NOVEL_ID,
      CHARACTER_ID,
      {
        contract_version: "character-voice-generation-request/1",
        timeline_id: null,
        character_instance_id: null,
        expected_binding_version: 0,
        seed: null,
      },
      "voice-generator-0001",
    );

    for (const operation of [
      () => getCharacterVoiceGeneratorCommand(NOVEL_ID, COMMAND_ID),
      () => cancelCharacterVoiceGeneratorCommand(NOVEL_ID, COMMAND_ID),
      () => applyCharacterVoiceGeneratorCommand(
        NOVEL_ID,
        COMMAND_ID,
        { expected_binding_version: 0 },
      ),
    ]) {
      fetchMock.mockResolvedValueOnce(
        response(voiceGeneratorCommand(OTHER_NOVEL_ID)),
      );
      await expect(operation()).rejects.toThrow(/response scope mismatch/);
    }
  });

  it("accepts the fresh command identity returned by VoiceGenerator retry", async () => {
    const retried = {
      ...voiceGeneratorCommand(),
      command_id: "10000000-0000-4000-8000-000000000099",
    };
    fetchMock.mockResolvedValueOnce(response(retried, 202));

    await expect(retryCharacterVoiceGeneratorCommand(
      NOVEL_ID,
      COMMAND_ID,
      { expected_binding_version: 0 },
    )).resolves.toMatchObject({ command_id: retried.command_id });

    fetchMock.mockResolvedValueOnce(response({
      ...retried,
      novel_id: OTHER_NOVEL_ID,
      current_character_binding: {
        ...retried.current_character_binding,
        novel_id: OTHER_NOVEL_ID,
      },
    }));
    await expect(retryCharacterVoiceGeneratorCommand(
      NOVEL_ID,
      COMMAND_ID,
      { expected_binding_version: 0 },
    )).rejects.toThrow(/response scope mismatch/);
  });

  it("does not send fake idempotency headers on confirm, cancel, or retry", async () => {
    fetchMock.mockResolvedValueOnce(response(deletionRequest(), 202));
    await createPrivateVoiceDeletionRequest(
      NOVEL_ID,
      PROFILE_ID,
      { expected_profile_version: 3 },
      "private-delete-0001",
    );
    expect((fetchMock.mock.calls[0]![1]?.headers as Record<string, string>)["Idempotency-Key"])
      .toBe("private-delete-0001");

    fetchMock.mockResolvedValueOnce(response(deletionRequest("live_deleting")));
    await confirmPrivateVoiceDeletionRequest(NOVEL_ID, REQUEST_ID, {
      expected_profile_version: 3,
      impact_digest: SHA,
    });
    fetchMock.mockResolvedValueOnce(response(deletionRequest("cancelled")));
    await cancelPrivateVoiceDeletionRequest(NOVEL_ID, REQUEST_ID);
    fetchMock.mockResolvedValueOnce(response(deletionRequest("live_deleting")));
    await retryPrivateVoiceDeletionRequest(NOVEL_ID, REQUEST_ID);

    for (const [, init] of fetchMock.mock.calls.slice(1)) {
      expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBeUndefined();
      expect(init?.method).toBe("POST");
    }
    expect(fetchMock.mock.calls[1]![1]?.body).toBeDefined();
    expect(fetchMock.mock.calls[2]![1]?.body).toBeUndefined();
    expect(fetchMock.mock.calls[3]![1]?.body).toBeUndefined();
  });
});
