export const ASSISTANT_PANE_MIN_WIDTH = 320;
export const ASSISTANT_PANE_DEFAULT_WIDTH = 450;
export const ASSISTANT_PANE_MAX_WIDTH = 750;
export const ASSISTANT_PANE_COLLAPSED_WIDTH = 52;
export const ASSISTANT_PANE_DEFAULT_MAIN_MIN_WIDTH = 640;
export const ASSISTANT_PANE_KEYBOARD_STEP = 10;
export const ASSISTANT_PANE_KEYBOARD_LARGE_STEP = 40;
export const ASSISTANT_PANE_PREFERENCE_SCHEMA_VERSION = 1;
export const ASSISTANT_PANE_PREFERENCE_KEY =
  "ai-novel-world-2026:workbench:assistant-pane:v1";


const ASSISTANT_PANE_PREFERENCE_MAX_LENGTH = 256;


export type AssistantPaneMode = "inline" | "overlay";


export interface AssistantPaneLayoutInput {
  preferredWidth?: number;
  availableWidth?: number;
  collapsed?: boolean;
  mainMinWidth?: number;
}


export interface AssistantPaneLayout {
  collapsed: boolean;
  mode: AssistantPaneMode;
  preferredWidth: number;
  expandedWidth: number;
  renderedWidth: number;
  dynamicMaxWidth: number;
}


export interface AssistantPaneProps extends AssistantPaneLayoutInput {
  defaultCollapsed?: boolean;
  defaultPreferredWidth?: number;
  ariaLabel?: string;
  innerId?: string;
  onCollapsedChange?: (collapsed: boolean) => void;
  onPreferredWidthChange?: (width: number) => void;
  persistPreference?: boolean;
  preferenceKey?: string;
  preferenceStorage?: AssistantPanePreferenceStorage | null;
  statusBar?: unknown;
}


interface AssistantPaneKeyboardEvent {
  key: string;
  shiftKey?: boolean;
  preventDefault?: () => void;
}


interface AssistantPanePointerEvent {
  pointerId: number;
  clientX: number;
  currentTarget?: AssistantPanePointerCaptureTarget;
  preventDefault?: () => void;
}


export interface AssistantPanePointerCaptureTarget {
  setPointerCapture?: (pointerId: number) => void;
  releasePointerCapture?: (pointerId: number) => void;
  hasPointerCapture?: (pointerId: number) => boolean;
}


export interface AssistantPanePreferenceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}


export interface AssistantPanePreference {
  readonly schemaVersion: 1;
  readonly preferredWidth: number;
  readonly collapsed: boolean;
}


export interface AssistantPaneResizeStart {
  pointerId: number;
  clientX: number;
  width: number;
  dynamicMaxWidth: number;
  captureTarget?: AssistantPanePointerCaptureTarget;
}


export interface AssistantPaneResizeSnapshot {
  active: boolean;
  pointerId?: number;
  width?: number;
}


export interface AssistantPaneResizeController {
  start(input: AssistantPaneResizeStart): boolean;
  move(
    pointerId: number,
    clientX: number,
    dynamicMaxWidth?: number,
  ): number | null;
  finish(pointerId: number): number | null;
  cancel(pointerId: number): number | null;
  snapshot(): AssistantPaneResizeSnapshot;
  dispose(): void;
}


export interface AssistantPaneRenderInput extends AssistantPaneLayoutInput {
  ariaLabel?: string;
  innerId?: string;
  onCollapsedChange?: (collapsed: boolean) => void;
  onPreferredWidthChange?: (width: number) => void;
  onPreferredWidthCommit?: (width: number) => void;
  resizeController?: AssistantPaneResizeController;
  statusBar?: unknown;
}


export interface QwenPawReactRuntime {
  createElement: (
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ) => unknown;
  useState: <T>(
    initial: T | (() => T),
  ) => [T, (next: T | ((current: T) => T)) => void];
  useRef: <T>(initial: T) => { current: T };
  useEffect: (
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ) => void;
}


function finiteNumberOr(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}


function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}


