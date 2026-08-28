import { describe, expect, it } from "vitest";

import {
  confirmEditionSelection,
  createExplicitNarrationUpdateIntent,
  deriveChapterNarrationState,
  selectEditionForConfirmation,
  type ActiveChapterPlayback,
  type ChapterNarrationStateInput,
} from "./chapter-narration-state";
import {
  EDITION_HISTORY_CONTRACT_VERSION,
  EditionHistoryContractError,
  parseDocumentEditionHistory,
} from "./edition-history";


const DOCUMENT = "20000000-0000-4000-8000-000000000001";
const CURRENT = "10000000-0000-4000-8000-000000000001";
const NEXT = "10000000-0000-4000-8000-000000000002";
const CURRENT_REVISION = "30000000-0000-4000-8000-000000000001";
const NEXT_REVISION = "30000000-0000-4000-8000-000000000002";
const SEGMENT = "40000000-0000-4000-8000-000000000001";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);


function historyPayload(options: {
  readonly workingHash?: string;
  readonly currentSourceHash?: string;
  readonly includeNext?: boolean;
  readonly nextSourceHash?: string;
  readonly pointerVersion?: number;
} = {}) {
  const workingHash = options.workingHash ?? SHA_A;
  const currentSourceHash = options.currentSourceHash ?? SHA_A;
  const currentSourceStatus = currentSourceHash === workingHash
    ? "current"
    : "working_copy_diverged";
  const item = (
    editionId: string,
    current: boolean,
    sourceHash: string,
  ) => ({
    edition_id: editionId,
    request_id: current
      ? "50000000-0000-4000-8000-000000000001"
      : "50000000-0000-4000-8000-000000000002",
    source_revision_id: current ? CURRENT_REVISION : NEXT_REVISION,
    source_content_hash: sourceHash,
    edition_fingerprint: current ? "c".repeat(64) : "d".repeat(64),
    state: "ready",
    created_at: current ? "2026-08-27T12:00:00Z" : "2026-08-27T12:30:00Z",
    manifest_revision: current ? 3 : 1,
    manifest_etag: current ? `"${"e".repeat(64)}"` : `"${"f".repeat(64)}"`,
    ready_segment_count: 8,
    total_segment_count: 8,
    is_current: current,
    source_status: current ? currentSourceStatus : "superseded",
    rights_available: true,
    playable: true,
    default_start_ready: true,
    resume_available: current,
    switch_allowed: true,
  });
  return {
    contract_version: EDITION_HISTORY_CONTRACT_VERSION,
    document_id: DOCUMENT,
    pointer_version: options.pointerVersion ?? 7,
    current_edition_id: CURRENT,
    working_copy_content_hash: workingHash,
    working_copy_draft_version: 12,
    editions: [
      item(CURRENT, true, currentSourceHash),
      ...(options.includeNext
        ? [item(NEXT, false, options.nextSourceHash ?? SHA_B)]
        : []),
    ],
  };
}


function playback(changes: Partial<ActiveChapterPlayback> = {}): ActiveChapterPlayback {
  return {
    editionId: CURRENT,
    phase: "playing",
    currentSegmentId: SEGMENT,
    currentOrdinal: 0,
    offsetMs: 450,
    durationMs: 1200,
    subtitle: {
      editionId: CURRENT,
      segmentId: SEGMENT,
      ordinal: 0,
      speakerLabel: "林晚",
      sourceText: "“旧稿的这句话。”",
      spokenText: "旧稿的这句话。",
    },
    ...changes,
  };
}


function input(options: {
  readonly history?: ReturnType<typeof parseDocumentEditionHistory>;
  readonly localHash?: string;
  readonly saveState?: "saved" | "dirty" | "saving" | "failed";
  readonly reviewOpen?: boolean;
  readonly playback?: ActiveChapterPlayback | null;
  readonly mapped?: ReadonlySet<string>;
} = {}): ChapterNarrationStateInput {
  const history = options.history ?? parseDocumentEditionHistory(historyPayload());
  return {
    documentId: DOCUMENT,
    generation: 4,
    history,
    workingCopy: {
      documentId: DOCUMENT,
      generation: 4,
      draftVersion: history.working_copy_draft_version,
      contentHash: options.localHash ?? history.working_copy_content_hash,
      saveState: options.saveState ?? "saved",
    },
    reviewOpen: options.reviewOpen ?? false,
    reviewSource: null,
    playback: options.playback === undefined ? playback() : options.playback,
    sessionMappedSegmentIds: options.mapped,
  };
}


