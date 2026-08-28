import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import manifestFixture from "../../../tests/fixtures/narration/manifest-v2.json";
import {
  fetchPlaybackMedia,
  getNarrationManifest,
  getNarrationPlaybackProgress,
  headPlaybackMedia,
  PlaybackApiError,
  prepareNarrationRange,
  putNarrationPlaybackProgress,
} from "./playback-api";
import {
  ManifestValidationError,
  parseManifest,
  PlaybackContractError,
  validateManifest,
} from "./playback-contracts";


const EDITION_ID = "10000000-0000-4000-8000-000000000001";
const SEGMENT_ID = "10000000-0000-4000-8000-000000000010";
const JOB_ID = "30000000-0000-4000-8000-000000000001";
const EDITION_SEGMENT_ID = "10000000-0000-4000-8000-000000000011";
const PROFILE_ID = "desktop:default";
const UPDATED_AT = "2026-08-27T09:30:00.123456+00:00";
const AUDIO_URL = "/api/ai-novel-world-2026/media-assets/20000000-0000-4000-8000-000000000020/content";
const MANIFEST_ETAG = `"${"364aca770ad453baafb24b0193e0a44ea0aa1887c63be073cf03401ca4dab2fe"}"`;
const AUDIO_ETAG = `"${"1".repeat(64)}"`;


function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}


const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();


beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
});


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("Manifest v2 production parser", () => {
  it("accepts and freezes the canonical production fixture", () => {
    const manifest = parseManifest(clone(manifestFixture));
    expect(manifest.schema_version).toBe("narration-manifest/2.0");
    expect(manifest.ready_prefix_count).toBe(3);
    expect(manifest.ready_ranges[0]).toEqual({
      start_ordinal: 0,
      end_ordinal_exclusive: 3,
      segment_count: 3,
      duration_ms: 9500,
      last_playable_start_ordinal: 0,
    });
    expect(Object.isFrozen(manifest)).toBe(true);
    expect(Object.isFrozen(manifest.segments)).toBe(true);
    expect(JSON.stringify(manifest)).not.toContain("text_sha256");
    expect(JSON.stringify(manifest)).not.toContain("text_hmac");
  });

  it("rejects extra fields, derived drift and non-production media URLs", () => {
    const extra = clone(manifestFixture) as unknown as Record<string, unknown>;
    extra.text_hmac = "secret-derived-value";
    expect(validateManifest(extra).map((item) => item.path)).toContain("$.text_hmac");

    const drift = clone(manifestFixture);
    drift.ready_prefix_count = 2;
    expect(() => parseManifest(drift)).toThrow(ManifestValidationError);

    const unsafe = clone(manifestFixture);
    const audio = unsafe.segments[0].audio;
    if (!audio) throw new Error("fixture must have playback audio");
    audio.url = `${audio.url}?token=secret`;
    expect(validateManifest(unsafe).map((item) => item.path)).toContain("segments[0].audio.url");
  });
});


