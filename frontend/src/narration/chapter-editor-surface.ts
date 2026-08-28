import type { Extension } from "@codemirror/state";

import type { AssistantTextControl } from "../chapter-workflow";
import {
  assertWellFormedUtf16,
  type DocumentLease,
  type EditorChangeOrigin,
  type NarrationEditorBridge,
  type NarrationEditorSelection,
  type OnEditorDocChanged,
} from "./editor-bridge";
import {
  createCodeMirrorNarrationAdapter,
  type CodeMirrorNarrationAdapter,
  type CodeMirrorNarrationAdapterOptions,
} from "./editor-codemirror";
import {
  createTextareaNarrationAdapter,
  normalizeTextareaSelection,
  type TextareaNarrationAdapter,
  type TextareaNarrationAdapterOptions,
} from "./editor-textarea-fallback";
import type { AuthorFollowInterruption } from "./segment-follow";
import type {
  EditorParagraphContextMenuRequest,
  OnEditorParagraphContextMenu,
  OnEditorParagraphPlaybackCommand,
} from "./paragraph-gutter";
import {
  createEditorParagraphGutterExtension,
  type EditorParagraphGutterEntry,
} from "./editor-paragraph-gutter";


export interface CreateChapterEditorSurfaceOptions {
  readonly parent: HTMLElement;
  readonly lease: DocumentLease;
  readonly initialValue: string;
  readonly currentContentHash: string;
  readonly ariaLabel: string;
  readonly selection?: NarrationEditorSelection;
  readonly onDocChanged: OnEditorDocChanged;
  readonly isLeaseCurrent: (lease: DocumentLease) => boolean;
  readonly onFocusChange?: (focused: boolean) => void;
  readonly onAuthorInteraction?: (interruption: AuthorFollowInterruption) => void;
  readonly onParagraphGutterActivate?: (paragraphOrdinal: number) => void;
  readonly onParagraphPlaybackCommand?: OnEditorParagraphPlaybackCommand;
  readonly codeMirrorExtensions?: readonly Extension[];
}


export interface ChapterEditorSurfaceHandle {
  readonly kind: "codemirror6" | "textarea-fallback";
  readonly bridge: NarrationEditorBridge;
  readonly assistantControl: AssistantTextControl;
  readValue(): string;
  setValue(nextValue: string, origin: EditorChangeOrigin): boolean;
  setParagraphGutter(entries: readonly EditorParagraphGutterEntry[]): boolean;
  requestPlaybackFromCursor(): boolean;
  focus(): void;
  dispose(): void;
}


interface ChapterEditorAdapter {
  readonly bridge: NarrationEditorBridge;
  readValue(): string;
  readSelection(): NarrationEditorSelection;
  setValue(nextValue: string, origin: EditorChangeOrigin): boolean;
  setParagraphGutter?(entries: readonly EditorParagraphGutterEntry[]): boolean;
  focusSelection(selection: NarrationEditorSelection): boolean;
  focus(): void;
  dispose(): void;
}


export interface ChapterEditorSurfaceDependencies {
  readonly createCodeMirrorAdapter: (
    options: CodeMirrorNarrationAdapterOptions,
  ) => CodeMirrorNarrationAdapter;
  readonly createTextareaAdapter: (
    options: TextareaNarrationAdapterOptions,
  ) => TextareaNarrationAdapter;
  readonly createTextareaElement: (parent: HTMLElement) => HTMLTextAreaElement;
  readonly hashEditorValue: (value: string) => Promise<string>;
}


export const CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE = "data-editor-value-sha256";
const SHA256_PATTERN = /^[a-f0-9]{64}$/;


