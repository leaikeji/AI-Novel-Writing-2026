import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { canonicalJson } from "../src/contracts.mjs";
import {
  actualContextMenuSeek,
  actualEditRoundTrip,
  actualKeyboardSeek,
  actualPendingGap,
  actualPlayerControls,
  assertStableBrowserIdentity,
  collectFixedLayoutObservation,
  collectFixedInteractionEvidence,
  differentEditorEdge,
  fixedRouteDecision,
  isObserverInducedPolicyConsole,
  isObserverInducedRangeConsole,
  isSafeFixedEditorPlayerOverlay,
  recordFixedPolicyBlockedUrl,
  summarizeFixedLayoutGeometry,
} from "../src/observer.mjs";


const PLAYER_SELECTOR = ".anw-chapter-narration-player[aria-label=\"\u7ae0\u8282\u667a\u80fd\u6717\u8bfb\u64ad\u653e\u5668\"]";
const PLAY_SELECTOR = `${PLAYER_SELECTOR} button[aria-label=\"\u64ad\u653e\u7ae0\u8282\u6717\u8bfb\"]`;
const PAUSE_SELECTOR = `${PLAYER_SELECTOR} button[aria-label=\"\u6682\u505c\u7ae0\u8282\u6717\u8bfb\"]`;


const PREVIOUS_SELECTOR = `${PLAYER_SELECTOR} button[aria-label="朗读上一句"]`;
const NEXT_SELECTOR = `${PLAYER_SELECTOR} button[aria-label="朗读下一句"]`;


class PlayerControlLocator {
  constructor(page, kind) {
    this.page = page;
    this.kind = kind;
  }

  async count() { return this.kind === "absent" ? 0 : 1; }
  async isEnabled() { return true; }
  async isVisible() {
    if (this.kind === "player") return true;
    if (this.kind === "play") return this.page.phase === "paused";
    if (this.kind === "pause") return this.page.phase === "playing";
    return false;
  }
  async click() {
    if (this.kind === "play") this.page.phase = "playing";
    if (this.kind === "pause" && this.page.pauseWorks) this.page.phase = "paused";
  }
}


class PlayerControlPage {
  constructor({ pauseWorks }) {
    this.pauseWorks = pauseWorks;
    this.phase = "paused";
    this.waits = [];
  }

  locator(selector) {
    if (selector === PLAYER_SELECTOR) return new PlayerControlLocator(this, "player");
    if (selector === PLAY_SELECTOR) return new PlayerControlLocator(this, "play");
    if (selector === PAUSE_SELECTOR) return new PlayerControlLocator(this, "pause");
    return new PlayerControlLocator(this, "absent");
  }

  async waitForTimeout(milliseconds) { this.waits.push(milliseconds); }
}


test("browser executable and signature identity must remain stable through observation", () => {
  const codesign = Object.freeze({
    cdhash: "fixed",
    deep_verified: true,
    gatekeeper_accepted: true,
    gatekeeper_override_security_disabled: true,
    gatekeeper_result_sha256: "a".repeat(64),
    gatekeeper_source_notarized_developer_id: true,
    identifier: "com.microsoft.edgemac",
    strict_result_sha256: "b".repeat(64),
    strict_verified: false,
    team_identifier: "UBF8T346G9",
  });
  const executableSha256 = "c".repeat(64);

  assert.doesNotThrow(() => assertStableBrowserIdentity(
    codesign,
    executableSha256,
    { ...codesign },
    executableSha256,
  ));
  assert.throws(
    () => assertStableBrowserIdentity(
      codesign,
      executableSha256,
      { ...codesign, cdhash: "changed" },
      executableSha256,
    ),
    /OBSERVER_EDGE_IDENTITY_CHANGED/u,
  );
  assert.throws(
    () => assertStableBrowserIdentity(
      codesign,
      executableSha256,
      codesign,
      "d".repeat(64),
    ),
    /OBSERVER_EDGE_IDENTITY_CHANGED/u,
  );
});


const observedSeek = Object.freeze({
  command_dispatched: true,
  elapsed_ms: 12,
  status: "observed",
  target_changed: true,
});
const observedLatestWins = Object.freeze({
  elapsed_ms: 20,
  final_target_won: true,
  first_dispatch_observed: true,
  second_dispatch_observed: true,
  status: "observed",
});
const observedControls = Object.freeze({
  elapsed_ms: 30,
  pause_observed: true,
  play_observed: true,
  rate_change_observed: true,
  seek_observed: true,
  status: "observed",
});
const observedEdit = Object.freeze({
  after_sha256: "a".repeat(64),
  before_sha256: "a".repeat(64),
  editor_restored: true,
  elapsed_ms: 40,
  status: "observed",
  tts_write_request_count: 0,
});
const observedMedia = Object.freeze({
  elapsed_ms: 50,
  etag_observed: true,
  if_none_match_304: true,
  if_range_206: true,
  range_206: true,
  request_count: 5,
  status: "observed",
  unsatisfied_range_416: true,
});


