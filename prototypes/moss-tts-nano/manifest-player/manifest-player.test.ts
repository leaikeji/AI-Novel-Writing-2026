import { describe, expect, it } from "vitest";

import invalidFixture from "./fixtures/manifest-v2.invalid.json";
import validFixture from "./fixtures/manifest-v2.valid.json";
import manifestSchema from "../../../docs/开发文档/证据/MOSS-TTS-Nano施工/T0-G/manifest-v2.schema.json";
import {
  MANIFEST_SCHEMA_VERSION,
  ManifestValidationError,
  PrepareRangeQueue,
  RapidSeekGuard,
  acceptManifestRefresh,
  decidePlayback,
  deriveManifestStatus,
  deriveReadyPrefixCount,
  deriveReadyRanges,
  parseManifest,
  validateManifest,
  type ManifestSegmentV2,
  type NarrationManifestV2,
  type PrepareRangeIntent,
} from "./manifest-player";

const HASH = "a".repeat(64);
const MANIFEST_ETAG = `"${"9".repeat(64)}"`;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function segment(renderStatus: ManifestSegmentV2["render_status"], ordinal: number): ManifestSegmentV2 {
  const actualSha256 = (ordinal % 10).toString().repeat(64);
  return {
    segment_id: `seg-${ordinal}`,
    ordinal,
    paragraph_ordinal: ordinal,
    source_block_key: `block-${ordinal}`,
    source_start_utf16: 0,
    source_end_utf16: 8,
    gap_after_ms: 250,
    render_status: renderStatus,
    audio: renderStatus === "ready" ? {
      url: `/api/ai-novel-world-2026/narration/media/asset-seg-${ordinal}`,
      actual_sha256: actualSha256,
      duration_ms: 3_000 + ordinal,
      sample_rate: 48_000,
      channels: 2,
      etag: `"${actualSha256}"`,
    } : null,
    failure: renderStatus === "failed" ? {
      code: "RENDER_FAILED",
      retryable: true,
      message: "fixture failure",
    } : null,
  };
}

function refreshDerived(candidate: NarrationManifestV2): NarrationManifestV2 {
  candidate.ready_ranges = deriveReadyRanges(candidate.segments, candidate.buffer_policy);
  candidate.ready_prefix_count = deriveReadyPrefixCount(candidate.segments);
  candidate.default_start_ready = candidate.ready_ranges.some((range) => range.start_ordinal === 0);
  candidate.last_playable_start_ordinal = candidate.ready_ranges.length > 0
    ? Math.max(...candidate.ready_ranges.map((range) => range.last_playable_start_ordinal))
    : null;
  candidate.status = deriveManifestStatus(candidate.segments);
  return candidate;
}

function manifest(states: ManifestSegmentV2["render_status"][]): NarrationManifestV2 {
  return refreshDerived({
    schema_version: MANIFEST_SCHEMA_VERSION,
    edition_id: "edition-1",
    chapter_id: "chapter-1",
    source_revision_id: "revision-1",
    source_sha256: HASH,
    buffer_policy: {
      version: "initial-buffer/v1-3-segments-8000ms",
      minimum_segments: 3,
      minimum_duration_ms: 8_000,
      target_segments: 5,
      chapter_end_exception: true,
    },
    manifest_revision: 4,
    etag: MANIFEST_ETAG,
    generated_at: "2026-08-26T08:00:00+08:00",
    status: "pending",
    ready_prefix_count: 0,
    default_start_ready: false,
    last_playable_start_ordinal: null,
    ready_ranges: [],
    segments: states.map(segment),
  });
}

function intent(overrides: Partial<PrepareRangeIntent> = {}): PrepareRangeIntent {
  return {
    requestId: "request-1",
    clientId: "client-1",
    editionId: "edition-1",
    targetSegmentId: "seg-0",
    startOrdinal: 0,
    endOrdinalExclusive: 5,
    manifestRevision: 4,
    priority: "interactive",
    createdAtMs: 10_000,
    ...overrides,
  };
}

