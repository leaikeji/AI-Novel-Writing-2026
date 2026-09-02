import type {
  JsonValue,
  StoryLedgerFactDetail,
  StoryLedgerFactItem,
} from "./contracts";
import { storyLedgerEntityLabel, storyLedgerFactTypeLabel } from "./fact-list";
import type { StoryLedgerElementNode, StoryLedgerReactRuntime } from "./runtime";
import {
  FACT_EFFECTIVE_REASON_LABELS,
  FACT_EFFECTIVE_STATE_LABELS,
  FACT_HEALTH_LABELS,
  FACT_HEALTH_REASON_LABELS,
} from "./state-model";

interface ButtonEvent {
  readonly currentTarget: HTMLElement;
}

interface KeyboardEventLike {
  readonly key: string;
  preventDefault(): void;
}

export interface StoryLedgerFactDetailProps {
  readonly idPrefix: string;
  readonly selectedItem: StoryLedgerFactItem | null;
  readonly detail: StoryLedgerFactDetail | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly multipleTimelines: boolean;
  readonly onRetry: () => void;
  readonly onClose: () => void;
  readonly onOpenSource: (fact: StoryLedgerFactItem, trigger: HTMLElement) => void;
  readonly onCorrect: (fact: StoryLedgerFactItem, trigger: HTMLElement) => void;
  readonly onPreviewBatchRevert: (
    fact: StoryLedgerFactItem,
    trigger: HTMLElement,
  ) => void;
}

export function renderStoryLedgerFactDetail(
  React: StoryLedgerReactRuntime,
  props: StoryLedgerFactDetailProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  const item = props.detail?.item ?? props.selectedItem;
  if (!item) {
    return h(
      "aside",
      { className: "anw-story-ledger-detail is-empty", "aria-label": "事实详情" },
      h("strong", null, "选择一条事实查看详情"),
      h("p", null, "这里会显示完整事实、权威状态解释、事件链接和不可变来源绑定。"),
    );
  }
  const titleId = `${props.idPrefix}-detail-title`;
  return h(
    "aside",
    {
      className: "anw-story-ledger-detail",
      "aria-labelledby": titleId,
      "aria-busy": props.loading || undefined,
      onKeyDown: (event: KeyboardEventLike) => {
        if (event.key === "Escape") {
          event.preventDefault();
          props.onClose();
        }
      },
    },
    h(
      "header",
      { className: "anw-story-ledger-detail-heading" },
      h(
        "div",
        null,
        h("p", null, storyLedgerFactTypeLabel(item.fact_type)),
        h("h2", { id: titleId, tabIndex: -1 }, item.subject || "未命名主体"),
      ),
      h("button", { type: "button", "aria-label": "关闭事实详情", onClick: props.onClose }, "×"),
    ),
    props.loading
      ? h("div", { className: "anw-story-ledger-state", role: "status" }, "正在读取事实详情…")
      : null,
    props.error
      ? h(
          "div",
          { className: "anw-story-ledger-state is-error", role: "alert" },
          h("p", null, props.error),
          h("button", { type: "button", onClick: props.onRetry }, "重新读取详情"),
        )
      : null,
    !props.loading && !props.error && props.detail
      ? renderLoadedDetail(React, props, props.detail)
      : null,
  );
}

