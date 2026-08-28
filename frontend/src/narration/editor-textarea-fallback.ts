import {
  createNarrationEditorBridge,
  type DocumentLease,
  type EditorChangeOrigin,
  type EditorTextChange,
  type NarrationEditorBridge,
  type NarrationEditorSelection,
  type OnEditorDocChanged,
  type TransactionMappingReport,
} from "./editor-bridge";
import type { AuthorFollowInterruption } from "./segment-follow";
import {
  isNarrationSeekKeyboardCommand,
  type NarrationKeyboardEventLike,
  type OnEditorParagraphContextMenu,
  type OnEditorParagraphPlaybackCommand,
} from "./paragraph-gutter";


export interface TextareaNarrationAdapterOptions {
  readonly element: HTMLTextAreaElement;
  readonly lease: DocumentLease;
  readonly initialValue?: string;
  readonly currentContentHash: string;
  readonly onDocChanged: OnEditorDocChanged;
  readonly isLeaseCurrent: (lease: DocumentLease) => boolean;
  readonly onFocusChange?: (focused: boolean) => void;
  readonly onAuthorInteraction?: (interruption: AuthorFollowInterruption) => void;
  readonly onParagraphPlaybackCommand?: OnEditorParagraphPlaybackCommand;
  readonly onParagraphContextMenu?: OnEditorParagraphContextMenu;
}


export interface TextareaNarrationAdapter {
  readonly bridge: NarrationEditorBridge;
  readonly element: HTMLTextAreaElement;
  readValue(): string;
  readSelection(): NarrationEditorSelection;
  setValue(nextValue: string, origin: EditorChangeOrigin): boolean;
  focusSelection(selection: NarrationEditorSelection): boolean;
  focus(): void;
  dispose(): void;
}


function splitsSurrogatePair(text: string, offset: number): boolean {
  return (
    offset > 0
    && offset < text.length
    && text.charCodeAt(offset - 1) >= 0xd800
    && text.charCodeAt(offset - 1) <= 0xdbff
    && text.charCodeAt(offset) >= 0xdc00
    && text.charCodeAt(offset) <= 0xdfff
  );
}


function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}


export function normalizeTextareaSelection(
  text: string,
  selection: NarrationEditorSelection,
): NarrationEditorSelection {
  let startUtf16 = clamp(selection.startUtf16, 0, text.length);
  let endUtf16 = clamp(selection.endUtf16, startUtf16, text.length);
  if (startUtf16 === endUtf16 && splitsSurrogatePair(text, startUtf16)) {
    startUtf16 -= 1;
    endUtf16 = startUtf16;
  } else {
    if (splitsSurrogatePair(text, startUtf16)) startUtf16 -= 1;
    if (splitsSurrogatePair(text, endUtf16)) endUtf16 += 1;
  }
  return {
    startUtf16,
    endUtf16,
    direction: startUtf16 === endUtf16 ? "none" : selection.direction,
  };
}


export function computeTextareaTextChange(
  previousValue: string,
  nextValue: string,
): EditorTextChange | null {
  if (previousValue === nextValue) return null;
  const sharedLength = Math.min(previousValue.length, nextValue.length);
  let prefixLength = 0;
  while (
    prefixLength < sharedLength
    && previousValue.charCodeAt(prefixLength) === nextValue.charCodeAt(prefixLength)
  ) {
    prefixLength += 1;
  }
  if (
    splitsSurrogatePair(previousValue, prefixLength)
    || splitsSurrogatePair(nextValue, prefixLength)
  ) {
    prefixLength -= 1;
  }

  let suffixLength = 0;
  while (
    suffixLength < previousValue.length - prefixLength
    && suffixLength < nextValue.length - prefixLength
    && previousValue.charCodeAt(previousValue.length - suffixLength - 1)
      === nextValue.charCodeAt(nextValue.length - suffixLength - 1)
  ) {
    suffixLength += 1;
  }
  const previousSuffixStart = previousValue.length - suffixLength;
  const nextSuffixStart = nextValue.length - suffixLength;
  if (
    splitsSurrogatePair(previousValue, previousSuffixStart)
    || splitsSurrogatePair(nextValue, nextSuffixStart)
  ) {
    suffixLength -= 1;
  }

  return {
    startUtf16: prefixLength,
    endUtf16: previousValue.length - suffixLength,
    insertedText: nextValue.slice(prefixLength, nextValue.length - suffixLength),
  };
}


