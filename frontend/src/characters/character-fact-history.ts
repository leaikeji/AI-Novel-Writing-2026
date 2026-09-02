import type { CharacterReactRuntime } from "./character-workspace";
import type {
  CharacterFactHistoryPageV2,
  CharacterFactHealth,
  CharacterFactEffectiveState,
  ProjectedFactViewV2,
} from "./contracts";
import {
  FACT_EFFECTIVE_STATE_LABELS,
  FACT_HEALTH_LABELS,
} from "./state-model";
import { characterFactDimensionLabel } from "./model";
import { renderCharacterFactActions } from "./character-fact-actions";

type ElementNode = unknown;

export interface CharacterFactHistoryViewProps {
  readonly titleId: string;
  readonly page: CharacterFactHistoryPageV2 | null;
  readonly loading: boolean;
  readonly loadingMore: boolean;
  readonly batchPreviewing: boolean;
  readonly error: string | null;
  readonly effectiveState: CharacterFactEffectiveState | "all";
  readonly health: CharacterFactHealth | "all";
  readonly dimension: string;
  readonly sourceDocumentId: string;
  readonly dimensionOptions: readonly string[];
  readonly sourceOptions: readonly {
    readonly id: string;
    readonly label: string;
  }[];
  readonly onEffectiveStateChange: (value: CharacterFactEffectiveState | "all") => void;
  readonly onHealthChange: (value: CharacterFactHealth | "all") => void;
  readonly onDimensionChange: (value: string) => void;
  readonly onSourceDocumentChange: (value: string) => void;
  readonly onLoadMore: () => void;
  readonly onOpenSource?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onCorrectFact?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onPreviewBatchRevert?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
}

interface SelectEvent { readonly target: { readonly value: string } }
interface ButtonEvent { readonly currentTarget: HTMLElement }

interface CharacterFactGroup {
  readonly key: string;
  readonly batchId: string | null;
  readonly sourceTitle: string | null;
  readonly facts: readonly ProjectedFactViewV2[];
}

function groupFactsByBatch(items: readonly ProjectedFactViewV2[]): readonly CharacterFactGroup[] {
  const groups: Array<{
    key: string;
    batchId: string | null;
    sourceTitle: string | null;
    facts: ProjectedFactViewV2[];
  }> = [];
  const batchIndexes = new Map<string, number>();
  for (const fact of items) {
    const batchId = fact.source?.commit_batch_id ?? null;
    if (!batchId) {
      groups.push({ key: `fact:${fact.id}`, batchId: null, sourceTitle: null, facts: [fact] });
      continue;
    }
    const knownIndex = batchIndexes.get(batchId);
    if (knownIndex !== undefined) {
      groups[knownIndex]?.facts.push(fact);
      continue;
    }
    batchIndexes.set(batchId, groups.length);
    groups.push({
      key: `batch:${batchId}`,
      batchId,
      sourceTitle: fact.source?.document_title ?? null,
      facts: [fact],
    });
  }
  return groups;
}

