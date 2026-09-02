import { describe, expect, it } from "vitest";

import type { NarrationEditionVoiceIdentity } from "./chapter-contracts";
import {
  INITIAL_CHAPTER_PLAYER_LAYOUT_STATE,
  LEGACY_EDITION_VOICE_NAME,
  chapterPlaybackHasEnded,
  deriveChapterPlayerView,
  formatChapterPlayerTime,
  resolveChapterPlaybackStartPosition,
  transitionChapterPlayerLayout,
} from "./chapter-player-view-state";
import type { NarrationPlayerState } from "./narration-player";
import type { ManifestSegmentV2 } from "./playback-contracts";


const SEGMENT_1 = "40000000-0000-4000-8000-000000000001";
const SEGMENT_2 = "40000000-0000-4000-8000-000000000002";
const SEGMENT_3 = "40000000-0000-4000-8000-000000000003";


function playerState(): NarrationPlayerState {
  return Object.freeze({
    phase: "playing",
    currentSegmentId: SEGMENT_2,
    currentOrdinal: 1,
    offsetMs: 500,
    durationMs: 2_000,
    rate: 1,
    volume: 0.8,
    followPaused: false,
    backend: "media-element",
    source: "default",
    failure: null,
  });
}


function manifestSegment(
  segmentId: string,
  ordinal: number,
  state: ManifestSegmentV2["render_status"],
  durationMs: number | null,
  gapAfterMs = 0,
): ManifestSegmentV2 {
  return Object.freeze({
    segment_id: segmentId,
    ordinal,
    paragraph_ordinal: ordinal,
    source_block_key: `paragraph-${ordinal}`,
    source_start_utf16: ordinal * 4,
    source_end_utf16: ordinal * 4 + 3,
    gap_after_ms: gapAfterMs,
    render_status: state,
    audio: durationMs === null ? null : Object.freeze({
      url: `/media/${segmentId}`,
      actual_sha256: "a".repeat(64),
      duration_ms: durationMs,
      sample_rate: 48_000,
      channels: 2,
      etag: `"${"b".repeat(64)}"`,
    }),
    failure: null,
  });
}


function voiceIdentity(legacy = false): NarrationEditionVoiceIdentity {
  return Object.freeze({
    profile_id: "10000000-0000-4000-8000-000000000001",
    voice_version_id: "20000000-0000-4000-8000-000000000001",
    display_name: legacy ? LEGACY_EDITION_VOICE_NAME : "林晚的雨夜声线",
    source_type: legacy ? null : "generated",
    preset_id: null,
    resolution_contract_version: legacy
      ? "narration-edition-resolution/1"
      : "narration-edition-resolution/2",
    legacy_fallback: legacy,
  });
}


