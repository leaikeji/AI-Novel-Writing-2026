import { describe, expect, it } from "vitest";

import {
  REQUIRED_SELECTION_MIRROR_SCENARIOS,
  SELECTION_GEOMETRY_SPIKE_DECISION,
  evaluateSelectionMirrorProbes,
  resolveSelectionToolbarPlacement,
  type ResolveSelectionToolbarPlacementInput,
  type SelectionMirrorProbeSample,
} from "./assistant-selection-geometry";


function stableProbeSamples(): SelectionMirrorProbeSample[] {
  return REQUIRED_SELECTION_MIRROR_SCENARIOS.map((scenario, index) => ({
    scenario,
    expected: { x: 100 + index, y: 200 + index },
    measured: { x: 100.5 + index, y: 199.5 + index },
    stable: true,
  }));
}


function placementInput(
  overrides: Partial<ResolveSelectionToolbarPlacementInput> = {},
): ResolveSelectionToolbarPlacementInput {
  return {
    viewportRect: { left: 0, top: 0, width: 1_000, height: 800 },
    fieldRect: { left: 100, top: 100, width: 600, height: 300 },
    toolbarSize: { width: 160, height: 40 },
    environment: {
      fieldScrollLeft: 0,
      fieldScrollTop: 0,
      visualViewportScale: 1,
      devicePixelRatio: 1,
      hasLongVisualLine: false,
      selectionWraps: false,
      isComposing: false,
    },
    mirror: {
      rect: { left: 300, top: 220, width: 120, height: 24 },
      styleParityVerified: true,
    },
    mirrorDecision: evaluateSelectionMirrorProbes(stableProbeSamples()),
    ...overrides,
  };
}


describe("selection mirror probe decision", () => {
  it("adopts mirror positioning only when every required scenario is stable", () => {
    const decision = evaluateSelectionMirrorProbes(stableProbeSamples());

    expect(decision).toEqual({
      strategy: "selection-mirror",
      missingScenarios: [],
      unstableScenarios: [],
      maxObservedErrorCssPx: 0.5,
    });
  });

  it("falls back when any scenario is missing, inaccurate or temporally unstable", () => {
    const missingIme = stableProbeSamples().filter(({ scenario }) => scenario !== "ime");
    const inaccurateZoom = stableProbeSamples().map((sample) => (
      sample.scenario === "zoom"
        ? { ...sample, measured: { x: sample.expected.x + 3, y: sample.expected.y } }
        : sample
    ));
    const flickeringWrap = stableProbeSamples().map((sample) => (
      sample.scenario === "wrapping" ? { ...sample, stable: false } : sample
    ));

    expect(evaluateSelectionMirrorProbes(missingIme)).toMatchObject({
      strategy: "field-anchor",
      missingScenarios: ["ime"],
    });
    expect(evaluateSelectionMirrorProbes(inaccurateZoom)).toMatchObject({
      strategy: "field-anchor",
      unstableScenarios: ["zoom"],
      maxObservedErrorCssPx: 3,
    });
    expect(evaluateSelectionMirrorProbes(flickeringWrap)).toMatchObject({
      strategy: "field-anchor",
      unstableScenarios: ["wrapping"],
    });
  });

  it("records the A0C-4 spike default as field anchoring without fake precision", () => {
    expect(SELECTION_GEOMETRY_SPIKE_DECISION.strategy).toBe("field-anchor");
    expect(SELECTION_GEOMETRY_SPIKE_DECISION.missingScenarios).toEqual(
      REQUIRED_SELECTION_MIRROR_SCENARIOS,
    );
  });
});


describe("resolveSelectionToolbarPlacement", () => {
  it("places a verified baseline mirror measurement by the selection", () => {
    const result = resolveSelectionToolbarPlacement(placementInput());

    expect(result).toEqual({
      strategy: "selection-mirror",
      precision: "verified-selection",
      x: 280,
      y: 172,
      placement: "selection-above",
      fallbackReasons: [],
    });
  });

  it("uses the field edge under the actual spike decision", () => {
    const result = resolveSelectionToolbarPlacement(placementInput({
      mirrorDecision: SELECTION_GEOMETRY_SPIKE_DECISION,
    }));

    expect(result).toEqual({
      strategy: "field-anchor",
      precision: "field-level",
      x: 540,
      y: 408,
      placement: "field-below",
      fallbackReasons: ["mirror-not-adopted"],
    });
  });

  it.each([
    {
      name: "scrolled textarea",
      environment: { fieldScrollTop: 120 },
      reason: "field-scroll-uncompensated",
    },
    {
      name: "browser zoom",
      environment: { visualViewportScale: 1.25 },
      reason: "zoom-uncompensated",
    },
    {
      name: "high DPI",
      environment: { devicePixelRatio: 2 },
      reason: "high-dpi-unverified",
    },
    {
      name: "long visual line",
      environment: { hasLongVisualLine: true },
      reason: "long-line-unverified",
    },
    {
      name: "wrapped selection",
      environment: { selectionWraps: true },
      reason: "wrapping-unverified",
    },
    {
      name: "active IME composition",
      environment: { isComposing: true },
      reason: "ime-composition-active",
    },
  ])("does not pretend mirror precision for $name", ({ environment, reason }) => {
    const base = placementInput();
    const result = resolveSelectionToolbarPlacement(placementInput({
      environment: { ...base.environment, ...environment },
    }));

    expect(result.strategy).toBe("field-anchor");
    expect(result.precision).toBe("field-level");
    expect(result.fallbackReasons).toContain(reason);
  });

  it("permits compensated scroll/zoom/high-DPI/long-line/wrapping after probes pass", () => {
    const base = placementInput();
    const result = resolveSelectionToolbarPlacement(placementInput({
      environment: {
        ...base.environment,
        fieldScrollLeft: 30,
        fieldScrollTop: 400,
        visualViewportScale: 1.5,
        devicePixelRatio: 2,
        hasLongVisualLine: true,
        selectionWraps: true,
      },
      mirror: {
        ...base.mirror!,
        scrollCompensated: true,
        zoomCoordinatesNormalized: true,
        highDpiCoordinatesNormalized: true,
        longLineMeasured: true,
        wrappedSelectionMeasured: true,
      },
    }));

    expect(result.strategy).toBe("selection-mirror");
    expect(result.fallbackReasons).toEqual([]);
  });

  it("still falls back when the mirror rect is invalid or outside the field", () => {
    const base = placementInput();
    const invalid = resolveSelectionToolbarPlacement(placementInput({
      mirror: { ...base.mirror!, rect: { left: 0, top: 0, width: 0, height: 0 } },
    }));
    const outside = resolveSelectionToolbarPlacement(placementInput({
      mirror: {
        ...base.mirror!,
        rect: { left: 800, top: 650, width: 40, height: 20 },
      },
    }));

    expect(invalid.fallbackReasons).toEqual(["mirror-rect-invalid"]);
    expect(outside.fallbackReasons).toEqual([
      "selection-outside-field",
    ]);
    expect(invalid.strategy).toBe("field-anchor");
    expect(outside.strategy).toBe("field-anchor");
  });

  it("clamps field anchoring to the visual viewport", () => {
    const result = resolveSelectionToolbarPlacement(placementInput({
      fieldRect: { left: 860, top: 730, width: 300, height: 200 },
      mirrorDecision: SELECTION_GEOMETRY_SPIKE_DECISION,
    }));

    expect(result.strategy).toBe("field-anchor");
    expect(result.placement).toBe("field-above");
    expect(result.x).toBe(832);
    expect(result.y).toBe(682);
  });
});
