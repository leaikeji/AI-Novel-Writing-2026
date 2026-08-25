import { describe, expect, it } from "vitest";

import {
  ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE,
  assistantToolRailIndexFromKey,
  assistantToolRailRovingIndexFromKey,
  resolveAssistantToolRailGeometry,
  resolveAssistantToolRailRovingFocus,
  type AssistantToolRailItem,
} from "./assistant-tool-rail";


const TOOL_ITEMS: readonly AssistantToolRailItem[] = [
  { id: "review", ariaLabel: "AI 审稿" },
  { id: "intelligence", ariaLabel: "查看章节情报", disabled: true },
  { id: "previous", ariaLabel: "上一章" },
  { id: "next", ariaLabel: "下一章", disabled: true },
];


describe("resolveAssistantToolRailGeometry", () => {
  it("keeps the vertical rail inside the editor and left of the assistant", () => {
    const layout = resolveAssistantToolRailGeometry({
      viewportWidth: 1920,
      hostNavigationWidth: 200,
      chapterTreeWidth: 270,
      assistantPaneWidth: 380,
    });

    expect(layout.mode).toBe("edge");
    expect(layout.orientation).toBe("vertical");
    expect(layout.railRight).toBeLessThanOrEqual(layout.assistantLeft);
    expect(layout.railLeft).toBeGreaterThanOrEqual(layout.editorLeft);
    expect(layout.rootProps).toMatchObject({
      role: "toolbar",
      "aria-label": "章节工具",
      "aria-orientation": "vertical",
      "data-assistant-tool-rail-mode": "edge",
      "data-assistant-tool-rail-orientation": "vertical",
      "data-assistant-tool-rail-overflow": "none",
    });
    expect(layout.rootProps.className).toContain("anw-editor-side-tools");
    expect(layout.rootProps.className).toContain("is-edge");
    expect(layout.rootProps.style).not.toHaveProperty("position");
    expect(layout.rootProps.style).not.toHaveProperty("right");
  });

  it("moves the rail to a horizontal footer instead of overlapping", () => {
    const layout = resolveAssistantToolRailGeometry({
      viewportWidth: 1280,
      hostNavigationWidth: 200,
      chapterTreeWidth: 270,
      assistantPaneWidth: 400,
    });

    expect(layout.mode).toBe("footer");
    expect(layout.orientation).toBe("horizontal");
    expect(layout.railRight).toBeLessThanOrEqual(layout.assistantLeft);
    expect(layout.railWidth).toBeGreaterThan(0);
    expect(layout.rootProps["aria-orientation"]).toBe("horizontal");
    expect(layout.rootProps["data-assistant-tool-rail-mode"]).toBe("footer");
  });

  it("never produces negative or assistant-overlapping geometry", () => {
    const layout = resolveAssistantToolRailGeometry({
      viewportWidth: 720,
      hostNavigationWidth: 240,
      chapterTreeWidth: 270,
      assistantPaneWidth: 380,
    });

    expect(layout.railWidth).toBeGreaterThanOrEqual(0);
    expect(layout.railLeft).toBeGreaterThanOrEqual(layout.editorLeft);
    expect(layout.railRight).toBeLessThanOrEqual(layout.assistantLeft);
  });

  it("uses a horizontal footer when the vertical hit targets do not fit", () => {
    const layout = resolveAssistantToolRailGeometry({
      viewportWidth: 1920,
      viewportHeight: 180,
      hostNavigationWidth: 200,
      chapterTreeWidth: 54,
      assistantPaneWidth: 320,
      itemCount: 4,
    });

    expect(layout.mode).toBe("footer");
    expect(layout.orientation).toBe("horizontal");
    expect(layout.railHeight).toBeGreaterThanOrEqual(
      ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE,
    );
    expect(layout.railRight).toBeLessThanOrEqual(layout.assistantLeft);
  });

  it("marks a too-narrow footer as scrollable without shrinking hit targets", () => {
    const layout = resolveAssistantToolRailGeometry({
      viewportWidth: 760,
      viewportHeight: 540,
      hostNavigationWidth: 200,
      chapterTreeWidth: 270,
      assistantPaneWidth: 320,
      itemCount: 4,
      buttonHitSize: 24,
    });

    expect(layout.mode).toBe("footer");
    expect(layout.overflow).toBe("scroll");
    expect(layout.buttonHitSize).toBe(ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE);
    expect(layout.rootProps.className).toContain("has-scroll-overflow");
    expect(layout.rootProps["data-assistant-tool-rail-min-hit-size"]).toBe("40");
    expect(layout.railRight).toBeLessThanOrEqual(layout.assistantLeft);
  });
});


