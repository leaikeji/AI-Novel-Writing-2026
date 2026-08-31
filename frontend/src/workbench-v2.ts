import { ApiError, apiRequest, getGenerationModelStatus } from "./api";
import {
  CHAPTER_BODY_FIELD_ID,
  CHAPTER_TITLE_FIELD_ID,
  ChapterWorkflowPanel,
  mountChapterBodyAssistantScope,
  mountChapterTitleAssistantScope,
  readAssistantTextSelection,
  restoreAssistantTextSelection,
  type AssistantTextControl,
  type ChapterBodyAssistantBinding,
  type ChapterFormAssistantBinding,
} from "./chapter-workflow";
import type { AssistantFormFieldAdapter } from "./assistant-form-field";
import { assistantContextRuntime } from "./assistant-context-runtime";
import {
  buildChapterTreeVolumes,
  canonicalChapterDocuments,
  canonicalVolumeRecords,
  chapterOrdinalFor,
  ChapterTreeChapter,
  ChapterTreeVolume,
} from "./chapter-tree";
import { CREATIVE_CENTER_CHAT_PATH } from "./contracts";
import {
  clearRecoveryDraft,
  loadRecoveryDraft,
  RecoveryDraft,
  saveRecoveryDraft,
} from "./recovery";
import {
  chapterDisplayTitle as formatChapterDisplayTitle,
  chapterTitleName,
  factStatusLabel,
  factTypeLabel,
  isClueFactType,
  revisionSourceLabel,
  selectFactView,
  volumeDisplayTitle,
} from "./presenters";
import { workbenchStore } from "./store";
import {
  DocumentRecord,
  GenerationModelStatus,
  NovelCharacterRecord,
  NovelRecord,
  RestorePreviewRecord,
  StoryFactRecord,
  VolumeRecord,
} from "./types";
import {
  activeWorkbenchRoute,
  clearWorkbenchRoute,
  isWorkbenchReadingPanel,
  isWorkbenchRouteSection,
  rememberWorkbenchLocation,
  replaceWorkbenchHistoryUrl,
  type WorkbenchReadingPanel,
  type WorkbenchRouteSection,
} from "./workbench-route";
import { canReuseActiveDocumentLoad } from "./workbench-document-load-fence";
import { StudioProjectView, WorkbenchSection } from "./workbench-studio";
import type { AssistantWorkspaceLayout } from "./assistant-layout";
import type { SelectionEditReviewHostComponent } from "./selection-edit-runtime";
import {
  createChapterEditorSurface,
  type ChapterEditorSurfaceHandle,
} from "./narration/chapter-editor-surface";
import {
  createChapterNarrationPanel,
  type ChapterNarrationPanelPhase,
  type ChapterNarrationSourceKind,
} from "./narration/chapter-narration-panel";
import {
  DEFAULT_PLAYBACK_PROFILE_ID,
  createChapterNarrationSession,
  type ChapterNarrationSession,
  type ChapterNarrationSessionPlayResult,
  type ChapterNarrationSessionSnapshot,
} from "./narration/chapter-narration-session";
import {
  ChapterNarrationWorkflowError,
  startChapterNarrationWorkflow,
  type ChapterNarrationWorkflowProgress,
  type StableChapterNarrationSource,
} from "./narration/chapter-narration-workflow";
import {
  getNarrationOverview,
  getFailedNarrationSegments,
  getNarrationWorkflow,
  listCharacterVoiceBindings,
  NarrationProductionApiError,
  retryFailedNarrationSegments,
  switchNarrationEdition,
} from "./narration/api";
import {
  loadChapterNarrationCapabilityGate,
  retainEquivalentChapterNarrationCapabilityGate,
  type ChapterNarrationCapabilityGate,
} from "./narration/chapter-capability-gate";
import {
  getNarrationScriptVersionForEdition,
  patchNarrationScriptSegment,
  type ScriptReviewVersionScope,
} from "./narration/script-api";
import {
  buildScriptReviewSpeakerChoices,
  createScriptReviewPanel,
  type ScriptReviewActiveCharacterBinding,
  type ScriptReviewFocusRef,
  type ScriptReviewSpeakerChoice,
} from "./narration/script-review-panel";
import { continueApprovedScriptProduction } from "./narration/script-review-continue";
import type {
  NarrationWorkflowResource,
} from "./narration/chapter-contracts";
import {
  createFailedSegmentRetryController,
  type FailedSegmentRetryController,
  type FailedSegmentRetrySnapshot,
} from "./narration/failed-segment-retry-state";
import type { EditionHistoryItem } from "./narration/edition-history";
import type { SegmentRenderStatus } from "./narration/playback-contracts";
import type {
  ScriptReviewResource,
  ScriptReviewSegmentResource,
} from "./narration/script-contracts";
import {
  createParagraphGutterController,
  type NarrationParagraphDescriptor,
  type ParagraphGutterController,
} from "./narration/paragraph-gutter";
import defaultNovelCover from "../assets/novel-cover-fengcunqu.jpg";
import { navigateNovelSurface } from "./novel-surface-navigation";
import { createNovelCoverView } from "./novel-cover";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const NovelCoverView = createNovelCoverView(React);
const ChapterNarrationPanel = createChapterNarrationPanel(React);
const ScriptReviewPanel = createScriptReviewPanel(React);
const NARRATION_GATE_REFRESH_MILLISECONDS = 5_000;
const {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Spin,
} = host.antd;
const {
  ArrowLeftOutlined,
  BookOutlined,
  BulbOutlined,
  CaretDownOutlined,
  CaretRightOutlined,
  ClockCircleOutlined,
  CopyOutlined,
  DatabaseOutlined,
  DoubleLeftOutlined,
  DoubleRightOutlined,
  EditOutlined,
  FileTextOutlined,
  PlusOutlined,
  SaveOutlined,
  SearchOutlined,
  SettingOutlined,
  SoundOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  UserOutlined,
} = host.antdIcons;


type ProjectSection = WorkbenchRouteSection;


function isProjectSection(value: string | null): value is ProjectSection {
  return isWorkbenchRouteSection(value);
}


function currentQuery(): URLSearchParams {
  const query = new URLSearchParams(window.location.search);
  const stored = activeWorkbenchRoute();
  if (stored?.roleView && !query.get("role_view")) {
    query.set("role_view", stored.roleView);
  }
  if (stored && !query.get("novel_id")) {
    query.set("novel_workbench", "1");
    query.set("novel_id", stored.novelId);
    if (stored.documentId) query.set("document_id", stored.documentId);
    if (stored.section) query.set("section", stored.section);
    if (stored.section === "reading" && stored.readingPanel !== "overview") {
      query.set("reading_panel", stored.readingPanel ?? "overview");
    }
  }
  return query;
}


function workbenchUrl(
  novelId: string,
  documentId?: string,
  section: ProjectSection = "chapters",
  readingPanel?: WorkbenchReadingPanel,
): string {
  rememberWorkbenchLocation(novelId, { documentId, section, readingPanel });
  const query = new URLSearchParams({ novel_workbench: "1", novel_id: novelId });
  if (documentId) query.set("document_id", documentId);
  if (section !== "chapters") query.set("section", section);
  if (section === "reading" && readingPanel && readingPanel !== "overview") {
    query.set("reading_panel", readingPanel);
  }
  return `/chat?${query.toString()}`;
}


function replaceWorkbenchUrl(url: string): void {
  replaceWorkbenchHistoryUrl(window.history, window.location.href, url);
}


function firstDocument(novel: NovelRecord): DocumentRecord | undefined {
  return canonicalChapterDocuments(novel)[0]
    ?? canonicalVolumeRecords(novel).flatMap((volume) => volume.documents)
    .find((document) => document.kind === "chapter")
    ?? canonicalVolumeRecords(novel).flatMap((volume) => volume.documents)[0];
}


function chapterNumberFor(novel: NovelRecord, documentId: string): number | undefined {
  return chapterOrdinalFor(novel, documentId);
}


function documentDisplayTitle(novel: NovelRecord, document: DocumentRecord): string {
  if (document.kind !== "chapter") return document.title;
  const chapterNumber = chapterOrdinalFor(novel, document.id);
  return chapterNumber === undefined
    ? document.title
    : formatChapterDisplayTitle(chapterNumber, document.title);
}


function novelCover(novel: NovelRecord, className = "anw-cover"): unknown {
  return h(NovelCoverView, { novel, className, fallbackSrc: defaultNovelCover });
}


function isAbortFailure(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


function delayWithAbort(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(new DOMException("operation aborted", "AbortError"));
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(handle);
      reject(new DOMException("operation aborted", "AbortError"));
    };
    const handle = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}


function failedSegmentRetryIdempotencyKey(): string {
  return `failed-segment-retry:${crypto.randomUUID()}`;
}


function narrationFailureMessage(reason: unknown): string {
  if (reason instanceof ChapterNarrationWorkflowError) return reason.message;
  if (reason instanceof NarrationProductionApiError) {
    if (reason.detail.code === "VOICE_RIGHTS_UNAVAILABLE") {
      return "当前旁白或人物音色没有可用于合成的授权版本，请到书本管理的“朗读”中处理。";
    }
    if (["VERSION_CONFLICT", "STALE_INPUT"].includes(reason.detail.code)) {
      return "正文或朗读设置已经变化，请保存并重新发起朗读。";
    }
    if (reason.detail.code === "STORAGE_UNAVAILABLE") {
      return "朗读生产数据库当前不可用；正文和既有朗读版本均未被修改。";
    }
    return reason.detail.message;
  }
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "章节朗读操作失败；正文和既有朗读版本均未被覆盖。";
}


interface ScriptReviewEditDraft {
  readonly segmentId: string;
  readonly idempotencyKey: string;
  readonly pendingReview: ScriptReviewResource | null;
  readonly speakerChoiceKey: string;
  readonly spokenText: string;
  readonly reason: string;
}


function scriptReviewScope(review: ScriptReviewResource): ScriptReviewVersionScope {
  return {
    novel_id: review.novel_id,
    document_id: review.document_id,
    revision_id: review.revision_id,
    source_content_hash: review.source_content_hash,
    script_id: review.script_id,
    script_version_id: review.script_version_id,
  };
}


function assertWorkflowMatchesReview(
  workflow: NarrationWorkflowResource,
  requestId: string,
  review: ScriptReviewResource,
  options: {
    readonly newerThanRequestVersion?: number;
    readonly requireReview?: boolean;
  } = {},
): void {
  if (
    workflow.request_id !== requestId
    || workflow.script_version_id !== review.script_version_id
    || workflow.source_revision_id !== review.revision_id
    || workflow.source_content_hash !== review.source_content_hash
  ) {
    throw new Error("脚本复核状态与当前章节请求不一致，已拒绝应用。请重新载入章节。");
  }
  if (
    options.newerThanRequestVersion !== undefined
    && workflow.request_version <= options.newerThanRequestVersion
  ) {
    throw new Error("服务端尚未发布修正后的 request_version，已阻止继续操作。");
  }
  if (options.requireReview && workflow.workflow_state !== "review_required") {
    throw new Error("修正后的生产请求未回到人工复核状态，已阻止继续操作。");
  }
}


function secureScriptReviewActionKey(prefix: string): string {
  const value = globalThis.crypto?.randomUUID?.();
  if (!value) throw new Error("浏览器未提供安全随机数，无法安全提交脚本修正。");
  return `${prefix}:${value}`;
}


interface ConflictDetail { current: DocumentRecord; }


interface AssistantTitleInputRef {
  focus?: () => void;
  input?: AssistantTextControl | null;
}


function sectionLabel(section: ProjectSection): string {
  return {
    chapters: "章节",
    outline: "大纲",
    roles: "角色",
    clues: "线索",
    settings: "设定",
    reading: "朗读",
  }[section];
}


function sectionIcon(section: ProjectSection): any {
  return {
    chapters: FileTextOutlined,
    outline: UnorderedListOutlined,
    roles: TeamOutlined,
    clues: BulbOutlined,
    settings: SettingOutlined,
    reading: SoundOutlined,
  }[section];
}


interface NovelWorkbenchProps {
  assistantWorkspaceLayout?: AssistantWorkspaceLayout;
  selectionEditReviewHost?: SelectionEditReviewHostComponent;
}


type ChapterNarrationGateState =
  | { readonly phase: "loading" }
  | { readonly phase: "blocked"; readonly message: string }
  | { readonly phase: "ready"; readonly gate: ChapterNarrationCapabilityGate };


function reconcileChapterNarrationGateState(
  current: ChapterNarrationGateState,
  next: ChapterNarrationGateState,
): ChapterNarrationGateState {
  if (current.phase === "ready" && next.phase === "ready") {
    const retainedGate = retainEquivalentChapterNarrationCapabilityGate(
      current.gate,
      next.gate,
    );
    return retainedGate === current.gate ? current : next;
  }
  if (current.phase === "blocked" && next.phase === "blocked") {
    return current.message === next.message ? current : next;
  }
  if (current.phase === "loading" && next.phase === "loading") return current;
  return next;
}


