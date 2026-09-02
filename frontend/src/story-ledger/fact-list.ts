import type {
  StoryLedgerEntityReference,
  StoryLedgerFactItem,
} from "./contracts";
import {
  STORY_LEDGER_ENTITY_TYPE_LABELS,
  STORY_LEDGER_FACT_TYPE_LABELS,
} from "./filters";
import type { StoryLedgerElementNode, StoryLedgerReactRuntime } from "./runtime";
import {
  FACT_EFFECTIVE_STATE_LABELS,
  FACT_HEALTH_LABELS,
} from "./state-model";

interface ButtonEvent {
  readonly currentTarget: HTMLElement;
}

interface KeyboardEventLike {
  readonly key: string;
  readonly currentTarget: HTMLElement;
  preventDefault(): void;
  stopPropagation?(): void;
}

export interface StoryLedgerFactListProps {
  readonly idPrefix: string;
  readonly items: readonly StoryLedgerFactItem[];
  readonly selectedFactId: string | null;
  readonly multipleTimelines: boolean;
  readonly loading: boolean;
  readonly loadingMore: boolean;
  readonly error: string | null;
  readonly nextCursor: string | null;
  readonly openMenuFactId: string | null;
  readonly onSelect: (fact: StoryLedgerFactItem, trigger: HTMLElement) => void;
  readonly onOpenSource: (fact: StoryLedgerFactItem, trigger: HTMLElement) => void;
  readonly onCorrect: (fact: StoryLedgerFactItem, trigger: HTMLElement) => void;
  readonly onPreviewBatchRevert: (
    fact: StoryLedgerFactItem,
    trigger: HTMLElement,
  ) => void;
  readonly onMenuOpenChange: (factId: string | null) => void;
  readonly onLoadMore: () => void;
  readonly onRetry: () => void;
}

export function storyLedgerFactTypeLabel(factType: string): string {
  return STORY_LEDGER_FACT_TYPE_LABELS[factType] ?? `其他事实（${factType}）`;
}

export function storyLedgerEntityLabel(entity: StoryLedgerEntityReference): string {
  const type = STORY_LEDGER_ENTITY_TYPE_LABELS[entity.entity_type];
  if (entity.reference_missing) {
    return `历史／未链接${type}：${entity.label || entity.entity_id}`;
  }
  return `${type}：${entity.label || entity.entity_id}`;
}