test("context-menu seek selects an absolute editor edge different from persisted progress", () => {
  assert.equal(differentEditorEdge(0, 58), "end");
  assert.equal(differentEditorEdge(1, 58), "start");
  assert.equal(differentEditorEdge(58, 58), "start");
  assert.equal(differentEditorEdge(null, 58), null);
  assert.equal(differentEditorEdge(0, 0), null);
  assert.equal(differentEditorEdge(59, 58), null);
});


const TIMELINE_SEEK_SELECTOR = `${PLAYER_SELECTOR} input[type="range"][aria-label="按句段跳转章节朗读位置"]`;
const EDITOR_CONTENT_SELECTOR = ".anw-chapter-editor-surface .cm-content[contenteditable=\"true\"]";
const CONTEXT_MENU_COMMAND_SELECTOR = ".anw-narration-paragraph-context-menu[role=\"menu\"] button[role=\"menuitem\"]";


class ContextMenuSeekLocator {
  constructor(page, kind) { this.page = page; this.kind = kind; }
  async count() { return 1; }
  async isVisible() { return this.kind !== "command" || this.page.menuVisible; }
  async isEnabled() { return true; }
  async inputValue() {
    return this.page.timelineReady ? String(this.page.ordinal) : "";
  }
  async getAttribute(name) {
    assert.equal(name, "max");
    return this.page.timelineReady ? String(this.page.maximum) : "0";
  }
  async boundingBox() { return { x: 0, y: 0, width: 500, height: 400 }; }
  async press(key) {
    this.page.presses.push(key);
    if (key === "Meta+Alt+Enter" && this.page.applyCommand) {
      this.page.ordinal = this.page.targetOrdinal;
    }
  }
  async click(options) {
    if (this.kind === "editor") {
      this.page.editorClicks.push(options ?? null);
      if (options?.button === "right") this.page.menuVisible = true;
      return;
    }
    if (this.kind === "command") {
      this.page.commandClicks += 1;
      if (this.page.applyCommand) this.page.ordinal = this.page.targetOrdinal;
    }
  }
}


class ContextMenuSeekPage {
  constructor({ initialOrdinal, maximum, targetOrdinal, applyCommand = true, applyAfterWaits = null, readyAfterWaits = null }) {
    this.ordinal = initialOrdinal;
    this.maximum = maximum;
    this.targetOrdinal = targetOrdinal;
    this.applyCommand = applyCommand;
    this.applyAfterWaits = applyAfterWaits;
    this.readyAfterWaits = readyAfterWaits;
    this.timelineReady = readyAfterWaits === null;
    this.menuVisible = false;
    this.commandClicks = 0;
    this.editorClicks = [];
    this.presses = [];
    this.waits = [];
  }
  locator(selector) {
    if (selector === TIMELINE_SEEK_SELECTOR) return new ContextMenuSeekLocator(this, "timeline");
    if (selector === EDITOR_CONTENT_SELECTOR) return new ContextMenuSeekLocator(this, "editor");
    if (selector === CONTEXT_MENU_COMMAND_SELECTOR) return new ContextMenuSeekLocator(this, "command");
    throw new Error(`unexpected selector: ${selector}`);
  }
  async waitForTimeout(milliseconds) {
    this.waits.push(milliseconds);
    if (
      Number.isSafeInteger(this.readyAfterWaits)
      && this.waits.length === this.readyAfterWaits
    ) this.timelineReady = true;
    if (
      Number.isSafeInteger(this.applyAfterWaits)
      && this.waits.length === this.applyAfterWaits
    ) this.ordinal = this.targetOrdinal;
  }
}


test("context-menu seek moves persisted chapter-end progress to the real document start", async () => {
  const page = new ContextMenuSeekPage({ initialOrdinal: 58, maximum: 58, targetOrdinal: 0 });

  const result = await actualContextMenuSeek(page, "codemirror6");

  assert.equal(result.command_dispatched, true);
  assert.equal(result.target_changed, true);
  assert.equal(page.commandClicks, 1);
  assert.deepEqual(page.presses, ["Meta+ArrowUp"]);
  assert.equal(page.editorClicks.at(-1).button, "right");
  assert.equal(page.editorClicks.at(-1).position.y, 12);
});


