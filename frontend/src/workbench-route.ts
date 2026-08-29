const WORKBENCH_ROUTE_KEY = "ai-novel-world-2026.workbench-route";
const WORKBENCH_ROUTE_STORAGE_VERSION = 1;
const CHAT_ROOT_PATH = "/chat";
const CREATIVE_CENTER_ROUTE_SCOPE_ID = "ai-novel-world-2026:creative-center";


export const WORKBENCH_ROUTE_SECTIONS = [
  "chapters",
  "outline",
  "roles",
  "clues",
  "settings",
  "reading",
] as const;


export type WorkbenchRouteSection = typeof WORKBENCH_ROUTE_SECTIONS[number];


export const WORKBENCH_READING_PANELS = [
  "overview",
  "narrator",
  "characters",
  "voice-library",
  "reading-rules",
  "storage-privacy",
  "casting-rules",
  "pronunciation",
  "audio-cache",
] as const;


export type WorkbenchReadingPanel = typeof WORKBENCH_READING_PANELS[number];


export type RouteSessionState =
  | "ordinary-chat"
  | "workbench-no-session"
  | "workbench-session"
  | "leaving-workbench";


export interface WorkbenchRouteState {
  novelId: string;
  documentId?: string;
  chatPath?: string;
  roleView?: "list" | "graph";
  section?: WorkbenchRouteSection;
  readingPanel?: WorkbenchReadingPanel;
}


export interface OwnedWorkbenchRouteState extends WorkbenchRouteState {
  ownerToken: string;
}


export interface RouteSessionSnapshot {
  state: RouteSessionState;
  route: OwnedWorkbenchRouteState | null;
  ownerToken: string | null;
}


export interface RouteSessionLocation {
  pathname: string;
  search: string;
}


export interface RouteSessionStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}


export interface RouteSessionStateMachineOptions {
  getLocation: () => RouteSessionLocation;
  storage: RouteSessionStorage;
  createOwnerToken?: () => string;
}


export interface WorkbenchHistory {
  readonly state: unknown;
  replaceState(data: unknown, unused: string, url?: string | URL | null): void;
}


interface StoredWorkbenchRoute extends OwnedWorkbenchRouteState {
  storageVersion: typeof WORKBENCH_ROUTE_STORAGE_VERSION;
  state: "workbench-no-session" | "workbench-session";
}


interface ExplicitWorkbenchRoute {
  novelId: string;
  documentId?: string;
  roleView?: "list" | "graph";
  section?: WorkbenchRouteSection;
  readingPanel?: WorkbenchReadingPanel;
}


export interface WorkbenchLocationUpdate {
  documentId?: string;
  section: WorkbenchRouteSection;
  readingPanel?: WorkbenchReadingPanel;
}


const ORDINARY_CHAT_SNAPSHOT: RouteSessionSnapshot = {
  state: "ordinary-chat",
  route: null,
  ownerToken: null,
};


function normalizePathname(pathname: string): string {
  if (!pathname || pathname === "/") return pathname || "/";
  return pathname.replace(/\/+$/, "");
}


function chatSessionPath(pathname: string): string | undefined {
  const normalized = normalizePathname(pathname);
  return normalized.startsWith(`${CHAT_ROOT_PATH}/`)
    && normalized.length > CHAT_ROOT_PATH.length + 1
    ? normalized
    : undefined;
}


function isChatRoot(pathname: string): boolean {
  return normalizePathname(pathname) === CHAT_ROOT_PATH;
}


function isChatLocation(pathname: string): boolean {
  return isChatRoot(pathname) || chatSessionPath(pathname) !== undefined;
}


function nonEmptyQueryValue(query: URLSearchParams, key: string): string | undefined {
  const value = query.get(key)?.trim();
  return value || undefined;
}


export function isWorkbenchRouteSection(value: unknown): value is WorkbenchRouteSection {
  return typeof value === "string"
    && (WORKBENCH_ROUTE_SECTIONS as readonly string[]).includes(value);
}


