import type {
  JsonValue,
  StoryLedgerBatchImpactPreview,
  StoryLedgerFactImpactPreview,
} from "./contracts";
import type { StoryLedgerElementNode, StoryLedgerReactRuntime } from "./runtime";

interface InputEvent { readonly target: { readonly value: string } }

export interface StoryLedgerCorrectionFact {
  readonly id: string;
  readonly object_text: string;
  readonly source?: {
    readonly document_title: string;
    readonly revision_id: string;
    readonly source_excerpt: string;
  } | null;
  readonly details?: Readonly<Record<string, JsonValue>>;
}

export interface StoryFactCorrectionDrawerProps {
  readonly dialogId: string;
  readonly titleId: string;
  readonly fact: StoryLedgerCorrectionFact;
  readonly objectText: string;
  readonly reason: string;
  readonly saving: boolean;
  readonly error: string | null;
  readonly impact?: StoryLedgerFactImpactPreview | null;
  readonly impactLoading?: boolean;
  readonly impactError?: string | null;
  readonly onObjectTextChange: (value: string) => void;
  readonly onReasonChange: (value: string) => void;
  readonly onSubmit: () => void;
  readonly onClose: () => void;
}

export function renderStoryFactCorrectionDrawer(
  React: StoryLedgerReactRuntime,
  props: StoryFactCorrectionDrawerProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  const changed = props.objectText.trim() !== props.fact.object_text.trim();
  const ready = changed
    && Boolean(props.reason.trim())
    && !props.saving
    && !props.impactLoading
    && props.impact?.correction_supported !== false;
  return h(
    "aside",
    {
      id: props.dialogId,
      className: "anw-character-drawer anw-character-correction",
      role: "dialog",
      "aria-modal": true,
      "aria-labelledby": props.titleId,
      "aria-busy": props.saving || props.impactLoading || undefined,
      tabIndex: -1,
    },
    h("header", null, h("div", null, h("h3", { id: props.titleId }, "修正故事事实"), h("p", null, "创建替代事实；旧事实仍保留用于审计。")), h("button", { type: "button", "aria-label": "关闭修正面板", "data-character-drawer-close": "true", disabled: props.saving, onClick: props.onClose }, "×")),
    h(
      "div",
      { className: "anw-character-drawer-body" },
      h("section", null, h("h4", null, "原事实"), h("p", { className: "anw-character-evidence" }, props.fact.object_text)),
      props.fact.source ? h("section", null, h("h4", null, "来源证据"), h("p", null, `${props.fact.source.document_title} · revision ${props.fact.source.revision_id.slice(0, 8)}`), h("blockquote", null, props.fact.source.source_excerpt || "来源区间未提供可显示摘录")) : null,
      h("label", { className: "anw-character-workspace-field" }, h("span", null, "替代事实"), h("textarea", { value: props.objectText, onChange: (event: InputEvent) => props.onObjectTextChange(event.target.value) })),
      h("label", { className: "anw-character-workspace-field" }, h("span", null, "修正理由 *"), h("textarea", { value: props.reason, maxLength: 1000, onChange: (event: InputEvent) => props.onReasonChange(event.target.value) })),
      renderFactImpact(React, props),
      props.saving ? h("p", { role: "status", "aria-live": "polite" }, "正在创建替代事实，完成前无法关闭。") : null,
      props.error ? h("div", { className: "anw-character-workspace-alert", role: "alert" }, props.error) : null,
    ),
    h("footer", null, h("button", { type: "button", className: "anw-character-workspace-button", disabled: props.saving, onClick: props.onClose }, "取消"), h("button", { type: "button", className: "anw-character-workspace-button anw-character-workspace-button--primary", disabled: !ready, onClick: props.onSubmit }, props.saving ? "正在创建…" : "创建替代事实")),
  );
}

