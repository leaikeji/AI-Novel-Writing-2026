import { describe, expect, it } from "vitest";

import { resolveAssistantWorkspaceLayout } from "./assistant-layout";
import {
  ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE,
  resolveAssistantToolRailGeometry,
  resolveAssistantToolRailRovingFocus,
} from "./assistant-tool-rail";


const HOST_NAVIGATION_WIDTH = 200;
const CHAPTER_TREE_WIDTHS = [
  { state: "expanded", width: 270 },
  { state: "collapsed", width: 54 },
] as const;
const ASSISTANT_WIDTHS = [320, 380, 520] as const;
const DESKTOP_VIEWPORTS = [
  { label: "1920x1080", width: 1920, height: 1080 },
  { label: "2560x1440", width: 2560, height: 1440 },
] as const;


const TOOL_ITEMS = [
  { id: "review", ariaLabel: "AI 审稿" },
  { id: "intelligence", ariaLabel: "查看章节情报" },
  { id: "previous", ariaLabel: "上一章" },
  { id: "next", ariaLabel: "下一章" },
] as const;


describe("assistant layout + chapter tool rail", () => {
  it.each(DESKTOP_VIEWPORTS.flatMap((viewport) => (
    ASSISTANT_WIDTHS.flatMap((assistantWidth) => (
      CHAPTER_TREE_WIDTHS.map((tree) => ({
        viewport,
        assistantWidth,
        tree,
      }))
    ))
  )))(
    "$viewport.label / assistant $assistantWidth / tree $tree.state keeps the rail before the assistant",
    ({ viewport, assistantWidth, tree }) => {
      const workspace = resolveAssistantWorkspaceLayout({
        containerWidth: viewport.width - HOST_NAVIGATION_WIDTH,
        preferredAssistantWidth: assistantWidth,
        pageKind: "chapter-editor",
      });
      const rail = resolveAssistantToolRailGeometry({
        viewportWidth: viewport.width,
        viewportHeight: viewport.height,
        hostNavigationWidth: HOST_NAVIGATION_WIDTH,
        chapterTreeWidth: tree.width,
        assistantPaneWidth: workspace.assistantWidth,
        itemCount: TOOL_ITEMS.length,
      });

      expect(workspace.assistantWidth).toBe(assistantWidth);
      expect(rail.mode).toBe("edge");
      expect(rail.orientation).toBe("vertical");
      expect(rail.assistantLeft).toBe(viewport.width - assistantWidth);
      expect(rail.railRight).toBeLessThanOrEqual(rail.assistantLeft);
      expect(Number(rail.rootProps["data-assistant-tool-rail-right"])).toBeLessThanOrEqual(
        Number(rail.rootProps["data-assistant-pane-left"]),
      );
      expect(rail.buttonHitSize).toBeGreaterThanOrEqual(
        ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE,
      );
    },
  );

  it.each(DESKTOP_VIEWPORTS.flatMap((viewport) => (
    ASSISTANT_WIDTHS.flatMap((assistantWidth) => (
      CHAPTER_TREE_WIDTHS.map((tree) => ({
        viewport,
        assistantWidth,
        tree,
      }))
    ))
  )))(
    "$viewport.label at 200% / assistant $assistantWidth uses a horizontal footer with tree $tree.state",
    ({ viewport, assistantWidth, tree }) => {
      const effectiveViewport = {
        width: Math.round(viewport.width / 2),
        height: Math.round(viewport.height / 2),
      };
      const workspace = resolveAssistantWorkspaceLayout({
        containerWidth: effectiveViewport.width - HOST_NAVIGATION_WIDTH,
        preferredAssistantWidth: assistantWidth,
        pageKind: "chapter-editor",
      });
      const rail = resolveAssistantToolRailGeometry({
        viewportWidth: effectiveViewport.width,
        viewportHeight: effectiveViewport.height,
        hostNavigationWidth: HOST_NAVIGATION_WIDTH,
        chapterTreeWidth: tree.width,
        assistantPaneWidth: workspace.assistantWidth,
        itemCount: TOOL_ITEMS.length,
      });
      const focus = resolveAssistantToolRailRovingFocus(
        TOOL_ITEMS,
        0,
        rail.buttonHitSize,
      );

      expect(rail.mode).toBe("footer");
      expect(rail.orientation).toBe("horizontal");
      expect(rail.rootProps["aria-orientation"]).toBe("horizontal");
      expect(rail.railRight).toBeLessThanOrEqual(rail.assistantLeft);
      expect(focus.itemProps.filter(({ tabIndex }) => tabIndex === 0)).toHaveLength(1);
      for (const props of focus.itemProps) {
        expect(Number.parseInt(props.style.minWidth, 10)).toBeGreaterThanOrEqual(40);
        expect(Number.parseInt(props.style.minHeight, 10)).toBeGreaterThanOrEqual(40);
      }
    },
  );
});
