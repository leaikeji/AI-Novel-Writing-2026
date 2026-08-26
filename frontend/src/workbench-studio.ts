import {
  apiErrorMessage,
  apiRequest,
  completedGenerationModelLabel,
  generationModelLabel,
  generationModelAuditLabel,
  getGenerationModelStatus,
  verifiedGenerationModelLabel,
} from "./api";
import {
  ChapterCreationCompleteRecord,
  ChapterCreationDraftRecord,
  CharacterRelationshipRecord,
  CreativeGenerationRecord,
  DocumentRecord,
  ForeshadowRecord,
  GenerationModelStatus,
  NovelCharacterRecord,
  NovelExportRecord,
  NovelRecord,
  NovelSearchResultRecord,
  OutlineCharacterDraft,
  OutlineDraftRecord,
  StorylineRecord,
  StorylineType,
  VolumeRecord,
} from "./types";
import type { AssistantWorkspaceLayout } from "./assistant-layout";
import type { NovelAssistantContextEnvelope } from "./assistant-context-schema";
import {
  assistantContextRuntime,
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantContextScopeHandle,
  type AssistantContextScopeInput,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import {
  createAssistantFormFieldAdapter,
  type AssistantFormFieldAdapter,
} from "./assistant-form-field";
import {
  readAssistantTextSelection,
  restoreAssistantTextSelection,
  type AssistantTextControl,
} from "./chapter-workflow";
import type { SelectionRange, SelectionSnapshot } from "./assistant-fields";
import type { SelectionEditReviewHostComponent } from "./selection-edit-runtime";
import { compressCover } from "./cover-utils";
import { chapterDisplayTitle } from "./presenters";
import { RelationshipEditor } from "./relationship-editor";
import { RelationshipWorkspace } from "./relationship-workspace";
import { rememberWorkbenchRoleView } from "./workbench-route";
import defaultNovelCover from "../assets/novel-cover-fengcunqu.jpg";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Spin,
} = host.antd;
const {
  ArrowDownOutlined,
  ArrowUpOutlined,
  BgColorsOutlined,
  BookOutlined,
  BulbOutlined,
  CaretDownOutlined,
  CaretRightOutlined,
  CheckOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  UploadOutlined,
} = host.antdIcons;


export type WorkbenchSection = "chapters" | "outline" | "roles" | "clues" | "settings";


export const STUDIO_ASSISTANT_FIELD_IDS = {
  outlineTargetChapterCount: "outline.targetChapterCount",
  outlineBackground: "outline.background",
  outlinePlot: "outline.plot",
  outlineHighlight: "outline.highlight",
  outlineCharacterRoleType: "outline.character.roleType",
  outlineCharacterName: "outline.character.name",
  outlineCharacterGender: "outline.character.gender",
  outlineCharacterAge: "outline.character.age",
  outlineCharacterPersonality: "outline.character.personality",
  outlineCharacterIdentity: "outline.character.identity",
  outlineCharacterDescription: "outline.character.description",
  characterRoleType: "character.roleType",
  characterName: "character.name",
  characterGender: "character.gender",
  characterAge: "character.age",
  characterIdentity: "character.identity",
  characterPersonality: "character.personality",
  characterDescription: "character.description",
  storylineType: "storyline.storylineType",
  storylineTitle: "storyline.title",
  storylineDescription: "storyline.description",
  storylineStatus: "storyline.status",
  storylineProgress: "storyline.progress",
  foreshadowTitle: "foreshadow.title",
  foreshadowContent: "foreshadow.content",
  foreshadowLatestProgress: "foreshadow.latestProgress",
  foreshadowStatus: "foreshadow.status",
  settingsTemplateName: "settings.templateName",
  settingsGenre: "settings.genre",
  settingsSubgenre: "settings.subgenre",
  settingsIdea: "settings.idea",
} as const;


export const STUDIO_SELECTION_REVIEW_FIELD_GROUPS = {
  outline: [
    STUDIO_ASSISTANT_FIELD_IDS.outlineTargetChapterCount,
    STUDIO_ASSISTANT_FIELD_IDS.outlineBackground,
    STUDIO_ASSISTANT_FIELD_IDS.outlinePlot,
    STUDIO_ASSISTANT_FIELD_IDS.outlineHighlight,
  ],
  outlineCharacter: [
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterRoleType,
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterName,
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterGender,
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterAge,
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterPersonality,
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterIdentity,
    STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterDescription,
  ],
  character: [
    STUDIO_ASSISTANT_FIELD_IDS.characterRoleType,
    STUDIO_ASSISTANT_FIELD_IDS.characterName,
    STUDIO_ASSISTANT_FIELD_IDS.characterGender,
    STUDIO_ASSISTANT_FIELD_IDS.characterAge,
    STUDIO_ASSISTANT_FIELD_IDS.characterIdentity,
    STUDIO_ASSISTANT_FIELD_IDS.characterPersonality,
    STUDIO_ASSISTANT_FIELD_IDS.characterDescription,
  ],
  storyline: [
    STUDIO_ASSISTANT_FIELD_IDS.storylineType,
    STUDIO_ASSISTANT_FIELD_IDS.storylineTitle,
    STUDIO_ASSISTANT_FIELD_IDS.storylineDescription,
    STUDIO_ASSISTANT_FIELD_IDS.storylineStatus,
    STUDIO_ASSISTANT_FIELD_IDS.storylineProgress,
  ],
  foreshadow: [
    STUDIO_ASSISTANT_FIELD_IDS.foreshadowTitle,
    STUDIO_ASSISTANT_FIELD_IDS.foreshadowContent,
    STUDIO_ASSISTANT_FIELD_IDS.foreshadowLatestProgress,
    STUDIO_ASSISTANT_FIELD_IDS.foreshadowStatus,
  ],
  settings: [
    STUDIO_ASSISTANT_FIELD_IDS.settingsTemplateName,
    STUDIO_ASSISTANT_FIELD_IDS.settingsGenre,
    STUDIO_ASSISTANT_FIELD_IDS.settingsSubgenre,
    STUDIO_ASSISTANT_FIELD_IDS.settingsIdea,
  ],
} as const;


function settingsTemplateFieldId(key: string): string {
  return `settings.templateData.${encodeURIComponent(key)}`;
}


export interface StudioAssistantFieldBinding {
  id: string;
  label: string;
  getValue: () => string;
  getDirty: () => boolean;
  applyDraftValue: (nextValue: string) => void | Promise<void>;
  markDirty: () => void | Promise<void>;
  getSelection?: () => SelectionSnapshot | null;
  restoreSelection?: (range: SelectionRange) => void;
  focus: () => void;
  dispose?: () => void;
}


export interface StudioAssistantScopeMount {
  readonly handle: AssistantContextScopeHandle;
  readonly adapters: ReadonlyMap<string, AssistantFormFieldAdapter>;
  dispose(): void;
}


