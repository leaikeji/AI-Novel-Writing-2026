import { describe, expect, it, vi } from "vitest";

import type {
  DocumentNarrationContext,
  NarrationEditionResource,
} from "./chapter-contracts";
import {
  createChapterNarrationSession,
  type ChapterNarrationSessionDependencies,
} from "./chapter-narration-session";
import {
  ProductionNarrationEditorBridge,
} from "./editor-bridge";
import type { DocumentEditionHistory, EditionHistoryItem } from "./edition-history";
import {
  ProductionNarrationPlayerController,
  type CreateNarrationPlayerOptions,
} from "./narration-player";
import {
  deriveManifestStatus,
  deriveReadyPrefixCount,
  deriveReadyRanges,
  type NarrationManifestV2,
  type SegmentRenderStatus,
} from "./playback-contracts";
import type { ManifestFetchResult } from "./playback-api";
import type { ScriptReviewResource } from "./script-contracts";
import type {
  NarrationPlayerQueueHooks,
} from "./narration-player";
import type {
  SegmentPlaybackQueuePort,
  SegmentPlaybackQueueStartOptions,
  SegmentPlaybackQueueStartResult,
} from "./segment-playback-queue";


const NOVEL_ID = "10000000-0000-4000-8000-000000000001";
const DOCUMENT_ID = "10000000-0000-4000-8000-000000000002";
const EDITION_ID = "10000000-0000-4000-8000-000000000003";
const CURRENT_EDITION_ID = "10000000-0000-4000-8000-000000000004";
const REQUEST_ID = "10000000-0000-4000-8000-000000000005";
const SCRIPT_ID = "10000000-0000-4000-8000-000000000006";
const SCRIPT_VERSION_ID = "10000000-0000-4000-8000-000000000007";
const CURRENT_SCRIPT_VERSION_ID = "10000000-0000-4000-8000-000000000008";
const REVISION_ID = "10000000-0000-4000-8000-000000000009";
const CURRENT_REVISION_ID = "10000000-0000-4000-8000-000000000010";
const SEGMENT_IDS = [
  "10000000-0000-4000-8000-000000000011",
  "10000000-0000-4000-8000-000000000012",
] as const;
const SOURCE_TEXTS = ["第一段。", "第二段。"] as const;
const SOURCE = SOURCE_TEXTS.join("");
const SOURCE_HASH = "a".repeat(64);
const WORKING_HASH = "b".repeat(64);
const EDITION_FINGERPRINT = "c".repeat(64);
const SETTINGS_FINGERPRINT = "d".repeat(64);
const IMMUTABLE_HASH = "e".repeat(64);


function etag(digit: string): string {
  return `"${digit.repeat(64)}"`;
}


function assetId(ordinal: number): string {
  return `20000000-0000-4000-8000-${String(ordinal + 1).padStart(12, "0")}`;
}


function sourceStart(ordinal: number): number {
  return ordinal === 0 ? 0 : SOURCE_TEXTS[0].length;
}


function manifest(
  states: readonly SegmentRenderStatus[],
  revision = 1,
  etagDigit = "1",
): NarrationManifestV2 {
  const segments = states.map((renderStatus, ordinal) => {
    const digest = String(ordinal + 1).repeat(64);
    const start = sourceStart(ordinal);
    const sourceText = SOURCE_TEXTS[ordinal];
    return {
      segment_id: SEGMENT_IDS[ordinal],
      ordinal,
      paragraph_ordinal: ordinal,
      source_block_key: `paragraph-${ordinal}`,
      source_start_utf16: start,
      source_end_utf16: start + sourceText.length,
      gap_after_ms: 100,
      render_status: renderStatus,
      audio: renderStatus === "ready" ? {
        url: `/api/ai-novel-world-2026/media-assets/${assetId(ordinal)}/content`,
        actual_sha256: digest,
        duration_ms: 1_000,
        sample_rate: 48_000,
        channels: 1,
        etag: `"${digest}"`,
      } : null,
      failure: renderStatus === "failed" ? {
        code: "RENDER_FAILED",
        retryable: true,
        message: "fixture render failure",
      } : null,
    };
  });
  const bufferPolicy = {
    version: "session-test/v1",
    minimum_segments: 2,
    minimum_duration_ms: 2_000,
    target_segments: 2,
    chapter_end_exception: true,
  } as const;
  const readyRanges = deriveReadyRanges(segments, bufferPolicy);
  return Object.freeze({
    schema_version: "narration-manifest/2.0",
    edition_id: EDITION_ID,
    chapter_id: DOCUMENT_ID,
    source_revision_id: REVISION_ID,
    source_sha256: SOURCE_HASH,
    buffer_policy: bufferPolicy,
    manifest_revision: revision,
    etag: etag(etagDigit),
    generated_at: "2026-08-27T08:00:00Z",
    status: deriveManifestStatus(segments),
    ready_prefix_count: deriveReadyPrefixCount(segments),
    default_start_ready: readyRanges.some((range) => range.start_ordinal === 0),
    last_playable_start_ordinal: readyRanges.length === 0
      ? null
      : Math.max(...readyRanges.map((range) => range.last_playable_start_ordinal)),
    ready_ranges: Object.freeze(readyRanges),
    segments: Object.freeze(segments),
  });
}


function editionHistoryItem(
  initialManifest: NarrationManifestV2,
  options: {
    current?: boolean;
    editionId?: string;
    requestId?: string;
    sourceRevisionId?: string;
    sourceContentHash?: string;
  } = {},
): EditionHistoryItem {
  const current = options.current ?? true;
  return Object.freeze({
    edition_id: options.editionId ?? EDITION_ID,
    request_id: options.requestId ?? REQUEST_ID,
    source_revision_id: options.sourceRevisionId ?? REVISION_ID,
    source_content_hash: options.sourceContentHash ?? SOURCE_HASH,
    edition_fingerprint: EDITION_FINGERPRINT,
    state: initialManifest.status === "ready" ? "ready" : "rendering",
    created_at: "2026-08-27T08:00:00Z",
    manifest_revision: initialManifest.manifest_revision,
    manifest_etag: initialManifest.etag,
    ready_segment_count: initialManifest.segments.filter(
      (segment) => segment.render_status === "ready",
    ).length,
    total_segment_count: initialManifest.segments.length,
    is_current: current,
    source_status: current ? "current" : "superseded",
    rights_available: true,
    playable: initialManifest.ready_ranges.length > 0,
    default_start_ready: initialManifest.default_start_ready,
    resume_available: false,
    switch_allowed: false,
  });
}


