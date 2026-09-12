import { describe, expect, it } from "vitest";

import { officialVoiceProfileDisplayName } from "./index";


describe("narration voice presentation", () => {
  it("adds the official speaker to legacy profile names without duplicating canonical names", () => {
    expect(officialVoiceProfileDisplayName("温暖女声", "qwen.WarmFemale"))
      .toBe("Serena｜温暖女声");
    expect(officialVoiceProfileDisplayName("Aiden｜明亮男声", "qwen.ClearMale"))
      .toBe("Aiden｜明亮男声");
    expect(officialVoiceProfileDisplayName("私人音色", null)).toBe("私人音色");
  });
});
