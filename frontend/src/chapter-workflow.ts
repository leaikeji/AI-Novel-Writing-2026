import {
  apiErrorMessage,
  apiRequest,
  completedGenerationModelLabel,
  generationModelLabel,
  generationModelAuditLabel,
  getGenerationModelStatus,
  isRetryableChapterLengthFailure,
  verifiedGenerationModelLabel,
} from "./api";
import {
  CandidateRecord,
  ChapterBriefRecord,
  CreativeGenerationRecord,
  DocumentRecord,
  GenerationJobRecord,
  GenerationModelStatus,
  IntelligenceItemRecord,
  IntelligenceProposalRecord,
  NovelRecord,
  PrivateAssetRecord,
  PrivateAssetType,
  RoleConstraints,
} from "./types";
import { restoreDialogTriggerFocus } from "./assistant-focus";
import {
  createAssistantBodyFieldAdapter,
  type AssistantBodyFieldAdapter,
} from "./assistant-body-field";
import {
  assistantContextRuntime,
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantContextScopeHandle,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import {
  NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
  type NovelPageView,
} from "./assistant-context-schema";
import {
  createAssistantFormFieldAdapter,
  type AssistantFormFieldAdapter,
} from "./assistant-form-field";
import type {
  AIApplyMeta,
  EditableFieldRegistration,
  SelectionRange,
  SelectionSnapshot,
} from "./assistant-fields";
import type { SelectionEditReviewHostComponent } from "./selection-edit-runtime";
const host = window.QwenPaw.host;
const React = host.React;
const ReactDOM = host.ReactDOM;
const h = React.createElement;
const {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  Modal,
  Spin,
  Tag,
  Tabs,
} = host.antd;
const {
  AuditOutlined,
  BookOutlined,
  BulbOutlined,
  EditOutlined,
  HistoryOutlined,
  PlusOutlined,
  SearchOutlined,
  SyncOutlined,
} = host.antdIcons;
const TextArea = Input.TextArea;


interface ChapterWorkflowProps {
  novel: NovelRecord;
  document: DocumentRecord;
  onPrepareGeneration?: () => Promise<DocumentRecord | null>;
  onDocumentChanged: (document: DocumentRecord, status: string) => void;
  onError: (message: string) => void;
  onStatus: (message: string) => void;
  chapterNumber?: number;
  titleToolsTargetId?: string;
  generateActionRef?: { current: (() => void) | null };
  onBodyGenerationStateChange?: (active: boolean, stage: string) => void;
  onAssistantModalStateChange?: (open: boolean) => void;
  selectionEditReviewHost?: SelectionEditReviewHostComponent;
}


export interface BriefFormState {
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
  targetWordCount: 2500,
  expectationText: "",
  outlineText: "",
  forbiddenText: "",
  requiredRoles: "",
  allowedRoles: "",
  contextOnlyRoles: "",
  forbiddenRoles: "",
};


export const CHAPTER_BODY_FIELD_ID = "chapter.body";
export const CHAPTER_TITLE_FIELD_ID = "chapter.title";
export const CHAPTER_OUTLINE_FIELD_IDS = {
  outlineText: "chapter.outline",
  targetCharacters: "chapter.outline.targetCharacters",
  expectation: "chapter.outline.expectation",
  forbidden: "chapter.outline.forbidden",
  requiredRoles: "chapter.outline.roles.required",
  allowedRoles: "chapter.outline.roles.allowed",
  contextOnlyRoles: "chapter.outline.roles.contextOnly",
  forbiddenRoles: "chapter.outline.roles.forbidden",
} as const;


export type ChapterOutlineFieldId = typeof CHAPTER_OUTLINE_FIELD_IDS[keyof typeof CHAPTER_OUTLINE_FIELD_IDS];


export interface AssistantTextControl {
  selectionStart: number | null;
  selectionEnd: number | null;
  selectionDirection: string | null;
  focus(): void;
  setSelectionRange(start: number, end: number, direction?: "forward" | "backward" | "none"): void;
}


export interface ChapterAssistantLocation {
  novel: Pick<NovelRecord, "id" | "title">;
  document: Pick<DocumentRecord, "id" | "volume_id" | "kind" | "title" | "version" | "draft_version" | "content_hash">;
  chapterNumber?: number;
  dirty: boolean;
}


type AssistantRuntimeMount = Pick<NovelAssistantContextRuntime, "mountScope">;


export interface ChapterBodyAssistantBindingOptions {
  runtime?: AssistantRuntimeMount;
  location: ChapterAssistantLocation;
  getValue: () => string;
  getDirty: () => boolean;
  getSelection: () => SelectionSnapshot | null;
  applyEditorContent: (nextValue: string, meta: Readonly<AIApplyMeta>) => void | Promise<void>;
  scheduleAutosave: (nextValue: string, meta: Readonly<AIApplyMeta>) => void | Promise<void>;
  restoreSelection: (range: SelectionRange) => void;
  focus: () => void;
}


export interface ChapterFormAssistantBindingOptions {
  runtime?: AssistantRuntimeMount;
  location: ChapterAssistantLocation;
  getSelection: (fieldId: string) => SelectionSnapshot | null;
  restoreSelection: (fieldId: string, range: SelectionRange) => void;
  focus: (fieldId: string) => void;
  markDirty: (fieldId: string, meta: Readonly<AIApplyMeta>) => void | Promise<void>;
}


export interface ChapterBodyAssistantBinding {
  readonly scope: AssistantContextScopeHandle;
  readonly adapter: AssistantBodyFieldAdapter;
  setFocusedField(focused: boolean): void;
  notifyFieldChanged(): void;
  dispose(): void;
}


export interface ChapterFormAssistantBinding<TAdapters> {
  readonly scope: AssistantContextScopeHandle;
  readonly adapters: TAdapters;
  setFocusedField(fieldId: string | undefined): void;
  notifyFieldChanged(fieldId: string): void;
  dispose(): void;
}


export interface ChapterTitleAssistantBindingOptions extends ChapterFormAssistantBindingOptions {
  getValue: () => string;
  getDirty: () => boolean;
  applyDraftValue: (nextValue: string, meta: Readonly<AIApplyMeta>) => void | Promise<void>;
}


export interface ChapterOutlineAssistantBindingOptions extends ChapterFormAssistantBindingOptions {
  getPersistenceVersion: () => number;
  getForm: () => BriefFormState;
  getBaseline: () => BriefFormState;
  applyField: <K extends keyof BriefFormState>(
    field: K,
    value: BriefFormState[K],
    meta: Readonly<AIApplyMeta>,
  ) => void | Promise<void>;
}


export type ChapterOutlineAssistantAdapters = Record<ChapterOutlineFieldId, AssistantFormFieldAdapter>;


export async function hashAssistantFieldValue(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is required for assistant field adapters");
  }
  const bytes = new TextEncoder().encode(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


export function readAssistantTextSelection(
  control: AssistantTextControl | null,
  value: string,
): SelectionSnapshot | null {
  if (!control) return null;
  const start = Math.max(0, Math.min(value.length, control.selectionStart ?? 0));
  const end = Math.max(start, Math.min(value.length, control.selectionEnd ?? start));
  if (start === end) return null;
  const rawDirection = control.selectionDirection;
  const direction = rawDirection === "forward" || rawDirection === "backward"
    ? rawDirection
    : "none";
  return {
    startUtf16: start,
    endUtf16: end,
    direction,
    text: value.slice(start, end),
    before: value.slice(
      Math.max(0, start - NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS),
      start,
    ),
    after: value.slice(
      end,
      end + NOVEL_ASSISTANT_SELECTION_CONTEXT_CHARACTERS,
    ),
  };
}


export function restoreAssistantTextSelection(
  control: AssistantTextControl | null,
  range: SelectionRange,
): void {
  if (!control) return;
  control.focus();
  control.setSelectionRange(range.startUtf16, range.endUtf16, range.direction);
}


function chapterAssistantEnvelope(
  location: ChapterAssistantLocation,
  modal?: Extract<NovelPageView, "title-editor" | "chapter-outline-editor">,
) {
  return {
    agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
    novel: { id: location.novel.id, title: location.novel.title },
    page: {
      section: "chapters" as const,
      view: "chapter-editor" as const,
      ...(modal ? { modal } : {}),
    },
    entity: {
      type: "document" as const,
      id: location.document.id,
      title: location.document.title,
    },
    document: {
      id: location.document.id,
      ...(location.document.volume_id ? { volumeId: location.document.volume_id } : {}),
      kind: location.document.kind,
      ...(location.chapterNumber === undefined ? {} : { chapterNumber: location.chapterNumber }),
      title: location.document.title,
      draftVersion: location.document.draft_version,
      savedContentHash: location.document.content_hash,
      dirty: location.dirty,
    },
  };
}


function disposeAssistantScope(
  scope: AssistantContextScopeHandle,
  registrations: EditableFieldRegistration[],
): () => void {
  let active = true;
  return () => {
    if (!active) return;
    active = false;
    for (const registration of [...registrations].reverse()) registration.dispose();
    scope.dispose();
  };
}


export function mountChapterBodyAssistantScope(
  options: ChapterBodyAssistantBindingOptions,
): ChapterBodyAssistantBinding {
  const runtime = options.runtime ?? assistantContextRuntime;
  const scope = runtime.mountScope({
    id: `page:chapter:${options.location.document.id}`,
    kind: "page",
    envelope: chapterAssistantEnvelope(options.location),
    persistenceBaseline: () => ({
      kind: "draft",
      version: options.location.document.draft_version,
    }),
  });
  const adapter = createAssistantBodyFieldAdapter({
    id: CHAPTER_BODY_FIELD_ID,
    label: "正文",
    getValue: options.getValue,
    getDirty: options.getDirty,
    getSelection: options.getSelection,
    hashValue: hashAssistantFieldValue,
    applyEditorContent: async (nextValue, meta) => {
      await options.applyEditorContent(nextValue, meta);
      scope.notifyFieldChanged(CHAPTER_BODY_FIELD_ID);
    },
    scheduleAutosave: options.scheduleAutosave,
    restoreSelection: options.restoreSelection,
    focus: options.focus,
  });
  const registrations = [scope.registerField(adapter)];
  const dispose = disposeAssistantScope(scope, registrations);
  return {
    scope,
    adapter,
    setFocusedField: (focused) => scope.setFocusedField(focused ? CHAPTER_BODY_FIELD_ID : undefined),
    notifyFieldChanged: () => scope.notifyFieldChanged(CHAPTER_BODY_FIELD_ID),
    dispose,
  };
}


export function mountChapterTitleAssistantScope(
  options: ChapterTitleAssistantBindingOptions,
): ChapterFormAssistantBinding<AssistantFormFieldAdapter> {
  const runtime = options.runtime ?? assistantContextRuntime;
  const scope = runtime.mountScope({
    id: `modal:chapter-title:${options.location.document.id}`,
    kind: "modal",
    envelope: chapterAssistantEnvelope(options.location, "title-editor"),
    persistenceBaseline: () => ({
      kind: "entity",
      version: options.location.document.version,
    }),
  });
  const adapter = createAssistantFormFieldAdapter({
    id: CHAPTER_TITLE_FIELD_ID,
    label: "章节标题",
    getValue: options.getValue,
    getDirty: options.getDirty,
    getSelection: () => options.getSelection(CHAPTER_TITLE_FIELD_ID),
    hashValue: hashAssistantFieldValue,
    applyDraftValue: async (nextValue, meta) => {
      await options.applyDraftValue(nextValue, meta);
      scope.notifyFieldChanged(CHAPTER_TITLE_FIELD_ID);
    },
    markDirty: (meta) => options.markDirty(CHAPTER_TITLE_FIELD_ID, meta),
    restoreSelection: (range) => options.restoreSelection(CHAPTER_TITLE_FIELD_ID, range),
    focus: () => options.focus(CHAPTER_TITLE_FIELD_ID),
  });
  const registrations = [scope.registerField(adapter)];
  const dispose = disposeAssistantScope(scope, registrations);
  return {
    scope,
    adapters: adapter,
    setFocusedField: (fieldId) => scope.setFocusedField(fieldId),
    notifyFieldChanged: (fieldId) => scope.notifyFieldChanged(fieldId),
    dispose,
  };
}


interface OutlineFieldSpec<K extends keyof BriefFormState = keyof BriefFormState> {
  id: ChapterOutlineFieldId;
  label: string;
  key: K;
  serialize: (value: BriefFormState[K]) => string;
  parse: (value: string) => BriefFormState[K];
}


const OUTLINE_FIELD_SPECS: OutlineFieldSpec[] = [
  { id: CHAPTER_OUTLINE_FIELD_IDS.outlineText, label: "章节大纲", key: "outlineText", serialize: String, parse: String },
  {
    id: CHAPTER_OUTLINE_FIELD_IDS.targetCharacters,
    label: "目标字数",
    key: "targetWordCount",
    serialize: String,
    parse: (value) => {
      if (!/^(0|[1-9]\d*)$/.test(value)) throw new Error("目标字数必须是非负整数");
      const parsed = Number(value);
      if (!Number.isSafeInteger(parsed)) throw new Error("目标字数超出安全整数范围");
      return parsed;
    },
  },
  { id: CHAPTER_OUTLINE_FIELD_IDS.expectation, label: "本章期待", key: "expectationText", serialize: String, parse: String },
  { id: CHAPTER_OUTLINE_FIELD_IDS.forbidden, label: "禁止事项", key: "forbiddenText", serialize: String, parse: String },
  { id: CHAPTER_OUTLINE_FIELD_IDS.requiredRoles, label: "必须出场角色", key: "requiredRoles", serialize: String, parse: String },
  { id: CHAPTER_OUTLINE_FIELD_IDS.allowedRoles, label: "允许出场角色", key: "allowedRoles", serialize: String, parse: String },
  { id: CHAPTER_OUTLINE_FIELD_IDS.contextOnlyRoles, label: "仅上下文角色", key: "contextOnlyRoles", serialize: String, parse: String },
  { id: CHAPTER_OUTLINE_FIELD_IDS.forbiddenRoles, label: "禁止出场角色", key: "forbiddenRoles", serialize: String, parse: String },
];


function assistantBriefFormIsDirty(
  form: BriefFormState,
  baseline: BriefFormState,
): boolean {
  return OUTLINE_FIELD_SPECS.some((spec) => (
    spec.serialize(form[spec.key]) !== spec.serialize(baseline[spec.key])
  ));
}


export function mountChapterOutlineAssistantScope(
  options: ChapterOutlineAssistantBindingOptions,
): ChapterFormAssistantBinding<ChapterOutlineAssistantAdapters> {
  const runtime = options.runtime ?? assistantContextRuntime;
  const scope = runtime.mountScope({
    id: `modal:chapter-outline:${options.location.document.id}`,
    kind: "modal",
    envelope: chapterAssistantEnvelope(options.location, "chapter-outline-editor"),
    persistenceBaseline: () => ({
      kind: "entity",
      version: options.getPersistenceVersion(),
    }),
  });
  const adapters = {} as ChapterOutlineAssistantAdapters;
  const registrations: EditableFieldRegistration[] = [];
  for (const spec of OUTLINE_FIELD_SPECS) {
    const adapter = createAssistantFormFieldAdapter({
      id: spec.id,
      label: spec.label,
      getValue: () => spec.serialize(options.getForm()[spec.key]),
      getDirty: () => spec.serialize(options.getForm()[spec.key])
        !== spec.serialize(options.getBaseline()[spec.key]),
      getSelection: () => options.getSelection(spec.id),
      hashValue: hashAssistantFieldValue,
      applyDraftValue: async (nextValue, meta) => {
        await options.applyField(spec.key, spec.parse(nextValue), meta);
        scope.notifyFieldChanged(spec.id);
      },
      markDirty: (meta) => options.markDirty(spec.id, meta),
      restoreSelection: (range) => options.restoreSelection(spec.id, range),
      focus: () => options.focus(spec.id),
    });
    adapters[spec.id] = adapter;
    registrations.push(scope.registerField(adapter));
  }
  const dispose = disposeAssistantScope(scope, registrations);
  return {
    scope,
    adapters,
    setFocusedField: (fieldId) => scope.setFocusedField(fieldId),
    notifyFieldChanged: (fieldId) => scope.notifyFieldChanged(fieldId),
    dispose,
  };
}


interface AssistantComponentControlRef {
  focus?: () => void;
  input?: AssistantTextControl | null;
  resizableTextArea?: { textArea?: AssistantTextControl | null } | null;
}


interface AssistantControlRefs {
  component: AssistantComponentControlRef | null;
  native: AssistantTextControl | null;
}


function assistantNativeControl(refs: AssistantControlRefs): AssistantTextControl | null {
  return refs.native
    ?? refs.component?.input
    ?? refs.component?.resizableTextArea?.textArea
    ?? null;
}


function focusAssistantControl(refs: AssistantControlRefs): void {
  if (refs.component?.focus) {
    refs.component.focus();
    return;
  }
  assistantNativeControl(refs)?.focus();
}


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
    targetWordCount: brief.target_word_count || 2500,
    expectationText: brief.expectation_text,
    outlineText: brief.outline_text,
    forbiddenText: brief.forbidden_text,
    requiredRoles: brief.role_constraints.required.join("、"),
    allowedRoles: brief.role_constraints.allowed.join("、"),
    contextOnlyRoles: brief.role_constraints.context_only.join("、"),
    forbiddenRoles: brief.role_constraints.forbidden.join("、"),
  };
}

