import { describe, expect, it, vi } from "vitest";

import {
  createChapterNarrationPanel,
  deriveChapterNarrationPanelModel,
  type ChapterNarrationPanelProps,
  type ChapterNarrationPanelReactRuntime,
} from "./chapter-narration-panel";
import {
  FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
  type NarrationEditionVoiceIdentity,
} from "./chapter-contracts";
import type { EditionHistoryItem } from "./edition-history";
import type { NarrationPlayerState } from "./narration-player";
import type { ManifestSegmentV2 } from "./playback-contracts";
import type { ScriptReviewSegmentResource } from "./script-contracts";
import { T4_CHAPTER_NARRATION_STYLES } from "./styles/t4-chapter";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


const DOCUMENT_ID = "20000000-0000-4000-8000-000000000001";
const EDITION_ID = "10000000-0000-4000-8000-000000000001";
const REQUEST_ID = "50000000-0000-4000-8000-000000000001";
const REVISION_ID = "30000000-0000-4000-8000-000000000001";
const SEGMENT_1 = "40000000-0000-4000-8000-000000000001";
const SEGMENT_2 = "40000000-0000-4000-8000-000000000002";
const JOB_ID = "70000000-0000-4000-8000-000000000001";


function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function segment(segmentId: string, ordinal: number, text: string): ScriptReviewSegmentResource {
  return Object.freeze({
    segment_id: segmentId,
    ordinal,
    segment_kind: ordinal === 0 ? "narration" : "dialogue",
    source_block_key: `sb1_${String(ordinal + 1).repeat(64)}`,
    source_start_utf16: ordinal * 4,
    source_end_utf16: ordinal * 4 + text.length,
    source_text: text,
    spoken_text: text,
    local_hash: String(ordinal + 1).repeat(64),
    speaker_kind: ordinal === 0 ? "narrator" : "anonymous",
    speaker_label: ordinal === 0 ? "旁白" : "路人甲",
    character_id: null,
    anonymous_speaker_id: ordinal === 0 ? null : "60000000-0000-4000-8000-000000000001",
    confidence: "high",
    casting_state: "resolved",
    issue_codes: Object.freeze([]),
    editable: false,
  });
}


function edition(): EditionHistoryItem {
  return Object.freeze({
    edition_id: EDITION_ID,
    request_id: REQUEST_ID,
    source_revision_id: REVISION_ID,
    source_content_hash: "a".repeat(64),
    edition_fingerprint: "b".repeat(64),
    state: "ready",
    created_at: "2026-08-27T08:00:00Z",
    manifest_revision: 2,
    manifest_etag: `"${"c".repeat(64)}"`,
    ready_segment_count: 2,
    total_segment_count: 2,
    is_current: true,
    source_status: "current",
    rights_available: true,
    playable: true,
    default_start_ready: true,
    resume_available: false,
    switch_allowed: true,
  });
}


function playerState(phase: NarrationPlayerState["phase"] = "idle"): NarrationPlayerState {
  return Object.freeze({
    phase,
    currentSegmentId: phase === "idle" ? null : SEGMENT_2,
    currentOrdinal: phase === "idle" ? null : 1,
    offsetMs: 0,
    durationMs: phase === "idle" ? 0 : 900,
    rate: 1,
    volume: 0.8,
    followPaused: false,
    backend: phase === "idle" ? null : "web-audio",
    source: phase === "idle" ? null : "default",
    failure: null,
  });
}


function props(patch: Partial<ChapterNarrationPanelProps> = {}): ChapterNarrationPanelProps {
  return {
    phase: "ready",
    sourceKind: "current",
    playerState: playerState(),
    segments: Object.freeze([
      segment(SEGMENT_1, 0, "第一句。"),
      segment(SEGMENT_2, 1, "第二句。"),
    ]),
    segmentStates: Object.freeze(["ready", "ready"]),
    editions: Object.freeze([edition()]),
    activeEditionId: EDITION_ID,
    currentEditionId: EDITION_ID,
    busy: false,
    productionAllowed: true,
    statusMessage: "朗读已就绪",
    onGenerate: vi.fn(),
    onUpdate: vi.fn(),
    onTogglePlayback: vi.fn(),
    onSeekOrdinal: vi.fn(),
    onRateChange: vi.fn(),
    onVolumeChange: vi.fn(),
    onResumeFollow: vi.fn(),
    onSelectEdition: vi.fn(),
    ...patch,
  };
}


