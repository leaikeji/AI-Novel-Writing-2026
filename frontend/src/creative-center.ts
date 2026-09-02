import {
  apiErrorMessage,
  apiRequest,
  completedGenerationModelLabel,
  generationModelLabel,
  generationModelAuditLabel,
  getGenerationModelStatus,
  verifiedGenerationModelLabel,
} from "./api";
import { CHAT_PATH, CREATIVE_CENTER_CHAT_PATH } from "./contracts";
import {
  AssetPresetRecord,
  CreativeGenerationRecord,
  NovelCreationDraftRecord,
  NovelMetadataRecord,
  NovelSummary,
  PrivateAssetRecord,
  PrivateAssetType,
} from "./types";
import { rememberWorkbenchRoute } from "./workbench-route";
import { compressCover, generateSystemCover } from "./cover-utils";
import { createNovelCoverView } from "./novel-cover";
import { navigateNovelSurface } from "./novel-surface-navigation";
import { createEmbeddingConfigPage } from "./embedding";
import defaultNovelCover from "../assets/novel-cover-fengcunqu.jpg";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const NovelCoverView = createNovelCoverView(React);
const EmbeddingConfigPage = createEmbeddingConfigPage(React, host.antd);
const {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  Modal,
  Select,
  Spin,
} = host.antd;
const {
  AppstoreOutlined,
  ArrowLeftOutlined,
  BgColorsOutlined,
  BookOutlined,
  BulbOutlined,
  CheckOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  ManOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  SoundOutlined,
  StarOutlined,
  TeamOutlined,
  UploadOutlined,
  WomanOutlined,
} = host.antdIcons;


const CREATION_DRAFT_KEY = "ai-novel-world-2026:creation-draft-key";
type LibraryView = "center" | "private-library" | "embedding-settings";
type TemplateTab = "system" | "custom";


const ASSET_META: Record<PrivateAssetType, { label: string; singular: string; placeholder: string }> = {
  plot: { label: "桥段配置", singular: "桥段", placeholder: "描述这个桥段的具体内容" },
  writing_style: { label: "写作风格", singular: "写作风格", placeholder: "描述语言节奏、视角和表达偏好" },
  vocabulary: { label: "特色词汇", singular: "特色词汇", placeholder: "填写词汇、口头禅或固定表达" },
  idea: { label: "热梗奇思", singular: "热梗奇思", placeholder: "记录可以用于创作的灵感" },
};


const WIZARD_LABELS = ["受众", "思路", "模板", "命名", "封面", "完成"];
const WIZARD_HINTS = [
  "还差5步了哦，你的故事即将诞生！",
  "还差4步了哦，你的故事正在快马加鞭赶来！",
  "还差3步了哦，马上就要大功告成啦！",
  "还差2步了哦，给作品取个响亮的名字吧！",
  "最后一步啦，为作品选择封面！",
  "万事俱备，完成创建！",
];


const SYSTEM_TEMPLATES: Record<string, Array<{ key: string; name: string; fields: string[] }>> = {
  现实: [
    { key: "real-life", name: "现实生活", fields: ["protagonist_identity", "background_setting", "core_conflict", "emotional_mainline", "style_features"] },
  ],
  言情: [
    { key: "republic-romance", name: "民国言情", fields: ["male_name", "female_name", "core_hook", "male_identity", "female_identity", "romance_line"] },
    { key: "ancient-romance", name: "古言脑洞", fields: ["male_name", "female_name", "core_hook", "male_identity", "female_identity", "romance_line"] },
    { key: "modern-romance", name: "现言脑洞", fields: ["male_name", "female_name", "core_hook", "male_identity", "female_identity", "romance_line"] },
    { key: "fantasy-romance", name: "玄幻言情", fields: ["male_name", "female_name", "core_hook", "male_identity", "female_identity", "romance_line"] },
  ],
  都市: [
    { key: "urban-growth", name: "都市成长", fields: ["lead_name", "core_hook", "lead_identity", "growth_line"] },
    { key: "urban-suspense", name: "都市悬疑", fields: ["lead_name", "core_hook", "lead_identity", "mystery_line"] },
  ],
  玄幻: [
    { key: "fantasy-rise", name: "玄幻升级", fields: ["lead_name", "core_hook", "lead_identity", "growth_line"] },
    { key: "eastern-fantasy", name: "东方玄幻", fields: ["lead_name", "core_hook", "lead_identity", "world_rule"] },
  ],
  悬疑: [
    { key: "suspense-case", name: "悬疑探案", fields: ["lead_name", "core_hook", "lead_identity", "mystery_line"] },
  ],
  科幻: [
    { key: "science-fiction", name: "未来科幻", fields: ["lead_name", "core_hook", "lead_identity", "world_rule"] },
  ],
  历史: [
    { key: "historical-rebirth", name: "历史穿越", fields: ["lead_name", "core_hook", "lead_identity", "growth_line"] },
  ],
};


const TEMPLATE_FIELD_META: Record<string, { label: string; placeholder: string }> = {
  protagonist_identity: { label: "主角身份", placeholder: "请输入主角身份" },
  background_setting: { label: "背景设定", placeholder: "请输入背景设定" },
  core_conflict: { label: "核心冲突", placeholder: "请输入核心冲突" },
  emotional_mainline: { label: "情感主线", placeholder: "请输入情感主线" },
  style_features: { label: "风格特点", placeholder: "请输入风格特点" },
  male_name: { label: "男主名字", placeholder: "请输入男主名字" },
  female_name: { label: "女主名字", placeholder: "请输入女主名字" },
  lead_name: { label: "主角名字", placeholder: "请输入主角名字" },
  core_hook: { label: "核心脑洞", placeholder: "一句话写清故事最重要的设定与冲突" },
  male_identity: { label: "男主身份", placeholder: "身份、处境、欲望与限制" },
  female_identity: { label: "女主身份", placeholder: "身份、处境、欲望与限制" },
  lead_identity: { label: "主角身份", placeholder: "身份、处境、欲望与限制" },
  romance_line: { label: "情感线", placeholder: "两人关系如何建立、误解、变化与确认" },
  growth_line: { label: "成长线", placeholder: "主角如何付出代价并完成改变" },
  mystery_line: { label: "谜团线", placeholder: "谜面、调查、反转和真相" },
  world_rule: { label: "世界规则", placeholder: "能力、技术或时代规则及其代价" },
};


function readableError(reason: unknown, fallback: string): string {
  return apiErrorMessage(reason, fallback);
}


function taskModelLabel(job: CreativeGenerationRecord): string {
  return job.state === "ready"
    ? verifiedGenerationModelLabel(job)
    : generationModelAuditLabel(job);
}


type CreativeCenterWorkbenchSection = "chapters" | "outline" | "roles" | "clues" | "settings" | "reading";


function workbenchUrl(novelId: string, section?: CreativeCenterWorkbenchSection): string {
  rememberWorkbenchRoute(novelId);
  const query = new URLSearchParams({ novel_workbench: "1", novel_id: novelId });
  if (section && section !== "chapters") query.set("section", section);
  return `/chat?${query.toString()}`;
}


function initialLibraryView(): LibraryView {
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "private-library" || view === "embedding-settings" ? view : "center";
}