test("context-menu seek moves persisted chapter-start progress to the real document end", async () => {
  const page = new ContextMenuSeekPage({ initialOrdinal: 0, maximum: 58, targetOrdinal: 58 });

  const result = await actualContextMenuSeek(page, "codemirror6");

  assert.equal(result.target_changed, true);
  assert.deepEqual(page.presses, ["Meta+ArrowDown"]);
  assert.equal(page.editorClicks.at(-1).position.y, 388);
});


test("context-menu seek remains failed when the real command leaves ordinal unchanged", async () => {
  const page = new ContextMenuSeekPage({
    initialOrdinal: 58,
    maximum: 58,
    targetOrdinal: 0,
    applyCommand: false,
  });

  const result = await actualContextMenuSeek(page, "codemirror6");

  assert.equal(result.command_dispatched, true);
  assert.equal(result.target_changed, false);
  assert.equal(page.commandClicks, 1);
  assert.equal(page.waits.length, 200);
  assert.ok(page.waits.every((value) => value === 25));
});


test("context-menu seek accepts a production ordinal that settles after one second", async () => {
  const page = new ContextMenuSeekPage({
    initialOrdinal: 58,
    maximum: 58,
    targetOrdinal: 0,
    applyCommand: false,
    applyAfterWaits: 60,
  });

  const result = await actualContextMenuSeek(page, "codemirror6");

  assert.equal(result.command_dispatched, true);
  assert.equal(result.target_changed, true);
  assert.equal(page.waits.length, 60);
});


test("context-menu seek waits for the production timeline before choosing an edge", async () => {
  const page = new ContextMenuSeekPage({
    initialOrdinal: 58,
    maximum: 58,
    targetOrdinal: 0,
    readyAfterWaits: 25,
  });

  const result = await actualContextMenuSeek(page, "codemirror6");

  assert.equal(result.command_dispatched, true);
  assert.equal(result.target_changed, true);
  assert.equal(page.waits.length, 25);
  assert.equal(page.presses.at(-1), "Meta+ArrowUp");
});


test("cursor keyboard seek selects the edge opposite the context-menu result", async () => {
  const page = new ContextMenuSeekPage({ initialOrdinal: 58, maximum: 58, targetOrdinal: 0 });
  const context = await actualContextMenuSeek(page, "codemirror6");
  page.targetOrdinal = 58;

  const keyboard = await actualKeyboardSeek(page, "codemirror6");

  assert.equal(context.target_changed, true);
  assert.equal(keyboard.command_dispatched, true);
  assert.equal(keyboard.target_changed, true);
  assert.equal(page.ordinal, 58);
  assert.deepEqual(page.presses, [
    "Meta+ArrowUp",
    "Meta+ArrowDown",
    "Meta+Alt+Enter",
  ]);
});


test("cursor keyboard seek remains failed when its command leaves ordinal unchanged", async () => {
  const page = new ContextMenuSeekPage({
    initialOrdinal: 0,
    maximum: 58,
    targetOrdinal: 58,
    applyCommand: false,
  });

  const result = await actualKeyboardSeek(page, "codemirror6");

  assert.equal(result.command_dispatched, true);
  assert.equal(result.target_changed, false);
  assert.deepEqual(page.presses, ["Meta+ArrowDown", "Meta+Alt+Enter"]);
  assert.equal(page.waits.length, 200);
});


class MockLocator {
  async count() { return 1; }
  async getAttribute() { return ""; }
  async isVisible() { return true; }
}


class MockPage {
  constructor() {
    this.waits = [];
  }

  locator(selector) {
    assert.equal(
      selector,
      ".anw-chapter-narration-player[aria-label=\"章节智能朗读播放器\"]",
    );
    return new MockLocator();
  }

  async waitForTimeout(milliseconds) {
    this.waits.push(milliseconds);
  }
}


test("player controls observe pause only after the paused UI state returns", async () => {
  const page = new PlayerControlPage({ pauseWorks: true });
  const result = await actualPlayerControls(page);
  assert.equal(result.play_observed, true);
  assert.equal(result.pause_observed, true);
  assert.equal(page.phase, "paused");
});


test("player controls fail pause observation when the pause handler has no effect", async () => {
  const page = new PlayerControlPage({ pauseWorks: false });
  const result = await actualPlayerControls(page);
  assert.equal(result.play_observed, true);
  assert.equal(result.pause_observed, false);
  assert.equal(page.phase, "playing");
  assert.equal(page.waits.filter((value) => value === 100).length, 20);
});


class EditRoundTripLocator {
  constructor(page) {
    this.page = page;
  }

  async boundingBox() {
    return { height: 600, width: 900, x: 0, y: 0 };
  }

