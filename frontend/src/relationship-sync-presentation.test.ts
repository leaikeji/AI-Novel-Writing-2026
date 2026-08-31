import { describe, expect, it } from "vitest";

import { relationshipSyncPresentation } from "./relationship-sync-presentation";
import { RelationshipAutoSyncStatusRecord } from "./types";


function status(
  override: Partial<RelationshipAutoSyncStatusRecord> = {},
): RelationshipAutoSyncStatusRecord {
  return {
    eligible: true,
    stale: true,
    state: "never",
    input_hash: "hash",
    last_synced_at: null,
    ai_relationship_count: 0,
    manual_relationship_count: 0,
    source_summary: {
      characters: 6,
      relationship_facts: 0,
      chapters: 1,
      excluded_chapters: 0,
    },
    job: null,
    ...override,
  };
}


const idle = { phase: "idle" as const, error: "", modelLabel: "", confirming: false };


describe("relationshipSyncPresentation", () => {
  it("explains that chapter sync can build the graph without a full snapshot", () => {
    const result = relationshipSyncPresentation(status(), idle);

    expect(result.title).toBe("尚无全书关系快照 · 可从章节同步逐步建立");
    expect(result.description).toContain("当前可分析 6 个角色、1 章正文、0 条已确认关系情报");
    expect(result.description).toContain("章节“同步进展”确认后会自动增量完善关系网");
    expect(result.actionLabel).toBe("生成全书关系快照");
    expect(result.forceNew).toBe(false);
  });

  it("distinguishes chapter-created relationships from a full snapshot", () => {
    const result = relationshipSyncPresentation(status({ ai_relationship_count: 2 }), idle);

    expect(result.title).toBe("关系网已由章节同步建立 · 当前 2 条 AI 关系");
    expect(result.actionLabel).toBe("生成全书关系快照");
  });

  it("distinguishes stale, running, failed, and ready states", () => {
    const stale = relationshipSyncPresentation(status({ last_synced_at: "2026-08-26T12:00:00Z" }), idle);
    const running = relationshipSyncPresentation(status({ state: "running" }), idle);
    const failed = relationshipSyncPresentation(status({ state: "failed" }), idle);
    const ready = relationshipSyncPresentation(status({ state: "ready", stale: false, last_synced_at: "2026-08-26T12:00:00Z" }), idle);

    expect(stale.actionLabel).toBe("更新全书关系快照");
    expect(running.actionDisabled).toBe(true);
    expect(running.title).toBe("关系网正在生成");
    expect(failed.actionLabel).toBe("重新生成");
    expect(ready.actionLabel).toBe("重新分析全书快照");
    expect(ready.forceNew).toBe(true);
  });

  it("retries status loading instead of starting generation after a read error", () => {
    const result = relationshipSyncPresentation(status(), {
      ...idle,
      error: "网络暂时不可用",
    });

    expect(result.action).toBe("reload-status");
    expect(result.actionLabel).toBe("重新读取状态");
    expect(result.forceNew).toBe(false);
  });
});
