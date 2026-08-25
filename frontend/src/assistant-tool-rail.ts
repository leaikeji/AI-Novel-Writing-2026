export type AssistantToolRailMode = "edge" | "footer";
export type AssistantToolRailOrientation = "vertical" | "horizontal";
export type AssistantToolRailOverflow = "none" | "scroll";


export const ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE = 40;
export const ASSISTANT_TOOL_RAIL_DEFAULT_HIT_SIZE = 48;
export const ASSISTANT_TOOL_RAIL_DEFAULT_WIDTH = 60;
export const ASSISTANT_TOOL_RAIL_DEFAULT_GAP = 16;
export const ASSISTANT_TOOL_RAIL_DEFAULT_ITEM_GAP = 12;
export const ASSISTANT_TOOL_RAIL_DEFAULT_EDITOR_MIN_WIDTH = 760;
export const ASSISTANT_TOOL_RAIL_DEFAULT_VIEWPORT_HEIGHT = 1_080;
export const ASSISTANT_TOOL_RAIL_DEFAULT_FOOTER_HEIGHT = 56;


export interface AssistantToolRailGeometryInput {
  viewportWidth: number;
  viewportHeight?: number;
  hostNavigationWidth: number;
  hostHeaderHeight?: number;
  chapterTreeWidth: number;
  assistantPaneWidth: number;
  toolRailWidth?: number;
  gap?: number;
  itemGap?: number;
  itemCount?: number;
  buttonHitSize?: number;
  footerHeight?: number;
  minimumEditorCanvasWidth?: number;
  ariaLabel?: string;
  className?: string;
}


export interface AssistantToolRailRootProps {
  readonly className: string;
  readonly role: "toolbar";
  readonly "aria-label": string;
  readonly "aria-orientation": AssistantToolRailOrientation;
  readonly "data-assistant-tool-rail-mode": AssistantToolRailMode;
  readonly "data-assistant-tool-rail-orientation": AssistantToolRailOrientation;
  readonly "data-assistant-tool-rail-overflow": AssistantToolRailOverflow;
  readonly "data-assistant-tool-rail-right": string;
  readonly "data-assistant-pane-left": string;
  readonly "data-assistant-tool-rail-min-hit-size": string;
  readonly style: Readonly<Record<string, string>>;
}


export interface AssistantToolRailGeometry {
  mode: AssistantToolRailMode;
  orientation: AssistantToolRailOrientation;
  overflow: AssistantToolRailOverflow;
  editorLeft: number;
  editorRight: number;
  assistantLeft: number;
  railLeft: number;
  railRight: number;
  railTop: number;
  railBottom: number;
  railWidth: number;
  railHeight: number;
  buttonHitSize: number;
  itemGap: number;
  rootProps: AssistantToolRailRootProps;
}


export interface AssistantToolRailItem {
  id: string;
  ariaLabel: string;
  disabled?: boolean;
  className?: string;
}


export interface AssistantToolRailButtonProps {
  readonly type: "button";
  readonly className: string;
  readonly tabIndex: 0 | -1;
  readonly disabled?: true;
  readonly "aria-label": string;
  readonly "aria-disabled"?: true;
  readonly "data-assistant-tool-rail-item": string;
  readonly "data-assistant-tool-rail-roving": "active" | "inactive";
  readonly "data-assistant-tool-rail-hit-size": string;
  readonly style: Readonly<{ minWidth: string; minHeight: string }>;
}


export interface AssistantToolRailRovingFocus {
  readonly activeIndex: number;
  readonly activeItemId?: string;
  readonly itemProps: readonly AssistantToolRailButtonProps[];
}


function finiteNonNegative(value: number | undefined, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.round(value))
    : fallback;
}


function finitePositiveInteger(value: number | undefined, fallback: number): number {
  const normalized = finiteNonNegative(value, fallback);
  return normalized > 0 ? normalized : fallback;
}


function joinClassNames(...values: Array<string | undefined>): string {
  return values
    .flatMap((value) => value?.split(/\s+/) ?? [])
    .filter(Boolean)
    .join(" ");
}


