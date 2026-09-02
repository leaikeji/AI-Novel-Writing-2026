import {
  apiErrorMessage,
  apiRequest,
  generationModelAuditLabel,
  generationModelLabel,
  generationTaskFromApiError,
  getGenerationModelStatus,
  verifiedGenerationModelLabel,
} from "./api";
import {
  RelationshipGraph,
  RelationshipGraphController,
} from "./relationship-graph";
import { toggleElementFullscreen } from "./relationship-fullscreen";
import { relationshipSyncPresentation } from "./relationship-sync-presentation";
import {
  CharacterRelationshipRecord,
  NovelCharacterRecord,
  RelationshipAutoSyncResponseRecord,
  RelationshipAutoSyncStatusRecord,
  RelationshipDirectionality,
  RelationshipGraphViewRecord,
  RelationshipKind,
} from "./types";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const { Alert, Button, Empty, Modal, Select, Spin } = host.antd;
const {
  ExclamationCircleOutlined,
  ExpandOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  LinkOutlined,
  MinusOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
  SearchOutlined,
} = host.antdIcons;


interface RelationshipWorkspaceProps {
  novelId: string;
  characters: NovelCharacterRecord[];
  relationships: CharacterRelationshipRecord[];
  onEditCharacter: (characterId: string) => void;
  onEditRelationship: (relationshipId: string) => void;
  onAddRelationship: () => void;
  onRelationshipsChanged: (relationships: CharacterRelationshipRecord[]) => void;
}


const EMPTY_VIEW = (novelId: string): RelationshipGraphViewRecord => ({
  id: null,
  novel_id: novelId,
  name: "默认视图",
  layout_algorithm: "force_atlas_2",
  random_seed: `relationship-${novelId}`,
  zoom: 1,
  pan_x: 0,
  pan_y: 0,
  version: 0,
  positions: [],
  updated_at: null,
});


const KIND_OPTIONS: Array<{ label: string; value: "all" | RelationshipKind }> = [
  { label: "全部分类", value: "all" },
  { label: "亲属", value: "family" },
  { label: "同事", value: "colleague" },
  { label: "师徒", value: "mentor" },
  { label: "盟友", value: "ally" },
  { label: "敌对", value: "enemy" },
  { label: "情感", value: "romance" },
  { label: "其他", value: "other" },
];


const DIRECTION_OPTIONS: Array<{
  label: string;
  value: "all" | RelationshipDirectionality;
}> = [
  { label: "全部方向", value: "all" },
  { label: "无向关系", value: "undirected" },
  { label: "有向关系", value: "directed" },
  { label: "方向待确认", value: "legacy_unspecified" },
];


function readError(reason: unknown): string {
  return apiErrorMessage(reason, "关系图操作失败");
}


