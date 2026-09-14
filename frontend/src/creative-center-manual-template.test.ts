// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";
import { templateFieldMeta } from "./template-field-meta";


describe("manual-template novel creation route", () => {
  const source = readFileSync(new URL("./creative-center.ts", import.meta.url), "utf8");

  it("marks the explicit no-AI route without inventing an idea", () => {
    expect(source).toContain('await persist(3, { ...data, manual_template_entry: true })');
    expect(source).toContain('updateData({ idea: event.target.value, manual_template_entry: false })');
  });

  it("uses one author-facing field vocabulary with a lossless custom-key fallback", () => {
    expect(templateFieldMeta("core_conflict")).toEqual({
      label: "核心冲突",
      placeholder: "请输入核心冲突",
    });
    expect(templateFieldMeta("weather_pressure")).toEqual({
      label: "自定义字段（weather_pressure）",
      placeholder: "请填写该自定义字段",
    });
    expect(templateFieldMeta("").label).toBe("自定义字段（空键）");
  });
});
