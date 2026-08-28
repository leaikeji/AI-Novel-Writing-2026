import { history, historyKeymap, redo, undo } from "@codemirror/commands";
import {
  Annotation,
  EditorSelection as CodeMirrorSelection,
  EditorState,
  StateEffect,
  StateField,
  Transaction,
  type ChangeSet,
  type Extension,
} from "@codemirror/state";
import {
  Decoration,
  EditorView,
  keymap,
  lineNumbers,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";

import {
  assertWellFormedUtf16,
  createNarrationEditorBridge,
  type CreateNarrationEditorBridgeOptions,
  type DocumentLease,
  type EditorChangeOrigin,
  type EditorTextChange,
  type NarrationEditorBridge,
  type NarrationEditorPresentationEvent,
  type NarrationEditorSelection,
  type OnEditorDocChanged,
  type TransactionMappingReport,
  type Utf16Range,
} from "./editor-bridge";
import type { AuthorFollowInterruption } from "./segment-follow";
import {
  isNarrationSeekKeyboardCommand,
  type NarrationKeyboardEventLike,
  type OnEditorParagraphContextMenu,
  type OnEditorParagraphPlaybackCommand,
} from "./paragraph-gutter";
import {
  clearEditorParagraphGutter,
  replaceEditorParagraphGutter,
  type EditorParagraphGutterEntry,
} from "./editor-paragraph-gutter";


export interface CodeMirrorNarrationAdapterOptions {
  readonly parent: HTMLElement;
  readonly lease: DocumentLease;
  readonly initialValue: string;
  readonly currentContentHash: string;
  readonly selection?: NarrationEditorSelection;
  readonly onDocChanged: OnEditorDocChanged;
  readonly isLeaseCurrent: (lease: DocumentLease) => boolean;
  readonly ariaLabel?: string;
  readonly onFocusChange?: (focused: boolean) => void;
  readonly onAuthorInteraction?: (interruption: AuthorFollowInterruption) => void;
  readonly onParagraphPlaybackCommand?: OnEditorParagraphPlaybackCommand;
  readonly onParagraphContextMenu?: OnEditorParagraphContextMenu;
  readonly extensions?: readonly Extension[];
}


export interface CodeMirrorNarrationAdapter {
  readonly bridge: NarrationEditorBridge;
  readonly view: EditorView;
  readValue(): string;
  readSelection(): NarrationEditorSelection;
  setValue(nextValue: string, origin: EditorChangeOrigin): boolean;
  focusSelection(selection: NarrationEditorSelection): boolean;
  focus(): void;
  undo(): boolean;
  redo(): boolean;
  setParagraphGutter(entries: readonly EditorParagraphGutterEntry[]): boolean;
  dispose(): void;
}


export interface CodeMirrorBridgeUpdate {
  readonly changes: ChangeSet;
  readonly state: EditorState;
  readonly transactions: readonly Transaction[];
  readonly docChanged: boolean;
  readonly selectionSet: boolean;
  readonly composing: boolean;
}


const narrationChangeOrigin = Annotation.define<EditorChangeOrigin>();
const narrationPresentation = Annotation.define<boolean>();


export function dispatchCodeMirrorKeyboardPlaybackCommand(
  event: NarrationKeyboardEventLike,
  positionUtf16: number,
  onCommand?: OnEditorParagraphPlaybackCommand,
): boolean {
  if (!onCommand || !isNarrationSeekKeyboardCommand(event)) return false;
  return onCommand({
    source: "keyboard",
    event,
    lookup: { positionUtf16 },
  });
}


export function dispatchCodeMirrorContextPlaybackCommand(
  positionUtf16: number,
  composing: boolean,
  onCommand?: OnEditorParagraphPlaybackCommand,
): boolean {
  if (!onCommand || composing) return false;
  return onCommand({
    source: "context-menu",
    lookup: { positionUtf16 },
  });
}


const setCodeMirrorNarrationRange = StateEffect.define<Utf16Range | null>({
  map(value, changes) {
    if (!value) return null;
    return {
      startUtf16: changes.mapPos(value.startUtf16, 1),
      endUtf16: changes.mapPos(value.endUtf16, -1),
    };
  },
});


const codeMirrorNarrationField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    let next = value.map(transaction.changes);
    for (const effect of transaction.effects) {
      if (!effect.is(setCodeMirrorNarrationRange)) continue;
      next = effect.value
        ? Decoration.set([
          Decoration.mark({
            class: "anw-narration-current-segment",
            attributes: { "data-narration-current": "true" },
          }).range(effect.value.startUtf16, effect.value.endUtf16),
        ])
        : Decoration.none;
    }
    return next;
  },
  provide: (field) => EditorView.decorations.from(field),
});


