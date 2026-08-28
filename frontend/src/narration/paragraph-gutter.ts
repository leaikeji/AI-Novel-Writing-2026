import {
  assertUtf16Range,
  type NarrationEditorBridge,
  type PlaybackIntentResult,
  type PlaybackLookup,
  type Utf16Range,
} from "./editor-bridge";
import {
  playbackLeaseMatchesDocument,
} from "./chapter-playback";
import {
  playbackLeasesEqual,
  type PlaybackLease,
} from "./segment-playback-queue";


export interface NarrationParagraphDescriptor {
  readonly paragraphOrdinal: number;
  readonly sourceBlockKey: string;
  readonly range: Utf16Range;
  readonly narratable: boolean;
}


export type ParagraphGutterAvailability =
  | "available"
  | "editor_gutter_unavailable"
  | "not_narratable"
  | "update_required"
  | "stale_scope";


export interface ParagraphGutterButtonModel {
  readonly paragraphOrdinal: number;
  readonly sourceBlockKey: string;
  readonly targetSegmentId: string | null;
  readonly availability: ParagraphGutterAvailability;
  readonly disabled: boolean;
  readonly ariaLabel: string;
  readonly title: string;
}


export type ParagraphPlaybackActionResult = Readonly<
  | {
      handled: true;
      fence: PlaybackLease;
      intentResult: PlaybackIntentResult;
    }
  | {
      handled: false;
      reason:
        | "unsupported_key"
        | "paragraph_not_found"
        | "not_narratable"
        | "editor_gutter_unavailable"
        | "stale_scope";
      fence: PlaybackLease | null;
    }
>;


export interface NarrationKeyboardEventLike {
  readonly key: string;
  readonly altKey?: boolean;
  readonly ctrlKey?: boolean;
  readonly metaKey?: boolean;
  readonly shiftKey?: boolean;
  readonly repeat?: boolean;
  readonly isComposing?: boolean;
}


export type EditorParagraphPlaybackCommand = Readonly<
  | {
      source: "context-menu" | "cursor-command";
      lookup: PlaybackLookup;
    }
  | {
      source: "keyboard";
      event: NarrationKeyboardEventLike;
      lookup: PlaybackLookup;
    }
>;


export type OnEditorParagraphPlaybackCommand = (
  command: EditorParagraphPlaybackCommand,
) => boolean;


export interface EditorParagraphContextMenuRequest {
  readonly lookup: PlaybackLookup;
  readonly clientX: number;
  readonly clientY: number;
}


export type OnEditorParagraphContextMenu = (
  request: EditorParagraphContextMenuRequest,
) => boolean;


export interface ParagraphGutterControllerOptions {
  readonly bridge: NarrationEditorBridge;
  readonly editionId: string;
  readonly paragraphs: readonly NarrationParagraphDescriptor[];
  readonly readPlaybackLease: () => PlaybackLease;
  readonly isPlaybackLeaseCurrent?: (lease: PlaybackLease) => boolean;
}


export interface ParagraphGutterController {
  listButtons(): readonly ParagraphGutterButtonModel[];
  requestFromGutter(paragraphOrdinal: number): ParagraphPlaybackActionResult;
  requestFromContextMenu(lookup: PlaybackLookup): ParagraphPlaybackActionResult;
  requestFromKeyboard(
    event: NarrationKeyboardEventLike,
    lookup: PlaybackLookup,
  ): ParagraphPlaybackActionResult;
  requestFromGutterKeyboard(
    paragraphOrdinal: number,
    event: NarrationKeyboardEventLike,
  ): ParagraphPlaybackActionResult;
  requestOrdinaryEditorClick(lookup: PlaybackLookup): PlaybackIntentResult;
  dispose(): void;
}


function freezePlaybackLease(lease: PlaybackLease): PlaybackLease {
  return Object.freeze({ ...lease });
}


