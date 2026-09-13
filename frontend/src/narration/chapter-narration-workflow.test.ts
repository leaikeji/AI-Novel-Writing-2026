import { describe, expect, it, vi } from "vitest";

import {
  ChapterNarrationWorkflowError,
  startChapterNarrationWorkflow,
  resumeChapterNarrationWorkflow,
  type ChapterNarrationWorkflowDependencies,
} from "./chapter-narration-workflow";
import type { NarrationSettingsResource } from "./contracts";
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


function dependencies(overrides: Partial<ChapterNarrationWorkflowDependencies> = {}) {
  return {
    getSettings: vi.fn(async () => settings()),
    createWorkflow: vi.fn(async () => workflow("queued", EDITION_ID)),
    getWorkflow: vi.fn(async () => workflow("queued", EDITION_ID)),
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


describe("resumeChapterNarrationWorkflow", () => {
  it("基础入口等分析完成后恢复旧音频，再等待可播放，不重复复核脚本", async () => {
    const oldId = "99999999-9999-4999-8999-999999999999";
    const recoverExisting = vi.fn(async () => ({ ...workflow("queued", EDITION_ID), request_id: oldId }));
    const getWorkflow = vi.fn(async (requestId: string) => requestId === oldId
      ? { ...workflow("partial_ready", EDITION_ID), request_id: oldId }
      : workflow("review_required"));
    const deps = dependencies({ createWorkflow: vi.fn(async () => workflow("analyzing")),
      recoverExisting, getWorkflow });
    const result = await startChapterNarrationWorkflow({ ...options(deps), reuseExistingAudio: true });
    expect(recoverExisting).toHaveBeenCalledOnce();
    expect(recoverExisting).toHaveBeenCalledWith(expect.objectContaining({
      workflow: expect.objectContaining({ workflow_state: "review_required" }),
      idempotencyKey: `chapter-tts:${ACTION_ID}:recover`,
    }));
    expect(result.workflow.request_id).toBe(oldId);
    expect(result.workflow.workflow_state).toBe("partial_ready");
    expect(deps.createWorkflow).toHaveBeenCalledOnce();
  });

  it("刷新后只恢复已知朗读请求，不保存或新建任务", async () => {
    const deps = dependencies({
      getWorkflow: vi.fn(async () => workflow("partial_ready", EDITION_ID)),
    });
    const input = options(deps);
    const progress = vi.fn();
    const onRestoring = vi.fn();
    const result = await resumeChapterNarrationWorkflow({
      ...input,
      currentRequestId: REQUEST_ID,
      onRestoring,
      onProgress: progress,
    });
    expect(result?.edition_id).toBe(EDITION_ID);
    expect(onRestoring).toHaveBeenCalledOnce();
    expect(deps.getWorkflow).toHaveBeenCalledWith(REQUEST_ID, expect.any(AbortSignal));
    expect(input.saveStableSource).not.toHaveBeenCalled();
    expect(deps.getSettings).not.toHaveBeenCalled();
    expect(deps.createWorkflow).not.toHaveBeenCalled();
    expect(progress.mock.calls.some(([value]) => value.step === "waiting")).toBe(true);
  });

  it("没有已知请求时不猜测、不新建", async () => {
    const deps = dependencies();
    expect(await resumeChapterNarrationWorkflow(options(deps))).toBeNull();
    expect(deps.getWorkflow).not.toHaveBeenCalled();
    expect(deps.createWorkflow).not.toHaveBeenCalled();
  });

  it("切章 Abort 拒绝旧请求响应", async () => {
    const controller = new AbortController();
    const deps = dependencies({
      getWorkflow: vi.fn(async () => {
        controller.abort();
        return workflow("rendering", EDITION_ID);
      }),
    });
    await expect(resumeChapterNarrationWorkflow({
      ...options(deps),
      currentRequestId: REQUEST_ID,
      signal: controller.signal,
    })).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("startChapterNarrationWorkflow", () => {
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

  it("默认等待窗口覆盖本地重模型排队，不在旧的 30 秒边界制造假失败", async () => {
    let nowCall = 0;
    const deps = dependencies({
      createWorkflow: vi.fn(async () => workflow("queued", EDITION_ID, null)),
      getWorkflow: vi.fn(async () => workflow("partial_ready", EDITION_ID, 1)),
      now: () => (nowCall++ === 0 ? 0 : 31_000),
    });

    const result = await startChapterNarrationWorkflow({
      ...options(deps),
      pollScheduleMs: [1],
    });

    expect(result.workflow.workflow_state).toBe("partial_ready");
    expect(deps.getWorkflow).toHaveBeenCalledOnce();
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
