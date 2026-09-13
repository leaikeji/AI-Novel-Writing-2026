export interface CharacterVoiceDesignEvidence {
  readonly ageAtStoryStartNote?: string | null;
  readonly gender?: string | null;
  readonly description?: string | null;
  readonly personality?: string | null;
}


export interface CharacterVoiceDesignSuggestion {
  readonly description: string;
  readonly ageEvidence: string | null;
  readonly ageSource: "profile" | "description" | "missing";
}


const EXPLICIT_AGE = /((?:[1-9]\d?|1[01]\d|120)\s*岁(?:左右|上下|前后)?|[零〇一二两三四五六七八九十百]{1,6}岁(?:左右|上下|前后)?)/u;
const UNKNOWN_AGE = /^(?:未知|不详|未定|未明确|不确定|暂不确定)$/u;


function compactText(value: string | null | undefined, maximumLength: number): string {
  if (typeof value !== "string") return "";
  return value.replace(/\s+/gu, " ").trim().slice(0, maximumLength);
}


function explicitAgeFromDescription(description: string | null | undefined): string | null {
  const compact = compactText(description, 500);
  const match = EXPLICIT_AGE.exec(compact);
  return match?.[1]?.replace(/\s+/gu, "") ?? null;
}


function normalizeGender(gender: string | null | undefined): string | null {
  const compact = compactText(gender, 24).toLowerCase();
  if (["男", "男性", "male", "man", "masculine"].includes(compact)) return "男性声音呈现";
  if (["女", "女性", "female", "woman", "feminine"].includes(compact)) return "女性声音呈现";
  if (["中性", "非二元", "androgynous", "non-binary", "nonbinary"].includes(compact)) {
    return "中性声音呈现";
  }
  return null;
}


function numericAge(ageEvidence: string): number | null {
  const match = /(?:^|\D)(\d{1,3})\s*岁/u.exec(ageEvidence);
  if (match === null) return null;
  const value = Number(match[1]);
  return Number.isInteger(value) && value >= 1 && value <= 120 ? value : null;
}


function ageGuard(ageEvidence: string): string {
  const age = numericAge(ageEvidence);
  if (age === null) return "准确呈现该年龄阶段，不擅自拔高或压低年龄感";
  if (age <= 12) return "保持儿童年龄感，避免成年化、低沉或沧桑";
  if (age <= 17) return "保持少年年龄感，避免中年化、厚重或沧桑";
  if (age <= 34) return "保持青年年龄感，避免中年化、厚重、沙哑或沧桑";
  if (age <= 49) return "保持成熟成年人的年龄感，避免少年化或老年化";
  if (age <= 64) return "保持中年人的年龄感，避免少年化或老年化";
  return "保持老年人的真实年龄感，避免刻意年轻化";
}


/**
 * Build an editable Mandarin voice-design description from saved character facts.
 * Age is always the first and strongest instruction. Missing age fails closed:
 * the system returns no suggestion instead of inferring from a name or occupation.
 */
export function buildCharacterVoiceDesignSuggestion(
  evidence: CharacterVoiceDesignEvidence,
): CharacterVoiceDesignSuggestion {
  const profileAge = compactText(evidence.ageAtStoryStartNote, 80);
  const hasProfileAge = Boolean(profileAge && !UNKNOWN_AGE.test(profileAge));
  const ageEvidence = hasProfileAge
    ? explicitAgeFromDescription(profileAge) ?? profileAge
    : explicitAgeFromDescription(evidence.description);
  if (ageEvidence === null) {
    return Object.freeze({
      description: "",
      ageEvidence: null,
      ageSource: "missing",
    });
  }

  const gender = normalizeGender(evidence.gender);
  const personality = compactText(evidence.personality, 80);
  const clauses = [
    `${ageEvidence}，年龄感为第一优先级，${ageGuard(ageEvidence)}`,
    gender,
    personality ? `表达气质参考：${personality}；气质不能覆盖年龄感` : null,
    "标准普通话，不使用方言",
    "自然清晰，适合小说人物对白，避免播音腔和刻意压低或抬高声线",
  ].filter((item): item is string => item !== null);

  return Object.freeze({
    description: `${clauses.join("；")}。`,
    ageEvidence,
    ageSource: hasProfileAge ? "profile" : "description",
  });
}