function assertParagraphs(paragraphs: readonly NarrationParagraphDescriptor[]): void {
  const ordinals = new Set<number>();
  const blockKeys = new Set<string>();
  for (const paragraph of paragraphs) {
    if (!Number.isSafeInteger(paragraph.paragraphOrdinal) || paragraph.paragraphOrdinal < 0) {
      throw new RangeError("paragraphOrdinal must be a non-negative safe integer");
    }
    if (!paragraph.sourceBlockKey.trim()) throw new TypeError("sourceBlockKey must not be empty");
    if (
      !Number.isSafeInteger(paragraph.range.startUtf16)
      || !Number.isSafeInteger(paragraph.range.endUtf16)
      || paragraph.range.startUtf16 < 0
      || paragraph.range.endUtf16 < paragraph.range.startUtf16
    ) throw new RangeError("paragraph range must contain valid UTF-16 offsets");
    if (ordinals.has(paragraph.paragraphOrdinal)) {
      throw new Error(`duplicate paragraphOrdinal: ${paragraph.paragraphOrdinal}`);
    }
    if (blockKeys.has(paragraph.sourceBlockKey)) {
      throw new Error(`duplicate sourceBlockKey: ${paragraph.sourceBlockKey}`);
    }
    ordinals.add(paragraph.paragraphOrdinal);
    blockKeys.add(paragraph.sourceBlockKey);
  }
}


function gutterButtonLabel(paragraphOrdinal: number): string {
  return `从第 ${paragraphOrdinal + 1} 段朗读`;
}


export function isNarrationSeekKeyboardCommand(
  event: NarrationKeyboardEventLike,
): boolean {
  if (event.isComposing || event.repeat || event.shiftKey) return false;
  const commandModifier = Boolean(event.metaKey || event.ctrlKey);
  return event.key === "Enter" && commandModifier && Boolean(event.altKey);
}


export function isGutterButtonActivationKey(event: NarrationKeyboardEventLike): boolean {
  return !event.isComposing && !event.repeat && (event.key === "Enter" || event.key === " ");
}


export class ProductionParagraphGutterController implements ParagraphGutterController {
  private readonly paragraphs: readonly NarrationParagraphDescriptor[];
  private readonly paragraphByOrdinal: ReadonlyMap<number, NarrationParagraphDescriptor>;
  private readonly isPlaybackLeaseCurrentExternal: (lease: PlaybackLease) => boolean;
  private disposed = false;

  constructor(private readonly options: ParagraphGutterControllerOptions) {
    if (!options.editionId.trim()) throw new TypeError("editionId must not be empty");
    assertParagraphs(options.paragraphs);
    const editorText = options.bridge.readSnapshot().text;
    for (const paragraph of options.paragraphs) {
      assertUtf16Range(editorText, paragraph.range, `paragraph ${paragraph.paragraphOrdinal}.range`);
    }
    this.paragraphs = Object.freeze(options.paragraphs.map((paragraph) => Object.freeze({
      ...paragraph,
      range: Object.freeze({ ...paragraph.range }),
    })));
    this.paragraphByOrdinal = new Map(
      this.paragraphs.map((paragraph) => [paragraph.paragraphOrdinal, paragraph]),
    );
    this.isPlaybackLeaseCurrentExternal = options.isPlaybackLeaseCurrent ?? (() => true);
  }

  listButtons(): readonly ParagraphGutterButtonModel[] {
    const fence = this.currentFence();
    return Object.freeze(this.paragraphs.map((paragraph) => {
      const label = gutterButtonLabel(paragraph.paragraphOrdinal);
      if (!fence) {
        return Object.freeze({
          paragraphOrdinal: paragraph.paragraphOrdinal,
          sourceBlockKey: paragraph.sourceBlockKey,
          targetSegmentId: null,
          availability: "stale_scope" as const,
          disabled: true,
          ariaLabel: label,
          title: "章节或朗读版本已变化，请使用当前版本。",
        });
      }
      if (!paragraph.narratable) {
        return Object.freeze({
          paragraphOrdinal: paragraph.paragraphOrdinal,
          sourceBlockKey: paragraph.sourceBlockKey,
          targetSegmentId: null,
          availability: "not_narratable" as const,
          disabled: true,
          ariaLabel: label,
          title: "此段没有可朗读内容。",
        });
      }
      if (!this.options.bridge.capabilities.paragraphGutter) {
        return Object.freeze({
          paragraphOrdinal: paragraph.paragraphOrdinal,
          sourceBlockKey: paragraph.sourceBlockKey,
          targetSegmentId: null,
          availability: "editor_gutter_unavailable" as const,
          disabled: true,
          ariaLabel: label,
          title: "当前编辑器请使用“从光标所在段朗读”。",
        });
      }
      const targetSegmentId = this.resolveParagraphTarget(paragraph);
      return Object.freeze({
        paragraphOrdinal: paragraph.paragraphOrdinal,
        sourceBlockKey: paragraph.sourceBlockKey,
        targetSegmentId,
        availability: targetSegmentId ? "available" as const : "update_required" as const,
        disabled: targetSegmentId === null,
        ariaLabel: label,
        title: targetSegmentId ? label : "本段已变化，请更新朗读后再播放。",
      });
    }));
  }

