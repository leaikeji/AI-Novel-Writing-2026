export interface CharacterVoiceDesignEvidence {
  readonly characterName?: string | null;
  readonly ageAtStoryStartNote?: string | null;
  readonly gender?: string | null;
  readonly description?: string | null;
  readonly personality?: string | null;
}

export interface CharacterVoiceDesignSuggestion {
  readonly description: string;
  readonly ageEvidence: string | null;
  readonly perceivedAgeEvidence: string | null;
  readonly ageSource: "profile" | "description" | "missing";
  readonly warning?: string | null;
}

const NUMBER = "(?:[0-9]+|[零〇一二两三四五六七八九十百千万]+)";
// Capture the entire qualified age, never the last number of a range or long lifespan.
const AGE = new RegExp(`(?:不到|未满|不满|超过|至少|约)?${NUMBER}(?:岁?[至到—–~～-]${NUMBER})?(?:多|余)?岁(?:左右|上下|前后|以上|以下|以内|以外)?`, "gu");
const AGE_STAGE = /儿童|少年|青年|年轻人?|中年|老年/gu;
const VOICE = /声音|声线|嗓音|嗓子|听感|听起来|听上去/u;
const UNKNOWN = /未知|不详|未定|未明确|不确定|待补充|尚未明确/u;
const NON_CURRENT = /回忆|当年|曾经|小时候|那年|过去|假如|如果|假设|据说|传闻|听说|有人说/u;
const TEMPORARY = /暂时|一时|昨晚|今天|此刻|感冒|哭过|哭泣|疲惫|疲劳|熬夜|受伤后/u;
const QUALITY = ["沙哑", "粗粝", "粗犷", "低沉", "浑厚", "清亮", "明亮", "清脆", "稚嫩", "沧桑", "磁性", "温柔", "柔和", "尖细", "干涩", "洪亮", "轻柔"] as const;
const EXPRESSION = ["冷静", "坚韧", "直率", "温柔", "活泼", "克制", "沉稳", "爽朗", "内敛"] as const;

function compact(value: string | null | undefined, limit = 500): string {
  return typeof value === "string" ? value.replace(/\s+/gu, " ").trim().slice(0, limit) : "";
}

function ages(text: string): string[] {
  return [...text.replace(/\s+/gu, "").matchAll(AGE)].map((match) => match[0]);
}

function exactAge(text: string): number | null {
  const match = new RegExp(`^(${NUMBER})岁$`, "u").exec(text);
  if (!match) return null;
  const number = match[1]!;
  if (/^\d+$/u.test(number)) return Number(number);
  const digits: Readonly<Record<string, number>> = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  const units: Readonly<Record<string, number>> = { 十: 10, 百: 100, 千: 1000, 万: 10000 };
  if (![...number].some((char) => units[char])) return Number([...number].map((char) => digits[char]).join(""));
  let total = 0;
  let section = 0;
  let digit = 0;
  for (const char of number) {
    const unit = units[char];
    if (unit === 10000) { total += (section + digit || 1) * unit; section = 0; digit = 0; }
    else if (unit) { section += (digit || 1) * unit; digit = 0; }
    else digit = digits[char] ?? 0;
  }
  return total + section + digit;
}

function sameAge(a: string, b: string): boolean {
  return a === b || (exactAge(a) !== null && exactAge(a) === exactAge(b));
}

function stageForAge(age: string | null): string | null {
  const value = age === null ? null : exactAge(age);
  if (value === null || value > 120 || value < 1) return null;
  if (value <= 12) return "儿童";
  if (value <= 17) return "少年";
  if (value <= 34) return "青年";
  if (value <= 49) return "成熟成年";
  if (value <= 64) return "中年";
  return "老年";
}

function sameStage(stage: string, age: string): boolean {
  const value = exactAge(age);
  return stage === stageForAge(age) || (stage === "中年" && value !== null && value >= 35 && value <= 64);
}

function normalizeGender(gender: string): string | null {
  if (["男", "男性", "male", "man", "masculine"].includes(gender.toLowerCase())) return "男声";
  if (["女", "女性", "female", "woman", "feminine"].includes(gender.toLowerCase())) return "女声";
  if (["中性", "非二元", "androgynous", "non-binary", "nonbinary"].includes(gender.toLowerCase())) return "中性声音";
  return null;
}

