import { ApiError, apiRequest } from "./api";
import {
  CandidateRecord,
  ChapterBriefRecord,
  CreativeGenerationRecord,
  DocumentRecord,
  GenerationJobRecord,
  IntelligenceItemRecord,
  IntelligenceProposalRecord,
  NovelRecord,
  PrivateAssetRecord,
  PrivateAssetType,
  RoleConstraints,
} from "./types";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Modal,
  Spin,
  Tag,
  Tabs,
} = host.antd;
const {
  ArrowDownOutlined,
  ArrowUpOutlined,
  AuditOutlined,
  BookOutlined,
  BulbOutlined,
  EditOutlined,
  FileTextOutlined,
  HistoryOutlined,
  PlusOutlined,
  SearchOutlined,
  SyncOutlined,
} = host.antdIcons;
const TextArea = Input.TextArea;
const FIXED_MODEL_ID = "MiniMax-M3";


interface ChapterWorkflowProps {
  novel: NovelRecord;
  document: DocumentRecord;
  onPrepareGeneration?: () => Promise<DocumentRecord | null>;
  onDocumentChanged: (document: DocumentRecord, status: string) => void;
  onError: (message: string) => void;
  onStatus: (message: string) => void;
  onPreviousChapter?: () => void;
  onNextChapter?: () => void;
  previousChapterTitle?: string;
  nextChapterTitle?: string;
}


interface BriefFormState {
  targetWordCount: number;
  expectationText: string;
  outlineText: string;
  forbiddenText: string;
  requiredRoles: string;
  allowedRoles: string;
  contextOnlyRoles: string;
  forbiddenRoles: string;
}


interface ReviewIssue {
  severity?: string;
  type?: string;
  evidence?: string;
  suggestion?: string;
}


const EMPTY_BRIEF_FORM: BriefFormState = {
  targetWordCount: 3500,
  expectationText: "",
  outlineText: "",
  forbiddenText: "",
  requiredRoles: "",
  allowedRoles: "",
  contextOnlyRoles: "",
  forbiddenRoles: "",
};


const ASSET_TABS: Array<{ key: PrivateAssetType; label: string; empty: string }> = [
  { key: "plot", label: "桥段配置", empty: "桥段配置" },
  { key: "writing_style", label: "写作风格", empty: "写作风格" },
  { key: "vocabulary", label: "特色词汇", empty: "特色词汇" },
  { key: "idea", label: "热梗奇思", empty: "热梗奇思" },
];


const INTELLIGENCE_GROUPS: Array<{ key: string; label: string; types: string[] }> = [
  { key: "character", label: "角色状态更新", types: ["character_state"] },
  { key: "relationship", label: "角色关系变化", types: ["relationship"] },
  { key: "storyline", label: "故事线进展", types: ["storyline_event"] },
  { key: "foreshadow", label: "伏笔进展", types: ["foreshadow_progress", "foreshadow_new"] },
  { key: "other", label: "其他情报", types: ["fact"] },
];


function splitNames(value: string): string[] {
  return Array.from(
    new Set(value.split(/[，,、\n]+/).map((item) => item.trim()).filter(Boolean)),
  );
}


function briefToForm(brief: ChapterBriefRecord): BriefFormState {
  return {
    targetWordCount: Math.max(3000, brief.target_word_count || 3500),
    expectationText: brief.expectation_text,
    outlineText: brief.outline_text,
    forbiddenText: brief.forbidden_text,
    requiredRoles: brief.role_constraints.required.join("、"),
    allowedRoles: brief.role_constraints.allowed.join("、"),
    contextOnlyRoles: brief.role_constraints.context_only.join("、"),
    forbiddenRoles: brief.role_constraints.forbidden.join("、"),
  };
}


function formRoleConstraints(form: BriefFormState): RoleConstraints {
  return {
    required: splitNames(form.requiredRoles),
    allowed: splitNames(form.allowedRoles),
    context_only: splitNames(form.contextOnlyRoles),
    forbidden: splitNames(form.forbiddenRoles),
  };
}


