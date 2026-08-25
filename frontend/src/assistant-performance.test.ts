import { describe, expect, it } from "vitest";

import { NovelAssistantContextStore } from "./assistant-context-store";
import type { AIApplyMeta, EditableFieldAdapter } from "./assistant-fields";


function percentile95(samples: readonly number[]): number {
  const ordered = [...samples].sort((left, right) => left - right);
  return ordered[Math.floor((ordered.length - 1) * 0.95)] ?? Number.POSITIVE_INFINITY;
}


function largeField(value: string): EditableFieldAdapter {
  return {
    id: "chapter.body",
    label: "正文",
    persistence: "autosave",
    undoPolicy: "ai-transaction",
    getValue: () => value,
    applyValue: (_next: string, _meta: AIApplyMeta) => undefined,
    getSelection: () => null,
    focus: () => undefined,
    getDirty: () => true,
    dispose: () => undefined,
  };
}


function largeContextStore(): NovelAssistantContextStore {
  const store = new NovelAssistantContextStore({
    agentId: "ai-novel-writer",
    sessionId: "performance-session",
    envelope: {
      agentId: "ai-novel-writer",
      novel: { id: "novel-performance", title: "性能验收长篇" },
      page: { section: "chapters", view: "chapter-editor" },
      entity: { type: "document", id: "document-performance", title: "长章节" },
      document: {
        id: "document-performance",
        kind: "chapter",
        chapterNumber: 1,
        title: "长章节",
        draftVersion: 1,
        savedContentHash: "a".repeat(64),
        dirty: true,
      },
    },
  });
  store.registerField(largeField("章".repeat(24_000)));
  store.setFocusedField("chapter.body");
  return store;
}


describe("assistant context performance gate", () => {
  it("builds a bounded 24k snapshot below the 50ms p95 gate", () => {
    const store = largeContextStore();
    const samples: number[] = [];
    for (let index = 0; index < 120; index += 1) {
      const startedAt = performance.now();
      const capture = store.capture();
      const elapsed = performance.now() - startedAt;
      expect(capture.serialized.length).toBeLessThanOrEqual(24_000);
      if (index >= 20) samples.push(elapsed);
    }
    expect(percentile95(samples)).toBeLessThan(50);
  });

  it("keeps 100 lightweight field invalidations below the 50ms long-task gate", () => {
    const store = largeContextStore();
    const samples: number[] = [];
    for (let index = 0; index < 100; index += 1) {
      const startedAt = performance.now();
      store.notifyFieldChanged("chapter.body");
      samples.push(performance.now() - startedAt);
    }
    expect(Math.max(...samples)).toBeLessThan(50);
  });
});