export function selectionFromCodeMirror(state: EditorState): NarrationEditorSelection {
  const selection = state.selection.main;
  return {
    startUtf16: selection.from,
    endUtf16: selection.to,
    direction: selection.empty
      ? "none"
      : selection.anchor > selection.head ? "backward" : "forward",
  };
}


function isNarrationPresentation(
  transactions: readonly Transaction[],
): boolean {
  return transactions.some((transaction) => transaction.annotation(narrationPresentation) === true);
}


export function codeMirrorAuthorInteraction(
  update: CodeMirrorBridgeUpdate,
): AuthorFollowInterruption | null {
  if (isNarrationPresentation(update.transactions)) return null;
  if (update.docChanged) {
    const origin = codeMirrorTransactionOrigin(update.transactions, update.composing);
    return origin === "composition" ? "composition" : "input";
  }
  if (!update.selectionSet) return null;
  return update.state.selection.main.empty ? "caret-move" : "selection";
}


function selectionToCodeMirror(selection: NarrationEditorSelection): CodeMirrorSelection {
  const anchor = selection.direction === "backward"
    ? selection.endUtf16
    : selection.startUtf16;
  const head = selection.direction === "backward"
    ? selection.startUtf16
    : selection.endUtf16;
  return CodeMirrorSelection.single(anchor, head);
}


export function codeMirrorChangesToEditorChanges(changes: ChangeSet): readonly EditorTextChange[] {
  const result: EditorTextChange[] = [];
  changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
    result.push({
      startUtf16: fromA,
      endUtf16: toA,
      insertedText: inserted.toString(),
    });
  });
  return result;
}


export function codeMirrorTransactionOrigin(
  transactions: readonly Transaction[],
  composing: boolean,
): EditorChangeOrigin {
  for (let index = transactions.length - 1; index >= 0; index -= 1) {
    const explicit = transactions[index].annotation(narrationChangeOrigin);
    if (explicit) return explicit;
  }
  if (composing) return "composition";
  for (let index = transactions.length - 1; index >= 0; index -= 1) {
    const userEvent = transactions[index].annotation(Transaction.userEvent);
    if (!userEvent) continue;
    if (userEvent === "undo" || userEvent.startsWith("undo.")) return "undo";
    if (userEvent === "redo" || userEvent.startsWith("redo.")) return "redo";
    if (userEvent.includes("compose")) return "composition";
  }
  return "input";
}


export function applyCodeMirrorUpdateToBridge(
  bridge: NarrationEditorBridge,
  update: CodeMirrorBridgeUpdate,
): TransactionMappingReport | null {
  const before = bridge.readSnapshot();
  const origin = codeMirrorTransactionOrigin(
    update.transactions,
    update.composing || before.composing,
  );
  if ((update.composing || origin === "composition") && !before.composing) {
    bridge.beginComposition();
  }

  let report: TransactionMappingReport | null = null;
  if (update.docChanged) {
    report = bridge.applyTransaction({
      changes: codeMirrorChangesToEditorChanges(update.changes),
      selectionAfter: selectionFromCodeMirror(update.state),
      origin,
    });
  } else if (update.selectionSet) {
    bridge.setSelection(selectionFromCodeMirror(update.state));
  }

  if (!update.composing && bridge.readSnapshot().composing) {
    bridge.endComposition();
  }
  return report;
}


