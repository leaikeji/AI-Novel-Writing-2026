import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { lstatSync, readFileSync } from "node:fs";

import {
  CONTROLLER_ID,
  EDGE_PATH,
  FIXED_CAPTURES,
  FIXED_ORIGIN,
  ObserverError,
  REPORT_SCHEMA,
  boundedDigestSummary,
  canonicalJson,
  finalRouteEvidence,
  fixedWorkbenchUrl,
  loopbackValidationHeaders,
  pngDimensions,
  sha256Bytes,
} from "./contracts.mjs";
import { loadFixedChromium } from "./runtime-identity.mjs";

const PLAYWRIGHT_VERSION = "1.62.1";
const EDGE_APP_PATH = "/Applications/Microsoft Edge.app";
const EDGE_IDENTIFIER = "com.microsoft.edgemac";
const EDGE_TEAM_IDENTIFIER = "UBF8T346G9";
const ASSISTANT_ROOT = ".anw-assistant-pane";
const ASSISTANT_TOGGLE = ".anw-assistant-pane-toggle";
const HOST_TOUR_CLOSE = ".qwenpaw-tour-close";
const HOST_TOUR_MASK = ".qwenpaw-tour-mask";
const EDITOR_ROOT = ".anw-chapter-editor-surface";
const EDITOR_VALUE_SHA256_ATTRIBUTE = "data-editor-value-sha256";
const CODEMIRROR_ROOT = `${EDITOR_ROOT} .cm-editor`;
const CODEMIRROR_CONTENT = `${EDITOR_ROOT} .cm-content[contenteditable=\"true\"]`;
const TEXTAREA_EDITOR = `${EDITOR_ROOT} textarea.anw-chapter-editor-textarea-fallback`;
const PLAYER = ".anw-chapter-narration-player[aria-label=\"章节智能朗读播放器\"]";
const PLAY = `${PLAYER} button[aria-label=\"播放章节朗读\"]`;
const PAUSE = `${PLAYER} button[aria-label=\"暂停章节朗读\"]`;
const PREVIOUS = `${PLAYER} button[aria-label=\"朗读上一句\"]`;
const NEXT = `${PLAYER} button[aria-label=\"朗读下一句\"]`;
const TIMELINE = `${PLAYER} input[type=\"range\"][aria-label=\"按句段跳转章节朗读位置\"]`;
const RATE = `${PLAYER} select[aria-label=\"朗读倍速\"]`;
const CONTEXT_MENU = ".anw-narration-paragraph-context-menu[role=\"menu\"]";
const CONTEXT_MENU_COMMAND = `${CONTEXT_MENU} button[role=\"menuitem\"]`;
const MEDIA_PATH = /^\/api\/ai-novel-world-2026\/media-assets\/[0-9a-f-]{36}\/content$/iu;
const LAYOUT_REGIONS = Object.freeze({
  assistant: ASSISTANT_ROOT,
  editor: EDITOR_ROOT,
  player: PLAYER,
  script_review: ".anw-script-review-shell",
});
// Only top-level regions that are expected to remain mutually exclusive are
// compared. The script-review shell intentionally overlays central authoring
// content, so its editor/player intersections are not defects; it is compared
// only with the independent native-assistant region.
const LAYOUT_MUTUALLY_EXCLUSIVE_PAIRS = Object.freeze([
  Object.freeze(["editor", "player"]),
  Object.freeze(["editor", "assistant"]),
  Object.freeze(["player", "assistant"]),
  Object.freeze(["script_review", "assistant"]),
]);
const MAX_CALIBRATION_ATTEMPTS = 8;
const EDIT_DIGEST_POLL_INTERVAL_MS = 25;
const EDIT_CHANGE_POLL_ATTEMPTS = 20;
const EDIT_UNDO_POLL_ATTEMPTS = 40;
const POST_LATEST_WINS_SETTLE_MS = 2_000;
const PENDING_GAP_POLL_INTERVAL_MS = 100;
const PENDING_GAP_POLL_ATTEMPTS = 300;
const PENDING_GAP_SEEK_SETTLE_ATTEMPTS = 50;
const CONTEXT_MENU_SEEK_POLL_INTERVAL_MS = 25;
// A real paragraph seek can wait behind the persisted-progress request and
// Manifest/media preparation on the author's machine.  The visible ordinal is
// still the production-owned proof; allow that async transition up to five
// seconds instead of treating a slow but valid command as a one-second miss.
const CONTEXT_MENU_SEEK_POLL_ATTEMPTS = 200;
const INITIAL_TIMELINE_READY_POLL_INTERVAL_MS = 100;
const INITIAL_TIMELINE_READY_POLL_ATTEMPTS = 100;
// Fixed by initial-buffer/v1-3-segments-8000ms, the production Manifest
// policy used by this sealed T4-K fixture and revalidated by the player.
const PENDING_GAP_MINIMUM_PLAYABLE_SEGMENTS = 3;
const OBSERVABLE_SEGMENT_STATES = new Set(["ready", "pending", "failed", "cancelled"]);

function elapsedMs(started) {
  return Math.max(0, Math.round(performance.now() - started));
}

function status(observed) {
  return observed ? "observed" : "not_observed";
}

export function fixedRouteDecision(rawUrl, headers, validationToken) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new ObserverError("OBSERVER_ROUTE_ESCAPED");
  }
  if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== FIXED_ORIGIN) {
    return Object.freeze({ action: "abort" });
  }
  if (url.protocol === "http:" || url.protocol === "https:") {
    return Object.freeze({
      action: "continue",
      headers: Object.freeze(loopbackValidationHeaders(headers, validationToken)),
    });
  }
  return Object.freeze({ action: "continue" });
}

export function recordFixedPolicyBlockedUrl(policyBlockedUrls, rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return false;
  }
  if (
    (url.protocol !== "http:" && url.protocol !== "https:")
    || url.origin === FIXED_ORIGIN
  ) return false;
  policyBlockedUrls.add(rawUrl);
  return true;
}

export function isObserverInducedPolicyConsole(
  messageType,
  rawLocationUrl,
  messageText,
  policyBlockedUrls,
) {
  if (messageType !== "error" || !policyBlockedUrls.has(rawLocationUrl)) return false;
  let location;
  try {
    location = new URL(rawLocationUrl);
  } catch {
    return false;
  }
  return (
    (location.protocol === "http:" || location.protocol === "https:")
    && location.origin !== FIXED_ORIGIN
    && /^Failed to load resource: net::ERR_BLOCKED_BY_CLIENT(?:\.Inspector)?$/u.test(messageText)
  );
}

export function isObserverInducedRangeConsole(
  messageType,
  rawLocationUrl,
  messageText,
  expectedRangeConsoleUrl,
) {
  return (
    messageType === "error"
    && typeof expectedRangeConsoleUrl === "string"
    && rawLocationUrl === expectedRangeConsoleUrl
    && messageText === "Failed to load resource: the server responded with a status of 416 (Requested Range Not Satisfiable)"
  );
}

