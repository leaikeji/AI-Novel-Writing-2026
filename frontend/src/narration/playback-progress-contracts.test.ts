import { describe, expect, it } from "vitest";

import {
  parsePlaybackProfileId,
  parsePlaybackProgressResponse,
  parseSavePlaybackProgressRequest,
} from "./playback-progress-contracts";
import { PlaybackContractError } from "./playback-contracts";


const EDITION_ID = "a7100000-0000-4000-8000-000000000001";
const EDITION_SEGMENT_ID = "a7100000-0000-4000-8000-000000000002";
const SEGMENT_ID = "a7100000-0000-4000-8000-000000000003";
const PROFILE_ID = "desktop.default";
const ETAG = `"${"a".repeat(64)}"`;
const UPDATED_AT = "2026-08-27T09:30:00.123456+00:00";


function requestFixture(changes: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    profile_id: PROFILE_ID,
    manifest_revision: 4,
    manifest_etag: ETAG,
    edition_segment_id: EDITION_SEGMENT_ID,
    segment_id: SEGMENT_ID,
    offset_ms: 450,
    last_legal_start_ordinal: 1,
    playback_rate_millis: 1_250,
    expected_updated_at: UPDATED_AT,
    ...changes,
  };
}


function responseFixture(
  progress: Record<string, unknown> | null = projectionFixture(),
  changes: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    contract_version: "narration-production-api/1",
    edition_id: EDITION_ID,
    profile_id: PROFILE_ID,
    progress,
    ...changes,
  };
}


function projectionFixture(changes: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    manifest_revision: 5,
    manifest_etag: ETAG,
    edition_segment_id: EDITION_SEGMENT_ID,
    segment_id: SEGMENT_ID,
    ordinal: 2,
    offset_ms: 450,
    last_legal_start_ordinal: 1,
    playback_rate_millis: 1_250,
    manifest_advanced: true,
    progress_updated_at: UPDATED_AT,
    ...changes,
  };
}


describe("playback progress wire contracts", () => {
  it("accepts and freezes first-write and CAS save bodies", () => {
    const first = parseSavePlaybackProgressRequest(requestFixture({
      expected_updated_at: null,
    }));
    const next = parseSavePlaybackProgressRequest(requestFixture());

    expect(first.expected_updated_at).toBeNull();
    expect(next.expected_updated_at).toBe(UPDATED_AT);
    expect(Object.isFrozen(first)).toBe(true);
    expect(Object.isFrozen(next)).toBe(true);
  });

  it("allows the private Edition-segment identity to be omitted for server resolution", () => {
    const request = requestFixture();
    delete request.edition_segment_id;

    const parsed = parseSavePlaybackProgressRequest(request);

    expect(parsed.edition_segment_id).toBeUndefined();
    expect(Object.prototype.hasOwnProperty.call(parsed, "edition_segment_id")).toBe(false);
  });

  it("parses both explicit null and an exact recoverable projection", () => {
    const missing = parsePlaybackProgressResponse(responseFixture(null));
    const restored = parsePlaybackProgressResponse(responseFixture());

    expect(missing.progress).toBeNull();
    expect(restored.progress).toMatchObject({
      manifest_revision: 5,
      edition_segment_id: EDITION_SEGMENT_ID,
      segment_id: SEGMENT_ID,
      manifest_advanced: true,
      progress_updated_at: UPDATED_AT,
    });
    expect(Object.isFrozen(restored)).toBe(true);
    expect(Object.isFrozen(restored.progress)).toBe(true);
  });

  it.each([
    ["extra request field", requestFixture({ extra: true })],
    ["weak manifest ETag", requestFixture({ manifest_etag: `W/${ETAG}` })],
    ["boolean revision", requestFixture({ manifest_revision: true })],
    ["negative offset", requestFixture({ offset_ms: -1 })],
    ["out-of-range rate", requestFixture({ playback_rate_millis: 4_001 })],
    ["naive CAS", requestFixture({ expected_updated_at: "2026-08-27T09:30:00" })],
    ["impossible CAS date", requestFixture({ expected_updated_at: "2026-02-30T09:30:00Z" })],
  ])("rejects %s before transport", (_label, value) => {
    expect(() => parseSavePlaybackProgressRequest(value)).toThrow(PlaybackContractError);
  });

  it.each([
    ["extra envelope field", responseFixture(null, { extra: true })],
    ["unsupported version", responseFixture(null, { contract_version: "narration-production-api/2" })],
    ["weak projection ETag", responseFixture(projectionFixture({ manifest_etag: `W/${ETAG}` }))],
    ["invalid Edition segment UUID", responseFixture(projectionFixture({ edition_segment_id: "bad" }))],
    ["unsafe revision", responseFixture(projectionFixture({ manifest_revision: Number.MAX_SAFE_INTEGER + 1 }))],
    ["negative projection offset", responseFixture(projectionFixture({ offset_ms: -1 }))],
    ["legal start after position", responseFixture(projectionFixture({ ordinal: 1, last_legal_start_ordinal: 2 }))],
    ["non-boolean advanced marker", responseFixture(projectionFixture({ manifest_advanced: 1 }))],
    ["naive updated_at", responseFixture(projectionFixture({ progress_updated_at: "2026-08-27T09:30:00" }))],
  ])("rejects %s", (_label, value) => {
    expect(() => parsePlaybackProgressResponse(value)).toThrow(PlaybackContractError);
  });

  it("accepts only the frozen profile identity alphabet and bound", () => {
    expect(parsePlaybackProfileId("desktop:writer-1.default")).toBe("desktop:writer-1.default");
    expect(() => parsePlaybackProfileId("bad profile")).toThrow(PlaybackContractError);
    expect(() => parsePlaybackProfileId(`a${"b".repeat(160)}`)).toThrow(PlaybackContractError);
  });
});
