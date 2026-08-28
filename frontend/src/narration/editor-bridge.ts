export interface DocumentLease {
  readonly documentId: string;
  readonly generation: number;
}


export interface NarrationEditionBinding {
  readonly editionId: string;
  readonly sourceRevisionId: string;
  readonly sourceContentHash: string;
}


export interface Utf16Range {
  readonly startUtf16: number;
  readonly endUtf16: number;
}


export interface NarrationEditorSelection extends Utf16Range {
  readonly direction: "forward" | "backward" | "none";
}


export interface NarrationSourceSegment {
  readonly segmentId: string;
  readonly sourceBlockKey: string;
  readonly sourceRange: Utf16Range;
  readonly sourceText: string;
  readonly prefixAnchor?: string;
  readonly suffixAnchor?: string;
}


export type EditorChangeOrigin =
  | "input"
  | "composition"
  | "undo"
  | "redo"
  | "ai-apply"
  | "ai-undo"
  | "recovery"
  | "external";


export interface OnEditorDocChangedEvent {
  readonly lease: DocumentLease;
  readonly nextValue: string;
  readonly origin: EditorChangeOrigin;
  readonly composing: boolean;
}


export type OnEditorDocChanged = (event: OnEditorDocChangedEvent) => void;


export interface NarrationEditorCapabilities {
  readonly editableDecorations: boolean;
  readonly paragraphGutter: boolean;
  readonly exactSegmentMapping: boolean;
}


export type SegmentInvalidationReason =
  | "transaction_intersection"
  | "boundary_adjacent"
  | "anchor_mismatch"
  | "source_diverged";


export type SegmentMapping =
  | Readonly<{
    segmentId: string;
    sourceBlockKey: string;
    state: "mapped";
    currentRange: Utf16Range;
  }>
  | Readonly<{
    segmentId: string;
    sourceBlockKey: string;
    state: "invalidated";
    currentRange: null;
    reason: SegmentInvalidationReason;
  }>;


export interface NarrationEditorSnapshot {
  readonly text: string;
  readonly selection: NarrationEditorSelection;
  readonly composing: boolean;
  readonly autoFollowPaused: boolean;
  readonly currentSegmentId: string | null;
  readonly exactEditionText: boolean;
  readonly edition: NarrationEditionBinding | null;
  readonly active: boolean;
  readonly inactiveReason: BridgeInactiveReason | null;
}


export interface EditorTextChange extends Utf16Range {
  readonly insertedText: string;
}


export interface NarrationEditorTransaction {
  readonly changes: readonly EditorTextChange[];
  readonly selectionAfter?: NarrationEditorSelection;
  readonly origin: EditorChangeOrigin;
}


export interface TransactionMappingReport {
  readonly applied: boolean;
  readonly inactiveReason: BridgeInactiveReason | null;
  readonly text: string;
  readonly mappedSegmentIds: readonly string[];
  readonly invalidated: Readonly<Record<string, SegmentInvalidationReason>>;
  readonly invalidatedSourceBlockKeys: readonly string[];
}


export type PlaybackIntentSource =
  | "editor-click"
  | "gutter"
  | "command"
  | "readonly-segment";


export interface PlaybackLookup {
  readonly segmentId?: string;
  readonly sourceBlockKey?: string;
  readonly range?: Utf16Range;
  readonly positionUtf16?: number;
}


export interface NarrationBridgeGuard {
  readonly lease: DocumentLease;
  readonly editionId?: string;
}


export interface PlaybackIntent {
  readonly lease: DocumentLease;
  readonly editionId: string;
  readonly source: Exclude<PlaybackIntentSource, "editor-click">;
  readonly segmentId: string;
  readonly sourceBlockKey: string;
}


export type PlaybackIntentResult =
  | Readonly<{ accepted: true; intent: PlaybackIntent }>
  | Readonly<{
    accepted: false;
    reason:
      | BridgeInactiveReason
      | "edition_unbound"
      | "edition_mismatch"
      | "editor_click_moves_caret_only"
      | "unsupported_surface"
      | "unmapped_target"
      | "missing_target";
  }>;