export function renderCharacterFactHistory(
  React: CharacterReactRuntime,
  props: CharacterFactHistoryViewProps,
): ElementNode {
  const h = React.createElement;
  const items = props.page?.items ?? [];
  const groups = groupFactsByBatch(items);
  const renderFactCard = (fact: ProjectedFactViewV2): ElementNode => h(
    "li",
    { key: fact.id, className: "anw-character-fact-card" },
    h(
      "div",
      { className: "anw-character-fact-card-field" },
      h("span", { className: "anw-character-fact-card-label" }, "状态"),
      h("span", { className: `anw-character-fact-state is-${fact.effective_state}` }, FACT_EFFECTIVE_STATE_LABELS[fact.effective_state]),
    ),
    h(
      "div",
      { className: "anw-character-fact-card-field" },
      h("span", { className: "anw-character-fact-card-label" }, "维度"),
      h("span", { className: "anw-character-fact-dimension" }, characterFactDimensionLabel(fact.dimension)),
    ),
    h(
      "div",
      { className: "anw-character-fact-card-field anw-character-fact-card-field--fact" },
      h("span", { className: "anw-character-fact-card-label" }, "事实"),
      h("div", { className: "anw-character-fact-text" }, h("strong", null, fact.object_text), fact.health === "ok" ? null : h("small", null, FACT_HEALTH_LABELS[fact.health])),
    ),
    h(
      "div",
      { className: "anw-character-fact-card-field" },
      h("span", { className: "anw-character-fact-card-label" }, "序位"),
      h("span", { className: "anw-character-fact-sequence" }, fact.story_sequence === null ? "未定位" : String(fact.story_sequence)),
    ),
    h(
      "div",
      { className: "anw-character-fact-card-field" },
      h("span", { className: "anw-character-fact-card-label" }, "来源"),
      h("span", { className: "anw-character-fact-source" }, fact.source?.document_title ?? "作者手工事实"),
    ),
    renderCharacterFactActions(React, {
      fact,
      menuIdPrefix: props.titleId,
      onOpenSource: props.onOpenSource,
      onCorrectFact: props.onCorrectFact,
    }),
  );
  return h(
    "section",
    { className: "anw-character-fact-history", "aria-labelledby": props.titleId },
    h(
      "div",
      { className: "anw-character-subsection-heading" },
      h("div", null, h("h4", { id: props.titleId, tabIndex: -1 }, "全部事实"), h("p", null, "历史、失效与已撤销事实保留用于审计，不会混入当前状态。")),
      h(
        "div",
        { className: "anw-character-fact-filters" },
        h(
          "label",
          null,
          h("span", null, "生命周期"),
          h(
            "select",
            { value: props.effectiveState, onChange: (event: SelectEvent) => props.onEffectiveStateChange(event.target.value as CharacterFactEffectiveState | "all") },
            h("option", { value: "all" }, "全部"),
            ...Object.entries(FACT_EFFECTIVE_STATE_LABELS).map(([value, label]) => h("option", { key: value, value }, label)),
          ),
        ),
        h(
          "label",
          null,
          h("span", null, "健康度"),
          h(
            "select",
            { value: props.health, onChange: (event: SelectEvent) => props.onHealthChange(event.target.value as CharacterFactHealth | "all") },
            h("option", { value: "all" }, "全部"),
            ...Object.entries(FACT_HEALTH_LABELS).map(([value, label]) => h("option", { key: value, value }, label)),
          ),
        ),
        h(
          "label",
          null,
          h("span", null, "维度"),
          h(
            "select",
            { value: props.dimension, onChange: (event: SelectEvent) => props.onDimensionChange(event.target.value) },
            h("option", { value: "" }, "全部"),
            ...props.dimensionOptions.map((value) => h(
              "option",
              { key: value, value },
              characterFactDimensionLabel(value),
            )),
          ),
        ),
        h(
          "label",
          null,
          h("span", null, "来源章节"),
          h(
            "select",
            { value: props.sourceDocumentId, onChange: (event: SelectEvent) => props.onSourceDocumentChange(event.target.value) },
            h("option", { value: "" }, "全部"),
            ...props.sourceOptions.map((source) => h(
              "option",
              { key: source.id, value: source.id },
              source.label,
            )),
          ),
        ),
      ),
    ),
    props.error ? h("div", { className: "anw-character-workspace-alert", role: "alert" }, props.error) : null,
    props.batchPreviewing
      ? h("div", { className: "anw-character-workspace-meta", role: "status", "aria-live": "polite" }, "正在读取同步批次的实际影响…")
      : null,
    props.loading
      ? h("div", { className: "anw-character-workspace-empty", role: "status" }, "正在读取事实账本…")
      : items.length === 0
        ? h("div", { className: "anw-character-workspace-empty" }, "当前筛选下没有事实。")
        : h(
            "ul",
            { className: "anw-character-fact-list", "aria-label": "人物事实历史" },
            ...groups.map((group) => {
              const revertTarget = group.facts.find((fact) => fact.effective_state !== "batch_reverted") ?? null;
              return h(
                "li",
                { key: group.key, className: "anw-character-fact-group" },
                group.batchId
                  ? h(
                      "header",
                      { className: "anw-character-fact-batch-heading" },
                      h(
                        "div",
                        null,
                        h("strong", null, `${group.sourceTitle ?? "未命名章节"}的同步批次`),
                        h("small", null, `共 ${group.facts.length} 条事实`),
                      ),
                      revertTarget && props.onPreviewBatchRevert
                        ? h(
                            "button",
                            {
                              type: "button",
                              onClick: (event: ButtonEvent) => props.onPreviewBatchRevert?.(
                                revertTarget,
                                event.currentTarget,
                              ),
                            },
                            "预览批次撤销",
                          )
                        : null,
                    )
                  : null,
                h(
                  "ul",
                  { className: "anw-character-fact-group-items" },
                  ...group.facts.map(renderFactCard),
                ),
              );
            }),
          ),
    props.page?.next_cursor
      ? h("button", { type: "button", className: "anw-character-load-more", disabled: props.loadingMore, onClick: props.onLoadMore }, props.loadingMore ? "正在加载…" : "加载更多")
      : null,
  );
}