function normalizeWidth(value: number | undefined): number {
  return Math.round(clamp(
    finiteNumberOr(value, ASSISTANT_PANE_DEFAULT_WIDTH),
    ASSISTANT_PANE_MIN_WIDTH,
    ASSISTANT_PANE_MAX_WIDTH,
  ));
}


function normalizeDynamicMaxWidth(value: number | undefined): number {
  return Math.round(clamp(
    finiteNumberOr(value, ASSISTANT_PANE_MAX_WIDTH),
    ASSISTANT_PANE_MIN_WIDTH,
    ASSISTANT_PANE_MAX_WIDTH,
  ));
}


function preferenceKeyOrDefault(key: string | undefined): string {
  return key?.trim() || ASSISTANT_PANE_PREFERENCE_KEY;
}


function defaultPreferenceStorage(): AssistantPanePreferenceStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}


function resolvePreferenceStorage(
  storage: AssistantPanePreferenceStorage | null | undefined,
): AssistantPanePreferenceStorage | null {
  return storage === undefined ? defaultPreferenceStorage() : storage;
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}


export function loadAssistantPanePreference(
  storage?: AssistantPanePreferenceStorage | null,
  key?: string,
): AssistantPanePreference | null {
  const target = resolvePreferenceStorage(storage);
  if (!target) return null;

  let serialized: string | null;
  try {
    serialized = target.getItem(preferenceKeyOrDefault(key));
  } catch {
    return null;
  }
  if (
    serialized === null
    || serialized.length === 0
    || serialized.length > ASSISTANT_PANE_PREFERENCE_MAX_LENGTH
  ) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(serialized);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;

  const preferredWidth = parsed.preferredWidth;
  if (
    parsed.schemaVersion !== ASSISTANT_PANE_PREFERENCE_SCHEMA_VERSION
    || typeof preferredWidth !== "number"
    || !Number.isInteger(preferredWidth)
    || preferredWidth < ASSISTANT_PANE_MIN_WIDTH
    || preferredWidth > ASSISTANT_PANE_MAX_WIDTH
    || typeof parsed.collapsed !== "boolean"
  ) {
    return null;
  }

  return {
    schemaVersion: ASSISTANT_PANE_PREFERENCE_SCHEMA_VERSION,
    preferredWidth,
    collapsed: parsed.collapsed,
  };
}


export function saveAssistantPanePreference(
  preference: Pick<AssistantPanePreference, "preferredWidth" | "collapsed">,
  storage?: AssistantPanePreferenceStorage | null,
  key?: string,
): boolean {
  const target = resolvePreferenceStorage(storage);
  if (!target || typeof preference.collapsed !== "boolean") return false;

  const preferredWidth = preference.preferredWidth;
  if (typeof preferredWidth !== "number" || !Number.isFinite(preferredWidth)) {
    return false;
  }
  const safePreference: AssistantPanePreference = {
    schemaVersion: ASSISTANT_PANE_PREFERENCE_SCHEMA_VERSION,
    preferredWidth: normalizeWidth(preferredWidth),
    collapsed: preference.collapsed,
  };
  try {
    target.setItem(
      preferenceKeyOrDefault(key),
      JSON.stringify(safePreference),
    );
    return true;
  } catch {
    return false;
  }
}


interface ActiveAssistantPaneResize {
  pointerId: number;
  startClientX: number;
  startWidth: number;
  currentWidth: number;
  dynamicMaxWidth: number;
  captureTarget?: AssistantPanePointerCaptureTarget;
}


function safeReleasePointerCapture(active: ActiveAssistantPaneResize): void {
  const target = active.captureTarget;
  if (!target?.releasePointerCapture) return;
  try {
    if (target.hasPointerCapture?.(active.pointerId) === false) return;
    target.releasePointerCapture(active.pointerId);
  } catch {
    // Pointer capture is a progressive enhancement. Losing the element or
    // capture during route teardown must not escape into the host UI.
  }
}