export function applyTextareaValueToBridge(
  bridge: NarrationEditorBridge,
  nextValue: string,
  selection: NarrationEditorSelection,
  origin: EditorChangeOrigin,
): TransactionMappingReport | null {
  const snapshot = bridge.readSnapshot();
  if (!snapshot.active || snapshot.text === nextValue) return null;
  const change = computeTextareaTextChange(snapshot.text, nextValue);
  if (!change) return null;
  return bridge.applyTransaction({
    changes: [change],
    selectionAfter: normalizeTextareaSelection(nextValue, selection),
    origin,
  });
}


export function textareaInputOrigin(
  event: Event,
  composing: boolean,
): EditorChangeOrigin {
  if (composing) return "composition";
  const inputType = "inputType" in event
    ? (event as Event & { readonly inputType?: unknown }).inputType
    : undefined;
  if (inputType === "historyUndo") return "undo";
  if (inputType === "historyRedo") return "redo";
  return "input";
}


function selectionFromTextarea(element: HTMLTextAreaElement): NarrationEditorSelection {
  const startUtf16 = element.selectionStart ?? 0;
  const endUtf16 = element.selectionEnd ?? startUtf16;
  return normalizeTextareaSelection(element.value, {
    startUtf16,
    endUtf16,
    direction: startUtf16 === endUtf16
      ? "none"
      : element.selectionDirection === "backward" ? "backward" : "forward",
  });
}


