import type {
  FollowFailureReason,
  NarrationEditorBridge,
} from "./editor-bridge";
import type {
  NarrationPlayerController,
  NarrationPlayerState,
} from "./narration-player";
import {
  playbackLeasesEqual,
  type PlaybackLease,
} from "./segment-playback-queue";
import { playbackLeaseMatchesDocument } from "./chapter-playback";


export type AuthorFollowInterruption =
  | "manual-scroll"
  | "caret-move"
  | "selection"
  | "input"
  | "composition";


export type SegmentFollowInactiveReason =
  | "disposed"
  | "stale_playback_lease"
  | "edition_mismatch"
  | "document_generation_changed";


export interface SegmentFollowState {
  readonly active: boolean;
  readonly paused: boolean;
  readonly resumeVisible: boolean;
  readonly pausedBy: AuthorFollowInterruption | null;
  readonly currentSegmentId: string | null;
  readonly lastAppliedFence: PlaybackLease | null;
  readonly lastFailure: FollowFailureReason | SegmentFollowInactiveReason | null;
}


export interface FollowAwareNarrationPlayerController extends NarrationPlayerController {
  setFollowPaused?(paused: boolean): void;
}


export interface SegmentFollowControllerOptions {
  readonly bridge: NarrationEditorBridge;
  readonly player: FollowAwareNarrationPlayerController;
  readonly editionId: string;
  readonly isPlaybackLeaseCurrent?: (lease: PlaybackLease) => boolean;
  readonly resumeOnExplicitPlayback?: boolean;
}


export interface SegmentFollowController {
  readState(): SegmentFollowState;
  noteAuthorInteraction(interruption: AuthorFollowInterruption): boolean;
  resumeExplicitly(): boolean;
  synchronizeNow(): void;
  subscribe(listener: (state: SegmentFollowState) => void): () => void;
  dispose(): void;
}


function freezePlaybackLease(lease: PlaybackLease): PlaybackLease {
  return Object.freeze({ ...lease });
}


function freezeState(state: SegmentFollowState): SegmentFollowState {
  return Object.freeze({
    ...state,
    lastAppliedFence: state.lastAppliedFence
      ? freezePlaybackLease(state.lastAppliedFence)
      : null,
  });
}


export class ProductionSegmentFollowController implements SegmentFollowController {
  private readonly listeners = new Set<(state: SegmentFollowState) => void>();
  private readonly isPlaybackLeaseCurrentExternal: (lease: PlaybackLease) => boolean;
  private readonly unsubscribePlayer: () => void;
  private state: SegmentFollowState;
  private lastPresentedSegmentId: string | null = null;
  private lastPlaybackRequestGeneration: number;
  private synchronizing = false;
  private disposed = false;

  constructor(private readonly options: SegmentFollowControllerOptions) {
    if (!options.editionId.trim()) throw new TypeError("editionId must not be empty");
    this.isPlaybackLeaseCurrentExternal = options.isPlaybackLeaseCurrent ?? (() => true);
    this.lastPlaybackRequestGeneration = options.player.lease.requestGeneration;
    const snapshot = options.bridge.readSnapshot();
    this.state = freezeState({
      active: snapshot.active,
      paused: snapshot.autoFollowPaused,
      resumeVisible: snapshot.autoFollowPaused,
      pausedBy: null,
      currentSegmentId: snapshot.currentSegmentId,
      lastAppliedFence: null,
      lastFailure: snapshot.inactiveReason,
    });
    this.unsubscribePlayer = options.player.subscribe(() => this.synchronizeNow());
    this.synchronizeNow();
  }

  readState(): SegmentFollowState {
    return this.state;
  }

  noteAuthorInteraction(interruption: AuthorFollowInterruption): boolean {
    const fence = this.currentFence();
    if (!fence) {
      this.publish({
        active: false,
        lastFailure: this.inactiveReason(),
      });
      return false;
    }
    const result = this.options.bridge.noteManualScroll();
    if (!result.applied) {
      this.publish({ active: false, lastFailure: result.reason });
      return false;
    }
    this.setPlayerFollowPaused(true);
    this.publish({
      active: true,
      paused: true,
      resumeVisible: true,
      pausedBy: interruption,
      lastAppliedFence: fence,
      lastFailure: null,
    });
    return true;
  }

  resumeExplicitly(): boolean {
    const fence = this.currentFence();
    if (!fence) {
      this.publish({ active: false, lastFailure: this.inactiveReason() });
      return false;
    }
    const resumed = this.options.bridge.resumeAutoFollow();
    if (!resumed.applied) {
      this.publish({ active: false, lastFailure: resumed.reason });
      return false;
    }
    this.setPlayerFollowPaused(false);
    this.publish({
      active: true,
      paused: false,
      resumeVisible: false,
      pausedBy: null,
      lastAppliedFence: fence,
      lastFailure: null,
    });
    this.presentCurrentSegment(this.options.player.readState(), fence, true);
    return true;
  }

