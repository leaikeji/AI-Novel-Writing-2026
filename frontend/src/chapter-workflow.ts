import { ApiError, apiRequest } from "./api";
import { factStatusLabel, factTypeLabel } from "./presenters";
import {
  CandidateRecord,
  ChapterBriefRecord,
  DocumentRecord,
  GenerationJobRecord,
  IntelligenceProposalRecord,
  NovelRecord,
  RoleConstraints,
  StoryFactRecord,
} from "./types";


const host = window.QwenPaw.host;
const React = host.React;
const {
  Alert,
  Button,
  Card,
  Checkbox,
  Divider,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} = host.antd;
const {
  BookOutlined,
  BulbOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  HistoryOutlined,
} = host.antdIcons;
const TextArea = Input.TextArea;


interface ChapterWorkflowProps {
  novel: NovelRecord;
  document: DocumentRecord;
  onDocumentChanged: (document: DocumentRecord, status: string) => void;
  onError: (message: string) => void;
  onStatus: (message: string) => void;
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


const EMPTY_BRIEF_FORM: BriefFormState = {
  targetWordCount: 2000,
  expectationText: "",
  outlineText: "",
  forbiddenText: "",
  requiredRoles: "",
  allowedRoles: "",
  contextOnlyRoles: "",
  forbiddenRoles: "",
};


function splitNames(value: string): string[] {
  return Array.from(
    new Set(value.split(/[，,、\n]+/).map((item) => item.trim()).filter(Boolean)),
  );
}


function briefToForm(brief: ChapterBriefRecord): BriefFormState {
  return {
    targetWordCount: brief.target_word_count,
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
      const detail = reason.detail as Record<string, unknown>;
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.type === "string") return `${fallback}：${detail.type}`;
    }
  }
  return reason instanceof Error ? reason.message : fallback;
}


function stateLabel(state: string): string {
  return {
    running: "生成中",
    ready: "待复核",
    accepted: "已采用",
    rejected: "已拒绝",
    partially_accepted: "部分采用",
    superseded: "来源已过期",
    failed: "失败",
  }[state] ?? state;
}


function stateColor(state: string): string {
  if (state === "accepted") return "success";
  if (state === "ready" || state === "partially_accepted") return "processing";
  if (state === "failed" || state === "superseded") return "error";
  if (state === "rejected") return "default";
  return "warning";
}


function field(
  label: string,
  control: unknown,
  help?: string,
): unknown {
  return React.createElement(
    "div",
    { style: { width: "100%" } },
    React.createElement(Typography.Text, { strong: true }, label),
    help
      ? React.createElement(
          Typography.Text,
          { type: "secondary", style: { display: "block", marginBlock: 3 } },
          help,
        )
      : null,
    control,
  );
}