export async function hashStudioAssistantField(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is required for assistant form fields");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


/** Mount one page/modal scope and bind only controlled React draft fields. */
export function mountStudioAssistantScope(
  runtime: NovelAssistantContextRuntime,
  input: AssistantContextScopeInput,
  bindings: readonly StudioAssistantFieldBinding[] = [],
  hashValue: (value: string) => string | Promise<string> = hashStudioAssistantField,
): StudioAssistantScopeMount {
  const handle = runtime.mountScope(input);
  const adapters = new Map<string, AssistantFormFieldAdapter>();
  try {
    for (const binding of bindings) {
      if (adapters.has(binding.id)) {
        throw new Error(`duplicate studio assistant field: ${binding.id}`);
      }
      const adapter = createAssistantFormFieldAdapter({
        id: binding.id,
        label: binding.label,
        getValue: binding.getValue,
        getDirty: binding.getDirty,
        getSelection: binding.getSelection ?? (() => null),
        hashValue,
        applyDraftValue: (nextValue) => binding.applyDraftValue(nextValue),
        markDirty: async () => {
          await binding.markDirty();
          handle.notifyFieldChanged(binding.id);
        },
        restoreSelection: binding.restoreSelection ?? (() => undefined),
        focus: binding.focus,
        dispose: binding.dispose,
      });
      try {
        handle.registerField(adapter);
      } catch (reason) {
        adapter.dispose();
        throw reason;
      }
      adapters.set(binding.id, adapter);
    }
  } catch (reason) {
    handle.dispose();
    throw reason;
  }
  return {
    handle,
    adapters,
    dispose: () => handle.dispose(),
  };
}


export function studioAssistantPageEnvelope(
  novel: Pick<NovelRecord, "id" | "title">,
  section: WorkbenchSection,
  roleView: "list" | "graph" = "list",
): NovelAssistantContextEnvelope | null {
  const base = {
    agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
    novel: { id: novel.id, title: novel.title },
  };
  if (section === "outline") {
    return {
      ...base,
      page: { section: "outline", view: "novel-outline" },
      entity: { type: "outline", id: novel.id, title: novel.title },
    };
  }
  if (section === "roles" && roleView === "list") {
    return {
      ...base,
      page: { section: "roles", view: "character-list" },
      entity: { type: "novel", id: novel.id, title: novel.title },
    };
  }
  if (section === "clues") {
    return {
      ...base,
      page: { section: "clues", view: "clue-list" },
      entity: { type: "novel", id: novel.id, title: novel.title },
    };
  }
  if (section === "settings") {
    return {
      ...base,
      page: { section: "settings", view: "novel-settings" },
      entity: { type: "setting", id: novel.id, title: novel.title },
    };
  }
  return null;
}


interface StudioMutableRef<T> {
  current: T;
}


interface StudioFocusableControl {
  focus?: () => void;
  input?: AssistantTextControl | null;
  resizableTextArea?: { textArea?: AssistantTextControl | null } | null;
  selectionStart?: number | null;
  selectionEnd?: number | null;
  selectionDirection?: string | null;
  setSelectionRange?: AssistantTextControl["setSelectionRange"];
}


function studioTextControl(
  control: StudioFocusableControl | undefined,
): AssistantTextControl | null {
  const candidate = control?.input
    ?? control?.resizableTextArea?.textArea
    ?? control;
  if (!candidate
    || typeof candidate.focus !== "function"
    || typeof candidate.setSelectionRange !== "function"
    || !("selectionStart" in candidate)
    || !("selectionEnd" in candidate)) {
    return null;
  }
  return candidate as AssistantTextControl;
}


function replaceStudioControlledState<T>(
  stateRef: StudioMutableRef<T>,
  setState: (next: T) => void,
  next: T,
): void {
  stateRef.current = next;
  setState(next);
}


function setStudioControlledField<T, Key extends keyof T>(
  stateRef: StudioMutableRef<T>,
  setState: (next: T) => void,
  key: Key,
  value: T[Key],
): void {
  replaceStudioControlledState(
    stateRef,
    setState,
    { ...stateRef.current, [key]: value },
  );
}


function requireStudioChoice<const Choice extends string>(
  value: string,
  choices: readonly Choice[],
  label: string,
): Choice {
  if (!choices.includes(value as Choice)) {
    throw new Error(`${label}值无效`);
  }
  return value as Choice;
}


function requireStudioPercentage(value: string): number {
  const parsed = Number(value);
  if (
    value.trim() !== value
    || !Number.isFinite(parsed)
    || parsed < 0
    || parsed > 100
    || String(parsed) !== value
  ) {
    throw new Error("故事线进度必须是 0 到 100 的数字");
  }
  return parsed;
}


function requireStudioMaxLength(
  value: string,
  maximum: number,
  label: string,
): string {
  if (value.length > maximum) {
    throw new Error(`${label}不能超过 ${maximum} 个 UTF-16 字符`);
  }
  return value;
}


const OUTLINE_STEPS = ["章节", "背景", "角色", "情节", "亮点"];
const OUTLINE_HINTS = [
  "还差4步了哦，故事即将诞生!",
  "还差3步了哦，正在快马加鞭赶来!",
  "还差2步了哦，马上就要大功告成啦!",
  "还差1步了哦，马上就要大功告成啦!",
  "最后一步啦，确认无误后点击完成!",
];


function readableError(reason: unknown, fallback: string): string {
  return apiErrorMessage(reason, fallback);
}


function creativeTaskModelLabel(job: CreativeGenerationRecord): string {
  return job.state === "ready"
    ? verifiedGenerationModelLabel(job)
    : generationModelAuditLabel(job);
}


function visibleCount(value: string): number {
  return value.replace(/\s+/g, "").length;
}


function field(label: string, control: unknown, hint?: string): unknown {
  return h(
    "label",
    { className: "mb-field" },
    h("span", { className: "mb-field-label" }, label),
    control,
    hint ? h("span", { className: "mb-field-hint" }, hint) : null,
  );
}


function sectionIcon(section: WorkbenchSection): any {
  return {
    chapters: FileTextOutlined,
    outline: UnorderedListOutlined,
    roles: TeamOutlined,
    clues: BulbOutlined,
    settings: SettingOutlined,
  }[section];
}


function sectionLabel(section: WorkbenchSection): string {
  return {
    chapters: "章节",
    outline: "大纲",
    roles: "角色",
    clues: "线索",
    settings: "设定",
  }[section];
}


function downloadExport(record: NovelExportRecord, title: string): void {
  const extension = record.export_format === "markdown" ? "md" : "txt";
  const blob = new Blob([record.content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${title}.${extension}`;
  link.click();
  URL.revokeObjectURL(url);
}


interface OutlineWizardProps {
  novel: NovelRecord;
  open: boolean;
  startStep: number;
  onClose: () => void;
  onGoChapters: () => void;
  onCompleted: (novel: NovelRecord) => void;
  onError: (message: string) => void;
  selectionEditReviewHost?: SelectionEditReviewHostComponent;
}


function OutlineWizard({
  novel,
  open,
  startStep,
  onClose,
  onGoChapters,
  onCompleted,
  onError,
  selectionEditReviewHost: SelectionEditReviewHost,
}: OutlineWizardProps) {
  const [draft, setDraft] = React.useState(null as OutlineDraftRecord | null);
  const [step, setStep] = React.useState(1);
  const [completed, setCompleted] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [activityText, setActivityText] = React.useState("");
  const [lastGeneratedModelLabel, setLastGeneratedModelLabel] = React.useState("");
  const [characterOpen, setCharacterOpen] = React.useState(false);
  const [characterIndex, setCharacterIndex] = React.useState(-1);
  const [characterForm, setCharacterForm] = React.useState({
    name: "", role_type: "main" as "main" | "supporting", gender: "", age: "",
    personality: "", identity: "", description: "",
  });
  const draftRef = React.useRef(draft) as StudioMutableRef<OutlineDraftRecord | null>;
  const characterFormRef = React.useRef(characterForm) as StudioMutableRef<typeof characterForm>;
  const outlineDirtyFieldsRef = React.useRef(new Set<string>()) as StudioMutableRef<Set<string>>;
  const outlineCharacterDirtyFieldsRef = React.useRef(new Set<string>()) as StudioMutableRef<Set<string>>;
  const outlineAssistantScopeRef = React.useRef(null as AssistantContextScopeHandle | null) as StudioMutableRef<AssistantContextScopeHandle | null>;
  const outlineCharacterAssistantScopeRef = React.useRef(null as AssistantContextScopeHandle | null) as StudioMutableRef<AssistantContextScopeHandle | null>;
  const outlineControlRefs = React.useRef(new Map<string, StudioFocusableControl>()) as StudioMutableRef<Map<string, StudioFocusableControl>>;
  draftRef.current = draft;
  characterFormRef.current = characterForm;

  const wrapSelectionReview = (
    fieldIds: readonly string[],
    className: string,
    child: unknown,
  ): unknown => SelectionEditReviewHost
    ? h(SelectionEditReviewHost, { fieldIds, className }, child)
    : child;

  const replaceDraft = (next: OutlineDraftRecord | null): void => {
    draftRef.current = next;
    setDraft(next);
  };
  const replaceCharacterForm = (next: typeof characterForm): void => {
    characterFormRef.current = next;
    setCharacterForm(next);
  };
  const outlineControlProps = (
    scopeRef: StudioMutableRef<AssistantContextScopeHandle | null>,
    fieldId: string,
  ) => ({
    ref: (control: StudioFocusableControl | null) => {
      if (control) outlineControlRefs.current.set(fieldId, control);
      else outlineControlRefs.current.delete(fieldId);
    },
    onFocus: () => scopeRef.current?.setFocusedField(fieldId),
    onBlur: () => scopeRef.current?.setFocusedField(undefined),
  });
  const outlineFieldBinding = (
    scopeRef: StudioMutableRef<AssistantContextScopeHandle | null>,
    dirtyRef: StudioMutableRef<Set<string>>,
    id: string,
    label: string,
    getValue: () => string,
    applyDraftValue: (value: string) => void,
  ): StudioAssistantFieldBinding => ({
    id,
    label,
    getValue,
    getDirty: () => dirtyRef.current.has(id),
    applyDraftValue,
    markDirty: () => { dirtyRef.current.add(id); },
    getSelection: () => readAssistantTextSelection(
      studioTextControl(outlineControlRefs.current.get(id)),
      getValue(),
    ),
    restoreSelection: (range) => restoreAssistantTextSelection(
      studioTextControl(outlineControlRefs.current.get(id)),
      range,
    ),
    focus: () => outlineControlRefs.current.get(id)?.focus?.(),
  });
  const markOutlineChanged = (
    scopeRef: StudioMutableRef<AssistantContextScopeHandle | null>,
    dirtyRef: StudioMutableRef<Set<string>>,
    fieldId: string,
  ): void => {
    dirtyRef.current.add(fieldId);
    scopeRef.current?.notifyFieldChanged(fieldId);
  };

  React.useEffect(() => {
    if (!open) return;
    setCompleted(false);
    setLastGeneratedModelLabel("");
    setLoading(true);
    void apiRequest<OutlineDraftRecord>(`/novels/${novel.id}/outline-draft`)
      .then((record) => {
        replaceDraft(record);
        outlineDirtyFieldsRef.current.clear();
        setStep(Math.max(1, Math.min(5, startStep >= 1 ? startStep : record.step || 1)));
        void apiRequest<CreativeGenerationRecord[]>(
          `/creative-generations?scope_type=outline&scope_id=${encodeURIComponent(record.id)}`,
        ).then((jobs) => {
          const latest = jobs.find((job) => job.kind.startsWith("outline_"));
          setLastGeneratedModelLabel(latest ? creativeTaskModelLabel(latest) : "");
        }).catch(() => setLastGeneratedModelLabel(""));
      })
      .catch((reason) => onError(readableError(reason, "加载大纲草稿失败")))
      .finally(() => setLoading(false));
  }, [open, novel.id, startStep]);

  const updateLocal = (patch: Partial<OutlineDraftRecord>) => {
    const current = draftRef.current;
    replaceDraft(current ? { ...current, ...patch } : current);
  };

  const saveDraft = async (
    base: OutlineDraftRecord,
    nextStep: number,
    patch: Record<string, unknown>,
  ): Promise<OutlineDraftRecord> => {
    const updated = await apiRequest<OutlineDraftRecord>(`/novels/${novel.id}/outline-draft`, {
      method: "PATCH",
      body: JSON.stringify({ expected_version: base.version, step: nextStep, ...patch }),
    });
    replaceDraft(updated);
    outlineDirtyFieldsRef.current.clear();
    setStep(nextStep);
    return updated;
  };

  const generate = async (
    base: OutlineDraftRecord,
    kind: "outline_background" | "outline_characters" | "outline_plot" | "outline_highlight",
  ): Promise<CreativeGenerationRecord> => {
    const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
      method: "POST",
      body: JSON.stringify({
        scope_type: "outline",
        scope_id: base.id,
        novel_id: novel.id,
        kind,
        force_new: true,
        input_snapshot: {
          novel_title: novel.title,
          audience: novel.audience,
          genre: novel.genre,
          subgenre: novel.subgenre,
          idea: novel.idea,
          template_name: novel.template_name,
          template_data: novel.template_data,
          target_chapter_count: base.target_chapter_count,
          background_text: base.background_text,
          characters: base.characters,
          plot_text: base.plot_text,
          highlight_text: base.highlight_text,
        },
      }),
    });
    if (job.state !== "ready") throw new Error(job.failure_message || "模型生成失败");
    setLastGeneratedModelLabel(creativeTaskModelLabel(job));
    return job;
  };

  const nextWithGeneration = async () => {
    if (!draft || generating) return;
    setGenerating(true);
    try {
      const currentModel = await getGenerationModelStatus();
      setActivityText(`${generationModelLabel(currentModel)} 正在生成...`);
      if (step === 1) {
        const saved = await saveDraft(draft, 1, { target_chapter_count: draft.target_chapter_count });
        const job = await generate(saved, "outline_background");
        await saveDraft(saved, 2, { background_text: String(job.output_json.background_text || "").slice(0, 2000) });
      } else if (step === 2) {
        const saved = await saveDraft(draft, 2, { background_text: draft.background_text });
        const job = await generate(saved, "outline_characters");
        const rows = Array.isArray(job.output_json.characters)
          ? job.output_json.characters
          : job.output_json.name
            ? [job.output_json]
            : [];
        const characters: OutlineCharacterDraft[] = rows.map((item: any): OutlineCharacterDraft => ({
          name: String(item.name || "").trim(),
          role_type: item.role_type === "main" ? "main" : "supporting",
          description: String(item.description || ""),
          details: item.details && typeof item.details === "object" ? item.details : {},
        })).filter((item: OutlineCharacterDraft) => Boolean(item.name));
        await saveDraft(saved, 3, { characters });
      } else if (step === 3) {
        const saved = await saveDraft(draft, 3, { characters: draft.characters });
        const job = await generate(saved, "outline_plot");
        await saveDraft(saved, 4, { plot_text: String(job.output_json.plot_text || "").slice(0, 5000) });
      } else if (step === 4) {
        const saved = await saveDraft(draft, 4, { plot_text: draft.plot_text });
        const job = await generate(saved, "outline_highlight");
        await saveDraft(saved, 5, { highlight_text: String(job.output_json.highlight_text || "").slice(0, 200) });
      }
    } catch (reason) {
      onError(readableError(reason, "生成大纲失败"));
    } finally {
      setGenerating(false);
      setActivityText("");
    }
  };

  const requestNextGeneration = async () => {
    if (!draft || generating || step >= 5) return;
    const generationName = step === 1 ? "故事背景" : step === 2 ? "角色设定" : step === 3 ? "故事情节" : "故事亮点";
    const generationCost = step === 1 || step === 2 ? 500 : step === 3 ? 1500 : 500;
    const explanation = step === 1
      ? "AI将根据您的设定创建一个引人入胜的故事世界。"
      : step === 2
        ? "AI将为主角和配角塑造鲜活的个性。"
        : step === 3
          ? "AI将为您构建精彩的故事主线，聚焦核心矛盾与转折。"
          : "AI将为您提炼作品的核心价值和独特之处。";
    let modelLabel: string;
    try {
      modelLabel = generationModelLabel(await getGenerationModelStatus());
    } catch (reason) {
      onError(readableError(reason, "读取当前有效模型失败"));
      return;
    }
    Modal.confirm({
      className: "anw-modal mb-outline-cost-modal",
      title: "确认扣除字数",
      content: h(
        "div",
        { className: "mb-outline-cost-copy" },
        h("h3", null, `需要消耗${generationCost}字`),
        h("p", null, `生成${generationName}需要消耗${generationCost}字，${explanation}`),
        h("p", null, `本次将使用 ${modelLabel}。`),
      ),
      okText: "确认",
      cancelText: "取消",
      onOk() {
        void nextWithGeneration();
      },
    });
  };

  const manualNext = async () => {
    if (!draft || step >= 5 || generating) return;
    const patch = step === 1
      ? { target_chapter_count: draft.target_chapter_count }
      : step === 2
        ? { background_text: draft.background_text }
        : step === 3
          ? { characters: draft.characters }
          : { plot_text: draft.plot_text };
    setActivityText("正在保存...");
    setGenerating(true);
    try {
      await saveDraft(draft, step + 1, patch);
    } catch (reason) {
      onError(readableError(reason, "保存大纲草稿失败"));
    } finally {
      setGenerating(false);
      setActivityText("");
    }
  };

  const previous = async () => {
    if (!draft || step <= 1 || generating) return;
    setActivityText("正在保存...");
    setGenerating(true);
    try {
      await saveDraft(draft, step - 1, {});
    } catch (reason) {
      onError(readableError(reason, "切换大纲步骤失败"));
    } finally {
      setGenerating(false);
      setActivityText("");
    }
  };

  const complete = async () => {
    if (!draft || generating) return;
    setActivityText("正在保存...");
    setGenerating(true);
    try {
      const saved = await saveDraft(draft, 5, { highlight_text: draft.highlight_text });
      const result = await apiRequest<{ outline: OutlineDraftRecord; novel: NovelRecord }>(
        `/novels/${novel.id}/outline-draft/complete`,
        { method: "POST", body: JSON.stringify({ expected_version: saved.version }) },
      );
      replaceDraft(result.outline);
      onCompleted(result.novel);
      setCompleted(true);
    } catch (reason) {
      onError(readableError(reason, "完成大纲失败"));
    } finally {
      setGenerating(false);
      setActivityText("");
    }
  };

  const openCharacter = (roleType: "main" | "supporting", index = -1) => {
    const current = index >= 0 ? draft?.characters[index] : null;
    setCharacterIndex(index);
    outlineCharacterDirtyFieldsRef.current.clear();
    replaceCharacterForm({
      name: current?.name ?? "",
      role_type: current?.role_type ?? roleType,
      gender: String(current?.details?.gender ?? ""),
      age: String(current?.details?.age ?? ""),
      personality: String(current?.details?.personality ?? ""),
      identity: String(current?.details?.identity ?? ""),
      description: current?.description ?? "",
    });
    setCharacterOpen(true);
  };

  const saveCharacter = () => {
    if (!draftRef.current || !characterFormRef.current.name.trim()) return;
    const currentForm = characterFormRef.current;
    const next: OutlineCharacterDraft = {
      name: currentForm.name.trim(),
      role_type: currentForm.role_type,
      description: currentForm.description.trim(),
      details: {
        gender: currentForm.gender.trim(),
        age: currentForm.age.trim(),
        personality: currentForm.personality.trim(),
        identity: currentForm.identity.trim(),
      },
    };
    const rows = [...draftRef.current.characters];
    if (characterIndex >= 0) rows[characterIndex] = next;
    else rows.push(next);
    updateLocal({ characters: rows });
    setCharacterOpen(false);
  };

  const removeCharacter = (index: number) => {
    if (!draft) return;
    updateLocal({ characters: draft.characters.filter((_: OutlineCharacterDraft, rowIndex: number) => rowIndex !== index) });
  };

  const changeOutlineField = (
    patch: Partial<OutlineDraftRecord>,
    fieldId: string,
  ): void => {
    updateLocal(patch);
    markOutlineChanged(
      outlineAssistantScopeRef,
      outlineDirtyFieldsRef,
      fieldId,
    );
  };
  const setOutlineCharacterField = <Key extends keyof typeof characterForm>(
    key: Key,
    value: (typeof characterForm)[Key],
  ): void => replaceCharacterForm({
    ...characterFormRef.current,
    [key]: value,
  });
  const changeOutlineCharacterField = <Key extends keyof typeof characterForm>(
    key: Key,
    value: (typeof characterForm)[Key],
    fieldId: string,
  ): void => {
    setOutlineCharacterField(key, value);
    markOutlineChanged(
      outlineCharacterAssistantScopeRef,
      outlineCharacterDirtyFieldsRef,
      fieldId,
    );
  };

  React.useEffect(() => {
    if (!open || !draft || completed) return;
    const ids = STUDIO_ASSISTANT_FIELD_IDS;
    const binding = step === 1
      ? outlineFieldBinding(
          outlineAssistantScopeRef,
          outlineDirtyFieldsRef,
          ids.outlineTargetChapterCount,
          "目标章节数",
          () => String(draftRef.current?.target_chapter_count ?? 10),
          (value) => {
            const parsed = Number(value);
            if (!Number.isSafeInteger(parsed) || parsed < 10 || parsed > 10_000) {
              throw new Error("目标章节数必须是 10-10000 的整数");
            }
            updateLocal({ target_chapter_count: parsed });
          },
        )
      : step === 2
        ? outlineFieldBinding(
            outlineAssistantScopeRef,
            outlineDirtyFieldsRef,
            ids.outlineBackground,
            "故事背景设定",
            () => draftRef.current?.background_text ?? "",
            (value) => updateLocal({ background_text: requireStudioMaxLength(value, 2000, "故事背景设定") }),
          )
        : step === 4
          ? outlineFieldBinding(
              outlineAssistantScopeRef,
              outlineDirtyFieldsRef,
              ids.outlinePlot,
              "故事主要情节",
              () => draftRef.current?.plot_text ?? "",
              (value) => updateLocal({ plot_text: requireStudioMaxLength(value, 5000, "故事主要情节") }),
            )
          : step === 5
            ? outlineFieldBinding(
                outlineAssistantScopeRef,
                outlineDirtyFieldsRef,
                ids.outlineHighlight,
                "亮点与简介",
                () => draftRef.current?.highlight_text ?? "",
                (value) => updateLocal({ highlight_text: requireStudioMaxLength(value, 200, "亮点与简介") }),
              )
            : null;
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:modal:outline:${novel.id}:${draft.id}:step-${step}`,
        kind: "modal",
        persistenceBaseline: () => ({ kind: "entity", version: draftRef.current?.version ?? 0 }),
        envelope: {
          agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
          novel: { id: novel.id, title: novel.title },
          page: {
            section: "outline",
            view: "novel-outline",
            modal: "novel-outline",
          },
          entity: { type: "outline", id: draft.id, title: `${novel.title}总体大纲` },
        },
      },
      binding ? [binding] : [],
    );
    outlineAssistantScopeRef.current = mounted.handle;
    return () => {
      if (outlineAssistantScopeRef.current === mounted.handle) {
        outlineAssistantScopeRef.current = null;
      }
      mounted.dispose();
    };
  }, [completed, draft?.id, novel.id, novel.title, open, step]);

  React.useEffect(() => {
    if (!open || !characterOpen || !draft) return;
    const ids = STUDIO_ASSISTANT_FIELD_IDS;
    const fields: Array<[
      string,
      string,
      keyof typeof characterForm,
      number,
    ]> = [
      [ids.outlineCharacterName, "姓名", "name", 10],
      [ids.outlineCharacterGender, "性别", "gender", 2],
      [ids.outlineCharacterAge, "年龄", "age", 5],
      [ids.outlineCharacterPersonality, "性格", "personality", 20],
      [ids.outlineCharacterIdentity, "身份", "identity", 20],
      [ids.outlineCharacterDescription, "人物小传", "description", 100],
    ];
    const bindings: StudioAssistantFieldBinding[] = [
      outlineFieldBinding(
        outlineCharacterAssistantScopeRef,
        outlineCharacterDirtyFieldsRef,
        ids.outlineCharacterRoleType,
        "角色类型",
        () => characterFormRef.current.role_type,
        (value) => setOutlineCharacterField(
          "role_type",
          requireStudioChoice(value, ["main", "supporting"] as const, "角色类型"),
        ),
      ),
      ...fields.map(([id, label, key, maximum]) => outlineFieldBinding(
        outlineCharacterAssistantScopeRef,
        outlineCharacterDirtyFieldsRef,
        id,
        label,
        () => String(characterFormRef.current[key]),
        (value) => setOutlineCharacterField(
          key,
          requireStudioMaxLength(value, maximum, label) as never,
        ),
      )),
    ];
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:modal:outline-character:${novel.id}:${draft.id}:${characterIndex}`,
        kind: "modal",
        persistenceBaseline: { kind: "none", version: null },
        envelope: {
          agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
          novel: { id: novel.id, title: novel.title },
          page: {
            section: "outline",
            view: "novel-outline",
            modal: "character-editor",
          },
          entity: {
            type: "character",
            title: characterFormRef.current.name || "大纲角色草稿",
          },
        },
      },
      bindings,
    );
    outlineCharacterAssistantScopeRef.current = mounted.handle;
    return () => {
      if (outlineCharacterAssistantScopeRef.current === mounted.handle) {
        outlineCharacterAssistantScopeRef.current = null;
      }
      mounted.dispose();
    };
  }, [characterIndex, characterOpen, draft?.id, novel.id, novel.title, open]);

  const canContinue = draft && (
    (step === 1 && draft.target_chapter_count >= 10 && draft.target_chapter_count <= 10000)
    || (step === 2 && Boolean(draft.background_text.trim()))
    || (step === 3 && draft.characters.some((item: OutlineCharacterDraft) => item.role_type === "main"))
    || (step === 4 && Boolean(draft.plot_text.trim()))
    || (step === 5 && Boolean(draft.highlight_text.trim()))
  );

  const stepBody = !draft ? null : step === 1
    ? h(
        "div",
        { className: "mb-outline-step-body is-count" },
        h("h3", null, "设置章节数"),
        h("p", null, "请输入您希望本小说大概要写多少章节，这将帮助我们生成更符合预期的大纲"),
        h(InputNumber, {
          ...outlineControlProps(outlineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineTargetChapterCount),
          min: 10, max: 10000, precision: 0, controls: false,
          value: draft.target_chapter_count,
          onChange: (value: number | null) => changeOutlineField(
            { target_chapter_count: Number(value || 10) },
            STUDIO_ASSISTANT_FIELD_IDS.outlineTargetChapterCount,
          ),
          "aria-label": "目标章节数",
        }),
      )
    : step === 2
      ? h(
          "div",
          { className: "mb-outline-step-body" },
          h("div", { className: "mb-outline-heading-row" }, h("h3", null, "故事背景设定"), h("span", null, "AI已为您生成了故事背景设定，您可以查看并修改")),
          h(Input.TextArea, {
            ...outlineControlProps(outlineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineBackground),
            rows: 7, maxLength: 2000, value: draft.background_text,
            placeholder: "故事背景设定将在这里显示...",
            onChange: (event: any) => changeOutlineField(
              { background_text: event.target.value },
              STUDIO_ASSISTANT_FIELD_IDS.outlineBackground,
            ),
            "aria-label": "故事背景设定",
          }),
          h("div", { className: "mb-count-hint" }, `最多2000字，当前：${visibleCount(draft.background_text)}/2000`),
        )
      : step === 3
        ? h(
            "div",
            { className: "mb-outline-step-body is-roles" },
            h("h3", null, "角色设定"),
            h("p", null, "AI已为您生成了主角和配角，点击角色标签可以查看和修改详细信息"),
            ...(["main", "supporting"] as const).map((roleType) => h(
              "section",
              { key: roleType, className: "mb-outline-role-group" },
              h("strong", null, roleType === "main" ? "主角" : "配角"),
              h(
                "div",
                { className: "mb-outline-role-pills" },
                ...draft.characters.map((character: OutlineCharacterDraft, index: number) => character.role_type === roleType
                  ? h(
                      "span",
                      { key: `${character.name}:${index}`, className: `mb-role-pill is-${roleType}` },
                      h("button", { type: "button", onClick: () => openCharacter(roleType, index) }, character.name),
                      h("button", { type: "button", className: "mb-role-remove", onClick: () => removeCharacter(index), "aria-label": `删除${character.name}` }, "×"),
                    )
                  : null),
                h(Button, { className: `mb-add-role is-${roleType}`, icon: h(PlusOutlined), onClick: () => openCharacter(roleType) }, "新增"),
              ),
            )),
          )
        : step === 4
          ? h(
              "div",
              { className: "mb-outline-step-body" },
              h("div", { className: "mb-outline-heading-row" }, h("h3", null, "故事主要情节"), h("span", null, "AI已为您生成了故事主要情节，您可以查看并修改")),
              h(Input.TextArea, {
                ...outlineControlProps(outlineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlinePlot),
                rows: 9, maxLength: 5000, value: draft.plot_text,
                placeholder: "故事情节将在这里显示...",
                onChange: (event: any) => changeOutlineField(
                  { plot_text: event.target.value },
                  STUDIO_ASSISTANT_FIELD_IDS.outlinePlot,
                ),
                "aria-label": "故事主要情节",
              }),
              h("div", { className: "mb-count-hint" }, `最多5000字，当前：${visibleCount(draft.plot_text)}/5000`),
            )
          : h(
              "div",
              { className: "mb-outline-step-body is-highlight" },
              h("h3", null, "亮点&简介"),
              h("p", null, "AI已为您生成了亮点&简介，您可以查看并修改。确认无误后点击完成即可创建大纲"),
              h(Input.TextArea, {
                ...outlineControlProps(outlineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineHighlight),
                rows: 6, maxLength: 200, value: draft.highlight_text,
                placeholder: "主题亮点将在这里显示...",
                onChange: (event: any) => changeOutlineField(
                  { highlight_text: event.target.value },
                  STUDIO_ASSISTANT_FIELD_IDS.outlineHighlight,
                ),
                "aria-label": "亮点与简介",
              }),
              h("div", { className: "mb-count-hint" }, `最多200字，当前：${visibleCount(draft.highlight_text)}/200`),
            );

  return h(
    React.Fragment,
    null,
    h(
      Modal,
      {
        open,
        centered: true,
        className: "anw-modal mb-outline-modal",
        wrapClassName: "anw-assistant-aware-modal-wrap",
        mask: false,
        width: 600,
        title: h("div", { className: "mb-outline-modal-title" }, h("strong", null, "生成大纲"), h("span", null, lastGeneratedModelLabel ? `(最近任务模型：${lastGeneratedModelLabel})` : "(本内容由AI生成)")),
        footer: null,
        destroyOnClose: true,
        onCancel: generating ? undefined : onClose,
      },
      h(
        Spin,
        { spinning: loading || generating, tip: generating ? activityText || "正在处理..." : "正在载入..." },
        wrapSelectionReview(
          STUDIO_SELECTION_REVIEW_FIELD_GROUPS.outline,
          "mb-outline-selection-review-host",
          draft ? h(
          "div",
          { className: "mb-outline-wizard" },
          h("div", { className: "mb-outline-progress-hint" }, completed ? "大纲已创建完成!" : OUTLINE_HINTS[step - 1]),
          h(
            "div",
            { className: "mb-outline-steps", "aria-label": "大纲生成步骤" },
            ...OUTLINE_STEPS.map((label, index) => {
              const number = index + 1;
              const stepCompleted = completed || number < step;
              return h(
                "div",
                { key: label, className: `mb-outline-step ${!completed && number === step ? "is-active" : ""} ${stepCompleted ? "is-complete" : ""}` },
                h("span", { className: "mb-outline-step-dot" }, stepCompleted ? "✓" : number),
                h("span", { className: "mb-outline-step-label" }, label),
              );
            }),
          ),
          completed
            ? h(
                "div",
                { className: "mb-outline-success" },
                h("div", { className: "mb-outline-success-icon" }, h(CheckOutlined)),
                h("h3", null, "创建成功!"),
                h("p", null, "大纲已创建完成，您现在可以去创作章节了"),
                h(Button, { size: "large", className: "anw-primary-button", block: true, onClick: () => { onClose(); onGoChapters(); } }, "去创建章节"),
              )
            : h(
                React.Fragment,
                null,
                stepBody,
                step < 5 ? h("button", { type: "button", className: "mb-manual-link", disabled: generating, onClick: manualNext }, ["我已有故事背景", "我已有角色", "我已有故事情节", "我已有亮点&简介"][step - 1], "，点击直接填写") : null,
                h(
                  "div",
                  { className: "mb-outline-footer" },
                  step > 1 ? h(Button, { size: "large", onClick: previous, disabled: generating }, "上一步") : null,
                  h(
                    Button,
                    {
                      size: "large", className: "anw-primary-button", block: true,
                      disabled: !canContinue || generating,
                      onClick: step === 5 ? complete : requestNextGeneration,
                    },
                    step === 5
                      ? h("span", { className: "mb-outline-complete-label" }, "完成")
                      : step === 1
                        ? "下一步：生成故事背景"
                        : `下一步：生成${OUTLINE_STEPS[step]}`,
                  ),
                ),
              ),
          ) : null,
        ),
      ),
    ),
    h(
      Modal,
      {
        open: characterOpen,
        className: "anw-modal mb-character-modal",
        wrapClassName: "anw-assistant-aware-modal-wrap",
        mask: false,
        width: 520,
        title: characterIndex >= 0 ? "修改角色" : "新增角色",
        footer: null,
        onCancel: () => setCharacterOpen(false),
      },
      wrapSelectionReview(
        STUDIO_SELECTION_REVIEW_FIELD_GROUPS.outlineCharacter,
        "mb-outline-character-selection-review-host",
        h(
          "div",
          { className: "mb-form-stack" },
          h(
            "div",
            { className: "mb-form-grid mb-form-grid-three" },
            field("姓名", h(Input, { ...outlineControlProps(outlineCharacterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterName), maxLength: 10, value: characterForm.name, onChange: (event: any) => changeOutlineCharacterField("name", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterName) })),
            field("性别", h(Select, { ...outlineControlProps(outlineCharacterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterGender), allowClear: true, value: characterForm.gender || undefined, options: [{ label: "男", value: "男" }, { label: "女", value: "女" }, { label: "其他", value: "其他" }, { label: "未知", value: "未知" }], onChange: (value: string) => changeOutlineCharacterField("gender", value || "", STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterGender) })),
            field("年龄", h(Input, { ...outlineControlProps(outlineCharacterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterAge), maxLength: 5, placeholder: "如：18岁", value: characterForm.age, onChange: (event: any) => changeOutlineCharacterField("age", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterAge) })),
          ),
          field("性格", h(Input, { ...outlineControlProps(outlineCharacterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterPersonality), maxLength: 20, value: characterForm.personality, onChange: (event: any) => changeOutlineCharacterField("personality", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterPersonality) })),
          field("身份", h(Input, { ...outlineControlProps(outlineCharacterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterIdentity), maxLength: 20, value: characterForm.identity, onChange: (event: any) => changeOutlineCharacterField("identity", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterIdentity) })),
          field("人物小传", h(Input.TextArea, { ...outlineControlProps(outlineCharacterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterDescription), rows: 4, maxLength: 100, value: characterForm.description, onChange: (event: any) => changeOutlineCharacterField("description", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.outlineCharacterDescription) })),
          h(Button, { size: "large", block: true, className: "anw-primary-button", disabled: !characterForm.name.trim(), onClick: saveCharacter }, "保存修改"),
        ),
      ),
    ),
  );
}


const CHAPTER_WIZARD_STEPS = ["线索", "角色", "伏笔", "期望剧情", "章节大纲", "完成"];
const CHAPTER_STEP_TITLES = ["选择线索", "配置角色", "配置伏笔", "期望剧情", "生成章节大纲", "确认并创建"];
const STORYLINE_GROUPS: Array<{ type: StorylineType; label: string; color: string }> = [
  { type: "main", label: "主线剧情", color: "#ff7548" },
  { type: "support", label: "支线", color: "#67b866" },
  { type: "romance", label: "感情线", color: "#ffad33" },
  { type: "faction", label: "势力线", color: "#8c55c7" },
];


interface ChapterCreationWizardProps {
  novel: NovelRecord;
  open: boolean;
  volumes: VolumeRecord[];
  characters: NovelCharacterRecord[];
  storylines: StorylineRecord[];
  foreshadows: ForeshadowRecord[];
  onClose: () => void;
  onAddForeshadow: () => void;
  onCompleted: (document: DocumentRecord) => void;
  onError: (message: string) => void;
}


function ChapterCreationWizard({
  novel,
  open,
  volumes,
  characters,
  storylines,
  foreshadows,
  onClose,
  onAddForeshadow,
  onCompleted,
  onError,
}: ChapterCreationWizardProps) {
  const [draft, setDraft] = React.useState(null as ChapterCreationDraftRecord | null);
  const [creating, setCreating] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [recommending, setRecommending] = React.useState(false);
  const [recommendConfirmOpen, setRecommendConfirmOpen] = React.useState(false);
  const [recommendationOptions, setRecommendationOptions] = React.useState([] as Array<{ id: string; reason: string }>);
  const [pendingRecommendationId, setPendingRecommendationId] = React.useState("");
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [outlineTaskModelLabel, setOutlineTaskModelLabel] = React.useState("");
  const [recommendationTaskModelLabel, setRecommendationTaskModelLabel] = React.useState("");
  const [innerError, setInnerError] = React.useState("");
  const [expandedGroups, setExpandedGroups] = React.useState(["main"] as StorylineType[]);
  const [selectedStorylineIds, setSelectedStorylineIds] = React.useState([] as string[]);
  const [requiredRoleIds, setRequiredRoleIds] = React.useState([] as string[]);
  const [optionalRoleIds, setOptionalRoleIds] = React.useState([] as string[]);
  const [selectedForeshadowIds, setSelectedForeshadowIds] = React.useState([] as string[]);
  const [allowNewRole, setAllowNewRole] = React.useState(true);
  const [allowExitRole, setAllowExitRole] = React.useState(true);
  const [autoSelectForeshadows, setAutoSelectForeshadows] = React.useState(false);
  const [expectationText, setExpectationText] = React.useState("");
  const [targetCharacterCount, setTargetCharacterCount] = React.useState(2500);
  const [chapterTitle, setChapterTitle] = React.useState("");
  const [outlineText, setOutlineText] = React.useState("");
  const draftKeyRef = React.useRef("");

  const chapterDocuments = novel.tree
    .flatMap((volume: VolumeRecord) => volume.documents)
    .filter((item: DocumentRecord) => item.kind === "chapter")
    .sort((left: DocumentRecord, right: DocumentRecord) => left.position - right.position);
  const selectableForeshadows = foreshadows.filter(
    (item: ForeshadowRecord) => item.status === "active" || item.status === "planned",
  );

  const hydrateDraft = (next: ChapterCreationDraftRecord) => {
    const data = next.data || {};
    const validStorylineIds = new Set(storylines.map((item: StorylineRecord) => item.id));
    const validCharacterIds = new Set(characters.map((item: NovelCharacterRecord) => item.id));
    const validForeshadowIds = new Set(selectableForeshadows.map((item: ForeshadowRecord) => item.id));
    const storedOptional = (data.optional_role_ids || []).map(String).filter((id: string) => validCharacterIds.has(id));
    const defaultRequired = characters.filter((item: NovelCharacterRecord) => item.required_next_chapter).map((item: NovelCharacterRecord) => item.id);
    setSelectedStorylineIds((data.storyline_ids || []).map(String).filter((id: string) => validStorylineIds.has(id)));
    // Required roles are a read-only projection of the latest accepted
    // chapter intelligence.  Never resurrect a stale stored snapshot after a
    // reload or a validation-rule upgrade.
    setRequiredRoleIds(defaultRequired);
    setOptionalRoleIds(storedOptional.filter((id: string) => !defaultRequired.includes(id)));
    setSelectedForeshadowIds((data.foreshadow_ids || []).map(String).filter((id: string) => validForeshadowIds.has(id)));
    setAllowNewRole(data.allow_new_role !== false);
    setAllowExitRole(data.allow_exit_role !== false);
    setAutoSelectForeshadows(Boolean(data.auto_select_foreshadows));
    setExpectationText(next.expectation_text || "");
    setTargetCharacterCount(Math.max(2000, Math.min(5000, Number(next.target_character_count || 2500))));
    setChapterTitle(next.title || "");
    setOutlineText(next.outline_text || "");
  };

  React.useEffect(() => {
    setDraft(null);
    draftKeyRef.current = window.sessionStorage.getItem(`anw-chapter-draft:${novel.id}`) || "";
  }, [novel.id]);

  React.useEffect(() => {
    if (!open || creating || (draft && draft.state === "draft")) return;
    const create = async () => {
      setCreating(true);
      setInnerError("");
      try {
        if (!draftKeyRef.current) {
          draftKeyRef.current = `chapter-${novel.id}-${crypto.randomUUID()}`;
          window.sessionStorage.setItem(`anw-chapter-draft:${novel.id}`, draftKeyRef.current);
        }
        const targetVolume = [...volumes].sort((left: VolumeRecord, right: VolumeRecord) => right.position - left.position)[0];
        const next = await apiRequest<ChapterCreationDraftRecord>(`/novels/${novel.id}/chapter-drafts`, {
          method: "POST",
          body: JSON.stringify({ draft_key: draftKeyRef.current, volume_id: targetVolume?.id ?? null }),
        });
        setDraft(next);
        hydrateDraft(next);
        try {
          const jobs = await apiRequest<CreativeGenerationRecord[]>(
            `/creative-generations?scope_type=chapter_creation&scope_id=${encodeURIComponent(next.id)}`,
          );
          const recommendation = jobs.find(
            (job) => job.kind === "chapter_storyline_recommendation",
          );
          const outline = jobs.find((job) => job.kind === "chapter_outline");
          setRecommendationTaskModelLabel(
            recommendation ? creativeTaskModelLabel(recommendation) : "",
          );
          setOutlineTaskModelLabel(outline ? creativeTaskModelLabel(outline) : "");
        } catch {
          setRecommendationTaskModelLabel("");
          setOutlineTaskModelLabel("");
        }
      } catch (reason) {
        const message = readableError(reason, "创建章节草稿失败");
        setInnerError(message);
        onError(message);
      } finally {
        setCreating(false);
      }
    };
    void create();
  }, [open, novel.id, draft?.state]);

  const dataPatch = (overrides: Record<string, unknown> = {}) => ({
    storyline_ids: selectedStorylineIds,
    required_role_ids: requiredRoleIds,
    optional_role_ids: optionalRoleIds,
    foreshadow_ids: selectedForeshadowIds,
    allow_new_role: allowNewRole,
    allow_exit_role: allowExitRole,
    auto_select_foreshadows: autoSelectForeshadows,
    ...overrides,
  });

  const persist = async (
    base: ChapterCreationDraftRecord,
    nextStep: number,
    overrides: {
      title?: string;
      target_character_count?: number;
      expectation_text?: string;
      outline_text?: string;
      data_patch?: Record<string, unknown>;
    } = {},
  ): Promise<ChapterCreationDraftRecord> => {
    const next = await apiRequest<ChapterCreationDraftRecord>(`/chapter-drafts/${base.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_version: base.version,
        step: nextStep,
        title: overrides.title ?? chapterTitle,
        target_character_count: overrides.target_character_count ?? targetCharacterCount,
        expectation_text: overrides.expectation_text ?? expectationText,
        outline_text: overrides.outline_text ?? outlineText,
        data_patch: dataPatch(overrides.data_patch),
      }),
    });
    setDraft(next);
    return next;
  };

  const changeStep = async (nextStep: number) => {
    if (!draft || saving || generating || recommending) return;
    setSaving(true);
    setInnerError("");
    try {
      await persist(draft, nextStep);
    } catch (reason) {
      const message = readableError(reason, "保存章节步骤失败");
      setInnerError(message);
      onError(message);
    } finally {
      setSaving(false);
    }
  };

  const recommendStorylines = async () => {
    if (!draft || recommending || generating) return;
    setRecommendConfirmOpen(false);
    setRecommending(true);
    setInnerError("");
    try {
      const currentModel = await getGenerationModelStatus();
      setRecommendationTaskModelLabel(generationModelLabel(currentModel));
      const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
        method: "POST",
        body: JSON.stringify({
          scope_type: "chapter_creation",
          scope_id: draft.id,
          novel_id: novel.id,
          kind: "chapter_storyline_recommendation",
          force_new: true,
          input_snapshot: {
            novel: { title: novel.title, genre: novel.genre, subgenre: novel.subgenre, main_plot: novel.main_plot },
            chapter_number: chapterDocuments.length + 1,
            storylines: storylines.map((item: StorylineRecord) => ({ id: item.id, type: item.storyline_type, title: item.title, description: item.description, status: item.status, progress: item.progress })),
            previous_chapter: chapterDocuments.length ? { title: chapterDocuments[chapterDocuments.length - 1].title, ending: chapterDocuments[chapterDocuments.length - 1].content_markdown.slice(-1800) } : null,
          },
        }),
      });
      setRecommendationTaskModelLabel(job.state === "ready" ? completedGenerationModelLabel(job) : generationModelAuditLabel(job));
      if (job.state !== "ready") throw new Error(job.failure_message || "模型线路推荐失败");
      const allowed = new Set(storylines.map((item: StorylineRecord) => item.id));
      let ids = (job.output_json?.storyline_ids || []).map(String).filter((id: string) => allowed.has(id));
      if (!ids.length) {
        ids = storylines.filter((item: StorylineRecord) => item.status === "active" && item.storyline_type === "main").slice(0, 2).map((item: StorylineRecord) => item.id);
      }
      if (!ids.length) throw new Error("当前没有可推荐的线路，请先在线索页创建线路");
      const reason = String(job.output_json?.reason || "这条线路最适合承接上一章结尾，并推动当前章节的核心冲突。").trim();
      setRecommendationOptions(ids.slice(0, 3).map((id: string) => ({ id, reason })));
      setPendingRecommendationId("");
    } catch (reason) {
      const message = readableError(reason, "模型线路推荐失败");
      setInnerError(message);
      onError(message);
    } finally {
      setRecommending(false);
    }
  };

  const generateOutline = async () => {
    if (!draft || generating || saving) return;
    setGenerating(true);
    setConfirmOpen(false);
    setInnerError("");
    try {
      const saved = await persist(draft, 5);
      const selectedStorylines = storylines.filter((item: StorylineRecord) => selectedStorylineIds.includes(item.id));
      const requiredRoles = characters.filter((item: NovelCharacterRecord) => requiredRoleIds.includes(item.id));
      const optionalRoles = characters.filter((item: NovelCharacterRecord) => optionalRoleIds.includes(item.id));
      const selectedForeshadows = selectableForeshadows.filter((item: ForeshadowRecord) => selectedForeshadowIds.includes(item.id));
      const previous = chapterDocuments[chapterDocuments.length - 1];
      let generatedOutline = "";
      let generatedTitle = "";
      let lastFailure: unknown = new Error("模型章纲生成失败");
      const currentModel = await getGenerationModelStatus();
      setOutlineTaskModelLabel(generationModelLabel(currentModel));
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
          const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
            method: "POST",
            body: JSON.stringify({
              scope_type: "chapter_creation",
              scope_id: saved.id,
              novel_id: novel.id,
              kind: "chapter_outline",
              force_new: true,
              input_snapshot: {
                novel: {
                  title: novel.title,
                  genre: novel.genre,
                  subgenre: novel.subgenre,
                  highlight: novel.highlight,
                  background: novel.background,
                  main_plot: novel.main_plot,
                },
                chapter_number: chapterDocuments.length + 1,
                target_character_count: targetCharacterCount,
                expectation_text: expectationText,
                storylines: selectedStorylines,
                required_roles: requiredRoles,
                optional_roles: optionalRoles,
                allow_new_role: allowNewRole,
                allow_exit_role: allowExitRole,
                auto_select_foreshadows: autoSelectForeshadows,
                foreshadows: selectedForeshadows,
                available_foreshadows: autoSelectForeshadows ? selectableForeshadows : [],
                previous_chapter: previous ? { title: previous.title, ending: previous.content_markdown.slice(-3000) } : null,
                rewrite_attempt: attempt,
                rewrite_requirement: attempt > 1 ? "上次章纲未达到260—500字或内容被截断，请完整重写，不能续写残句。" : "",
              },
            }),
          });
          setOutlineTaskModelLabel(job.state === "ready" ? completedGenerationModelLabel(job) : generationModelAuditLabel(job));
          if (job.state !== "ready") {
            throw new Error(job.failure_message || "模型章纲生成失败");
          }
          const nextOutline = String(job.output_json?.outline_text || "").trim();
          const outlineCharacterCount = visibleCount(nextOutline);
          if (outlineCharacterCount < 260 || outlineCharacterCount > 500) {
            throw new Error(`第 ${attempt} 次章纲为 ${outlineCharacterCount} 字，未通过260—500字验收`);
          }
          generatedOutline = nextOutline;
          generatedTitle = String(job.output_json?.title || job.output_json?.chapter_title || `第${chapterDocuments.length + 1}章`).trim();
          break;
        } catch (reason) {
          lastFailure = reason;
        }
      }
      if (!generatedOutline) throw lastFailure;
      setChapterTitle(generatedTitle);
      setOutlineText(generatedOutline);
      const updated = await persist(saved, 5, { title: generatedTitle, outline_text: generatedOutline });
      setDraft(updated);
    } catch (reason) {
      const message = readableError(reason, "模型章纲生成失败");
      setInnerError(message);
      onError(message);
    } finally {
      setGenerating(false);
    }
  };

  const complete = async () => {
    if (!draft || saving || generating) return;
    setSaving(true);
    setInnerError("");
    try {
      const result = await apiRequest<ChapterCreationCompleteRecord>(`/chapter-drafts/${draft.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ expected_version: draft.version }),
      });
      setDraft(result.draft);
      draftKeyRef.current = "";
      window.sessionStorage.removeItem(`anw-chapter-draft:${novel.id}`);
      onClose();
      onCompleted(result.document);
    } catch (reason) {
      const message = readableError(reason, "创建章节失败");
      setInnerError(message);
      onError(message);
    } finally {
      setSaving(false);
    }
  };

  const toggleStoryline = (id: string) => setSelectedStorylineIds((current: string[]) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const toggleOptionalRole = (id: string) => setOptionalRoleIds((current: string[]) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const toggleForeshadow = (id: string) => setSelectedForeshadowIds((current: string[]) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);

  const openOutlineGenerationConfirm = async () => {
    try {
      const current = await getGenerationModelStatus();
      setOutlineTaskModelLabel(generationModelLabel(current));
      setConfirmOpen(true);
    } catch (reason) {
      const message = readableError(reason, "读取当前有效模型失败");
      setInnerError(message);
      onError(message);
    }
  };

  const openRecommendationConfirm = async () => {
    try {
      const current = await getGenerationModelStatus();
      setRecommendationTaskModelLabel(generationModelLabel(current));
      setRecommendConfirmOpen(true);
    } catch (reason) {
      const message = readableError(reason, "读取当前有效模型失败");
      setInnerError(message);
      onError(message);
    }
  };
  const step = Math.max(1, Math.min(6, draft?.step || 1));
  const requiredCharacters = characters.filter((item: NovelCharacterRecord) => requiredRoleIds.includes(item.id));
  const optionalCharacters = characters.filter((item: NovelCharacterRecord) => !requiredRoleIds.includes(item.id));
  const selectedForeshadowCount = autoSelectForeshadows ? selectableForeshadows.length : selectedForeshadowIds.length;

  const wizardSteps = h(
    React.Fragment,
    null,
    h("div", { className: "mb-chapter-step-chip" }, `${step === 6 ? "最后一步" : `第${["一", "二", "三", "四", "五"][step - 1]}步`}：${CHAPTER_STEP_TITLES[step - 1]}`),
    h(
      "div",
      { className: "mb-chapter-steps", style: { "--mb-chapter-progress": `${((step - 1) / 5) * 100}%` } as any },
      ...CHAPTER_WIZARD_STEPS.map((label, index) => {
        const number = index + 1;
        const completed = number < step;
        return h(
          "div",
          { key: label, className: `mb-chapter-step ${number === step ? "is-active" : ""} ${completed ? "is-complete" : ""}` },
          h("span", { className: "mb-chapter-step-dot" }, completed ? h(CheckOutlined) : number),
          h("span", { className: "mb-chapter-step-label" }, label),
        );
      }),
    ),
  );

  const selectionMark = (selected: boolean) => h("span", { className: `mb-chapter-selection ${selected ? "is-selected" : ""}` }, selected ? h(CheckOutlined) : null);

  const renderStepOne = () => h(
    "div",
    { className: "mb-chapter-step-body is-storyline" },
    h("h3", null, "选择线索"),
    h("p", null, "选择本章要推进的线索（可同时推进多条）"),
    h("div", { className: "mb-chapter-tip" }, h(BulbOutlined), h("span", null, "务必推动合适线路发展，只选择主线可能会遇到剧情停滞，建议根据剧情需要选择支线、感情线或势力线")),
    h(Button, { className: "anw-primary-button mb-chapter-ai-button", icon: h(UnorderedListOutlined), loading: recommending, onClick: () => void openRecommendationConfirm() }, "AI智能推荐线路"),
    h("p", { className: "mb-chapter-ai-caption" }, "若您不知道如何选择正确线路，可以使用AI智能推荐线路，帮您自动选择合适线路"),
    h(
      "div",
      { className: "mb-chapter-line-groups" },
      ...STORYLINE_GROUPS.map((group) => {
        const items = storylines.filter((item: StorylineRecord) => item.storyline_type === group.type);
        const expanded = expandedGroups.includes(group.type);
        return h(
          "section",
          { key: group.type, className: `mb-chapter-line-group ${expanded ? "is-expanded" : ""}` },
          h("button", { type: "button", className: "mb-chapter-group-toggle", onClick: () => setExpandedGroups((current: StorylineType[]) => current.includes(group.type) ? current.filter((item) => item !== group.type) : [...current, group.type]) },
            h("span", { className: "mb-chapter-group-name" }, h("i", { style: { background: group.color } }), h("strong", null, group.label), h("small", null, `${items.length} 条`)),
            h(expanded ? CaretDownOutlined : CaretRightOutlined),
          ),
          expanded ? h("div", { className: "mb-chapter-group-items" }, items.length ? items.map((item: StorylineRecord) => {
            const selected = selectedStorylineIds.includes(item.id);
            return h("button", { key: item.id, type: "button", className: `mb-chapter-choice-card ${selected ? "is-selected" : ""}`, onClick: () => toggleStoryline(item.id) },
              h("span", { className: "mb-chapter-choice-copy" }, h("strong", null, item.title), h("span", null, item.description || "尚未填写线路说明"), h("small", null, `${item.storyline_type === "main" ? "主线剧情" : group.label} · 当前进度 ${item.progress}%`)),
              selectionMark(selected),
            );
          }) : h("div", { className: "mb-chapter-group-empty" }, `暂无${group.label}`)) : null,
        );
      }),
    ),
    h("button", { type: "button", className: "mb-chapter-direct-link", disabled: saving, onClick: () => void changeStep(4) }, "我已有正文，点击直接填写"),
    h(Button, { size: "large", block: true, className: "anw-primary-button mb-chapter-next", disabled: !selectedStorylineIds.length, loading: saving, onClick: () => void changeStep(2) }, "下一步：配置角色"),
  );

  const roleCard = (item: NovelCharacterRecord, selected: boolean, required: boolean) => h(
    "button",
    { key: item.id, type: "button", className: `mb-chapter-choice-card is-role ${selected ? "is-selected" : ""}`, onClick: required ? undefined : () => toggleOptionalRole(item.id) },
    h("span", { className: "mb-chapter-choice-copy" },
      h("span", { className: "mb-chapter-role-title" }, h("strong", null, item.name), required ? h("em", null, "必选") : null, h("em", null, item.role_type === "main" ? "主角" : "配角")),
      h("span", null, String(item.details?.identity || item.description || "尚未填写角色身份")),
      item.details?.status ? h("small", null, `现状：${String(item.details.status)}`) : null,
    ),
    selectionMark(selected),
  );

  const renderStepTwo = () => h(
    "div",
    { className: "mb-chapter-step-body is-roles" },
    h("h3", null, "配置章节角色"),
    h("p", null, "AI将根据角色配置生成更连贯的章节内容"),
    requiredCharacters.length ? h(React.Fragment, null,
      h("div", { className: "mb-chapter-section-heading" }, h("strong", null, "必选角色"), h("span", null, `${requiredCharacters.length} 人`)),
      h("div", { className: "mb-chapter-soft-tip" }, "以下角色根据上一章的【下一章必现角色】自动添加"),
      h("div", { className: "mb-chapter-choice-list" }, requiredCharacters.map((item: NovelCharacterRecord) => roleCard(item, true, true))),
    ) : null,
    h("div", { className: "mb-chapter-section-heading" }, h("strong", null, "可选角色"), h("span", null, `已选 ${requiredRoleIds.length + optionalRoleIds.length} 人`)),
    h("div", { className: "mb-chapter-choice-list" }, optionalCharacters.length ? optionalCharacters.map((item: NovelCharacterRecord) => roleCard(item, optionalRoleIds.includes(item.id), false)) : h("div", { className: "mb-chapter-inline-empty" }, "暂无其他角色")),
    h("div", { className: "mb-chapter-section-heading" }, h("strong", null, "AI自动操作")),
    h("div", { className: "mb-chapter-ai-options" },
      h("label", null, h(Checkbox, { checked: allowNewRole, onChange: (event: any) => setAllowNewRole(event.target.checked) }), h("span", null, h("strong", null, "允许AI新增角色"), h("small", null, "AI可能会根据情节需要引入新角色"))),
      h("label", null, h(Checkbox, { checked: allowExitRole, onChange: (event: any) => setAllowExitRole(event.target.checked) }), h("span", null, h("strong", null, "允许AI退场角色"), h("small", null, "AI可能会让某些角色在本章退场"))),
    ),
    h(Button, { size: "large", block: true, className: "anw-primary-button mb-chapter-next", loading: saving, onClick: () => void changeStep(3) }, "下一步：配置伏笔"),
  );

  const renderStepThree = () => h(
    "div",
    { className: "mb-chapter-step-body is-foreshadow" },
    h("div", { className: "mb-chapter-title-row" }, h("span"), h("div", null, h("h3", null, "配置章节伏笔"), h("p", null, "选择需要在本章推进或解决的伏笔")), h(Button, { className: "anw-primary-button", icon: h(PlusOutlined), onClick: onAddForeshadow }, "添加伏笔")),
    selectableForeshadows.length
      ? h(
          React.Fragment,
          null,
          h("label", { className: "mb-chapter-auto-card" }, h(Checkbox, { checked: autoSelectForeshadows, onChange: (event: any) => setAutoSelectForeshadows(event.target.checked) }), h("span", null, h("strong", null, "让AI自动选择伏笔"), h("small", null, "AI将根据章节内容自动决定推进哪些伏笔"))),
          h("div", { className: "mb-chapter-choice-list" }, ...selectableForeshadows.map((item: ForeshadowRecord) => {
            const selected = selectedForeshadowIds.includes(item.id);
            return h("button", { key: item.id, type: "button", disabled: autoSelectForeshadows, className: `mb-chapter-choice-card is-foreshadow ${selected ? "is-selected" : ""}`, onClick: () => toggleForeshadow(item.id) },
              h("span", { className: "mb-chapter-choice-copy" }, h("span", { className: "mb-chapter-foreshadow-title" }, h("strong", null, item.title), h("em", null, item.status === "resolved" ? "已解决" : item.status === "planned" ? "待埋设" : "进行中")), h("span", null, item.content || "尚未填写伏笔内容"), h("small", null, `最新进展：${item.latest_progress || "暂无进展"}`)),
              selectionMark(selected),
            );
          })),
        )
      : h("div", { className: "mb-chapter-foreshadow-empty" }, h("span", null, "暂无伏笔"), h("small", null, "不用担心伏笔遗漏问题，可以跳过此步骤")),
    h("div", { className: "mb-chapter-dual-actions" },
      h(Button, { size: "large", disabled: saving, onClick: () => void changeStep(2) }, "返回"),
      h(Button, { size: "large", className: "anw-primary-button", loading: saving, onClick: () => void changeStep(4) }, "下一步"),
    ),
  );

  const renderStepFour = () => h(
    "div",
    { className: "mb-chapter-step-body is-expectation" },
    h("h3", null, "期望剧情走向"),
    h("p", null, "描述您对本章节的剧情走向的期望"),
    h("div", { className: "mb-chapter-section-heading" }, h("strong", null, "期望剧情走向（可选）")),
    h(Input.TextArea, { rows: 7, maxLength: 5000, value: expectationText, placeholder: "输入您对本章节的剧情走向的设计，如：本章主要推进主角与配角的合作关系、揭开某个谜团的真相、引发新的冲突等...", onChange: (event: any) => setExpectationText(event.target.value) }),
    h("div", { className: "mb-chapter-textarea-hint" }, h("span", null, h(BulbOutlined), " 您可以描述希望发生的剧情、角色的目标或面临的挑战，AI会根据您的描述生成更符合预期的章节内容"), h("small", null, `最多5000字，当前：${visibleCount(expectationText)}/5000`)),
    h(Button, { size: "large", block: true, className: "anw-primary-button mb-chapter-next", loading: saving, onClick: () => void changeStep(5) }, "下一步：生成章节大纲"),
    h("button", { type: "button", className: "mb-chapter-back-link", disabled: saving, onClick: () => void changeStep(3) }, "返回上一步"),
  );

  const renderStepFive = () => {
    if (generating) return h(
      "div",
      { className: "mb-chapter-step-body is-generating" },
      h("div", { className: "mb-chapter-target-block" }, h("strong", null, "目标字数"), h(InputNumber, { min: 2000, max: 5000, controls: false, value: targetCharacterCount, onChange: (value: number | null) => setTargetCharacterCount(Math.max(2000, Math.min(5000, Number(value || 2500)))) })),
      h(Spin, { size: "large" }),
      h("h3", null, `${outlineTaskModelLabel || "当前任务模型"} 正在创作章节大纲...`),
      h("p", null, "正在分析角色和伏笔配置"),
      h(Progress, { percent: 42, showInfo: false, strokeColor: "#ff7548", trailColor: "#fde8df" }),
      h("small", null, "预计需要 8-15 秒"),
    );
    if (outlineText) return h(
      "div",
      { className: "mb-chapter-step-body is-outline-result" },
      h("div", { className: "mb-chapter-target-block" }, h("strong", null, "目标字数"), h(InputNumber, { min: 2000, max: 5000, controls: false, value: targetCharacterCount, onChange: (value: number | null) => setTargetCharacterCount(Math.max(2000, Math.min(5000, Number(value || 2500)))) }), h("small", null, h(BulbOutlined), " AI生成字数会有±500-1500字的浮动，请合理设置目标字数"), h("small", null, "字数限制：2000-5000字")),
      h("div", { className: "mb-chapter-result-heading" }, h("h3", null, "章节大纲已生成"), h("p", null, outlineTaskModelLabel ? `任务模型：${outlineTaskModelLabel}` : "请查看并确认生成的章节大纲")),
      field("章节标题", h(Input, { maxLength: 20, value: chapterTitle, onChange: (event: any) => setChapterTitle(event.target.value) }), `最多20字，当前：${visibleCount(chapterTitle)}/20`),
      field("章节大纲", h(Input.TextArea, { rows: 10, maxLength: 5000, value: outlineText, onChange: (event: any) => setOutlineText(event.target.value) }), `最多5000字，当前：${visibleCount(outlineText)}/5000`),
      h("div", { className: "mb-chapter-summary-card" }, h("strong", null, "角色配置摘要"), h("p", null, `实际选择：${requiredRoleIds.length + optionalRoleIds.length} 人`), h("p", null, `${allowNewRole ? "允许AI新增角色" : "不允许AI新增角色"}，${allowExitRole ? "允许AI退场角色" : "不允许AI退场角色"}`)),
      h("div", { className: "mb-chapter-summary-card" }, h("strong", null, "伏笔配置摘要"), h("p", null, autoSelectForeshadows ? "由AI自动选择伏笔" : `手动选择 ${selectedForeshadowCount} 个伏笔`)),
      h("div", { className: "mb-chapter-triple-actions" },
        h(Button, { size: "large", disabled: saving, onClick: () => void changeStep(4) }, "返回修改"),
        h(Button, { size: "large", className: "anw-primary-button", disabled: !chapterTitle.trim() || !outlineText.trim(), loading: saving, onClick: () => void changeStep(6) }, "下一步"),
        h(Button, { size: "large", onClick: () => void openOutlineGenerationConfirm() }, "重新生成"),
      ),
    );
    return h(
      "div",
      { className: "mb-chapter-step-body is-target" },
      h("div", { className: "mb-chapter-target-block" }, h("strong", null, "目标字数"), h(InputNumber, { min: 2000, max: 5000, controls: false, value: targetCharacterCount, onChange: (value: number | null) => setTargetCharacterCount(Math.max(2000, Math.min(5000, Number(value || 2500)))) }), h("small", null, h(BulbOutlined), " AI生成字数会有±500-1500字的浮动，请合理设置目标字数"), h("small", null, "字数限制：2000-5000字")),
      h(Button, { size: "large", block: true, className: "anw-primary-button mb-chapter-next", onClick: () => void openOutlineGenerationConfirm() }, "生成章节大纲"),
    );
  };

  const renderStepSix = () => h(
    "div",
    { className: "mb-chapter-step-body is-complete" },
    h("div", { className: "mb-chapter-result-heading" }, h("h3", null, "确认章节信息"), h("p", null, "请确认以下信息无误后创建章节")),
    h("article", { className: "mb-chapter-final-card" },
      h("dl", null,
        h("div", null, h("dt", null, "章节标题"), h("dd", null, chapterTitle)),
        h("div", null, h("dt", null, "目标字数"), h("dd", null, `${targetCharacterCount} 字`)),
        h("div", null, h("dt", null, "角色配置"), h("dd", null, `已选 ${requiredRoleIds.length + optionalRoleIds.length} 人，${allowNewRole ? "允许AI新增" : "不允许AI新增"}，${allowExitRole ? "允许AI退场" : "不允许AI退场"}`)),
        h("div", null, h("dt", null, "伏笔配置"), h("dd", null, autoSelectForeshadows ? "由AI自动选择伏笔" : `已选 ${selectedForeshadowCount} 个伏笔`)),
        h("div", null, h("dt", null, "章节大纲"), h("dd", { className: "is-outline" }, outlineText)),
      ),
    ),
    h(Button, { size: "large", block: true, className: "anw-primary-button mb-chapter-next", loading: saving, onClick: () => void complete() }, "确认创建章节"),
    h("button", { type: "button", className: "mb-chapter-back-link", disabled: saving, onClick: () => void changeStep(5) }, "返回修改"),
  );

  const stepBody = step === 1 ? renderStepOne() : step === 2 ? renderStepTwo() : step === 3 ? renderStepThree() : step === 4 ? renderStepFour() : step === 5 ? renderStepFive() : renderStepSix();

  return h(
    React.Fragment,
    null,
    h(
      Modal,
      {
        open,
        centered: true,
        width: 570,
        footer: null,
        maskClosable: false,
        className: "anw-modal mb-chapter-wizard-modal",
        title: "创建新章节",
        onCancel: saving || generating || recommending ? undefined : onClose,
      },
      creating || !draft ? h("div", { className: "mb-chapter-loading" }, h(Spin, { size: "large" }), h("span", null, "正在准备章节创作流程...")) : h(
        "div",
        { className: "mb-chapter-wizard" },
        innerError ? h(Alert, { type: "error", showIcon: true, closable: true, message: innerError, onClose: () => setInnerError("") }) : null,
        wizardSteps,
        stepBody,
      ),
    ),
    h(
      Modal,
      {
        open: confirmOpen,
        centered: true,
        width: 390,
        footer: null,
        className: "anw-modal mb-chapter-confirm-modal",
        title: "确认",
        onCancel: () => setConfirmOpen(false),
      },
      h("p", null, `生成章节将使用 ${outlineTaskModelLabel || "当前有效模型"} 并消耗500字数，确定继续吗？`),
      h("div", { className: "mb-chapter-confirm-actions" },
        h(Button, { size: "large", onClick: () => setConfirmOpen(false) }, "取消"),
        h(Button, { size: "large", className: "anw-primary-button", onClick: () => void generateOutline() }, "确定"),
      ),
    ),
    h(
      Modal,
      {
        open: recommendConfirmOpen,
        centered: true,
        width: 430,
        footer: null,
        className: "anw-modal mb-chapter-confirm-modal",
        title: "AI智能推荐线路",
        onCancel: () => setRecommendConfirmOpen(false),
      },
      h("p", null, `使用 ${recommendationTaskModelLabel || "当前有效模型"} 推荐线路将消耗 500 字。AI将分析前文内容和所有线路，为您推荐最适合本章推进的线路。是否继续？`),
      h("div", { className: "mb-chapter-confirm-actions" },
        h(Button, { size: "large", onClick: () => setRecommendConfirmOpen(false) }, "取消"),
        h(Button, { size: "large", className: "anw-primary-button", onClick: () => void recommendStorylines() }, "确定消耗 500 字"),
      ),
    ),
    h(
      Modal,
      {
        open: recommending,
        centered: true,
        width: 460,
        footer: null,
        closable: false,
        maskClosable: false,
        className: "anw-modal mb-chapter-recommend-loading",
      },
      h(Spin, { size: "large" }),
      h("h3", null, `${recommendationTaskModelLabel || "当前任务模型"} 正在分析推荐...`),
      h("p", null, "正在分析前文内容和所有线路发展情况"),
      h("strong", null, "⚠️ 重要提示"),
      h("p", null, "请勿关闭页面 · 请勿切换屏幕 · 请勿让设备息屏"),
      h("small", null, "预计需要 30-60 秒"),
    ),
    h(
      Modal,
      {
        open: recommendationOptions.length > 0 && !recommending,
        centered: true,
        width: 520,
        footer: null,
        className: "anw-modal mb-chapter-recommend-results",
        title: "AI为您推荐以下线路",
        onCancel: () => { setRecommendationOptions([]); setPendingRecommendationId(""); },
      },
      h("p", null, recommendationTaskModelLabel ? `任务模型：${recommendationTaskModelLabel}` : "请选择其中一个线路继续"),
      h("div", { className: "mb-chapter-choice-list" }, ...recommendationOptions.map((option: { id: string; reason: string }, index: number) => {
        const item = storylines.find((storyline: StorylineRecord) => storyline.id === option.id);
        if (!item) return null;
        const selected = pendingRecommendationId === option.id;
        const group = STORYLINE_GROUPS.find((candidate) => candidate.type === item.storyline_type);
        return h("button", { key: option.id, type: "button", className: `mb-chapter-choice-card ${selected ? "is-selected" : ""}`, onClick: () => setPendingRecommendationId(option.id) },
          h("span", { className: "mb-chapter-choice-copy" },
            h("strong", null, `选项 ${index + 1}：${item.title}`),
            h("small", null, item.storyline_type === "main" ? "主线" : group?.label || "支线"),
            h("span", null, option.reason || item.description),
          ),
          selectionMark(selected),
        );
      })),
      h("div", { className: "mb-chapter-confirm-actions" },
        h(Button, { size: "large", onClick: () => { setRecommendationOptions([]); setPendingRecommendationId(""); } }, "取消"),
        h(Button, { size: "large", className: "anw-primary-button", disabled: !pendingRecommendationId, onClick: () => {
          const selected = storylines.find((item: StorylineRecord) => item.id === pendingRecommendationId);
          if (!selected) return;
          setSelectedStorylineIds([selected.id]);
          setExpandedGroups([selected.storyline_type]);
          setRecommendationOptions([]);
          setPendingRecommendationId("");
          Modal.success({ className: "anw-modal", content: `✅ 已为您选择「${selected.title}」线路`, okText: "确定" });
        } }, "确认选择"),
      ),
    ),
  );
}


interface StudioProps {
  novel: NovelRecord;
  section: WorkbenchSection;
  onSectionChange: (section: WorkbenchSection) => void;
  onSelectDocument: (documentId: string) => void;
  onNovelChanged: (novel: NovelRecord) => void;
  onReload: () => Promise<NovelRecord | null>;
  onBack: () => void;
  onError: (message: string) => void;
  openChapterWizardSignal?: number;
  assistantWorkspaceLayout?: AssistantWorkspaceLayout;
  selectionEditReviewHost?: SelectionEditReviewHostComponent;
}


export function StudioProjectView({
  novel,
  section,
  onSectionChange,
  onSelectDocument,
  onNovelChanged,
  onReload,
  onBack,
  onError,
  openChapterWizardSignal = 0,
  assistantWorkspaceLayout,
  selectionEditReviewHost: SelectionEditReviewHost,
}: StudioProps) {
  const [busy, setBusy] = React.useState(false);
  const [generationModelStatus, setGenerationModelStatus] = React.useState(null as GenerationModelStatus | null);
  const [generationModelStatusError, setGenerationModelStatusError] = React.useState(false);
  const [characters, setCharacters] = React.useState([] as NovelCharacterRecord[]);
  const [relationships, setRelationships] = React.useState([] as CharacterRelationshipRecord[]);
  const [storylines, setStorylines] = React.useState([] as StorylineRecord[]);
  const [foreshadows, setForeshadows] = React.useState([] as ForeshadowRecord[]);
  const [roleTab, setRoleTab] = React.useState(
    (new URLSearchParams(window.location.search).get("role_view") === "graph" ? "graph" : "list") as "list" | "graph",
  );
  const [clueTab, setClueTab] = React.useState("main" as StorylineType);
  const [settingsTab, setSettingsTab] = React.useState("template" as "template" | "foreshadow");
  const [expandedVolumes, setExpandedVolumes] = React.useState([] as string[]);
  const [volumeDescending, setVolumeDescending] = React.useState(true);
  const [outlineOpen, setOutlineOpen] = React.useState(false);
  const [outlineStep, setOutlineStep] = React.useState(0);
  const [chapterWizardOpen, setChapterWizardOpen] = React.useState(false);
  const [volumeOpen, setVolumeOpen] = React.useState(false);
  const [volumeEditing, setVolumeEditing] = React.useState(null as VolumeRecord | null);
  const [volumeTitle, setVolumeTitle] = React.useState("");
  const [characterOpen, setCharacterOpen] = React.useState(false);
  const [characterEditing, setCharacterEditing] = React.useState(null as NovelCharacterRecord | null);
  const [characterForm, setCharacterForm] = React.useState({ role_type: "main" as "main" | "supporting", name: "", gender: "", age: "", identity: "", personality: "", description: "" });
  const [relationshipOpen, setRelationshipOpen] = React.useState(false);
  const [relationshipFocusCharacterId, setRelationshipFocusCharacterId] = React.useState(null as string | null);
  const [relationshipFocusId, setRelationshipFocusId] = React.useState(null as string | null);
  const [relationshipStartWithNew, setRelationshipStartWithNew] = React.useState(false);
  const [storylineOpen, setStorylineOpen] = React.useState(false);
  const [storylineEditing, setStorylineEditing] = React.useState(null as StorylineRecord | null);
  const [storylineForm, setStorylineForm] = React.useState({ storyline_type: "main" as StorylineType, title: "", description: "", status: "active", progress: 0 });
  const [foreshadowOpen, setForeshadowOpen] = React.useState(false);
  const [foreshadowEditing, setForeshadowEditing] = React.useState(null as ForeshadowRecord | null);
  const [foreshadowForm, setForeshadowForm] = React.useState({ title: "", content: "", latest_progress: "", status: "planned", progress: 0 });
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [settingsForm, setSettingsForm] = React.useState({ genre: "", subgenre: "", idea: "", template_name: "", template_data: {} as Record<string, string> });
  const [coverOpen, setCoverOpen] = React.useState(false);
  const [coverMode, setCoverMode] = React.useState("ai" as "ai" | "system" | "upload");
  const [coverImageData, setCoverImageData] = React.useState("");
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [searchResults, setSearchResults] = React.useState([] as NovelSearchResultRecord[]);
  const [searching, setSearching] = React.useState(false);

  const characterFormRef = React.useRef(characterForm) as StudioMutableRef<typeof characterForm>;
  const storylineFormRef = React.useRef(storylineForm) as StudioMutableRef<typeof storylineForm>;
  const foreshadowFormRef = React.useRef(foreshadowForm) as StudioMutableRef<typeof foreshadowForm>;
  const settingsFormRef = React.useRef(settingsForm) as StudioMutableRef<typeof settingsForm>;
  characterFormRef.current = characterForm;
  storylineFormRef.current = storylineForm;
  foreshadowFormRef.current = foreshadowForm;
  settingsFormRef.current = settingsForm;

  const characterDirtyFieldsRef = React.useRef(new Set<string>()) as StudioMutableRef<Set<string>>;
  const storylineDirtyFieldsRef = React.useRef(new Set<string>()) as StudioMutableRef<Set<string>>;
  const foreshadowDirtyFieldsRef = React.useRef(new Set<string>()) as StudioMutableRef<Set<string>>;
  const settingsDirtyFieldsRef = React.useRef(new Set<string>()) as StudioMutableRef<Set<string>>;
  const characterAssistantScopeRef = React.useRef(null as AssistantContextScopeHandle | null) as StudioMutableRef<AssistantContextScopeHandle | null>;
  const storylineAssistantScopeRef = React.useRef(null as AssistantContextScopeHandle | null) as StudioMutableRef<AssistantContextScopeHandle | null>;
  const foreshadowAssistantScopeRef = React.useRef(null as AssistantContextScopeHandle | null) as StudioMutableRef<AssistantContextScopeHandle | null>;
  const settingsAssistantScopeRef = React.useRef(null as AssistantContextScopeHandle | null) as StudioMutableRef<AssistantContextScopeHandle | null>;
  const assistantControlRefs = React.useRef(new Map<string, StudioFocusableControl>()) as StudioMutableRef<Map<string, StudioFocusableControl>>;

  const wrapSelectionReview = (
    fieldIds: readonly string[],
    className: string,
    child: unknown,
  ): unknown => SelectionEditReviewHost
    ? h(SelectionEditReviewHost, { fieldIds, className }, child)
    : child;

  const focusAssistantControl = (fieldId: string): void => {
    assistantControlRefs.current.get(fieldId)?.focus?.();
  };
  const assistantControlProps = (
    scopeRef: StudioMutableRef<AssistantContextScopeHandle | null>,
    fieldId: string,
  ) => ({
    ref: (control: StudioFocusableControl | null) => {
      if (control) assistantControlRefs.current.set(fieldId, control);
      else assistantControlRefs.current.delete(fieldId);
    },
    onFocus: () => scopeRef.current?.setFocusedField(fieldId),
    onBlur: () => scopeRef.current?.setFocusedField(undefined),
  });
  const markAssistantFieldDirty = (
    dirtyFieldsRef: StudioMutableRef<Set<string>>,
    scopeRef: StudioMutableRef<AssistantContextScopeHandle | null>,
    fieldId: string,
  ): void => {
    dirtyFieldsRef.current.add(fieldId);
    scopeRef.current?.notifyFieldChanged(fieldId);
  };
  const setCharacterFieldValue = <Key extends keyof typeof characterForm>(
    key: Key,
    value: (typeof characterForm)[Key],
  ): void => setStudioControlledField(characterFormRef, setCharacterForm, key, value);
  const changeCharacterFieldValue = <Key extends keyof typeof characterForm>(
    key: Key,
    value: (typeof characterForm)[Key],
    fieldId: string,
  ): void => {
    setCharacterFieldValue(key, value);
    markAssistantFieldDirty(
      characterDirtyFieldsRef,
      characterAssistantScopeRef,
      fieldId,
    );
  };
  const setStorylineFieldValue = <Key extends keyof typeof storylineForm>(
    key: Key,
    value: (typeof storylineForm)[Key],
  ): void => setStudioControlledField(storylineFormRef, setStorylineForm, key, value);
  const changeStorylineFieldValue = <Key extends keyof typeof storylineForm>(
    key: Key,
    value: (typeof storylineForm)[Key],
    fieldId: string,
  ): void => {
    setStorylineFieldValue(key, value);
    markAssistantFieldDirty(
      storylineDirtyFieldsRef,
      storylineAssistantScopeRef,
      fieldId,
    );
  };
  const setForeshadowFieldValue = <Key extends keyof typeof foreshadowForm>(
    key: Key,
    value: (typeof foreshadowForm)[Key],
  ): void => setStudioControlledField(foreshadowFormRef, setForeshadowForm, key, value);
  const changeForeshadowFieldValue = <Key extends keyof typeof foreshadowForm>(
    key: Key,
    value: (typeof foreshadowForm)[Key],
    fieldId: string,
  ): void => {
    setForeshadowFieldValue(key, value);
    markAssistantFieldDirty(
      foreshadowDirtyFieldsRef,
      foreshadowAssistantScopeRef,
      fieldId,
    );
  };
  const setSettingsFieldValue = <Key extends keyof typeof settingsForm>(
    key: Key,
    value: (typeof settingsForm)[Key],
  ): void => setStudioControlledField(settingsFormRef, setSettingsForm, key, value);
  const changeSettingsFieldValue = <Key extends Exclude<keyof typeof settingsForm, "template_data">>(
    key: Key,
    value: (typeof settingsForm)[Key],
    fieldId: string,
  ): void => {
    setSettingsFieldValue(key, value);
    markAssistantFieldDirty(
      settingsDirtyFieldsRef,
      settingsAssistantScopeRef,
      fieldId,
    );
  };
  const setSettingsTemplateValue = (key: string, value: string): void => {
    setSettingsFieldValue("template_data", {
      ...settingsFormRef.current.template_data,
      [key]: value,
    });
  };
  const changeSettingsTemplateValue = (key: string, value: string): void => {
    const fieldId = settingsTemplateFieldId(key);
    setSettingsTemplateValue(key, value);
    markAssistantFieldDirty(
      settingsDirtyFieldsRef,
      settingsAssistantScopeRef,
      fieldId,
    );
  };
  const controlledAssistantBinding = (
    scopeRef: StudioMutableRef<AssistantContextScopeHandle | null>,
    dirtyFieldsRef: StudioMutableRef<Set<string>>,
    id: string,
    label: string,
    getValue: () => string,
    applyDraftValue: (nextValue: string) => void,
  ): StudioAssistantFieldBinding => ({
    id,
    label,
    getValue,
    getDirty: () => dirtyFieldsRef.current.has(id),
    applyDraftValue,
    markDirty: () => { dirtyFieldsRef.current.add(id); },
    getSelection: () => readAssistantTextSelection(
      studioTextControl(assistantControlRefs.current.get(id)),
      getValue(),
    ),
    restoreSelection: (range) => restoreAssistantTextSelection(
      studioTextControl(assistantControlRefs.current.get(id)),
      range,
    ),
    focus: () => focusAssistantControl(id),
  });

  React.useEffect(() => {
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
  }, [novel.id]);

  React.useEffect(() => {
    // No outline/settings editor modal view exists in the frozen V2 enum.
    // While either unsupported editor is open, publish no misleading
    // background-page draft context; closing it remounts the page scope.
    if (outlineOpen || settingsOpen) return;
    const envelope = studioAssistantPageEnvelope(novel, section, roleTab);
    if (!envelope) return;
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:page:${novel.id}:${envelope.page.view}`,
        kind: "page",
        envelope,
      },
    );
    return () => mounted.dispose();
  }, [novel.id, novel.title, outlineOpen, roleTab, section, settingsOpen]);

  React.useEffect(() => {
    if (!characterOpen || section !== "roles" || roleTab !== "list") return;
    const background = studioAssistantPageEnvelope(novel, "roles", "list");
    if (!background) return;
    const ids = STUDIO_ASSISTANT_FIELD_IDS;
    const bindings: StudioAssistantFieldBinding[] = [
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterRoleType,
        "角色类型",
        () => characterFormRef.current.role_type,
        (value) => setCharacterFieldValue(
          "role_type",
          requireStudioChoice(value, ["main", "supporting"] as const, "角色类型"),
        ),
      ),
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterName,
        "角色姓名",
        () => characterFormRef.current.name,
        (value) => setCharacterFieldValue("name", value),
      ),
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterGender,
        "性别",
        () => characterFormRef.current.gender,
        (value) => setCharacterFieldValue(
          "gender",
          requireStudioChoice(value, ["", "男", "女", "其他", "未知"] as const, "性别"),
        ),
      ),
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterAge,
        "年龄",
        () => characterFormRef.current.age,
        (value) => setCharacterFieldValue("age", value),
      ),
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterIdentity,
        "身份",
        () => characterFormRef.current.identity,
        (value) => setCharacterFieldValue("identity", value),
      ),
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterPersonality,
        "性格",
        () => characterFormRef.current.personality,
        (value) => setCharacterFieldValue("personality", value),
      ),
      controlledAssistantBinding(
        characterAssistantScopeRef,
        characterDirtyFieldsRef,
        ids.characterDescription,
        "人物小传",
        () => characterFormRef.current.description,
        (value) => setCharacterFieldValue("description", value),
      ),
    ];
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:modal:character:${novel.id}:${characterEditing?.id ?? "new"}`,
        kind: "modal",
        persistenceBaseline: characterEditing
          ? { kind: "entity", version: characterEditing.version }
          : { kind: "none", version: null },
        envelope: {
          ...background,
          page: { ...background.page, modal: "character-editor" },
          entity: {
            type: "character",
            ...(characterEditing?.id ? { id: characterEditing.id } : {}),
            title: characterEditing?.name || "新增角色",
          },
        },
      },
      bindings,
    );
    characterAssistantScopeRef.current = mounted.handle;
    return () => {
      if (characterAssistantScopeRef.current === mounted.handle) {
        characterAssistantScopeRef.current = null;
      }
      mounted.dispose();
    };
  }, [characterEditing?.id, characterOpen, novel.id, novel.title, roleTab, section]);

  React.useEffect(() => {
    if (!storylineOpen || section !== "clues") return;
    const background = studioAssistantPageEnvelope(novel, "clues");
    if (!background) return;
    const ids = STUDIO_ASSISTANT_FIELD_IDS;
    const bindings: StudioAssistantFieldBinding[] = [
      controlledAssistantBinding(
        storylineAssistantScopeRef,
        storylineDirtyFieldsRef,
        ids.storylineType,
        "故事线类型",
        () => storylineFormRef.current.storyline_type,
        (value) => setStorylineFieldValue(
          "storyline_type",
          requireStudioChoice(
            value,
            ["main", "support", "romance", "faction"] as const,
            "故事线类型",
          ),
        ),
      ),
      controlledAssistantBinding(
        storylineAssistantScopeRef,
        storylineDirtyFieldsRef,
        ids.storylineTitle,
        "故事线名称",
        () => storylineFormRef.current.title,
        (value) => setStorylineFieldValue("title", value),
      ),
      controlledAssistantBinding(
        storylineAssistantScopeRef,
        storylineDirtyFieldsRef,
        ids.storylineDescription,
        "情节说明",
        () => storylineFormRef.current.description,
        (value) => setStorylineFieldValue("description", value),
      ),
    ];
    if (storylineEditing) {
      bindings.push(
        controlledAssistantBinding(
          storylineAssistantScopeRef,
          storylineDirtyFieldsRef,
          ids.storylineStatus,
          "故事线状态",
          () => storylineFormRef.current.status,
          (value) => setStorylineFieldValue(
            "status",
            requireStudioChoice(
              value,
              ["active", "paused", "completed", "archived"] as const,
              "故事线状态",
            ),
          ),
        ),
        controlledAssistantBinding(
          storylineAssistantScopeRef,
          storylineDirtyFieldsRef,
          ids.storylineProgress,
          "故事线进度",
          () => String(storylineFormRef.current.progress),
          (value) => setStorylineFieldValue("progress", requireStudioPercentage(value)),
        ),
      );
    }
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:modal:storyline:${novel.id}:${storylineEditing?.id ?? "new"}`,
        kind: "modal",
        persistenceBaseline: storylineEditing
          ? { kind: "entity", version: storylineEditing.version }
          : { kind: "none", version: null },
        envelope: {
          ...background,
          page: { ...background.page, modal: "storyline-editor" },
          entity: {
            type: "storyline",
            ...(storylineEditing?.id ? { id: storylineEditing.id } : {}),
            title: storylineEditing?.title || "新增故事线",
          },
        },
      },
      bindings,
    );
    storylineAssistantScopeRef.current = mounted.handle;
    return () => {
      if (storylineAssistantScopeRef.current === mounted.handle) {
        storylineAssistantScopeRef.current = null;
      }
      mounted.dispose();
    };
  }, [novel.id, novel.title, section, storylineEditing?.id, storylineOpen]);

  React.useEffect(() => {
    if (!foreshadowOpen || section !== "settings" || settingsTab !== "foreshadow") return;
    const background = studioAssistantPageEnvelope(novel, "settings");
    if (!background) return;
    const ids = STUDIO_ASSISTANT_FIELD_IDS;
    const bindings: StudioAssistantFieldBinding[] = [
      controlledAssistantBinding(
        foreshadowAssistantScopeRef,
        foreshadowDirtyFieldsRef,
        ids.foreshadowTitle,
        "伏笔名称",
        () => foreshadowFormRef.current.title,
        (value) => setForeshadowFieldValue(
          "title",
          requireStudioMaxLength(value, 50, "伏笔名称"),
        ),
      ),
      controlledAssistantBinding(
        foreshadowAssistantScopeRef,
        foreshadowDirtyFieldsRef,
        ids.foreshadowContent,
        "伏笔内容",
        () => foreshadowFormRef.current.content,
        (value) => setForeshadowFieldValue(
          "content",
          requireStudioMaxLength(value, 200, "伏笔内容"),
        ),
      ),
      controlledAssistantBinding(
        foreshadowAssistantScopeRef,
        foreshadowDirtyFieldsRef,
        ids.foreshadowLatestProgress,
        "伏笔进展",
        () => foreshadowFormRef.current.latest_progress,
        (value) => setForeshadowFieldValue(
          "latest_progress",
          requireStudioMaxLength(value, 200, "伏笔进展"),
        ),
      ),
    ];
    if (foreshadowEditing) {
      bindings.push(
        controlledAssistantBinding(
          foreshadowAssistantScopeRef,
          foreshadowDirtyFieldsRef,
          ids.foreshadowStatus,
          "伏笔状态",
          () => foreshadowFormRef.current.status,
          (value) => setForeshadowFieldValue(
            "status",
            requireStudioChoice(value, ["active", "resolved"] as const, "伏笔状态"),
          ),
        ),
      );
    }
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:modal:foreshadow:${novel.id}:${foreshadowEditing?.id ?? "new"}`,
        kind: "modal",
        persistenceBaseline: foreshadowEditing
          ? { kind: "entity", version: foreshadowEditing.version }
          : { kind: "none", version: null },
        envelope: {
          ...background,
          page: { ...background.page, modal: "foreshadow-editor" },
          entity: {
            type: "foreshadow",
            ...(foreshadowEditing?.id ? { id: foreshadowEditing.id } : {}),
            title: foreshadowEditing?.title || "新增伏笔",
          },
        },
      },
      bindings,
    );
    foreshadowAssistantScopeRef.current = mounted.handle;
    return () => {
      if (foreshadowAssistantScopeRef.current === mounted.handle) {
        foreshadowAssistantScopeRef.current = null;
      }
      mounted.dispose();
    };
  }, [foreshadowEditing?.id, foreshadowOpen, novel.id, novel.title, section, settingsTab]);

  React.useEffect(() => {
    if (!settingsOpen || section !== "settings" || settingsTab !== "template") return;
    const background = studioAssistantPageEnvelope(novel, "settings");
    if (!background) return;
    const ids = STUDIO_ASSISTANT_FIELD_IDS;
    const bindings: StudioAssistantFieldBinding[] = [
      controlledAssistantBinding(
        settingsAssistantScopeRef,
        settingsDirtyFieldsRef,
        ids.settingsTemplateName,
        "模板名称",
        () => settingsFormRef.current.template_name,
        (value) => setSettingsFieldValue("template_name", value),
      ),
      controlledAssistantBinding(
        settingsAssistantScopeRef,
        settingsDirtyFieldsRef,
        ids.settingsGenre,
        "分类",
        () => settingsFormRef.current.genre,
        (value) => setSettingsFieldValue("genre", value),
      ),
      controlledAssistantBinding(
        settingsAssistantScopeRef,
        settingsDirtyFieldsRef,
        ids.settingsSubgenre,
        "细分类",
        () => settingsFormRef.current.subgenre,
        (value) => setSettingsFieldValue("subgenre", value),
      ),
      controlledAssistantBinding(
        settingsAssistantScopeRef,
        settingsDirtyFieldsRef,
        ids.settingsIdea,
        "创作思路",
        () => settingsFormRef.current.idea,
        (value) => setSettingsFieldValue("idea", value),
      ),
      ...Object.keys(settingsFormRef.current.template_data).map((key) => (
        controlledAssistantBinding(
          settingsAssistantScopeRef,
          settingsDirtyFieldsRef,
          settingsTemplateFieldId(key),
          key,
          () => settingsFormRef.current.template_data[key] ?? "",
          (value) => setSettingsTemplateValue(key, value),
        )
      )),
    ];
    const mounted = mountStudioAssistantScope(
      assistantContextRuntime,
      {
        id: `studio:modal:settings:${novel.id}`,
        kind: "modal",
        persistenceBaseline: { kind: "entity", version: novel.version },
        envelope: {
          ...background,
          page: { ...background.page, modal: "novel-settings" },
          entity: { type: "setting", id: novel.id, title: novel.template_name || novel.title },
        },
      },
      bindings,
    );
    settingsAssistantScopeRef.current = mounted.handle;
    return () => {
      if (settingsAssistantScopeRef.current === mounted.handle) {
        settingsAssistantScopeRef.current = null;
      }
      mounted.dispose();
    };
  }, [novel.id, novel.title, section, settingsOpen, settingsTab]);

  const volumes = novel.tree.filter((item: VolumeRecord) => item.id !== null);
  const orderedVolumes = volumeDescending ? [...volumes].reverse() : volumes;
  const ungrouped = novel.tree.find((item: VolumeRecord) => item.id === null);
  const chapterDocuments = novel.tree.flatMap((volume: VolumeRecord) => volume.documents).filter((item: DocumentRecord) => item.kind === "chapter");
  const chapterNumberById = new Map(
    [...chapterDocuments]
      .sort((left: DocumentRecord, right: DocumentRecord) => left.position - right.position)
      .map((document: DocumentRecord, index: number) => [document.id, index + 1]),
  );

  const setRoleSubview = (next: "list" | "graph") => {
    setRoleTab(next);
    rememberWorkbenchRoleView(novel.id, next);
    const url = new URL(window.location.href);
    if (next === "graph") url.searchParams.set("role_view", "graph");
    else url.searchParams.delete("role_view");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  };

  const loadDomains = React.useCallback(async () => {
    const failures: string[] = [];
    await Promise.all([
      apiRequest<NovelCharacterRecord[]>(`/novels/${novel.id}/characters`)
        .then(setCharacters)
        .catch((reason) => failures.push(readableError(reason, "加载角色失败"))),
      apiRequest<CharacterRelationshipRecord[]>(`/novels/${novel.id}/relationships`)
        .then(setRelationships)
        .catch((reason) => failures.push(readableError(reason, "加载角色关系失败"))),
      apiRequest<StorylineRecord[]>(`/novels/${novel.id}/storylines`)
        .then(setStorylines)
        .catch((reason) => failures.push(readableError(reason, "加载故事线失败"))),
      apiRequest<ForeshadowRecord[]>(`/novels/${novel.id}/foreshadows`)
        .then(setForeshadows)
        .catch((reason) => failures.push(readableError(reason, "加载伏笔失败"))),
    ]);
    if (failures.length > 0) onError(failures.join("；"));
  }, [novel.id]);

  React.useEffect(() => { void loadDomains(); }, [loadDomains]);
  React.useEffect(() => {
    if (openChapterWizardSignal > 0) setChapterWizardOpen(true);
  }, [openChapterWizardSignal]);
  React.useEffect(() => {
    const initial = volumeDescending ? volumes[volumes.length - 1] : volumes[0];
    if (expandedVolumes.length === 0 && initial?.id) setExpandedVolumes([String(initial.id)]);
  }, [novel.id, volumes.length, volumeDescending]);

  const perform = async (action: () => Promise<void>, fallback: string) => {
    setBusy(true);
    try {
      await action();
    } catch (reason) {
      onError(readableError(reason, fallback));
    } finally {
      setBusy(false);
    }
  };

  const refreshAll = async () => {
    const next = await onReload();
    if (next) onNovelChanged(next);
    await loadDomains();
  };

  const openOutline = (targetStep = 0) => {
    setOutlineStep(targetStep);
    setOutlineOpen(true);
  };

  const openVolume = (volume: VolumeRecord | null = null) => {
    setVolumeEditing(volume);
    setVolumeTitle(volume?.title ?? "");
    setVolumeOpen(true);
  };

  const saveVolume = () => perform(async () => {
    if (!volumeTitle.trim()) return;
    if (volumeEditing?.id) {
      await apiRequest(`/novels/${novel.id}/volumes/${volumeEditing.id}`, {
        method: "PUT",
        body: JSON.stringify({ expected_version: volumeEditing.version, title: volumeTitle.trim() }),
      });
    } else {
      const created = await apiRequest<{ id: string }>(`/novels/${novel.id}/volumes`, {
        method: "POST",
        body: JSON.stringify({ title: volumeTitle.trim() }),
      });
      setExpandedVolumes((current: string[]) => current.includes(created.id) ? current : [...current, created.id]);
    }
    setVolumeOpen(false);
    await refreshAll();
  }, "保存分卷失败");

  const deleteVolume = (volume: VolumeRecord) => {
    const otherVolumes = volumes.filter((item: VolumeRecord) => item.id !== volume.id);
    const chapters = volume.documents.filter((item: DocumentRecord) => item.kind === "chapter");
    let destination = otherVolumes[0]?.id ?? null;
    Modal.confirm({
      className: "anw-modal",
      title: `删除“${volume.title}”？`,
      content: h(
        "div",
        { className: "mb-form-stack" },
        h("p", null, chapters.length ? `本卷有 ${chapters.length} 章，删除时必须移动到其他分卷。` : "删除后无法恢复。"),
        chapters.length ? field("章节移动到", h(Select, {
          defaultValue: destination,
          options: otherVolumes.map((item: VolumeRecord) => ({ label: item.title, value: item.id })),
          onChange: (value: string) => { destination = value; },
        })) : null,
      ),
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true, disabled: chapters.length > 0 && !destination },
      onOk: () => perform(async () => {
        await apiRequest(`/novels/${novel.id}/volumes/${volume.id}`, {
          method: "DELETE",
          body: JSON.stringify({ expected_version: volume.version, move_documents_to: chapters.length ? destination : null }),
        });
        await refreshAll();
      }, "删除分卷失败"),
    });
  };

  const moveChapter = (document: DocumentRecord, volumeId: string | null) => perform(async () => {
    await apiRequest(`/novels/${novel.id}/chapters/reorder`, {
      method: "POST",
      body: JSON.stringify({
        ordered_document_ids: chapterDocuments.map((item: DocumentRecord) => item.id),
        volume_by_document: { [document.id]: volumeId },
      }),
    });
    await refreshAll();
  }, "移动章节失败");

  const exportNovel = (format: "markdown" | "text" = "text") => perform(async () => {
    const record = await apiRequest<NovelExportRecord>(`/novels/${novel.id}/exports`, {
      method: "POST", body: JSON.stringify({ export_format: format }),
    });
    downloadExport(record, novel.title);
  }, "导出作品失败");

  const runSearch = async () => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const results = await apiRequest<NovelSearchResultRecord[]>(
        `/novels/${novel.id}/search?q=${encodeURIComponent(query)}&limit=50`,
      );
      setSearchResults(results);
    } catch (reason) {
      onError(readableError(reason, "搜索全书失败"));
    } finally {
      setSearching(false);
    }
  };

  const openSearchResult = (result: NovelSearchResultRecord) => {
    setSearchOpen(false);
    onSelectDocument(result.document_id);
  };

  const searchLocation = (result: NovelSearchResultRecord): string => {
    const volume = novel.tree.find((item: VolumeRecord) => item.documents.some((document: DocumentRecord) => document.id === result.document_id));
    const kind = result.kind === "chapter" ? "章节" : result.kind === "outline" ? "大纲" : "设定";
    return [volume?.id ? volume.title : "未分卷", kind].join(" · ");
  };

  const downloadCover = () => {
    const link = document.createElement("a");
    link.href = novel.cover_image_data || defaultNovelCover;
    link.download = `${novel.title}-封面.jpg`;
    link.click();
  };

  const openCover = () => {
    setCoverMode("ai");
    setCoverImageData("");
    setCoverOpen(true);
  };

  const uploadCover = (event: any) => {
    const file = event.target.files?.[0] as File | undefined;
    if (!file) return;
    void perform(async () => {
      setCoverImageData(await compressCover(file));
    }, "上传封面失败");
    event.target.value = "";
  };

  const applyCover = () => perform(async () => {
    let nextCover = coverImageData;
    const templateData = { ...(novel.template_data || {}) } as Record<string, unknown>;
    if (coverMode === "ai") {
      await getGenerationModelStatus();
      const job = await apiRequest<CreativeGenerationRecord>("/creative-generations", {
        method: "POST",
        body: JSON.stringify({
          scope_type: "novel",
          scope_id: novel.id,
          novel_id: novel.id,
          kind: "novel_cover",
          input_snapshot: { title: novel.title, genre: novel.genre, subgenre: novel.subgenre, idea: novel.idea, highlight: novel.highlight },
          force_new: true,
        }),
      });
      if (job.state !== "ready") throw new Error(job.failure_message || "模型封面方案生成失败");
      templateData.cover_prompt = String(job.output_json?.cover_prompt || "");
      templateData.cover_generation_job_id = job.id;
      nextCover = novel.cover_image_data || defaultNovelCover;
    } else if (coverMode === "system") {
      nextCover = defaultNovelCover;
    }
    if (!nextCover) throw new Error("请先选择或上传封面");
    const updated = await apiRequest<NovelRecord>(`/novels/${novel.id}/settings`, {
      method: "PUT",
      body: JSON.stringify({
        expected_version: novel.version,
        genre: novel.genre,
        subgenre: novel.subgenre,
        idea: novel.idea,
        template_name: novel.template_name,
        template_data: templateData,
        cover_image_data: nextCover,
      }),
    });
    onNovelChanged(updated);
    setCoverOpen(false);
  }, "修改封面失败");

  const openCharacterForm = (roleType: "main" | "supporting", item: NovelCharacterRecord | null = null) => {
    setCharacterEditing(item);
    characterDirtyFieldsRef.current.clear();
    replaceStudioControlledState(characterFormRef, setCharacterForm, {
      role_type: item?.role_type ?? roleType,
      name: item?.name ?? "",
      gender: String(item?.details?.gender ?? ""),
      age: String(item?.details?.age ?? ""),
      identity: String(item?.details?.identity ?? ""),
      personality: String(item?.details?.personality ?? ""),
      description: item?.description ?? "",
    });
    setCharacterOpen(true);
  };

  const saveCharacter = () => perform(async () => {
    const current = characterFormRef.current;
    const payload = {
      role_type: current.role_type,
      name: current.name.trim(),
      description: current.description.trim(),
      details: { gender: current.gender.trim(), age: current.age.trim(), identity: current.identity.trim(), personality: current.personality.trim() },
    };
    await apiRequest(`/novels/${novel.id}/characters${characterEditing ? `/${characterEditing.id}` : ""}`, {
      method: characterEditing ? "PUT" : "POST",
      body: JSON.stringify(characterEditing ? { ...payload, expected_version: characterEditing.version } : payload),
    });
    setCharacterOpen(false);
    await loadDomains();
  }, "保存角色失败");

  const deleteCharacter = (item: NovelCharacterRecord) => Modal.confirm({
    className: "anw-modal", title: `归档角色“${item.name}”？`, content: "角色和相关关系会归档并保留历史记录。", okText: "归档", cancelText: "取消", okButtonProps: { danger: true },
    onOk: () => perform(async () => {
      await apiRequest(`/novels/${novel.id}/characters/${item.id}?expected_version=${item.version}`, { method: "DELETE" });
      await loadDomains();
    }, "归档角色失败"),
  });

  const openRelationshipsForCharacter = (characterId: string) => {
    setRelationshipFocusCharacterId(characterId);
    setRelationshipFocusId(null);
    setRelationshipStartWithNew(false);
    setRelationshipOpen(true);
  };

  const openRelationshipById = (relationshipId: string) => {
    const relationship = relationships.find((item: CharacterRelationshipRecord) => item.id === relationshipId);
    setRelationshipFocusCharacterId(relationship?.source_character_id ?? null);
    setRelationshipFocusId(relationshipId);
    setRelationshipStartWithNew(false);
    setRelationshipOpen(true);
  };

  const openNewRelationship = () => {
    setRelationshipFocusCharacterId(null);
    setRelationshipFocusId(null);
    setRelationshipStartWithNew(true);
    setRelationshipOpen(true);
  };

  const openStorylineForm = (type: StorylineType, item: StorylineRecord | null = null) => {
    setStorylineEditing(item);
    storylineDirtyFieldsRef.current.clear();
    replaceStudioControlledState(storylineFormRef, setStorylineForm, { storyline_type: item?.storyline_type ?? type, title: item?.title ?? "", description: item?.description ?? "", status: item?.status ?? "active", progress: item?.progress ?? 0 });
    setStorylineOpen(true);
  };

  const saveStoryline = () => perform(async () => {
    const current = storylineFormRef.current;
    const base = { storyline_type: current.storyline_type, title: current.title.trim(), description: current.description.trim() };
    const payload = storylineEditing ? { ...base, expected_version: storylineEditing.version, status: current.status, progress: current.progress } : base;
    await apiRequest(`/novels/${novel.id}/storylines${storylineEditing ? `/${storylineEditing.id}` : ""}`, {
      method: storylineEditing ? "PUT" : "POST", body: JSON.stringify(payload),
    });
    setStorylineOpen(false);
    await loadDomains();
  }, "保存故事线失败");

  const deleteStoryline = (item: StorylineRecord) => perform(async () => {
    await apiRequest(`/novels/${novel.id}/storylines/${item.id}?expected_version=${item.version}`, { method: "DELETE" });
    await loadDomains();
  }, "删除故事线失败");

  const openForeshadowForm = (item: ForeshadowRecord | null = null) => {
    setForeshadowEditing(item);
    foreshadowDirtyFieldsRef.current.clear();
    replaceStudioControlledState(foreshadowFormRef, setForeshadowForm, { title: item?.title ?? "", content: item?.content ?? "", latest_progress: item?.latest_progress ?? "", status: item?.status ?? "active", progress: item?.progress ?? 0 });
    setForeshadowOpen(true);
  };

  const saveForeshadow = () => perform(async () => {
    const current = foreshadowFormRef.current;
    const base = { title: current.title.trim(), content: current.content.trim(), latest_progress: current.latest_progress.trim() };
    const payload = foreshadowEditing ? { ...base, expected_version: foreshadowEditing.version, status: current.status, progress: current.status === "resolved" ? 100 : current.progress } : base;
    await apiRequest(`/novels/${novel.id}/foreshadows${foreshadowEditing ? `/${foreshadowEditing.id}` : ""}`, {
      method: foreshadowEditing ? "PUT" : "POST", body: JSON.stringify(payload),
    });
    setForeshadowOpen(false);
    await loadDomains();
  }, "保存伏笔失败");

  const deleteForeshadow = (item: ForeshadowRecord) => perform(async () => {
    await apiRequest(`/novels/${novel.id}/foreshadows/${item.id}?expected_version=${item.version}`, { method: "DELETE" });
    await loadDomains();
  }, "删除伏笔失败");

  const openSettings = () => {
    const data: Record<string, string> = {};
    Object.entries(novel.template_data || {}).forEach(([key, value]) => { data[key] = String(value ?? ""); });
    settingsDirtyFieldsRef.current.clear();
    replaceStudioControlledState(settingsFormRef, setSettingsForm, { genre: novel.genre, subgenre: novel.subgenre, idea: novel.idea, template_name: novel.template_name, template_data: data });
    setSettingsOpen(true);
  };

  const saveSettings = () => perform(async () => {
    const updated = await apiRequest<NovelRecord>(`/novels/${novel.id}/settings`, {
      method: "PUT",
      body: JSON.stringify({ expected_version: novel.version, ...settingsFormRef.current }),
    });
    onNovelChanged(updated);
    setSettingsOpen(false);
  }, "保存模板设定失败");

  const toggleVolume = (id: string) => setExpandedVolumes((current: string[]) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);

  const renderChapterCard = (document: DocumentRecord, volumeId: string | null) => h(
    "article",
    { key: document.id, className: "mb-chapter-card" },
    h("button", { type: "button", className: "mb-chapter-open", onClick: () => onSelectDocument(document.id) },
      h("strong", null, chapterDisplayTitle(chapterNumberById.get(document.id) ?? 1, document.title)),
      h("span", null, `${document.visible_character_count} 字`),
    ),
    h(
      "div",
      { className: "mb-chapter-actions" },
      volumeId
        ? h(Button, { type: "link", size: "small", onClick: () => void moveChapter(document, null) }, "移出")
        : h(Select, {
            size: "small", className: "mb-move-select", placeholder: "移入分卷",
            options: volumes.map((volume: VolumeRecord) => ({ label: volume.title, value: volume.id })),
            onChange: (value: string) => void moveChapter(document, value),
          }),
    ),
  );

  const renderChapters = () => h(
    "div",
    { className: "mb-chapter-dashboard" },
    h(
      "div",
      { className: "mb-subtitle-row" },
      h("h3", null, "分卷管理"),
      h(Button, { type: "text", className: "mb-inline-add", icon: h(PlusOutlined), onClick: () => openVolume() }, "新增分卷"),
    ),
    h(
      "div",
      { className: "mb-volume-grid" },
      orderedVolumes.length === 0 ? h("div", { className: "mb-volume-zero" }, "暂无分卷，点击上方按钮创建") : null,
      ...orderedVolumes.map((volume: VolumeRecord) => {
        const id = String(volume.id);
        const expanded = expandedVolumes.includes(id);
        const chapters = volume.documents.filter((item: DocumentRecord) => item.kind === "chapter");
        return h(
          "section",
          { key: id, className: `mb-volume-card ${expanded ? "is-expanded" : ""}` },
          h(
            "header",
            { className: "mb-volume-header" },
            h("button", { type: "button", className: "mb-volume-toggle", onClick: () => toggleVolume(id) },
              h(expanded ? CaretDownOutlined : CaretRightOutlined),
              h("strong", null, volume.title),
              h("span", null, `${chapters.length}章`),
            ),
            h("div", { className: "mb-volume-actions" },
              h(Button, { type: "text", size: "small", onClick: () => openVolume(volume) }, "编辑"),
              h(Button, { type: "text", size: "small", danger: true, onClick: () => deleteVolume(volume) }, "删除"),
            ),
          ),
          expanded ? h("div", { className: "mb-volume-chapters" }, chapters.length ? chapters.map((item: DocumentRecord) => renderChapterCard(item, id)) : h("div", { className: "mb-volume-empty" }, "该分卷暂无章节")) : null,
        );
      }),
    ),
    h(
      "section",
      { className: "mb-ungrouped" },
      ungrouped?.documents.filter((item: DocumentRecord) => item.kind === "chapter").length
        ? h("div", { className: "mb-ungrouped-list" }, ...ungrouped.documents.filter((item: DocumentRecord) => item.kind === "chapter").map((item: DocumentRecord) => renderChapterCard(item, null)))
        : h("div", { className: "mb-ungrouped-empty" }, h("strong", null, "暂无章节"), h("span", null, "点击上方按钮创建新章节")),
    ),
  );

  const outlineCards = [
    { label: "亮点&简介", value: novel.highlight, step: 5 },
    { label: "故事背景设定", value: novel.background, step: 2 },
    { label: "故事主要情节", value: novel.main_plot, step: 4 },
  ];
  const hasOutline = outlineCards.some((item) => Boolean(item.value));

  const renderOutline = () => hasOutline
    ? h(
        "div",
        { className: "mb-outline-cards" },
        ...outlineCards.map((item) => h(
          "article",
          { key: item.label, className: "mb-outline-card" },
          h("header", null,
            h("h3", null, item.label),
            h("div", null,
              h(Button, { type: "text", icon: h(CopyOutlined), disabled: !item.value, onClick: () => void navigator.clipboard.writeText(item.value) }),
              h(Button, { type: "text", icon: h(EditOutlined), onClick: () => openOutline(item.step) }),
            ),
          ),
          h("p", null, item.value || "尚未生成"),
        )),
      )
    : h(
        "div",
        { className: "mb-outline-empty" },
        h(FileTextOutlined),
        h("strong", null, "暂无大纲"),
        h("span", null, "点击上方按钮开始生成大纲"),
      );

  const characterGroups = [
    { type: "main" as const, label: "主角", className: "is-main" },
    { type: "supporting" as const, label: "配角", className: "is-supporting" },
  ];

  const renderRoles = () => roleTab === "list"
    ? h(
        "div",
        { className: "mb-role-list" },
        ...characterGroups.map((group) => {
          const rows = characters.filter((item: NovelCharacterRecord) => item.role_type === group.type);
          return h(
            "section",
            { key: group.type, className: `mb-role-section ${group.className}` },
            h(
              "div",
              { className: "mb-subtitle-row" },
              h("h3", null, group.label, h("span", null, `(${rows.length})`)),
              h(Button, { type: "text", icon: h(PlusOutlined), onClick: () => openCharacterForm(group.type) }, `新增${group.label}`),
            ),
            rows.length ? h("div", { className: "mb-role-grid" }, ...rows.map((item: NovelCharacterRecord) => h(
              "article", { key: item.id, className: "mb-role-card" },
              h("button", { type: "button", className: "mb-role-card-main", onClick: () => openCharacterForm(group.type, item) },
                h("span", { className: "mb-role-avatar" }, item.name.slice(0, 1)),
                h("span", { className: "mb-role-copy" }, h("strong", null, item.name), h("small", null, String(item.details?.identity || item.description || "未填写身份"))),
              ),
              h(Button, { type: "text", size: "small", danger: true, icon: h(DeleteOutlined), onClick: () => deleteCharacter(item), "aria-label": `删除${item.name}` }),
            ))) : h("div", { className: "mb-inline-empty" }, `暂无${group.label}`),
          );
        }),
      )
    : h(
        "div",
        { className: "mb-relationship-panel" },
        characters.length
          ? h(RelationshipWorkspace, {
              novelId: novel.id,
              characters,
              relationships,
              onEditCharacter: openRelationshipsForCharacter,
              onEditRelationship: openRelationshipById,
              onAddRelationship: openNewRelationship,
              onRelationshipsChanged: setRelationships,
            })
          : h(Empty, { description: "请先新增至少两个角色" }),
      );

  const storylineLabels: Record<StorylineType, string> = { main: "主线", support: "支线", romance: "感情线", faction: "势力线" };
  const activeClueTab = clueTab as StorylineType;
  const activeStorylines = storylines.filter((item: StorylineRecord) => item.storyline_type === activeClueTab);

  const renderClues = () => h(
    "div",
    { className: "mb-storyline-board" },
    activeStorylines.length
      ? h("div", { className: "mb-storyline-timeline" }, ...activeStorylines.map((item: StorylineRecord, index: number) => h(
          "article", { key: item.id, className: "mb-storyline-card" },
          h("span", { className: "mb-timeline-index" }, index + 1),
          h("div", { className: "mb-storyline-content" }, h("header", null, h("h3", null, item.title), h("span", null, `${item.progress}%`)), h("p", null, item.description || "尚未填写情节说明"), h(Progress, { percent: item.progress, showInfo: false, strokeColor: "#ff7548" })),
          h("div", { className: "mb-card-actions" }, h(Button, { type: "text", icon: h(EditOutlined), onClick: () => openStorylineForm(activeClueTab, item) }), h(Button, { type: "text", danger: true, icon: h(DeleteOutlined), onClick: () => void deleteStoryline(item) })),
        )))
      : h("div", { className: "mb-large-empty" }, h(Empty, { description: `暂无${storylineLabels[activeClueTab]}，可以从真实创作计划中新增。` }), h(Button, { className: "anw-primary-button", icon: h(PlusOutlined), onClick: () => openStorylineForm(activeClueTab) }, `新增${storylineLabels[activeClueTab]}`)),
  );

  const templateEntries = Object.entries(novel.template_data || {}).filter(([key]) => !key.startsWith("cover_"));
  const foreshadowStatusLabel: Record<string, string> = { planned: "待埋设", active: "进行中", resolved: "已解决", dropped: "已放弃" };
  const renderSettings = () => settingsTab === "template"
    ? h(
        "div",
        { className: "mb-template-settings" },
        h("article", { className: "mb-template-card" },
          h("header", null, h("div", null, h("h3", null, novel.template_name || "自定义模板"), h("span", null, [novel.genre, novel.subgenre].filter(Boolean).join(" / ") || "未设置分类")), h(Button, { icon: h(EditOutlined), onClick: openSettings }, "编辑模板设定")),
          h("section", null, h("strong", null, "创作思路"), h("p", null, novel.idea || "尚未填写创作思路")),
          h("div", { className: "mb-template-grid" }, ...(templateEntries.length ? templateEntries : [["模板字段", "尚未填写"]]).map(([key, value]) => h("div", { key }, h("span", null, key), h("strong", null, String(value || "未填写"))))),
        ),
      )
    : h(
        "div",
        { className: "mb-foreshadow-board" },
        h("div", { className: "mb-foreshadow-summary" },
          h("span", null, h("strong", null, foreshadows.length), "全部"),
          h("span", null, h("strong", null, foreshadows.filter((item: ForeshadowRecord) => item.status === "active").length), "进行中"),
          h("span", null, h("strong", null, foreshadows.filter((item: ForeshadowRecord) => item.status === "resolved").length), "已解决"),
        ),
        foreshadows.length ? h("div", { className: "mb-foreshadow-grid" }, ...foreshadows.map((item: ForeshadowRecord) => h(
          "article", { key: item.id, className: "mb-foreshadow-card" },
          h("header", null, h("h3", null, item.title), h("span", { className: `is-${item.status}` }, foreshadowStatusLabel[item.status])),
          h("p", null, item.content || "尚未填写伏笔内容"),
          h("div", { className: "mb-foreshadow-progress" }, h("strong", null, "最新进展："), h("span", null, item.latest_progress || "暂无进展")),
          h("div", { className: "mb-card-actions" }, h(Button, { type: "text", icon: h(EditOutlined), onClick: () => openForeshadowForm(item) }, "编辑"), h(Button, { type: "text", danger: true, icon: h(DeleteOutlined), onClick: () => void deleteForeshadow(item) }, "删除")),
        ))) : h("div", { className: "mb-large-empty" }, h(Empty, { description: "暂无伏笔" })),
      );

  const panelActions = section === "chapters"
    ? h(React.Fragment, null,
        h(Button, { icon: h(volumeDescending ? ArrowDownOutlined : ArrowUpOutlined), title: volumeDescending ? "按分卷倒序显示" : "按分卷正序显示", "aria-label": volumeDescending ? "按分卷倒序显示" : "按分卷正序显示", onClick: () => setVolumeDescending((current: boolean) => !current) }),
        h(Button, { icon: h(SearchOutlined), title: "搜索全书", "aria-label": "搜索全书", onClick: () => setSearchOpen(true) }),
        h(Button, { icon: h(DownloadOutlined), title: "下载全书", "aria-label": "下载全书", onClick: () => void exportNovel("text") }),
        h(Button, { className: "anw-primary-button", icon: h(PlusOutlined), onClick: () => setChapterWizardOpen(true) }, "新建章节"),
      )
    : section === "outline"
      ? h(Button, { className: "anw-primary-button", icon: h(ReloadOutlined), onClick: () => openOutline(hasOutline ? 1 : 0) }, hasOutline ? "重新生成" : "生成大纲")
      : section === "roles"
        ? h("div", { className: "mb-top-tabs" }, h("button", { type: "button", className: roleTab === "list" ? "is-active" : "", onClick: () => setRoleSubview("list") }, "角色列表"), h("button", { type: "button", className: roleTab === "graph" ? "is-active" : "", onClick: () => setRoleSubview("graph") }, "关系网"))
        : section === "clues"
          ? h("div", { className: "mb-top-tabs is-four" }, ...(Object.keys(storylineLabels) as StorylineType[]).map((type) => h("button", { key: type, type: "button", className: clueTab === type ? "is-active" : "", onClick: () => setClueTab(type) }, storylineLabels[type])))
          : h("div", { className: "mb-top-tabs is-settings" }, h("button", { type: "button", className: settingsTab === "template" ? "is-active" : "", onClick: () => setSettingsTab("template") }, "模板设定"), h("button", { type: "button", className: settingsTab === "foreshadow" ? "is-active" : "", onClick: () => setSettingsTab("foreshadow") }, "伏笔管理"));

  const panelBody = section === "chapters" ? renderChapters() : section === "outline" ? renderOutline() : section === "roles" ? renderRoles() : section === "clues" ? renderClues() : renderSettings();

  return h(
    React.Fragment,
    null,
    h(
      Spin,
      { spinning: busy },
      h(
        "main",
        {
          className: "anw-app mb-workbench",
          "data-assistant-density": assistantWorkspaceLayout?.density ?? "comfortable",
          "data-assistant-overlay": String(assistantWorkspaceLayout?.assistantOverlay === true),
        },
        h(
          "aside",
          { className: "mb-book-rail" },
          h("div", { className: "mb-book-cover-wrap" }, h("img", { src: novel.cover_image_data || defaultNovelCover, alt: `${novel.title}封面`, className: "mb-book-cover" }), h("div", { className: "mb-book-cover-actions" }, h(Button, { type: "text", icon: h(DownloadOutlined), onClick: downloadCover, "aria-label": "下载封面" }), h(Button, { type: "text", icon: h(EditOutlined), onClick: openCover, "aria-label": "修改封面" }))),
          h("h1", null, novel.title),
          h("p", null, [novel.genre, novel.subgenre].filter(Boolean).join(" / ") || "长篇小说"),
          h("div", { className: "mb-book-stats" }, h("span", null, `${chapterDocuments.reduce((sum: number, item: DocumentRecord) => sum + item.visible_character_count, 0)} 字`), h("span", null, `${chapterDocuments.length} 章节`)),
          h("section", { className: "anw-current-model-card", "aria-label": "当前有效模型" },
            h("strong", null, "当前有效模型"),
            h("span", null, generationModelStatus ? generationModelLabel(generationModelStatus) : generationModelStatusError ? "暂时无法读取" : "正在读取…"),
            h("small", null, "跟随 AI 小说作家 Agent；专属模型优先，未设置则继承 QwenPaw 全局模型。"),
          ),
          h(
            "nav",
            { className: "mb-book-nav", "aria-label": "作品创作流程" },
            ...(["chapters", "outline", "roles", "clues", "settings"] as WorkbenchSection[]).map((item) => {
              const Icon = sectionIcon(item);
              return h("button", { key: item, type: "button", className: section === item ? "is-active" : "", onClick: () => onSectionChange(item) }, h(Icon), h("span", null, sectionLabel(item)));
            }),
          ),
          h("div", { className: "mb-back-center-wrap" }, h(Button, { className: "mb-back-center", onClick: onBack }, "返回创作中心")),
        ),
        h(
          "section",
          { className: "mb-workbench-main" },
          h("header", { className: `mb-panel-header ${section === "roles" || section === "clues" || section === "settings" ? "is-tabs-only" : ""}` }, h("h2", null, section === "chapters" ? "章节列表" : sectionLabel(section)), h("div", { className: "mb-panel-actions" }, panelActions)),
          h("div", { className: "mb-panel-body" }, panelBody),
        ),
      ),
    ),
    h(OutlineWizard, {
      novel, open: outlineOpen, startStep: outlineStep,
      onClose: () => setOutlineOpen(false),
      onGoChapters: () => onSectionChange("chapters"),
      onCompleted: (updated: NovelRecord) => { onNovelChanged(updated); void loadDomains(); },
      onError,
      selectionEditReviewHost: SelectionEditReviewHost,
    }),
    h(ChapterCreationWizard, {
      novel,
      open: chapterWizardOpen,
      volumes,
      characters,
      storylines,
      foreshadows,
      onClose: () => setChapterWizardOpen(false),
      onAddForeshadow: () => openForeshadowForm(),
      onCompleted: (created: DocumentRecord) => {
        void (async () => {
          await refreshAll();
          onSelectDocument(created.id);
        })();
      },
      onError,
    }),
    h(
      Modal,
      {
        open: searchOpen,
        centered: true,
        width: 680,
        footer: null,
        className: "anw-modal mb-search-modal",
        title: "搜索全书",
        onCancel: () => setSearchOpen(false),
      },
      h(
        "div",
        { className: "mb-search-body" },
        h(Input, {
          autoFocus: true,
          allowClear: true,
          size: "large",
          prefix: h(SearchOutlined),
          value: searchQuery,
          placeholder: "搜索章节标题或正文内容",
          "aria-label": "全书搜索词",
          onChange: (event: any) => setSearchQuery(event.target.value),
          onPressEnter: () => void runSearch(),
        }),
        h(Button, { size: "large", className: "anw-primary-button", loading: searching, disabled: !searchQuery.trim(), onClick: () => void runSearch() }, "搜索"),
        h(
          "div",
          { className: "mb-search-results", "aria-live": "polite" },
          searching
            ? h("div", { className: "mb-search-empty" }, h(Spin), h("span", null, "正在搜索全书…"))
            : searchResults.length
              ? h(React.Fragment, null, ...searchResults.map((result: NovelSearchResultRecord) => h(
                  "button",
                  { key: result.document_id, type: "button", className: "mb-search-result", onClick: () => openSearchResult(result) },
                  h("span", { className: "mb-search-result-heading" }, h("strong", null, result.title), h("small", null, searchLocation(result))),
                  h("span", { className: "mb-search-result-snippet" }, result.snippet || "命中标题"),
                )))
              : h("div", { className: "mb-search-empty" }, h(SearchOutlined), h("span", null, searchQuery.trim() ? "没有找到匹配内容" : "输入关键词后按回车搜索")),
        ),
      ),
    ),
    h(
      Modal,
      { open: volumeOpen, centered: true, closable: false, footer: null, className: "anw-modal mb-small-modal mb-volume-modal", width: 500, title: volumeEditing ? "编辑分卷" : "新增分卷", onCancel: () => setVolumeOpen(false) },
      h(
        "div",
        { className: "mb-volume-form" },
        field("分卷名称", h(Input, { autoFocus: true, value: volumeTitle, placeholder: "请输入分卷名称", onChange: (event: any) => setVolumeTitle(event.target.value), onPressEnter: () => void saveVolume() })),
        h(
          "div",
          { className: "mb-volume-form-actions" },
          h(Button, { size: "large", onClick: () => setVolumeOpen(false) }, "取消"),
          h(Button, { size: "large", className: "anw-primary-button", onClick: () => void saveVolume() }, "确定"),
        ),
      ),
    ),
    h(Modal, { open: characterOpen, className: "anw-modal mb-entity-modal", wrapClassName: "anw-assistant-aware-modal-wrap", mask: false, width: 720, title: characterEditing ? "编辑角色" : "新增角色", footer: null, onCancel: () => setCharacterOpen(false) },
      wrapSelectionReview(
        STUDIO_SELECTION_REVIEW_FIELD_GROUPS.character,
        "mb-character-selection-review-host",
        h("div", { className: "mb-form-stack" },
          field("角色类型", h(Select, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterRoleType), value: characterForm.role_type, options: [{ label: "主角", value: "main" }, { label: "配角", value: "supporting" }], onChange: (value: "main" | "supporting") => changeCharacterFieldValue("role_type", value, STUDIO_ASSISTANT_FIELD_IDS.characterRoleType) })),
          field("角色姓名", h(Input, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterName), value: characterForm.name, onChange: (event: any) => changeCharacterFieldValue("name", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.characterName) })),
          h("div", { className: "mb-form-grid mb-character-demographics" },
            field("性别", h(Select, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterGender), allowClear: true, value: characterForm.gender || undefined, options: [{ label: "男", value: "男" }, { label: "女", value: "女" }, { label: "其他", value: "其他" }, { label: "未知", value: "未知" }], onChange: (value: string) => changeCharacterFieldValue("gender", value || "", STUDIO_ASSISTANT_FIELD_IDS.characterGender) })),
            field("年龄", h(Input, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterAge), value: characterForm.age, onChange: (event: any) => changeCharacterFieldValue("age", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.characterAge) })),
          ),
          field("身份", h(Input.TextArea, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterIdentity), className: "mb-character-identity-input", rows: 2, value: characterForm.identity, onChange: (event: any) => changeCharacterFieldValue("identity", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.characterIdentity) })),
          field("性格", h(Input.TextArea, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterPersonality), rows: 3, value: characterForm.personality, onChange: (event: any) => changeCharacterFieldValue("personality", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.characterPersonality) })),
          field("人物小传", h(Input.TextArea, { ...assistantControlProps(characterAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.characterDescription), rows: 5, value: characterForm.description, onChange: (event: any) => changeCharacterFieldValue("description", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.characterDescription) })),
          h(Button, { size: "large", block: true, className: "anw-primary-button", disabled: !characterForm.name.trim(), onClick: () => void saveCharacter() }, "保存"),
        ),
      ),
    ),
    h(RelationshipEditor, {
      novelId: novel.id,
      novelTitle: novel.title,
      open: relationshipOpen,
      characters,
      relationships,
      focusCharacterId: relationshipFocusCharacterId,
      focusRelationshipId: relationshipFocusId,
      startWithNew: relationshipStartWithNew,
      onClose: () => setRelationshipOpen(false),
      onSaved: loadDomains,
      selectionEditReviewHost: SelectionEditReviewHost,
    }),
    h(Modal, { open: storylineOpen, className: "anw-modal mb-entity-modal", wrapClassName: "anw-assistant-aware-modal-wrap", mask: false, width: 680, title: storylineEditing ? "编辑故事线" : `新增${storylineLabels[storylineForm.storyline_type as StorylineType]}`, footer: null, onCancel: () => setStorylineOpen(false) },
      wrapSelectionReview(
        STUDIO_SELECTION_REVIEW_FIELD_GROUPS.storyline,
        "mb-storyline-selection-review-host",
        h("div", { className: "mb-form-stack" },
          field("故事线类型", h(Select, { ...assistantControlProps(storylineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.storylineType), value: storylineForm.storyline_type, options: (Object.keys(storylineLabels) as StorylineType[]).map((type) => ({ label: storylineLabels[type], value: type })), onChange: (value: StorylineType) => changeStorylineFieldValue("storyline_type", value, STUDIO_ASSISTANT_FIELD_IDS.storylineType) })),
          field("故事线名称", h(Input, { ...assistantControlProps(storylineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.storylineTitle), value: storylineForm.title, onChange: (event: any) => changeStorylineFieldValue("title", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.storylineTitle) })),
          field("情节说明", h(Input.TextArea, { ...assistantControlProps(storylineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.storylineDescription), rows: 6, value: storylineForm.description, onChange: (event: any) => changeStorylineFieldValue("description", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.storylineDescription) })),
          storylineEditing ? h("div", { className: "mb-form-grid" },
            field("状态", h(Select, { ...assistantControlProps(storylineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.storylineStatus), value: storylineForm.status, options: [{ label: "进行中", value: "active" }, { label: "暂停", value: "paused" }, { label: "已完成", value: "completed" }, { label: "已归档", value: "archived" }], onChange: (value: string) => changeStorylineFieldValue("status", value, STUDIO_ASSISTANT_FIELD_IDS.storylineStatus) })),
            field("进度", h(InputNumber, { ...assistantControlProps(storylineAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.storylineProgress), min: 0, max: 100, value: storylineForm.progress, formatter: (value: number) => `${value}%`, parser: (value: string) => Number(String(value).replace("%", "")), onChange: (value: number | null) => changeStorylineFieldValue("progress", Number(value || 0), STUDIO_ASSISTANT_FIELD_IDS.storylineProgress) })),
          ) : null,
          h(Button, { size: "large", block: true, className: "anw-primary-button", disabled: !storylineForm.title.trim(), onClick: () => void saveStoryline() }, "保存"),
        ),
      ),
    ),
    h(Modal, { open: foreshadowOpen, centered: true, closable: false, className: "anw-modal mb-entity-modal mb-foreshadow-modal", wrapClassName: "anw-assistant-aware-modal-wrap", mask: false, width: 480, title: foreshadowEditing ? "编辑伏笔" : "新增伏笔", footer: null, onCancel: () => setForeshadowOpen(false) },
      wrapSelectionReview(
        STUDIO_SELECTION_REVIEW_FIELD_GROUPS.foreshadow,
        "mb-foreshadow-selection-review-host",
        h("div", { className: "mb-form-stack" },
          field("伏笔名称", h(Input, { ...assistantControlProps(foreshadowAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.foreshadowTitle), maxLength: 50, showCount: true, placeholder: "如：神秘的黑衣人、丢失的玉佩...", value: foreshadowForm.title, onChange: (event: any) => changeForeshadowFieldValue("title", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.foreshadowTitle) })),
          field("伏笔内容", h(Input.TextArea, { ...assistantControlProps(foreshadowAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.foreshadowContent), rows: 4, maxLength: 200, showCount: true, placeholder: "详细描述伏笔的内容，如：第一章在城门口遇到一个黑衣人...", value: foreshadowForm.content, onChange: (event: any) => changeForeshadowFieldValue("content", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.foreshadowContent) })),
          field("伏笔进展（可选）", h(Input.TextArea, { ...assistantControlProps(foreshadowAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.foreshadowLatestProgress), rows: 3, maxLength: 200, showCount: true, placeholder: "记录伏笔的最新进展，如：第十章黑衣人再次出现...", value: foreshadowForm.latest_progress, onChange: (event: any) => changeForeshadowFieldValue("latest_progress", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.foreshadowLatestProgress) })),
          foreshadowEditing ? field("状态", h(Select, { ...assistantControlProps(foreshadowAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.foreshadowStatus), value: foreshadowForm.status === "resolved" ? "resolved" : "active", options: [{ label: "进行中", value: "active" }, { label: "已解决", value: "resolved" }], onChange: (value: string) => changeForeshadowFieldValue("status", value, STUDIO_ASSISTANT_FIELD_IDS.foreshadowStatus) })) : null,
          h(Button, { size: "large", block: true, className: "anw-primary-button", disabled: !foreshadowForm.title.trim(), onClick: () => void saveForeshadow() }, "保存"),
        ),
      ),
    ),
    h(Modal, { open: coverOpen, centered: true, closable: false, className: "anw-modal mb-cover-edit-modal", width: 500, title: "修改封面", footer: null, onCancel: () => setCoverOpen(false) },
      h("div", { className: "mb-cover-edit-stack" },
        h("div", { className: "mb-cover-edit-modes" },
          ...([
            ["ai", BgColorsOutlined, "智能生成"],
            ["system", BookOutlined, "系统封面"],
            ["upload", UploadOutlined, "上传图片"],
          ] as const).map(([mode, Icon, label]) => h("button", { key: mode, type: "button", className: coverMode === mode ? "is-active" : "", onClick: () => { setCoverMode(mode); setCoverImageData(mode === "system" ? defaultNovelCover : ""); } }, h(Icon), h("strong", null, label))),
        ),
        coverMode === "upload" ? h("label", { className: `mb-cover-edit-preview is-upload${coverImageData ? " has-image" : ""}` }, coverImageData ? h("img", { src: coverImageData, alt: "上传封面预览" }) : h("span", null, h(UploadOutlined), "点击上传图片"), h("input", { type: "file", accept: "image/*", onChange: uploadCover }))
          : h("div", { className: `mb-cover-edit-preview${coverMode === "system" ? " has-image" : ""}` }, coverMode === "system" ? h("img", { src: defaultNovelCover, alt: "系统封面预览" }) : h("span", null, h(PictureOutlined), "点击下方按钮生成封面")),
        coverMode === "ai" ? h("small", { className: "mb-name-cost" }, `当前有效模型：${generationModelStatus ? generationModelLabel(generationModelStatus) : generationModelStatusError ? "无法读取" : "读取中…"}`) : null,
        h(Button, { size: "large", block: true, className: "anw-primary-button", disabled: coverMode === "upload" && !coverImageData, onClick: () => void applyCover() }, coverMode === "ai" ? "开始生成" : "确认使用"),
        h(Button, { size: "large", block: true, onClick: () => setCoverOpen(false) }, "取消"),
      ),
    ),
    h(Modal, { open: settingsOpen, className: "anw-modal mb-entity-modal", wrapClassName: "anw-assistant-aware-modal-wrap", mask: false, width: 760, title: "编辑模板设定", footer: null, onCancel: () => setSettingsOpen(false) },
      wrapSelectionReview(
        [
          ...STUDIO_SELECTION_REVIEW_FIELD_GROUPS.settings,
          ...Object.keys(settingsForm.template_data).map(settingsTemplateFieldId),
        ],
        "mb-settings-selection-review-host",
        h("div", { className: "mb-form-stack" },
          h("div", { className: "mb-form-grid" },
            field("模板名称", h(Input, { ...assistantControlProps(settingsAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.settingsTemplateName), value: settingsForm.template_name, onChange: (event: any) => changeSettingsFieldValue("template_name", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.settingsTemplateName) })),
            field("分类", h(Input, { ...assistantControlProps(settingsAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.settingsGenre), value: settingsForm.genre, onChange: (event: any) => changeSettingsFieldValue("genre", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.settingsGenre) })),
          ),
          field("细分类", h(Input, { ...assistantControlProps(settingsAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.settingsSubgenre), value: settingsForm.subgenre, onChange: (event: any) => changeSettingsFieldValue("subgenre", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.settingsSubgenre) })),
          field("创作思路", h(Input.TextArea, { ...assistantControlProps(settingsAssistantScopeRef, STUDIO_ASSISTANT_FIELD_IDS.settingsIdea), rows: 5, value: settingsForm.idea, onChange: (event: any) => changeSettingsFieldValue("idea", event.target.value, STUDIO_ASSISTANT_FIELD_IDS.settingsIdea) })),
          ...Object.entries(settingsForm.template_data).map(([key, value]) => field(key, h(Input.TextArea, { ...assistantControlProps(settingsAssistantScopeRef, settingsTemplateFieldId(key)), key, rows: 2, value, onChange: (event: any) => changeSettingsTemplateValue(key, event.target.value) }))),
          h(Button, { size: "large", block: true, className: "anw-primary-button", onClick: () => void saveSettings() }, "保存"),
        ),
      ),
    ),
  );
}