export function isWorkbenchReadingPanel(value: unknown): value is WorkbenchReadingPanel {
  return typeof value === "string"
    && (WORKBENCH_READING_PANELS as readonly string[]).includes(value);
}


function routePageLocation(
  section: WorkbenchRouteSection | undefined,
  readingPanel: WorkbenchReadingPanel | undefined,
): Pick<WorkbenchRouteState, "section" | "readingPanel"> {
  if (!section) return {};
  if (section !== "reading") return { section };
  return {
    section,
    readingPanel: readingPanel ?? "overview",
  };
}


function explicitWorkbenchRoute(
  location: RouteSessionLocation,
): ExplicitWorkbenchRoute | null {
  if (!isChatLocation(location.pathname)) return null;

  const query = new URLSearchParams(location.search);
  const novelId = nonEmptyQueryValue(query, "novel_id");
  if (query.get("novel_workbench") === "1" && novelId) {
    const queryRoleView = query.get("role_view");
    const querySection = query.get("section");
    const section = isWorkbenchRouteSection(querySection) && querySection !== "chapters"
      ? querySection
      : undefined;
    const readingPanel = section === "reading" && isWorkbenchReadingPanel(
      query.get("reading_panel"),
    )
      ? query.get("reading_panel") as WorkbenchReadingPanel
      : undefined;
    return {
      novelId,
      documentId: nonEmptyQueryValue(query, "document_id"),
      roleView: queryRoleView === "list" || queryRoleView === "graph"
        ? queryRoleView
        : undefined,
      ...routePageLocation(section, readingPanel),
    };
  }
  return query.get("novel_center") === "1"
    ? { novelId: CREATIVE_CENTER_ROUTE_SCOPE_ID }
    : null;
}


function validOwnerToken(value: unknown): value is string {
  return typeof value === "string"
    && value.length >= 16
    && value.length <= 128
    && /^[A-Za-z0-9_-]+$/.test(value);
}


function optionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}


function optionalRoleView(value: unknown): value is "list" | "graph" | undefined {
  return value === undefined || value === "list" || value === "graph";
}


function validStoredPageLocation(candidate: Record<string, unknown>): boolean {
  if (candidate.section === undefined) return candidate.readingPanel === undefined;
  if (!isWorkbenchRouteSection(candidate.section) || candidate.section === "chapters") return false;
  if (candidate.section !== "reading") return candidate.readingPanel === undefined;
  return isWorkbenchReadingPanel(candidate.readingPanel);
}


function isStoredWorkbenchRoute(value: unknown): value is StoredWorkbenchRoute {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  const validState = candidate.state === "workbench-no-session"
    || candidate.state === "workbench-session";
  const validChatPath = candidate.chatPath === undefined
    || (typeof candidate.chatPath === "string"
      && chatSessionPath(candidate.chatPath) === candidate.chatPath);

  return candidate.storageVersion === WORKBENCH_ROUTE_STORAGE_VERSION
    && validState
    && typeof candidate.novelId === "string"
    && candidate.novelId.trim().length > 0
    && optionalString(candidate.documentId)
    && validChatPath
    && optionalRoleView(candidate.roleView)
    && validStoredPageLocation(candidate)
    && validOwnerToken(candidate.ownerToken)
    && (candidate.state !== "workbench-session" || candidate.chatPath !== undefined);
}


function secureOwnerToken(): string {
  const cryptography = globalThis.crypto;
  if (!cryptography?.getRandomValues) {
    throw new Error("Secure randomness is required for a workbench owner token");
  }
  const bytes = new Uint8Array(16);
  cryptography.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}


function cloneRoute(route: OwnedWorkbenchRouteState): OwnedWorkbenchRouteState {
  return { ...route };
}


