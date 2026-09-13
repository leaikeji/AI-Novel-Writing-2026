import type {
  LibraryCheckHit,
  LibraryCheckReport,
  LibraryQueryFilters,
  PrivateLibraryCategory,
} from "./contracts";
import {
  LEXICON_ACTION_LABEL,
  PRIVATE_LIBRARY_CATEGORIES,
  PRIVATE_LIBRARY_CATEGORY_META,
  assetDraftFromView,
  entryDraftFromEntry,
  filterPrivateLibraryAssets,
  newAssetDraft,
  newEntryDraft,
  splitTags,
  type LexiconEntryDraft,
  type LibraryEnabledFilter,
  type LibraryScopeFilter,
  type PrivateLibraryAssetDraft,
  type PrivateLibraryAssetView,
} from "./model";
import type {
  FocusHandle,
  InputChangeEvent,
  KeyboardEventLike,
  PrivateLibraryAntdRuntime,
  PrivateLibraryReactRuntime,
} from "./ui-runtime";


export interface ActiveLibraryNovel {
  readonly id: string;
  readonly title: string;
}


export interface PrivateLibraryAssetHistoryItem {
  readonly id: string;
  readonly version_number: number;
  readonly title: string;
  readonly content_hash: string;
  readonly created_at: string | null;
  readonly current: boolean;
}


export interface PrivateLibraryWorkspaceProps {
  readonly assets: readonly PrivateLibraryAssetView[];
  readonly activeNovel?: ActiveLibraryNovel | null;
  readonly selectedAssetId?: string | null;
  readonly filters?: LibraryQueryFilters;
  readonly onFiltersChange?: (filters: LibraryQueryFilters) => void;
  readonly total?: number;
  readonly selectedAsset?: PrivateLibraryAssetView | null;
  readonly detailLoading?: boolean;
  readonly detailError?: string | null;
  readonly checkReport?: LibraryCheckReport | null;
  readonly history?: readonly PrivateLibraryAssetHistoryItem[];
  readonly historyLoading?: boolean;
  readonly loading?: boolean;
  readonly hasMore?: boolean;
  readonly loadError?: string | null;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly initialCategory?: PrivateLibraryCategory;
  readonly onRefresh: () => void | Promise<void>;
  readonly onLoadMore?: () => void | Promise<void>;
  readonly onSelectAsset?: (assetId: string) => void;
  readonly onSaveAsset: (draft: PrivateLibraryAssetDraft) => void | Promise<void>;
  readonly onSaveEntry: (
    assetId: string,
    draft: LexiconEntryDraft,
  ) => void | Promise<void>;
  readonly onToggleEnabled: (
    asset: PrivateLibraryAssetView,
    enabled: boolean,
  ) => void | Promise<void>;
  readonly onLocateHit: (hit: LibraryCheckHit) => void;
  readonly onSetArchived?: (
    asset: PrivateLibraryAssetView,
    archived: boolean,
  ) => void | Promise<void>;
  readonly onRestoreVersion?: (
    asset: PrivateLibraryAssetView,
    version: PrivateLibraryAssetHistoryItem,
  ) => void | Promise<void>;
}


type EditorState =
  | { readonly kind: "asset"; readonly draft: PrivateLibraryAssetDraft }
  | { readonly kind: "entry"; readonly assetId: string; readonly draft: LexiconEntryDraft };

interface EditorSession {
  readonly contextKey: string;
  readonly novel: ActiveLibraryNovel | null;
  readonly targetAssetId: string | null;
  pending: boolean;
  saved: boolean;
}


const SCOPE_OPTIONS = [
  { value: "all", label: "全部范围" },
  { value: "library", label: "通用库" },
  { value: "novel", label: "本书专用" },
] as const;


const ENABLED_OPTIONS = [
  { value: "all", label: "全部状态" },
  { value: "enabled", label: "已启用" },
  { value: "disabled", label: "未启用" },
] as const;


const CHECK_STATUS_LABEL: Readonly<Record<LibraryCheckReport["status"], string>> = {
  complete: "检查完成",
  incomplete: "检查未完成，部分规则尚未扫描",
  stale: "规则或正文已变化，请重新检查",
  failed: "检查失败，正文未被修改",
};


function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}


function promiseFrom(value: void | Promise<void>): Promise<void> {
  return Promise.resolve(value);
}