function toolRailRootProps(input: {
  mode: AssistantToolRailMode;
  orientation: AssistantToolRailOrientation;
  overflow: AssistantToolRailOverflow;
  railRight: number;
  assistantLeft: number;
  railWidth: number;
  railHeight: number;
  buttonHitSize: number;
  gap: number;
  itemGap: number;
  ariaLabel: string;
  className?: string;
}): AssistantToolRailRootProps {
  return Object.freeze({
    className: joinClassNames(
      "anw-editor-side-tools",
      "anw-assistant-tool-rail",
      `is-${input.mode}`,
      `is-${input.orientation}`,
      input.overflow === "scroll" ? "has-scroll-overflow" : undefined,
      input.className,
    ),
    role: "toolbar",
    "aria-label": input.ariaLabel,
    "aria-orientation": input.orientation,
    "data-assistant-tool-rail-mode": input.mode,
    "data-assistant-tool-rail-orientation": input.orientation,
    "data-assistant-tool-rail-overflow": input.overflow,
    "data-assistant-tool-rail-right": String(input.railRight),
    "data-assistant-pane-left": String(input.assistantLeft),
    "data-assistant-tool-rail-min-hit-size": String(input.buttonHitSize),
    style: Object.freeze({
      "--anw-assistant-tool-rail-inline-size": `${input.railWidth}px`,
      "--anw-assistant-tool-rail-block-size": `${input.railHeight}px`,
      "--anw-assistant-tool-rail-gap": `${input.gap}px`,
      "--anw-assistant-tool-rail-item-gap": `${input.itemGap}px`,
      "--anw-assistant-tool-rail-hit-size": `${input.buttonHitSize}px`,
    }),
  });
}


/**
 * 计算结果以当前 visual viewport 的 CSS px 为证据坐标，但 rootProps 不包含
 * position:fixed 或视口 right 值。页面应把节点放进中心编辑区的相对布局上下文，
 * 并由 A1-G 样式消费 class/data/CSS 变量。
 */
