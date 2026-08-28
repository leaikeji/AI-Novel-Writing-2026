import type {
  DocumentLease,
  NarrationEditorBridge,
  PlaybackIntent,
  PlaybackIntentResult,
  PlaybackLookup,
  PlaybackIntentSource,
} from "./editor-bridge";
import type {
  NarrationPlayerController,
  NarrationPlaybackSource,
  PlaybackDecision,
} from "./narration-player";
import {
  playbackLeasesEqual,
  type PlaybackLease,
} from "./segment-playback-queue";


export const T4_G_DESKTOP_VIEWPORTS = Object.freeze({
  minimum: Object.freeze({ width: 1_920, height: 1_080 }),
  supplemental: Object.freeze({ width: 2_560, height: 1_440 }),
  belowMinimumIsBlocking: false,
});


export type ChapterPlaybackRequestResult = Readonly<
  | {
      status: "completed";
      intent: PlaybackIntent;
      fence: PlaybackLease;
      decision: PlaybackDecision;
    }
  | {
      status: "rejected";
      reason:
        | Extract<PlaybackIntentResult, { accepted: false }>["reason"]
        | "coordinator_disposed"
        | "intent_listener_unavailable";
      fence: PlaybackLease | null;
    }
  | {
      status: "stale";
      reason:
        | "document_generation_changed"
        | "edition_changed"
        | "manifest_revision_changed"
        | "request_superseded"
        | "external_fence_rejected";
      fence: PlaybackLease;
    }
  | {
      status: "failed";
      reason: "player_rejected_request";
      fence: PlaybackLease;
      error: unknown;
    }
>;


export interface ChapterPlaybackCoordinatorOptions {
  readonly bridge: NarrationEditorBridge;
  readonly player: NarrationPlayerController;
  readonly isPlaybackLeaseCurrent?: (lease: PlaybackLease) => boolean;
  readonly onResult?: (result: ChapterPlaybackRequestResult) => void;
  readonly disposePlayer?: boolean;
}


export interface ChapterPlaybackRequest {
  readonly source: PlaybackIntentSource;
  readonly lookup: PlaybackLookup;
}


export interface ChapterPlaybackCoordinator {
  readonly bridge: NarrationEditorBridge;
  readonly player: NarrationPlayerController;
  readFence(): PlaybackLease | null;
  requestPlayback(request: ChapterPlaybackRequest): Promise<ChapterPlaybackRequestResult>;
  requestOrdinaryEditorClick(lookup: PlaybackLookup): PlaybackIntentResult;
  isFenceCurrent(fence: PlaybackLease): boolean;
  dispose(): void;
}


function freezePlaybackLease(lease: PlaybackLease): PlaybackLease {
  return Object.freeze({ ...lease });
}


function freezeDocumentLease(lease: DocumentLease): DocumentLease {
  return Object.freeze({ ...lease });
}


export function playbackLeaseMatchesDocument(
  playbackLease: PlaybackLease,
  documentLease: DocumentLease,
  editionId: string,
): boolean {
  return playbackLease.documentId === documentLease.documentId
    && playbackLease.documentGeneration === documentLease.generation
    && playbackLease.editionId === editionId;
}


export function staleChapterPlaybackReason(
  expected: PlaybackLease,
  actual: PlaybackLease,
): Extract<ChapterPlaybackRequestResult, { status: "stale" }>["reason"] {
  if (
    expected.documentId !== actual.documentId
    || expected.documentGeneration !== actual.documentGeneration
  ) return "document_generation_changed";
  if (expected.editionId !== actual.editionId) return "edition_changed";
  if (expected.manifestRevision !== actual.manifestRevision) {
    return "manifest_revision_changed";
  }
  return "request_superseded";
}


function playbackSource(intent: PlaybackIntent): NarrationPlaybackSource {
  return intent.source;
}


export class ProductionChapterPlaybackCoordinator implements ChapterPlaybackCoordinator {
  readonly bridge: NarrationEditorBridge;
  readonly player: NarrationPlayerController;

  private readonly operations = new WeakMap<PlaybackIntent, Promise<ChapterPlaybackRequestResult>>();
  private readonly isPlaybackLeaseCurrentExternal: (lease: PlaybackLease) => boolean;
  private readonly unsubscribeIntent: () => void;
  private disposed = false;

  constructor(private readonly options: ChapterPlaybackCoordinatorOptions) {
    this.bridge = options.bridge;
    this.player = options.player;
    this.isPlaybackLeaseCurrentExternal = options.isPlaybackLeaseCurrent ?? (() => true);
    this.unsubscribeIntent = this.bridge.registerPlaybackIntent((intent) => {
      const operation = this.executeIntent(intent);
      this.operations.set(intent, operation);
      void operation.then((result) => this.publishResult(result));
    });
  }

  readFence(): PlaybackLease | null {
    if (this.disposed) return null;
    const snapshot = this.bridge.readSnapshot();
    const editionId = snapshot.edition?.editionId;
    if (!snapshot.active || !editionId) return null;
    const lease = freezePlaybackLease(this.player.lease);
    if (!playbackLeaseMatchesDocument(lease, this.bridge.lease, editionId)) return null;
    if (!this.externalFenceCurrent(lease)) return null;
    return lease;
  }

