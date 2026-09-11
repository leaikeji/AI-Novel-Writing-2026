// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


describe("workbench full-book narration gap recovery", () => {
  const source = readFileSync(new URL("./workbench-v2.ts", import.meta.url), "utf8");

  it("resumes a partial-ready gap through the session polling path", () => {
    const recoveryStart = source.indexOf("const pendingBookGapSegmentId = (");
    const refreshStart = source.indexOf(
      "const refreshed = await session.refresh();",
      recoveryStart,
    );

    expect(recoveryStart).toBeGreaterThan(-1);
    expect(refreshStart).toBeGreaterThan(recoveryStart);
    expect(source.slice(recoveryStart, refreshStart + 120)).toContain(
      "snapshot?.playerState?.failure !== null",
    );
    expect(source).toContain("await session.playSegment(");
    expect(source).toContain(
      '["created", "rendering", "partial_ready", "ready"].includes(edition.state)',
    );
  });

  it("limits automatic recovery to the live full-book run and current chapter", () => {
    expect(source).toContain('["preparing", "playing"].includes(activeBookQueue?.phase ?? "")');
    expect(source).toContain("activeBookQueueOwnsSession && !pendingBookGapSegmentId");
    expect(source).toContain("currentQueue.runId !== activeBookRunId");
    expect(source).toContain('["preparing", "playing"].includes(currentQueue.phase)');
    expect(source).toContain("currentBookNarrationChapter(currentQueue).documentId !== currentDocument.id");
    expect(source).toContain("narrationSessionRef.current !== session");
  });

  it("re-arms recovery when the same pending gap remains after a bounded attempt", () => {
    expect(source).toContain(
      "const [bookNarrationRecoveryTick, setBookNarrationRecoveryTick] = React.useState(0)",
    );
    expect(source).toContain(
      "setBookNarrationRecoveryTick((value: number) => value + 1);",
    );
    expect(source).toContain("bookNarrationRecoveryTick,");
  });

  it("promotes an initially partial chapter to playing after recovery starts", () => {
    expect(source).toContain('if (liveQueue.phase === "preparing")');
    expect(source).toContain(
      "publishBookNarrationState(markBookNarrationPlaying(liveQueue));",
    );
  });

  it("keeps explicit render failures stable so the user can open recovery controls", () => {
    const renderStatusStart = source.indexOf("const pendingBookGapRenderStatus =");
    const recoveryTimerStart = source.indexOf("const handle = setTimeout(() => {", renderStatusStart);

    expect(renderStatusStart).toBeGreaterThan(-1);
    expect(recoveryTimerStart).toBeGreaterThan(renderStatusStart);
    expect(source.slice(renderStatusStart, recoveryTimerStart)).toContain(
      'pendingBookGapRenderStatus === "failed" && !hasPendingNarrationRenders',
    );
  });

  it("rechecks a transient failed gap while the rest of the chapter is still rendering", () => {
    expect(source).toContain("snapshot?.playerState?.failure !== null");
    expect(source).toContain(
      "const bookGapPlaybackSegmentId = pendingBookGapSegmentId;",
    );
    expect(source).toContain("const refreshed = await session.refresh();");
    expect(source).toContain("const latestHasPendingRenders = latestSegments.some");
  });

  it("refreshes a stale partial manifest even when the live Edition is already ready", () => {
    expect(source).toContain(
      '["created", "rendering", "partial_ready", "ready"].includes(edition.state)',
    );
  });

  it("stops generic manifest polling after only terminal failures remain", () => {
    expect(source).toContain("const hasPendingNarrationRenders =");
    expect(source).toContain('["pending", "queued", "rendering"].includes(segment.render_status)');
    expect(source).toContain("(!pendingBookGapSegmentId && !hasPendingNarrationRenders)");
  });
});
