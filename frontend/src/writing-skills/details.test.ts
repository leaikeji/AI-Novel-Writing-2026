import { describe, expect, it } from "vitest";
import { parseMethodDetails } from "./details";
import { canAdvanceWritingMethodStatus, parseWritingMethodStatus } from "./contracts";

const DOC = "11111111-1111-4111-8111-111111111111";
const JOB = "22222222-2222-4222-8222-222222222222";
const DETAILS = { schema_version: "writing-method-details/1", primary_skill: "prose-writing",
  methods: [{ skill_id: "prose-writing", display_name: "冻结正文方法", version: "0.3.0", body_sha256: "a".repeat(64),
    reference_count: 2, basis: "primary", evidence_refs: [] }], reasons: ["author_generic_only"], estimated_tokens: 100 };

describe("frozen method evidence", () => {
  it("includes the primary method with its frozen name/version, not current catalog labels", () => {
    const details = parseMethodDetails({ ...DETAILS, text: "must be stripped" })!;
    expect(details).not.toHaveProperty("text");
    const status = parseWritingMethodStatus({ schema_version: "writing-method-status/1", action_id: DOC,
      dispatch_id: JOB, state: "dispatched", job_ref: `chapter:${JOB}`, method_input_hash: "b".repeat(64), details })!;
    expect(status.details?.methods[0]).toMatchObject({ display_name: "冻结正文方法", version: "0.3.0" });
    expect(canAdvanceWritingMethodStatus(status, { ...status, details: null })).toBe(false);
  });
  it.each([
    { version: "latest" }, { display_name: "x".repeat(81) }, { body_sha256: "fake" },
    { reference_count: -1 }, { reference_count: 0.5 }, { basis: "model_used" },
    { evidence_refs: ["private story contents"] },
  ])("rejects malformed metadata %#", patch => {
    expect(parseMethodDetails({ ...DETAILS, methods: [{ ...DETAILS.methods[0], ...patch }] })).toBeNull();
  });
});
