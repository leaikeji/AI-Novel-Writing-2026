import { describe, expect, it } from "vitest";

import {
  chapterVersionPresentation,
  formatChapterUpdatedAt,
} from "./chapter-list";


describe("chapterVersionPresentation", () => {
  it("只投影真实草稿和检查点状态，不产生发布标签", () => {
    expect(chapterVersionPresentation("empty_draft").label).toBe("空白草稿");
    expect(chapterVersionPresentation("saved_working_copy").label).toBe("工作稿已保存");
    expect(chapterVersionPresentation("checkpointed").label).toBe("已建检查点");
    expect([
      chapterVersionPresentation("empty_draft").label,
      chapterVersionPresentation("saved_working_copy").label,
      chapterVersionPresentation("checkpointed").label,
    ]).not.toContain("已发布");
  });

  it("兼容尚未返回 version_state 的旧后端", () => {
    expect(chapterVersionPresentation(undefined)).toMatchObject({
      label: "已保存",
      tone: "saved",
    });
  });
});


describe("formatChapterUpdatedAt", () => {
  it("把有效时间格式化为紧凑的月日与时分", () => {
    expect(formatChapterUpdatedAt("2026-09-01T08:09:00+08:00")).toMatch(
      /^\d{2}-\d{2} \d{2}:\d{2}$/,
    );
  });

  it("缺失或无效时间使用占位符", () => {
    expect(formatChapterUpdatedAt(null)).toBe("—");
    expect(formatChapterUpdatedAt("not-a-date")).toBe("—");
  });
});
