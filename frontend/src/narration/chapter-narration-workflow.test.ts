import { describe, expect, it, vi } from "vitest";

import {
  ChapterNarrationWorkflowError,
  startChapterNarrationWorkflow,
  type ChapterNarrationWorkflowDependencies,
} from "./chapter-narration-workflow";
import type { NarrationSettingsResource, VoicePreparationSnapshot } from "./contracts";
import type { NarrationWorkflowResource } from "./chapter-contracts";


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "22222222-2222-4222-8222-222222222222";
const REQUEST_ID = "33333333-3333-4333-8333-333333333333";
const REVISION_ID = "44444444-4444-4444-8444-444444444444";
const SCRIPT_ID = "55555555-5555-4555-8555-555555555555";
const EDITION_ID = "66666666-6666-4666-8666-666666666666";
const ACTION_ID = "77777777-7777-4777-8777-777777777777";
const HASH = "a".repeat(64);


function settings(exists = true): NarrationSettingsResource {
  return {
    contract_version: "narration-settings-api/1",
    schema_version: "narration-settings/1",
    novel_id: NOVEL_ID,
    settings_id: exists ? "88888888-8888-4888-8888-888888888888" : null,
    exists,
    version: exists ? 3 : 0,
    values: {
      narrator: null,
      language: "zh-CN",
      output_format: "m4a_aac_lc",
      script_review_policy: "blockers_only",
      analysis_mode: "local_rules_only",
      text_rules: {
        read_chapter_title: false,
        read_author_notes: false,
        read_section_breaks: false,
        first_person_mode: "narrator",
        first_person_character_id: null,
        inner_monologue_mode: "character",
      },
      timing: {
        sentence_gap_ms: 120,
        paragraph_gap_ms: 360,
        section_gap_ms: 700,
      },
      casting: {
        anonymous_reuse_scope: "chapter",
        same_scene_voice_deduplication: true,
        unknown_speaker_action: "block",
      },
      playback: { playback_rate: 1, volume: 1 },
    },
    updated_at: exists ? "2026-08-27T00:00:00Z" : null,
  };
}


function workflow(
  state: NarrationWorkflowResource["workflow_state"],
  editionId: string | null = null,
  manifestRevision: number | null = editionId ? 1 : null,
): NarrationWorkflowResource {
  return {
    contract_version: "narration-production-api/1",
    request_id: REQUEST_ID,
    intent: "create",
    request_version: 2,
    workflow_state: state,
    source_revision_id: REVISION_ID,
    source_content_hash: HASH,
    settings_fingerprint: "b".repeat(64),
    warning_count: 0,
    blocker_count: state === "review_required" ? 1 : 0,
    script_version_id: SCRIPT_ID,
    edition_id: editionId,
    current_manifest_revision: manifestRevision,
    job_ids: [],
    replayed: false,
  };
}


function preparation(
  state: VoicePreparationSnapshot["state"],
  narrationRequestId: string | null,
): VoicePreparationSnapshot {
  const terminal = ["ready", "ready_with_warnings", "failed", "cancelled", "superseded"]
    .includes(state);
  return {
    contractVersion: "narration-voice-preparation/1",
    commandId: "99999999-9999-4999-8999-999999999999",
    state,
    serverNow: "2026-09-03T00:00:00Z",
    progressCurrent: narrationRequestId === null ? 1 : 2,
    progressTotal: 2,
    preflightRequestId: REQUEST_ID,
    preflightScriptVersionId: SCRIPT_ID,
    chapterReady: narrationRequestId !== null,
    backgroundRemaining: 0,
    continuationState: narrationRequestId === null ? "pending" : "created",
    narrationRequestId,
    currentTarget: null,
    preserved: [],
    generated: [],
    fallback: [],
    failed: [],
    cancellable: !terminal,
    retryable: false,
    terminal,
    failureCode: null,
    updatedAt: "2026-09-03T00:00:00Z",
  };
}


function dependencies(overrides: Partial<ChapterNarrationWorkflowDependencies> = {}) {
  return {
    getSettings: vi.fn(async () => settings()),
    createWorkflow: vi.fn(async () => workflow("queued", EDITION_ID)),
    getWorkflow: vi.fn(async () => workflow("queued", EDITION_ID)),
    createVoicePreparation: vi.fn(async () => {
      throw new Error("unexpected voice preparation call");
    }),
    getVoicePreparation: vi.fn(async () => {
      throw new Error("unexpected voice preparation poll");
    }),
    createActionId: () => ACTION_ID,
    delay: vi.fn(async () => undefined),
    now: () => 0,
    ...overrides,
  } satisfies ChapterNarrationWorkflowDependencies;
}


function options(deps: ChapterNarrationWorkflowDependencies) {
  return {
    novelId: NOVEL_ID,
    documentId: DOCUMENT_ID,
    generation: 4,
    intent: "create" as const,
    forceReview: false,
    saveStableSource: vi.fn(async () => ({
      documentId: DOCUMENT_ID,
      draftVersion: 9,
      contentHash: HASH,
    })),
    isGenerationCurrent: () => true,
    dependencies: deps,
  };
}


