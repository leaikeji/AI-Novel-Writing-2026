import { describe, expect, it } from "vitest";
import { parseTimingInput, updateInvalidTimingInputs } from "./timing-input";

describe("timing input validation", () => {
  it.each(["", " ", "-1", "5001", "1.5", "1e3", "abc"])("rejects %j without treating it as a duration", (raw) => {
    expect(parseTimingInput(raw, 5000)).toBeNull();
  });
  it.each(["0", "220", "221", "5000"])("accepts integer milliseconds %s", (raw) => {
    expect(parseTimingInput(raw, 5000)).toBe(Number(raw));
  });
  it("preserves invalid text independently until each field is corrected", () => {
    const first = updateInvalidTimingInputs({}, "sentence_gap_ms", "6000", 5000);
    const second = updateInvalidTimingInputs(first, "paragraph_gap_ms", "", 10000);
    expect(second).toEqual({ sentence_gap_ms: "6000", paragraph_gap_ms: "" });
    expect(updateInvalidTimingInputs(second, "sentence_gap_ms", "220", 5000)).toEqual({ paragraph_gap_ms: "" });
    expect(first).toEqual({ sentence_gap_ms: "6000" });
  });
});