function cloneSnapshot(snapshot: RouteSessionSnapshot): RouteSessionSnapshot {
  return {
    state: snapshot.state,
    route: snapshot.route ? cloneRoute(snapshot.route) : null,
    ownerToken: snapshot.ownerToken,
  };
}


export function replaceWorkbenchHistoryUrl(
  history: WorkbenchHistory,
  currentHref: string,
  targetUrl: string,
): void {
  const current = new URL(currentHref);
  const target = new URL(targetUrl, current);
  target.hash = current.hash;
  history.replaceState(
    history.state,
    "",
    `${target.pathname}${target.search}${target.hash}`,
  );
}


/**
 * The single owner of workbench route/session lifecycle state.
 *
 * It intentionally uses only the public URL, the current in-memory owner and
 * tab-scoped sessionStorage.  A bare /chat reached while this same runtime is
 * already rendering an owned workbench is the native "new conversation"
 * transition; a fresh/direct /chat load still falls back to ordinary chat.
 */
export class RouteSessionStateMachine {
  private readonly getLocation: () => RouteSessionLocation;
  private readonly storage: RouteSessionStorage;
  private readonly createOwnerToken: () => string;
  private currentSnapshot: RouteSessionSnapshot = ORDINARY_CHAT_SNAPSHOT;

  constructor(options: RouteSessionStateMachineOptions) {
    this.getLocation = options.getLocation;
    this.storage = options.storage;
    this.createOwnerToken = options.createOwnerToken ?? secureOwnerToken;
  }

  snapshot(): RouteSessionSnapshot {
    return cloneSnapshot(this.currentSnapshot);
  }

  resolve(): RouteSessionSnapshot {
    const location = this.getLocation();
    const explicit = explicitWorkbenchRoute(location);
    const sessionPath = chatSessionPath(location.pathname);
    const stored = this.readStoredRoute();

    if (explicit) {
      const storedMatchesNovel = stored?.novelId === explicit.novelId;
      const storedMatchesSession = !sessionPath
        || !stored?.chatPath
        || stored.chatPath === sessionPath;
      const reusable = storedMatchesNovel && storedMatchesSession ? stored : null;
      const ownerToken = reusable?.ownerToken ?? this.newOwnerToken();
      if (!ownerToken) return this.toOrdinaryChat();

      const route: OwnedWorkbenchRouteState = {
        novelId: explicit.novelId,
        documentId: explicit.documentId,
        chatPath: sessionPath ?? reusable?.chatPath,
        roleView: explicit.roleView ?? reusable?.roleView,
        ...routePageLocation(explicit.section, explicit.readingPanel),
        ownerToken,
      };
      const state = sessionPath ? "workbench-session" : "workbench-no-session";
      return this.persistWorkbench(state, route);
    }

    if (!sessionPath) {
      const activeRoute = this.currentSnapshot.route;
      const isOwnedNativeNewChat = isChatRoot(location.pathname)
        && location.search === ""
        && (this.currentSnapshot.state === "workbench-session"
          || this.currentSnapshot.state === "workbench-no-session")
        && activeRoute !== null
        && stored !== null
        && stored.ownerToken === activeRoute.ownerToken
        && stored.novelId === activeRoute.novelId;
      if (!isOwnedNativeNewChat || !activeRoute) return this.toOrdinaryChat();
      return this.persistWorkbench("workbench-no-session", {
        novelId: activeRoute.novelId,
        documentId: activeRoute.documentId,
        chatPath: undefined,
        roleView: activeRoute.roleView,
        ...routePageLocation(activeRoute.section, activeRoute.readingPanel),
        ownerToken: activeRoute.ownerToken,
      });
    }
    if (!stored) return this.transition(ORDINARY_CHAT_SNAPSHOT);

    if (stored.chatPath && stored.chatPath !== sessionPath) {
      return this.toOrdinaryChat();
    }

    const route: OwnedWorkbenchRouteState = {
      novelId: stored.novelId,
      documentId: stored.documentId,
      chatPath: sessionPath,
      roleView: stored.roleView,
      ...routePageLocation(stored.section, stored.readingPanel),
      ownerToken: stored.ownerToken,
    };
    return this.persistWorkbench("workbench-session", route);
  }