export function createCodeMirrorNarrationExtensions(
  bridge: NarrationEditorBridge,
  options: Pick<
    CodeMirrorNarrationAdapterOptions,
    | "ariaLabel"
    | "onFocusChange"
    | "onAuthorInteraction"
    | "onParagraphContextMenu"
    | "onParagraphPlaybackCommand"
  > = {},
): readonly Extension[] {
  const noteAuthorInteraction = (interruption: AuthorFollowInterruption) => {
    if (!bridge.readSnapshot().active) return;
    bridge.noteManualScroll();
    options.onAuthorInteraction?.(interruption);
  };
  return [
    codeMirrorNarrationField,
    history(),
    keymap.of(historyKeymap),
    EditorView.updateListener.of((update: ViewUpdate) => {
      const bridgeUpdate: CodeMirrorBridgeUpdate = {
        changes: update.changes,
        state: update.state,
        transactions: update.transactions,
        docChanged: update.docChanged,
        selectionSet: update.selectionSet,
        composing: update.view.composing,
      };
      applyCodeMirrorUpdateToBridge(bridge, bridgeUpdate);
      const interaction = codeMirrorAuthorInteraction(bridgeUpdate);
      if (interaction) noteAuthorInteraction(interaction);
      if (update.focusChanged) options.onFocusChange?.(update.view.hasFocus);
    }),
    EditorView.domEventHandlers({
      keydown(event, view) {
        const commandEvent: NarrationKeyboardEventLike = {
          key: event.key,
          altKey: event.altKey,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          shiftKey: event.shiftKey,
          repeat: event.repeat,
          isComposing: event.isComposing || view.composing,
        };
        const handled = dispatchCodeMirrorKeyboardPlaybackCommand(
          commandEvent,
          view.state.selection.main.head,
          options.onParagraphPlaybackCommand,
        );
        if (!handled) return false;
        event.preventDefault();
        event.stopPropagation();
        return true;
      },
      contextmenu(event, view) {
        const positionUtf16 = view.posAtCoords({ x: event.clientX, y: event.clientY })
          ?? view.state.selection.main.head;
        const handled = view.composing
          ? false
          : options.onParagraphContextMenu
            ? options.onParagraphContextMenu({
                lookup: { positionUtf16 },
                clientX: event.clientX,
                clientY: event.clientY,
              })
            : dispatchCodeMirrorContextPlaybackCommand(
                positionUtf16,
                false,
                options.onParagraphPlaybackCommand,
              );
        if (!handled) return false;
        event.preventDefault();
        event.stopPropagation();
        return true;
      },
      compositionstart() {
        bridge.beginComposition();
        noteAuthorInteraction("composition");
        return false;
      },
      compositionend() {
        queueMicrotask(() => bridge.endComposition());
        return false;
      },
    }),
    lineNumbers(),
    EditorView.lineWrapping,
    ...(options.ariaLabel
      ? [EditorView.contentAttributes.of({ "aria-label": options.ariaLabel })]
      : []),
  ];
}


export function createCodeMirrorNarrationState(
  text: string,
  bridge: NarrationEditorBridge,
  extensions: readonly Extension[] = [],
  interactionOptions: Pick<
    CodeMirrorNarrationAdapterOptions,
    | "ariaLabel"
    | "onFocusChange"
    | "onAuthorInteraction"
    | "onParagraphContextMenu"
    | "onParagraphPlaybackCommand"
  > = {},
): EditorState {
  const snapshot = bridge.readSnapshot();
  if (snapshot.text !== text) {
    throw new Error("CodeMirror initial text must equal the NarrationEditorBridge snapshot");
  }
  return EditorState.create({
    doc: text,
    selection: selectionToCodeMirror(snapshot.selection),
    extensions: [
      ...createCodeMirrorNarrationExtensions(bridge, interactionOptions),
      ...extensions,
    ],
  });
}


export function codeMirrorNarrationEffect(
  range: Utf16Range | null,
): StateEffect<Utf16Range | null> {
  return setCodeMirrorNarrationRange.of(range);
}


export function codeMirrorNarrationRanges(state: EditorState): readonly Utf16Range[] {
  const decorations = state.field(codeMirrorNarrationField, false);
  if (!decorations) return [];
  const ranges: Utf16Range[] = [];
  decorations.between(0, state.doc.length, (from, to) => {
    ranges.push({ startUtf16: from, endUtf16: to });
  });
  return ranges;
}


export function codeMirrorOriginAnnotation(
  origin: EditorChangeOrigin,
): Annotation<EditorChangeOrigin> {
  return narrationChangeOrigin.of(origin);
}


export function codeMirrorNarrationPresentationAnnotation(): Annotation<boolean> {
  return narrationPresentation.of(true);
}


