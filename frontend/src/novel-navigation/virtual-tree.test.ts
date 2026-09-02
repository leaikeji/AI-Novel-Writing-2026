import { describe, expect, it } from "vitest";

import type { ChapterTreeVolume } from "../chapter-tree";
import {
  fixedVirtualScrollTarget,
  flattenChapterTreeRows,
  virtualizeFixedRows,
  virtualizeChapterTreeRows,
} from "./virtual-tree";


function volumes(chapterCount: number): ChapterTreeVolume[] {
  return [{
    key: "volume-1",
    volume: { id: "volume-1", title: "第一卷", position: 1000, version: 1, documents: [] },
    volumeNumber: 1,
    displayTitle: "第一卷",
    chapters: Array.from({ length: chapterCount }, (_, index) => ({
      chapterNumber: index + 1,
      displayTitle: `第${index + 1}章`,
      document: {
        id: `chapter-${index + 1}`,
        novel_id: "novel-1",
        volume_id: "volume-1",
        kind: "chapter",
        title: "",
        position: (index + 1) * 1000,
        version: 1,
        draft_version: 1,
        base_revision_id: null,
        content_markdown: "",
        content_hash: "hash",
        visible_character_count: 2000,
        updated_at: null,
        revisions: [],
      },
    })),
  }];
}


describe("chapter tree virtualization", () => {
  it("keeps the rendered row window bounded for 2,500 chapters", () => {
    const rows = flattenChapterTreeRows(volumes(2500), new Set(["volume-1"]));
    const window = virtualizeChapterTreeRows(rows, 52_000, 840);
    expect(rows).toHaveLength(2501);
    expect(window.rows.length).toBeLessThanOrEqual(37);
    expect(window.totalHeight).toBe(2501 * 42);
    expect(window.rows[0].index).toBeGreaterThan(1000);
  });

  it("renders only volume rows while a volume is collapsed", () => {
    const rows = flattenChapterTreeRows(volumes(2500), new Set());
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe("volume");
  });

  it("bounds the project chapter dashboard without dropping absolute positions", () => {
    const chapters = Array.from({ length: 2500 }, (_, index) => `chapter-${index + 1}`);
    const window = virtualizeFixedRows(chapters, 90_000, 720, 72, 8);
    expect(window.rows.length).toBeLessThanOrEqual(26);
    expect(window.totalHeight).toBe(180_000);
    expect(window.rows[0].index).toBeGreaterThan(1000);
    expect(window.rows[0].top).toBe(window.rows[0].index * 72);
  });

  it("provides deterministic keyboard targets for a virtual scrollport", () => {
    expect(fixedVirtualScrollTarget("End", 0, 720, 180_000)).toBe(179_280);
    expect(fixedVirtualScrollTarget("Home", 90_000, 720, 180_000)).toBe(0);
    expect(fixedVirtualScrollTarget("PageDown", 90_000, 720, 180_000)).toBe(90_720);
    expect(fixedVirtualScrollTarget("PageUp", 100, 720, 180_000)).toBe(0);
    expect(fixedVirtualScrollTarget("ArrowDown", 0, 720, 180_000)).toBeNull();
  });
});
