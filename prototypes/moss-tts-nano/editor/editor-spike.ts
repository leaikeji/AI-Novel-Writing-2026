import { history, historyKeymap, redo, undo } from "@codemirror/commands";
import {
  EditorSelection as CodeMirrorSelection,
  EditorState,
  StateEffect,
  StateField,
  type Extension,
} from "@codemirror/state";
import {
  Decoration,
  EditorView,
  keymap,
  lineNumbers,
  type DecorationSet,
} from "@codemirror/view";


export interface Utf16Range {
  startUtf16: number;
  endUtf16: number;
}


export interface NarrationEditorSelection extends Utf16Range {
  direction: "forward" | "backward" | "none";
}


export interface NarrationSourceSegment {
  segmentId: string;
  sourceBlockKey: string;
  sourceRange: Utf16Range;
  sourceText: string;
  prefixAnchor?: string;
  suffixAnchor?: string;
}


export type SegmentInvalidationReason =
  | "transaction_intersection"
  | "boundary_adjacent"
  | "anchor_mismatch"
  | "reload_diverged";


export type SegmentMapping =
  | {
    segmentId: string;
    sourceBlockKey: string;
    state: "mapped";
    currentRange: Utf16Range;
  }
  | {
    segmentId: string;
    sourceBlockKey: string;
    state: "invalidated";
    currentRange: null;
    reason: SegmentInvalidationReason;
  };


export interface NarrationEditorSnapshot {
  text: string;
  selection: NarrationEditorSelection;
  composing: boolean;
  autoFollowPaused: boolean;
  currentSegmentId: string | null;
  exactEditionText: boolean;
}


export interface EditorTextChange extends Utf16Range {
  insertedText: string;
}


export interface NarrationEditorTransaction {
  changes: readonly EditorTextChange[];
  selectionAfter?: NarrationEditorSelection;
  origin: "input" | "composition" | "undo" | "redo" | "external";
}


export interface TransactionMappingReport {
  text: string;
  mappedSegmentIds: readonly string[];
  invalidated: Readonly<Record<string, SegmentInvalidationReason>>;
  invalidatedSourceBlockKeys: readonly string[];
}


export type PlaybackIntentSource =
  | "editor-click"
  | "gutter"
  | "command"
  | "readonly-segment";


export interface PlaybackLookup {
  segmentId?: string;
  sourceBlockKey?: string;
  range?: Utf16Range;
  positionUtf16?: number;
}


export interface PlaybackIntent {
  source: Exclude<PlaybackIntentSource, "editor-click">;
  segmentId: string;
  sourceBlockKey: string;
}


export type PlaybackIntentResult =
  | { accepted: true; intent: PlaybackIntent }
  | {
    accepted: false;
    reason: "editor_click_moves_caret_only" | "unmapped_target" | "missing_target";
  };


export type FollowResult =
  | { applied: true; segmentId: string }
  | {
    applied: false;
    reason: "composition" | "manual_scroll" | "unmapped_segment";
  };


export interface NarrationEditorBridge {
  readSnapshot(): NarrationEditorSnapshot;
  setSelection(selection: NarrationEditorSelection): void;
  beginComposition(): void;
  endComposition(): void;
  resolvePlaybackTarget(lookup: PlaybackLookup): string | null;
  markCurrentSegment(segmentId: string): FollowResult;
  scrollCurrentSegmentIntoView(): FollowResult;
  clearCurrentSegment(): void;
  noteManualScroll(): void;
  resumeAutoFollow(): void;
  registerPlaybackIntent(listener: (intent: PlaybackIntent) => void): () => void;
  requestPlayback(source: PlaybackIntentSource, lookup: PlaybackLookup): PlaybackIntentResult;
  applyTransaction(transaction: NarrationEditorTransaction): TransactionMappingReport;
  resetAfterPageReload(input: { currentText: string; currentContentHash: string }): void;
  mappingFor(segmentId: string): SegmentMapping | null;
}


export interface PrototypeNarrationEditorBridgeOptions {
  text: string;
  editionContentHash: string;
  currentContentHash: string;
  segments: readonly NarrationSourceSegment[];
  selection?: NarrationEditorSelection;
}


export interface CodeMirrorDocumentChange {
  text: string;
  composing: boolean;
  transactionCount: number;
}


export interface CodeMirrorPrototypeHandle {
  readonly view: EditorView;
  highlight(range: Utf16Range | null): void;
  undo(): boolean;
  redo(): boolean;
  destroy(): void;
}


