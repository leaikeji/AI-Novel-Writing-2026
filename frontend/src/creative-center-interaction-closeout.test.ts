import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createReactHarness } from "./embedding/test-harness";


let page: typeof import("./creative-center");


beforeEach(async () => {
  vi.resetModules();
  const harness = createReactHarness();
  const input = Object.assign("input", { TextArea: "textarea" });
  const components = new Proxy({ Input: input }, {
    get: (target, key) => key === "Input" ? target.Input : String(key),
  });
  vi.stubGlobal("window", {
    QwenPaw: {
      host: {
        React: { ...harness.React, useCallback: <T>(callback: T) => callback },
        ReactDOM: {},
        antd: components,
        antdIcons: components,
      },
    },
  });
  page = await import("./creative-center");
});


afterEach(() => vi.unstubAllGlobals());


describe("creation wizard closeout", () => {
  const closeLock = () => ({ current: false });

  it("enables keyboard close only outside a protected operation", () => {
    expect(page.creationWizardModalInteraction(false)).toEqual({
      keyboard: true,
      closable: true,
      maskClosable: false,
      focusTriggerAfterClose: true,
    });
    expect(page.creationWizardModalInteraction(true)).toEqual({
      keyboard: false,
      closable: false,
      maskClosable: false,
      focusTriggerAfterClose: true,
    });
  });

  it("refuses every close path while busy", async () => {
    const save = vi.fn(async () => undefined);
    const close = vi.fn();
    const setBusy = vi.fn();
    const reportError = vi.fn();
    await expect(page.closeCreationWizardSafely({
      busy: true,
      hasDraft: true,
      lock: closeLock(),
      save,
      close,
      setBusy,
      reportError,
    })).resolves.toBe("blocked");
    expect(save).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
    expect(setBusy).not.toHaveBeenCalled();
  });

  it("saves once before closing a non-busy draft", async () => {
    const order: string[] = [];
    const setBusy = vi.fn((busy: boolean) => order.push(`busy:${busy}`));
    await expect(page.closeCreationWizardSafely({
      busy: false,
      hasDraft: true,
      lock: closeLock(),
      save: vi.fn(async () => { order.push("save"); }),
      close: vi.fn(() => { order.push("close"); }),
      setBusy,
      reportError: vi.fn(),
    })).resolves.toBe("closed");
    expect(order).toEqual(["busy:true", "save", "close", "busy:false"]);
  });

  it("keeps the wizard open and reports a recoverable save failure", async () => {
    const close = vi.fn();
    const reportError = vi.fn();
    const failure = new Error("version conflict");
    await expect(page.closeCreationWizardSafely({
      busy: false,
      hasDraft: true,
      lock: closeLock(),
      save: vi.fn(async () => { throw failure; }),
      close,
      setBusy: vi.fn(),
      reportError,
    })).resolves.toBe("save-failed");
    expect(close).not.toHaveBeenCalled();
    expect(reportError).toHaveBeenCalledWith(failure);
  });

  it("synchronously rejects a second close before React commits busy state", async () => {
    let finishSave!: () => void;
    const pendingSave = new Promise<void>((resolve) => { finishSave = resolve; });
    const lock = closeLock();
    const save = vi.fn(() => pendingSave);
    const close = vi.fn();
    const actions = {
      busy: false,
      hasDraft: true,
      lock,
      save,
      close,
      setBusy: vi.fn(),
      reportError: vi.fn(),
    };

    const first = page.closeCreationWizardSafely(actions);
    const second = page.closeCreationWizardSafely(actions);

    await expect(second).resolves.toBe("blocked");
    expect(save).toHaveBeenCalledOnce();
    expect(close).not.toHaveBeenCalled();

    finishSave();
    await expect(first).resolves.toBe("closed");
    expect(save).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(lock.current).toBe(false);
  });
});
