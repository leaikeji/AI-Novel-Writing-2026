import { describe, expect, it } from "vitest";
import sharedCases from "../../../tests/fixtures/character_voice_design_cases.json";

import { buildCharacterVoiceDesignSuggestion, type CharacterVoiceDesignEvidence } from "./character-voice-design-suggestion";

interface Fixture {
  readonly id: string;
  readonly evidence: CharacterVoiceDesignEvidence;
  readonly age: string | null;
  readonly perceived: string | null;
  readonly includes: readonly string[];
  readonly excludes: readonly string[];
}
const fixtures: readonly Fixture[] = sharedCases;

describe("buildCharacterVoiceDesignSuggestion", () => {
  it.each(fixtures)("satisfies the shared handoff case $id", (fixture) => {
    const result = buildCharacterVoiceDesignSuggestion(fixture.evidence);
    expect(result.ageEvidence).toBe(fixture.age);
    expect(result.perceivedAgeEvidence).toBe(fixture.perceived);
    for (const text of fixture.includes) expect(result.description).toContain(text);
    for (const text of fixture.excludes) expect(result.description).not.toContain(text);
    if (result.description) expect(result.description).toContain("标准普通话");
    expect(result.description.length).toBeLessThanOrEqual(500);
  });

  it("keeps saved age first and summarizes personality without reproducing its prose", () => {
    const result = buildCharacterVoiceDesignSuggestion({
      ageAtStoryStartNote: "故事开始时26岁", gender: "男",
      description: "26岁水电工，做事冷静。", personality: "冷静、坚韧，总是像老人一样操心所有人的生活。",
    });
    expect(result.ageSource).toBe("profile");
    expect(result.description.startsWith("人物实际26岁")).toBe(true);
    expect(result.description).toContain("保持青年年龄感，男声");
    expect(result.description).toContain("表达冷静、坚韧");
    expect(result.description).not.toContain("老人");
    expect(result.description).not.toContain("方言");
  });

  it.each(["二十一岁左右", "26岁水电工", "他今年18岁", "陈屿十八岁"])("accepts direct own opening age: %s", (description) => {
    const result = buildCharacterVoiceDesignSuggestion({ characterName: "陈屿", description });
    expect(result.ageSource).toBe("description");
    expect(result.ageEvidence).not.toBeNull();
  });

  it.each(["从业七年，负责检修。", "父亲四十岁。他的声音沙哑。", "赵德发十八岁，声音低沉。", "回忆当年他十八岁。", "如果他十八岁，声音会很清亮。", "据说他四十岁。"])("does not inherit another subject, experience or non-current age: %s", (description) => {
    const result = buildCharacterVoiceDesignSuggestion({ characterName: "陈屿", description });
    expect(result.ageEvidence).toBeNull();
    expect(result.perceivedAgeEvidence).toBeNull();
    expect(result.description).not.toContain("低沉");
    expect(result.description).not.toContain("沙哑");
  });

  it("recovers only at an explicitly named subject after another person", () => {
    const result = buildCharacterVoiceDesignSuggestion({ characterName: "陈屿", description: "赵德发四十岁，他的声音粗粝。陈屿十八岁，陈屿的声音清亮。" });
    expect(result.ageEvidence).toBe("十八岁");
    expect(result.description).toContain("清亮");
    expect(result.description).not.toContain("粗粝");
  });

  it("keeps direct biography clauses after a standalone exact character name", () => {
    const result = buildCharacterVoiceDesignSuggestion({ characterName: "陈屿", description: "陈屿，26岁，声音清亮。" });
    expect(result.ageEvidence).toBe("26岁");
    expect(result.ageSource).toBe("description");
    expect(result.description).toContain("清亮");
    expect(result.warning).toBeNull();
  });

  it.each(["陈屿的父亲，四十岁，声音低沉。", "陈屿然，四十岁，声音低沉。"])("does not treat a name prefix as an exact character subject: %s", (description) => {
    const result = buildCharacterVoiceDesignSuggestion({ characterName: "陈屿", description });
    expect(result.ageEvidence).toBeNull();
    expect(result.perceivedAgeEvidence).toBeNull();
    expect(result.description).not.toContain("四十岁");
    expect(result.description).not.toContain("低沉");
  });

  it.each(["二十多岁", "18岁至22岁", "不到十八岁", "一千岁"])("preserves qualified and fantasy age: %s", (ageAtStoryStartNote) => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote });
    expect(result.ageEvidence).toBe(ageAtStoryStartNote);
    expect(result.description).toContain(ageAtStoryStartNote);
  });

  it("retains only saved age when biography contradicts it and asks for review", () => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "18岁", description: "他四十岁，声音低沉。" });
    expect(result.ageEvidence).toBe("18岁");
    expect(result.warning).toContain("核对");
    expect(result.description).not.toContain("四十岁");
  });

  it("does not choose between two conflicting actual or perceived ages", () => {
    expect(buildCharacterVoiceDesignSuggestion({ description: "他十八岁。他四十岁。" }).ageEvidence).toBeNull();
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "18岁", description: "声音听起来像四十岁。声音听起来像六十岁。" });
    expect(result.perceivedAgeEvidence).toBeNull();
    expect(result.warning).toContain("核对");
  });

  it.each(["声音不像四十岁。", "声音不要显得像四十岁。", "声音听起来像十八岁。", "声音听起来像年轻人。"])("avoids negated and same-age overrides: %s", (description) => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "十八岁", description });
    expect(result.perceivedAgeEvidence).toBeNull();
    expect(result.description).toContain("青年");
    expect(result.description).not.toContain("反差");
  });

  it("preserves the author's explicit voice gender contrast", () => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "18岁", gender: "男", description: "声音像四十岁的中年女人，保持沙哑和粗粝。" });
    expect(result.perceivedAgeEvidence).toBe("四十岁");
    expect(result.description).toContain("四十岁女声");
    expect(result.description).not.toContain("男声");
    expect(result.description).toContain("沙哑、粗粝");
  });

  it("accepts explicit young listening age with unknown actual age", () => {
    const result = buildCharacterVoiceDesignSuggestion({ description: "他的声音听起来像青年，保持清亮。" });
    expect(result.ageSource).toBe("missing");
    expect(result.perceivedAgeEvidence).toBe("青年");
    expect(result.description).toContain("清亮");
    expect(result.warning).toContain("实际年龄");
  });

  it.each(["声音不是沙哑而是清亮。", "声音不要过于沙哑，保持清亮。", "平时声音清亮，昨晚哭过后暂时沙哑。"])("keeps only stable positive voice quality: %s", (description) => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "18岁", description });
    expect(result.description).toContain("清亮");
    expect(result.description).not.toContain("沙哑");
  });

  it("does not invent an age from occupation or personality", () => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "不详，待补充", gender: "男", description: "资深律师，性格威严。", personality: "沉稳" });
    expect(result.ageSource).toBe("missing");
    expect(result.description).toContain("男声");
    expect(result.description).not.toContain("中年");
    expect(result.warning).toContain("实际年龄");
  });

  it("does not collect appearance adjectives from a mixed-subject voice sentence", () => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "18岁", description: "声音低沉而眼睛明亮。" });
    expect(result.description).not.toContain("明亮");
    expect(result.warning).toContain("核对");
  });

  it("does not solidify contradictory quality descriptions", () => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "18岁", description: "声音沙哑。声音并非沙哑，而是清亮。" });
    expect(result.description).not.toContain("沙哑");
    expect(result.description).toContain("清亮");
    expect(result.warning).toContain("核对");
  });

  it.each([
    ["陈屿今年26岁。声音清亮，眼睛明亮。", "26岁", "清亮", "明亮"],
    ["他的声音清亮而眼睛干涩。", null, null, "干涩"],
    ["他18岁，父亲40岁，声音低沉。", "18岁", null, "低沉"],
  ])("keeps subject boundaries for %s", (description, age, included, excluded) => {
    const result = buildCharacterVoiceDesignSuggestion({ characterName: "陈屿", description });
    expect(result.ageEvidence).toBe(age);
    if (included) expect(result.description).toContain(included);
    if (excluded) expect(result.description).not.toContain(excluded);
  });

  it.each([["18 至 22岁", "18至22岁"], ["18岁以上", "18岁以上"], ["18 岁以下", "18岁以下"]])("preserves spaced ranges and bounds %s", (ageAtStoryStartNote, age) => {
    expect(buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote }).ageEvidence).toBe(age);
  });

  it("does not force a 35-year-old voice into a middle-aged template", () => {
    const result = buildCharacterVoiceDesignSuggestion({ ageAtStoryStartNote: "35岁" });
    expect(result.description).toContain("成熟成年");
    expect(result.description).not.toContain("中年");
  });

  it("does not produce a model-ready empty-facts suggestion", () => {
    const result = buildCharacterVoiceDesignSuggestion({});
    expect(result.description).toBe("");
    expect(result.ageSource).toBe("missing");
  });
});