function isTtsWriteRequest(request) {
  const method = request.method().toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return false;
  try {
    const url = new URL(request.url());
    if (
      url.origin !== FIXED_ORIGIN
      || !url.pathname.startsWith("/api/ai-novel-world-2026/")
      || !/(?:narration|voice)/u.test(url.pathname)
    ) return false;
    // These are expected player writes, not synthesis/configuration writes
    // caused by an editor change. They are measured by their own interactions.
    return !/(?:\/playback-progress|\/prepare-range)$/u.test(url.pathname);
  } catch {
    return false;
  }
}

function trackRequest(networkState, request) {
  if (isTtsWriteRequest(request)) networkState.ttsWriteRequestCount += 1;
  if (networkState.mediaCandidate !== null) return;
  let url;
  try {
    url = new URL(request.url());
  } catch {
    return;
  }
  if (url.origin !== FIXED_ORIGIN || !MEDIA_PATH.test(url.pathname)) return;
  const headers = request.headers();
  const edition = headers["x-narration-edition-id"];
  const revision = headers["x-narration-manifest-revision"];
  if (!edition || !revision) return;
  networkState.mediaCandidate = Object.freeze({
    url: url.href,
    headers: Object.freeze({
      "X-Narration-Edition-Id": edition,
      "X-Narration-Manifest-Revision": revision,
    }),
  });
}

async function locatorVisible(locator) {
  return (await locator.count()) === 1 && await locator.isVisible();
}