function renderFactImpact(
  React: StoryLedgerReactRuntime,
  props: StoryFactCorrectionDrawerProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  if (props.impactLoading) {
    return h("section", { className: "anw-character-correction-impact", role: "status" }, h("h4", null, "影响预览"), h("p", null, "正在读取当前账本快照的实际影响…"));
  }
  if (props.impactError) {
    return h("section", { className: "anw-character-correction-impact" }, h("h4", null, "影响预览"), h("p", { role: "alert" }, props.impactError));
  }
  if (!props.impact) {
    return h("section", { className: "anw-character-correction-impact" }, h("h4", null, "影响预览"), h("p", null, "提交前将按当前账本快照读取实际影响。"));
  }
  const impact = props.impact;
  return h(
    "section",
    { className: "anw-character-correction-impact" },
    h("h4", null, "影响预览"),
    h(
      "ul",
      null,
      h("li", null, impact.currently_in_projection ? "当前投影将重新计算" : "该事实当前未进入投影"),
      h("li", null, `${impact.related_event_link_count} 条事件链接受关联核对`),
      h("li", null, `${impact.batch_fact_count} 条批次事实、${impact.batch_relationship_count} 条关系记录相关`),
      h("li", null, impact.embedding_rebuild_required ? "语义索引需要重建" : "无需重建语义索引"),
    ),
    impact.correction_supported
      ? null
      : h("p", { role: "alert" }, impact.correction_block_reason || "当前事实不支持修正"),
  );
}

export interface StoryLedgerBatchRevertDrawerProps {
  readonly dialogId: string;
  readonly titleId: string;
  readonly impact: StoryLedgerBatchImpactPreview;
  readonly reason: string;
  readonly saving: boolean;
  readonly error: string | null;
  readonly onReasonChange: (value: string) => void;
  readonly onSubmit: () => void;
  readonly onClose: () => void;
}

export function renderStoryLedgerBatchRevertDrawer(
  React: StoryLedgerReactRuntime,
  props: StoryLedgerBatchRevertDrawerProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  const supersedeCount = props.impact.facts.filter(
    (fact) => fact.disposition === "supersede",
  ).length;
  const followupCount = props.impact.facts.filter(
    (fact) => fact.disposition === "preserve_followup",
  ).length;
  return h(
    "aside",
    {
      id: props.dialogId,
      className: "anw-character-drawer",
      role: "dialog",
      "aria-modal": true,
      "aria-labelledby": props.titleId,
      "aria-busy": props.saving || undefined,
      tabIndex: -1,
    },
    h("header", null, h("div", null, h("h3", { id: props.titleId }, "撤销本次同步"), h("p", null, "只撤销该批次产生的派生事实，人物与关系根记录保留。")), h("button", { type: "button", "aria-label": "关闭撤销面板", "data-character-drawer-close": "true", disabled: props.saving, onClick: props.onClose }, "×")),
    h("div", { className: "anw-character-drawer-body" }, h("section", { className: "anw-character-correction-impact" }, h("h4", null, "影响预览"), h("ul", null, h("li", null, `${supersedeCount} 条批次事实将标记为已撤销同步`), h("li", null, `${followupCount} 条后续修正保留`), h("li", null, `${props.impact.relationships.length} 条关系根记录保留并重新投影`))), h("label", { className: "anw-character-workspace-field" }, h("span", null, "撤销说明（可选）"), h("textarea", { value: props.reason, maxLength: 500, onChange: (event: InputEvent) => props.onReasonChange(event.target.value) })), props.saving ? h("p", { role: "status", "aria-live": "polite" }, "正在撤销同步，完成前无法关闭。") : null, props.error ? h("div", { className: "anw-character-workspace-alert", role: "alert" }, props.error) : null),
    h("footer", null, h("button", { type: "button", className: "anw-character-workspace-button", disabled: props.saving, onClick: props.onClose }, "取消"), h("button", { type: "button", className: "anw-character-workspace-button anw-character-workspace-button--danger", disabled: props.saving || props.impact.already_reverted, onClick: props.onSubmit }, props.saving ? "正在撤销…" : props.impact.already_reverted ? "已撤销" : "确认撤销同步")),
  );
}
