import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api";
import {
  NarrationApiError,
  buildUploadedVoiceVersionFormData,
  createNarrationCloudConsent,
  createOfficialVoicePreview,
  createPresetVoiceVersion,
  createNarrationWorkflow,
  createUploadedVoiceVersion,
  createVoiceProfile,
  getDocumentNarrationContext,
  getFailedNarrationSegments,
  getNarrationEdition,
  getNarrationEditionVoiceIdentities,
  getNarrationSettings,
  getNarrationWorkflow,
  listOfficialVoicePresets,
  selectOfficialVoice,
  getVoicePreview,
  putCharacterVoiceBinding,
  putNarrationSettings,
  putNarrationPlaybackPreferences,
  revokeNarrationCloudConsent,
  retryFailedNarrationSegments,
  switchNarrationEdition,
} from "./api";
import {
  ChapterNarrationContractError,
  DOCUMENT_NARRATION_CONTEXT_VERSION,
  FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
  NARRATION_PRODUCTION_API_VERSION,
} from "./chapter-contracts";
import {
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  NARRATION_VOICE_SCHEMA_VERSION,
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_MANIFEST_IDENTITY,
  NarrationContractError,
} from "./contracts";
import { EDITION_HISTORY_CONTRACT_VERSION } from "./edition-history";

const NOVEL_ID = "10000000-0000-4000-8000-000000000001";
const PROFILE_ID = "10000000-0000-4000-8000-000000000002";
const VERSION_ID = "10000000-0000-4000-8000-000000000003";
const CHARACTER_ID = "10000000-0000-4000-8000-000000000004";
const RIGHTS_ID = "10000000-0000-4000-8000-000000000005";
const ASSET_ID = "10000000-0000-4000-8000-000000000006";
const NOW = "2026-08-26T12:00:00Z";
function officialCatalog(
  evidenceRows: readonly (typeof OFFICIAL_PRESET_EVIDENCE)[number][] = OFFICIAL_PRESET_EVIDENCE,
) {
  return {
    schema_version: "moss-tts-official-preset-catalog/2.0",
    items: evidenceRows.map((evidence, index) => {
      const presetLanguage = index < 6 ? "zh-CN" : index < 11 ? "en" : "ja-JP";
      return {
        preset_id: evidence.presetId,
        display_name: evidence.manifestVoice,
        group: "Official",
        language: presetLanguage,
        local_use_status: "available",
        commercial_distribution_status: "not_evaluated",
        validation_tier: ["Junhao", "Zhiming", "Xiaoyu"].includes(evidence.manifestVoice)
          ? "canonical_chapter_verified"
          : "pinned_catalog_unreviewed",
        language_scope: presetLanguage,
        selectable_now: true,
        previewable_now: true,
        renderable_existing: true,
        usage_notice: "private_local_writing_tool",
        provenance: {
          schema_version: "moss-tts-official-preset-provenance/1.0",
          repository: OFFICIAL_PRESET_MANIFEST_IDENTITY.repository,
          revision: OFFICIAL_PRESET_MANIFEST_IDENTITY.revision,
          manifest_path: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestPath,
          manifest_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.manifestSha256,
          preset_id: evidence.presetId,
          manifest_voice: evidence.manifestVoice,
          prompt_codes_sha256: evidence.promptCodesSha256,
          prompt_frame_count: evidence.promptFrameCount,
          prompt_quantizer_count: evidence.promptQuantizerCount,
          model_fingerprint_sha256: OFFICIAL_PRESET_MANIFEST_IDENTITY.modelFingerprintSha256,
          provenance_fingerprint_sha256: evidence.provenanceFingerprintSha256,
        },
      };
    }),
  };
}

const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function settingsValues() {
  return {
    narrator: null,
    language: "zh-CN",
    output_format: "m4a_aac_lc" as const,
    script_review_policy: "blockers_only" as const,
    analysis_mode: "local_rules_only" as const,
    text_rules: {
      read_chapter_title: true,
      read_author_notes: false,
      read_section_breaks: false,
      first_person_mode: "narrator" as const,
      first_person_character_id: null,
      inner_monologue_mode: "character" as const,
    },
    timing: {
      sentence_gap_ms: 220,
      paragraph_gap_ms: 480,
      section_gap_ms: 850,
    },
    casting: {
      anonymous_reuse_scope: "scene" as const,
      same_scene_voice_deduplication: true,
      unknown_speaker_action: "block" as const,
    },
    playback: { playback_rate: 1, volume: 1 },
  };
}

function settingsResource() {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    settings_id: null,
    exists: false,
    version: 0,
    values: settingsValues(),
    updated_at: null,
  };
}

function draftProfile() {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    profile_id: PROFILE_ID,
    novel_id: NOVEL_ID,
    name: "女主角",
    status: "draft",
    version: 1,
    current_version_id: null,
    versions: [],
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
  };
}

