import { describe, expect, it } from "vitest";

import {
  advanceBookNarrationQueue,
  bookNarrationEditionIsCurrent,
  createBookNarrationQueue,
  currentBookNarrationChapter,
  markBookNarrationPaused,
  markBookNarrationPlaying,
  selectNarratableBookChapters,
  stopBookNarrationQueue,
} from "./book-narration-queue";


const chapters = [
  { documentId: "chapter-1", label: "第1章 开门", sourceContentHash: "1".repeat(64) },
  { documentId: "chapter-2", label: "第2章 蓄水", sourceContentHash: "2".repeat(64) },
  { documentId: "chapter-3", label: "第3章 下井", sourceContentHash: "3".repeat(64) },
] as const;


describe("book narration queue", () => {
  it("follows canonical input order and consumes one ended event once", () => {
    const started = createBookNarrationQueue("novel-1", chapters, 1);
    expect(currentBookNarrationChapter(started).documentId).toBe("chapter-1");
    expect(currentBookNarrationChapter(started).sourceContentHash).toBe("1".repeat(64));
    expect(Object.isFrozen(started.chapters[0])).toBe(true);
    const playing = markBookNarrationPlaying(started);
    const second = advanceBookNarrationQueue(playing, "edition-1:ended");
    expect(second.phase).toBe("preparing");
    expect(currentBookNarrationChapter(second).documentId).toBe("chapter-2");
    expect(advanceBookNarrationQueue(second, "edition-1:ended")).toBe(second);
  });

  it("does not advance while paused and ends after the final chapter", () => {
    let state = markBookNarrationPlaying(createBookNarrationQueue("novel-1", chapters, 2));
    state = advanceBookNarrationQueue(state, "edition-1:ended");
    state = markBookNarrationPlaying(state);
    const paused = markBookNarrationPaused(state);
    expect(advanceBookNarrationQueue(paused, "edition-2:ended")).toBe(paused);
    state = advanceBookNarrationQueue(markBookNarrationPlaying(paused), "edition-2:ended");
    state = advanceBookNarrationQueue(markBookNarrationPlaying(state), "edition-3:ended");
    expect(state.phase).toBe("ended");
    expect(state.message).toContain("3 章已连续朗读完成");
  });

  it("stops without changing chapter order or position", () => {
    const state = markBookNarrationPlaying(createBookNarrationQueue("novel-1", chapters, 3));
    const stopped = stopBookNarrationQueue(state);
    expect(stopped.phase).toBe("idle");
    expect(stopped.index).toBe(0);
    expect(stopped.chapters).toEqual(chapters);
  });

  it("selects navigation-shell chapters by visible count instead of absent bodies", () => {
    const selected = selectNarratableBookChapters([
      { ...chapters[0], visibleCharacterCount: 2739 },
      { ...chapters[1], visibleCharacterCount: 0 },
      { ...chapters[2], visibleCharacterCount: 2555 },
    ]);
    expect(selected.map((chapter) => chapter.documentId)).toEqual(["chapter-1", "chapter-3"]);
    expect(selected[0]).not.toHaveProperty("visibleCharacterCount");
  });

  it("rejects a ready edition whose source hash is older than the frozen queue", () => {
    const state = createBookNarrationQueue("novel-1", chapters, 4);
    expect(bookNarrationEditionIsCurrent(
      state,
      "chapter-1",
      "1".repeat(64),
      "1".repeat(64),
    )).toBe(true);
    expect(bookNarrationEditionIsCurrent(
      state,
      "chapter-1",
      "1".repeat(64),
      "f".repeat(64),
    )).toBe(false);
  });
});
