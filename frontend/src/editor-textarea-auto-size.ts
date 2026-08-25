export interface EditorTextareaAutoSizeTarget {
  readonly ownerDocument?: {
    readonly fonts?: { readonly ready: PromiseLike<unknown> };
  };
  readonly scrollHeight: number;
  readonly style: { height: string };
  getBoundingClientRect(): { readonly width: number };
}


export interface EditorTextareaResizeObserverEntry {
  readonly target: EditorTextareaAutoSizeTarget;
  readonly contentRect: { readonly width: number };
}


export interface EditorTextareaResizeObserver {
  observe(target: EditorTextareaAutoSizeTarget): void;
  disconnect(): void;
}


export interface EditorTextareaAutoSizeRuntime {
  createResizeObserver(
    callback: (entries: readonly EditorTextareaResizeObserverEntry[]) => void,
  ): EditorTextareaResizeObserver | null;
  addWindowResizeListener(listener: () => void): void;
  removeWindowResizeListener(listener: () => void): void;
}


const browserRuntime: EditorTextareaAutoSizeRuntime = {
  createResizeObserver: (callback) => {
    if (typeof ResizeObserver === "undefined") return null;
    const observer = new ResizeObserver((entries) => callback(entries.map((entry) => ({
      target: entry.target as unknown as EditorTextareaAutoSizeTarget,
      contentRect: { width: entry.contentRect.width },
    }))));
    return {
      observe: (target) => observer.observe(target as unknown as Element),
      disconnect: () => observer.disconnect(),
    };
  },
  addWindowResizeListener: (listener) => window.addEventListener("resize", listener),
  removeWindowResizeListener: (listener) => window.removeEventListener("resize", listener),
};


export function resizeEditorTextareaToContent(
  textarea: EditorTextareaAutoSizeTarget,
  minimumHeight = 560,
): number {
  textarea.style.height = "auto";
  const nextHeight = Math.max(minimumHeight, textarea.scrollHeight);
  textarea.style.height = `${nextHeight}px`;
  return nextHeight;
}


export function observeEditorTextareaAutoSize(
  textarea: EditorTextareaAutoSizeTarget,
  runtime: EditorTextareaAutoSizeRuntime = browserRuntime,
): () => void {
  let active = true;
  let measuredWidth: number | null = null;

  const resize = (width: number, force = false) => {
    if (!active || width <= 0) return;
    if (!force && measuredWidth !== null && Math.abs(measuredWidth - width) < 0.5) return;
    measuredWidth = width;
    resizeEditorTextareaToContent(textarea);
  };

  const resizeFromElement = () => resize(textarea.getBoundingClientRect().width, true);
  resizeFromElement();

  const observer = runtime.createResizeObserver((entries) => {
    const entry = entries.find((item) => item.target === textarea);
    if (entry) resize(entry.contentRect.width);
  });
  observer?.observe(textarea);

  runtime.addWindowResizeListener(resizeFromElement);
  const fontsReady = textarea.ownerDocument?.fonts?.ready;
  if (fontsReady) {
    void Promise.resolve(fontsReady).then(resizeFromElement, () => undefined);
  }

  return () => {
    active = false;
    observer?.disconnect();
    runtime.removeWindowResizeListener(resizeFromElement);
  };
}