export function createCodeMirrorNarrationAdapter(
  options: CodeMirrorNarrationAdapterOptions,
): CodeMirrorNarrationAdapter {
  const bridgeOptions: CreateNarrationEditorBridgeOptions = {
    kind: "codemirror6",
    lease: options.lease,
    text: options.initialValue,
    currentContentHash: options.currentContentHash,
    selection: options.selection,
    onDocChanged: options.onDocChanged,
    isLeaseCurrent: options.isLeaseCurrent,
  };
  const bridge = createNarrationEditorBridge(bridgeOptions);
  const originalChildren = new Set(Array.from(options.parent.childNodes));
  let view: EditorView;
  try {
    const state = createCodeMirrorNarrationState(
      options.initialValue,
      bridge,
      options.extensions,
      options,
    );
    view = new EditorView({ state, parent: options.parent });
  } catch (error) {
    bridge.dispose();
    for (const child of Array.from(options.parent.childNodes)) {
      if (!originalChildren.has(child)) options.parent.removeChild(child);
    }
    throw error;
  }
  let disposed = false;
  let presentationScheduled = false;
  let presentationQueue: NarrationEditorPresentationEvent[] = [];
  let suppressManualScroll = false;
  let scrollReleaseHandle: number | null = null;

  const releaseProgrammaticScroll = () => {
    suppressManualScroll = false;
    scrollReleaseHandle = null;
  };

  const applyPresentation = (event: NarrationEditorPresentationEvent) => {
    if (disposed || !bridge.readSnapshot().active) return;
    if (event.type === "clear-current-segment") {
      view.dispatch({
        effects: setCodeMirrorNarrationRange.of(null),
        annotations: narrationPresentation.of(true),
      });
      return;
    }
    if (event.type === "focus-selection") {
      const selection = selectionToCodeMirror(event.selection);
      if (!view.state.selection.eq(selection)) {
        view.dispatch({
          selection,
          annotations: narrationPresentation.of(true),
        });
      }
      view.focus();
      return;
    }
    const mapping = bridge.mappingFor(event.segmentId, {
      lease: bridge.lease,
      editionId: bridge.readSnapshot().edition?.editionId,
    });
    if (mapping?.state !== "mapped") return;
    if (event.type === "current-segment") {
      view.dispatch({
        effects: setCodeMirrorNarrationRange.of(mapping.currentRange),
        annotations: narrationPresentation.of(true),
      });
      return;
    }
    suppressManualScroll = true;
    view.dispatch({
      effects: EditorView.scrollIntoView(mapping.currentRange.startUtf16, { y: "center" }),
      annotations: narrationPresentation.of(true),
    });
    if (typeof requestAnimationFrame === "function") {
      scrollReleaseHandle = requestAnimationFrame(releaseProgrammaticScroll);
    } else {
      queueMicrotask(releaseProgrammaticScroll);
    }
  };

  const unsubscribePresentation = bridge.registerPresentationListener((event) => {
    presentationQueue.push(event);
    if (presentationScheduled) return;
    presentationScheduled = true;
    queueMicrotask(() => {
      presentationScheduled = false;
      const events = presentationQueue;
      presentationQueue = [];
      for (const queued of events) applyPresentation(queued);
    });
  });

  const onScroll = () => {
    if (!disposed && !suppressManualScroll) {
      bridge.noteManualScroll();
      options.onAuthorInteraction?.("manual-scroll");
    }
  };
  view.scrollDOM.addEventListener("scroll", onScroll, { passive: true });

  return {
    bridge,
    view,
    readValue() {
      return view.state.doc.toString();
    },
    readSelection() {
      return selectionFromCodeMirror(view.state);
    },
    setValue(nextValue, origin) {
      if (disposed || !bridge.readSnapshot().active) return false;
      if (view.state.doc.toString() === nextValue) return false;
      assertWellFormedUtf16(nextValue, "CodeMirror nextValue");
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: nextValue },
        annotations: narrationChangeOrigin.of(origin),
      });
      return true;
    },
    focusSelection(selection) {
      if (disposed || !bridge.readSnapshot().active) return false;
      const focused = bridge.focusSelection(selection);
      if (!focused.applied) return false;
      const codeMirrorSelection = selectionToCodeMirror(selection);
      if (!view.state.selection.eq(codeMirrorSelection)) {
        view.dispatch({
          selection: codeMirrorSelection,
          annotations: narrationPresentation.of(true),
        });
      }
      view.focus();
      return true;
    },
    focus() {
      if (!disposed && bridge.readSnapshot().active) view.focus();
    },
    undo() {
      return !disposed && bridge.readSnapshot().active && undo(view);
    },
    redo() {
      return !disposed && bridge.readSnapshot().active && redo(view);
    },
    setParagraphGutter(entries) {
      if (disposed || !bridge.readSnapshot().active) return false;
      view.dispatch({
        effects: entries.length > 0
          ? replaceEditorParagraphGutter(entries)
          : clearEditorParagraphGutter(),
        annotations: narrationPresentation.of(true),
      });
      return true;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      presentationQueue = [];
      unsubscribePresentation();
      view.scrollDOM.removeEventListener("scroll", onScroll);
      if (scrollReleaseHandle !== null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(scrollReleaseHandle);
      }
      bridge.dispose();
      view.destroy();
    },
  };
}
