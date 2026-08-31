import { describe, expect, it, vi } from "vitest";

import {
  isCreativeCenterRouteSession,
  isNovelWorkbenchRouteSession,
  replaceWorkbenchHistoryUrl,
  RouteSessionLocation,
  RouteSessionStateMachine,
  RouteSessionStorage,
} from "./workbench-route";


class MemorySessionStorage implements RouteSessionStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  dump(): string[] {
    return [...this.values.values()];
  }
}


const OWNER_ONE = "owner_token_0000000000000001";
const OWNER_TWO = "owner_token_0000000000000002";


function locationOf(path: string): RouteSessionLocation {
  const url = new URL(path, "https://qwenpaw.test");
  return { pathname: url.pathname, search: url.search };
}


function createHarness(initialPath = "/apps/ai-novel-world-2026") {
  const storage = new MemorySessionStorage();
  let location = locationOf(initialPath);
  const tokens = [OWNER_ONE, OWNER_TWO];
  const machine = new RouteSessionStateMachine({
    getLocation: () => location,
    storage,
    createOwnerToken: () => tokens.shift() ?? "owner_token_0000000000000099",
  });

  return {
    machine,
    storage,
    navigate(path: string) {
      location = locationOf(path);
    },
  };
}


describe("RouteSessionStateMachine", () => {
  it("keeps the creative center shell when native chat normalizes to a session path", () => {
    const harness = createHarness("/chat?novel_center=1");

    const entered = harness.machine.resolve();
    harness.navigate("/chat/session-center");
    const normalized = harness.machine.resolve();

    expect(isCreativeCenterRouteSession(entered)).toBe(true);
    expect(isNovelWorkbenchRouteSession(entered)).toBe(false);
    expect(normalized.state).toBe("workbench-session");
    expect(normalized.ownerToken).toBe(OWNER_ONE);
    expect(isCreativeCenterRouteSession(normalized)).toBe(true);
    expect(isNovelWorkbenchRouteSession(normalized)).toBe(false);
  });

  it("prefers an explicit novel workbench when both surface flags are present", () => {
    const harness = createHarness(
      "/chat?novel_center=1&novel_workbench=1&novel_id=novel-1",
    );

    const resolved = harness.machine.resolve();

    expect(isCreativeCenterRouteSession(resolved)).toBe(false);
    expect(isNovelWorkbenchRouteSession(resolved)).toBe(true);
    expect(resolved.route?.novelId).toBe("novel-1");
  });

  it("creates a tab owner when a novel is opened from the creative center", () => {
    const harness = createHarness();

    const pending = harness.machine.enterWorkbench("novel-1", "document-1");
    harness.navigate(
      "/chat?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    const entered = harness.machine.resolve();

    expect(pending).toEqual({
      state: "workbench-no-session",
      route: {
        novelId: "novel-1",
        documentId: "document-1",
        chatPath: undefined,
        roleView: undefined,
        ownerToken: OWNER_ONE,
      },
      ownerToken: OWNER_ONE,
    });
    expect(entered.state).toBe("workbench-no-session");
    expect(entered.ownerToken).toBe(OWNER_ONE);
    expect(entered.route?.novelId).toBe("novel-1");
  });

  it("keeps the owner and page when /chat is normalized to a session path", () => {
    const harness = createHarness();
    harness.machine.enterWorkbench("novel-1", "document-1");
    harness.navigate(
      "/chat?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    harness.machine.resolve();

    harness.navigate("/chat/session-1");
    const normalized = harness.machine.resolve();

    expect(normalized).toEqual({
      state: "workbench-session",
      route: {
        novelId: "novel-1",
        documentId: "document-1",
        chatPath: "/chat/session-1",
        roleView: undefined,
        ownerToken: OWNER_ONE,
      },
      ownerToken: OWNER_ONE,
    });
  });

  it("keeps an owned workbench when the native assistant starts a new chat", () => {
    const harness = createHarness(
      "/chat?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    harness.machine.resolve();
    harness.navigate("/chat/session-1");
    harness.machine.resolve();

    harness.navigate("/chat");
    const newChat = harness.machine.resolve();
    harness.navigate("/chat/session-2");
    const normalizedNewChat = harness.machine.resolve();

    expect(newChat).toEqual({
      state: "workbench-no-session",
      route: {
        novelId: "novel-1",
        documentId: "document-1",
        chatPath: undefined,
        roleView: undefined,
        ownerToken: OWNER_ONE,
      },
      ownerToken: OWNER_ONE,
    });
    expect(normalizedNewChat).toEqual({
      state: "workbench-session",
      route: {
        novelId: "novel-1",
        documentId: "document-1",
        chatPath: "/chat/session-2",
        roleView: undefined,
        ownerToken: OWNER_ONE,
      },
      ownerToken: OWNER_ONE,
    });
  });

  it("does not restore a stale workbench owner on a fresh direct /chat load", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1",
    );
    harness.machine.resolve();
    harness.navigate("/chat");

    const freshMachine = new RouteSessionStateMachine({
      getLocation: () => locationOf("/chat"),
      storage: harness.storage,
      createOwnerToken: () => OWNER_TWO,
    });
    const direct = freshMachine.resolve();

    expect(direct).toEqual({
      state: "ordinary-chat",
      route: null,
      ownerToken: null,
    });
    expect(harness.storage.dump()).toEqual([]);
  });

  it("also degrades a direct change to a different native session", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1",
    );
    harness.machine.resolve();

    harness.navigate("/chat/session-2");
    const changed = harness.machine.resolve();

    expect(changed.state).toBe("ordinary-chat");
    expect(changed.ownerToken).toBeNull();
    expect(harness.storage.dump()).toEqual([]);
  });

  it("clears route and owner before returning to the creative center", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1",
    );
    harness.machine.resolve();

    const leaving = harness.machine.leaveWorkbench();

    expect(leaving).toEqual({
      state: "leaving-workbench",
      route: null,
      ownerToken: null,
    });
    expect(harness.storage.dump()).toEqual([]);
    harness.navigate("/apps/ai-novel-world-2026");
    expect(harness.machine.resolve().state).toBe("ordinary-chat");
  });

  it("clears a stale owner on explicit ordinary-chat navigation", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1",
    );
    harness.machine.resolve();

    harness.navigate("/chat?source=sidebar");
    const ordinary = harness.machine.resolve();

    expect(ordinary.state).toBe("ordinary-chat");
    expect(ordinary.route).toBeNull();
    expect(ordinary.ownerToken).toBeNull();
    expect(harness.storage.dump()).toEqual([]);
  });

  it("restores a refreshed workbench session only with its matching tab owner", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    const original = harness.machine.resolve();
    harness.navigate("/chat/session-1");

    const refreshedMachine = new RouteSessionStateMachine({
      getLocation: () => locationOf("/chat/session-1"),
      storage: harness.storage,
      createOwnerToken: () => OWNER_TWO,
    });
    const refreshed = refreshedMachine.resolve();

    expect(refreshed.state).toBe("workbench-session");
    expect(refreshed.ownerToken).toBe(original.ownerToken);
    expect(refreshed.route).toMatchObject({
      novelId: "novel-1",
      documentId: "document-1",
      chatPath: "/chat/session-1",
    });
  });

  it("atomically restores a reading panel after the host removes the public query", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=characters",
    );
    const explicit = harness.machine.resolve();

    expect(explicit.route).toMatchObject({
      novelId: "novel-1",
      chatPath: "/chat/session-1",
      section: "reading",
      readingPanel: "characters",
    });

    harness.navigate("/chat/session-1");
    const normalized = harness.machine.resolve();
    const refreshedMachine = new RouteSessionStateMachine({
      getLocation: () => locationOf("/chat/session-1"),
      storage: harness.storage,
      createOwnerToken: () => OWNER_TWO,
    });
    const refreshed = refreshedMachine.resolve();

    expect(normalized.route).toMatchObject({
      section: "reading",
      readingPanel: "characters",
    });
    expect(refreshed.route).toMatchObject({
      section: "reading",
      readingPanel: "characters",
    });
    expect(refreshed.ownerToken).toBe(explicit.ownerToken);
  });

  it.each(["advanced-tuning", "private-voices"] as const)(
    "keeps the %s TTS workspace addressable across refresh",
    (readingPanel) => {
      const harness = createHarness(
        `/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=${readingPanel}`,
      );

      const explicit = harness.machine.resolve();
      expect(explicit.route).toMatchObject({
        novelId: "novel-1",
        section: "reading",
        readingPanel,
      });

      harness.navigate("/chat/session-1");
      expect(harness.machine.resolve().route).toMatchObject({
        section: "reading",
        readingPanel,
      });
    },
  );

  it("lets an explicit URL replace a stale panel and rejects unknown panels", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=characters",
    );
    harness.machine.resolve();

    harness.navigate(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=voice-generator",
    );
    const invalidPanel = harness.machine.resolve();
    expect(invalidPanel.route).toMatchObject({
      section: "reading",
      readingPanel: "overview",
    });

    harness.navigate(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=roles&reading_panel=characters",
    );
    const leftReading = harness.machine.resolve();
    expect(leftReading.route).toMatchObject({ section: "roles" });
    expect(leftReading.route).not.toHaveProperty("readingPanel");
  });

  it("clears a reading panel when leaving reading or switching novels", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=characters",
    );
    harness.machine.resolve();

    const chapters = harness.machine.rememberLocation("novel-1", {
      section: "chapters",
    });
    expect(chapters.route).not.toHaveProperty("section");
    expect(chapters.route).not.toHaveProperty("readingPanel");

    const switched = harness.machine.rememberLocation("novel-2", {
      section: "reading",
      readingPanel: "narrator",
    });
    expect(switched.ownerToken).toBe(OWNER_TWO);
    expect(switched.route).toMatchObject({
      novelId: "novel-2",
      section: "reading",
      readingPanel: "narrator",
    });
    expect(harness.storage.dump().join("\n")).not.toContain("novel-1");

    harness.machine.leaveWorkbench();
    expect(harness.storage.dump()).toEqual([]);
  });

  it("reconstructs a deep link from its public URL without restoring selection state", () => {
    const harness = createHarness(
      "/chat/session-9?novel_workbench=1&novel_id=novel-9&document_id=document-3&role_view=graph",
    );

    const deepLink = harness.machine.resolve();

    expect(deepLink).toEqual({
      state: "workbench-session",
      route: {
        novelId: "novel-9",
        documentId: "document-3",
        chatPath: "/chat/session-9",
        roleView: "graph",
        ownerToken: OWNER_ONE,
      },
      ownerToken: OWNER_ONE,
    });
    expect(deepLink.route).not.toHaveProperty("selection");
  });

  it("keeps one owner across matching browser back and forward entries", () => {
    const harness = createHarness(
      "/chat?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    harness.machine.resolve();
    harness.navigate("/chat/session-1");
    expect(harness.machine.resolve().state).toBe("workbench-session");

    harness.navigate(
      "/chat?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    const back = harness.machine.resolve();
    harness.navigate("/chat/session-1");
    const forward = harness.machine.resolve();

    expect(back.state).toBe("workbench-no-session");
    expect(back.ownerToken).toBe(OWNER_ONE);
    expect(forward.state).toBe("workbench-session");
    expect(forward.ownerToken).toBe(OWNER_ONE);
  });

  it("does not revive a cleared workbench through browser forward navigation", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1",
    );
    harness.machine.resolve();
    harness.navigate("/chat?source=sidebar");
    harness.machine.resolve();

    harness.navigate("/chat/session-1");
    const forward = harness.machine.resolve();

    expect(forward.state).toBe("ordinary-chat");
    expect(forward.ownerToken).toBeNull();
  });

  it("rotates the owner and destroys the old page binding when switching novels", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&document_id=document-1&role_view=graph",
    );
    harness.machine.resolve();

    const switched = harness.machine.enterWorkbench("novel-2", "document-2");

    expect(switched).toEqual({
      state: "workbench-no-session",
      route: {
        novelId: "novel-2",
        documentId: "document-2",
        chatPath: undefined,
        roleView: undefined,
        ownerToken: OWNER_TWO,
      },
      ownerToken: OWNER_TWO,
    });
    const persisted = harness.storage.dump().join("\n");
    expect(persisted).not.toContain(OWNER_ONE);
    expect(persisted).not.toContain("document-1");
    expect(persisted).not.toContain("/chat/session-1");
  });

  it("keeps the existing role-view API inside the same owned workbench", () => {
    const harness = createHarness(
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&document_id=document-1",
    );
    harness.machine.resolve();

    const remembered = harness.machine.rememberRoleView("novel-1", "graph");

    expect(remembered.state).toBe("workbench-session");
    expect(remembered.ownerToken).toBe(OWNER_ONE);
    expect(remembered.route).toMatchObject({
      novelId: "novel-1",
      documentId: "document-1",
      chatPath: "/chat/session-1",
      roleView: "graph",
    });
  });
});


describe("workbench history replacement", () => {
  it("preserves host history state and hash without creating a pushed entry", () => {
    const hostState = { session: "session-1" };
    const replaceState = vi.fn();
    const history = { state: hostState, replaceState };

    replaceWorkbenchHistoryUrl(
      history,
      "https://qwenpaw.test/chat/session-1?old=1#assistant",
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=characters",
    );

    expect(replaceState).toHaveBeenCalledOnce();
    expect(replaceState).toHaveBeenCalledWith(
      hostState,
      "",
      "/chat/session-1?novel_workbench=1&novel_id=novel-1&section=reading&reading_panel=characters#assistant",
    );
    expect(history).not.toHaveProperty("pushState");
  });
});
