import { ApiError, apiRequest } from "./api";
import { ChapterWorkflowPanel } from "./chapter-workflow";
import { APP_PATH } from "./contracts";
import {
  clearRecoveryDraft,
  loadRecoveryDraft,
  RecoveryDraft,
  saveRecoveryDraft,
} from "./recovery";
import {
  factStatusLabel,
  factTypeLabel,
  isClueFactType,
  revisionSourceLabel,
  selectFactView,
} from "./presenters";
import { workbenchStore } from "./store";
import {
  DocumentRecord,
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
  BookOutlined,
  BulbOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  EditOutlined,
  FileTextOutlined,
  HistoryOutlined,
  HomeOutlined,
  PlusOutlined,
  SaveOutlined,
  SettingOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  UserOutlined,
} = host.antdIcons;


type ProjectSection = "chapters" | "outline" | "roles" | "clues" | "settings";


function currentQuery(): URLSearchParams {
  const query = new URLSearchParams(window.location.search);
  const stored = activeWorkbenchRoute();
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


function novelCover(title: string, className = "anw-cover"): unknown {
  return h(
    "div",
    {
      className: className === "anw-cover" ? "anw-cover-fallback" : "anw-book-cover-empty",
      role: "img",
      "aria-label": `${title}尚未设置封面`,
    },
    h("span", { className: "anw-cover-monogram", "aria-hidden": "true" }, title.slice(0, 1) || "书"),
    h("span", { className: "anw-cover-empty-label" }, "未设置封面"),
  );
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


export function NovelWorkbench() {
  const query = currentQuery();
  const queryNovelId = query.get("novel_id");
  const queryDocumentId = query.get("document_id");
  const initialSection = (query.get("section") as ProjectSection | null) ?? "chapters";

  const [novel, setNovel] = React.useState(null as NovelRecord | null);
  const [document, setDocument] = React.useState(null as DocumentRecord | null);
  const [content, setContent] = React.useState("");
  const [section, setSection] = React.useState(initialSection as ProjectSection);
  const [editorOpen, setEditorOpen] = React.useState(Boolean(queryDocumentId));
  const [saveState, setSaveState] = React.useState("正在加载…");
  const [error, setError] = React.useState("");
  const [conflict, setConflict] = React.useState(null as DocumentRecord | null);
  const [recovery, setRecovery] = React.useState(null as RecoveryDraft | null);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [projectFacts, setProjectFacts] = React.useState([] as StoryFactRecord[]);
  const [projectFactsLoading, setProjectFactsLoading] = React.useState(false);
  const timerRef = React.useRef(null as ReturnType<typeof setTimeout> | null);
  const documentRef = React.useRef(null as DocumentRecord | null);
  const contentRef = React.useRef("");

  const loadDocument = React.useCallback(async (documentId: string) => {
    setBusy(true);
    try {
      const loaded = await apiRequest<DocumentRecord>(`/documents/${documentId}`);
      documentRef.current = loaded;
      contentRef.current = loaded.content_markdown;
      setDocument(loaded);
      setContent(loaded.content_markdown);
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

  const refreshNovel = async () => {
    if (!novel) return;
    const loaded = await apiRequest<NovelRecord>(`/novels/${novel.id}`);
    setNovel(loaded);
  };

  const selectDocument = (documentId: string) => {
    const active = documentRef.current;
    if (active && contentRef.current !== active.content_markdown) void saveNow(contentRef.current);
    void loadDocument(documentId);
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
    setConflict(null);
    setRecovery(null);
    setSaveState(status);
    void clearRecoveryDraft(updated.id);
  };

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

  if (!queryNovelId) {
    return h(
      "section",
      { className: "anw-app anw-empty-state" },
      h("strong", null, "请先选择一本小说"),
      h(Button, { onClick: () => { clearWorkbenchRoute(); window.location.assign(APP_PATH); } }, "打开创作中心"),
    );
  }

  if (editorOpen && document) {
    return h(
      Spin,
      { spinning: busy },
      h(
        "main",
        { className: "anw-app anw-editor" },
        h(
          "header",
          { className: "anw-editor-topbar" },
          h(Button, { type: "text", icon: h(HomeOutlined), onClick: backToProject }, "返回作品"),
          h(
            "div",
            { className: "anw-editor-crumb" },
            novel?.title,
            " / ",
            h("strong", null, document.title),
          ),
          h(
            "span",
            { className: `anw-save-state ${saveState.includes("失败") || saveState.includes("冲突") ? "is-error" : ""}` },
            saveState,
          ),
          h(Button, { icon: h(DatabaseOutlined), onClick: copyContext }, "复制上下文"),
          h(Button, { icon: h(SaveOutlined), className: "anw-primary-button", onClick: checkpoint }, "保存版本"),
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
                h("h1", { className: "anw-editor-title" }, document.title),
                h("div", { className: "anw-editor-count" }, "本章字数 ", h("strong", null, document.visible_character_count), " 字"),
              ),
              h(EditOutlined, { style: { color: "#8a909d", fontSize: 17 } }),
            ),
            h("textarea", {
              className: "anw-editor-textarea",
              value: content,
              onChange: onContentChange,
              spellCheck: false,
              "aria-label": `${document.title}正文编辑器`,
              placeholder: "开始写作……Markdown 源文本会自动保存。",
            }),
          ),
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
                })
              : null,
            h(Button, { icon: h(HistoryOutlined), onClick: () => setHistoryOpen(true) }, "历史"),
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
            h(Button, { onClick: () => { clearWorkbenchRoute(); window.location.assign(APP_PATH); } }, "返回创作中心"),
            section === "chapters" ? h(Button, { onClick: createVolume }, "+ 新增分卷") : null,
            section === "chapters" ? h(Button, { className: "anw-primary-button", icon: h(PlusOutlined), onClick: createChapter }, "新建章节") : null,
          ),
        ),
        h("div", { className: "anw-panel-body" }, renderPanelBody()),
      ),
    ),
  );
}
