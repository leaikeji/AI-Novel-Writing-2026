import { ApiError, apiRequest } from "./api";
import {
  createAssistantFormFieldAdapter,
  type AssistantFormFieldAdapter,
} from "./assistant-form-field";
import {
  assistantContextRuntime,
  NOVEL_ASSISTANT_TARGET_AGENT_ID,
  type AssistantContextScopeHandle,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import type {
  EditableFieldRegistration,
  SelectionRange,
  SelectionSnapshot,
} from "./assistant-fields";
import {
  readAssistantTextSelection,
  restoreAssistantTextSelection,
  type AssistantTextControl,
} from "./chapter-workflow";
import type { SelectionEditReviewHostComponent } from "./selection-edit-runtime";
import {
  CharacterRelationshipRecord,
  NovelCharacterRecord,
  RelationshipDirectionality,
  RelationshipKind,
} from "./types";


export const RELATIONSHIP_ASSISTANT_FIELD_IDS = {
  sourceCharacterId: "relationship.sourceCharacterId",
  targetCharacterId: "relationship.targetCharacterId",
  kind: "relationship.kind",
  directionality: "relationship.directionality",
  label: "relationship.label",
  description: "relationship.description",
} as const;


export const RELATIONSHIP_SELECTION_REVIEW_FIELD_IDS = Object.freeze(
  Object.values(RELATIONSHIP_ASSISTANT_FIELD_IDS),
);


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const { Alert, Button, Input, Modal, Radio, Select } = host.antd;
const { DeleteOutlined, PlusOutlined, UndoOutlined } = host.antdIcons;


export interface RelationshipDraft {
  key: string;
  id: string | null;
  expected_version: number | null;
  source_character_id: string;
  target_character_id: string;
  directionality: RelationshipDirectionality;
  relation_kind: RelationshipKind;
  label: string;
  description: string;
  status: "active" | "resolved" | "archived";
  original: string | null;
}


export interface RelationshipEditorProps {
  novelId: string;
  novelTitle: string;
  open: boolean;
  characters: NovelCharacterRecord[];
  relationships: CharacterRelationshipRecord[];
  focusCharacterId: string | null;
  focusRelationshipId: string | null;
  startWithNew?: boolean;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  selectionEditReviewHost?: SelectionEditReviewHostComponent;
}


type RelationshipAssistantRuntime = Pick<NovelAssistantContextRuntime, "mountScope">;
type RelationshipAssistantDraftField =
  | "source_character_id"
  | "target_character_id"
  | "relation_kind"
  | "directionality"
  | "label"
  | "description";


export interface RelationshipAssistantScopeOptions {
  runtime?: RelationshipAssistantRuntime;
  novelId: string;
  novelTitle: string;
  draftKey: string;
  characterIds: readonly string[];
  getDraft: () => RelationshipDraft | null;
  applyDraftField: (
    field: RelationshipAssistantDraftField,
    value: string,
  ) => void | Promise<void>;
  getDirty: (fieldId: string) => boolean;
  markDirty: (fieldId: string) => void | Promise<void>;
  getSelection?: (fieldId: string, value: string) => SelectionSnapshot | null;
  restoreSelection?: (fieldId: string, range: SelectionRange) => void;
  focus: (fieldId: string) => void;
}


export interface RelationshipAssistantScopeBinding {
  readonly draftKey: string;
  readonly scope: AssistantContextScopeHandle;
  readonly adapters: ReadonlyMap<string, AssistantFormFieldAdapter>;
  dispose(): void;
}


interface RelationshipAssistantFieldSpec {
  id: string;
  label: string;
  field: RelationshipAssistantDraftField;
  validate: (value: string, options: RelationshipAssistantScopeOptions) => string;
}


const KIND_OPTIONS: Array<{ label: string; value: RelationshipKind }> = [
  { label: "亲属", value: "family" },
  { label: "同事", value: "colleague" },
  { label: "师徒", value: "mentor" },
  { label: "盟友", value: "ally" },
  { label: "敌对", value: "enemy" },
  { label: "情感", value: "romance" },
  { label: "其他", value: "other" },
];


function requireRelationshipChoice(
  value: string,
  choices: readonly string[],
  label: string,
): string {
  if (!choices.includes(value)) throw new Error(`${label}值无效`);
  return value;
}


function requireRelationshipLength(
  value: string,
  maximum: number,
  label: string,
): string {
  if (value.length > maximum) {
    throw new Error(`${label}不能超过 ${maximum} 个 UTF-16 字符`);
  }
  return value;
}


const RELATIONSHIP_ASSISTANT_FIELD_SPECS: readonly RelationshipAssistantFieldSpec[] = [
  {
    id: RELATIONSHIP_ASSISTANT_FIELD_IDS.sourceCharacterId,
    label: "起点角色",
    field: "source_character_id",
    validate: (value, options) => requireRelationshipChoice(
      value,
      options.characterIds,
      "起点角色",
    ),
  },
  {
    id: RELATIONSHIP_ASSISTANT_FIELD_IDS.targetCharacterId,
    label: "终点角色",
    field: "target_character_id",
    validate: (value, options) => requireRelationshipChoice(
      value,
      options.characterIds,
      "终点角色",
    ),
  },
  {
    id: RELATIONSHIP_ASSISTANT_FIELD_IDS.kind,
    label: "关系分类",
    field: "relation_kind",
    validate: (value) => requireRelationshipChoice(
      value,
      KIND_OPTIONS.map((option) => option.value),
      "关系分类",
    ),
  },
  {
    id: RELATIONSHIP_ASSISTANT_FIELD_IDS.directionality,
    label: "关系方向",
    field: "directionality",
    validate: (value) => requireRelationshipChoice(
      value,
      ["directed", "undirected"],
      "关系方向",
    ),
  },
  {
    id: RELATIONSHIP_ASSISTANT_FIELD_IDS.label,
    label: "关系名称",
    field: "label",
    validate: (value) => requireRelationshipLength(value, 80, "关系名称"),
  },
  {
    id: RELATIONSHIP_ASSISTANT_FIELD_IDS.description,
    label: "关系描述",
    field: "description",
    validate: (value) => requireRelationshipLength(value, 10_000, "关系描述"),
  },
];


export async function hashRelationshipAssistantField(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is required for relationship fields");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


export function selectRelationshipAssistantDraft(
  drafts: readonly RelationshipDraft[],
  focusRelationshipId: string | null,
): RelationshipDraft | null {
  if (focusRelationshipId) {
    return drafts.find((draft) => draft.id === focusRelationshipId) ?? null;
  }
  return drafts.find((draft) => draft.id === null) ?? drafts[0] ?? null;
}


export function mountRelationshipAssistantScope(
  options: RelationshipAssistantScopeOptions,
): RelationshipAssistantScopeBinding {
  const initialDraft = options.getDraft();
  if (!initialDraft || initialDraft.key !== options.draftKey) {
    throw new Error("relationship assistant draft is not available");
  }
  const novelTitle = options.novelTitle.trim();
  if (!novelTitle) throw new Error("relationship assistant novel title must not be empty");
  const runtime = options.runtime ?? assistantContextRuntime;
  const scope = runtime.mountScope({
    id: `modal:relationship:${options.novelId}:${options.draftKey}`,
    kind: "modal",
    persistenceBaseline: () => {
      const draft = options.getDraft();
      if (!draft || draft.key !== options.draftKey) {
        throw new Error("relationship assistant draft is no longer available");
      }
      return draft.id && draft.expected_version
        ? { kind: "entity" as const, version: draft.expected_version }
        : { kind: "none" as const, version: null };
    },
    envelope: {
      agentId: NOVEL_ASSISTANT_TARGET_AGENT_ID,
      novel: { id: options.novelId, title: novelTitle },
      page: {
        section: "roles",
        view: "relationship-graph",
        modal: "relationship-editor",
      },
      entity: {
        type: "relationship",
        id: initialDraft.id ?? initialDraft.key,
        title: initialDraft.label || "未命名关系",
      },
    },
  });
  const registrations: EditableFieldRegistration[] = [];
  const adapters = new Map<string, AssistantFormFieldAdapter>();
  const currentDraft = (): RelationshipDraft => {
    const draft = options.getDraft();
    if (!draft || draft.key !== options.draftKey) {
      throw new Error("relationship assistant draft is no longer available");
    }
    return draft;
  };
  try {
    for (const spec of RELATIONSHIP_ASSISTANT_FIELD_SPECS) {
      const adapter = createAssistantFormFieldAdapter({
        id: spec.id,
        label: spec.label,
        getValue: () => currentDraft()[spec.field],
        getDirty: () => options.getDirty(spec.id),
        getSelection: () => options.getSelection?.(
          spec.id,
          currentDraft()[spec.field],
        ) ?? null,
        hashValue: hashRelationshipAssistantField,
        applyDraftValue: async (nextValue) => {
          await options.applyDraftField(
            spec.field,
            spec.validate(nextValue, options),
          );
        },
        markDirty: async () => {
          await options.markDirty(spec.id);
          scope.notifyFieldChanged(spec.id);
        },
        restoreSelection: (range) => options.restoreSelection?.(spec.id, range),
        focus: () => options.focus(spec.id),
      });
      try {
        registrations.push(scope.registerField(adapter));
      } catch (reason) {
        adapter.dispose();
        throw reason;
      }
      adapters.set(spec.id, adapter);
    }
  } catch (reason) {
    for (const registration of [...registrations].reverse()) registration.dispose();
    scope.dispose();
    throw reason;
  }

  let active = true;
  return {
    draftKey: options.draftKey,
    scope,
    adapters,
    dispose: () => {
      if (!active) return;
      active = false;
      for (const registration of [...registrations].reverse()) registration.dispose();
      scope.dispose();
    },
  };
}


function draftComparable(draft: RelationshipDraft): string {
  return JSON.stringify({
    source_character_id: draft.source_character_id,
    target_character_id: draft.target_character_id,
    directionality: draft.directionality,
    relation_kind: draft.relation_kind,
    label: draft.label.trim(),
    description: draft.description.trim(),
    status: draft.status === "archived" ? "active" : draft.status,
  });
}


function fromRelationship(relationship: CharacterRelationshipRecord): RelationshipDraft {
  const draft: RelationshipDraft = {
    key: relationship.id,
    id: relationship.id,
    expected_version: relationship.version,
    source_character_id: relationship.source_character_id,
    target_character_id: relationship.target_character_id,
    directionality: relationship.directionality,
    relation_kind: relationship.relation_kind,
    label: relationship.label || relationship.relation_type,
    description: relationship.description,
    status: relationship.definition_status || relationship.status,
    original: null,
  };
  draft.original = draftComparable(draft);
  return draft;
}


function newDraft(
  characters: NovelCharacterRecord[],
  focusCharacterId: string | null,
): RelationshipDraft {
  const source = focusCharacterId || characters[0]?.id || "";
  const target = characters.find((character) => character.id !== source)?.id || "";
  return {
    key: `new-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    id: null,
    expected_version: null,
    source_character_id: source,
    target_character_id: target,
    directionality: "undirected",
    relation_kind: "other",
    label: "",
    description: "",
    status: "active",
    original: null,
  };
}


function errorText(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (typeof reason.detail === "string") return reason.detail;
    const detail = reason.detail as { current?: unknown } | null;
    if (reason.status === 409 && detail?.current) return "关系已在其他页面修改，请关闭后重新打开。";
  }
  return reason instanceof Error ? reason.message : "保存角色关系失败";
}


export function RelationshipEditor({
  novelId,
  novelTitle,
  open,
  characters,
  relationships,
  focusCharacterId,
  focusRelationshipId,
  startWithNew = false,
  onClose,
  onSaved,
  selectionEditReviewHost: SelectionEditReviewHost,
}: RelationshipEditorProps) {
  const [drafts, setDrafts] = React.useState([] as RelationshipDraft[]);
  const [archived, setArchived] = React.useState([] as RelationshipDraft[]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [hydratedDraftScopeKey, setHydratedDraftScopeKey] = React.useState("");
  const draftsRef = React.useRef(drafts) as { current: RelationshipDraft[] };
  const assistantDirtyFieldsRef = React.useRef(new Map<string, Set<string>>()) as {
    current: Map<string, Set<string>>;
  };
  const assistantBindingRef = React.useRef(
    null as RelationshipAssistantScopeBinding | null,
  ) as { current: RelationshipAssistantScopeBinding | null };
  interface RelationshipFocusableControl {
    focus?: () => void;
    input?: AssistantTextControl | null;
    resizableTextArea?: { textArea?: AssistantTextControl | null } | null;
    selectionStart?: number | null;
    selectionEnd?: number | null;
    selectionDirection?: string | null;
    setSelectionRange?: AssistantTextControl["setSelectionRange"];
  }
  const assistantControlRefs = React.useRef(new Map<string, RelationshipFocusableControl>()) as {
    current: Map<string, RelationshipFocusableControl>;
  };
  draftsRef.current = drafts;

  const requestedDraftScopeKey = [
    novelId,
    focusCharacterId ?? "",
    focusRelationshipId ?? "",
    startWithNew ? "new" : "existing",
  ].join(":");
  const replaceDrafts = (next: RelationshipDraft[]): void => {
    draftsRef.current = next;
    setDrafts(next);
  };
  const updateDraftRows = (
    update: (current: RelationshipDraft[]) => RelationshipDraft[],
  ): void => replaceDrafts(update(draftsRef.current));
  const dirtyFieldsFor = (draftKey: string): Set<string> => {
    let fields = assistantDirtyFieldsRef.current.get(draftKey);
    if (!fields) {
      fields = new Set<string>();
      assistantDirtyFieldsRef.current.set(draftKey, fields);
    }
    return fields;
  };
  const markAssistantFieldDirty = (draftKey: string, fieldId: string): void => {
    dirtyFieldsFor(draftKey).add(fieldId);
    const active = assistantBindingRef.current;
    if (active?.draftKey === draftKey) active.scope.notifyFieldChanged(fieldId);
  };
  const updateDraft = (
    key: string,
    patch: Partial<RelationshipDraft>,
    fieldId?: string,
  ): void => {
    updateDraftRows((current) => current.map(
      (draft) => draft.key === key ? { ...draft, ...patch } : draft,
    ));
    if (fieldId) markAssistantFieldDirty(key, fieldId);
  };
  const applyAssistantDraftField = (
    key: string,
    field: RelationshipAssistantDraftField,
    value: string,
  ): void => {
    if (field === "source_character_id") {
      updateDraft(key, { source_character_id: value });
    } else if (field === "target_character_id") {
      updateDraft(key, { target_character_id: value });
    } else if (field === "relation_kind") {
      const kind = KIND_OPTIONS.find((option) => option.value === value)?.value;
      if (!kind) throw new Error("关系分类值无效");
      updateDraft(key, { relation_kind: kind });
    } else if (field === "directionality") {
      if (value !== "directed" && value !== "undirected") {
        throw new Error("关系方向值无效");
      }
      updateDraft(key, { directionality: value });
    } else if (field === "label") {
      updateDraft(key, { label: value });
    } else {
      updateDraft(key, { description: value });
    }
  };
  const assistantControlKey = (draftKey: string, fieldId: string): string => (
    `${draftKey}:${fieldId}`
  );
  const assistantTextControl = (
    draftKey: string,
    fieldId: string,
  ): AssistantTextControl | null => {
    const control = assistantControlRefs.current.get(
      assistantControlKey(draftKey, fieldId),
    );
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
  };
  const assistantControlProps = (draftKey: string, fieldId: string) => ({
    ref: (control: RelationshipFocusableControl | null) => {
      const key = assistantControlKey(draftKey, fieldId);
      if (control) assistantControlRefs.current.set(key, control);
      else assistantControlRefs.current.delete(key);
    },
    onFocus: () => {
      const active = assistantBindingRef.current;
      if (active?.draftKey === draftKey) active.scope.setFocusedField(fieldId);
    },
    onBlur: () => {
      const active = assistantBindingRef.current;
      if (active?.draftKey === draftKey) active.scope.setFocusedField(undefined);
    },
  });

  React.useEffect(() => {
    if (!open) {
      replaceDrafts([]);
      assistantDirtyFieldsRef.current.clear();
      setHydratedDraftScopeKey("");
      return;
    }
    let rows = focusCharacterId
      ? relationships.filter(
          (relationship) => relationship.source_character_id === focusCharacterId
            || relationship.target_character_id === focusCharacterId,
        )
      : focusRelationshipId
        ? relationships.filter((relationship) => relationship.id === focusRelationshipId)
        : [];
    rows = [...rows].sort((left, right) => {
      if (left.id === focusRelationshipId) return -1;
      if (right.id === focusRelationshipId) return 1;
      return (left.label || left.relation_type).localeCompare(
        right.label || right.relation_type,
        "zh-CN",
      );
    });
    const nextDrafts = rows.map(fromRelationship);
    if (startWithNew || (!focusCharacterId && !focusRelationshipId)) {
      nextDrafts.unshift(newDraft(characters, focusCharacterId));
    }
    assistantDirtyFieldsRef.current.clear();
    replaceDrafts(nextDrafts);
    setHydratedDraftScopeKey(requestedDraftScopeKey);
    setArchived([]);
    setError("");
  }, [open, novelId, focusCharacterId, focusRelationshipId, startWithNew]);

  const assistantDraft = hydratedDraftScopeKey === requestedDraftScopeKey
    ? selectRelationshipAssistantDraft(drafts, focusRelationshipId)
    : null;
  const assistantCharacterIds = characters.map((character) => character.id);
  const assistantCharacterScopeKey = assistantCharacterIds.join(":");

  React.useEffect(() => {
    if (!open || !assistantDraft) return;
    const draftKey = assistantDraft.key;
    const binding = mountRelationshipAssistantScope({
      novelId,
      novelTitle,
      draftKey,
      characterIds: assistantCharacterIds,
      getDraft: () => draftsRef.current.find((draft) => draft.key === draftKey) ?? null,
      applyDraftField: (field, value) => applyAssistantDraftField(draftKey, field, value),
      getDirty: (fieldId) => {
        const draft = draftsRef.current.find((item) => item.key === draftKey);
        return draft?.id === null || dirtyFieldsFor(draftKey).has(fieldId);
      },
      markDirty: (fieldId) => { dirtyFieldsFor(draftKey).add(fieldId); },
      getSelection: (fieldId, value) => readAssistantTextSelection(
        assistantTextControl(draftKey, fieldId),
        value,
      ),
      restoreSelection: (fieldId, range) => restoreAssistantTextSelection(
        assistantTextControl(draftKey, fieldId),
        range,
      ),
      focus: (fieldId) => {
        assistantControlRefs.current
          .get(assistantControlKey(draftKey, fieldId))
          ?.focus?.();
      },
    });
    assistantBindingRef.current = binding;
    return () => {
      if (assistantBindingRef.current === binding) {
        assistantBindingRef.current = null;
      }
      binding.dispose();
    };
  }, [
    open,
    novelId,
    novelTitle,
    assistantDraft?.key,
    assistantCharacterScopeKey,
  ]);

  const characterName = (characterId: string): string => (
    characters.find((character) => character.id === characterId)?.name || "未知角色"
  );
  const focusName = focusCharacterId ? characterName(focusCharacterId) : "角色";
  const removeDraft = (draft: RelationshipDraft) => {
    if (assistantBindingRef.current?.draftKey === draft.key) {
      assistantBindingRef.current.dispose();
      assistantBindingRef.current = null;
    }
    assistantDirtyFieldsRef.current.delete(draft.key);
    updateDraftRows((current) => current.filter((item) => item.key !== draft.key));
    if (draft.id) setArchived((current: RelationshipDraft[]) => [...current, draft]);
  };
  const restoreLast = () => {
    setArchived((current: RelationshipDraft[]) => {
      const restored = current[current.length - 1];
      if (restored) updateDraftRows((rows) => [...rows, restored]);
      return current.slice(0, -1);
    });
  };
  const addDraft = () => updateDraftRows((current) => [
    ...current,
    newDraft(characters, focusCharacterId),
  ]);

  const invalid = drafts.some((draft: RelationshipDraft) => (
    !draft.source_character_id
    || !draft.target_character_id
    || draft.source_character_id === draft.target_character_id
    || !draft.label.trim()
    || draft.directionality === "legacy_unspecified"
  ));

  const save = async () => {
    const currentInvalid = draftsRef.current.some((draft) => (
      !draft.source_character_id
      || !draft.target_character_id
      || draft.source_character_id === draft.target_character_id
      || !draft.label.trim()
      || draft.directionality === "legacy_unspecified"
    ));
    if (currentInvalid || saving) return;
    const operations: Array<Record<string, unknown>> = [];
    for (const draft of draftsRef.current) {
      const payload = {
        source_character_id: draft.source_character_id,
        target_character_id: draft.target_character_id,
        directionality: draft.directionality,
        relation_kind: draft.relation_kind,
        label: draft.label.trim(),
        description: draft.description.trim(),
        status: draft.status === "archived" ? "active" : draft.status,
      };
      if (!draft.id) {
        operations.push({ action: "create", client_id: draft.key, ...payload });
      } else if (draftComparable(draft) !== draft.original) {
        operations.push({
          action: "update",
          relationship_id: draft.id,
          expected_version: draft.expected_version,
          ...payload,
        });
      }
    }
    for (const draft of archived) {
      operations.push({
        action: "archive",
        relationship_id: draft.id,
        expected_version: draft.expected_version,
      });
    }
    if (operations.length === 0) {
      onClose();
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiRequest(`/novels/${novelId}/relationships/batch`, {
        method: "POST",
        body: JSON.stringify({ operations }),
      });
      await onSaved();
      onClose();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const options = characters.map((character) => ({ label: character.name, value: character.id }));
  const wrapSelectionReview = (child: unknown): unknown => SelectionEditReviewHost
    ? h(SelectionEditReviewHost, {
      fieldIds: RELATIONSHIP_SELECTION_REVIEW_FIELD_IDS,
      className: "mb-relationship-selection-review-host",
    }, child)
    : child;
  return h(
    Modal,
    {
      open,
      className: "anw-modal mb-relationship-editor-modal",
      wrapClassName: "anw-assistant-aware-modal-wrap",
      mask: false,
      width: 760,
      title: h(
        "div",
        { className: "mb-relationship-editor-title" },
        h("strong", null, "编辑关系"),
        h("span", null, focusCharacterId ? `${focusName}的关系` : "角色关系"),
      ),
      onCancel: saving ? undefined : onClose,
      footer: h(
        "div",
        { className: "mb-relationship-editor-footer" },
        archived.length
          ? h(Button, { icon: h(UndoOutlined), onClick: restoreLast }, `撤销删除 (${archived.length})`)
          : h("span", null),
        h(
          Button,
          {
            size: "large",
            className: "anw-primary-button",
            loading: saving,
            disabled: invalid,
            onClick: () => void save(),
          },
          "保存所有修改",
        ),
      ),
    },
    wrapSelectionReview(h(
      "div",
      { className: "mb-relationship-editor-body" },
      error ? h(Alert, { type: "error", showIcon: true, message: error }) : null,
      h(
        "div",
        { className: "mb-relationship-editor-heading" },
        h("strong", null, "角色关系列表"),
        h(Button, { icon: h(PlusOutlined), onClick: addDraft }, "添加关系"),
      ),
      drafts.length === 0
        ? h("div", { className: "mb-relationship-editor-empty" }, "暂无关系，点击“添加关系”建立第一条关系。")
        : h(
            "div",
            { className: "mb-relationship-draft-list" },
            ...drafts.map((draft: RelationshipDraft) => {
              const directionMark = draft.directionality === "directed"
                ? "→"
                : draft.directionality === "undirected"
                  ? "—"
                  : "?";
              return h(
                "article",
                {
                  key: draft.key,
                  className: `mb-relationship-draft${draft.id === focusRelationshipId ? " is-focused" : ""}`,
                },
                h(
                  "header",
                  null,
                  h(
                    "strong",
                    null,
                    `${characterName(draft.source_character_id)} ${directionMark} ${characterName(draft.target_character_id)}`,
                    draft.label ? `：${draft.label}` : "",
                  ),
                  h(
                    Button,
                    {
                      type: "text",
                      danger: true,
                      icon: h(DeleteOutlined),
                      onClick: () => removeDraft(draft),
                      "aria-label": `删除${draft.label || "未命名关系"}`,
                    },
                    "删除",
                  ),
                ),
                h(
                  "div",
                  { className: "mb-relationship-draft-grid" },
                  h(
                    "label",
                    null,
                    h("span", null, "起点角色"),
                    h(Select, {
                      ...assistantControlProps(
                        draft.key,
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.sourceCharacterId,
                      ),
                      value: draft.source_character_id || undefined,
                      options,
                      onChange: (value: string) => updateDraft(
                        draft.key,
                        { source_character_id: value },
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.sourceCharacterId,
                      ),
                    }),
                  ),
                  h(
                    "label",
                    null,
                    h("span", null, "终点角色"),
                    h(Select, {
                      ...assistantControlProps(
                        draft.key,
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.targetCharacterId,
                      ),
                      value: draft.target_character_id || undefined,
                      options,
                      onChange: (value: string) => updateDraft(
                        draft.key,
                        { target_character_id: value },
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.targetCharacterId,
                      ),
                    }),
                  ),
                  h(
                    "label",
                    null,
                    h("span", null, "关系分类"),
                    h(Select, {
                      ...assistantControlProps(
                        draft.key,
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.kind,
                      ),
                      value: draft.relation_kind,
                      options: KIND_OPTIONS,
                      onChange: (value: RelationshipKind) => updateDraft(
                        draft.key,
                        { relation_kind: value },
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.kind,
                      ),
                    }),
                  ),
                ),
                h(
                  "label",
                  { className: "mb-relationship-direction" },
                  h("span", null, "关系方向"),
                  h(
                    Radio.Group,
                    {
                      ...assistantControlProps(
                        draft.key,
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.directionality,
                      ),
                      value: draft.directionality === "legacy_unspecified" ? undefined : draft.directionality,
                      onChange: (event: any) => updateDraft(
                        draft.key,
                        { directionality: event.target.value },
                        RELATIONSHIP_ASSISTANT_FIELD_IDS.directionality,
                      ),
                    },
                    h(Radio, { value: "undirected" }, "无向关系 A — B"),
                    h(Radio, { value: "directed" }, "有向关系 A → B"),
                  ),
                  draft.directionality === "legacy_unspecified"
                    ? h("small", { role: "alert" }, "这是一条旧关系，请先确认方向后再保存。")
                    : null,
                ),
                h(
                  "label",
                  null,
                  h("span", null, "关系名称"),
                  h(Input, {
                    ...assistantControlProps(
                      draft.key,
                      RELATIONSHIP_ASSISTANT_FIELD_IDS.label,
                    ),
                    maxLength: 80,
                    value: draft.label,
                    placeholder: "例如：恋人、邻居、师徒、竞争对手",
                    onChange: (event: any) => updateDraft(
                      draft.key,
                      { label: event.target.value },
                      RELATIONSHIP_ASSISTANT_FIELD_IDS.label,
                    ),
                  }),
                ),
                h(
                  "label",
                  null,
                  h("span", null, "关系描述"),
                  h(Input.TextArea, {
                    ...assistantControlProps(
                      draft.key,
                      RELATIONSHIP_ASSISTANT_FIELD_IDS.description,
                    ),
                    rows: 3,
                    maxLength: 10000,
                    value: draft.description,
                    placeholder: "记录这段关系的背景、冲突和当前状态",
                    onChange: (event: any) => updateDraft(
                      draft.key,
                      { description: event.target.value },
                      RELATIONSHIP_ASSISTANT_FIELD_IDS.description,
                    ),
                  }),
                ),
              );
            }),
          ),
    )),
  );
}