function context(
  initialManifest: NarrationManifestV2,
  oldDraft = false,
): DocumentNarrationContext {
  const active = editionHistoryItem(initialManifest, { current: !oldDraft });
  const current = oldDraft
    ? editionHistoryItem(initialManifest, {
        current: true,
        editionId: CURRENT_EDITION_ID,
        requestId: CURRENT_SCRIPT_VERSION_ID,
        sourceRevisionId: CURRENT_REVISION_ID,
        sourceContentHash: WORKING_HASH,
      })
    : active;
  const history: DocumentEditionHistory = Object.freeze({
    contract_version: "narration-edition-history/1",
    document_id: DOCUMENT_ID,
    pointer_version: 7,
    current_edition_id: current.edition_id,
    working_copy_content_hash: oldDraft ? WORKING_HASH : SOURCE_HASH,
    working_copy_draft_version: 4,
    editions: Object.freeze(oldDraft ? [current, active] : [active]),
  });
  return Object.freeze({
    contract_version: "document-narration-context/1",
    document_id: DOCUMENT_ID,
    novel_id: NOVEL_ID,
    pointer_version: 7,
    current_script_version_id: oldDraft ? CURRENT_SCRIPT_VERSION_ID : SCRIPT_VERSION_ID,
    current_edition_id: current.edition_id,
    active_edition_id: EDITION_ID,
    active_is_current: !oldDraft,
    working_copy_draft_version: 4,
    working_copy_content_hash: oldDraft ? WORKING_HASH : SOURCE_HASH,
    source_snapshot: Object.freeze({
      revision_id: REVISION_ID,
      content_hash: SOURCE_HASH,
      matches_working_copy: !oldDraft,
    }),
    compatibility: oldDraft ? "superseded" : "current",
    source_notice_code: oldDraft ? "HISTORICAL_EDITION" : "CURRENT_SOURCE_SNAPSHOT",
    editor_timeline_mode: oldDraft ? "immutable_edition_only" : "exact_working_copy",
    old_draft_subtitle_required: oldDraft,
    explicit_update_required: oldDraft,
    can_request_update: oldDraft,
    available_current_source_edition_ids: Object.freeze(oldDraft ? [CURRENT_EDITION_ID] : [EDITION_ID]),
    edition_history: history,
  });
}


function noEditionContext(): DocumentNarrationContext {
  const history: DocumentEditionHistory = Object.freeze({
    contract_version: "narration-edition-history/1",
    document_id: DOCUMENT_ID,
    pointer_version: 0,
    current_edition_id: null,
    working_copy_content_hash: SOURCE_HASH,
    working_copy_draft_version: 1,
    editions: Object.freeze([]),
  });
  return Object.freeze({
    contract_version: "document-narration-context/1",
    document_id: DOCUMENT_ID,
    novel_id: NOVEL_ID,
    pointer_version: 0,
    current_script_version_id: null,
    current_edition_id: null,
    active_edition_id: null,
    active_is_current: false,
    working_copy_draft_version: 1,
    working_copy_content_hash: SOURCE_HASH,
    source_snapshot: null,
    compatibility: "no_current_edition",
    source_notice_code: "NO_CURRENT_EDITION",
    editor_timeline_mode: "none",
    old_draft_subtitle_required: false,
    explicit_update_required: false,
    can_request_update: true,
    available_current_source_edition_ids: Object.freeze([]),
    edition_history: history,
  });
}


function edition(initialManifest: NarrationManifestV2): NarrationEditionResource {
  const count = (state: SegmentRenderStatus) => initialManifest.segments.filter(
    (segment) => segment.render_status === state,
  ).length;
  return Object.freeze({
    contract_version: "narration-production-api/1",
    edition_id: EDITION_ID,
    request_id: REQUEST_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    script_version_id: SCRIPT_VERSION_ID,
    settings_fingerprint: SETTINGS_FINGERPRINT,
    edition_fingerprint: EDITION_FINGERPRINT,
    state: initialManifest.status === "ready" ? "ready" : "rendering",
    segment_count: initialManifest.segments.length,
    pending_segment_count: count("pending"),
    queued_segment_count: count("queued"),
    rendering_segment_count: count("rendering"),
    ready_segment_count: count("ready"),
    failed_segment_count: count("failed"),
    current_manifest_revision: initialManifest.manifest_revision,
    job_ids: Object.freeze([]),
  });
}


function script(): ScriptReviewResource {
  return Object.freeze({
    contract_version: "narration-script-review-api/1",
    taxonomy_version: "narration-review-taxonomy/1",
    script_id: SCRIPT_ID,
    script_version_id: SCRIPT_VERSION_ID,
    novel_id: NOVEL_ID,
    document_id: DOCUMENT_ID,
    revision_id: REVISION_ID,
    source_content_hash: SOURCE_HASH,
    immutable_hash: IMMUTABLE_HASH,
    version_number: 3,
    state: "approved",
    effective_policy: "blockers_only",
    source_status: "current",
    warning_count: 0,
    blocker_count: 0,
    allowed_actions: Object.freeze([]),
    segments: Object.freeze(SEGMENT_IDS.map((segmentId, ordinal) => {
      const start = sourceStart(ordinal);
      const sourceText = SOURCE_TEXTS[ordinal];
      return Object.freeze({
        segment_id: segmentId,
        ordinal,
        segment_kind: "narration" as const,
        source_block_key: `paragraph-${ordinal}`,
        source_start_utf16: start,
        source_end_utf16: start + sourceText.length,
        source_text: sourceText,
        spoken_text: sourceText,
        local_hash: String(ordinal + 3).repeat(64),
        speaker_kind: "narrator" as const,
        speaker_label: "旁白",
        character_id: null,
        anonymous_speaker_id: null,
        confidence: "high" as const,
        casting_state: "resolved" as const,
        issue_codes: Object.freeze([]),
        editable: true,
      });
    })),
    issues: Object.freeze([]),
    approval: Object.freeze({
      kind: "auto_no_blockers",
      request_id: REQUEST_ID,
      actor_type: "system",
      actor_id: "narration-session-test",
      approved_at: "2026-08-27T08:00:00Z",
    }),
  });
}


