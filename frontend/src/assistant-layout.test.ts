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

  it("uses the studio width policy for the creative center", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 1_500,
      preferredAssistantWidth: 480,
      pageKind: "creative-center",
    })).toMatchObject({
      assistantWidth: 480,
      mainWidth: 1_020,
      mainMinWidth: 720,
      assistantOverlay: false,
    });
  });

  it("clamps a persisted wide assistant before stealing the chapter editor and tree width", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 1_280,
      preferredAssistantWidth: 520,
      pageKind: "chapter-editor",
    })).toMatchObject({
      assistantWidth: 400,
      mainWidth: 880,
      density: "constrained",
      assistantOverlay: false,
    });
  });

  it("moves the assistant to an overlay when its minimum cannot coexist with the chapter tree", () => {
    expect(resolveAssistantWorkspaceLayout({
      containerWidth: 1_180,
      preferredAssistantWidth: 520,
      pageKind: "chapter-editor",
    })).toMatchObject({
      assistantWidth: 520,
      mainWidth: 1_180,
      mainMinWidth: 640,
      density: "constrained",
      assistantOverlay: true,
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
