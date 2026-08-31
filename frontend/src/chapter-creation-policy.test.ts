import { describe, expect, it } from "vitest";

import {
  CHAPTER_CREATION_REQUIRES_VOLUME_MESSAGE,
  chapterCreationBlockedReason,
  chapterPreparationResponseIsCurrent,
  chapterWizardPreparationState,
  chapterWizardPreparationTransition,
  startChapterPreparationRequest,
} from "./chapter-creation-policy";


describe("chapter creation prerequisites", () => {
  it("没有分卷时阻止新增章节并给出明确提示", () => {
    expect(chapterCreationBlockedReason(0)).toBe(CHAPTER_CREATION_REQUIRES_VOLUME_MESSAGE);
  });

  it("至少存在一个分卷时允许进入章节创建流程", () => {
    expect(chapterCreationBlockedReason(1)).toBeNull();
  });
});


describe("chapter wizard preparation state", () => {
  it("关闭时保持 idle，打开首帧直接进入 loading", () => {
    expect(chapterWizardPreparationState({
      open: false,
      requestPhase: "not_started",
      draftState: null,
      scopeValid: true,
    })).toBe("idle");
    expect(chapterWizardPreparationState({
      open: true,
      requestPhase: "not_started",
      draftState: null,
      scopeValid: true,
    })).toBe("loading");
  });

  it("请求失败后显示 failure，不继续伪装成 loading", () => {
    expect(chapterWizardPreparationState({
      open: true,
      requestPhase: "failed",
      draftState: null,
      scopeValid: true,
    })).toBe("failure");
  });

  it("只有成功返回、草稿未完成且分卷范围有效时 ready", () => {
    expect(chapterWizardPreparationState({
      open: true,
      requestPhase: "succeeded",
      draftState: "draft",
      scopeValid: true,
    })).toBe("ready");
    expect(chapterWizardPreparationState({
      open: true,
      requestPhase: "succeeded",
      draftState: "draft",
      scopeValid: false,
    })).toBe("failure");
  });

  it("已完成草稿恢复原章节，不重新进入六步向导", () => {
    expect(chapterWizardPreparationTransition({
      open: true,
      requestPhase: "succeeded",
      draftState: "completed",
      scopeValid: true,
      completedDocumentId: "document-1",
    })).toEqual({ state: "loading", effect: "restore_completed_document" });
    expect(chapterWizardPreparationTransition({
      open: true,
      requestPhase: "succeeded",
      draftState: "completed",
      scopeValid: true,
      completedDocumentId: null,
    })).toEqual({ state: "failure", effect: "none" });
  });
});


describe("chapter preparation request scope", () => {
  it("首次打开、retry、关闭重开和切书后打开都分配不复用的 generation", () => {
    const firstOpen = startChapterPreparationRequest(0, "novel-a", "draft-a");
    const retry = startChapterPreparationRequest(firstOpen.scope.requestGeneration, "novel-a", "draft-a");
    const reopen = startChapterPreparationRequest(retry.scope.requestGeneration, "novel-a", "draft-a");
    const switchedNovel = startChapterPreparationRequest(reopen.scope.requestGeneration, "novel-b", "draft-b");

    expect([firstOpen, retry, reopen, switchedNovel].map((item) => item.scope.requestGeneration))
      .toEqual([1, 2, 3, 4]);
    expect([firstOpen, retry, reopen, switchedNovel].every((item) => item.requestPhase === "loading"))
      .toBe(true);
  });

  it("Abort 或任一 scope 字段过期时拒绝提交响应和错误", () => {
    const oldRequest = startChapterPreparationRequest(7, "novel-a", "draft-a");
    const activeRequest = startChapterPreparationRequest(
      oldRequest.scope.requestGeneration,
      "novel-a",
      "draft-a",
    );

    expect(chapterPreparationResponseIsCurrent(activeRequest.scope, activeRequest.scope)).toBe(true);
    expect(chapterPreparationResponseIsCurrent(activeRequest.scope, oldRequest.scope)).toBe(false);
    expect(chapterPreparationResponseIsCurrent(activeRequest.scope, {
      ...activeRequest.scope,
      novelId: "novel-b",
    })).toBe(false);
    expect(chapterPreparationResponseIsCurrent(activeRequest.scope, {
      ...activeRequest.scope,
      draftKey: "draft-b",
    })).toBe(false);
    expect(chapterPreparationResponseIsCurrent(activeRequest.scope, activeRequest.scope, true)).toBe(false);
    expect(chapterPreparationResponseIsCurrent(null, activeRequest.scope)).toBe(false);
  });

  it("拒绝无法保证继续单调递增的 generation", () => {
    expect(() => startChapterPreparationRequest(-1, "novel-a", "draft-a")).toThrow(RangeError);
    expect(() => startChapterPreparationRequest(Number.MAX_SAFE_INTEGER, "novel-a", "draft-a"))
      .toThrow(RangeError);
  });
});