function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError) {
    if (typeof reason.detail === "string") return reason.detail;
    if (reason.detail && typeof reason.detail === "object") {
      const detail = reason.detail as Record<string, any>;
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.job?.failure_message === "string") return detail.job.failure_message;
      if (typeof detail.proposal?.failure_message === "string") return detail.proposal.failure_message;
      if (typeof detail.type === "string") return `${fallback}：${detail.type}`;
    }
  }
  return reason instanceof Error ? reason.message : fallback;
}


function stateLabel(state: string): string {
  return {
    running: "生成中",
    ready: "生成成功",
    accepted: "已采用",
    rejected: "已放弃",
    failed: "生成失败",
  }[state] ?? state;
}


function stateColor(state: string): string {
  if (state === "accepted" || state === "ready") return "success";
  if (state === "failed") return "error";
  if (state === "rejected") return "default";
  return "processing";
}


function formatDate(value: string | null): string {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}


function field(label: string, control: unknown, help?: string): unknown {
  return h(
    "label",
    { className: "anw-chapter-field" },
    h("strong", null, label),
    help ? h("span", null, help) : null,
    control,
  );
}


function groupedIntelligence(items: IntelligenceItemRecord[]) {
  return INTELLIGENCE_GROUPS.map((group) => ({
    ...group,
    items: items.filter((item) => group.types.includes(item.item_type)),
  })).filter((group) => group.items.length > 0);
}


