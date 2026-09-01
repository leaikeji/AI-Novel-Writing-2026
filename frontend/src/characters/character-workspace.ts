import type {
  CharacterWorkspaceActionError,
  CharacterFactHistoryPageV2,
  CharacterFactHistoryQueryV2,
  CharacterFactHealth,
  CharacterFactEffectiveState,
  CharacterWorkspaceSaveCommandV2,
  CharacterWorkspaceSelectionV1,
  CharacterWorkspaceV2,
  CharacterWorkspaceVoiceSlotProps,
  IntelligenceBatchRevertCommandV1,
  IntelligenceBatchRevertImpactV1,
  ProjectedFactViewV2,
  StoryFactCorrectionCommandV1,
} from "./contracts";
import {
  buildSaveCommand,
  characterRoleLabel,
  characterWorkspaceTabFromKey,
  continuityLabel,
  fieldError,
  hasProfileChanges,
  hasRootChanges,
  isMultiTimeline,
  normalizeActionError,
  profileDraftFromWorkspace,
  rootDraftFromWorkspace,
  tabForField,
  updateProfileText,
  valueAsText,
  type CharacterProfileDraft,
  type CharacterRootDraft,
  type CharacterWorkspaceTab,
  type ProfileFieldKey,
} from "./model";
import { ensureCharacterWorkspaceStyles } from "./styles";
import { renderCharacterStatePanel } from "./character-state-panel";
import { renderCharacterFactHistory } from "./character-fact-history";
import {
  renderCharacterBatchRevertDrawer,
  renderCharacterFactCorrectionDrawer,
} from "./character-fact-correction";
import { resolveCharacterSourceRange, type SourceRangeResolution } from "./source-coordinate";
import { characterProfileGroupCompletion, validateCharacterProfile } from "./state-model";
import {
  renderCharacterSourceViewer,
  type CharacterSourceRevisionV1,
} from "./workbench-character-source";

type StateSetter<T> = (value: T | ((previous: T) => T)) => void;
type ElementNode = unknown;

const CHARACTER_WORKSPACE_PORTAL_ROOT_ID = "anw-character-workspace-portal-root";

export interface CharacterReactRuntime {
  createElement(type: unknown, props?: Record<string, unknown> | null, ...children: unknown[]): ElementNode;
  useState<T>(initial: T | (() => T)): [T, StateSetter<T>];
  useEffect(effect: () => void | (() => void), dependencies?: readonly unknown[]): void;
  useRef<T>(initial: T): { current: T };
  useId?(): string;
}

export interface CharacterWorkspacePortalRuntime {
  createPortal(node: ElementNode, container: Element): ElementNode;
  getContainer(): Element | null;
}

export function getCharacterWorkspacePortalContainer(): Element | null {
  if (typeof document === "undefined") return null;
  const existing = document.getElementById(CHARACTER_WORKSPACE_PORTAL_ROOT_ID);
  if (existing) return existing;
  const container = document.createElement("div");
  container.id = CHARACTER_WORKSPACE_PORTAL_ROOT_ID;
  container.dataset.aiNovelCharacterWorkspacePortal = "true";
  document.body.appendChild(container);
  return container;
}

export interface CharacterWorkspaceDialogProps {
  readonly workspace: CharacterWorkspaceV2;
  readonly onSave?: (command: CharacterWorkspaceSaveCommandV2) => Promise<CharacterWorkspaceV2>;
  readonly onSelectionChange?: (
    selection: CharacterWorkspaceSelectionV1,
  ) => Promise<CharacterWorkspaceV2>;
  readonly voiceSlot?: (props: CharacterWorkspaceVoiceSlotProps) => ElementNode;
  readonly onLoadFacts?: (
    query: CharacterFactHistoryQueryV2,
  ) => Promise<CharacterFactHistoryPageV2>;
  readonly onCorrectFact?: (
    factId: string,
    command: StoryFactCorrectionCommandV1,
  ) => Promise<CharacterWorkspaceV2>;
  readonly onPreviewBatchRevert?: (
    batchId: string,
  ) => Promise<IntelligenceBatchRevertImpactV1>;
  readonly onRevertBatch?: (
    batchId: string,
    command: IntelligenceBatchRevertCommandV1,
  ) => Promise<CharacterWorkspaceV2>;
  readonly onLoadSource?: (
    documentId: string,
    revisionId: string,
  ) => Promise<CharacterSourceRevisionV1>;
  readonly onRequestClose?: () => void;
  readonly titleId?: string;
  readonly className?: string;
}

interface InputChangeEvent {
  readonly target: { readonly value: string };
}

interface KeyboardEventLike {
  readonly key: string;
  readonly shiftKey?: boolean;
  preventDefault(): void;
}

interface PointerEventLike {
  readonly target: unknown;
  readonly currentTarget: unknown;
}

interface DrawerTrigger {
  readonly element: HTMLElement;
  readonly fallbackId: string;
}

interface ToggleEventLike {
  readonly currentTarget: { readonly open: boolean };
}

const TAB_LABELS: Readonly<Record<CharacterWorkspaceTab, string>> = {
  basic: "基础资料",
  "line-profile": "当前线设定",
  growth: "状态与经历",
  voice: "声音",
};

const PROFILE_FIELDS: readonly {
  readonly key: ProfileFieldKey;
  readonly label: string;
  readonly multiline?: boolean;
  readonly list?: boolean;
  readonly placeholder?: string;
}[] = [
  { key: "public_identity", label: "现实身份", placeholder: "当前对外可见的身份" },
  { key: "true_identity", label: "真实身份", placeholder: "作者掌握的真实身份" },
  { key: "cover_identity", label: "掩护身份", placeholder: "伪装或临时使用的身份" },
  { key: "birth_year", label: "出生年", placeholder: "可写年份、纪年或未知" },
  { key: "birth_calendar_id", label: "出生历法", placeholder: "如公历、帝国历或自定义历法" },
  { key: "birth_information", label: "出生信息", multiline: true },
  { key: "age_at_story_start_note", label: "开篇年龄说明" },
  { key: "occupation", label: "职业" },
  { key: "personality", label: "初始性格", multiline: true },
  { key: "goals", label: "目标", multiline: true, list: true, placeholder: "每行一项" },
  { key: "flaws", label: "缺陷", multiline: true, list: true, placeholder: "每行一项" },
  { key: "secrets", label: "秘密", multiline: true, list: true, placeholder: "每行一项，仅作者可见" },
  { key: "growth_direction", label: "成长方向", multiline: true },
];

