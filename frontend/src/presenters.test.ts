import { describe, expect, it } from "vitest";

import {
  chapterDisplayTitle,
  chapterTitleName,
  factStatusLabel,
  factTypeLabel,
  isClueFactType,
  revisionSourceLabel,
  selectFactView,
} from "./presenters";
import type { StoryFactRecord } from "./types";


function fact(overrides: Partial<StoryFactRecord>): StoryFactRecord {
  return {
    id: "fact-id",
    novel_id: "novel-id",
    fact_type: "fact",
    subject: "主题",
    predicate: "状态",
    object_text: "内容",
    details: {},
    source_revision_id: "revision-id",
    status: "active",
    created_at: null,
    ...overrides,
  };
}


describe("story fact presenters", () => {
  it("优先展示当前有效资料，不混入旧稿资料", () => {
    const view = selectFactView(
      [
        fact({ id: "stale", status: "source_superseded" }),
        fact({ id: "current", status: "active" }),
      ],
      () => true,
    );

    expect(view.state).toBe("current");
    expect(view.facts.map((item) => item.id)).toEqual(["current"]);
  });

  it("没有当前资料时明确返回待复核旧稿，而不是演示数据", () => {
    const view = selectFactView(
      [fact({ id: "stale", status: "source_superseded" })],
      () => true,
    );

    expect(view.state).toBe("stale");
    expect(view.facts.map((item) => item.id)).toEqual(["stale"]);
  });

  it("把随版本恢复重新生效的资料视为当前资料", () => {
    const view = selectFactView(
      [fact({ id: "restored", status: "source_restored" })],
      () => true,
    );

    expect(view.state).toBe("current");
    expect(view.facts.map((item) => item.id)).toEqual(["restored"]);
  });

  it("把内部类型和版本来源转换成作者可读中文", () => {
    expect(factTypeLabel("character_state")).toBe("人物状态");
    expect(factStatusLabel("source_superseded")).toBe("基于旧稿");
    expect(revisionSourceLabel("manual_restore")).toBe("历史恢复");
    expect(revisionSourceLabel("pre_restore_checkpoint")).toBe("恢复前保护版本");
    expect(isClueFactType("foreshadow_new")).toBe(true);
    expect(isClueFactType("relationship")).toBe(false);
  });

  it("按全书顺序补齐章节序号，并替换标题中已有的旧序号", () => {
    expect(chapterDisplayTitle(4, "退回的旧木盒")).toBe("第4章 退回的旧木盒");
    expect(chapterDisplayTitle(5, "第五章：雾里来的人")).toBe("第5章 雾里来的人");
    expect(chapterDisplayTitle(6, "第6章")).toBe("第6章");
    expect(chapterTitleName("第十二章 · 潮声来信")).toBe("潮声来信");
  });
});
