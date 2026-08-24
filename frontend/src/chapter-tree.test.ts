import { describe, expect, it } from "vitest";

import { buildChapterTreeVolumes } from "./chapter-tree";
import { DocumentRecord, NovelRecord, VolumeRecord } from "./types";


function chapter(id: string, title: string, position: number, count: number): DocumentRecord {
  return {
    id,
    novel_id: "novel-1",
    volume_id: position < 3 ? "volume-1" : "volume-2",
    kind: "chapter",
    title,
    position,
    version: 1,
    draft_version: 1,
    base_revision_id: null,
    content_markdown: "",
    content_hash: "",
    visible_character_count: count,
    updated_at: null,
    revisions: [],
  };
}


function novelWithVolumes(volumes: VolumeRecord[]): NovelRecord {
  return { id: "novel-1", tree: volumes } as NovelRecord;
}


describe("buildChapterTreeVolumes", () => {
  it("按卷章位置排序并生成跨卷连续章节编号", () => {
    const novel = novelWithVolumes([
      { id: "volume-2", title: "第二卷 潮汐回信", position: 2, version: 1, documents: [chapter("chapter-4", "退回的旧木盒", 4, 1021)] },
      { id: "volume-1", title: "第一卷 潮汐旧声", position: 1, version: 1, documents: [chapter("chapter-2", "海风与旧巷", 2, 1200), chapter("chapter-1", "旧电台", 1, 1100)] },
    ]);

    const tree = buildChapterTreeVolumes(novel);

    expect(tree.map((item) => item.key)).toEqual(["volume-1", "volume-2"]);
    expect(tree.flatMap((item) => item.chapters.map((chapterItem) => chapterItem.displayTitle))).toEqual([
      "第1章 旧电台",
      "第2章 海风与旧巷",
      "第3章 退回的旧木盒",
    ]);
  });

  it("可按卷名或章节名过滤且保留原章节编号", () => {
    const novel = novelWithVolumes([
      { id: "volume-1", title: "第一卷 潮汐旧声", position: 1, version: 1, documents: [chapter("chapter-1", "旧电台", 1, 1100)] },
      { id: "volume-2", title: "第二卷 潮汐回信", position: 2, version: 1, documents: [chapter("chapter-4", "退回的旧木盒", 4, 1021), chapter("chapter-5", "雾里来的人", 5, 1186)] },
    ]);

    expect(buildChapterTreeVolumes(novel, "潮汐回信")[0].chapters).toHaveLength(2);
    expect(buildChapterTreeVolumes(novel, "雾里")[0].chapters[0].displayTitle).toBe("第3章 雾里来的人");
    expect(buildChapterTreeVolumes(novel, "不存在")).toEqual([]);
  });
});
