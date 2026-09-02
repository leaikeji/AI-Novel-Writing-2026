import {
  STORY_LEDGER_EFFECTIVE_STATES,
  STORY_LEDGER_FACT_TYPES,
  STORY_LEDGER_HEALTH_STATES,
  type StoryLedgerEntityType,
  type StoryLedgerFactEffectiveState,
  type StoryLedgerFactHealth,
  type StoryLedgerFilters,
} from "./contracts";
import type { StoryLedgerElementNode, StoryLedgerReactRuntime } from "./runtime";
import {
  FACT_EFFECTIVE_STATE_LABELS,
  FACT_HEALTH_LABELS,
} from "./state-model";

export const STORY_LEDGER_FACT_TYPE_LABELS: Readonly<Record<string, string>> = {
  character_state: "人物状态",
  relationship_state: "关系状态",
  storyline_event: "故事线事件",
  foreshadow_event: "伏笔事件",
  story_time: "故事时间",
  knowledge_event: "知情变化",
  world_state: "世界状态",
  general_fact: "通用事实",
};

export const STORY_LEDGER_ENTITY_TYPE_LABELS: Readonly<Record<StoryLedgerEntityType, string>> = {
  character: "人物",
  character_instance: "人物实例",
  relationship: "关系",
  storyline: "故事线",
  foreshadow: "伏笔",
};

const ENTITY_TYPES = Object.keys(
  STORY_LEDGER_ENTITY_TYPE_LABELS,
) as readonly StoryLedgerEntityType[];

interface SelectEvent {
  readonly target: { readonly value: string };
}

interface InputEvent {
  readonly target: { readonly value: string; readonly checked?: boolean };
}

export function normalizeStoryLedgerFilters(
  filters: StoryLedgerFilters,
): StoryLedgerFilters {
  const factTypes = [...new Set(filters.factTypes ?? [])]
    .map((value) => value.trim())
    .filter(Boolean)
    .sort();
  const clean = (value: string | null | undefined): string | null => {
    const normalized = value?.trim() ?? "";
    return normalized || null;
  };
  const entityType = filters.entityType ?? null;
  const entityId = clean(filters.entityId);
  return {
    ...(factTypes.length ? { factTypes } : {}),
    ...(filters.effectiveState ? { effectiveState: filters.effectiveState } : {}),
    ...(filters.health ? { health: filters.health } : {}),
    ...(clean(filters.dimension) ? { dimension: clean(filters.dimension) } : {}),
    ...(clean(filters.sourceDocumentId)
      ? { sourceDocumentId: clean(filters.sourceDocumentId) }
      : {}),
    ...(clean(filters.commitBatchId) ? { commitBatchId: clean(filters.commitBatchId) } : {}),
    ...(clean(filters.factTimelineId)
      ? { factTimelineId: clean(filters.factTimelineId) }
      : {}),
    ...(entityType ? { entityType } : {}),
    ...(entityType && entityId ? { entityId } : {}),
    ...(filters.reviewOnly ? { reviewOnly: true } : {}),
  };
}

export function storyLedgerFilterCount(filters: StoryLedgerFilters): number {
  const normalized = normalizeStoryLedgerFilters(filters);
  return (normalized.factTypes?.length ? 1 : 0)
    + (normalized.effectiveState ? 1 : 0)
    + (normalized.health ? 1 : 0)
    + (normalized.dimension ? 1 : 0)
    + (normalized.sourceDocumentId ? 1 : 0)
    + (normalized.commitBatchId ? 1 : 0)
    + (normalized.factTimelineId ? 1 : 0)
    + (normalized.entityType ? 1 : 0)
    + (normalized.entityId ? 1 : 0)
    + (normalized.reviewOnly ? 1 : 0);
}

export function describeStoryLedgerFilters(filters: StoryLedgerFilters): string {
  const normalized = normalizeStoryLedgerFilters(filters);
  const labels: string[] = [];
  if (normalized.reviewOnly) labels.push("仅待核对");
  if (normalized.factTypes?.length) {
    labels.push(normalized.factTypes
      .map((value) => STORY_LEDGER_FACT_TYPE_LABELS[value] ?? value)
      .join("、"));
  }
  if (normalized.effectiveState) {
    labels.push(FACT_EFFECTIVE_STATE_LABELS[normalized.effectiveState]);
  }
  if (normalized.health) labels.push(FACT_HEALTH_LABELS[normalized.health]);
  if (normalized.dimension) labels.push(`维度：${normalized.dimension}`);
  if (normalized.sourceDocumentId) labels.push(`来源：${normalized.sourceDocumentId}`);
  if (normalized.commitBatchId) labels.push(`批次：${normalized.commitBatchId}`);
  if (normalized.factTimelineId) labels.push(`事实时间线：${normalized.factTimelineId}`);
  if (normalized.entityType) {
    labels.push(`实体：${STORY_LEDGER_ENTITY_TYPE_LABELS[normalized.entityType]}${
      normalized.entityId ? ` / ${normalized.entityId}` : ""
    }`);
  }
  return labels.length ? labels.join("；") : "全部事实";
}

export interface StoryLedgerFilterViewProps {
  readonly idPrefix: string;
  readonly filters: StoryLedgerFilters;
  readonly multipleTimelines: boolean;
  readonly timelineOptions?: readonly {
    readonly id: string;
    readonly name: string;
  }[];
  readonly disabled?: boolean;
  readonly onChange: (filters: StoryLedgerFilters) => void;
}