  enterWorkbench(novelId: string, documentId?: string): RouteSessionSnapshot {
    const normalizedNovelId = novelId.trim();
    if (!normalizedNovelId) return this.toOrdinaryChat();

    const active = this.resolve();
    const activeRoute = active.route?.novelId === normalizedNovelId
      ? active.route
      : null;
    const ownerToken = activeRoute?.ownerToken ?? this.newOwnerToken();
    if (!ownerToken) return this.toOrdinaryChat();

    const route: OwnedWorkbenchRouteState = {
      novelId: normalizedNovelId,
      documentId,
      chatPath: activeRoute?.chatPath,
      roleView: activeRoute?.roleView,
      ...routePageLocation(activeRoute?.section, activeRoute?.readingPanel),
      ownerToken,
    };
    const state = activeRoute && active.state === "workbench-session"
      ? "workbench-session"
      : "workbench-no-session";
    return this.persistWorkbench(state, route);
  }

  rememberRoleView(
    novelId: string,
    roleView: "list" | "graph",
  ): RouteSessionSnapshot {
    const normalizedNovelId = novelId.trim();
    const active = this.resolve();
    if (!normalizedNovelId || active.route?.novelId !== normalizedNovelId) {
      const entered = this.enterWorkbench(normalizedNovelId);
      if (!entered.route) return entered;
      const state = entered.state === "workbench-session"
        ? "workbench-session"
        : "workbench-no-session";
      return this.persistWorkbench(state, {
        ...entered.route,
        roleView,
      });
    }

    const state = active.state === "workbench-session"
      ? "workbench-session"
      : "workbench-no-session";
    return this.persistWorkbench(state, {
      novelId: active.route.novelId,
      documentId: active.route.documentId,
      chatPath: active.route.chatPath,
      roleView,
      ...routePageLocation(active.route.section, active.route.readingPanel),
      ownerToken: active.route.ownerToken,
    });
  }

  rememberLocation(
    novelId: string,
    update: WorkbenchLocationUpdate,
  ): RouteSessionSnapshot {
    const normalizedNovelId = novelId.trim();
    if (!normalizedNovelId || !isWorkbenchRouteSection(update.section)) {
      return this.toOrdinaryChat();
    }

    const active = this.resolve();
    const activeRoute = active.route?.novelId === normalizedNovelId
      ? active.route
      : null;
    const ownerToken = activeRoute?.ownerToken ?? this.newOwnerToken();
    if (!ownerToken) return this.toOrdinaryChat();

    const section = update.section === "chapters" ? undefined : update.section;
    const readingPanel = section === "reading" && isWorkbenchReadingPanel(update.readingPanel)
      ? update.readingPanel
      : section === "reading"
        ? "overview"
        : undefined;
    const state = activeRoute && active.state === "workbench-session"
      ? "workbench-session"
      : "workbench-no-session";
    return this.persistWorkbench(state, {
      novelId: normalizedNovelId,
      documentId: update.documentId,
      chatPath: activeRoute?.chatPath,
      roleView: activeRoute?.roleView,
      ...routePageLocation(section, readingPanel),
      ownerToken,
    });
  }

  leaveWorkbench(): RouteSessionSnapshot {
    this.removeStoredRoute();
    return this.transition({
      state: "leaving-workbench",
      route: null,
      ownerToken: null,
    });
  }

  private newOwnerToken(): string | null {
    try {
      const ownerToken = this.createOwnerToken();
      return validOwnerToken(ownerToken) ? ownerToken : null;
    } catch {
      return null;
    }
  }