async function readOrdinal(page) {
  const timeline = page.locator(TIMELINE);
  if (!await locatorVisible(timeline)) return null;
  const value = Number(await timeline.inputValue());
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

async function timelineBounds(page) {
  const timeline = page.locator(TIMELINE);
  if (!await locatorVisible(timeline) || !await timeline.isEnabled()) return null;
  const maximum = Number(await timeline.getAttribute("max"));
  if (!Number.isSafeInteger(maximum) || maximum < 0) return null;
  return Object.freeze({ maximum, timeline });
}

async function readPlayerGapState(player) {
  const [phase, failureCode, ordinalRaw, statesRaw] = await Promise.all([
    player.getAttribute("data-player-phase"),
    player.getAttribute("data-player-failure-code"),
    player.getAttribute("data-current-ordinal"),
    player.getAttribute("data-segment-states"),
  ]);
  if (
    typeof phase !== "string"
    || typeof failureCode !== "string"
    || typeof ordinalRaw !== "string"
    || typeof statesRaw !== "string"
    || statesRaw.length === 0
  ) return null;
  const states = statesRaw.split(",");
  if (states.length < 2 || states.some((state) => !OBSERVABLE_SEGMENT_STATES.has(state))) {
    return null;
  }
  let currentOrdinal = null;
  if (ordinalRaw !== "") {
    if (!/^(?:0|[1-9][0-9]*)$/u.test(ordinalRaw)) return null;
    currentOrdinal = Number(ordinalRaw);
    if (!Number.isSafeInteger(currentOrdinal) || currentOrdinal >= states.length) return null;
  }
  const gapOrdinal = states.findIndex((state, index) => (
    index > 0 && state === "pending" && states[index - 1] === "ready"
  ));
  return Object.freeze({
    currentOrdinal,
    failureCode,
    gapOrdinal,
    phase,
    states: Object.freeze(states),
    statesRaw,
  });
}

async function dispatchTimelineValue(timeline, value) {
  const [minimumRaw, maximumRaw] = await Promise.all([
    timeline.getAttribute("min"),
    timeline.getAttribute("max"),
  ]);
  const minimum = Number(minimumRaw);
  const maximum = Number(maximumRaw);
  if (
    !Number.isSafeInteger(minimum)
    || !Number.isSafeInteger(maximum)
    || minimum > maximum
    || !Number.isSafeInteger(value)
    || value < minimum
    || value > maximum
  ) throw new Error("fixed range bounds unavailable");

  // Use only native keyboard interaction so React and the browser own the
  // range state transition. Always walk forward from Home: jumping to End can
  // intentionally select a pending final sentence, whose controlled rerender
  // invalidates a follow-up ArrowLeft before it reaches the ready boundary.
  await timeline.press("Home");
  for (let step = minimum; step < value; step += 1) {
    await timeline.press("ArrowRight");
  }
}

async function detectEditorKind(page) {
  if (await locatorVisible(page.locator(CODEMIRROR_ROOT))) return "codemirror6";
  if (await locatorVisible(page.locator(TEXTAREA_EDITOR))) return "textarea-fallback";
  return "not_observed";
}

async function editorDigest(page) {
  const raw = await page.locator(EDITOR_ROOT).getAttribute(
    EDITOR_VALUE_SHA256_ATTRIBUTE,
  );
  return typeof raw === "string" && /^[0-9a-f]{64}$/u.test(raw)
    ? raw
    : null;
}

async function waitForEditorDigest(page, predicate, maximumAttempts, fallbackDigest) {
  let digest = fallbackDigest;
  for (let attempt = 0; attempt < maximumAttempts; attempt += 1) {
    const observedDigest = await editorDigest(page);
    if (observedDigest !== null) {
      digest = observedDigest;
      if (predicate(digest)) return Object.freeze({ digest, observed: true });
    }
    await page.waitForTimeout(EDIT_DIGEST_POLL_INTERVAL_MS);
  }
  const observedDigest = await editorDigest(page);
  if (observedDigest !== null) digest = observedDigest;
  return Object.freeze({ digest, observed: false });
}

async function placeEditorCaret(page, editorKind, edge) {
  const selector = editorKind === "codemirror6" ? CODEMIRROR_CONTENT : TEXTAREA_EDITOR;
  const editor = page.locator(selector);
  if (editorKind === "textarea-fallback") {
    await editor.evaluate((element, wantedEdge) => {
      const target = element;
      const offset = wantedEdge === "end" ? target.value.length : 0;
      target.focus();
      target.setSelectionRange(offset, offset, "none");
      target.dispatchEvent(new Event("select", { bubbles: true }));
    }, edge);
    return editor;
  }
  const box = await editor.boundingBox();
  if (!box) throw new ObserverError("OBSERVER_EDITOR_NOT_INTERACTIVE");
  // A coordinate-only click selects the first/last *visible* line and is not
  // an absolute document edge when CodeMirror has followed persisted playback
  // near the end of a chapter.  Move the real browser selection to the exact
  // document edge first; CodeMirror scrolls that caret into view, after which
  // the right-click coordinate below resolves to the same edge paragraph.
  await editor.click();
  await editor.press(edge === "end" ? "Meta+ArrowDown" : "Meta+ArrowUp");
  await editor.click({
    position: { x: Math.min(24, Math.max(1, box.width - 1)), y: edge === "end" ? Math.max(1, box.height - 12) : 12 },
  });
  return editor;
}

export function differentEditorEdge(currentOrdinal, maximumOrdinal) {
  if (
    !Number.isSafeInteger(currentOrdinal)
    || !Number.isSafeInteger(maximumOrdinal)
    || currentOrdinal < 0
    || maximumOrdinal < 1
    || currentOrdinal > maximumOrdinal
  ) return null;
  return currentOrdinal === 0 ? "end" : "start";
}

export async function actualContextMenuSeek(page, editorKind) {
  const started = performance.now();
  if (editorKind === "not_observed") {
    return Object.freeze({ command_dispatched: false, elapsed_ms: elapsedMs(started), status: "not_observed", target_changed: false });
  }
  let before = null;
  let bounds = null;
  for (
    let attempt = 0;
    attempt < INITIAL_TIMELINE_READY_POLL_ATTEMPTS;
    attempt += 1
  ) {
    [before, bounds] = await Promise.all([
      readOrdinal(page),
      timelineBounds(page),
    ]);
    if (
      before !== null
      && bounds !== null
      && bounds.maximum >= 1
      && before <= bounds.maximum
    ) break;
    await page.waitForTimeout(INITIAL_TIMELINE_READY_POLL_INTERVAL_MS);
  }
  const targetEdge = differentEditorEdge(before, bounds?.maximum);
  if (targetEdge === null) {
    return Object.freeze({ command_dispatched: false, elapsed_ms: elapsedMs(started), status: "not_observed", target_changed: false });
  }
  const editor = await placeEditorCaret(page, editorKind, targetEdge);
  if (editorKind === "textarea-fallback") {
    await editor.dispatchEvent("contextmenu", { button: 2, clientX: 16, clientY: 16 });
  } else {
    const box = await editor.boundingBox();
    if (!box) throw new ObserverError("OBSERVER_EDITOR_NOT_INTERACTIVE");
    await editor.click({
      button: "right",
      position: {
        x: Math.min(24, Math.max(1, box.width - 1)),
        y: targetEdge === "end" ? Math.max(1, box.height - 12) : 12,
      },
    });
  }
  const command = page.locator(CONTEXT_MENU_COMMAND);
  if (!await locatorVisible(command)) {
    return Object.freeze({ command_dispatched: false, elapsed_ms: elapsedMs(started), status: "not_observed", target_changed: false });
  }
  await command.click();
  let after = await readOrdinal(page);
  for (
    let attempt = 0;
    attempt < CONTEXT_MENU_SEEK_POLL_ATTEMPTS && after === before;
    attempt += 1
  ) {
    await page.waitForTimeout(CONTEXT_MENU_SEEK_POLL_INTERVAL_MS);
    after = await readOrdinal(page);
  }
  return Object.freeze({
    command_dispatched: true,
    elapsed_ms: elapsedMs(started),
    status: "observed",
    target_changed: before !== null && after !== null && before !== after,
  });
}

export async function actualKeyboardSeek(page, editorKind) {
  const started = performance.now();
  if (editorKind === "not_observed") {
    return Object.freeze({ command_dispatched: false, elapsed_ms: elapsedMs(started), status: "not_observed", target_changed: false });
  }
  const [before, bounds] = await Promise.all([
    readOrdinal(page),
    timelineBounds(page),
  ]);
  const targetEdge = differentEditorEdge(before, bounds?.maximum);
  if (targetEdge === null) {
    return Object.freeze({ command_dispatched: false, elapsed_ms: elapsedMs(started), status: "not_observed", target_changed: false });
  }
  const editor = await placeEditorCaret(page, editorKind, targetEdge);
  await editor.press("Meta+Alt+Enter");
  let after = await readOrdinal(page);
  for (
    let attempt = 0;
    attempt < CONTEXT_MENU_SEEK_POLL_ATTEMPTS && after === before;
    attempt += 1
  ) {
    await page.waitForTimeout(CONTEXT_MENU_SEEK_POLL_INTERVAL_MS);
    after = await readOrdinal(page);
  }
  return Object.freeze({
    command_dispatched: true,
    elapsed_ms: elapsedMs(started),
    status: "observed",
    target_changed: before !== null && after !== null && before !== after,
  });
}

async function actualLatestWins(page) {
  const started = performance.now();
  const bounds = await timelineBounds(page);
  if (!bounds || bounds.maximum < 1) {
    return Object.freeze({
      elapsed_ms: elapsedMs(started),
      final_target_won: false,
      first_dispatch_observed: false,
      second_dispatch_observed: false,
      status: "not_observed",
    });
  }
  const first = 0;
  const second = Math.min(1, bounds.maximum);
  await dispatchTimelineValue(bounds.timeline, first);
  await dispatchTimelineValue(bounds.timeline, second);
  await page.waitForTimeout(750);
  const settled = await readOrdinal(page);
  return Object.freeze({
    elapsed_ms: elapsedMs(started),
    final_target_won: settled === second,
    first_dispatch_observed: true,
    second_dispatch_observed: true,
    status: "observed",
  });
}

export async function actualPlayerControls(page) {
  const started = performance.now();
  const player = page.locator(PLAYER);
  if (!await locatorVisible(player)) {
    return Object.freeze({ elapsed_ms: elapsedMs(started), pause_observed: false, play_observed: false, rate_change_observed: false, seek_observed: false, status: "not_observed" });
  }
  let playObserved = false;
  let pauseObserved = false;
  let play = page.locator(PLAY);
  // Previous seeks can leave the player temporarily preparing/buffering, and
  // a prior observation can enter with the semantic pause control visible.
  // Normalize to one actionable paused state before probing play.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await locatorVisible(play) && await play.isEnabled()) break;
    const initialPause = page.locator(PAUSE);
    if (await locatorVisible(initialPause) && await initialPause.isEnabled()) {
      await initialPause.click();
    }
    await page.waitForTimeout(100);
    play = page.locator(PLAY);
  }
  if (await locatorVisible(play) && await play.isEnabled()) {
    await play.click();
    // The click first enters buffering while the scoped media bytes cross the
    // host.fetch bridge. Poll for the semantic pause control instead of
    // assuming one fixed decode latency on the author's machine.
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const pendingPause = page.locator(PAUSE);
      if (await locatorVisible(pendingPause) && await pendingPause.isEnabled()) {
        playObserved = true;
        await pendingPause.click();
        // A successful click is not proof that the player paused. Require the
        // semantic controls to settle back to the paused UI state.
        for (let settleAttempt = 0; settleAttempt < 20; settleAttempt += 1) {
          const resumedPlay = page.locator(PLAY);
          const lingeringPause = page.locator(PAUSE);
          if (
            await locatorVisible(resumedPlay)
            && await resumedPlay.isEnabled()
            && !await locatorVisible(lingeringPause)
          ) {
            pauseObserved = true;
            break;
          }
          await page.waitForTimeout(100);
        }
        break;
      }
      await page.waitForTimeout(100);
    }
  }
  const rate = page.locator(RATE);
  let rateObserved = false;
  if (await locatorVisible(rate) && await rate.isEnabled()) {
    await rate.selectOption("1.25");
    rateObserved = await rate.inputValue() === "1.25";
  }
  const bounds = await timelineBounds(page);
  let seekObserved = false;
  if (bounds) {
    const target = bounds.maximum > 0 ? Math.min(1, bounds.maximum) : 0;
    await dispatchTimelineValue(bounds.timeline, target);
    await page.waitForTimeout(250);
    seekObserved = await readOrdinal(page) === target;
  }
  return Object.freeze({
    elapsed_ms: elapsedMs(started),
    pause_observed: pauseObserved,
    play_observed: playObserved,
    rate_change_observed: rateObserved,
    seek_observed: seekObserved,
    status: status(playObserved || pauseObserved || rateObserved || seekObserved),
  });
}

