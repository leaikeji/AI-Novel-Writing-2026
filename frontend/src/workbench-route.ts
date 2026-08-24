const WORKBENCH_ROUTE_KEY = "ai-novel-world-2026.workbench-route";


export interface WorkbenchRouteState {
  novelId: string;
  documentId?: string;
  chatPath?: string;
  roleView?: "list" | "graph";
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
  const existing = readStoredState();
  storeState({
    novelId,
    documentId,
    roleView: existing?.novelId === novelId ? existing.roleView : undefined,
  });
}


export function rememberWorkbenchRoleView(
  novelId: string,
  roleView: "list" | "graph",
): void {
  const existing = readStoredState();
  storeState({
    novelId,
    documentId: existing?.novelId === novelId ? existing.documentId : undefined,
    chatPath: existing?.novelId === novelId ? existing.chatPath : undefined,
    roleView,
  });
}


export function activeWorkbenchRoute(): WorkbenchRouteState | null {
  const query = new URLSearchParams(window.location.search);
  if (query.get("novel_workbench") === "1" && query.get("novel_id")) {
    const existing = readStoredState();
    const novelId = query.get("novel_id") as string;
    const queryRoleView = query.get("role_view");
    const state: WorkbenchRouteState = {
      novelId,
      documentId: query.get("document_id") ?? undefined,
      chatPath: window.location.pathname === "/chat" ? undefined : window.location.pathname,
      roleView: queryRoleView === "graph" || queryRoleView === "list"
        ? queryRoleView
        : existing?.novelId === novelId
          ? existing.roleView
          : undefined,
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