export function ChapterWorkflowPanel(props: ChapterWorkflowProps) {
  const { novel, document, onDocumentChanged, onError, onStatus } = props;
  const [brief, setBrief] = React.useState(null as ChapterBriefRecord | null);
  const [briefForm, setBriefForm] = React.useState(EMPTY_BRIEF_FORM);
  const [briefOpen, setBriefOpen] = React.useState(false);
  const [jobsOpen, setJobsOpen] = React.useState(false);
  const [intelligenceOpen, setIntelligenceOpen] = React.useState(false);
  const [ledgerOpen, setLedgerOpen] = React.useState(false);
  const [jobs, setJobs] = React.useState([] as GenerationJobRecord[]);
  const [selectedCandidate, setSelectedCandidate] = React.useState(null as CandidateRecord | null);
  const [proposals, setProposals] = React.useState([] as IntelligenceProposalRecord[]);
  const [selectedProposal, setSelectedProposal] = React.useState(null as IntelligenceProposalRecord | null);
  const [selectedItemIds, setSelectedItemIds] = React.useState([] as string[]);
  const [facts, setFacts] = React.useState([] as StoryFactRecord[]);
  const [busyAction, setBusyAction] = React.useState("");
  const [workflowError, setWorkflowError] = React.useState("");

  React.useEffect(() => {
    setBrief(null);
    setJobs([]);
    setSelectedCandidate(null);
    setProposals([]);
    setSelectedProposal(null);
    setSelectedItemIds([]);
    setBriefOpen(false);
    setJobsOpen(false);
    setIntelligenceOpen(false);
    setLedgerOpen(false);
    setWorkflowError("");
  }, [document.id]);

  const loadBrief = async (): Promise<ChapterBriefRecord> => {
    const loaded = await apiRequest<ChapterBriefRecord>(
      `/documents/${document.id}/chapter-brief`,
    );
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
      onError(errorMessage(reason, "加载章节任务书失败"));
    } finally {
      setBusyAction("");
    }
  };

  const saveBrief = async () => {
    setBusyAction("brief-save");
    try {
      const saved = await apiRequest<ChapterBriefRecord>(
        `/documents/${document.id}/chapter-brief`,
        {
          method: "PUT",
          body: JSON.stringify({
            expected_version: brief?.version ?? 0,
            target_word_count: briefForm.targetWordCount,
            expectation_text: briefForm.expectationText,
            outline_text: briefForm.outlineText,
            forbidden_text: briefForm.forbiddenText,
            role_constraints: formRoleConstraints(briefForm),
          }),
        },
      );
      setBrief(saved);
      setBriefForm(briefToForm(saved));
      setBriefOpen(false);
      onStatus("章节任务书已保存");
    } catch (reason) {
      onError(errorMessage(reason, "保存章节任务书失败"));
    } finally {
      setBusyAction("");
    }
  };

  const loadJobs = async (): Promise<GenerationJobRecord[]> => {
    const loaded = await apiRequest<GenerationJobRecord[]>(
      `/documents/${document.id}/generation-jobs`,
    );
    setJobs(loaded);
    const firstCandidate = loaded.find((job) => job.candidate)?.candidate ?? null;
    setSelectedCandidate(firstCandidate);
    return loaded;
  };

  const openJobs = async () => {
    setBusyAction("jobs-load");
    try {
      await loadJobs();
      setJobsOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载候选历史失败"));
    } finally {
      setBusyAction("");
    }
  };

  const generateCandidate = async () => {
    setBusyAction("generate");
    try {
      const currentBrief = brief ?? await loadBrief();
      if (currentBrief.version === 0) {
        setBriefOpen(true);
        onStatus("请先填写并保存章节任务书");
        return;
      }
      onStatus("AI 正在生成候选稿；当前正文不会被修改");
      const job = await apiRequest<GenerationJobRecord>(
        `/documents/${document.id}/generation-jobs/body?agent_id=ai-novel-writer`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_brief_version: currentBrief.version,
            force_new: true,
          }),
        },
      );
      const loaded = await loadJobs();
      setSelectedCandidate(job.candidate ?? loaded.find((item) => item.candidate)?.candidate ?? null);
      setJobsOpen(true);
      onStatus("AI 候选稿已生成，尚未写入正文");
    } catch (reason) {
      onError(errorMessage(reason, "生成候选稿失败"));
      onStatus("候选生成失败，正文未变化");
    } finally {
      setBusyAction("");
    }
  };

  const adopt = async (candidate: CandidateRecord) => {
    setBusyAction(`adopt:${candidate.id}`);
    try {
      const result = await apiRequest<{ document: DocumentRecord; candidate: CandidateRecord }>(
        `/candidates/${candidate.id}/adopt`,
        {
          method: "POST",
          body: JSON.stringify({ expected_draft_version: document.draft_version }),
        },
      );
      onDocumentChanged(result.document, "候选稿已采用并建立正式版本");
      await loadJobs();
    } catch (reason) {
      onError(errorMessage(reason, "采用候选稿失败"));
    } finally {
      setBusyAction("");
    }
  };

  const reject = async (candidate: CandidateRecord) => {
    setBusyAction(`reject:${candidate.id}`);
    try {
      await apiRequest(`/candidates/${candidate.id}/reject`, { method: "POST" });
      await loadJobs();
      onStatus("候选稿已拒绝，正文未变化");
    } catch (reason) {
      onError(errorMessage(reason, "拒绝候选稿失败"));
    } finally {
      setBusyAction("");
    }
  };

  const loadProposals = async (): Promise<IntelligenceProposalRecord[]> => {
    const loaded = await apiRequest<IntelligenceProposalRecord[]>(
      `/documents/${document.id}/intelligence-proposals`,
    );
    setProposals(loaded);
    const selected = loaded[0] ?? null;
    setSelectedProposal(selected);
    setSelectedItemIds([]);
    return loaded;
  };

  const openIntelligence = async () => {
    setBusyAction("intelligence-load");
    try {
      await loadProposals();
      setIntelligenceOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载章节情报失败"));
    } finally {
      setBusyAction("");
    }
  };

  const extractIntelligence = async () => {
    if (!document.base_revision_id) {
      const message = "当前章节还没有正式版本，请先建立检查点";
      setWorkflowError(message);
      onError(message);
      return;
    }
    setBusyAction("intelligence-extract");
    setWorkflowError("");
    try {
      onStatus("AI 正在提取候选情报；故事账本不会自动变化");
      const proposal = await apiRequest<IntelligenceProposalRecord>(
        `/documents/${document.id}/intelligence-proposals?agent_id=ai-novel-writer`,
        {
          method: "POST",
          body: JSON.stringify({ revision_id: document.base_revision_id }),
        },
      );
      await loadProposals();
      setSelectedProposal(proposal);
      setSelectedItemIds([]);
      setIntelligenceOpen(true);
      onStatus("候选情报已生成，等待逐条确认");
    } catch (reason) {
      const message = errorMessage(reason, "提取章节情报失败");
      setWorkflowError(message);
      onError(message);
      onStatus("情报提取失败，故事账本未变化");
    } finally {
      setBusyAction("");
    }
  };

  const selectProposal = (proposal: IntelligenceProposalRecord) => {
    setSelectedProposal(proposal);
    setSelectedItemIds([]);
  };

  const toggleItem = (itemId: string, checked: boolean) => {
    setSelectedItemIds((current: string[]) =>
      checked ? Array.from(new Set([...current, itemId])) : current.filter((id) => id !== itemId),
    );
  };

  const rejectIntelligenceItem = async (itemId: string) => {
    setBusyAction(`item-reject:${itemId}`);
    try {
      const updated = await apiRequest<IntelligenceProposalRecord>(
        `/intelligence-items/${itemId}`,
        { method: "PATCH", body: JSON.stringify({ review_state: "rejected" }) },
      );
      setSelectedProposal(updated);
      setSelectedItemIds((current: string[]) => current.filter((id) => id !== itemId));
      await loadProposals();
    } catch (reason) {
      onError(errorMessage(reason, "拒绝情报项失败"));
    } finally {
      setBusyAction("");
    }
  };

  const commitSelectedItems = async () => {
    if (!selectedProposal || selectedItemIds.length === 0) return;
    setBusyAction("intelligence-commit");
    try {
      const updated = await apiRequest<IntelligenceProposalRecord>(
        `/intelligence-proposals/${selectedProposal.id}/commit`,
        {
          method: "POST",
          body: JSON.stringify({ accepted_item_ids: selectedItemIds, item_overrides: {} }),
        },
      );
      setSelectedProposal(updated);
      setSelectedItemIds([]);
      await loadProposals();
      onStatus("所选情报已写入故事账本");
    } catch (reason) {
      onError(errorMessage(reason, "采用情报失败"));
    } finally {
      setBusyAction("");
    }
  };

  const openLedger = async () => {
    setBusyAction("ledger-load");
    try {
      setFacts(await apiRequest<StoryFactRecord[]>(`/novels/${novel.id}/story-facts`));
      setLedgerOpen(true);
    } catch (reason) {
      onError(errorMessage(reason, "加载故事账本失败"));
    } finally {
      setBusyAction("");
    }
  };

  const selectedProposalItems = selectedProposal?.items ?? [];

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      Space,
      { size: 8, wrap: true, className: "anw-workflow-panel" },
      React.createElement(
        Button,
        { icon: React.createElement(FileTextOutlined), onClick: openBrief, loading: busyAction === "brief-load" },
        "修改章纲",
      ),
      React.createElement(
        Button,
        { className: "anw-generate-button", icon: React.createElement(BookOutlined), onClick: generateCandidate, loading: busyAction === "generate" },
        "生成正文",
      ),
      React.createElement(
        Button,
        { icon: React.createElement(HistoryOutlined), onClick: openJobs, loading: busyAction === "jobs-load" },
        "候选",
      ),
      React.createElement(
        Button,
        { className: "anw-intel-button", icon: React.createElement(BulbOutlined), onClick: openIntelligence, loading: busyAction === "intelligence-load" },
        "情报",
      ),
      React.createElement(
        Button,
        { icon: React.createElement(DatabaseOutlined), onClick: openLedger, loading: busyAction === "ledger-load" },
        "故事账本",
      ),
    ),
    React.createElement(
      Modal,
      {
        open: briefOpen,
        className: "anw-modal",
        title: `章节任务书 · ${document.title}`,
        width: 760,
        style: { top: 24 },
        styles: { body: { maxHeight: "calc(100vh - 190px)", overflowY: "auto" } },
        onCancel: () => setBriefOpen(false),
        footer: [
          React.createElement(Button, { key: "cancel", onClick: () => setBriefOpen(false) }, "取消"),
          React.createElement(
            Button,
            { key: "save", type: "primary", loading: busyAction === "brief-save", onClick: saveBrief },
            "保存任务书",
          ),
        ],
      },
      React.createElement(
        Space,
        { direction: "vertical", size: 14, style: { width: "100%" } },
        React.createElement(Alert, {
          type: "info",
          showIcon: true,
          message: "任务书是生成控制面；修改后只影响新的候选，不会改正文。",
        }),
        field(
          "目标字数",
          React.createElement(InputNumber, {
            min: 200,
            max: 20000,
            step: 100,
            "aria-label": "目标字数",
            value: briefForm.targetWordCount,
            onChange: (value: number | null) => setBriefForm((current: BriefFormState) => ({
              ...current,
              targetWordCount: value ?? 2000,
            })),
            style: { width: 180 },
          }),
        ),
        field(
          "本章期望",
          React.createElement(TextArea, {
            rows: 3,
            "aria-label": "本章期望",
            value: briefForm.expectationText,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({
              ...current,
              expectationText: event.target.value,
            })),
            placeholder: "本章要推进什么、读者应该获得什么感受",
          }),
        ),
        field(
          "章节大纲",
          React.createElement(TextArea, {
            rows: 7,
            "aria-label": "章节大纲",
            value: briefForm.outlineText,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({
              ...current,
              outlineText: event.target.value,
            })),
            placeholder: "按场景或节拍填写；可以完全手写",
          }),
        ),
        field(
          "内容禁区",
          React.createElement(TextArea, {
            rows: 2,
            "aria-label": "内容禁区",
            value: briefForm.forbiddenText,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({
              ...current,
              forbiddenText: event.target.value,
            })),
            placeholder: "不能提前揭示的真相、不能新增的规则等",
          }),
        ),
        React.createElement(Divider, { style: { marginBlock: 2 } }, "角色约束（逗号、顿号或换行分隔）"),
        field(
          "必须出场 required",
          React.createElement(Input, {
            "aria-label": "必须出场角色",
            value: briefForm.requiredRoles,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({ ...current, requiredRoles: event.target.value })),
          }),
        ),
        field(
          "允许出场 allowed",
          React.createElement(Input, {
            "aria-label": "允许出场角色",
            value: briefForm.allowedRoles,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({ ...current, allowedRoles: event.target.value })),
          }),
        ),
        field(
          "仅上下文 context-only",
          React.createElement(Input, {
            "aria-label": "仅上下文角色",
            value: briefForm.contextOnlyRoles,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({ ...current, contextOnlyRoles: event.target.value })),
          }),
        ),
        field(
          "禁止出现 forbidden",
          React.createElement(Input, {
            "aria-label": "禁止出现角色",
            value: briefForm.forbiddenRoles,
            onChange: (event: any) => setBriefForm((current: BriefFormState) => ({ ...current, forbiddenRoles: event.target.value })),
          }),
        ),
      ),
    ),
    React.createElement(
      Modal,
      {
        open: jobsOpen,
        className: "anw-modal",
        title: "AI 候选历史与 Diff",
        width: 1120,
        style: { top: 24 },
        styles: { body: { maxHeight: "calc(100vh - 150px)", overflowY: "auto" } },
        footer: null,
        onCancel: () => setJobsOpen(false),
      },
      jobs.length === 0
        ? React.createElement(Empty, { description: "还没有候选任务" })
        : React.createElement(
            "div",
            { style: { display: "grid", gridTemplateColumns: "260px minmax(0, 1fr)", gap: 16, minHeight: 520 } },
            React.createElement(
              "div",
              { style: { maxHeight: 560, overflow: "auto" } },
              ...jobs.map((job: GenerationJobRecord) =>
                React.createElement(
                  Card,
                  {
                    key: job.id,
                    size: "small",
                    hoverable: Boolean(job.candidate),
                    onClick: () => job.candidate && setSelectedCandidate(job.candidate),
                    style: {
                      marginBottom: 8,
                      borderColor: selectedCandidate?.generation_job_id === job.id ? "var(--ant-color-primary)" : undefined,
                    },
                  },
                  React.createElement(
                    Space,
                    { direction: "vertical", size: 4 },
                    React.createElement(
                      Tag,
                      { color: stateColor(job.candidate?.state ?? job.state) },
                      stateLabel(job.candidate?.state ?? job.state),
                    ),
                    job.candidate
                      ? React.createElement(Typography.Text, null, `${job.candidate.visible_character_count} 字`)
                      : null,
                    job.failure_message
                      ? React.createElement(Typography.Text, { type: "danger", ellipsis: true }, job.failure_message)
                      : null,
                  ),
                ),
              ),
            ),
            selectedCandidate
              ? React.createElement(
                  "section",
                  { style: { minWidth: 0 } },
                  React.createElement(
                    Space,
                    { style: { width: "100%", justifyContent: "space-between", marginBottom: 10 }, wrap: true },
                    React.createElement(
                      Space,
                      null,
                      React.createElement(Tag, { color: stateColor(selectedCandidate.state) }, stateLabel(selectedCandidate.state)),
                      React.createElement(Typography.Text, null, `${selectedCandidate.visible_character_count} 字`),
                    ),
                    selectedCandidate.state === "ready"
                      ? React.createElement(
                          Space,
                          null,
                          React.createElement(
                            Button,
                            { danger: true, loading: busyAction === `reject:${selectedCandidate.id}`, onClick: () => reject(selectedCandidate) },
                            "拒绝",
                          ),
                          React.createElement(
                            Button,
                            { type: "primary", loading: busyAction === `adopt:${selectedCandidate.id}`, onClick: () => adopt(selectedCandidate) },
                            "采用整稿并建立版本",
                          ),
                        )
                      : null,
                  ),
                  React.createElement(Alert, {
                    type: "warning",
                    showIcon: true,
                    message: "采用前只预览 Diff；若正文基线已经变化，服务端会拒绝覆盖。",
                    style: { marginBottom: 10 },
                  }),
                  React.createElement(
                    "pre",
                    {
                      style: {
                        maxHeight: 470,
                        overflow: "auto",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        padding: 14,
                        borderRadius: 8,
                        background: "var(--ant-color-fill-quaternary, rgba(255,255,255,.04))",
                        font: "13px/1.65 ui-monospace, SFMono-Regular, Menlo, monospace",
                      },
                    },
                    selectedCandidate.unified_diff || "候选与生成基线没有文本差异。",
                  ),
                )
              : React.createElement(Empty, { description: "选择一份候选查看 Diff" }),
          ),
    ),
    React.createElement(
      Modal,
      {
        open: intelligenceOpen,
        className: "anw-modal",
        title: "章节情报提案",
        width: 1080,
        style: { top: 24 },
        styles: { body: { maxHeight: "calc(100vh - 190px)", overflowY: "auto" } },
        footer: [
          React.createElement(
            Button,
            { key: "extract", loading: busyAction === "intelligence-extract", onClick: extractIntelligence },
            "提取当前正式版本",
          ),
          React.createElement(
            Button,
            {
              key: "commit",
              type: "primary",
              disabled: !selectedProposal?.source_current || selectedItemIds.length === 0,
              loading: busyAction === "intelligence-commit",
              onClick: commitSelectedItems,
            },
            `采用所选（${selectedItemIds.length}）`,
          ),
        ],
        onCancel: () => setIntelligenceOpen(false),
      },
      React.createElement(
        Spin,
        { spinning: busyAction === "intelligence-extract" },
        workflowError
          ? React.createElement(Alert, {
              type: "error",
              showIcon: true,
              closable: true,
              message: workflowError,
              onClose: () => setWorkflowError(""),
              style: { marginBottom: 12 },
            })
          : null,
        proposals.length === 0
          ? React.createElement(Empty, { description: "还没有情报提案；先为当前正式版本提取" })
          : React.createElement(
              "div",
              { style: { display: "grid", gridTemplateColumns: "230px minmax(0, 1fr)", gap: 16, minHeight: 460 } },
              React.createElement(
                "div",
                null,
                ...proposals.map((proposal: IntelligenceProposalRecord) =>
                  React.createElement(
                    Button,
                    {
                      key: proposal.id,
                      block: true,
                      type: selectedProposal?.id === proposal.id ? "primary" : "text",
                      onClick: () => selectProposal(proposal),
                      style: { height: "auto", minHeight: 44, marginBottom: 6, textAlign: "left" },
                    },
                    `${stateLabel(proposal.state)} · ${proposal.items.length} 项`,
                  ),
                ),
              ),
              React.createElement(
                "section",
                { style: { minWidth: 0, maxHeight: 520, overflow: "auto" } },
                React.createElement(Alert, {
                  type: "info",
                  showIcon: true,
                  message: "候选默认不选中；请逐条确认后再写入故事账本。",
                  style: { marginBottom: 10 },
                }),
                selectedProposal && !selectedProposal.source_current
                  ? React.createElement(Alert, {
                      type: "error",
                      showIcon: true,
                      message: "这份提案基于旧正文，只能审计，不能采用。请重新建立检查点并提取。",
                      style: { marginBottom: 10 },
                    })
                  : null,
                selectedProposalItems.length === 0
                  ? React.createElement(Empty, { description: "模型没有提出可复核情报" })
                  : React.createElement(List, {
                      dataSource: selectedProposalItems,
                      renderItem: (item: any) => React.createElement(
                        List.Item,
                        { key: item.id },
                        React.createElement(
                          Card,
                          { size: "small", style: { width: "100%" } },
                          React.createElement(
                            Space,
                            { align: "start", style: { width: "100%" } },
                            React.createElement(Checkbox, {
                              checked: item.review_state === "accepted" || selectedItemIds.includes(item.id),
                              disabled: item.review_state !== "pending" || !selectedProposal?.source_current,
                              "aria-label": `选择情报：${item.suggested_payload.subject}，${item.suggested_payload.predicate}，${item.suggested_payload.object}`,
                              onChange: (event: any) => toggleItem(item.id, event.target.checked),
                            }),
                            React.createElement(
                              "div",
                              { style: { flex: 1, minWidth: 0 } },
                              React.createElement(
                                Space,
                                { wrap: true },
                                React.createElement(Tag, null, factTypeLabel(item.item_type)),
                                React.createElement(Tag, { color: stateColor(item.review_state) }, stateLabel(item.review_state)),
                                React.createElement(Typography.Text, { type: "secondary" }, `置信度 ${item.confidence}`),
                              ),
                              React.createElement(
                                Typography.Paragraph,
                                { style: { marginBlock: 8 } },
                                `${item.suggested_payload.subject} · ${item.suggested_payload.predicate} · ${item.suggested_payload.object}`,
                              ),
                              React.createElement(Typography.Text, { type: "secondary" }, `证据：${item.source_text}`),
                              item.reasoning_summary
                                ? React.createElement(Typography.Paragraph, { type: "secondary", style: { marginTop: 6, marginBottom: 0 } }, item.reasoning_summary)
                                : null,
                            ),
                            item.review_state === "pending"
                              ? React.createElement(
                                  Button,
                                  { size: "small", danger: true, loading: busyAction === `item-reject:${item.id}`, onClick: () => rejectIntelligenceItem(item.id) },
                                  "拒绝",
                                )
                              : null,
                          ),
                        ),
                      ),
                    }),
              ),
            ),
      ),
    ),
    React.createElement(
      Modal,
      {
        open: ledgerOpen,
        className: "anw-modal",
        title: `故事账本 · ${novel.title}`,
        width: 880,
        style: { top: 24 },
        styles: { body: { maxHeight: "calc(100vh - 150px)", overflowY: "auto" } },
        footer: null,
        onCancel: () => setLedgerOpen(false),
      },
      facts.length === 0
        ? React.createElement(Empty, { description: "故事账本还是空的" })
        : React.createElement(List, {
            dataSource: facts,
            renderItem: (fact: StoryFactRecord) => React.createElement(
              List.Item,
              { key: fact.id },
              React.createElement(List.Item.Meta, {
                title: React.createElement(
                  Space,
                  { wrap: true },
                  React.createElement(Tag, null, factTypeLabel(fact.fact_type)),
                  React.createElement(
                    Tag,
                    { color: fact.status === "active" || fact.status === "source_restored" ? "success" : "warning" },
                    factStatusLabel(fact.status),
                  ),
                  React.createElement(Typography.Text, { strong: true }, `${fact.subject} · ${fact.predicate}`),
                ),
                description: fact.object_text,
              }),
            ),
          }),
    ),
  );
}