export async function actualPendingGap(page) {
  const notObserved = (reasonCode) => Object.freeze({
    reason_code: reasonCode,
    status: "not_observed",
    stop_before_gap_observed: false,
  });
  const player = page.locator(PLAYER);
  if (!await locatorVisible(player)) return notObserved("PLAYER_NOT_VISIBLE");
  const initial = await readPlayerGapState(player);
  if (initial === null) return notObserved("STATE_UNAVAILABLE");
  if (initial.gapOrdinal < 1) return notObserved("BOUNDARY_NOT_FOUND");
  const boundaryOrdinal = initial.gapOrdinal - 1;
  const playableStartOrdinal = Math.max(
    0,
    initial.gapOrdinal - PENDING_GAP_MINIMUM_PLAYABLE_SEGMENTS,
  );
  const bounds = await timelineBounds(page);
  if (
    bounds === null
    || bounds.maximum !== initial.states.length - 1
    || boundaryOrdinal > bounds.maximum
    || playableStartOrdinal > boundaryOrdinal
  ) return notObserved("TIMELINE_MISMATCH");

  // Shorten only this real playable boundary window through the maximum
  // production UI rate control. The observer still waits for an actual queue
  // transition and never edits the Manifest or injects a playback result.
  const rate = page.locator(RATE);
  if (await locatorVisible(rate) && await rate.isEnabled()) {
    await rate.selectOption("2");
    if (await rate.inputValue() !== "2") return notObserved("RATE_CHANGE_FAILED");
  }

  // Move through the production sentence-navigation buttons and wait for the
  // player-owned ordinal after every click. This avoids treating a controlled
  // range thumb's transient DOM value as a committed playback target.
  if (initial.currentOrdinal === null) {
    return notObserved("SEEK_CURRENT_NULL");
  }
  let seekSettled = false;
  let lastSeekObservation = initial;
  const seekAttempts = Math.abs(
    playableStartOrdinal - initial.currentOrdinal,
  ) + 4;
  for (let attempt = 0; attempt < seekAttempts; attempt += 1) {
    const current = lastSeekObservation.currentOrdinal;
    if (current === playableStartOrdinal) {
      seekSettled = true;
      break;
    }
    if (current === null) return notObserved("SEEK_CURRENT_NULL");
    const command = page.locator(current < playableStartOrdinal ? NEXT : PREVIOUS);
    if (!await locatorVisible(command) || !await command.isEnabled()) {
      return notObserved("SEEK_COMMAND_UNAVAILABLE");
    }
    await command.click();
    let commandApplied = false;
    for (
      let settleAttempt = 0;
      settleAttempt < PENDING_GAP_SEEK_SETTLE_ATTEMPTS;
      settleAttempt += 1
    ) {
      await page.waitForTimeout(PENDING_GAP_POLL_INTERVAL_MS);
      const observed = await readPlayerGapState(player);
      if (observed === null) return notObserved("STATE_UNAVAILABLE");
      lastSeekObservation = observed;
      if (
        observed.statesRaw !== initial.statesRaw
        || observed.gapOrdinal !== initial.gapOrdinal
      ) return notObserved("STATE_CHANGED");
      if (
        observed.currentOrdinal !== null
        && observed.currentOrdinal >= initial.gapOrdinal
      ) return notObserved("GAP_CROSSED");
      if (observed.currentOrdinal !== current) {
        commandApplied = true;
        break;
      }
    }
    if (!commandApplied) return notObserved("SEEK_COMMAND_NOT_APPLIED");
  }
  if (!seekSettled) {
    if (lastSeekObservation.currentOrdinal === null) {
      return notObserved("SEEK_CURRENT_NULL");
    }
    if (lastSeekObservation.currentOrdinal === initial.currentOrdinal) {
      return notObserved("SEEK_COMMAND_NOT_APPLIED");
    }
    return notObserved("SEEK_WRONG_READY_ORDINAL");
  }
  const boundaryState = await readPlayerGapState(player);
  if (boundaryState === null) return notObserved("STATE_UNAVAILABLE");
  if (boundaryState.phase === "blocked") {
    if (
      boundaryState.failureCode === "PENDING_GAP"
      && boundaryState.currentOrdinal === boundaryOrdinal
    ) {
      return Object.freeze({
        reason_code: "OBSERVED",
        status: "observed",
        stop_before_gap_observed: true,
      });
    }
    return notObserved("BLOCKED_MISMATCH");
  }
  if (["idle", "paused", "ended"].includes(boundaryState.phase)) {
    const play = page.locator(PLAY);
    if (!await locatorVisible(play) || !await play.isEnabled()) {
      return notObserved("PLAYBACK_START_UNAVAILABLE");
    }
    await play.click();
  }
  let lastPlaybackObservation = boundaryState;
  for (let attempt = 0; attempt < PENDING_GAP_POLL_ATTEMPTS; attempt += 1) {
    // Let the production input handler publish the new seek before comparing
    // ordinals. The preceding fixed recipe may legitimately have been at a
    // later sentence, and that pre-dispatch state is not a crossed-gap result.
    await page.waitForTimeout(PENDING_GAP_POLL_INTERVAL_MS);
    const observed = await readPlayerGapState(player);
    if (
      observed === null
    ) return notObserved("STATE_UNAVAILABLE");
    lastPlaybackObservation = observed;
    if (
      observed.statesRaw !== initial.statesRaw
      || observed.gapOrdinal !== initial.gapOrdinal
    ) return notObserved("STATE_CHANGED");
    if (
      observed.currentOrdinal !== null
      && observed.currentOrdinal >= initial.gapOrdinal
    ) return notObserved("GAP_CROSSED");
    if (observed.phase === "blocked") {
      if (
        observed.failureCode === "PENDING_GAP"
        && observed.currentOrdinal === boundaryOrdinal
      ) {
        return Object.freeze({
          reason_code: "OBSERVED",
          status: "observed",
          stop_before_gap_observed: true,
        });
      }
      return notObserved("BLOCKED_MISMATCH");
    }
  }
  const timeoutPhases = new Set([
    "idle",
    "preparing",
    "buffering",
    "playing",
    "paused",
    "ended",
    "error",
  ]);
  return notObserved(
    timeoutPhases.has(lastPlaybackObservation.phase)
      ? `PLAYBACK_TIMEOUT_${lastPlaybackObservation.phase.toUpperCase()}`
      : "PLAYBACK_TIMEOUT",
  );
}