  private readStoredRoute(): StoredWorkbenchRoute | null {
    let value: string | null;
    try {
      value = this.storage.getItem(WORKBENCH_ROUTE_KEY);
    } catch {
      return null;
    }
    if (!value) return null;

    try {
      const parsed: unknown = JSON.parse(value);
      if (isStoredWorkbenchRoute(parsed)) return parsed;
    } catch {
      // Invalid data is cleared below instead of being trusted as an owner.
    }
    this.removeStoredRoute();
    return null;
  }

  private persistWorkbench(
    state: "workbench-no-session" | "workbench-session",
    route: OwnedWorkbenchRouteState,
  ): RouteSessionSnapshot {
    const stored: StoredWorkbenchRoute = {
      storageVersion: WORKBENCH_ROUTE_STORAGE_VERSION,
      state,
      ...route,
    };
    try {
      this.storage.setItem(WORKBENCH_ROUTE_KEY, JSON.stringify(stored));
    } catch {
      return this.toOrdinaryChat();
    }
    return this.transition({ state, route, ownerToken: route.ownerToken });
  }

  private toOrdinaryChat(): RouteSessionSnapshot {
    this.removeStoredRoute();
    return this.transition(ORDINARY_CHAT_SNAPSHOT);
  }

  private removeStoredRoute(): void {
    try {
      this.storage.removeItem(WORKBENCH_ROUTE_KEY);
    } catch {
      // The caller still receives the conservative non-workbench state.
    }
  }

  private transition(snapshot: RouteSessionSnapshot): RouteSessionSnapshot {
    this.currentSnapshot = cloneSnapshot(snapshot);
    return cloneSnapshot(this.currentSnapshot);
  }
}


let browserRouteSessionStateMachine: RouteSessionStateMachine | undefined;


function browserStateMachine(): RouteSessionStateMachine {
  if (!browserRouteSessionStateMachine) {
    browserRouteSessionStateMachine = new RouteSessionStateMachine({
      getLocation: () => window.location,
      storage: {
        getItem: (key) => window.sessionStorage.getItem(key),
        setItem: (key, value) => window.sessionStorage.setItem(key, value),
        removeItem: (key) => window.sessionStorage.removeItem(key),
      },
    });
  }
  return browserRouteSessionStateMachine;
}


export function rememberWorkbenchRoute(novelId: string, documentId?: string): void {
  browserStateMachine().enterWorkbench(novelId, documentId);
}


export function rememberWorkbenchLocation(
  novelId: string,
  update: WorkbenchLocationUpdate,
): void {
  browserStateMachine().rememberLocation(novelId, update);
}


export function rememberCreativeCenterRoute(): void {
  browserStateMachine().enterWorkbench(CREATIVE_CENTER_ROUTE_SCOPE_ID);
}


export function rememberWorkbenchRoleView(
  novelId: string,
  roleView: "list" | "graph",
): void {
  browserStateMachine().rememberRoleView(novelId, roleView);
}


export function activeWorkbenchRouteSession(): RouteSessionSnapshot {
  return browserStateMachine().resolve();
}


export function activeWorkbenchRoute(): WorkbenchRouteState | null {
  const snapshot = activeWorkbenchRouteSession();
  return isCreativeCenterRouteSession(snapshot) ? null : snapshot.route;
}


export function clearWorkbenchRoute(): void {
  browserStateMachine().leaveWorkbench();
}


export function isCreativeCenterRouteSession(
  snapshot: RouteSessionSnapshot,
): boolean {
  return snapshot.route?.novelId === CREATIVE_CENTER_ROUTE_SCOPE_ID
    && (snapshot.state === "workbench-no-session"
      || snapshot.state === "workbench-session");
}


export function isNovelWorkbenchRouteSession(
  snapshot: RouteSessionSnapshot,
): boolean {
  return snapshot.route !== null
    && snapshot.route.novelId !== CREATIVE_CENTER_ROUTE_SCOPE_ID
    && (snapshot.state === "workbench-no-session"
      || snapshot.state === "workbench-session");
}