function failedSegments(retryable = true) {
  return Object.freeze({
    contract_version: FAILED_SEGMENT_RETRY_CONTRACT_VERSION,
    edition_id: EDITION_ID,
    request_id: REQUEST_ID,
    request_version: 4,
    manifest_revision: 2,
    request_state: "partial_ready" as const,
    edition_state: "partial_ready" as const,
    items: Object.freeze([
      Object.freeze({
        segment_id: SEGMENT_1,
        ordinal: 0,
        failure_code: "LEASE_EXPIRED",
        retryable,
        retry_reason_code: retryable ? null : "FANOUT_NOT_ALL_FAILED",
        job_id: JOB_ID,
        fanout_segment_ids: Object.freeze([SEGMENT_1, SEGMENT_2]),
      }),
      Object.freeze({
        segment_id: SEGMENT_2,
        ordinal: 1,
        failure_code: "LEASE_EXPIRED",
        retryable,
        retry_reason_code: retryable ? null : "FANOUT_NOT_ALL_FAILED",
        job_id: JOB_ID,
        fanout_segment_ids: Object.freeze([SEGMENT_1, SEGMENT_2]),
      }),
    ]),
  });
}


function manifestSegments(): readonly ManifestSegmentV2[] {
  return Object.freeze([SEGMENT_1, SEGMENT_2].map((segmentId, ordinal) => Object.freeze({
    segment_id: segmentId,
    ordinal,
    paragraph_ordinal: ordinal,
    source_block_key: `paragraph-${ordinal}`,
    source_start_utf16: ordinal * 4,
    source_end_utf16: ordinal * 4 + 3,
    gap_after_ms: ordinal === 0 ? 100 : 0,
    render_status: "ready" as const,
    audio: Object.freeze({
      url: `/media/${segmentId}`,
      actual_sha256: "a".repeat(64),
      duration_ms: ordinal === 0 ? 1_000 : 2_000,
      sample_rate: 48_000,
      channels: 2,
      etag: `"${"b".repeat(64)}"`,
    }),
    failure: null,
  })));
}


function legacyVoiceIdentity(): NarrationEditionVoiceIdentity {
  return Object.freeze({
    profile_id: "80000000-0000-4000-8000-000000000001",
    voice_version_id: "90000000-0000-4000-8000-000000000001",
    display_name: "旧版未保存名称",
    source_type: null,
    preset_id: null,
    resolution_contract_version: "narration-edition-resolution/1",
    legacy_fallback: true,
  });
}


const React: ChapterNarrationPanelReactRuntime = {
  createElement(type, elementProps, ...children): FakeElement {
    return { type, props: elementProps ?? {}, children };
  },
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
    return [typeof initial === "function" ? (initial as () => T)() : initial, () => undefined];
  },
  useRef<T>(initial: T): { current: T } {
    return { current: initial };
  },
  useEffect(effect: () => void | (() => void)): void {
    effect();
  },
};