  async click() {
    this.page.events.push("click");
  }

  async evaluate() {}

  async press(key) {
    this.page.events.push(key);
    if (key === "Space" && this.page.applyInsert) this.page.digest = "b".repeat(64);
    if (key === "Meta+z" && this.page.applyUndo) this.page.digest = this.page.originalDigest;
  }
}


class EditDigestSurfaceLocator {
  constructor(page) {
    this.page = page;
  }

  async getAttribute(name) {
    assert.equal(name, "data-editor-value-sha256");
    return this.page.digest;
  }
}


class EditRoundTripPage {
  constructor({
    applyInsert = true,
    applyUndo = true,
    editorKind = "codemirror6",
    initialDigest = "a".repeat(64),
  } = {}) {
    this.applyInsert = applyInsert;
    this.applyUndo = applyUndo;
    this.editorKind = editorKind;
    this.events = [];
    this.originalDigest = initialDigest;
    this.digest = initialDigest;
    this.editor = new EditRoundTripLocator(this);
    this.digestSurface = new EditDigestSurfaceLocator(this);
  }

  locator(selector) {
    if (selector === ".anw-chapter-editor-surface") return this.digestSurface;
    const expected = this.editorKind === "codemirror6"
      ? ".anw-chapter-editor-surface .cm-content[contenteditable=\"true\"]"
      : ".anw-chapter-editor-surface textarea.anw-chapter-editor-textarea-fallback";
    assert.equal(selector, expected);
    return this.editor;
  }

  async waitForTimeout(milliseconds) {
    assert.equal(milliseconds, 25);
  }
}


test("fixed interaction recipe produces exact evidence from a mocked browser", async () => {
  const marker = new MockPage();
  const networkState = { mediaCandidate: null, ttsWriteRequestCount: 0 };
  const evidence = await collectFixedInteractionEvidence(marker, networkState, {
    contextMenuSeek: async (page, kind) => {
      assert.equal(page, marker);
      assert.equal(kind, "codemirror6");
      return observedSeek;
    },
    detectEditorKind: async (page) => {
      assert.equal(page, marker);
      return "codemirror6";
    },
    editRoundTrip: async (page, kind, state) => {
      assert.equal(page, marker);
      assert.equal(kind, "codemirror6");
      assert.equal(state, networkState);
      return observedEdit;
    },
    keyboardSeek: async () => observedSeek,
    latestWins: async () => observedLatestWins,
    mediaContract: async () => observedMedia,
    playerControls: async () => observedControls,
  });
  assert.deepEqual(Object.keys(evidence).sort(), [
    "controls",
    "cursor_keyboard_seek",
    "edit_without_tts_write",
    "editor",
    "latest_wins",
    "media_http",
    "paragraph_context_menu_seek",
    "pending_gap",
    "player",
  ]);
  assert.deepEqual(evidence.editor, {
    codemirror_observed: true,
    kind: "codemirror6",
    textarea_fallback_observed: false,
  });
  assert.deepEqual(evidence.pending_gap, {
    reason_code: "STATE_UNAVAILABLE",
    status: "not_observed",
    stop_before_gap_observed: false,
  });
  assert.equal(evidence.player.visible, true);
  assert.equal(evidence.edit_without_tts_write.tts_write_request_count, 0);
  assert.equal(evidence.media_http.if_none_match_304, true);
  assert.deepEqual(marker.waits, [2_000]);
});


const TIMELINE_SELECTOR = `${PLAYER_SELECTOR} input[type="range"][aria-label="\u6309\u53e5\u6bb5\u8df3\u8f6c\u7ae0\u8282\u6717\u8bfb\u4f4d\u7f6e"]`;


class PendingGapPlayerLocator {
  constructor(page) { this.page = page; }

  async count() { return 1; }
  async isVisible() { return true; }
  async getAttribute(name) {
    const snapshot = this.page.snapshots[this.page.snapshotIndex];
    const values = {
      "data-current-ordinal": snapshot.ordinal,
      "data-player-failure-code": snapshot.failure,
      "data-player-phase": snapshot.phase,
      "data-segment-states": snapshot.states,
    };
    return values[name] ?? null;
  }
}


class PendingGapTimelineLocator {
  constructor(page) { this.page = page; }