class TestQueue implements SegmentPlaybackQueuePort {
  readonly starts: SegmentPlaybackQueueStartOptions[] = [];
  pauseCount = 0;
  resumeCount = 0;
  disposeCount = 0;
  stopCount = 0;
  readonly rates: number[] = [];
  readonly volumes: number[] = [];

  constructor(private readonly hooks: NarrationPlayerQueueHooks) {}

  async start(options: SegmentPlaybackQueueStartOptions): Promise<SegmentPlaybackQueueStartResult> {
    this.starts.push(options);
    const target = options.manifest.segments[options.startOrdinal];
    const durationMs = target.audio?.duration_ms ?? 0;
    this.hooks.onEvent({
      type: "segment-start",
      lease: options.lease,
      backend: "web-audio",
      segmentId: target.segment_id,
      ordinal: target.ordinal,
      offsetMs: options.startOffsetMs ?? 0,
      durationMs,
    });
    return Object.freeze({
      kind: "started",
      lease: options.lease,
      backend: "web-audio",
      segmentId: target.segment_id,
      ordinal: target.ordinal,
    });
  }

  pause(): void { this.pauseCount += 1; }
  async resume(): Promise<void> { this.resumeCount += 1; }
  setRate(rate: number): void { this.rates.push(rate); }
  setVolume(volume: number): void { this.volumes.push(volume); }
  readPosition(): Readonly<{ segmentId: string; ordinal: number; offsetMs: number }> | null {
    const start = this.starts[this.starts.length - 1];
    if (!start) return null;
    const segment = start.manifest.segments[start.startOrdinal];
    return Object.freeze({
      segmentId: segment.segment_id,
      ordinal: segment.ordinal,
      offsetMs: start.startOffsetMs ?? 0,
    });
  }
  stop(): void { this.stopCount += 1; }
  dispose(): void { this.disposeCount += 1; }
}


interface FixtureResources {
  context: DocumentNarrationContext;
  edition: NarrationEditionResource;
  script: ScriptReviewResource;
  manifest: NarrationManifestV2;
}


interface HarnessOptions {
  resources?: FixtureResources;
  getManifest?: ChapterNarrationSessionDependencies["getNarrationManifest"];
  delay?: ChapterNarrationSessionDependencies["delay"];
  now?: ChapterNarrationSessionDependencies["now"];
  onState?: (state: ReturnType<ReturnType<typeof createChapterNarrationSession>["readSnapshot"]>) => void;
  pollTimeoutMs?: number;
  createPlayer?: ChapterNarrationSessionDependencies["createPlayer"];
  getProgress?: ChapterNarrationSessionDependencies["getNarrationPlaybackProgress"];
  putProgress?: ChapterNarrationSessionDependencies["putNarrationPlaybackProgress"];
  getSettings?: NonNullable<ChapterNarrationSessionDependencies["getNarrationSettings"]>;
  putPreferences?: NonNullable<ChapterNarrationSessionDependencies["putNarrationPlaybackPreferences"]>;
  onPlaybackPreferenceStatus?: (
    status: "saving" | "saved" | "conflict" | "error",
    message?: string,
  ) => void;
  bridgeContentHash?: string;
}


function fixture(
  states: readonly SegmentRenderStatus[] = ["ready", "ready"],
  oldDraft = false,
): FixtureResources {
  const initialManifest = manifest(states);
  return {
    context: context(initialManifest, oldDraft),
    edition: edition(initialManifest),
    script: script(),
    manifest: initialManifest,
  };
}


function narrationSettings(
  version = 4,
  playback = { playback_rate: 0.9, volume: 0.4 },
) {
  return Object.freeze({
    contract_version: "narration-settings-api/1" as const,
    schema_version: "narration-settings/1" as const,
    novel_id: NOVEL_ID,
    settings_id: "10000000-0000-4000-8000-000000000098",
    exists: true,
    version,
    values: Object.freeze({
      narrator: null,
      language: "zh-CN",
      output_format: "m4a_aac_lc" as const,
      script_review_policy: "blockers_only" as const,
      analysis_mode: "local_rules_only" as const,
      text_rules: Object.freeze({
        read_chapter_title: true,
        read_author_notes: false,
        read_section_breaks: false,
        first_person_mode: "narrator" as const,
        first_person_character_id: null,
        inner_monologue_mode: "character" as const,
      }),
      timing: Object.freeze({
        sentence_gap_ms: 200,
        paragraph_gap_ms: 500,
        section_gap_ms: 900,
      }),
      casting: Object.freeze({
        anonymous_reuse_scope: "scene" as const,
        same_scene_voice_deduplication: true,
        unknown_speaker_action: "block" as const,
      }),
      playback: Object.freeze(playback),
    }),
    updated_at: "2026-08-29T10:00:00Z",
  });
}