describe("chapter narration source projection", () => {
  it("keeps an exact current Edition on the editable timeline", () => {
    const state = deriveChapterNarrationState(input());

    expect(state.sourceStatus).toBe("current");
    expect(state.timelineMode).toBe("exact-working-copy");
    expect(state.canDecorateCurrentSegment).toBe(true);
    expect(state.playerPlacement).toBe("full");
    expect(state.fullPlayerVisible).toBe(true);
    expect(state.subtitle.oldDraft).toBe(false);
    expect(state.explicitUpdateRequired).toBe(false);
  });

  it("keeps old audio playing while the edited sentence moves to immutable subtitles", () => {
    const state = deriveChapterNarrationState(input({
      localHash: SHA_B,
      saveState: "dirty",
      reviewOpen: true,
    }));

    expect(state.sourceStatus).toBe("working_copy_diverged");
    expect(state.sourceNotice.label).toContain("旧稿朗读");
    expect(state.timelineMode).toBe("immutable-edition-only");
    expect(state.canDecorateCurrentSegment).toBe(false);
    expect(state.playerPlacement).toBe("compact-in-review");
    expect(state.fullPlayerVisible).toBe(false);
    expect(state.compactPlayer).toMatchObject({ oldDraft: true, speakerLabel: "林晚" });
    expect(state.subtitle).toMatchObject({
      visible: true,
      oldDraft: true,
      sourceText: "“旧稿的这句话。”",
    });
    expect(state.explicitUpdateRequired).toBe(true);
  });

  it("allows only an explicitly verified session mapping to decorate a divergent sentence", () => {
    const mapped = deriveChapterNarrationState(input({
      localHash: SHA_B,
      saveState: "dirty",
      mapped: new Set([SEGMENT]),
    }));
    const unmapped = deriveChapterNarrationState(input({
      localHash: SHA_B,
      saveState: "dirty",
      mapped: new Set(),
    }));

    expect(mapped.timelineMode).toBe("session-safe-mapping");
    expect(mapped.canDecorateCurrentSegment).toBe(true);
    expect(unmapped.timelineMode).toBe("immutable-edition-only");
    expect(unmapped.canDecorateCurrentSegment).toBe(false);
  });

  it("projects an unsaved first edit as divergent before the server history hash changes", () => {
    const state = deriveChapterNarrationState({
      ...input({ saveState: "dirty", mapped: new Set([SEGMENT]) }),
      liveWorkingCopyDiverged: true,
    });

    expect(state.sourceStatus).toBe("working_copy_diverged");
    expect(state.timelineMode).toBe("session-safe-mapping");
    expect(state.canDecorateCurrentSegment).toBe(true);
    expect(state.explicitUpdateRequired).toBe(true);
    expect(state.availableCurrentSourceEditionIds).toEqual([]);
    expect(state.subtitle).toMatchObject({ visible: true, oldDraft: true });
  });

  it("hides the full player while review is open and no audio session is active", () => {
    const state = deriveChapterNarrationState(input({
      reviewOpen: true,
      playback: playback({ phase: "ended" }),
    }));
    expect(state.playerPlacement).toBe("hidden");
    expect(state.fullPlayerVisible).toBe(false);
    expect(state.compactPlayer).toBeNull();
  });

  it("treats an explicitly selected historical playback as historical without changing current", () => {
    const history = parseDocumentEditionHistory(historyPayload({ includeNext: true }));
    const state = deriveChapterNarrationState(input({
      history,
      playback: playback({
        editionId: NEXT,
        subtitle: {
          editionId: NEXT,
          segmentId: SEGMENT,
          ordinal: 0,
          speakerLabel: "旁白",
          sourceText: "历史正文",
          spokenText: "历史正文",
        },
      }),
    }));

    expect(state.sourceStatus).toBe("superseded");
    expect(state.currentEdition?.edition_id).toBe(CURRENT);
    expect(state.playbackEdition?.edition_id).toBe(NEXT);
    expect(state.history.current_edition_id).toBe(CURRENT);
  });
});