export function resolveAssistantToolRailGeometry(
  input: AssistantToolRailGeometryInput,
): AssistantToolRailGeometry {
  const viewportWidth = finiteNonNegative(input.viewportWidth);
  const viewportHeight = finitePositiveInteger(
    input.viewportHeight,
    ASSISTANT_TOOL_RAIL_DEFAULT_VIEWPORT_HEIGHT,
  );
  const hostNavigationWidth = finiteNonNegative(input.hostNavigationWidth);
  const hostHeaderHeight = Math.min(
    viewportHeight,
    finiteNonNegative(input.hostHeaderHeight),
  );
  const chapterTreeWidth = finiteNonNegative(input.chapterTreeWidth);
  const assistantPaneWidth = finiteNonNegative(input.assistantPaneWidth);
  const buttonHitSize = Math.max(
    ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE,
    finiteNonNegative(
      input.buttonHitSize,
      ASSISTANT_TOOL_RAIL_DEFAULT_HIT_SIZE,
    ),
  );
  const toolRailWidth = Math.max(
    buttonHitSize,
    finiteNonNegative(
      input.toolRailWidth,
      ASSISTANT_TOOL_RAIL_DEFAULT_WIDTH,
    ),
  );
  const gap = Math.max(
    8,
    finiteNonNegative(input.gap, ASSISTANT_TOOL_RAIL_DEFAULT_GAP),
  );
  const itemGap = Math.max(
    0,
    finiteNonNegative(input.itemGap, ASSISTANT_TOOL_RAIL_DEFAULT_ITEM_GAP),
  );
  const itemCount = finiteNonNegative(input.itemCount, 4);
  const minimumEditorCanvasWidth = Math.max(
    320,
    finiteNonNegative(
      input.minimumEditorCanvasWidth,
      ASSISTANT_TOOL_RAIL_DEFAULT_EDITOR_MIN_WIDTH,
    ),
  );
  const footerHeight = Math.max(
    buttonHitSize,
    finiteNonNegative(
      input.footerHeight,
      ASSISTANT_TOOL_RAIL_DEFAULT_FOOTER_HEIGHT,
    ),
  );
  const editorLeft = Math.min(
    viewportWidth,
    hostNavigationWidth + chapterTreeWidth,
  );
  const assistantLeft = Math.max(editorLeft, viewportWidth - assistantPaneWidth);
  const editorRight = assistantLeft;
  const availableEditorWidth = Math.max(0, editorRight - editorLeft);
  const requiredItemSpan = itemCount > 0
    ? itemCount * buttonHitSize + (itemCount - 1) * itemGap
    : 0;
  const availableVerticalSpan = Math.max(
    0,
    viewportHeight - hostHeaderHeight - gap * 2,
  );
  const requiredVerticalSpan = Math.max(buttonHitSize, requiredItemSpan);
  const canUseEdge = availableEditorWidth >= (
    minimumEditorCanvasWidth + toolRailWidth + gap * 2
  ) && requiredVerticalSpan <= availableVerticalSpan;

  if (canUseEdge) {
    const railRight = Math.max(editorLeft, editorRight - gap);
    const railLeft = Math.max(editorLeft, railRight - toolRailWidth);
    const railHeight = requiredVerticalSpan;
    const railTop = hostHeaderHeight + gap + Math.max(
      0,
      Math.round((availableVerticalSpan - railHeight) / 2),
    );
    const railBottom = Math.min(viewportHeight, railTop + railHeight);
    const overflow: AssistantToolRailOverflow = requiredItemSpan > railHeight
      ? "scroll"
      : "none";
    const rootProps = toolRailRootProps({
      mode: "edge",
      orientation: "vertical",
      overflow,
      railRight,
      assistantLeft,
      railWidth: railRight - railLeft,
      railHeight,
      buttonHitSize,
      gap,
      itemGap,
      ariaLabel: input.ariaLabel?.trim() || "章节工具",
      className: input.className,
    });
    return Object.freeze({
      mode: "edge",
      orientation: "vertical",
      overflow,
      editorLeft,
      editorRight,
      assistantLeft,
      railLeft,
      railRight,
      railTop,
      railBottom,
      railWidth: railRight - railLeft,
      railHeight,
      buttonHitSize,
      itemGap,
      rootProps,
    });
  }

  const railLeft = Math.min(editorRight, editorLeft + gap);
  const railRight = Math.max(railLeft, editorRight - gap);
  const railHeight = Math.min(
    footerHeight,
    Math.max(buttonHitSize, viewportHeight - hostHeaderHeight),
  );
  const railBottom = viewportHeight;
  const railTop = Math.max(hostHeaderHeight, railBottom - railHeight);
  const railWidth = railRight - railLeft;
  const overflow: AssistantToolRailOverflow = requiredItemSpan > railWidth
    ? "scroll"
    : "none";
  const rootProps = toolRailRootProps({
    mode: "footer",
    orientation: "horizontal",
    overflow,
    railRight,
    assistantLeft,
    railWidth,
    railHeight,
    buttonHitSize,
    gap,
    itemGap,
    ariaLabel: input.ariaLabel?.trim() || "章节工具",
    className: input.className,
  });
  return Object.freeze({
    mode: "footer",
    orientation: "horizontal",
    overflow,
    editorLeft,
    editorRight,
    assistantLeft,
    railLeft,
    railRight,
    railTop,
    railBottom,
    railWidth,
    railHeight,
    buttonHitSize,
    itemGap,
    rootProps,
  });
}


function normalizedItems(
  items: readonly AssistantToolRailItem[],
): readonly AssistantToolRailItem[] {
  const ids = new Set<string>();
  return items.map((item) => {
    const id = item.id.trim();
    const ariaLabel = item.ariaLabel.trim();
    if (!id) throw new Error("assistant tool rail item id must not be empty");
    if (ids.has(id)) {
      throw new Error(`duplicate assistant tool rail item id: ${id}`);
    }
    if (!ariaLabel) {
      throw new Error(`assistant tool rail item ariaLabel must not be empty: ${id}`);
    }
    ids.add(id);
    return { ...item, id, ariaLabel };
  });
}


function enabledIndices(items: readonly AssistantToolRailItem[]): number[] {
  const result: number[] = [];
  items.forEach((item, index) => {
    if (item.disabled !== true) result.push(index);
  });
  return result;
}


function nearestEnabledIndex(
  enabled: readonly number[],
  requestedIndex: number,
): number {
  if (enabled.length === 0) return -1;
  const normalizedRequest = Number.isFinite(requestedIndex)
    ? Math.max(0, Math.round(requestedIndex))
    : 0;
  return enabled.find((index) => index >= normalizedRequest) ?? enabled[0];
}


