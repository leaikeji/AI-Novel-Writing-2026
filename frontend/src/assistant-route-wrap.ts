import {
  ASSISTANT_PANE_DEFAULT_WIDTH,
  AssistantPanePreferenceStorage,
  AssistantPaneProps,
  createQwenPawAssistantPane,
  loadAssistantPanePreference,
  QwenPawReactRuntime,
} from "./assistant-pane";
import {
  AssistantWorkspacePageKind,
  resolveAssistantWorkspaceLayout,
} from "./assistant-layout";
import {
  activeWorkbenchRouteSession,
  OwnedWorkbenchRouteState,
  RouteSessionLocation,
  RouteSessionSnapshot,
} from "./workbench-route";
import {
  assistantContextRuntime,
  type AssistantContextRuntimeStatus,
  type NovelAssistantContextRuntime,
} from "./assistant-context-runtime";
import type { AssistantContextRefCoordinator } from "./assistant-context-ref";
import type { AssistantSelectionController } from "./assistant-selection-controller";
import { createAssistantSelectionToolbar } from "./assistant-selection-toolbar";


export type AssistantRouteReactRuntime = QwenPawReactRuntime;


export interface AssistantRouteEventTarget {
  addEventListener(type: "popstate" | "resize", listener: () => void): void;
  removeEventListener(type: "popstate" | "resize", listener: () => void): void;
}


export interface AssistantRouteContainerElement {
  clientWidth?: number;
  getBoundingClientRect?: () => { width: number };
}


export interface AssistantRouteResizeObserverEntry {
  target: unknown;
  contentRect: { width: number };
}


export interface AssistantRouteResizeObserver {
  observe(target: AssistantRouteContainerElement): void;
  disconnect(): void;
}


export type AssistantRouteResizeObserverFactory = (
  callback: (entries: readonly AssistantRouteResizeObserverEntry[]) => void,
) => AssistantRouteResizeObserver | null;


export interface AssistantRouteDisposable {
  dispose(): void;
}


export interface AssistantRouteApi {
  wrap(
    pluginId: string,
    targetRouteId: string,
    wrapper: (Inner: unknown) => unknown,
  ): AssistantRouteDisposable;
}


export interface AssistantRouteWrapOptions {
  React: AssistantRouteReactRuntime;
  Workbench: unknown;
  getRouteSession?: () => RouteSessionSnapshot;
  getLocation?: () => RouteSessionLocation;
  eventTarget?: AssistantRouteEventTarget | null;
  createResizeObserver?: AssistantRouteResizeObserverFactory;
  createAssistantPane?: (
    React: QwenPawReactRuntime,
    Inner: unknown,
  ) => (props?: AssistantPaneProps) => unknown;
  defaultAssistantCollapsed?: boolean;
  defaultAssistantWidth?: number;
  assistantPreferenceKey?: string;
  assistantPreferenceStorage?: AssistantPanePreferenceStorage | null;
  persistAssistantPreference?: boolean;
  contextRuntime?: NovelAssistantContextRuntime;
  useSelectedAgent?: () => { id: string } | null;
  useCurrentSession?: () => { id: string } | null;
  getSelectedAgentId?: () => string | null;
  getCurrentSessionId?: () => string | null;
  contextRefCoordinator?: AssistantContextRefCoordinator;
  selectionController?: AssistantSelectionController;
}


export interface RegisterAssistantRouteWrapOptions extends AssistantRouteWrapOptions {
  pluginId: string;
  targetRouteId: string;
  route: AssistantRouteApi;
}


export interface ObserveAssistantRouteContainerOptions {
  container: AssistantRouteContainerElement;
  onWidth: (width: number) => void;
  createResizeObserver: AssistantRouteResizeObserverFactory;
  fallbackEventTarget?: AssistantRouteEventTarget | null;
}


function finiteContainerWidth(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.round(value))
    : null;
}


function measureContainerWidth(container: AssistantRouteContainerElement): number {
  try {
    const measured = finiteContainerWidth(container.getBoundingClientRect?.().width);
    if (measured !== null) return measured;
  } catch {
    // Fall through to clientWidth when a detached element cannot be measured.
  }
  return finiteContainerWidth(container.clientWidth) ?? 0;
}