describe("playback API host facade", () => {
  it("loads an exact Manifest with conditional ETag and AbortSignal", async () => {
    const signal = new AbortController().signal;
    fetchMock.mockResolvedValue(new Response(JSON.stringify(manifestFixture), {
      status: 200,
      headers: { "Content-Type": "application/json", ETag: MANIFEST_ETAG },
    }));

    const result = await getNarrationManifest(EDITION_ID, {
      manifestRevision: 4,
      ifNoneMatch: MANIFEST_ETAG,
      signal,
    });

    expect(result.not_modified).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe(`/${"ai-novel-world-2026"}/narration-editions/${EDITION_ID}/manifest?manifest_revision=4`);
    expect(init?.signal).toBe(signal);
    expect(init?.headers).not.toBeInstanceOf(Headers);
    expect(Object.getPrototypeOf(init?.headers)).toBe(Object.prototype);
    expect(new Headers(init?.headers).get("If-None-Match")).toBe(MANIFEST_ETAG);
  });

  it("preserves a 304 without inventing a Manifest", async () => {
    fetchMock.mockResolvedValue(new Response(null, {
      status: 304,
      headers: { ETag: MANIFEST_ETAG },
    }));
    await expect(getNarrationManifest(EDITION_ID, { ifNoneMatch: MANIFEST_ETAG })).resolves.toEqual({
      not_modified: true,
      etag: MANIFEST_ETAG,
      manifest: null,
    });
  });

  it("posts prepare-range with the frozen scope and parses promoted jobs", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      contract_version: "narration-production-api/1",
      edition_id: EDITION_ID,
      start_segment_id: SEGMENT_ID,
      start_ordinal: 0,
      state: "preparing",
      manifest_revision: 4,
      manifest_etag: MANIFEST_ETAG,
      ready_range: null,
      promoted_job_ids: [JOB_ID],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const result = await prepareNarrationRange(
      EDITION_ID,
      SEGMENT_ID,
      "user_seek",
      4,
      "seek:test:0001",
    );
    expect(result.promoted_job_ids).toEqual([JOB_ID]);
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("seek:test:0001");
    expect(JSON.parse(String(init?.body))).toEqual({
      start_segment_id: SEGMENT_ID,
      reason: "user_seek",
      expected_manifest_revision: 4,
    });
  });

  it("restores an explicit null or exact progress projection through the scoped GET", async () => {
    const signal = new AbortController().signal;
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({
        contract_version: "narration-production-api/1",
        edition_id: EDITION_ID,
        profile_id: PROFILE_ID,
        progress: null,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        contract_version: "narration-production-api/1",
        edition_id: EDITION_ID,
        profile_id: PROFILE_ID,
        progress: {
          manifest_revision: 5,
          manifest_etag: MANIFEST_ETAG,
          edition_segment_id: EDITION_SEGMENT_ID,
          segment_id: SEGMENT_ID,
          ordinal: 2,
          offset_ms: 450,
          last_legal_start_ordinal: 1,
          playback_rate_millis: 1_250,
          manifest_advanced: true,
          progress_updated_at: UPDATED_AT,
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const missing = await getNarrationPlaybackProgress(
      EDITION_ID,
      PROFILE_ID,
      { signal },
    );
    const restored = await getNarrationPlaybackProgress(EDITION_ID, PROFILE_ID);

    expect(missing.progress).toBeNull();
    expect(restored.progress).toMatchObject({
      manifest_revision: 5,
      manifest_advanced: true,
      progress_updated_at: UPDATED_AT,
    });
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/${"ai-novel-world-2026"}/narration-editions/${EDITION_ID}/playback-progress?profile_id=desktop%3Adefault`,
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("GET");
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(signal);
  });

  it("saves every progress fence and accepts a newer Manifest of the same Edition", async () => {
    const signal = new AbortController().signal;
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      contract_version: "narration-production-api/1",
      edition_id: EDITION_ID,
      profile_id: PROFILE_ID,
      progress: {
        manifest_revision: 5,
        manifest_etag: MANIFEST_ETAG,
        edition_segment_id: EDITION_SEGMENT_ID,
        segment_id: SEGMENT_ID,
        ordinal: 2,
        offset_ms: 450,
        last_legal_start_ordinal: 1,
        playback_rate_millis: 1_250,
        manifest_advanced: true,
        progress_updated_at: UPDATED_AT,
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    const result = await putNarrationPlaybackProgress(EDITION_ID, {
      profile_id: PROFILE_ID,
      manifest_revision: 4,
      manifest_etag: MANIFEST_ETAG,
      edition_segment_id: EDITION_SEGMENT_ID,
      segment_id: SEGMENT_ID,
      offset_ms: 450,
      last_legal_start_ordinal: 1,
      playback_rate_millis: 1_250,
      expected_updated_at: "2026-08-27T09:29:00Z",
    }, { signal });

    expect(result.progress).toMatchObject({ manifest_revision: 5, manifest_advanced: true });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toContain(`/narration-editions/${EDITION_ID}/playback-progress?profile_id=desktop%3Adefault`);
    expect(init?.method).toBe("PUT");
    expect(init?.signal).toBe(signal);
    expect(JSON.parse(String(init?.body))).toEqual({
      profile_id: PROFILE_ID,
      manifest_revision: 4,
      manifest_etag: MANIFEST_ETAG,
      edition_segment_id: EDITION_SEGMENT_ID,
      segment_id: SEGMENT_ID,
      offset_ms: 450,
      last_legal_start_ordinal: 1,
      playback_rate_millis: 1_250,
      expected_updated_at: "2026-08-27T09:29:00Z",
    });
  });

  it("omits the private Edition-segment ID and accepts the resolved projection", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      contract_version: "narration-production-api/1",
      edition_id: EDITION_ID,
      profile_id: PROFILE_ID,
      progress: {
        manifest_revision: 4,
        manifest_etag: MANIFEST_ETAG,
        edition_segment_id: EDITION_SEGMENT_ID,
        segment_id: SEGMENT_ID,
        ordinal: 2,
        offset_ms: 250,
        last_legal_start_ordinal: 1,
        playback_rate_millis: 1_000,
        manifest_advanced: false,
        progress_updated_at: UPDATED_AT,
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    await putNarrationPlaybackProgress(EDITION_ID, {
      profile_id: PROFILE_ID,
      manifest_revision: 4,
      manifest_etag: MANIFEST_ETAG,
      segment_id: SEGMENT_ID,
      offset_ms: 250,
      last_legal_start_ordinal: 1,
      playback_rate_millis: 1_000,
      expected_updated_at: null,
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).not.toHaveProperty(
      "edition_segment_id",
    );
  });

  it("rejects invalid save input and mismatched response scope before use", async () => {
    await expect(putNarrationPlaybackProgress(EDITION_ID, {
      profile_id: "bad profile",
      manifest_revision: 4,
      manifest_etag: MANIFEST_ETAG,
      edition_segment_id: EDITION_SEGMENT_ID,
      segment_id: SEGMENT_ID,
      offset_ms: 0,
      last_legal_start_ordinal: 0,
      playback_rate_millis: 1_000,
      expected_updated_at: null,
    })).rejects.toBeInstanceOf(PlaybackContractError);
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      contract_version: "narration-production-api/1",
      edition_id: "10000000-0000-4000-8000-000000000099",
      profile_id: PROFILE_ID,
      progress: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(getNarrationPlaybackProgress(EDITION_ID, PROFILE_ID)).rejects.toThrow(
      /scope mismatch/,
    );
  });

  it.each([
    [409, "VERSION_CONFLICT", "MANIFEST_REVISION_CONFLICT"],
    [404, "SCOPE_VIOLATION", "SCOPE_VIOLATION"],
  ])("reuses the existing structured error parser for HTTP %i", async (
    status,
    serverCode,
    parsedCode,
  ) => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      detail: {
        contract_version: "narration-production-api/1",
        code: serverCode,
        message: "sanitized playback failure",
        retryable: false,
        field: null,
        current_version: null,
      },
    }), { status, headers: { "Content-Type": "application/json" } }));

    let thrown: unknown;
    try {
      await getNarrationPlaybackProgress(EDITION_ID, PROFILE_ID);
    } catch (error) {
      thrown = error;
    }
    expect(thrown).toBeInstanceOf(PlaybackApiError);
    expect(thrown).toMatchObject({ status, detail: { code: parsedCode } });
  });

  it("streams one Range through host.fetch without JSON parsing or URL tokens", async () => {
    const signal = new AbortController().signal;
    const response = new Response(new Uint8Array([1, 2, 3]), {
      status: 206,
      headers: {
        ETag: AUDIO_ETAG,
        "Content-Range": "bytes 0-2/10",
        "Content-Type": "audio/ogg",
        "Accept-Ranges": "bytes",
        "Content-Length": "3",
      },
    });
    const jsonSpy = vi.spyOn(response, "json");
    fetchMock.mockResolvedValue(response);

    const result = await fetchPlaybackMedia({
      url: AUDIO_URL,
      editionId: EDITION_ID,
      manifestRevision: 4,
      range: "bytes=0-2",
      ifRange: AUDIO_ETAG,
      ifNoneMatch: `"${"2".repeat(64)}"`,
      signal,
    });

    expect(result).toBe(response);
    expect(jsonSpy).not.toHaveBeenCalled();
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe(`/ai-novel-world-2026/media-assets/20000000-0000-4000-8000-000000000020/content`);
    expect(path).not.toContain("token");
    expect(init?.signal).toBe(signal);
    expect(init?.headers).not.toBeInstanceOf(Headers);
    expect(Object.getPrototypeOf(init?.headers)).toBe(Object.prototype);
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Narration-Edition-Id")).toBe(EDITION_ID);
    expect(headers.get("X-Narration-Manifest-Revision")).toBe("4");
    expect(headers.get("Range")).toBe("bytes=0-2");
    expect(headers.get("If-Range")).toBe(AUDIO_ETAG);
    expect(headers.get("If-None-Match")).toBe(`"${"2".repeat(64)}"`);
    expect(headers.get("Authorization")).toBeNull();
  });

  it("preserves 416 and HEAD while rejecting queries and multi-range requests", async () => {
    fetchMock.mockResolvedValue(new Response(null, {
      status: 416,
      headers: {
        ETag: AUDIO_ETAG,
        "Content-Range": "bytes */10",
      },
    }));
    await expect(headPlaybackMedia({
      url: AUDIO_URL,
      editionId: EDITION_ID,
      manifestRevision: 4,
      range: "bytes=999-",
    })).resolves.toHaveProperty("status", 416);
    expect(fetchMock.mock.calls[0][1]?.method).toBe("HEAD");

    await expect(fetchPlaybackMedia({
      url: `${AUDIO_URL}?token=secret`,
      editionId: EDITION_ID,
      manifestRevision: 4,
    })).rejects.toThrow(/token-free playback route/);
    await expect(fetchPlaybackMedia({
      url: AUDIO_URL,
      editionId: EDITION_ID,
      manifestRevision: 4,
      range: "bytes=0-1,4-5",
    })).rejects.toThrow(/one bytes range/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
