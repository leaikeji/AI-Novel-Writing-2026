import type { CharacterReactRuntime } from "./character-workspace";
import type { ProjectedFactViewV2 } from "./contracts";

type ElementNode = unknown;

interface ButtonEvent {
  readonly currentTarget: HTMLElement;
}

interface MenuKeyboardEvent {
  readonly key: string;
  readonly currentTarget: HTMLElement & { open?: boolean };
  preventDefault(): void;
  stopPropagation?(): void;
}

export interface CharacterFactActionsProps {
  readonly fact: ProjectedFactViewV2;
  readonly menuIdPrefix: string;
  readonly onOpenSource?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
  readonly onCorrectFact?: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void;
}

function closeActionMenu(trigger: HTMLElement): HTMLElement {
  const details = trigger.closest?.("details");
  const summary = details?.querySelector<HTMLElement>("summary") ?? null;
  if (details && "open" in details) details.open = false;
  return summary ?? trigger;
}

function invokeAction(
  event: ButtonEvent,
  fact: ProjectedFactViewV2,
  action: (fact: ProjectedFactViewV2, trigger: HTMLElement) => void,
): void {
  action(fact, closeActionMenu(event.currentTarget));
}

/**
 * Keep the source action visible while moving destructive or mutating actions
 * into a native disclosure. `details/summary` remains operable without a
 * JavaScript menu state machine; Escape explicitly closes it and restores the
 * summary focus instead of escaping the whole character dialog.
 */
export function renderCharacterFactActions(
  React: CharacterReactRuntime,
  props: CharacterFactActionsProps,
): ElementNode {
  const h = React.createElement;
  const canCorrect = props.fact.effective_state === "current" && Boolean(props.onCorrectFact);
  const hasMore = canCorrect;
  const safeFactId = props.fact.id.replace(/[^a-zA-Z0-9_-]/g, "-");
  const safePrefix = props.menuIdPrefix.replace(/[^a-zA-Z0-9_-]/g, "-");
  const menuId = `${safePrefix}-fact-actions-${safeFactId}`;

  return h(
    "div",
    { className: "anw-character-row-actions" },
    props.fact.source && props.onOpenSource
      ? h(
          "button",
          {
            type: "button",
            className: "anw-character-row-primary-action",
            "aria-label": `查看${props.fact.object_text}的来源`,
            onClick: (event: ButtonEvent) => invokeAction(
              event,
              props.fact,
              props.onOpenSource as NonNullable<CharacterFactActionsProps["onOpenSource"]>,
            ),
          },
          "查看",
        )
      : null,
    hasMore
      ? h(
          "details",
          {
            className: "anw-character-action-menu",
            onKeyDown: (event: MenuKeyboardEvent) => {
              if (event.key !== "Escape" || !event.currentTarget.open) return;
              event.preventDefault();
              event.stopPropagation?.();
              event.currentTarget.open = false;
              event.currentTarget.querySelector<HTMLElement>("summary")?.focus({ preventScroll: true });
            },
          },
          h(
            "summary",
            {
              "aria-controls": menuId,
              "aria-haspopup": "menu",
              "aria-label": `${props.fact.object_text}的更多操作`,
            },
            "更多",
          ),
          h(
            "div",
            { id: menuId, className: "anw-character-action-menu-popover", role: "menu" },
            canCorrect
              ? h(
                  "button",
                  {
                    type: "button",
                    role: "menuitem",
                    onClick: (event: ButtonEvent) => invokeAction(
                      event,
                      props.fact,
                      props.onCorrectFact as NonNullable<CharacterFactActionsProps["onCorrectFact"]>,
                    ),
                  },
                  "修正",
                )
              : null,
          ),
        )
      : null,
  );
}