function browserEventTarget(): AssistantRouteEventTarget | null {
  if (typeof window === "undefined") return null;
  return {
    addEventListener: (type, listener) => window.addEventListener(type, listener),
    removeEventListener: (type, listener) => window.removeEventListener(type, listener),
  };
}


function browserResizeObserverFactory(
  callback: (entries: readonly AssistantRouteResizeObserverEntry[]) => void,
): AssistantRouteResizeObserver | null {
  if (typeof ResizeObserver !== "function") return null;
  const observer = new ResizeObserver((entries) => callback(entries.map((entry) => ({
    target: entry.target,
    contentRect: { width: entry.contentRect.width },
  }))));
  return {
    observe: (target) => observer.observe(target as Element),
    disconnect: () => observer.disconnect(),
  };
}


export function observeAssistantRouteContainer(
  options: ObserveAssistantRouteContainerOptions,
): () => void {
  const publishMeasuredWidth = () => {
    options.onWidth(measureContainerWidth(options.container));
  };
  publishMeasuredWidth();

  let observer: AssistantRouteResizeObserver | null = null;
  try {
    observer = options.createResizeObserver((entries) => {
      const entry = entries.find((candidate) => candidate.target === options.container)
        ?? entries[0];
      const observedWidth = finiteContainerWidth(entry?.contentRect.width);
      if (observedWidth === null) publishMeasuredWidth();
      else options.onWidth(observedWidth);
    });
    observer?.observe(options.container);
  } catch {
    observer?.disconnect();
    observer = null;
  }

  if (observer) {
    return () => observer?.disconnect();
  }

  options.fallbackEventTarget?.addEventListener("resize", publishMeasuredWidth);
  return () => {
    options.fallbackEventTarget?.removeEventListener("resize", publishMeasuredWidth);
  };
}


export function resolveAssistantRoutePageKind(
  location: RouteSessionLocation,
  route: OwnedWorkbenchRouteState,
): AssistantWorkspacePageKind {
  const query = new URLSearchParams(location.search);
  const section = query.get("section");
  if (section && section !== "chapters") return "studio";
  return query.get("document_id") || route.documentId
    ? "chapter-editor"
    : "studio";
}


function isWorkbenchRoute(snapshot: RouteSessionSnapshot): boolean {
  return snapshot.route !== null
    && (snapshot.state === "workbench-no-session"
      || snapshot.state === "workbench-session");
}


const SECTION_LABELS = {
  chapters: "章节",
  outline: "大纲",
  roles: "角色",
  clues: "线索",
  settings: "设定",
} as const;


function contextPreparationLabel(status: AssistantContextRuntimeStatus): string {
  if (!status.supportedAgent) return "当前 Agent 不接收小说页面上下文";
  if (!status.active) return "等待页面上下文";
  return {
    idle: "等待页面变化",
    settling: "等待输入稳定",
    preparing: "正在准备本轮上下文",
    ready: "本轮上下文已就绪",
    failed: "页面上下文准备失败",
    expired: "页面上下文已过期",
  }[status.preparation];
}


