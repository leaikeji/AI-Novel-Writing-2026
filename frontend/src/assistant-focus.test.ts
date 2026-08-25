import { describe, expect, it, vi } from "vitest";

import { restoreDialogTriggerFocus } from "./assistant-focus";


describe("restoreDialogTriggerFocus", () => {
  it("returns focus to the dialog trigger without scrolling", () => {
    const focus = vi.fn();

    expect(restoreDialogTriggerFocus({ focus })).toBe(true);
    expect(focus).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
  });

  it("does nothing when the trigger is no longer mounted", () => {
    expect(restoreDialogTriggerFocus(null)).toBe(false);
  });
});
