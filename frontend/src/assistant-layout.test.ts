import { describe, expect, it } from "vitest";

import { resolveAssistantWorkspaceLayout } from "./assistant-layout";


describe("resolveAssistantWorkspaceLayout", () => {
  it("keeps a 380px inline assistant and a comfortable studio on a 2K work area", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 2_320,
      preferredAssistantWidth: 380,
      pageKind: "studio",
    })).toMatchObject({
      assistantWidth: 380,
      mainWidth: 1_940,
      density: "comfortable",
      assistantOverlay: false,
      recommendedNavigationWidth: 286,
    });
  });

  it("clamps the assistant before stealing the chapter editor minimum width", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 1_180,
      preferredAssistantWidth: 520,
      pageKind: "chapter-editor",
    })).toMatchObject({
      assistantWidth: 420,
      mainWidth: 760,
      density: "constrained",
      assistantOverlay: false,
    });
  });

  it("uses an overlay only when the verified 320px minimum cannot coexist", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 1_040,
      pageKind: "chapter-editor",
    })).toMatchObject({
      assistantOverlay: true,
      mainWidth: 1_040,
      mainMinWidth: 640,
      density: "constrained",
    });
  });

  it("returns the center width after a persistent collapse", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 1_500,
      assistantCollapsed: true,
      pageKind: "studio",
    })).toMatchObject({
      assistantWidth: 52,
      mainWidth: 1_448,
      assistantOverlay: false,
    });
  });
});