export function NovelWorkbench(props: NovelWorkbenchProps = {}) {
  const query = currentQuery();
  const SelectionEditReviewHost = props.selectionEditReviewHost;
  const queryNovelId = query.get("novel_id");
  const queryDocumentId = query.get("document_id");
  const requestedSection = query.get("section");
  const initialSection: ProjectSection = isProjectSection(requestedSection)
    ? requestedSection
    : "chapters";
  const requestedReadingPanel = query.get("reading_panel");
  const initialReadingPanel: WorkbenchReadingPanel = initialSection === "reading"
    && isWorkbenchReadingPanel(requestedReadingPanel)
    ? requestedReadingPanel
    : "overview";

  const [novel, setNovel] = React.useState(null as NovelRecord | null);
  const [document, setDocument] = React.useState(null as DocumentRecord | null);
  const [content, setContent] = React.useState("");
  const [section, setSection] = React.useState(initialSection as ProjectSection);
  const [readingPanel, setReadingPanel] = React.useState(initialReadingPanel);
  const [editorOpen, setEditorOpen] = React.useState(Boolean(queryDocumentId));
  const [saveState, setSaveState] = React.useState("正在加载…");
  const [generationModelStatus, setGenerationModelStatus] = React.useState(null as GenerationModelStatus | null);
  const [generationModelStatusError, setGenerationModelStatusError] = React.useState(false);
  const [error, setError] = React.useState("");
  const [conflict, setConflict] = React.useState(null as DocumentRecord | null);
  const [recovery, setRecovery] = React.useState(null as RecoveryDraft | null);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [saveVolumeOpen, setSaveVolumeOpen] = React.useState(false);
  const [titleEditOpen, setTitleEditOpen] = React.useState(false);
  const [titleDraft, setTitleDraft] = React.useState("");
  const [titleSaving, setTitleSaving] = React.useState(false);
  const [chapterOutlineAssistantOpen, setChapterOutlineAssistantOpen] = React.useState(false);
  const [assistantPageScopeVersion, setAssistantPageScopeVersion] = React.useState(0);
  const [manualEditorOpen, setManualEditorOpen] = React.useState(false);
  const [bodyGenerationState, setBodyGenerationState] = React.useState({ active: false, stage: "" });
  const [openChapterWizardSignal, setOpenChapterWizardSignal] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [projectFacts, setProjectFacts] = React.useState([] as StoryFactRecord[]);
  const [projectFactsLoading, setProjectFactsLoading] = React.useState(false);
  const [chapterTreeCollapsed, setChapterTreeCollapsed] = React.useState(false);
  const [chapterTreeSearchOpen, setChapterTreeSearchOpen] = React.useState(false);
  const [chapterTreeQuery, setChapterTreeQuery] = React.useState("");
  const [expandedChapterVolumeIds, setExpandedChapterVolumeIds] = React.useState(null as string[] | null);
  const timerRef = React.useRef(null as ReturnType<typeof setTimeout> | null);
  const documentRef = React.useRef(null as DocumentRecord | null);
  const contentRef = React.useRef("");
  const documentGenerationRef = React.useRef(0);
  const saveInFlightRef = React.useRef(null as Promise<DocumentRecord | null> | null);
  const editorSurfaceParentRef = React.useRef(null as HTMLDivElement | null);
  const editorSurfaceRef = React.useRef(null as ChapterEditorSurfaceHandle | null);
  const editorControlRef = React.useRef(null as AssistantTextControl | null);
  const [editorSurfaceGeneration, setEditorSurfaceGeneration] = React.useState(0);
  const [narrationSnapshot, setNarrationSnapshot] = React.useState(
    null as ChapterNarrationSessionSnapshot | null,
  );
  const [narrationWorkflow, setNarrationWorkflow] = React.useState(
    null as NarrationWorkflowResource | null,
  );
  const [narrationBusy, setNarrationBusy] = React.useState(false);
  const [narrationStatus, setNarrationStatus] = React.useState(
    "正在读取本章朗读状态…",
  );
  const [narrationError, setNarrationError] = React.useState(null as string | null);
  const [narrationPlaybackPreferenceStatus, setNarrationPlaybackPreferenceStatus] = React.useState(
    null as Readonly<{
      state: "idle" | "saving" | "saved" | "conflict" | "error";
      message?: string;
    }> | null,
  );
  const [narrationGateState, setNarrationGateState] = React.useState(
    { phase: "loading" } as ChapterNarrationGateState,
  );
  const [failedSegmentRetrySnapshot, setFailedSegmentRetrySnapshot] = React.useState(
    Object.freeze({
      phase: "idle",
      scope: null,
      projection: null,
      busySegmentIds: Object.freeze([]),
      statusMessage: null,
      errorMessage: null,
    }) as FailedSegmentRetrySnapshot,
  );
  const [failedSegmentRetryFocusId, setFailedSegmentRetryFocusId] = React.useState(
    null as string | null,
  );
  const [scriptReview, setScriptReview] = React.useState(null as ScriptReviewResource | null);
  const [scriptReviewRequestId, setScriptReviewRequestId] = React.useState(null as string | null);
  const [scriptReviewOpen, setScriptReviewOpen] = React.useState(false);
  const [scriptReviewEdit, setScriptReviewEdit] = React.useState(
    null as ScriptReviewEditDraft | null,
  );
  const [scriptReviewEditError, setScriptReviewEditError] = React.useState(
    null as string | null,
  );
  const [scriptReviewCharacterBindings, setScriptReviewCharacterBindings] = React.useState(
    [] as ScriptReviewActiveCharacterBinding[],
  );
  const narrationSessionRef = React.useRef(null as ChapterNarrationSession | null);
  const paragraphGutterControllerRef = React.useRef(null as ParagraphGutterController | null);
  const narrationActionAbortRef = React.useRef(null as AbortController | null);
  const failedSegmentRetryControllerRef = React.useRef(
    null as FailedSegmentRetryController | null,
  );
  const failedSegmentRetryTriggerRef = React.useRef(
    null as { focus(): void } | null,
  );
  const failedSegmentRetryWasSubmittingRef = React.useRef(false);
  const scriptReviewActionAbortRef = React.useRef(null as AbortController | null);
  const scriptReviewTriggerRef = React.useRef(null) as ScriptReviewFocusRef;
  const titleDraftRef = React.useRef("");
  const titleBaselineRef = React.useRef("");
  const titleInputRef = React.useRef(null as AssistantTitleInputRef | null);
  const titleInputNativeRef = React.useRef(null as AssistantTextControl | null);
  const assistantBodyBindingRef = React.useRef(null as ChapterBodyAssistantBinding | null);
  const assistantTitleBindingRef = React.useRef(
    null as ChapterFormAssistantBinding<AssistantFormFieldAdapter> | null,
  );
  const assistantPageLocationFingerprintRef = React.useRef("");
  const chapterGenerateActionRef = React.useRef(null as (() => void) | null);

  const assistantChapterNumber = novel && document?.kind === "chapter"
    && novel.id === document.novel_id
    ? chapterNumberFor(novel, document.id)
    : undefined;
  const assistantPageLocationFingerprint = novel && document?.kind === "chapter"
    && novel.id === document.novel_id && assistantChapterNumber !== undefined
    ? JSON.stringify([
        novel.id,
        novel.title,
        document.id,
        document.volume_id,
        document.title,
        document.draft_version,
        document.content_hash,
        content !== document.content_markdown,
        assistantChapterNumber,
      ])
    : "";

  React.useEffect(() => {
    let mounted = true;
    const controller = createFailedSegmentRetryController({
      getProjection: getFailedNarrationSegments,
      retry: retryFailedNarrationSegments,
      createIdempotencyKey: failedSegmentRetryIdempotencyKey,
      formatFailure: narrationFailureMessage,
      onState: (snapshot) => {
        if (mounted) setFailedSegmentRetrySnapshot(snapshot);
      },
      afterAccepted: async (response, scope, signal) => {
        for (let attempt = 0; attempt < 20; attempt += 1) {
          if (
            signal.aborted
            || documentGenerationRef.current !== scope.documentGeneration
          ) {
            throw new DOMException("failed-segment retry superseded", "AbortError");
          }
          const session = narrationSessionRef.current;
          if (!session) throw new Error("当前章节朗读会话已经失效，请重新载入章节。");
          let result;
          try {
            result = await session.refresh();
          } catch (reason) {
            if (signal.aborted || isAbortFailure(reason)) throw reason;
            if (attempt === 19) throw reason;
            await delayWithAbort(1_500, signal);
            continue;
          }
          if (
            signal.aborted
            || narrationSessionRef.current !== session
            || documentGenerationRef.current !== scope.documentGeneration
          ) {
            throw new DOMException("failed-segment retry superseded", "AbortError");
          }
          if (
            result.status !== "ready"
            || result.bundle.edition.edition_id !== scope.editionId
          ) {
            throw new Error("重试后的朗读版本发生变化，已停止等待且未改写正文。");
          }
          const statusById = new Map(result.bundle.manifest.segments.map((segment: {
            readonly segment_id: string;
            readonly render_status: SegmentRenderStatus;
          }) => (
            [segment.segment_id, segment.render_status] as const
          )));
          if (response.affected_segment_ids.every(
            (segmentId) => statusById.get(segmentId) === "ready",
          )) return;
          if (attempt < 19) await delayWithAbort(1_500, signal);
        }
        throw new Error("重试已受理，但句段音频仍未就绪；可以稍后再次重试。");
      },
    });
    failedSegmentRetryControllerRef.current = controller;
    return () => {
      mounted = false;
      if (failedSegmentRetryControllerRef.current === controller) {
        failedSegmentRetryControllerRef.current = null;
      }
      controller.dispose();
    };
  }, []);

  React.useEffect(() => {
    const submitting = failedSegmentRetrySnapshot.phase === "submitting";
    if (failedSegmentRetryWasSubmittingRef.current && !submitting) {
      failedSegmentRetryTriggerRef.current?.focus();
    }
    failedSegmentRetryWasSubmittingRef.current = submitting;
  }, [failedSegmentRetrySnapshot.phase]);

  const loadDocument = React.useCallback(async (documentId: string) => {
    if (canReuseActiveDocumentLoad({
      requestedDocumentId: documentId,
      activeDocumentId: documentRef.current?.id ?? null,
      activeGeneration: documentGenerationRef.current,
      surfaceLease: editorSurfaceRef.current?.bridge.lease ?? null,
    })) return;
    const generation = documentGenerationRef.current + 1;
    documentGenerationRef.current = generation;
    narrationActionAbortRef.current?.abort("chapter switched");
    narrationActionAbortRef.current = null;
    failedSegmentRetryControllerRef.current?.reset("chapter switched");
    setFailedSegmentRetryFocusId(null);
    scriptReviewActionAbortRef.current?.abort("chapter switched");
    scriptReviewActionAbortRef.current = null;
    narrationSessionRef.current?.dispose();
    narrationSessionRef.current = null;
    paragraphGutterControllerRef.current?.dispose();
    paragraphGutterControllerRef.current = null;
    setNarrationSnapshot(null);
    setNarrationWorkflow(null);
    setNarrationBusy(false);
    setNarrationError(null);
    setNarrationPlaybackPreferenceStatus(null);
    setNarrationStatus("正在读取本章朗读状态…");
    setScriptReview(null);
    setScriptReviewRequestId(null);
    setScriptReviewOpen(false);
    setScriptReviewEdit(null);
    setScriptReviewEditError(null);
    setScriptReviewCharacterBindings([]);
    setBusy(true);
    try {
      const loaded = await apiRequest<DocumentRecord>(`/documents/${documentId}`);
      if (documentGenerationRef.current !== generation) return;
      documentRef.current = loaded;
      contentRef.current = loaded.content_markdown;
      setDocument(loaded);
      setContent(loaded.content_markdown);
      setManualEditorOpen(false);
      setTitleEditOpen(false);
      setChapterOutlineAssistantOpen(false);
      titleDraftRef.current = "";
      titleBaselineRef.current = "";
      titleInputNativeRef.current = null;
      setBodyGenerationState({ active: false, stage: "" });
      setError("");
      setConflict(null);
      setEditorOpen(true);
      setSaveState("已保存");
      workbenchStore.getState().select(loaded.novel_id, loaded.id);
      replaceWorkbenchUrl(workbenchUrl(loaded.novel_id, loaded.id));
      const local = await loadRecoveryDraft(loaded.id);
      if (
        documentGenerationRef.current !== generation
        || documentRef.current?.id !== loaded.id
      ) return;
      if (local && local.contentMarkdown !== loaded.content_markdown) {
        setRecovery(local);
        setSaveState("发现未同步本地草稿");
      } else {
        setRecovery(null);
        await clearRecoveryDraft(loaded.id);
      }
    } catch (reason) {
      if (documentGenerationRef.current === generation) {
        setError(reason instanceof Error ? reason.message : "加载章节失败");
      }
    } finally {
      if (documentGenerationRef.current === generation) setBusy(false);
    }
  }, []);

  const loadNovel = React.useCallback(async (novelId: string) => {
    setBusy(true);
    try {
      const loaded = await apiRequest<NovelRecord>(`/novels/${novelId}`);
      setNovel(loaded);
      setError("");
      if (queryDocumentId) {
        const selected = loaded.tree.flatMap((volume) => volume.documents)
          .find((item) => item.id === queryDocumentId) ?? firstDocument(loaded);
        if (selected) await loadDocument(selected.id);
      } else {
        setEditorOpen(false);
        workbenchStore.getState().select(loaded.id, null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载小说失败");
    } finally {
      setBusy(false);
    }
  }, [loadDocument, queryDocumentId]);

  React.useEffect(() => { if (queryNovelId) void loadNovel(queryNovelId); }, [loadNovel, queryNovelId]);

  React.useEffect(() => {
    const novelId = novel?.id;
    if (!novelId) {
      setNarrationGateState((current: ChapterNarrationGateState) => (
        reconcileChapterNarrationGateState(current, { phase: "loading" })
      ));
      return;
    }
    const controller = new AbortController();
    let refreshInFlight = false;
    setNarrationGateState((current: ChapterNarrationGateState) => (
      reconcileChapterNarrationGateState(current, { phase: "loading" })
    ));
    const refresh = async (): Promise<void> => {
      if (refreshInFlight || controller.signal.aborted) return;
      refreshInFlight = true;
      try {
        const gate = await loadChapterNarrationCapabilityGate(
          novelId,
          getNarrationOverview,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setNarrationGateState((current: ChapterNarrationGateState) => (
            reconcileChapterNarrationGateState(current, { phase: "ready", gate })
          ));
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          const blockedState: ChapterNarrationGateState = {
            phase: "blocked",
            message: reason instanceof Error && reason.message.trim()
              ? reason.message
              : "无法核实章节朗读产品门禁，朗读入口已关闭。",
          };
          setNarrationGateState((current: ChapterNarrationGateState) => (
            reconcileChapterNarrationGateState(current, blockedState)
          ));
        }
      } finally {
        refreshInFlight = false;
      }
    };
    void refresh();
    const refreshTimer = window.setInterval(
      () => { void refresh(); },
      NARRATION_GATE_REFRESH_MILLISECONDS,
    );
    return () => {
      window.clearInterval(refreshTimer);
      controller.abort("novel narration gate changed");
    };
  }, [novel?.id]);

  React.useLayoutEffect(() => {
    // Section and chapter routes share the workbench's own scroll container.
    // Returning from a long chapter must not carry that scroll offset into the
    // next page, otherwise its left rail and main panel start off-screen.
    (window.document.querySelector(".mb-workbench") as HTMLElement | null)?.scrollTo({
      top: 0,
      left: 0,
      behavior: "auto",
    });
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [document?.id, editorOpen, section]);

  React.useEffect(() => {
    if (!queryNovelId) return;
    let active = true;
    const load = () => {
      setGenerationModelStatusError(false);
      void getGenerationModelStatus()
        .then((status) => {
          if (active) setGenerationModelStatus(status);
        })
        .catch(() => {
          if (active) {
            setGenerationModelStatus(null);
            setGenerationModelStatusError(true);
          }
        });
    };
    load();
    window.addEventListener("focus", load);
    return () => {
      active = false;
      window.removeEventListener("focus", load);
    };
  }, [queryNovelId]);

  React.useEffect(() => {
    const volumeId = document?.volume_id ?? null;
    if (!novel || !volumeId) return;
    const allVolumeIds = buildChapterTreeVolumes(novel).map((item: ChapterTreeVolume) => item.key);
    setExpandedChapterVolumeIds((current: string[] | null) => {
      if (current === null || current.includes(volumeId)) return current;
      return [...current.filter((key: string) => allVolumeIds.includes(key)), volumeId];
    });
  }, [document?.id, document?.volume_id, novel?.id]);

  React.useEffect(() => {
    if (!novel || (section !== "roles" && section !== "clues")) return;
    let cancelled = false;
    setProjectFactsLoading(true);
    void apiRequest<StoryFactRecord[]>(`/novels/${novel.id}/story-facts`)
      .then((facts) => { if (!cancelled) setProjectFacts(facts); })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "加载故事资料失败");
      })
      .finally(() => { if (!cancelled) setProjectFactsLoading(false); });
    return () => { cancelled = true; };
  }, [novel?.id, section]);

  const saveNow = React.useCallback(async (markdown: string): Promise<DocumentRecord | null> => {
    const previous = saveInFlightRef.current;
    if (previous) {
      await previous;
      return saveNow(markdown);
    }
    const active = documentRef.current;
    if (!active) return null;
    const generation = documentGenerationRef.current;
    if (active.content_markdown === markdown) {
      setSaveState("已保存");
      return active;
    }
    setSaveState("正在保存…");
    const operation = (async (): Promise<DocumentRecord | null> => {
      try {
        const saved = await apiRequest<DocumentRecord>(`/documents/${active.id}/draft`, {
          method: "PATCH",
          body: JSON.stringify({ expected_draft_version: active.draft_version, content_markdown: markdown }),
        });
        if (
          documentGenerationRef.current !== generation
          || documentRef.current?.id !== active.id
        ) return null;
        const merged = {
          ...saved,
          revisions: saved.revisions ?? active.revisions ?? [],
        };
        documentRef.current = merged;
        setDocument(merged);
        if (contentRef.current === markdown) {
          setSaveState("已保存");
          await clearRecoveryDraft(merged.id);
        } else {
          setSaveState("有新内容待保存");
          timerRef.current = setTimeout(() => {
            if (
              documentGenerationRef.current === generation
              && documentRef.current?.id === active.id
            ) void saveNow(contentRef.current);
          }, 100);
        }
        return merged;
      } catch (reason) {
        if (
          documentGenerationRef.current !== generation
          || documentRef.current?.id !== active.id
        ) return null;
        if (reason instanceof ApiError && reason.status === 409) {
          setConflict((reason.detail as ConflictDetail).current);
          setSaveState("版本冲突，本地稿已保留");
        } else {
          setSaveState("同步失败，本地稿已保留");
        }
        return null;
      }
    })();
    saveInFlightRef.current = operation;
    try {
      return await operation;
    } finally {
      if (saveInFlightRef.current === operation) saveInFlightRef.current = null;
    }
  }, []);

  const saveStableNarrationSource = React.useCallback(async (): Promise<StableChapterNarrationSource> => {
    const active = documentRef.current;
    if (!active || active.kind !== "chapter") {
      throw new Error("当前没有可制作朗读的章节正文。");
    }
    const documentId = active.id;
    const generation = documentGenerationRef.current;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      const target = contentRef.current;
      const saved = await saveNow(target);
      if (
        documentGenerationRef.current !== generation
        || documentRef.current?.id !== documentId
      ) {
        throw new Error("章节已经切换，旧章节朗读操作已取消。");
      }
      if (!saved) {
        throw new Error("正文尚未稳定保存；请先处理保存失败或版本冲突。");
      }
      const current = documentRef.current;
      if (
        current
        && current.id === documentId
        && current.content_markdown === contentRef.current
        && saved.content_markdown === contentRef.current
        && current.content_hash === saved.content_hash
      ) {
        return Object.freeze({
          documentId,
          draftVersion: current.draft_version,
          contentHash: current.content_hash,
        });
      }
    }
    throw new Error("正文仍在持续变化；停止输入后再创建或更新朗读。");
  }, [saveNow]);

  const applyContentChange = React.useCallback((markdown: string) => {
    if (markdown === contentRef.current) return;
    const active = documentRef.current;
    setContent(markdown);
    contentRef.current = markdown;
    assistantBodyBindingRef.current?.notifyFieldChanged();
    setSaveState("本地草稿");
    if (!active) return;
    void saveRecoveryDraft({
      documentId: active.id,
      draftVersion: active.draft_version,
      contentMarkdown: markdown,
      updatedAt: Date.now(),
    });
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => void saveNow(markdown), 600);
  }, [saveNow]);

  const editorShouldMount = editorOpen
    && !bodyGenerationState.active
    && (Boolean(content.trim()) || manualEditorOpen);

  React.useLayoutEffect(() => {
    const active = documentRef.current;
    const parent = editorSurfaceParentRef.current;
    if (!active || !parent || !editorShouldMount) return;
    const generation = documentGenerationRef.current;
    const activeDisplayTitle = novel && novel.id === active.novel_id
      ? documentDisplayTitle(novel, active)
      : active.title;
    const handle = createChapterEditorSurface({
      parent,
      lease: { documentId: active.id, generation },
      initialValue: contentRef.current,
      currentContentHash: active.content_hash,
      ariaLabel: `${activeDisplayTitle}正文编辑器`,
      onDocChanged: (event) => {
        if (
          event.lease.documentId !== documentRef.current?.id
          || event.lease.generation !== documentGenerationRef.current
        ) return;
        try {
          narrationSessionRef.current?.noteWorkingCopyChanged();
        } catch {
          // A stale/disposed narration session cannot change the active editor.
        }
        applyContentChange(event.nextValue);
      },
      isLeaseCurrent: (lease) => (
        lease.documentId === documentRef.current?.id
        && lease.generation === documentGenerationRef.current
      ),
      onFocusChange: (focused) => assistantBodyBindingRef.current?.setFocusedField(focused),
      onAuthorInteraction: (interruption) => {
        try {
          narrationSessionRef.current?.noteAuthorInteraction(interruption);
        } catch {
          // A chapter switch can dispose the session between the DOM event and
          // this callback.  The editor interaction still remains authoritative.
        }
      },
      onParagraphGutterActivate: (paragraphOrdinal) => {
        const result = paragraphGutterControllerRef.current?.requestFromGutter(
          paragraphOrdinal,
        );
        if (!result?.handled || !result.intentResult.accepted) {
          setNarrationError("该段正文已变化，或当前编辑器朗读入口已经失效。");
          return;
        }
        setNarrationError(null);
        setNarrationStatus(`正在从第 ${paragraphOrdinal + 1} 段准备朗读。`);
      },
      onParagraphPlaybackCommand: (command) => {
        const controller = paragraphGutterControllerRef.current;
        const result = command.source === "keyboard"
          ? controller?.requestFromKeyboard(command.event, command.lookup)
          : controller?.requestFromContextMenu(command.lookup);
        if (!result?.handled || !result.intentResult.accepted) {
          setNarrationError("光标所在句段已变化，或当前朗读入口已经失效。");
          return false;
        }
        setNarrationError(null);
        setNarrationStatus("正在从当前段准备朗读。");
        return true;
      },
    });
    editorSurfaceRef.current = handle;
    editorControlRef.current = handle.assistantControl;
    setEditorSurfaceGeneration((current: number) => current + 1);
    return () => {
      if (editorSurfaceRef.current === handle) editorSurfaceRef.current = null;
      if (editorControlRef.current === handle.assistantControl) editorControlRef.current = null;
      handle.dispose();
    };
  }, [applyContentChange, document?.id, document?.title, editorShouldMount, novel]);

  React.useEffect(() => {
    const surface = editorSurfaceRef.current;
    if (!surface || surface.readValue() === content) return;
    surface.setValue(content, "external");
  }, [content, document?.id, editorSurfaceGeneration]);

  React.useEffect(() => {
    const activeNovel = novel;
    const activeDocument = documentRef.current;
    const surface = editorSurfaceRef.current;
    const narrationGate = narrationGateState.phase === "ready"
      ? narrationGateState.gate
      : null;
    if (
      !activeNovel
      || !activeDocument
      || activeDocument.kind !== "chapter"
      || !editorOpen
      || !editorShouldMount
      || !surface
      || !narrationGate?.canLoadSession
      || surface.bridge.lease.documentId !== activeDocument.id
    ) {
      return;
    }
    const generation = surface.bridge.lease.generation;
    const session = createChapterNarrationSession({
      novelId: activeNovel.id,
      documentId: activeDocument.id,
      generation,
      profileId: DEFAULT_PLAYBACK_PROFILE_ID,
      bridge: surface.bridge,
      isGenerationCurrent: (documentId, expectedGeneration) => (
        documentRef.current?.id === documentId
        && documentGenerationRef.current === expectedGeneration
      ),
      onState: (snapshot) => {
        if (
          narrationSessionRef.current !== session
          || documentRef.current?.id !== activeDocument.id
          || documentGenerationRef.current !== generation
        ) return;
        setNarrationSnapshot(snapshot);
        if (snapshot.phase === "loading") {
          setNarrationStatus("正在读取本章朗读版本与句段清单…");
        } else if (snapshot.phase === "no-edition") {
          setNarrationStatus("本章尚未生成朗读。保存正文后可开始智能朗读。");
        } else if (snapshot.phase === "ready" && snapshot.bundle) {
          const edition = snapshot.bundle.edition;
          setNarrationStatus(
            snapshot.workingCopyDiverged
              ? "正文已修改；音频继续播放旧稿，需要时可显式更新朗读。"
              : edition.state === "ready"
              ? "本章朗读已经准备完成。"
              : edition.state === "partial_ready"
                ? `已有 ${edition.ready_segment_count}/${edition.segment_count} 句可播放，其余句段继续制作。`
                : "朗读版本已建立，点击播放会优先准备所选句段。",
          );
          setNarrationError(null);
        } else if (snapshot.phase === "error" && snapshot.error && !isAbortFailure(snapshot.error)) {
          setNarrationError(narrationFailureMessage(snapshot.error));
        }
      },
      onPlaybackPreferenceStatus: (state, message) => {
        if (
          narrationSessionRef.current !== session
          || documentRef.current?.id !== activeDocument.id
          || documentGenerationRef.current !== generation
        ) return;
        setNarrationPlaybackPreferenceStatus({ state, message });
      },
    });
    narrationSessionRef.current?.dispose();
    narrationSessionRef.current = session;
    setNarrationSnapshot(session.readSnapshot());
    void session.load().catch((reason: unknown) => {
      if (
        narrationSessionRef.current === session
        && !isAbortFailure(reason)
      ) setNarrationError(narrationFailureMessage(reason));
    });
    return () => {
      if (narrationSessionRef.current === session) {
        narrationSessionRef.current = null;
      }
      session.dispose();
    };
  }, [
    document?.id,
    editorOpen,
    editorShouldMount,
    editorSurfaceGeneration,
    narrationGateState,
    novel?.id,
  ]);

  React.useEffect(() => {
    if (narrationSnapshot?.phase !== "ready" || !narrationSnapshot.bundle) return;
    if (failedSegmentRetryControllerRef.current?.readSnapshot().phase === "submitting") return;
    const bundle = narrationSnapshot.bundle;
    void failedSegmentRetryControllerRef.current?.load({
      editionId: bundle.edition.edition_id,
      requestId: bundle.edition.request_id,
      documentGeneration: documentGenerationRef.current,
      manifestRevision: bundle.manifest.manifest_revision,
    });
  }, [
    narrationSnapshot?.bundle?.edition.edition_id,
    narrationSnapshot?.bundle?.edition.request_id,
    narrationSnapshot?.bundle?.manifest.manifest_revision,
    narrationSnapshot?.phase,
  ]);

  React.useEffect(() => {
    const session = narrationSessionRef.current;
    const surface = editorSurfaceRef.current;
    const bundle = narrationSnapshot?.bundle;
    paragraphGutterControllerRef.current?.dispose();
    paragraphGutterControllerRef.current = null;
    if (
      !session
      || !surface
      || !bundle
      || !session.player
      || bundle.script.source_content_hash !== bundle.context.working_copy_content_hash
      || surface.bridge.readSnapshot().edition?.editionId !== bundle.edition.edition_id
    ) {
      surface?.setParagraphGutter([]);
      return;
    }
    const controller = createParagraphGutterController({
      bridge: surface.bridge,
      editionId: bundle.edition.edition_id,
      paragraphs: bundle.paragraphs,
      readPlaybackLease: () => {
        const player = session.player;
        if (!player) throw new Error("朗读播放器已经释放。");
        return player.lease;
      },
      isPlaybackLeaseCurrent: (lease) => (
        narrationSessionRef.current === session
        && session.player?.lease.documentId === lease.documentId
        && session.player?.lease.documentGeneration === lease.documentGeneration
        && session.player?.lease.editionId === lease.editionId
        && session.player?.lease.manifestRevision === lease.manifestRevision
      ),
    });
    paragraphGutterControllerRef.current = controller;
    const paragraphByOrdinal = new Map<number, NarrationParagraphDescriptor>(
      bundle.paragraphs.map((paragraph: NarrationParagraphDescriptor) => [
        paragraph.paragraphOrdinal,
        paragraph,
      ]),
    );
    const installed = surface.setParagraphGutter(
      controller.listButtons().map((button) => ({
        sourceStartUtf16: paragraphByOrdinal.get(button.paragraphOrdinal)?.range.startUtf16 ?? -1,
        button,
      })).filter((entry) => entry.sourceStartUtf16 >= 0),
    );
    if (!installed && surface.kind === "codemirror6") {
      controller.dispose();
      paragraphGutterControllerRef.current = null;
      setNarrationError("段落朗读入口没有成功安装，播放器句段跳转仍可使用。");
    }
    return () => {
      if (paragraphGutterControllerRef.current === controller) {
        paragraphGutterControllerRef.current = null;
      }
      controller.dispose();
      if (editorSurfaceRef.current === surface) surface.setParagraphGutter([]);
    };
  }, [editorSurfaceGeneration, narrationSnapshot?.bundle]);

  React.useEffect(() => () => {
    narrationActionAbortRef.current?.abort("workbench disposed");
    narrationActionAbortRef.current = null;
    scriptReviewActionAbortRef.current?.abort("workbench disposed");
    scriptReviewActionAbortRef.current = null;
  }, []);

  React.useEffect(() => {
    if (editorOpen) return;
    scriptReviewActionAbortRef.current?.abort("chapter editor closed");
    scriptReviewActionAbortRef.current = null;
    setScriptReviewOpen(false);
    setScriptReviewEdit(null);
    setScriptReviewEditError(null);
    setScriptReviewCharacterBindings([]);
  }, [editorOpen]);

  React.useEffect(() => {
    const session = narrationSessionRef.current;
    const snapshot = narrationSnapshot;
    const edition = snapshot?.bundle?.edition;
    const playerPhase = snapshot?.playerState?.phase;
    if (
      !session
      || snapshot?.phase !== "ready"
      || !edition
      || !["created", "rendering"].includes(edition.state)
      || ["preparing", "buffering", "playing", "paused"].includes(playerPhase ?? "idle")
    ) return;
    const handle = setTimeout(() => {
      if (narrationSessionRef.current !== session) return;
      void session.refresh().catch((reason: unknown) => {
        if (!isAbortFailure(reason) && narrationSessionRef.current === session) {
          setNarrationError(narrationFailureMessage(reason));
        }
      });
    }, 2_500);
    return () => clearTimeout(handle);
  }, [
    narrationSnapshot?.bundle?.edition.state,
    narrationSnapshot?.bundle?.manifest.manifest_revision,
    narrationSnapshot?.phase,
    narrationSnapshot?.playerState?.phase,
  ]);

  const startNarration = async (intent: "create" | "update") => {
    const activeNovel = novel;
    const activeDocument = documentRef.current;
    const session = narrationSessionRef.current;
    if (narrationGateState.phase !== "ready" || !narrationGateState.gate.canProduce) {
      const reasonCode = narrationGateState.phase === "ready"
        ? narrationGateState.gate.reasonCode
        : "NARRATION_CAPABILITY_UNVERIFIED";
      setNarrationError(`章节智能朗读尚未通过产品门禁（${reasonCode ?? "CAPABILITY_DISABLED"}）。`);
      return;
    }
    if (!activeNovel || !activeDocument || activeDocument.kind !== "chapter" || !session) {
      setNarrationError("章节正文编辑器尚未准备完成，暂时不能创建朗读。");
      return;
    }
    const generation = documentGenerationRef.current;
    failedSegmentRetryControllerRef.current?.reset("new narration request started");
    setFailedSegmentRetryFocusId(null);
    narrationActionAbortRef.current?.abort("superseded narration action");
    scriptReviewActionAbortRef.current?.abort("new narration request started");
    scriptReviewActionAbortRef.current = null;
    const controller = new AbortController();
    narrationActionAbortRef.current = controller;
    setNarrationBusy(true);
    setNarrationError(null);
    setScriptReviewOpen(false);
    setScriptReviewEdit(null);
    setScriptReviewEditError(null);
    setScriptReviewCharacterBindings([]);
    try {
      const liveGate = await loadChapterNarrationCapabilityGate(
        activeNovel.id,
        getNarrationOverview,
        controller.signal,
      );
      if (
        controller.signal.aborted
        || documentRef.current?.id !== activeDocument.id
        || documentGenerationRef.current !== generation
      ) return;
      setNarrationGateState((current: ChapterNarrationGateState) => (
        reconcileChapterNarrationGateState(current, { phase: "ready", gate: liveGate })
      ));
      if (!liveGate.canProduce) {
        setNarrationError(
          `章节智能朗读运行态尚未就绪（${liveGate.reasonCode ?? "CAPABILITY_DISABLED"}）。`,
        );
        return;
      }
      const result = await startChapterNarrationWorkflow({
        novelId: activeNovel.id,
        documentId: activeDocument.id,
        generation,
        intent,
        forceReview: false,
        signal: controller.signal,
        saveStableSource: saveStableNarrationSource,
        isGenerationCurrent: (documentId, expectedGeneration) => (
          documentRef.current?.id === documentId
          && documentGenerationRef.current === expectedGeneration
        ),
        onProgress: (progress: ChapterNarrationWorkflowProgress) => {
          if (
            controller.signal.aborted
            || documentRef.current?.id !== activeDocument.id
            || documentGenerationRef.current !== generation
          ) return;
          setNarrationStatus(progress.message);
          if (progress.workflow) setNarrationWorkflow(progress.workflow);
        },
      });
      if (
        controller.signal.aborted
        || documentRef.current?.id !== activeDocument.id
        || documentGenerationRef.current !== generation
      ) return;
      setNarrationWorkflow(result.workflow);
      if (result.workflow.workflow_state === "review_required") {
        if (!result.workflow.script_version_id) {
          throw new Error("复核请求缺少脚本版本标识，已拒绝继续生产。");
        }
        const review = await getNarrationScriptVersionForEdition(
          result.workflow.script_version_id,
          {
            novel_id: activeNovel.id,
            document_id: activeDocument.id,
            revision_id: result.workflow.source_revision_id,
            source_content_hash: result.workflow.source_content_hash,
          },
          controller.signal,
        );
        if (
          controller.signal.aborted
          || documentRef.current?.id !== activeDocument.id
          || documentGenerationRef.current !== generation
        ) return;
        setScriptReview(review);
        setScriptReviewRequestId(result.workflow.request_id);
        setScriptReviewOpen(true);
        setNarrationStatus(
          review.blocker_count > 0
            ? `人物识别发现 ${review.blocker_count} 个阻塞；音频尚未生成。`
            : "脚本等待作者复核；音频尚未生成。",
        );
        return;
      }
      if (["failed", "cancelled"].includes(result.workflow.workflow_state)) {
        throw new Error(
          result.workflow.workflow_state === "failed"
            ? "朗读制作失败；正文和既有朗读版本均未被覆盖。"
            : "朗读制作已取消。",
        );
      }
      if (!result.workflow.edition_id) {
        throw new Error("朗读请求没有建立 Edition，已拒绝显示可播放状态。");
      }
      setScriptReview(null);
      setScriptReviewRequestId(null);
      await session.load(result.workflow.edition_id);
      if (!controller.signal.aborted) {
        setNarrationStatus("朗读版本已建立；可从任一句或任一段开始准备并播放。");
      }
    } catch (reason) {
      if (!controller.signal.aborted && !isAbortFailure(reason)) {
        setNarrationError(narrationFailureMessage(reason));
      }
    } finally {
      if (narrationActionAbortRef.current === controller) {
        narrationActionAbortRef.current = null;
        setNarrationBusy(false);
      }
    }
  };

  const reportPlaybackResult = (result: ChapterNarrationSessionPlayResult): void => {
    if (result.status === "completed") {
      if (result.decision.kind === "play") {
        setNarrationStatus("正在按句段播放；编辑或手动滚动会暂停自动跟随。");
        setNarrationError(null);
      } else if (result.decision.kind === "blocked") {
        setNarrationError("当前播放窗口存在未完成或失败句段，播放器没有跳过缺口。");
      } else if (result.decision.kind === "error") {
        setNarrationError("句段音频加载失败；未切换到其他朗读版本。");
      }
      return;
    }
    if (result.status === "timeout") {
      setNarrationError("目标句段仍在合成，可稍后再次点击播放。");
    } else if (result.status === "error") {
      setNarrationError(narrationFailureMessage(result.error));
    } else if (result.status === "rejected") {
      setNarrationError("目标句段已变化或不属于当前朗读版本，请更新后重试。");
    }
  };

  const playNarrationOrdinal = (
    ordinal: number,
    source: "command" | "readonly-segment" = "command",
    offsetMs = 0,
  ) => {
    const session = narrationSessionRef.current;
    const segment = session?.readSnapshot().bundle?.script.segments[ordinal];
    if (!session || !segment) {
      setNarrationError("找不到这一句对应的当前朗读片段。");
      return;
    }
    setNarrationError(null);
    void session.playSegment(segment.segment_id, source, offsetMs).then(reportPlaybackResult);
  };

  const toggleNarrationPlayback = () => {
    const session = narrationSessionRef.current;
    if (!session) return;
    const snapshot = session.readSnapshot();
    if (snapshot.playerState?.phase === "playing") {
      session.pause();
      setNarrationStatus("朗读已暂停。");
      return;
    }
    setNarrationError(null);
    if (snapshot.playerState?.phase === "paused") {
      void session.resume().then(reportPlaybackResult);
      return;
    }
    playNarrationOrdinal(
      snapshot.playerState?.currentOrdinal ?? 0,
      "readonly-segment",
      snapshot.playerState?.offsetMs ?? 0,
    );
  };

  const closeScriptReview = (): void => {
    const action = scriptReviewActionAbortRef.current;
    if (action) {
      action.abort("script review closed");
      scriptReviewActionAbortRef.current = null;
      setNarrationBusy(false);
    }
    setScriptReviewOpen(false);
    setScriptReviewEdit(null);
    setScriptReviewEditError(null);
    setScriptReviewCharacterBindings([]);
  };

  const openNarrationReview = () => {
    const session = narrationSessionRef.current;
    const bundle = session?.readSnapshot().bundle;
    if (!session || !bundle) return;
    const generation = documentGenerationRef.current;
    const requestId = bundle.edition.request_id;
    scriptReviewActionAbortRef.current?.abort("review state refresh superseded");
    const controller = new AbortController();
    scriptReviewActionAbortRef.current = controller;
    setNarrationBusy(true);
    setNarrationError(null);
    void getNarrationWorkflow(requestId, controller.signal).then((workflow) => {
      assertWorkflowMatchesReview(workflow, requestId, bundle.script);
      if (
        controller.signal.aborted
        || narrationSessionRef.current !== session
        || documentRef.current?.id !== bundle.context.document_id
        || documentGenerationRef.current !== generation
      ) return;
      setNarrationWorkflow(workflow);
      setScriptReview(bundle.script);
      setScriptReviewRequestId(requestId);
      setScriptReviewEdit(null);
      setScriptReviewEditError(null);
      setScriptReviewCharacterBindings([]);
      setScriptReviewOpen(true);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted && !isAbortFailure(reason)) {
        setNarrationError(narrationFailureMessage(reason));
      }
    }).finally(() => {
      if (scriptReviewActionAbortRef.current === controller) {
        scriptReviewActionAbortRef.current = null;
        setNarrationBusy(false);
      }
    });
  };

  const synchronizeChangedScriptReview = (nextReview: ScriptReviewResource): void => {
    const activeDocument = documentRef.current;
    const session = narrationSessionRef.current;
    const requestId = scriptReviewRequestId;
    const currentWorkflow = narrationWorkflow;
    if (
      !activeDocument
      || !session
      || !requestId
      || !currentWorkflow
      || currentWorkflow.request_id !== requestId
    ) {
      setNarrationError("脚本复核请求状态已经失效，请重新载入章节。");
      return;
    }
    const generation = documentGenerationRef.current;
    scriptReviewActionAbortRef.current?.abort("script review action superseded");
    const controller = new AbortController();
    scriptReviewActionAbortRef.current = controller;
    setNarrationBusy(true);
    setNarrationError(null);
    setScriptReviewOpen(false);
    setScriptReviewEdit(null);
    setScriptReviewEditError(null);
    setScriptReviewCharacterBindings([]);
    if (nextReview.state === "approved") {
      setScriptReview(nextReview);
      setNarrationStatus("脚本已由作者冻结；正在等待服务端建立真实朗读版本…");
      void continueApprovedScriptProduction({
        requestId,
        approvedReview: nextReview,
        dependencies: { getWorkflow: getNarrationWorkflow },
        signal: controller.signal,
        onWorkflow: (workflow) => {
          if (
            !controller.signal.aborted
            && narrationSessionRef.current === session
            && documentRef.current?.id === activeDocument.id
            && documentGenerationRef.current === generation
          ) {
            setNarrationWorkflow(workflow);
            setNarrationStatus(
              workflow.workflow_state === "queued"
                ? "脚本已冻结，音频任务已经排队。"
                : workflow.workflow_state === "rendering"
                  ? "脚本已冻结，正在合成句段音频。"
                  : "脚本已冻结，正在确认可播放朗读版本。",
            );
          }
        },
      }).then(async (result) => {
        if (
          controller.signal.aborted
          || narrationSessionRef.current !== session
          || documentRef.current?.id !== activeDocument.id
          || documentGenerationRef.current !== generation
        ) return;
        setNarrationWorkflow(result.workflow);
        await session.load(result.editionId);
        if (
          controller.signal.aborted
          || narrationSessionRef.current !== session
          || documentRef.current?.id !== activeDocument.id
          || documentGenerationRef.current !== generation
        ) return;
        setScriptReview(null);
        setScriptReviewRequestId(null);
        setScriptReviewOpen(false);
        setNarrationStatus("作者批准已生效，真实朗读版本已经建立并载入。");
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && !isAbortFailure(reason)) {
          setNarrationError(narrationFailureMessage(reason));
          setNarrationStatus("脚本已经冻结，但服务端尚未确认可用的真实朗读版本。");
          setScriptReviewOpen(true);
        }
      }).finally(() => {
        if (scriptReviewActionAbortRef.current === controller) {
          scriptReviewActionAbortRef.current = null;
          setNarrationBusy(false);
        }
      });
      return;
    }
    setNarrationStatus("脚本已生成新版本，正在同步服务端请求版本…");
    void getNarrationWorkflow(requestId, controller.signal).then((workflow) => {
      assertWorkflowMatchesReview(workflow, requestId, nextReview, {
        newerThanRequestVersion: currentWorkflow.request_version,
        requireReview: true,
      });
      if (
        controller.signal.aborted
        || narrationSessionRef.current !== session
        || documentRef.current?.id !== activeDocument.id
        || documentGenerationRef.current !== generation
      ) return;
      setNarrationWorkflow(workflow);
      setScriptReview(nextReview);
      setScriptReviewRequestId(requestId);
      setScriptReviewOpen(true);
      setNarrationStatus(`脚本仍有 ${nextReview.blocker_count} 个阻塞。`);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted && !isAbortFailure(reason)) {
        setNarrationError(narrationFailureMessage(reason));
        setNarrationStatus("新脚本已经返回，但 request_version 尚未同步；已禁止继续操作。");
      }
    }).finally(() => {
      if (scriptReviewActionAbortRef.current === controller) {
        scriptReviewActionAbortRef.current = null;
        setNarrationBusy(false);
      }
    });
  };

  const openScriptReviewSegmentEdit = (segment: ScriptReviewSegmentResource): void => {
    const activeNovel = novel;
    const activeDocument = documentRef.current;
    const session = narrationSessionRef.current;
    const review = scriptReview;
    const workflow = narrationWorkflow;
    const requestId = scriptReviewRequestId;
    if (
      !activeNovel
      || !activeDocument
      || !session
      || !review
      || !workflow
      || !requestId
      || workflow.request_id !== requestId
      || workflow.script_version_id !== review.script_version_id
      || workflow.workflow_state !== "review_required"
      || !review.allowed_actions.includes("edit_segment")
      || !segment.editable
      || !review.segments.some((item: ScriptReviewSegmentResource) => (
        item.segment_id === segment.segment_id && item.local_hash === segment.local_hash
      ))
    ) {
      setNarrationError("当前脚本或请求版本不允许修正该句段。");
      return;
    }
    try {
      assertWorkflowMatchesReview(workflow, requestId, review, { requireReview: true });
    } catch (reason) {
      setNarrationError(narrationFailureMessage(reason));
      return;
    }
    const generation = documentGenerationRef.current;
    scriptReviewActionAbortRef.current?.abort("speaker choices refresh superseded");
    const controller = new AbortController();
    scriptReviewActionAbortRef.current = controller;
    setNarrationBusy(true);
    setNarrationError(null);
    setNarrationStatus("正在读取活跃角色的当前音色绑定…");
    setScriptReviewOpen(false);
    void Promise.all([
      apiRequest<NovelCharacterRecord[]>(`/novels/${activeNovel.id}/characters`, {
        signal: controller.signal,
      }),
      listCharacterVoiceBindings(activeNovel.id, controller.signal),
      getNarrationWorkflow(requestId, controller.signal),
    ]).then(([characters, bindingList, refreshedWorkflow]) => {
      if (bindingList.novel_id !== activeNovel.id) {
        throw new Error("人物音色绑定返回了其他作品的数据，已拒绝显示。");
      }
      assertWorkflowMatchesReview(refreshedWorkflow, requestId, review, { requireReview: true });
      if (refreshedWorkflow.request_version < workflow.request_version) {
        throw new Error("脚本复核 request_version 发生倒退，已拒绝显示修正弹窗。");
      }
      const currentBindings = new Map(
        bindingList.items.filter((binding) => (
          binding.novel_id === activeNovel.id
          && ["dedicated", "inherited"].includes(binding.binding_policy)
          && binding.profile_id !== null
          && binding.version_id !== null
        )).map((binding) => [binding.character_id, binding] as const),
      );
      const activeBindings = characters.filter((character: NovelCharacterRecord) => (
        character.novel_id === activeNovel.id
        && character.lifecycle_state === "active"
        && currentBindings.has(character.id)
      )).map((character: NovelCharacterRecord) => Object.freeze({
        characterId: character.id,
        speakerLabel: character.name,
      }));
      const choices = buildScriptReviewSpeakerChoices(review, activeBindings);
      const currentChoice = choices.find((choice) => (
        (segment.speaker_kind === "narrator" && choice.speakerKind === "narrator")
        || (
          segment.speaker_kind === "character"
          && choice.characterId !== null
          && choice.characterId === segment.character_id
        )
        || (
          segment.speaker_kind === "anonymous"
          && choice.anonymousSpeakerId !== null
          && choice.anonymousSpeakerId === segment.anonymous_speaker_id
        )
      )) ?? choices[0];
      if (
        controller.signal.aborted
        || narrationSessionRef.current !== session
        || documentRef.current?.id !== activeDocument.id
        || documentGenerationRef.current !== generation
      ) return;
      setNarrationWorkflow(refreshedWorkflow);
      setScriptReviewCharacterBindings(activeBindings);
      setScriptReviewEdit({
        segmentId: segment.segment_id,
        idempotencyKey: secureScriptReviewActionKey("script-segment-patch"),
        pendingReview: null,
        speakerChoiceKey: currentChoice.key,
        spokenText: segment.spoken_text,
        reason: "作者人工确认句段说话人与朗读文本",
      });
      setScriptReviewEditError(null);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted && !isAbortFailure(reason)) {
        setNarrationError(narrationFailureMessage(reason));
        setScriptReviewOpen(true);
      }
    }).finally(() => {
      if (scriptReviewActionAbortRef.current === controller) {
        scriptReviewActionAbortRef.current = null;
        setNarrationBusy(false);
      }
    });
  };

  const submitScriptReviewSegmentEdit = (): void => {
    const draft = scriptReviewEdit;
    const review = scriptReview;
    const workflow = narrationWorkflow;
    const requestId = scriptReviewRequestId;
    const activeDocument = documentRef.current;
    const session = narrationSessionRef.current;
    if (!draft || !review || !workflow || !requestId || !activeDocument || !session) return;
    const segment = review.segments.find(
      (item: ScriptReviewSegmentResource) => item.segment_id === draft.segmentId,
    );
    const choice = buildScriptReviewSpeakerChoices(review, scriptReviewCharacterBindings).find(
      (item: ScriptReviewSpeakerChoice) => item.key === draft.speakerChoiceKey,
    );
    if (!segment || !choice || !draft.spokenText.trim() || !draft.reason.trim()) {
      setScriptReviewEditError("请选择可验证的说话人，并填写朗读文本和修正原因。");
      return;
    }
    try {
      assertWorkflowMatchesReview(workflow, requestId, review, { requireReview: true });
    } catch (reason) {
      setScriptReviewEditError(narrationFailureMessage(reason));
      return;
    }
    const generation = documentGenerationRef.current;
    scriptReviewActionAbortRef.current?.abort("segment correction superseded");
    const controller = new AbortController();
    scriptReviewActionAbortRef.current = controller;
    let patchApplied = draft.pendingReview !== null;
    setNarrationBusy(true);
    setNarrationError(null);
    setScriptReviewEditError(null);
    setScriptReviewOpen(false);
    const operation = draft.pendingReview === null
      ? patchNarrationScriptSegment(
          review.script_version_id,
          segment.segment_id,
          {
            expected_request_version: workflow.request_version,
            expected_version_number: review.version_number,
            expected_immutable_hash: review.immutable_hash,
            expected_local_hash: segment.local_hash,
            request_id: requestId,
            speaker_kind: choice.speakerKind,
            speaker_label: choice.speakerLabel,
            character_id: choice.characterId,
            anonymous_speaker_id: choice.anonymousSpeakerId,
            group_key: null,
            spoken_text: draft.spokenText.trim(),
            reason: draft.reason.trim(),
          },
          scriptReviewScope(review),
          draft.idempotencyKey,
          controller.signal,
        )
      : Promise.resolve(draft.pendingReview);
    void operation.then(async (nextReview) => {
      patchApplied = true;
      setScriptReviewEdit((current: ScriptReviewEditDraft | null) => (
        current?.idempotencyKey === draft.idempotencyKey
          ? { ...current, pendingReview: nextReview }
          : current
      ));
      const nextWorkflow = await getNarrationWorkflow(requestId, controller.signal);
      assertWorkflowMatchesReview(nextWorkflow, requestId, nextReview, {
        newerThanRequestVersion: workflow.request_version,
        requireReview: true,
      });
      if (
        controller.signal.aborted
        || narrationSessionRef.current !== session
        || documentRef.current?.id !== activeDocument.id
        || documentGenerationRef.current !== generation
      ) return;
      setNarrationWorkflow(nextWorkflow);
      setScriptReview(nextReview);
      setScriptReviewRequestId(requestId);
      setScriptReviewEdit(null);
      setScriptReviewEditError(null);
      setScriptReviewCharacterBindings([]);
      setScriptReviewOpen(true);
      setNarrationStatus(`句段修正已保存；脚本仍有 ${nextReview.blocker_count} 个阻塞。`);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted && !isAbortFailure(reason)) {
        const message = narrationFailureMessage(reason);
        setScriptReviewEditError(
          patchApplied
            ? `修正已提交，但请求版本同步失败：${message}。请重试同步，期间不能继续批准或重新分析。`
            : message,
        );
        if (!patchApplied) setScriptReviewOpen(true);
      }
    }).finally(() => {
      if (scriptReviewActionAbortRef.current === controller) {
        scriptReviewActionAbortRef.current = null;
        setNarrationBusy(false);
      }
    });
  };

  const closeScriptReviewSegmentEdit = (): void => {
    const uncertain = scriptReviewActionAbortRef.current !== null
      || (scriptReviewEdit !== null && scriptReviewEdit.pendingReview !== null);
    scriptReviewActionAbortRef.current?.abort("segment correction dialog closed");
    scriptReviewActionAbortRef.current = null;
    setNarrationBusy(false);
    setScriptReviewEdit(null);
    setScriptReviewEditError(null);
    setScriptReviewCharacterBindings([]);
    if (uncertain) {
      setScriptReviewOpen(false);
      setNarrationError("句段修正状态尚未完成同步，请重新载入章节后再继续复核。");
    } else {
      setScriptReviewOpen(true);
    }
  };

  const selectNarrationEdition = (editionId: string) => {
    const session = narrationSessionRef.current;
    const snapshot = session?.readSnapshot();
    const context = snapshot?.bundle?.context
      ?? (snapshot?.loadResult?.status === "no-edition" ? snapshot.loadResult.context : null);
    const target = context?.edition_history.editions.find(
      (item: EditionHistoryItem) => item.edition_id === editionId,
    );
    if (!session || !context || !target) {
      setNarrationError("朗读版本列表已经变化，请重新加载本章。");
      return;
    }
    if (target.is_current) {
      failedSegmentRetryControllerRef.current?.reset("Edition selection changed");
      setFailedSegmentRetryFocusId(null);
      void session.load(target.edition_id).catch((reason: unknown) => {
        if (!isAbortFailure(reason)) setNarrationError(narrationFailureMessage(reason));
      });
      return;
    }
    if (!target.playable || !target.switch_allowed) {
      setNarrationError("该朗读版本尚未形成合法连续播放起点，暂时不能设为当前版本。");
      return;
    }
    Modal.confirm({
      className: "anw-modal anw-narration-edition-confirm",
      title: "切换本章朗读版本？",
      width: 620,
      content: h(
        "div",
        { className: "anw-narration-edition-confirm__copy" },
        h("p", null, `来源 revision：${target.source_revision_id}`),
        h("p", null, `来源哈希：${target.source_content_hash}`),
        h("p", null, target.source_content_hash === context.working_copy_content_hash
          ? "该版本对应当前正文。"
          : "该版本对应不可变旧稿，播放器会明确显示“旧稿朗读”。"),
      ),
      okText: "确认切换",
      cancelText: "取消",
      onOk: async () => {
        const generation = documentGenerationRef.current;
        const controller = new AbortController();
        failedSegmentRetryControllerRef.current?.reset("Edition selection changed");
        setFailedSegmentRetryFocusId(null);
        narrationActionAbortRef.current?.abort("Edition switch superseded");
        narrationActionAbortRef.current = controller;
        setNarrationBusy(true);
        setNarrationError(null);
        try {
          await switchNarrationEdition(
            context.document_id,
            {
              target_edition_id: target.edition_id,
              expected_version: context.pointer_version,
              switch_mode: "next_playback",
              start_segment_id: null,
              playback_rate_millis: Math.round((snapshot?.playerState?.rate ?? 1) * 1_000),
              confirmed: true,
            },
            controller.signal,
          );
          if (
            controller.signal.aborted
            || documentRef.current?.id !== context.document_id
            || documentGenerationRef.current !== generation
          ) return;
          await session.load(target.edition_id);
          setNarrationStatus("已切换本章朗读版本；下次播放从该版本的合法起点开始。");
        } catch (reason) {
          if (!controller.signal.aborted && !isAbortFailure(reason)) {
            setNarrationError(narrationFailureMessage(reason));
          }
          throw reason;
        } finally {
          if (narrationActionAbortRef.current === controller) {
            narrationActionAbortRef.current = null;
            setNarrationBusy(false);
          }
        }
      },
    });
  };

  const retryFailedNarrationSegment = (segmentId: string) => {
    setFailedSegmentRetryFocusId(segmentId);
    void failedSegmentRetryControllerRef.current?.retrySegment(segmentId);
  };

  const refreshNovel = async (): Promise<NovelRecord | null> => {
    if (!novel) return null;
    const loaded = await apiRequest<NovelRecord>(`/novels/${novel.id}`);
    setNovel(loaded);
    return loaded;
  };

  const selectDocument = (documentId: string) => {
    const active = documentRef.current;
    if (active && contentRef.current !== active.content_markdown) void saveNow(contentRef.current);
    void loadDocument(documentId);
  };

  const navigateToChapter = async (documentId: string) => {
    const active = documentRef.current;
    if (active?.id === documentId) return;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (active && contentRef.current !== active.content_markdown) {
      const saved = await saveNow(contentRef.current);
      if (!saved) return;
    }
    await loadDocument(documentId);
  };

  const createChapter = async () => {
    if (!novel) return;
    const realVolumes = canonicalVolumeRecords(novel)
      .filter((volume: VolumeRecord) => volume.id !== null);
    const targetVolumeId = realVolumes[realVolumes.length - 1]?.id;
    if (!targetVolumeId) {
      const message = "请先新建分卷，再新建章节。";
      setError(message);
      Modal.warning({ title: "暂时不能新建章节", content: message, okText: "知道了" });
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await apiRequest<DocumentRecord>(`/novels/${novel.id}/documents`, {
        method: "POST",
        body: JSON.stringify({
          title: "",
          kind: "chapter",
          volume_id: targetVolumeId,
        }),
      });
      await refreshNovel();
      await loadDocument(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新建章节失败");
    } finally {
      setBusy(false);
    }
  };

  const createVolume = async () => {
    if (!novel) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/novels/${novel.id}/volumes`, {
        method: "POST",
        body: JSON.stringify({ title: "" }),
      });
      await refreshNovel();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新增分卷失败");
    } finally {
      setBusy(false);
    }
  };

  const createStructuredDocument = async (kind: "outline" | "setting") => {
    if (!novel) return;
    const title = kind === "outline" ? "故事大纲" : "世界设定";
    const created = await apiRequest<DocumentRecord>(`/novels/${novel.id}/documents`, {
      method: "POST",
      body: JSON.stringify({ title, kind, volume_id: null }),
    });
    await refreshNovel();
    await loadDocument(created.id);
  };

  const checkpoint = async () => {
    const saved = await saveNow(contentRef.current);
    if (!saved) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ document: DocumentRecord }>(`/documents/${saved.id}/checkpoints`, {
        method: "POST",
        body: JSON.stringify({ expected_draft_version: saved.draft_version }),
      });
      documentRef.current = result.document;
      setDocument(result.document);
      setSaveState("正式版本已建立");
    } finally {
      setBusy(false);
    }
  };

  const saveChapterToVolume = async (volumeId: string | null, continueWriting = false) => {
    if (!novel || !document) return;
    const saved = await saveNow(contentRef.current);
    if (!saved) return;
    setBusy(true);
    try {
      const chapterIds = canonicalChapterDocuments(novel)
        .map((item: DocumentRecord) => item.id);
      await apiRequest(`/novels/${novel.id}/chapters/reorder`, {
        method: "POST",
        body: JSON.stringify({
          ordered_document_ids: chapterIds,
          volume_by_document: { [saved.id]: volumeId },
        }),
      });
      const result = await apiRequest<{ document: DocumentRecord }>(`/documents/${saved.id}/checkpoints`, {
        method: "POST",
        body: JSON.stringify({ expected_draft_version: saved.draft_version }),
      });
      documentRef.current = result.document;
      setDocument(result.document);
      setSaveVolumeOpen(false);
      setSaveState("已保存");
      await refreshNovel();
      if (continueWriting) {
        setEditorOpen(false);
        setSection("chapters");
        setOpenChapterWizardSignal((current: number) => current + 1);
        replaceWorkbenchUrl(workbenchUrl(novel.id));
      } else {
        Modal.success({ title: "提示", content: "保存成功", okText: "确定" });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存章节失败");
    } finally {
      setBusy(false);
    }
  };

  const confirmSaveChapterToVolume = (volumeId: string | null, continueWriting = false) => {
    if (continueWriting) {
      const hasValidVolume = Boolean(
        volumeId
        && novel
        && canonicalVolumeRecords(novel).some((volume) => volume.id === volumeId),
      );
      if (!hasValidVolume) {
        const message = novel && canonicalVolumeRecords(novel).some((volume) => volume.id !== null)
          ? "当前章节尚未分卷，请先选择一个分卷保存，再新建下一章。"
          : "请先新建分卷，再新建下一章。";
        setError(message);
        Modal.warning({ title: "暂时不能新建下一章", content: message, okText: "知道了" });
        return;
      }
    }
    setSaveVolumeOpen(false);
    Modal.confirm({
      className: "anw-modal anw-save-confirm",
      title: "确认",
      width: 520,
      centered: true,
      content: h("div", { className: "anw-save-confirm-copy" },
        h("strong", null, "💡 保存提示："),
        h("p", null, "1. 角色记忆将同步更新到角色表"),
        h("p", null, "2. 退场的角色将自动删除其记忆"),
        h("p", null, "3. 保存后将同步最新进展，请确认内容无误。"),
        h("b", null, "确定要保存章节内容吗？"),
      ),
      okText: "确定",
      cancelText: "取消",
      onOk: () => saveChapterToVolume(volumeId, continueWriting),
    });
  };

  const restore = async (revisionId: string, preview: RestorePreviewRecord) => {
    const active = documentRef.current;
    if (!active) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ document: DocumentRecord }>(
        `/documents/${active.id}/revisions/${revisionId}/restore`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_draft_version: preview.expected_draft_version,
            expected_fact_plan_hash: preview.fact_plan_hash,
          }),
        },
      );
      documentRef.current = result.document;
      contentRef.current = result.document.content_markdown;
      setDocument(result.document);
      setContent(result.document.content_markdown);
      setHistoryOpen(false);
      setSaveState(
        preview.will_reactivate.length
          ? `已恢复正文，并重新启用 ${preview.will_reactivate.length} 条故事资料`
          : "已恢复为新版本",
      );
      await clearRecoveryDraft(result.document.id);
    } catch (reason) {
      if (
        reason instanceof ApiError
        && reason.status === 409
        && (reason.detail as { type?: string })?.type === "restoration_plan_conflict"
      ) {
        setError("恢复预览期间故事资料发生变化，请重新预览后再确认。");
      } else {
        setError(reason instanceof Error ? reason.message : "恢复失败");
      }
    } finally {
      setBusy(false);
    }
  };

  const confirmRestore = async (revision: DocumentRecord["revisions"][number]) => {
    const saved = await saveNow(contentRef.current);
    if (!saved) return;
    setBusy(true);
    let preview: RestorePreviewRecord;
    try {
      preview = await apiRequest<RestorePreviewRecord>(
        `/documents/${saved.id}/revisions/${revision.id}/restore-preview`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法建立恢复预览");
      setBusy(false);
      return;
    }
    setBusy(false);
    Modal.confirm({
      className: "anw-modal",
      title: `恢复版本 ${revision.revision_number}？`,
      width: 680,
      content: h(
        "div",
        { className: "anw-restore-confirm" },
        h("p", null, `将以“${revisionSourceLabel(revision.source)}”版本建立一份新的当前版本。`),
        h("p", null, `目标正文 ${revision.visible_character_count} 字；当前版本和后续版本仍会保留。`),
        h(
          "div",
          { className: "anw-restore-impact", role: "status", "aria-label": "故事资料恢复影响" },
          h("strong", null, "故事资料同步"),
          h(
            "ul",
            null,
            h("li", null, `退出当前故事：${preview.will_deactivate.length} 条`),
            h("li", null, `随目标版本重新启用：${preview.will_reactivate.length} 条`),
            h("li", null, `保持有效：${preview.will_remain_current.length} 条`),
            h("li", null, `可复用采用批次：${preview.available_commit_batches.length} 个`),
          ),
        ),
        preview.working_copy_dirty
          ? h(Alert, {
              type: "warning",
              showIcon: true,
              message: "当前工作稿尚未建立正式版本；确认恢复时会先自动建立一份“恢复前保护版本”。",
            })
          : null,
        h(
          "details",
          { className: "anw-restore-diff" },
          h("summary", null, preview.unified_diff ? "查看正文差异" : "正文内容与当前版本相同"),
          preview.unified_diff ? h("pre", null, preview.unified_diff) : null,
        ),
      ),
      okText: "恢复并同步故事资料",
      cancelText: "取消",
      okButtonProps: { className: "anw-primary-button" },
      onOk: () => restore(revision.id, preview),
    });
  };

  const copyContext = async () => {
    if (!novel || !document) return;
    const currentDocumentTitle = documentDisplayTitle(novel, document);
    await navigator.clipboard.writeText([
      `当前小说：${novel.title}`,
      `novel_id: ${novel.id}`,
      `当前文档：${currentDocumentTitle}`,
      `document_id: ${document.id}`,
      "请按需调用 novel_get_context、novel_get_document 或 novel_search；不要修改正文。",
    ].join("\n"));
    setSaveState("AI 上下文已复制");
  };

  const loadServerConflict = () => {
    if (!conflict) return;
    documentRef.current = conflict;
    contentRef.current = conflict.content_markdown;
    setDocument(conflict);
    setContent(conflict.content_markdown);
    setConflict(null);
    setSaveState("已载入服务器版本；本地恢复稿仍保留");
  };

  const recoverLocal = () => {
    if (!recovery) return;
    setContent(recovery.contentMarkdown);
    contentRef.current = recovery.contentMarkdown;
    setRecovery(null);
    setSaveState("已恢复本地草稿，正在同步");
    void saveNow(recovery.contentMarkdown);
  };

  const applyWorkflowDocument = (updated: DocumentRecord, status: string) => {
    documentRef.current = updated;
    contentRef.current = updated.content_markdown;
    setDocument(updated);
    setContent(updated.content_markdown);
    setError("");
    setConflict(null);
    setRecovery(null);
    setSaveState(status);
    void clearRecoveryDraft(updated.id);
  };

  const openTitleEditor = () => {
    const active = documentRef.current;
    if (!active) return;
    const currentTitle = active.kind === "chapter" ? chapterTitleName(active.title) : active.title.trim();
    titleDraftRef.current = currentTitle;
    titleBaselineRef.current = currentTitle;
    titleInputNativeRef.current = null;
    setTitleDraft(currentTitle);
    setTitleEditOpen(true);
  };

  const updateTitleDraft = (value: string) => {
    const nextTitle = (
      documentRef.current?.kind === "chapter" ? chapterTitleName(value) : value
    ).slice(0, 20);
    titleDraftRef.current = nextTitle;
    setTitleDraft(nextTitle);
    assistantTitleBindingRef.current?.notifyFieldChanged(CHAPTER_TITLE_FIELD_ID);
  };

  const renameDocument = async () => {
    const active = documentRef.current;
    const nextTitle = titleDraftRef.current.trim();
    if (!novel || !active || (active.kind !== "chapter" && !nextTitle)) return;
    const storedTitle = active.kind === "chapter" ? chapterTitleName(nextTitle) : nextTitle;
    setTitleSaving(true);
    setError("");
    try {
      let current = active;
      if (contentRef.current !== active.content_markdown) {
        const saved = await saveNow(contentRef.current);
        if (!saved) return;
        current = saved;
      }
      const updated = await apiRequest<DocumentRecord>(`/novels/${novel.id}/documents/${current.id}`, {
        method: "PUT",
        body: JSON.stringify({ expected_version: current.version, title: storedTitle }),
      });
      const merged = {
        ...updated,
        revisions: updated.revisions ?? current.revisions ?? [],
      };
      documentRef.current = merged;
      setDocument(merged);
      setTitleEditOpen(false);
      setSaveState(active.kind === "chapter" ? "章节名称已修改" : "文档名称已修改");
      try {
        await refreshNovel();
      } catch {
        setError("名称已经保存，但作品列表暂未刷新；重新进入页面即可看到最新名称。");
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        const current = (reason.detail as ConflictDetail)?.current;
        if (current) {
          const currentTitle = current.kind === "chapter" ? chapterTitleName(current.title) : current.title;
          documentRef.current = current;
          setDocument(current);
          titleDraftRef.current = currentTitle;
          titleBaselineRef.current = currentTitle;
          setTitleDraft(currentTitle);
          assistantTitleBindingRef.current?.notifyFieldChanged(CHAPTER_TITLE_FIELD_ID);
        }
        setError("章节名称已在其他位置更新，请确认最新名称后重新保存。");
      } else {
        setError(reason instanceof Error ? reason.message : "修改章节名称失败");
      }
    } finally {
      setTitleSaving(false);
    }
  };

  React.useEffect(() => {
    if (!editorOpen || !novel || !document || document.kind !== "chapter") {
      assistantPageLocationFingerprintRef.current = "";
      return;
    }
    if (novel.id !== document.novel_id || assistantChapterNumber === undefined) {
      assistantPageLocationFingerprintRef.current = "";
      return;
    }
    const binding = mountChapterBodyAssistantScope({
      location: {
        novel,
        document,
        chapterNumber: assistantChapterNumber,
        dirty: contentRef.current !== document.content_markdown,
      },
      getValue: () => contentRef.current,
      getDirty: () => {
        const active = documentRef.current;
        return Boolean(active && contentRef.current !== active.content_markdown);
      },
      getSelection: () => readAssistantTextSelection(
        editorControlRef.current,
        contentRef.current,
      ),
      applyEditorContent: (nextValue) => {
        const active = documentRef.current;
        if (!active || active.id !== document.id) {
          throw new Error("章节已切换，不能应用到旧正文");
        }
        const surface = editorSurfaceRef.current;
        if (!surface || !surface.setValue(nextValue, "ai-apply")) {
          applyContentChange(nextValue);
        }
        setSaveState("已应用，正在自动保存");
      },
      scheduleAutosave: (nextValue) => {
        const active = documentRef.current;
        if (!active || active.id !== document.id) return;
        if (timerRef.current) clearTimeout(timerRef.current);
        setSaveState("已应用，正在自动保存");
        timerRef.current = setTimeout(() => void saveNow(nextValue), 600);
      },
      restoreSelection: (range) => restoreAssistantTextSelection(
        editorControlRef.current,
        range,
      ),
      focus: () => editorControlRef.current?.focus(),
    });
    assistantPageLocationFingerprintRef.current = assistantPageLocationFingerprint;
    assistantBodyBindingRef.current = binding;
    return () => {
      if (assistantBodyBindingRef.current === binding) {
        assistantBodyBindingRef.current = null;
      }
      binding.dispose();
    };
  }, [
    applyContentChange,
    assistantChapterNumber,
    assistantPageScopeVersion,
    document?.id,
    editorOpen,
    editorSurfaceGeneration,
    novel?.id,
    saveNow,
  ]);

  React.useEffect(() => {
    if (!titleEditOpen || !novel || !document || document.kind !== "chapter") return;
    if (novel.id !== document.novel_id || assistantChapterNumber === undefined) return;
    const currentControl = () => titleInputNativeRef.current ?? titleInputRef.current?.input ?? null;
    const binding = mountChapterTitleAssistantScope({
      location: {
        novel,
        document,
        chapterNumber: assistantChapterNumber,
        dirty: titleDraftRef.current !== titleBaselineRef.current,
      },
      getValue: () => titleDraftRef.current,
      getDirty: () => titleDraftRef.current !== titleBaselineRef.current,
      getSelection: () => readAssistantTextSelection(currentControl(), titleDraftRef.current),
      applyDraftValue: (nextValue) => {
        const semanticTitle = chapterTitleName(nextValue);
        if (semanticTitle.length > 20) throw new Error("章节名称不能超过 20 字");
        titleDraftRef.current = semanticTitle;
        setTitleDraft(semanticTitle);
      },
      restoreSelection: (_fieldId, range) => restoreAssistantTextSelection(currentControl(), range),
      focus: () => {
        if (titleInputRef.current?.focus) titleInputRef.current.focus();
        else currentControl()?.focus();
      },
      markDirty: () => setSaveState("已应用到标题草稿，尚未保存"),
    });
    assistantTitleBindingRef.current = binding;
    return () => {
      if (assistantTitleBindingRef.current === binding) {
        assistantTitleBindingRef.current = null;
      }
      binding.dispose();
    };
  }, [assistantChapterNumber, document?.id, novel?.id, titleEditOpen]);

  React.useEffect(() => {
    if (!assistantPageLocationFingerprint || titleEditOpen || chapterOutlineAssistantOpen) return;
    if (assistantContextRuntime.getStatus().scopeKind === "modal") return;
    if (assistantPageLocationFingerprintRef.current === assistantPageLocationFingerprint) return;
    setAssistantPageScopeVersion((current: number) => current + 1);
  }, [assistantPageLocationFingerprint, chapterOutlineAssistantOpen, titleEditOpen]);

  React.useEffect(() => {
    setSection(initialSection);
    setReadingPanel(initialReadingPanel);
  }, [queryNovelId, initialSection, initialReadingPanel]);

  const switchSection = async (next: ProjectSection) => {
    if (!novel) return;
    setSection(next);
    setReadingPanel("overview");
    setEditorOpen(false);
    replaceWorkbenchUrl(workbenchUrl(novel.id, undefined, next, "overview"));
  };

  const switchReadingPanel = (next: WorkbenchReadingPanel) => {
    if (!novel || section !== "reading") return;
    setReadingPanel(next);
    replaceWorkbenchUrl(workbenchUrl(novel.id, undefined, "reading", next));
  };

  const backToProject = () => {
    if (!novel) return;
    const nextSection: ProjectSection = document?.kind === "outline"
      ? "outline"
      : document?.kind === "setting"
        ? "settings"
        : "chapters";
    setEditorOpen(false);
    setSection(nextSection);
    setReadingPanel("overview");
    replaceWorkbenchUrl(workbenchUrl(novel.id, undefined, nextSection));
  };

  const confirmDeleteDocument = () => {
    if (!novel || !document) return;
    const currentDocumentTitle = documentDisplayTitle(novel, document);
    Modal.confirm({
      className: "anw-modal anw-delete-document-confirm",
      title: "删除章节",
      content: `确认删除《${currentDocumentTitle}》吗？删除后将返回章节列表。`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setBusy(true);
        try {
          await apiRequest(`/novels/${novel.id}/documents/${document.id}?expected_version=${document.version}`, {
            method: "DELETE",
          });
          await refreshNovel();
          backToProject();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "删除章节失败");
          throw reason;
        } finally {
          setBusy(false);
        }
      },
    });
  };

  if (!queryNovelId) {
    return h(
      "section",
      { className: "anw-app anw-empty-state" },
      h("strong", null, "请先选择一本小说"),
      h(Button, { onClick: () => { clearWorkbenchRoute(); navigateNovelSurface(CREATIVE_CENTER_CHAT_PATH); } }, "打开创作中心"),
    );
  }

  if (editorOpen && document) {
    const orderedChapters = novel ? canonicalChapterDocuments(novel) : [];
    const currentChapterIndex = orderedChapters.findIndex((item: DocumentRecord) => item.id === document.id);
    const orderedDisplayVolumes = novel
      ? canonicalVolumeRecords(novel).filter((volume: VolumeRecord) => volume.id !== null)
      : [];
    const chapterDisplayTitle = document.kind === "chapter" && currentChapterIndex >= 0
      ? formatChapterDisplayTitle(currentChapterIndex + 1, document.title)
      : document.title;
    const generationModelName = generationModelStatus
      ? generationModelStatus.model_id
      : generationModelStatusError ? "无法读取" : "读取中…";
    const showEditor = Boolean(content.trim()) || manualEditorOpen;
    const isChapterEditor = document.kind === "chapter" && Boolean(novel);
    const chapterTitleToolsTargetId = `anw-chapter-title-tools-${document.id}`;
    const allChapterTreeVolumes = novel ? buildChapterTreeVolumes(novel) : [];
    const chapterTreeVolumes = novel ? buildChapterTreeVolumes(novel, chapterTreeQuery) : [];
    const expandedVolumeKeys = expandedChapterVolumeIds
      ?? allChapterTreeVolumes.map((item: ChapterTreeVolume) => item.key);
    const toggleChapterVolume = (volumeKey: string) => {
      setExpandedChapterVolumeIds((current: string[] | null) => {
        const openKeys = current ?? allChapterTreeVolumes.map((item: ChapterTreeVolume) => item.key);
        return openKeys.includes(volumeKey)
          ? openKeys.filter((key: string) => key !== volumeKey)
          : [...openKeys, volumeKey];
      });
    };
    const chapterTree = !isChapterEditor
      ? null
      : chapterTreeCollapsed
        ? h(
            "aside",
            { className: "anw-chapter-tree is-collapsed", "aria-label": "章节目录，已折叠" },
            h(Button, {
              type: "text",
              className: "anw-chapter-tree-restore",
              icon: h(DoubleRightOutlined),
              onClick: () => setChapterTreeCollapsed(false),
              title: "展开章节目录",
              "aria-label": "展开章节目录",
            }),
          )
        : h(
            "aside",
            { className: "anw-chapter-tree", "aria-label": "章节目录" },
            h(
              "header",
              { className: "anw-chapter-tree-header" },
              h("h2", null, "章节目录"),
              h(
                "div",
                { className: "anw-chapter-tree-controls" },
                h(Button, {
                  type: "text",
                  className: `anw-chapter-tree-icon-button ${chapterTreeSearchOpen ? "is-active" : ""}`,
                  icon: h(SearchOutlined),
                  onClick: () => {
                    setChapterTreeSearchOpen((current: boolean) => !current);
                    if (chapterTreeSearchOpen) setChapterTreeQuery("");
                  },
                  title: "搜索章节",
                  "aria-label": "搜索章节",
                  "aria-expanded": chapterTreeSearchOpen,
                }),
                h(Button, {
                  type: "text",
                  className: "anw-chapter-tree-icon-button",
                  icon: h(DoubleLeftOutlined),
                  onClick: () => setChapterTreeCollapsed(true),
                  title: "折叠章节目录",
                  "aria-label": "折叠章节目录",
                }),
              ),
            ),
            chapterTreeSearchOpen
              ? h(
                  "div",
                  { className: "anw-chapter-tree-search" },
                  h(Input, {
                    autoFocus: true,
                    allowClear: true,
                    value: chapterTreeQuery,
                    prefix: h(SearchOutlined),
                    placeholder: "搜索卷或章节",
                    "aria-label": "搜索卷或章节",
                    onChange: (event: any) => setChapterTreeQuery(event.target.value),
                  }),
                )
              : null,
            h("div", { className: "anw-chapter-tree-book-title", title: novel?.title }, novel?.title),
            h(
              "nav",
              { className: "anw-chapter-tree-nav", "aria-label": "全书卷章导航" },
              chapterTreeVolumes.length
                ? chapterTreeVolumes.map((item: ChapterTreeVolume) => {
                    const expanded = Boolean(chapterTreeQuery.trim()) || expandedVolumeKeys.includes(item.key);
                    const volumeLabel = item.displayTitle;
                    const treeId = `anw-chapter-tree-volume-${item.key}`;
                    return h(
                      "section",
                      { key: item.key, className: `anw-chapter-tree-volume ${expanded ? "is-expanded" : ""}` },
                      h(
                        "button",
                        {
                          type: "button",
                          className: "anw-chapter-tree-volume-toggle",
                          onClick: () => toggleChapterVolume(item.key),
                          "aria-expanded": expanded,
                          "aria-controls": treeId,
                        },
                        h(expanded ? CaretDownOutlined : CaretRightOutlined),
                        h("strong", { title: volumeLabel }, volumeLabel),
                        h("span", null, `${item.chapters.length}章`),
                      ),
                      expanded
                        ? h(
                            "div",
                            { id: treeId, className: "anw-chapter-tree-chapters" },
                            ...item.chapters.map((chapter: ChapterTreeChapter) => {
                              const active = chapter.document.id === document.id;
                              return h(
                                "button",
                                {
                                  key: chapter.document.id,
                                  type: "button",
                                  className: `anw-chapter-tree-chapter ${active ? "is-active" : ""}`,
                                  "aria-current": active ? "page" : undefined,
                                  "data-document-id": chapter.document.id,
                                  onClick: () => { void navigateToChapter(chapter.document.id); },
                                  title: chapter.displayTitle,
                                },
                                h("span", null, chapter.displayTitle),
                                h("small", null, `${chapter.document.visible_character_count}字`),
                              );
                            }),
                          )
                        : null,
                    );
                  })
                : h(
                    "div",
                    { className: "anw-chapter-tree-empty" },
                    chapterTreeQuery.trim() ? "没有找到匹配的卷或章节" : "暂无章节",
                  ),
            ),
          );
    const narrationBundle = narrationSnapshot?.bundle ?? null;
    const narrationGate = narrationGateState.phase === "ready"
      ? narrationGateState.gate
      : null;
    const narrationContext = narrationBundle?.context
      ?? (narrationSnapshot?.loadResult?.status === "no-edition"
        ? narrationSnapshot.loadResult.context
        : null);
    const narrationHistory = narrationContext?.edition_history.editions ?? [];
    const activeNarrationHistoryItem = narrationContext?.active_edition_id
      ? narrationHistory.find(
          (item: EditionHistoryItem) => item.edition_id === narrationContext.active_edition_id,
        ) ?? null
      : null;
    let narrationPanelPhase: ChapterNarrationPanelPhase = "loading";
    if (narrationSnapshot?.phase === "no-edition") narrationPanelPhase = "no-edition";
    if (narrationSnapshot?.phase === "ready") narrationPanelPhase = "ready";
    if (narrationSnapshot?.phase === "error") narrationPanelPhase = "error";
    if (narrationBundle?.edition.state === "unavailable") narrationPanelPhase = "unavailable";
    if (narrationGate !== null && !narrationGate.canLoadSession) {
      narrationPanelPhase = "unavailable";
    }
    let narrationSourceKind: ChapterNarrationSourceKind = "current";
    if (
      narrationSnapshot?.workingCopyDiverged
      || (
      narrationBundle
      && narrationBundle.script.source_content_hash
        !== narrationBundle.context.working_copy_content_hash
      )
    ) {
      narrationSourceKind = "working-copy-diverged";
    } else if (
      narrationBundle
      && !narrationBundle.context.active_is_current
      && narrationBundle.context.current_edition_id !== null
    ) {
      narrationSourceKind = "historical";
    }
    const narrationPanel = isChapterEditor
      && showEditor
      && !scriptReviewOpen
      && narrationGate?.visible
      ? h(ChapterNarrationPanel, {
          phase: narrationPanelPhase,
          sourceKind: narrationSourceKind,
          playerState: narrationSnapshot?.playerState ?? null,
          segments: narrationBundle?.script.segments ?? [],
          manifestSegments: narrationBundle?.manifest.segments ?? [],
          segmentStates: narrationBundle?.manifest.segments.map(
            (segment: { readonly render_status: SegmentRenderStatus }) => segment.render_status,
          ) ?? [],
          editions: narrationHistory,
          activeEditionId: narrationContext?.active_edition_id ?? null,
          currentEditionId: narrationContext?.current_edition_id ?? null,
          busy: narrationBusy,
          productionAllowed: narrationGate.canProduce,
          statusMessage: narrationGate.canLoadSession
            ? narrationStatus
            : `章节智能朗读尚未通过产品门禁（${narrationGate.reasonCode ?? "CAPABILITY_DISABLED"}）。`,
          errorMessage: narrationError,
          followPaused: narrationSnapshot?.playerState?.followPaused ?? false,
          reviewAvailable: narrationBundle?.script !== undefined,
          failedSegments: failedSegmentRetrySnapshot.scope?.editionId
            === narrationContext?.active_edition_id
            ? failedSegmentRetrySnapshot.projection
            : null,
          retryBusySegmentIds: failedSegmentRetrySnapshot.busySegmentIds,
          retrySubmitting: failedSegmentRetrySnapshot.phase === "submitting",
          retryStatusMessage: failedSegmentRetrySnapshot.statusMessage,
          retryErrorMessage: failedSegmentRetrySnapshot.errorMessage,
          retryFocusSegmentId: failedSegmentRetryFocusId,
          voiceIdentities: narrationBundle?.voiceIdentities.items ?? [],
          playbackPreferenceStatus: narrationPlaybackPreferenceStatus,
          updateRequired: Boolean(
            narrationSnapshot?.workingCopyDiverged
            || narrationContext?.explicit_update_required,
          ),
          onGenerate: () => { void startNarration("create"); },
          onUpdate: () => { void startNarration("update"); },
          onTogglePlayback: toggleNarrationPlayback,
          onSeekOrdinal: (ordinal: number) => playNarrationOrdinal(ordinal),
          cursorPlaybackAvailable: editorSurfaceRef.current?.kind === "textarea-fallback",
          onPlaybackFromCursor: () => {
            if (!editorSurfaceRef.current?.requestPlaybackFromCursor()) {
              setNarrationError("无法从当前光标位置找到可朗读句段。");
            }
          },
          onRateChange: (rate: number) => {
            try {
              narrationSessionRef.current?.setRate(rate);
            } catch (reason) {
              setNarrationError(narrationFailureMessage(reason));
            }
          },
          onVolumeChange: (volume: number) => {
            try {
              narrationSessionRef.current?.setVolume(volume);
            } catch (reason) {
              setNarrationError(narrationFailureMessage(reason));
            }
          },
          onResumeFollow: () => {
            try {
              narrationSessionRef.current?.resumeFollow();
              setNarrationStatus("已恢复跟随当前朗读句段。");
            } catch (reason) {
              setNarrationError(narrationFailureMessage(reason));
            }
          },
          onSelectEdition: selectNarrationEdition,
          onRetryFailedSegment: retryFailedNarrationSegment,
          onOpenReview: openNarrationReview,
          reviewTriggerRef: scriptReviewTriggerRef,
          retryTriggerRef: failedSegmentRetryTriggerRef,
        })
      : null;
    const reviewPlayerState = narrationSnapshot?.playerState ?? null;
    const reviewCurrentSegment = reviewPlayerState?.currentOrdinal === null
      || reviewPlayerState?.currentOrdinal === undefined
      ? null
      : narrationBundle?.script.segments[reviewPlayerState.currentOrdinal] ?? null;
    const matchingReviewWorkflow = scriptReview
      && scriptReviewRequestId
      && narrationWorkflow?.request_id === scriptReviewRequestId
      && narrationWorkflow.script_version_id === scriptReview.script_version_id
      && narrationWorkflow.source_revision_id === scriptReview.revision_id
      && narrationWorkflow.source_content_hash === scriptReview.source_content_hash
      ? narrationWorkflow
      : null;
    const scriptReviewSurface = isChapterEditor
      && scriptReviewOpen
      && scriptReview
      && scriptReviewRequestId
      && matchingReviewWorkflow
      ? h(
          "div",
          { className: "anw-script-review-shell" },
          h(ScriptReviewPanel, {
            review: scriptReview,
            requestId: scriptReviewRequestId,
            requestVersion: matchingReviewWorkflow.request_version,
            triggerRef: scriptReviewTriggerRef,
            onReviewChanged: synchronizeChangedScriptReview,
            onEditSegment: openScriptReviewSegmentEdit,
            onClose: closeScriptReview,
            compactPlayer: narrationBundle && reviewPlayerState && reviewCurrentSegment
              ? {
                  editionId: narrationBundle.edition.edition_id,
                  sourceStatus: activeNarrationHistoryItem?.source_status ?? "superseded",
                  oldDraft: narrationBundle.script.source_content_hash
                    !== narrationBundle.context.working_copy_content_hash,
                  phase: reviewPlayerState.phase,
                  speakerLabel: reviewCurrentSegment.speaker_label,
                  offsetMs: reviewPlayerState.offsetMs,
                  durationMs: reviewPlayerState.durationMs,
                  onTogglePlayback: toggleNarrationPlayback,
                }
              : undefined,
          }),
        )
      : null;
    const scriptReviewEditChoices = scriptReview
      ? buildScriptReviewSpeakerChoices(scriptReview, scriptReviewCharacterBindings)
      : [];
    const scriptReviewEditSegment = scriptReviewEdit && scriptReview
      ? scriptReview.segments.find(
          (segment: ScriptReviewSegmentResource) => segment.segment_id === scriptReviewEdit.segmentId,
        ) ?? null
      : null;
    const scriptReviewEditSurface = isChapterEditor
      && scriptReviewEdit
      && scriptReview
      && scriptReviewEditSegment
      ? h(
          Modal,
          {
            open: true,
            className: "anw-modal anw-script-review-edit-modal",
            title: "修正句段说话人与朗读文本",
            width: 760,
            okText: scriptReviewEdit.pendingReview ? "重新同步请求版本" : "保存修正",
            cancelText: "关闭",
            confirmLoading: narrationBusy,
            onOk: submitScriptReviewSegmentEdit,
            onCancel: closeScriptReviewSegmentEdit,
          },
          h(
            "div",
            {
              className: "anw-script-review-edit",
              "data-min-viewport": "1920x1080",
            },
            h("p", null, `原文：${scriptReviewEditSegment.source_text}`),
            h(
              "label",
              { htmlFor: "anw-script-review-speaker" },
              "说话人（仅当前脚本中服务端已验证的绑定）",
            ),
            h(
              "select",
              {
                id: "anw-script-review-speaker",
                value: scriptReviewEdit.speakerChoiceKey,
                disabled: narrationBusy || scriptReviewEdit.pendingReview !== null,
                onChange: (event: any) => setScriptReviewEdit((current: ScriptReviewEditDraft | null) => (
                  current ? { ...current, speakerChoiceKey: event.target.value } : current
                )),
              },
              ...scriptReviewEditChoices.map((choice) => h(
                "option",
                { key: choice.key, value: choice.key },
                `${choice.speakerKind === "narrator" ? "旁白" : choice.speakerKind === "character" ? "角色" : "匿名人物"} · ${choice.speakerLabel}`,
              )),
            ),
            h("label", { htmlFor: "anw-script-review-spoken-text" }, "朗读文本"),
            h(Input.TextArea, {
              id: "anw-script-review-spoken-text",
              rows: 3,
              maxLength: 4_000,
              value: scriptReviewEdit.spokenText,
              disabled: narrationBusy || scriptReviewEdit.pendingReview !== null,
              onChange: (event: any) => setScriptReviewEdit((current: ScriptReviewEditDraft | null) => (
                current ? { ...current, spokenText: event.target.value } : current
              )),
            }),
            h("label", { htmlFor: "anw-script-review-reason" }, "修正原因"),
            h(Input, {
              id: "anw-script-review-reason",
              maxLength: 500,
              value: scriptReviewEdit.reason,
              disabled: narrationBusy || scriptReviewEdit.pendingReview !== null,
              onChange: (event: any) => setScriptReviewEdit((current: ScriptReviewEditDraft | null) => (
                current ? { ...current, reason: event.target.value } : current
              )),
            }),
            h(
              "p",
              { role: "note" },
              "本操作只提交人物标识、句段文本和并发围栏；不会提交音色 profile、人物配音绑定或 casting。群体说话人暂不支持人工改派。",
            ),
            scriptReviewEditError
              ? h(Alert, { type: "error", showIcon: true, message: scriptReviewEditError })
              : null,
          ),
        )
      : null;
    const bodyEditor = h("div", {
      ref: editorSurfaceParentRef,
      className: "anw-chapter-editor-surface",
      "data-editor-generation": documentGenerationRef.current,
    });
    const titleInputControl = h(Input, {
      ref: (node: AssistantTitleInputRef | null) => {
        titleInputRef.current = node;
        titleInputNativeRef.current = node?.input ?? null;
      },
      id: "anw-document-title-input",
      autoFocus: true,
      size: "large",
      value: titleDraft,
      maxLength: 20,
      placeholder: document.kind === "chapter" ? "请输入章节名称" : "请输入文档标题",
      onChange: (event: any) => updateTitleDraft(event.target.value as string),
      onFocus: (event: { currentTarget: AssistantTextControl }) => {
        titleInputNativeRef.current = event.currentTarget;
        assistantTitleBindingRef.current?.setFocusedField(CHAPTER_TITLE_FIELD_ID);
      },
      onSelect: (event: { currentTarget: AssistantTextControl }) => {
        titleInputNativeRef.current = event.currentTarget;
      },
      onBlur: () => assistantTitleBindingRef.current?.setFocusedField(undefined),
      onPressEnter: () => {
        if ((document.kind === "chapter" || titleDraftRef.current.trim()) && !titleSaving) {
          void renameDocument();
        }
      },
    });
    const titleEditorForm = h(
      "div",
      { className: "anw-title-edit-form" },
      h("label", { htmlFor: "anw-document-title-input" }, document.kind === "chapter" ? "章节名称" : "文档标题"),
      document.kind === "chapter" && currentChapterIndex >= 0
        ? h(
            "div",
            { className: "anw-numbered-title-control" },
            h("span", { className: "anw-numbered-title-prefix", "aria-hidden": "true" }, `第${currentChapterIndex + 1}章`),
            titleInputControl,
          )
        : titleInputControl,
      h("p", { className: "anw-title-edit-count" }, document.kind === "chapter"
        ? `序号由系统按全书顺序生成；名称最多20字，当前：${titleDraft.length}/20`
        : `最多20字，当前：${titleDraft.length}/20`),
      h(
        "div",
        { className: "anw-title-edit-actions" },
        h(Button, {
          className: "anw-title-edit-cancel",
          disabled: titleSaving,
          onClick: () => setTitleEditOpen(false),
        }, "取消"),
        h(Button, {
          className: "anw-primary-button anw-title-edit-save",
          loading: titleSaving,
          disabled: document.kind !== "chapter" && !titleDraft.trim(),
          onClick: () => void renameDocument(),
        }, "保存"),
      ),
    );
    return h(
      Spin,
      { spinning: busy },
      h(
        "main",
        { className: `anw-app anw-editor ${isChapterEditor ? "has-chapter-tree" : ""} ${chapterTreeCollapsed ? "is-chapter-tree-collapsed" : ""}` },
        chapterTree,
        h(
          "div",
          {
            className: `anw-editor-content ${
              isChapterEditor && showEditor ? "has-chapter-narration" : ""
            }`,
          },
        h(
          "header",
          { className: "anw-editor-topbar" },
          h(Button, { type: "text", icon: h(ArrowLeftOutlined), onClick: backToProject }, "返回列表"),
          h("div", {
            className: "anw-current-model-inline",
            title: generationModelName,
            "aria-label": `当前模型：${generationModelName}`,
          }, h("strong", null, generationModelName)),
          h(Button, { className: "anw-delete-button", onClick: confirmDeleteDocument }, "删除"),
          h(Button, { icon: h(CopyOutlined), onClick: copyContext, title: "复制 AI 写作上下文" }, "复制"),
          h(Button, { icon: h(SaveOutlined), className: "anw-primary-button", onClick: document.kind === "chapter" ? () => setSaveVolumeOpen(true) : checkpoint, title: saveState }, "保存"),
        ),
        error ? h(Alert, { type: "error", closable: true, message: error, onClose: () => setError(""), style: { margin: "10px 16px 0" } }) : null,
        recovery ? h(Alert, { type: "warning", showIcon: true, message: "发现未同步的崩溃恢复草稿", action: h(Button, { size: "small", onClick: recoverLocal }, "恢复本地稿"), style: { margin: "10px 16px 0" } }) : null,
        conflict ? h(Alert, { type: "error", showIcon: true, message: "服务器版本已经变化，未覆盖正文", action: h(Button, { size: "small", onClick: loadServerConflict }, "载入服务器版"), style: { margin: "10px 16px 0" } }) : null,
        h(
          "section",
          { className: "anw-editor-scroll" },
          h(
            "article",
            { className: "anw-editor-paper" },
            h(
              "div",
              { className: "anw-editor-title-row" },
              h(
                "div",
                null,
                h("h1", { className: "anw-editor-title" }, chapterDisplayTitle),
                h("div", { className: "anw-editor-count" }, "本章字数 ", h("strong", null, document.visible_character_count), " 字"),
              ),
              h("div", { className: "anw-editor-title-actions" },
                isChapterEditor
                  ? h("div", {
                      id: chapterTitleToolsTargetId,
                      className: "anw-chapter-title-tools",
                    })
                  : null,
                h(Button, {
                  type: "text",
                  className: "anw-title-edit-button",
                  icon: h(EditOutlined),
                  onClick: openTitleEditor,
                  title: document.kind === "chapter" ? "修改章节名称" : "修改文档名称",
                  "aria-label": document.kind === "chapter" ? "修改章节名称" : "修改文档名称",
                }),
              ),
            ),
            bodyGenerationState.active
              ? h(
                  "section",
                  { className: "anw-editor-generating", "aria-label": "AI 正在创作章节内容" },
                  h(Spin, { size: "large" }),
                  h("strong", null, "AI 正在创作章节内容..."),
                  h("p", null, bodyGenerationState.stage || "正在分析角色关系、伏笔推进和章节情节"),
                  h("span", null, "请稍候，精彩内容即将呈现"),
                  h("small", null, "预计需要 30-60 秒"),
                )
              : showEditor
              ? (SelectionEditReviewHost
                ? h(
                  SelectionEditReviewHost,
                  {
                    fieldIds: CHAPTER_BODY_FIELD_ID,
                    className: "anw-editor-selection-review-host",
                  },
                  bodyEditor,
                )
                : bodyEditor)
              : h(
                  "section",
                  { className: "anw-editor-empty", "aria-label": "章节正文空状态" },
                  h("span", { className: "anw-editor-empty-icon" }, h(FileTextOutlined)),
                  h("strong", null, "暂无章节内容"),
                  h("p", null, "点击下方按钮开始生成"),
                  h(Button, {
                    className: "anw-primary-button anw-editor-empty-generate",
                    icon: h(BookOutlined),
                    onClick: () => chapterGenerateActionRef.current?.(),
                  }, "生成章节内容"),
                  h("button", {
                    type: "button",
                    className: "anw-editor-direct-link",
                    onClick: () => setManualEditorOpen(true),
                  }, "我已有正文，点击直接填写"),
                ),
            h(
              "div",
              { className: "anw-editor-footer" },
              h(
                "div",
                { className: "anw-workflow-buttons" },
                document.kind === "chapter" && novel
                  ? h(ChapterWorkflowPanel, {
                      novel,
                      document,
                      onPrepareGeneration: () => saveNow(contentRef.current),
                      onDocumentChanged: applyWorkflowDocument,
                      onError: setError,
                      onStatus: setSaveState,
                      chapterNumber: currentChapterIndex + 1,
                      titleToolsTargetId: chapterTitleToolsTargetId,
                      generateActionRef: chapterGenerateActionRef,
                      onBodyGenerationStateChange: (active: boolean, stage: string) => setBodyGenerationState({ active, stage }),
                      onAssistantModalStateChange: setChapterOutlineAssistantOpen,
                      selectionEditReviewHost: SelectionEditReviewHost,
                    })
                  : null,
              ),
            ),
          ),
        ),
        narrationPanel,
        scriptReviewSurface,
        scriptReviewEditSurface,
        ),
        h(
          Modal,
          {
            open: titleEditOpen,
            className: "anw-modal anw-title-edit-modal",
            wrapClassName: "anw-assistant-aware-modal-wrap",
            mask: false,
            title: document.kind === "chapter" ? "编辑章节标题" : "编辑文档标题",
            width: 520,
            centered: true,
            closable: false,
            footer: null,
            maskClosable: !titleSaving,
            onCancel: () => { if (!titleSaving) setTitleEditOpen(false); },
          },
          SelectionEditReviewHost
            ? h(
              SelectionEditReviewHost,
              { fieldIds: CHAPTER_TITLE_FIELD_ID, className: "anw-title-selection-review-host" },
              titleEditorForm,
            )
            : titleEditorForm,
        ),
        h(
          Modal,
          {
            open: saveVolumeOpen,
            className: "anw-modal anw-save-volume-modal",
            title: "选择分卷",
            width: 520,
            centered: true,
            footer: null,
            onCancel: () => setSaveVolumeOpen(false),
          },
          h(
            "div",
            { className: "anw-save-volume-body" },
            h("p", null, "请选择将章节保存到哪个分卷，不选择则跳过分卷保存。"),
            h(
              "div",
              { className: "anw-save-volume-list" },
              ...orderedDisplayVolumes.map((volume: VolumeRecord, index: number) => h(
                "button",
                {
                  key: volume.id,
                  type: "button",
                  disabled: busy,
                  onClick: () => confirmSaveChapterToVolume(volume.id),
                },
                h("strong", null, volumeDisplayTitle(index + 1, volume.title)),
                h("span", null, `${volume.documents.filter((item: DocumentRecord) => item.kind === "chapter").length} 章`),
              )),
              h(Button, { block: true, disabled: busy, onClick: () => confirmSaveChapterToVolume(null) }, "不选分卷"),
              h(Button, { block: true, className: "anw-save-and-next-button", disabled: busy, onClick: () => confirmSaveChapterToVolume(document.volume_id, true) }, "保存并新建下一章"),
            ),
          ),
        ),
        h(
          Modal,
          { open: historyOpen, className: "anw-modal", title: "版本历史", footer: null, onCancel: () => setHistoryOpen(false) },
          document.revisions?.length
            ? h(
                "div",
                { className: "anw-content-sections" },
                ...document.revisions.map((revision: DocumentRecord["revisions"][number]) => h(
                  "div",
                  { key: revision.id, className: "anw-info-card", style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 } },
                  h(
                    "div",
                    null,
                    h("strong", { className: "anw-version-title" }, `版本 ${revision.revision_number}`),
                    h("div", { className: "anw-panel-subtitle" }, `${revisionSourceLabel(revision.source)} · ${revision.visible_character_count} 字`),
                  ),
                  h(
                    Button,
                    { size: "small", loading: busy, onClick: () => void confirmRestore(revision) },
                    "恢复为新版本",
                  ),
                )),
              )
            : h(Empty, { description: "暂无版本" }),
        ),
      ),
    );
  }

  if (!novel) {
    return h("main", { className: "anw-app anw-empty-state" }, h(Spin), h("strong", null, "正在载入作品…"));
  }

  return h(StudioProjectView, {
    novel,
    section,
    readingPanel,
    onSectionChange: (next: WorkbenchSection) => { void switchSection(next); },
    onReadingPanelChange: switchReadingPanel,
    onSelectDocument: selectDocument,
    onNovelChanged: (updated: NovelRecord) => setNovel(updated),
    onReload: refreshNovel,
    openChapterWizardSignal,
    onBack: () => { clearWorkbenchRoute(); navigateNovelSurface(CREATIVE_CENTER_CHAT_PATH); },
    onError: setError,
    assistantWorkspaceLayout: props.assistantWorkspaceLayout,
    selectionEditReviewHost: props.selectionEditReviewHost,
  });

  const chapterDocuments = novel ? canonicalChapterDocuments(novel) : [];
  const structuredDocuments = (novel?.tree ?? []).flatMap((volume: VolumeRecord) => volume.documents)
    .filter((item: DocumentRecord) => item.kind === (section === "settings" ? "setting" : "outline"));
  const chapterOrder = new Map(
    chapterDocuments.map((item: DocumentRecord, index: number) => [item.id, index + 1]),
  );
  const roleFactView = selectFactView(
    projectFacts,
    (fact: StoryFactRecord) => fact.fact_type === "character_state",
  );
  const roleMap = new Map<string, StoryFactRecord[]>();
  for (const fact of roleFactView.facts) {
    const list = roleMap.get(fact.subject) ?? [];
    list.push(fact);
    roleMap.set(fact.subject, list);
  }
  const clueFactView = selectFactView(
    projectFacts,
    (fact: StoryFactRecord) => isClueFactType(fact.fact_type),
  );

  const renderPanelBody = (): unknown => {
    if (section === "chapters") {
      const volumeTiles = canonicalVolumeRecords(novel).filter(
        (volume: VolumeRecord) => volume.id !== null
          || volume.documents.some((item: DocumentRecord) => item.kind === "chapter"),
      );
      return h(
        "div",
        { className: "anw-chapter-dashboard" },
        h("h3", { className: "anw-subsection-title" }, "分卷管理"),
        volumeTiles.length
          ? h(
              "div",
              { className: "anw-volume-overview" },
              ...volumeTiles.map((volume: VolumeRecord, volumeIndex: number) => {
                const count = volume.documents.filter((item: DocumentRecord) => item.kind === "chapter").length;
                const volumeTitle = volume.id
                  ? volumeDisplayTitle(volumeIndex + 1, volume.title)
                  : "未分卷";
                return h(
                  "article",
                  { key: volume.id ?? "ungrouped", className: "anw-volume-tile" },
                  h("div", { className: "anw-volume-index" }, volume.id ? String(volumeIndex + 1).padStart(2, "0") : "—"),
                  h("div", { className: "anw-volume-name" }, volumeTitle),
                  h("div", { className: "anw-volume-count" }, `${count} 章`),
                  volume.id
                    ? h(
                        "div",
                        { className: "anw-volume-actions" },
                        h(Button, { size: "small", type: "text", disabled: true, title: "分卷编辑暂未开放" }, "编辑"),
                        h(Button, { size: "small", type: "text", danger: true, disabled: true, title: "分卷删除暂未开放" }, "删除"),
                      )
                    : null,
                );
              }),
            )
          : h(Empty, { description: "还没有分卷" }),
        h(
          "div",
          { className: "anw-subsection-row" },
          h("h3", { className: "anw-subsection-title" }, "章节目录"),
          h("span", { className: "anw-panel-subtitle" }, `共 ${chapterDocuments.length} 章`),
        ),
        volumeTiles.length
          ? h(
              "div",
              { className: "anw-chapter-volume-list" },
              ...volumeTiles.map((volume: VolumeRecord, volumeIndex: number) => {
                const volumeChapters = volume.documents.filter((item: DocumentRecord) => item.kind === "chapter");
                const volumeTitle = volume.id
                  ? volumeDisplayTitle(volumeIndex + 1, volume.title)
                  : "未分卷";
                return h(
                  "section",
                  { key: `chapters:${volume.id ?? "ungrouped"}`, className: "anw-chapter-volume-section" },
                  h(
                    "div",
                    { className: "anw-chapter-group-header" },
                    h("strong", null, volumeTitle),
                    h("span", null, `${volumeChapters.length} 章`),
                  ),
                  volumeChapters.length
                    ? h(
                        "div",
                        { className: "anw-chapter-list anw-chapter-shelf" },
                        ...volumeChapters.map((item: DocumentRecord) => h(
                          "button",
                          { key: item.id, type: "button", className: "anw-chapter-row", onClick: () => selectDocument(item.id) },
                          h("span", { className: "anw-chapter-number" }, String(chapterOrder.get(item.id) ?? 0).padStart(2, "0")),
                          h("span", { className: "anw-chapter-row-title" }, formatChapterDisplayTitle(chapterOrder.get(item.id) ?? 0, item.title)),
                          h("span", { className: "anw-chapter-row-meta" }, `${item.visible_character_count} 字`),
                          h("span", { className: "anw-chapter-row-meta is-ready" }, "已保存"),
                        )),
                      )
                    : h("div", { className: "anw-inline-empty" }, "本卷还没有章节"),
                );
              }),
            )
          : null,
      );
    }

    if (section === "outline" || section === "settings") {
      if (structuredDocuments.length === 0) {
        const kind = section === "settings" ? "setting" : "outline";
        return h(
          "div",
          { className: "anw-empty-panel" },
          h(Empty, { description: section === "settings" ? "还没有世界设定" : "还没有故事大纲" }),
          h(
            Button,
            { className: "anw-primary-button", onClick: () => void createStructuredDocument(kind) },
            section === "settings" ? "创建世界设定" : "创建故事大纲",
          ),
        );
      }
      return h(
        "div",
        { className: "anw-content-sections" },
        ...structuredDocuments.map((item: DocumentRecord) => h(
          "button",
          { key: item.id, type: "button", className: "anw-info-card", onClick: () => selectDocument(item.id), style: { textAlign: "left", cursor: "pointer" } },
          h("h3", { className: "anw-info-card-title" }, item.title),
          h("p", { className: "anw-info-card-copy" }, item.content_markdown || "点击进入编辑并补充内容。"),
        )),
      );
    }

    if (section === "roles") {
      const actualRoles = Array.from(roleMap.entries()).map(([name, facts]) => [name, "故事角色", facts.slice(0, 2).map((fact) => `${fact.predicate}：${fact.object_text}`).join("；")] as const);
      return h(
        "div",
        { className: "anw-entity-group" },
        h(
          "div",
          { className: "anw-subsection-row" },
          h("h3", { className: "anw-entity-heading" }, `角色列表（${actualRoles.length}）`),
          h(
            "div",
            { className: "anw-segmented" },
            h("button", { type: "button", className: "is-active" }, "角色卡"),
            h("button", { type: "button", disabled: true, title: "关系实体化后开放" }, "关系图"),
          ),
        ),
        projectFactsLoading
          ? h("div", { className: "anw-loading-panel" }, h(Spin), h("span", null, "正在载入角色资料…"))
          : h(
              React.Fragment,
              null,
              roleFactView.state === "stale"
                ? h(Alert, { type: "warning", showIcon: true, message: "这些角色资料来自旧版本正文，当前仅供复核。", style: { marginBottom: 14 } })
                : null,
              actualRoles.length
                ? h(
                    "div",
                    { className: "anw-entity-grid" },
                    ...actualRoles.map(([name, identity, copy]) => h(
                      "article",
                      { key: name, className: `anw-entity-card ${roleFactView.state === "stale" ? "is-stale" : ""}` },
                      h("div", { className: "anw-avatar" }, name.slice(0, 1)),
                      h("div", { className: "anw-entity-name" }, name),
                      h("div", { className: "anw-role-identity" }, identity),
                      h("div", { className: "anw-entity-copy" }, copy),
                      h(
                        "div",
                        { className: "anw-role-footer" },
                        h("span", null, "资料状态"),
                        h("strong", { className: roleFactView.state === "stale" ? "is-stale" : "" }, roleFactView.state === "stale" ? "待复核" : "当前有效"),
                      ),
                    )),
                  )
                : h(Empty, { description: "故事账本中还没有已确认的人物状态" }),
            ),
      );
    }

    return h(
      "div",
      { className: "anw-clue-board" },
      h(
        "div",
        { className: "anw-segmented anw-clue-tabs", "aria-label": "线索分类" },
        h("button", { type: "button", className: "is-active" }, "全部"),
        ...["主线", "支线", "感情线", "伏笔"].map((label) => h(
          "button",
          { key: label, type: "button", disabled: true, title: "完成线路实体化后开放分类筛选" },
          label,
        )),
      ),
      projectFactsLoading
        ? h("div", { className: "anw-loading-panel" }, h(Spin), h("span", null, "正在载入线索资料…"))
        : h(
            React.Fragment,
            null,
            clueFactView.state === "stale"
              ? h(Alert, { type: "warning", showIcon: true, message: "这些线索来自旧版本正文，当前仅供复核。", style: { marginBottom: 14 } })
              : null,
            clueFactView.facts.length
              ? h(
                  "div",
                  { className: "anw-content-sections" },
                  ...clueFactView.facts.map((fact: StoryFactRecord) => h(
                    "article",
                    { key: fact.id, className: `anw-clue-card ${clueFactView.state === "stale" ? "is-stale" : ""}` },
                    h("span", { className: "anw-clue-kind" }, factTypeLabel(fact.fact_type)),
                    h("div", { className: "anw-clue-content" }, h("h3", null, `${fact.subject} · ${fact.predicate}`), h("p", null, fact.object_text)),
                    h("span", { className: `anw-clue-state ${clueFactView.state === "stale" ? "is-stale" : ""}` }, factStatusLabel(fact.status)),
                  )),
                )
              : h(Empty, { description: "故事账本中还没有已确认的线索或伏笔" }),
          ),
    );
  };

  return h(
    Spin,
    { spinning: busy },
    h(
      "main",
      { className: "anw-app anw-project" },
      h(
        "aside",
        { className: "anw-book-rail" },
        h(
          "div",
          { className: "anw-book-rail-top" },
          novel ? novelCover(novel, "anw-book-cover-large") : null,
          h("h1", { className: "anw-book-title" }, novel?.title ?? "加载中"),
          h("div", { className: "anw-book-description" }, novel?.description || "长篇小说创作项目"),
          h("div", { className: "anw-book-counts" }, h("span", null, `${chapterDocuments.length} 章节`), h("span", null, `${chapterDocuments.reduce((sum: number, item: DocumentRecord) => sum + item.visible_character_count, 0)} 字`)),
        ),
        h(
          "nav",
          { className: "anw-project-nav", "aria-label": "作品创作流程" },
          ...(["chapters", "outline", "roles", "clues", "settings", "reading"] as ProjectSection[]).map((item) => {
            const Icon = sectionIcon(item);
            return h(
              "button",
              { key: item, type: "button", className: `anw-project-nav-button ${section === item ? "is-active" : ""}`, onClick: () => void switchSection(item) },
              h(Icon),
              h("span", { className: "anw-nav-label" }, sectionLabel(item)),
            );
          }),
        ),
      ),
      h(
        "section",
        { className: "anw-project-main" },
        error ? h(Alert, { type: "error", closable: true, message: error, onClose: () => setError(""), style: { margin: 14 } }) : null,
        h(
          "header",
          { className: "anw-panel-header" },
          h("div", null, h("h2", { className: "anw-panel-title" }, section === "chapters" ? "章节列表" : sectionLabel(section)), h("div", { className: "anw-panel-subtitle" }, section === "chapters" ? "按分卷管理正文，点击章节进入专注编辑" : "统一管理作品的结构化创作资料")),
          h(
            "div",
            { className: "anw-panel-actions" },
            h(Button, { onClick: () => { clearWorkbenchRoute(); navigateNovelSurface(CREATIVE_CENTER_CHAT_PATH); } }, "返回创作中心"),
            section === "chapters" ? h(Button, { onClick: createVolume }, "+ 新增分卷") : null,
            section === "chapters" ? h(Button, { className: "anw-primary-button", icon: h(PlusOutlined), onClick: createChapter }, "新建章节") : null,
          ),
        ),
        h("div", { className: "anw-panel-body" }, renderPanelBody()),
      ),
    ),
  );
}
