import { describe, expect, it } from "vitest";
import { methodDetailLines, parseMethodDetails } from "./details";
import { canAdvanceWritingMethodStatus, parseWritingMethodStatus } from "./contracts";
import { historyLines, parseChapterMethodHistory } from "./history";
import { writingMethodPresentation } from "./status";

const DOC = "11111111-1111-4111-8111-111111111111";
const JOB = "22222222-2222-4222-8222-222222222222";
const DETAILS = { schema_version: "writing-method-details/1", primary_skill: "prose-writing",
  methods: [{ skill_id: "prose-writing", display_name: "冻结正文方法", version: "0.3.0", body_sha256: "a".repeat(64),
    reference_count: 2, basis: "primary", evidence_refs: [] }], reasons: ["author_generic_only"], estimated_tokens: 100 };
const HISTORY = { schema_version: "chapter-method-history/1", document_id: DOC, job_id: JOB,
  record_status: "recorded", phase: "dispatched", method_input_hash: "b".repeat(64), details: DETAILS };

describe("frozen method evidence", () => {
  it("includes the primary method with its frozen name/version, not current catalog labels", () => {
    const details = parseMethodDetails({ ...DETAILS, text: "must be stripped" })!;
    expect(methodDetailLines(details).join("\n")).toContain("版本 0.3.0");
    expect(methodDetailLines(details).join("\n")).toContain("作者选择本次仅通用");
    expect(methodDetailLines(details).join("\n")).toContain("不是 Provider 实际用量");
    expect(details).not.toHaveProperty("text");
    const status = parseWritingMethodStatus({ schema_version: "writing-method-status/1", action_id: DOC,
      dispatch_id: JOB, state: "dispatched", job_ref: `chapter:${JOB}`, method_input_hash: "b".repeat(64), details })!;
    expect(writingMethodPresentation(status, { "prose-writing": "不可倒填的新版名称" }).title).toContain("冻结正文方法");
    expect(canAdvanceWritingMethodStatus(status, { ...status, details: null })).toBe(false);
  });
  it.each([
    { version: "latest" }, { display_name: "x".repeat(81) }, { body_sha256: "fake" },
    { reference_count: -1 }, { reference_count: 0.5 }, { basis: "model_used" },
    { evidence_refs: ["private story contents"] },
  ])("rejects malformed metadata %#", patch => {
    expect(parseMethodDetails({ ...DETAILS, methods: [{ ...DETAILS.methods[0], ...patch }] })).toBeNull();
  });
  it("does not claim method loading for legacy or damaged historical references", () => {
    for (const state of ["legacy_unrecorded", "evidence_unavailable"]) {
      const value = parseChapterMethodHistory({ ...HISTORY, record_status: state, phase: null,
        method_input_hash: null, details: null }, DOC, JOB)!;
      expect(value).not.toBeNull();
      expect(historyLines(value).join(" ")).toMatch(/未记录|缺失/);
      expect(parseChapterMethodHistory({ ...HISTORY, record_status: state }, DOC, JOB)).toBeNull();
    }
  });
  it("rejects another chapter/job and distinguishes an unknown dispatch from a success", () => {
    expect(parseChapterMethodHistory(HISTORY, JOB, JOB)).toBeNull();
    expect(parseChapterMethodHistory(HISTORY, DOC, DOC)).toBeNull();
    const unknown = parseChapterMethodHistory({ ...HISTORY, phase: "unknown" }, DOC, JOB)!;
    expect(historyLines(unknown).join(" ")).toContain("不代表生成成功");
    expect(parseChapterMethodHistory({ ...HISTORY, phase: "guaranteed" }, DOC, JOB)).toBeNull();
  });
});