function withoutOwnSubject(text: string, name: string, allowPronoun: boolean): string {
  let result = text.replace(/^(?:但是|不过|但|平时|天生|长期|一贯|本来|通常|一直)+/u, "");
  if (name && result.startsWith(name)) result = result.slice(name.length).replace(/^的/u, "");
  else if (allowPronoun) result = result.replace(/^(?:本人|人物|他|她)(?:的)?/u, "");
  return result;
}

// Negation ends at an explicit contrast. This is deliberately local, not a general parser.
function positiveParts(text: string): string[] {
  return text.split(/而是|但是|但|却|仍(?:然)?/u).filter((part) => !/(?:不要|不是|并非|不像|不必|避免|没有|不带|不显|不应|不能|不太|不够|不)/u.test(part));
}

/** Direct, saved character evidence only. Ambiguity produces a review hint, not invented facts. */
export function buildCharacterVoiceDesignSuggestion(evidence: CharacterVoiceDesignEvidence): CharacterVoiceDesignSuggestion {
  const name = compact(evidence.characterName, 80);
  const profile = compact(evidence.ageAtStoryStartNote, 80);
  const profileAges = UNKNOWN.test(profile) ? [] : ages(profile);
  const hasProfileAge = profileAges.length === 1 && !NON_CURRENT.test(profile);
  let ageEvidence = hasProfileAge ? profileAges[0]! : null;
  let ageSource: CharacterVoiceDesignSuggestion["ageSource"] = hasProfileAge ? "profile" : "missing";
  const actualCandidates: string[] = [];
  const perceivedCandidates: string[] = [];
  const genderCandidates: string[] = [];
  const qualities = new Set<string>();
  const negatedQualities = new Set<string>();
  let uncertain = profileAges.length > 1;
  let foreignSubject = false;

  for (const sentence of compact(evidence.description).split(/[。！？；\n]/u)) {
    if (!sentence.trim()) continue;
    if (NON_CURRENT.test(sentence) || /[“”「」]/u.test(sentence)) {
      if (VOICE.test(sentence) || ages(sentence).length) uncertain = true;
      foreignSubject = true;
      continue;
    }
    let voiceContinuation = false;
    for (const raw of sentence.split(/[，,]/u)) {
      const clause = raw.trim();
      // A standalone exact name establishes the following direct biographical clauses.
      // Possessives such as “陈屿的父亲” must still pass the unknown-subject boundary below.
      if (name && clause.replace(/^(?:但是|不过|但)/u, "") === name) {
        foreignSubject = false;
        voiceContinuation = false;
        continue;
      }
      const named = Boolean(name && clause.replace(/^(?:但是|不过|但)/u, "").startsWith(name));
      if (named) foreignSubject = false;
      const own = withoutOwnSubject(clause, name, !foreignSubject);
      const directVoice = !foreignSubject && /^(?:声音|声线|嗓音|嗓子|听感|听起来|听上去)/u.test(own);
      const directAgeText = own.replace(/\s+/gu, "").replace(/^(?:在)?(?:故事(?:开始|开篇)(?:时)?|开篇时|实际年龄(?:是|为)?|年龄(?:是|为)?|今年|年仅|现年)/u, "");
      const ageMatch = ages(directAgeText)[0];
      if (!foreignSubject && !directVoice && ageMatch && directAgeText.startsWith(ageMatch)) {
        actualCandidates.push(ageMatch);
        voiceContinuation = false;
        continue;
      }
      const continuesVoice = voiceContinuation && /^(?:像|如同|仿佛|接近|保持|带着|带有|有着|显得|呈现|听起来|听上去|而是|但|仍)/u.test(own);
      if (!directVoice && !continuesVoice) {
        voiceContinuation = false;
        if (VOICE.test(clause) || ages(clause).length) uncertain = true;
        // Unrecognized subjects cannot lend their next pronoun to the current character.
        if (!/^(?:实际年龄|年龄)/u.test(own)) foreignSubject = true;
        continue;
      }
      voiceContinuation = true;
      if (TEMPORARY.test(clause)) { uncertain = true; voiceContinuation = false; continue; }
      const parts = positiveParts(own);
      for (const part of own.split(/而是|但是|但|却|仍(?:然)?/u)) {
        if (!parts.includes(part)) for (const term of QUALITY) if (part.includes(term)) negatedQualities.add(term);
      }
      for (const positive of parts) {
        // Mixed voice/appearance subjects are not a direct voice-quality statement.
        if (/(?:眼睛|眼神|皮肤|面容|外貌|性格)/u.test(positive)) { uncertain = true; continue; }
        for (const term of QUALITY) if (positive.includes(term)) qualities.add(term);
        if (/(?:像|如同|仿佛|接近|听感|听起来|听上去)/u.test(positive)) {
          const numeric = ages(positive);
          perceivedCandidates.push(...(numeric.length ? numeric : [...positive.matchAll(AGE_STAGE)].map((match) => match[0])));
        }
        if (/(?:女声|女人|女性)/u.test(positive)) genderCandidates.push("女声");
        if (/(?:男声|男人|男性)/u.test(positive)) genderCandidates.push("男声");
      }
    }
  }

  const distinctActual = actualCandidates.filter((age, i, list) => !list.slice(0, i).some((other) => sameAge(age, other)));
  for (const term of negatedQualities) if (qualities.delete(term)) uncertain = true;
  if (distinctActual.length > 1 || (ageEvidence && distinctActual.some((age) => !sameAge(age, ageEvidence!)))) uncertain = true;
  if (!ageEvidence && distinctActual.length === 1) { ageEvidence = distinctActual[0]!; ageSource = "description"; }
  const perceived = [...new Set(perceivedCandidates.map((age) => age.startsWith("年轻") ? "青年" : age))];
  const distinctPerceived = perceived.filter((age, i, list) => !list.slice(0, i).some((other) => sameAge(age, other) || sameStage(age, other) || sameStage(other, age)));
  if (distinctPerceived.length > 1) uncertain = true;
  const candidate = distinctPerceived.length === 1 ? distinctPerceived[0]! : null;
  const perceivedAgeEvidence = candidate && (!ageEvidence || (!sameAge(candidate, ageEvidence) && !sameStage(candidate, ageEvidence))) ? candidate : null;
  const voiceGenders = [...new Set(genderCandidates)];
  if (voiceGenders.length > 1) uncertain = true;
  const gender = voiceGenders.length === 1 ? voiceGenders[0]! : normalizeGender(compact(evidence.gender, 24));
  const personality = EXPRESSION.filter((term) => positiveParts(compact(evidence.personality, 120)).some((part) => part.includes(term))).slice(0, 2);
  const clauses = [
    ageEvidence ? `人物实际${ageEvidence}` : null,
    perceivedAgeEvidence ? `声音听感明确接近${perceivedAgeEvidence}${gender ?? ""}${ageEvidence ? "，保留人物固有的声音反差" : ""}`
      : ageEvidence ? `${stageForAge(ageEvidence) ? `保持${stageForAge(ageEvidence)}年龄感` : (exactAge(ageEvidence) ?? 0) > 120 ? "长寿设定不自动换算成人类声音年龄" : "保留该年龄范围，听感请结合人物设定"}${gender ? `，${gender}` : ""}` : gender,
    qualities.size ? `稳定音质：${[...qualities].slice(0, 4).join("、")}${ageEvidence && !perceivedAgeEvidence ? "，音质不改变年龄感" : ""}` : null,
    personality.length ? `表达${personality.join("、")}` : null,
    "标准普通话，自然对白，吐字清楚",
  ].filter((item): item is string => item !== null);
  const hasFacts = Boolean(ageEvidence || perceivedAgeEvidence || qualities.size || gender || personality.length);
  return Object.freeze({
    description: hasFacts ? `${clauses.join("；")}。`.slice(0, 500) : "",
    ageEvidence,
    perceivedAgeEvidence,
    ageSource,
    warning: uncertain ? "部分年龄或声音描述的归属、时效或含义不明确，未自动采用；请核对声音描述。"
      : !ageEvidence ? "人物实际年龄尚未明确，请核对目标声音的年龄感。" : null,
  });
}