  synchronizeNow(): void {
    if (this.disposed || this.synchronizing) return;
    this.synchronizing = true;
    try {
      const fence = this.currentFence();
      if (!fence) {
        this.publish({
          active: false,
          lastFailure: this.inactiveReason(),
        });
        return;
      }
      const playerState = this.options.player.readState();
      const bridgeSnapshot = this.options.bridge.readSnapshot();
      const isNewPlayback = fence.requestGeneration !== this.lastPlaybackRequestGeneration;
      if (isNewPlayback) {
        this.lastPresentedSegmentId = null;
      }
      if (
        isNewPlayback
        && (this.options.resumeOnExplicitPlayback ?? true)
        && playerState.phase === "playing"
      ) {
        this.lastPlaybackRequestGeneration = fence.requestGeneration;
        this.options.bridge.resumeAutoFollow();
        this.setPlayerFollowPaused(false);
      } else if (isNewPlayback && playerState.phase === "playing") {
        this.lastPlaybackRequestGeneration = fence.requestGeneration;
      } else if (bridgeSnapshot.autoFollowPaused && !playerState.followPaused) {
        this.setPlayerFollowPaused(true);
      }
      const paused = this.options.bridge.readSnapshot().autoFollowPaused;
      this.publish({
        active: true,
        paused,
        resumeVisible: paused,
        pausedBy: paused ? this.state.pausedBy : null,
        currentSegmentId: playerState.currentSegmentId,
        lastAppliedFence: fence,
        lastFailure: null,
      });
      if (playerState.phase === "playing" && playerState.currentSegmentId) {
        this.presentCurrentSegment(playerState, fence, false);
      }
    } finally {
      this.synchronizing = false;
    }
  }

  subscribe(listener: (state: SegmentFollowState) => void): () => void {
    if (this.disposed) return () => undefined;
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.unsubscribePlayer();
    this.listeners.clear();
    this.state = freezeState({
      ...this.state,
      active: false,
      lastFailure: "disposed",
    });
  }

  private presentCurrentSegment(
    playerState: NarrationPlayerState,
    fence: PlaybackLease,
    forceScroll: boolean,
  ): void {
    const segmentId = playerState.currentSegmentId;
    if (!segmentId || !this.isFenceCurrent(fence)) return;
    const shouldPresent = forceScroll || segmentId !== this.lastPresentedSegmentId;
    if (!shouldPresent) return;
    const alreadyMarked = this.options.bridge.readSnapshot().currentSegmentId === segmentId;
    if (!alreadyMarked) {
      const marked = this.options.bridge.markCurrentSegment({
        lease: this.options.bridge.lease,
        editionId: this.options.editionId,
        segmentId,
      });
      if (!marked.applied) {
        this.publish({
          currentSegmentId: segmentId,
          lastAppliedFence: fence,
          lastFailure: marked.reason,
        });
        return;
      }
    }
    this.lastPresentedSegmentId = segmentId;
    const paused = this.options.bridge.readSnapshot().autoFollowPaused;
    let followFailure: FollowFailureReason | null = null;
    if (!paused || forceScroll) {
      const scrolled = this.options.bridge.scrollCurrentSegmentIntoView({
        lease: this.options.bridge.lease,
        editionId: this.options.editionId,
      });
      if (!scrolled.applied && scrolled.reason !== "composition") {
        followFailure = scrolled.reason;
      }
    }
    this.publish({
      currentSegmentId: segmentId,
      paused: this.options.bridge.readSnapshot().autoFollowPaused,
      resumeVisible: this.options.bridge.readSnapshot().autoFollowPaused,
      lastAppliedFence: fence,
      lastFailure: followFailure,
    });
  }

  private currentFence(): PlaybackLease | null {
    if (this.disposed) return null;
    const bridgeSnapshot = this.options.bridge.readSnapshot();
    if (!bridgeSnapshot.active || bridgeSnapshot.edition?.editionId !== this.options.editionId) {
      return null;
    }
    const first = freezePlaybackLease(this.options.player.lease);
    if (!playbackLeaseMatchesDocument(
      first,
      this.options.bridge.lease,
      this.options.editionId,
    )) return null;
    try {
      if (!this.isPlaybackLeaseCurrentExternal(first)) return null;
    } catch {
      return null;
    }
    return playbackLeasesEqual(first, this.options.player.lease) ? first : null;
  }

  private isFenceCurrent(fence: PlaybackLease): boolean {
    const current = this.currentFence();
    return current !== null && playbackLeasesEqual(current, fence);
  }

  private inactiveReason(): SegmentFollowInactiveReason {
    if (this.disposed) return "disposed";
    const snapshot = this.options.bridge.readSnapshot();
    if (
      this.options.player.lease.documentId !== this.options.bridge.lease.documentId
      || this.options.player.lease.documentGeneration !== this.options.bridge.lease.generation
      || !snapshot.active
    ) return "document_generation_changed";
    if (
      this.options.player.lease.editionId !== this.options.editionId
      || snapshot.edition?.editionId !== this.options.editionId
    ) return "edition_mismatch";
    return "stale_playback_lease";
  }

  private setPlayerFollowPaused(paused: boolean): void {
    if (this.options.player.readState().followPaused === paused) return;
    this.options.player.setFollowPaused?.(paused);
  }

  private publish(patch: Partial<SegmentFollowState>): void {
    if (this.disposed) return;
    const next = freezeState({ ...this.state, ...patch });
    const changed = next.active !== this.state.active
      || next.paused !== this.state.paused
      || next.resumeVisible !== this.state.resumeVisible
      || next.pausedBy !== this.state.pausedBy
      || next.currentSegmentId !== this.state.currentSegmentId
      || next.lastFailure !== this.state.lastFailure
      || (
        next.lastAppliedFence === null
          ? this.state.lastAppliedFence !== null
          : this.state.lastAppliedFence === null
            || !playbackLeasesEqual(next.lastAppliedFence, this.state.lastAppliedFence)
      );
    this.state = next;
    if (!changed) return;
    for (const listener of [...this.listeners]) listener(this.state);
  }
}


export function createSegmentFollowController(
  options: SegmentFollowControllerOptions,
): SegmentFollowController {
  return new ProductionSegmentFollowController(options);
}
