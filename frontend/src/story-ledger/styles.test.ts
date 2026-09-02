import { afterEach, describe, expect, it, vi } from "vitest";

import {
  STORY_LEDGER_WORKSPACE_STYLE_ID,
  STORY_LEDGER_WORKSPACE_STYLES,
  ensureStoryLedgerWorkspaceStyles,
} from "./styles";

afterEach(() => vi.unstubAllGlobals());

describe("story ledger local responsive styles", () => {
  it("uses the ledger container rather than viewport width for list/detail degradation", () => {
    expect(STORY_LEDGER_WORKSPACE_STYLES).toContain("container: anw-story-ledger / inline-size");
    expect(STORY_LEDGER_WORKSPACE_STYLES).toContain("@container anw-story-ledger (min-width: 960px)");
    expect(STORY_LEDGER_WORKSPACE_STYLES).toContain("@container anw-story-ledger (max-width: 959px)");
    expect(STORY_LEDGER_WORKSPACE_STYLES).toContain(".anw-story-ledger-detail-shell.is-open");
    expect(STORY_LEDGER_WORKSPACE_STYLES).toContain("@container anw-story-ledger (max-width: 639px)");
    expect(STORY_LEDGER_WORKSPACE_STYLES).not.toContain("@media");
  });

  it("keeps the desktop fact-detail actions inside the host workbench viewport", () => {
    expect(STORY_LEDGER_WORKSPACE_STYLES).toContain("max-height: calc(100dvh - 240px)");
    expect(STORY_LEDGER_WORKSPACE_STYLES).not.toContain("max-height: calc(100vh - 180px)");
  });

  it("installs one module-local style element idempotently", () => {
    const appendChild = vi.fn();
    const style = { id: "", textContent: "" };
    const getElementById = vi.fn()
      .mockReturnValueOnce(null)
      .mockReturnValueOnce(style);
    vi.stubGlobal("document", {
      getElementById,
      createElement: vi.fn(() => style),
      head: { appendChild },
    });

    ensureStoryLedgerWorkspaceStyles();
    ensureStoryLedgerWorkspaceStyles();

    expect(style.id).toBe(STORY_LEDGER_WORKSPACE_STYLE_ID);
    expect(style.textContent).toBe(STORY_LEDGER_WORKSPACE_STYLES);
    expect(appendChild).toHaveBeenCalledTimes(1);
  });
});
