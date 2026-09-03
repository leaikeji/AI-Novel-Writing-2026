import { describe, expect, it, vi } from "vitest";

import {
  createVoicePreviewPlayback,
  fetchGenericVoiceSlotObjectUrl,
  fetchVoicePreviewObjectUrl,
  type VoicePreviewPlaybackReactRuntime,
} from "./voice-preview-playback";
import {
  NARRATION_SETTINGS_API_VERSION,
  type VoicePreviewResource,
} from "./contracts";


const PREVIEW_ID = "11111111-1111-4111-8111-111111111111";
const PROFILE_ID = "22222222-2222-4222-8222-222222222222";
const VERSION_ID = "33333333-3333-4333-8333-333333333333";
const ASSET_ID = "44444444-4444-4444-8444-444444444444";
const SLOT_ID = "55555555-5555-4555-8555-555555555555";


function preview(path = `/media-assets/${ASSET_ID}/content`): VoicePreviewResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    preview_id: PREVIEW_ID,
    profile_id: PROFILE_ID,
    version_id: VERSION_ID,
    status: "ready",
    job_id: null,
    asset: {
      asset_id: ASSET_ID,
      content_path: path,
      mime_type: "audio/wav",
      byte_size: 4,
      duration_ms: 900,
      checksum_sha256: "a".repeat(64),
    },
    temporary: true,
    expires_at: "2026-08-27T10:00:00Z",
    failure_code: null,
  };
}


describe("voice preview controlled playback", () => {
  it("loads a persisted generic slot preview with only the slot authorization header", async () => {
    const host = {
      fetch: vi.fn(async () => new Response(
        new Blob(["WAVE"], { type: "audio/wav" }),
        { status: 200, headers: { "Content-Type": "audio/wav", "Content-Length": "4" } },
      )),
    };
    const objectUrls = {
      createObjectURL: vi.fn(() => "blob:generic-slot"),
      revokeObjectURL: vi.fn(),
    };
    const asset = preview().asset!;

    await expect(fetchGenericVoiceSlotObjectUrl(SLOT_ID, asset, { host, objectUrls }))
      .resolves.toBe("blob:generic-slot");
    expect(host.fetch).toHaveBeenCalledWith(
      `/ai-novel-world-2026/media-assets/${ASSET_ID}/content`,
      expect.objectContaining({
        method: "GET",
        headers: {
          Accept: "audio/wav",
          "X-Narration-Generic-Voice-Slot-Id": SLOT_ID,
        },
      }),
    );
  });

  it("uses the frozen media path and preview header without query or token", async () => {
    const host = {
      fetch: vi.fn(async (_input: string, _init?: RequestInit) => new Response(
        new Blob(["WAVE"], { type: "audio/wav" }),
        {
          status: 200,
          headers: { "Content-Type": "audio/wav", "Content-Length": "4" },
        },
      )),
    };
    const objectUrls = {
      createObjectURL: vi.fn(() => "blob:voice-preview"),
      revokeObjectURL: vi.fn(),
    };

    await expect(fetchVoicePreviewObjectUrl(preview(), { host, objectUrls }))
      .resolves.toBe("blob:voice-preview");
    expect(host.fetch).toHaveBeenCalledWith(
      `/ai-novel-world-2026/media-assets/${ASSET_ID}/content`,
      expect.objectContaining({
        method: "GET",
        headers: {
          Accept: "audio/wav",
          "X-Narration-Voice-Preview-Id": PREVIEW_ID,
        },
      }),
    );
    const requested = vi.mocked(host.fetch).mock.calls[0][0];
    expect(requested).not.toContain("?");
    expect(requested).not.toContain("token");
    expect(objectUrls.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("rejects path drift before calling the host", async () => {
    const host = { fetch: vi.fn() };
    await expect(fetchVoicePreviewObjectUrl(
      preview(`/media-assets/${ASSET_ID}/content?token=private`),
      { host },
    )).rejects.toThrow("路径未通过范围校验");
    expect(host.fetch).not.toHaveBeenCalled();
  });

  it("revokes the generated Object URL when the playback component unmounts", async () => {
    const states: unknown[] = [];
    const refs: Array<{ current: unknown }> = [];
    const effects: Array<() => void | (() => void)> = [];
    let stateIndex = 0;
    let refIndex = 0;
    const React: VoicePreviewPlaybackReactRuntime = {
      createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }),
      useState<T>(initial: T | (() => T)) {
        const index = stateIndex++;
        if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
        return [states[index] as T, (next: T | ((current: T) => T)) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        }];
      },
      useRef<T>(initial: T) {
        const index = refIndex++;
        if (!refs[index]) refs[index] = { current: initial };
        return refs[index] as { current: T };
      },
      useEffect(effect) { effects.push(effect); },
    };
    const objectUrls = {
      createObjectURL: vi.fn(() => "blob:recyclable"),
      revokeObjectURL: vi.fn(),
    };
    const Playback = createVoicePreviewPlayback(React, {
      host: {
        fetch: async () => ({
          ok: true,
          status: 200,
          headers: new Headers({ "Content-Type": "audio/wav", "Content-Length": "4" }),
          blob: async () => new Blob(["WAVE"], { type: "audio/wav" }),
        } as Response),
      },
      objectUrls,
    });

    Playback({ preview: preview() });
    const cleanup = effects[0]();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(objectUrls.createObjectURL).toHaveBeenCalledTimes(1);
    expect(typeof cleanup).toBe("function");
    cleanup?.();
    expect(objectUrls.revokeObjectURL).toHaveBeenCalledWith("blob:recyclable");
  });

  it("rejects missing or mismatched response identity before creating an Object URL", async () => {
    const objectUrls = {
      createObjectURL: vi.fn(() => "blob:must-not-exist"),
      revokeObjectURL: vi.fn(),
    };
    const host = {
      fetch: vi.fn(async () => new Response(
        new Blob(["WAVE"], { type: "audio/wav" }),
        { status: 200, headers: { "Content-Type": "audio/wav" } },
      )),
    };

    await expect(fetchVoicePreviewObjectUrl(preview(), { host, objectUrls }))
      .rejects.toThrow("长度头");
    expect(objectUrls.createObjectURL).not.toHaveBeenCalled();
  });
});
