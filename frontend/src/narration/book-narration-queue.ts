export type BookNarrationQueuePhase =
  | "idle"
  | "preparing"
  | "playing"
  | "paused"
  | "blocked"
  | "failed"
  | "ended";


export interface BookNarrationChapter {
  readonly documentId: string;
  readonly label: string;
  readonly sourceContentHash: string;
}


export interface BookNarrationChapterCandidate extends BookNarrationChapter {
  readonly visibleCharacterCount: number;
}


export interface BookNarrationQueueState {
  readonly runId: number;
  readonly novelId: string;
  readonly chapters: readonly BookNarrationChapter[];
  readonly index: number;
  readonly phase: BookNarrationQueuePhase;
  readonly consumedEndedKey: string | null;
  readonly message: string;
}


export function createBookNarrationQueue(
  novelId: string,
  chapters: readonly BookNarrationChapter[],
  runId: number,
): BookNarrationQueueState {
  if (!novelId || chapters.length === 0 || !Number.isSafeInteger(runId) || runId < 1) {
    throw new Error("全书朗读需要有效作品、章节顺序与运行代次。");
  }
  return Object.freeze({
    runId,
    novelId,
    chapters: Object.freeze(chapters.map((chapter) => Object.freeze({ ...chapter }))),
    index: 0,
    phase: "preparing",
    consumedEndedKey: null,
    message: `正在准备 1/${chapters.length} · ${chapters[0]?.label ?? "第一章"}`,
  });
}


export function selectNarratableBookChapters(
  chapters: readonly BookNarrationChapterCandidate[],
): readonly BookNarrationChapter[] {
  return Object.freeze(chapters
    .filter((chapter) => chapter.visibleCharacterCount > 0 && chapter.sourceContentHash.length > 0)
    .map(({ documentId, label, sourceContentHash }) => Object.freeze({
      documentId,
      label,
      sourceContentHash,
    })));
}


export function bookNarrationEditionIsCurrent(
  state: BookNarrationQueueState,
  documentId: string,
  documentContentHash: string,
  editionSourceContentHash: string,
): boolean {
  const current = currentBookNarrationChapter(state);
  return current.documentId === documentId
    && current.sourceContentHash === documentContentHash
    && current.sourceContentHash === editionSourceContentHash;
}


export function currentBookNarrationChapter(
  state: BookNarrationQueueState,
): BookNarrationChapter {
  const current = state.chapters[state.index];
  if (!current) throw new Error("全书朗读位置已经超出章节范围。");
  return current;
}


export function markBookNarrationPlaying(
  state: BookNarrationQueueState,
): BookNarrationQueueState {
  const chapter = currentBookNarrationChapter(state);
  return Object.freeze({
    ...state,
    phase: "playing",
    message: `正在朗读 ${state.index + 1}/${state.chapters.length} · ${chapter.label}`,
  });
}


export function markBookNarrationPaused(
  state: BookNarrationQueueState,
): BookNarrationQueueState {
  const chapter = currentBookNarrationChapter(state);
  return Object.freeze({
    ...state,
    phase: "paused",
    message: `已暂停 ${state.index + 1}/${state.chapters.length} · ${chapter.label}`,
  });
}


export function advanceBookNarrationQueue(
  state: BookNarrationQueueState,
  endedKey: string,
): BookNarrationQueueState {
  if (state.phase !== "playing" || !endedKey || state.consumedEndedKey === endedKey) return state;
  const nextIndex = state.index + 1;
  if (nextIndex >= state.chapters.length) {
    return Object.freeze({
      ...state,
      phase: "ended",
      consumedEndedKey: endedKey,
      message: `全书 ${state.chapters.length} 章已连续朗读完成。`,
    });
  }
  const next = state.chapters[nextIndex];
  return Object.freeze({
    ...state,
    index: nextIndex,
    phase: "preparing",
    consumedEndedKey: endedKey,
    message: `正在准备 ${nextIndex + 1}/${state.chapters.length} · ${next?.label ?? "下一章"}`,
  });
}


export function stopBookNarrationQueue(
  state: BookNarrationQueueState,
  message = "全书朗读已停止。",
): BookNarrationQueueState {
  return Object.freeze({ ...state, phase: "idle", message });
}
