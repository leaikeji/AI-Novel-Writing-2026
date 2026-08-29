import type {
  CharacterGenerationState,
  CharacterNameConflictResolution,
  CharacterRegenerationConfirmationState,
  CharacterRegenerationPlan,
  ExistingCharacterSummary,
  NameConflictDecisionState,
  OutlineCharacterDraftV2,
  OutlineCharacterNameConflict,
} from "./contracts";
import {
  buildRegenerationPlan,
  canConfirmRegeneration,
  createFreshCharacterGenerationPlan,
  findCharacterNameConflicts,
  initialNameConflictDecision,
  openRegenerationConfirmation,
  regenerationAffectedDrafts,
  resolutionFromDecision,
  setRegenerationScope,
  toggleRegenerationDraft,
  validateCharacterDrafts,
} from "./state";
import type {
  CheckedChangeEvent,
  InputChangeEvent,
  OutlineCharacterAntdRuntime,
  OutlineCharacterReactRuntime,
} from "./ui-runtime";


export interface OutlineCharacterDraftsPanelProps {
  readonly drafts: readonly OutlineCharacterDraftV2[];
  readonly existingCharacters: readonly ExistingCharacterSummary[];
  /** Optional authoritative conflicts returned by the backend. */
  readonly nameConflicts?: readonly OutlineCharacterNameConflict[];
  readonly conflictDecisions?: Readonly<Record<string, NameConflictDecisionState>>;
  readonly generation: CharacterGenerationState;
  readonly regenerationConfirmation: CharacterRegenerationConfirmationState | null;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly onDraftChange: (draft: OutlineCharacterDraftV2) => void;
  readonly onAddManualDraft: () => void;
  readonly onRemoveDraft?: (draftKey: string) => void;
  readonly onConflictDecisionChange: (
    draftKey: string,
    decision: NameConflictDecisionState,
  ) => void;
  readonly onResolveNameConflict: (
    draftKey: string,
    resolution: CharacterNameConflictResolution,
  ) => void;
  readonly onRegenerationConfirmationChange: (
    state: CharacterRegenerationConfirmationState | null,
  ) => void;
  readonly onConfirmRegeneration: (plan: CharacterRegenerationPlan) => void;
}


const ROLE_OPTIONS = [
  { value: "main", label: "主角" },
  { value: "supporting", label: "配角" },
] as const;


const GENDER_OPTIONS = ["男", "女", "其他", "未知"].map((value) => ({ value, label: value }));


function authoritativeConflicts(props: OutlineCharacterDraftsPanelProps) {
  const detected = findCharacterNameConflicts(props.drafts, props.existingCharacters);
  const byDraftKey = new Map(detected.map((conflict) => [conflict.draft_key, conflict]));
  for (const conflict of props.nameConflicts ?? []) {
    const draft = props.drafts.find((item) => item.draft_key === conflict.draft_key);
    if (draft?.character_id === null) byDraftKey.set(conflict.draft_key, conflict);
  }
  return [...byDraftKey.values()];
}