export function createAssistantPaneResizeController(): AssistantPaneResizeController {
  let active: ActiveAssistantPaneResize | null = null;
  let disposed = false;

  const close = (pointerId: number): number | null => {
    if (!active || active.pointerId !== pointerId) return null;
    const completed = active;
    active = null;
    safeReleasePointerCapture(completed);
    return completed.currentWidth;
  };

  return {
    start(input) {
      if (
        disposed
        || active !== null
        || !Number.isFinite(input.pointerId)
        || !Number.isFinite(input.clientX)
      ) {
        return false;
      }
      const dynamicMaxWidth = normalizeDynamicMaxWidth(input.dynamicMaxWidth);
      const width = Math.round(clamp(
        finiteNumberOr(input.width, ASSISTANT_PANE_DEFAULT_WIDTH),
        ASSISTANT_PANE_MIN_WIDTH,
        dynamicMaxWidth,
      ));
      active = {
        pointerId: input.pointerId,
        startClientX: input.clientX,
        startWidth: width,
        currentWidth: width,
        dynamicMaxWidth,
        captureTarget: input.captureTarget,
      };
      try {
        input.captureTarget?.setPointerCapture?.(input.pointerId);
      } catch {
        // Continue with element-local pointer events when capture is blocked.
      }
      return true;
    },
    move(pointerId, clientX, dynamicMaxWidth) {
      if (
        !active
        || active.pointerId !== pointerId
        || !Number.isFinite(clientX)
      ) {
        return null;
      }
      if (dynamicMaxWidth !== undefined) {
        active.dynamicMaxWidth = normalizeDynamicMaxWidth(dynamicMaxWidth);
      }
      active.currentWidth = Math.round(clamp(
        active.startWidth + active.startClientX - clientX,
        ASSISTANT_PANE_MIN_WIDTH,
        active.dynamicMaxWidth,
      ));
      return active.currentWidth;
    },
    finish(pointerId) {
      return close(pointerId);
    },
    cancel(pointerId) {
      return close(pointerId);
    },
    snapshot() {
      return active
        ? {
            active: true,
            pointerId: active.pointerId,
            width: active.currentWidth,
          }
        : { active: false };
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      if (!active) return;
      const abandoned = active;
      active = null;
      safeReleasePointerCapture(abandoned);
    },
  };
}


export function resolveAssistantPaneLayout(
  input: AssistantPaneLayoutInput = {},
): AssistantPaneLayout {
  const preferredWidth = normalizeWidth(input.preferredWidth);
  const mainMinWidth = Math.max(
    0,
    Math.round(finiteNumberOr(
      input.mainMinWidth,
      ASSISTANT_PANE_DEFAULT_MAIN_MIN_WIDTH,
    )),
  );
  const availableWidth = finiteNumberOr(input.availableWidth, Number.POSITIVE_INFINITY);
  const collapsed = input.collapsed === true;
  const hasExpandedInlineSpace = (
    availableWidth >= mainMinWidth + ASSISTANT_PANE_MIN_WIDTH
  );
  // A collapsed rail is only 52px wide and must keep that space in the flex
  // layout. Treating it as an overlay lets the main area grow underneath the
  // rail on narrow screens, covering the rightmost content. Re-evaluating the
  // same width after expansion still selects overlay when 320px cannot fit.
  const mode: AssistantPaneMode = collapsed || hasExpandedInlineSpace
    ? "inline"
    : "overlay";
  const dynamicMaxWidth = hasExpandedInlineSpace
    ? Math.round(clamp(
      availableWidth - mainMinWidth,
      ASSISTANT_PANE_MIN_WIDTH,
      ASSISTANT_PANE_MAX_WIDTH,
    ))
    : ASSISTANT_PANE_MAX_WIDTH;
  const expandedWidth = clamp(
    preferredWidth,
    ASSISTANT_PANE_MIN_WIDTH,
    dynamicMaxWidth,
  );

  return {
    collapsed,
    mode,
    preferredWidth,
    expandedWidth,
    renderedWidth: collapsed ? ASSISTANT_PANE_COLLAPSED_WIDTH : expandedWidth,
    dynamicMaxWidth,
  };
}