export function createPrivateLibraryWorkspace(
  React: PrivateLibraryReactRuntime,
  antd: PrivateLibraryAntdRuntime,
): (props: PrivateLibraryWorkspaceProps) => unknown {
  const h = React.createElement;
  const { Alert, Button, Card, Drawer, Empty, Input, Select, Spin, Switch, Tag } = antd;

  return function PrivateLibraryWorkspace(props: PrivateLibraryWorkspaceProps): unknown {
    const [localCategory, setCategory] = React.useState<PrivateLibraryCategory>(
      props.initialCategory ?? "vocabulary",
    );
    const [localQuery, setQuery] = React.useState("");
    const [localScope, setScope] = React.useState<LibraryScopeFilter>("all");
    const [localEnabled, setEnabled] = React.useState<LibraryEnabledFilter>("all");
    const [localSelectedId, setLocalSelectedId] = React.useState<string | null>(null);
    const [editor, setEditor] = React.useState<EditorState | null>(null);
    const [saving, setSaving] = React.useState(false);
    const [saveError, setSaveError] = React.useState<string | null>(null);
    const [saveNotice, setSaveNotice] = React.useState<string | null>(null);
    const tabRefs = React.useRef<Array<FocusHandle | null>>([]);
    const returnFocusRef = React.useRef<FocusHandle | null>(null);
    const editorInputRef = React.useRef<FocusHandle | null>(null);
    const editorSessionRef = React.useRef<EditorSession | null>(null);

    const filters: LibraryQueryFilters = props.filters ?? {
      category: localCategory, query: localQuery, scope: localScope, enabled: localEnabled,
    };
    const { category, query, scope, enabled } = filters;
    const changeFilters = (patch: Partial<LibraryQueryFilters>) => {
      const next = { ...filters, ...patch };
      if (props.filters) props.onFiltersChange?.(next);
      else {
        setCategory(next.category);
        setQuery(next.query);
        setScope(next.scope);
        setEnabled(next.enabled);
      }
    };
    // A server-filtered summary page need not contain the matching entry text.
    const filtered = props.filters
      ? props.assets
      : filterPrivateLibraryAssets(props.assets, filters);
    const requestedSelectedId = props.selectedAssetId ?? localSelectedId;
    const selectedSummary = filtered.find((asset) => asset.id === requestedSelectedId)
      ?? filtered[0]
      ?? null;
    const selected = props.selectedAsset && props.selectedAsset.id === selectedSummary?.id
      ? props.selectedAsset
      : selectedSummary;
    const detailReady = selected !== null && selected.detail_loaded !== false
      && !props.detailLoading && !props.detailError;
    const busy = props.disabled === true || saving;
    const contextKey = JSON.stringify([
      props.activeNovel?.id ?? null, category, query, scope, enabled,
      filters.includeArchived === true, requestedSelectedId ?? null, selected?.id ?? null,
      selected?.current_version_id ?? null,
    ]);
    const currentContextRef = React.useRef(contextKey);
    currentContextRef.current = contextKey;
    const editorSession = editorSessionRef.current;
    const editorContextChanged = editor !== null && editorSession?.contextKey !== contextKey;
    const editorNovel = editorSession?.novel ?? null;

    React.useEffect(() => {
      if (!selected || selected.id === requestedSelectedId) return;
      setLocalSelectedId(selected.id);
      props.onSelectAsset?.(selected.id);
    }, [selected?.id, requestedSelectedId]);

    const selectAsset = (assetId: string) => {
      setLocalSelectedId(assetId);
      props.onSelectAsset?.(assetId);
    };

    const openEditor = (state: EditorState, trigger?: FocusHandle | null) => {
      if (editorSessionRef.current) {
        setSaveError("请先处理当前表单，输入仍保留；关闭前可选中文字复制。");
        editorInputRef.current?.focus();
        return;
      }
      const targetAssetId = state.kind === "entry" ? state.assetId : state.draft.assetId ?? null;
      editorSessionRef.current = {
        contextKey,
        novel: props.activeNovel ? { ...props.activeNovel } : null,
        targetAssetId, pending: false, saved: false,
      };
      returnFocusRef.current = trigger ?? null;
      setSaveError(null);
      setSaveNotice(null);
      setEditor(state);
    };

    const closeEditor = () => {
      if (editorSessionRef.current?.pending) return;
      editorSessionRef.current = null;
      setEditor(null);
      setSaveError(null);
      setSaveNotice(null);
      setSaving(false);
      returnFocusRef.current?.focus();
    };

    const saveEditor = () => {
      const session = editorSessionRef.current;
      if (!editor || !session || session !== editorSession || session.pending || session.saved) return;
      const targetAssetId = editor.kind === "entry" ? editor.assetId : editor.draft.assetId ?? null;
      if (session.contextKey !== currentContextRef.current || targetAssetId !== session.targetAssetId) {
        setSaveError("当前作品、筛选或选中资料已变化，不能把原表单保存到新范围。输入仍保留，可复制，或返回原上下文后保存。");
        return;
      }
      const invalidAsset = editor.kind === "asset" && (
        !editor.draft.title.trim()
        || (editor.draft.scopeKind === "novel" && !editor.draft.scopeNovelId)
      );
      const invalidEntry = editor.kind === "entry" && !editor.draft.term.trim();
      if (invalidAsset || invalidEntry) {
        setSaveError(invalidEntry ? "请输入词或短语。" : "请填写名称并确认保存范围。");
        editorInputRef.current?.focus();
        return;
      }
      session.pending = true;
      setSaving(true);
      setSaveError(null);
      setSaveNotice(null);
      let operation: void | Promise<void>;
      try {
        operation = editor.kind === "asset"
          ? props.onSaveAsset(editor.draft)
          : props.onSaveEntry(editor.assetId, editor.draft);
      } catch (error: unknown) {
        operation = Promise.reject(error);
      }
      void promiseFrom(operation).then(() => {
        if (editorSessionRef.current !== session) return;
        session.pending = false;
        session.saved = true;
        setSaving(false);
        if (currentContextRef.current === session.contextKey) closeEditor();
        else setSaveNotice("资料已按原范围保存。当前界面已变化，原输入继续保留，可复制后关闭；不会重复保存到当前作品。");
      }).catch((error: unknown) => {
        if (editorSessionRef.current !== session) return;
        session.pending = false;
        setSaving(false);
        setSaveError(error instanceof Error ? error.message : "保存失败，请重试。");
      });
    };

    const moveCategoryFocus = (index: number, event: KeyboardEventLike) => {
      let target = index;
      if (event.key === "ArrowRight") target = (index + 1) % PRIVATE_LIBRARY_CATEGORIES.length;
      else if (event.key === "ArrowLeft") {
        target = (index - 1 + PRIVATE_LIBRARY_CATEGORIES.length) % PRIVATE_LIBRARY_CATEGORIES.length;
      } else if (event.key === "Home") target = 0;
      else if (event.key === "End") target = PRIVATE_LIBRARY_CATEGORIES.length - 1;
      else return;
      event.preventDefault();
      changeFilters({ category: PRIVATE_LIBRARY_CATEGORIES[target]! });
      tabRefs.current[target]?.focus();
    };

    const renderAssetList = (): unknown => {
      if (props.loading && props.assets.length === 0) {
        return h("div", { className: "anw-private-library__loading", role: "status" }, h(Spin), "正在加载私有库…");
      }
      if (filtered.length === 0) {
        if (props.loadError) return h("p", { role: "status" }, "资料列表尚未加载，请重新加载。");
        if (props.hasMore) return h("p", { role: "status" }, "当前已加载资料没有匹配项，可继续加载。");
        const filteredEmpty = Boolean(query.trim()) || scope !== "all" || enabled !== "all";
        return h(
          "div",
          { className: "anw-private-library__empty" },
          h(Empty, {
            description: filteredEmpty
              ? "没有符合当前筛选的资料。"
              : PRIVATE_LIBRARY_CATEGORY_META[category].empty,
          }),
          filteredEmpty
            ? h(Button, {
                type: "link",
                onClick: () => {
                  changeFilters({ query: "", scope: "all", enabled: "all" });
                },
              }, "清除筛选")
            : null,
        );
      }
      return h(
        "div",
        { className: "anw-private-library__asset-list", role: "list" },
        ...filtered.map((asset) => h(
          Card,
          {
            key: asset.id,
            className: classNames(
              "anw-private-library__asset-card",
              selected?.id === asset.id && "is-selected",
            ),
            role: "listitem",
          },
          h(
            "button",
            {
              type: "button",
              className: "anw-private-library__asset-select",
              "aria-pressed": selected?.id === asset.id,
              onClick: () => selectAsset(asset.id),
            },
            h("strong", null, asset.title),
            h("span", null, asset.asset_type === "vocabulary"
              ? `${asset.entry_count ?? asset.lexicon?.entries.length ?? 0} 个词项`
              : asset.summary || "暂无摘要"),
          ),
          h(
            "div",
            { className: "anw-private-library__asset-meta" },
            h(Tag, { color: asset.scope_kind === "novel" ? "purple" : "default" },
              asset.scope_kind === "novel" ? "本书专用" : "通用库"),
            h(Tag, { color: asset.enabled ? "green" : "default" }, asset.enabled ? "已启用" : "未启用"),
            asset.archived ? h(Tag, null, "已归档") : null,
            h("span", null, `v${asset.version}`),
          ),
        )),
      );
    };

    const renderLexiconEntries = (asset: PrivateLibraryAssetView): unknown => {
      const entries = asset.lexicon?.entries ?? [];
      return h(
        "section",
        { className: "anw-private-library__entries", "aria-labelledby": "anw-private-library-entry-title" },
        h(
          "div",
          { className: "anw-private-library__section-title" },
          h("h3", { id: "anw-private-library-entry-title" }, `词项（${entries.length}）`),
          h(Button, {
            disabled: busy || asset.archived,
            onClick: (event: { currentTarget?: FocusHandle }) => openEditor(
              { kind: "entry", assetId: asset.id, draft: newEntryDraft() },
              event.currentTarget,
            ),
          }, "添加词项"),
        ),
        entries.length === 0
          ? h(Empty, { description: "这个词包还没有词项。" })
          : h(
              "ul",
              { className: "anw-private-library__entry-list" },
              ...entries.map((entry) => h(
                "li",
                { key: entry.entry_id, "data-entry-id": entry.entry_id },
                h("div", null,
                  h("strong", null, entry.term),
                  h(Tag, { color: entry.action === "forbid" ? "red" : entry.action === "watch" ? "orange" : "green" }, LEXICON_ACTION_LABEL[entry.action]),
                  entry.state === "inactive" ? h(Tag, null, "已停用") : null,
                ),
                entry.note ? h("p", null, entry.note) : null,
                h(Button, {
                  type: "link",
                  disabled: busy || asset.archived,
                  onClick: (event: { currentTarget?: FocusHandle }) => openEditor(
                    { kind: "entry", assetId: asset.id, draft: entryDraftFromEntry(entry) },
                    event.currentTarget,
                  ),
                }, "编辑"),
              )),
            ),
      );
    };

    const renderCheckReport = (): unknown => {
      const report = props.checkReport;
      if (!report) return h(Empty, { description: "还没有检查结果。" });
      return h(
        "section",
        { className: "anw-private-library__check", "aria-labelledby": "anw-private-library-check-title" },
        h("h3", { id: "anw-private-library-check-title" }, "用词检查"),
        h(Alert, {
          type: report.status === "failed" ? "error" : report.status === "complete" ? "success" : "warning",
          showIcon: true,
          message: CHECK_STATUS_LABEL[report.status],
          description: `${report.total_hits} 处命中${report.has_more ? `（当前展示 ${report.hits.length} 处）` : ""}`,
        }),
        report.hits.length === 0
          ? h("p", null, report.status === "complete" && report.total_hits === 0
              ? "当前结果没有命中慎用或禁用词。"
              : "当前页没有命中，不代表完整检查已通过。")
          : h(
              "ol",
              { className: "anw-private-library__hit-list" },
              ...report.hits.map((hit) => h(
                "li",
                { key: hit.hit_id },
                h("div", null,
                  h(Tag, { color: hit.action === "forbid" ? "red" : "orange" }, hit.action === "forbid" ? "禁用" : "慎用"),
                  h("strong", null, hit.matched_text),
                  h("span", null, hit.reason),
                ),
                h(Button, { type: "link", onClick: () => props.onLocateHit(hit) }, "定位原句"),
              )),
            ),
      );
    };

    const renderDetail = (): unknown => {
      if (!selected) return h("div", { className: "anw-private-library__detail-empty" }, "选择一项资料查看详情。");
      return h(
        "article",
        { className: "anw-private-library__detail", "data-asset-id": selected.id },
        h(
          "header",
          { className: "anw-private-library__detail-header" },
          h("div", null,
            h("h2", null, selected.title),
            h("p", null, selected.scope_kind === "novel"
              ? `仅用于${props.activeNovel?.title ?? "指定作品"}`
              : `通用资料 · ${selected.binding_count} 本作品正在使用`),
          ),
          h("div", { className: "anw-private-library__detail-actions" },
            h("label", null,
              h("span", null, selected.enabled ? "已启用" : "未启用"),
              h(Switch, {
                checked: selected.enabled,
                disabled: busy || !props.activeNovel || (selected.archived && !selected.enabled),
                "aria-label": `${selected.title}启用状态`,
                onChange: (checked: boolean) => {
                  if (!busy && props.activeNovel && !(selected.archived && checked)) {
                    void props.onToggleEnabled(selected, checked);
                  }
                },
              }),
            ),
            h(Button, {
              disabled: busy || !detailReady,
              onClick: (event: { currentTarget?: FocusHandle }) => {
                if (detailReady && !busy) openEditor(
                  { kind: "asset", draft: assetDraftFromView(selected) }, event.currentTarget,
                );
              },
            }, "编辑资料"),
            props.onSetArchived
              ? h(Button, {
                  danger: !selected.archived,
                  disabled: busy || !detailReady,
                  onClick: () => { void props.onSetArchived?.(selected, !selected.archived); },
                }, selected.archived ? "恢复资料" : "归档资料")
              : null,
          ),
        ),
        !props.activeNovel ? h("p", null, "进入一部作品后，可管理本书启用状态。") : null,
        selected.archived ? h("p", null, selected.enabled
          ? "资料已归档，本书仍使用固定版本；可直接停用。"
          : "资料已归档，恢复资料后才能重新启用。") : null,
        props.detailError ? h(Alert, { type: "error", showIcon: true, message: "资料详情加载失败", description: props.detailError }) : null,
        !detailReady && !props.detailError
          ? h("div", { role: "status" }, props.detailLoading ? h(Spin) : null, "正在等待资料详情，暂不可编辑。") : null,
        detailReady && selected.summary ? h("p", { className: "anw-private-library__summary" }, selected.summary) : null,
        detailReady && selected.asset_type === "vocabulary" ? renderLexiconEntries(selected) : null,
        detailReady ? h("section", { className: "anw-private-library__history" },
          h("h3", null, "版本历史"),
          props.historyLoading
            ? h(Spin, { size: "small" })
            : !props.history?.length
              ? h("p", null, "暂无历史版本。")
              : h("ol", null, ...props.history.map((version) => h("li", { key: version.id },
                  h("span", null, `v${version.version_number} · ${version.title}`),
                  version.current
                    ? h(Tag, { color: "green" }, "当前")
                    : props.onRestoreVersion
                      ? h(Button, {
                          type: "link",
                          disabled: busy,
                          onClick: () => { void props.onRestoreVersion?.(selected, version); },
                        }, "恢复此版本")
                      : null,
                ))),
        ) : null,
        renderCheckReport(),
      );
    };

    const renderAssetEditor = (draft: PrivateLibraryAssetDraft): unknown => h(
      "div",
      { className: "anw-private-library__editor-fields" },
      h("label", null, h("span", null, "名称"), h(Input, {
        ref: (node: FocusHandle | null) => { editorInputRef.current = node; },
        value: draft.title,
        maxLength: 240,
        "aria-label": "资料名称",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "asset",
          draft: { ...draft, title: event.target.value },
        }),
      })),
      h("label", null, h("span", null, "分类"), h(Select, {
        value: draft.assetType,
        disabled: Boolean(draft.assetId),
        options: PRIVATE_LIBRARY_CATEGORIES.map((value) => ({
          value,
          label: PRIVATE_LIBRARY_CATEGORY_META[value].label,
        })),
        "aria-label": "资料分类",
        onChange: (assetType: PrivateLibraryCategory) => setEditor({
          kind: "asset",
          draft: { ...draft, assetType },
        }),
      })),
      h("label", null, h("span", null, "保存范围"), h(Select, {
        value: draft.scopeKind,
        disabled: Boolean(draft.assetId),
        options: [
          { value: "library", label: "通用库" },
          ...(editorNovel ? [{ value: "novel", label: `本书专用：${editorNovel.title}` }] : []),
        ],
        "aria-label": "资料保存范围",
        onChange: (scopeKind: "library" | "novel") => setEditor({
          kind: "asset",
          draft: {
            ...draft,
            scopeKind,
            scopeNovelId: scopeKind === "novel" ? editorNovel?.id : undefined,
          },
        }),
      })),
      h("label", null, h("span", null, "标签（逗号分隔）"), h(Input, {
        value: draft.tags.join("，"),
        "aria-label": "资料标签",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "asset",
          draft: { ...draft, tags: splitTags(event.target.value) },
        }),
      })),
      h("label", null, h("span", null, "内容摘要"), h(Input.TextArea, {
        value: draft.summary,
        rows: 6,
        maxLength: 30_000,
        "aria-label": "资料内容摘要",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "asset",
          draft: { ...draft, summary: event.target.value },
        }),
      })),
      h("label", null,
        h(Switch, {
          checked: draft.enabled,
          disabled: !editorNovel,
          "aria-label": "保存后启用",
          onChange: (next: boolean) => setEditor({
            kind: "asset",
            draft: { ...draft, enabled: next },
          }),
        }),
        h("span", null, "保存后启用"),
      ),
    );

    const renderEntryEditor = (assetId: string, draft: LexiconEntryDraft): unknown => h(
      "div",
      { className: "anw-private-library__editor-fields", "data-asset-id": assetId },
      h("label", null, h("span", null, "词或短语"), h(Input, {
        ref: (node: FocusHandle | null) => { editorInputRef.current = node; },
        value: draft.term,
        maxLength: 120,
        "aria-label": "词或短语",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "entry",
          assetId,
          draft: { ...draft, term: event.target.value },
        }),
      })),
      h("label", null, h("span", null, "使用方式"), h(Select, {
        value: draft.action,
        options: Object.entries(LEXICON_ACTION_LABEL).map(([value, label]) => ({ value, label })),
        "aria-label": "词项使用方式",
        onChange: (action: LexiconEntryDraft["action"]) => setEditor({
          kind: "entry", assetId, draft: { ...draft, action },
        }),
      })),
      h("label", null, h("span", null, "适用分类（逗号分隔）"), h(Input, {
        value: draft.categories.join("，"),
        "aria-label": "词项适用分类",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "entry", assetId, draft: { ...draft, categories: splitTags(event.target.value) },
        }),
      })),
      h("label", null, h("span", null, "说明"), h(Input.TextArea, {
        value: draft.note,
        rows: 3,
        maxLength: 1_000,
        "aria-label": "词项说明",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "entry", assetId, draft: { ...draft, note: event.target.value },
        }),
      })),
      h("label", null, h("span", null, "替换提示（可选）"), h(Input, {
        value: draft.replacementHint,
        maxLength: 500,
        "aria-label": "词项替换提示",
        onChange: (event: InputChangeEvent) => setEditor({
          kind: "entry", assetId, draft: { ...draft, replacementHint: event.target.value },
        }),
      })),
    );

    return h(
      "section",
      { className: classNames("anw-private-library", props.className), "aria-labelledby": "anw-private-library-title" },
      h(
        "header",
        { className: "anw-private-library__header" },
        h("div", null,
          h("h1", { id: "anw-private-library-title" }, "私有库"),
          h("p", null, "管理用词、文风、叙事机制与灵感；是否用于写作由你明确决定。"),
        ),
        h(Button, {
          type: "primary",
          disabled: busy,
          onClick: (event: { currentTarget?: FocusHandle }) => openEditor(
            { kind: "asset", draft: newAssetDraft(category, props.activeNovel?.id) },
            event.currentTarget,
          ),
        }, `新建${PRIVATE_LIBRARY_CATEGORY_META[category].singular}`),
      ),
      h(
        "div",
        { className: "anw-private-library__categories", role: "tablist", "aria-label": "私有库分类" },
        ...PRIVATE_LIBRARY_CATEGORIES.map((value, index) => h(
          "button",
          {
            key: value,
            ref: (node: FocusHandle | null) => { tabRefs.current[index] = node; },
            type: "button",
            role: "tab",
            id: `anw-private-library-tab-${value}`,
            "aria-selected": category === value,
            tabIndex: category === value ? 0 : -1,
            onClick: () => changeFilters({ category: value }),
            onKeyDown: (event: KeyboardEventLike) => moveCategoryFocus(index, event),
          },
          PRIVATE_LIBRARY_CATEGORY_META[value].label,
        )),
      ),
      h(
        "div",
        { className: "anw-private-library__filters", role: "search" },
        h(Input, {
          value: query,
          allowClear: true,
          placeholder: "搜索名称、标签或词项",
          "aria-label": "搜索私有库",
          onChange: (event: InputChangeEvent) => changeFilters({ query: event.target.value }),
        }),
        h(Select, {
          value: scope,
          options: props.activeNovel ? SCOPE_OPTIONS : SCOPE_OPTIONS.filter((item) => item.value !== "novel"),
          "aria-label": "筛选保存范围",
          onChange: (value: LibraryScopeFilter) => changeFilters({ scope: value }),
        }),
        h(Select, {
          value: enabled,
          disabled: !props.activeNovel,
          options: ENABLED_OPTIONS,
          "aria-label": "筛选启用状态",
          onChange: (value: LibraryEnabledFilter) => changeFilters({ enabled: value }),
        }),
        props.filters ? h("label", null,
          h("input", {
            type: "checkbox",
            checked: filters.includeArchived === true,
            "aria-label": "包含已归档资料",
            onChange: (event: { target: { checked: boolean } }) => changeFilters({ includeArchived: event.target.checked }),
          }), "包含已归档资料",
        ) : null,
        props.loading && props.assets.length > 0 ? h(Spin, { size: "small", "aria-label": "正在刷新" }) : null,
      ),
      props.loadError
        ? h(Alert, {
            type: "error",
            showIcon: true,
            message: "私有库加载失败",
            description: props.loadError,
            action: h(Button, { onClick: () => { void props.onRefresh(); } }, "重新加载"),
          })
        : null,
      h(
        "div",
        { className: "anw-private-library__desktop-layout" },
        h("aside", { className: "anw-private-library__master", "aria-label": "资料列表" },
          props.total !== undefined && !props.loadError
            ? h("p", { role: "status" }, `当前筛选共 ${props.total} 项 · 已加载 ${filtered.length} 项`)
            : null,
          renderAssetList(),
          props.hasMore && props.onLoadMore
            ? h(Button, {
                className: "anw-private-library__load-more", loading: props.loading,
                disabled: busy || props.loading,
                onClick: () => { void props.onLoadMore?.(); },
              }, "继续加载") : null,
        ),
        h("main", { className: "anw-private-library__detail-pane" }, renderDetail()),
      ),
      h(
        Drawer,
        {
          open: editor !== null,
          width: 520,
          destroyOnClose: true,
          closable: !saving,
          keyboard: !saving,
          maskClosable: !saving,
          title: editor?.kind === "entry"
            ? editor.draft.entryId ? "编辑词项" : "添加词项"
            : editor?.draft.assetId ? "编辑资料" : "新建资料",
          onClose: closeEditor,
          afterOpenChange: (open: boolean) => { if (open) editorInputRef.current?.focus(); },
          footer: h("div", { className: "anw-private-library__drawer-footer" },
            h(Button, { disabled: saving, onClick: closeEditor }, "取消"),
            h(Button, {
              type: "primary", loading: saving,
              disabled: saving || editorContextChanged || editorSession?.saved === true,
              onClick: saveEditor,
            }, "保存"),
          ),
        },
        saveError ? h(Alert, { type: "error", showIcon: true, message: saveError }) : null,
        saveNotice ? h(Alert, { type: "success", showIcon: true, message: saveNotice }) : null,
        editorContextChanged ? h(Alert, {
          type: "warning", showIcon: true,
          message: "当前上下文已切换，原表单暂停保存",
          description: `原范围：${editorNovel?.title ?? "通用私有库"}。输入仍保留，可选中文字复制；返回原作品、筛选和资料后可继续，或明确取消后重新打开。`,
        }) : null,
        h("fieldset", { disabled: saving, style: { border: 0, padding: 0, margin: 0 } },
          editor?.kind === "asset" ? renderAssetEditor(editor.draft) : null,
          editor?.kind === "entry" ? renderEntryEditor(editor.assetId, editor.draft) : null,
        ),
      ),
    );
  };
}