  async count() { return 1; }
  async isEnabled() { return true; }
  async isVisible() { return true; }
  async inputValue() { return String(this.page.timelineValue); }
  async getAttribute(name) {
    if (name === "min") return "0";
    assert.equal(name, "max");
    return String(this.page.maximum);
  }
  async press(key) {
    if (key === "Home") this.page.timelineValue = 0;
    else if (key === "End") this.page.timelineValue = this.page.maximum;
    else if (key === "ArrowRight") {
      this.page.timelineValue = Math.min(
        this.page.maximum,
        this.page.timelineValue + 1,
      );
    } else if (key === "ArrowLeft") {
      this.page.timelineValue = Math.max(0, this.page.timelineValue - 1);
    }
    else assert.fail(`unexpected range key ${key}`);
    this.page.dispatched.push(this.page.timelineValue);
    if (this.page.snapshots.length > 1) this.page.snapshotIndex = 1;
  }
}


class PendingGapCommandLocator {
  constructor(page, direction) {
    this.page = page;
    this.direction = direction;
  }

  async count() { return 1; }
  async isEnabled() { return true; }
  async isVisible() { return true; }
  async click() { this.page.commands.push(this.direction); }
}


class PendingGapPage {
  constructor(snapshots, { maximum = 5 } = {}) {
    this.maximum = maximum;
    this.snapshots = snapshots;
    this.snapshotIndex = 0;
    this.timelineValue = 0;
    this.dispatched = [];
    this.commands = [];
    this.waits = [];
    this.player = new PendingGapPlayerLocator(this);
    this.timeline = new PendingGapTimelineLocator(this);
    this.previous = new PendingGapCommandLocator(this, "previous");
    this.next = new PendingGapCommandLocator(this, "next");
    this.play = new PendingGapCommandLocator(this, "play");
  }

  locator(selector) {
    if (selector === PLAYER_SELECTOR) return this.player;
    if (selector === TIMELINE_SELECTOR) return this.timeline;
    if (selector === PREVIOUS_SELECTOR) return this.previous;
    if (selector === NEXT_SELECTOR) return this.next;
    if (selector === PLAY_SELECTOR) return this.play;
    return new PlayerControlLocator(this, "absent");
  }

  async waitForTimeout(milliseconds) {
    assert.equal(milliseconds, 100);
    this.waits.push(milliseconds);
    if (this.snapshotIndex < this.snapshots.length - 1) this.snapshotIndex += 1;
  }
}


function gapSnapshot({
  failure = "",
  ordinal = "",
  phase = "idle",
  states = "ready,ready,ready,ready,pending,ready",
} = {}) {
  return Object.freeze({ failure, ordinal, phase, states });
}


test("pending-gap probe follows real locator state through the ready boundary and stops before it", async () => {
  const page = new PendingGapPage([
    gapSnapshot({ ordinal: "0" }),
    gapSnapshot({ ordinal: "1", phase: "buffering" }),
    gapSnapshot({ ordinal: "1", phase: "playing" }),
    gapSnapshot({ failure: "PENDING_GAP", ordinal: "3", phase: "blocked" }),
  ]);

  const result = await actualPendingGap(page);

  assert.deepEqual(result, {
    reason_code: "OBSERVED",
    status: "observed",
    stop_before_gap_observed: true,
  });
  assert.deepEqual(page.commands, ["next"]);
  assert.deepEqual(page.dispatched, []);
  assert.deepEqual(page.waits, [100, 100, 100]);
});


test("pending-gap probe keeps a real boundary timeout not_observed", async () => {
  const page = new PendingGapPage([
    gapSnapshot({ ordinal: "0" }),
    gapSnapshot({ ordinal: "1", phase: "playing" }),
  ]);

  const result = await actualPendingGap(page);

  assert.equal(result.status, "not_observed");
  assert.equal(result.reason_code, "PLAYBACK_TIMEOUT_PLAYING");
  assert.equal(result.stop_before_gap_observed, false);
  assert.deepEqual(page.commands, ["next"]);
  assert.deepEqual(page.dispatched, []);
  assert.equal(page.waits.filter((value) => value === 100).length, 301);
});


test("pending-gap probe resumes a paused boundary through the real play control", async () => {
  const page = new PendingGapPage([
    gapSnapshot({ ordinal: "0" }),
    gapSnapshot({ ordinal: "1", phase: "paused" }),
    gapSnapshot({ failure: "PENDING_GAP", ordinal: "3", phase: "blocked" }),
  ]);

  const result = await actualPendingGap(page);

  assert.deepEqual(result, {
    reason_code: "OBSERVED",
    status: "observed",
    stop_before_gap_observed: true,
  });
  assert.deepEqual(page.commands, ["next", "play"]);
});


test("pending-gap probe distinguishes an unchanged seek target", async () => {
  const page = new PendingGapPage([
    gapSnapshot({ ordinal: "0", phase: "paused" }),
    gapSnapshot({ ordinal: "0", phase: "paused" }),
  ]);

  const result = await actualPendingGap(page);

  assert.equal(result.status, "not_observed");
  assert.equal(result.reason_code, "SEEK_COMMAND_NOT_APPLIED");
  assert.equal(page.waits.filter((value) => value === 100).length, 50);
});


