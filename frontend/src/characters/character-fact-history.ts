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

type ElementNode = unknown;

export interface CharacterFactHistoryViewProps {
  readonly titleId: string;
  readonly page: CharacterFactHistoryPageV2 | null;
  readonly loading: boolean;
  readonly loadingMore: boolean;
  readonly error: string | null;
  readonly effectiveState: CharacterFactEffectiveState | "all";
  readonly health: CharacterFactHealth | "all";
  readonly onEffectiveStateChange: (value: CharacterFactEffectiveState | "all") => void;
  readonly onHealthChange: (value: CharacterFactHealth | "all") => void;
  readonly onLoadMore: () => void;
  readonly onOpenSource: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onCorrectFact: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onPreviewBatchRevert: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
}

interface SelectEvent { readonly target: { readonly value: string } }
interface ButtonEvent { readonly currentTarget: HTMLElement }

export function renderCharacterFactHistory(
  React: CharacterReactRuntime,
  props: CharacterFactHistoryViewProps,
): ElementNode {
  const h = React.createElement;
  const items = props.page?.items ?? [];
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
      ),
    ),
    props.error ? h("div", { className: "anw-character-workspace-alert", role: "alert" }, props.error) : null,
    props.loading
      ? h("div", { className: "anw-character-workspace-empty", role: "status" }, "正在读取事实账本…")
      : items.length === 0
        ? h("div", { className: "anw-character-workspace-empty" }, "当前筛选下没有事实。")
        : h(
            "div",
            { className: "anw-character-fact-table", role: "table", "aria-label": "人物事实历史" },
            ...items.map((fact) => h(
              "article",
              { key: fact.id, className: "anw-character-fact-table-row", role: "row" },
              h("span", { className: `anw-character-fact-state is-${fact.effective_state}` }, FACT_EFFECTIVE_STATE_LABELS[fact.effective_state]),
              h("span", { className: "anw-character-fact-dimension" }, characterFactDimensionLabel(fact.dimension)),
              h("div", { className: "anw-character-fact-text" }, h("strong", null, fact.object_text), fact.health === "ok" ? null : h("small", null, FACT_HEALTH_LABELS[fact.health])),
              h("span", { className: "anw-character-fact-sequence" }, fact.story_sequence === null ? "未定位" : `序位 ${fact.story_sequence}`),
              h("span", { className: "anw-character-fact-source" }, fact.source?.document_title ?? "作者手工事实"),
              h(
                "div",
                { className: "anw-character-row-actions" },
                fact.source ? h("button", { type: "button", onClick: (event: ButtonEvent) => props.onOpenSource(fact, event.currentTarget) }, "来源") : null,
                fact.effective_state === "current" ? h("button", { type: "button", onClick: (event: ButtonEvent) => props.onCorrectFact(fact, event.currentTarget) }, "修正") : null,
                fact.source?.commit_batch_id && fact.effective_state !== "batch_reverted"
                  ? h("button", { type: "button", onClick: (event: ButtonEvent) => props.onPreviewBatchRevert(fact, event.currentTarget) }, "撤销同步")
                  : null,
              ),
            )),
          ),
    props.page?.next_cursor
      ? h("button", { type: "button", className: "anw-character-load-more", disabled: props.loadingMore, onClick: props.onLoadMore }, props.loadingMore ? "正在加载…" : "加载更多")
      : null,
  );
}