describe("assistantToolRailIndexFromKey", () => {
  it("supports roving focus in vertical and horizontal modes", () => {
    expect(assistantToolRailIndexFromKey(0, 4, "ArrowUp", "vertical")).toBe(3);
    expect(assistantToolRailIndexFromKey(3, 4, "ArrowDown", "vertical")).toBe(0);
    expect(assistantToolRailIndexFromKey(0, 4, "ArrowLeft", "horizontal")).toBe(3);
    expect(assistantToolRailIndexFromKey(3, 4, "ArrowRight", "horizontal")).toBe(0);
    expect(assistantToolRailIndexFromKey(2, 4, "Home", "vertical")).toBe(0);
    expect(assistantToolRailIndexFromKey(1, 4, "End", "horizontal")).toBe(3);
  });

  it("ignores unrelated keys and empty rails", () => {
    expect(assistantToolRailIndexFromKey(0, 4, "Enter", "vertical")).toBeNull();
    expect(assistantToolRailIndexFromKey(0, 0, "ArrowDown", "vertical")).toBeNull();
  });
});


describe("assistant tool rail page props and roving focus", () => {
  it("returns one tab stop and direct button props with at least a 40px hit area", () => {
    const focus = resolveAssistantToolRailRovingFocus(TOOL_ITEMS, 1, 24);

    expect(focus.activeIndex).toBe(2);
    expect(focus.activeItemId).toBe("previous");
    expect(focus.itemProps.map(({ tabIndex }) => tabIndex)).toEqual([-1, -1, 0, -1]);
    expect(focus.itemProps[0]).toMatchObject({
      type: "button",
      "aria-label": "AI 审稿",
      "data-assistant-tool-rail-item": "review",
      "data-assistant-tool-rail-hit-size": "40",
      style: { minWidth: "40px", minHeight: "40px" },
    });
    expect(focus.itemProps[1]).toMatchObject({
      disabled: true,
      "aria-disabled": true,
      tabIndex: -1,
    });
    expect(focus.itemProps[2].className).toContain("is-roving-active");
  });

  it("skips disabled actions and wraps in both orientations", () => {
    expect(assistantToolRailRovingIndexFromKey(
      0,
      TOOL_ITEMS,
      "ArrowDown",
      "vertical",
    )).toBe(2);
    expect(assistantToolRailRovingIndexFromKey(
      2,
      TOOL_ITEMS,
      "ArrowDown",
      "vertical",
    )).toBe(0);
    expect(assistantToolRailRovingIndexFromKey(
      0,
      TOOL_ITEMS,
      "ArrowLeft",
      "horizontal",
    )).toBe(2);
    expect(assistantToolRailRovingIndexFromKey(
      2,
      TOOL_ITEMS,
      "ArrowRight",
      "horizontal",
    )).toBe(0);
    expect(assistantToolRailRovingIndexFromKey(
      2,
      TOOL_ITEMS,
      "Home",
      "horizontal",
    )).toBe(0);
    expect(assistantToolRailRovingIndexFromKey(
      0,
      TOOL_ITEMS,
      "End",
      "vertical",
    )).toBe(2);
  });

  it("leaves an all-disabled toolbar out of the Tab order", () => {
    const focus = resolveAssistantToolRailRovingFocus([
      { id: "previous", ariaLabel: "已经是第一章", disabled: true },
      { id: "next", ariaLabel: "已经是最后一章", disabled: true },
    ]);

    expect(focus.activeIndex).toBe(-1);
    expect(focus.activeItemId).toBeUndefined();
    expect(focus.itemProps.every(({ tabIndex }) => tabIndex === -1)).toBe(true);
    expect(assistantToolRailRovingIndexFromKey(
      0,
      [
        { id: "previous", ariaLabel: "上一章", disabled: true },
        { id: "next", ariaLabel: "下一章", disabled: true },
      ],
      "ArrowRight",
      "horizontal",
    )).toBeNull();
  });

  it("rejects duplicate ids and missing accessible names", () => {
    expect(() => resolveAssistantToolRailRovingFocus([
      { id: "review", ariaLabel: "审稿" },
      { id: "review", ariaLabel: "重复" },
    ])).toThrow("duplicate assistant tool rail item id");
    expect(() => resolveAssistantToolRailRovingFocus([
      { id: "review", ariaLabel: " " },
    ])).toThrow("ariaLabel must not be empty");
  });
});
