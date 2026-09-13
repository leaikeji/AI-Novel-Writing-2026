// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


describe("workbench narration manifest refresh and gap recovery", () => {
  const source = readFileSync(new URL("./workbench-v2.ts", import.meta.url), "utf8");

  it("uses in-place Manifest refresh instead of rebuilding the session", () => {
    expect(source).toContain("await session.refreshManifestInPlace()");
    expect(source).not.toContain("const refreshed = await session.refresh();");
    expect(source).toContain("narrationManifestRefreshAtRef.current = Date.now()");
  });

  it("continues an exact pending gap through the session intent fence", () => {
    expect(source).toContain('livePlayer.failure?.code === "PENDING_GAP"');
    expect(source).toContain("const result = await session.continuePendingGap();");
    expect(source).toContain('result.status === "rejected"');
  });

  it("limits full-book promotion to the same live run", () => {
    expect(source).toContain("const activeBookRunId = bookNarrationRef.current?.runId;");
    expect(source).toContain("liveQueue?.runId === activeBookRunId");
    expect(source).toContain('["preparing", "playing"].includes(liveQueue.phase)');
    expect(source).toContain(
      "currentBookNarrationChapter(liveQueue).documentId === currentDocument.id",
    );
    expect(source).toContain(
      "publishBookNarrationState(markBookNarrationPlaying(liveQueue));",
    );
  });

  it("re-arms unchanged idle, paused, or blocked polling without a second loop", () => {
    const refreshStart = source.indexOf("const hasPendingNarrationRenders =");
    const refreshEnd = source.indexOf("const startNarration =", refreshStart);
    const refreshEffect = source.slice(refreshStart, refreshEnd);
    expect(source).toContain("if (!refreshed.changed && narrationSessionRef.current === session)");
    expect(source).toContain("schedule(2_500);");
    expect(source).not.toContain("bookNarrationRecoveryTick");
    expect(refreshEffect).not.toContain("setInterval(");
  });

  it("refreshes while playing only once per segment boundary", () => {
    expect(source).toContain("narrationPlayingRefreshSegmentRef.current === segmentKey");
    expect(source).toContain("narrationPlayingRefreshSegmentRef.current = segmentKey");
    expect(source).toContain("Math.max(0, 2_500 - elapsed)");
  });

  it("does not refresh while buffering or preparing", () => {
    expect(source).toContain('["preparing", "buffering"].includes(playerPhase)');
  });

  it("continues polling from Manifest segment truth rather than stale Edition counters", () => {
    expect(source).toContain("const hasPendingNarrationRenders =");
    expect(source).toContain('["pending", "queued", "rendering"].includes(segment.render_status)');
    expect(source).not.toContain(
      '["created", "rendering", "partial_ready", "ready"].includes(edition.state)',
    );
  });

  it("cancels the one-shot timer when the effect scope changes", () => {
    expect(source).toContain("cancelled = true;");
    expect(source).toContain("if (handle !== null) clearTimeout(handle);");
    expect(source).toContain("if (narrationSessionRef.current !== session) return;");
  });

  it("keeps the editor mounted while generation or unresolved recovery makes it read-only", () => {
    const mountStart = source.indexOf("const editorShouldMount = editorOpen");
    const mountEnd = source.indexOf("React.useLayoutEffect", mountStart);
    const mountContract = source.slice(mountStart, mountEnd);

    expect(mountContract).not.toContain("!bodyGenerationState.active");
    expect(source).toContain(
      "editorSurfaceRef.current?.setEditable(!bodyGenerationState.active && !recovery && !busy && !recoveryLoadingRef.current);",
    );
    expect(mountContract).not.toContain("!recovery");
    expect(source).toContain("现有正文暂时只读，朗读可以继续");
  });

  it("marks adopted server text as diverged before applying it to the live surface", () => {
    const applyStart = source.indexOf("const applyWorkflowDocument =");
    const divergence = source.indexOf(
      "narrationSessionRef.current?.noteWorkingCopyChanged();",
      applyStart,
    );
    const documentUpdate = source.indexOf("documentRef.current = updated;", applyStart);

    expect(applyStart).toBeGreaterThan(-1);
    expect(divergence).toBeGreaterThan(applyStart);
    expect(documentUpdate).toBeGreaterThan(divergence);
  });
});