export function createTextareaNarrationAdapter(
  options: TextareaNarrationAdapterOptions,
): TextareaNarrationAdapter {
  const initialValue = options.initialValue ?? options.element.value;
  options.element.value = initialValue;
  const initialSelection = normalizeTextareaSelection(initialValue, {
    startUtf16: options.element.selectionStart ?? 0,
    endUtf16: options.element.selectionEnd ?? options.element.selectionStart ?? 0,
    direction: options.element.selectionStart === options.element.selectionEnd
      ? "none"
      : options.element.selectionDirection === "backward" ? "backward" : "forward",
  });
  options.element.setSelectionRange(
    initialSelection.startUtf16,
    initialSelection.endUtf16,
    initialSelection.direction,
  );
  const bridge = createNarrationEditorBridge({
    kind: "textarea-fallback",
    lease: options.lease,
    text: initialValue,
    currentContentHash: options.currentContentHash,
    selection: initialSelection,
    onDocChanged: options.onDocChanged,
    isLeaseCurrent: options.isLeaseCurrent,
  });
  let disposed = false;

  const noteAuthorInteraction = (interruption: AuthorFollowInterruption) => {
    if (disposed || !bridge.readSnapshot().active) return;
    bridge.noteManualScroll();
    options.onAuthorInteraction?.(interruption);
  };

  const syncSelection = (notify: boolean) => {
    if (disposed || !bridge.readSnapshot().active) return;
    const previous = bridge.readSnapshot().selection;
    const next = selectionFromTextarea(options.element);
    bridge.setSelection(next);
    if (
      notify
      && (
        previous.startUtf16 !== next.startUtf16
        || previous.endUtf16 !== next.endUtf16
        || previous.direction !== next.direction
      )
    ) {
      noteAuthorInteraction(next.startUtf16 === next.endUtf16 ? "caret-move" : "selection");
    }
  };

  const syncValue = (origin: EditorChangeOrigin) => {
    if (disposed || !bridge.readSnapshot().active) return false;
    const report = applyTextareaValueToBridge(
      bridge,
      options.element.value,
      selectionFromTextarea(options.element),
      origin,
    );
    return report?.applied ?? false;
  };

  const onInput: EventListener = (event) => {
    const composing = bridge.readSnapshot().composing;
    if (syncValue(textareaInputOrigin(event, composing))) {
      noteAuthorInteraction(composing ? "composition" : "input");
    }
  };
  const onCompositionStart: EventListener = () => {
    bridge.beginComposition();
    noteAuthorInteraction("composition");
  };
  const onCompositionEnd: EventListener = () => {
    if (syncValue("composition")) noteAuthorInteraction("composition");
    bridge.endComposition();
  };
  const onSelection: EventListener = () => {
    syncSelection(true);
  };
  const onScroll: EventListener = () => {
    if (!disposed) noteAuthorInteraction("manual-scroll");
  };
  const onFocus: EventListener = () => {
    if (!disposed && bridge.readSnapshot().active) options.onFocusChange?.(true);
  };
  const onBlur: EventListener = () => {
    if (!disposed && bridge.readSnapshot().active) options.onFocusChange?.(false);
  };
  const onKeyDown: EventListener = (event) => {
    if (!options.onParagraphPlaybackCommand) return;
    const keyboardEvent = event as KeyboardEvent;
    const commandEvent: NarrationKeyboardEventLike = {
      key: keyboardEvent.key,
      altKey: keyboardEvent.altKey,
      ctrlKey: keyboardEvent.ctrlKey,
      metaKey: keyboardEvent.metaKey,
      shiftKey: keyboardEvent.shiftKey,
      repeat: keyboardEvent.repeat,
      isComposing: keyboardEvent.isComposing || bridge.readSnapshot().composing,
    };
    if (!isNarrationSeekKeyboardCommand(commandEvent)) return;
    syncSelection(false);
    const handled = options.onParagraphPlaybackCommand({
      source: "keyboard",
      event: commandEvent,
      lookup: { positionUtf16: bridge.readSnapshot().selection.startUtf16 },
    });
    if (!handled) return;
    event.preventDefault();
    event.stopPropagation();
  };
  const onContextMenu: EventListener = (event) => {
    if (bridge.readSnapshot().composing) return;
    syncSelection(false);
    const lookup = { positionUtf16: bridge.readSnapshot().selection.startUtf16 };
    const pointer = event as MouseEvent;
    const handled = options.onParagraphContextMenu
      ? options.onParagraphContextMenu({
          lookup,
          clientX: pointer.clientX,
          clientY: pointer.clientY,
        })
      : options.onParagraphPlaybackCommand?.({ source: "context-menu", lookup }) ?? false;
    if (!handled) return;
    event.preventDefault();
    event.stopPropagation();
  };

  options.element.addEventListener("input", onInput);
  options.element.addEventListener("compositionstart", onCompositionStart);
  options.element.addEventListener("compositionend", onCompositionEnd);
  options.element.addEventListener("select", onSelection);
  options.element.addEventListener("keyup", onSelection);
  options.element.addEventListener("mouseup", onSelection);
  options.element.addEventListener("scroll", onScroll, { passive: true });
  options.element.addEventListener("focus", onFocus);
  options.element.addEventListener("blur", onBlur);
  options.element.addEventListener("keydown", onKeyDown);
  options.element.addEventListener("contextmenu", onContextMenu);

  return {
    bridge,
    element: options.element,
    readValue() {
      return options.element.value;
    },
    readSelection() {
      return selectionFromTextarea(options.element);
    },
    setValue(nextValue, origin) {
      if (disposed || !bridge.readSnapshot().active) return false;
      if (options.element.value === nextValue) return false;
      const previousValue = options.element.value;
      options.element.value = nextValue;
      try {
        return syncValue(origin);
      } catch (error) {
        options.element.value = previousValue;
        throw error;
      }
    },
    focusSelection(selection) {
      if (disposed || !bridge.readSnapshot().active) return false;
      const normalized = normalizeTextareaSelection(options.element.value, selection);
      if (!bridge.focusSelection(normalized).applied) return false;
      options.element.setSelectionRange(
        normalized.startUtf16,
        normalized.endUtf16,
        normalized.direction,
      );
      options.element.focus();
      return true;
    },
    focus() {
      if (!disposed && bridge.readSnapshot().active) options.element.focus();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      options.element.removeEventListener("input", onInput);
      options.element.removeEventListener("compositionstart", onCompositionStart);
      options.element.removeEventListener("compositionend", onCompositionEnd);
      options.element.removeEventListener("select", onSelection);
      options.element.removeEventListener("keyup", onSelection);
      options.element.removeEventListener("mouseup", onSelection);
      options.element.removeEventListener("scroll", onScroll);
      options.element.removeEventListener("focus", onFocus);
      options.element.removeEventListener("blur", onBlur);
      options.element.removeEventListener("keydown", onKeyDown);
      options.element.removeEventListener("contextmenu", onContextMenu);
      bridge.dispose();
    },
  };
}
