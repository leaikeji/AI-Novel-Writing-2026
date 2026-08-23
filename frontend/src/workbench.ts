import { ApiError, apiRequest } from "./api";
import { APP_PATH } from "./contracts";
import {
  clearRecoveryDraft,
  loadRecoveryDraft,
  RecoveryDraft,
  saveRecoveryDraft,
} from "./recovery";
import { workbenchStore } from "./store";
import { DocumentRecord, NovelRecord, NovelSummary, VolumeRecord } from "./types";
import {
  activeWorkbenchRoute,
  clearWorkbenchRoute,
  rememberWorkbenchRoute,
} from "./workbench-route";


const host = window.QwenPaw.host;
const React = host.React;
const {
  Alert,
  Button,
  Card,
  Divider,
  Empty,
  Input,
  List,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} = host.antd;


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


function workbenchUrl(novelId: string, documentId?: string): string {
  rememberWorkbenchRoute(novelId, documentId);
  const query = new URLSearchParams({ novel_workbench: "1", novel_id: novelId });
  if (documentId) query.set("document_id", documentId);
  return `/chat?${query.toString()}`;
}


function firstDocument(novel: NovelRecord): DocumentRecord | undefined {
  return novel.tree.flatMap((volume) => volume.documents).find((document) => document.kind === "chapter")
    ?? novel.tree.flatMap((volume) => volume.documents)[0];
}


export function NovelLibraryPage() {
  const [novels, setNovels] = React.useState([] as NovelSummary[]);
  const [title, setTitle] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
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

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const createNovel = async () => {
    if (!title.trim()) return;
    setCreating(true);
    try {
      const novel = await apiRequest<NovelRecord>("/novels", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), description: "" }),
      });
      const document = firstDocument(novel);
      window.location.assign(workbenchUrl(novel.id, document?.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建作品失败");
    } finally {
      setCreating(false);
    }
  };

  return React.createElement(
    "main",
    { style: { minHeight: "100%", padding: 28, overflow: "auto" } },
    React.createElement(
      Space,
      { direction: "vertical", size: 20, style: { width: "100%", maxWidth: 1100, margin: "0 auto" } },
      React.createElement(Typography.Title, { level: 2, style: { margin: 0 } }, "AI小说世界2026"),
      React.createElement(
        Typography.Text,
        { type: "secondary" },
        "创建作品、编辑章节并自动保存；AI 讨论继续使用 QwenPaw 原生助手。",
      ),
      error ? React.createElement(Alert, { type: "error", showIcon: true, message: error }) : null,
      React.createElement(
        Card,
        { title: "新建小说" },
        React.createElement(
          Space,
          { style: { width: "100%" } },
          React.createElement(Input, {
            placeholder: "小说名称",
            value: title,
            maxLength: 240,
            onChange: (event: any) => setTitle(event.target.value),
            onPressEnter: createNovel,
            style: { width: 360 },
          }),
          React.createElement(
            Button,
            { type: "primary", loading: creating, disabled: !title.trim(), onClick: createNovel },
            "创建并开始写作",
          ),
        ),
      ),
      React.createElement(
        Card,
        { title: `我的作品（${novels.length}）` },
        loading
          ? React.createElement(Spin)
          : novels.length === 0
            ? React.createElement(Empty, { description: "还没有小说" })
            : React.createElement(List, {
                dataSource: novels,
                renderItem: (novel: NovelSummary) =>
                  React.createElement(
                    List.Item,
                    {
                      actions: [
                        React.createElement(
                          Button,
                          { type: "link", onClick: () => window.location.assign(workbenchUrl(novel.id)) },
                          "打开工作台",
                        ),
                      ],
                    },
                    React.createElement(List.Item.Meta, {
                      title: novel.title,
                      description: `${novel.chapter_count} 章 · ${novel.visible_character_count} 字`,
                    }),
                  ),
              }),
      ),
    ),
  );
}


interface ConflictDetail {
  current: DocumentRecord;
}


