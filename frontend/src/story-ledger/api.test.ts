import { afterEach, describe, expect, it, vi } from "vitest";

import {
  correctStoryLedgerFact,
  loadStoryLedgerFacts,
  loadStoryLedgerFactSource,
  loadStoryLedgerSummary,
  revertStoryLedgerBatch,
} from "./api";

function response(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("story ledger API", () => {
  it("encodes a normalized bounded page request and forwards AbortSignal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ schema_version: "story-ledger-page/1" }));
    vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
    const controller = new AbortController();

    await loadStoryLedgerFacts({
      novelId: "novel 1",
      timelineId: "timeline-1",
      narrativeCutoff: 8,
      snapshotToken: "snapshot-token",
    }, {
      limit: 40,
      cursor: "cursor-token",
      factTypes: ["world_state", "character_state"],
      health: "conflict",
      reviewOnly: true,
    }, controller.signal);

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(path, "https://local.invalid");
    expect(parsed.pathname).toBe("/ai-novel-world-2026/novels/novel%201/story-ledger/facts");
    expect(parsed.searchParams.getAll("fact_type")).toEqual(["character_state", "world_state"]);
    expect(parsed.searchParams.get("timeline_id")).toBe("timeline-1");
    expect(parsed.searchParams.get("narrative_cutoff")).toBe("8");
    expect(parsed.searchParams.get("snapshot_token")).toBe("snapshot-token");
    expect(parsed.searchParams.get("cursor")).toBe("cursor-token");
    expect(parsed.searchParams.get("limit")).toBe("40");
    expect(parsed.searchParams.get("review_only")).toBe("true");
    expect(init.signal).toBe(controller.signal);
  });

  it("keeps summary and source on the same explicit snapshot scope", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ schema_version: "story-ledger-summary/1" }))
      .mockResolvedValueOnce(response({ schema_version: "story-ledger-source/1" }));
    vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
    const scope = { novelId: "novel-1", timelineId: "timeline-1", snapshotToken: "snap" };
    await loadStoryLedgerSummary(scope, { effectiveState: "current" });
    await loadStoryLedgerFactSource(scope, "fact-1");
    expect(fetchMock.mock.calls.map(([path]) => String(path))).toEqual([
      "/ai-novel-world-2026/novels/novel-1/story-ledger/summary?timeline_id=timeline-1&snapshot_token=snap&effective_state=current",
      "/ai-novel-world-2026/novels/novel-1/story-ledger/facts/fact-1/source?timeline_id=timeline-1&snapshot_token=snap",
    ]);
  });

  it("uses one shared mutation API and preserves the supplied operation key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ replayed: false }));
    vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
    await correctStoryLedgerFact("novel-1", "fact-1", {
      schema_version: "story-fact-correction/1",
      operation_key: "story-ledger-correction:same-attempt",
      expected_story_ledger_version: 9,
      reason: "修正",
      replacement: { object_text: "新事实" },
    });
    await revertStoryLedgerBatch("novel-1", "batch-1", {
      operation_key: "story-ledger-batch-revert:same-attempt",
      expected_story_ledger_version: 10,
      reason: null,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body)).operation_key)
      .toBe("story-ledger-correction:same-attempt");
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body)).operation_key)
      .toBe("story-ledger-batch-revert:same-attempt");
  });
});