export type FollowFailureReason =
  | BridgeInactiveReason
  | "edition_unbound"
  | "edition_mismatch"
  | "composition"
  | "manual_scroll"
  | "unmapped_segment"
  | "unsupported_capability";


export type FollowResult =
  | Readonly<{ applied: true; segmentId: string }>
  | Readonly<{
    applied: false;
    reason: FollowFailureReason;
  }>;


export type BridgeInactiveReason = "disposed" | "stale_generation";


export type BridgeCommandResult =
  | Readonly<{ applied: true }>
  | Readonly<{
    applied: false;
    reason: BridgeInactiveReason | "edition_mismatch" | "composition";
  }>;


export type NarrationEditorPresentationEvent =
  | Readonly<{ type: "current-segment"; segmentId: string; range: Utf16Range }>
  | Readonly<{ type: "clear-current-segment" }>
  | Readonly<{ type: "scroll-current-segment"; segmentId: string; range: Utf16Range }>
  | Readonly<{ type: "focus-selection"; selection: NarrationEditorSelection }>;


export interface BindNarrationEditionInput extends NarrationEditionBinding {
  readonly lease: DocumentLease;
  readonly segments: readonly NarrationSourceSegment[];
}


export interface RequestNarrationPlaybackInput extends NarrationBridgeGuard {
  readonly source: PlaybackIntentSource;
  readonly lookup: PlaybackLookup;
}


export interface MarkCurrentSegmentInput extends NarrationBridgeGuard {
  readonly segmentId: string;
}


export interface NarrationEditorBridge {
  readonly kind: "codemirror6" | "textarea-fallback";
  readonly lease: DocumentLease;
  readonly capabilities: NarrationEditorCapabilities;

  readSnapshot(): NarrationEditorSnapshot;
  bindEdition(input: BindNarrationEditionInput): BridgeCommandResult;
  unbindEdition(guard: NarrationBridgeGuard): BridgeCommandResult;
  setSelection(selection: NarrationEditorSelection): BridgeCommandResult;
  focusSelection(selection: NarrationEditorSelection): BridgeCommandResult;
  beginComposition(): BridgeCommandResult;
  endComposition(): FollowResult | BridgeCommandResult;
  resolvePlaybackTarget(guard: NarrationBridgeGuard, lookup: PlaybackLookup): string | null;
  markCurrentSegment(input: MarkCurrentSegmentInput): FollowResult;
  scrollCurrentSegmentIntoView(guard: NarrationBridgeGuard): FollowResult;
  clearCurrentSegment(guard: NarrationBridgeGuard): BridgeCommandResult;
  noteManualScroll(): BridgeCommandResult;
  resumeAutoFollow(): BridgeCommandResult;
  registerPlaybackIntent(listener: (intent: PlaybackIntent) => void): () => void;
  registerPresentationListener(listener: (event: NarrationEditorPresentationEvent) => void): () => void;
  requestPlayback(input: RequestNarrationPlaybackInput): PlaybackIntentResult;
  applyTransaction(transaction: NarrationEditorTransaction): TransactionMappingReport;
  mappingFor(segmentId: string, guard?: NarrationBridgeGuard): SegmentMapping | null;
  dispose(): void;
}


export interface CreateNarrationEditorBridgeOptions {
  readonly kind: NarrationEditorBridge["kind"];
  readonly lease: DocumentLease;
  readonly text: string;
  readonly currentContentHash: string;
  readonly selection?: NarrationEditorSelection;
  readonly onDocChanged: OnEditorDocChanged;
  readonly isLeaseCurrent: (lease: DocumentLease) => boolean;
}


interface SourceBlockRange extends Utf16Range {
  readonly sourceBlockKey: string;
}


interface PendingFollow {
  readonly segmentId: string | null;
  readonly scrollRequested: boolean;
}