export function renderStoryLedgerFilters(
  React: StoryLedgerReactRuntime,
  props: StoryLedgerFilterViewProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  const filters = normalizeStoryLedgerFilters(props.filters);
  const selectedTypes = new Set(filters.factTypes ?? []);
  const patch = (value: Partial<StoryLedgerFilters>): void => {
    props.onChange(normalizeStoryLedgerFilters({ ...filters, ...value }));
  };
  const selectValue = <T extends string>(value: string): T | null => (
    value ? value as T : null
  );
  const textField = (
    key: "dimension" | "sourceDocumentId" | "commitBatchId" | "entityId",
    label: string,
    placeholder: string,
  ): StoryLedgerElementNode => h(
    "label",
    { className: "anw-story-ledger-filter" },
    h("span", null, label),
    h("input", {
      id: `${props.idPrefix}-${key}`,
      type: "text",
      value: filters[key] ?? "",
      placeholder,
      disabled: props.disabled,
      onChange: (event: InputEvent) => patch({ [key]: event.target.value }),
    }),
  );

  return h(
    "form",
    {
      className: "anw-story-ledger-filters",
      "aria-label": "故事账本组合筛选",
      onSubmit: (event: { preventDefault(): void }) => event.preventDefault(),
    },
    h(
      "fieldset",
      { className: "anw-story-ledger-type-filter", disabled: props.disabled },
      h("legend", null, "事实类型"),
      ...STORY_LEDGER_FACT_TYPES.map((factType) => h(
        "label",
        { key: factType },
        h("input", {
          type: "checkbox",
          value: factType,
          checked: selectedTypes.has(factType),
          onChange: (event: InputEvent) => {
            const next = new Set(selectedTypes);
            if (event.target.checked) next.add(factType);
            else next.delete(factType);
            patch({ factTypes: [...next] });
          },
        }),
        h("span", null, STORY_LEDGER_FACT_TYPE_LABELS[factType]),
      )),
    ),
    h(
      "div",
      { className: "anw-story-ledger-filter-grid" },
      h(
        "label",
        { className: "anw-story-ledger-filter" },
        h("span", null, "生命周期"),
        h(
          "select",
          {
            value: filters.effectiveState ?? "",
            disabled: props.disabled,
            onChange: (event: SelectEvent) => patch({
              effectiveState: selectValue<StoryLedgerFactEffectiveState>(event.target.value),
            }),
          },
          h("option", { value: "" }, "全部生命周期"),
          ...STORY_LEDGER_EFFECTIVE_STATES.map((state) => h(
            "option",
            { key: state, value: state },
            FACT_EFFECTIVE_STATE_LABELS[state],
          )),
        ),
      ),
      h(
        "label",
        { className: "anw-story-ledger-filter" },
        h("span", null, "健康度"),
        h(
          "select",
          {
            value: filters.health ?? "",
            disabled: props.disabled,
            onChange: (event: SelectEvent) => patch({
              health: selectValue<StoryLedgerFactHealth>(event.target.value),
            }),
          },
          h("option", { value: "" }, "全部健康度"),
          ...STORY_LEDGER_HEALTH_STATES.map((health) => h(
            "option",
            { key: health, value: health },
            FACT_HEALTH_LABELS[health],
          )),
        ),
      ),
      textField("dimension", "维度", "例如 location"),
      textField("sourceDocumentId", "来源文档", "文档 ID"),
      textField("commitBatchId", "同步批次", "批次 ID"),
      h(
        "label",
        { className: "anw-story-ledger-filter" },
        h("span", null, "实体类型"),
        h(
          "select",
          {
            value: filters.entityType ?? "",
            disabled: props.disabled,
            onChange: (event: SelectEvent) => patch({
              entityType: selectValue<StoryLedgerEntityType>(event.target.value),
              ...(!event.target.value ? { entityId: null } : {}),
            }),
          },
          h("option", { value: "" }, "全部实体"),
          ...ENTITY_TYPES.map((entityType) => h(
            "option",
            { key: entityType, value: entityType },
            STORY_LEDGER_ENTITY_TYPE_LABELS[entityType],
          )),
        ),
      ),
      textField("entityId", "实体 ID", filters.entityType ? "精确实体 ID" : "请先选择实体类型"),
      props.multipleTimelines
        ? h(
            "label",
            { className: "anw-story-ledger-filter" },
            h("span", null, "事实所属时间线"),
            props.timelineOptions?.length
              ? h(
                  "select",
                  {
                    value: filters.factTimelineId ?? "",
                    disabled: props.disabled,
                    onChange: (event: SelectEvent) => patch({
                      factTimelineId: event.target.value || null,
                    }),
                  },
                  h("option", { value: "" }, "全部时间线"),
                  ...props.timelineOptions.map((timeline) => h(
                    "option",
                    { key: timeline.id, value: timeline.id },
                    timeline.name,
                  )),
                )
              : h("input", {
                  type: "text",
                  value: filters.factTimelineId ?? "",
                  placeholder: "时间线 ID",
                  disabled: props.disabled,
                  onChange: (event: InputEvent) => patch({
                    factTimelineId: event.target.value,
                  }),
                }),
          )
        : null,
    ),
    h(
      "div",
      { className: "anw-story-ledger-filter-actions" },
      h(
        "label",
        { className: "anw-story-ledger-review-toggle" },
        h("input", {
          type: "checkbox",
          checked: filters.reviewOnly === true,
          disabled: props.disabled,
          onChange: (event: InputEvent) => patch({ reviewOnly: event.target.checked === true }),
        }),
        h("span", null, "只看核对队列"),
      ),
      h(
        "button",
        {
          type: "button",
          disabled: props.disabled || storyLedgerFilterCount(filters) === 0,
          onClick: () => props.onChange({}),
        },
        "清除筛选",
      ),
    ),
  );
}