export async function actualEditRoundTrip(page, editorKind, networkState) {
  const started = performance.now();
  if (editorKind === "not_observed") {
    return Object.freeze({
      after_sha256: "0".repeat(64), before_sha256: "0".repeat(64), editor_restored: false,
      elapsed_ms: elapsedMs(started), status: "not_observed", tts_write_request_count: 0,
    });
  }
  const initial = await waitForEditorDigest(
    page,
    () => true,
    EDIT_UNDO_POLL_ATTEMPTS,
    "0".repeat(64),
  );
  if (!initial.observed) {
    return Object.freeze({
      after_sha256: initial.digest,
      before_sha256: initial.digest,
      editor_restored: false,
      elapsed_ms: elapsedMs(started),
      status: "not_observed",
      tts_write_request_count: 0,
    });
  }
  const beforeSha = initial.digest;
  const beforeWrites = networkState.ttsWriteRequestCount;
  const editor = await placeEditorCaret(page, editorKind, "end");
  await editor.press("End");
  await editor.press("Space");

  // CodeMirror dispatch and its DOM projection can settle on different turns.
  // Do not send undo until a real one-character edit is observable. This also
  // prevents an unchanged before/after digest from being misreported as a
  // successful round trip when the editor ignored the insertion entirely.
  const changed = await waitForEditorDigest(
    page,
    (digest) => digest !== beforeSha,
    EDIT_CHANGE_POLL_ATTEMPTS,
    beforeSha,
  );
  if (!changed.observed) {
    return Object.freeze({
      after_sha256: changed.digest,
      before_sha256: beforeSha,
      editor_restored: false,
      elapsed_ms: elapsedMs(started),
      status: "not_observed",
      tts_write_request_count: Math.max(0, networkState.ttsWriteRequestCount - beforeWrites),
    });
  }

  await editor.press("Meta+z");
  const restored = await waitForEditorDigest(
    page,
    (digest) => digest === beforeSha,
    EDIT_UNDO_POLL_ATTEMPTS,
    changed.digest,
  );
  return Object.freeze({
    after_sha256: restored.digest,
    before_sha256: beforeSha,
    editor_restored: restored.observed,
    elapsed_ms: elapsedMs(started),
    status: restored.observed ? "observed" : "not_observed",
    tts_write_request_count: Math.max(0, networkState.ttsWriteRequestCount - beforeWrites),
  });
}

async function actualMediaContract(page, networkState) {
  const started = performance.now();
  const candidate = networkState.mediaCandidate;
  if (candidate === null) {
    return Object.freeze({
      elapsed_ms: elapsedMs(started), etag_observed: false, if_none_match_304: false,
      if_range_206: false, range_206: false, request_count: 0, status: "not_observed",
      unsatisfied_range_416: false,
    });
  }
  networkState.expectedRangeConsoleUrl = candidate.url;
  let result;
  try {
    result = await page.evaluate(async ({ url, requiredHeaders }) => {
    const request = async (extraHeaders) => {
      const response = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { ...requiredHeaders, ...extraHeaders },
        method: "GET",
      });
      return { etag: response.headers.get("ETag"), status: response.status };
    };
    const baseline = await request({});
    const conditional = baseline.etag ? await request({ "If-None-Match": baseline.etag }) : null;
    const ranged = await request({ Range: "bytes=0-0" });
    const ifRange = baseline.etag
      ? await request({ "If-Range": baseline.etag, Range: "bytes=0-0" })
      : null;
    const unsatisfied = await request({ Range: "bytes=9223372036854775807-" });
    return {
      etagObserved: typeof baseline.etag === "string" && /^"[a-f0-9]{64}"$/u.test(baseline.etag),
      ifNoneMatch304: conditional?.status === 304,
      ifRange206: ifRange?.status === 206,
      range206: ranged.status === 206,
      requestCount: 3 + Number(conditional !== null) + Number(ifRange !== null),
      unsatisfiedRange416: unsatisfied.status === 416,
    };
    }, { requiredHeaders: candidate.headers, url: candidate.url });
  } finally {
    networkState.expectedRangeConsoleUrl = null;
  }
  return Object.freeze({
    elapsed_ms: elapsedMs(started),
    etag_observed: result.etagObserved,
    if_none_match_304: result.ifNoneMatch304,
    if_range_206: result.ifRange206,
    range_206: result.range206,
    request_count: result.requestCount,
    status: "observed",
    unsatisfied_range_416: result.unsatisfiedRange416,
  });
}

/**
 * Execute the one fixed browser interaction recipe.  Overrides exist only as
 * an injected test seam; the executable calls this without caller input.
 */
export async function collectFixedInteractionEvidence(page, networkState, overrides = {}) {
  const actions = {
    contextMenuSeek: actualContextMenuSeek,
    detectEditorKind,
    editRoundTrip: actualEditRoundTrip,
    keyboardSeek: actualKeyboardSeek,
    latestWins: actualLatestWins,
    mediaContract: actualMediaContract,
    pendingGap: actualPendingGap,
    playerControls: actualPlayerControls,
    ...overrides,
  };
  const playerVisible = await locatorVisible(page.locator(PLAYER));
  const editorKind = await actions.detectEditorKind(page);
  const contextMenuSeek = await actions.contextMenuSeek(page, editorKind);
  const keyboardSeek = await actions.keyboardSeek(page, editorKind);
  const latestWins = await actions.latestWins(page);
  // A seek updates the visible ordinal before the asynchronous media queue has
  // necessarily left its preparing/buffering phase.  Give that fixed local
  // transition time to settle before deciding whether the controls and first
  // real media request are actionable; otherwise a successful latest-wins
  // seek can make the immediately following control probe a false negative.
  await page.waitForTimeout(POST_LATEST_WINS_SETTLE_MS);
  const controls = await actions.playerControls(page);
  // Prove the real ready-to-pending stop before the edit round trip. Even
  // after DOM text is undone, the production session deliberately remembers
  // that a working-copy divergence occurred and may reject later playback
  // against the old Edition until an explicit reload/update.
  const pendingGap = await actions.pendingGap(page);
  const editWithoutTtsWrite = await actions.editRoundTrip(page, editorKind, networkState);
  const mediaHttp = await actions.mediaContract(page, networkState);
  return Object.freeze({
    controls,
    cursor_keyboard_seek: keyboardSeek,
    edit_without_tts_write: editWithoutTtsWrite,
    editor: Object.freeze({
      codemirror_observed: editorKind === "codemirror6",
      kind: editorKind,
      textarea_fallback_observed: editorKind === "textarea-fallback",
    }),
    latest_wins: latestWins,
    media_http: mediaHttp,
    paragraph_context_menu_seek: contextMenuSeek,
    pending_gap: pendingGap,
    player: Object.freeze({ visible: playerVisible }),
  });
}

function nonzeroIntersection(left, right) {
  return (
    Math.min(left.right, right.right) > Math.max(left.left, right.left)
    && Math.min(left.bottom, right.bottom) > Math.max(left.top, right.top)
  );
}