const BOUNDARY_SENSITIVE = /[\n\r“”「」『』"'：:。！？!?；;\uff0c,—…]/u;


const CODEMIRROR_CAPABILITIES: NarrationEditorCapabilities = Object.freeze({
  editableDecorations: true,
  paragraphGutter: true,
  exactSegmentMapping: true,
});


const TEXTAREA_CAPABILITIES: NarrationEditorCapabilities = Object.freeze({
  editableDecorations: false,
  paragraphGutter: false,
  exactSegmentMapping: true,
});


export const TEXTAREA_SAFE_FALLBACK = Object.freeze({
  editableDecoration: false,
  editableGutterSeek: false,
  ordinaryClickSeeks: false,
  allowedSeekSurfaces: ["readonly-segment", "paragraph-list", "explicit-command"] as const,
  divergedCopyPresentation: ["player-subtitle", "immutable-edition-drawer"] as const,
  requiredRecoveryAction: "update-narration" as const,
});


export function documentLeasesEqual(left: DocumentLease, right: DocumentLease): boolean {
  return left.documentId === right.documentId && left.generation === right.generation;
}


export function assertWellFormedUtf16(text: string, label: string): void {
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new RangeError(`${label} contains an unpaired UTF-16 high surrogate`);
      }
      index += 1;
      continue;
    }
    if (code >= 0xdc00 && code <= 0xdfff) {
      throw new RangeError(`${label} contains an unpaired UTF-16 low surrogate`);
    }
  }
}