export const TEXTAREA_SAFE_FALLBACK = Object.freeze({
  editableDecoration: false,
  editableGutterSeek: false,
  ordinaryClickSeeks: false,
  allowedSeekSurfaces: ["readonly-segment", "paragraph-list", "explicit-command"] as const,
  divergedCopyPresentation: ["player-subtitle", "immutable-edition-drawer"] as const,
  requiredRecoveryAction: "update-narration" as const,
});


interface SourceBlockRange extends Utf16Range {
  sourceBlockKey: string;
}


const BOUNDARY_SENSITIVE = /[\n\r“”「」『』"'：:。！？!?；;，,—…]/u;


function copyRange(range: Utf16Range): Utf16Range {
  return { startUtf16: range.startUtf16, endUtf16: range.endUtf16 };
}


function copySelection(selection: NarrationEditorSelection): NarrationEditorSelection {
  return { ...copyRange(selection), direction: selection.direction };
}


function assertOffset(text: string, value: number, label: string): void {
  if (!Number.isInteger(value) || value < 0 || value > text.length) {
    throw new RangeError(`${label} must be an integer UTF-16 offset within the document`);
  }
  if (
    value > 0
    && value < text.length
    && text.charCodeAt(value - 1) >= 0xd800
    && text.charCodeAt(value - 1) <= 0xdbff
    && text.charCodeAt(value) >= 0xdc00
    && text.charCodeAt(value) <= 0xdfff
  ) {
    throw new RangeError(`${label} must not split a UTF-16 surrogate pair`);
  }
}


function assertRange(text: string, range: Utf16Range, label: string): void {
  assertOffset(text, range.startUtf16, `${label}.startUtf16`);
  assertOffset(text, range.endUtf16, `${label}.endUtf16`);
  if (range.endUtf16 < range.startUtf16) {
    throw new RangeError(`${label}.endUtf16 must be greater than or equal to startUtf16`);
  }
}


function rangesTouch(change: EditorTextChange, range: Utf16Range): boolean {
  if (change.startUtf16 === change.endUtf16) {
    return change.startUtf16 >= range.startUtf16 && change.startUtf16 <= range.endUtf16;
  }
  return change.startUtf16 <= range.endUtf16 && change.endUtf16 >= range.startUtf16;
}


function rangesOverlap(left: Utf16Range, right: Utf16Range): boolean {
  return left.startUtf16 < right.endUtf16 && right.startUtf16 < left.endUtf16;
}


function applyTextChanges(text: string, changes: readonly EditorTextChange[]): string {
  let result = text;
  for (let index = changes.length - 1; index >= 0; index -= 1) {
    const change = changes[index];
    result = `${result.slice(0, change.startUtf16)}${change.insertedText}${result.slice(change.endUtf16)}`;
  }
  return result;
}


function changeDelta(change: EditorTextChange): number {
  return change.insertedText.length - (change.endUtf16 - change.startUtf16);
}


function mapUnaffectedRange(
  range: Utf16Range,
  changes: readonly EditorTextChange[],
): Utf16Range {
  let delta = 0;
  for (const change of changes) {
    if (change.endUtf16 < range.startUtf16) delta += changeDelta(change);
  }
  return {
    startUtf16: range.startUtf16 + delta,
    endUtf16: range.endUtf16 + delta,
  };
}


function mapSelectionPosition(
  position: number,
  changes: readonly EditorTextChange[],
  association: -1 | 1,
): number {
  let delta = 0;
  for (const change of changes) {
    const insertedEnd = change.startUtf16 + delta + change.insertedText.length;
    if (position < change.startUtf16) break;
    if (position > change.endUtf16) {
      delta += changeDelta(change);
      continue;
    }
    if (position === change.startUtf16 && association < 0) {
      return change.startUtf16 + delta;
    }
    return insertedEnd;
  }
  return position + delta;
}


function buildSourceBlocks(segments: readonly NarrationSourceSegment[]): SourceBlockRange[] {
  const blocks = new Map<string, SourceBlockRange>();
  for (const segment of segments) {
    const existing = blocks.get(segment.sourceBlockKey);
    if (existing) {
      existing.startUtf16 = Math.min(existing.startUtf16, segment.sourceRange.startUtf16);
      existing.endUtf16 = Math.max(existing.endUtf16, segment.sourceRange.endUtf16);
    } else {
      blocks.set(segment.sourceBlockKey, {
        sourceBlockKey: segment.sourceBlockKey,
        ...copyRange(segment.sourceRange),
      });
    }
  }
  return [...blocks.values()].sort((left, right) => (
    left.startUtf16 - right.startUtf16 || left.sourceBlockKey.localeCompare(right.sourceBlockKey)
  ));
}


function assertSegments(text: string, segments: readonly NarrationSourceSegment[]): void {
  const ids = new Set<string>();
  for (const segment of segments) {
    if (ids.has(segment.segmentId)) throw new Error(`duplicate segmentId: ${segment.segmentId}`);
    ids.add(segment.segmentId);
    assertRange(text, segment.sourceRange, `segment ${segment.segmentId}`);
    if (segment.sourceRange.startUtf16 === segment.sourceRange.endUtf16) {
      throw new RangeError(`segment ${segment.segmentId} must define a non-empty range`);
    }
    if (text.slice(segment.sourceRange.startUtf16, segment.sourceRange.endUtf16) !== segment.sourceText) {
      throw new Error(`segment ${segment.segmentId} sourceText does not match its UTF-16 range`);
    }
  }
}


function mappingCopy(mapping: SegmentMapping): SegmentMapping {
  return mapping.state === "mapped"
    ? { ...mapping, currentRange: copyRange(mapping.currentRange) }
    : { ...mapping };
}


export class PrototypeNarrationEditorBridge implements NarrationEditorBridge {
  private text: string;
  private readonly editionContentHash: string;
  private currentContentHash: string;
  private readonly segments: readonly NarrationSourceSegment[];
  private readonly segmentById: ReadonlyMap<string, NarrationSourceSegment>;
  private readonly sourceBlocks: readonly SourceBlockRange[];
  private mappings = new Map<string, SegmentMapping>();
  private selection: NarrationEditorSelection;
  private composing = false;
  private autoFollowPaused = false;
  private currentSegmentId: string | null = null;
  private lastScrollRequest: string | null = null;
  private readonly intentListeners = new Set<(intent: PlaybackIntent) => void>();

  constructor(options: PrototypeNarrationEditorBridgeOptions) {
    assertSegments(options.text, options.segments);
    this.text = options.text;
    this.editionContentHash = options.editionContentHash;
    this.currentContentHash = options.currentContentHash;
    this.segments = options.segments.map((segment) => ({
      ...segment,
      sourceRange: copyRange(segment.sourceRange),
    }));
    this.segmentById = new Map(this.segments.map((segment) => [segment.segmentId, segment]));
    this.sourceBlocks = buildSourceBlocks(this.segments);
    this.selection = options.selection
      ? copySelection(options.selection)
      : { startUtf16: 0, endUtf16: 0, direction: "none" };
    assertRange(this.text, this.selection, "selection");
    this.rebindExactRevisionOrInvalidate();
  }

  readSnapshot(): NarrationEditorSnapshot {
    return {
      text: this.text,
      selection: copySelection(this.selection),
      composing: this.composing,
      autoFollowPaused: this.autoFollowPaused,
      currentSegmentId: this.currentSegmentId,
      exactEditionText: this.currentContentHash === this.editionContentHash,
    };
  }

  setSelection(selection: NarrationEditorSelection): void {
    assertRange(this.text, selection, "selection");
    this.selection = copySelection(selection);
  }

  beginComposition(): void {
    this.composing = true;
  }

  endComposition(): void {
    this.composing = false;
  }

  resolvePlaybackTarget(lookup: PlaybackLookup): string | null {
    if (lookup.segmentId) {
      return this.isMapped(lookup.segmentId) ? lookup.segmentId : null;
    }
    const candidates = this.segments
      .filter((segment) => !lookup.sourceBlockKey || segment.sourceBlockKey === lookup.sourceBlockKey)
      .map((segment) => ({ segment, mapping: this.mappings.get(segment.segmentId) }))
      .filter((candidate): candidate is {
        segment: NarrationSourceSegment;
        mapping: Extract<SegmentMapping, { state: "mapped" }>;
      } => candidate.mapping?.state === "mapped")
      .sort((left, right) => left.mapping.currentRange.startUtf16 - right.mapping.currentRange.startUtf16);

    if (lookup.range) {
      const lookupRange = lookup.range;
      assertRange(this.text, lookupRange, "playback lookup range");
      return candidates.find(({ mapping }) => (
        rangesOverlap(mapping.currentRange, lookupRange)
        || (
          lookupRange.startUtf16 === lookupRange.endUtf16
          && lookupRange.startUtf16 >= mapping.currentRange.startUtf16
          && lookupRange.startUtf16 <= mapping.currentRange.endUtf16
        )
      ))?.segment.segmentId ?? null;
    }
    if (lookup.positionUtf16 !== undefined) {
      const positionUtf16 = lookup.positionUtf16;
      assertOffset(this.text, positionUtf16, "playback lookup positionUtf16");
      const containing = candidates.find(({ mapping }) => (
        positionUtf16 >= mapping.currentRange.startUtf16
        && positionUtf16 <= mapping.currentRange.endUtf16
      ));
      if (containing) return containing.segment.segmentId;
      return candidates.find(({ mapping }) => mapping.currentRange.startUtf16 > positionUtf16)
        ?.segment.segmentId ?? candidates.at(-1)?.segment.segmentId ?? null;
    }
    return candidates[0]?.segment.segmentId ?? null;
  }

  markCurrentSegment(segmentId: string): FollowResult {
    if (this.composing) return { applied: false, reason: "composition" };
    if (!this.isMapped(segmentId)) return { applied: false, reason: "unmapped_segment" };
    this.currentSegmentId = segmentId;
    return { applied: true, segmentId };
  }

  scrollCurrentSegmentIntoView(): FollowResult {
    if (this.composing) return { applied: false, reason: "composition" };
    if (this.autoFollowPaused) return { applied: false, reason: "manual_scroll" };
    if (!this.currentSegmentId || !this.isMapped(this.currentSegmentId)) {
      return { applied: false, reason: "unmapped_segment" };
    }
    this.lastScrollRequest = this.currentSegmentId;
    return { applied: true, segmentId: this.currentSegmentId };
  }

  clearCurrentSegment(): void {
    this.currentSegmentId = null;
    this.lastScrollRequest = null;
  }

  noteManualScroll(): void {
    this.autoFollowPaused = true;
  }

  resumeAutoFollow(): void {
    this.autoFollowPaused = false;
  }

  registerPlaybackIntent(listener: (intent: PlaybackIntent) => void): () => void {
    this.intentListeners.add(listener);
    return () => this.intentListeners.delete(listener);
  }

  requestPlayback(source: PlaybackIntentSource, lookup: PlaybackLookup): PlaybackIntentResult {
    if (source === "editor-click") {
      return { accepted: false, reason: "editor_click_moves_caret_only" };
    }
    let segmentId: string | null = null;
    if (source === "readonly-segment" && lookup.segmentId && this.segmentById.has(lookup.segmentId)) {
      // A click in the explicitly labelled immutable old-edition view is
      // allowed even when that segment no longer maps into the working copy.
      segmentId = lookup.segmentId;
    } else {
      segmentId = this.resolvePlaybackTarget(lookup);
    }
    if (!segmentId) {
      return {
        accepted: false,
        reason: Object.keys(lookup).length === 0 ? "missing_target" : "unmapped_target",
      };
    }
    const segment = this.segmentById.get(segmentId);
    if (!segment) return { accepted: false, reason: "missing_target" };
    const intent: PlaybackIntent = {
      source,
      segmentId,
      sourceBlockKey: segment.sourceBlockKey,
    };
    for (const listener of this.intentListeners) listener(intent);
    return { accepted: true, intent };
  }

  applyTransaction(transaction: NarrationEditorTransaction): TransactionMappingReport {
    const changes = [...transaction.changes].sort((left, right) => (
      left.startUtf16 - right.startUtf16 || left.endUtf16 - right.endUtf16
    ));
    let previousEnd = -1;
    for (const [index, change] of changes.entries()) {
      assertRange(this.text, change, `changes[${index}]`);
      if (change.startUtf16 < previousEnd) {
        throw new RangeError("transaction changes must not overlap");
      }
      previousEnd = change.endUtf16;
    }

    const invalidatedBlocks = new Set<string>();
    const directInvalidatedSegments = new Set<string>();
    const boundarySensitiveBlocks = new Set<string>();
    for (const segment of this.segments) {
      const mapping = this.mappings.get(segment.segmentId);
      if (mapping?.state !== "mapped") continue;
      for (const change of changes) {
        if (!rangesTouch(change, mapping.currentRange)) continue;
        directInvalidatedSegments.add(segment.segmentId);
        invalidatedBlocks.add(segment.sourceBlockKey);
        const removedText = this.text.slice(change.startUtf16, change.endUtf16);
        if (
          BOUNDARY_SENSITIVE.test(change.insertedText)
          || BOUNDARY_SENSITIVE.test(removedText)
          || change.startUtf16 === mapping.currentRange.startUtf16
          || change.startUtf16 === mapping.currentRange.endUtf16
          || change.endUtf16 === mapping.currentRange.startUtf16
          || change.endUtf16 === mapping.currentRange.endUtf16
        ) {
          boundarySensitiveBlocks.add(segment.sourceBlockKey);
        }
      }
    }

    for (const blockKey of boundarySensitiveBlocks) {
      const index = this.sourceBlocks.findIndex((block) => block.sourceBlockKey === blockKey);
      if (index > 0) invalidatedBlocks.add(this.sourceBlocks[index - 1].sourceBlockKey);
      if (index >= 0 && index + 1 < this.sourceBlocks.length) {
        invalidatedBlocks.add(this.sourceBlocks[index + 1].sourceBlockKey);
      }
    }

    const nextText = applyTextChanges(this.text, changes);
    const invalidated: Record<string, SegmentInvalidationReason> = {};
    for (const segment of this.segments) {
      const mapping = this.mappings.get(segment.segmentId);
      if (!mapping || mapping.state === "invalidated") continue;
      if (invalidatedBlocks.has(segment.sourceBlockKey)) {
        const reason: SegmentInvalidationReason = directInvalidatedSegments.has(segment.segmentId)
          ? "transaction_intersection"
          : "boundary_adjacent";
        this.mappings.set(segment.segmentId, {
          segmentId: segment.segmentId,
          sourceBlockKey: segment.sourceBlockKey,
          state: "invalidated",
          currentRange: null,
          reason,
        });
        invalidated[segment.segmentId] = reason;
        continue;
      }
      const currentRange = mapUnaffectedRange(mapping.currentRange, changes);
      const matchesText = nextText.slice(currentRange.startUtf16, currentRange.endUtf16) === segment.sourceText;
      const matchesPrefix = segment.prefixAnchor === undefined
        || nextText.slice(Math.max(0, currentRange.startUtf16 - segment.prefixAnchor.length), currentRange.startUtf16)
          === segment.prefixAnchor;
      const matchesSuffix = segment.suffixAnchor === undefined
        || nextText.slice(currentRange.endUtf16, currentRange.endUtf16 + segment.suffixAnchor.length)
          === segment.suffixAnchor;
      if (!matchesText || !matchesPrefix || !matchesSuffix) {
        this.mappings.set(segment.segmentId, {
          segmentId: segment.segmentId,
          sourceBlockKey: segment.sourceBlockKey,
          state: "invalidated",
          currentRange: null,
          reason: "anchor_mismatch",
        });
        invalidated[segment.segmentId] = "anchor_mismatch";
      } else {
        this.mappings.set(segment.segmentId, {
          segmentId: segment.segmentId,
          sourceBlockKey: segment.sourceBlockKey,
          state: "mapped",
          currentRange,
        });
      }
    }

    this.text = nextText;
    if (changes.length > 0) {
      this.currentContentHash = `active-session-diverged:${transaction.origin}`;
    }
    if (transaction.selectionAfter) {
      assertRange(this.text, transaction.selectionAfter, "selectionAfter");
      this.selection = copySelection(transaction.selectionAfter);
    } else if (changes.length > 0) {
      this.selection = {
        startUtf16: mapSelectionPosition(this.selection.startUtf16, changes, -1),
        endUtf16: mapSelectionPosition(this.selection.endUtf16, changes, 1),
        direction: this.selection.direction,
      };
    }
    if (this.currentSegmentId && !this.isMapped(this.currentSegmentId)) this.clearCurrentSegment();

    return {
      text: this.text,
      mappedSegmentIds: this.segments
        .map((segment) => segment.segmentId)
        .filter((segmentId) => this.isMapped(segmentId)),
      invalidated,
      invalidatedSourceBlockKeys: [...invalidatedBlocks],
    };
  }

  resetAfterPageReload(input: { currentText: string; currentContentHash: string }): void {
    this.text = input.currentText;
    this.currentContentHash = input.currentContentHash;
    this.selection = { startUtf16: 0, endUtf16: 0, direction: "none" };
    this.composing = false;
    this.autoFollowPaused = false;
    this.clearCurrentSegment();
    this.rebindExactRevisionOrInvalidate();
  }

  mappingFor(segmentId: string): SegmentMapping | null {
    const mapping = this.mappings.get(segmentId);
    return mapping ? mappingCopy(mapping) : null;
  }

  lastRequestedScrollSegment(): string | null {
    return this.lastScrollRequest;
  }

  private isMapped(segmentId: string): boolean {
    return this.mappings.get(segmentId)?.state === "mapped";
  }

  private rebindExactRevisionOrInvalidate(): void {
    this.mappings = new Map();
    const exactEditionText = this.currentContentHash === this.editionContentHash;
    for (const segment of this.segments) {
      const exactLocalText = this.text.slice(
        segment.sourceRange.startUtf16,
        segment.sourceRange.endUtf16,
      ) === segment.sourceText;
      this.mappings.set(segment.segmentId, exactEditionText && exactLocalText
        ? {
          segmentId: segment.segmentId,
          sourceBlockKey: segment.sourceBlockKey,
          state: "mapped",
          currentRange: copyRange(segment.sourceRange),
        }
        : {
          segmentId: segment.segmentId,
          sourceBlockKey: segment.sourceBlockKey,
          state: "invalidated",
          currentRange: null,
          reason: "reload_diverged",
        });
    }
  }
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


export function createCodeMirrorPrototypeExtensions(
  onGutterIntent?: (lineStartUtf16: number) => void,
  onDocumentChange?: (change: CodeMirrorDocumentChange) => void,
): readonly Extension[] {
  return [
    codeMirrorNarrationField,
    history(),
    keymap.of(historyKeymap),
    EditorView.updateListener.of((update) => {
      if (!update.docChanged) return;
      onDocumentChange?.({
        text: update.state.doc.toString(),
        composing: update.view.composing,
        transactionCount: update.transactions.length,
      });
    }),
    lineNumbers({
      domEventHandlers: {
        mousedown(view, line) {
          onGutterIntent?.(line.from);
          view.focus();
          return true;
        },
      },
    }),
  ];
}


export function createCodeMirrorPrototypeState(
  text: string,
  selection?: NarrationEditorSelection,
): EditorState {
  const anchor = selection
    ? selection.direction === "backward" ? selection.endUtf16 : selection.startUtf16
    : 0;
  const head = selection
    ? selection.direction === "backward" ? selection.startUtf16 : selection.endUtf16
    : anchor;
  return EditorState.create({
    doc: text,
    selection: CodeMirrorSelection.single(anchor, head),
    extensions: createCodeMirrorPrototypeExtensions(),
  });
}


export function mountCodeMirrorPrototype(
  parent: HTMLElement,
  text: string,
  options: {
    selection?: NarrationEditorSelection;
    onGutterIntent?: (lineStartUtf16: number) => void;
    onDocumentChange?: (change: CodeMirrorDocumentChange) => void;
  } = {},
): CodeMirrorPrototypeHandle {
  const anchor = options.selection
    ? options.selection.direction === "backward"
      ? options.selection.endUtf16
      : options.selection.startUtf16
    : 0;
  const head = options.selection
    ? options.selection.direction === "backward"
      ? options.selection.startUtf16
      : options.selection.endUtf16
    : anchor;
  const state = EditorState.create({
    doc: text,
    selection: CodeMirrorSelection.single(anchor, head),
    extensions: createCodeMirrorPrototypeExtensions(
      options.onGutterIntent,
      options.onDocumentChange,
    ),
  });
  const view = new EditorView({ state, parent });
  return {
    view,
    highlight(range) {
      view.dispatch({ effects: setCodeMirrorNarrationRange.of(range) });
    },
    undo: () => undo(view),
    redo: () => redo(view),
    destroy() {
      view.destroy();
    },
  };
}


export function codeMirrorNarrationEffect(range: Utf16Range | null): StateEffect<Utf16Range | null> {
  return setCodeMirrorNarrationRange.of(range);
}


export function codeMirrorNarrationRanges(state: EditorState): readonly Utf16Range[] {
  const ranges: Utf16Range[] = [];
  state.field(codeMirrorNarrationField).between(0, state.doc.length, (from, to) => {
    ranges.push({ startUtf16: from, endUtf16: to });
  });
  return ranges;
}
