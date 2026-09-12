// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


describe("VC43 studio chapter wizard integration", () => {
  const source = readFileSync(new URL("./workbench-studio.ts", import.meta.url), "utf8");

  it("blocks before allocating a draft key when no real volume exists", () => {
    const effectStart = source.indexOf("React.useEffect(() => {\n    if (!open) return;\n    if (!targetVolume?.id)");
    const keyAllocation = source.indexOf("if (!draftKeyRef.current)", effectStart);
    expect(effectStart).toBeGreaterThan(-1);
    expect(keyAllocation).toBeGreaterThan(effectStart);
    expect(source.slice(effectStart, keyAllocation)).toContain("CHAPTER_CREATION_REQUIRES_VOLUME_MESSAGE");
  });

  it("uses an explicit request phase, monotonic generation, abort, and full scope checks", () => {
    expect(source).toContain('React.useState("not_started" as ChapterWizardRequestPhase)');
    expect(source).toContain("startChapterPreparationRequest(");
    expect(source).toContain("requestGenerationRef.current = started.scope.requestGeneration");
    expect(source).toContain("preparationAbortRef.current?.abort()");
    expect(source.match(/chapterPreparationResponseIsCurrent\(/g)?.length).toBeGreaterThanOrEqual(4);
    expect(source).toContain("setPreparationAttempt((current: number) => current + 1)");
  });

  it("restores completed drafts and reports a recovered volume without creating again", () => {
    expect(source).toContain('transition.effect === "restore_completed_document"');
    expect(source).toContain('apiRequest<DocumentRecord>(`/documents/${next.completed_document_id}`');
    expect(source).toContain("onCompleted(completed)");
    expect(source).toContain('next.recovery?.kind === "volume_rebound"');
    expect(source).toContain("原章节草稿已恢复，并已重新绑定到当前有效分卷");
  });

  it("derives preview ordinals canonically and only submits semantic names", () => {
    expect(source).toContain("canonicalChapterDocuments(novel)");
    expect(source).toContain("nextChapterOrdinalForVolume(novel, targetVolumeId)");
    expect(source).toContain("title: chapterTitleForStorage(chapterNumber, overrides.title ?? chapterTitle)");
    expect(source).toContain("const storedTitle = volumeTitleForStorage(volumeNumber, volumeTitle)");
  });

  it("creates in the selected volume and keeps that target visible through confirmation", () => {
    expect(source).toContain("targetVolumeId: selectedChapterVolume?.id ? String(selectedChapterVolume.id) : null");
    expect(source).toContain("String(volume.id) === requestedTargetVolumeId");
    expect(source).toContain('"aria-label": "目标分卷"');
    expect(source).toContain('h("dt", null, "目标分卷"), h("dd", null, targetVolumeLabel)');
    expect(source).toContain("requestedTargetVolumeId, volumeScopeKey");
  });

  it("lets authors with existing prose create a blank chapter without invoking AI", () => {
    expect(source).toContain("const completeManualEntry = async () => {");
    expect(source).toContain('manual_entry: true');
    expect(source).toContain('outline_text: expectationText.trim() || "作者选择跳过 AI，直接填写正文；本章章纲以作者最终保存的正文为准。"');
    expect(source).toContain("onClick: () => void completeManualEntry()");
    expect(source).toContain("跳过 AI，创建空白章节并直接填写");
  });

  it("lets a resumed chapter wizard return from role configuration to manual entry", () => {
    expect(source).toContain('onClick: () => void changeStep(1) }, "返回线索选择"');
  });
});
