import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EmbeddingApiError,
  clearNovelSemanticIndex,
  putNovelEmbeddingConsent,
  saveEmbeddingCandidate,
  testEmbeddingConnection,
} from "./api";
import { NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION } from "./contracts";
import { config, consent, novelStatus, TEST_NOVEL_ID } from "./test-fixtures";


const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();


function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}


function errorResponse(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ detail: { code, message } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
});


afterEach(() => vi.unstubAllGlobals());


describe("embedding API client", () => {
  it("sends a replacement key only in the write request", async () => {
    fetchMock.mockResolvedValueOnce(response(config()));
    await saveEmbeddingCandidate({
      expected_version: 7,
      base_url: "https://dashscope.aliyuncs.com/api/v1",
      requested_model_id: "qwen3.7-text-embedding",
      requested_dimension: 1024,
      api_key_action: "replace",
      api_key: "secret-write-only",
    });

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/ai-novel-world-2026/embedding-config/candidate");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      expected_version: 7,
      api_key_action: "replace",
      api_key: "secret-write-only",
    });
  });

  it("keeps consent revocation and vector cleanup on separate endpoints", async () => {
    fetchMock.mockResolvedValueOnce(response(consent({ state: "revoked", version: 2 })));
    await putNovelEmbeddingConsent(TEST_NOVEL_ID, {
      action: "revoke",
      expected_version: 1,
      notice_version: NOVEL_EMBEDDING_CONSENT_NOTICE_VERSION,
      acknowledged_scopes: [
        "formal_manuscript",
        "formal_planning",
        "author_secrets",
        "bound_private_assets",
      ],
    });
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/ai-novel-world-2026/novels/${TEST_NOVEL_ID}/embedding-consent`,
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("PUT");

    fetchMock.mockResolvedValueOnce(response(novelStatus()));
    await clearNovelSemanticIndex(TEST_NOVEL_ID);
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/ai-novel-world-2026/novels/${TEST_NOVEL_ID}/semantic-index`,
    );
    expect(fetchMock.mock.calls[1][1]?.method).toBe("DELETE");
  });

  it("turns provider and secret-store failures into Chinese reminders", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(
      503,
      "embedding_auth_failed",
      "Embedding authentication failed",
    ));

    await expect(testEmbeddingConnection({
      base_url: "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
      requested_model_id: "qwen3.7-text-embedding",
      requested_dimension: 1024,
      api_key: "secret-write-only",
    })).rejects.toMatchObject({
      message: "API Key 验证失败，请检查后重新输入。",
    } satisfies Partial<EmbeddingApiError>);
  });
});
