import { describe, expect, it, vi } from "vitest";

import {
  navigateNovelSurface,
  NOVEL_SURFACE_NAVIGATION_EVENT,
  novelSurfaceTarget,
} from "./novel-surface-navigation";


describe("novel surface navigation", () => {
  it("keeps the active native chat session while changing PawApp surfaces", () => {
    expect(novelSurfaceTarget(
      "/chat?novel_workbench=1&novel_id=novel-1",
      { origin: "https://qwenpaw.test", pathname: "/chat/session-1" },
    )).toBe("/chat/session-1?novel_workbench=1&novel_id=novel-1");
  });

  it("uses the requested chat root outside an already mounted chat route", () => {
    expect(novelSurfaceTarget(
      "/chat?novel_center=1",
      { origin: "https://qwenpaw.test", pathname: "/apps/ai-novel-world-2026" },
    )).toBe("/chat?novel_center=1");
  });

  it("pushes one history entry and explicitly notifies the mounted wrapper", () => {
    const pushState = vi.fn();
    const dispatchEvent = vi.fn(() => true);
    const event = { type: NOVEL_SURFACE_NAVIGATION_EVENT } as Event;

    navigateNovelSurface("/chat?novel_center=1", {
      location: { origin: "https://qwenpaw.test", pathname: "/chat/session-1" },
      history: { state: { host: "preserved" }, pushState },
      eventTarget: { dispatchEvent },
      createEvent: () => event,
    });

    expect(pushState).toHaveBeenCalledWith(
      { host: "preserved" },
      "",
      "/chat/session-1?novel_center=1",
    );
    expect(dispatchEvent).toHaveBeenCalledWith(event);
  });
});