function setLibraryUrl(view: LibraryView): void {
  const target = new URL(CREATIVE_CENTER_CHAT_PATH, window.location.origin);
  const currentPath = window.location.pathname;
  if (currentPath === CHAT_PATH || currentPath.startsWith(`${CHAT_PATH}/`)) {
    target.pathname = currentPath;
  }
  const query = target.searchParams;
  if (view !== "center") query.set("view", view);
  else query.delete("view");
  window.history.replaceState(
    null,
    "",
    `${target.pathname}?${query.toString()}`,
  );
}


function audienceLabel(audience: string): string {
  if (audience === "female") return "女频";
  if (audience === "male") return "男频";
  return "未分类";
}


function latestChapterTitle(novel: NovelSummary): string {
  return novel.chapter_count > 0
    ? `最新进度：已完成 ${novel.chapter_count} 章`
    : "尚未开始正文创作";
}


function CenterAction(props: { icon: any; label: string; onClick: () => void }) {
  return h(
    "button",
    { type: "button", className: "mb-center-action", onClick: props.onClick },
    h("span", { className: "mb-center-action-icon" }, h(props.icon)),
    h("span", null, props.label),
  );
}


function NovelCard(props: {
  novel: NovelSummary;
  onOpen: (section?: CreativeCenterWorkbenchSection) => void;
  onDelete: () => void;
}) {
  const { novel, onOpen, onDelete } = props;
  const tools = [
    [FileTextOutlined, "大纲", "outline"],
    [TeamOutlined, "角色", "roles"],
    [ClockCircleOutlined, "线索", "clues"],
    [SoundOutlined, "朗读", "reading"],
    [DeleteOutlined, "删除", "delete"],
  ] as const;
  return h(
    "article",
    { className: "mb-novel-card" },
    h(
      "div",
      { className: "mb-novel-card-hero" },
      h(NovelCoverView, { novel, className: "mb-novel-cover", fallbackSrc: defaultNovelCover }),
      h(
        "div",
        { className: "mb-novel-card-meta" },
        h("h2", null, novel.title),
        h(
          "div",
          { className: "mb-novel-counts" },
          h("span", null, h(BookOutlined), `${novel.chapter_count}章`),
          h("span", null, h(FileTextOutlined), `${novel.visible_character_count}字`),
        ),
        h(
          "div",
          { className: "mb-novel-tags" },
          h("span", { className: "is-audience" }, audienceLabel(novel.audience)),
          novel.genre ? h("span", null, novel.genre) : null,
          novel.subgenre ? h("span", null, novel.subgenre) : null,
        ),
      ),
    ),
    h("div", { className: "mb-latest-chapter" }, latestChapterTitle(novel)),
    h(
      "div",
      { className: "mb-novel-tool-row has-reading" },
      ...tools.map(([Icon, label, target]) => h(
        "button",
        {
          key: label,
          type: "button",
          onClick: () => target === "delete" ? onDelete() : onOpen(target),
        },
        h(Icon),
        h("span", null, label),
      )),
    ),
    h(
      "div",
      { className: "mb-novel-start" },
      h(Button, { block: true, className: "mb-orange-button", onClick: () => onOpen("chapters") }, "开始创作"),
    ),
  );
}