describe("Manifest 2.0 wire parsing and validation", () => {
  it("keeps the checked-in JSON Schema aligned with the frozen wire discriminators", () => {
    const schema = manifestSchema as unknown as {
      additionalProperties: boolean;
      required: string[];
      properties: {
        schema_version: { const: string };
        manifest_revision: { minimum: number };
      };
      $defs: {
        segment: { required: string[]; additionalProperties: boolean };
      };
    };
    expect(schema.additionalProperties).toBe(false);
    expect(schema.properties.schema_version.const).toBe(MANIFEST_SCHEMA_VERSION);
    expect(schema.properties.manifest_revision.minimum).toBe(1);
    expect(schema.required).toEqual(expect.arrayContaining([
      "status",
      "ready_prefix_count",
      "default_start_ready",
      "last_playable_start_ordinal",
      "ready_ranges",
    ]));
    expect(schema.$defs.segment.additionalProperties).toBe(false);
    expect(schema.$defs.segment.required).toEqual([
      "segment_id",
      "ordinal",
      "paragraph_ordinal",
      "source_block_key",
      "source_start_utf16",
      "source_end_utf16",
      "gap_after_ms",
      "render_status",
      "audio",
      "failure",
    ]);
    expect(JSON.stringify(schema)).not.toContain("text_sha256");
    expect(JSON.stringify(schema)).not.toContain("text_hmac");
  });

  it("parses the canonical snake_case positive fixture", () => {
    const parsed = parseManifest(clone(validFixture));
    expect(parsed.schema_version).toBe("narration-manifest/2.0");
    expect(parsed.manifest_revision).toBe(4);
    expect(parsed.segments.map((item) => item.ordinal)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(parsed.ready_ranges).toEqual([
      {
        start_ordinal: 0,
        end_ordinal_exclusive: 3,
        segment_count: 3,
        duration_ms: 9_500,
        last_playable_start_ordinal: 0,
      },
      {
        start_ordinal: 4,
        end_ordinal_exclusive: 6,
        segment_count: 2,
        duration_ms: 3_250,
        last_playable_start_ordinal: 5,
      },
    ]);
  });

  it("rejects the checked-in negative fixture", () => {
    const paths = validateManifest(clone(invalidFixture)).map((problem) => problem.path);
    expect(paths).toEqual(expect.arrayContaining([
      "manifest_revision",
      "etag",
      "generated_at",
      "buffer_policy.target_segments",
      "segments[0].text_sha256",
      "segments[0].source_end_utf16",
      "segments[0].audio.url",
      "segments[0].audio.etag",
      "segments[1].ordinal",
    ]));
    expect(() => parseManifest(clone(invalidFixture))).toThrow(ManifestValidationError);
  });

  it("rejects revision zero, non-contiguous ordinal and invalid UTF-16 offsets", () => {
    const candidate = manifest(["ready", "pending"]);
    candidate.manifest_revision = 0;
    candidate.segments[1].ordinal = 5;
    candidate.segments[0].source_end_utf16 = candidate.segments[0].source_start_utf16;
    const paths = validateManifest(candidate).map((problem) => problem.path);
    expect(paths).toEqual(expect.arrayContaining([
      "manifest_revision",
      "segments[0].source_end_utf16",
      "segments[1].ordinal",
    ]));
  });

  it("rejects public short-text digest or HMAC fields", () => {
    for (const field of ["text_sha256", "text_hmac"] as const) {
      const candidate = clone(validFixture) as unknown as Record<string, unknown>;
      const segments = candidate.segments as Array<Record<string, unknown>>;
      segments[0][field] = "secret-derived-value";
      expect(validateManifest(candidate)).toContainEqual({
        path: `segments[0].${field}`,
        message: "is not allowed by the public wire contract",
      });
    }
  });

  it("rejects media URLs carrying tokens, queries, fragments or traversal", () => {
    for (const url of [
      "/api/ai-novel-world-2026/narration/media/a?token=secret",
      "/api/ai-novel-world-2026/narration/media/a#secret",
      "/api/ai-novel-world-2026/narration/media/../secret",
      "https://example.invalid/audio.wav",
    ]) {
      const candidate = clone(validFixture) as unknown as NarrationManifestV2;
      const audio = candidate.segments[0].audio;
      if (!audio) throw new Error("fixture must contain ready audio");
      audio.url = url;
      expect(validateManifest(candidate).map((problem) => problem.path)).toContain("segments[0].audio.url");
    }
  });

  it("requires each audio ETag to identify actual_sha256", () => {
    const candidate = clone(validFixture) as unknown as NarrationManifestV2;
    const audio = candidate.segments[0].audio;
    if (!audio) throw new Error("fixture must contain ready audio");
    audio.etag = `"${"b".repeat(64)}"`;
    expect(validateManifest(candidate)).toContainEqual({
      path: "segments[0].audio.etag",
      message: "must identify the actual audio SHA-256",
    });
  });

  it("rejects any server ready-range field that drifts from segments and buffer_policy", () => {
    const mutations: Array<[keyof NarrationManifestV2["ready_ranges"][number], number]> = [
      ["start_ordinal", 1],
      ["end_ordinal_exclusive", 4],
      ["segment_count", 2],
      ["duration_ms", 9_499],
      ["last_playable_start_ordinal", 1],
    ];
    for (const [field, value] of mutations) {
      const candidate = clone(validFixture) as unknown as NarrationManifestV2;
      candidate.ready_ranges[0][field] = value;
      expect(validateManifest(candidate).map((problem) => problem.path)).toContain(`ready_ranges[0].${field}`);
    }
  });

  it("rejects derived prefix, default start, global last playable and status drift", () => {
    const candidate = clone(validFixture) as unknown as NarrationManifestV2;
    candidate.ready_prefix_count = 2;
    candidate.default_start_ready = false;
    candidate.last_playable_start_ordinal = 4;
    candidate.status = "ready";
    expect(validateManifest(candidate).map((problem) => problem.path)).toEqual(expect.arrayContaining([
      "ready_prefix_count",
      "default_start_ready",
      "last_playable_start_ordinal",
      "status",
    ]));
  });
});

describe("server-authoritative ready ranges and playback decisions", () => {
  it("derives only playable disjoint ranges without crossing a pending gap", () => {
    const candidate = manifest(["ready", "ready", "ready", "pending", "ready", "ready"]);
    expect(candidate.ready_ranges.map((range) => [range.start_ordinal, range.end_ordinal_exclusive])).toEqual([
      [0, 3],
      [4, 6],
    ]);
    expect(candidate.ready_ranges[0].duration_ms).toBe(9_503);
    expect(candidate.ready_ranges[0].last_playable_start_ordinal).toBe(0);
    expect(candidate.ready_ranges[1].last_playable_start_ordinal).toBe(5);
  });

  it("omits a non-final ready island that has no legal playback start", () => {
    const candidate = manifest(["ready", "ready", "pending", "ready", "ready"]);
    expect(candidate.ready_prefix_count).toBe(2);
    expect(candidate.default_start_ready).toBe(false);
    expect(candidate.ready_ranges.map((range) => [range.start_ordinal, range.end_ordinal_exclusive])).toEqual([[3, 5]]);
  });

  it("uses server default_start_ready and never jumps over a chapter-start gap", () => {
    const decision = decidePlayback(manifest(["ready", "ready", "pending", "ready", "ready"]));
    expect(decision).toMatchObject({
      kind: "prepare_required",
      target_segment_id: "seg-0",
      reason: "ready_window_too_short",
      requested_start_ordinal: 0,
    });
  });

  it("plays an explicit middle segment only when the authoritative range allows that start", () => {
    const candidate = manifest(["pending", "pending", "ready", "ready", "ready", "pending"]);
    expect(decidePlayback(candidate, "seg-2")).toMatchObject({
      kind: "play",
      target_segment_id: "seg-2",
      ready_range: { start_ordinal: 2, end_ordinal_exclusive: 5, segment_count: 3 },
    });
    expect(decidePlayback(candidate, "seg-3")).toMatchObject({
      kind: "prepare_required",
      reason: "ready_window_too_short",
    });
  });

  it("requires both segment count and duration before a non-final gap", () => {
    const candidate = manifest(["ready", "ready", "ready", "pending"]);
    for (const item of candidate.segments.slice(0, 3)) {
      if (item.audio) item.audio.duration_ms = 1_000;
    }
    refreshDerived(candidate);
    expect(decidePlayback(candidate)).toMatchObject({
      kind: "prepare_required",
      reason: "ready_window_too_short",
    });
  });

  it("allows the fully ready chapter remainder below thresholds only when policy permits", () => {
    const candidate = manifest(["pending", "pending", "ready"]);
    if (candidate.segments[2].audio) candidate.segments[2].audio.duration_ms = 500;
    refreshDerived(candidate);
    expect(decidePlayback(candidate, "seg-2")).toMatchObject({
      kind: "play",
      ready_range: { start_ordinal: 2, end_ordinal_exclusive: 3, duration_ms: 500 },
    });

    candidate.buffer_policy.chapter_end_exception = false;
    refreshDerived(candidate);
    expect(decidePlayback(candidate, "seg-2")).toMatchObject({
      kind: "prepare_required",
      reason: "ready_window_too_short",
    });
  });

  it("never skips a failed segment inside the requested window", () => {
    expect(decidePlayback(manifest(["ready", "ready", "failed", "ready"]), "seg-0")).toMatchObject({
      kind: "blocked",
      reason: "gap_failed",
      failed_segment_id: "seg-2",
    });
  });

  it("requests the selected range instead of falling back to chapter start", () => {
    expect(decidePlayback(
      manifest(["ready", "ready", "pending", "pending", "pending", "ready"]),
      "seg-3",
    )).toMatchObject({
      kind: "prepare_required",
      target_segment_id: "seg-3",
      requested_start_ordinal: 3,
      requested_end_ordinal_exclusive: 6,
    });
  });
});

describe("manifest refresh", () => {
  it("accepts same-edition monotonic revisions", () => {
    const current = manifest(["ready", "pending"]);
    const incoming = manifest(["ready", "ready"]);
    incoming.manifest_revision = current.manifest_revision + 1;
    incoming.etag = `"${"8".repeat(64)}"`;
    expect(acceptManifestRefresh(current, incoming)).toEqual({ accepted: true });
  });

  it("rejects implicit edition switches and source changes", () => {
    const current = manifest(["ready"]);
    const otherEdition = clone(current);
    otherEdition.edition_id = "edition-2";
    expect(acceptManifestRefresh(current, otherEdition)).toEqual({ accepted: false, reason: "edition_changed" });

    const otherSource = clone(current);
    otherSource.source_sha256 = "b".repeat(64);
    expect(acceptManifestRefresh(current, otherSource)).toEqual({ accepted: false, reason: "source_changed" });
  });

  it("accepts an idempotent refresh but rejects a reused revision with another strong ETag", () => {
    const current = manifest(["ready", "pending"]);
    expect(acceptManifestRefresh(current, clone(current))).toEqual({ accepted: true });

    const collision = clone(current);
    collision.etag = `"${"7".repeat(64)}"`;
    expect(acceptManifestRefresh(current, collision)).toEqual({
      accepted: false,
      reason: "revision_collision",
    });
  });

  it("rejects a regressed or structurally invalid revision", () => {
    const current = manifest(["ready"]);
    const stale = clone(current);
    stale.manifest_revision = 3;
    expect(acceptManifestRefresh(current, stale)).toEqual({ accepted: false, reason: "revision_regressed" });
    stale.manifest_revision = 0;
    expect(acceptManifestRefresh(current, stale)).toEqual({ accepted: false, reason: "invalid" });
  });
});

describe("prepare-range scheduling", () => {
  it("supersedes older rapid seeks for the same client and edition", () => {
    const queue = new PrepareRangeQueue();
    queue.enqueue(intent({ requestId: "old", targetSegmentId: "seg-2" }));
    const superseded = queue.enqueue(intent({ requestId: "new", targetSegmentId: "seg-9", createdAtMs: 10_001 }));
    expect(superseded).toEqual(["old"]);
    expect(queue.has("old")).toBe(false);
    expect(queue.has("new")).toBe(true);
  });

  it("lets an old background request win through bounded fairness aging", () => {
    const queue = new PrepareRangeQueue();
    queue.enqueue(intent({
      requestId: "background",
      clientId: "batch-client",
      priority: "background",
      createdAtMs: 0,
    }));
    queue.enqueue(intent({ requestId: "interactive", createdAtMs: 1_000_000 }));
    expect(queue.next(1_000_000, 2_000)?.requestId).toBe("background");
  });

  it("rejects stale prepare-range completions after a newer seek", () => {
    const guard = new RapidSeekGuard();
    const first = guard.begin("request-1", "edition-1", "seg-2");
    const second = guard.begin("request-2", "edition-1", "seg-8");
    expect(guard.accepts(first)).toBe(false);
    expect(guard.accepts(second)).toBe(true);
  });
});
