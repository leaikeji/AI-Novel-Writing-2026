import { ApiError, apiRequest } from "./api";
import {
  CharacterRelationshipRecord,
  NovelCharacterRecord,
  RelationshipDirectionality,
  RelationshipKind,
} from "./types";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const { Alert, Button, Input, Modal, Radio, Select } = host.antd;
const { DeleteOutlined, PlusOutlined, UndoOutlined } = host.antdIcons;


interface RelationshipDraft {
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
  open: boolean;
  characters: NovelCharacterRecord[];
  relationships: CharacterRelationshipRecord[];
  focusCharacterId: string | null;
  focusRelationshipId: string | null;
  startWithNew?: boolean;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
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
    status: relationship.status,
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
  open,
  characters,
  relationships,
  focusCharacterId,
  focusRelationshipId,
  startWithNew = false,
  onClose,
  onSaved,
}: RelationshipEditorProps) {
  const [drafts, setDrafts] = React.useState([] as RelationshipDraft[]);
  const [archived, setArchived] = React.useState([] as RelationshipDraft[]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!open) return;
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
    setDrafts(nextDrafts);
    setArchived([]);
    setError("");
  }, [open, focusCharacterId, focusRelationshipId, startWithNew]);

  const characterName = (characterId: string): string => (
    characters.find((character) => character.id === characterId)?.name || "未知角色"
  );
  const focusName = focusCharacterId ? characterName(focusCharacterId) : "角色";
  const updateDraft = (key: string, patch: Partial<RelationshipDraft>) => {
    setDrafts((current: RelationshipDraft[]) => current.map(
      (draft) => draft.key === key ? { ...draft, ...patch } : draft,
    ));
  };
  const removeDraft = (draft: RelationshipDraft) => {
    setDrafts((current: RelationshipDraft[]) => current.filter((item) => item.key !== draft.key));
    if (draft.id) setArchived((current: RelationshipDraft[]) => [...current, draft]);
  };
  const restoreLast = () => {
    setArchived((current: RelationshipDraft[]) => {
      const restored = current[current.length - 1];
      if (restored) setDrafts((rows: RelationshipDraft[]) => [...rows, restored]);
      return current.slice(0, -1);
    });
  };
  const addDraft = () => setDrafts((current: RelationshipDraft[]) => [
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
    if (invalid || saving) return;
    const operations: Array<Record<string, unknown>> = [];
    for (const draft of drafts) {
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
  return h(
    Modal,
    {
      open,
      className: "anw-modal mb-relationship-editor-modal",
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
    h(
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
                      value: draft.source_character_id || undefined,
                      options,
                      onChange: (value: string) => updateDraft(draft.key, { source_character_id: value }),
                    }),
                  ),
                  h(
                    "label",
                    null,
                    h("span", null, "终点角色"),
                    h(Select, {
                      value: draft.target_character_id || undefined,
                      options,
                      onChange: (value: string) => updateDraft(draft.key, { target_character_id: value }),
                    }),
                  ),
                  h(
                    "label",
                    null,
                    h("span", null, "关系分类"),
                    h(Select, {
                      value: draft.relation_kind,
                      options: KIND_OPTIONS,
                      onChange: (value: RelationshipKind) => updateDraft(draft.key, { relation_kind: value }),
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
                      value: draft.directionality === "legacy_unspecified" ? undefined : draft.directionality,
                      onChange: (event: any) => updateDraft(draft.key, { directionality: event.target.value }),
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
                    maxLength: 80,
                    value: draft.label,
                    placeholder: "例如：恋人、邻居、师徒、竞争对手",
                    onChange: (event: any) => updateDraft(draft.key, { label: event.target.value }),
                  }),
                ),
                h(
                  "label",
                  null,
                  h("span", null, "关系描述"),
                  h(Input.TextArea, {
                    rows: 3,
                    maxLength: 10000,
                    value: draft.description,
                    placeholder: "记录这段关系的背景、冲突和当前状态",
                    onChange: (event: any) => updateDraft(draft.key, { description: event.target.value }),
                  }),
                ),
              );
            }),
          ),
    ),
  );
}