export function RelationshipWorkspace({
  novelId,
  characters,
  relationships,
  onEditCharacter,
  onEditRelationship,
  onAddRelationship,
  onRelationshipsChanged,
}: RelationshipWorkspaceProps) {
  const [view, setView] = React.useState(EMPTY_VIEW(novelId) as RelationshipGraphViewRecord);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [autoSyncError, setAutoSyncError] = React.useState("");
  const [autoSyncStatus, setAutoSyncStatus] = React.useState(
    null as RelationshipAutoSyncStatusRecord | null,
  );
  const [checkingAutoSync, setCheckingAutoSync] = React.useState(true);
  const [preparingAutoSync, setPreparingAutoSync] = React.useState(false);
  const [confirmingAutoSync, setConfirmingAutoSync] = React.useState(false);
  const [syncingRelationships, setSyncingRelationships] = React.useState(false);
  const [autoSyncModelLabel, setAutoSyncModelLabel] = React.useState("");
  const [scale, setScale] = React.useState(1);
  const [dirty, setDirty] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [focusCharacterId, setFocusCharacterId] = React.useState("");
  const [kindFilter, setKindFilter] = React.useState("all" as "all" | RelationshipKind);
  const [directionFilter, setDirectionFilter] = React.useState(
    "all" as "all" | RelationshipDirectionality,
  );
  const controllerRef = React.useRef(null as RelationshipGraphController | null);
  const canvasShellRef = React.useRef(null as HTMLDivElement | null);
  const syncInFlightRef = React.useRef(false);

  React.useEffect(() => {
    const syncFullscreenState = () => {
      setFullscreen(document.fullscreenElement === canvasShellRef.current);
      window.requestAnimationFrame(() => controllerRef.current?.fit());
    };
    document.addEventListener("fullscreenchange", syncFullscreenState);
    return () => document.removeEventListener("fullscreenchange", syncFullscreenState);
  }, []);

  const syncRelationships = React.useCallback(async (forceNew: boolean) => {
    if (syncInFlightRef.current) return;
    syncInFlightRef.current = true;
    setSyncingRelationships(true);
    setAutoSyncError("");
    try {
      const result = await apiRequest<RelationshipAutoSyncResponseRecord>(
        `/novels/${novelId}/relationships/auto-sync`,
        {
          method: "POST",
          body: JSON.stringify({ force_new: forceNew }),
        },
      );
      setAutoSyncStatus(result.status);
      setAutoSyncModelLabel(
        result.job.state === "ready"
          ? verifiedGenerationModelLabel(result.job)
          : generationModelAuditLabel(result.job),
      );
      onRelationshipsChanged(result.relationships);
    } catch (reason) {
      const failedTask = generationTaskFromApiError(reason);
      if (failedTask) setAutoSyncModelLabel(generationModelAuditLabel(failedTask));
      setAutoSyncError(readError(reason));
    } finally {
      syncInFlightRef.current = false;
      setSyncingRelationships(false);
    }
  }, [novelId, onRelationshipsChanged]);

  const requestRelationshipSync = React.useCallback(async (forceNew: boolean) => {
    if (preparingAutoSync || confirmingAutoSync || syncInFlightRef.current) return;
    setPreparingAutoSync(true);
    setAutoSyncError("");
    try {
      const currentModel = await getGenerationModelStatus();
      const modelLabel = generationModelLabel(currentModel);
      setPreparingAutoSync(false);
      setConfirmingAutoSync(true);
      Modal.confirm({
        title: forceNew ? "确认重新分析全书关系快照" : "确认生成全书关系快照",
        content: `章节写作后的“同步进展”会在你确认候选后自动增量完善关系网，无需每次来这里生成。本次整书分析是可选的初始化/重建操作，将使用 ${modelLabel} 分析当前角色设定、大纲和章节正文；成功后会写入 AI 关系，并可能归档已不符合当前资料的旧 AI 关系。人工关系和正文不会被覆盖，任务会保留 requested/actual 模型证据。`,
        okText: forceNew ? "重新分析" : "开始生成",
        cancelText: "取消",
        onOk: async () => {
          setConfirmingAutoSync(false);
          setAutoSyncModelLabel(`请求 ${modelLabel} · 实际未核验`);
          await syncRelationships(forceNew);
        },
        onCancel: () => setConfirmingAutoSync(false),
      });
    } catch (reason) {
      setAutoSyncError(readError(reason));
      setPreparingAutoSync(false);
      setConfirmingAutoSync(false);
    }
  }, [confirmingAutoSync, preparingAutoSync, syncRelationships]);

  const loadAutoSyncStatus = React.useCallback(async (silent = false) => {
    if (!silent) setCheckingAutoSync(true);
    setAutoSyncError("");
    try {
      const status = await apiRequest<RelationshipAutoSyncStatusRecord>(
        `/novels/${novelId}/relationships/auto-sync/status`,
      );
      setAutoSyncStatus(status);
      setAutoSyncModelLabel(
        status.job
          ? status.job.state === "ready"
            ? verifiedGenerationModelLabel(status.job)
            : generationModelAuditLabel(status.job)
          : "",
      );
    } catch (reason) {
      setAutoSyncError(readError(reason));
    } finally {
      if (!silent) setCheckingAutoSync(false);
    }
  }, [novelId]);

  React.useEffect(() => {
    void loadAutoSyncStatus();
  }, [loadAutoSyncStatus]);

  React.useEffect(() => {
    if (autoSyncStatus?.state !== "running" || syncingRelationships) return undefined;
    const timer = window.setInterval(() => {
      void loadAutoSyncStatus(true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [autoSyncStatus?.state, loadAutoSyncStatus, syncingRelationships]);

  const loadView = React.useCallback(async () => {
    setLoading(true);
    try {
      const next = await apiRequest<RelationshipGraphViewRecord>(
        `/novels/${novelId}/relationship-graph-view`,
      );
      setView(next);
      setScale(next.zoom);
      setDirty(false);
      setError("");
    } catch (reason) {
      setView(EMPTY_VIEW(novelId));
      setError(readError(reason));
    } finally {
      setLoading(false);
    }
  }, [novelId]);

  React.useEffect(() => { void loadView(); }, [loadView]);

  const visibleRelationships = React.useMemo(
    () => relationships.filter((relationship) => (
      (kindFilter === "all" || relationship.relation_kind === kindFilter)
      && (directionFilter === "all" || relationship.directionality === directionFilter)
    )),
    [relationships, kindFilter, directionFilter],
  );
  const legacyCount = relationships.filter(
    (relationship) => relationship.directionality === "legacy_unspecified",
  ).length;
  const autoSyncPhase = syncingRelationships
    ? "syncing"
    : preparingAutoSync
      ? "preparing"
      : checkingAutoSync
        ? "checking"
        : "idle";
  const autoSyncPresentation = relationshipSyncPresentation(autoSyncStatus, {
    phase: autoSyncPhase,
    error: autoSyncError,
    modelLabel: autoSyncModelLabel,
    confirming: confirmingAutoSync,
  });
  const autoSyncBusy = autoSyncPhase !== "idle" || autoSyncStatus?.state === "running";

  const saveLayout = async () => {
    const snapshot = controllerRef.current?.snapshot();
    if (!snapshot || saving) return;
    setSaving(true);
    setError("");
    try {
      const saved = await apiRequest<RelationshipGraphViewRecord>(
        `/novels/${novelId}/relationship-graph-view`,
        {
          method: "PUT",
          body: JSON.stringify({
            expected_version: view.version,
            name: view.name,
            layout_algorithm: view.layout_algorithm,
            random_seed: view.random_seed,
            ...snapshot,
          }),
        },
      );
      setView(saved);
      setScale(saved.zoom);
      setDirty(false);
    } catch (reason) {
      setError(readError(reason));
    } finally {
      setSaving(false);
    }
  };

  const toggleFullscreen = async () => {
    const target = canvasShellRef.current;
    if (!target) return;
    setError("");
    try {
      await toggleElementFullscreen(target);
    } catch (reason) {
      setError(readError(reason));
    }
  };

  const relationLabel = (relationship: CharacterRelationshipRecord): string => {
    const source = characters.find(
      (character) => character.id === relationship.source_character_id,
    )?.name || "未知角色";
    const target = characters.find(
      (character) => character.id === relationship.target_character_id,
    )?.name || "未知角色";
    const mark = relationship.directionality === "directed"
      ? "→"
      : relationship.directionality === "undirected"
        ? "—"
        : "?";
    return `${source} ${mark} ${target}`;
  };

  if (loading) {
    return h("div", { className: "mb-relation-loading" }, h(Spin), "正在加载关系网…");
  }

  return h(
    "div",
    { className: "mb-relationship-workspace" },
    h(
      "div",
      {
        className: `mb-relation-ai-status${autoSyncBusy ? " is-syncing" : ""}${autoSyncError ? " is-error" : ""}`,
        role: "status",
        "aria-live": "polite",
      },
      h("span", { className: "mb-relation-ai-icon" }, autoSyncBusy ? h(Spin, { size: "small" }) : h(RobotOutlined)),
      h("span", { className: "mb-relation-ai-copy" }, h("strong", null, autoSyncPresentation.title), h("small", null, autoSyncPresentation.description)),
      h(Button, {
        type: "text",
        size: "small",
        icon: h(ReloadOutlined),
        disabled: autoSyncPresentation.actionDisabled,
        onClick: () => {
          if (autoSyncPresentation.action === "reload-status") {
            void loadAutoSyncStatus();
            return;
          }
          void requestRelationshipSync(autoSyncPresentation.forceNew);
        },
      }, autoSyncPresentation.actionLabel),
    ),
    h(
      "div",
      { className: "mb-relation-canvas-shell", ref: canvasShellRef },
      h(
        "div",
        { className: "mb-relation-overlay-stack" },
        error ? h(Alert, { type: "error", showIcon: true, closable: true, message: error, onClose: () => setError("") }) : null,
        h(
          "div",
          { className: "mb-relation-toolbar", role: "toolbar", "aria-label": "关系图工具栏" },
          h(
            "div",
            { className: "mb-relation-filter-tools", role: "group", "aria-label": "关系筛选" },
            h(Select, {
              className: "mb-relation-character-search",
              popupClassName: "mb-relation-filter-dropdown",
              allowClear: true,
              showSearch: true,
              value: focusCharacterId || undefined,
              placeholder: "搜索并聚焦角色",
              suffixIcon: h(SearchOutlined),
              getPopupContainer: () => canvasShellRef.current ?? document.body,
              optionFilterProp: "label",
              options: characters.map((character) => ({ label: character.name, value: character.id })),
              onChange: (value: string | undefined) => {
                setFocusCharacterId(value || "");
                if (value) controllerRef.current?.focusNode(value);
              },
            }),
            h(Select, {
              popupClassName: "mb-relation-filter-dropdown",
              getPopupContainer: () => canvasShellRef.current ?? document.body,
              value: kindFilter,
              options: KIND_OPTIONS,
              onChange: (value: "all" | RelationshipKind) => setKindFilter(value),
              "aria-label": "按关系分类筛选",
            }),
            h(Select, {
              popupClassName: "mb-relation-filter-dropdown",
              getPopupContainer: () => canvasShellRef.current ?? document.body,
              value: directionFilter,
              options: DIRECTION_OPTIONS,
              onChange: (value: "all" | RelationshipDirectionality) => setDirectionFilter(value),
              "aria-label": "按关系方向筛选",
            }),
          ),
          h(
            "div",
            { className: "mb-relation-edit-tools" },
            legacyCount
              ? h(
                  "button",
                  {
                    type: "button",
                    className: `mb-relation-legacy-chip${directionFilter === "legacy_unspecified" ? " is-active" : ""}`,
                    title: "只查看方向待确认的旧关系",
                    onClick: () => setDirectionFilter("legacy_unspecified"),
                  },
                  h(ExclamationCircleOutlined),
                  `${legacyCount} 条方向待确认`,
                )
              : h("span", { className: "mb-relation-toolbar-spacer" }),
            h(
              "div",
              { className: "mb-relation-view-tools", role: "group", "aria-label": "画布视图控制" },
              h(Button, { size: "small", icon: h(MinusOutlined), title: "缩小", "aria-label": "缩小关系图", onClick: () => controllerRef.current?.zoomOut() }),
              h("span", { className: "mb-relation-scale", "aria-live": "polite" }, `${Math.round(scale * 100)}%`),
              h(Button, { size: "small", icon: h(PlusOutlined), title: "放大", "aria-label": "放大关系图", onClick: () => controllerRef.current?.zoomIn() }),
              h(Button, { size: "small", icon: h(ExpandOutlined), title: "适应画布", "aria-label": "适应画布", onClick: () => controllerRef.current?.fit() }),
              h(Button, { size: "small", icon: h(ReloadOutlined), title: "自动排布", "aria-label": "自动排布", onClick: () => controllerRef.current?.autoLayout() }),
              h(Button, {
                size: "small",
                icon: h(fullscreen ? FullscreenExitOutlined : FullscreenOutlined),
                title: fullscreen ? "退出全屏" : "全屏显示",
                "aria-label": fullscreen ? "退出关系图全屏" : "全屏显示关系图",
                "aria-pressed": fullscreen,
                onClick: () => void toggleFullscreen(),
              }),
            ),
            h(Button, { icon: h(LinkOutlined), className: "anw-primary-button mb-relation-add", disabled: characters.length < 2, onClick: onAddRelationship }, "新增关系"),
          ),
        ),
      ),
      h(
        "div",
        { className: "mb-relation-stage" },
        h(RelationshipGraph, {
          characters,
          relationships: visibleRelationships,
          view,
          controllerRef,
          focusCharacterId,
          onCharacterClick: (character: NovelCharacterRecord) => onEditCharacter(character.id),
          onRelationshipClick: (relationship: CharacterRelationshipRecord) => onEditRelationship(relationship.id),
          onViewStateChange: (nextScale: number, nextDirty: boolean) => {
            setScale(nextScale);
            if (nextDirty) setDirty(true);
          },
        }),
        dirty
          ? h(
              "div",
              { className: "mb-relation-layout-actions", role: "status" },
              h("span", null, "布局有改动"),
              h(Button, { size: "small", onClick: () => void loadView() }, "撤销"),
              h(Button, { size: "small", icon: h(SaveOutlined), className: "anw-primary-button", loading: saving, onClick: () => void saveLayout() }, "保存"),
            )
          : null,
        visibleRelationships.length === 0 && relationships.length > 0
          ? h("div", { className: "mb-relation-filter-empty" }, "当前筛选条件下没有关系")
          : null,
      ),
    ),
    h(
      "section",
      { className: "mb-relation-accessible-list", "aria-labelledby": "mb-relation-list-title" },
      h(
        "header",
        null,
        h("div", null, h("h4", { id: "mb-relation-list-title" }, "关系列表"), h("span", null, `${visibleRelationships.length} 条`)),
        h("small", null, "无需操作画布，也可以在这里完整查看和编辑关系。"),
      ),
      visibleRelationships.length
        ? h(
            "ul",
            null,
            ...visibleRelationships.map((relationship: CharacterRelationshipRecord) => h(
              "li",
              { key: relationship.id },
              h(
                "button",
                { type: "button", onClick: () => onEditRelationship(relationship.id) },
                h("span", { className: `mb-relation-direction is-${relationship.directionality}` }, relationLabel(relationship)),
                h("span", { className: "mb-relation-list-title" },
                  h("strong", null, relationship.label),
                  h("em", { className: relationship.manual_override ? "is-manual" : "is-ai" }, relationship.manual_override ? "人工确认" : `AI生成${relationship.confidence ? ` ${relationship.confidence}%` : ""}`),
                ),
                h("small", null, relationship.latest_state ? `当前变化：${relationship.latest_state}` : (relationship.description || "未填写关系说明")),
              ),
            )),
          )
        : h(Empty, { description: relationships.length ? "当前筛选条件下没有关系" : "还没有角色关系" }),
    ),
  );
}