export function assertUtf16Offset(text: string, value: number, label: string): void {
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


export function assertUtf16Range(text: string, range: Utf16Range, label: string): void {
  assertUtf16Offset(text, range.startUtf16, `${label}.startUtf16`);
  assertUtf16Offset(text, range.endUtf16, `${label}.endUtf16`);
  if (range.endUtf16 < range.startUtf16) {
    throw new RangeError(`${label}.endUtf16 must be greater than or equal to startUtf16`);
  }
}


function assertLease(lease: DocumentLease, label: string): void {
  if (!lease.documentId.trim()) throw new TypeError(`${label}.documentId must not be empty`);
  if (!Number.isInteger(lease.generation) || lease.generation < 0) {
    throw new RangeError(`${label}.generation must be a non-negative integer`);
  }
}


function assertNonEmpty(value: string, label: string): void {
  if (!value.trim()) throw new TypeError(`${label} must not be empty`);
}


function copyLease(lease: DocumentLease): DocumentLease {
  return Object.freeze({ documentId: lease.documentId, generation: lease.generation });
}


function copyRange(range: Utf16Range): Utf16Range {
  return { startUtf16: range.startUtf16, endUtf16: range.endUtf16 };
}


function copySelection(selection: NarrationEditorSelection): NarrationEditorSelection {
  return { ...copyRange(selection), direction: selection.direction };
}


function copyEdition(edition: NarrationEditionBinding): NarrationEditionBinding {
  return Object.freeze({
    editionId: edition.editionId,
    sourceRevisionId: edition.sourceRevisionId,
    sourceContentHash: edition.sourceContentHash,
  });
}


function copySegment(segment: NarrationSourceSegment): NarrationSourceSegment {
  return Object.freeze({
    ...segment,
    sourceRange: Object.freeze(copyRange(segment.sourceRange)),
  });
}


function mappingCopy(mapping: SegmentMapping): SegmentMapping {
  return mapping.state === "mapped"
    ? { ...mapping, currentRange: copyRange(mapping.currentRange) }
    : { ...mapping };
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


function mapUnaffectedRange(range: Utf16Range, changes: readonly EditorTextChange[]): Utf16Range {
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


function buildSourceBlocks(segments: readonly NarrationSourceSegment[]): readonly SourceBlockRange[] {
  const blocks = new Map<string, { sourceBlockKey: string; startUtf16: number; endUtf16: number }>();
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


function assertSegmentsShape(segments: readonly NarrationSourceSegment[]): void {
  const ids = new Set<string>();
  for (const segment of segments) {
    assertNonEmpty(segment.segmentId, "segment.segmentId");
    assertNonEmpty(segment.sourceBlockKey, `segment ${segment.segmentId}.sourceBlockKey`);
    assertWellFormedUtf16(segment.sourceText, `segment ${segment.segmentId}.sourceText`);
    if (segment.prefixAnchor !== undefined) {
      assertWellFormedUtf16(segment.prefixAnchor, `segment ${segment.segmentId}.prefixAnchor`);
    }
    if (segment.suffixAnchor !== undefined) {
      assertWellFormedUtf16(segment.suffixAnchor, `segment ${segment.segmentId}.suffixAnchor`);
    }
    if (ids.has(segment.segmentId)) throw new Error(`duplicate segmentId: ${segment.segmentId}`);
    ids.add(segment.segmentId);
    if (
      !Number.isInteger(segment.sourceRange.startUtf16)
      || !Number.isInteger(segment.sourceRange.endUtf16)
      || segment.sourceRange.startUtf16 < 0
      || segment.sourceRange.endUtf16 <= segment.sourceRange.startUtf16
    ) {
      throw new RangeError(`segment ${segment.segmentId} must define a non-empty UTF-16 range`);
    }
    if (
      segment.sourceRange.endUtf16 - segment.sourceRange.startUtf16
      !== segment.sourceText.length
    ) {
      throw new RangeError(`segment ${segment.segmentId} source range length must match sourceText`);
    }
  }
}


export class ProductionNarrationEditorBridge implements NarrationEditorBridge {
  readonly kind: NarrationEditorBridge["kind"];
  readonly lease: DocumentLease;
  readonly capabilities: NarrationEditorCapabilities;

  private text: string;
  private currentContentHash: string;
  private selection: NarrationEditorSelection;
  private composing = false;
  private autoFollowPaused = false;
  private currentSegmentId: string | null = null;
  private lastScrollRequest: string | null = null;
  private edition: NarrationEditionBinding | null = null;
  private segments: readonly NarrationSourceSegment[] = [];
  private segmentById: ReadonlyMap<string, NarrationSourceSegment> = new Map();
  private sourceBlocks: readonly SourceBlockRange[] = [];
  private mappings = new Map<string, SegmentMapping>();
  private pendingFollow: PendingFollow | null = null;
  private disposed = false;
  private onDocChanged: OnEditorDocChanged | null;
  private isLeaseCurrent: ((lease: DocumentLease) => boolean) | null;
  private readonly intentListeners = new Set<(intent: PlaybackIntent) => void>();
  private readonly presentationListeners = new Set<(event: NarrationEditorPresentationEvent) => void>();

  constructor(options: CreateNarrationEditorBridgeOptions) {
    assertLease(options.lease, "lease");
    assertWellFormedUtf16(options.text, "text");
    assertNonEmpty(options.currentContentHash, "currentContentHash");
    this.kind = options.kind;
    this.lease = copyLease(options.lease);
    this.capabilities = options.kind === "codemirror6"
      ? CODEMIRROR_CAPABILITIES
      : TEXTAREA_CAPABILITIES;
    this.text = options.text;
    this.currentContentHash = options.currentContentHash;
    this.selection = options.selection
      ? copySelection(options.selection)
      : { startUtf16: 0, endUtf16: 0, direction: "none" };
    assertUtf16Range(this.text, this.selection, "selection");
    this.onDocChanged = options.onDocChanged;
    this.isLeaseCurrent = options.isLeaseCurrent;
  }

  readSnapshot(): NarrationEditorSnapshot {
    const inactiveReason = this.inactiveReason();
    return {
      text: this.text,
      selection: copySelection(this.selection),
      composing: this.composing,
      autoFollowPaused: this.autoFollowPaused,
      currentSegmentId: this.currentSegmentId,
      exactEditionText: this.edition !== null
        && this.currentContentHash === this.edition.sourceContentHash,
      edition: this.edition ? copyEdition(this.edition) : null,
      active: inactiveReason === null,
      inactiveReason,
    };
  }

  bindEdition(input: BindNarrationEditionInput): BridgeCommandResult {
    const inactiveReason = this.guardReason(input);
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    assertNonEmpty(input.editionId, "editionId");
    assertNonEmpty(input.sourceRevisionId, "sourceRevisionId");
    assertNonEmpty(input.sourceContentHash, "sourceContentHash");
    assertSegmentsShape(input.segments);
    this.edition = copyEdition(input);
    this.segments = input.segments.map(copySegment);
    this.segmentById = new Map(this.segments.map((segment) => [segment.segmentId, segment]));
    this.sourceBlocks = buildSourceBlocks(this.segments);
    this.mappings = new Map();
    this.pendingFollow = null;
    this.clearCurrentSegmentImmediately();
    this.rebindExactEditionOrInvalidate();
    return { applied: true };
  }

  unbindEdition(guard: NarrationBridgeGuard): BridgeCommandResult {
    const inactiveReason = this.guardReason(guard);
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    if (guard.editionId && this.edition?.editionId !== guard.editionId) {
      return { applied: false, reason: "edition_mismatch" };
    }
    this.edition = null;
    this.segments = [];
    this.segmentById = new Map();
    this.sourceBlocks = [];
    this.mappings.clear();
    this.pendingFollow = null;
    this.clearCurrentSegmentImmediately();
    return { applied: true };
  }

  setSelection(selection: NarrationEditorSelection): BridgeCommandResult {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    assertUtf16Range(this.text, selection, "selection");
    this.selection = copySelection(selection);
    return { applied: true };
  }

  focusSelection(selection: NarrationEditorSelection): BridgeCommandResult {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    if (this.composing) return { applied: false, reason: "composition" };
    assertUtf16Range(this.text, selection, "selection");
    this.selection = copySelection(selection);
    this.emitPresentation({ type: "focus-selection", selection: copySelection(selection) });
    return { applied: true };
  }

  beginComposition(): BridgeCommandResult {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    this.composing = true;
    return { applied: true };
  }

  endComposition(): FollowResult | BridgeCommandResult {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    this.composing = false;
    const pending = this.pendingFollow;
    this.pendingFollow = null;
    if (!pending) return { applied: true };
    if (pending.segmentId === null) {
      this.clearCurrentSegmentImmediately();
      return { applied: true };
    }
    if (!this.isMapped(pending.segmentId)) {
      this.clearCurrentSegmentImmediately();
      return { applied: false, reason: "unmapped_segment" };
    }
    this.applyCurrentSegment(pending.segmentId);
    if (pending.scrollRequested && !this.autoFollowPaused && this.capabilities.editableDecorations) {
      this.emitScroll(pending.segmentId);
    }
    return { applied: true, segmentId: pending.segmentId };
  }

  resolvePlaybackTarget(guard: NarrationBridgeGuard, lookup: PlaybackLookup): string | null {
    if (this.guardReason(guard) || !this.editionMatches(guard)) return null;
    return this.resolvePlaybackTargetUnchecked(lookup);
  }

  markCurrentSegment(input: MarkCurrentSegmentInput): FollowResult {
    const rejected = this.followGuardReason(input);
    if (rejected) return { applied: false, reason: rejected };
    if (!this.isMapped(input.segmentId)) return { applied: false, reason: "unmapped_segment" };
    if (this.composing) {
      this.pendingFollow = {
        segmentId: input.segmentId,
        scrollRequested: this.pendingFollow?.scrollRequested ?? false,
      };
      return { applied: false, reason: "composition" };
    }
    this.applyCurrentSegment(input.segmentId);
    return { applied: true, segmentId: input.segmentId };
  }

  scrollCurrentSegmentIntoView(guard: NarrationBridgeGuard): FollowResult {
    const rejected = this.followGuardReason(guard);
    if (rejected) return { applied: false, reason: rejected };
    if (!this.capabilities.editableDecorations) {
      return { applied: false, reason: "unsupported_capability" };
    }
    const segmentId = this.pendingFollow?.segmentId ?? this.currentSegmentId;
    if (this.composing) {
      if (!segmentId || !this.isMapped(segmentId)) {
        return { applied: false, reason: "unmapped_segment" };
      }
      this.pendingFollow = { segmentId, scrollRequested: true };
      return { applied: false, reason: "composition" };
    }
    if (this.autoFollowPaused) return { applied: false, reason: "manual_scroll" };
    if (!segmentId || !this.isMapped(segmentId)) {
      return { applied: false, reason: "unmapped_segment" };
    }
    this.emitScroll(segmentId);
    return { applied: true, segmentId };
  }

  clearCurrentSegment(guard: NarrationBridgeGuard): BridgeCommandResult {
    const inactiveReason = this.guardReason(guard);
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    if (!this.editionMatches(guard)) return { applied: false, reason: "edition_mismatch" };
    if (this.composing) {
      this.pendingFollow = { segmentId: null, scrollRequested: false };
    } else {
      this.clearCurrentSegmentImmediately();
    }
    return { applied: true };
  }

  noteManualScroll(): BridgeCommandResult {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    this.autoFollowPaused = true;
    return { applied: true };
  }

  resumeAutoFollow(): BridgeCommandResult {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return { applied: false, reason: inactiveReason };
    this.autoFollowPaused = false;
    return { applied: true };
  }

  registerPlaybackIntent(listener: (intent: PlaybackIntent) => void): () => void {
    if (this.inactiveReason()) return () => undefined;
    this.intentListeners.add(listener);
    return () => this.intentListeners.delete(listener);
  }

  registerPresentationListener(listener: (event: NarrationEditorPresentationEvent) => void): () => void {
    if (this.inactiveReason()) return () => undefined;
    this.presentationListeners.add(listener);
    return () => this.presentationListeners.delete(listener);
  }

  requestPlayback(input: RequestNarrationPlaybackInput): PlaybackIntentResult {
    const inactiveReason = this.guardReason(input);
    if (inactiveReason) return { accepted: false, reason: inactiveReason };
    if (!this.edition) return { accepted: false, reason: "edition_unbound" };
    if (!this.editionMatches(input)) return { accepted: false, reason: "edition_mismatch" };
    if (input.source === "editor-click") {
      return { accepted: false, reason: "editor_click_moves_caret_only" };
    }
    if (input.source === "gutter" && !this.capabilities.paragraphGutter) {
      return { accepted: false, reason: "unsupported_surface" };
    }
    let segmentId: string | null;
    if (
      input.source === "readonly-segment"
      && input.lookup.segmentId
      && this.segmentById.has(input.lookup.segmentId)
    ) {
      segmentId = input.lookup.segmentId;
    } else {
      segmentId = this.resolvePlaybackTargetUnchecked(input.lookup);
    }
    if (!segmentId) {
      return {
        accepted: false,
        reason: Object.keys(input.lookup).length === 0 ? "missing_target" : "unmapped_target",
      };
    }
    const segment = this.segmentById.get(segmentId);
    if (!segment) return { accepted: false, reason: "missing_target" };
    const intent: PlaybackIntent = Object.freeze({
      lease: this.lease,
      editionId: this.edition.editionId,
      source: input.source,
      segmentId,
      sourceBlockKey: segment.sourceBlockKey,
    });
    for (const listener of [...this.intentListeners]) listener(intent);
    return { accepted: true, intent };
  }

  applyTransaction(transaction: NarrationEditorTransaction): TransactionMappingReport {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return this.inactiveTransactionReport(inactiveReason);
    const changes = [...transaction.changes].sort((left, right) => (
      left.startUtf16 - right.startUtf16 || left.endUtf16 - right.endUtf16
    ));
    let previousEnd = -1;
    for (const [index, change] of changes.entries()) {
      assertUtf16Range(this.text, change, `changes[${index}]`);
      assertWellFormedUtf16(change.insertedText, `changes[${index}].insertedText`);
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
    assertWellFormedUtf16(nextText, "transaction result");
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
      const matchesText = nextText.slice(currentRange.startUtf16, currentRange.endUtf16)
        === segment.sourceText;
      const matchesPrefix = segment.prefixAnchor === undefined
        || nextText.slice(
          Math.max(0, currentRange.startUtf16 - segment.prefixAnchor.length),
          currentRange.startUtf16,
        ) === segment.prefixAnchor;
      const matchesSuffix = segment.suffixAnchor === undefined
        || nextText.slice(
          currentRange.endUtf16,
          currentRange.endUtf16 + segment.suffixAnchor.length,
        ) === segment.suffixAnchor;
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
    if (changes.length > 0) this.currentContentHash = `active-session-diverged:${transaction.origin}`;
    if (transaction.selectionAfter) {
      assertUtf16Range(this.text, transaction.selectionAfter, "selectionAfter");
      this.selection = copySelection(transaction.selectionAfter);
    } else if (changes.length > 0) {
      this.selection = {
        startUtf16: mapSelectionPosition(this.selection.startUtf16, changes, -1),
        endUtf16: mapSelectionPosition(this.selection.endUtf16, changes, 1),
        direction: this.selection.direction,
      };
    }
    if (this.currentSegmentId && !this.isMapped(this.currentSegmentId)) {
      if (this.composing) {
        this.pendingFollow = { segmentId: null, scrollRequested: false };
      } else {
        this.clearCurrentSegmentImmediately();
      }
    }

    if (changes.length > 0) {
      this.onDocChanged?.({
        lease: this.lease,
        nextValue: this.text,
        origin: transaction.origin,
        composing: this.composing,
      });
    }
    return {
      applied: true,
      inactiveReason: null,
      text: this.text,
      mappedSegmentIds: this.mappedSegmentIds(),
      invalidated,
      invalidatedSourceBlockKeys: [...invalidatedBlocks],
    };
  }

  mappingFor(segmentId: string, guard?: NarrationBridgeGuard): SegmentMapping | null {
    if (guard && (this.guardReason(guard) || !this.editionMatches(guard))) return null;
    if (!guard && this.inactiveReason()) return null;
    const mapping = this.mappings.get(segmentId);
    return mapping ? mappingCopy(mapping) : null;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.composing = false;
    this.pendingFollow = null;
    this.intentListeners.clear();
    this.presentationListeners.clear();
    this.onDocChanged = null;
    this.isLeaseCurrent = null;
  }

  lastRequestedScrollSegment(): string | null {
    return this.inactiveReason() ? null : this.lastScrollRequest;
  }

  private inactiveReason(): BridgeInactiveReason | null {
    if (this.disposed) return "disposed";
    try {
      if (!this.isLeaseCurrent?.(this.lease)) return "stale_generation";
    } catch {
      return "stale_generation";
    }
    return null;
  }

  private guardReason(guard: NarrationBridgeGuard): BridgeInactiveReason | null {
    const inactiveReason = this.inactiveReason();
    if (inactiveReason) return inactiveReason;
    return documentLeasesEqual(this.lease, guard.lease) ? null : "stale_generation";
  }

  private editionMatches(guard: NarrationBridgeGuard): boolean {
    return guard.editionId === undefined || this.edition?.editionId === guard.editionId;
  }

  private followGuardReason(
    guard: NarrationBridgeGuard,
  ): FollowFailureReason | null {
    const inactiveReason = this.guardReason(guard);
    if (inactiveReason) return inactiveReason;
    if (!this.edition) return "edition_unbound";
    if (!this.editionMatches(guard)) return "edition_mismatch";
    return null;
  }

  private resolvePlaybackTargetUnchecked(lookup: PlaybackLookup): string | null {
    if (lookup.segmentId) return this.isMapped(lookup.segmentId) ? lookup.segmentId : null;
    const candidates = this.segments
      .map((segment) => ({ segment, mapping: this.mappings.get(segment.segmentId) }))
      .filter((candidate): candidate is {
        segment: NarrationSourceSegment;
        mapping: Extract<SegmentMapping, { state: "mapped" }>;
      } => candidate.mapping?.state === "mapped")
      .filter(({ segment }) => (
        !lookup.sourceBlockKey || segment.sourceBlockKey === lookup.sourceBlockKey
      ))
      .sort((left, right) => (
        left.mapping.currentRange.startUtf16 - right.mapping.currentRange.startUtf16
      ));
    if (lookup.range) {
      const lookupRange = lookup.range;
      assertUtf16Range(this.text, lookupRange, "playback lookup range");
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
      assertUtf16Offset(this.text, lookup.positionUtf16, "playback lookup positionUtf16");
      const containing = candidates.find(({ mapping }) => (
        lookup.positionUtf16 !== undefined
        && lookup.positionUtf16 >= mapping.currentRange.startUtf16
        && lookup.positionUtf16 <= mapping.currentRange.endUtf16
      ));
      if (containing) return containing.segment.segmentId;
      return candidates.find(({ mapping }) => (
        lookup.positionUtf16 !== undefined
        && mapping.currentRange.startUtf16 > lookup.positionUtf16
      ))?.segment.segmentId ?? candidates[candidates.length - 1]?.segment.segmentId ?? null;
    }
    return candidates[0]?.segment.segmentId ?? null;
  }

  private isMapped(segmentId: string): boolean {
    return this.mappings.get(segmentId)?.state === "mapped";
  }

  private mappedSegmentIds(): readonly string[] {
    return this.segments
      .map((segment) => segment.segmentId)
      .filter((segmentId) => this.isMapped(segmentId));
  }

  private rebindExactEditionOrInvalidate(): void {
    this.mappings.clear();
    const exactEditionText = this.edition !== null
      && this.currentContentHash === this.edition.sourceContentHash;
    for (const segment of this.segments) {
      let exactLocalText = false;
      let anchorsMatch = false;
      if (
        exactEditionText
        && segment.sourceRange.endUtf16 <= this.text.length
      ) {
        assertUtf16Range(this.text, segment.sourceRange, `segment ${segment.segmentId}`);
        exactLocalText = this.text.slice(
          segment.sourceRange.startUtf16,
          segment.sourceRange.endUtf16,
        ) === segment.sourceText;
        const prefixMatches = segment.prefixAnchor === undefined
          || this.text.slice(
            Math.max(0, segment.sourceRange.startUtf16 - segment.prefixAnchor.length),
            segment.sourceRange.startUtf16,
          ) === segment.prefixAnchor;
        const suffixMatches = segment.suffixAnchor === undefined
          || this.text.slice(
            segment.sourceRange.endUtf16,
            segment.sourceRange.endUtf16 + segment.suffixAnchor.length,
          ) === segment.suffixAnchor;
        anchorsMatch = prefixMatches && suffixMatches;
      }
      this.mappings.set(segment.segmentId, exactEditionText && exactLocalText && anchorsMatch
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
          reason: exactEditionText ? "anchor_mismatch" : "source_diverged",
        });
    }
  }

  private applyCurrentSegment(segmentId: string): void {
    const mapping = this.mappings.get(segmentId);
    if (mapping?.state !== "mapped") return;
    this.currentSegmentId = segmentId;
    this.emitPresentation({
      type: "current-segment",
      segmentId,
      range: copyRange(mapping.currentRange),
    });
  }

  private clearCurrentSegmentImmediately(): void {
    const hadCurrent = this.currentSegmentId !== null || this.lastScrollRequest !== null;
    this.currentSegmentId = null;
    this.lastScrollRequest = null;
    if (hadCurrent) this.emitPresentation({ type: "clear-current-segment" });
  }

  private emitScroll(segmentId: string): void {
    const mapping = this.mappings.get(segmentId);
    if (mapping?.state !== "mapped") return;
    this.lastScrollRequest = segmentId;
    this.emitPresentation({
      type: "scroll-current-segment",
      segmentId,
      range: copyRange(mapping.currentRange),
    });
  }

  private emitPresentation(event: NarrationEditorPresentationEvent): void {
    if (this.inactiveReason()) return;
    for (const listener of [...this.presentationListeners]) listener(event);
  }

  private inactiveTransactionReport(reason: BridgeInactiveReason): TransactionMappingReport {
    return {
      applied: false,
      inactiveReason: reason,
      text: this.text,
      mappedSegmentIds: this.mappedSegmentIds(),
      invalidated: {},
      invalidatedSourceBlockKeys: [],
    };
  }
}


export function createNarrationEditorBridge(
  options: CreateNarrationEditorBridgeOptions,
): ProductionNarrationEditorBridge {
  return new ProductionNarrationEditorBridge(options);
}