export function isSafeFixedEditorPlayerOverlay(evidence) {
  if (
    evidence === null
    || typeof evidence !== "object"
    || evidence.exact_dom_relation !== true
    || evidence.player_position !== "sticky"
    || !["auto", "overlay", "scroll"].includes(evidence.scroll_container_overflow_y)
  ) return false;
  const playerHeight = Number(evidence.player_height);
  const stickyBottom = Number(evidence.sticky_bottom);
  const scrollContentPadding = Number(evidence.scroll_content_padding_bottom);
  const editorPadding = Number(evidence.editor_padding_bottom);
  if (
    !Number.isFinite(playerHeight)
    || !Number.isFinite(stickyBottom)
    || !Number.isFinite(scrollContentPadding)
    || !Number.isFinite(editorPadding)
    || playerHeight <= 0
    || stickyBottom < 0
  ) return false;
  const requiredPadding = playerHeight + stickyBottom;
  return scrollContentPadding >= requiredPadding && editorPadding >= requiredPadding;
}

/**
 * Reduce transient viewport-clipped geometry to count-only report evidence.
 * Coordinates and overlay mechanics never enter the report. A real editor /
 * player intersection is ignored only when the fixed DOM and computed-style
 * proof establishes the one intentional sticky safe-overlay arrangement.
 */
export function summarizeFixedLayoutGeometry(snapshot) {
  const visible = new Map(
    snapshot.regions.filter((region) => region.visible).map((region) => [region.key, region]),
  );
  const safeEditorPlayerOverlay = isSafeFixedEditorPlayerOverlay(snapshot.editor_player_overlay);
  let overlapCount = 0;
  for (const [leftKey, rightKey] of LAYOUT_MUTUALLY_EXCLUSIVE_PAIRS) {
    const left = visible.get(leftKey);
    const right = visible.get(rightKey);
    if (!left || !right) continue;
    if (!nonzeroIntersection(left, right)) continue;
    if (leftKey === "editor" && rightKey === "player" && safeEditorPlayerOverlay) continue;
    overlapCount += 1;
  }
  return Object.freeze({
    horizontal_overflow_px: Math.max(0, Math.ceil(snapshot.scroll_width - snapshot.inner_width)),
    nonzero_overlap_pair_count: overlapCount,
    tracked_visible_region_count: visible.size,
  });
}

export async function collectFixedLayoutObservation(page) {
  const snapshot = await page.evaluate(({ pairs, selectors }) => {
    const entries = Object.entries(selectors).map(([key, selector]) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return { element: null, key, visible: false };
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      const left = Math.max(0, Math.min(window.innerWidth, box.left));
      const right = Math.max(0, Math.min(window.innerWidth, box.right));
      const top = Math.max(0, Math.min(window.innerHeight, box.top));
      const bottom = Math.max(0, Math.min(window.innerHeight, box.bottom));
      return {
        bottom,
        element,
        key,
        left,
        right,
        top,
        visible: style.display !== "none"
          && style.visibility !== "hidden"
          && Number(style.opacity || "1") > 0
          && right > left
          && bottom > top,
      };
    });
    const byKey = new Map(entries.map((entry) => [entry.key, entry]));
    const containingPairs = [];
    for (const [leftKey, rightKey] of pairs) {
      const left = byKey.get(leftKey)?.element;
      const right = byKey.get(rightKey)?.element;
      if (!left || !right) continue;
      if (left.contains(right)) containingPairs.push([leftKey, rightKey]);
      else if (right.contains(left)) containingPairs.push([rightKey, leftKey]);
    }
    const editor = byKey.get("editor")?.element;
    const player = byKey.get("player")?.element;
    let editorPlayerOverlay = null;
    if (editor instanceof HTMLElement && player instanceof HTMLElement) {
      const scrollContainer = editor.closest(".anw-editor-content.has-chapter-narration");
      const scrollContent = editor.closest(".anw-editor-scroll");
      const editorPaddingTarget = editor.querySelector(
        ".cm-content[contenteditable=\"true\"], textarea.anw-chapter-editor-textarea-fallback",
      );
      const exactDomRelation = (
        scrollContainer instanceof HTMLElement
        && scrollContent instanceof HTMLElement
        && editorPaddingTarget instanceof HTMLElement
        && scrollContent.parentElement === scrollContainer
        && player.parentElement === scrollContainer
        && scrollContent.nextElementSibling === player
        && scrollContent.contains(editor)
        && editor.contains(editorPaddingTarget)
      );
      const playerStyle = getComputedStyle(player);
      const scrollContainerStyle = scrollContainer instanceof HTMLElement
        ? getComputedStyle(scrollContainer)
        : null;
      const scrollContentStyle = scrollContent instanceof HTMLElement
        ? getComputedStyle(scrollContent)
        : null;
      const editorStyle = editorPaddingTarget instanceof HTMLElement
        ? getComputedStyle(editorPaddingTarget)
        : null;
      editorPlayerOverlay = {
        editor_padding_bottom: Number.parseFloat(editorStyle?.paddingBottom ?? ""),
        exact_dom_relation: exactDomRelation,
        player_height: player.getBoundingClientRect().height,
        player_position: playerStyle.position,
        scroll_container_overflow_y: scrollContainerStyle?.overflowY ?? "",
        scroll_content_padding_bottom: Number.parseFloat(scrollContentStyle?.paddingBottom ?? ""),
        sticky_bottom: Number.parseFloat(playerStyle.bottom),
      };
    }
    return {
      containing_pairs: containingPairs,
      editor_player_overlay: editorPlayerOverlay,
      inner_width: window.innerWidth,
      regions: entries.map(({ element: _element, ...entry }) => entry),
      scroll_width: document.documentElement.scrollWidth,
    };
  }, {
    pairs: LAYOUT_MUTUALLY_EXCLUSIVE_PAIRS,
    selectors: LAYOUT_REGIONS,
  });
  return summarizeFixedLayoutGeometry(snapshot);
}