  async requestPlayback(
    request: ChapterPlaybackRequest,
  ): Promise<ChapterPlaybackRequestResult> {
    const fence = this.readFence();
    if (this.disposed) {
      return Object.freeze({ status: "rejected", reason: "coordinator_disposed", fence });
    }
    const snapshot = this.bridge.readSnapshot();
    const result = this.bridge.requestPlayback({
      lease: freezeDocumentLease(this.bridge.lease),
      editionId: snapshot.edition?.editionId,
      source: request.source,
      lookup: request.lookup,
    });
    if (!result.accepted) {
      return Object.freeze({ status: "rejected", reason: result.reason, fence });
    }
    const operation = this.operations.get(result.intent);
    if (!operation) {
      return Object.freeze({
        status: "rejected",
        reason: "intent_listener_unavailable",
        fence,
      });
    }
    return operation;
  }

  requestOrdinaryEditorClick(lookup: PlaybackLookup): PlaybackIntentResult {
    const snapshot = this.bridge.readSnapshot();
    return this.bridge.requestPlayback({
      lease: freezeDocumentLease(this.bridge.lease),
      editionId: snapshot.edition?.editionId,
      source: "editor-click",
      lookup,
    });
  }

  isFenceCurrent(fence: PlaybackLease): boolean {
    if (this.disposed) return false;
    const current = this.readFence();
    return current !== null && playbackLeasesEqual(current, fence);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.unsubscribeIntent();
    if (this.options.disposePlayer) this.player.dispose();
  }

  private async executeIntent(intent: PlaybackIntent): Promise<ChapterPlaybackRequestResult> {
    const before = this.readFence();
    if (!before) {
      const playerLease = freezePlaybackLease(this.player.lease);
      return Object.freeze({
        status: "stale",
        reason: this.classifyUnavailableFence(intent, playerLease),
        fence: playerLease,
      });
    }
    if (!playbackLeaseMatchesDocument(before, intent.lease, intent.editionId)) {
      return Object.freeze({
        status: "stale",
        reason: before.editionId === intent.editionId
          ? "document_generation_changed"
          : "edition_changed",
        fence: before,
      });
    }

    let pending: Promise<PlaybackDecision>;
    try {
      pending = this.player.playFromSegment(intent.segmentId, playbackSource(intent));
    } catch (error) {
      return Object.freeze({
        status: "failed",
        reason: "player_rejected_request" as const,
        fence: before,
        error,
      });
    }
    const issued = freezePlaybackLease(this.player.lease);
    if (
      issued.documentId !== before.documentId
      || issued.documentGeneration !== before.documentGeneration
      || issued.editionId !== before.editionId
      || issued.manifestRevision !== before.manifestRevision
      || issued.requestGeneration !== before.requestGeneration + 1
    ) {
      return Object.freeze({
        status: "stale",
        reason: staleChapterPlaybackReason(before, issued),
        fence: issued,
      });
    }

    try {
      const decision = await pending;
      if (!playbackLeasesEqual(decision.lease, issued)) {
        return Object.freeze({
          status: "stale",
          reason: staleChapterPlaybackReason(issued, decision.lease),
          fence: decision.lease,
        });
      }
      const current = this.readFence();
      if (!current || !playbackLeasesEqual(current, issued)) {
        const actual = freezePlaybackLease(this.player.lease);
        return Object.freeze({
          status: "stale",
          reason: current
            ? staleChapterPlaybackReason(issued, current)
            : this.externalFenceCurrent(issued)
              ? this.classifyUnavailableFence(intent, actual)
              : "external_fence_rejected",
          fence: issued,
        });
      }
      return Object.freeze({
        status: "completed",
        intent,
        fence: issued,
        decision,
      });
    } catch (error) {
      if (!this.isFenceCurrent(issued)) {
        return Object.freeze({
          status: "stale",
          reason: "request_superseded",
          fence: issued,
        });
      }
      return Object.freeze({
        status: "failed",
        reason: "player_rejected_request" as const,
        fence: issued,
        error,
      });
    }
  }

  private classifyUnavailableFence(
    intent: PlaybackIntent,
    actual: PlaybackLease,
  ): Extract<ChapterPlaybackRequestResult, { status: "stale" }>["reason"] {
    if (
      actual.documentId !== intent.lease.documentId
      || actual.documentGeneration !== intent.lease.generation
    ) return "document_generation_changed";
    if (actual.editionId !== intent.editionId) return "edition_changed";
    if (!this.externalFenceCurrent(actual)) return "external_fence_rejected";
    return "request_superseded";
  }

  private externalFenceCurrent(lease: PlaybackLease): boolean {
    try {
      return this.isPlaybackLeaseCurrentExternal(lease);
    } catch {
      return false;
    }
  }

  private publishResult(result: ChapterPlaybackRequestResult): void {
    try {
      this.options.onResult?.(result);
    } catch {
      // Result observers are presentation-only and must not break playback.
    }
  }
}


export function createChapterPlaybackCoordinator(
  options: ChapterPlaybackCoordinatorOptions,
): ChapterPlaybackCoordinator {
  return new ProductionChapterPlaybackCoordinator(options);
}