export function renderStoryLedgerFactList(
  React: StoryLedgerReactRuntime,
  props: StoryLedgerFactListProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  const restoreMenuFocus = (factId: string): void => {
    if (typeof document === "undefined") return;
    document.getElementById(`${props.idPrefix}-more-${safeId(factId)}`)?.focus();
  };
  const menuTrigger = (factId: string, fallback: HTMLElement): HTMLElement => {
    if (typeof document === "undefined") return fallback;
    return document.getElementById(
      `${props.idPrefix}-more-${safeId(factId)}`,
    ) as HTMLElement | null ?? fallback;
  };
  const closeMenu = (factId: string): void => {
    props.onMenuOpenChange(null);
    restoreMenuFocus(factId);
  };

  if (props.loading && props.items.length === 0) {
    return h(
      "div",
      {
        className: "anw-story-ledger-state",
        role: "status",
        "aria-live": "polite",
      },
      "正在读取故事事实…",
    );
  }
  if (props.error && props.items.length === 0) {
    return h(
      "div",
      { className: "anw-story-ledger-state is-error", role: "alert" },
      h("p", null, props.error),
      h("button", { type: "button", onClick: props.onRetry }, "重新加载"),
    );
  }
  if (props.items.length === 0) {
    return h(
      "div",
      { className: "anw-story-ledger-state" },
      h("strong", null, "当前筛选下没有事实"),
      h("p", null, "可以清除部分筛选，或切换到其他时间线查看。"),
    );
  }

  return h(
    "div",
    { className: "anw-story-ledger-list-region" },
    props.error
      ? h("div", { className: "anw-story-ledger-inline-error", role: "alert" }, props.error)
      : null,
    h(
      "ul",
      {
        className: "anw-story-ledger-fact-list",
        "aria-label": "故事账本事实记录",
        "aria-busy": props.loading || props.loadingMore || undefined,
      },
      ...props.items.map((fact) => {
        const itemId = `${props.idPrefix}-fact-${safeId(fact.id)}`;
        const menuId = `${itemId}-menu`;
        const menuOpen = props.openMenuFactId === fact.id;
        const hasSource = Boolean(fact.source);
        // The impact endpoints are the authority for whether a correction or
        // batch revert is supported. The list must not reproduce those rules.
        const canCorrect = true;
        const canRevert = Boolean(fact.source?.commit_batch_id);
        const hasMenu = hasSource || canCorrect || canRevert;
        return h(
          "li",
          { key: fact.id, className: "anw-story-ledger-fact-record" },
          h(
            "article",
            {
              id: itemId,
              className: `anw-story-ledger-fact-card${
                props.selectedFactId === fact.id ? " is-selected" : ""
              }`,
              "aria-labelledby": `${itemId}-title`,
            },
            h(
              "header",
              { className: "anw-story-ledger-fact-heading" },
              h(
                "div",
                null,
                h(
                  "p",
                  { className: "anw-story-ledger-fact-kicker" },
                  storyLedgerFactTypeLabel(fact.fact_type),
                ),
                h("h3", { id: `${itemId}-title` }, fact.subject || "未命名主体"),
              ),
              h(
                "div",
                { className: "anw-story-ledger-fact-badges" },
                h(
                  "span",
                  { className: `is-effective-${fact.effective_state}` },
                  FACT_EFFECTIVE_STATE_LABELS[fact.effective_state],
                ),
                fact.health === "ok"
                  ? null
                  : h(
                      "span",
                      { className: `is-health-${fact.health}` },
                      FACT_HEALTH_LABELS[fact.health],
                    ),
              ),
            ),
            h(
              "p",
              { className: "anw-story-ledger-fact-value" },
              h("span", { className: "anw-story-ledger-field-label" }, "事实内容"),
              fact.object_preview || "（空事实内容）",
              fact.object_truncated ? h("span", { "aria-label": "内容已截断" }, "…") : null,
            ),
            h(
              "dl",
              { className: "anw-story-ledger-fact-meta" },
              metaRow(React, "谓词", fact.predicate || "未提供"),
              metaRow(React, "维度", fact.dimension || "未分类"),
              metaRow(
                React,
                "叙事序位",
                fact.story_sequence === null ? "未定位" : String(fact.story_sequence),
              ),
              props.multipleTimelines
                ? metaRow(React, "事实时间线", fact.timeline_id || "全局／未绑定")
                : null,
              metaRow(
                React,
                "来源",
                fact.source?.document_title
                  || (fact.source ? "来源记录未命名" : "作者手工事实／无来源绑定"),
              ),
            ),
            h(
              "div",
              {
                className: "anw-story-ledger-entities",
                "aria-label": "关联实体",
              },
              fact.entities.length
                ? fact.entities.map((entity) => h(
                    "span",
                    {
                      key: `${entity.entity_type}:${entity.entity_id}`,
                      className: entity.reference_missing ? "is-missing" : undefined,
                    },
                    storyLedgerEntityLabel(entity),
                  ))
                : h(
                    "span",
                    { className: "is-unlinked" },
                    `未关联实体 · 保留原始主体：${fact.subject || "未命名主体"}`,
                  ),
            ),
            h(
              "footer",
              { className: "anw-story-ledger-fact-actions" },
              h(
                "button",
                {
                  type: "button",
                  className: "anw-story-ledger-primary-action",
                  onClick: (event: ButtonEvent) => props.onSelect(fact, event.currentTarget),
                },
                "查看",
              ),
              hasMenu
                ? h(
                    "div",
                    { className: "anw-story-ledger-action-menu" },
                    h(
                      "button",
                      {
                        id: `${props.idPrefix}-more-${safeId(fact.id)}`,
                        type: "button",
                        "aria-haspopup": "menu",
                        "aria-expanded": menuOpen,
                        "aria-controls": menuId,
                        "aria-label": `更多操作：${fact.subject || storyLedgerFactTypeLabel(fact.fact_type)}`,
                        onClick: () => props.onMenuOpenChange(menuOpen ? null : fact.id),
                        onKeyDown: (event: KeyboardEventLike) => {
                          if (["ArrowDown", "Enter", " "].includes(event.key)) {
                            event.preventDefault();
                            props.onMenuOpenChange(fact.id);
                          } else if (event.key === "Escape" && menuOpen) {
                            event.preventDefault();
                            closeMenu(fact.id);
                          }
                        },
                      },
                      "更多",
                    ),
                    menuOpen
                      ? h(
                          "div",
                          {
                            id: menuId,
                            className: "anw-story-ledger-menu-popover",
                            role: "menu",
                            "aria-label": `${fact.subject || "事实"}的更多操作`,
                            onKeyDown: (event: KeyboardEventLike) => {
                              if (event.key === "Escape") {
                                event.preventDefault();
                                event.stopPropagation?.();
                                closeMenu(fact.id);
                              }
                            },
                          },
                          hasSource
                            ? menuButton(React, "查看来源", (event) => {
                                props.onOpenSource(
                                  fact,
                                  menuTrigger(fact.id, event.currentTarget),
                                );
                                props.onMenuOpenChange(null);
                              })
                            : null,
                          canCorrect
                            ? menuButton(React, "修正事实", (event) => {
                                props.onCorrect(
                                  fact,
                                  menuTrigger(fact.id, event.currentTarget),
                                );
                                props.onMenuOpenChange(null);
                              })
                            : null,
                          canRevert
                            ? menuButton(React, batchActionLabel(fact), (event) => {
                                props.onPreviewBatchRevert(
                                  fact,
                                  menuTrigger(fact.id, event.currentTarget),
                                );
                                props.onMenuOpenChange(null);
                              })
                            : null,
                        )
                      : null,
                  )
                : null,
            ),
          ),
        );
      }),
    ),
    props.nextCursor
      ? h(
          "button",
          {
            type: "button",
            className: "anw-story-ledger-load-more",
            disabled: props.loadingMore,
            onClick: props.onLoadMore,
          },
          props.loadingMore ? "正在加载更多…" : "加载更多事实",
        )
      : null,
  );
}

function metaRow(
  React: StoryLedgerReactRuntime,
  label: string,
  value: string,
): StoryLedgerElementNode {
  const h = React.createElement;
  return h("div", null, h("dt", null, label), h("dd", null, value));
}

function menuButton(
  React: StoryLedgerReactRuntime,
  label: string,
  onClick: (event: ButtonEvent) => void,
): StoryLedgerElementNode {
  return React.createElement(
    "button",
    { type: "button", role: "menuitem", onClick },
    label,
  );
}

function batchActionLabel(fact: StoryLedgerFactItem): string {
  if (fact.source?.document_position !== null
    && fact.source?.document_position !== undefined) {
    return `预览撤销第 ${fact.source.document_position} 章同步`;
  }
  return `预览撤销同步批次 ${fact.source?.commit_batch_id ?? ""}`.trim();
}

function safeId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "-");
}