function createHarness(options: HarnessOptions = {}) {
  const resources = options.resources ?? fixture();
  let currentGeneration = 5;
  const onDocChanged = vi.fn();
  const onPresentation = vi.fn();
  const bridge = new ProductionNarrationEditorBridge({
    kind: "codemirror6",
    lease: { documentId: DOCUMENT_ID, generation: 5 },
    text: SOURCE,
    currentContentHash: options.bridgeContentHash ?? resources.context.working_copy_content_hash,
    onDocChanged,
    isLeaseCurrent: (lease) => (
      lease.documentId === DOCUMENT_ID && lease.generation === currentGeneration
    ),
  });
  bridge.registerPresentationListener(onPresentation);
  const getContext = vi.fn<ChapterNarrationSessionDependencies["getDocumentNarrationContext"]>(
    async () => resources.context,
  );
  const getEdition = vi.fn<ChapterNarrationSessionDependencies["getNarrationEdition"]>(
    async () => resources.edition,
  );
  const getScript = vi.fn<ChapterNarrationSessionDependencies["getNarrationScriptVersionForEdition"]>(
    async () => resources.script,
  );
  const getManifest = options.getManifest
    ? vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(options.getManifest)
    : vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(async () => ({
        not_modified: false,
        etag: resources.manifest.etag,
        manifest: resources.manifest,
      }));
  const prepareRange = vi.fn<ChapterNarrationSessionDependencies["prepareNarrationRange"]>(
    async (_editionId, startSegmentId) => Object.freeze({
      contract_version: "narration-production-api/1",
      edition_id: EDITION_ID,
      start_segment_id: startSegmentId,
      start_ordinal: SEGMENT_IDS.indexOf(startSegmentId as typeof SEGMENT_IDS[number]),
      state: "preparing",
      manifest_revision: resources.manifest.manifest_revision,
      manifest_etag: resources.manifest.etag,
      ready_range: null,
      promoted_job_ids: Object.freeze([]),
    }),
  );
  const getProgress = vi.fn<ChapterNarrationSessionDependencies["getNarrationPlaybackProgress"]>(
    options.getProgress ?? (async (editionId, profileId) => Object.freeze({
      contract_version: "narration-production-api/1",
      edition_id: editionId,
      profile_id: profileId,
      progress: null,
    })),
  );
  let progressVersion = 0;
  const putProgress = vi.fn<ChapterNarrationSessionDependencies["putNarrationPlaybackProgress"]>(
    options.putProgress ?? (async (editionId, request) => {
      progressVersion += 1;
      return Object.freeze({
        contract_version: "narration-production-api/1",
        edition_id: editionId,
        profile_id: request.profile_id,
        progress: Object.freeze({
          manifest_revision: request.manifest_revision,
          manifest_etag: request.manifest_etag,
          edition_segment_id: "10000000-0000-4000-8000-000000000099",
          segment_id: request.segment_id,
          ordinal: SEGMENT_IDS.indexOf(request.segment_id as typeof SEGMENT_IDS[number]),
          offset_ms: request.offset_ms,
          last_legal_start_ordinal: request.last_legal_start_ordinal,
          playback_rate_millis: request.playback_rate_millis,
          manifest_advanced: false,
          progress_updated_at: `2026-08-27T09:30:0${progressVersion}Z`,
        }),
      });
    }),
  );
  const queues: TestQueue[] = [];
  let clock = 0;
  const dependencies: ChapterNarrationSessionDependencies = {
    getDocumentNarrationContext: getContext,
    getNarrationEdition: getEdition,
    getNarrationScriptVersionForEdition: getScript,
    getNarrationManifest: getManifest,
    prepareNarrationRange: prepareRange,
    getNarrationPlaybackProgress: getProgress,
    putNarrationPlaybackProgress: putProgress,
    getNarrationSettings: options.getSettings,
    putNarrationPlaybackPreferences: options.putPreferences,
    createPlayer: options.createPlayer ?? ((playerOptions: CreateNarrationPlayerOptions) => (
      new ProductionNarrationPlayerController({
        ...playerOptions,
        createQueue: (hooks) => {
          const queue = new TestQueue(hooks);
          queues.push(queue);
          return queue;
        },
      })
    )),
    delay: options.delay ?? (async (milliseconds, signal) => {
      if (signal.aborted) throw new DOMException("aborted", "AbortError");
      clock += milliseconds;
    }),
    now: options.now ?? (() => clock),
  };
  const session = createChapterNarrationSession({
    novelId: NOVEL_ID,
    documentId: DOCUMENT_ID,
    generation: 5,
    bridge,
    isGenerationCurrent: (documentId, generation) => (
      documentId === DOCUMENT_ID && generation === currentGeneration
    ),
    onState: options.onState,
    onPlaybackPreferenceStatus: options.onPlaybackPreferenceStatus,
    pollScheduleMs: [1],
    pollTimeoutMs: options.pollTimeoutMs ?? 20,
    maxPollAttempts: 10,
    dependencies,
  });
  return {
    session,
    bridge,
    dependencies,
    queues,
    getContext,
    getEdition,
    getScript,
    getManifest,
    prepareRange,
    onDocChanged,
    onPresentation,
    getProgress,
    putProgress,
    invalidateGeneration() {
      currentGeneration += 1;
    },
  };
}


