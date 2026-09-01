import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductionChapterPlaybackCoordinator } from "./chapter-playback";
import { createChapterEditorSurface } from "./chapter-editor-surface";
import type { DocumentLease } from "./editor-bridge";
import type {
  NarrationPlayerController,
  NarrationPlayerState,
  NarrationPlaybackSource,
  PlaybackDecision,
} from "./narration-player";
import { ProductionParagraphGutterController } from "./paragraph-gutter";
import type { NarrationManifestV2 } from "./playback-contracts";
import type { PlaybackLease } from "./segment-playback-queue";


const DOCUMENT_ID = "20000000-0000-4000-8000-000000000001";
const EDITION_ID = "10000000-0000-4000-8000-000000000001";
const REVISION_ID = "30000000-0000-4000-8000-000000000001";
const SEGMENT_1 = "40000000-0000-4000-8000-000000000001";
const SEGMENT_2 = "40000000-0000-4000-8000-000000000002";
const TEXT = "第一段。\n第二段。";
const HASH = "a".repeat(64);
const LEASE: DocumentLease = { documentId: DOCUMENT_ID, generation: 11 };


class FakeNode {
  parentNode: FakeParent | null = null;
}


class FakeParent extends FakeNode {
  readonly childNodes: FakeNode[] = [];
  readonly ownerDocument = null;

  appendChild<T extends FakeNode>(child: T): T {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  removeChild<T extends FakeNode>(child: T): T {
    const index = this.childNodes.indexOf(child);
    if (index >= 0) this.childNodes.splice(index, 1);
    child.parentNode = null;
    return child;
  }
}


class FakeTextarea extends EventTarget {
  parentNode: FakeParent | null = null;
  value = "";
  selectionStart = 0;
  selectionEnd = 0;
  selectionDirection: "forward" | "backward" | "none" = "none";
  className = "";
  spellcheck = false;
  wrap = "";
  readonly attributes = new Map<string, string>();

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  setSelectionRange(
    start: number,
    end: number,
    direction: "forward" | "backward" | "none" = "none",
  ): void {
    this.selectionStart = start;
    this.selectionEnd = end;
    this.selectionDirection = direction;
  }

  focus(): void {}
}


function playerState(): NarrationPlayerState {
  return Object.freeze({
    phase: "idle",
    currentSegmentId: null,
    currentOrdinal: null,
    offsetMs: 0,
    durationMs: 0,
    rate: 1,
    volume: 1,
    followPaused: false,
    backend: null,
    source: null,
    failure: null,
  });
}


class FakePlayer implements NarrationPlayerController {
  private currentLease: PlaybackLease = Object.freeze({
    documentId: DOCUMENT_ID,
    documentGeneration: LEASE.generation,
    editionId: EDITION_ID,
    manifestRevision: 3,
    requestGeneration: 0,
  });
  readonly operations: Array<Readonly<{
    segmentId: string;
    source: NarrationPlaybackSource;
    lease: PlaybackLease;
  }>> = [];

  get lease(): PlaybackLease { return this.currentLease; }
  readState(): NarrationPlayerState { return playerState(); }
  bindManifest(_manifest: NarrationManifestV2): void {}

  async playFromSegment(
    segmentId: string,
    source: NarrationPlaybackSource,
  ): Promise<PlaybackDecision> {
    this.currentLease = Object.freeze({
      ...this.currentLease,
      requestGeneration: this.currentLease.requestGeneration + 1,
    });
    const lease = this.currentLease;
    this.operations.push(Object.freeze({ segmentId, source, lease }));
    return Object.freeze({
      kind: "play",
      lease,
      segmentId,
      ordinal: segmentId === SEGMENT_1 ? 0 : 1,
      backend: "media-element",
    });
  }

