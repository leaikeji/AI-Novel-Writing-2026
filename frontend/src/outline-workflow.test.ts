import { describe, expect, it } from "vitest";

import {
  nextOutlineGenerationTarget,
  outlineGenerationTarget,
} from "./outline-workflow";


describe("outline page generation targets", () => {
  it("maps each editable content step to its own generation kind", () => {
    expect(outlineGenerationTarget(2)).toMatchObject({ kind: "outline_background", name: "故事背景" });
    expect(outlineGenerationTarget(3)).toMatchObject({ kind: "outline_characters", name: "角色设定" });
    expect(outlineGenerationTarget(4)).toMatchObject({ kind: "outline_plot", name: "故事情节" });
    expect(outlineGenerationTarget(5)).toMatchObject({ kind: "outline_highlight", name: "故事亮点" });
  });

  it("generates the following step when the author clicks next", () => {
    expect(nextOutlineGenerationTarget(1).step).toBe(2);
    expect(nextOutlineGenerationTarget(2).step).toBe(3);
    expect(nextOutlineGenerationTarget(3).step).toBe(4);
    expect(nextOutlineGenerationTarget(4).step).toBe(5);
  });

  it("rejects capacity and completed steps as generation targets", () => {
    expect(() => outlineGenerationTarget(1)).toThrow("大纲生成步骤无效");
    expect(() => nextOutlineGenerationTarget(5)).toThrow("大纲生成步骤无效");
  });
});
