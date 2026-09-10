import { describe, expect, it } from "vitest";

import {
  STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS,
  validateStoryLedgerAssistantContext,
} from "./assistant-context";
import {
  accountLegacyLedgerFixtureBudget,
  legacyLedgerContextFixture,
} from "./assistant-context.fixture";


describe("legacy story ledger assistant context validation", () => {
  it("accepts the frozen wire example with its exact Unicode code-point budget", () => {
    const context = legacyLedgerContextFixture();
    expect(validateStoryLedgerAssistantContext(context)).toBe(true);
    expect(context.budget.used_code_points).toBe([...JSON.stringify(context)].length);
    expect(context.budget.used_code_points).toBeLessThanOrEqual(
      STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS,
    );
  });

  it("rejects an added top-level excerpt with an otherwise correct budget", () => {
    const context = accountLegacyLedgerFixtureBudget({
      ...legacyLedgerContextFixture(),
      source_excerpt: "泄漏的正文摘录",
    });
    expect(validateStoryLedgerAssistantContext(context)).toBe(false);
  });

  it("rejects unapproved selected-fact details with an otherwise correct budget", () => {
    const context = legacyLedgerContextFixture();
    const leaked = accountLegacyLedgerFixtureBudget({
      ...context,
      selected_fact: { ...context.selected_fact!, details: { private_note: "不允许泄漏" } },
    });
    expect(validateStoryLedgerAssistantContext(leaked)).toBe(false);
  });

  it("rejects source excerpts nested under otherwise valid source metadata", () => {
    const context = legacyLedgerContextFixture();
    const leaked = accountLegacyLedgerFixtureBudget({
      ...context,
      selected_fact: {
        ...context.selected_fact!,
        source: { ...context.selected_fact!.source!, excerpt: "不允许泄漏" },
      },
    });
    expect(validateStoryLedgerAssistantContext(leaked)).toBe(false);
  });

  it("rejects an oversized Unicode payload even when its budget count is accurate", () => {
    const context = legacyLedgerContextFixture();
    const oversized = accountLegacyLedgerFixtureBudget({
      ...context,
      selected_fact: { ...context.selected_fact!, object_text: "😀".repeat(6_000) },
    });
    expect(oversized.budget.used_code_points).toBe([...JSON.stringify(oversized)].length);
    expect(oversized.budget.used_code_points).toBeGreaterThan(6_000);
    expect(validateStoryLedgerAssistantContext(oversized)).toBe(false);
  });

  it("rejects a forged budget and a selected fact that does not match its id", () => {
    const context = legacyLedgerContextFixture();
    context.budget.used_code_points += 1;
    expect(validateStoryLedgerAssistantContext(context)).toBe(false);

    const mismatched = accountLegacyLedgerFixtureBudget({
      ...legacyLedgerContextFixture(), selected_fact_id: "another-fact",
    });
    expect(validateStoryLedgerAssistantContext(mismatched)).toBe(false);
  });
});
