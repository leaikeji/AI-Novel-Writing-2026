import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateTtsCloudProfile,
  createTtsCloudProfile,
  testTtsCloudProfile,
  TtsCloudProfileApiError,
  updateTtsCloudProfile,
} from "./api";
import { TTS_CLOUD_PROTOCOL } from "./contracts";
import { cloudProfiles, cloudTestResponse } from "./test-fixtures";


const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();


function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}


function errorResponse(status: number, code: string): Response {
  return new Response(JSON.stringify({ detail: { code, message: "private provider detail" } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
});


afterEach(() => vi.unstubAllGlobals());


describe("TTS cloud profile API client", () => {
  it("sends a write-only key only in create and update requests", async () => {
    fetchMock.mockImplementation(async () => response(cloudProfiles()));
    await createTtsCloudProfile({
      expected_version: 0,
      idempotency_key: "tts-cloud-create-1",
      name: "渠道 A",
      protocol: TTS_CLOUD_PROTOCOL,
      base_url: "https://voice.example.com/qwen",
      quality_model_id: "quality-model",
      speed_model_id: null,
      api_key: "secret-write-only",
    });
    await updateTtsCloudProfile("profile/a", {
      expected_version: 3,
      idempotency_key: "tts-cloud-update-1",
      name: "渠道 A",
      protocol: TTS_CLOUD_PROTOCOL,
      base_url: "https://voice.example.com/qwen",
      quality_model_id: "quality-model",
      speed_model_id: "speed-model",
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/ai-novel-world-2026/tts-cloud-profiles");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      api_key: "secret-write-only",
      expected_version: 0,
    });
    expect(fetchMock.mock.calls[1][0]).toBe("/ai-novel-world-2026/tts-cloud-profiles/profile%2Fa");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("PATCH");
    expect(String(fetchMock.mock.calls[1][1]?.body)).not.toContain("secret-write-only");
  });

  it("sends explicit billing confirmation and a slot for model tests", async () => {
    fetchMock.mockResolvedValueOnce(response(cloudTestResponse()));
    await testTtsCloudProfile("profile-1", {
      expected_version: 3,
      slot: "quality",
      billing_confirmed: true,
      idempotency_key: "tts-cloud-test-1",
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/ai-novel-world-2026/tts-cloud-profiles/profile-1/test",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      slot: "quality",
      billing_confirmed: true,
      expected_version: 3,
    });
  });

  it("keeps activation explicit and sanitizes provider errors", async () => {
    fetchMock.mockResolvedValueOnce(response(cloudProfiles()));
    await activateTtsCloudProfile("profile-1", {
      expected_version: 3,
      idempotency_key: "tts-cloud-mutate-1",
    });
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/ai-novel-world-2026/tts-cloud-profiles/profile-1/activate",
    );

    fetchMock.mockResolvedValueOnce(errorResponse(401, "TTS_CLOUD_PROVIDER_AUTH_FAILED"));
    await expect(testTtsCloudProfile("profile-1", {
      expected_version: 3,
      slot: "quality",
      billing_confirmed: true,
      idempotency_key: "tts-cloud-test-2",
    })).rejects.toMatchObject({
      message: "API Key 验证失败，请检查渠道凭据。",
    } satisfies Partial<TtsCloudProfileApiError>);
  });
});