export function assistantPaneWidthFromKey(
  layout: AssistantPaneLayout,
  key: string,
  shiftKey = false,
): number | null {
  const step = shiftKey
    ? ASSISTANT_PANE_KEYBOARD_LARGE_STEP
    : ASSISTANT_PANE_KEYBOARD_STEP;

  switch (key) {
    case "ArrowLeft":
      return clamp(
        layout.expandedWidth + step,
        ASSISTANT_PANE_MIN_WIDTH,
        layout.dynamicMaxWidth,
      );
    case "ArrowRight":
      return clamp(
        layout.expandedWidth - step,
        ASSISTANT_PANE_MIN_WIDTH,
        layout.dynamicMaxWidth,
      );
    case "Home":
      return ASSISTANT_PANE_MIN_WIDTH;
    case "End":
      return layout.dynamicMaxWidth;
    default:
      return null;
  }
}


export function renderQwenPawAssistantPane(
  React: Pick<QwenPawReactRuntime, "createElement">,
  Inner: unknown,
  input: AssistantPaneRenderInput = {},
): unknown {
  const h = React.createElement;
  const layout = resolveAssistantPaneLayout(input);
  const paneLabel = input.ariaLabel || "QwenPaw 原生对话助手";
  const innerId = input.innerId?.trim() || "anw-qwenpaw-assistant-inner";
  const resizeController = input.resizeController
    ?? createAssistantPaneResizeController();

  const handleResizeKey = (event: AssistantPaneKeyboardEvent) => {
    if (layout.collapsed) return;
    const nextWidth = assistantPaneWidthFromKey(
      layout,
      event.key,
      event.shiftKey === true,
    );
    if (nextWidth === null) {
      return;
    }
    event.preventDefault?.();
    input.onPreferredWidthChange?.(nextWidth);
    input.onPreferredWidthCommit?.(nextWidth);
  };

  const handlePointerDown = (event: AssistantPanePointerEvent) => {
    if (layout.collapsed) return;
    const started = resizeController.start({
      pointerId: event.pointerId,
      clientX: event.clientX,
      width: layout.expandedWidth,
      dynamicMaxWidth: layout.dynamicMaxWidth,
      captureTarget: event.currentTarget,
    });
    if (started) event.preventDefault?.();
  };

  const handlePointerMove = (event: AssistantPanePointerEvent) => {
    const nextWidth = resizeController.move(
      event.pointerId,
      event.clientX,
      layout.dynamicMaxWidth,
    );
    if (nextWidth === null) return;
    event.preventDefault?.();
    input.onPreferredWidthChange?.(nextWidth);
  };

  const handlePointerUp = (event: AssistantPanePointerEvent) => {
    const finalMove = resizeController.move(
      event.pointerId,
      event.clientX,
      layout.dynamicMaxWidth,
    );
    if (finalMove !== null) {
      event.preventDefault?.();
      input.onPreferredWidthChange?.(finalMove);
    }
    const finalWidth = resizeController.finish(event.pointerId);
    if (finalWidth !== null) input.onPreferredWidthCommit?.(finalWidth);
  };

  const handlePointerCancel = (event: AssistantPanePointerEvent) => {
    const finalWidth = resizeController.cancel(event.pointerId);
    if (finalWidth === null) return;
    event.preventDefault?.();
    input.onPreferredWidthCommit?.(finalWidth);
  };

  return h(
    "aside",
    {
      "aria-label": paneLabel,
      className: [
        "anw-assistant-pane",
        layout.collapsed ? "is-collapsed" : "",
        layout.mode === "overlay" ? "is-overlay" : "",
      ].filter(Boolean).join(" "),
      "data-assistant-pane-collapsed": String(layout.collapsed),
      "data-assistant-pane-mode": layout.mode,
      "data-assistant-pane-width": String(layout.renderedWidth),
      style: {
        alignSelf: "stretch",
        background: "var(--qwenpaw-color-bg-container, #fff)",
        borderLeft: "1px solid var(--qwenpaw-color-border-secondary, #eceef1)",
        boxSizing: "border-box",
        flex: `0 0 ${layout.renderedWidth}px`,
        height: "100%",
        maxWidth: `${layout.renderedWidth}px`,
        minWidth: `${layout.renderedWidth}px`,
        overflow: "hidden",
        position: layout.mode === "overlay" ? "absolute" : "relative",
        right: layout.mode === "overlay" ? 0 : undefined,
        top: layout.mode === "overlay" ? 0 : undefined,
        width: `${layout.renderedWidth}px`,
        zIndex: layout.mode === "overlay" ? 20 : 1,
      },
    },
    h("div", {
      "aria-controls": innerId,
      "aria-disabled": layout.collapsed,
      "aria-hidden": layout.collapsed,
      "aria-label": "调整 QwenPaw 助手宽度",
      "aria-orientation": "vertical",
      "aria-valuemax": layout.dynamicMaxWidth,
      "aria-valuemin": ASSISTANT_PANE_MIN_WIDTH,
      "aria-valuenow": layout.expandedWidth,
      "aria-valuetext": `${layout.expandedWidth} 像素`,
      className: "anw-assistant-pane-separator",
      onKeyDown: handleResizeKey,
      onLostPointerCapture: handlePointerCancel,
      onPointerCancel: handlePointerCancel,
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
      role: "separator",
      style: {
        bottom: 0,
        cursor: layout.collapsed ? "default" : "col-resize",
        left: 0,
        opacity: layout.collapsed ? 0 : 1,
        pointerEvents: layout.collapsed ? "none" : "auto",
        position: "absolute",
        touchAction: "none",
        top: 0,
        userSelect: "none",
        width: "6px",
        zIndex: 2,
      },
      tabIndex: layout.collapsed ? -1 : 0,
      title: layout.collapsed ? undefined : "拖动或使用方向键调整助手宽度",
    }),
    h(
      "button",
      {
        "aria-controls": innerId,
        "aria-expanded": !layout.collapsed,
        "aria-label": layout.collapsed
          ? "展开 QwenPaw 助手"
          : "折叠 QwenPaw 助手",
        className: "anw-assistant-pane-toggle",
        onClick: () => input.onCollapsedChange?.(!layout.collapsed),
        style: {
          alignItems: "center",
          background: "var(--qwenpaw-color-bg-container, #fff)",
          border: "1px solid var(--qwenpaw-color-border, #d9dce1)",
          borderRadius: "8px",
          cursor: "pointer",
          display: "inline-flex",
          height: "36px",
          justifyContent: "center",
          left: layout.collapsed ? "8px" : undefined,
          position: "absolute",
          right: layout.collapsed ? undefined : "8px",
          top: "10px",
          width: "36px",
          // The context status slot is z-index 4.  Keep the collapse control
          // above it so the public native-chat chrome cannot cover the only
          // route back to the collapsed state.
          zIndex: 5,
        },
        title: layout.collapsed ? "展开助手" : "折叠助手",
        type: "button",
      },
      layout.collapsed ? "›" : "‹",
    ),
    h(
      "div",
      {
        "aria-hidden": layout.collapsed,
        className: `anw-assistant-pane-inner ${input.statusBar ? "has-status-bar" : ""}`,
        id: innerId,
        style: {
          height: "100%",
          minWidth: `${layout.expandedWidth}px`,
          opacity: layout.collapsed ? 0 : 1,
          pointerEvents: layout.collapsed ? "none" : "auto",
          visibility: layout.collapsed ? "hidden" : "visible",
          width: `${layout.expandedWidth}px`,
        },
      },
      h(Inner),
      input.statusBar
        ? h("div", { className: "anw-assistant-context-status-slot" }, input.statusBar)
        : null,
    ),
  );
}


