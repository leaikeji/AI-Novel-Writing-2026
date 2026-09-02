import { describe, expect, it } from "vitest";

import {
  chapterDisplayTitle,
  chapterTitleForStorage,
  chapterTitleName,
  revisionSourceLabel,
  volumeDisplayTitle,
  volumeTitleForStorage,
  volumeTitleName,
} from "./presenters";
describe("document title presenters", () => {
  it("把版本来源转换成作者可读中文", () => {
    expect(revisionSourceLabel("manual_restore")).toBe("历史恢复");
    expect(revisionSourceLabel("pre_restore_checkpoint")).toBe("恢复前保护版本");
  });

  it("按全书顺序补齐章节序号，并替换标题中已有的旧序号", () => {
    expect(chapterDisplayTitle(4, "退回的旧木盒")).toBe("第4章 退回的旧木盒");
    expect(chapterDisplayTitle(5, "第五章：雾里来的人")).toBe("第5章 雾里来的人");
    expect(chapterDisplayTitle(6, "第6章")).toBe("第6章");
    expect(chapterTitleName("第十二章 · 潮声来信")).toBe("潮声来信");
    expect(chapterTitleName("第 12 章：潮声来信")).toBe("潮声来信");
    expect(chapterTitleName("第一万章 - 潮声来信")).toBe("潮声来信");
    expect(chapterTitleForStorage(7, "第六章：潮声来信")).toBe("潮声来信");
    expect(chapterTitleForStorage(7, "第六章")).toBe("");
    expect(chapterTitleForStorage(7, "  ")).toBe("");
    expect(chapterTitleName("第一章里的秘密")).toBe("第一章里的秘密");
  });

  it("按分卷顺序补齐卷序号，并把作者输入限制为卷名本身", () => {
    expect(volumeDisplayTitle(3, "海堤下的静默")).toBe("第3卷 海堤下的静默");
    expect(volumeDisplayTitle(2, "第五卷：黎明前的广播")).toBe("第2卷 黎明前的广播");
    expect(volumeDisplayTitle(1, "第一卷")).toBe("第1卷");
    expect(volumeTitleName("第十二卷 · 潮汐旧声")).toBe("潮汐旧声");
    expect(volumeTitleName("第 1 卷 - 潮汐旧声")).toBe("潮汐旧声");
    expect(volumeTitleForStorage(4, "第二卷：潮汐旧声")).toBe("潮汐旧声");
    expect(volumeTitleForStorage(4, "第二卷")).toBe("");
    expect(volumeTitleForStorage(4, "  ")).toBe("");
    expect(volumeTitleName("第三卷轴之谜")).toBe("第三卷轴之谜");
  });
});