export function createOutlineCharacterDraftsPanel(
  React: OutlineCharacterReactRuntime,
  antd: OutlineCharacterAntdRuntime,
): (props: OutlineCharacterDraftsPanelProps) => unknown {
  const h = React.createElement;
  const { Alert, Button, Card, Input, Select, Tag } = antd;

  const field = (
    label: string,
    control: unknown,
    help?: string,
  ) => h(
    "label",
    { className: "outline-character-drafts__field" },
    h("span", { className: "outline-character-drafts__field-label" }, label),
    control,
    help ? h("small", null, help) : null,
  );

  return function OutlineCharacterDraftsPanel(
    props: OutlineCharacterDraftsPanelProps,
  ): unknown {
    const conflicts = authoritativeConflicts(props);
    const conflictByKey = new Map(conflicts.map((conflict) => [conflict.draft_key, conflict]));
    const issues = validateCharacterDrafts(props.drafts);
    const busy = props.disabled === true || props.generation.phase === "generating";

    const patchDraft = (
      draft: OutlineCharacterDraftV2,
      patch: Partial<OutlineCharacterDraftV2>,
    ) => props.onDraftChange({ ...draft, ...patch });

    const renderConflict = (conflict: OutlineCharacterNameConflict): unknown => {
      const decision = props.conflictDecisions?.[conflict.draft_key]
        ?? initialNameConflictDecision(conflict);
      const resolution = resolutionFromDecision(conflict, decision);
      return h(
        "section",
        {
          className: "outline-character-drafts__conflict",
          role: "group",
          "aria-label": `${conflict.draft_name}同名人物处理`,
        },
        h(Alert, {
          type: "warning",
          showIcon: true,
          message: "发现同名正式人物，请明确处理",
          description: "系统不会按姓名自动关联。可以关联已有人物；如需新建，必须先改名。",
        }),
        field("处理方式", h(Select, {
          value: decision.mode,
          options: [
            { value: "unresolved", label: "请选择" },
            { value: "link_existing", label: "关联已有人物" },
            { value: "create_new", label: "改名后新建" },
          ],
          disabled: busy,
          "aria-label": `${conflict.draft_name}同名冲突处理方式`,
          onChange: (mode: NameConflictDecisionState["mode"]) => {
            props.onConflictDecisionChange(conflict.draft_key, { ...decision, mode });
          },
        })),
        decision.mode === "link_existing"
          ? field("已有人物", h(Select, {
              value: decision.existing_character_id,
              options: conflict.candidates.map((candidate) => ({
                value: candidate.character_id,
                label: `${candidate.name}（${candidate.role_type === "main" ? "主角" : "配角"}）`,
              })),
              disabled: busy,
              "aria-label": `${conflict.draft_name}关联的人物`,
              onChange: (characterId: string) => props.onConflictDecisionChange(
                conflict.draft_key,
                { ...decision, existing_character_id: characterId },
              ),
            }))
          : null,
        decision.mode === "create_new"
          ? field("新人物姓名", h(Input, {
              value: decision.renamed_name,
              disabled: busy,
              maxLength: 240,
              "aria-label": `${conflict.draft_name}新建时的姓名`,
              onChange: (event: InputChangeEvent) => props.onConflictDecisionChange(
                conflict.draft_key,
                { ...decision, renamed_name: event.target.value },
              ),
            }), "姓名必须与冲突中的正式人物不同。")
          : null,
        h(Button, {
          disabled: busy || resolution === null,
          onClick: () => {
            if (resolution) props.onResolveNameConflict(conflict.draft_key, resolution);
          },
        }, decision.mode === "link_existing" ? "确认关联" : "确认改名并新建"),
      );
    };

    const renderDraft = (draft: OutlineCharacterDraftV2, index: number): unknown => {
      const draftIssues = issues.filter((item) => item.draft_key === draft.draft_key);
      const conflict = conflictByKey.get(draft.draft_key);
      return h(
        Card,
        {
          key: draft.draft_key || `draft-${index}`,
          className: "outline-character-drafts__card",
          title: draft.name.trim() || `未命名人物 ${index + 1}`,
          extra: h(
            "span",
            null,
            h(Tag, null, draft.origin === "manual" ? "手工草案" : "AI 草案"),
            draft.character_id ? h(Tag, { color: "blue" }, "已关联正式人物") : null,
          ),
        },
        h("code", { className: "outline-character-drafts__key" }, draft.draft_key),
        field("角色层级", h(Select, {
          value: draft.role_type,
          options: ROLE_OPTIONS,
          disabled: busy,
          "aria-label": `${draft.name || `人物${index + 1}`}角色层级`,
          onChange: (value: OutlineCharacterDraftV2["role_type"]) => patchDraft(
            draft,
            { role_type: value },
          ),
        })),
        field("姓名", h(Input, {
          value: draft.name,
          maxLength: 240,
          disabled: busy,
          "aria-label": `人物${index + 1}姓名`,
          onChange: (event: InputChangeEvent) => patchDraft(draft, { name: event.target.value }),
        })),
        field("性别", h(Select, {
          value: draft.gender,
          options: GENDER_OPTIONS,
          disabled: busy,
          "aria-label": `${draft.name || `人物${index + 1}`}性别`,
          onChange: (value: OutlineCharacterDraftV2["gender"]) => patchDraft(
            draft,
            { gender: value },
          ),
        })),
        field("故事开始时年龄说明", h(Input, {
          value: draft.age_at_story_start_note,
          maxLength: 2_000,
          disabled: busy,
          "aria-label": `${draft.name || `人物${index + 1}`}故事开始时年龄说明`,
          onChange: (event: InputChangeEvent) => patchDraft(
            draft,
            { age_at_story_start_note: event.target.value },
          ),
        }), "这是作者说明，不替代按出生信息与故事时间计算的年龄。"),
        field("身份摘要", h("textarea", {
          value: draft.identity_summary,
          maxLength: 2_000,
          disabled: busy,
          rows: 2,
          "aria-label": `${draft.name || `人物${index + 1}`}身份摘要`,
          onChange: (event: InputChangeEvent) => patchDraft(
            draft,
            { identity_summary: event.target.value },
          ),
        })),
        field("性格摘要", h("textarea", {
          value: draft.personality_summary,
          maxLength: 4_000,
          disabled: busy,
          rows: 3,
          "aria-label": `${draft.name || `人物${index + 1}`}性格摘要`,
          onChange: (event: InputChangeEvent) => patchDraft(
            draft,
            { personality_summary: event.target.value },
          ),
        })),
        field("核心目标", h("textarea", {
          value: draft.core_goal,
          maxLength: 2_000,
          disabled: busy,
          rows: 2,
          "aria-label": `${draft.name || `人物${index + 1}`}核心目标`,
          onChange: (event: InputChangeEvent) => patchDraft(draft, { core_goal: event.target.value }),
        })),
        field("人物小传", h("textarea", {
          value: draft.bio,
          maxLength: 8_000,
          disabled: busy,
          rows: 4,
          "aria-label": `${draft.name || `人物${index + 1}`}人物小传`,
          onChange: (event: InputChangeEvent) => patchDraft(draft, { bio: event.target.value }),
        })),
        draftIssues.length > 0 ? h(Alert, {
          type: "error",
          showIcon: true,
          message: "请完善人物草案",
          description: draftIssues.map((item) => item.message).join("；"),
        }) : null,
        conflict ? renderConflict(conflict) : null,
        props.onRemoveDraft ? h(Button, {
          danger: true,
          disabled: busy,
          onClick: () => props.onRemoveDraft?.(draft.draft_key),
          "aria-label": `删除${draft.name || `人物${index + 1}`}`,
        }, "删除草案") : null,
      );
    };

    const confirmation = props.regenerationConfirmation;
    const affected = confirmation
      ? regenerationAffectedDrafts(confirmation, props.drafts)
      : [];
    const affectsManual = affected.some((draft) => draft.origin === "manual");

    return h(
      "section",
      { className: props.className ?? "outline-character-drafts", "aria-label": "大纲人物草案" },
      h(
        "header",
        { className: "outline-character-drafts__header" },
        h("div", null, h("h3", null, "人物草案"), h("p", null, "草案保持轻量；正式化后再进入人物根与时间线实例。")),
        h(Button, {
          disabled: busy,
          onClick: () => {
            if (props.drafts.length === 0) {
              props.onConfirmRegeneration(createFreshCharacterGenerationPlan());
              return;
            }
            props.onRegenerationConfirmationChange(openRegenerationConfirmation(props.drafts));
          },
        }, props.drafts.length > 0 ? "再次生成人物" : "生成人物"),
      ),
      props.generation.phase === "failed" ? h(Alert, {
        type: "error",
        showIcon: true,
        message: "AI 生成人物失败",
        description: `${props.generation.failure_message || "本次没有生成可用草案。"} 原草案已保留，你仍可手工填写。`,
      }) : null,
      props.generation.phase === "generating" ? h(Alert, {
        type: "info",
        showIcon: true,
        message: "正在生成人物草案",
      }) : null,
      h("div", { className: "outline-character-drafts__list" }, ...props.drafts.map(renderDraft)),
      h(Button, {
        disabled: busy,
        onClick: props.onAddManualDraft,
      }, "手工新增人物"),
      confirmation ? h(
        "section",
        {
          className: "outline-character-drafts__regeneration-confirmation",
          role: "dialog",
          "aria-modal": "true",
          "aria-label": "确认再次生成人物的替换范围",
        },
        h("h4", null, "确认替换范围"),
        h("p", null, "再次生成不会默认覆盖手工草案。请选择本次允许替换的草案。"),
        field("替换范围", h(Select, {
          value: confirmation.scope,
          options: [
            { value: "ai_generated_only", label: "仅替换 AI 草案" },
            { value: "selected_drafts", label: "仅替换选中的草案" },
            { value: "all_drafts", label: "替换全部草案" },
          ],
          "aria-label": "再次生成替换范围",
          onChange: (scope: CharacterRegenerationConfirmationState["scope"]) => {
            props.onRegenerationConfirmationChange(
              setRegenerationScope(confirmation, scope, props.drafts),
            );
          },
        })),
        confirmation.scope === "selected_drafts" ? h(
          "fieldset",
          null,
          h("legend", null, "选择要替换的人物草案"),
          ...props.drafts.map((draft) => h(
            "label",
            { key: draft.draft_key },
            h("input", {
              type: "checkbox",
              checked: confirmation.selected_draft_keys.includes(draft.draft_key),
              onChange: (event: CheckedChangeEvent) => props.onRegenerationConfirmationChange(
                toggleRegenerationDraft(confirmation, draft.draft_key, event.target.checked),
              ),
            }),
            draft.name || draft.draft_key,
            draft.origin === "manual" ? "（手工）" : "（AI）",
          )),
        ) : null,
        h("p", null, `将替换 ${affected.length} 项，保留 ${props.drafts.length - affected.length} 项。`),
        affectsManual ? h(
          "label",
          { className: "outline-character-drafts__manual-acknowledgement" },
          h("input", {
            type: "checkbox",
            checked: confirmation.manual_replacement_acknowledged,
            onChange: (event: CheckedChangeEvent) => props.onRegenerationConfirmationChange({
              ...confirmation,
              manual_replacement_acknowledged: event.target.checked,
            }),
          }),
          "我确认替换范围包含手工填写的人物草案",
        ) : null,
        h(Button, {
          onClick: () => props.onRegenerationConfirmationChange(null),
        }, "取消"),
        h(Button, {
          type: "primary",
          disabled: !canConfirmRegeneration(confirmation, props.drafts),
          onClick: () => props.onConfirmRegeneration(
            buildRegenerationPlan(confirmation, props.drafts),
          ),
        }, "确认并再次生成"),
      ) : null,
    );
  };
}