export function createAssistantRouteWrap(
  options: AssistantRouteWrapOptions,
): (Inner: unknown) => unknown {
  const React = options.React;
  const h = React.createElement;
  const getRouteSession = options.getRouteSession ?? activeWorkbenchRouteSession;
  const getLocation = options.getLocation ?? (() => window.location);
  const eventTarget = options.eventTarget === undefined
    ? browserEventTarget()
    : options.eventTarget;
  const createResizeObserver = options.createResizeObserver
    ?? browserResizeObserverFactory;
  const createAssistantPane = options.createAssistantPane
    ?? createQwenPawAssistantPane;
  const defaultAssistantWidth = options.defaultAssistantWidth
    ?? ASSISTANT_PANE_DEFAULT_WIDTH;
  const defaultAssistantCollapsed = options.defaultAssistantCollapsed === true;
  const contextRuntime = options.contextRuntime ?? assistantContextRuntime;
  const useSelectedAgent = options.useSelectedAgent
    ?? (typeof window !== "undefined" ? window.QwenPaw.host.useSelectedAgent : undefined);
  const useCurrentSession = options.useCurrentSession
    ?? (typeof window !== "undefined" ? window.QwenPaw.host.useCurrentSession : undefined);
  const getSelectedAgentId = options.getSelectedAgentId
    ?? (typeof window !== "undefined" ? window.QwenPaw.host.getSelectedAgentId : undefined);
  const getCurrentSessionId = options.getCurrentSessionId
    ?? (typeof window !== "undefined" ? window.QwenPaw.host.getCurrentSessionId : undefined);
  const createPortal = typeof window !== "undefined"
    && typeof window.QwenPaw.host.ReactDOM?.createPortal === "function"
      ? window.QwenPaw.host.ReactDOM.createPortal.bind(window.QwenPaw.host.ReactDOM)
      : undefined;
  const AssistantSelectionToolbar = options.selectionController
    ? createAssistantSelectionToolbar(
        React,
        options.selectionController,
        createPortal ? {
          createPortal,
          getContainer: () => (
            typeof document !== "undefined" ? document.body : null
          ),
        } : undefined,
      )
    : null;

  function AssistantContextStatusBar() {
    const [status, setStatus] = React.useState(() => contextRuntime.getStatus());
    React.useEffect(() => contextRuntime.subscribe(setStatus), []);
    const location = [
      status.novelTitle,
      status.section ? SECTION_LABELS[status.section] : undefined,
      status.entityTitle,
    ].filter(Boolean).join(" · ");
    const fieldSummary = status.fieldCount > 0
      ? `${status.fieldCount} 个字段${status.dirtyFieldCount > 0 ? ` · ${status.dirtyFieldCount} 个未保存` : ""}`
      : "当前页无可编辑字段";
    return h(
      "section",
      {
        className: `anw-assistant-context-status ${status.supportedAgent ? "is-supported" : "is-unsupported"}`,
        "aria-label": "QwenPaw 助手页面感知状态",
        "aria-live": "polite",
      },
      h("div", { className: "anw-assistant-context-status-main" },
        h("strong", null, location || "小说工作台"),
        h("span", null, contextPreparationLabel(status)),
      ),
      h("div", { className: "anw-assistant-context-status-meta" },
        h("span", null, fieldSummary),
        status.selectionCharacters > 0 ? h("span", null, `选区 ${status.selectionCharacters} 字`) : null,
        status.truncated ? h("span", null, "已按预算截断") : null,
      ),
      h("small", null, "页面内容可能成为此工作台会话历史的一部分"),
    );
  }

  return function wrapNativeChat(Inner: unknown) {
    const AssistantPane = createAssistantPane(React, Inner);

    return function NativeChatWithNovelWorkbench() {
      const selectedAgent = useSelectedAgent?.() ?? null;
      const currentSession = useCurrentSession?.() ?? null;
      const selectedAgentId = selectedAgent?.id ?? getSelectedAgentId?.() ?? undefined;
      const currentSessionId = currentSession?.id ?? getCurrentSessionId?.() ?? undefined;
      const shellRenderCountRef = React.useRef(0);
      shellRenderCountRef.current += 1;
      const routeRevisionRef = React.useRef(0);
      const [, setRouteRevision] = React.useState(0);
      const [containerWidth, setContainerWidth] = React.useState(0);
      const [assistantPreference, setAssistantPreference] = React.useState(() => {
        const stored = options.persistAssistantPreference === false
          ? null
          : loadAssistantPanePreference(
              options.assistantPreferenceStorage,
              options.assistantPreferenceKey,
            );
        return stored ?? {
          collapsed: defaultAssistantCollapsed,
          preferredWidth: defaultAssistantWidth,
        };
      });
      const containerRef = React.useRef<AssistantRouteContainerElement | null>(null);
      const routeSession = getRouteSession();
      const workbenchActive = isWorkbenchRoute(routeSession);

      React.useEffect(() => {
        if (!eventTarget) return undefined;
        const handlePopState = () => {
          routeRevisionRef.current += 1;
          setRouteRevision(routeRevisionRef.current);
        };
        eventTarget.addEventListener("popstate", handlePopState);
        return () => eventTarget.removeEventListener("popstate", handlePopState);
      }, []);

      React.useEffect(() => {
        const container = containerRef.current;
        if (!workbenchActive || !container) return undefined;
        return observeAssistantRouteContainer({
          container,
          onWidth: setContainerWidth,
          createResizeObserver,
          fallbackEventTarget: eventTarget,
        });
      }, [workbenchActive]);

      React.useEffect(() => {
        contextRuntime.setHostBinding(selectedAgentId, currentSessionId);
        if (!workbenchActive) contextRuntime.clear();
      }, [workbenchActive, selectedAgentId, currentSessionId]);

      React.useEffect(() => {
        if (!workbenchActive || !options.contextRefCoordinator) return undefined;
        return options.contextRefCoordinator.start();
      }, [workbenchActive]);

      React.useEffect(() => {
        if (!options.selectionController) return undefined;
        if (!workbenchActive) {
          // A confirmed route exit is destructive for ephemeral selections.
          options.selectionController.stop();
          return undefined;
        }
        options.selectionController.start();
        // Native chat may remount its wrapped route while streaming a response.
        // Preserve an in-flight selection across that host-only lifecycle.
        return () => options.selectionController?.suspend();
      }, [workbenchActive]);

      if (!workbenchActive || !routeSession.route) {
        return h(Inner);
      }

      const pageKind = resolveAssistantRoutePageKind(
        getLocation(),
        routeSession.route,
      );
      const layout = resolveAssistantWorkspaceLayout({
        containerWidth,
        preferredAssistantWidth: assistantPreference.preferredWidth,
        assistantCollapsed: assistantPreference.collapsed,
        pageKind,
      });

      return h(
        "div",
        {
          ref: containerRef,
          "data-ai-novel-workbench": "active",
          "data-assistant-density": layout.density,
          "data-assistant-overlay": String(layout.assistantOverlay),
          "data-assistant-page-kind": pageKind,
          "data-assistant-shell-render-count": String(shellRenderCountRef.current),
          "data-assistant-width": String(layout.assistantWidth),
          "data-container-width": String(layout.containerWidth),
          "data-route-session-state": routeSession.state,
          className: "anw-workbench-frame",
          style: {
            display: "flex",
            height: "100%",
            minWidth: 0,
            overflow: "hidden",
            position: "relative",
            width: "100%",
          },
        },
        h(
          "section",
          {
            className: "anw-workbench-main",
            "data-main-min-width": String(layout.mainMinWidth),
            "data-main-width": String(layout.mainWidth),
            style: {
              flex: "1 1 auto",
              minWidth: 0,
              width: layout.assistantOverlay ? "100%" : `${layout.mainWidth}px`,
            },
          },
          h(options.Workbench, { assistantWorkspaceLayout: layout }),
        ),
        h(AssistantPane, {
          preferenceKey: options.assistantPreferenceKey,
          preferenceStorage: options.assistantPreferenceStorage,
          persistPreference: options.persistAssistantPreference,
          availableWidth: layout.containerWidth,
          collapsed: assistantPreference.collapsed,
          mainMinWidth: layout.mainMinWidth,
          onCollapsedChange: (collapsed: boolean) => setAssistantPreference(
            (current) => ({ ...current, collapsed }),
          ),
          onPreferredWidthChange: (preferredWidth: number) => setAssistantPreference(
            (current) => ({ ...current, preferredWidth }),
          ),
          preferredWidth: assistantPreference.preferredWidth,
          statusBar: h(AssistantContextStatusBar),
        }),
        AssistantSelectionToolbar
          ? h(AssistantSelectionToolbar, {
              onEnsureAssistantOpen: () => setAssistantPreference(
                (current) => ({ ...current, collapsed: false }),
              ),
            })
          : null,
      );
    };
  };
}


export function registerAssistantRouteWrap(
  options: RegisterAssistantRouteWrapOptions,
): AssistantRouteDisposable {
  return options.route.wrap(
    options.pluginId,
    options.targetRouteId,
    createAssistantRouteWrap(options),
  );
}