test("pending-gap probe distinguishes null and unapplied seek targets", async () => {
  for (const [ordinal, reason] of [
    ["", "SEEK_CURRENT_NULL"],
    ["0", "SEEK_COMMAND_NOT_APPLIED"],
  ]) {
    const page = new PendingGapPage([
      gapSnapshot({ ordinal: ordinal === "" ? "" : "3", phase: "paused" }),
      gapSnapshot({ ordinal, phase: "paused" }),
    ]);
    const result = await actualPendingGap(page);
    assert.equal(result.status, "not_observed");
    assert.equal(result.reason_code, reason);
    assert.equal(
      page.waits.filter((value) => value === 100).length,
      ordinal === "" ? 0 : 51,
    );
  }
});


test("pending-gap probe fails closed when the observed ordinal enters or crosses the gap", async () => {
  for (const ordinal of ["4", "5"]) {
    const page = new PendingGapPage([
      gapSnapshot({ ordinal: "0" }),
      gapSnapshot({ failure: "PENDING_GAP", ordinal, phase: "blocked" }),
    ]);
    const result = await actualPendingGap(page);
    assert.equal(result.status, "not_observed");
    assert.equal(result.reason_code, "GAP_CROSSED");
    assert.equal(result.stop_before_gap_observed, false);
    assert.deepEqual(page.commands, ["next"]);
    assert.deepEqual(page.dispatched, []);
  }
});


test("pending-gap probe never dispatches when no exact ready-to-pending boundary exists", async () => {
  const page = new PendingGapPage([
    gapSnapshot({ states: "ready,ready,ready,ready" }),
  ]);

  const result = await actualPendingGap(page);

  assert.equal(result.status, "not_observed");
  assert.equal(result.reason_code, "BOUNDARY_NOT_FOUND");
  assert.equal(result.stop_before_gap_observed, false);
  assert.deepEqual(page.dispatched, []);
  assert.deepEqual(page.waits, []);
});


for (const editorKind of ["codemirror6", "textarea-fallback"]) {
  test(`edit round trip observes a changed digest before undo for ${editorKind}`, async () => {
    const page = new EditRoundTripPage({ editorKind });
    const result = await actualEditRoundTrip(
      page,
      editorKind,
      { mediaCandidate: null, ttsWriteRequestCount: 0 },
    );
    assert.equal(result.status, "observed");
    assert.equal(result.editor_restored, true);
    assert.equal(result.before_sha256, result.after_sha256);
    assert.deepEqual(page.events.filter((event) => event === "Space" || event === "Meta+z"), [
      "Space",
      "Meta+z",
    ]);
  });
}


test("edit round trip fails closed and never sends undo when insertion has no digest effect", async () => {
  const page = new EditRoundTripPage({ applyInsert: false });
  const result = await actualEditRoundTrip(
    page,
    "codemirror6",
    { mediaCandidate: null, ttsWriteRequestCount: 0 },
  );
  assert.equal(result.before_sha256, result.after_sha256);
  assert.equal(result.editor_restored, false);
  assert.equal(result.status, "not_observed");
  assert.equal(page.events.includes("Meta+z"), false);
});


test("edit round trip fails closed when changed digest does not return after undo", async () => {
  const page = new EditRoundTripPage({ applyUndo: false, editorKind: "textarea-fallback" });
  const result = await actualEditRoundTrip(
    page,
    "textarea-fallback",
    { mediaCandidate: null, ttsWriteRequestCount: 0 },
  );
  assert.notEqual(result.before_sha256, result.after_sha256);
  assert.equal(result.editor_restored, false);
  assert.equal(result.status, "not_observed");
  assert.equal(page.events.filter((event) => event === "Meta+z").length, 1);
});


test("edit round trip never mutates when the canonical digest surface is absent", async () => {
  const page = new EditRoundTripPage({ initialDigest: null });
  const result = await actualEditRoundTrip(
    page,
    "codemirror6",
    { mediaCandidate: null, ttsWriteRequestCount: 0 },
  );
  assert.equal(result.before_sha256, "0".repeat(64));
  assert.equal(result.after_sha256, "0".repeat(64));
  assert.equal(result.editor_restored, false);
  assert.equal(result.status, "not_observed");
  assert.deepEqual(page.events, []);
});