function uploadedVersion() {
  return {
    schema_version: NARRATION_VOICE_SCHEMA_VERSION,
    version_id: VERSION_ID,
    profile_id: PROFILE_ID,
    version_number: 1,
    source_type: "uploaded",
    state: "preview_ready",
    provider_id: "moss-nano",
    model_id: "MOSS-TTS-Nano-100M-ONNX",
    model_revision: "frozen-revision",
    preset_key: null,
    language: "zh-CN",
    fingerprint: "a".repeat(64),
    quality_state: "pending",
    activation_basis: "preview_confirmed",
    validation_basis: "pending",
    rights: {
      rights_record_id: RIGHTS_ID,
      state: "active",
      notice_version: "voice-rights/1",
      source_kind: "user_upload",
      source_identifier_sha256: "d".repeat(64),
      purpose: "private_novel_narration",
      commercial_use: false,
      redistribution: false,
      voice_cloning: true,
      subject_consent_recorded: true,
      confirmed_at: NOW,
      expires_at: null,
      risk_flags: [],
    },
    official_preset: null,
    reference_asset_id: ASSET_ID,
    preview_asset: null,
    description_available: false,
    locked_at: null,
    created_at: NOW,
  };
}

function uploadMetadata() {
  return {
    expected_profile_version: 1,
    language: "zh-CN",
    original_filename: "authorized-reference.wav",
    reference_sha256: "b".repeat(64),
    rights: {
      notice_version: "voice-rights/1",
      source_identifier: "local-recording-1",
      purpose: "private_novel_narration" as const,
      commercial_use: false,
      redistribution: false,
      voice_cloning: true as const,
      subject_consent_reference: "consent-local-1",
      confirmed: true as const,
    },
  };
}


const CHAPTER_DOCUMENT_ID = "f1000000-0000-4000-8000-000000000001";
const CHAPTER_NOVEL_ID = "f1000000-0000-4000-8000-000000000002";
const CHAPTER_EDITION_ID = "f1000000-0000-4000-8000-000000000003";
const CHAPTER_TARGET_EDITION_ID = "f1000000-0000-4000-8000-000000000004";
const CHAPTER_REQUEST_ID = "f1000000-0000-4000-8000-000000000005";
const CHAPTER_REVISION_ID = "f1000000-0000-4000-8000-000000000006";
const CHAPTER_SCRIPT_VERSION_ID = "f1000000-0000-4000-8000-000000000007";
const CHAPTER_JOB_ID = "f1000000-0000-4000-8000-000000000008";
const CHAPTER_SEGMENT_ID = "f1000000-0000-4000-8000-000000000009";
const CHAPTER_PROGRESS_ID = "f1000000-0000-4000-8000-000000000010";
const CHAPTER_FANOUT_SEGMENT_ID = "f1000000-0000-4000-8000-000000000011";
const CHAPTER_RETRY_COMMAND_ID = "f1000000-0000-4000-8000-000000000012";
const CHAPTER_PROFILE_ID = "f1000000-0000-4000-8000-000000000013";
const CHAPTER_VOICE_VERSION_ID = "f1000000-0000-4000-8000-000000000014";
const CHAPTER_SHA_A = "1".repeat(64);
const CHAPTER_SHA_B = "2".repeat(64);
const CHAPTER_SHA_C = "3".repeat(64);


function chapterHistoryItem(changes: Record<string, unknown> = {}) {
  return {
    edition_id: CHAPTER_EDITION_ID,
    request_id: CHAPTER_REQUEST_ID,
    source_revision_id: CHAPTER_REVISION_ID,
    source_content_hash: CHAPTER_SHA_A,
    edition_fingerprint: CHAPTER_SHA_C,
    state: "ready",
    created_at: NOW,
    manifest_revision: 7,
    manifest_etag: `"${CHAPTER_SHA_C}"`,
    ready_segment_count: 3,
    total_segment_count: 3,
    is_current: true,
    source_status: "current",
    rights_available: true,
    playable: true,
    default_start_ready: true,
    resume_available: true,
    switch_allowed: false,
    ...changes,
  };
}


function chapterContext(changes: Record<string, unknown> = {}) {
  return {
    contract_version: DOCUMENT_NARRATION_CONTEXT_VERSION,
    document_id: CHAPTER_DOCUMENT_ID,
    novel_id: CHAPTER_NOVEL_ID,
    pointer_version: 4,
    current_script_version_id: CHAPTER_SCRIPT_VERSION_ID,
    current_edition_id: CHAPTER_EDITION_ID,
    active_edition_id: CHAPTER_EDITION_ID,
    active_is_current: true,
    working_copy_draft_version: 7,
    working_copy_content_hash: CHAPTER_SHA_A,
    source_snapshot: {
      revision_id: CHAPTER_REVISION_ID,
      content_hash: CHAPTER_SHA_A,
      matches_working_copy: true,
    },
    compatibility: "current",
    source_notice_code: "CURRENT_SOURCE_SNAPSHOT",
    editor_timeline_mode: "exact_working_copy",
    old_draft_subtitle_required: false,
    explicit_update_required: false,
    can_request_update: true,
    available_current_source_edition_ids: [],
    edition_history: {
      contract_version: EDITION_HISTORY_CONTRACT_VERSION,
      document_id: CHAPTER_DOCUMENT_ID,
      pointer_version: 4,
      current_edition_id: CHAPTER_EDITION_ID,
      working_copy_content_hash: CHAPTER_SHA_A,
      working_copy_draft_version: 7,
      editions: [chapterHistoryItem()],
    },
    ...changes,
  };
}