describe("chapter narration bundle gates", () => {
  it("returns an explicit no-edition result without constructing playback runtime", async () => {
    const initial = fixture();
    const resources = { ...initial, context: noEditionContext() };
    const harness = createHarness({ resources });

    await expect(harness.session.load()).resolves.toMatchObject({ status: "no-edition" });
    expect(harness.session.readSnapshot()).toMatchObject({ phase: "no-edition", bundle: null });
    expect(harness.session.player).toBeNull();
    expect(harness.getEdition).not.toHaveBeenCalled();
    expect(harness.getScript).not.toHaveBeenCalled();
    expect(harness.getManifest).not.toHaveBeenCalled();
  });

  it.each([
    ["Context novel scope", (resources: FixtureResources) => ({
      ...resources,
      context: { ...resources.context, novel_id: CURRENT_EDITION_ID },
    })],
    ["Edition document scope", (resources: FixtureResources) => ({
      ...resources,
      edition: { ...resources.edition, document_id: CURRENT_EDITION_ID },
    })],
    ["Script source scope", (resources: FixtureResources) => ({
      ...resources,
      script: { ...resources.script, revision_id: CURRENT_REVISION_ID },
    })],
    ["Manifest chapter scope", (resources: FixtureResources) => ({
      ...resources,
      manifest: { ...resources.manifest, chapter_id: CURRENT_EDITION_ID },
    })],
  ])("fails closed when %s crosses its authority scope", async (label, mutate) => {
    const harness = createHarness({ resources: mutate(fixture()) });
    await expect(harness.session.load()).rejects.toThrow(/does not match/);
    expect(harness.session.player).toBeNull();
    expect(harness.bridge.readSnapshot().edition).toBeNull();
    if (label === "Script source scope") expect(harness.getManifest).not.toHaveBeenCalled();
  });

  it.each([
    ["duplicate IDs", (resources: FixtureResources) => ({
      ...resources,
      script: {
        ...resources.script,
        segments: [
          resources.script.segments[0],
          { ...resources.script.segments[1], segment_id: SEGMENT_IDS[0] },
        ],
      },
      manifest: {
        ...resources.manifest,
        segments: [
          resources.manifest.segments[0],
          { ...resources.manifest.segments[1], segment_id: SEGMENT_IDS[0] },
        ],
      },
    })],
    ["missing rows", (resources: FixtureResources) => ({
      ...resources,
      manifest: { ...resources.manifest, segments: resources.manifest.segments.slice(0, 1) },
    })],
    ["order drift", (resources: FixtureResources) => ({
      ...resources,
      manifest: {
        ...resources.manifest,
        segments: [resources.manifest.segments[1], resources.manifest.segments[0]],
      },
    })],
    ["incomplete source anchors", (resources: FixtureResources) => ({
      ...resources,
      script: {
        ...resources.script,
        segments: [
          { ...resources.script.segments[0], source_start_utf16: null },
          resources.script.segments[1],
        ],
      },
    })],
  ])("rejects %s before binding the editor", async (_label, mutate) => {
    const harness = createHarness({ resources: mutate(fixture()) });
    await expect(harness.session.load()).rejects.toThrow();
    expect(harness.bridge.readSnapshot().edition).toBeNull();
    expect(harness.queues).toHaveLength(0);
  });

  it("rolls back a current-source Bridge binding if player construction fails", async () => {
    const createPlayer = vi.fn<ChapterNarrationSessionDependencies["createPlayer"]>(() => {
      throw new Error("player construction failed");
    });
    const harness = createHarness({ createPlayer });

    await expect(harness.session.load()).rejects.toThrow("player construction failed");
    expect(createPlayer).toHaveBeenCalledOnce();
    expect(harness.session.readSnapshot()).toMatchObject({ phase: "error", bundle: null });
    expect(harness.session.player).toBeNull();
    expect(harness.bridge.readSnapshot().edition).toBeNull();
  });

  it("rejects a stale Bridge content hash even when visible text still matches", async () => {
    const harness = createHarness({ bridgeContentHash: WORKING_HASH });

    await expect(harness.session.load()).rejects.toThrow(
      "Bridge did not confirm the exact current source",
    );
    expect(harness.session.player).toBeNull();
    expect(harness.bridge.readSnapshot().edition).toBeNull();
  });
});