async function hashEditorValueSha256(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is required for chapter editor evidence");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


const DEFAULT_DEPENDENCIES: ChapterEditorSurfaceDependencies = Object.freeze({
  createCodeMirrorAdapter: createCodeMirrorNarrationAdapter,
  createTextareaAdapter: createTextareaNarrationAdapter,
  createTextareaElement(parent: HTMLElement) {
    const ownerDocument = parent.ownerDocument ?? globalThis.document;
    if (!ownerDocument) throw new Error("A document is required for the textarea fallback");
    return ownerDocument.createElement("textarea");
  },
  hashEditorValue: hashEditorValueSha256,
});


function removeAddedChildren(parent: HTMLElement, originalChildren: ReadonlySet<Node>): void {
  for (const child of Array.from(parent.childNodes)) {
    if (!originalChildren.has(child)) parent.removeChild(child);
  }
}


function normalizedSelection(
  text: string,
  start: number,
  end: number,
  direction: string | null | undefined,
): NarrationEditorSelection {
  return normalizeTextareaSelection(text, {
    startUtf16: start,
    endUtf16: end,
    direction: direction === "forward" || direction === "backward" ? direction : "none",
  });
}


class SurfaceAssistantTextControl implements AssistantTextControl {
  constructor(
    private readonly getAdapter: () => ChapterEditorAdapter | null,
  ) {}

  get selectionStart(): number | null {
    return this.getAdapter()?.readSelection().startUtf16 ?? null;
  }

  set selectionStart(value: number | null) {
    const adapter = this.getAdapter();
    if (!adapter || value === null) return;
    const current = adapter.readSelection();
    this.setSelectionRange(value, Math.max(value, current.endUtf16), current.direction);
  }

  get selectionEnd(): number | null {
    return this.getAdapter()?.readSelection().endUtf16 ?? null;
  }

  set selectionEnd(value: number | null) {
    const adapter = this.getAdapter();
    if (!adapter || value === null) return;
    const current = adapter.readSelection();
    this.setSelectionRange(Math.min(current.startUtf16, value), value, current.direction);
  }

  get selectionDirection(): string | null {
    return this.getAdapter()?.readSelection().direction ?? null;
  }

  set selectionDirection(value: string | null) {
    const adapter = this.getAdapter();
    if (!adapter) return;
    const current = adapter.readSelection();
    this.setSelectionRange(current.startUtf16, current.endUtf16, (
      value === "forward" || value === "backward" ? value : "none"
    ));
  }

  focus(): void {
    this.getAdapter()?.focus();
  }

  setSelectionRange(
    start: number,
    end: number,
    direction: "forward" | "backward" | "none" = "none",
  ): void {
    const adapter = this.getAdapter();
    if (!adapter) return;
    adapter.focusSelection(normalizedSelection(adapter.readValue(), start, end, direction));
  }
}


function createTextareaFallback(
  options: CreateChapterEditorSurfaceOptions,
  dependencies: ChapterEditorSurfaceDependencies,
  onParagraphContextMenu?: OnEditorParagraphContextMenu,
): TextareaNarrationAdapter {
  const element = dependencies.createTextareaElement(options.parent);
  element.className = "anw-chapter-editor-textarea-fallback";
  element.setAttribute("aria-label", options.ariaLabel);
  element.spellcheck = true;
  element.wrap = "soft";
  element.value = options.initialValue;
  if (options.selection) {
    const selection = normalizedSelection(
      options.initialValue,
      options.selection.startUtf16,
      options.selection.endUtf16,
      options.selection.direction,
    );
    element.setSelectionRange(
      selection.startUtf16,
      selection.endUtf16,
      selection.direction,
    );
  }
  options.parent.appendChild(element);
  try {
    return dependencies.createTextareaAdapter({
      element,
      lease: options.lease,
      initialValue: options.initialValue,
      currentContentHash: options.currentContentHash,
      onDocChanged: options.onDocChanged,
      isLeaseCurrent: options.isLeaseCurrent,
      onFocusChange: options.onFocusChange,
      onAuthorInteraction: options.onAuthorInteraction,
      onParagraphPlaybackCommand: options.onParagraphPlaybackCommand,
      onParagraphContextMenu,
    });
  } catch (error) {
    if (element.parentNode === options.parent) options.parent.removeChild(element);
    throw error;
  }
}


export function createChapterEditorSurface(
  options: CreateChapterEditorSurfaceOptions,
  dependencyOverrides: Partial<ChapterEditorSurfaceDependencies> = {},
): ChapterEditorSurfaceHandle {
  if (!options.ariaLabel.trim()) throw new TypeError("ariaLabel must not be empty");
  assertWellFormedUtf16(options.initialValue, "Chapter editor initialValue");
  const dependencies: ChapterEditorSurfaceDependencies = {
    ...DEFAULT_DEPENDENCIES,
    ...dependencyOverrides,
  };
  const originalChildren = new Set(Array.from(options.parent.childNodes));
  let disposed = false;
  let digestGeneration = 0;
  let canonicalEditorValue = options.initialValue;
  const clearCanonicalEditorDigest = () => {
    const removeAttribute = options.parent.removeAttribute;
    if (typeof removeAttribute === "function") {
      removeAttribute.call(options.parent, CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE);
    }
  };
  const publishCanonicalEditorDigest = (value: string) => {
    canonicalEditorValue = value;
    const generation = ++digestGeneration;
    clearCanonicalEditorDigest();
    void Promise.resolve()
      .then(() => dependencies.hashEditorValue(value))
      .then((digest) => {
        if (
          disposed
          || generation !== digestGeneration
          || value !== canonicalEditorValue
          || !SHA256_PATTERN.test(digest)
        ) return;
        const setAttribute = options.parent.setAttribute;
        if (typeof setAttribute === "function") {
          setAttribute.call(options.parent, CHAPTER_EDITOR_VALUE_SHA256_ATTRIBUTE, digest);
        }
      })
      .catch(() => {
        // Missing is the fail-closed state; never retain an older value digest.
      });
  };
  const onDocChanged: OnEditorDocChanged = (event) => {
    publishCanonicalEditorDigest(event.nextValue);
    options.onDocChanged(event);
  };
  let contextMenu: HTMLDivElement | null = null;
  let restoreContextFocus = false;
  const ownerDocument = options.parent.ownerDocument;
  const closeContextMenu = () => {
    if (!contextMenu) return;
    const closing = contextMenu;
    contextMenu = null;
    ownerDocument?.removeEventListener("pointerdown", onDocumentPointerDown, true);
    ownerDocument?.removeEventListener("keydown", onDocumentKeyDown, true);
    closing.remove();
    if (restoreContextFocus && !disposed) adapter?.focus();
    restoreContextFocus = false;
  };
  const onDocumentPointerDown = (event: Event) => {
    if (contextMenu && !contextMenu.contains(event.target as Node | null)) closeContextMenu();
  };
  const onDocumentKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    restoreContextFocus = true;
    closeContextMenu();
  };
  const openContextMenu = (request: EditorParagraphContextMenuRequest): boolean => {
    if (disposed || !options.onParagraphPlaybackCommand || !ownerDocument?.body) return false;
    closeContextMenu();
    const menu = ownerDocument.createElement("div");
    menu.className = "anw-narration-paragraph-context-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", "段落朗读命令");
    menu.style.position = "fixed";
    menu.style.left = `${Math.max(0, request.clientX)}px`;
    menu.style.top = `${Math.max(0, request.clientY)}px`;
    menu.style.zIndex = "1100";
    const command = ownerDocument.createElement("button");
    command.type = "button";
    command.setAttribute("role", "menuitem");
    command.className = "anw-narration-paragraph-context-menu__command";
    command.textContent = "从本段朗读";
    command.addEventListener("click", () => {
      options.onParagraphPlaybackCommand?.({
        source: "context-menu",
        lookup: request.lookup,
      });
      restoreContextFocus = true;
      closeContextMenu();
    }, { once: true });
    menu.appendChild(command);
    ownerDocument.body.appendChild(menu);
    contextMenu = menu;
    ownerDocument.addEventListener("pointerdown", onDocumentPointerDown, true);
    ownerDocument.addEventListener("keydown", onDocumentKeyDown, true);
    command.focus();
    return true;
  };
  let adapter: ChapterEditorAdapter;
  try {
    adapter = dependencies.createCodeMirrorAdapter({
      parent: options.parent,
      lease: options.lease,
      initialValue: options.initialValue,
      currentContentHash: options.currentContentHash,
      selection: options.selection,
      onDocChanged,
      isLeaseCurrent: options.isLeaseCurrent,
      ariaLabel: options.ariaLabel,
      onFocusChange: options.onFocusChange,
      onAuthorInteraction: options.onAuthorInteraction,
      onParagraphPlaybackCommand: options.onParagraphPlaybackCommand,
      onParagraphContextMenu: ownerDocument?.body ? openContextMenu : undefined,
      extensions: [
        ...(options.onParagraphGutterActivate
          ? [createEditorParagraphGutterExtension({
              onActivate: options.onParagraphGutterActivate,
            })]
          : []),
        ...(options.codeMirrorExtensions ?? []),
      ],
    });
  } catch {
    removeAddedChildren(options.parent, originalChildren);
    adapter = createTextareaFallback(
      { ...options, onDocChanged },
      dependencies,
      ownerDocument?.body ? openContextMenu : undefined,
    );
  }
  publishCanonicalEditorDigest(options.initialValue);

  const assistantControl = new SurfaceAssistantTextControl(() => (
    disposed ? null : adapter
  ));

  return {
    kind: adapter.bridge.kind,
    bridge: adapter.bridge,
    assistantControl,
    readValue() {
      return disposed ? adapter.bridge.readSnapshot().text : adapter.readValue();
    },
    setValue(nextValue, origin) {
      if (disposed) return false;
      assertWellFormedUtf16(nextValue, "Chapter editor nextValue");
      return adapter.setValue(nextValue, origin);
    },
    setParagraphGutter(entries) {
      if (disposed || !adapter.setParagraphGutter) return false;
      return adapter.setParagraphGutter(entries);
    },
    requestPlaybackFromCursor() {
      if (disposed || !options.onParagraphPlaybackCommand) return false;
      const snapshot = adapter.bridge.readSnapshot();
      if (!snapshot.active || snapshot.composing) return false;
      return options.onParagraphPlaybackCommand({
        source: "cursor-command",
        lookup: { positionUtf16: adapter.readSelection().startUtf16 },
      });
    },
    focus() {
      if (!disposed) adapter.focus();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      digestGeneration += 1;
      clearCanonicalEditorDigest();
      closeContextMenu();
      adapter.dispose();
      removeAddedChildren(options.parent, originalChildren);
    },
  };
}