function chapterWorkflow(changes: Record<string, unknown> = {}) {
  return {
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    request_id: CHAPTER_REQUEST_ID,
    intent: "create",
    request_version: 4,
    workflow_state: "queued",
    source_revision_id: CHAPTER_REVISION_ID,
    source_content_hash: CHAPTER_SHA_A,
    settings_fingerprint: CHAPTER_SHA_B,
    warning_count: 0,
    blocker_count: 0,
    script_version_id: CHAPTER_SCRIPT_VERSION_ID,
    edition_id: CHAPTER_EDITION_ID,
    current_manifest_revision: null,
    job_ids: [CHAPTER_JOB_ID],
    replayed: false,
    ...changes,
  };
}


function chapterEdition(changes: Record<string, unknown> = {}) {
  return {
    contract_version: NARRATION_PRODUCTION_API_VERSION,
    edition_id: CHAPTER_EDITION_ID,
    request_id: CHAPTER_REQUEST_ID,
    novel_id: CHAPTER_NOVEL_ID,
    document_id: CHAPTER_DOCUMENT_ID,
    script_version_id: CHAPTER_SCRIPT_VERSION_ID,
    settings_fingerprint: CHAPTER_SHA_B,
    edition_fingerprint: CHAPTER_SHA_C,
    state: "rendering",
    segment_count: 3,
    pending_segment_count: 0,
    queued_segment_count: 2,
    rendering_segment_count: 1,
    ready_segment_count: 0,
    failed_segment_count: 0,
    current_manifest_revision: null,
    job_ids: [CHAPTER_JOB_ID],
    ...changes,
  };
}


function chapterSwitchResponse(changes: Record<string, unknown> = {}) {
  return {
    contract_version: DOCUMENT_NARRATION_CONTEXT_VERSION,
    document_id: CHAPTER_DOCUMENT_ID,
    current_edition_id: CHAPTER_TARGET_EDITION_ID,
    pointer_version: 5,
    switch_mode: "immediate",
    start_segment_id: CHAPTER_SEGMENT_ID,
    manifest_revision: 8,
    playback_progress_id: CHAPTER_PROGRESS_ID,
    ...changes,
  };
}


function chapterFailedSegments(changes: Record<string, unknown> = {}) {
  return {
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: CHAPTER_EDITION_ID,
    request_id: CHAPTER_REQUEST_ID,
    request_version: 4,
    manifest_revision: 7,
    request_state: "partial_ready",
    edition_state: "partial_ready",
    items: [{
      segment_id: CHAPTER_SEGMENT_ID,
      ordinal: 1,
      failure_code: "LEASE_EXPIRED",
      retryable: true,
      retry_reason_code: null,
      job_id: CHAPTER_JOB_ID,
      fanout_segment_ids: [CHAPTER_SEGMENT_ID, CHAPTER_FANOUT_SEGMENT_ID],
    }],
    ...changes,
  };
}


