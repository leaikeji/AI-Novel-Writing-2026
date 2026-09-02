import { describe, expect, it, vi } from "vitest";

import {
  StoryLedgerRequestFence,
  filterStoryLedgerFacts,
  prepareStoryLedgerOperationAttempt,
  storyLedgerFilterIdentity,
  summarizeStoryLedgerRisks,
} from "./state-model";

describe("story ledger shared state", () => {
  it("keeps effective state and health independent", () => {
    const facts = [
      { id: "a", dimension: "location", effective_state: "current", health: "conflict", source_document_id: "d1" },
      { id: "b", dimension: "location", effective_state: "historical", health: "ok", source_document_id: "d1" },
      { id: "c", dimension: "goal", effective_state: "source_invalid", health: "ambiguous", source_document_id: "d2" },
    ] as const;
    expect(filterStoryLedgerFacts(facts, {
      effectiveState: "current",
      health: "conflict",
    }).map((fact) => fact.id)).toEqual(["a"]);
    expect(summarizeStoryLedgerRisks(facts)).toEqual({
      actionableCount: 2,
      conflictCount: 1,
      ambiguousCount: 1,
      invalidSourceCount: 1,
    });
  });

  it("normalizes filter identity without depending on fact-type order", () => {
    const first = storyLedgerFilterIdentity({
      factTypes: ["world_state", "character_state"],
      reviewOnly: true,
    });
    const second = storyLedgerFilterIdentity({
      reviewOnly: true,
      factTypes: ["character_state", "world_state"],
    });
    expect(first).toBe(second);
  });

  it("reuses one operation key for the exact payload and rotates it after edits", () => {
    const keys = ["story-ledger-correction:first", "story-ledger-correction:second"];
    const keyFactory = vi.fn(() => keys.shift() as string);
    const first = prepareStoryLedgerOperationAttempt(
      null,
      "correction",
      "fact-1",
      { reason: "证据", replacement: { details: { b: 2, a: 1 }, object_text: "新事实" } },
      keyFactory,
    );
    const exactRetry = prepareStoryLedgerOperationAttempt(
      first,
      "correction",
      "fact-1",
      { replacement: { object_text: "新事实", details: { a: 1, b: 2 } }, reason: "证据" },
      keyFactory,
    );
    const edited = prepareStoryLedgerOperationAttempt(
      exactRetry,
      "correction",
      "fact-1",
      { replacement: { object_text: "另一事实", details: { a: 1, b: 2 } }, reason: "证据" },
      keyFactory,
    );

    expect(exactRetry).toBe(first);
    expect(edited.operationKey).toBe("story-ledger-correction:second");
    expect(edited).not.toBe(first);
    expect(keyFactory).toHaveBeenCalledTimes(2);
  });

  it("isolates late completions per channel and invalidates every channel on scope change", () => {
    const fence = new StoryLedgerRequestFence();
    fence.setScope("novel-1:timeline-1:snapshot-1");
    const page1 = fence.begin("page", "filters-a");
    const source = fence.begin("source", "fact-a");
    const page2 = fence.begin("page", "filters-b");

    expect(page1.signal.aborted).toBe(true);
    expect(page1.isCurrent()).toBe(false);
    expect(page2.isCurrent()).toBe(true);
    expect(source.isCurrent()).toBe(true);

    fence.setScope("novel-1:timeline-2:snapshot-2");
    expect(page2.signal.aborted).toBe(true);
    expect(source.signal.aborted).toBe(true);
    expect(page2.isCurrent()).toBe(false);
    expect(source.isCurrent()).toBe(false);
  });

  it("keeps page, append, preview, source and mutation completions independently fenced", () => {
    const fence = new StoryLedgerRequestFence();
    fence.setScope("scope");
    const leases = ["page", "append", "impact-preview", "source", "mutation"]
      .map((channel) => fence.begin(channel, `${channel}:1`));
    expect(leases.every((lease) => lease.isCurrent())).toBe(true);
    const replacement = fence.begin("impact-preview", "fact-2");
    expect(leases[2].isCurrent()).toBe(false);
    expect(replacement.isCurrent()).toBe(true);
    expect(leases.filter((_, index) => index !== 2).every((lease) => lease.isCurrent()))
      .toBe(true);
  });
});
