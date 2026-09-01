import type { CharacterReactRuntime } from "./character-workspace";
import type { CharacterWorkspaceV2, ProjectedFactViewV2 } from "./contracts";
import { characterFactDimensionLabel } from "./model";

type ElementNode = unknown;

export interface CharacterStatePanelProps {
  readonly currentStateTitleId: string;
  readonly recentChangesTitleId: string;
  readonly workspace: CharacterWorkspaceV2;
  readonly historyOpen: boolean;
  readonly onToggleHistory: () => void;
  readonly onOpenSource: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onCorrectFact: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
}

interface ButtonEvent { readonly currentTarget: HTMLElement }

export function renderCharacterStatePanel(
  React: CharacterReactRuntime,
  props: CharacterStatePanelProps,
): ElementNode {
  const h = React.createElement;
  const state = props.workspace.writing_state;
  const risks = state.risk_summary;
  const actionable = risks.conflict_count + risks.ambiguous_count + risks.invalid_source_count;
  const recent = state.recent_changes.slice(0, 5);

  return h(
    "div",
    { className: "anw-character-state" },
    h(
      "div",
      { className: "anw-character-state-layout" },
      h(
        "section",
        { className: "anw-character-state-current", "aria-labelledby": props.currentStateTitleId },
        h("h4", { id: props.currentStateTitleId }, "当前写作状态"),
        h(
          "dl",
          { className: "anw-character-state-slots" },
          ...state.slots.map((slot) => h(
            "div",
            { key: slot.key, className: `anw-character-state-slot is-${slot.health}` },
            h("dt", null, slot.label),
            h(
              "dd",
              null,
              slot.values.length === 0
                ? h("span", { className: "anw-character-workspace-muted-value" }, "尚未形成可靠状态")
                : slot.values.map((value) => value.object_text).join("；"),
              slot.health !== "ok" && slot.health !== "missing"
                ? h("span", { className: "anw-character-fact-status" }, slot.health === "conflicted" ? "有冲突" : "不确定")
                : null,
            ),
          )),
        ),
      ),
      h(
        "aside",
        { className: `anw-character-state-risk${actionable ? " has-risk" : ""}` },
        h("h4", null, "核对摘要"),
        actionable === 0
          ? h("p", { className: "anw-character-state-ok" }, "当前状态来源清晰，没有待核对项。")
          : h(
              "ul",
              null,
              h("li", null, h("strong", null, risks.conflict_count), " 项冲突"),
              h("li", null, h("strong", null, risks.ambiguous_count), " 项不确定"),
              h("li", null, h("strong", null, risks.invalid_source_count), " 项来源失效"),
            ),
        h(
          "p",
          { className: "anw-character-workspace-meta" },
          `截至故事序位 ${state.as_of.narrative_cutoff ?? "最新"}`,
        ),
      ),
    ),
    h(
      "section",
      { className: "anw-character-recent" },
      h(
        "div",
        { className: "anw-character-subsection-heading" },
        h("div", null, h("h4", { id: props.recentChangesTitleId, tabIndex: -1 }, "最近变化"), h("p", null, "只显示最近 5 条，帮助续写前快速校准。")),
        h(
          "button",
          { type: "button", className: "anw-character-link-button", onClick: props.onToggleHistory },
          props.historyOpen ? "收起全部事实" : `查看全部事实（${state.history_summary.total}）`,
        ),
      ),
      recent.length === 0
        ? h("div", { className: "anw-character-workspace-empty" }, "尚无已确认的状态变化。")
        : h(
            "div",
            { className: "anw-character-recent-list" },
            ...recent.map((fact) => h(
              "article",
              { key: fact.id, className: "anw-character-recent-row" },
              h("span", { className: "anw-character-fact-dimension" }, characterFactDimensionLabel(fact.dimension)),
              h("div", { className: "anw-character-recent-content" }, h("strong", null, fact.object_text), h("small", null, fact.source?.document_title ?? "作者手工事实")),
              h("span", { className: "anw-character-fact-sequence" }, fact.story_sequence === null ? "未定位" : `序位 ${fact.story_sequence}`),
              h(
                "div",
                { className: "anw-character-row-actions" },
                fact.source ? h("button", { type: "button", onClick: (event: ButtonEvent) => props.onOpenSource(fact, event.currentTarget) }, "查看来源") : null,
                fact.effective_state === "current"
                  ? h("button", { type: "button", onClick: (event: ButtonEvent) => props.onCorrectFact(fact, event.currentTarget) }, "修正")
                  : null,
              ),
            )),
          ),
    ),
  );
}