function chapterRetryResponse(changes: Record<string, unknown> = {}) {
  return {
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: CHAPTER_EDITION_ID,
    request_id: CHAPTER_REQUEST_ID,
    accepted_segment_ids: [CHAPTER_SEGMENT_ID],
    affected_segment_ids: [CHAPTER_SEGMENT_ID, CHAPTER_FANOUT_SEGMENT_ID],
    commands: [{
      command_id: CHAPTER_RETRY_COMMAND_ID,
      job_id: CHAPTER_JOB_ID,
      affected_segment_ids: [CHAPTER_SEGMENT_ID, CHAPTER_FANOUT_SEGMENT_ID],
    }],
    request_version: 5,
    request_state: "rendering",
    edition_state: "rendering",
    replayed: false,
    ...changes,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("window", {
    QwenPaw: {
      host: { fetch: fetchMock },
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("narration settings API client", () => {
  it("loads the exact 18-item pinned preset catalog and sends exact preset_id", async () => {
    const catalog = officialCatalog();
    fetchMock.mockResolvedValueOnce(response(catalog));

    const loaded = await listOfficialVoicePresets();
    expect(loaded.items).toHaveLength(18);
    expect(loaded.items.map((item) => item.preset_id)).toContain("onnx.Trump");
    expect(loaded.items.map((item) => item.preset_id)).toContain("onnx.Xiaoyu");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/ai-novel-world-2026/voice-presets",
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );

    const preset = catalog.items[3];
    const created = {
      ...uploadedVersion(),
      source_type: "preset",
      provider_id: "moss-tts-nano-onnx",
      model_id: preset.provenance.repository,
      model_revision: preset.provenance.revision,
      preset_key: preset.preset_id,
      language: preset.language,
      rights: {
        ...uploadedVersion().rights,
        notice_version: "official-preset-local-use/1",
        source_kind: "official_preset",
        voice_cloning: false,
        subject_consent_recorded: false,
      },
      official_preset: preset.provenance,
      reference_asset_id: null,
    };
    fetchMock.mockResolvedValueOnce(response(created));
    await createPresetVoiceVersion(
      PROFILE_ID,
      { expected_profile_version: 1, preset_id: "onnx.Xiaoyu" },
      "preset-request-0001",
    );
    const [path, init] = fetchMock.mock.calls[1];
    expect(path).toBe(`/ai-novel-world-2026/voice-profiles/${PROFILE_ID}/versions/preset`);
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_profile_version: 1,
      preset_id: "onnx.Xiaoyu",
    });

    const incomplete = officialCatalog();
    incomplete.items.pop();
    fetchMock.mockResolvedValueOnce(response(incomplete));
    await expect(listOfficialVoicePresets()).rejects.toThrow(/exact 18-item/);
  });

  it("sends one official narrator selection command and validates its frozen result", async () => {
    const preset = officialCatalog().items[0]!;
    const version = {
      ...uploadedVersion(),
      source_type: "preset",
      state: "locked",
      provider_id: "local-sidecar",
      model_id: preset.provenance.repository,
      model_revision: preset.provenance.revision,
      preset_key: preset.preset_id,
      language: preset.language,
      quality_state: "pending",
      activation_basis: "explicit_official_preset_selection",
      validation_basis: "not_required",
      rights: {
        ...uploadedVersion().rights,
        source_kind: "official_preset",
        voice_cloning: false,
        subject_consent_recorded: false,
      },
      official_preset: preset.provenance,
      reference_asset_id: null,
      locked_at: null,
    };
    const profile = {
      ...draftProfile(),
      status: "active",
      current_version_id: VERSION_ID,
      versions: [version],
    };
    const settings = {
      ...settingsResource(),
      settings_id: ASSET_ID,
      exists: true,
      version: 1,
      values: {
        ...settingsValues(),
        narrator: { profile_id: PROFILE_ID, version_id: VERSION_ID },
      },
      updated_at: NOW,
    };
    fetchMock.mockResolvedValueOnce(response({
      contract_version: "official-voice-selection/1.0",
      replayed: false,
      selection_still_current: true,
      frozen_result: {
        command_id: RIGHTS_ID,
        preset_id: preset.preset_id,
        target_kind: "narrator",
        character_id: null,
        profile_id: PROFILE_ID,
        version_id: VERSION_ID,
        settings_version: 1,
        binding_version: null,
        target_language: "zh-CN",
        language_mismatch: false,
        completed_at: NOW,
      },
      profile,
      current_settings: settings,
      current_character_binding: null,
    }));

    const selected = await selectOfficialVoice(
      NOVEL_ID,
      {
        preset_id: "onnx.Junhao",
        target_kind: "narrator",
        character_id: null,
        expected_settings_version: 0,
        expected_binding_version: null,
      },
      "official-select-0001",
    );

    expect(selected.frozen_result.version_id).toBe(VERSION_ID);
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe(`/ai-novel-world-2026/novels/${NOVEL_ID}/official-voice-selections`);
    expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBe("official-select-0001");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      preset_id: "onnx.Junhao",
      target_kind: "narrator",
      expected_settings_version: 0,
    });

    fetchMock.mockResolvedValueOnce(response({
      contract_version: "official-voice-selection/1.0",
      replayed: true,
      selection_still_current: false,
      frozen_result: selected.frozen_result,
      profile,
      current_settings: {
        ...settings,
        version: 2,
        values: { ...settings.values, narrator: null },
      },
      current_character_binding: null,
    }));
    const replayed = await selectOfficialVoice(
      NOVEL_ID,
      {
        preset_id: "onnx.Junhao",
        target_kind: "narrator",
        character_id: null,
        expected_settings_version: 0,
        expected_binding_version: null,
      },
      "official-select-0001",
    );
    expect(replayed.replayed).toBe(true);
    expect(replayed.selection_still_current).toBe(false);
    expect(replayed.current_settings?.version).toBe(2);
  });

  it("uses the PawApp namespace and validates every JSON response", async () => {
    fetchMock.mockResolvedValue(response(settingsResource()));

    const result = await getNarrationSettings(NOVEL_ID);

    expect(result.version).toBe(0);
    expect(fetchMock).toHaveBeenCalledWith(
      `/ai-novel-world-2026/novels/${NOVEL_ID}/narration-settings`,
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("rejects a 200 response whose wire shape drifted", async () => {
    fetchMock.mockResolvedValue(response({ ...settingsResource(), unexpected: true }));

    await expect(getNarrationSettings(NOVEL_ID)).rejects.toBeInstanceOf(
      NarrationContractError,
    );
  });

  it("turns only a valid structured server failure into NarrationApiError", async () => {
    fetchMock.mockResolvedValue(response({
      detail: {
        contract_version: NARRATION_SETTINGS_API_VERSION,
        code: "CAPABILITY_DISABLED",
        message: "参考音色产品闸门尚未通过。",
        retryable: false,
        field: null,
        current_version: null,
        capability: "reference_clone",
      },
    }, 409));

    await expect(getNarrationSettings(NOVEL_ID)).rejects.toMatchObject({
      status: 409,
      detail: {
        code: "CAPABILITY_DISABLED",
        capability: "reference_clone",
      },
    });

    fetchMock.mockResolvedValue(response({ detail: "legacy failure" }, 500));
    await expect(getNarrationSettings(NOVEL_ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("sends exact CAS settings JSON without client scope fields", async () => {
    fetchMock.mockResolvedValue(response(settingsResource()));

    await putNarrationSettings(NOVEL_ID, {
      expected_version: 0,
      values: settingsValues(),
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_version: 0,
      values: settingsValues(),
    });
    expect(String(init?.body)).not.toContain("owner_id");
    expect(String(init?.body)).not.toContain("workspace_id");
  });

  it("patches only playback preferences with the current settings version", async () => {
    fetchMock.mockResolvedValue(response(settingsResource()));

    await putNarrationPlaybackPreferences(NOVEL_ID, {
      expected_version: 4,
      playback: { playback_rate: 1.5, volume: 0.35 },
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      `/ai-novel-world-2026/novels/${NOVEL_ID}/narration-settings/playback-preferences`,
    );
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_version: 4,
      playback: { playback_rate: 1.5, volume: 0.35 },
    });
  });

  it("requires a stable idempotency key for profile creation", async () => {
    fetchMock.mockResolvedValue(response(draftProfile(), 201));

    await createVoiceProfile(
      { novel_id: NOVEL_ID, name: "女主角" },
      "profile-create-0001",
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({
      "Idempotency-Key": "profile-create-0001",
      "Content-Type": "application/json",
    });

    expect(() => createVoiceProfile(
      { novel_id: NOVEL_ID, name: "女主角" },
      "bad",
    )).toThrow(NarrationContractError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("uses idempotency for cloud consent and CAS-targets revocation", async () => {
    const consentId = "10000000-0000-4000-8000-000000000009";
    const active = {
      consent_id: consentId,
      version: 1,
      state: "active",
      purpose: "narration_speaker_analysis",
      data_scope: "uncertain_segments_with_minimal_context",
      notice_version: "narration-cloud/1",
      provider_id: null,
      model_id: null,
      confirmed_at: NOW,
      revoked_at: null,
    };
    fetchMock.mockResolvedValue(response(active, 201));
    await createNarrationCloudConsent(
      NOVEL_ID,
      {
        notice_version: "narration-cloud/1",
        data_scope: "uncertain_segments_with_minimal_context",
        provider_id: null,
        model_id: null,
        confirmed: true,
      },
      "cloud-consent-0001",
    );

    let [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ "Idempotency-Key": "cloud-consent-0001" });

    fetchMock.mockResolvedValue(response({
      ...active,
      version: 2,
      state: "revoked",
      revoked_at: NOW,
    }));
    await revokeNarrationCloudConsent(
      NOVEL_ID,
      { consent_id: consentId, expected_version: 1 },
    );

    [, init] = fetchMock.mock.calls[1];
    expect(init?.method).toBe("DELETE");
    expect(JSON.parse(String(init?.body))).toEqual({
      consent_id: consentId,
      expected_version: 1,
    });
  });

  it("builds exactly metadata and binary reference parts", () => {
    const audio = new Blob([new Uint8Array([1, 2, 3, 4])], { type: "audio/wav" });
    const form = buildUploadedVoiceVersionFormData(uploadMetadata(), audio);
    const entries = Array.from(form.entries());

    expect(entries.map(([key]) => key)).toEqual(["metadata", "reference_audio"]);
    expect(JSON.parse(String(entries[0][1]))).toEqual(uploadMetadata());
    expect(entries[1][1]).toBeInstanceOf(Blob);
    expect((entries[1][1] as Blob).type).toBe("audio/wav");
  });

  it("does not set multipart Content-Type and validates the returned voice version", async () => {
    fetchMock.mockResolvedValue(response(uploadedVersion(), 201));
    const audio = new Blob([new Uint8Array([1, 2, 3, 4])], { type: "audio/wav" });

    const result = await createUploadedVoiceVersion(
      PROFILE_ID,
      uploadMetadata(),
      audio,
      "upload-reference-0001",
    );

    expect(result.source_type).toBe("uploaded");
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.body).toBeInstanceOf(FormData);
    expect(init?.headers).toEqual({
      Accept: "application/json",
      "Idempotency-Key": "upload-reference-0001",
    });
  });

  it("provides a pollable preview resource instead of treating 202 as ready audio", async () => {
    const previewId = "10000000-0000-4000-8000-000000000007";
    fetchMock.mockResolvedValue(response({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      preview_id: previewId,
      profile_id: PROFILE_ID,
      version_id: VERSION_ID,
      status: "running",
      job_id: "10000000-0000-4000-8000-000000000008",
      asset: null,
      temporary: true,
      expires_at: null,
      failure_code: null,
    }));

    const result = await getVoicePreview(previewId);

    expect(result.status).toBe("running");
    expect(result.asset).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toContain(`/voice-previews/${previewId}`);
  });

  it("creates an optional official preview without sending binding state", async () => {
    const previewId = "10000000-0000-4000-8000-000000000007";
    fetchMock.mockResolvedValue(response({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      preview_id: previewId,
      profile_id: PROFILE_ID,
      version_id: VERSION_ID,
      status: "queued",
      job_id: "10000000-0000-4000-8000-000000000008",
      asset: null,
      temporary: true,
      expires_at: null,
      failure_code: null,
    }, 202));

    const result = await createOfficialVoicePreview(
      NOVEL_ID,
      { preset_id: OFFICIAL_PRESET_EVIDENCE[0].presetId },
      "official-preview-0001",
    );

    expect(result.status).toBe("queued");
    expect(fetchMock).toHaveBeenCalledWith(
      `/ai-novel-world-2026/novels/${NOVEL_ID}/official-voice-previews`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ preset_id: OFFICIAL_PRESET_EVIDENCE[0].presetId }),
        headers: expect.objectContaining({ "Idempotency-Key": "official-preview-0001" }),
      }),
    );
  });

  it("rejects unsupported or empty reference audio before network I/O", async () => {
    expect(() => buildUploadedVoiceVersionFormData(
      uploadMetadata(),
      new Blob([new Uint8Array([1])], { type: "audio/mpeg" }),
    )).toThrow(/reference_audio.type/);
    expect(() => buildUploadedVoiceVersionFormData(
      uploadMetadata(),
      new Blob([], { type: "audio/wav" }),
    )).toThrow(/reference_audio.size/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses the character binding route and carries the explicit unset state", async () => {
    fetchMock.mockResolvedValue(response({
      contract_version: NARRATION_SETTINGS_API_VERSION,
      binding_id: null,
      novel_id: NOVEL_ID,
      character_id: CHARACTER_ID,
      binding_policy: "unset",
      profile_id: null,
      version_id: null,
      language: "zh-CN",
      version: 0,
      impact: {
        affected_chapter_count: 0,
        affected_segment_count: 0,
        historical_edition_count: 0,
        regeneration_required: false,
      },
      updated_at: null,
    }));

    const result = await putCharacterVoiceBinding(
      NOVEL_ID,
      CHARACTER_ID,
      {
        expected_version: 0,
        binding_policy: "unset",
        profile_id: null,
        version_id: null,
        language: "zh-CN",
      },
    );

    expect(result.binding_policy).toBe("unset");
    expect(fetchMock.mock.calls[0][0]).toContain(
      `/novels/${NOVEL_ID}/characters/${CHARACTER_ID}/voice-binding`,
    );
  });

  it("propagates AbortSignal into host fetch", async () => {
    fetchMock.mockResolvedValue(response(settingsResource()));
    const controller = new AbortController();

    await getNarrationSettings(NOVEL_ID, controller.signal);

    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});


describe("chapter narration production API client", () => {
  it("loads Context and Edition only from their exact request scope", async () => {
    fetchMock.mockResolvedValueOnce(response(chapterContext()));
    const context = await getDocumentNarrationContext(
      CHAPTER_DOCUMENT_ID,
      CHAPTER_EDITION_ID,
    );
    expect(context.active_edition_id).toBe(CHAPTER_EDITION_ID);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/ai-novel-world-2026/documents/${CHAPTER_DOCUMENT_ID}/narration-playback-context?active_edition_id=${CHAPTER_EDITION_ID}`,
    );

    fetchMock.mockResolvedValueOnce(response(chapterEdition()));
    const editionResource = await getNarrationEdition(CHAPTER_EDITION_ID);
    expect(editionResource.edition_id).toBe(CHAPTER_EDITION_ID);
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/ai-novel-world-2026/narration-editions/${CHAPTER_EDITION_ID}`,
    );

    fetchMock.mockResolvedValueOnce(response(chapterContext({
      document_id: "f1000000-0000-4000-8000-000000000099",
    })));
    await expect(getDocumentNarrationContext(CHAPTER_DOCUMENT_ID)).rejects.toThrow(
      /outer document state/u,
    );
    fetchMock.mockResolvedValueOnce(response(chapterEdition({
      edition_id: CHAPTER_TARGET_EDITION_ID,
    })));
    await expect(getNarrationEdition(CHAPTER_EDITION_ID)).rejects.toThrow(/edition_id/u);
  });

  it("loads frozen Edition voice identities from the dedicated versioned route", async () => {
    fetchMock.mockResolvedValue(response({
      contract_version: "narration-edition-voice-identities/1",
      edition_id: CHAPTER_EDITION_ID,
      items: [{
        profile_id: CHAPTER_PROFILE_ID,
        voice_version_id: CHAPTER_VOICE_VERSION_ID,
        display_name: "小雨",
        source_type: "preset",
        preset_id: "onnx.Xiaoyu",
        resolution_contract_version: "narration-edition-resolution/2",
        legacy_fallback: false,
      }],
    }));

    const identities = await getNarrationEditionVoiceIdentities(CHAPTER_EDITION_ID);

    expect(identities.items[0]?.display_name).toBe("小雨");
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/ai-novel-world-2026/narration-editions/${CHAPTER_EDITION_ID}/voice-identities`,
    );
  });

  it("rejects Context nested drift before the workbench can consume it", async () => {
    const drift = chapterContext();
    drift.edition_history.pointer_version = 5;
    fetchMock.mockResolvedValue(response(drift));

    await expect(getDocumentNarrationContext(CHAPTER_DOCUMENT_ID)).rejects.toThrow(
      /outer document state/u,
    );
  });

  it("puts Idempotency-Key only in the header and sends exact workflow JSON", async () => {
    fetchMock.mockResolvedValue(response(chapterWorkflow()));
    const request = {
      intent: "create" as const,
      expected_draft_version: 7,
      expected_content_hash: CHAPTER_SHA_A,
      expected_settings_version: 3,
      force_review: false,
    };

    await createNarrationWorkflow(
      CHAPTER_DOCUMENT_ID,
      request,
      "chapter-create-0001",
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.headers).toEqual(expect.objectContaining({
      "Idempotency-Key": "chapter-create-0001",
    }));
    expect(JSON.parse(String(init?.body))).toEqual(request);
    expect(String(init?.body)).not.toContain("idempotency");
    expect(String(init?.body)).not.toContain("owner_id");
    expect(String(init?.body)).not.toContain("workspace_id");

    await expect(createNarrationWorkflow(
      CHAPTER_DOCUMENT_ID,
      { ...request, idempotency_key: "spoofed" } as typeof request,
      "chapter-create-0002",
    )).rejects.toThrow(/unexpected or missing fields/u);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects Workflow intent/source drift and wrong recovery request identity", async () => {
    const request = {
      intent: "create" as const,
      expected_draft_version: 7,
      expected_content_hash: CHAPTER_SHA_A,
      expected_settings_version: 3,
      force_review: false,
    };
    fetchMock.mockResolvedValueOnce(response(chapterWorkflow({ intent: "update" })));
    await expect(createNarrationWorkflow(
      CHAPTER_DOCUMENT_ID,
      request,
      "chapter-create-0003",
    )).rejects.toThrow(/requested intent/u);

    fetchMock.mockResolvedValueOnce(response(chapterWorkflow({ source_content_hash: CHAPTER_SHA_C })));
    await expect(createNarrationWorkflow(
      CHAPTER_DOCUMENT_ID,
      request,
      "chapter-create-0004",
    )).rejects.toThrow(/saved source/u);

    fetchMock.mockResolvedValueOnce(response(chapterWorkflow({ request_id: CHAPTER_JOB_ID })));
    await expect(getNarrationWorkflow(CHAPTER_REQUEST_ID)).rejects.toThrow(/request_id/u);
  });

  it("rejects every switched target, CAS, mode, and start response drift", async () => {
    const request = {
      target_edition_id: CHAPTER_TARGET_EDITION_ID,
      expected_version: 4,
      switch_mode: "immediate" as const,
      start_segment_id: CHAPTER_SEGMENT_ID,
      playback_rate_millis: 1000,
      confirmed: true as const,
    };
    for (const drift of [
      { current_edition_id: CHAPTER_EDITION_ID },
      { pointer_version: 6 },
      { switch_mode: "next_playback", start_segment_id: null, playback_progress_id: null },
      { start_segment_id: CHAPTER_JOB_ID },
    ]) {
      fetchMock.mockResolvedValueOnce(response(chapterSwitchResponse(drift)));
      await expect(switchNarrationEdition(CHAPTER_DOCUMENT_ID, request)).rejects.toBeInstanceOf(
        ChapterNarrationContractError,
      );
    }
  });

  it("accepts exact immediate and next-playback switches and forwards AbortSignal", async () => {
    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(response(chapterSwitchResponse()));
    await expect(switchNarrationEdition(
      CHAPTER_DOCUMENT_ID,
      {
        target_edition_id: CHAPTER_TARGET_EDITION_ID,
        expected_version: 4,
        switch_mode: "immediate",
        start_segment_id: CHAPTER_SEGMENT_ID,
        playback_rate_millis: 1000,
        confirmed: true,
      },
      controller.signal,
    )).resolves.toMatchObject({ pointer_version: 5 });
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);

    fetchMock.mockResolvedValueOnce(response(chapterSwitchResponse({
      switch_mode: "next_playback",
      start_segment_id: null,
      playback_progress_id: null,
    })));
    await expect(switchNarrationEdition(CHAPTER_DOCUMENT_ID, {
      target_edition_id: CHAPTER_TARGET_EDITION_ID,
      expected_version: 4,
      switch_mode: "next_playback",
      start_segment_id: null,
      playback_rate_millis: 1000,
      confirmed: true,
    })).resolves.toMatchObject({ switch_mode: "next_playback" });
  });

  it("normalizes the strict production error contract without accepting legacy drift", async () => {
    fetchMock.mockResolvedValue(response({
      detail: {
        contract_version: NARRATION_PRODUCTION_API_VERSION,
        code: "VERSION_CONFLICT",
        message: "正文版本已经变化。",
        retryable: false,
        field: null,
        current_version: 5,
      },
    }, 409));
    await expect(getNarrationWorkflow(CHAPTER_REQUEST_ID)).rejects.toMatchObject({
      status: 409,
      detail: { code: "VERSION_CONFLICT", current_version: 5 },
    });
  });

  it("loads failed segments and accepts a 202 idempotent retry replay with AbortSignal", async () => {
    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(response(chapterFailedSegments()));
    const projection = await getFailedNarrationSegments(
      CHAPTER_EDITION_ID,
      controller.signal,
    );
    expect(projection.items[0]?.segment_id).toBe(CHAPTER_SEGMENT_ID);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/ai-novel-world-2026/narration-editions/${CHAPTER_EDITION_ID}/failed-segments`,
    );
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);

    fetchMock.mockResolvedValueOnce(response(chapterRetryResponse({ replayed: true }), 202));
    const request = {
      segment_ids: [CHAPTER_SEGMENT_ID],
      expected_request_version: 4,
      expected_manifest_revision: 7,
    };
    const result = await retryFailedNarrationSegments(
      CHAPTER_EDITION_ID,
      request,
      "failed-segment-retry-0001",
      controller.signal,
    );
    expect(result.replayed).toBe(true);
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/ai-novel-world-2026/narration-editions/${CHAPTER_EDITION_ID}/retry-failed-segments`,
    );
    const retryInit = fetchMock.mock.calls[1][1];
    expect(retryInit?.method).toBe("POST");
    expect(retryInit?.headers).toEqual(expect.objectContaining({
      "Idempotency-Key": "failed-segment-retry-0001",
    }));
    expect(retryInit?.signal).toBe(controller.signal);
    expect(JSON.parse(String(retryInit?.body))).toEqual(request);
    expect(String(retryInit?.body)).not.toContain("owner_id");
    expect(String(retryInit?.body)).not.toContain("workspace_id");
    expect(String(retryInit?.body)).not.toContain("idempotency");
  });

  it("rejects failed-segment scope drift, server reselection, and noncanonical input", async () => {
    fetchMock.mockResolvedValueOnce(response(chapterFailedSegments({
      edition_id: CHAPTER_TARGET_EDITION_ID,
    })));
    await expect(getFailedNarrationSegments(CHAPTER_EDITION_ID)).rejects.toThrow(
      /edition_id/u,
    );

    fetchMock.mockResolvedValueOnce(response(chapterRetryResponse({
      edition_id: CHAPTER_TARGET_EDITION_ID,
    }), 202));
    await expect(retryFailedNarrationSegments(
      CHAPTER_EDITION_ID,
      {
        segment_ids: [CHAPTER_SEGMENT_ID],
        expected_request_version: 4,
        expected_manifest_revision: 7,
      },
      "failed-segment-retry-0002",
    )).rejects.toThrow(/edition_id/u);

    fetchMock.mockResolvedValueOnce(response(chapterRetryResponse({
      accepted_segment_ids: [CHAPTER_FANOUT_SEGMENT_ID],
    }), 202));
    await expect(retryFailedNarrationSegments(
      CHAPTER_EDITION_ID,
      {
        segment_ids: [CHAPTER_SEGMENT_ID],
        expected_request_version: 4,
        expected_manifest_revision: 7,
      },
      "failed-segment-retry-0003",
    )).rejects.toThrow(/requested selection/u);

    await expect(retryFailedNarrationSegments(
      CHAPTER_EDITION_ID,
      {
        segment_ids: [CHAPTER_SEGMENT_ID],
        expected_request_version: 4,
        expected_manifest_revision: 7,
        owner_id: CHAPTER_NOVEL_ID,
      } as never,
      "failed-segment-retry-0004",
    )).rejects.toThrow(/unexpected or missing fields/u);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
