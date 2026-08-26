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
import { buildChapterTreeVolumes, ChapterTreeChapter, ChapterTreeVolume } from "./chapter-tree";
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
} from "./presenters";
import { workbenchStore } from "./store";
import {
  DocumentRecord,
  GenerationModelStatus,
  NovelRecord,
  NovelSummary,
  RestorePreviewRecord,
  StoryFactRecord,
  VolumeRecord,
} from "./types";
import {
  activeWorkbenchRoute,
  clearWorkbenchRoute,
  rememberWorkbenchRoute,
} from "./workbench-route";
import { StudioProjectView, WorkbenchSection } from "./workbench-studio";
import type { AssistantWorkspaceLayout } from "./assistant-layout";
import type { SelectionEditReviewHostComponent } from "./selection-edit-runtime";
import {
  observeEditorTextareaAutoSize,
  resizeEditorTextareaToContent,
} from "./editor-textarea-auto-size";
import defaultNovelCover from "../assets/novel-cover-fengcunqu.jpg";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
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
  TeamOutlined,
  UnorderedListOutlined,
  UserOutlined,
} = host.antdIcons;


type ProjectSection = WorkbenchSection;


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
  }
  return query;
}


function workbenchUrl(
  novelId: string,
  documentId?: string,
  section?: ProjectSection,
): string {
  rememberWorkbenchRoute(novelId, documentId);
  const query = new URLSearchParams({ novel_workbench: "1", novel_id: novelId });
  if (documentId) query.set("document_id", documentId);
  if (section && section !== "chapters") query.set("section", section);
  return `/chat?${query.toString()}`;
}


function firstDocument(novel: NovelRecord): DocumentRecord | undefined {
  return novel.tree.flatMap((volume) => volume.documents)
    .find((document) => document.kind === "chapter")
    ?? novel.tree.flatMap((volume) => volume.documents)[0];
}


function chapterNumberFor(novel: NovelRecord, documentId: string): number | undefined {
  const index = [...novel.tree]
    .sort((left, right) => left.position - right.position)
    .flatMap((volume) => [...volume.documents].sort((left, right) => left.position - right.position))
    .filter((document) => document.kind === "chapter")
    .findIndex((document) => document.id === documentId);
  return index >= 0 ? index + 1 : undefined;
}


function novelCover(title: string, className = "anw-cover"): unknown {
  return h("img", {
    className,
    src: defaultNovelCover,
    alt: `${title}封面`,
  });
}


function toolButton(
  Icon: any,
  label: string,
  onClick: () => void,
): unknown {
  return h(
    "button",
    { type: "button", className: "anw-tool-button", onClick },
    h(Icon),
    h("span", null, label),
  );
}


function latestChapterTitle(novel: NovelSummary): string {
  return novel.chapter_count > 0 ? `最新进度：已完成 ${novel.chapter_count} 章` : "尚未开始正文创作";
}