describe("explicit update barrier", () => {
  it("creates an update request only after a matching stable save receipt", () => {
    const state = deriveChapterNarrationState(input());
    expect(createExplicitNarrationUpdateIntent(state, {
      documentId: DOCUMENT,
      generation: 4,
      draftVersion: 12,
      contentHash: SHA_A,
      stable: true,
    }, {
      settingsVersion: 3,
      forceReview: false,
      idempotencyKey: "narration:update:chapter-12",
    })).toEqual({
      document_id: DOCUMENT,
      intent: "update",
      expected_draft_version: 12,
      expected_content_hash: SHA_A,
      expected_settings_version: 3,
      force_review: false,
      idempotency_key: "narration:update:chapter-12",
    });
  });

  it("rejects dirty state and stale document-generation receipts", () => {
    const dirty = deriveChapterNarrationState(input({
      localHash: SHA_B,
      saveState: "dirty",
    }));
    expect(() => createExplicitNarrationUpdateIntent(dirty, {
      documentId: DOCUMENT,
      generation: 4,
      draftVersion: 12,
      contentHash: SHA_B,
      stable: true,
    }, {
      settingsVersion: 1,
      forceReview: false,
      idempotencyKey: "narration:update:dirty",
    })).toThrow(/save[_ ]barrier/u);

    const saved = deriveChapterNarrationState(input());
    expect(() => createExplicitNarrationUpdateIntent(saved, {
      documentId: DOCUMENT,
      generation: 3,
      draftVersion: 12,
      contentHash: SHA_A,
      stable: true,
    }, {
      settingsVersion: 1,
      forceReview: false,
      idempotencyKey: "narration:update:stale",
    })).toThrow(/document lease/u);
  });
});


describe("two-step Edition switching", () => {
  it("selection is inert until explicit confirmation creates a CAS intent", () => {
    const history = parseDocumentEditionHistory(historyPayload({ includeNext: true }));
    const state = deriveChapterNarrationState(input({ history }));

    const pending = selectEditionForConfirmation(state, NEXT);
    expect(pending.confirmationRequired).toBe(true);
    expect(state.history.current_edition_id).toBe(CURRENT);
    expect(confirmEditionSelection(state, pending, "immediate", SEGMENT)).toEqual({
      document_id: DOCUMENT,
      edition_id: NEXT,
      expected_version: 7,
      switch_mode: "immediate",
      start_segment_id: SEGMENT,
    });
    expect(state.history.current_edition_id).toBe(CURRENT);
  });

  it("surfaces a ready current-source Edition but never switches to it automatically", () => {
    const history = parseDocumentEditionHistory(historyPayload({
      workingHash: SHA_B,
      currentSourceHash: SHA_A,
      includeNext: true,
      nextSourceHash: SHA_B,
    }));
    const state = deriveChapterNarrationState(input({ history }));

    expect(state.explicitUpdateRequired).toBe(true);
    expect(state.availableCurrentSourceEditionIds).toEqual([NEXT]);
    expect(state.currentEdition?.edition_id).toBe(CURRENT);
  });

  it("rejects a pending selection after pointer history advances", () => {
    const history = parseDocumentEditionHistory(historyPayload({ includeNext: true }));
    const state = deriveChapterNarrationState(input({ history }));
    const pending = selectEditionForConfirmation(state, NEXT);
    const advanced = deriveChapterNarrationState(input({
      history: parseDocumentEditionHistory(historyPayload({
        includeNext: true,
        pointerVersion: 8,
      })),
    }));
    expect(() => confirmEditionSelection(advanced, pending, "next_playback")).toThrow(
      /stale/u,
    );
  });

  it("allows a manifest-verified immediate start when chapter start and resume are absent", () => {
    const payload = historyPayload({ includeNext: true });
    payload.editions[1].default_start_ready = false;
    payload.editions[1].resume_available = false;
    payload.editions[1].switch_allowed = false;
    const state = deriveChapterNarrationState(input({
      history: parseDocumentEditionHistory(payload),
    }));

    expect(() => selectEditionForConfirmation(state, NEXT)).toThrow(/no legal/u);
    const pending = selectEditionForConfirmation(state, NEXT, SEGMENT);
    expect(confirmEditionSelection(state, pending, "immediate")).toEqual({
      document_id: DOCUMENT,
      edition_id: NEXT,
      expected_version: 7,
      switch_mode: "immediate",
      start_segment_id: SEGMENT,
    });
    expect(() => confirmEditionSelection(state, pending, "next_playback")).toThrow(
      /cannot be deferred/u,
    );
    expect(state.history.current_edition_id).toBe(CURRENT);
  });
});


describe("chapter state fencing", () => {
  it("rejects cross-document leases and cross-Edition subtitles", () => {
    const base = input();
    expect(() => deriveChapterNarrationState({
      ...base,
      workingCopy: { ...base.workingCopy, generation: 3 },
    })).toThrow(EditionHistoryContractError);
    expect(() => deriveChapterNarrationState(input({
      playback: playback({
        subtitle: {
          editionId: NEXT,
          segmentId: SEGMENT,
          ordinal: 0,
          speakerLabel: "旁白",
          sourceText: "错误版本",
          spokenText: "错误版本",
        },
      }),
    }))).toThrow(/playback Edition/u);
  });
});