describe("chapter narration panel", () => {
  it("uses sentence-level progress and derives truthful previous/next targets", () => {
    const model = deriveChapterNarrationPanelModel(props({ playerState: playerState("playing") }));
    expect(model.currentSegment?.speaker_label).toBe("路人甲");
    expect(model.progressLabel).toBe("2 / 2 句");
    expect(model.previousOrdinal).toBe(0);
    expect(model.nextOrdinal).toBeNull();
    expect(model.playbackLabel).toBe("暂停");
  });

  it("shows only a real generate action when no Edition exists", () => {
    const onGenerate = vi.fn();
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({
      phase: "no-edition",
      playerState: null,
      segments: [],
      editions: [],
      activeEditionId: null,
      currentEditionId: null,
      onGenerate,
    }));
    const generate = findAll(root, (item) => item.type === "button" && textContent(item) === "智能朗读")[0];
    expect(generate).toBeDefined();
    (generate.props.onClick as () => void)();
    expect(onGenerate).toHaveBeenCalledTimes(1);
    expect(findAll(root, (item) => item.type === "input" && item.props.type === "range")).toHaveLength(0);
  });

  it("dispatches sentence seek and applies volume immediately in normalized units", () => {
    const onSeekOrdinal = vi.fn();
    const onVolumeChange = vi.fn();
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({ onSeekOrdinal, onVolumeChange }));
    const slider = findAll(
      root,
      (item) => item.type === "input" && item.props["aria-label"] === "按句段跳转章节朗读位置",
    )[0];
    (slider.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "1" } });
    expect(onSeekOrdinal).toHaveBeenCalledWith(1);
    const volume = findAll(
      root,
      (item) => item.type === "input" && item.props["aria-label"] === "章节朗读音量",
    )[0];
    expect(volume.props).toMatchObject({ min: 0, max: 100, value: 80 });
    (volume.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "35" } });
    expect(onVolumeChange).toHaveBeenCalledWith(0.35);
  });

  it("covers the complete 0.5–3 playback-rate range", () => {
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props());
    const select = findAll(
      root,
      (item) => item.type === "select"
        && item.props["aria-label"] === "朗读倍速，范围 0.5 到 3 倍",
    )[0];
    const values = findAll(select, (item) => item.type === "option")
      .map((item) => item.props.value);
    expect(values).toEqual([
      "0.5", "0.75", "1", "1.25", "1.5", "1.75", "2", "2.25", "2.5", "2.75", "3",
    ]);
  });

  it("shows truthful timing, whole-chapter generation, frozen legacy identity, and preference status", () => {
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({
      manifestSegments: manifestSegments(),
      voiceIdentities: [legacyVoiceIdentity()],
      playbackPreferenceStatus: { state: "conflict" },
    }));

    expect(textContent(root)).toContain("可播放0:03 · 2/2 句");
    expect(textContent(root)).toContain("全章生成100%");
    expect(textContent(root)).toContain("旧版未保存名称");
    expect(textContent(root)).toContain("播放偏好已在别处更新");
    const player = findAll(root, (item) => item.props["aria-label"] === "章节智能朗读播放器")[0];
    expect(player.props).toMatchObject({
      "data-content-phase": "ready",
      "data-player-phase": "idle",
      "data-source-kind": "current",
      "data-generation-state": "complete",
      "data-layout-mode": "compact",
      "data-preference-state": "conflict",
    });
  });

  it("keeps failure rows in a closed details region instead of the compact bar", () => {
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({ failedSegments: failedSegments() }));
    const trigger = findAll(
      root,
      (item) => item.type === "button" && textContent(item) === "失败 2",
    )[0];
    const details = findAll(root, (item) => item.props.id === "anw-chapter-player-details")[0];
    const failures = findAll(root, (item) => item.props["aria-label"] === "失败句段重试")[0];
    expect(trigger.props).toMatchObject({
      "aria-controls": "anw-chapter-player-details",
      "aria-expanded": false,
    });
    expect(details.props.hidden).toBe(true);
    expect(failures.props.hidden).toBe(true);
  });

  it("uses natural player layout, explicit narrow-screen rules, and 44px controls", () => {
    expect(T4_CHAPTER_NARRATION_STYLES).not.toContain("--anw-chapter-player-height");
    expect(T4_CHAPTER_NARRATION_STYLES).not.toContain("94px");
    expect(T4_CHAPTER_NARRATION_STYLES).toContain("min-height: 44px");
    expect(T4_CHAPTER_NARRATION_STYLES).toContain("@container (max-width: 720px)");
    expect(T4_CHAPTER_NARRATION_STYLES).toContain(
      "grid-template-columns: minmax(0, 1fr) auto auto",
    );
    expect(T4_CHAPTER_NARRATION_STYLES).toContain(
      ".anw-chapter-narration-details__overview,",
    );
    expect(T4_CHAPTER_NARRATION_STYLES).toContain(
      "grid-template-columns: minmax(0, 1fr);",
    );
    expect(T4_CHAPTER_NARRATION_STYLES).toContain("@media (max-width: 720px)");
    expect(T4_CHAPTER_NARRATION_STYLES).toContain("z-index: 0;");
    expect(T4_CHAPTER_NARRATION_STYLES).toContain("@media (max-width: 390px)");
  });

  it("exposes only bounded non-sensitive playback state for the fixed observer", () => {
    const Panel = createChapterNarrationPanel(React);
    const blocked: NarrationPlayerState = Object.freeze({
      ...playerState("blocked"),
      currentSegmentId: SEGMENT_1,
      currentOrdinal: 0,
      failure: Object.freeze({
        code: "PENDING_GAP",
        message: "not exposed by the player root",
        retryable: true,
        segmentId: SEGMENT_2,
        ordinal: 1,
      }),
    });
    const root = Panel(props({
      playerState: blocked,
      segmentStates: Object.freeze(["ready", "rendering"]),
    }));
    const player = findAll(
      root,
      (item) => item.type === "section"
        && item.props["aria-label"] === "章节智能朗读播放器",
    )[0];

    expect(player.props).toMatchObject({
      "data-player-phase": "blocked",
      "data-player-failure-code": "PENDING_GAP",
      "data-current-ordinal": "0",
      "data-segment-states": "ready,pending",
    });
    expect(JSON.stringify({
      phase: player.props["data-player-phase"],
      failure: player.props["data-player-failure-code"],
      ordinal: player.props["data-current-ordinal"],
      states: player.props["data-segment-states"],
    })).not.toContain("not exposed");
  });

  it("fails the observer contract closed when segment state cardinality drifts", () => {
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({ segmentStates: Object.freeze(["ready"]) }));
    const player = findAll(
      root,
      (item) => item.type === "section"
        && item.props["aria-label"] === "章节智能朗读播放器",
    )[0];
    expect(player.props["data-segment-states"]).toBe("");
  });

  it("labels diverged playback as old draft and offers explicit follow resume", () => {
    const onResumeFollow = vi.fn();
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({
      sourceKind: "working-copy-diverged",
      followPaused: true,
      onResumeFollow,
    }));
    expect(textContent(root)).toContain("旧稿朗读");
    expect(textContent(root)).toContain("正文待更新");
    expect(textContent(root)).toContain("旧稿字幕");
    const resume = findAll(
      root,
      (item) => item.type === "button" && textContent(item) === "返回当前朗读位置",
    )[0];
    (resume.props.onClick as () => void)();
    expect(onResumeFollow).toHaveBeenCalledTimes(1);
  });

  it("offers the explicit cursor command only for the textarea fallback", () => {
    const onPlaybackFromCursor = vi.fn();
    const Panel = createChapterNarrationPanel(React);
    const fallback = Panel(props({
      cursorPlaybackAvailable: true,
      onPlaybackFromCursor,
    }));
    const command = findAll(
      fallback,
      (item) => item.type === "button" && textContent(item) === "从光标所在段朗读",
    )[0];
    expect(command).toBeDefined();
    expect(command.props.disabled).toBe(false);
    (command.props.onClick as () => void)();
    expect(onPlaybackFromCursor).toHaveBeenCalledOnce();

    const codeMirror = Panel(props({
      cursorPlaybackAvailable: false,
      onPlaybackFromCursor,
    }));
    expect(findAll(
      codeMirror,
      (item) => item.type === "button" && textContent(item) === "从光标所在段朗读",
    )).toHaveLength(0);
  });

  it("keeps generation and update inert while the production capability is held", () => {
    expect(deriveChapterNarrationPanelModel(props({
      phase: "no-edition",
      playerState: null,
      segments: [],
      editions: [],
      activeEditionId: null,
      currentEditionId: null,
      productionAllowed: false,
    })).canGenerate).toBe(false);
    expect(deriveChapterNarrationPanelModel(props({
      productionAllowed: false,
    })).canUpdate).toBe(false);
  });

  it("shows failed sentences only when present and dispatches a keyboard-native retry", () => {
    const onRetryFailedSegment = vi.fn();
    const retryTriggerRef = { current: null };
    const Panel = createChapterNarrationPanel(React);
    const withoutFailures = Panel(props());
    expect(findAll(
      withoutFailures,
      (item) => item.props["aria-label"] === "失败句段重试",
    )).toHaveLength(0);

    const root = Panel(props({
      failedSegments: failedSegments(),
      onRetryFailedSegment,
      retryFocusSegmentId: SEGMENT_1,
      retryTriggerRef,
    }));
    expect(textContent(root)).toContain("失败句段（2）");
    expect(textContent(root)).toContain("此音频被 2 句共用");
    const buttons = findAll(
      root,
      (item) => item.type === "button" && textContent(item) === "重试本句",
    );
    expect(buttons).toHaveLength(2);
    expect(buttons[0]?.props).toMatchObject({
      type: "button",
      disabled: false,
      "aria-busy": "false",
      ref: retryTriggerRef,
    });
    (buttons[0]?.props.onClick as () => void)();
    expect(onRetryFailedSegment).toHaveBeenCalledWith(SEGMENT_1);
  });

  it("disables the whole fanout group while busy and re-enables it after an announced error", () => {
    const Panel = createChapterNarrationPanel(React);
    const busyRoot = Panel(props({
      failedSegments: failedSegments(),
      retryBusySegmentIds: [SEGMENT_1, SEGMENT_2],
      retrySubmitting: true,
      onRetryFailedSegment: vi.fn(),
    }));
    const buttons = findAll(
      busyRoot,
      (item) => item.type === "button" && textContent(item) === "正在重试…",
    );
    expect(buttons).toHaveLength(2);
    expect(buttons.every((button) => button.props.disabled === true)).toBe(true);
    expect(buttons.every((button) => button.props["aria-busy"] === "true")).toBe(true);

    const recoveredRoot = Panel(props({
      failedSegments: failedSegments(),
      retrySubmitting: false,
      retryErrorMessage: "本次重试失败，可以再次重试。",
      onRetryFailedSegment: vi.fn(),
    }));
    const recoveredButtons = findAll(
      recoveredRoot,
      (item) => item.type === "button" && textContent(item) === "重试本句",
    );
    expect(recoveredButtons).toHaveLength(2);
    expect(recoveredButtons.every((button) => button.props.disabled === false)).toBe(true);
    const live = findAll(
      recoveredRoot,
      (item) => item.props.className === "anw-chapter-narration-retry-live is-error",
    )[0];
    expect(live?.props).toMatchObject({ role: "status", "aria-live": "polite" });
    expect(textContent(live)).toContain("可以再次重试");
  });

  it("moves the retry focus target to the stable status region after the failed item disappears", () => {
    const Panel = createChapterNarrationPanel(React);
    const retryTriggerRef = { current: null };
    const emptyProjection = Object.freeze({
      ...failedSegments(),
      items: Object.freeze([]),
    });
    const root = Panel(props({
      failedSegments: emptyProjection,
      retryStatusMessage: "失败句段已经恢复，可继续播放。",
      retryFocusSegmentId: SEGMENT_1,
      retryTriggerRef,
    }));

    expect(findAll(
      root,
      (item) => item.props["aria-label"] === "失败句段重试",
    )).toHaveLength(0);
    const live = findAll(
      root,
      (item) => item.props.className === "anw-chapter-narration-retry-live",
    )[0];
    expect(live?.props).toMatchObject({
      role: "status",
      "aria-live": "polite",
      tabIndex: -1,
      ref: retryTriggerRef,
    });
    expect(textContent(live)).toContain("已经恢复");
  });

  it("keeps a stable explanation and no action for non-retryable segments", () => {
    const onRetryFailedSegment = vi.fn();
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({
      failedSegments: failedSegments(false),
      onRetryFailedSegment,
    }));
    expect(textContent(root)).toContain("为避免覆盖正在使用的音频，暂不能重试");
    const blocked = findAll(
      root,
      (item) => item.type === "button" && textContent(item) === "暂不可重试",
    );
    expect(blocked).toHaveLength(2);
    expect(blocked.every((button) => button.props.disabled === true)).toBe(true);
  });
});