export function NovelLibraryPage() {
  const [novels, setNovels] = React.useState([] as NovelSummary[]);
  const [title, setTitle] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [error, setError] = React.useState("");

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      setNovels(await apiRequest<NovelSummary[]>("/novels"));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载作品失败");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { void reload(); }, [reload]);

  const createNovel = async () => {
    if (!title.trim()) return;
    setCreating(true);
    try {
      const novel = await apiRequest<NovelRecord>("/novels", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), description: "" }),
      });
      window.location.assign(workbenchUrl(novel.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建作品失败");
    } finally {
      setCreating(false);
    }
  };

  const openNovel = (novelId: string, section: ProjectSection = "chapters") => {
    window.location.assign(workbenchUrl(novelId, undefined, section));
  };

  return h(
    "main",
    { className: "anw-app anw-page" },
    h(
      "div",
      { className: "anw-page-inner" },
      h(
        "header",
        { className: "anw-page-header" },
        h(
          "div",
          null,
          h("div", { className: "anw-eyebrow" }, "AI NOVEL STUDIO"),
          h("h1", { className: "anw-page-title" }, "创作中心"),
          h("p", { className: "anw-page-subtitle" }, "从作品设定到章节版本，把长篇小说真正写完。"),
        ),
        h(
          Button,
          {
            type: "primary",
            className: "anw-primary-button",
            icon: h(PlusOutlined),
            onClick: () => setCreateOpen(true),
          },
          "创建新小说",
        ),
      ),
      error ? h(Alert, { type: "error", showIcon: true, message: error, style: { marginBottom: 16 } }) : null,
      h(
        "nav",
        { className: "anw-quick-nav", "aria-label": "创作中心导航" },
        h("button", { type: "button", className: "anw-quick-item is-active" }, h(BookOutlined), "我的作品"),
        h(
          "button",
          {
            type: "button",
            className: "anw-quick-item",
            disabled: true,
            title: "故事资料库将在资料实体化后开放",
            "aria-label": "故事资料库，暂未开放",
          },
          h(DatabaseOutlined),
          "故事资料库",
          h("span", { className: "anw-soon-badge" }, "待开放"),
        ),
        h(
          "button",
          {
            type: "button",
            className: "anw-quick-item",
            disabled: true,
            title: "创作灵感功能正在建设",
            "aria-label": "创作灵感，暂未开放",
          },
          h(BulbOutlined),
          "创作灵感",
          h("span", { className: "anw-soon-badge" }, "待开放"),
        ),
      ),
      loading
        ? h("div", { className: "anw-empty-library" }, h(Spin), h("p", null, "正在载入作品…"))
        : novels.length === 0
          ? h(
              "section",
              { className: "anw-empty-library" },
              h("h2", null, "还没有小说"),
              h("p", null, "先创建第一本作品，系统会自动准备首卷和第一章。"),
              h(Button, { className: "anw-primary-button", onClick: () => setCreateOpen(true) }, "创建第一本小说"),
            )
          : h(
              "section",
              { className: "anw-library-grid", "aria-label": `我的作品，共 ${novels.length} 本` },
              ...novels.map((novel: NovelSummary) => h(
                "article",
                { key: novel.id, className: "anw-novel-card" },
                h(
                  "div",
                  { className: "anw-novel-hero" },
                  novelCover(novel.title),
                  h(
                    "div",
                    { className: "anw-novel-meta" },
                    h("h2", { className: "anw-novel-title" }, novel.title),
                    h(
                      "div",
                      { className: "anw-stats" },
                      h("span", null, `${novel.chapter_count} 章`),
                      h("span", null, `${novel.visible_character_count} 字`),
                    ),
                    h(
                      "div",
                      { className: "anw-tags" },
                      h("span", { className: "anw-tag is-accent" }, "长篇小说"),
                      h("span", { className: "anw-tag" }, novel.chapter_count ? "持续创作" : "新作品"),
                    ),
                    h("div", { className: "anw-latest" }, latestChapterTitle(novel)),
                  ),
                ),
                h(
                  "div",
                  { className: "anw-novel-tools" },
                  toolButton(UnorderedListOutlined, "大纲", () => openNovel(novel.id, "outline")),
                  toolButton(TeamOutlined, "角色", () => openNovel(novel.id, "roles")),
                  toolButton(BulbOutlined, "线索", () => openNovel(novel.id, "clues")),
                  toolButton(SettingOutlined, "设定", () => openNovel(novel.id, "settings")),
                ),
                h(
                  "div",
                  { className: "anw-start" },
                  h(
                    Button,
                    { block: true, className: "anw-primary-button", onClick: () => openNovel(novel.id) },
                    "开始创作",
                  ),
                ),
              )),
            ),
      h(
        Modal,
        {
          open: createOpen,
          className: "anw-modal",
          title: "创建新小说",
          onCancel: () => setCreateOpen(false),
          onOk: createNovel,
          okText: "创建并进入作品",
          cancelText: "取消",
          okButtonProps: { className: "anw-primary-button", loading: creating, disabled: !title.trim() },
        },
        h("p", { style: { color: "#8a909d", marginTop: 0 } }, "先给作品一个名字，其他设定可以进入作品后继续完善。"),
        h(Input, {
          autoFocus: true,
          size: "large",
          value: title,
          maxLength: 240,
          "aria-label": "小说名称",
          placeholder: "小说名称",
          onChange: (event: any) => setTitle(event.target.value),
          onPressEnter: createNovel,
        }),
      ),
    ),
  );
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
  }[section];
}


function sectionIcon(section: ProjectSection): any {
  return {
    chapters: FileTextOutlined,
    outline: UnorderedListOutlined,
    roles: TeamOutlined,
    clues: BulbOutlined,
    settings: SettingOutlined,
  }[section];
}


interface NovelWorkbenchProps {
  assistantWorkspaceLayout?: AssistantWorkspaceLayout;
  selectionEditReviewHost?: SelectionEditReviewHostComponent;
}