function PrivateLibrary(props: { onBack: () => void }) {
  const [assets, setAssets] = React.useState([] as PrivateAssetRecord[]) as [PrivateAssetRecord[], any];
  const [presets, setPresets] = React.useState([] as AssetPresetRecord[]) as [AssetPresetRecord[], any];
  const [activeType, setActiveType] = React.useState("plot" as PrivateAssetType) as [PrivateAssetType, any];
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [assetModalOpen, setAssetModalOpen] = React.useState(false);
  const [editingAsset, setEditingAsset] = React.useState(null as PrivateAssetRecord | null);
  const [assetTitle, setAssetTitle] = React.useState("");
  const [assetContent, setAssetContent] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [presetListOpen, setPresetListOpen] = React.useState(false);
  const [presetFormOpen, setPresetFormOpen] = React.useState(false);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [editingPreset, setEditingPreset] = React.useState(null as AssetPresetRecord | null);
  const [presetTitle, setPresetTitle] = React.useState("");
  const [presetDescription, setPresetDescription] = React.useState("");
  const [selectedAssetIds, setSelectedAssetIds] = React.useState([] as string[]);
  const [pickerType, setPickerType] = React.useState("plot" as PrivateAssetType) as [PrivateAssetType, any];
  const [pickerSearch, setPickerSearch] = React.useState("");

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const [nextAssets, nextPresets] = await Promise.all([
        apiRequest<PrivateAssetRecord[]>("/private-assets"),
        apiRequest<AssetPresetRecord[]>("/asset-presets"),
      ]);
      setAssets(nextAssets);
      setPresets(nextPresets);
      setError("");
    } catch (reason) {
      setError(readableError(reason, "加载私有库失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { void reload(); }, [reload]);

  const openAssetForm = (asset?: PrivateAssetRecord) => {
    setEditingAsset(asset ?? null);
    setAssetTitle(asset?.title ?? "");
    setAssetContent(asset?.content ?? "");
    setAssetModalOpen(true);
  };

  const saveAsset = async () => {
    if (!assetTitle.trim()) return;
    setSaving(true);
    try {
      if (editingAsset) {
        await apiRequest(`/private-assets/${editingAsset.id}`, {
          method: "PUT",
          body: JSON.stringify({
            expected_version: editingAsset.version,
            title: assetTitle.trim(),
            content: assetContent.trim(),
          }),
        });
      } else {
        await apiRequest("/private-assets", {
          method: "POST",
          body: JSON.stringify({ asset_type: activeType, title: assetTitle.trim(), content: assetContent.trim() }),
        });
      }
      setAssetModalOpen(false);
      await reload();
    } catch (reason) {
      setError(readableError(reason, "保存私有库资料失败"));
    } finally {
      setSaving(false);
    }
  };

  const deleteAsset = (asset: PrivateAssetRecord) => {
    Modal.confirm({
      className: "anw-modal mb-confirm-modal",
      title: `删除“${asset.title}”`,
      content: "删除后，这条资料不会再出现在生成选择中。",
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      async onOk() {
        try {
          await apiRequest(`/private-assets/${asset.id}?expected_version=${asset.version}`, { method: "DELETE" });
          await reload();
        } catch (reason) {
          setError(readableError(reason, "删除私有库资料失败"));
        }
      },
    });
  };

  const openPresetForm = (preset?: AssetPresetRecord) => {
    setEditingPreset(preset ?? null);
    setPresetTitle(preset?.title ?? "");
    setPresetDescription(preset?.description ?? "");
    setSelectedAssetIds((preset?.assets ?? []).map((asset) => asset.id));
    setPresetListOpen(false);
    setPresetFormOpen(true);
  };

  const savePreset = async () => {
    if (!presetTitle.trim()) return;
    setSaving(true);
    try {
      const base = {
        title: presetTitle.trim(),
        description: presetDescription.trim(),
        asset_ids: selectedAssetIds,
      };
      if (editingPreset) {
        await apiRequest(`/asset-presets/${editingPreset.id}`, {
          method: "PUT",
          body: JSON.stringify({ ...base, expected_version: editingPreset.version }),
        });
      } else {
        await apiRequest("/asset-presets", { method: "POST", body: JSON.stringify(base) });
      }
      setPresetFormOpen(false);
      setPresetListOpen(true);
      await reload();
    } catch (reason) {
      setError(readableError(reason, "保存私有库预设失败"));
    } finally {
      setSaving(false);
    }
  };

  const deletePreset = (preset: AssetPresetRecord) => {
    Modal.confirm({
      className: "anw-modal mb-confirm-modal",
      title: `删除预设“${preset.title}”`,
      content: "预设会被删除，原有私有库资料不会受影响。",
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      async onOk() {
        try {
          await apiRequest(`/asset-presets/${preset.id}?expected_version=${preset.version}`, { method: "DELETE" });
          await reload();
        } catch (reason) {
          setError(readableError(reason, "删除预设失败"));
        }
      },
    });
  };

  const toggleAssetForPreset = (assetId: string) => {
    setSelectedAssetIds((current: string[]) => current.includes(assetId)
      ? current.filter((id) => id !== assetId)
      : [...current, assetId]);
  };

  const currentAssets = assets.filter((asset) => asset.asset_type === activeType);
  const pickerAssets = assets.filter((asset) => asset.asset_type === pickerType
    && (!pickerSearch.trim() || `${asset.title}${asset.content}`.includes(pickerSearch.trim())));

  return h(
    "main",
    { className: "anw-app mb-private-page" },
    h(
      "div",
      { className: "mb-private-inner" },
      h(
        "header",
        { className: "mb-private-header" },
        h(
          "div",
          { className: "mb-private-title-row" },
          h("button", { type: "button", className: "mb-back-link", onClick: props.onBack }, h(ArrowLeftOutlined), "返回"),
          h("h1", null, "私有库"),
        ),
        h(Button, { className: "mb-preset-button", icon: h(StarOutlined), onClick: () => setPresetListOpen(true) }, "预设"),
      ),
      error ? h(Alert, { type: "error", showIcon: true, message: error, closable: true, onClose: () => setError("") }) : null,
      h(
        "nav",
        { className: "mb-private-tabs", "aria-label": "私有库分类" },
        ...(Object.keys(ASSET_META) as PrivateAssetType[]).map((type) => h(
          "button",
          { key: type, type: "button", className: type === activeType ? "is-active" : "", onClick: () => setActiveType(type) },
          ASSET_META[type].label,
        )),
      ),
      h(
        "button",
        { type: "button", className: "mb-add-asset", onClick: () => openAssetForm() },
        h(PlusOutlined),
        `新增${ASSET_META[activeType].label}`,
      ),
      loading
        ? h("div", { className: "mb-private-loading" }, h(Spin), "正在加载私有库…")
        : currentAssets.length === 0
          ? h("div", { className: "mb-private-empty" }, h(Empty, { description: `还没有${ASSET_META[activeType].label}` }))
          : h(
              "section",
              { className: "mb-asset-grid" },
              ...currentAssets.map((asset) => h(
                "article",
                { key: asset.id, className: "mb-asset-card" },
                h("h2", null, asset.title),
                h("p", null, asset.content || "未填写内容"),
                h(
                  "div",
                  { className: "mb-asset-actions" },
                  h("button", { type: "button", onClick: () => openAssetForm(asset) }, h(EditOutlined), "编辑"),
                  h("button", { type: "button", className: "is-danger", onClick: () => deleteAsset(asset) }, h(DeleteOutlined), "删除"),
                ),
              )),
            ),
    ),
    h(
      Modal,
      {
        open: assetModalOpen,
        className: "anw-modal mb-form-modal",
        width: 500,
        title: editingAsset ? "编辑" : "新增",
        footer: null,
        onCancel: () => setAssetModalOpen(false),
        destroyOnClose: false,
      },
      h("label", { className: "mb-field-label" }, `${ASSET_META[activeType].singular}名称`),
      h(Input, { value: assetTitle, maxLength: 240, placeholder: `例如：${activeType === "plot" ? "扮猪吃老虎" : ASSET_META[activeType].singular}`, onChange: (event: any) => setAssetTitle(event.target.value) }),
      h("label", { className: "mb-field-label" }, `${ASSET_META[activeType].singular}内容`),
      h(Input.TextArea, { value: assetContent, maxLength: 30000, rows: 5, placeholder: ASSET_META[activeType].placeholder, onChange: (event: any) => setAssetContent(event.target.value) }),
      h(
        "div",
        { className: "mb-modal-actions" },
        h(Button, { onClick: () => setAssetModalOpen(false) }, "取消"),
        h(Button, { className: "mb-orange-button", loading: saving, disabled: !assetTitle.trim(), onClick: saveAsset }, editingAsset ? "保存" : "创建"),
      ),
    ),
    h(
      Modal,
      {
        open: presetListOpen,
        className: "anw-modal mb-preset-list-modal",
        width: 520,
        title: "私有库预设",
        footer: null,
        onCancel: () => setPresetListOpen(false),
      },
      presets.length === 0
        ? h("div", { className: "mb-preset-empty" }, h(StarOutlined), h("p", null, "暂无预设，点击下方按钮创建"))
        : h(
            "div",
            { className: "mb-preset-list" },
            ...presets.map((preset) => h(
              "article",
              { key: preset.id },
              h("div", null, h("strong", null, preset.title), h("p", null, preset.description || `${preset.assets.length} 条私有库资料`)),
              h("div", null,
                h(Button, { type: "text", icon: h(EditOutlined), onClick: () => openPresetForm(preset) }),
                h(Button, { type: "text", danger: true, icon: h(DeleteOutlined), onClick: () => deletePreset(preset) }),
              ),
            )),
          ),
      h(
        "div",
        { className: "mb-modal-actions" },
        h(Button, { onClick: () => setPresetListOpen(false) }, "关闭"),
        h(Button, { className: "mb-orange-button", icon: h(PlusOutlined), onClick: () => openPresetForm() }, "新建预设"),
      ),
    ),
    h(
      Modal,
      {
        open: presetFormOpen,
        className: "anw-modal mb-form-modal",
        width: 500,
        title: editingPreset ? "编辑预设" : "新建预设",
        footer: null,
        onCancel: () => setPresetFormOpen(false),
      },
      h("label", { className: "mb-field-label" }, "预设名称"),
      h(Input, { value: presetTitle, maxLength: 240, placeholder: "请输入预设名称", onChange: (event: any) => setPresetTitle(event.target.value) }),
      h("label", { className: "mb-field-label" }, "预设介绍（可选）"),
      h(Input.TextArea, { value: presetDescription, rows: 3, maxLength: 4000, placeholder: "请输入预设介绍", onChange: (event: any) => setPresetDescription(event.target.value) }),
      h("label", { className: "mb-field-label" }, "私有库配置"),
      h(
        "button",
        {
          type: "button",
          className: "mb-preset-picker-entry",
          onClick: () => {
            setPresetFormOpen(false);
            setPickerOpen(true);
          },
        },
        h(AppstoreOutlined),
        selectedAssetIds.length ? `已选择 ${selectedAssetIds.length} 条资料` : "点击配置私有库",
      ),
      h(
        "div",
        { className: "mb-modal-actions" },
        h(Button, { onClick: () => { setPresetFormOpen(false); setPresetListOpen(true); } }, "返回"),
        h(Button, { className: "mb-orange-button", loading: saving, disabled: !presetTitle.trim(), onClick: savePreset }, "保存"),
      ),
    ),
    h(
      Modal,
      {
        open: pickerOpen,
        className: "anw-modal mb-picker-modal",
        width: 700,
        title: "选择私有库配置",
        footer: null,
        onCancel: () => {
          setPickerOpen(false);
          setPresetFormOpen(true);
        },
      },
      h("p", { className: "mb-picker-subtitle" }, "AI 将重点展示选中的内容到生成结果中"),
      h(Input, { value: pickerSearch, prefix: h(SearchOutlined), placeholder: "搜索私有库配置", onChange: (event: any) => setPickerSearch(event.target.value) }),
      h(
        "nav",
        { className: "mb-picker-tabs" },
        ...(Object.keys(ASSET_META) as PrivateAssetType[]).map((type) => h(
          "button",
          { key: type, type: "button", className: pickerType === type ? "is-active" : "", onClick: () => setPickerType(type) },
          ASSET_META[type].label,
        )),
      ),
      h(
        "div",
        { className: "mb-picker-list" },
        pickerAssets.length === 0
          ? h(Empty, { description: "当前分类暂无资料" })
          : pickerAssets.map((asset) => h(
              "label",
              { key: asset.id, className: "mb-picker-item" },
              h(Checkbox, { checked: selectedAssetIds.includes(asset.id), onChange: () => toggleAssetForPreset(asset.id) }),
              h("span", null, h("strong", null, asset.title), h("small", null, asset.content || "未填写内容")),
            )),
      ),
      h(
        "div",
        { className: "mb-modal-actions" },
        h(Button, { onClick: () => { setSelectedAssetIds([]); setPickerOpen(false); setPresetFormOpen(true); } }, "跳过"),
        h(Button, { className: "mb-orange-button", onClick: () => { setPickerOpen(false); setPresetFormOpen(true); } }, "确定选择"),
      ),
    ),
  );
}


function WizardProgress(props: { step: number }) {
  const step = Math.max(1, Math.min(6, props.step));
  return h(
    "div",
    { className: "mb-wizard-progress" },
    h("div", { className: "mb-wizard-hint" }, WIZARD_HINTS[step - 1]),
    h(
      "div",
      { className: "mb-wizard-steps" },
      ...WIZARD_LABELS.map((label, index) => {
        const number = index + 1;
        const complete = number < step;
        const current = number === step;
        return h(
          "div",
          { key: label, className: `mb-wizard-step${complete ? " is-complete" : ""}${current ? " is-current" : ""}` },
          h("span", { className: "mb-wizard-dot" }, complete ? h(CheckOutlined) : number),
          h("span", { className: "mb-wizard-step-label" }, label),
        );
      }),
    ),
  );
}


function ChoiceCard(props: { selected: boolean; icon: any; title: string; copy: string; badge?: string; onClick: () => void }) {
  return h(
    "button",
    { type: "button", className: `mb-choice-card${props.selected ? " is-selected" : ""}`, onClick: props.onClick },
    h("span", { className: "mb-choice-icon" }, h(props.icon)),
    h("strong", null, props.title, props.badge && props.selected ? h("span", { className: "mb-choice-badge" }, props.badge) : null),
    h("small", null, props.copy),
    props.selected ? h(CheckOutlined, { className: "mb-choice-check" }) : null,
  );
}


function CreateNovelWizard(props: { open: boolean; onClose: () => void; onCompleted: (novel: NovelMetadataRecord, next?: "outline") => Promise<void> }) {
  const [draft, setDraft] = React.useState(null as NovelCreationDraftRecord | null);
  const [completedNovel, setCompletedNovel] = React.useState(null as NovelMetadataRecord | null);
  const [step, setStep] = React.useState(0);
  const [data, setData] = React.useState({ writing_type: "", audience: "male", cover_mode: "ai", template_data: {} } as Record<string, any>);
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [templateModalOpen, setTemplateModalOpen] = React.useState(false);
  const [templateGenerating, setTemplateGenerating] = React.useState(false);
  const [templateTab, setTemplateTab] = React.useState("system" as TemplateTab);
  const [templateCategory, setTemplateCategory] = React.useState("");
  const [templateCandidate, setTemplateCandidate] = React.useState(null as { key: string; name: string; fields: string[] } | null);
  const [templateTaskModelLabel, setTemplateTaskModelLabel] = React.useState("");
  const [namingTaskModelLabel, setNamingTaskModelLabel] = React.useState("");
  const [coverTaskModelLabel, setCoverTaskModelLabel] = React.useState("");

  React.useEffect(() => {
    setBusy(false);
  }, [step]);

  const startDraft = React.useCallback(async () => {
    setLoading(true);
    try {
      let draftKey = window.localStorage.getItem(CREATION_DRAFT_KEY);
      if (!draftKey) {
        draftKey = `novel-${crypto.randomUUID()}`;
        window.localStorage.setItem(CREATION_DRAFT_KEY, draftKey);
      }
      let next = await apiRequest<NovelCreationDraftRecord>("/creation-drafts", {
        method: "POST",
        body: JSON.stringify({ draft_key: draftKey }),
      });
      if (next.state === "completed") {
        draftKey = `novel-${crypto.randomUUID()}`;
        window.localStorage.setItem(CREATION_DRAFT_KEY, draftKey);
        next = await apiRequest<NovelCreationDraftRecord>("/creation-drafts", {
          method: "POST",
          body: JSON.stringify({ draft_key: draftKey }),
        });
      }
      const nextData: Record<string, any> = {
        writing_type: "",
        audience: "male",
        cover_mode: "ai",
        template_data: {},
        ...(next.data || {}),
      };
      setDraft(next);
      setData(nextData);
      setStep(next.step || 0);
      setError("");
      try {
        const jobs = await apiRequest<CreativeGenerationRecord[]>(
          `/creative-generations?scope_type=novel_creation&scope_id=${encodeURIComponent(next.id)}`,
        );
        const byId = new Map(jobs.map((job) => [job.id, job]));
        const labelFor = (jobId: unknown) => {
          const job = byId.get(String(jobId || ""));
          return job ? taskModelLabel(job) : "";
        };
        setTemplateTaskModelLabel(labelFor(nextData.template_generation_job_id));
        setNamingTaskModelLabel(labelFor(nextData.naming_generation_job_id));
        setCoverTaskModelLabel(labelFor(nextData.cover_generation_job_id));
      } catch {
        setTemplateTaskModelLabel("");
        setNamingTaskModelLabel("");
        setCoverTaskModelLabel("");
      }
    } catch (reason) {
      setError(readableError(reason, "加载建书草稿失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (props.open) void startDraft();
  }, [props.open, startDraft]);

  const updateData = (patch: Record<string, any>) => setData((current: Record<string, any>) => ({ ...current, ...patch }));
  const updateTemplateData = (key: string, value: string) => setData((current: Record<string, any>) => ({
    ...current,
    template_data: { ...(current.template_data || {}), [key]: value },
  }));

  const persist = async (nextStep: number, patch: Record<string, any> = data) => {
    if (!draft) throw new Error("建书草稿尚未就绪");
    const merged = { ...data, ...patch };
    const next = await apiRequest<NovelCreationDraftRecord>(`/creation-drafts/${draft.id}`, {
      method: "PATCH",
      body: JSON.stringify({ expected_version: draft.version, step: nextStep, data_patch: merged }),
    });
    setDraft(next);
    setData({ writing_type: "", audience: "male", cover_mode: "ai", template_data: {}, ...(next.data || {}) });
    setStep(nextStep);
    return next;
  };

  const closeWizard = async () => {
    if (completedNovel) {
      const novel = completedNovel;
      setCompletedNovel(null);
      await props.onCompleted(novel);
      return;
    }
    if (!draft || busy) {
      props.onClose();
      return;
    }
    setBusy(true);
    try {
      await persist(step, data);
    } catch (reason) {
      setError(readableError(reason, "保存建书草稿失败"));
    } finally {
      setBusy(false);
      props.onClose();
    }
  };

  const goBack = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await persist(Math.max(0, step - 1), data);
      setError("");
    } catch (reason) {
      setError(readableError(reason, "返回上一步失败"));
    } finally {
      setBusy(false);
    }
  };

  const goDirectToTemplate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await persist(3, data);
      setError("");
    } catch (reason) {
      setError(readableError(reason, "进入模板填写失败"));
    } finally {
      setBusy(false);
    }
  };

  const generateTemplate = async () => {
    if (!draft || busy) return;
    setBusy(true);
    setTemplateGenerating(true);
    setStep(3);
    try {
      const currentModel = await getGenerationModelStatus();
      setTemplateTaskModelLabel(generationModelLabel(currentModel));
      const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
        method: "POST",
        body: JSON.stringify({
          scope_type: "novel_creation",
          scope_id: draft.id,
          kind: "novel_template",
          input_snapshot: {
            audience: data.audience,
            idea: data.idea,
          },
          force_new: true,
        }),
      });
      setTemplateTaskModelLabel(job.state === "ready" ? completedGenerationModelLabel(job) : generationModelAuditLabel(job));
      const output = job.output_json || {};
      const fields = Array.isArray(output.template_fields) ? output.template_fields.map(String) : [];
      const templateData = output.template_data && typeof output.template_data === "object" ? output.template_data : {};
      if (
        job.state !== "ready"
        || !String(output.genre || "").trim()
        || !String(output.template_key || "").trim()
        || !String(output.template_name || "").trim()
        || fields.length === 0
        || fields.some((field: string) => !String(templateData[field] || "").trim())
      ) {
        throw new Error(job.failure_message || "模型模板生成失败");
      }
      await persist(3, {
        genre: String(output.genre),
        subgenre: String(output.template_name),
        template_key: String(output.template_key),
        template_name: String(output.template_name),
        template_fields: fields,
        template_data: templateData,
        template_generation_job_id: job.id,
      });
      setError("");
    } catch (reason) {
      setError(readableError(reason, "AI模板生成失败"));
    } finally {
      setTemplateGenerating(false);
      setBusy(false);
    }
  };

  const requestTemplateGeneration = async () => {
    if (!draft || busy || !String(data.idea || "").trim()) return;
    let modelLabel: string;
    try {
      modelLabel = generationModelLabel(await getGenerationModelStatus());
    } catch (reason) {
      setError(readableError(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal mb-confirm-modal",
      title: "确认",
      content: `生成模板设定将使用 ${modelLabel}，确定继续吗？`,
      okText: "确定",
      cancelText: "取消",
      onOk() {
        void generateTemplate();
      },
    });
  };

  const templateFields = (data.template_fields || []) as string[];
  const templateReady = Boolean(data.template_key && data.template_name && templateFields.every((field) => String(data.template_data?.[field] || "").trim()));

  const nextDisabled = () => {
    if (step === 0) return data.writing_type !== "long";
    if (step === 1) return !["male", "female"].includes(data.audience);
    if (step === 2) return !String(data.idea || "").trim();
    if (step === 3) return !templateReady;
    if (step === 4) return !String(data.author_name || "").trim() || !String(data.title || "").trim();
    if (step === 5) return !data.cover_mode || (data.cover_mode === "upload" && !data.cover_image_data);
    return false;
  };

  const goNext = async () => {
    if (nextDisabled() || busy) return;
    setBusy(true);
    try {
      if (step === 5 && data.cover_mode === "system") {
        const patch = {
          cover_image_data: generateSystemCover(String(data.title || ""), String(data.author_name || ""), String(data.audience || "female")),
          cover_file_name: "system-cover.jpg",
        };
        updateData(patch);
        await persist(6, patch);
      } else if (step === 5 && data.cover_mode === "text") {
        const patch = { cover_image_data: "", cover_file_name: "" };
        updateData(patch);
        await persist(6, patch);
      } else if (step === 5 && data.cover_mode === "ai" && !data.cover_prompt) {
        if (!draft) throw new Error("建书草稿尚未就绪");
        const currentModel = await getGenerationModelStatus();
        setCoverTaskModelLabel(generationModelLabel(currentModel));
        const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
          method: "POST",
          body: JSON.stringify({
            scope_type: "novel_creation",
            scope_id: draft.id,
            kind: "novel_cover",
            input_snapshot: {
              audience: data.audience,
              genre: data.genre,
              subgenre: data.subgenre,
              idea: data.idea,
              title: data.title,
              template_name: data.template_name,
              template_data: data.template_data,
            },
            force_new: true,
          }),
        });
        setCoverTaskModelLabel(job.state === "ready" ? completedGenerationModelLabel(job) : generationModelAuditLabel(job));
        if (job.state !== "ready") {
          throw new Error(job.failure_message || "模型封面方案生成失败");
        }
        const patch = {
          cover_prompt: String(job.output_json?.cover_prompt || ""),
          cover_subtitle: String(job.output_json?.subtitle || ""),
          cover_generation_job_id: job.id,
        };
        updateData(patch);
        await persist(6, patch);
      } else {
        await persist(step + 1, data);
      }
      setError("");
    } catch (reason) {
      setError(readableError(reason, "进入下一步失败"));
    } finally {
      setBusy(false);
    }
  };

  const requestGoNext = async () => {
    if (step !== 5 || data.cover_mode !== "ai" || data.cover_prompt) {
      await goNext();
      return;
    }
    let modelLabel: string;
    try {
      modelLabel = generationModelLabel(await getGenerationModelStatus());
      setCoverTaskModelLabel(modelLabel);
    } catch (reason) {
      setError(readableError(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal mb-confirm-modal",
      title: "确认",
      content: `生成封面方案将使用 ${modelLabel}，确定继续吗？`,
      okText: "确定",
      cancelText: "取消",
      onOk: () => { void goNext(); },
    });
  };

  const chooseTemplate = (categoryOverride?: string) => {
    if (!templateCandidate) return;
    const category = categoryOverride || templateCategory || "自定义";
    updateData({
      genre: category,
      subgenre: templateCandidate.name,
      template_key: templateCandidate.key,
      template_name: templateCandidate.name,
      template_fields: templateCandidate.fields,
      template_data: {},
    });
    setTemplateModalOpen(false);
  };

  const generateName = async () => {
    if (!draft || busy) return;
    let modelLabel: string;
    try {
      modelLabel = generationModelLabel(await getGenerationModelStatus());
      setNamingTaskModelLabel(modelLabel);
    } catch (reason) {
      setError(readableError(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal mb-confirm-modal",
      title: "确认",
      content: `生成小说名称将使用 ${modelLabel}，确定继续吗？`,
      okText: "确定",
      cancelText: "取消",
      onOk() {
        setBusy(true);
        void (async () => {
          try {
            const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
              method: "POST",
              body: JSON.stringify({
                scope_type: "novel_creation",
                scope_id: draft.id,
                kind: "novel_naming",
                input_snapshot: {
                  audience: data.audience,
                  genre: data.genre,
                  subgenre: data.subgenre,
                  idea: data.idea,
                  template_name: data.template_name,
                  template_data: data.template_data,
                },
                force_new: true,
              }),
            });
            setNamingTaskModelLabel(job.state === "ready" ? completedGenerationModelLabel(job) : generationModelAuditLabel(job));
            const titles = Array.isArray(job.output_json?.titles) ? job.output_json.titles.slice(0, 8) : [];
            if (job.state !== "ready" || !titles.length) {
              throw new Error(job.failure_message || "模型没有返回有效书名");
            }
            updateData({
              title: titles.map((title: unknown, index: number) => `${index + 1}. ${String(title).trim()}`).join(" "),
              naming_generation_job_id: job.id,
            });
            setError("");
          } catch (reason) {
            setError(readableError(reason, "AI 取名失败"));
          } finally {
            setBusy(false);
          }
        })();
      },
    });
  };

  const uploadCover = async (event: any) => {
    const file = event.target.files?.[0] as File | undefined;
    if (!file) return;
    setBusy(true);
    try {
      updateData({ cover_image_data: await compressCover(file), cover_file_name: file.name });
      setError("");
    } catch (reason) {
      setError(readableError(reason, "上传封面失败"));
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  };

  const complete = async () => {
    if (!draft || busy) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ draft: NovelCreationDraftRecord; novel: NovelMetadataRecord }>(`/creation-drafts/${draft.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ expected_version: draft.version }),
      });
      window.localStorage.removeItem(CREATION_DRAFT_KEY);
      setCompletedNovel(result.novel);
      setError("");
    } catch (reason) {
      setError(readableError(reason, "创建作品失败"));
    } finally {
      setBusy(false);
    }
  };

  const renderTemplateForm = () => h(
    "div",
    { className: "mb-template-form" },
    h(
      "div",
      { className: "mb-template-current" },
      h("div", null, h("strong", null, "当前选择"), h("span", null, `${data.genre}·${data.template_name}`)),
      h(
        "div",
        { className: "mb-template-actions" },
        h(Button, { onClick: requestTemplateGeneration }, "重新生成"),
        h(Button, { className: "mb-orange-button", onClick: () => setTemplateModalOpen(true) }, "修改模板"),
      ),
    ),
    h("div", { className: "mb-template-heading" }, h("strong", null, "模板设定"), h("span", null, "可修改")),
    ...templateFields.map((field) => {
      const meta = TEMPLATE_FIELD_META[field] || { label: field, placeholder: "请填写" };
      return h(
        "label",
        { key: field, className: "mb-wizard-field" },
        h("span", null, meta.label),
        h(Input, { value: data.template_data?.[field] || "", placeholder: meta.placeholder, onChange: (event: any) => updateTemplateData(field, event.target.value) }),
      );
    }),
  );

  const renderStep = () => {
    if (step === 0) {
      return h(
        "div",
        { className: "mb-type-step" },
        h("h2", null, "选择创作类型"),
        h("p", null, "请选择您要创作的作品类型"),
        h(
          "div",
          { className: "mb-type-cards" },
          h(ChoiceCard, { selected: data.writing_type === "long", icon: BookOutlined, title: "长篇小说", copy: "多章节 · 大纲 · 角色", onClick: () => updateData({ writing_type: "long" }) }),
          h(ChoiceCard, { selected: false, icon: FileTextOutlined, title: "短篇小说", copy: "短篇 · 直接生成", onClick: () => setError("当前流程验收使用长篇小说") }),
        ),
      );
    }
    if (step === 1) {
      return h(
        "div",
        { className: "mb-wizard-body" },
        h("h2", null, "选择小说受众"),
        h("p", null, "请选择您的小说主要面向的读者群体"),
        h(
          "div",
          { className: "mb-audience-cards" },
          h(ChoiceCard, { selected: data.audience === "male", icon: ManOutlined, title: "男频", copy: "玄幻 · 都市 · 历史", onClick: () => updateData({ audience: "male" }) }),
          h(ChoiceCard, { selected: data.audience === "female", icon: WomanOutlined, title: "女频", copy: "言情 · 穿越 · 种田", onClick: () => updateData({ audience: "female" }) }),
        ),
      );
    }
    if (step === 2) {
      return h(
        "div",
        { className: "mb-wizard-body" },
        h("h2", null, "创作思路"),
        h("p", null, "用简洁的语言描述您的创作想法"),
        h(
          "div",
          { className: "mb-idea-label" },
          h("strong", null, "描述您的创作想法"),
          h("button", { type: "button", className: "mb-direct-template", onClick: goDirectToTemplate }, "已有作品点击直接填写模板"),
        ),
        h(Input.TextArea, {
          className: "mb-idea-input",
          rows: 7,
          maxLength: 2000,
          value: data.idea || "",
          placeholder: "例如：一个现代都市青年穿越到古代，成为了一名书生，凭借现代知识在古代混得风生水起...",
          onChange: (event: any) => updateData({ idea: event.target.value }),
        }),
        h(
          "div",
          { className: "mb-idea-meta" },
          h("span", { className: "mb-idea-tip" }, h(BulbOutlined), "提示：描述越详细，AI生成的模板越精准"),
          h("span", { className: "mb-char-count" }, `${String(data.idea || "").length}/2000`),
        ),
      );
    }
    if (step === 3) {
      return h(
        "div",
        { className: "mb-wizard-body" },
        h("h2", null, templateGenerating || data.template_key ? "智能模板生成" : "选择模板"),
        h("p", null, templateGenerating || data.template_key ? "AI根据您的创作思路自动选择最佳模板" : "请选择适合的模板"),
        templateGenerating
          ? h(
              "div",
              { className: "mb-template-generating" },
              h(Spin, { size: "large" }),
              h("strong", null, "AI正在分析您的创作思路"),
              h("span", null, templateTaskModelLabel ? `任务模型：${templateTaskModelLabel}` : "正在为您匹配最合适的模板设定"),
            )
          : data.template_key
          ? renderTemplateForm()
          : h(
              "div",
              { className: "mb-template-empty" },
              h(AppstoreOutlined),
              h("strong", null, "等待选择模板"),
              h(Button, { className: "mb-orange-button", onClick: () => setTemplateModalOpen(true) }, "选择模板"),
            ),
      );
    }
    if (step === 4) {
      return h(
        "div",
        { className: "mb-wizard-body mb-info-step" },
        h("h2", null, "作品信息"),
        h("p", null, "填写作者名称和小说名称"),
        h("label", { className: "mb-wizard-field" }, h("span", null, "作者名称 *"), h(Input, { value: data.author_name || "", maxLength: 120, placeholder: "请输入您的笔名", onChange: (event: any) => updateData({ author_name: event.target.value }) })),
        h("label", { className: "mb-wizard-field" }, h("span", null, "小说名称 *"), h(Input, { value: data.title || "", maxLength: 240, placeholder: "请输入小说名称", onChange: (event: any) => updateData({ title: event.target.value }) })),
        h(Button, {
          block: true,
          className: "mb-orange-button mb-ai-name",
          icon: busy ? null : data.title ? h(ReloadOutlined) : h(RobotOutlined),
          disabled: busy,
          onClick: generateName,
        }, busy ? "AI生成中..." : data.title ? "重新生成名称" : "AI帮我取名"),
        namingTaskModelLabel
          ? h("small", { className: "mb-name-cost" }, `取名模型：${namingTaskModelLabel}`)
          : null,
      );
    }
    if (step === 5) {
      const coverModes = [
        { key: "ai", icon: RobotOutlined, title: "AI智能生成", badge: "推荐", copy: "AI根据您的故事风格生成独一无二的封面方案", button: "开始生成精美封面" },
        { key: "text", icon: FileTextOutlined, title: "文字封面", copy: "直接显示书名和作者，不生成、不上传、也不保存图片", button: "使用文字封面" },
        { key: "system", icon: BookOutlined, title: "系统封面", copy: "根据小说分类自动生成，包含书名和作者", button: "生成系统封面" },
        { key: "upload", icon: PictureOutlined, title: "上传图片", copy: "上传您自己的图片，自动裁剪为3:4", button: "确认使用此封面" },
      ];
      return h(
        "div",
        { className: "mb-wizard-body" },
        h("h2", null, "选择封面"),
        h("p", null, "为您的作品选择一个精美的封面"),
        h("strong", { className: "mb-cover-label" }, "选择生成方式"),
        data.cover_mode === "ai" && coverTaskModelLabel ? h("small", { className: "mb-name-cost" }, `封面任务模型：${coverTaskModelLabel}`) : null,
        h(
          "div",
          { className: "mb-cover-mode-list" },
          ...coverModes.map((mode) => h(ChoiceCard, {
            key: mode.key,
            selected: data.cover_mode === mode.key,
            icon: mode.icon,
            title: mode.title,
            badge: mode.badge,
            copy: mode.copy,
            onClick: () => updateData({ cover_mode: mode.key, ...(mode.key !== "upload" ? { cover_image_data: "" } : {}) }),
          })),
        ),
        data.cover_mode === "upload"
          ? h(
              "label",
              { className: `mb-cover-upload${data.cover_image_data ? " has-image" : ""}` },
              data.cover_image_data
                ? h("img", { src: data.cover_image_data, alt: "已上传封面预览" })
                : h("span", null, h(UploadOutlined), "点击上传图片"),
              h("input", { type: "file", accept: "image/*", onChange: uploadCover }),
            )
          : data.cover_mode === "text"
            ? h(NovelCoverView, {
                novel: {
                  title: String(data.title || "未命名小说"),
                  author_name: String(data.author_name || "佚名"),
                  cover_mode: "text",
                  cover_image_data: "",
                },
                className: "mb-cover-text-preview",
                fallbackSrc: defaultNovelCover,
              })
            : null,
      );
    }
    return h(
      "div",
      { className: "mb-wizard-body mb-complete-step" },
      h("h2", null, "封面生成完成"),
      h("p", null, "您的专属封面已准备就绪"),
      h(NovelCoverView, {
        novel: {
          title: String(data.title || "新小说"),
          author_name: String(data.author_name || "佚名"),
          cover_mode: data.cover_mode,
          cover_image_data: String(data.cover_image_data || ""),
        },
        className: "mb-complete-cover",
        fallbackSrc: defaultNovelCover,
      }),
      h("div", { className: "mb-complete-book" }, h("strong", null, data.title), h("span", null, `${data.author_name} 著`)),
    );
  };

  const footerLabel = step === 0 ? "下一步" : step === 2 ? "确认并生成模板" : step === 3 ? "确认模板" : step === 5
    ? ({ ai: "开始生成精美封面", text: "使用文字封面", system: "生成系统封面", upload: "确认使用此封面" }[data.cover_mode as "ai" | "text" | "system" | "upload"] || "下一步")
    : "下一步";

  return h(
    Modal,
    {
      open: props.open,
      className: "anw-modal mb-create-modal",
      width: 600,
      title: "创建新小说",
      footer: null,
      maskClosable: false,
      keyboard: false,
      onCancel: closeWizard,
      destroyOnClose: false,
    },
    completedNovel
      ? h(
          "div",
          { className: "mb-create-success" },
          h(CheckOutlined, { className: "mb-create-success-icon" }),
          h("h2", null, "创建成功！"),
          h("p", null, `您的作品《${completedNovel.title}》已创建完成`),
          h(
            "div",
            { className: "mb-create-success-actions" },
            h(Button, {
              className: "mb-orange-button",
              onClick: async () => {
                const novel = completedNovel;
                setCompletedNovel(null);
                await props.onCompleted(novel, "outline");
              },
            }, "立即创建大纲"),
            h(Button, {
              onClick: async () => {
                const novel = completedNovel;
                setCompletedNovel(null);
                await props.onCompleted(novel);
              },
            }, "返回作品列表"),
          ),
        )
      : loading
      ? h("div", { className: "mb-wizard-loading" }, h(Spin), "正在读取建书草稿…")
      : h(
          React.Fragment,
          null,
          error ? h(Alert, { type: "error", showIcon: true, closable: true, message: error, onClose: () => setError("") }) : null,
          step > 0 ? h(WizardProgress, { step }) : null,
          renderStep(),
          templateGenerating ? null : h(
            "div",
            { className: "mb-wizard-footer" },
            step > 1 ? h(Button, { onClick: goBack, disabled: busy }, step === 6 ? "返回修改" : "上一步") : null,
            h(Button, {
              block: step === 0,
              className: "mb-orange-button",
              loading: busy && step !== 4,
              disabled: nextDisabled() || busy,
              onClick: step === 6 ? complete : step === 2 ? requestTemplateGeneration : requestGoNext,
            }, step === 6 ? "完成创建" : footerLabel),
          ),
        ),
    h(
      Modal,
      {
        open: templateModalOpen,
        className: "anw-modal mb-template-modal",
        width: 610,
        title: h("span", { className: "mb-template-modal-title" }, h(BgColorsOutlined), "选择模板"),
        footer: null,
        onCancel: () => setTemplateModalOpen(false),
      },
      h(
        "div",
        { className: "mb-template-tabs" },
        h("button", { type: "button", className: templateTab === "system" ? "is-active" : "", onClick: () => setTemplateTab("system") }, "系统模板"),
        h("button", { type: "button", className: templateTab === "custom" ? "is-active" : "", onClick: () => setTemplateTab("custom") }, "自定义模板"),
      ),
      templateTab === "system"
        ? h(
            React.Fragment,
            null,
            h("label", { className: "mb-field-label" }, "选择模板分类"),
            h(Select, {
              className: "mb-template-category-select",
              popupClassName: "mb-template-category-dropdown",
              value: templateCategory || undefined,
              placeholder: "请选择分类",
              options: Object.keys(SYSTEM_TEMPLATES).map((category) => ({ label: category, value: category })),
              onChange: (category: string) => {
                setTemplateCategory(category);
                setTemplateCandidate(null);
              },
            }),
            h("label", { className: "mb-field-label" }, "选择模板"),
            h(
              "div",
              { className: "mb-template-list" },
              !templateCategory
                ? h("div", { className: "mb-template-list-empty" }, h(AppstoreOutlined), "请先选择系统模板分类")
                : SYSTEM_TEMPLATES[templateCategory].map((template) => h(
                    "button",
                    { key: template.key, type: "button", className: templateCandidate?.key === template.key ? "is-active" : "", onClick: () => setTemplateCandidate(template) },
                    h("span", null, h("strong", null, template.name), h("small", null, `${templateCategory} · ${template.name}`)),
                    templateCandidate?.key === template.key ? h(CheckOutlined) : null,
                  )),
            ),
          )
        : h(
            "div",
            { className: "mb-template-list-empty mb-custom-template-empty" },
            h(AppstoreOutlined),
            h("strong", null, "使用自定义模板"),
            h("p", null, "按当前故事自由填写核心设定，不加入运营模板。"),
            h(Button, {
              onClick: () => setTemplateCandidate({ key: "custom-longform", name: "自定义长篇", fields: ["lead_name", "core_hook", "lead_identity", "growth_line", "world_rule"] }),
              className: templateCandidate?.key === "custom-longform" ? "mb-orange-button" : "",
            }, templateCandidate?.key === "custom-longform" ? "已选择" : "选择自定义模板"),
          ),
      h(
        "div",
        { className: "mb-modal-actions" },
        h(Button, { onClick: () => setTemplateModalOpen(false) }, "取消"),
        h(Button, { className: "mb-orange-button", disabled: !templateCandidate, onClick: () => {
          chooseTemplate(templateTab === "custom" ? (data.genre || "自定义") : templateCategory);
        } }, "确认选择"),
      ),
    ),
  );
}


export function NovelLibraryPage() {
  const [view, setView] = React.useState(initialLibraryView() as LibraryView);
  const [novels, setNovels] = React.useState([] as NovelSummary[]) as [NovelSummary[], any];
  const [activeNovelId, setActiveNovelId] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [wizardOpen, setWizardOpen] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const next = await apiRequest<NovelSummary[]>("/novels");
      setNovels(next);
      setActiveNovelId((current: string) => next.some((novel) => novel.id === current) ? current : (next[0]?.id || ""));
      setError("");
    } catch (reason) {
      setError(readableError(reason, "加载作品失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { void reload(); }, [reload]);

  const changeView = (next: LibraryView) => {
    setView(next);
    setLibraryUrl(next);
  };

  const activeNovel = novels.find((novel) => novel.id === activeNovelId) || novels[0];

  const openNovel = (novelId: string, section?: CreativeCenterWorkbenchSection) => {
    navigateNovelSurface(workbenchUrl(novelId, section));
  };

  const deleteNovel = (novel: NovelSummary) => {
    Modal.confirm({
      className: "anw-modal mb-confirm-modal",
      title: `删除《${novel.title}》`,
      content: "作品、分卷、章节和创作资料都会一起删除，此操作不可撤销。",
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      async onOk() {
        try {
          await apiRequest(`/novels/${novel.id}?expected_version=${novel.version}`, { method: "DELETE" });
          await reload();
        } catch (reason) {
          setError(readableError(reason, "删除作品失败"));
        }
      },
    });
  };

  if (view === "private-library") {
    return h(PrivateLibrary, { onBack: () => changeView("center") });
  }
  if (view === "embedding-settings") {
    return h(
      "main",
      { className: "anw-app mb-center-page mb-center-page--embedding" },
      h(
        "div",
        { className: "mb-center-inner" },
        h(Button, { icon: h(ArrowLeftOutlined), onClick: () => changeView("center") }, "返回创作中心"),
        h(EmbeddingConfigPage),
      ),
    );
  }

  return h(
    "main",
    { className: "anw-app mb-center-page" },
    h(
      "div",
      { className: "mb-center-inner" },
      h("header", { className: "mb-center-header" }, h("h1", null, "创作中心")),
      h(
        "nav",
        { className: "mb-center-actions", "aria-label": "创作中心功能" },
        h(CenterAction, { icon: DatabaseOutlined, label: "私有库", onClick: () => changeView("private-library") }),
        h(CenterAction, { icon: RobotOutlined, label: "向量模型接入", onClick: () => changeView("embedding-settings") }),
      ),
      error ? h(Alert, { type: "error", showIcon: true, closable: true, message: error, onClose: () => setError("") }) : null,
      loading
        ? h("div", { className: "mb-center-loading" }, h(Spin), "正在载入作品…")
        : activeNovel
          ? h(
              React.Fragment,
              null,
              h(NovelCard, {
                novel: activeNovel,
                onOpen: (section?: CreativeCenterWorkbenchSection) => openNovel(activeNovel.id, section),
                onDelete: () => deleteNovel(activeNovel),
              }),
              h(
                "div",
                { className: "mb-novel-switcher", "aria-label": `切换作品，共${novels.length}本` },
                ...novels.map((novel) => h(
                  "button",
                  { key: novel.id, type: "button", className: novel.id === activeNovel.id ? "is-active" : "", onClick: () => setActiveNovelId(novel.id), title: novel.title },
                  h(NovelCoverView, { novel, className: "mb-novel-switch-cover", fallbackSrc: defaultNovelCover }),
                  novel.id === activeNovel.id ? h(CheckOutlined, { className: "mb-novel-switch-check" }) : null,
                )),
                h("button", { type: "button", className: "mb-new-novel-tile", onClick: () => setWizardOpen(true) }, h(PlusOutlined), h("span", null, "新建")),
              ),
            )
          : h(
              "section",
              { className: "mb-empty-center" },
              h(BookOutlined),
              h("h2", null, "开始您的第一部长篇小说"),
              h("p", null, "通过六步建书完成受众、思路、模板、命名和封面。"),
              h(Button, { className: "mb-orange-button", icon: h(PlusOutlined), onClick: () => setWizardOpen(true) }, "创建新小说"),
            ),
    ),
    h(CreateNovelWizard, {
      open: wizardOpen,
      onClose: () => setWizardOpen(false),
      onCompleted: async (novel: NovelMetadataRecord, next?: "outline") => {
        setWizardOpen(false);
        await reload();
        setActiveNovelId(novel.id);
        if (next === "outline") openNovel(novel.id, "outline");
      },
    }),
  );
}