/**
 * 返回可以直接展开到原生 button/Ant Button 的 props。只有一个可用项进入 Tab
 * 顺序；disabled 项永远不会成为 roving target。命中区通过内联 min-size 与 data
 * 契约双重声明，A1-G 仍负责最终视觉样式。
 */
export function resolveAssistantToolRailRovingFocus(
  rawItems: readonly AssistantToolRailItem[],
  requestedIndex = 0,
  requestedHitSize = ASSISTANT_TOOL_RAIL_DEFAULT_HIT_SIZE,
): AssistantToolRailRovingFocus {
  const items = normalizedItems(rawItems);
  const hitSize = Math.max(
    ASSISTANT_TOOL_RAIL_MIN_HIT_SIZE,
    finiteNonNegative(requestedHitSize, ASSISTANT_TOOL_RAIL_DEFAULT_HIT_SIZE),
  );
  const enabled = enabledIndices(items);
  const requested = Number.isFinite(requestedIndex)
    ? Math.max(0, Math.min(items.length - 1, Math.round(requestedIndex)))
    : 0;
  const activeIndex = enabled.includes(requested)
    ? requested
    : nearestEnabledIndex(enabled, requested);
  const itemProps = items.map((item, index): AssistantToolRailButtonProps => {
    const active = index === activeIndex;
    const disabled = item.disabled === true;
    return Object.freeze({
      type: "button",
      className: joinClassNames(
        "anw-assistant-tool-rail-button",
        active ? "is-roving-active" : undefined,
        item.className,
      ),
      tabIndex: active ? 0 : -1,
      disabled: disabled ? true : undefined,
      "aria-label": item.ariaLabel,
      "aria-disabled": disabled ? true : undefined,
      "data-assistant-tool-rail-item": item.id,
      "data-assistant-tool-rail-roving": active ? "active" : "inactive",
      "data-assistant-tool-rail-hit-size": String(hitSize),
      style: Object.freeze({
        minWidth: `${hitSize}px`,
        minHeight: `${hitSize}px`,
      }),
    });
  });
  return Object.freeze({
    activeIndex,
    activeItemId: activeIndex >= 0 ? items[activeIndex]?.id : undefined,
    itemProps: Object.freeze(itemProps),
  });
}


export function assistantToolRailRovingIndexFromKey(
  currentIndex: number,
  rawItems: readonly AssistantToolRailItem[],
  key: string,
  orientation: AssistantToolRailOrientation,
): number | null {
  const items = normalizedItems(rawItems);
  const enabled = enabledIndices(items);
  if (enabled.length === 0) return null;
  if (key === "Home") return enabled[0];
  if (key === "End") return enabled[enabled.length - 1];

  const previousKey = orientation === "vertical" ? "ArrowUp" : "ArrowLeft";
  const nextKey = orientation === "vertical" ? "ArrowDown" : "ArrowRight";
  if (key !== previousKey && key !== nextKey) return null;

  const current = enabled.includes(currentIndex)
    ? currentIndex
    : nearestEnabledIndex(enabled, currentIndex);
  const enabledPosition = Math.max(0, enabled.indexOf(current));
  const delta = key === previousKey ? -1 : 1;
  const nextPosition = (
    enabledPosition + delta + enabled.length
  ) % enabled.length;
  return enabled[nextPosition];
}


/** Backward-compatible A0C helper for rails whose every item is enabled. */
export function assistantToolRailIndexFromKey(
  currentIndex: number,
  itemCount: number,
  key: string,
  orientation: AssistantToolRailOrientation,
): number | null {
  const normalizedCount = finiteNonNegative(itemCount);
  if (normalizedCount <= 0) return null;
  const normalizedCurrent = Number.isFinite(currentIndex)
    ? Math.min(normalizedCount - 1, Math.max(0, Math.round(currentIndex)))
    : 0;
  const items = Array.from({ length: normalizedCount }, (_, index) => ({
    id: `item-${index}`,
    ariaLabel: `工具 ${index + 1}`,
  }));
  return assistantToolRailRovingIndexFromKey(
    normalizedCurrent,
    items,
    key,
    orientation,
  );
}