const WRITING_PROFILE_KEYS = new Set<ProfileFieldKey>([
  "occupation", "personality", "goals", "flaws", "secrets", "growth_direction",
]);
const IDENTITY_PROFILE_KEYS = new Set<ProfileFieldKey>([
  "public_identity", "true_identity", "cover_identity",
]);
const BIRTH_PROFILE_KEYS = new Set<ProfileFieldKey>([
  "birth_year", "birth_calendar_id", "birth_information", "age_at_story_start_note",
]);

function errorFieldId(baseId: string, field: string): string {
  const normalized = field
    .replace(/^character\./, "")
    .replace(/^profile\./, "")
    .replace(/\.\d+(?:\..*)?$/, "");
  const scope = field.startsWith("profile.") ? "profile" : "character";
  return `${baseId}-field-${scope}-${normalized.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function workspaceOperationKey(scope: "correction" | "revert"): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `character-${scope}:${random}`;
}

export function createCharacterWorkspaceDialog(
  React: CharacterReactRuntime,
  portal?: CharacterWorkspacePortalRuntime,
) {
  const h = React.createElement;

  return function CharacterWorkspaceDialog(props: CharacterWorkspaceDialogProps): ElementNode {
    const initial = props.workspace;
    const [workspace, setWorkspace] = React.useState<CharacterWorkspaceV2>(initial);
    const [rootDraft, setRootDraft] = React.useState<CharacterRootDraft>(() => rootDraftFromWorkspace(initial));
    const [profileDraft, setProfileDraft] = React.useState<CharacterProfileDraft>(() => profileDraftFromWorkspace(initial));
    const [activeTab, setActiveTab] = React.useState<CharacterWorkspaceTab>("basic");
    const [saving, setSaving] = React.useState(false);
    const [selecting, setSelecting] = React.useState(false);
    const [error, setError] = React.useState<CharacterWorkspaceActionError | null>(null);
    const [historyOpen, setHistoryOpen] = React.useState(false);
    const [historyPage, setHistoryPage] = React.useState<CharacterFactHistoryPageV2 | null>(null);
    const [historyLoading, setHistoryLoading] = React.useState(false);
    const [historyLoadingMore, setHistoryLoadingMore] = React.useState(false);
    const [historyError, setHistoryError] = React.useState<string | null>(null);
    const [historyEffectiveState, setHistoryEffectiveState] = React.useState<CharacterFactEffectiveState | "all">("all");
    const [historyHealth, setHistoryHealth] = React.useState<CharacterFactHealth | "all">("all");
    const [historyRefresh, setHistoryRefresh] = React.useState(0);
    const [correctionFact, setCorrectionFact] = React.useState<ProjectedFactViewV2 | null>(null);
    const [correctionObjectText, setCorrectionObjectText] = React.useState("");
    const [correctionReason, setCorrectionReason] = React.useState("");
    const [correctionSaving, setCorrectionSaving] = React.useState(false);
    const [correctionError, setCorrectionError] = React.useState<string | null>(null);
    const [batchImpact, setBatchImpact] = React.useState<IntelligenceBatchRevertImpactV1 | null>(null);
    const [batchReason, setBatchReason] = React.useState("");
    const [batchSaving, setBatchSaving] = React.useState(false);
    const [batchError, setBatchError] = React.useState<string | null>(null);
    const [sourceFact, setSourceFact] = React.useState<ProjectedFactViewV2 | null>(null);
    const [sourceRevision, setSourceRevision] = React.useState<CharacterSourceRevisionV1 | null>(null);
    const [sourceResolution, setSourceResolution] = React.useState<SourceRangeResolution | null>(null);
    const [sourceLoading, setSourceLoading] = React.useState(false);
    const [sourceError, setSourceError] = React.useState<string | null>(null);
    const [identityOpen, setIdentityOpen] = React.useState(true);
    const [birthOpen, setBirthOpen] = React.useState(() => [
      "birth_year",
      "birth_calendar_id",
      "birth_information",
      "age_at_story_start_note",
    ].some((key) => Boolean(initial.selected_instance.profile[key])));
    const reactInstanceId = React.useId?.();
    const instanceIdSuffix = reactInstanceId?.replace(/[^a-zA-Z0-9_-]/g, "");
    const baseIdRef = React.useRef(
      `character-workspace-${workspace.character.id.replace(/[^a-zA-Z0-9_-]/g, "-")}${
        instanceIdSuffix ? `-${instanceIdSuffix}` : ""
      }`,
    );
    const bodyRef = React.useRef<HTMLElement | null>(null);
    const tabScrollRef = React.useRef<Record<CharacterWorkspaceTab, number>>({
      basic: 0,
      "line-profile": 0,
      growth: 0,
      voice: 0,
    });
    const lastPropWorkspaceRef = React.useRef(initial);
    const drawerTriggerRef = React.useRef<DrawerTrigger | null>(null);
    const drawerWasOpenRef = React.useRef(false);
    const sourceRequestGenerationRef = React.useRef(0);
    const baseId = baseIdRef.current;
    const dialogId = `${baseId}-dialog`;
    const currentStateTitleId = `${baseId}-current-state-title`;
    const recentChangesTitleId = `${baseId}-recent-changes-title`;
    const factHistoryTitleId = `${baseId}-fact-history-title`;
    const correctionDialogId = `${baseId}-correction-dialog`;
    const correctionTitleId = `${baseId}-correction-title`;
    const batchRevertDialogId = `${baseId}-batch-revert-dialog`;
    const batchRevertTitleId = `${baseId}-batch-revert-title`;
    const sourceDialogId = `${baseId}-source-dialog`;
    const sourceTitleId = `${baseId}-source-title`;
    const activeSource = sourceFact?.source ?? null;
    const drawerOpen = Boolean(correctionFact || batchImpact || activeSource);
    const activeDrawerId = correctionFact
      ? correctionDialogId
      : batchImpact
        ? batchRevertDialogId
        : activeSource
          ? sourceDialogId
          : null;
    const dirty = hasRootChanges(workspace, rootDraft) || hasProfileChanges(workspace, profileDraft);
    const factRiskCount = workspace.writing_state.risk_summary.conflict_count
      + workspace.writing_state.risk_summary.ambiguous_count
      + workspace.writing_state.risk_summary.invalid_source_count;
    const showCharacterDraftActions = activeTab !== "voice" || dirty;
    const multiTimeline = isMultiTimeline(workspace);
    const requestClose = (): void => {
      if (!props.onRequestClose) return;
      if (dirty && typeof window !== "undefined"
        && !window.confirm("人物卡尚有未保存修改，确定离开吗？")) return;
      props.onRequestClose();
    };

    const applyWorkspace = (next: CharacterWorkspaceV2): void => {
      setWorkspace(next);
      setRootDraft(rootDraftFromWorkspace(next));
      setProfileDraft(profileDraftFromWorkspace(next));
      setHistoryPage(null);
      setHistoryRefresh((value) => value + 1);
      setError(null);
    };

    React.useEffect(() => {
      ensureCharacterWorkspaceStyles();
    }, []);

    React.useEffect(() => {
      if (typeof document === "undefined") return;
      const previouslyFocused = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      const focusDialog = (): void => document.getElementById(dialogId)?.focus();
      if (typeof queueMicrotask === "function") queueMicrotask(focusDialog);
      else focusDialog();
      return () => {
        if (!previouslyFocused) return;
        const modality = previouslyFocused.dataset.characterOpenModality;
        previouslyFocused.focus({ preventScroll: true });
        if (modality === "pointer") previouslyFocused.blur();
        delete previouslyFocused.dataset.characterOpenModality;
      };
    }, []);

    React.useEffect(() => {
      if (!activeDrawerId || typeof document === "undefined") return;
      const focusDrawer = (): void => {
        const drawer = document.getElementById(activeDrawerId);
        if (!drawer) return;
        const closeButton = drawer.querySelector<HTMLButtonElement>(
          '[data-character-drawer-close="true"]:not([disabled])',
        );
        (closeButton ?? drawer).focus({ preventScroll: true });
      };
      if (typeof queueMicrotask === "function") queueMicrotask(focusDrawer);
      else focusDrawer();
    }, [activeDrawerId]);

    React.useEffect(() => {
      if (drawerOpen) {
        drawerWasOpenRef.current = true;
        return;
      }
      if (!drawerWasOpenRef.current) return;
      drawerWasOpenRef.current = false;
      const returnTarget = drawerTriggerRef.current;
      drawerTriggerRef.current = null;
      const restoreDrawerFocus = (): void => {
        if (typeof document === "undefined") return;
        const trigger = returnTarget?.element;
        const triggerDisabled = Boolean(
          trigger && "disabled" in trigger && (trigger as HTMLButtonElement).disabled,
        );
        if (trigger?.isConnected && !triggerDisabled) {
          trigger.focus({ preventScroll: true });
          return;
        }
        const fallbackIds = [
          returnTarget?.fallbackId,
          recentChangesTitleId,
          factHistoryTitleId,
          `${baseId}-tab-growth`,
        ].filter((value, index, values): value is string => Boolean(value) && values.indexOf(value) === index);
        for (const fallbackId of fallbackIds) {
          const fallback = document.getElementById(fallbackId);
          if (!fallback) continue;
          fallback.focus({ preventScroll: true });
          return;
        }
      };
      if (typeof queueMicrotask === "function") queueMicrotask(restoreDrawerFocus);
      else restoreDrawerFocus();
    }, [drawerOpen]);

    React.useEffect(() => () => {
      sourceRequestGenerationRef.current += 1;
    }, []);

    React.useEffect(() => {
      if (lastPropWorkspaceRef.current !== props.workspace) {
        if (!dirty) {
          lastPropWorkspaceRef.current = props.workspace;
          applyWorkspace(props.workspace);
        }
      }
    }, [props.workspace, dirty]);

    React.useEffect(() => {
      if (!error?.field_errors) return;
      const firstField = Object.keys(error.field_errors)[0];
      if (!firstField) return;
      if (["public_identity", "true_identity", "cover_identity"].some((key) => firstField.endsWith(key))) {
        setIdentityOpen(true);
      }
      if (["birth_year", "birth_calendar_id", "birth_information", "age_at_story_start_note"].some((key) => firstField.endsWith(key))) {
        setBirthOpen(true);
      }
      const focusTarget = (): void => {
        if (typeof document === "undefined") return;
        document.getElementById(errorFieldId(baseId, firstField))?.focus();
      };
      if (typeof queueMicrotask === "function") queueMicrotask(focusTarget);
      else focusTarget();
    }, [error]);

    React.useEffect(() => {
      if (!historyOpen || !props.onLoadFacts) return;
      let cancelled = false;
      setHistoryLoading(true);
      setHistoryError(null);
      void props.onLoadFacts({
        limit: 20,
        effective_state: historyEffectiveState,
        health: historyHealth,
      }).then((page) => {
        if (!cancelled) setHistoryPage(page);
      }).catch((reason) => {
        if (!cancelled) setHistoryError(normalizeActionError(reason).message);
      }).finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
      return () => { cancelled = true; };
    }, [
      historyOpen,
      historyEffectiveState,
      historyHealth,
      historyRefresh,
      workspace.selected_timeline.id,
      workspace.selected_instance.id,
    ]);

    const loadMoreFacts = async (): Promise<void> => {
      if (!props.onLoadFacts || !historyPage?.next_cursor || historyLoadingMore) return;
      setHistoryLoadingMore(true);
      setHistoryError(null);
      try {
        const next = await props.onLoadFacts({
          cursor: historyPage.next_cursor,
          limit: 20,
          effective_state: historyEffectiveState,
          health: historyHealth,
        });
        setHistoryPage({
          ...next,
          items: [...historyPage.items, ...next.items],
        });
      } catch (reason) {
        setHistoryError(normalizeActionError(reason).message);
      } finally {
        setHistoryLoadingMore(false);
      }
    };

    const rememberDrawerTrigger = (trigger: HTMLElement, fallbackId: string): void => {
      drawerTriggerRef.current = { element: trigger, fallbackId };
    };

    const invalidateSourceRequest = (): void => {
      sourceRequestGenerationRef.current += 1;
    };

    const clearSource = (): void => {
      invalidateSourceRequest();
      setSourceFact(null);
      setSourceRevision(null);
      setSourceResolution(null);
      setSourceError(null);
      setSourceLoading(false);
    };

    const openCorrection = (
      fact: ProjectedFactViewV2,
      trigger: HTMLElement,
      fallbackId: string,
    ): void => {
      rememberDrawerTrigger(trigger, fallbackId);
      invalidateSourceRequest();
      setBatchImpact(null);
      setSourceFact(null);
      setCorrectionFact(fact);
      setCorrectionObjectText(fact.object_text);
      setCorrectionReason("");
      setCorrectionError(null);
    };

    const closeCorrection = (): void => {
      if (!correctionFact || correctionSaving) return;
      const changed = correctionObjectText.trim() !== correctionFact.object_text.trim()
        || Boolean(correctionReason.trim());
      if (changed && typeof window !== "undefined"
        && !window.confirm("事实修正尚未提交，确定放弃吗？")) return;
      setCorrectionFact(null);
    };

    const submitCorrection = async (): Promise<void> => {
      if (!correctionFact || !props.onCorrectFact || correctionSaving) return;
      setCorrectionSaving(true);
      setCorrectionError(null);
      try {
        const next = await props.onCorrectFact(correctionFact.id, {
          schema_version: "story-fact-correction/1",
          operation_key: workspaceOperationKey("correction"),
          expected_story_ledger_version: workspace.story_ledger_version,
          reason: correctionReason.trim(),
          replacement: { object_text: correctionObjectText.trim() },
        });
        applyWorkspace(next);
        setCorrectionFact(null);
      } catch (reason) {
        setCorrectionError(normalizeActionError(reason).message);
      } finally {
        setCorrectionSaving(false);
      }
    };

    const closeBatchRevert = (): void => {
      if (batchSaving) return;
      setBatchImpact(null);
    };

    const previewBatchRevert = async (
      fact: ProjectedFactViewV2,
      trigger: HTMLElement,
      fallbackId: string,
    ): Promise<void> => {
      const batchId = fact.source?.commit_batch_id;
      if (!batchId || !props.onPreviewBatchRevert) return;
      rememberDrawerTrigger(trigger, fallbackId);
      invalidateSourceRequest();
      setCorrectionFact(null);
      setSourceFact(null);
      setBatchError(null);
      try {
        setBatchImpact(await props.onPreviewBatchRevert(batchId));
        setBatchReason("");
      } catch (reason) {
        setHistoryError(normalizeActionError(reason).message);
      }
    };

    const submitBatchRevert = async (): Promise<void> => {
      if (!batchImpact || !props.onRevertBatch || batchSaving) return;
      setBatchSaving(true);
      setBatchError(null);
      try {
        const next = await props.onRevertBatch(batchImpact.batch_id, {
          operation_key: workspaceOperationKey("revert"),
          expected_story_ledger_version: workspace.story_ledger_version,
          reason: batchReason.trim() || null,
        });
        applyWorkspace(next);
        setBatchImpact(null);
      } catch (reason) {
        setBatchError(normalizeActionError(reason).message);
      } finally {
        setBatchSaving(false);
      }
    };

    const openSource = async (
      fact: ProjectedFactViewV2,
      trigger: HTMLElement,
      fallbackId: string,
    ): Promise<void> => {
      if (!fact.source || !props.onLoadSource) return;
      rememberDrawerTrigger(trigger, fallbackId);
      const requestGeneration = sourceRequestGenerationRef.current + 1;
      sourceRequestGenerationRef.current = requestGeneration;
      setCorrectionFact(null);
      setBatchImpact(null);
      setSourceFact(fact);
      setSourceRevision(null);
      setSourceResolution(null);
      setSourceError(null);
      setSourceLoading(true);
      try {
        const revision = await props.onLoadSource(
          fact.source.document_id,
          fact.source.revision_id,
        );
        if (requestGeneration !== sourceRequestGenerationRef.current) return;
        setSourceRevision(revision);
        if (
          fact.source.source_start === null
          || fact.source.source_end === null
          || fact.source.source_range_hash === null
        ) {
          setSourceResolution({
            status: "fallback",
            reason: "invalid_range",
            excerpt: [...fact.source.source_excerpt].slice(0, 500).join(""),
            excerptTruncated: fact.source.source_excerpt_truncated,
          });
        } else {
          const resolution = await resolveCharacterSourceRange(
            revision.content_text,
            revision.content_hash,
            {
              source_content_hash: fact.source.source_content_hash,
              source_coordinate: fact.source.source_coordinate,
              source_start: fact.source.source_start,
              source_end: fact.source.source_end,
              source_range_hash: fact.source.source_range_hash,
              source_excerpt: fact.source.source_excerpt,
              source_excerpt_truncated: fact.source.source_excerpt_truncated,
            },
          );
          if (requestGeneration !== sourceRequestGenerationRef.current) return;
          setSourceResolution(resolution);
        }
      } catch (reason) {
        if (requestGeneration === sourceRequestGenerationRef.current) {
          setSourceError(normalizeActionError(reason).message);
        }
      } finally {
        if (requestGeneration === sourceRequestGenerationRef.current) {
          setSourceLoading(false);
        }
      }
    };

    const activateTab = (tab: CharacterWorkspaceTab): void => {
      if (bodyRef.current) tabScrollRef.current[activeTab] = bodyRef.current.scrollTop;
      setActiveTab(tab);
      if (typeof document !== "undefined") {
        const focus = (): void => {
          if (bodyRef.current) bodyRef.current.scrollTop = tabScrollRef.current[tab];
          document.getElementById(`${baseId}-tab-${tab}`)?.focus();
        };
        if (typeof queueMicrotask === "function") queueMicrotask(focus);
        else focus();
      }
    };

    const onTabKeyDown = (tab: CharacterWorkspaceTab, event: KeyboardEventLike): void => {
      const next = characterWorkspaceTabFromKey(tab, event.key);
      if (!next) return;
      event.preventDefault();
      activateTab(next);
    };

    const onDialogKeyDown = (event: KeyboardEventLike): void => {
      if (event.key === "Escape" && correctionFact) {
        event.preventDefault();
        closeCorrection();
        return;
      }
      if (event.key === "Escape" && batchImpact) {
        event.preventDefault();
        closeBatchRevert();
        return;
      }
      if (event.key === "Escape" && sourceFact) {
        event.preventDefault();
        clearSource();
        return;
      }
      if (event.key === "Escape" && !saving && props.onRequestClose) {
        event.preventDefault();
        requestClose();
        return;
      }
      if (event.key !== "Tab" || typeof document === "undefined") return;
      const dialog = document.getElementById(dialogId);
      if (!dialog) return;
      const focusScope = activeDrawerId
        ? document.getElementById(activeDrawerId)
        : dialog;
      if (!focusScope) return;
      const focusable = Array.from(focusScope.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => (
        !element.closest('[inert], [hidden], [aria-hidden="true"]')
        && element.getAttribute("aria-hidden") !== "true"
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        focusScope.focus({ preventScroll: true });
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeIndex = focusable.indexOf(document.activeElement as HTMLElement);
      if (activeIndex === -1) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus({ preventScroll: true });
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus({ preventScroll: true });
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus({ preventScroll: true });
      }
    };

    const resetDrafts = (): void => {
      setRootDraft(rootDraftFromWorkspace(workspace));
      setProfileDraft(profileDraftFromWorkspace(workspace));
      setError(null);
    };

    const save = async (): Promise<void> => {
      if (!dirty || saving || !props.onSave) return;
      if (!rootDraft.name.trim()) {
        const nextError: CharacterWorkspaceActionError = {
          code: "validation_failed",
          message: "请修正人物卡中的必填项。",
          field_errors: { "character.name": "人物姓名不能为空。" },
        };
        activateTab("basic");
        setError(nextError);
        return;
      }
      const profileValidation = validateCharacterProfile(
        profileDraft,
        workspace.selected_instance.profile_schema_version === 1 ? 1 : 2,
      );
      if (hasProfileChanges(workspace, profileDraft) && !profileValidation.ok) {
        activateTab("line-profile");
        setError({
          code: "validation_failed",
          message: "请核对当前线设定中的字段后再保存。",
          field_errors: Object.fromEntries(
            Object.entries(profileValidation.fieldErrors).map(([key, value]) => [`profile.${key}`, value]),
          ),
        });
        return;
      }
      setSaving(true);
      setError(null);
      try {
        const normalizedProfile = profileValidation.ok
          ? { ...profileValidation.profile }
          : profileDraft;
        const next = await props.onSave(buildSaveCommand(workspace, rootDraft, normalizedProfile));
        applyWorkspace(next);
      } catch (reason) {
        const nextError = normalizeActionError(reason);
        const firstField = Object.keys(nextError.field_errors ?? {})[0];
        if (firstField) activateTab(tabForField(firstField));
        // Deliberately keep both drafts unchanged on validation and CAS conflicts.
        setError(nextError);
      } finally {
        setSaving(false);
      }
    };

    const changeSelection = async (timelineId: string, requestedInstanceId?: string): Promise<void> => {
      if (!props.onSelectionChange || selecting) return;
      if (dirty) {
        setError({
          code: "unsaved_changes",
          message: "请先保存或撤销当前修改，再切换时间线或人物版本。",
        });
        return;
      }
      const possibleInstances = workspace.instances.filter(
        (instance) => instance.origin_timeline_id === timelineId,
      );
      const instanceId =
        requestedInstanceId && possibleInstances.some((instance) => instance.id === requestedInstanceId)
          ? requestedInstanceId
          : possibleInstances[0]?.id;
      if (!instanceId) {
        setError({ code: "instance_required", message: "该时间线没有可选的人物版本。" });
        return;
      }
      setSelecting(true);
      setError(null);
      try {
        applyWorkspace(await props.onSelectionChange({ timelineId, instanceId }));
      } catch (reason) {
        setError(normalizeActionError(reason));
      } finally {
        setSelecting(false);
      }
    };

    const renderField = (
      id: string,
      label: string,
      value: string,
      onChange: (value: string) => void,
      options: { readonly wide?: boolean; readonly span?: 3 | 6 | 12; readonly multiline?: boolean; readonly required?: boolean; readonly placeholder?: string } = {},
    ): ElementNode => {
      const message = fieldError(error, id);
      const inputId = errorFieldId(baseId, id);
      const describedBy = message ? `${inputId}-error` : undefined;
      const controlProps: Record<string, unknown> = {
        id: inputId,
        value,
        required: options.required,
        placeholder: options.placeholder,
        "aria-invalid": Boolean(message),
        "aria-describedby": describedBy,
        onChange: (event: InputChangeEvent) => onChange(event.target.value),
      };
      return h(
        "label",
        { className: `anw-character-workspace-field${options.wide ? " anw-character-workspace-field--wide" : ""}${options.span ? ` anw-character-workspace-field--span-${options.span}` : ""}` },
        h("span", null, label, options.required ? " *" : ""),
        options.multiline ? h("textarea", controlProps) : h("input", { ...controlProps, type: "text" }),
        message ? h("span", { id: describedBy, className: "anw-character-workspace-error" }, message) : null,
      );
    };

    const renderRoleField = (): ElementNode => {
      const inputId = errorFieldId(baseId, "character.role_type");
      const message = fieldError(error, "character.role_type");
      const describedBy = message ? `${inputId}-error` : undefined;
      return h(
        "label",
        { className: "anw-character-workspace-field anw-character-workspace-field--span-3" },
        h("span", null, "角色定位"),
        h(
          "select",
          {
            id: inputId,
            value: rootDraft.role_type,
            "aria-invalid": Boolean(message),
            "aria-describedby": describedBy,
            onChange: (event: InputChangeEvent) => setRootDraft({ ...rootDraft, role_type: event.target.value }),
          },
          h("option", { value: "main" }, "主角"),
          h("option", { value: "supporting" }, "配角"),
        ),
        message ? h("span", { id: describedBy, className: "anw-character-workspace-error" }, message) : null,
      );
    };

    const basicPanel = h(
      "section",
      {
        id: `${baseId}-panel-basic`,
        role: "tabpanel",
        "aria-labelledby": `${baseId}-tab-basic`,
        hidden: activeTab !== "basic",
        className: "anw-character-workspace-panel",
      },
      h(
        "div",
        { className: "anw-character-workspace-section-heading" },
        h("div", null, h("h3", null, "人物基础信息"), h("p", null, "跨时间线共用的姓名、定位与公共介绍。")),
        h("span", { className: "anw-character-workspace-editable-badge" }, "可编辑"),
      ),
      h(
        "div",
        { className: "anw-character-workspace-form-grid anw-character-workspace-form-grid--basic" },
        renderField("character.name", "人物姓名", rootDraft.name, (name) => setRootDraft({ ...rootDraft, name }), {
          required: true,
          span: 6,
        }),
        renderRoleField(),
        renderField("character.gender", "性别", rootDraft.gender, (gender) =>
          setRootDraft({ ...rootDraft, gender }),
          { span: 3 },
        ),
        renderField("character.core_theme", "核心主题", rootDraft.core_theme, (core_theme) =>
          setRootDraft({ ...rootDraft, core_theme }),
          { span: 12 },
        ),
        renderField(
          "character.description",
          "公共小传",
          rootDraft.description,
          (description) => setRootDraft({ ...rootDraft, description }),
          { multiline: true, wide: true, span: 12 },
        ),
      ),
      h(
        "div",
        { className: "anw-character-workspace-overview-grid" },
        h(
          "div",
          { className: "anw-character-workspace-readonly-card" },
          h("h3", null, "称谓与别名"),
          workspace.aliases.length === 0
            ? h("p", { className: "anw-character-workspace-muted-value" }, "尚未记录别名")
            : h("p", null, workspace.aliases.map((alias) => alias.alias).join("、")),
        ),
        h(
          "div",
          { className: "anw-character-workspace-readonly-card" },
          h("h3", null, "引用概览"),
          h(
            "div",
            { className: "anw-character-workspace-metrics", "aria-label": "人物引用统计" },
            h("span", null, h("strong", null, workspace.relationships.length), "关系"),
            h("span", null, h("strong", null, workspace.chapter_references.length), "章节引用"),
          ),
        ),
      ),
    );

    const profileSchemaVersion = workspace.selected_instance.profile_schema_version === 1 ? 1 : 2;
    const writingCompletion = characterProfileGroupCompletion(profileDraft, profileSchemaVersion, "writing");
    const identityCompletion = characterProfileGroupCompletion(profileDraft, profileSchemaVersion, "identity");
    const birthCompletion = characterProfileGroupCompletion(profileDraft, profileSchemaVersion, "birth");
    const renderProfileField = (field: (typeof PROFILE_FIELDS)[number]): ElementNode => renderField(
      `profile.${field.key}`,
      field.label,
      valueAsText(profileDraft[field.key]),
      (value) => setProfileDraft(updateProfileText(profileDraft, field.key, value, Boolean(field.list))),
      {
        multiline: field.multiline,
        wide: field.multiline,
        placeholder: field.placeholder,
      },
    );

    const profilePanel = h(
      "section",
      {
        id: `${baseId}-panel-line-profile`,
        role: "tabpanel",
        "aria-labelledby": `${baseId}-tab-line-profile`,
        hidden: activeTab !== "line-profile",
        className: "anw-character-workspace-panel",
      },
      h(
        "div",
        { className: "anw-character-workspace-section-heading" },
        h("div", null, h("h3", null, "当前线设定"), h("p", null, "记录身份、目标、缺陷与作者掌握的秘密。")),
        h("span", { className: "anw-character-workspace-editable-badge" }, "可编辑"),
      ),
      multiTimeline
        ? h(
            "div",
            { className: "anw-character-workspace-readonly-card" },
            h("h3", null, workspace.selected_instance.display_label || "当前人物版本"),
            h("p", null, continuityLabel(workspace.selected_instance.continuity_kind)),
          )
        : null,
      h(
        "div",
        { className: "anw-character-profile-layout" },
        h(
          "section",
          { className: "anw-character-profile-main" },
          h("div", { className: "anw-character-profile-group-title" }, h("h4", null, "写作核心"), h("span", null, `已填写 ${writingCompletion.filled}/${writingCompletion.total}`)),
          h(
            "div",
            { className: "anw-character-workspace-form-grid anw-character-workspace-form-grid--writing" },
            ...PROFILE_FIELDS.filter((field) => WRITING_PROFILE_KEYS.has(field.key)).map(renderProfileField),
          ),
        ),
        h(
          "aside",
          { className: "anw-character-profile-side" },
          h(
            "details",
            { open: identityOpen, onToggle: (event: ToggleEventLike) => setIdentityOpen(event.currentTarget.open) },
            h("summary", null, h("span", null, "身份层"), h("small", null, `已填写 ${identityCompletion.filled}/${identityCompletion.total}`)),
            h("div", { className: "anw-character-profile-detail-fields" }, ...PROFILE_FIELDS.filter((field) => IDENTITY_PROFILE_KEYS.has(field.key)).map(renderProfileField)),
          ),
          h(
            "details",
            { open: birthOpen, onToggle: (event: ToggleEventLike) => setBirthOpen(event.currentTarget.open) },
            h("summary", null, h("span", null, "出生与年龄"), h("small", null, `已填写 ${birthCompletion.filled}/${birthCompletion.total}`)),
            h("div", { className: "anw-character-profile-detail-fields" }, ...PROFILE_FIELDS.filter((field) => BIRTH_PROFILE_KEYS.has(field.key) && (profileSchemaVersion === 2 || field.key !== "age_at_story_start_note")).map(renderProfileField)),
          ),
        ),
      ),
    );

    const growthPanel = h(
      "section",
      {
        id: `${baseId}-panel-growth`,
        role: "tabpanel",
        "aria-labelledby": `${baseId}-tab-growth`,
        hidden: activeTab !== "growth",
        className: "anw-character-workspace-panel",
        "aria-label": "状态与经历，只读",
      },
      h(
        "div",
        { className: "anw-character-workspace-section-heading" },
        h("div", null, h("h3", null, "状态与经历"), h("p", null, "先看续写所需当前状态，需要时再展开可审计事实历史。")),
        h("span", { className: "anw-character-workspace-readonly-badge" }, "事实投影 · 只读"),
      ),
      renderCharacterStatePanel(React, {
        currentStateTitleId,
        recentChangesTitleId,
        workspace,
        historyOpen,
        onToggleHistory: () => setHistoryOpen((value) => !value),
        onOpenSource: (fact, trigger) => void openSource(fact, trigger, recentChangesTitleId),
        onCorrectFact: (fact, trigger) => openCorrection(fact, trigger, recentChangesTitleId),
      }),
      historyOpen
        ? renderCharacterFactHistory(React, {
            titleId: factHistoryTitleId,
            page: historyPage,
            loading: historyLoading,
            loadingMore: historyLoadingMore,
            error: historyError,
            effectiveState: historyEffectiveState,
            health: historyHealth,
            onEffectiveStateChange: (value) => {
              setHistoryEffectiveState(value);
              setHistoryPage(null);
            },
            onHealthChange: (value) => {
              setHistoryHealth(value);
              setHistoryPage(null);
            },
            onLoadMore: () => void loadMoreFacts(),
            onOpenSource: (fact, trigger) => void openSource(fact, trigger, factHistoryTitleId),
            onCorrectFact: (fact, trigger) => openCorrection(fact, trigger, factHistoryTitleId),
            onPreviewBatchRevert: (fact, trigger) => void previewBatchRevert(fact, trigger, factHistoryTitleId),
          })
        : null,
    );

    const voicePanel = h(
      "section",
      {
        id: `${baseId}-panel-voice`,
        role: "tabpanel",
        "aria-labelledby": `${baseId}-tab-voice`,
        hidden: activeTab !== "voice",
        className: "anw-character-workspace-panel",
      },
      activeTab === "voice" && props.voiceSlot
        ? props.voiceSlot({
            novelId: workspace.novel_id,
            characterId: workspace.character.id,
            characterName: rootDraft.name,
            binding: workspace.voice_binding,
          })
        : h("div", { className: "anw-character-workspace-empty" }, "声音设置组件尚未接入。人物卡不会创建第二份声音数据。"),
    );

    const firstErrorField = Object.keys(error?.field_errors ?? {})[0];
    const instancesForSelectedTimeline = workspace.instances.filter(
      (instance) => instance.origin_timeline_id === workspace.selected_timeline.id,
    );

    const overlay = h(
      "div",
      {
        className: "anw-character-workspace-backdrop",
        onMouseDown: (event: PointerEventLike) => {
          if (event.target === event.currentTarget && !drawerOpen && !saving && props.onRequestClose) requestClose();
        },
      },
      h(
        "div",
        {
          id: dialogId,
          role: "dialog",
          "aria-modal": true,
          "aria-labelledby": props.titleId ?? `${baseId}-title`,
          "aria-describedby": `${baseId}-summary-description`,
          tabIndex: -1,
          onKeyDown: onDialogKeyDown,
          className: `anw-character-workspace-dialog${props.className ? ` ${props.className}` : ""}`,
        },
        h(
          "header",
          { className: "anw-character-workspace-summary", inert: drawerOpen ? "" : undefined, "aria-hidden": drawerOpen || undefined },
          h(
            "div",
            { className: "anw-character-workspace-heading" },
            h(
              "div",
              { className: "anw-character-workspace-identity" },
              h("span", { className: "anw-character-workspace-avatar", "aria-hidden": true }, (rootDraft.name || "人").slice(0, 1)),
              h(
                "div",
                null,
                h("h2", { id: props.titleId ?? `${baseId}-title` }, rootDraft.name || "未命名人物"),
                h(
                  "div",
                  { className: "anw-character-workspace-heading-meta", id: `${baseId}-summary-description` },
                  h("span", { className: `anw-character-workspace-role-badge is-${rootDraft.role_type}` }, characterRoleLabel(rootDraft.role_type)),
                  h("span", null, `正式人物卡 · v${workspace.character.version}`),
                  multiTimeline ? h("span", null, workspace.selected_timeline.name) : null,
                ),
              ),
            ),
            h(
              "div",
              { className: "anw-character-workspace-heading-actions" },
              dirty ? h("span", { className: "anw-character-workspace-unsaved", role: "status" }, "有未保存修改") : null,
              props.onRequestClose
                ? h(
                    "button",
                    {
                      type: "button",
                      className: "anw-character-workspace-close",
                      disabled: saving,
                      "aria-label": "关闭人物卡",
                      title: "关闭人物卡（Esc）",
                      onClick: requestClose,
                    },
                    "×",
                  )
                : null,
            ),
          ),
          multiTimeline
            ? h(
                "div",
                { className: "anw-character-workspace-selectors" },
                h(
                  "label",
                  { className: "anw-character-workspace-field" },
                  h("span", null, "时间线"),
                  h(
                    "select",
                    {
                      value: workspace.selected_timeline.id,
                      disabled: selecting || dirty,
                      "aria-describedby": dirty ? `${baseId}-selection-guidance` : undefined,
                      onChange: (event: InputChangeEvent) => void changeSelection(event.target.value),
                    },
                    ...workspace.timelines.map((timeline) =>
                      h("option", { key: timeline.id, value: timeline.id }, timeline.name),
                    ),
                  ),
                ),
                h(
                  "label",
                  { className: "anw-character-workspace-field" },
                  h("span", null, "人物版本"),
                  h(
                    "select",
                    {
                      value: workspace.selected_instance.id,
                      disabled: selecting || dirty,
                      "aria-describedby": dirty ? `${baseId}-selection-guidance` : undefined,
                      onChange: (event: InputChangeEvent) =>
                        void changeSelection(workspace.selected_timeline.id, event.target.value),
                    },
                    ...instancesForSelectedTimeline.map((instance) =>
                      h(
                        "option",
                        { key: instance.id, value: instance.id },
                        instance.display_label || continuityLabel(instance.continuity_kind),
                      ),
                    ),
                  ),
                ),
                dirty
                  ? h("p", { id: `${baseId}-selection-guidance`, className: "anw-character-workspace-meta" }, "切换前请先保存或撤销当前修改。")
                  : null,
              )
            : null,
        ),
        h(
          "nav",
          { className: "anw-character-workspace-tabs", role: "tablist", "aria-label": "人物卡栏目", inert: drawerOpen ? "" : undefined, "aria-hidden": drawerOpen || undefined },
          ...(["basic", "line-profile", "growth", "voice"] as const).map((tab) =>
            h(
              "button",
              {
                key: tab,
                id: `${baseId}-tab-${tab}`,
                type: "button",
                role: "tab",
                className: "anw-character-workspace-tab",
                "aria-selected": activeTab === tab,
                "aria-controls": `${baseId}-panel-${tab}`,
                tabIndex: activeTab === tab ? 0 : -1,
                onClick: () => activateTab(tab),
                onKeyDown: (event: KeyboardEventLike) => onTabKeyDown(tab, event),
              },
              h("span", null, TAB_LABELS[tab]),
              tab === "growth" && factRiskCount > 0
                ? h("span", { className: "anw-character-workspace-tab-count", "aria-label": `${factRiskCount} 项待核对` }, factRiskCount)
                : null,
            ),
          ),
        ),
        error
          ? h(
              "div",
              { className: "anw-character-workspace-alert", role: "alert", "aria-live": "assertive" },
              h("strong", null, error.code === "cas_conflict" ? "人物卡已在其他位置更新" : "操作未完成"),
              h("div", null, error.message),
              firstErrorField
                ? h(
                    "button",
                    {
                      type: "button",
                      onClick: () => {
                        activateTab(tabForField(firstErrorField));
                        if (typeof document !== "undefined") {
                          document.getElementById(errorFieldId(baseId, firstErrorField))?.focus();
                        }
                      },
                    },
                    "定位到需要处理的字段",
                  )
                : null,
            )
          : null,
        h("main", { ref: (element: HTMLElement | null) => { bodyRef.current = element; }, className: "anw-character-workspace-body", inert: drawerOpen ? "" : undefined, "aria-hidden": drawerOpen || undefined }, basicPanel, profilePanel, growthPanel, voicePanel),
        h(
          "footer",
          { className: "anw-character-workspace-footer", inert: drawerOpen ? "" : undefined, "aria-hidden": drawerOpen || undefined },
          h(
            "span",
            { className: "anw-character-workspace-meta" },
            activeTab === "growth"
              ? "状态与经历来自故事账本，仅供查看。"
              : activeTab === "voice"
                ? dirty
                  ? "其他栏目还有未保存修改；下方撤销和保存只处理人物卡字段。"
                  : "声音设置由共用声音组件独立保存。"
                : dirty
                  ? "修改尚未保存。"
                  : "人物卡已是最新状态。按 Esc 可关闭。",
          ),
          h(
            "div",
            { className: "anw-character-workspace-actions" },
            showCharacterDraftActions
              ? h(
                "button",
                {
                  type: "button",
                  className: "anw-character-workspace-button",
                  disabled: saving || !dirty,
                  onClick: resetDrafts,
                },
                "撤销修改",
              )
              : null,
            props.onRequestClose
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "anw-character-workspace-button",
                    disabled: saving,
                    onClick: requestClose,
                  },
                  "关闭",
                )
              : null,
            showCharacterDraftActions
              ? h(
                "button",
                {
                  type: "button",
                  className: "anw-character-workspace-button anw-character-workspace-button--primary",
                  disabled: saving || !dirty || !props.onSave,
                  onClick: () => void save(),
                },
                saving ? "正在保存…" : "保存人物卡",
              )
              : null,
          ),
        ),
        correctionFact
          ? renderCharacterFactCorrectionDrawer(React, {
              dialogId: correctionDialogId,
              titleId: correctionTitleId,
              fact: correctionFact,
              objectText: correctionObjectText,
              reason: correctionReason,
              saving: correctionSaving,
              error: correctionError,
              onObjectTextChange: setCorrectionObjectText,
              onReasonChange: setCorrectionReason,
              onSubmit: () => void submitCorrection(),
              onClose: () => {
                closeCorrection();
              },
            })
          : null,
        batchImpact
          ? renderCharacterBatchRevertDrawer(React, {
              dialogId: batchRevertDialogId,
              titleId: batchRevertTitleId,
              impact: batchImpact,
              reason: batchReason,
              saving: batchSaving,
              error: batchError,
              onReasonChange: setBatchReason,
              onSubmit: () => void submitBatchRevert(),
              onClose: closeBatchRevert,
            })
          : null,
        activeSource
          ? renderCharacterSourceViewer(React, {
              dialogId: sourceDialogId,
              titleId: sourceTitleId,
              source: activeSource,
              revision: sourceRevision,
              resolution: sourceResolution,
              loading: sourceLoading,
              error: sourceError,
              onClose: clearSource,
            })
          : null,
      ),
    );
    const portalContainer = portal?.getContainer();
    return portal && portalContainer
      ? portal.createPortal(overlay, portalContainer)
      : overlay;
  };
}
