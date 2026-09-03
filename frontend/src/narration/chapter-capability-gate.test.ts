import { describe, expect, it } from "vitest";

import {
  CAPABILITY_KEYS,
  type CapabilityKey,
  type FeatureCapability,
  type NarrationCapabilities,
} from "./contracts";
import {
  deriveChapterNarrationCapabilityGate,
  loadChapterNarrationCapabilityGate,
  retainEquivalentChapterNarrationCapabilityGate,
  type ChapterNarrationCapabilityGate,
} from "./chapter-capability-gate";


function capabilities(
  enabled: readonly CapabilityKey[],
  visibleHeld: readonly CapabilityKey[] = [],
): NarrationCapabilities {
  const enabledKeys = new Set(enabled);
  const visibleHeldKeys = new Set(visibleHeld);
  return Object.freeze({
    schema_version: "narration-capabilities/4",
    items: Object.freeze(CAPABILITY_KEYS.map((key): FeatureCapability => {
      if (enabledKeys.has(key)) {
        return Object.freeze({
          key,
          state: "enabled",
          visible: true,
          actionable: true,
          reason_code: null,
          required_gate: null,
        });
      }
      return Object.freeze({
        key,
        state: "hold",
        visible: visibleHeldKeys.has(key),
        actionable: false,
        reason_code: `${key.toUpperCase()}_GATE_REQUIRED`,
        required_gate: "T4-GATE",
      });
    })),
  });
}


describe("chapter narration capability gate", () => {
  it("treats fresh gates with the same effective release meaning as equivalent", () => {
    const enabled = [
      "narration_product",
      "product_player",
      "editor_production",
      "narration_synthesis",
      "automatic_speaker_detection",
    ] as const satisfies readonly CapabilityKey[];
    const current = deriveChapterNarrationCapabilityGate(capabilities(enabled));
    const refreshed = deriveChapterNarrationCapabilityGate(capabilities([
      ...enabled,
      "reading_settings",
    ]));

    expect(refreshed).not.toBe(current);
    expect(retainEquivalentChapterNarrationCapabilityGate(current, refreshed)).toBe(current);
    expect(retainEquivalentChapterNarrationCapabilityGate(current, current)).toBe(current);
  });

  it("detects every effective gate field that must invalidate the current session state", () => {
    const current = deriveChapterNarrationCapabilityGate(capabilities([
      "narration_product",
      "product_player",
      "editor_production",
      "narration_synthesis",
      "automatic_speaker_detection",
    ]));
    const variants: readonly ChapterNarrationCapabilityGate[] = [
      { ...current, visible: false },
      { ...current, canLoadSession: false },
      { ...current, canProduce: false },
      { ...current, reasonCode: "PRODUCT_RUNTIME_UNAVAILABLE" },
      { ...current, blockedCapability: "product_player" },
    ];

    for (const variant of variants) {
      expect(retainEquivalentChapterNarrationCapabilityGate(current, variant)).toBe(variant);
      expect(retainEquivalentChapterNarrationCapabilityGate(variant, current)).toBe(current);
    }
  });

  it("keeps the chapter player hidden and unmounted under the current T2-only matrix", () => {
    const gate = deriveChapterNarrationCapabilityGate(capabilities([
      "narration_product",
      "reading_settings",
    ]));

    expect(gate).toEqual({
      visible: false,
      canLoadSession: false,
      canProduce: false,
      canPrepareVoices: false,
      reasonCode: "PRODUCT_PLAYER_GATE_REQUIRED",
      blockedCapability: "product_player",
    });
  });

  it("allows playback but not production when synthesis remains held", () => {
    const gate = deriveChapterNarrationCapabilityGate(capabilities([
      "narration_product",
      "product_player",
      "editor_production",
    ], ["narration_synthesis"]));

    expect(gate).toMatchObject({
      visible: true,
      canLoadSession: true,
      canProduce: false,
      blockedCapability: "narration_synthesis",
    });
  });

  it("requires every frozen chapter capability before enabling production", () => {
    const gate = deriveChapterNarrationCapabilityGate(capabilities([
      "narration_product",
      "product_player",
      "editor_production",
      "narration_synthesis",
      "automatic_speaker_detection",
    ]));

    expect(gate).toEqual({
      visible: true,
      canLoadSession: true,
      canProduce: true,
      canPrepareVoices: false,
      reasonCode: null,
      blockedCapability: null,
    });
  });

  it("re-reads a degraded server matrix instead of reusing a stale release", async () => {
    const released = capabilities([
      "narration_product",
      "product_player",
      "editor_production",
      "narration_synthesis",
      "automatic_speaker_detection",
    ]);
    const degraded = capabilities(["narration_product", "reading_settings"]);
    let current = released;
    const loader = async (novelId: string) => ({
      novel_id: novelId,
      capabilities: current,
    });

    expect((await loadChapterNarrationCapabilityGate("novel-a", loader)).canProduce)
      .toBe(true);
    current = degraded;
    const refreshed = await loadChapterNarrationCapabilityGate("novel-a", loader);
    expect(refreshed.canProduce).toBe(false);
    expect(refreshed.blockedCapability).toBe("product_player");
  });

  it("rejects a late overview from another novel", async () => {
    await expect(loadChapterNarrationCapabilityGate(
      "novel-a",
      async () => ({ novel_id: "novel-b", capabilities: capabilities([]) }),
    )).rejects.toThrow("其他作品范围");
  });
});