describe("chapter narration editor and playback integration", () => {
  it("applies work playback preferences immediately and persists only the narrow CAS payload", async () => {
    vi.useFakeTimers();
    const statuses = vi.fn();
    const getSettings = vi.fn<NonNullable<ChapterNarrationSessionDependencies["getNarrationSettings"]>>(
      async () => narrationSettings(),
    );
    const putPreferences = vi.fn<NonNullable<ChapterNarrationSessionDependencies["putNarrationPlaybackPreferences"]>>(
      async (_novelId, request) => narrationSettings(5, request.playback),
    );
    const harness = createHarness({
      getSettings,
      putPreferences,
      onPlaybackPreferenceStatus: statuses,
    });

    try {
      await harness.session.load();
      expect(harness.session.readSnapshot().playerState).toMatchObject({
        rate: 0.9,
        volume: 0.4,
      });

      harness.session.setRate(1.5);
      harness.session.setVolume(0.25);
      expect(harness.session.readSnapshot().playerState).toMatchObject({
        rate: 1.5,
        volume: 0.25,
      });
      await vi.advanceTimersByTimeAsync(250);

      expect(putPreferences).toHaveBeenCalledWith(NOVEL_ID, {
        expected_version: 4,
        playback: { playback_rate: 1.5, volume: 0.25 },
      });
      expect(statuses).toHaveBeenLastCalledWith("saved");
    } finally {
      harness.session.dispose();
      vi.useRealTimers();
    }
  });

  it("restores the exact profile position, rate, and real queue start offset", async () => {
    const resources = fixture();
    const getProgress = vi.fn<ChapterNarrationSessionDependencies["getNarrationPlaybackProgress"]>(
      async (editionId, profileId) => ({
        contract_version: "narration-production-api/1",
        edition_id: editionId,
        profile_id: profileId,
        progress: {
          manifest_revision: resources.manifest.manifest_revision,
          manifest_etag: resources.manifest.etag,
          edition_segment_id: "10000000-0000-4000-8000-000000000099",
          segment_id: SEGMENT_IDS[1],
          ordinal: 1,
          offset_ms: 450,
          last_legal_start_ordinal: 1,
          playback_rate_millis: 1_250,
          manifest_advanced: false,
          progress_updated_at: "2026-08-27T09:30:00Z",
        },
      }),
    );
    const harness = createHarness({ resources, getProgress });

    await harness.session.load();

    expect(harness.getProgress).toHaveBeenCalledWith(
      EDITION_ID,
      "desktop.default",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(harness.session.readSnapshot().playerState).toMatchObject({
      phase: "idle",
      currentSegmentId: SEGMENT_IDS[1],
      currentOrdinal: 1,
      offsetMs: 450,
      rate: 1.25,
    });
    await harness.session.playSegment(SEGMENT_IDS[1], "readonly-segment", 450);
    expect(harness.queues[0].starts[0]).toMatchObject({
      startOrdinal: 1,
      startOffsetMs: 450,
      rate: 1.25,
    });
  });

  it("advances restore only to a newer Manifest of the same exact Edition", async () => {
    const resources = fixture();
    const advanced = manifest(["ready", "ready"], 2, "2");
    const getManifest = vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(
      async (_editionId, options) => options?.manifestRevision === 2
        ? { not_modified: false, etag: advanced.etag, manifest: advanced }
        : { not_modified: false, etag: resources.manifest.etag, manifest: resources.manifest },
    );
    const getProgress = vi.fn<ChapterNarrationSessionDependencies["getNarrationPlaybackProgress"]>(
      async (editionId, profileId) => ({
        contract_version: "narration-production-api/1",
        edition_id: editionId,
        profile_id: profileId,
        progress: {
          manifest_revision: 2,
          manifest_etag: advanced.etag,
          edition_segment_id: "10000000-0000-4000-8000-000000000099",
          segment_id: SEGMENT_IDS[0],
          ordinal: 0,
          offset_ms: 200,
          last_legal_start_ordinal: 0,
          playback_rate_millis: 1_000,
          manifest_advanced: true,
          progress_updated_at: "2026-08-27T09:30:00Z",
        },
      }),
    );
    const harness = createHarness({ resources, getManifest, getProgress });

    await harness.session.load();

    expect(harness.session.readSnapshot().bundle?.manifest.manifest_revision).toBe(2);
    expect(harness.getManifest).toHaveBeenLastCalledWith(
      EDITION_ID,
      expect.objectContaining({ manifestRevision: 2 }),
    );
  });

  it("keeps narration ready when progress restore fails", async () => {
    const harness = createHarness({
      getProgress: async () => { throw new Error("progress unavailable"); },
    });

    await expect(harness.session.load()).resolves.toMatchObject({ status: "ready" });
    expect(harness.session.readSnapshot()).toMatchObject({
      phase: "ready",
      playerState: { currentSegmentId: null, offsetMs: 0, rate: 1 },
    });
  });

  it("fails closed on a cross-Edition progress envelope without blocking narration", async () => {
    const resources = fixture();
    const getProgress = vi.fn<ChapterNarrationSessionDependencies["getNarrationPlaybackProgress"]>(
      async (_editionId, profileId) => ({
        contract_version: "narration-production-api/1",
        edition_id: "10000000-0000-4000-8000-000000000088",
        profile_id: profileId,
        progress: {
          manifest_revision: resources.manifest.manifest_revision,
          manifest_etag: resources.manifest.etag,
          edition_segment_id: "10000000-0000-4000-8000-000000000099",
          segment_id: SEGMENT_IDS[1],
          ordinal: 1,
          offset_ms: 450,
          last_legal_start_ordinal: 1,
          playback_rate_millis: 1_250,
          manifest_advanced: false,
          progress_updated_at: "2026-08-27T09:30:00Z",
        },
      }),
    );
    const harness = createHarness({ resources, getProgress });

    await expect(harness.session.load()).resolves.toMatchObject({ status: "ready" });
    expect(harness.session.readSnapshot().playerState).toMatchObject({
      phase: "idle",
      currentSegmentId: null,
      currentOrdinal: null,
      offsetMs: 0,
      rate: 1,
    });
  });

  it("debounces progress writes and advances the per-Edition CAS token", async () => {
    vi.useFakeTimers();
    try {
      const harness = createHarness();
      await harness.session.load();
      await harness.session.playSegment(SEGMENT_IDS[0]);
      harness.session.setRate(1.5);

      await vi.advanceTimersByTimeAsync(250);
      expect(harness.putProgress).toHaveBeenCalledTimes(1);
      expect(harness.putProgress.mock.calls[0][1]).toMatchObject({
        profile_id: "desktop.default",
        segment_id: SEGMENT_IDS[0],
        playback_rate_millis: 1_500,
        expected_updated_at: null,
      });

      harness.session.pause();
      await vi.advanceTimersByTimeAsync(250);
      expect(harness.putProgress).toHaveBeenCalledTimes(2);
      expect(harness.putProgress.mock.calls[1][1].expected_updated_at).toBe(
        "2026-08-27T09:30:01Z",
      );

      harness.session.noteWorkingCopyChanged();
      await vi.advanceTimersByTimeAsync(300);
      expect(harness.putProgress).toHaveBeenCalledTimes(2);
      harness.session.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("binds exact current-source mappings while highlight/follow remains presentation-only", async () => {
    const harness = createHarness();
    await harness.session.load();

    expect(harness.bridge.readSnapshot().edition).toMatchObject({
      editionId: EDITION_ID,
      sourceRevisionId: REVISION_ID,
      sourceContentHash: SOURCE_HASH,
    });
    expect(harness.bridge.mappingFor(SEGMENT_IDS[1], {
      lease: harness.bridge.lease,
      editionId: EDITION_ID,
    })).toMatchObject({
      state: "mapped",
      currentRange: {
        startUtf16: SOURCE_TEXTS[0].length,
        endUtf16: SOURCE.length,
      },
    });

    await expect(harness.session.playSegment(SEGMENT_IDS[1], "command")).resolves.toMatchObject({
      status: "completed",
      decision: { kind: "play", segmentId: SEGMENT_IDS[1] },
    });
    expect(harness.bridge.readSnapshot().currentSegmentId).toBe(SEGMENT_IDS[1]);
    expect(harness.session.noteAuthorInteraction("manual-scroll")).toBe(true);
    expect(harness.session.resumeFollow()).toBe(true);
    harness.session.setRate(1.5);
    harness.session.pause();
    await expect(harness.session.resume()).resolves.toMatchObject({
      status: "completed",
      decision: { kind: "play", segmentId: SEGMENT_IDS[1] },
    });

    expect(harness.onPresentation).toHaveBeenCalled();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("projects the first local edit immediately while audio continues and only safe mappings remain", async () => {
    const onState = vi.fn();
    const harness = createHarness({ onState });
    await harness.session.load();
    await harness.session.playSegment(SEGMENT_IDS[1], "command");
    const stateBefore = harness.session.player?.readState();
    const requestsBefore = harness.getManifest.mock.calls.length;
    const startsBefore = harness.queues[0].starts.length;

    harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 1, endUtf16: 1, insertedText: "新" }],
    });
    expect(harness.session.noteWorkingCopyChanged()).toBe(true);

    expect(harness.session.readSnapshot()).toMatchObject({
      phase: "ready",
      workingCopyDiverged: true,
      mappedSegmentIds: [SEGMENT_IDS[1]],
      playerState: expect.objectContaining({
        phase: "playing",
        currentSegmentId: SEGMENT_IDS[1],
      }),
    });
    expect(harness.bridge.readSnapshot().currentSegmentId).toBe(SEGMENT_IDS[1]);
    expect(harness.session.player?.readState()).toEqual(stateBefore);
    expect(harness.queues[0].starts).toHaveLength(startsBefore);
    expect(harness.getManifest).toHaveBeenCalledTimes(requestsBefore);
    expect(harness.prepareRange).not.toHaveBeenCalled();
    expect(harness.queues[0].pauseCount).toBe(0);
    expect(harness.onDocChanged).toHaveBeenCalledOnce();

    const secondMapping = harness.bridge.mappingFor(SEGMENT_IDS[1], {
      lease: harness.bridge.lease,
      editionId: EDITION_ID,
    });
    if (secondMapping?.state !== "mapped") throw new Error("expected safe second mapping");
    harness.bridge.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: secondMapping.currentRange.startUtf16 + 1,
        endUtf16: secondMapping.currentRange.startUtf16 + 1,
        insertedText: "改",
      }],
    });
    expect(harness.session.noteWorkingCopyChanged()).toBe(true);
    expect(harness.session.readSnapshot().mappedSegmentIds).toEqual([]);
    expect(harness.bridge.readSnapshot().currentSegmentId).toBeNull();
    expect(harness.session.player?.readState()).toMatchObject({
      phase: "playing",
      currentSegmentId: SEGMENT_IDS[1],
    });
    expect(harness.queues[0].pauseCount).toBe(0);
    expect(harness.prepareRange).not.toHaveBeenCalled();
    expect(onState).toHaveBeenLastCalledWith(expect.objectContaining({
      workingCopyDiverged: true,
      mappedSegmentIds: [],
    }));
  });

  it("reloads a locally diverged current Edition conservatively without rebinding decorations", async () => {
    const harness = createHarness();
    await harness.session.load();
    harness.bridge.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 1, endUtf16: 1, insertedText: "新" }],
    });
    expect(harness.session.noteWorkingCopyChanged()).toBe(true);

    await expect(harness.session.refresh()).resolves.toMatchObject({ status: "ready" });
    expect(harness.session.readSnapshot()).toMatchObject({
      phase: "ready",
      workingCopyDiverged: true,
      mappedSegmentIds: [],
      bundle: { edition: { edition_id: EDITION_ID } },
    });
    expect(harness.bridge.readSnapshot()).toMatchObject({
      edition: { editionId: EDITION_ID },
      exactEditionText: false,
      currentSegmentId: null,
    });
    expect(harness.prepareRange).not.toHaveBeenCalled();
  });

  it("rejects a late live projection after the document generation changes", async () => {
    const onState = vi.fn();
    const harness = createHarness({ onState });
    await harness.session.load();
    const snapshot = harness.session.readSnapshot();
    const stateCalls = onState.mock.calls.length;

    harness.invalidateGeneration();

    expect(harness.session.noteWorkingCopyChanged()).toBe(false);
    expect(harness.session.readSnapshot()).toBe(snapshot);
    expect(onState).toHaveBeenCalledTimes(stateCalls);
    expect(harness.prepareRange).not.toHaveBeenCalled();
  });

  it("keeps an old immutable Edition playable without decorating the working copy", async () => {
    const harness = createHarness({ resources: fixture(["ready", "ready"], true) });
    await harness.session.load();

    expect(harness.bridge.readSnapshot().edition).toBeNull();
    expect(harness.session.player).not.toBeNull();
    expect(harness.session.coordinator).not.toBeNull();
    expect(harness.session.follow).not.toBeNull();
    await expect(harness.session.playSegment(SEGMENT_IDS[0])).resolves.toMatchObject({
      status: "completed",
      decision: { kind: "play", segmentId: SEGMENT_IDS[0] },
    });
    expect(harness.queues[0].starts[0].startOrdinal).toBe(0);
    expect(harness.bridge.readSnapshot().currentSegmentId).toBeNull();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });

  it("polls with the latest ETag and replays only after a ready range appears", async () => {
    const resources = fixture(["pending", "pending"]);
    const pendingV2 = manifest(["pending", "pending"], 2, "2");
    const readyV3 = manifest(["ready", "ready"], 3, "3");
    let pollIndex = 0;
    const getManifest = vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(
      async (_editionId, options): Promise<ManifestFetchResult> => {
        if (options?.manifestRevision !== undefined) {
          return { not_modified: false, etag: resources.manifest.etag, manifest: resources.manifest };
        }
        pollIndex += 1;
        if (pollIndex === 1) {
          return { not_modified: false, etag: pendingV2.etag, manifest: pendingV2 };
        }
        if (pollIndex === 2) {
          return { not_modified: true, etag: pendingV2.etag, manifest: null };
        }
        return { not_modified: false, etag: readyV3.etag, manifest: readyV3 };
      },
    );
    const harness = createHarness({ resources, getManifest });
    await harness.session.load();

    await expect(harness.session.playSegment(SEGMENT_IDS[0], "gutter")).resolves.toMatchObject({
      status: "completed",
      decision: { kind: "play", segmentId: SEGMENT_IDS[0] },
    });
    const pollOptions = harness.getManifest.mock.calls
      .map((call) => call[1])
      .filter((options): options is NonNullable<typeof options> => (
        options?.ifNoneMatch !== undefined
      ));
    expect(pollOptions.map((options) => options.ifNoneMatch)).toEqual([
      resources.manifest.etag,
      pendingV2.etag,
      pendingV2.etag,
    ]);
    expect(pollOptions.every((options) => options.signal instanceof AbortSignal)).toBe(true);
    expect(harness.prepareRange).toHaveBeenCalledOnce();
    expect(harness.queues[0].starts).toHaveLength(1);
    expect(
      harness.session.readSnapshot().bundle?.segmentById.get(SEGMENT_IDS[0])?.manifest.render_status,
    ).toBe("ready");
  });

  it("cancels an older seek poll and only replays the latest segment", async () => {
    const resources = fixture(["pending", "pending"]);
    const ready = manifest(["ready", "ready"], 2, "2");
    let pollCount = 0;
    let firstPollSignal: AbortSignal | undefined;
    let resolveFirstPoll!: (result: ManifestFetchResult) => void;
    let notifyFirstPoll!: () => void;
    const firstPollStarted = new Promise<void>((resolve) => { notifyFirstPoll = resolve; });
    const getManifest = vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(
      async (_editionId, options): Promise<ManifestFetchResult> => {
        if (options?.manifestRevision !== undefined) {
          return { not_modified: false, etag: resources.manifest.etag, manifest: resources.manifest };
        }
        pollCount += 1;
        if (pollCount === 1) {
          firstPollSignal = options?.signal;
          notifyFirstPoll();
          return new Promise<ManifestFetchResult>((resolve) => {
            resolveFirstPoll = resolve;
          });
        }
        return { not_modified: false, etag: ready.etag, manifest: ready };
      },
    );
    const harness = createHarness({ resources, getManifest });
    await harness.session.load();

    const first = harness.session.playSegment(SEGMENT_IDS[0], "gutter");
    await firstPollStarted;
    const second = harness.session.playSegment(SEGMENT_IDS[1], "command");

    await expect(second).resolves.toMatchObject({
      status: "completed",
      decision: { kind: "play", segmentId: SEGMENT_IDS[1] },
    });
    resolveFirstPoll({ not_modified: false, etag: ready.etag, manifest: ready });
    await expect(first).resolves.toEqual({ status: "superseded", segmentId: SEGMENT_IDS[0] });
    expect(firstPollSignal?.aborted).toBe(true);
    expect(harness.queues[0].starts.map((start) => start.startOrdinal)).toEqual([1]);
    expect(harness.bridge.readSnapshot().currentSegmentId).toBe(SEGMENT_IDS[1]);
    expect(harness.session.readSnapshot().lastPlayResult).toMatchObject({
      status: "completed",
      decision: { kind: "play", segmentId: SEGMENT_IDS[1] },
    });
  });

  it.each(["failed", "cancelled"] as const)(
    "stops polling when the target becomes %s",
    async (terminalState) => {
      const resources = fixture(["pending", "pending"]);
      const terminal = manifest([terminalState, "pending"], 2, "2");
      const getManifest = vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(
        async (_editionId, options) => options?.manifestRevision !== undefined
          ? { not_modified: false, etag: resources.manifest.etag, manifest: resources.manifest }
          : { not_modified: false, etag: terminal.etag, manifest: terminal },
      );
      const harness = createHarness({ resources, getManifest });
      await harness.session.load();

      await expect(harness.session.playSegment(SEGMENT_IDS[0])).resolves.toMatchObject({
        status: "completed",
        decision: { kind: "blocked" },
      });
      expect(harness.getManifest).toHaveBeenCalledTimes(2);
      expect(harness.queues[0].starts).toHaveLength(0);
    },
  );

  it("times out after bounded delay without issuing a post-deadline Manifest request", async () => {
    const resources = fixture(["pending", "pending"]);
    let clock = 0;
    const delay = vi.fn<ChapterNarrationSessionDependencies["delay"]>(
      async (milliseconds, signal) => {
        if (signal.aborted) throw new DOMException("aborted", "AbortError");
        clock += milliseconds * 20;
      },
    );
    const harness = createHarness({ resources, delay, now: () => clock });
    await harness.session.load();

    await expect(harness.session.playSegment(SEGMENT_IDS[0])).resolves.toEqual({
      status: "timeout",
      segmentId: SEGMENT_IDS[0],
      attempts: 1,
    });
    expect(harness.getManifest).toHaveBeenCalledTimes(1);
    expect(delay).toHaveBeenCalledOnce();
  });

  it("aborts and bounds a Manifest fetch that never settles", async () => {
    const resources = fixture(["pending", "pending"]);
    let pollSignal: AbortSignal | undefined;
    const getManifest = vi.fn<ChapterNarrationSessionDependencies["getNarrationManifest"]>(
      async (_editionId, options): Promise<ManifestFetchResult> => {
        if (options?.manifestRevision !== undefined) {
          return { not_modified: false, etag: resources.manifest.etag, manifest: resources.manifest };
        }
        pollSignal = options?.signal;
        return new Promise<ManifestFetchResult>(() => undefined);
      },
    );
    const harness = createHarness({ resources, getManifest, pollTimeoutMs: 10 });
    await harness.session.load();

    await expect(harness.session.playSegment(SEGMENT_IDS[0])).resolves.toEqual({
      status: "timeout",
      segmentId: SEGMENT_IDS[0],
      attempts: 1,
    });
    expect(pollSignal?.aborted).toBe(true);
    expect(harness.queues[0].starts).toHaveLength(0);
  });

  it("dispose aborts polling and releases audio, subscriptions, timers, and binding", async () => {
    const resources = fixture(["pending", "pending"]);
    let activeDelays = 0;
    let notifyDelay!: () => void;
    const delayStarted = new Promise<void>((resolve) => { notifyDelay = resolve; });
    const delay = vi.fn<ChapterNarrationSessionDependencies["delay"]>(
      async (_milliseconds, signal) => new Promise<void>((_resolve, reject) => {
        activeDelays += 1;
        notifyDelay();
        signal.addEventListener("abort", () => {
          activeDelays -= 1;
          reject(new DOMException("disposed", "AbortError"));
        }, { once: true });
      }),
    );
    const harness = createHarness({ resources, delay });
    await harness.session.load();
    const play = harness.session.playSegment(SEGMENT_IDS[0]);
    await delayStarted;

    harness.session.dispose();

    await expect(play).resolves.toEqual({ status: "superseded", segmentId: SEGMENT_IDS[0] });
    expect(activeDelays).toBe(0);
    expect(harness.queues[0].disposeCount).toBe(1);
    expect(harness.session.readSnapshot()).toMatchObject({
      phase: "disposed",
      bundle: null,
      pollingSegmentId: null,
    });
    expect(harness.bridge.readSnapshot().edition).toBeNull();
    expect(harness.onDocChanged).not.toHaveBeenCalled();
  });
});
