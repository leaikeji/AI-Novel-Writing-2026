const WORKBENCH_ROUTE_KEY = "ai-novel-world-2026.workbench-route";


export interface WorkbenchRouteState {
  novelId: string;
  documentId?: string;
  chatPath?: string;
}


function readStoredState(): WorkbenchRouteState | null {
  try {
    const value = window.sessionStorage.getItem(WORKBENCH_ROUTE_KEY);
    return value ? JSON.parse(value) as WorkbenchRouteState : null;
  } catch {
    return null;
  }
}


function storeState(state: WorkbenchRouteState): void {
  window.sessionStorage.setItem(WORKBENCH_ROUTE_KEY, JSON.stringify(state));
}


export function rememberWorkbenchRoute(novelId: string, documentId?: string): void {
  storeState({ novelId, documentId });
}


export function activeWorkbenchRoute(): WorkbenchRouteState | null {
  const query = new URLSearchParams(window.location.search);
  if (query.get("novel_workbench") === "1" && query.get("novel_id")) {
    const state: WorkbenchRouteState = {
      novelId: query.get("novel_id") as string,
      documentId: query.get("document_id") ?? undefined,
      chatPath: window.location.pathname === "/chat" ? undefined : window.location.pathname,
    };
    storeState(state);
    return state;
  }

  if (!window.location.pathname.startsWith("/chat")) return null;
  const stored = readStoredState();
  if (!stored) return null;

  if (!stored.chatPath && window.location.pathname !== "/chat") {
    stored.chatPath = window.location.pathname;
    storeState(stored);
  } else if (stored.chatPath && stored.chatPath !== window.location.pathname) {
    return null;
  }
  return stored;
}


export function clearWorkbenchRoute(): void {
  window.sessionStorage.removeItem(WORKBENCH_ROUTE_KEY);
}
