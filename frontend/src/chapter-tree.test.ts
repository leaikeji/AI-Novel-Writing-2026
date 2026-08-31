import { describe, expect, it } from "vitest";

import {
  buildChapterTreeVolumes,
  canonicalChapterDocuments,
  chapterOrdinalFor,
  nextChapterOrdinalForVolume,
} from "./chapter-tree";
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
    expect(tree.map((item) => item.displayTitle)).toEqual([
      "第1卷 潮汐旧声",
      "第2卷 潮汐回信",
    ]);
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
    expect(buildChapterTreeVolumes(novel, "第3章")[0].chapters[0].document.id).toBe("chapter-5");
    expect(buildChapterTreeVolumes(novel, "不存在")).toEqual([]);
  });

  it("无论 position 如何都把未分卷章节投影在真实分卷之后", () => {
    const assigned = chapter("chapter-assigned", "卷内章节", 2, 100);
    assigned.volume_id = "volume-1";
    const unassigned = chapter("chapter-unassigned", "历史未分卷", 1, 100);
    unassigned.volume_id = null;
    const novel = novelWithVolumes([
      { id: null, title: "未分卷", position: 0, version: 1, documents: [unassigned] },
      { id: "volume-1", title: "", position: 9, version: 1, documents: [assigned] },
    ]);

    expect(canonicalChapterDocuments(novel).map((item) => item.id)).toEqual([
      "chapter-assigned",
      "chapter-unassigned",
    ]);
    expect(chapterOrdinalFor(novel, "chapter-assigned")).toBe(1);
    expect(chapterOrdinalFor(novel, "chapter-unassigned")).toBe(2);
    expect(buildChapterTreeVolumes(novel).map((item) => item.key)).toEqual([
      "volume-1",
      "unassigned",
    ]);
  });

  it("按目标卷末尾计算新章预览序号，不把其后的卷或未分卷计入", () => {
    const novel = novelWithVolumes([
      { id: "volume-2", title: "后卷", position: 20, version: 1, documents: [chapter("chapter-3", "后卷章节", 1, 100)] },
      { id: null, title: "未分卷", position: 0, version: 1, documents: [chapter("chapter-4", "历史未分卷", 1, 100)] },
      { id: "volume-1", title: "前卷", position: 10, version: 1, documents: [chapter("chapter-1", "一", 1, 100), chapter("chapter-2", "二", 2, 100)] },
    ]);

    expect(nextChapterOrdinalForVolume(novel, "volume-1")).toBe(3);
    expect(nextChapterOrdinalForVolume(novel, "volume-2")).toBe(4);
    expect(nextChapterOrdinalForVolume(novel, "missing")).toBeUndefined();
  });
});
