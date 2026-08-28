import { describe, expect, it, vi } from "vitest";

import {
  createChapterNarrationPanel,
  deriveChapterNarrationPanelModel,
  type ChapterNarrationPanelProps,
  type ChapterNarrationPanelReactRuntime,
} from "./chapter-narration-panel";
import { FAILED_SEGMENT_RETRY_CONTRACT_VERSION } from "./chapter-contracts";
import type { EditionHistoryItem } from "./edition-history";
import type { NarrationPlayerState } from "./narration-player";
import type { ScriptReviewSegmentResource } from "./script-contracts";


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


const React: ChapterNarrationPanelReactRuntime = {
  createElement(type, elementProps, ...children): FakeElement {
    return { type, props: elementProps ?? {}, children };
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

  it("dispatches explicit sentence seek and exposes no unsupported volume control", () => {
    const onSeekOrdinal = vi.fn();
    const Panel = createChapterNarrationPanel(React);
    const root = Panel(props({ onSeekOrdinal }));
    const slider = findAll(root, (item) => item.type === "input" && item.props.type === "range")[0];
    (slider.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "1" } });
    expect(onSeekOrdinal).toHaveBeenCalledWith(1);
    expect(textContent(root)).not.toMatch(/音量/u);
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
