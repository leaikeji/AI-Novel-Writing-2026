import { describe, expect, it } from "vitest";

import { buildCharacterVoiceDesignSuggestion } from "./character-voice-design-suggestion";


describe("buildCharacterVoiceDesignSuggestion", () => {
  it("puts the saved exact age first and keeps personality subordinate", () => {
    const result = buildCharacterVoiceDesignSuggestion({
      ageAtStoryStartNote: "故事开始时26岁",
      gender: "男",
      description: "26岁水电工，做事冷静。",
      personality: "冷静、坚韧",
    });

    expect(result.ageSource).toBe("profile");
    expect(result.ageEvidence).toBe("26岁");
    expect(result.description.startsWith("26岁，年龄感为第一优先级")).toBe(true);
    expect(result.description).toContain("保持青年年龄感");
    expect(result.description).toContain("气质不能覆盖年龄感");
    expect(result.description).toContain("标准普通话，不使用方言");
    expect(result.description).toContain("避免中年化、厚重、沙哑或沧桑");
  });

  it("uses only an explicit age mention from the public description as fallback", () => {
    const result = buildCharacterVoiceDesignSuggestion({
      gender: "女",
      description: "二十一岁左右，刚刚离开校园。",
    });

    expect(result.ageSource).toBe("description");
    expect(result.ageEvidence).toBe("二十一岁左右");
    expect(result.description.startsWith("二十一岁左右，年龄感为第一优先级")).toBe(true);
    expect(result.description).toContain("女性声音呈现");
  });

  it("finds an Arabic age immediately followed by the occupation", () => {
    const result = buildCharacterVoiceDesignSuggestion({
      gender: "男",
      description: "26岁水电工，做事利落。",
    });

    expect(result.ageSource).toBe("description");
    expect(result.ageEvidence).toBe("26岁");
    expect(result.description).toContain("避免中年化、厚重、沙哑或沧桑");
  });

  it("does not infer age from a name, occupation, identity, or unknown marker", () => {
    expect(buildCharacterVoiceDesignSuggestion({
      ageAtStoryStartNote: "未知",
      gender: "男",
      description: "资深律师，性格威严。",
      personality: "沉稳",
    })).toEqual({
      description: "",
      ageEvidence: null,
      ageSource: "missing",
    });
  });

  it("does not mistake years of experience for a character age", () => {
    const result = buildCharacterVoiceDesignSuggestion({
      description: "从业七年，负责高压配电检修。",
    });

    expect(result.ageSource).toBe("missing");
    expect(result.description).toBe("");
  });
});
