import { describe, expect, it } from "vitest";

import {
  actualGenerationModelLabel,
  completedGenerationModelLabel,
  generationModelAuditLabel,
  requestedGenerationModelLabel,
} from "./api";

const task = (patch: Record<string, unknown> = {}) => ({
  requested_provider_id: "provider-a",
  requested_model_id: "model-a",
  actual_provider_id: "provider-a",
  actual_model_id: "model-a",
  provider_profile: null,
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
});
