import { describe, expect, it } from "vitest";
import {
  assembledCapabilityIds, parseWritingMethodStatus, WRITING_METHOD_STATUS_SCHEMA,
} from "./contracts";

const BASE = {
  schema_version: WRITING_METHOD_STATUS_SCHEMA,
  action_id: "11111111-1111-4111-8111-111111111111",
  dispatch_id: "22222222-2222-4222-8222-222222222222", state: "claimed",
};

describe("writing-method-status/1", () => {
  it("defaults semantic enhancement off and strips content-bearing extra fields", () => {
    const parsed = parseWritingMethodStatus({ ...BASE, prompt: "private text", novel: "private" });
    expect(parsed).toEqual({ ...BASE, selected_ids: [], omitted_ids: [], method_input_hash: null,
      semantic_enabled: false, auxiliary_calls: 0, job_ref: null });
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed?.selected_ids)).toBe(true);
  });

  it.each([
    { schema_version: "writing-method-status/2" }, { action_id: "other" }, { dispatch_id: "other" },
    { state: "used_by_model" }, { auxiliary_calls: -1 }, { auxiliary_calls: 0.5 },
    { auxiliary_calls: NaN }, { auxiliary_calls: null }, { semantic_enabled: "false" },
    { semantic_enabled: null }, { selected_ids: null }, { selected_ids: ["../escape"] },
    { selected_ids: ["a", "a"] }, { omitted_ids: [5] }, { method_input_hash: "invalid" },
    { job_ref: "" }, { job_ref: "x".repeat(241) },
    { state: "assembled" }, { state: "dispatch_started" },
    { state: "claimed", method_input_hash: "a".repeat(64) },
    { state: "dispatched", method_input_hash: "a".repeat(64) },
  ])("rejects malformed or unproven response %#", (patch) => {
    expect(parseWritingMethodStatus({ ...BASE, ...patch })).toBeNull();
  });

  it("subtracts omitted IDs from assembled capability names", () => {
    const parsed = parseWritingMethodStatus({ ...BASE, state: "assembled", method_input_hash: "a".repeat(64),
      selected_ids: ["suspense-writing", "future-module"], omitted_ids: ["future-module"] });
    expect(parsed).not.toBeNull();
    expect(assembledCapabilityIds(parsed!)).toEqual(["suspense-writing"]);
    expect(assembledCapabilityIds(parseWritingMethodStatus(BASE)!)).toEqual([]);
  });
});