function renderLoadedDetail(
  React: StoryLedgerReactRuntime,
  props: StoryLedgerFactDetailProps,
  detail: StoryLedgerFactDetail,
): StoryLedgerElementNode {
  const h = React.createElement;
  const item = detail.item;
  const canRevert = Boolean(item.source?.commit_batch_id);
  return h(
    "div",
    { className: "anw-story-ledger-detail-body" },
    h(
      "section",
      { "aria-labelledby": `${props.idPrefix}-detail-content` },
      h("h3", { id: `${props.idPrefix}-detail-content` }, "事实内容"),
      h("p", { className: "anw-story-ledger-detail-value" }, detail.object_text || "（空事实内容）"),
      h(
        "dl",
        { className: "anw-story-ledger-detail-properties" },
        detailRow(React, "谓词", item.predicate || "未提供"),
        detailRow(React, "维度", item.dimension || "未分类"),
        detailRow(React, "事件类型", item.event_kind || "不适用"),
        detailRow(
          React,
          "叙事序位",
          item.story_sequence === null ? "未定位" : String(item.story_sequence),
        ),
        props.multipleTimelines
          ? detailRow(React, "事实时间线", item.timeline_id || "全局／未绑定")
          : null,
        detailRow(React, "事实生命周期", detail.lifecycle_status),
        detail.schema_version_of_fact
          ? detailRow(React, "事实 schema", detail.schema_version_of_fact)
          : null,
      ),
    ),
    h(
      "section",
      { "aria-labelledby": `${props.idPrefix}-detail-authority` },
      h("h3", { id: `${props.idPrefix}-detail-authority` }, "权威状态与健康度"),
      h(
        "dl",
        { className: "anw-story-ledger-detail-properties" },
        detailRow(React, "生命周期结果", FACT_EFFECTIVE_STATE_LABELS[item.effective_state]),
        detailRow(
          React,
          "当前投影",
          item.included_in_current_projection ? "已纳入" : "未纳入",
        ),
        detailRow(React, "健康度", FACT_HEALTH_LABELS[item.health]),
      ),
      renderReasons(
        React,
        "生命周期解释",
        item.effective_reason_codes,
        FACT_EFFECTIVE_REASON_LABELS,
      ),
      renderReasons(
        React,
        "健康度解释",
        item.health_reason_codes,
        FACT_HEALTH_REASON_LABELS,
      ),
    ),
    h(
      "section",
      { "aria-labelledby": `${props.idPrefix}-detail-entities` },
      h("h3", { id: `${props.idPrefix}-detail-entities` }, "关联实体"),
      item.entities.length
        ? h(
            "ul",
            { className: "anw-story-ledger-detail-list" },
            ...item.entities.map((entity) => h(
              "li",
              { key: `${entity.entity_type}:${entity.entity_id}` },
              h("strong", null, storyLedgerEntityLabel(entity)),
              entity.lifecycle_state
                ? h("span", null, ` · 目录状态：${entity.lifecycle_state}`)
                : null,
            )),
          )
        : h(
            "p",
            { className: "anw-story-ledger-unlinked" },
            `未关联实体；原始主体“${item.subject || "未命名主体"}”仍作为不可变事实内容保留。`,
          ),
    ),
    Object.keys(detail.details).length
      ? renderJsonRecord(React, `${props.idPrefix}-detail-structured`, "结构化详情", detail.details)
      : null,
    detail.story_time
      ? renderJsonRecord(React, `${props.idPrefix}-detail-time`, "故事时间", detail.story_time)
      : null,
    detail.visibility
      ? renderJsonRecord(React, `${props.idPrefix}-detail-visibility`, "可见性", detail.visibility)
      : null,
    h(
      "section",
      { "aria-labelledby": `${props.idPrefix}-detail-links` },
      h("h3", { id: `${props.idPrefix}-detail-links` }, `事件链接（${detail.event_links.length}）`),
      detail.event_links.length
        ? h(
            "ul",
            { className: "anw-story-ledger-detail-list" },
            ...detail.event_links.map((link) => h(
              "li",
              { key: link.id },
              h("strong", null, link.direction === "incoming" ? "传入" : "传出"),
              ` · ${link.link_type} · 关联事实 ${link.other_fact_id}`,
            )),
          )
        : h("p", null, "没有事件链接。"),
    ),
    h(
      "section",
      { "aria-labelledby": `${props.idPrefix}-detail-bindings` },
      h("h3", { id: `${props.idPrefix}-detail-bindings` }, `不可变来源绑定（${detail.bindings.length}）`),
      detail.bindings.length
        ? h(
            "ul",
            { className: "anw-story-ledger-detail-list" },
            ...detail.bindings.map((binding) => h(
              "li",
              { key: binding.id },
              h("strong", null, `绑定 ${binding.validity_state}`),
              h("span", null, ` · revision ${binding.source_revision_id}`),
              binding.commit_batch_id
                ? h(
                    "span",
                    null,
                    ` · 批次 ${binding.commit_batch_id}${
                      binding.commit_batch_state ? `（${binding.commit_batch_state}）` : ""
                    }`,
                  )
                : null,
            )),
          )
        : h("p", null, "没有来源绑定；可能是作者手工事实。"),
    ),
    h(
      "footer",
      { className: "anw-story-ledger-detail-actions" },
      item.source
        ? h(
            "button",
            {
              type: "button",
              onClick: (event: ButtonEvent) => props.onOpenSource(item, event.currentTarget),
            },
            "查看来源证据",
          )
        : null,
      h(
        "button",
        {
          type: "button",
          onClick: (event: ButtonEvent) => props.onCorrect(item, event.currentTarget),
        },
        "检查并修正这条事实",
      ),
      canRevert
        ? h(
            "button",
            {
              type: "button",
              onClick: (event: ButtonEvent) => props.onPreviewBatchRevert(
                item,
                event.currentTarget,
              ),
            },
            "预览撤销同步批次",
          )
        : null,
    ),
  );
}

function detailRow(
  React: StoryLedgerReactRuntime,
  label: string,
  value: string,
): StoryLedgerElementNode {
  const h = React.createElement;
  return h("div", null, h("dt", null, label), h("dd", null, value));
}

function renderReasons(
  React: StoryLedgerReactRuntime,
  title: string,
  reasonCodes: readonly string[],
  labels: Readonly<Record<string, string>>,
): StoryLedgerElementNode {
  const h = React.createElement;
  return h(
    "div",
    { className: "anw-story-ledger-reasons" },
    h("h4", null, title),
    reasonCodes.length
      ? h(
          "ul",
          null,
          ...reasonCodes.map((code) => h("li", { key: code }, labels[code] ?? code)),
        )
      : h("p", null, "服务端未返回补充原因。"),
  );
}

function renderJsonRecord(
  React: StoryLedgerReactRuntime,
  titleId: string,
  title: string,
  record: Readonly<Record<string, JsonValue>>,
): StoryLedgerElementNode {
  const h = React.createElement;
  return h(
    "section",
    { "aria-labelledby": titleId },
    h("h3", { id: titleId }, title),
    h(
      "dl",
      { className: "anw-story-ledger-detail-properties" },
      ...Object.entries(record).map(([key, value]) => detailRow(
        React,
        key,
        displayJsonValue(value),
      )),
    ),
  );
}

function displayJsonValue(value: JsonValue): string {
  if (value === null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