function executableSha256(path) {
  const details = lstatSync(path);
  if (!details.isFile() || details.isSymbolicLink()) {
    throw new ObserverError("OBSERVER_EXECUTABLE_IDENTITY_INVALID");
  }
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function codeSignIdentity() {
  const details = spawnSync(
    "/usr/bin/codesign",
    ["-dv", "--verbose=4", EDGE_APP_PATH],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  if (details.error || details.status !== 0) {
    throw new ObserverError("OBSERVER_EDGE_IDENTITY_INVALID");
  }
  // codesign intentionally emits display metadata on stderr.
  const output = `${details.stdout ?? ""}${details.stderr ?? ""}`;
  const value = (key) => output.match(new RegExp(`(?:^|\\n)${key}=([^\\n]+)`))?.[1] ?? null;
  const identity = {
    cdhash: value("CDHash"),
    identifier: value("Identifier"),
    team_identifier: value("TeamIdentifier"),
  };
  if (
    !identity.cdhash
    || identity.identifier !== EDGE_IDENTIFIER
    || identity.team_identifier !== EDGE_TEAM_IDENTIFIER
  ) {
    throw new ObserverError("OBSERVER_EDGE_IDENTITY_INVALID");
  }
  const deep = spawnSync(
    "/usr/bin/codesign",
    ["--verify", "--deep", EDGE_APP_PATH],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  if (deep.error || deep.status !== 0) {
    throw new ObserverError("OBSERVER_EDGE_IDENTITY_INVALID");
  }
  const strict = spawnSync(
    "/usr/bin/codesign",
    ["--verify", "--deep", "--strict", EDGE_APP_PATH],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const gatekeeper = spawnSync(
    "/usr/sbin/spctl",
    ["--assess", "--type", "execute", "--verbose=4", EDGE_APP_PATH],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const strictOutput = `${strict.stdout ?? ""}${strict.stderr ?? ""}`;
  const gatekeeperOutput = `${gatekeeper.stdout ?? ""}${gatekeeper.stderr ?? ""}`;
  return Object.freeze({
    ...identity,
    deep_verified: true,
    gatekeeper_accepted: !gatekeeper.error && gatekeeper.status === 0,
    gatekeeper_override_security_disabled: /(?:^|\n)override=security disabled(?:\n|$)/u.test(gatekeeperOutput),
    gatekeeper_result_sha256: sha256Bytes(Buffer.from(gatekeeperOutput, "utf8")),
    gatekeeper_source_notarized_developer_id: /(?:^|\n)source=Notarized Developer ID(?:\n|$)/u.test(gatekeeperOutput),
    strict_result_sha256: sha256Bytes(Buffer.from(strictOutput, "utf8")),
    strict_verified: !strict.error && strict.status === 0,
  });
}

export function assertStableBrowserIdentity(
  beforeCodesign,
  beforeExecutableSha256,
  afterCodesign,
  afterExecutableSha256,
) {
  if (
    typeof beforeExecutableSha256 !== "string"
    || !/^[0-9a-f]{64}$/u.test(beforeExecutableSha256)
    || afterExecutableSha256 !== beforeExecutableSha256
    || canonicalJson(afterCodesign) !== canonicalJson(beforeCodesign)
  ) {
    throw new ObserverError("OBSERVER_EDGE_IDENTITY_CHANGED");
  }
}

async function actualViewport(page) {
  return page.evaluate(() => ({
    device_pixel_ratio: window.devicePixelRatio,
    inner_height: window.innerHeight,
    inner_width: window.innerWidth,
    outer_height: window.outerHeight,
    outer_width: window.outerWidth,
    screen_height: window.screen.height,
    screen_width: window.screen.width,
  }));
}

async function calibrate(page, cdp, windowId, target) {
  const attempts = [];
  await cdp.send("Emulation.clearDeviceMetricsOverride");
  for (let index = 0; index < MAX_CALIBRATION_ATTEMPTS; index += 1) {
    const actual = await actualViewport(page);
    const bounds = (await cdp.send("Browser.getWindowBounds", { windowId })).bounds;
    attempts.push(Object.freeze({
      observed_inner_height: actual.inner_height,
      observed_inner_width: actual.inner_width,
      requested_outer_height: bounds.height,
      requested_outer_width: bounds.width,
    }));
    if (actual.inner_width === target.width && actual.inner_height === target.height) {
      return Object.freeze({ actual: Object.freeze(actual), attempts: Object.freeze(attempts) });
    }
    // macOS clamps headed windows to the physical display's visible frame.
    // After bounded real-window attempts, use Chromium's own device-metrics
    // override so the actual page inner size and screenshot still exercise
    // the exact frozen desktop viewport on smaller host displays.
    if (index === 2) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        deviceScaleFactor: actual.device_pixel_ratio,
        height: target.height,
        mobile: false,
        screenHeight: target.height,
        screenWidth: target.width,
        width: target.width,
      });
      await page.waitForTimeout(100);
      continue;
    }
    const nextWidth = Math.max(target.width, bounds.width + target.width - actual.inner_width);
    const nextHeight = Math.max(target.height, bounds.height + target.height - actual.inner_height);
    await cdp.send("Browser.setWindowBounds", {
      windowId,
      bounds: { width: nextWidth, height: nextHeight, windowState: "normal" },
    });
    await page.waitForTimeout(100);
  }
  throw new ObserverError("OBSERVER_VIEWPORT_CALIBRATION_FAILED");
}

async function setAssistantMode(page, mode) {
  const root = page.locator(ASSISTANT_ROOT);
  const toggle = page.locator(ASSISTANT_TOGGLE);
  await root.waitFor({ state: "visible" });
  const wantedCollapsed = mode === "collapsed";
  const current = await root.getAttribute("data-assistant-pane-collapsed");
  // The QwenPaw host may temporarily place a transparent pointer-capturing
  // rect above the wrapped workbench while its native pane settles.  Use the
  // toggle's keyboard contract so capture setup does not depend on pointer
  // hit-testing through a host-owned overlay.
  if (current !== String(wantedCollapsed)) await toggle.press("Enter");
  await page.waitForFunction(
    ({ selector, expected }) => document.querySelector(selector)?.getAttribute(
      "data-assistant-pane-collapsed",
    ) === expected,
    { selector: ASSISTANT_ROOT, expected: String(wantedCollapsed) },
  );
  return Object.freeze({
    collapsed_attribute: await root.getAttribute("data-assistant-pane-collapsed"),
    mode_attribute: await root.getAttribute("data-assistant-pane-mode"),
    observed_mode: wantedCollapsed ? "collapsed" : "expanded",
    toggle_aria_expanded: await toggle.getAttribute("aria-expanded"),
  });
}

async function dismissFixedHostTour(page) {
  const close = page.locator(HOST_TOUR_CLOSE);
  if (await close.count() === 0 || !await close.isVisible()) return;
  await close.click();
  const mask = page.locator(HOST_TOUR_MASK);
  if (await mask.count() > 0) await mask.waitFor({ state: "hidden" });
}

export async function collectFixedObservation(request, validationToken, dependencies = {}) {
  const launch = dependencies.launch ?? ((options) => loadFixedChromium().launch(options));
  const edgeSha = dependencies.edgeSha256 ?? (() => executableSha256(EDGE_PATH));
  const codesign = dependencies.codesignIdentity ?? codeSignIdentity;
  // Validate before hashing identities or launching a browser.  This projection
  // is discarded and neither the capability nor its digest enters the report.
  loopbackValidationHeaders({}, validationToken);
  // Establish the fixed executable identity before any browser process starts.
  const verifiedCodeSign = codesign();
  const verifiedEdgeSha256 = edgeSha();
  const browser = await launch({
    executablePath: EDGE_PATH,
    headless: false,
    timeout: 30_000,
  });
  try {
    const context = await browser.newContext({
      acceptDownloads: false,
      baseURL: FIXED_ORIGIN,
      bypassCSP: false,
      serviceWorkers: "block",
      viewport: null,
    });
    const consoleRows = [];
    const networkRows = [];
    const pageErrorRows = [];
    const policyBlockedExternalUrls = new Set();
    const networkState = {
      expectedRangeConsoleUrl: null,
      mediaCandidate: null,
      ttsWriteRequestCount: 0,
    };
    await context.route("**/*", async (route) => {
      const rawUrl = route.request().url();
      const decision = fixedRouteDecision(
        rawUrl,
        route.request().headers(),
        validationToken,
      );
      if (decision.action === "abort") {
        if (!recordFixedPolicyBlockedUrl(policyBlockedExternalUrls, rawUrl)) {
          throw new ObserverError("OBSERVER_ROUTE_ESCAPED");
        }
        await route.abort("blockedbyclient");
        return;
      }
      if (decision.headers) {
        await route.continue({ headers: decision.headers });
        return;
      }
      await route.continue();
    });
    context.on("request", (request) => trackRequest(networkState, request));
    context.on("console", (message) => {
      const location = message.location();
      const rawLocationUrl = location.url ?? "";
      const messageType = message.type();
      const messageText = message.text();
      if (isObserverInducedPolicyConsole(
        messageType,
        rawLocationUrl,
        messageText,
        policyBlockedExternalUrls,
      )) return;
      if (isObserverInducedRangeConsole(
        messageType,
        rawLocationUrl,
        messageText,
        networkState.expectedRangeConsoleUrl,
      )) return;
      consoleRows.push({
        kind: messageType,
        location: `${rawLocationUrl}:${location.lineNumber ?? 0}:${location.columnNumber ?? 0}`,
        message: messageText,
      });
    });
    context.on("weberror", (error) => {
      pageErrorRows.push({ kind: "pageerror", location: error.page()?.url() ?? "", message: error.error()?.message ?? "" });
    });
    context.on("response", (response) => {
      const request = response.request();
      networkRows.push({
        kind: request.resourceType(),
        location: response.url(),
        message: `${request.method()} ${response.status()}`,
      });
    });
    context.on("requestfailed", (request) => {
      networkRows.push({
        kind: request.resourceType(),
        location: request.url(),
        message: `${request.method()} FAILED ${request.failure()?.errorText ?? "unknown"}`,
      });
    });
    const page = await context.newPage();
    await page.goto(fixedWorkbenchUrl(request), { waitUntil: "domcontentloaded" });
    await page.locator(EDITOR_ROOT).waitFor({ state: "visible" });
    // A fresh isolated QwenPaw context shows its native desktop-mode tour.
    // Dismiss that fixed host chrome before exercising the PawApp; otherwise
    // its SVG mask legitimately intercepts every editor pointer action.
    await dismissFixedHostTour(page);
    let routeEvidence = finalRouteEvidence(page.url(), request);
    const cdp = await context.newCDPSession(page);
    const version = await cdp.send("Browser.getVersion");
    const { windowId } = await cdp.send("Browser.getWindowForTarget");
    // Real interactions must run in one of the four frozen desktop layouts.
    // Edge's ambient launch size can otherwise put the assistant overlay over
    // the editor and turn a valid control into an unclickable target.
    await calibrate(page, cdp, windowId, FIXED_CAPTURES[0]);
    await setAssistantMode(page, FIXED_CAPTURES[0].assistantMode);
    // Close any transient host navigation/drawer layer left open by the
    // root-to-session redirect before exercising workbench pointer controls.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
    const interactionEvidence = await (
      dependencies.collectInteractions ?? collectFixedInteractionEvidence
    )(page, networkState);
    const captures = [];
    for (const target of FIXED_CAPTURES) {
      const consoleStart = consoleRows.length;
      const pageErrorStart = pageErrorRows.length;
      const calibration = await calibrate(page, cdp, windowId, target);
      const assistant = await setAssistantMode(page, target.assistantMode);
      routeEvidence = finalRouteEvidence(page.url(), request);
      const actual = await actualViewport(page);
      if (actual.inner_width !== target.width || actual.inner_height !== target.height) {
        throw new ObserverError("OBSERVER_VIEWPORT_CHANGED");
      }
      const layoutObservation = await (
        dependencies.collectLayout ?? collectFixedLayoutObservation
      )(page);
      const png = await page.screenshot({
        animations: "disabled",
        caret: "hide",
        fullPage: false,
        scale: "device",
        type: "png",
      });
      const dimensions = pngDimensions(png);
      const expectedWidth = Math.round(target.width * actual.device_pixel_ratio);
      const expectedHeight = Math.round(target.height * actual.device_pixel_ratio);
      if (dimensions.width !== expectedWidth || dimensions.height !== expectedHeight) {
        throw new ObserverError("OBSERVER_SCREENSHOT_DIMENSION_MISMATCH");
      }
      captures.push(Object.freeze({
        assistant,
        calibration_attempts: calibration.attempts,
        console_summary: boundedDigestSummary(consoleRows.slice(consoleStart)),
        device_pixel_ratio: actual.device_pixel_ratio,
        layout_observation: layoutObservation,
        observed_inner_height: actual.inner_height,
        observed_inner_width: actual.inner_width,
        page_error_summary: boundedDigestSummary(pageErrorRows.slice(pageErrorStart)),
        screenshot_bytes: png.length,
        screenshot_pixel_height: dimensions.height,
        screenshot_pixel_width: dimensions.width,
        screenshot_png_base64: png.toString("base64"),
        screenshot_sha256: sha256Bytes(png),
        target_css_height: target.height,
        target_css_width: target.width,
      }));
    }
    routeEvidence = finalRouteEvidence(page.url(), request);
    assertStableBrowserIdentity(
      verifiedCodeSign,
      verifiedEdgeSha256,
      codesign(),
      edgeSha(),
    );
    const report = {
      browser_identity: {
        codesign: verifiedCodeSign,
        edge_executable_path: EDGE_PATH,
        edge_executable_sha256: verifiedEdgeSha256,
        js_version: version.jsVersion,
        node_executable_sha256: executableSha256(process.execPath),
        node_version: process.versions.node,
        playwright_core_version: PLAYWRIGHT_VERSION,
        product: version.product,
        protocol_version: version.protocolVersion,
        user_agent_sha256: sha256Bytes(Buffer.from(version.userAgent, "utf8")),
      },
      captures,
      console_summary: boundedDigestSummary(consoleRows),
      controller_id: CONTROLLER_ID,
      interaction_evidence: interactionEvidence,
      network_summary: boundedDigestSummary(networkRows),
      page_error_summary: boundedDigestSummary(pageErrorRows),
      request_fingerprint_sha256: request.request_fingerprint_sha256,
      route_evidence: routeEvidence,
      run_fingerprint_sha256: request.run_fingerprint_sha256,
      schema_version: REPORT_SCHEMA,
      target_scope_sha256: request.target_scope_sha256,
    };
    return Object.freeze({ ...report, report_sha256: sha256Bytes(Buffer.from(canonicalJson(report), "utf8")) });
  } finally {
    await browser.close();
  }
}
