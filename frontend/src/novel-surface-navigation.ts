export const NOVEL_SURFACE_NAVIGATION_EVENT = "ai-novel-world-2026:navigation";


export interface NovelSurfaceLocation {
  origin: string;
  pathname: string;
}


export interface NovelSurfaceHistory {
  readonly state: unknown;
  pushState(data: unknown, unused: string, url?: string | URL | null): void;
}


export interface NovelSurfaceEventTarget {
  dispatchEvent(event: Event): boolean;
}


export interface NovelSurfaceNavigationOptions {
  location?: NovelSurfaceLocation;
  history?: NovelSurfaceHistory;
  eventTarget?: NovelSurfaceEventTarget;
  createEvent?: (type: string) => Event;
}


function isChatPath(pathname: string): boolean {
  return pathname === "/chat" || pathname.startsWith("/chat/");
}


export function novelSurfaceTarget(
  target: string,
  location: NovelSurfaceLocation,
): string {
  const url = new URL(target, location.origin);
  if (isChatPath(location.pathname) && isChatPath(url.pathname)) {
    url.pathname = location.pathname;
  }
  return `${url.pathname}${url.search}${url.hash}`;
}


/**
 * Switch between project-owned surfaces without unloading QwenPaw's chat shell.
 * The dedicated event is necessary because pushState does not emit popstate.
 */
export function navigateNovelSurface(
  target: string,
  options: NovelSurfaceNavigationOptions = {},
): void {
  const location = options.location ?? window.location;
  const history = options.history ?? window.history;
  const eventTarget = options.eventTarget ?? window;
  const createEvent = options.createEvent ?? ((type: string) => new Event(type));
  const next = novelSurfaceTarget(target, location);

  history.pushState(history.state, "", next);
  eventTarget.dispatchEvent(createEvent(NOVEL_SURFACE_NAVIGATION_EVENT));
}
