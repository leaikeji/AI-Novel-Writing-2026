import { describe, expect, it } from "vitest";

import {
  splitBoundedSourceExcerpt,
  unicodeCodePointOffsetToUtf16,
} from "./source-coordinate";

describe("story ledger source coordinates", () => {
  it("converts Python code-point offsets without splitting surrogate pairs", () => {
    expect(unicodeCodePointOffsetToUtf16("甲😀乙", 2)).toBe(3);
    expect(splitBoundedSourceExcerpt("前😀证据后", 1, 4)).toEqual({
      before: "前",
      highlighted: "😀证据",
      after: "后",
    });
  });

  it("refuses invalid bounded highlight coordinates", () => {
    expect(splitBoundedSourceExcerpt("短文本", 3, 2)).toBeNull();
    expect(splitBoundedSourceExcerpt("短文本", 1, 99)).toBeNull();
  });
});