export function ChapterWorkflowPanel(props: ChapterWorkflowProps) {
  const {
    novel,
    document,
    onPrepareGeneration,
    onDocumentChanged,
    onError,
    onStatus,
    onPreviousChapter,
    onNextChapter,
    previousChapterTitle,
    nextChapterTitle,
  } = props;
  const [brief, setBrief] = React.useState(null as ChapterBriefRecord | null);
  const [briefForm, setBriefForm] = React.useState(EMPTY_BRIEF_FORM);
  const [briefOpen, setBriefOpen] = React.useState(false);
  const [assetPickerOpen, setAssetPickerOpen] = React.useState(false);
  const [assets, setAssets] = React.useState([] as PrivateAssetRecord[]);
  const [assetTab, setAssetTab] = React.useState("plot" as PrivateAssetType);
  const [assetSearch, setAssetSearch] = React.useState("");
  const [selectedAssetIds, setSelectedAssetIds] = React.useState([] as string[]);
  const [quickAssetOpen, setQuickAssetOpen] = React.useState(false);
  const [quickAssetTitle, setQuickAssetTitle] = React.useState("");
  const [quickAssetContent, setQuickAssetContent] = React.useState("");
  const [generatingOpen, setGeneratingOpen] = React.useState(false);
  const [generationStage, setGenerationStage] = React.useState("正在分析前文、章纲和章节情节");
  const [jobsOpen, setJobsOpen] = React.useState(false);
  const [jobs, setJobs] = React.useState([] as GenerationJobRecord[]);
  const [featuredCandidateId, setFeaturedCandidateId] = React.useState("");
  const [intelligenceOpen, setIntelligenceOpen] = React.useState(false);
  const [selectedProposal, setSelectedProposal] = React.useState(null as IntelligenceProposalRecord | null);
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [reviewJob, setReviewJob] = React.useState(null as CreativeGenerationRecord | null);
  const [busyAction, setBusyAction] = React.useState("");

  React.useEffect(() => {
    setBrief(null);
    setBriefOpen(false);
    setAssetPickerOpen(false);
    setAssetSearch("");
    setSelectedAssetIds([]);
    setGeneratingOpen(false);
    setJobsOpen(false);
    setJobs([]);
    setFeaturedCandidateId("");
    setIntelligenceOpen(false);
    setSelectedProposal(null);
    setReviewOpen(false);
    setReviewJob(null);
  }, [document.id]);

  const loadBrief = async (): Promise<ChapterBriefRecord> => {
    const loaded = await apiRequest<ChapterBriefRecord>(`/documents/${document.id}/chapter-brief`);
    setBrief(loaded);
    setBriefForm(briefToForm(loaded));
    return loaded;
  };

  const openBrief = async () => {
    setBusyAction("brief-load");
    try {
      await loadBrief();
      setBriefOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载章纲失败"));
    } finally {
      setBusyAction("");
    }
  };

  const persistBrief = async (currentBrief: ChapterBriefRecord, form: BriefFormState): Promise<ChapterBriefRecord> => apiRequest<ChapterBriefRecord>(
    `/documents/${document.id}/chapter-brief`,
    {
      method: "PUT",
      body: JSON.stringify({
        expected_version: currentBrief.version,
        target_word_count: Math.max(3000, form.targetWordCount),
        expectation_text: form.expectationText,
        outline_text: form.outlineText,
        forbidden_text: form.forbiddenText,
        role_constraints: formRoleConstraints(form),
      }),
    },
  );

  const saveBrief = async () => {
    setBusyAction("brief-save");
    try {
      const currentBrief = brief ?? await loadBrief();
      const saved = await persistBrief(currentBrief, briefForm);
      setBrief(saved);
      setBriefForm(briefToForm(saved));
      setBriefOpen(false);
      onStatus("章纲已保存");
    } catch (reason) {
      onError(errorMessage(reason, "保存章纲失败"));
    } finally {
      setBusyAction("");
    }
  };

  const loadAssets = async () => {
    const loaded = await apiRequest<PrivateAssetRecord[]>("/private-assets");
    setAssets(loaded.filter((item) => !item.archived));
    return loaded;
  };

  const openAssetPicker = async () => {
    setBusyAction("assets-load");
    try {
      await loadAssets();
      setAssetPickerOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载私有库配置失败"));
    } finally {
      setBusyAction("");
    }
  };

  const openGenerationOptions = () => {
    if (document.visible_character_count === 0) {
      void openAssetPicker();
      return;
    }
    Modal.confirm({
      className: "anw-modal anw-simple-confirm",
      title: "确认",
      content: "重新生成将放弃当前内容，确定要重新生成吗？",
      okText: "确定",
      cancelText: "取消",
      onOk: openAssetPicker,
    });
  };

  const ensureBrief = async (): Promise<ChapterBriefRecord> => {
    const currentBrief = brief ?? await loadBrief();
    if (currentBrief.version > 0 && currentBrief.target_word_count >= 3000) return currentBrief;
    const form = briefToForm(currentBrief);
    const saved = await persistBrief(currentBrief, { ...form, targetWordCount: Math.max(3500, form.targetWordCount) });
    setBrief(saved);
    setBriefForm(briefToForm(saved));
    return saved;
  };

  const generateBody = async (assetIds: string[] = selectedAssetIds) => {
    setAssetPickerOpen(false);
    setGenerationStage("正在分析前文、章纲和章节情节");
    setGeneratingOpen(true);
    setBusyAction("generate");
    try {
      if (onPrepareGeneration) {
        const prepared = await onPrepareGeneration();
        if (!prepared) throw new Error("当前正文保存失败，请稍后重试");
      }
      const currentBrief = await ensureBrief();
      onStatus(`${FIXED_MODEL_ID} 正在创作章节正文…`);
      const job = await apiRequest<GenerationJobRecord>(
        `/documents/${document.id}/generation-jobs/body?agent_id=ai-novel-writer`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_brief_version: currentBrief.version,
            force_new: true,
            asset_ids: assetIds,
            requested_model_id: FIXED_MODEL_ID,
          }),
        },
      );
      if (!job.candidate) throw new Error(job.failure_message || "模型没有返回正文");
      if (job.actual_model_id !== FIXED_MODEL_ID) throw new Error("实际模型不是 MiniMax-M3，结果已作废");
      setGenerationStage("正文已生成，正在写入编辑器");
      const result = await apiRequest<{ document: DocumentRecord; candidate: CandidateRecord }>(
        `/candidates/${job.candidate.id}/adopt`,
        {
          method: "POST",
          body: JSON.stringify({ expected_draft_version: job.candidate.base_draft_version }),
        },
      );
      setFeaturedCandidateId(result.candidate.id);
      setSelectedAssetIds([]);
      onDocumentChanged(result.document, `${FIXED_MODEL_ID} 正文生成完成 · ${result.candidate.visible_character_count} 字`);
    } catch (reason) {
      const message = errorMessage(reason, "生成正文失败");
      onError(message);
      onStatus(message.includes("低于") ? "本次不足 3000 字，必须整章重写" : "正文生成失败");
    } finally {
      setGeneratingOpen(false);
      setBusyAction("");
    }
  };

  const saveQuickAsset = async () => {
    if (!quickAssetTitle.trim() || !quickAssetContent.trim()) return;
    setBusyAction("asset-create");
    try {
      const created = await apiRequest<PrivateAssetRecord>("/private-assets", {
        method: "POST",
        body: JSON.stringify({ asset_type: assetTab, title: quickAssetTitle.trim(), content: quickAssetContent.trim() }),
      });
      await loadAssets();
      setSelectedAssetIds((current: string[]) => Array.from(new Set([...current, created.id])));
      setQuickAssetTitle("");
      setQuickAssetContent("");
      setQuickAssetOpen(false);
    } catch (reason) {
      onError(errorMessage(reason, "添加私有库配置失败"));
    } finally {
      setBusyAction("");
    }
  };

  const loadJobs = async () => {
    const loaded = await apiRequest<GenerationJobRecord[]>(`/documents/${document.id}/generation-jobs`);
    setJobs(loaded);
    return loaded;
  };

  const openJobs = async () => {
    setBusyAction("jobs-load");
    try {
      const loaded = await loadJobs();
      const best = loaded
        .filter((job) => job.candidate)
        .sort((left, right) => right.output_visible_character_count - left.output_visible_character_count)[0];
      setFeaturedCandidateId(best?.candidate?.id || "");
      setJobsOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载生成历史失败"));
    } finally {
      setBusyAction("");
    }
  };

  const restoreCandidate = async (job: GenerationJobRecord) => {
    const candidate = job.candidate;
    if (!candidate) return;
    setBusyAction(`restore:${candidate.id}`);
    try {
      let updated: DocumentRecord;
      if (candidate.state === "ready") {
        const result = await apiRequest<{ document: DocumentRecord }>(`/candidates/${candidate.id}/adopt`, {
          method: "POST",
          body: JSON.stringify({ expected_draft_version: document.draft_version }),
        });
        updated = result.document;
      } else if (candidate.adopted_revision_id) {
        const result = await apiRequest<{ document: DocumentRecord }>(
          `/documents/${document.id}/revisions/${candidate.adopted_revision_id}/restore`,
          { method: "POST", body: JSON.stringify({ expected_draft_version: document.draft_version }) },
        );
        updated = result.document;
      } else {
        throw new Error("这次生成没有可恢复的正文版本");
      }
      setJobsOpen(false);
      onDocumentChanged(updated, `已恢复第 ${job.attempt} 次生成正文`);
    } catch (reason) {
      onError(errorMessage(reason, "恢复生成版本失败"));
    } finally {
      setBusyAction("");
    }
  };

  const loadLatestIntelligence = async () => {
    const loaded = await apiRequest<IntelligenceProposalRecord[]>(`/documents/${document.id}/intelligence-proposals`);
    const current = loaded.find((proposal) => proposal.source_current) ?? loaded[0] ?? null;
    setSelectedProposal(current);
    return current;
  };

  const openIntelligence = async () => {
    setBusyAction("intelligence-load");
    try {
      await loadLatestIntelligence();
      setIntelligenceOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载本章情报失败"));
    } finally {
      setBusyAction("");
    }
  };

  const runSyncProgress = async () => {
    setBusyAction("sync");
    setGenerationStage("正在从本章正文提取角色、关系、故事线与伏笔进展");
    setGeneratingOpen(true);
    try {
      const prepared = onPrepareGeneration ? await onPrepareGeneration() : document;
      if (!prepared) throw new Error("当前正文保存失败，请稍后重试");
      const checkpoint = await apiRequest<{ document: DocumentRecord }>(`/documents/${prepared.id}/checkpoints`, {
        method: "POST",
        body: JSON.stringify({ expected_draft_version: prepared.draft_version }),
      });
      const source = checkpoint.document;
      if (!source.base_revision_id) throw new Error("本章正文尚未形成可同步版本");
      onDocumentChanged(source, `${FIXED_MODEL_ID} 正在同步进展…`);
      let proposal = await apiRequest<IntelligenceProposalRecord>(
        `/documents/${source.id}/intelligence-proposals?agent_id=ai-novel-writer`,
        { method: "POST", body: JSON.stringify({ revision_id: source.base_revision_id }) },
      );
      if (proposal.actual_model_id !== FIXED_MODEL_ID) throw new Error("实际模型不是 MiniMax-M3，情报结果已作废");
      const pendingIds = proposal.items.filter((item) => item.review_state === "pending").map((item) => item.id);
      if (pendingIds.length > 0) {
        proposal = await apiRequest<IntelligenceProposalRecord>(`/intelligence-proposals/${proposal.id}/commit`, {
          method: "POST",
          body: JSON.stringify({ accepted_item_ids: pendingIds, item_overrides: {} }),
        });
      }
      setSelectedProposal(proposal);
      setIntelligenceOpen(true);
      onStatus(`同步进展完成 · ${proposal.items.length} 条本章情报`);
    } catch (reason) {
      onError(errorMessage(reason, "同步进展失败"));
      onStatus("同步进展失败");
    } finally {
      setGeneratingOpen(false);
      setBusyAction("");
    }
  };

  const confirmSyncProgress = () => {
    Modal.confirm({
      className: "anw-modal anw-sync-confirm",
      title: "确认",
      width: 520,
      content: h("div", { className: "anw-sync-copy" },
        h("p", null, `本次同步进展将分析 ${document.visible_character_count} 字正文。`),
        h("p", null, "AI 将根据当前章节内容提取情报信息（角色、伏笔、剧情线等），并更新到作品创作资料中。"),
        h("strong", null, "确认同步并继续吗？"),
      ),
      okText: "确定",
      cancelText: "取消",
      onOk: () => { void runSyncProgress(); },
    });
  };

  const runReview = async () => {
    setBusyAction("review");
    setGenerationStage("正在从文字流畅、描写生动、人物一致性等维度审阅正文");
    setGeneratingOpen(true);
    try {
      const prepared = onPrepareGeneration ? await onPrepareGeneration() : document;
      if (!prepared) throw new Error("当前正文保存失败，请稍后重试");
      const currentBrief = await ensureBrief();
      const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
        method: "POST",
        body: JSON.stringify({
          scope_type: "document",
          scope_id: prepared.id,
          novel_id: novel.id,
          document_id: prepared.id,
          kind: "review",
          input_snapshot: {
            novel_title: novel.title,
            chapter_title: prepared.title,
            visible_character_count: prepared.visible_character_count,
            outline_text: currentBrief.outline_text,
            expectation_text: currentBrief.expectation_text,
            content_markdown: prepared.content_markdown,
          },
          requested_model_id: FIXED_MODEL_ID,
          force_new: true,
        }),
      });
      if (job.state !== "ready" || job.actual_model_id !== FIXED_MODEL_ID) throw new Error(job.failure_message || "MiniMax-M3 审稿失败");
      setReviewJob(job);
      setReviewOpen(true);
      onStatus("AI 审稿完成");
    } catch (reason) {
      onError(errorMessage(reason, "AI 审稿失败"));
    } finally {
      setGeneratingOpen(false);
      setBusyAction("");
    }
  };

  const confirmReview = () => {
    Modal.confirm({
      className: "anw-modal anw-review-confirm",
      title: "确认",
      width: 520,
      content: "审稿将使用 MiniMax-M3 从文字流畅、描写生动、人物一致性、时空因果、伏笔与重复内容等维度分析正文并给出修改建议。是否开始审稿？",
      okText: "确定",
      cancelText: "取消",
      onOk: () => { void runReview(); },
    });
  };

  const filteredAssets = assets.filter((item: PrivateAssetRecord) => item.asset_type === assetTab && (!assetSearch.trim() || `${item.title}\n${item.content}`.includes(assetSearch.trim())));
  const currentAssetLabel = ASSET_TABS.find((item) => item.key === assetTab)?.label || "私有库配置";
  const intelligenceGroups = groupedIntelligence(selectedProposal?.items ?? []);
  const reviewIssues = Array.isArray(reviewJob?.output_json?.issues) ? reviewJob?.output_json.issues as ReviewIssue[] : [];

  return h(
    React.Fragment,
    null,
    h("div", { className: "anw-workflow-panel" },
      h(Button, { className: "anw-generate-button", icon: h(BookOutlined), onClick: openGenerationOptions, loading: busyAction === "generate" || busyAction === "assets-load" }, document.visible_character_count > 0 ? "重新生成" : "生成正文"),
      h(Button, { className: "anw-outline-button", icon: h(EditOutlined), onClick: openBrief, loading: busyAction === "brief-load" }, "修改章纲"),
      h(Button, { className: "anw-sync-button", icon: h(SyncOutlined), onClick: confirmSyncProgress, loading: busyAction === "sync", disabled: document.visible_character_count === 0 }, "同步进展"),
    ),
    h("aside", { className: "anw-editor-side-tools", "aria-label": "章节工具" },
      h(Button, { className: "is-orange", shape: "circle", icon: h(AuditOutlined), onClick: confirmReview, disabled: document.visible_character_count === 0, title: "审稿" }, h("span", null, "审稿")),
      h(Button, { className: "is-orange", shape: "circle", icon: h(BulbOutlined), onClick: openIntelligence, loading: busyAction === "intelligence-load", title: "情报" }, h("span", null, "情报")),
      h(Button, { shape: "circle", icon: h(HistoryOutlined), onClick: openJobs, loading: busyAction === "jobs-load", title: "历史" }, h("span", null, "历史")),
      h(Button, { className: "is-orange is-chapter-nav", shape: "circle", icon: h(ArrowUpOutlined), onClick: onPreviousChapter, disabled: !onPreviousChapter, title: previousChapterTitle ? `上一章：${previousChapterTitle}` : "已经是第一章", "aria-label": previousChapterTitle ? `上一章：${previousChapterTitle}` : "已经是第一章" }),
      h(Button, { className: "is-orange is-chapter-nav", shape: "circle", icon: h(ArrowDownOutlined), onClick: onNextChapter, disabled: !onNextChapter, title: nextChapterTitle ? `下一章：${nextChapterTitle}` : "已经是最后一章", "aria-label": nextChapterTitle ? `下一章：${nextChapterTitle}` : "已经是最后一章" }),
    ),
    h(Modal, {
      open: briefOpen,
      className: "anw-modal anw-outline-edit-modal",
      title: h("div", { className: "anw-outline-edit-title" }, h(FileTextOutlined), h("strong", null, "修改章纲"), h("span", null, document.title)),
      width: 720,
      centered: true,
      onCancel: () => setBriefOpen(false),
      footer: [h(Button, { key: "cancel", onClick: () => setBriefOpen(false) }, "取消"), h(Button, { key: "save", type: "primary", loading: busyAction === "brief-save", onClick: saveBrief }, "保存章纲")],
    }, h("div", { className: "anw-outline-edit-body" },
      field("章节大纲", h(TextArea, { rows: 12, showCount: true, maxLength: 30000, "aria-label": "章节大纲", value: briefForm.outlineText, onChange: (event: any) => setBriefForm((current: BriefFormState) => ({ ...current, outlineText: event.target.value })), placeholder: "请输入章节大纲..." })),
      field("目标字数", h(InputNumber, { min: 3000, max: 5000, step: 100, "aria-label": "目标字数", value: briefForm.targetWordCount, onChange: (value: number | null) => setBriefForm((current: BriefFormState) => ({ ...current, targetWordCount: value ?? 3500 })) }), "每章 3000-5000 字；低于 3000 字的生成结果不能采用。"),
    )),
    h(Modal, {
      open: assetPickerOpen,
      className: "anw-modal anw-asset-modal",
      title: "选择私有库配置",
      width: 860,
      centered: true,
      onCancel: () => setAssetPickerOpen(false),
      footer: [h(Button, { key: "skip", onClick: () => void generateBody([]) }, "跳过"), h(Button, { key: "generate", type: "primary", onClick: () => void generateBody(selectedAssetIds) }, `确定选择${selectedAssetIds.length ? `（${selectedAssetIds.length}）` : ""}`)],
    }, h("section", { className: "anw-asset-picker" },
      h("p", { className: "anw-asset-picker-copy" }, "AI 将重点展示选中的内容到生成结果中"),
      h("div", { className: "anw-asset-search-row" }, h(Input, { value: assetSearch, prefix: h(SearchOutlined), placeholder: "搜索私有库配置", onChange: (event: any) => setAssetSearch(event.target.value) }), h(Button, { type: "link", icon: h(PlusOutlined), onClick: () => setQuickAssetOpen(true) }, "快速添加")),
      h(Tabs, { activeKey: assetTab, onChange: (key: string) => setAssetTab(key as PrivateAssetType), items: ASSET_TABS.map((tab) => ({
        key: tab.key,
        label: tab.label,
        children: filteredAssets.length ? h("div", { className: "anw-asset-grid" }, ...filteredAssets.map((asset: PrivateAssetRecord) => {
          const selected = selectedAssetIds.includes(asset.id);
          return h("button", { type: "button", key: asset.id, className: `anw-asset-card${selected ? " is-selected" : ""}`, onClick: () => setSelectedAssetIds((current: string[]) => selected ? current.filter((id) => id !== asset.id) : [...current, asset.id]) }, h(Checkbox, { checked: selected, tabIndex: -1 }), h("span", null, h("strong", null, asset.title), h("small", null, asset.content)));
        })) : h("div", { className: "anw-asset-empty" }, h(Empty, { description: `暂无可选${tab.empty}` })),
      })) }),
    )),
    h(Modal, {
      open: quickAssetOpen,
      className: "anw-modal anw-quick-asset-modal",
      title: `快速添加${currentAssetLabel}`,
      width: 520,
      centered: true,
      onCancel: () => setQuickAssetOpen(false),
      footer: [h(Button, { key: "cancel", onClick: () => setQuickAssetOpen(false) }, "取消"), h(Button, { key: "save", type: "primary", loading: busyAction === "asset-create", disabled: !quickAssetTitle.trim() || !quickAssetContent.trim(), onClick: saveQuickAsset }, "添加并选中")],
    }, h("div", { className: "anw-quick-asset-body" }, field("名称", h(Input, { value: quickAssetTitle, maxLength: 160, onChange: (event: any) => setQuickAssetTitle(event.target.value), placeholder: `给这条${currentAssetLabel}起个名字` })), field("内容", h(TextArea, { rows: 7, value: quickAssetContent, maxLength: 12000, showCount: true, onChange: (event: any) => setQuickAssetContent(event.target.value), placeholder: "输入希望本次正文重点采用的内容" })))),
    h(Modal, { open: generatingOpen, className: "anw-modal anw-generating-modal", width: 520, centered: true, closable: false, maskClosable: false, keyboard: false, footer: null }, h("section", { className: "anw-generation-progress" }, h(Spin, { size: "large" }), h("h2", null, `${FIXED_MODEL_ID} 正在工作`), h("p", null, generationStage), h("span", null, "完成后将自动返回当前章节"))),
    h(Modal, {
      open: jobsOpen,
      className: "anw-modal anw-generation-history-modal",
      title: h("div", { className: "anw-history-title" }, h("strong", null, `生成历史（共 ${jobs.length} 次）`), h(Tag, { color: "processing" }, FIXED_MODEL_ID)),
      width: 760,
      centered: true,
      footer: null,
      onCancel: () => setJobsOpen(false),
    }, jobs.length === 0 ? h(Empty, { description: "还没有正文生成记录" }) : h("div", { className: "anw-generation-history-list" }, ...jobs.map((job: GenerationJobRecord) => {
      const candidate = job.candidate;
      const state = candidate?.state ?? job.state;
      return h("article", { key: job.id, className: `anw-history-card${candidate?.id === featuredCandidateId ? " is-featured" : ""}` },
        h("header", null, h("div", null, h("strong", null, `第 ${job.attempt || 1} 次生成`), h("span", null, formatDate(job.completed_at || job.created_at))), h(Tag, { color: stateColor(state) }, stateLabel(state))),
        h("div", { className: "anw-history-meta" }, h("span", null, `正文 ${job.output_visible_character_count || candidate?.visible_character_count || 0} 字`), h("span", null, `目标 ${job.target_visible_character_count || 3000} 字`), h("span", null, job.actual_model_id || job.requested_model_id || FIXED_MODEL_ID)),
        candidate ? h("p", null, candidate.content_text.slice(0, 230) || "本次生成正文为空") : h("p", { className: "is-error" }, job.failure_message || "本次生成没有可用正文"),
        h("footer", null, job.asset_snapshot?.length ? h("small", null, `采用私有库：${job.asset_snapshot.map((item: GenerationJobRecord["asset_snapshot"][number]) => item.title).join("、")}`) : h("small", null, "未选择私有库配置"), h(Button, { disabled: !candidate || candidate.state === "rejected", loading: busyAction === `restore:${candidate?.id}`, onClick: () => void restoreCandidate(job) }, candidate ? "恢复此版本" : "需要整章重写")),
      );
    }))),
    h(
      Modal,
      {
        open: intelligenceOpen,
        className: "anw-modal anw-intelligence-modal",
        title: h("div", { className: "anw-intelligence-title" }, h("strong", null, "本章章节情报"), h("span", null, "（本内容由AI生成）")),
        width: 800,
        centered: true,
        onCancel: () => setIntelligenceOpen(false),
        footer: [h(Button, { key: "close", type: "primary", onClick: () => setIntelligenceOpen(false) }, "关闭")],
      },
      !selectedProposal || intelligenceGroups.length === 0
        ? h(Empty, { description: "本章还没有情报；完成正文后点击“同步进展”生成" })
        : h(
            "div",
            { className: "anw-intelligence-groups" },
            ...intelligenceGroups.map((group) => h(
              "section",
              { key: group.key },
              h("h3", null, `${group.label}（${group.items.length}）`),
              ...group.items.map((item) => h(
                "article",
                { key: item.id },
                h("strong", null, item.suggested_payload.subject),
                h(
                  "div",
                  null,
                  h("span", null, h("small", null, "变化类型："), item.suggested_payload.predicate),
                  h("span", null, h("small", null, "最新进展："), item.suggested_payload.object),
                ),
              )),
            )),
          ),
    ),
    h(Modal, {
      open: reviewOpen,
      className: "anw-modal anw-review-result-modal",
      title: h("div", { className: "anw-review-title" }, h(AuditOutlined), h("strong", null, "AI审稿报告"), h(Tag, { color: "processing" }, FIXED_MODEL_ID)),
      width: 820,
      centered: true,
      footer: [h(Button, { key: "close", type: "primary", onClick: () => setReviewOpen(false) }, "关闭")],
      onCancel: () => setReviewOpen(false),
    }, reviewJob ? h("div", { className: "anw-review-result" }, h(Alert, { type: reviewJob.output_json?.passed ? "success" : "warning", showIcon: true, message: reviewJob.output_json?.passed ? "本章通过基础审阅" : "本章存在需要修改的问题", description: String(reviewJob.output_json?.summary || "MiniMax-M3 已完成本章审阅。") }), reviewIssues.length ? h("div", { className: "anw-review-issues" }, ...reviewIssues.map((issue, index) => h(Card, { key: `${issue.type}-${index}`, size: "small" }, h("header", null, h(Tag, { color: issue.severity === "P0" || issue.severity === "P1" ? "error" : "warning" }, issue.severity || "P2"), h("strong", null, issue.type || "正文问题")), issue.evidence ? h("p", null, h("b", null, "原文依据："), issue.evidence) : null, issue.suggestion ? h("p", null, h("b", null, "修改建议："), issue.suggestion) : null))) : h(Empty, { description: "未发现需要单列的问题" })) : h(Empty, { description: "暂无审稿结果" })),
  );
}