function chapterLengthWindow(targetWordCount: number): { minimum: number; maximum: number; label: string } {
  const target = Math.max(1, Math.round(targetWordCount));
  const minimum = Math.floor(target * 0.85);
  const maximum = Math.ceil(target * 1.15);
  return { minimum, maximum, label: `${minimum}—${maximum} 字（目标 ${target} 字，±15%）` };
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
  return apiErrorMessage(reason, fallback);
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
    chapterNumber,
    titleToolsTargetId,
    generateActionRef,
    onBodyGenerationStateChange,
    onAssistantModalStateChange,
    selectionEditReviewHost: SelectionEditReviewHost,
  } = props;
  const [brief, setBrief] = React.useState(null as ChapterBriefRecord | null);
  const [briefForm, setBriefForm] = React.useState(EMPTY_BRIEF_FORM);
  const [briefOpen, setBriefOpen] = React.useState(false);
  const briefTriggerRef = React.useRef(null as HTMLButtonElement | null);
  const briefFormRef = React.useRef({ ...EMPTY_BRIEF_FORM } as BriefFormState);
  const briefBaselineRef = React.useRef({ ...EMPTY_BRIEF_FORM } as BriefFormState);
  const assistantBriefBindingRef = React.useRef(
    null as ChapterFormAssistantBinding<ChapterOutlineAssistantAdapters> | null,
  );
  const assistantBriefControlRefs = React.useRef(
    {} as Record<ChapterOutlineFieldId, AssistantControlRefs>,
  );
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
  const [titleToolsTarget, setTitleToolsTarget] = React.useState(null as HTMLElement | null);
  const [reviewJob, setReviewJob] = React.useState(null as CreativeGenerationRecord | null);
  const [activeGenerationModel, setActiveGenerationModel] = React.useState(null as GenerationModelStatus | null);
  const [busyAction, setBusyAction] = React.useState("");

  const loadGenerationModel = async (): Promise<GenerationModelStatus> => {
    const current = await getGenerationModelStatus();
    setActiveGenerationModel(current);
    return current;
  };

  React.useEffect(() => {
    const emptyForm = { ...EMPTY_BRIEF_FORM };
    briefFormRef.current = emptyForm;
    briefBaselineRef.current = { ...emptyForm };
    assistantBriefControlRefs.current = {} as Record<ChapterOutlineFieldId, AssistantControlRefs>;
    setBrief(null);
    setBriefForm(emptyForm);
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

  React.useEffect(() => {
    onAssistantModalStateChange?.(briefOpen);
    return () => {
      if (briefOpen) onAssistantModalStateChange?.(false);
    };
  }, [briefOpen, document.id, onAssistantModalStateChange]);

  React.useEffect(() => {
    if (!titleToolsTargetId) {
      setTitleToolsTarget(null);
      return;
    }
    setTitleToolsTarget(window.document.getElementById(titleToolsTargetId));
  }, [titleToolsTargetId, document.id]);

  const loadBrief = async (): Promise<ChapterBriefRecord> => {
    const loaded = await apiRequest<ChapterBriefRecord>(`/documents/${document.id}/chapter-brief`);
    const loadedForm = briefToForm(loaded);
    setBrief(loaded);
    briefFormRef.current = loadedForm;
    briefBaselineRef.current = { ...loadedForm };
    setBriefForm(loadedForm);
    return loaded;
  };

  React.useEffect(() => {
    if (!briefOpen) return;
    const binding = mountChapterOutlineAssistantScope({
      location: {
        novel,
        document,
        chapterNumber,
        dirty: assistantBriefFormIsDirty(briefFormRef.current, briefBaselineRef.current),
      },
      getPersistenceVersion: () => {
        if (!brief || brief.version < 1) {
          throw new Error("章纲尚未建立可比较的保存版本");
        }
        return brief.version;
      },
      getForm: () => briefFormRef.current,
      getBaseline: () => briefBaselineRef.current,
      getSelection: (fieldId) => {
        const refs = assistantBriefControlRefs.current[fieldId as ChapterOutlineFieldId];
        const field = OUTLINE_FIELD_SPECS.find((item) => item.id === fieldId);
        if (!refs || !field) return null;
        return readAssistantTextSelection(
          assistantNativeControl(refs),
          field.serialize(briefFormRef.current[field.key]),
        );
      },
      applyField: (field, value) => {
        const next = { ...briefFormRef.current, [field]: value };
        briefFormRef.current = next;
        setBriefForm(next);
      },
      restoreSelection: (fieldId, range) => {
        const refs = assistantBriefControlRefs.current[fieldId as ChapterOutlineFieldId];
        if (!refs) return;
        restoreAssistantTextSelection(assistantNativeControl(refs), range);
      },
      focus: (fieldId) => {
        const refs = assistantBriefControlRefs.current[fieldId as ChapterOutlineFieldId];
        if (refs) focusAssistantControl(refs);
      },
      markDirty: () => onStatus("已应用到章纲草稿，尚未保存"),
    });
    assistantBriefBindingRef.current = binding;
    return () => {
      if (assistantBriefBindingRef.current === binding) {
        assistantBriefBindingRef.current = null;
      }
      binding.dispose();
    };
  }, [brief?.version, briefOpen, chapterNumber, document.id, novel.id, onStatus]);

  const getAssistantBriefControl = (fieldId: ChapterOutlineFieldId): AssistantControlRefs => {
    const current = assistantBriefControlRefs.current[fieldId];
    if (current) return current;
    const created: AssistantControlRefs = { component: null, native: null };
    assistantBriefControlRefs.current[fieldId] = created;
    return created;
  };

  const assistantBriefControlProps = (fieldId: ChapterOutlineFieldId) => {
    const refs = getAssistantBriefControl(fieldId);
    return {
      ref: (node: AssistantComponentControlRef | null) => {
        refs.component = node;
        refs.native = node?.input ?? node?.resizableTextArea?.textArea ?? null;
      },
      onFocus: (event: { currentTarget: AssistantTextControl }) => {
        refs.native = event.currentTarget;
        assistantBriefBindingRef.current?.setFocusedField(fieldId);
      },
      onSelect: (event: { currentTarget: AssistantTextControl }) => {
        refs.native = event.currentTarget;
      },
      onBlur: () => assistantBriefBindingRef.current?.setFocusedField(undefined),
    };
  };

  const updateBriefField = <K extends keyof BriefFormState>(
    fieldId: ChapterOutlineFieldId,
    key: K,
    value: BriefFormState[K],
  ) => {
    const next = { ...briefFormRef.current, [key]: value };
    briefFormRef.current = next;
    setBriefForm(next);
    assistantBriefBindingRef.current?.notifyFieldChanged(fieldId);
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
        target_word_count: Math.min(10000, Math.max(500, form.targetWordCount)),
        expectation_text: form.expectationText,
        outline_text: form.outlineText,
        forbidden_text: form.forbiddenText,
        role_constraints: formRoleConstraints(form),
      }),
    },
  );

  const saveBrief = async () => {
    if (!briefForm.outlineText.trim()) {
      onError("请先填写章节大纲");
      return;
    }
    if (briefForm.targetWordCount < 500 || briefForm.targetWordCount > 10000) {
      onError("目标字数需在 500-10000 字之间");
      return;
    }
    setBusyAction("brief-save");
    try {
      const currentBrief = brief ?? await loadBrief();
      const saved = await persistBrief(currentBrief, briefForm);
      const savedForm = briefToForm(saved);
      setBrief(saved);
      briefFormRef.current = savedForm;
      briefBaselineRef.current = { ...savedForm };
      setBriefForm(savedForm);
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

  if (generateActionRef) generateActionRef.current = openGenerationOptions;

  const ensureBrief = async (): Promise<ChapterBriefRecord> => {
    const currentBrief = brief ?? await loadBrief();
    if (currentBrief.version > 0 && currentBrief.target_word_count >= 500) return currentBrief;
    const form = briefToForm(currentBrief);
    const saved = await persistBrief(currentBrief, { ...form, targetWordCount: Math.max(2500, form.targetWordCount) });
    const savedForm = briefToForm(saved);
    setBrief(saved);
    briefFormRef.current = savedForm;
    briefBaselineRef.current = { ...savedForm };
    setBriefForm(savedForm);
    return saved;
  };

  const generateBody = async (assetIds: string[] = selectedAssetIds) => {
    setAssetPickerOpen(false);
    const bodyStage = "正在分析角色关系、伏笔推进和章节情节";
    setGenerationStage(bodyStage);
    onBodyGenerationStateChange?.(true, bodyStage);
    setBusyAction("generate");
    try {
      const currentModel = await loadGenerationModel();
      const currentModelLabel = generationModelLabel(currentModel);
      if (onPrepareGeneration) {
        const prepared = await onPrepareGeneration();
        if (!prepared) throw new Error("当前正文保存失败，请稍后重试");
      }
      const currentBrief = await ensureBrief();
      const lengthWindow = chapterLengthWindow(currentBrief.target_word_count);
      let acceptedJob: GenerationJobRecord | null = null;
      let lastFailure: unknown = null;
      const maximumAttempts = 3;

      for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
        const attemptStage = attempt === 1
          ? "正在分析角色关系、伏笔推进和章节情节"
          : `第 ${attempt} 次整章重写：正在校准 ${lengthWindow.label}`;
        setGenerationStage(attemptStage);
        onBodyGenerationStateChange?.(true, attemptStage);
        onStatus(attempt === 1
          ? `${currentModelLabel} 正在创作章节正文…`
          : `第 ${attempt} 次整章重写中，上次正文未达 ${lengthWindow.label}…`);

        try {
          const job = await apiRequest<GenerationJobRecord>(
            `/documents/${document.id}/generation-jobs/body`,
            {
              method: "POST",
              body: JSON.stringify({
                expected_brief_version: currentBrief.version,
                force_new: true,
                asset_ids: assetIds,
              }),
            },
          );
          if (!job.candidate) throw new Error(job.failure_message || "模型没有返回正文");
          acceptedJob = job;
          break;
        } catch (reason) {
          lastFailure = reason;
          if (!isRetryableChapterLengthFailure(reason) || attempt === maximumAttempts) {
            throw reason;
          }
        }
      }

      if (!acceptedJob?.candidate) throw lastFailure || new Error("模型没有返回正文");
      setGenerationStage("正文已生成，正在写入编辑器");
      const result = await apiRequest<{ document: DocumentRecord; candidate: CandidateRecord }>(
        `/candidates/${acceptedJob.candidate.id}/adopt`,
        {
          method: "POST",
          body: JSON.stringify({ expected_draft_version: acceptedJob.candidate.base_draft_version }),
        },
      );
      setFeaturedCandidateId(result.candidate.id);
      setSelectedAssetIds([]);
      const completedModel = completedGenerationModelLabel(acceptedJob);
      onDocumentChanged(result.document, `${completedModel} 正文生成完成 · ${result.candidate.visible_character_count} 字`);
      setGeneratingOpen(false);
      await confirmSyncProgress(result.document);
    } catch (reason) {
      const message = errorMessage(reason, "生成正文失败");
      const lengthFailure = isRetryableChapterLengthFailure(reason);
      onError(message);
      const currentTarget = brief?.target_word_count ?? briefFormRef.current.targetWordCount;
      const currentWindow = chapterLengthWindow(currentTarget);
      onStatus(lengthFailure ? `本次未达 ${currentWindow.label}，必须整章重写` : "正文生成失败");
      Modal.error({
        className: "anw-modal anw-generation-failure",
        title: "章节正文生成失败",
        width: 560,
        centered: true,
        content: h("div", { className: "anw-generation-confirm-copy" },
          h("p", null, message),
          h("strong", null, "本次没有修改正式正文。"),
          h("p", null, lengthFailure
            ? `三次完整生成均未进入 ${currentWindow.label}；下次手动重试仍会携带最新字数差额。`
            : "请确认“AI小说作家”的当前模型可用后，再点击“生成正文”重新尝试。"),
        ),
        okText: "我知道了",
      });
    } finally {
      setGeneratingOpen(false);
      onBodyGenerationStateChange?.(false, "");
      setBusyAction("");
    }
  };

  const confirmGenerateBody = async (assetIds: string[]) => {
    setAssetPickerOpen(false);
    let currentModel: GenerationModelStatus;
    try {
      currentModel = await loadGenerationModel();
    } catch (reason) {
      onError(errorMessage(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal anw-generation-confirm",
      title: "确认",
      width: 520,
      centered: true,
      content: h("div", { className: "anw-generation-confirm-copy" },
        h("strong", null, "⚠️ 请确保当前模型连接可用，并避免重复发起生成"),
        h("p", null, "页面可以留在后台；若模型长时间无响应，系统会安全结束任务并显示失败原因。"),
        h("p", null, "生成开始后请勿重复发起；失败时系统会保留正式正文不变。"),
        h("p", null, "若完整正文未进入字数硬范围，系统最多自动整章重写两次（本次最多 3 次模型调用）。"),
        h("p", null, `本次将使用 ${generationModelLabel(currentModel)}。`),
        h("p", null, "若多次出现生成失败，请检查当前有效模型连接。"),
        h("b", null, "确定继续生成吗？"),
      ),
      okText: "确定",
      cancelText: "取消",
      onOk: () => { void generateBody(assetIds); },
    });
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

  async function runSyncProgress(preparedOverride?: DocumentRecord) {
    setBusyAction("sync");
    setGenerationStage("正在从本章正文提取角色、关系、故事线与伏笔进展");
    setGeneratingOpen(true);
    try {
      const currentModel = await loadGenerationModel();
      const prepared = preparedOverride ?? (onPrepareGeneration ? await onPrepareGeneration() : document);
      if (!prepared) throw new Error("当前正文保存失败，请稍后重试");
      const checkpoint = await apiRequest<{ document: DocumentRecord }>(`/documents/${prepared.id}/checkpoints`, {
        method: "POST",
        body: JSON.stringify({ expected_draft_version: prepared.draft_version }),
      });
      const source = checkpoint.document;
      if (!source.base_revision_id) throw new Error("本章正文尚未形成可同步版本");
      onDocumentChanged(source, `${generationModelLabel(currentModel)} 正在同步进展…`);
      let proposal = await apiRequest<IntelligenceProposalRecord>(
        `/documents/${source.id}/intelligence-proposals`,
        { method: "POST", body: JSON.stringify({ revision_id: source.base_revision_id }) },
      );
      const syncableIds = proposal.items
        .filter((item) => item.review_state === "pending" || item.review_state === "accepted")
        .map((item) => item.id);
      let relationshipChanges = { created: 0, updated: 0, skipped: 0 };
      if (syncableIds.length > 0) {
        const committed = await apiRequest<IntelligenceProposalRecord & {
          relationship_sync?: { created: number; updated: number; skipped: number };
        }>(`/intelligence-proposals/${proposal.id}/commit`, {
          method: "POST",
          body: JSON.stringify({ accepted_item_ids: syncableIds, item_overrides: {} }),
        });
        proposal = committed;
        relationshipChanges = committed.relationship_sync || relationshipChanges;
      }
      setSelectedProposal(proposal);
      setIntelligenceOpen(true);
      const relationshipTotal = relationshipChanges.created + relationshipChanges.updated;
      onStatus(
        `${completedGenerationModelLabel(proposal)} 同步进展完成 · ${proposal.items.length} 条本章情报 · ${relationshipTotal ? `关系网新增/更新 ${relationshipTotal} 条` : "关系网已同步"}`,
      );
    } catch (reason) {
      onError(errorMessage(reason, "同步进展失败"));
      onStatus("同步进展失败");
    } finally {
      setGeneratingOpen(false);
      setBusyAction("");
    }
  }

  const confirmSyncProgress = async (preparedOverride?: DocumentRecord) => {
    const source = preparedOverride ?? document;
    let currentModel: GenerationModelStatus;
    try {
      currentModel = await loadGenerationModel();
    } catch (reason) {
      onError(errorMessage(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal anw-sync-confirm",
      title: "确认",
      width: 520,
      content: h("div", { className: "anw-sync-copy" },
        h("p", null, `本次同步进展将分析 ${source.visible_character_count} 字正文。`),
        h("p", null, `本次将使用 ${generationModelLabel(currentModel)}。`),
        h("p", null, "AI 将根据当前章节内容提取情报信息（角色、伏笔、剧情线等），并更新到作品创作资料中。"),
        h("strong", null, "确认同步并继续吗？"),
      ),
      okText: "确定",
      cancelText: "取消",
      onOk: () => { void runSyncProgress(preparedOverride); },
    });
  };

  const runReview = async () => {
    setBusyAction("review");
    setGenerationStage("正在从文字流畅、描写生动、人物一致性等维度审阅正文");
    setGeneratingOpen(true);
    try {
      await loadGenerationModel();
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
          force_new: true,
        }),
      });
      if (job.state !== "ready") throw new Error(job.failure_message || "模型审稿失败");
      setReviewJob(job);
      setReviewOpen(true);
      onStatus(`${completedGenerationModelLabel(job)} AI 审稿完成`);
    } catch (reason) {
      onError(errorMessage(reason, "AI 审稿失败"));
    } finally {
      setGeneratingOpen(false);
      setBusyAction("");
    }
  };

  const confirmReview = async () => {
    let currentModel: GenerationModelStatus;
    try {
      currentModel = await loadGenerationModel();
    } catch (reason) {
      onError(errorMessage(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal anw-review-confirm",
      title: "确认",
      width: 520,
      content: `审稿将使用 ${generationModelLabel(currentModel)}，从文字流畅、描写生动、人物一致性、时空因果、伏笔与重复内容等维度分析正文并给出修改建议。是否开始审稿？`,
      okText: "确定",
      cancelText: "取消",
      onOk: () => { void runReview(); },
    });
  };

  const filteredAssets = assets.filter((item: PrivateAssetRecord) => item.asset_type === assetTab && (!assetSearch.trim() || `${item.title}\n${item.content}`.includes(assetSearch.trim())));
  const currentAssetLabel = ASSET_TABS.find((item) => item.key === assetTab)?.label || "私有库配置";
  const intelligenceGroups = groupedIntelligence(selectedProposal?.items ?? []);
  const reviewIssues = Array.isArray(reviewJob?.output_json?.issues) ? reviewJob?.output_json.issues as ReviewIssue[] : [];
  const outlineChapterNumber = chapterNumber ?? Math.max(1, Math.round(document.position / 1000));
  const briefSaveDisabled = !briefForm.outlineText.trim()
    || briefForm.targetWordCount < 500
    || briefForm.targetWordCount > 10000;
  const titleTools = document.visible_character_count > 0
    ? h("div", { className: "anw-chapter-title-tool-buttons", role: "toolbar", "aria-label": "章节工具" },
        h(Button, {
          className: "anw-chapter-title-tool",
          icon: h(AuditOutlined),
          onClick: confirmReview,
          title: "AI 审稿",
          "aria-label": "AI 审稿",
        }, "审稿"),
        h(Button, {
          className: "anw-chapter-title-tool",
          icon: h(BulbOutlined),
          onClick: openIntelligence,
          loading: busyAction === "intelligence-load",
          title: "查看章节情报",
          "aria-label": "查看章节情报",
        }, "情报"),
      )
    : null;
  const mountedTitleTools = titleTools && titleToolsTarget && typeof ReactDOM?.createPortal === "function"
    ? ReactDOM.createPortal(titleTools, titleToolsTarget)
    : titleTools;
  const briefEditorBody = h(
    "div",
    { className: "anw-outline-edit-body" },
    h(
      "label",
      { className: "anw-outline-edit-field" },
      h("strong", null, "章节大纲"),
      h(TextArea, {
        ...assistantBriefControlProps(CHAPTER_OUTLINE_FIELD_IDS.outlineText),
        maxLength: 30000,
        "aria-label": "章节大纲",
        value: briefForm.outlineText,
        onChange: (event: any) => updateBriefField(
          CHAPTER_OUTLINE_FIELD_IDS.outlineText,
          "outlineText",
          event.target.value,
        ),
        placeholder: "请输入章节大纲...",
      }),
    ),
    h(
      "label",
      { className: "anw-outline-edit-field anw-outline-edit-target" },
      h("strong", null, "目标字数"),
      h(Input, {
        ...assistantBriefControlProps(CHAPTER_OUTLINE_FIELD_IDS.targetCharacters),
        type: "number",
        min: 500,
        max: 10000,
        step: 100,
        inputMode: "numeric",
        "aria-label": "目标字数",
        value: briefForm.targetWordCount,
        onChange: (event: any) => {
          const value = Number(event.target.value);
          if (Number.isFinite(value)) updateBriefField(
            CHAPTER_OUTLINE_FIELD_IDS.targetCharacters,
            "targetWordCount",
            value,
          );
        },
      }),
      h("small", null, "建议范围：500-10000字"),
    ),
    ...OUTLINE_FIELD_SPECS.filter((spec) => !new Set<string>([
      CHAPTER_OUTLINE_FIELD_IDS.outlineText,
      CHAPTER_OUTLINE_FIELD_IDS.targetCharacters,
    ]).has(spec.id)).map((spec) => h(
      "label",
      { key: spec.id, className: "anw-outline-edit-field" },
      h("strong", null, spec.label),
      h(TextArea, {
        ...assistantBriefControlProps(spec.id),
        rows: spec.id === CHAPTER_OUTLINE_FIELD_IDS.expectation
          || spec.id === CHAPTER_OUTLINE_FIELD_IDS.forbidden ? 3 : 2,
        "aria-label": spec.label,
        value: spec.serialize(briefForm[spec.key]),
        onChange: (event: any) => updateBriefField(
          spec.id,
          spec.key,
          spec.parse(event.target.value) as never,
        ),
      }),
    )),
  );

  return h(
    React.Fragment,
    null,
    h("div", { className: "anw-workflow-panel" },
      h(Button, { className: "anw-generate-button", icon: h(BookOutlined), onClick: openGenerationOptions, loading: busyAction === "generate" || busyAction === "assets-load" }, document.visible_character_count > 0 ? "重新生成" : "生成正文"),
      h(Button, { ref: briefTriggerRef, className: "anw-outline-button", icon: h(EditOutlined), onClick: openBrief, loading: busyAction === "brief-load" }, "修改章纲"),
      h(Button, { className: "anw-sync-button", icon: h(SyncOutlined), onClick: confirmSyncProgress, loading: busyAction === "sync", disabled: document.visible_character_count === 0 }, "同步进展"),
      h(Button, { className: "anw-history-button", icon: h(HistoryOutlined), onClick: openJobs, loading: busyAction === "jobs-load" }, "历史"),
    ),
    mountedTitleTools,
    h(Modal, {
      open: briefOpen,
      className: "anw-modal anw-outline-edit-modal",
      wrapClassName: "anw-assistant-aware-modal-wrap",
      mask: false,
      title: h("div", { className: "anw-outline-edit-title" },
        h("span", { className: "anw-outline-edit-icon", "aria-hidden": "true" }, h(EditOutlined)),
        h("span", { className: "anw-outline-edit-heading" },
          h("strong", null, "编辑章纲"),
          h("small", null, `第${outlineChapterNumber}章`),
        ),
      ),
      width: 610,
      centered: true,
      focusTriggerAfterClose: false,
      afterClose: () => restoreDialogTriggerFocus(briefTriggerRef.current),
      onCancel: () => setBriefOpen(false),
      footer: [
        h("button", { key: "cancel", type: "button", className: "anw-outline-edit-cancel", onClick: () => setBriefOpen(false) }, "取消"),
        h(Button, { key: "save", className: "anw-outline-edit-save", type: "primary", loading: busyAction === "brief-save", disabled: briefSaveDisabled, onClick: saveBrief }, "保存章纲"),
      ],
    }, SelectionEditReviewHost
      ? h(
        SelectionEditReviewHost,
        {
          fieldIds: Object.values(CHAPTER_OUTLINE_FIELD_IDS),
          className: "anw-outline-selection-review-host",
        },
        briefEditorBody,
      )
      : briefEditorBody),
    h(Modal, {
      open: assetPickerOpen,
      className: "anw-modal anw-asset-modal",
      title: "选择私有库配置",
      width: 700,
      centered: true,
      onCancel: () => setAssetPickerOpen(false),
      footer: [h(Button, { key: "skip", onClick: () => confirmGenerateBody([]) }, "跳过"), h(Button, { key: "generate", type: "primary", onClick: () => confirmGenerateBody(selectedAssetIds) }, `确定选择${selectedAssetIds.length ? `（${selectedAssetIds.length}）` : ""}`)],
    }, h("section", { className: "anw-asset-picker" },
      h("p", { className: "anw-asset-picker-copy" }, "AI 将重点展示选中的内容到生成结果中"),
      h("div", { className: "anw-asset-search-row" }, h(Input, { value: assetSearch, prefix: h(SearchOutlined), placeholder: "搜索私有库素材", onChange: (event: any) => setAssetSearch(event.target.value) }), h(Button, { type: "link", icon: h(PlusOutlined), onClick: () => setQuickAssetOpen(true) }, "快速添加私有素材")),
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
    h(Modal, { open: generatingOpen, className: "anw-modal anw-generating-modal", width: 520, centered: true, closable: false, maskClosable: false, keyboard: false, footer: null }, h("section", { className: "anw-generation-progress" }, h(Spin, { size: "large" }), h("h2", null, `${activeGenerationModel ? generationModelLabel(activeGenerationModel) : "当前有效模型"} 正在工作`), h("p", null, generationStage), h("span", null, "完成后将自动返回当前章节"))),
    h(Modal, {
      open: jobsOpen,
      className: "anw-modal anw-generation-history-modal",
      title: h("div", { className: "anw-history-title" }, h("strong", null, `生成历史（共 ${jobs.length} 次）`), h(Tag, { color: "processing" }, "按任务记录模型")),
      width: 760,
      centered: true,
      footer: null,
      onCancel: () => setJobsOpen(false),
    }, jobs.length === 0 ? h(Empty, { description: "还没有正文生成记录" }) : h("div", { className: "anw-generation-history-list" }, ...jobs.map((job: GenerationJobRecord) => {
      const candidate = job.candidate;
      const state = candidate?.state ?? job.state;
      const minimumCount = job.minimum_visible_character_count ?? job.target_visible_character_count;
      const maximumCount = job.maximum_visible_character_count;
      return h("article", { key: job.id, className: `anw-history-card${candidate?.id === featuredCandidateId ? " is-featured" : ""}` },
        h("header", null, h("div", null, h("strong", null, `第 ${job.attempt || 1} 次生成`), h("span", null, formatDate(job.completed_at || job.created_at))), h(Tag, { color: stateColor(state) }, stateLabel(state))),
        h("div", { className: "anw-history-meta" },
          h("span", null, `正文 ${job.output_visible_character_count || candidate?.visible_character_count || 0} 字`),
          h("span", null, maximumCount ? `验收 ${minimumCount}–${maximumCount} 字` : `验收不少于 ${minimumCount} 字`),
          h("span", null, verifiedGenerationModelLabel(job)),
        ),
        candidate ? h("p", null, candidate.content_text.slice(0, 230) || "本次生成正文为空") : h("p", { className: "is-error" }, job.failure_message || "本次生成没有可用正文"),
        h("footer", null, job.asset_snapshot?.length ? h("small", null, `采用私有库：${job.asset_snapshot.map((item: GenerationJobRecord["asset_snapshot"][number]) => item.title).join("、")}`) : h("small", null, "未选择私有库配置"), h(Button, { disabled: !candidate || candidate.state === "rejected", loading: busyAction === `restore:${candidate?.id}`, onClick: () => void restoreCandidate(job) }, candidate ? "恢复此版本" : "需要整章重写")),
      );
    }))),
    h(
      Modal,
      {
        open: intelligenceOpen,
        className: "anw-modal anw-intelligence-modal",
        title: h("div", { className: "anw-intelligence-title" }, h("strong", null, "本章章节情报"), h("span", null, selectedProposal ? `（${selectedProposal.state === "failed" ? generationModelAuditLabel(selectedProposal) : verifiedGenerationModelLabel(selectedProposal)}）` : "（本内容由AI生成）")),
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
      title: h("div", { className: "anw-review-title" }, h(AuditOutlined), h("strong", null, "AI审稿报告"), h(Tag, { color: "processing" }, reviewJob ? verifiedGenerationModelLabel(reviewJob) : "当前任务模型")),
      width: 820,
      centered: true,
      footer: [h(Button, { key: "close", type: "primary", onClick: () => setReviewOpen(false) }, "关闭")],
      onCancel: () => setReviewOpen(false),
    }, reviewJob ? h("div", { className: "anw-review-result" }, h(Alert, { type: reviewJob.output_json?.passed ? "success" : "warning", showIcon: true, message: reviewJob.output_json?.passed ? "本章通过基础审阅" : "本章存在需要修改的问题", description: String(reviewJob.output_json?.summary || "模型已完成本章审阅。") }), reviewIssues.length ? h("div", { className: "anw-review-issues" }, ...reviewIssues.map((issue, index) => h(Card, { key: `${issue.type}-${index}`, size: "small" }, h("header", null, h(Tag, { color: issue.severity === "P0" || issue.severity === "P1" ? "error" : "warning" }, issue.severity || "P2"), h("strong", null, issue.type || "正文问题")), issue.evidence ? h("p", null, h("b", null, "原文依据："), issue.evidence) : null, issue.suggestion ? h("p", null, h("b", null, "修改建议："), issue.suggestion) : null))) : h(Empty, { description: "未发现需要单列的问题" })) : h(Empty, { description: "暂无审稿结果" })),
  );
}