describe("chapter player view state", () => {
  it("keeps compact, expanded, and failure details as an explicit pure state machine", () => {
    const expanded = transitionChapterPlayerLayout(
      INITIAL_CHAPTER_PLAYER_LAYOUT_STATE,
      { type: "toggle-expanded" },
    );
    expect(expanded.mode).toBe("expanded");
    expect(transitionChapterPlayerLayout(expanded, { type: "toggle-expanded" }).mode).toBe("compact");
    expect(transitionChapterPlayerLayout(expanded, {
      type: "open-failure-details",
      failureCount: 2,
    }).mode).toBe("failure-details");
    expect(transitionChapterPlayerLayout(expanded, {
      type: "open-failure-details",
      failureCount: 0,
    })).toBe(expanded);
    expect(transitionChapterPlayerLayout(
      { mode: "failure-details" },
      { type: "failures-cleared" },
    ).mode).toBe("compact");
  });

  it("projects playback, source, generation, and layout-independent metrics without collapsing them", () => {
    const view = deriveChapterPlayerView({
      contentPhase: "ready",
      sourceKind: "historical",
      playerState: playerState(),
      segmentIds: [SEGMENT_1, SEGMENT_2, SEGMENT_3],
      manifestSegments: [
        manifestSegment(SEGMENT_1, 0, "ready", 1_000, 100),
        manifestSegment(SEGMENT_2, 1, "ready", 2_000),
        manifestSegment(SEGMENT_3, 2, "rendering", null),
      ],
      voiceIdentities: [voiceIdentity()],
    });

    expect(view).toMatchObject({
      contentPhase: "ready",
      playbackPhase: "playing",
      playbackLabel: "正在播放",
      sourceKind: "historical",
      sourceLabel: "历史版本",
      currentTimeMs: 1_600,
      currentTimeLabel: "0:01",
      currentTimeBasis: "chapter",
      playableDurationMs: 3_100,
      playableDurationLabel: "0:03",
      voiceSummary: "林晚的雨夜声线 · 高级调音",
    });
    expect(view.generation).toMatchObject({
      state: "partial",
      readyCount: 2,
      pendingCount: 1,
      completedCount: 2,
      completionPercent: 67,
    });
  });

  it("shows a persisted idle position as resumable progress instead of claiming it was never played", () => {
    const restored: NarrationPlayerState = Object.freeze({
      ...playerState(),
      phase: "idle",
      currentSegmentId: SEGMENT_2,
      currentOrdinal: 1,
      offsetMs: 450,
      backend: null,
      source: null,
    });
    const view = deriveChapterPlayerView({
      contentPhase: "ready",
      sourceKind: "current",
      playerState: restored,
      segmentIds: [SEGMENT_1, SEGMENT_2, SEGMENT_3],
      segmentStates: ["ready", "ready", "ready"],
    });

    expect(view.playbackPhase).toBe("idle");
    expect(view.playbackLabel).toBe("上次停在第 2 段");
    expect(view.playbackLabel).not.toBe("尚未播放");
  });

  it("recognizes a restored idle cursor at the exact chapter end", () => {
    const restored: NarrationPlayerState = Object.freeze({
      ...playerState(),
      phase: "idle",
      currentSegmentId: SEGMENT_3,
      currentOrdinal: 2,
      offsetMs: 3_000,
      durationMs: 0,
      backend: null,
      source: null,
    });
    const manifest = [
      manifestSegment(SEGMENT_1, 0, "ready", 1_000),
      manifestSegment(SEGMENT_2, 1, "ready", 2_000),
      manifestSegment(SEGMENT_3, 2, "ready", 3_000),
    ];
    const view = deriveChapterPlayerView({
      contentPhase: "ready",
      sourceKind: "current",
      playerState: restored,
      segmentIds: [SEGMENT_1, SEGMENT_2, SEGMENT_3],
      manifestSegments: manifest,
    });

    expect(chapterPlaybackHasEnded(restored, 3, 3_000)).toBe(true);
    expect(view.playbackLabel).toBe("本章播放结束");
    expect(resolveChapterPlaybackStartPosition(restored, 3, 3_000)).toEqual({
      ordinal: 0,
      offsetMs: 0,
      resumeExistingSession: false,
    });
  });

  it("fails timing closed on a misaligned manifest while retaining exact segment generation states", () => {
    const view = deriveChapterPlayerView({
      contentPhase: "ready",
      sourceKind: "current",
      playerState: playerState(),
      segmentIds: [SEGMENT_1, SEGMENT_2],
      segmentStates: ["ready", "failed"],
      manifestSegments: [
        manifestSegment(SEGMENT_2, 0, "ready", 1_000),
        manifestSegment(SEGMENT_1, 1, "ready", 2_000),
      ],
    });

    expect(view.playableDurationMs).toBeNull();
    expect(view.playableDurationLabel).toBe("待计算");
    expect(view.currentTimeBasis).toBe("segment");
    expect(view.currentTimeMs).toBe(500);
    expect(view.generation.failedCount).toBe(1);
  });

  it("never substitutes a current profile name for a legacy Edition identity", () => {
    const identity = voiceIdentity(true);
    const view = deriveChapterPlayerView({
      contentPhase: "ready",
      sourceKind: "historical",
      playerState: null,
      segmentIds: [SEGMENT_1],
      segmentStates: ["ready"],
      voiceIdentities: [identity],
    });

    expect(view.voiceSummary).toBe(`${LEGACY_EDITION_VOICE_NAME} · 历史音色标识`);
    expect(view.voiceIdentities[0]).toEqual({
      key: identity.voice_version_id,
      displayName: LEGACY_EDITION_VOICE_NAME,
      sourceLabel: "历史音色标识",
      legacy: true,
    });
  });

  it("summarizes multiple frozen voices without exposing Edition jargon", () => {
    const first = voiceIdentity();
    const second = Object.freeze({
      ...voiceIdentity(),
      voice_version_id: "30000000-0000-4000-8000-000000000003",
      display_name: "沈砥的案发现场声线",
    });
    const view = deriveChapterPlayerView({
      contentPhase: "ready",
      sourceKind: "current",
      playerState: null,
      segmentIds: [SEGMENT_1],
      segmentStates: ["ready"],
      voiceIdentities: [first, second],
    });

    expect(view.voiceSummary).toBe("2 个冻结声音");
    expect(view.voiceSummary).not.toContain("Edition");
  });

  it("formats long chapter time without locale-dependent output", () => {
    expect(formatChapterPlayerTime(0)).toBe("0:00");
    expect(formatChapterPlayerTime(65_999)).toBe("1:05");
    expect(formatChapterPlayerTime(3_661_000)).toBe("1:01:01");
  });

  it("restarts from the first sentence after the chapter has ended", () => {
    expect(resolveChapterPlaybackStartPosition(Object.freeze({
      ...playerState(),
      phase: "ended",
      currentSegmentId: SEGMENT_3,
      currentOrdinal: 2,
      offsetMs: 1_000,
      durationMs: 1_000,
    }), 3)).toEqual({ ordinal: 0, offsetMs: 0, resumeExistingSession: false });
  });

  it("treats the exact end of the last segment as ended even before the phase settles", () => {
    expect(resolveChapterPlaybackStartPosition(Object.freeze({
      ...playerState(),
      phase: "paused",
      currentSegmentId: SEGMENT_3,
      currentOrdinal: 2,
      offsetMs: 1_000,
      durationMs: 1_000,
    }), 3)).toEqual({ ordinal: 0, offsetMs: 0, resumeExistingSession: false });
  });

  it("preserves a valid mid-chapter resume position and bounds an invalid one", () => {
    expect(resolveChapterPlaybackStartPosition(Object.freeze({
      ...playerState(),
      phase: "paused",
      currentOrdinal: 1,
      offsetMs: 420,
    }), 3)).toEqual({ ordinal: 1, offsetMs: 420, resumeExistingSession: true });
    expect(resolveChapterPlaybackStartPosition(Object.freeze({
      ...playerState(),
      phase: "idle",
      currentOrdinal: 99,
      offsetMs: -5,
    }), 3)).toEqual({ ordinal: 0, offsetMs: 0, resumeExistingSession: false });
  });

  it("fails closed when no valid segment exists instead of reusing an unrelated offset", () => {
    expect(resolveChapterPlaybackStartPosition(Object.freeze({
      ...playerState(),
      phase: "idle",
      currentOrdinal: 99,
      offsetMs: 800,
    }), 3)).toEqual({ ordinal: 0, offsetMs: 0, resumeExistingSession: false });
    expect(resolveChapterPlaybackStartPosition(playerState(), 0)).toEqual({
      ordinal: 0,
      offsetMs: 0,
      resumeExistingSession: false,
    });
  });
});
