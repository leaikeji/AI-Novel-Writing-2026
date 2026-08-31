export const CHAPTER_CREATION_REQUIRES_VOLUME_MESSAGE = "请先创建分卷，再新建章节";


export function chapterCreationBlockedReason(volumeCount: number): string | null {
  return volumeCount > 0 ? null : CHAPTER_CREATION_REQUIRES_VOLUME_MESSAGE;
}


export type ChapterWizardPreparationState = "idle" | "loading" | "ready" | "failure";
export type ChapterWizardRequestPhase = "not_started" | "loading" | "succeeded" | "failed";
export type ChapterWizardDraftState = "draft" | "completed" | null;
export type ChapterWizardPreparationEffect = "none" | "restore_completed_document";


export interface ChapterWizardPreparationInput {
  open: boolean;
  requestPhase: ChapterWizardRequestPhase;
  draftState: ChapterWizardDraftState;
  scopeValid: boolean;
  completedDocumentId?: string | null;
}


export interface ChapterWizardPreparationTransition {
  state: ChapterWizardPreparationState;
  effect: ChapterWizardPreparationEffect;
}


/**
 * Derive the only preparation state that the wizard is allowed to render.
 *
 * A completed draft is kept in loading while its existing document is restored;
 * it must never reopen the six-step wizard or flash a generic failure first.
 */
export function chapterWizardPreparationTransition(
  input: ChapterWizardPreparationInput,
): ChapterWizardPreparationTransition {
  if (!input.open) return { state: "idle", effect: "none" };
  if (!input.scopeValid) return { state: "failure", effect: "none" };

  if (input.requestPhase === "not_started" || input.requestPhase === "loading") {
    return { state: "loading", effect: "none" };
  }
  if (input.requestPhase === "failed") {
    return { state: "failure", effect: "none" };
  }
  if (input.draftState === "draft") {
    return { state: "ready", effect: "none" };
  }
  if (input.draftState === "completed" && input.completedDocumentId?.trim()) {
    return { state: "loading", effect: "restore_completed_document" };
  }
  return { state: "failure", effect: "none" };
}


export function chapterWizardPreparationState(
  input: ChapterWizardPreparationInput,
): ChapterWizardPreparationState {
  return chapterWizardPreparationTransition(input).state;
}


export interface ChapterPreparationRequestScope {
  novelId: string;
  draftKey: string;
  requestGeneration: number;
}


export interface ChapterPreparationRequestStart {
  requestPhase: "loading";
  scope: ChapterPreparationRequestScope;
}


function assertRequestGeneration(value: number): void {
  if (!Number.isSafeInteger(value) || value < 0 || value >= Number.MAX_SAFE_INTEGER) {
    throw new RangeError("requestGeneration must be a non-negative safe integer with room to increment");
  }
}


/**
 * Allocate a fresh request generation and enter loading in one pure transition.
 * The caller retains the returned generation across close/reopen and novel changes.
 */
export function startChapterPreparationRequest(
  previousGeneration: number,
  novelId: string,
  draftKey: string,
): ChapterPreparationRequestStart {
  assertRequestGeneration(previousGeneration);
  return {
    requestPhase: "loading",
    scope: {
      novelId,
      draftKey,
      requestGeneration: previousGeneration + 1,
    },
  };
}


/**
 * A request may commit data or errors only while its complete scope is current.
 */
export function chapterPreparationResponseIsCurrent(
  activeScope: ChapterPreparationRequestScope | null,
  responseScope: ChapterPreparationRequestScope,
  signalAborted = false,
): boolean {
  if (signalAborted || !activeScope) return false;
  return activeScope.novelId === responseScope.novelId
    && activeScope.draftKey === responseScope.draftKey
    && activeScope.requestGeneration === responseScope.requestGeneration;
}
