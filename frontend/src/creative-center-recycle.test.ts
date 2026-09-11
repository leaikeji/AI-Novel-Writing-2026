// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";


const source = readFileSync(new URL("./creative-center.ts", import.meta.url), "utf8");
const recycleSource = readFileSync(new URL("./recycle-bin.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.ts", import.meta.url), "utf8");


describe("creative center recoverable deletion", () => {
  it("uses reversible copy and the recycle endpoint helper", () => {
    expect(source).toContain("移入回收站");
    expect(source).toContain("可随时从回收站恢复");
    expect(source).toContain("recycleNovel(novel.id, novel.version)");
    expect(source).not.toContain("此操作不可撤销");
    expect(source).not.toContain("`/novels/${novel.id}?expected_version=${novel.version}`");
  });

  it("exposes the recycle bin without bulk purge", () => {
    expect(source).toContain('label: "回收站"');
    expect(source).toContain('view === "recycle-bin"');
    expect(styles).toContain(".mb-recycle-card");
    expect(styles).toContain("@media (max-width:720px)");
    expect(source).not.toContain("清空回收站");
  });

  it("uses the author's two-step typed confirmation without a hidden backup prerequisite", () => {
    expect(recycleSource).toContain("作品已经经过移入回收站这一步");
    expect(recycleSource).toContain('confirmationText !== "确认删除"');
    expect(recycleSource).toContain("purgeContent(message)");
    expect(recycleSource).not.toContain("系统必须已存在与当前作品版本绑定");
  });
});