export function NovelWorkbench(props: NovelWorkbenchProps = {}) {
  const query = currentQuery();
  const SelectionEditReviewHost = props.selectionEditReviewHost;
  const queryNovelId = query.get("novel_id");
  const queryDocumentId = query.get("document_id");
  const initialSection = (query.get("section") as ProjectSection | null) ?? "chapters";

  const [novel, setNovel] = React.useState(null as NovelRecord | null);
  const [document, setDocument] = React.useState(null as DocumentRecord | null);
  const [content, setContent] = React.useState("");
  const [section, setSection] = React.useState(initialSection as ProjectSection);
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
  const editorTextareaRef = React.useRef(null as HTMLTextAreaElement | null);
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

  const loadDocument = React.useCallback(async (documentId: string) => {
    setBusy(true);
    try {
      const loaded = await apiRequest<DocumentRecord>(`/documents/${documentId}`);
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
      window.history.replaceState(null, "", workbenchUrl(loaded.novel_id, loaded.id));
      const local = await loadRecoveryDraft(loaded.id);
      if (local && local.contentMarkdown !== loaded.content_markdown) {
        setRecovery(local);
        setSaveState("发现未同步本地草稿");
      } else {
        setRecovery(null);
        await clearRecoveryDraft(loaded.id);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载章节失败");
    } finally {
      setBusy(false);
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

  React.useLayoutEffect(() => {
    const textarea = editorTextareaRef.current;
    if (!textarea || !editorOpen) return;
    resizeEditorTextareaToContent(textarea);
  }, [content, document?.id, editorOpen]);

  React.useLayoutEffect(() => {
    const textarea = editorTextareaRef.current;
    if (!textarea || !editorOpen || bodyGenerationState.active) return;
    return observeEditorTextareaAutoSize(textarea);
  }, [bodyGenerationState.active, document?.id, editorOpen, manualEditorOpen]);

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
    const active = documentRef.current;
    if (!active) return null;
    if (active.content_markdown === markdown) {
      setSaveState("已保存");
      return active;
    }
    setSaveState("正在保存…");
    try {
      const saved = await apiRequest<DocumentRecord>(`/documents/${active.id}/draft`, {
        method: "PATCH",
        body: JSON.stringify({ expected_draft_version: active.draft_version, content_markdown: markdown }),
      });
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
        timerRef.current = setTimeout(() => void saveNow(contentRef.current), 100);
      }
      return merged;
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setConflict((reason.detail as ConflictDetail).current);
        setSaveState("版本冲突，本地稿已保留");
      } else {
        setSaveState("同步失败，本地稿已保留");
      }
      return null;
    }
  }, []);

  const onContentChange = (event: any) => {
    const markdown = event.target.value as string;
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
    const documents = novel.tree.flatMap((volume: VolumeRecord) => volume.documents)
      .filter((item: DocumentRecord) => item.kind === "chapter");
    const targetVolume = novel.tree.find((volume: VolumeRecord) => volume.id !== null);
    const created = await apiRequest<DocumentRecord>(`/novels/${novel.id}/documents`, {
      method: "POST",
      body: JSON.stringify({
        title: `第${documents.length + 1}章`,
        kind: "chapter",
        volume_id: targetVolume?.id ?? null,
      }),
    });
    await refreshNovel();
    await loadDocument(created.id);
  };

  const createVolume = async () => {
    if (!novel) return;
    await apiRequest(`/novels/${novel.id}/volumes`, {
      method: "POST",
      body: JSON.stringify({ title: `第${novel.tree.filter((item: VolumeRecord) => item.id).length + 1}卷` }),
    });
    await refreshNovel();
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
      const chapterIds = novel.tree
        .flatMap((volume: VolumeRecord) => volume.documents)
        .filter((item: DocumentRecord) => item.kind === "chapter")
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
        rememberWorkbenchRoute(novel.id);
        window.history.replaceState(null, "", workbenchUrl(novel.id));
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
    await navigator.clipboard.writeText([
      `当前小说：${novel.title}`,
      `novel_id: ${novel.id}`,
      `当前文档：${document.title}`,
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
    const nextTitle = value.slice(0, 20);
    titleDraftRef.current = nextTitle;
    setTitleDraft(nextTitle);
    assistantTitleBindingRef.current?.notifyFieldChanged(CHAPTER_TITLE_FIELD_ID);
  };

  const renameDocument = async () => {
    const active = documentRef.current;
    const nextTitle = titleDraftRef.current.trim();
    if (!novel || !active || !nextTitle) return;
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
        body: JSON.stringify({ expected_version: current.version, title: nextTitle }),
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
        editorTextareaRef.current,
        contentRef.current,
      ),
      applyEditorContent: (nextValue) => {
        const active = documentRef.current;
        if (!active || active.id !== document.id) {
          throw new Error("章节已切换，不能应用到旧正文");
        }
        contentRef.current = nextValue;
        setContent(nextValue);
        setSaveState("已应用，正在自动保存");
        void saveRecoveryDraft({
          documentId: active.id,
          draftVersion: active.draft_version,
          contentMarkdown: nextValue,
          updatedAt: Date.now(),
        });
      },
      scheduleAutosave: (nextValue) => {
        const active = documentRef.current;
        if (!active || active.id !== document.id) return;
        if (timerRef.current) clearTimeout(timerRef.current);
        setSaveState("已应用，正在自动保存");
        timerRef.current = setTimeout(() => void saveNow(nextValue), 600);
      },
      restoreSelection: (range) => restoreAssistantTextSelection(
        editorTextareaRef.current,
        range,
      ),
      focus: () => editorTextareaRef.current?.focus(),
    });
    assistantPageLocationFingerprintRef.current = assistantPageLocationFingerprint;
    assistantBodyBindingRef.current = binding;
    return () => {
      if (assistantBodyBindingRef.current === binding) {
        assistantBodyBindingRef.current = null;
      }
      binding.dispose();
    };
  }, [assistantChapterNumber, assistantPageScopeVersion, document?.id, editorOpen, novel?.id, saveNow]);

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
        if (nextValue.length > 20) throw new Error("章节标题不能超过 20 字");
        titleDraftRef.current = nextValue;
        setTitleDraft(nextValue);
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

  const switchSection = async (next: ProjectSection) => {
    if (!novel) return;
    setSection(next);
    setEditorOpen(false);
    rememberWorkbenchRoute(novel.id);
    window.history.replaceState(null, "", workbenchUrl(novel.id, undefined, next));
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
    rememberWorkbenchRoute(novel.id);
    window.history.replaceState(null, "", workbenchUrl(novel.id, undefined, nextSection));
  };

  const confirmDeleteDocument = () => {
    if (!novel || !document) return;
    Modal.confirm({
      className: "anw-modal anw-delete-document-confirm",
      title: "删除章节",
      content: `确认删除《${document.title}》吗？删除后将返回章节列表。`,
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
      h(Button, { onClick: () => { clearWorkbenchRoute(); window.location.assign(CREATIVE_CENTER_CHAT_PATH); } }, "打开创作中心"),
    );
  }

  if (editorOpen && document) {
    const orderedChapters = novel
      ? [...novel.tree]
          .sort((left: VolumeRecord, right: VolumeRecord) => left.position - right.position)
          .flatMap((volume: VolumeRecord) => [...volume.documents].sort((left: DocumentRecord, right: DocumentRecord) => left.position - right.position))
          .filter((item: DocumentRecord) => item.kind === "chapter")
      : [];
    const currentChapterIndex = orderedChapters.findIndex((item: DocumentRecord) => item.id === document.id);
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
                    const volumeLabel = item.volume.id ? item.volume.title : "未分卷";
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
    const bodyEditor = h("textarea", {
      ref: editorTextareaRef,
      className: "anw-editor-textarea",
      value: content,
      onChange: onContentChange,
      onFocus: () => assistantBodyBindingRef.current?.setFocusedField(true),
      onBlur: () => assistantBodyBindingRef.current?.setFocusedField(false),
      spellCheck: false,
      "aria-label": `${chapterDisplayTitle}正文编辑器`,
      placeholder: "开始写作……Markdown 源文本会自动保存。",
    });
    const titleEditorForm = h(
      "div",
      { className: "anw-title-edit-form" },
      h("label", { htmlFor: "anw-document-title-input" }, document.kind === "chapter" ? "章节标题" : "文档标题"),
      h(Input, {
        ref: (node: AssistantTitleInputRef | null) => {
          titleInputRef.current = node;
          titleInputNativeRef.current = node?.input ?? null;
        },
        id: "anw-document-title-input",
        autoFocus: true,
        size: "large",
        value: titleDraft,
        maxLength: 20,
        placeholder: document.kind === "chapter" ? "请输入章节标题" : "请输入文档标题",
        onChange: (event: any) => updateTitleDraft(event.target.value as string),
        onFocus: (event: { currentTarget: AssistantTextControl }) => {
          titleInputNativeRef.current = event.currentTarget;
          assistantTitleBindingRef.current?.setFocusedField(CHAPTER_TITLE_FIELD_ID);
        },
        onSelect: (event: { currentTarget: AssistantTextControl }) => {
          titleInputNativeRef.current = event.currentTarget;
        },
        onBlur: () => assistantTitleBindingRef.current?.setFocusedField(undefined),
        onPressEnter: () => { if (titleDraftRef.current.trim() && !titleSaving) void renameDocument(); },
      }),
      h("p", { className: "anw-title-edit-count" }, `最多20字，当前：${titleDraft.length}/20`),
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
          disabled: !titleDraft.trim(),
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
          { className: "anw-editor-content" },
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
              ...novel.tree.filter((volume: VolumeRecord) => volume.id).map((volume: VolumeRecord, index: number) => h(
                "button",
                {
                  key: volume.id,
                  type: "button",
                  disabled: busy,
                  onClick: () => confirmSaveChapterToVolume(volume.id),
                },
                h("strong", null, /^第[^卷]*卷(?:\s|$)/.test(volume.title.trim()) ? volume.title.trim() : `第${index + 1}卷 ${volume.title.replace(/^第[^卷]*卷\s*/, "").trim()}`),
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
    onSectionChange: (next: WorkbenchSection) => { void switchSection(next); },
    onSelectDocument: selectDocument,
    onNovelChanged: (updated: NovelRecord) => setNovel(updated),
    onReload: refreshNovel,
    openChapterWizardSignal,
    onBack: () => { clearWorkbenchRoute(); window.location.assign(CREATIVE_CENTER_CHAT_PATH); },
    onError: setError,
    assistantWorkspaceLayout: props.assistantWorkspaceLayout,
    selectionEditReviewHost: props.selectionEditReviewHost,
  });

  const chapterDocuments = (novel?.tree ?? []).flatMap((volume: VolumeRecord) => volume.documents)
    .filter((item: DocumentRecord) => item.kind === "chapter");
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
      const volumeTiles = (novel?.tree ?? []).filter(
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
                return h(
                  "article",
                  { key: volume.id ?? "ungrouped", className: "anw-volume-tile" },
                  h("div", { className: "anw-volume-index" }, volume.id ? String(volumeIndex + 1).padStart(2, "0") : "—"),
                  h("div", { className: "anw-volume-name" }, volume.title),
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
              ...volumeTiles.map((volume: VolumeRecord) => {
                const volumeChapters = volume.documents.filter((item: DocumentRecord) => item.kind === "chapter");
                return h(
                  "section",
                  { key: `chapters:${volume.id ?? "ungrouped"}`, className: "anw-chapter-volume-section" },
                  h(
                    "div",
                    { className: "anw-chapter-group-header" },
                    h("strong", null, volume.title),
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
                          h("span", { className: "anw-chapter-row-title" }, item.title),
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
          novel ? novelCover(novel.title, "anw-book-cover-large") : null,
          h("h1", { className: "anw-book-title" }, novel?.title ?? "加载中"),
          h("div", { className: "anw-book-description" }, novel?.description || "长篇小说创作项目"),
          h("div", { className: "anw-book-counts" }, h("span", null, `${chapterDocuments.length} 章节`), h("span", null, `${chapterDocuments.reduce((sum: number, item: DocumentRecord) => sum + item.visible_character_count, 0)} 字`)),
        ),
        h(
          "nav",
          { className: "anw-project-nav", "aria-label": "作品创作流程" },
          ...(["chapters", "outline", "roles", "clues", "settings"] as ProjectSection[]).map((item) => {
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
            h(Button, { onClick: () => { clearWorkbenchRoute(); window.location.assign(CREATIVE_CENTER_CHAT_PATH); } }, "返回创作中心"),
            section === "chapters" ? h(Button, { onClick: createVolume }, "+ 新增分卷") : null,
            section === "chapters" ? h(Button, { className: "anw-primary-button", icon: h(PlusOutlined), onClick: createChapter }, "新建章节") : null,
          ),
        ),
        h("div", { className: "anw-panel-body" }, renderPanelBody()),
      ),
    ),
  );
}