describe("startChapterNarrationWorkflow", () => {
  it("一次智能朗读先准备人物声音并复用服务端续接的正式请求", async () => {
    const createVoicePreparation = vi.fn(async () => preparation("preparing", null));
    const getVoicePreparation = vi.fn(async () => preparation("ready", REQUEST_ID));
    const deps = dependencies({
      createVoicePreparation,
      getVoicePreparation,
      getWorkflow: vi.fn(async () => workflow("partial_ready", EDITION_ID)),
    });

    const result = await startChapterNarrationWorkflow({
      ...options(deps),
      automaticVoicePreparationEnabled: true,
      pollScheduleMs: [1],
    });

    expect(createVoicePreparation).toHaveBeenCalledWith(
      NOVEL_ID,
      expect.objectContaining({
        document_id: DOCUMENT_ID,
        expected_draft_version: 9,
        expected_content_hash: HASH,
        expected_settings_version: 3,
      }),
      `chapter-voice-prepare:${ACTION_ID}`,
      expect.any(AbortSignal),
    );
    expect(getVoicePreparation).toHaveBeenCalledTimes(1);
    expect(deps.createWorkflow).not.toHaveBeenCalled();
    expect(result.workflow.request_id).toBe(REQUEST_ID);
  });

  it("完成保存屏障后才读取设置并创建严格作用域请求", async () => {
    const order: string[] = [];
    const deps = dependencies({
      getSettings: vi.fn(async () => { order.push("settings"); return settings(); }),
      createWorkflow: vi.fn(async (_documentId, request, key) => {
        order.push("request");
        expect(request).toEqual({
          intent: "create",
          expected_draft_version: 9,
          expected_content_hash: HASH,
          expected_settings_version: 3,
          force_review: false,
        });
        expect(key).toBe(`chapter-tts:${ACTION_ID}`);
        return workflow("partial_ready", EDITION_ID);
      }),
    });
    const input = options(deps);
    input.saveStableSource = vi.fn(async () => {
      order.push("save");
      return { documentId: DOCUMENT_ID, draftVersion: 9, contentHash: HASH };
    });

    const result = await startChapterNarrationWorkflow(input);

    expect(order).toEqual(["save", "settings", "request"]);
    expect(result.workflow.edition_id).toBe(EDITION_ID);
  });

  it("设置尚未正式保存时 fail closed 且不创建请求", async () => {
    const deps = dependencies({ getSettings: vi.fn(async () => settings(false)) });

    await expect(startChapterNarrationWorkflow(options(deps))).rejects.toMatchObject({
      code: "SETTINGS_REQUIRED",
    } satisfies Partial<ChapterNarrationWorkflowError>);
    expect(deps.createWorkflow).not.toHaveBeenCalled();
  });

  it("轮询分析态直到 review_required 并停止，不伪造 Edition", async () => {
    const deps = dependencies({
      createWorkflow: vi.fn(async () => workflow("analyzing")),
      getWorkflow: vi.fn(async () => workflow("review_required")),
      now: (() => {
        let value = 0;
        return () => value++;
      })(),
    });

    const result = await startChapterNarrationWorkflow({
      ...options(deps),
      pollScheduleMs: [1],
      pollTimeoutMs: 100,
    });

    expect(result.workflow.workflow_state).toBe("review_required");
    expect(result.workflow.edition_id).toBeNull();
    expect(deps.getWorkflow).toHaveBeenCalledTimes(1);
  });

  it("已有 Edition 但首个 Manifest 尚未发布时继续轮询", async () => {
    const deps = dependencies({
      createWorkflow: vi.fn(async () => workflow("queued", EDITION_ID, null)),
      getWorkflow: vi.fn()
        .mockResolvedValueOnce(workflow("rendering", EDITION_ID, null))
        .mockResolvedValueOnce(workflow("partial_ready", EDITION_ID, 1)),
      now: (() => {
        let value = 0;
        return () => value++;
      })(),
    });

    const result = await startChapterNarrationWorkflow({
      ...options(deps),
      pollScheduleMs: [1],
      pollTimeoutMs: 100,
    });

    expect(result.workflow).toMatchObject({
      workflow_state: "partial_ready",
      edition_id: EDITION_ID,
      current_manifest_revision: 1,
    });
    expect(deps.getWorkflow).toHaveBeenCalledTimes(2);
    expect(deps.delay).toHaveBeenCalledTimes(2);
  });

  it("已有 Manifest 但仍在 queued/rendering 时等待首个可播放句段", async () => {
    const deps = dependencies({
      createWorkflow: vi.fn(async () => workflow("queued", EDITION_ID, 1)),
      getWorkflow: vi.fn()
        .mockResolvedValueOnce(workflow("rendering", EDITION_ID, 2))
        .mockResolvedValueOnce(workflow("partial_ready", EDITION_ID, 3)),
      now: (() => {
        let value = 0;
        return () => value++;
      })(),
    });

    const result = await startChapterNarrationWorkflow({
      ...options(deps),
      pollScheduleMs: [1],
      pollTimeoutMs: 100,
    });

    expect(result.workflow).toMatchObject({
      workflow_state: "partial_ready",
      current_manifest_revision: 3,
    });
    expect(deps.getWorkflow).toHaveBeenCalledTimes(2);
    expect(deps.delay).toHaveBeenCalledTimes(2);
  });

  it.each(["partial_ready", "ready"] as const)(
    "拒绝 %s 在没有 Manifest 时伪装成可播放",
    async (state) => {
      const deps = dependencies({
        createWorkflow: vi.fn(async () => workflow(state, EDITION_ID, null)),
      });

      await expect(startChapterNarrationWorkflow(options(deps))).rejects.toMatchObject({
        code: "INVALID_INPUT",
      } satisfies Partial<ChapterNarrationWorkflowError>);
      expect(deps.getWorkflow).not.toHaveBeenCalled();
    },
  );

  it("章节 generation 变化后拒绝应用旧响应", async () => {
    let current = true;
    const deps = dependencies({
      getSettings: vi.fn(async () => {
        current = false;
        return settings();
      }),
    });

    await expect(startChapterNarrationWorkflow({
      ...options(deps),
      isGenerationCurrent: () => current,
    })).rejects.toMatchObject({ code: "STALE_GENERATION" });
    expect(deps.createWorkflow).not.toHaveBeenCalled();
  });
});