  requestFromGutter(paragraphOrdinal: number): ParagraphPlaybackActionResult {
    const paragraph = this.paragraphByOrdinal.get(paragraphOrdinal);
    if (!paragraph) return this.unhandled("paragraph_not_found");
    if (!paragraph.narratable) return this.unhandled("not_narratable");
    if (!this.options.bridge.capabilities.paragraphGutter) {
      return this.unhandled("editor_gutter_unavailable");
    }
    return this.request("gutter", {
      sourceBlockKey: paragraph.sourceBlockKey,
      positionUtf16: paragraph.range.startUtf16,
    });
  }

  requestFromContextMenu(lookup: PlaybackLookup): ParagraphPlaybackActionResult {
    return this.request("command", lookup);
  }

  requestFromKeyboard(
    event: NarrationKeyboardEventLike,
    lookup: PlaybackLookup,
  ): ParagraphPlaybackActionResult {
    if (!isNarrationSeekKeyboardCommand(event)) return this.unhandled("unsupported_key");
    return this.request("command", lookup);
  }

  requestFromGutterKeyboard(
    paragraphOrdinal: number,
    event: NarrationKeyboardEventLike,
  ): ParagraphPlaybackActionResult {
    if (!isGutterButtonActivationKey(event)) return this.unhandled("unsupported_key");
    return this.requestFromGutter(paragraphOrdinal);
  }

  requestOrdinaryEditorClick(lookup: PlaybackLookup): PlaybackIntentResult {
    return this.options.bridge.requestPlayback({
      lease: this.options.bridge.lease,
      editionId: this.options.editionId,
      source: "editor-click",
      lookup,
    });
  }

  dispose(): void {
    this.disposed = true;
  }

  private request(
    source: "gutter" | "command",
    lookup: PlaybackLookup,
  ): ParagraphPlaybackActionResult {
    const fence = this.currentFence();
    if (!fence) return this.unhandled("stale_scope");
    const intentResult = this.options.bridge.requestPlayback({
      lease: this.options.bridge.lease,
      editionId: this.options.editionId,
      source,
      lookup,
    });
    return Object.freeze({ handled: true, fence, intentResult });
  }

  private resolveParagraphTarget(paragraph: NarrationParagraphDescriptor): string | null {
    return this.options.bridge.resolvePlaybackTarget(
      { lease: this.options.bridge.lease, editionId: this.options.editionId },
      {
        sourceBlockKey: paragraph.sourceBlockKey,
        positionUtf16: paragraph.range.startUtf16,
      },
    );
  }

  private currentFence(): PlaybackLease | null {
    if (this.disposed) return null;
    const snapshot = this.options.bridge.readSnapshot();
    if (!snapshot.active || snapshot.edition?.editionId !== this.options.editionId) return null;
    let lease: PlaybackLease;
    try {
      lease = freezePlaybackLease(this.options.readPlaybackLease());
    } catch {
      return null;
    }
    if (!playbackLeaseMatchesDocument(
      lease,
      this.options.bridge.lease,
      this.options.editionId,
    )) return null;
    try {
      if (!this.isPlaybackLeaseCurrentExternal(lease)) return null;
      const reread = this.options.readPlaybackLease();
      if (!playbackLeasesEqual(lease, reread)) return null;
    } catch {
      return null;
    }
    return lease;
  }

  private unhandled(
    reason: Extract<ParagraphPlaybackActionResult, { handled: false }>["reason"],
  ): ParagraphPlaybackActionResult {
    return Object.freeze({ handled: false, reason, fence: this.currentFence() });
  }
}


export function createParagraphGutterController(
  options: ParagraphGutterControllerOptions,
): ParagraphGutterController {
  return new ProductionParagraphGutterController(options);
}