test("observer entrypoint obtains the capability only from inherited FD 3", () => {
  const source = readFileSync(new URL("../bin/observe.mjs", import.meta.url), "utf8");
  assert.match(source, /readSync\(3,/u);
  assert.doesNotMatch(source, /process\.env|argv\[[^\]]+\]|validation[_-]?token.*URL/iu);
  const observer = readFileSync(new URL("../src/observer.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(observer, /sha256(?:Bytes)?\([^\n]*validationToken/iu);
});


test("interaction evidence contains no prose, URL, identifier, header or capability", () => {
  const evidence = {
    controls: observedControls,
    cursor_keyboard_seek: observedSeek,
    edit_without_tts_write: observedEdit,
    editor: { codemirror_observed: true, kind: "codemirror6", textarea_fallback_observed: false },
    latest_wins: observedLatestWins,
    media_http: observedMedia,
    paragraph_context_menu_seek: observedSeek,
    pending_gap: {
      reason_code: "BOUNDARY_NOT_FOUND",
      status: "not_observed",
      stop_before_gap_observed: false,
    },
    player: { visible: true },
  };
  const serialized = canonicalJson(evidence);
  assert.doesNotMatch(serialized, /https?:|X-AI|novel_id|document_id|media-assets|secret body/u);
});


test("browser routing injects one capability only for the fixed loopback origin", () => {
  const token = "T".repeat(43);
  const loopback = fixedRouteDecision(
    "http://127.0.0.1:18088/api/ai-novel-world-2026/example",
    { "x-ai-novel-tts-validation": "replace-me", accept: "application/json" },
    token,
  );
  assert.equal(loopback.action, "continue");
  assert.deepEqual(
    Object.keys(loopback.headers).filter((name) => name.toLowerCase() === "x-ai-novel-tts-validation"),
    ["X-AI-Novel-TTS-Validation"],
  );
  assert.equal(loopback.headers["X-AI-Novel-TTS-Validation"], token);
  const external = fixedRouteDecision("https://example.invalid/collect", {}, token);
  assert.deepEqual(external, { action: "abort" });
  assert.equal("headers" in external, false);
  assert.deepEqual(fixedRouteDecision("data:text/plain,ok", {}, token), { action: "continue" });
});


test("console filter removes only an exact external URL aborted by this observer run", () => {
  const blocked = new Set();
  const exactUrl = "https://arbitrary.external.invalid/assets/image.png?cache=1";
  assert.equal(recordFixedPolicyBlockedUrl(blocked, exactUrl), true);
  assert.deepEqual([...blocked], [exactUrl]);
  assert.equal(isObserverInducedPolicyConsole(
    "error",
    exactUrl,
    "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT.Inspector",
    blocked,
  ), true);
  // The request failure remains separately observable in networkRows; this
  // predicate applies only to the observer-induced console duplicate.
});


test("console policy filter fails closed for non-exact, loopback, non-policy and assert entries", () => {
  const exactUrl = "https://arbitrary.external.invalid/assets/image.png?cache=1";
  const loopbackUrl = "http://127.0.0.1:18088/assets/image.png";
  const blocked = new Set([exactUrl, loopbackUrl]);
  for (const [messageType, locationUrl, messageText] of [
    ["error", `${exactUrl}&other=1`, "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT"],
    ["error", loopbackUrl, "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT"],
    ["error", exactUrl, "Failed to load resource: net::ERR_CONNECTION_REFUSED"],
    ["error", exactUrl, "application observed ERR_BLOCKED_BY_CLIENT while recovering"],
    ["assert", exactUrl, "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT"],
    ["error", "not a URL", "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT"],
  ]) {
    assert.equal(
      isObserverInducedPolicyConsole(messageType, locationUrl, messageText, blocked),
      false,
    );
  }
  assert.equal(recordFixedPolicyBlockedUrl(blocked, loopbackUrl), false);
  assert.equal(recordFixedPolicyBlockedUrl(blocked, "data:text/plain,blocked"), false);
  assert.equal(recordFixedPolicyBlockedUrl(blocked, "not a URL"), false);
});


test("range console filter removes only the observer's exact expected 416", () => {
  const url = "http://127.0.0.1:18088/api/ai-novel-world-2026/media-assets/00000000-0000-4000-8000-000000000001/content";
  const message = "Failed to load resource: the server responded with a status of 416 (Requested Range Not Satisfiable)";
  assert.equal(isObserverInducedRangeConsole("error", url, message, url), true);
  assert.equal(isObserverInducedRangeConsole("error", `${url}?changed=1`, message, url), false);
  assert.equal(isObserverInducedRangeConsole("error", url, `${message}.`, url), false);
  assert.equal(isObserverInducedRangeConsole("warning", url, message, url), false);
  assert.equal(isObserverInducedRangeConsole("error", url, message, null), false);
});


test("layout summary counts only clipped top-level mutually-exclusive overlaps", () => {
  const base = {
    containing_pairs: [],
    inner_width: 1920,
    scroll_width: 1937.2,
    regions: [
      { key: "editor", visible: true, left: 100, right: 1200, top: 200, bottom: 900 },
      { key: "player", visible: true, left: 100, right: 1200, top: 100, bottom: 200 },
      { key: "assistant", visible: true, left: 1200, right: 1920, top: 0, bottom: 1080 },
      // Script review intentionally overlays editor; that pair is not compared.
      { key: "script_review", visible: true, left: 400, right: 1100, top: 240, bottom: 850 },
    ],
  };
  assert.deepEqual(summarizeFixedLayoutGeometry(base), {
    horizontal_overflow_px: 18,
    nonzero_overlap_pair_count: 0,
    tracked_visible_region_count: 4,
  });
  assert.deepEqual(summarizeFixedLayoutGeometry({
    ...base,
    containing_pairs: [["editor", "player"]],
    regions: base.regions.map((region) => (
      region.key === "player" ? { ...region, top: 150, bottom: 250 } : region
    )),
  }), {
    horizontal_overflow_px: 18,
    nonzero_overlap_pair_count: 1,
    tracked_visible_region_count: 4,
  });
  assert.equal(summarizeFixedLayoutGeometry({
    ...base,
    scroll_width: 1920,
    regions: base.regions.map((region) => (
      region.key === "assistant" ? { ...region, left: 1150 } : region
    )),
}).nonzero_overlap_pair_count, 2);
});


test("editor and sticky player overlap is safe only with exact DOM and sufficient dual padding", () => {
  const sufficient = {
    editor_padding_bottom: 120,
    exact_dom_relation: true,
    player_height: 94,
    player_position: "sticky",
    scroll_container_overflow_y: "auto",
    scroll_content_padding_bottom: 128,
    sticky_bottom: 14,
  };
  assert.equal(isSafeFixedEditorPlayerOverlay(sufficient), true);
  const snapshot = {
    containing_pairs: [],
    editor_player_overlay: sufficient,
    inner_width: 1920,
    scroll_width: 1920,
    regions: [
      { key: "editor", visible: true, left: 100, right: 1200, top: 100, bottom: 900 },
      { key: "player", visible: true, left: 200, right: 1100, top: 800, bottom: 894 },
    ],
  };
  assert.equal(summarizeFixedLayoutGeometry(snapshot).nonzero_overlap_pair_count, 0);
  for (const unsafe of [
    { ...sufficient, scroll_content_padding_bottom: 107 },
    { ...sufficient, editor_padding_bottom: 107 },
    { ...sufficient, exact_dom_relation: false },
    { ...sufficient, player_position: "fixed" },
    { ...sufficient, scroll_container_overflow_y: "visible" },
  ]) {
    assert.equal(isSafeFixedEditorPlayerOverlay(unsafe), false);
    assert.equal(summarizeFixedLayoutGeometry({
      ...snapshot,
      editor_player_overlay: unsafe,
    }).nonzero_overlap_pair_count, 1);
  }
});


test("mocked layout browser receives only the fixed selectors and returns count-only evidence", async () => {
  const page = {
    async evaluate(_callback, input) {
      assert.deepEqual(input.selectors, {
        assistant: ".anw-assistant-pane",
        editor: ".anw-chapter-editor-surface",
        player: ".anw-chapter-narration-player[aria-label=\"章节智能朗读播放器\"]",
        script_review: ".anw-script-review-shell",
      });
      assert.deepEqual(input.pairs, [
        ["editor", "player"],
        ["editor", "assistant"],
        ["player", "assistant"],
        ["script_review", "assistant"],
      ]);
      return {
        containing_pairs: [],
        inner_width: 2560,
        scroll_width: 2560,
        regions: [
          { key: "editor", visible: true, left: 0, right: 1800, top: 140, bottom: 1440 },
          { key: "player", visible: true, left: 0, right: 1800, top: 0, bottom: 140 },
          { key: "assistant", visible: true, left: 1800, right: 2560, top: 0, bottom: 1440 },
          { key: "script_review", visible: false },
        ],
      };
    },
  };
  const observation = await collectFixedLayoutObservation(page);
  assert.deepEqual(Object.keys(observation).sort(), [
    "horizontal_overflow_px",
    "nonzero_overlap_pair_count",
    "tracked_visible_region_count",
  ]);
  assert.deepEqual(observation, {
    horizontal_overflow_px: 0,
    nonzero_overlap_pair_count: 0,
    tracked_visible_region_count: 3,
  });
});
