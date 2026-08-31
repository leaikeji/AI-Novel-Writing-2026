import { describe, expect, it } from "vitest";

import type { NanoVoiceExperimentResource } from "./contracts";
import { selectNanoExperimentForTarget } from "./voice-feature-workspaces";


const ADVANCED_VERSION_ID = "10000000-0000-4000-8000-000000000001";
const OFFICIAL_VERSION_ID = "10000000-0000-4000-8000-000000000002";


function experiment(
  state: NanoVoiceExperimentResource["state"],
  versionId = ADVANCED_VERSION_ID,
): NanoVoiceExperimentResource {
  return {
    base_preset_id: "onnx.Zhiming",
    target_kind: "narrator",
    character_id: null,
    state,
    version_id: versionId,
  } as NanoVoiceExperimentResource;
}


describe("Nano advanced workspace history selection", () => {
  it("shows the latest applied experiment only while that Version remains bound", () => {
    const latest = experiment("ready_applied");
    const older = experiment("ready_unapplied", OFFICIAL_VERSION_ID);
    expect(selectNanoExperimentForTarget([latest, older], {
      basePresetId: "onnx.Zhiming",
      targetKind: "narrator",
      characterId: null,
      currentVoiceVersionId: ADVANCED_VERSION_ID,
    })).toBe(latest);

    expect(selectNanoExperimentForTarget([latest, older], {
      basePresetId: "onnx.Zhiming",
      targetKind: "narrator",
      characterId: null,
      currentVoiceVersionId: OFFICIAL_VERSION_ID,
    })).toBeNull();
  });

  it("keeps a current running or unapplied result visible before binding", () => {
    for (const state of ["running", "ready_unapplied"] as const) {
      const current = experiment(state);
      expect(selectNanoExperimentForTarget([current], {
        basePresetId: "onnx.Zhiming",
        targetKind: "narrator",
        characterId: null,
        currentVoiceVersionId: OFFICIAL_VERSION_ID,
      })).toBe(current);
    }
  });
});
