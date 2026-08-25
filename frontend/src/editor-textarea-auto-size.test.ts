import { describe, expect, it, vi } from "vitest";

import {
  EditorTextareaAutoSizeRuntime,
  EditorTextareaAutoSizeTarget,
  EditorTextareaResizeObserverEntry,
  observeEditorTextareaAutoSize,
  resizeEditorTextareaToContent,
} from "./editor-textarea-auto-size";


function textareaTarget(width: number, scrollHeight: number) {
  const target = {
    width,
    contentHeight: scrollHeight,
    style: { height: "" },
    get scrollHeight() { return this.contentHeight; },
    getBoundingClientRect() { return { width: this.width }; },
  };
  return target;
}


describe("editor textarea auto size", () => {
  it("uses the complete scroll height and keeps the minimum editor height", () => {
    const target = textareaTarget(700, 420);

    expect(resizeEditorTextareaToContent(target)).toBe(560);
    expect(target.style.height).toBe("560px");

    target.contentHeight = 940;
    expect(resizeEditorTextareaToContent(target)).toBe(940);
    expect(target.style.height).toBe("940px");
  });

  it("recalculates height when the assistant changes the editor width", () => {
    const target = textareaTarget(820, 900);
    let observerCallback: (
      entries: readonly EditorTextareaResizeObserverEntry[],
    ) => void = () => undefined;
    let windowResizeListener: () => void = () => undefined;
    const disconnect = vi.fn();
    const removeWindowResizeListener = vi.fn();
    const runtime: EditorTextareaAutoSizeRuntime = {
      createResizeObserver: (callback) => {
        observerCallback = callback;
        return { observe: vi.fn(), disconnect };
      },
      addWindowResizeListener: (listener) => { windowResizeListener = listener; },
      removeWindowResizeListener,
    };

    const stop = observeEditorTextareaAutoSize(
      target as EditorTextareaAutoSizeTarget,
      runtime,
    );
    expect(target.style.height).toBe("900px");

    target.width = 610;
    target.contentHeight = 1130;
    observerCallback([{ target, contentRect: { width: 610 } }]);
    expect(target.style.height).toBe("1130px");

    target.contentHeight = 1240;
    windowResizeListener();
    expect(target.style.height).toBe("1240px");

    stop();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(removeWindowResizeListener).toHaveBeenCalledWith(windowResizeListener);
  });
});
