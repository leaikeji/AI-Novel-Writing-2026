import { describe, expect, it } from "vitest";

import {
  ApiError,
  actualGenerationModelLabel,
  apiErrorMessage,
  completedGenerationModelLabel,
  generationModelAuditLabel,
  requestedGenerationModelLabel,
  verifiedGenerationModelLabel,
} from "./api";

const task = (patch: Record<string, unknown> = {}) => ({
  requested_provider_id: "provider-a",
  requested_model_id: "model-a",
  actual_provider_id: "provider-a",
  actual_model_id: "model-a",
  provider_profile: null,
  model_evidence: null,
  ...patch,
}) as any;

describe("generation model presentation", () => {
  it("uses actual task evidence for a completed result", () => {
    const record = task({ actual_provider_id: "provider-b", actual_model_id: "model-b" });
    expect(completedGenerationModelLabel(record)).toBe("provider-b / model-b");
    expect(generationModelAuditLabel(record)).toBe("请求 provider-a / model-a · 实际 provider-b / model-b");
  });

  it("falls back to requested evidence when actual evidence is absent", () => {
    const record = task({ actual_provider_id: null, actual_model_id: null });
    expect(actualGenerationModelLabel(record)).toBeNull();
    expect(completedGenerationModelLabel(record)).toBe("provider-a / model-a");
    expect(generationModelAuditLabel(record)).toContain("实际未核验");
    expect(verifiedGenerationModelLabel(record)).toBe("请求 provider-a / model-a · 实际未核验");
  });

  it("describes not-exposed public evidence without claiming actual verification", () => {
    const record = task({
      actual_provider_id: null,
      actual_model_id: null,
      model_evidence: {
        schema_version: "model-execution-evidence/2",
        status: "not_exposed",
      },
    });
    expect(verifiedGenerationModelLabel(record)).toBe(
      "宿主未公开实际模型；任务前后有效模型一致（provider-a / model-a）",
    );
  });

  it("keeps a historical model label independent of the current effective model", () => {
    const historical = task({
      requested_provider_id: "minimax-cn",
      requested_model_id: "MiniMax-M3",
      actual_provider_id: "minimax-cn",
      actual_model_id: "MiniMax-M3",
    });
    expect(completedGenerationModelLabel(historical)).toBe("minimax-cn / MiniMax-M3");
  });

  it("supports legacy records whose requested provider was not recorded", () => {
    const historical = task({
      requested_provider_id: null,
      requested_model_id: "legacy-model",
      actual_provider_id: null,
      actual_model_id: null,
      provider_profile: "legacy-provider",
    });
    expect(requestedGenerationModelLabel(historical)).toBe("legacy-model");
    expect(completedGenerationModelLabel(historical)).toBe("legacy-model");
  });

  it("keeps structured API failure details and task model evidence", () => {
    const reason = new ApiError(502, "HTTP 502", {
      type: "model_verification_failed",
      job: task({
        actual_provider_id: "provider-b",
        actual_model_id: "model-b",
        failure_message: "回复模型与任务启动模型不一致",
      }),
    });
    expect(apiErrorMessage(reason, "生成失败")).toBe(
      "回复模型与任务启动模型不一致（请求 provider-a / model-a · 实际 provider-b / model-b）",
    );
  });

  it("shows a public model-status message instead of a bare HTTP status", () => {
    const reason = new ApiError(503, "HTTP 503", {
      type: "generation_model_unavailable",
      message: "AI 小说作家当前没有可用的有效模型",
    });
    expect(apiErrorMessage(reason, "读取失败")).toBe("AI 小说作家当前没有可用的有效模型");
  });
});