export function NovelWorkbench() {
  const [novel, setNovel] = React.useState(null as NovelRecord | null);
  const [document, setDocument] = React.useState(null as DocumentRecord | null);
  const [content, setContent] = React.useState("");
  const [saveState, setSaveState] = React.useState("正在加载…");
  const [error, setError] = React.useState("");
  const [conflict, setConflict] = React.useState(null as DocumentRecord | null);
  const [recovery, setRecovery] = React.useState(null as RecoveryDraft | null);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const timerRef = React.useRef(null as ReturnType<typeof setTimeout> | null);
  const documentRef = React.useRef(null as DocumentRecord | null);
  const contentRef = React.useRef("");

  const query = currentQuery();
  const queryNovelId = query.get("novel_id");
  const queryDocumentId = query.get("document_id");

  const loadDocument = React.useCallback(async (documentId: string) => {
    setBusy(true);
    try {
      const loaded = await apiRequest<DocumentRecord>(`/documents/${documentId}`);
      documentRef.current = loaded;
      contentRef.current = loaded.content_markdown;
      setDocument(loaded);
      setContent(loaded.content_markdown);
      setConflict(null);
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
      const selected = loaded.tree
        .flatMap((volume) => volume.documents)
        .find((item) => item.id === queryDocumentId) ?? firstDocument(loaded);
      if (selected) await loadDocument(selected.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载小说失败");
    } finally {
      setBusy(false);
    }
  }, [loadDocument, queryDocumentId]);

  React.useEffect(() => {
    if (queryNovelId) void loadNovel(queryNovelId);
  }, [loadNovel, queryNovelId]);

  const saveNow = React.useCallback(async (markdown: string): Promise<DocumentRecord | null> => {
    const active = documentRef.current;
    if (!active) return null;
    setSaveState("正在保存…");
    try {
      const saved = await apiRequest<DocumentRecord>(`/documents/${active.id}/draft`, {
        method: "PATCH",
        body: JSON.stringify({
          expected_draft_version: active.draft_version,
          content_markdown: markdown,
        }),
      });
      documentRef.current = saved;
      setDocument(saved);
      if (contentRef.current === markdown) {
        setSaveState("已保存");
        await clearRecoveryDraft(saved.id);
      } else {
        setSaveState("有新内容待保存");
        timerRef.current = setTimeout(() => void saveNow(contentRef.current), 100);
      }
      return saved;
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        const detail = reason.detail as ConflictDetail;
        setConflict(detail.current);
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

  const selectDocument = (documentId: string) => {
    const active = documentRef.current;
    if (active && contentRef.current !== active.content_markdown) void saveNow(contentRef.current);
    void loadDocument(documentId);
  };

  const refreshNovel = async () => {
    if (novel) await loadNovel(novel.id);
  };

  const createChapter = async () => {
    if (!novel) return;
    const documents = novel.tree
      .flatMap((volume: VolumeRecord) => volume.documents)
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
      body: JSON.stringify({
        title: `第${novel.tree.filter((item: VolumeRecord) => item.id).length + 1}卷`,
      }),
    });
    await refreshNovel();
  };

  const checkpoint = async () => {
    const saved = await saveNow(contentRef.current);
    if (!saved) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ document: DocumentRecord }>(
        `/documents/${saved.id}/checkpoints`,
        {
          method: "POST",
          body: JSON.stringify({ expected_draft_version: saved.draft_version }),
        },
      );
      documentRef.current = result.document;
      setDocument(result.document);
      setSaveState("检查点已建立");
    } finally {
      setBusy(false);
    }
  };

  const restore = async (revisionId: string) => {
    const active = documentRef.current;
    if (!active) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ document: DocumentRecord }>(
        `/documents/${active.id}/revisions/${revisionId}/restore`,
        {
          method: "POST",
          body: JSON.stringify({ expected_draft_version: active.draft_version }),
        },
      );
      documentRef.current = result.document;
      contentRef.current = result.document.content_markdown;
      setDocument(result.document);
      setContent(result.document.content_markdown);
      setHistoryOpen(false);
      setSaveState("已恢复为新版本");
      await clearRecoveryDraft(result.document.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "恢复失败");
    } finally {
      setBusy(false);
    }
  };

  const copyContext = async () => {
    if (!novel || !document) return;
    const text = [
      `当前小说：${novel.title}`,
      `novel_id: ${novel.id}`,
      `当前文档：${document.title}`,
      `document_id: ${document.id}`,
      "请按需调用 novel_get_context、novel_get_document 或 novel_search；不要修改正文。",
    ].join("\n");
    await navigator.clipboard.writeText(text);
    setSaveState("AI 上下文标识已复制");
  };

  if (!queryNovelId) {
    return React.createElement(
      "section",
      { style: { padding: 24 } },
      React.createElement(Empty, { description: "请先选择一本小说" }),
      React.createElement(Button, { onClick: () => { clearWorkbenchRoute(); window.location.assign(APP_PATH); } }, "打开作品库"),
    );
  }

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
    const recoveredMarkdown = recovery.contentMarkdown;
    setContent(recoveredMarkdown);
    contentRef.current = recoveredMarkdown;
    setRecovery(null);
    setSaveState("已恢复本地草稿，正在同步");
    void saveNow(recoveredMarkdown);
  };

  return React.createElement(
    Spin,
    { spinning: busy },
    React.createElement(
      "div",
      { style: { display: "grid", gridTemplateColumns: "220px minmax(0, 1fr)", height: "100%" } },
      React.createElement(
        "aside",
        { style: { borderRight: "1px solid var(--ant-color-border-secondary, #303030)", padding: 12, overflow: "auto" } },
        React.createElement(
          Button,
          {
            type: "text",
            onClick: () => { clearWorkbenchRoute(); window.location.assign(APP_PATH); },
            style: { paddingInline: 0 },
          },
          "← 作品库",
        ),
        React.createElement(Typography.Title, { level: 4, ellipsis: true }, novel?.title ?? "加载中"),
        React.createElement(
          Space,
          { size: 4, wrap: true },
          React.createElement(Button, { size: "small", onClick: createChapter }, "+ 章节"),
          React.createElement(Button, { size: "small", onClick: createVolume }, "+ 分卷"),
        ),
        React.createElement(Divider, { style: { marginBlock: 12 } }),
        ...(novel?.tree ?? []).map((volume: VolumeRecord) =>
          React.createElement(
            "div",
            { key: volume.id ?? "ungrouped", style: { marginBottom: 14 } },
            React.createElement(Typography.Text, { strong: true }, volume.title),
            ...volume.documents.map((item) =>
              React.createElement(
                Button,
                {
                  key: item.id,
                  type: item.id === document?.id ? "primary" : "text",
                  block: true,
                  onClick: () => selectDocument(item.id),
                  style: { marginTop: 4, textAlign: "left", overflow: "hidden" },
                },
                item.title,
              ),
            ),
          ),
        ),
      ),
      React.createElement(
        "main",
        { style: { minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", padding: "14px 18px" } },
        error ? React.createElement(Alert, { type: "error", closable: true, message: error, onClose: () => setError("") }) : null,
        recovery
          ? React.createElement(Alert, {
              type: "warning",
              showIcon: true,
              message: "发现未同步的崩溃恢复草稿",
              action: React.createElement(Button, { size: "small", onClick: recoverLocal }, "恢复本地稿"),
              style: { marginBottom: 8 },
            })
          : null,
        conflict
          ? React.createElement(Alert, {
              type: "error",
              showIcon: true,
              message: "服务器版本已经变化，未覆盖正文",
              action: React.createElement(Button, { size: "small", onClick: loadServerConflict }, "载入服务器版"),
              style: { marginBottom: 8 },
            })
          : null,
        React.createElement(
          "header",
          { style: { display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 10 } },
          React.createElement(
            Typography.Title,
            { level: 3, style: { margin: 0, flex: "1 1 180px", minWidth: 120 } },
            document?.title ?? "选择章节",
          ),
          React.createElement(Tag, { color: saveState.includes("失败") || saveState.includes("冲突") ? "error" : "default" }, saveState),
          React.createElement(Typography.Text, { type: "secondary" }, `${document?.visible_character_count ?? 0} 字`),
          React.createElement(
            "div",
            { style: { display: "flex", flex: "1 0 100%", flexWrap: "wrap", justifyContent: "flex-end", gap: 8 } },
            React.createElement(Button, { onClick: copyContext, disabled: !document }, "复制 AI 上下文"),
            React.createElement(Button, { onClick: () => setHistoryOpen(true), disabled: !document }, "历史"),
            React.createElement(Button, { type: "primary", onClick: checkpoint, disabled: !document }, "建立检查点"),
          ),
        ),
        React.createElement("textarea", {
          value: content,
          onChange: onContentChange,
          spellCheck: false,
          placeholder: "开始写作……Markdown 源文本会自动保存。",
          style: {
            flex: 1,
            minHeight: 360,
            width: "100%",
            resize: "none",
            border: "1px solid var(--ant-color-border, #424242)",
            borderRadius: 8,
            outline: "none",
            padding: "24px 28px",
            background: "var(--ant-color-bg-container, #141414)",
            color: "var(--ant-color-text, #fff)",
            font: "17px/1.9 ui-serif, STSong, Songti SC, serif",
            boxSizing: "border-box",
          },
        }),
        React.createElement(
          Typography.Text,
          { type: "secondary", style: { marginTop: 8 } },
          document ? `novel_id ${document.novel_id} · document_id ${document.id}` : "",
        ),
        React.createElement(
          Modal,
          { open: historyOpen, title: "版本历史", footer: null, onCancel: () => setHistoryOpen(false) },
          document?.revisions?.length
            ? React.createElement(List, {
                dataSource: document.revisions,
                renderItem: (revision: any) =>
                  React.createElement(
                    List.Item,
                    {
                      actions: [
                        React.createElement(
                          Button,
                          { size: "small", onClick: () => restore(revision.id) },
                          "恢复为新版本",
                        ),
                      ],
                    },
                    React.createElement(List.Item.Meta, {
                      title: `版本 ${revision.revision_number}`,
                      description: `${revision.source} · ${revision.visible_character_count} 字`,
                    }),
                  ),
              })
            : React.createElement(Empty, { description: "暂无版本" }),
        ),
      ),
    ),
  );
}