  pause(): void {}
  async resume(): Promise<PlaybackDecision> {
    return Object.freeze({ kind: "noop", lease: this.currentLease, reason: "not_paused" });
  }
  setRate(_rate: number): void {}
  setVolume(_volume: number): void {}
  updateManifest(_manifest: NarrationManifestV2): void {}
  subscribe(_listener: (state: NarrationPlayerState) => void): () => void {
    return () => undefined;
  }
  dispose(): void {}
}


function keyboardEvent(patch: { repeat?: boolean; isComposing?: boolean } = {}): Event {
  const event = new Event("keydown", { cancelable: true });
  Object.defineProperties(event, {
    key: { value: "Enter" },
    altKey: { value: true },
    ctrlKey: { value: true },
    metaKey: { value: false },
    shiftKey: { value: false },
    repeat: { value: patch.repeat ?? false },
    isComposing: { value: patch.isComposing ?? false },
  });
  return event;
}


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("chapter workbench paragraph playback interactions", () => {
  it("wires textarea context, shortcut, and cursor commands through the fenced player only", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const parent = new FakeParent();
    const textarea = new FakeTextarea();
    const onDocChanged = vi.fn();
    let gutter: ProductionParagraphGutterController | null = null;
    const surface = createChapterEditorSurface({
      parent: parent as unknown as HTMLElement,
      lease: LEASE,
      initialValue: TEXT,
      currentContentHash: HASH,
      ariaLabel: "章节正文",
      onDocChanged,
      isLeaseCurrent: (candidate) => (
        candidate.documentId === LEASE.documentId && candidate.generation === LEASE.generation
      ),
      onParagraphPlaybackCommand(command) {
        const result = command.source === "keyboard"
          ? gutter?.requestFromKeyboard(command.event, command.lookup)
          : gutter?.requestFromContextMenu(command.lookup);
        return Boolean(result?.handled && result.intentResult.accepted);
      },
    }, {
      createCodeMirrorAdapter() {
        throw new Error("force textarea fallback");
      },
      createTextareaElement: () => textarea as unknown as HTMLTextAreaElement,
    });
    expect(surface.bridge.bindEdition({
      lease: LEASE,
      editionId: EDITION_ID,
      sourceRevisionId: REVISION_ID,
      sourceContentHash: HASH,
      segments: [
        {
          segmentId: SEGMENT_1,
          sourceBlockKey: "paragraph-1",
          sourceText: "第一段。",
          sourceRange: { startUtf16: 0, endUtf16: 4 },
        },
        {
          segmentId: SEGMENT_2,
          sourceBlockKey: "paragraph-2",
          sourceText: "第二段。",
          sourceRange: { startUtf16: 5, endUtf16: 9 },
        },
      ],
    })).toEqual({ applied: true });
    const player = new FakePlayer();
    const results = vi.fn();
    const coordinator = new ProductionChapterPlaybackCoordinator({
      bridge: surface.bridge,
      player,
      onResult: results,
    });
    gutter = new ProductionParagraphGutterController({
      bridge: surface.bridge,
      editionId: EDITION_ID,
      paragraphs: [
        {
          paragraphOrdinal: 0,
          sourceBlockKey: "paragraph-1",
          range: { startUtf16: 0, endUtf16: 4 },
          narratable: true,
        },
        {
          paragraphOrdinal: 1,
          sourceBlockKey: "paragraph-2",
          range: { startUtf16: 5, endUtf16: 9 },
          narratable: true,
        },
      ],
      readPlaybackLease: () => player.lease,
    });

    textarea.selectionStart = 6;
    textarea.selectionEnd = 6;
    const shortcut = keyboardEvent();
    textarea.dispatchEvent(shortcut);
    textarea.selectionStart = 1;
    textarea.selectionEnd = 1;
    const context = new Event("contextmenu", { cancelable: true });
    textarea.dispatchEvent(context);
    textarea.selectionStart = 7;
    textarea.selectionEnd = 7;
    expect(surface.requestPlaybackFromCursor()).toBe(true);
    await Promise.resolve();
    await Promise.resolve();

    expect(player.operations.map(({ segmentId, source, lease }) => ({
      segmentId,
      source,
      requestGeneration: lease.requestGeneration,
    }))).toEqual([
      { segmentId: SEGMENT_2, source: "command", requestGeneration: 1 },
      { segmentId: SEGMENT_1, source: "command", requestGeneration: 2 },
      { segmentId: SEGMENT_2, source: "command", requestGeneration: 3 },
    ]);
    expect(shortcut.defaultPrevented).toBe(true);
    expect(context.defaultPrevented).toBe(true);
    expect(results).toHaveBeenCalledTimes(3);
    expect(results).toHaveBeenLastCalledWith(expect.objectContaining({
      status: "completed",
      fence: expect.objectContaining({ requestGeneration: 3 }),
    }));
    expect(onDocChanged).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    textarea.dispatchEvent(new Event("click"));
    textarea.dispatchEvent(keyboardEvent({ repeat: true }));
    textarea.dispatchEvent(new Event("compositionstart"));
    textarea.dispatchEvent(keyboardEvent({ isComposing: true }));
    textarea.dispatchEvent(new Event("contextmenu", { cancelable: true }));
    expect(surface.requestPlaybackFromCursor()).toBe(false);
    expect(player.operations).toHaveLength(3);
    expect(onDocChanged).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    gutter.dispose();
    coordinator.dispose();
    surface.dispose();
  });
});
