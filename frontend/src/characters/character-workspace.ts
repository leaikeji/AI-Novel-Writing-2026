import type {
  CharacterWorkspaceActionError,
  CharacterWorkspaceSaveCommandV1,
  CharacterWorkspaceSelectionV1,
  CharacterWorkspaceV1,
  CharacterWorkspaceVoiceSlotProps,
  JsonValue,
} from "./contracts";
import {
  buildSaveCommand,
  characterFactDimensionLabel,
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

type StateSetter<T> = (value: T | ((previous: T) => T)) => void;
type ElementNode = unknown;

export interface CharacterReactRuntime {
  createElement(type: unknown, props?: Record<string, unknown> | null, ...children: unknown[]): ElementNode;
  useState<T>(initial: T | (() => T)): [T, StateSetter<T>];
  useEffect(effect: () => void | (() => void), dependencies?: readonly unknown[]): void;
  useRef<T>(initial: T): { current: T };
}

export interface CharacterWorkspaceDialogProps {
  readonly workspace: CharacterWorkspaceV1;
  readonly onSave?: (command: CharacterWorkspaceSaveCommandV1) => Promise<CharacterWorkspaceV1>;
  readonly onSelectionChange?: (
    selection: CharacterWorkspaceSelectionV1,
  ) => Promise<CharacterWorkspaceV1>;
  readonly voiceSlot?: (props: CharacterWorkspaceVoiceSlotProps) => ElementNode;
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

const TAB_LABELS: Readonly<Record<CharacterWorkspaceTab, string>> = {
  basic: "基础资料",
  "line-profile": "本线档案",
  growth: "成长与状态",
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

function displayJson(value: JsonValue): string {
  if (value === null) return "未记录";
  if (typeof value === "string") return value || "未记录";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => displayJson(item)).join("、") || "未记录";
  return Object.entries(value)
    .map(([key, item]) => `${key}：${displayJson(item)}`)
    .join("；");
}

function errorFieldId(baseId: string, field: string): string {
  const normalized = field
    .replace(/^character\./, "")
    .replace(/^profile\./, "")
    .replace(/\.\d+(?:\..*)?$/, "");
  const scope = field.startsWith("profile.") ? "profile" : "character";
  return `${baseId}-field-${scope}-${normalized.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

export function createCharacterWorkspaceDialog(React: CharacterReactRuntime) {
  const h = React.createElement;

  return function CharacterWorkspaceDialog(props: CharacterWorkspaceDialogProps): ElementNode {
    const initial = props.workspace;
    const [workspace, setWorkspace] = React.useState<CharacterWorkspaceV1>(initial);
    const [rootDraft, setRootDraft] = React.useState<CharacterRootDraft>(() => rootDraftFromWorkspace(initial));
    const [profileDraft, setProfileDraft] = React.useState<CharacterProfileDraft>(() => profileDraftFromWorkspace(initial));
    const [activeTab, setActiveTab] = React.useState<CharacterWorkspaceTab>("basic");
    const [saving, setSaving] = React.useState(false);
    const [selecting, setSelecting] = React.useState(false);
    const [error, setError] = React.useState<CharacterWorkspaceActionError | null>(null);
    const baseIdRef = React.useRef(
      `character-workspace-${workspace.character.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`,
    );
    const lastPropWorkspaceRef = React.useRef(initial);
    const baseId = baseIdRef.current;
    const dialogId = `${baseId}-dialog`;
    const dirty = hasRootChanges(workspace, rootDraft) || hasProfileChanges(workspace, profileDraft);
    const multiTimeline = isMultiTimeline(workspace);
    const requestClose = (): void => {
      if (!props.onRequestClose) return;
      if (dirty && typeof window !== "undefined"
        && !window.confirm("人物卡尚有未保存修改，确定离开吗？")) return;
      props.onRequestClose();
    };

    const applyWorkspace = (next: CharacterWorkspaceV1): void => {
      setWorkspace(next);
      setRootDraft(rootDraftFromWorkspace(next));
      setProfileDraft(profileDraftFromWorkspace(next));
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
      return () => previouslyFocused?.focus();
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
      const focusTarget = (): void => {
        if (typeof document === "undefined") return;
        document.getElementById(errorFieldId(baseId, firstField))?.focus();
      };
      if (typeof queueMicrotask === "function") queueMicrotask(focusTarget);
      else focusTarget();
    }, [error]);

    const activateTab = (tab: CharacterWorkspaceTab): void => {
      setActiveTab(tab);
      if (typeof document !== "undefined") {
        const focus = (): void => document.getElementById(`${baseId}-tab-${tab}`)?.focus();
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
      if (event.key === "Escape" && !saving && props.onRequestClose) {
        event.preventDefault();
        requestClose();
        return;
      }
      if (event.key !== "Tab" || typeof document === "undefined") return;
      const dialog = document.getElementById(dialogId);
      if (!dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
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
        setActiveTab("basic");
        setError(nextError);
        return;
      }
      setSaving(true);
      setError(null);
      try {
        const next = await props.onSave(buildSaveCommand(workspace, rootDraft, profileDraft));
        applyWorkspace(next);
      } catch (reason) {
        const nextError = normalizeActionError(reason);
        const firstField = Object.keys(nextError.field_errors ?? {})[0];
        if (firstField) setActiveTab(tabForField(firstField));
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
      options: { readonly wide?: boolean; readonly multiline?: boolean; readonly required?: boolean; readonly placeholder?: string } = {},
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
        { className: `anw-character-workspace-field${options.wide ? " anw-character-workspace-field--wide" : ""}` },
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
        { className: "anw-character-workspace-field" },
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
        }),
        renderRoleField(),
        renderField("character.gender", "性别", rootDraft.gender, (gender) =>
          setRootDraft({ ...rootDraft, gender }),
        ),
        renderField("character.core_theme", "核心主题", rootDraft.core_theme, (core_theme) =>
          setRootDraft({ ...rootDraft, core_theme }),
        ),
        renderField(
          "character.description",
          "公共小传",
          rootDraft.description,
          (description) => setRootDraft({ ...rootDraft, description }),
          { multiline: true, wide: true },
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
        h("div", null, h("h3", null, "当前故事线档案"), h("p", null, "记录身份、目标、缺陷与作者掌握的秘密。")),
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
        { className: "anw-character-workspace-form-grid anw-character-workspace-form-grid--profile" },
        ...PROFILE_FIELDS.map((field) =>
          renderField(
            `profile.${field.key}`,
            field.label,
            valueAsText(profileDraft[field.key]),
            (value) =>
              setProfileDraft(updateProfileText(profileDraft, field.key, value, Boolean(field.list))),
            {
              multiline: field.multiline,
              wide: field.multiline,
              placeholder: field.placeholder,
            },
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
        "aria-label": "成长与状态，只读",
      },
      h(
        "div",
        { className: "anw-character-workspace-section-heading" },
        h("div", null, h("h3", null, "成长与当前状态"), h("p", null, "由已确认故事事实投影生成，需要回到事实账本修正来源。")),
        h("span", { className: "anw-character-workspace-readonly-badge" }, `${workspace.projected_state.current_facts.length} 条 · 只读`),
      ),
      workspace.projected_state.conflicts.length > 0
        ? h(
            "div",
            { className: "anw-character-workspace-alert", role: "status" },
            "当前状态存在冲突，请回到事实账本处理。",
            ...workspace.projected_state.conflicts.map((conflict) =>
              h("p", { key: conflict.conflict_key }, `${conflict.conflict_key}：${conflict.reason}`),
            ),
          )
        : null,
      workspace.projected_state.ambiguous_fact_ids.length > 0
        ? h("p", { className: "anw-character-workspace-readonly-card" }, "部分故事时间或状态依据不足，当前结果为不确定状态。")
        : null,
      workspace.projected_state.current_facts.length === 0
        ? h("div", { className: "anw-character-workspace-empty" }, "截至当前叙事位置，尚无已确认的成长状态。")
        : h(
            "div",
            { className: "anw-character-workspace-fact-grid" },
            ...workspace.projected_state.current_facts.map((fact) =>
              h(
                "article",
                { key: fact.id, className: "anw-character-workspace-readonly-card anw-character-workspace-fact-card" },
                h(
                  "header",
                  null,
                  h("h3", null, fact.predicate || characterFactDimensionLabel(fact.dimension)),
                  h(
                    "span",
                    null,
                    h("span", { className: "anw-character-workspace-sr-only" }, "事实维度："),
                    characterFactDimensionLabel(fact.dimension),
                  ),
                ),
                h("p", null, fact.object_text || displayJson(fact.details)),
                fact.story_sequence === null
                  ? null
                  : h("p", { className: "anw-character-workspace-meta" }, `故事序位 ${fact.story_sequence}`),
              ),
            ),
          ),
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

    return h(
      "div",
      {
        className: "anw-character-workspace-backdrop",
        onMouseDown: (event: PointerEventLike) => {
          if (event.target === event.currentTarget && !saving && props.onRequestClose) requestClose();
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
          { className: "anw-character-workspace-summary" },
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
          { className: "anw-character-workspace-tabs", role: "tablist", "aria-label": "人物卡栏目" },
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
                onClick: () => setActiveTab(tab),
                onKeyDown: (event: KeyboardEventLike) => onTabKeyDown(tab, event),
              },
              h("span", null, TAB_LABELS[tab]),
              tab === "growth" && workspace.projected_state.current_facts.length > 0
                ? h("span", { className: "anw-character-workspace-tab-count", "aria-hidden": true }, workspace.projected_state.current_facts.length)
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
                        setActiveTab(tabForField(firstErrorField));
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
        h("main", { className: "anw-character-workspace-body" }, basicPanel, profilePanel, growthPanel, voicePanel),
        h(
          "footer",
          { className: "anw-character-workspace-footer" },
          h(
            "span",
            { className: "anw-character-workspace-meta" },
            activeTab === "growth"
              ? "成长状态来自事实账本，仅供查看。"
              : activeTab === "voice"
                ? "声音设置由共用声音组件独立保存。"
                : dirty
                  ? "修改尚未保存。"
                  : "人物卡已是最新状态。按 Esc 可关闭。",
          ),
          h(
            "div",
            { className: "anw-character-workspace-actions" },
            h(
              "button",
              {
                type: "button",
                className: "anw-character-workspace-button",
                disabled: saving || !dirty,
                onClick: resetDrafts,
              },
              "撤销修改",
            ),
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
            h(
              "button",
              {
                type: "button",
                className: "anw-character-workspace-button anw-character-workspace-button--primary",
                disabled: saving || !dirty || !props.onSave,
                onClick: () => void save(),
              },
              saving ? "正在保存…" : "保存人物卡",
            ),
          ),
        ),
      ),
    );
  };
}