function createAssistantPaneResizeLease(): AssistantPaneResizeController {
  let current: AssistantPaneResizeController | null = null;
  const get = (): AssistantPaneResizeController => {
    current ??= createAssistantPaneResizeController();
    return current;
  };

  return {
    start(input) {
      return get().start(input);
    },
    move(pointerId, clientX, dynamicMaxWidth) {
      return current?.move(pointerId, clientX, dynamicMaxWidth) ?? null;
    },
    finish(pointerId) {
      return current?.finish(pointerId) ?? null;
    },
    cancel(pointerId) {
      return current?.cancel(pointerId) ?? null;
    },
    snapshot() {
      return current?.snapshot() ?? { active: false };
    },
    dispose() {
      current?.dispose();
      current = null;
    },
  };
}


export function createQwenPawAssistantPane(
  React: QwenPawReactRuntime,
  Inner: unknown,
) {
  function QwenPawAssistantPane(props: AssistantPaneProps = {}) {
    const [internalPreference, setInternalPreference] = React.useState<AssistantPanePreference>(
      () => {
        const stored = props.persistPreference === false
          ? null
          : loadAssistantPanePreference(
              props.preferenceStorage,
              props.preferenceKey,
            );
        return stored ?? {
          schemaVersion: ASSISTANT_PANE_PREFERENCE_SCHEMA_VERSION,
          preferredWidth: normalizeWidth(props.defaultPreferredWidth),
          collapsed: props.defaultCollapsed === true,
        };
      },
    );
    const resizeLeaseRef = React.useRef<AssistantPaneResizeController | null>(null);
    if (resizeLeaseRef.current === null) {
      resizeLeaseRef.current = createAssistantPaneResizeLease();
    }

    const collapsedControlled = typeof props.collapsed === "boolean";
    const widthControlled = typeof props.preferredWidth === "number"
      && Number.isFinite(props.preferredWidth);
    const collapsed = collapsedControlled
      ? props.collapsed === true
      : internalPreference.collapsed;
    const preferredWidth = widthControlled
      ? normalizeWidth(props.preferredWidth)
      : internalPreference.preferredWidth;
    const latestPreferenceRef = React.useRef({
      collapsed,
      persist: props.persistPreference !== false,
      preferenceKey: props.preferenceKey,
      preferenceStorage: props.preferenceStorage,
      preferredWidth,
    });
    latestPreferenceRef.current = {
      collapsed,
      persist: props.persistPreference !== false,
      preferenceKey: props.preferenceKey,
      preferenceStorage: props.preferenceStorage,
      preferredWidth,
    };

    const persistPreference = (width: number, nextCollapsed: boolean) => {
      if (props.persistPreference === false) return;
      saveAssistantPanePreference(
        { preferredWidth: width, collapsed: nextCollapsed },
        props.preferenceStorage,
        props.preferenceKey,
      );
    };

    React.useEffect(() => {
      const resizeLease = resizeLeaseRef.current;
      return () => {
        if (!resizeLease) return;
        const activeWidth = resizeLease.snapshot().width;
        const latest = latestPreferenceRef.current;
        if (activeWidth !== undefined && latest.persist) {
          saveAssistantPanePreference(
            {
              preferredWidth: activeWidth,
              collapsed: latest.collapsed,
            },
            latest.preferenceStorage,
            latest.preferenceKey,
          );
        }
        resizeLease.dispose();
      };
    }, []);

    return renderQwenPawAssistantPane(React, Inner, {
      ...props,
      collapsed,
      preferredWidth,
      resizeController: resizeLeaseRef.current,
      onCollapsedChange: (nextCollapsed) => {
        if (!collapsedControlled) {
          setInternalPreference((current) => ({
            ...current,
            collapsed: nextCollapsed,
          }));
        }
        props.onCollapsedChange?.(nextCollapsed);
        persistPreference(preferredWidth, nextCollapsed);
      },
      onPreferredWidthChange: (nextWidth) => {
        if (!widthControlled) {
          setInternalPreference((current) => ({
            ...current,
            preferredWidth: normalizeWidth(nextWidth),
          }));
        }
        props.onPreferredWidthChange?.(nextWidth);
      },
      onPreferredWidthCommit: (nextWidth) => {
        persistPreference(nextWidth, collapsed);
      },
    });
  }

  return QwenPawAssistantPane;
}
