import type { CharacterReactRuntime } from "./character-workspace";
import type { CharacterWorkspaceV2, ProjectedFactViewV2 } from "./contracts";
import { characterFactDimensionLabel } from "./model";
import { renderCharacterFactActions } from "./character-fact-actions";

type ElementNode = unknown;

export interface CharacterStatePanelProps {
  readonly currentStateTitleId: string;
  readonly recentChangesTitleId: string;
  readonly workspace: CharacterWorkspaceV2;
  readonly historyOpen: boolean;
  readonly onToggleHistory: () => void;
  readonly onOpenSource?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onCorrectFact?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
}

const WRITING_STATE_DIMENSION_COUNT = 8;
const DEFAULT_VISIBLE_VALUES = 3;
const DEFAULT_VISIBLE_CODE_POINTS = 120;

function renderBoundedStateValue(
  React: CharacterReactRuntime,
  value: string,
  key: string,
): ElementNode {
  const h = React.createElement;
  const codePoints = [...value];
  if (codePoints.length <= DEFAULT_VISIBLE_CODE_POINTS) return value;
  const preview = `${codePoints.slice(0, DEFAULT_VISIBLE_CODE_POINTS).join("")}…`;
  return h(
    "span",
    { key, className: "anw-character-state-bounded-value" },
    h("span", null, preview),
    h(
      "details",
      null,
      h("summary", null, "查看完整内容"),
      h("p", null, value),
    ),
  );
}

function renderStateValues(
  React: CharacterReactRuntime,
  values: CharacterWorkspaceV2["writing_state"]["slots"][number]["values"],
): ElementNode {
  const h = React.createElement;
  if (values.length === 0) {
    return h("span", { className: "anw-character-workspace-muted-value" }, "尚未形成可靠状态");
  }
  const visible = values.slice(0, DEFAULT_VISIBLE_VALUES);
  const remaining = values.slice(DEFAULT_VISIBLE_VALUES);
  return h(
    "div",
    { className: "anw-character-state-value-group" },
    h(
      "ul",
      { className: "anw-character-state-values" },
      ...visible.map((value) => h(
        "li",
        { key: value.fact_id },
        renderBoundedStateValue(React, value.object_text, value.fact_id),
      )),
    ),
    remaining.length > 0
      ? h(
          "details",
          { className: "anw-character-state-more-values" },
          h("summary", null, `共 ${values.length} 条，查看全部`),
          h(
            "ul",
            null,
            ...remaining.map((value) => h(
              "li",
              { key: value.fact_id },
              renderBoundedStateValue(React, value.object_text, value.fact_id),
            )),
          ),
        )
      : null,
  );
}

export function renderCharacterStatePanel(
  React: CharacterReactRuntime,
  props: CharacterStatePanelProps,
): ElementNode {
  const h = React.createElement;
  const state = props.workspace.writing_state;
  const risks = state.risk_summary;
  const actionable = risks.conflict_count + risks.ambiguous_count + risks.invalid_source_count;
  const recent = state.recent_changes.slice(0, 5);
  const recordedDimensions = Math.min(
    WRITING_STATE_DIMENSION_COUNT,
    state.slots.filter((slot) => slot.values.length > 0).length,
  );
  const missingDimensions = WRITING_STATE_DIMENSION_COUNT - recordedDimensions;

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
              renderStateValues(React, slot.values),
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
        h(
          "p",
          { className: "anw-character-state-coverage" },
          `已记录 ${recordedDimensions}/${WRITING_STATE_DIMENSION_COUNT}，${missingDimensions} 项尚无事实。`,
        ),
        actionable === 0
          ? h(
              "p",
              { className: "anw-character-state-ok" },
              missingDimensions > 0
                ? "暂未发现冲突、不确定或来源失效；缺失维度仍需按写作需要补充。"
                : "8 项关键状态均有事实，暂未发现需要核对的异常。",
            )
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
            "ul",
            { className: "anw-character-recent-list" },
            ...recent.map((fact) => h(
              "li",
              { key: fact.id, className: "anw-character-recent-row" },
              h("span", { className: "anw-character-fact-dimension" }, characterFactDimensionLabel(fact.dimension)),
              h("div", { className: "anw-character-recent-content" }, h("strong", null, fact.object_text), h("small", null, fact.source?.document_title ?? "作者手工事实")),
              h("span", { className: "anw-character-fact-sequence" }, fact.story_sequence === null ? "未定位" : `序位 ${fact.story_sequence}`),
              renderCharacterFactActions(React, {
                fact,
                menuIdPrefix: props.recentChangesTitleId,
                onOpenSource: props.onOpenSource,
                onCorrectFact: props.onCorrectFact,
              }),
            )),
          ),
    ),
  );
}
