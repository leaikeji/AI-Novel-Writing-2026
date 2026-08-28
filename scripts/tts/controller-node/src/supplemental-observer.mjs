import {
  FIXED_ORIGIN,
  ObserverError,
  loopbackValidationHeaders,
  sha256Bytes,
} from "./contracts.mjs";
import {
  collectFixedInteractionEvidence,
  collectFixedLayoutObservation,
  collectFixedObservation,
  fixedRouteDecision,
} from "./observer.mjs";
import {
  SUPPLEMENT_CAPTURES,
  SUPPLEMENT_CONTROLLER_ID,
  SUPPLEMENT_REPORT_SCHEMA,
  SUPPLEMENT_SELECTORS,
  SYSTEM_IME_CHECKPOINT_ID,
  SYSTEM_IME_OPERATOR_TIMEOUT_MS,
  TEXTAREA_FAULT_INJECTION_ID,
  SupplementalObserverError,
  baseObserverRequest,
  chapterSelector,
  classifySupplementRequest,
  finalizeSupplementReport,
  summarizeImeCheckpoint,
  supplementalWorkbenchUrl,
} from "./supplemental-contracts.mjs";


const EDITOR_DIGEST_ATTRIBUTE = "data-editor-value-sha256";
const SHA256 = /^[0-9a-f]{64}$/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const HOST_TOUR_CLOSE = ".qwenpaw-tour-close";
const IME_STATE_KEY = "__anwT4GateSupplementImeV1";
const FALLBACK_STATE_KEY = "__anwT4GateFallbackInjectionV1";
const PROGRESS_PROFILE = "desktop.default";
const MAX_EDITOR_RECOVERY_UNDOS = 128;
const EDITOR_RECOVERY_UNDO_SETTLE_MS = 200;

function observed(value) {
  return value ? "observed" : "not_observed";
}

async function visible(locator) {
  return await locator.count() === 1 && await locator.isVisible();
}

async function dismissHostTour(page) {
  const close = page.locator(HOST_TOUR_CLOSE);
  if (await close.count() > 0 && await close.isVisible()) await close.click();
}

async function waitForWorkbench(page) {
  await page.locator(SUPPLEMENT_SELECTORS.editor_root).waitFor({ state: "visible" });
  await dismissHostTour(page);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
}

async function editorKind(page) {
  if (await visible(page.locator(SUPPLEMENT_SELECTORS.code_mirror_root))) return "codemirror6";
  if (await visible(page.locator(SUPPLEMENT_SELECTORS.textarea))) return "textarea-fallback";
  return "not_observed";
}

async function editorDigest(page) {
  const value = await page.locator(SUPPLEMENT_SELECTORS.editor_root).getAttribute(
    EDITOR_DIGEST_ATTRIBUTE,
  );
  return typeof value === "string" && SHA256.test(value) ? value : null;
}

async function waitForDigest(page, wanted, timeout = 4_000) {
  try {
    await page.waitForFunction(
      ({ attribute, selector, value }) => document.querySelector(selector)?.getAttribute(attribute) === value,
      { attribute: EDITOR_DIGEST_ATTRIBUTE, selector: SUPPLEMENT_SELECTORS.editor_root, value: wanted },
      { timeout },
    );
    return true;
  } catch {
    return false;
  }
}

async function waitForDigestChange(page, baseline, timeout = 4_000) {
  try {
    await page.waitForFunction(
      ({ attribute, selector, value }) => {
        const digest = document.querySelector(selector)?.getAttribute(attribute);
        return typeof digest === "string" && /^[0-9a-f]{64}$/u.test(digest) && digest !== value;
      },
      { attribute: EDITOR_DIGEST_ATTRIBUTE, selector: SUPPLEMENT_SELECTORS.editor_root, value: baseline },
      { timeout },
    );
    return editorDigest(page);
  } catch {
    return null;
  }
}

async function setAssistantMode(page, mode) {
  const root = page.locator(SUPPLEMENT_SELECTORS.assistant_root);
  const toggle = page.locator(SUPPLEMENT_SELECTORS.assistant_toggle);
  await root.waitFor({ state: "visible" });
  const expected = String(mode === "collapsed");
  if (await root.getAttribute("data-assistant-pane-collapsed") !== expected) {
    await toggle.press("Enter");
  }
  await page.waitForFunction(
    ({ selector, value }) => document.querySelector(selector)?.getAttribute(
      "data-assistant-pane-collapsed",
    ) === value,
    { selector: SUPPLEMENT_SELECTORS.assistant_root, value: expected },
  );
}

async function installImeCheckpoint(page, selector, beforeHanCount) {
  await page.evaluate(({ key, selector: targetSelector, initialHanCount }) => {
    const prior = globalThis[key];
    if (prior?.cleanup) prior.cleanup();
    const target = document.querySelector(targetSelector);
    if (!(target instanceof HTMLElement)) throw new Error("supplement editor unavailable");
    const text = () => target instanceof HTMLTextAreaElement ? target.value : (target.textContent ?? "");
    const state = {
      cleanup: null,
      composing: false,
      end_seen: false,
      focus_preserved: true,
      initial_han_count: initialHanCount,
      seek_count: 0,
      trusted: { compositionstart: 0, compositionupdate: 0, compositionend: 0 },
      untrusted: 0,
    };
    const composition = (event) => {
      if (event.target !== target && !target.contains(event.target)) return;
      if (!event.isTrusted) {
        state.untrusted += 1;
        return;
      }
      state.trusted[event.type] += 1;
      if (event.type === "compositionstart") state.composing = true;
      if (event.type === "compositionend") {
        state.composing = false;
        state.end_seen = true;
      }
      if (document.activeElement !== target && !target.contains(document.activeElement)) {
        state.focus_preserved = false;
      }
    };
    const keydown = (event) => {
      if (state.composing && event.altKey && (event.metaKey || event.ctrlKey) && event.key === "Enter") {
        state.seek_count += 1;
      }
    };
    const overlay = document.createElement("div");
    overlay.setAttribute("data-t4-gate-system-ime-checkpoint", "true");
    overlay.setAttribute("role", "status");
    overlay.textContent = "T4 补证：请使用 macOS 系统中文输入法，在光标处输入并提交至少两个汉字。请勿粘贴或使用自动输入。";
    Object.assign(overlay.style, {
      background: "#fff7d6", border: "2px solid #9a6700", color: "#3b2f00",
      font: "600 16px/1.5 system-ui", left: "24px", maxWidth: "620px",
      padding: "14px 18px", position: "fixed", top: "24px", zIndex: "2147483647",
    });
    document.body.appendChild(overlay);
    for (const name of ["compositionstart", "compositionupdate", "compositionend"]) {
      document.addEventListener(name, composition, true);
    }
    document.addEventListener("keydown", keydown, true);
    state.cleanup = () => {
      for (const name of ["compositionstart", "compositionupdate", "compositionend"]) {
        document.removeEventListener(name, composition, true);
      }
      document.removeEventListener("keydown", keydown, true);
      overlay.remove();
    };
    state.read = () => ({
      end_seen: state.end_seen,
      focus_preserved_during_composition: state.focus_preserved,
      han_character_count_delta: Math.max(0, (text().match(/\p{Script=Han}/gu) ?? []).length - state.initial_han_count),
      playback_seek_during_composition_count: state.seek_count,
      selection_preserved_or_expected: target instanceof HTMLTextAreaElement
        ? target.selectionStart === target.selectionEnd
        : Boolean(getSelection()?.isCollapsed
          && getSelection()?.anchorNode
          && target.contains(getSelection().anchorNode)),
      trusted_counts: { ...state.trusted },
      untrusted_event_count: state.untrusted,
    });
    globalThis[key] = state;
    target.focus();
    if (target instanceof HTMLTextAreaElement) target.setSelectionRange(target.value.length, target.value.length);
    else {
      const selection = getSelection();
      const range = document.createRange();
      range.selectNodeContents(target);
      range.collapse(false);
      selection?.removeAllRanges();
      selection?.addRange(range);
    }
  }, { initialHanCount: beforeHanCount, key: IME_STATE_KEY, selector });
}

async function readAndClearImeCheckpoint(page) {
  return page.evaluate((key) => {
    const state = globalThis[key];
    const value = state?.read?.() ?? null;
    state?.cleanup?.();
    delete globalThis[key];
    return value;
  }, IME_STATE_KEY);
}

export async function recoverEditorHistory({ isBaseline, pressUndo }) {
  let restored = await isBaseline(200);
  for (let attempt = 0; !restored && attempt < MAX_EDITOR_RECOVERY_UNDOS; attempt += 1) {
    await pressUndo();
    restored = await isBaseline(EDITOR_RECOVERY_UNDO_SETTLE_MS);
  }
  return restored;
}

async function restoreEditor(page, selector, baselineDigest) {
  // A system IME may commit a longer phrase as several CodeMirror history
  // transactions.  Three undos only covered short probes and could leave a
  // valid operator checkpoint saved in the working copy.  Walk the bounded
  // editor history until the exact pre-checkpoint digest is reached; stop at
  // that digest so pre-existing author history is never crossed.
  const restored = await recoverEditorHistory({
    isBaseline: (timeout) => waitForDigest(page, baselineDigest, timeout),
    pressUndo: () => page.locator(selector).press("Meta+z"),
  });
  if (!restored) {
    throw new SupplementalObserverError("SUPPLEMENT_RECOVERY_FAILED", "failed");
  }
  // Autosave is 600 ms.  Let the normal CAS save the restored working copy,
  // then reload to prove the authoritative projection is back at baseline.
  await page.waitForTimeout(1_100);
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForWorkbench(page);
  if (!await waitForDigest(page, baselineDigest, 8_000)) {
    throw new SupplementalObserverError("SUPPLEMENT_RECOVERY_FAILED", "failed");
  }
}

export async function collectSystemImeCheckpoint(
  page,
  { assistantMode, baselineDigest, editor = "codemirror6", timeoutMs = SYSTEM_IME_OPERATOR_TIMEOUT_MS },
) {
  const selector = editor === "textarea-fallback"
    ? SUPPLEMENT_SELECTORS.textarea
    : SUPPLEMENT_SELECTORS.code_mirror_content;
  if (await editorDigest(page) !== baselineDigest || !await visible(page.locator(selector))) {
    throw new SupplementalObserverError("SUPPLEMENT_BASELINE_MISMATCH", "not_required");
  }
  const beforeWrites = page.__anwSupplementNetwork?.counts.tts_creation_write ?? 0;
  const beforeHanCount = await page.locator(selector).evaluate((element) => (
    ((element instanceof HTMLTextAreaElement ? element.value : element.textContent ?? "").match(/\p{Script=Han}/gu) ?? []).length
  ));
  await installImeCheckpoint(page, selector, beforeHanCount);
  let raw = null;
  try {
    await page.waitForFunction(
      (key) => {
        const value = globalThis[key]?.read?.();
        return value?.end_seen === true && value.han_character_count_delta >= 2;
      },
      IME_STATE_KEY,
      { timeout: timeoutMs },
    );
    raw = await readAndClearImeCheckpoint(page);
  } catch {
    raw = await readAndClearImeCheckpoint(page).catch(() => null);
    if (await editorDigest(page) !== baselineDigest) await restoreEditor(page, selector, baselineDigest);
    throw new SupplementalObserverError("SYSTEM_IME_OPERATOR_INPUT_REQUIRED", "restored");
  }
  let trusted;
  try {
    trusted = summarizeImeCheckpoint(raw);
  } catch (error) {
    if (await editorDigest(page) !== baselineDigest) await restoreEditor(page, selector, baselineDigest);
    throw error;
  }
  const committedDigest = await waitForDigestChange(page, baselineDigest);
  if (committedDigest === null) {
    if (await editorDigest(page) !== baselineDigest) await restoreEditor(page, selector, baselineDigest);
    throw new SupplementalObserverError("SYSTEM_IME_OPERATOR_INPUT_REQUIRED", "restored");
  }
  await restoreEditor(page, selector, baselineDigest);
  await setAssistantMode(page, assistantMode);
  const afterWrites = page.__anwSupplementNetwork?.counts.tts_creation_write ?? 0;
  return Object.freeze({
    ...trusted,
    after_sha256: await editorDigest(page),
    before_sha256: baselineDigest,
    checkpoint_id: SYSTEM_IME_CHECKPOINT_ID,
    committed_sha256: committedDigest,
    editor_kind: editor,
    editor_restored: await editorDigest(page) === baselineDigest,
    status: "observed",
    tts_write_request_count: Math.max(0, afterWrites - beforeWrites),
  });
}

export function codeMirrorFallbackFaultInjection() {
  // Keep this function self-contained: Playwright serializes it into the page
  // and no module closure is available there.
  const stateKey = "__anwT4GateFallbackInjectionV1";
  const nativeAppendChild = Node.prototype.appendChild;
  const state = { count: 0, restored: false };
  globalThis[stateKey] = state;
  Node.prototype.appendChild = function supplementalAppendChild(node) {
    if (
      state.count === 0
      && this instanceof HTMLElement
      && this.matches(".anw-chapter-editor-surface")
      && node instanceof HTMLElement
      && (
        node.matches(".cm-editor")
        // CodeMirror assigns the root's `cm-editor` class after appending it.
        // Its two direct structural children are already classified at the
        // append boundary, so they form the stable pre-class mount signature.
        || (
          node.tagName === "DIV"
          && Array.from(node.children).some((child) => child instanceof HTMLElement
            && child.matches(".cm-announced"))
          && Array.from(node.children).some((child) => child instanceof HTMLElement
            && child.matches(".cm-scroller"))
        )
      )
    ) {
      state.count = 1;
      Node.prototype.appendChild = nativeAppendChild;
      state.restored = true;
      throw new Error("T4_GATE_CODEMIRROR_ROOT_APPEND_THROW");
    }
    return nativeAppendChild.call(this, node);
  };
}

function installNetworkTracker(page) {
  const rows = [];
  const counts = {
    draft_write: 0,
    media_read: 0,
    other: 0,
    progress_write: 0,
    tts_creation_write: 0,
  };
  const onRequest = (request) => {
    const classified = classifySupplementRequest(
      request.method(), request.url(), request.postData(),
    );
    counts[classified.kind] += 1;
    rows.push(Object.freeze({
      edition_id_sha256: (() => {
        const header = request.headers()["x-narration-edition-id"];
        return typeof header === "string" && UUID.test(header)
          ? sha256Bytes(Buffer.from(header.toLowerCase(), "utf8"))
          : classified.resource_id_sha256;
      })(),
      intent: classified.intent,
      kind: classified.kind,
      scope_sha256: classified.scope_sha256,
    }));
  };
  page.on("request", onRequest);
  const tracker = {
    counts,
    rows,
    dispose() { page.off("request", onRequest); },
  };
  page.__anwSupplementNetwork = tracker;
  return tracker;
}

async function playerProjection(page) {
  const player = page.locator(SUPPLEMENT_SELECTORS.player);
  if (!await visible(player)) return null;
  let editionId;
  let ordinalRaw;
  let rateRaw;
  try {
    // A chapter switch can unmount the previously visible player between the
    // visibility probe and these reads. That transition means "no projection"
    // for the new chapter; it must not turn into Playwright's 30 s locator wait.
    editionId = await page.locator(
      `${SUPPLEMENT_SELECTORS.player} select[aria-label="选择章节朗读版本"]`,
    ).inputValue({ timeout: 1_000 });
    ordinalRaw = await player.getAttribute("data-current-ordinal", { timeout: 1_000 });
    rateRaw = await page.locator(SUPPLEMENT_SELECTORS.rate).inputValue({ timeout: 1_000 });
  } catch {
    return null;
  }
  if (!UUID.test(editionId)) return null;
  const ordinal = Number(ordinalRaw);
  const rateMillis = Math.round(Number(rateRaw) * 1_000);
  return Object.freeze({
    edition_id: editionId,
    edition_id_sha256: sha256Bytes(Buffer.from(editionId, "utf8")),
    ordinal: Number.isSafeInteger(ordinal) && ordinal >= 0 ? ordinal : 0,
    playback_rate_millis: rateMillis,
  });
}

async function progressApi(page, editionId, method = "GET", body = null) {
  return page.evaluate(async ({ body: requestBody, edition, method: requestMethod, profile }) => {
    const path = `/api/ai-novel-world-2026/narration-editions/${edition}/playback-progress?profile_id=${encodeURIComponent(profile)}`;
    const response = await fetch(path, {
      cache: "no-store",
      credentials: "same-origin",
      method: requestMethod,
      headers: requestBody === null
        ? { Accept: "application/json" }
        : { Accept: "application/json", "Content-Type": "application/json" },
      body: requestBody === null ? undefined : JSON.stringify(requestBody),
    });
    let value = null;
    try { value = await response.json(); } catch { /* fail closed below */ }
    return { ok: response.ok, status: response.status, value };
  }, { body, edition: editionId, method, profile: PROGRESS_PROFILE });
}

function progressProjection(response) {
  const progress = response?.value?.progress;
  if (!response?.ok || progress === null || typeof progress !== "object") return null;
  const fields = {
    edition_segment_id: progress.edition_segment_id,
    expected_updated_at: progress.progress_updated_at,
    last_legal_start_ordinal: progress.last_legal_start_ordinal,
    manifest_etag: progress.manifest_etag,
    manifest_revision: progress.manifest_revision,
    offset_ms: progress.offset_ms,
    ordinal: progress.ordinal,
    playback_rate_millis: progress.playback_rate_millis,
    segment_id: progress.segment_id,
    updated_at: progress.progress_updated_at,
  };
  if (
    !UUID.test(fields.edition_segment_id)
    || !UUID.test(fields.segment_id)
    || !Number.isSafeInteger(fields.ordinal)
    || !Number.isSafeInteger(fields.offset_ms)
    || !Number.isSafeInteger(fields.playback_rate_millis)
    || !Number.isSafeInteger(fields.manifest_revision)
    || typeof fields.manifest_etag !== "string"
    || typeof fields.updated_at !== "string"
  ) return null;
  return Object.freeze(fields);
}

function progressRestoreBody(baseline, current) {
  return Object.freeze({
    edition_segment_id: baseline.edition_segment_id,
    expected_updated_at: current.updated_at,
    last_legal_start_ordinal: baseline.last_legal_start_ordinal,
    manifest_etag: baseline.manifest_etag,
    manifest_revision: baseline.manifest_revision,
    offset_ms: baseline.offset_ms,
    playback_rate_millis: baseline.playback_rate_millis,
    profile_id: PROGRESS_PROFILE,
    segment_id: baseline.segment_id,
  });
}

async function waitProgressChange(page, editionId, baseline, timeout = 8_000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const current = progressProjection(await progressApi(page, editionId));
    if (current && current.updated_at !== baseline.updated_at) return current;
    await page.waitForTimeout(200);
  }
  return null;
}

async function collectProgressLifecycle(page, request) {
  const before = await playerProjection(page);
  if (!before) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_UNAVAILABLE");
  const baseline = progressProjection(await progressApi(page, before.edition_id));
  if (!baseline) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_BASELINE_REQUIRED");
  const rate = page.locator(SUPPLEMENT_SELECTORS.rate);
  const options = await rate.locator("option").evaluateAll((nodes) => nodes.map((node) => node.value));
  const nextRate = options.find((value) => Math.round(Number(value) * 1_000) !== baseline.playback_rate_millis);
  if (!nextRate) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_UNAVAILABLE");
  let restored = false;
  try {
    await rate.selectOption(nextRate);
    const changed = await waitProgressChange(page, before.edition_id, baseline);
    if (!changed) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_SAVE_NOT_OBSERVED");
    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForWorkbench(page);
    await page.locator(SUPPLEMENT_SELECTORS.player).waitFor({ state: "visible" });
    const afterReload = await playerProjection(page);
    const reloadRestored = afterReload?.edition_id === before.edition_id
      && afterReload.ordinal === changed.ordinal
      && afterReload.playback_rate_millis === changed.playback_rate_millis;

    const fresh = await page.context().newPage();
    let freshProjection = null;
    try {
      await fresh.goto(supplementalWorkbenchUrl(request), { waitUntil: "domcontentloaded" });
      await waitForWorkbench(fresh);
      await fresh.locator(SUPPLEMENT_SELECTORS.player).waitFor({ state: "visible" });
      freshProjection = await playerProjection(fresh);
    } finally {
      await fresh.close();
    }
    // Close a successfully restored page and open a second fresh page.  The
    // primary evidence page stays alive only so the enclosing fixed observer
    // can continue its four captures; this pair is the explicit close/reopen
    // lifecycle under test.
    const reopened = await page.context().newPage();
    let reopenedProjection = null;
    try {
      await reopened.goto(supplementalWorkbenchUrl(request), { waitUntil: "domcontentloaded" });
      await waitForWorkbench(reopened);
      await reopened.locator(SUPPLEMENT_SELECTORS.player).waitFor({ state: "visible" });
      reopenedProjection = await playerProjection(reopened);
    } finally {
      await reopened.close();
    }
    const closeReopenRestored = freshProjection?.edition_id === before.edition_id
      && freshProjection.ordinal === changed.ordinal
      && freshProjection.playback_rate_millis === changed.playback_rate_millis
      && reopenedProjection?.edition_id === before.edition_id
      && reopenedProjection.ordinal === changed.ordinal
      && reopenedProjection.playback_rate_millis === changed.playback_rate_millis;

    const current = progressProjection(await progressApi(page, before.edition_id));
    if (!current) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_RECOVERY_FAILED", "failed");
    const restore = progressProjection(await progressApi(
      page, before.edition_id, "PUT", progressRestoreBody(baseline, current),
    ));
    restored = restore?.ordinal === baseline.ordinal
      && restore.offset_ms === baseline.offset_ms
      && restore.playback_rate_millis === baseline.playback_rate_millis;
    if (!restored) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_RECOVERY_FAILED", "failed");
    return Object.freeze({
      baseline_projection_sha256: sha256Bytes(Buffer.from(JSON.stringify(baseline), "utf8")),
      close_reopen_restored: closeReopenRestored,
      edition_id_sha256: before.edition_id_sha256,
      offset_tolerance_ms: 1_500,
      progress_put_observed: true,
      reload_restored: reloadRestored,
      restored_projection_sha256: sha256Bytes(Buffer.from(JSON.stringify(restore), "utf8")),
      status: observed(reloadRestored && closeReopenRestored && restored),
    });
  } finally {
    if (!restored) {
      const current = progressProjection(await progressApi(page, before.edition_id).catch(() => null));
      if (current) {
        const restore = progressProjection(await progressApi(
          page, before.edition_id, "PUT", progressRestoreBody(baseline, current),
        ).catch(() => null));
        restored = restore?.ordinal === baseline.ordinal
          && restore.offset_ms === baseline.offset_ms
          && restore.playback_rate_millis === baseline.playback_rate_millis;
      }
      if (!restored) throw new SupplementalObserverError("SUPPLEMENT_PROGRESS_RECOVERY_FAILED", "failed");
    }
  }
}

async function collectChapterSwitch(page, request, tracker) {
  const before = await playerProjection(page);
  const generationA = Number(await page.locator(SUPPLEMENT_SELECTORS.editor_root).getAttribute("data-editor-generation"));
  if (!before || !Number.isSafeInteger(generationA)) {
    throw new SupplementalObserverError("SUPPLEMENT_CHAPTER_SWITCH_UNAVAILABLE");
  }
  const clickChapter = async (documentId) => {
    const target = page.locator(chapterSelector(documentId));
    await target.waitFor({ state: "visible" });
    await target.press("Enter");
    await page.waitForFunction(
      (wanted) => new URL(location.href).searchParams.get("document_id") === wanted,
      documentId,
    );
    try {
      await page.locator(SUPPLEMENT_SELECTORS.editor_root).waitFor({ state: "visible" });
    } catch {
      throw new SupplementalObserverError(
        "SUPPLEMENT_CHAPTER_SWITCH_EDITOR_UNAVAILABLE",
        "not_required",
      );
    }
  };
  const networkStart = tracker.rows.length;
  await clickChapter(request.secondary_document_id);
  const generationB = Number(await page.locator(SUPPLEMENT_SELECTORS.editor_root).getAttribute("data-editor-generation"));
  const playerAInactiveOnB = !await visible(page.locator(SUPPLEMENT_SELECTORS.player))
    || (await playerProjection(page))?.edition_id !== before.edition_id;
  await page.waitForTimeout(500);
  const stalePrimaryActionCount = tracker.rows.slice(networkStart).filter((row) => (
    row.kind === "media_read" && row.edition_id_sha256 === before.edition_id_sha256
  )).length;
  await clickChapter(request.primary_document_id);
  const generationReturn = Number(await page.locator(SUPPLEMENT_SELECTORS.editor_root).getAttribute("data-editor-generation"));
  await page.locator(SUPPLEMENT_SELECTORS.player).waitFor({ state: "visible" });
  const after = await playerProjection(page);
  const passed = generationB > generationA
    && generationReturn > generationB
    && playerAInactiveOnB
    && stalePrimaryActionCount === 0
    && after?.edition_id === before.edition_id;
  return Object.freeze({
    generation_a: generationA,
    generation_b: generationB,
    generation_return: generationReturn,
    player_a_inactive_on_b: playerAInactiveOnB,
    primary_edition_id_sha256: before.edition_id_sha256,
    restored_same_edition: after?.edition_id === before.edition_id,
    stale_primary_action_count: stalePrimaryActionCount,
    status: observed(passed),
  });
}

async function collectOldDraftUpdate(page, tracker, baselineDigest) {
  const player = page.locator(SUPPLEMENT_SELECTORS.player);
  const before = await playerProjection(page);
  if (!before || await editorDigest(page) !== baselineDigest) {
    throw new SupplementalObserverError("SUPPLEMENT_BASELINE_MISMATCH");
  }
  const editor = await editorKind(page);
  const selector = editor === "codemirror6"
    ? SUPPLEMENT_SELECTORS.code_mirror_content
    : SUPPLEMENT_SELECTORS.textarea;
  const ttsBefore = tracker.counts.tts_creation_write;
  const draftBefore = tracker.counts.draft_write;
  let explicitIntent = null;
  let oldDraftVisible = false;
  let unchangedEdition = false;
  let automaticWrites = 0;
  let gutterUpdateRequired = false;
  let restored = false;
  const requestPattern = /\/api\/ai-novel-world-2026\/documents\/[0-9a-f-]{36}\/narration-requests$/iu;
  const intercept = async (route) => {
    const classified = classifySupplementRequest(
      route.request().method(), route.request().url(), route.request().postData(),
    );
    explicitIntent = classified.intent;
    await route.fulfill({
      body: JSON.stringify({ detail: { code: "SUPPLEMENT_CONTROLLED_UPDATE_STOP", message: "supplemental observer stopped before synthesis" } }),
      contentType: "application/json",
      status: 503,
    });
  };
  try {
    await page.locator(selector).press("End");
    await page.locator(selector).press("Space");
    await page.waitForFunction(
      (selector) => document.querySelector(selector)?.getAttribute("data-source-kind") === "working-copy-diverged",
      SUPPLEMENT_SELECTORS.player,
    );
    const update = page.getByRole("button", { name: "更新朗读", exact: true });
    oldDraftVisible = await player.getAttribute("data-source-kind") === "working-copy-diverged"
      && await update.isVisible() && await update.isEnabled();
    unchangedEdition = (await playerProjection(page))?.edition_id === before.edition_id;
    automaticWrites = tracker.counts.tts_creation_write - ttsBefore;
    gutterUpdateRequired = editor !== "codemirror6" || await page.locator(
      ".anw-chapter-paragraph-gutter-button[data-availability=\"update_required\"]:disabled",
    ).count() >= 1;
    await page.route(requestPattern, intercept);
    try {
      await update.press("Enter");
      const started = Date.now();
      while (explicitIntent === null && Date.now() - started < 8_000) await page.waitForTimeout(100);
    } finally {
      await page.unroute(requestPattern, intercept);
    }
  } finally {
    if (await editorDigest(page) !== baselineDigest) {
      await restoreEditor(page, selector, baselineDigest);
    }
    restored = await editorDigest(page) === baselineDigest;
  }
  return Object.freeze({
    automatic_tts_write_count: automaticWrites,
    baseline_edition_unchanged: unchangedEdition,
    controlled_update_response_status: 503,
    draft_write_count: tracker.counts.draft_write - draftBefore,
    explicit_update_intent: explicitIntent,
    gutter_update_required_observed: gutterUpdateRequired,
    old_audio_remained_available: await visible(page.locator(SUPPLEMENT_SELECTORS.player)),
    old_draft_marker_visible: oldDraftVisible,
    source_restored: restored,
    status: observed(oldDraftVisible && unchangedEdition && automaticWrites === 0 && gutterUpdateRequired && explicitIntent === "update" && restored),
    synthesis_completed_claimed: false,
  });
}

async function collectFocusAria(page) {
  const player = page.locator(SUPPLEMENT_SELECTORS.player);
  const controls = player.locator("button:visible:not(:disabled), input:visible:not(:disabled), select:visible:not(:disabled)");
  const controlFacts = await controls.evaluateAll((nodes) => nodes.map((node) => ({
    accessible_name_nonempty: Boolean(node.getAttribute("aria-label") || node.textContent?.trim() || node.getAttribute("title")),
    keyboard_reachable: node instanceof HTMLElement && node.tabIndex >= 0,
  })));
  const first = controls.first();
  const style = async () => first.evaluate((node) => {
    const value = getComputedStyle(node);
    return `${value.outlineStyle}|${value.outlineWidth}|${value.outlineColor}|${value.boxShadow}`;
  });
  // Enter and leave the first control through the real keyboard focus order;
  // programmatic focus alone does not establish :focus-visible behavior.
  await first.focus();
  await page.keyboard.press("Shift+Tab");
  const beforeStyle = await style();
  await page.keyboard.press("Tab");
  const focusedStyle = await style();
  const firstFocused = await first.evaluate((node) => document.activeElement === node);
  const focusVisibleStyleObserved = firstFocused && beforeStyle !== focusedStyle;

  const editor = (await editorKind(page)) === "codemirror6"
    ? page.locator(SUPPLEMENT_SELECTORS.code_mirror_content)
    : page.locator(SUPPLEMENT_SELECTORS.textarea);
  await editor.click({ button: "right" });
  const menuItem = page.locator(SUPPLEMENT_SELECTORS.context_menu_command);
  await menuItem.waitFor({ state: "visible" });
  const menuFocused = await menuItem.evaluate((node) => document.activeElement === node);
  await page.keyboard.press("Escape");
  const editorFocusRestored = await editor.evaluate((node) => document.activeElement === node || node.contains(document.activeElement));

  const reviewTrigger = page.getByRole("button", { name: "复核脚本", exact: true });
  let review = {
    aria_references_exist: false,
    dialog_focus_observed: false,
    trigger_focus_restored: false,
  };
  if (await visible(reviewTrigger)) {
    await reviewTrigger.focus();
    await reviewTrigger.press("Enter");
    const dialog = page.locator(SUPPLEMENT_SELECTORS.review_dialog);
    await dialog.waitFor({ state: "visible" });
    review = await dialog.evaluate((node) => {
      const labelledby = node.getAttribute("aria-labelledby");
      const describedby = node.getAttribute("aria-describedby");
      return {
        aria_references_exist: Boolean(labelledby && describedby && document.getElementById(labelledby) && document.getElementById(describedby)),
        dialog_focus_observed: node.contains(document.activeElement),
        trigger_focus_restored: false,
      };
    });
    await page.getByRole("button", { name: "关闭脚本复核", exact: true }).press("Enter");
    review.trigger_focus_restored = await reviewTrigger.evaluate((node) => document.activeElement === node);
  }
  const liveRegion = page.locator(SUPPLEMENT_SELECTORS.live_region);
  const liveRegionPolite = await visible(liveRegion)
    && await liveRegion.getAttribute("role") === "status"
    && await liveRegion.getAttribute("aria-live") === "polite";
  return Object.freeze({
    all_control_names_nonempty: controlFacts.length > 0 && controlFacts.every((row) => row.accessible_name_nonempty),
    all_visible_enabled_controls_keyboard_reachable: controlFacts.length > 0 && controlFacts.every((row) => row.keyboard_reachable),
    context_menu_focus_observed: menuFocused,
    editor_focus_restored: editorFocusRestored,
    focus_visible_style_observed: focusVisibleStyleObserved,
    live_region_polite: liveRegionPolite,
    review: Object.freeze(review),
    visible_enabled_control_count: controlFacts.length,
  });
}

async function focusAriaSentinel(page) {
  const player = page.locator(SUPPLEMENT_SELECTORS.player);
  const controls = player.locator("button:visible:not(:disabled), input:visible:not(:disabled), select:visible:not(:disabled)");
  const facts = await controls.evaluateAll((nodes) => nodes.map((node) => ({
    name: Boolean(node.getAttribute("aria-label") || node.textContent?.trim() || node.getAttribute("title")),
    reachable: node instanceof HTMLElement && node.tabIndex >= 0,
  })));
  return Object.freeze({
    all_control_names_nonempty: facts.length > 0 && facts.every((row) => row.name),
    all_controls_keyboard_reachable: facts.length > 0 && facts.every((row) => row.reachable),
    control_count: facts.length,
  });
}

async function fallbackContext(page, validationToken) {
  const storageState = await page.context().storageState();
  const browser = page.context().browser();
  if (!browser) throw new SupplementalObserverError("SUPPLEMENT_BROWSER_UNAVAILABLE");
  const context = await browser.newContext({
    acceptDownloads: false,
    baseURL: FIXED_ORIGIN,
    bypassCSP: false,
    serviceWorkers: "block",
    storageState,
    viewport: { width: 1920, height: 1080 },
  });
  await context.addInitScript(codeMirrorFallbackFaultInjection);
  await context.route("**/*", async (route) => {
    const decision = fixedRouteDecision(route.request().url(), route.request().headers(), validationToken);
    if (decision.action === "abort") await route.abort("blockedbyclient");
    else await route.continue({ headers: decision.headers });
  });
  return context;
}

async function collectTextareaFallback(primaryPage, request, validationToken) {
  const context = await fallbackContext(primaryPage, validationToken);
  try {
    const page = await context.newPage();
    installNetworkTracker(page);
    await page.goto(supplementalWorkbenchUrl(request), { waitUntil: "domcontentloaded" });
    await waitForWorkbench(page);
    const kind = await editorKind(page);
    const injection = await page.evaluate((key) => globalThis[key] ?? null, FALLBACK_STATE_KEY);
    if (kind !== "textarea-fallback" || injection?.count !== 1 || injection?.restored !== true) {
      throw new SupplementalObserverError("SUPPLEMENT_TEXTAREA_FALLBACK_NOT_OBSERVED");
    }
    const baseline = await editorDigest(page);
    if (baseline !== request.baseline_source_sha256) {
      throw new SupplementalObserverError("SUPPLEMENT_BASELINE_MISMATCH");
    }
    await setAssistantMode(page, "collapsed");
    const ime = await collectSystemImeCheckpoint(page, {
      assistantMode: "collapsed", baselineDigest: baseline, editor: "textarea-fallback",
    });
    const textarea = page.locator(SUPPLEMENT_SELECTORS.textarea);
    const accessibleName = await textarea.getAttribute("aria-label");
    const sentinels = [];
    for (const target of SUPPLEMENT_CAPTURES) {
      await page.setViewportSize({ width: target.width, height: target.height });
      await setAssistantMode(page, target.assistantMode);
      sentinels.push(Object.freeze({
        assistant_mode: target.assistantMode,
        code_mirror_absent: await page.locator(SUPPLEMENT_SELECTORS.code_mirror_root).count() === 0,
        focus_aria: await focusAriaSentinel(page),
        observed_inner_height: await page.evaluate(() => innerHeight),
        observed_inner_width: await page.evaluate(() => innerWidth),
        target_css_height: target.height,
        target_css_width: target.width,
        textarea_visible: await visible(textarea),
      }));
    }
    return Object.freeze({
      accessible_name_nonempty: Boolean(accessibleName?.trim()),
      audio_playable: await visible(page.locator(SUPPLEMENT_SELECTORS.player)),
      code_mirror_absent: true,
      fault_injection_count: injection.count,
      fault_injection_id: TEXTAREA_FAULT_INJECTION_ID,
      gutter_count: await page.locator(".cm-gutters").count(),
      ime,
      sentinels: Object.freeze(sentinels),
      status: "observed",
      textarea_visible: true,
    });
  } finally {
    await context.close();
  }
}

export async function collectSupplementalObservation(request, validationToken, dependencies = {}) {
  loopbackValidationHeaders({}, validationToken);
  const state = {
    chapterSwitch: null,
    finalSourceDigest: null,
    focusAria: null,
    focusAriaCaptures: [],
    oldDraftUpdate: null,
    progressLifecycle: null,
    systemIme: [],
    textareaFallback: null,
  };
  const baseRequest = baseObserverRequest(request);
  const collectBase = dependencies.collectBase ?? collectFixedObservation;
  const baseObservation = await collectBase(baseRequest, validationToken, {
    ...(dependencies.baseDependencies ?? {}),
    collectInteractions: async (page, networkState) => {
      const tracker = installNetworkTracker(page);
      // Keep the tracker attached through the four subsequent layout/IME
      // captures. The browser context owns its lifetime and closes it after
      // collection; disposing here would make later "zero TTS writes" claims
      // unobservable rather than proven.
      const baseInteractions = await collectFixedInteractionEvidence(page, networkState);
      state.oldDraftUpdate = await collectOldDraftUpdate(page, tracker, request.baseline_source_sha256);
      state.progressLifecycle = await collectProgressLifecycle(page, request);
      state.chapterSwitch = await collectChapterSwitch(page, request, tracker);
      state.focusAria = await collectFocusAria(page);
      state.textareaFallback = await collectTextareaFallback(page, request, validationToken);
      return baseInteractions;
    },
    collectLayout: async (page) => {
      const width = await page.evaluate(() => innerWidth);
      const height = await page.evaluate(() => innerHeight);
      const collapsed = await page.locator(SUPPLEMENT_SELECTORS.assistant_root).getAttribute(
        "data-assistant-pane-collapsed",
      );
      const assistantMode = collapsed === "true" ? "collapsed" : "expanded";
      const target = SUPPLEMENT_CAPTURES.find((row) => (
        row.width === width && row.height === height && row.assistantMode === assistantMode
      ));
      if (!target) throw new SupplementalObserverError("SUPPLEMENT_VIEWPORT_OUT_OF_SCOPE");
      const ime = await collectSystemImeCheckpoint(page, {
        assistantMode, baselineDigest: request.baseline_source_sha256, editor: "codemirror6",
      });
      state.systemIme.push(Object.freeze({
        ...ime,
        assistant_mode: assistantMode,
        target_css_height: height,
        target_css_width: width,
      }));
      state.focusAriaCaptures.push(Object.freeze({
        assistant_mode: assistantMode,
        ...(await focusAriaSentinel(page)),
        target_css_height: height,
        target_css_width: width,
      }));
      state.finalSourceDigest = await editorDigest(page);
      if (state.finalSourceDigest !== request.baseline_source_sha256) {
        throw new SupplementalObserverError("SUPPLEMENT_RECOVERY_FAILED", "failed");
      }
      return collectFixedLayoutObservation(page);
    },
  });
  if (
    state.systemIme.length !== SUPPLEMENT_CAPTURES.length
    || state.focusAriaCaptures.length !== SUPPLEMENT_CAPTURES.length
    || state.chapterSwitch === null
    || state.finalSourceDigest !== request.baseline_source_sha256
    || state.focusAria === null
    || state.oldDraftUpdate === null
    || state.progressLifecycle === null
    || state.textareaFallback === null
  ) throw new SupplementalObserverError("SUPPLEMENT_EVIDENCE_INCOMPLETE", "restored");
  const captures = baseObservation.captures.map((capture) => Object.freeze({
    assistant_mode: capture.assistant.observed_mode,
    console_count: capture.console_summary.count,
    console_dropped_count: capture.console_summary.dropped_count,
    console_summary_sha256: capture.console_summary.summary_sha256,
    device_pixel_ratio: capture.device_pixel_ratio,
    horizontal_overflow_px: capture.layout_observation.horizontal_overflow_px,
    nonzero_overlap_pair_count: capture.layout_observation.nonzero_overlap_pair_count,
    observed_inner_height: capture.observed_inner_height,
    observed_inner_width: capture.observed_inner_width,
    page_error_count: capture.page_error_summary.count,
    page_error_dropped_count: capture.page_error_summary.dropped_count,
    page_error_summary_sha256: capture.page_error_summary.summary_sha256,
    screenshot_bytes: capture.screenshot_bytes,
    screenshot_pixel_height: capture.screenshot_pixel_height,
    screenshot_pixel_width: capture.screenshot_pixel_width,
    screenshot_sha256: capture.screenshot_sha256,
    target_css_height: capture.target_css_height,
    target_css_width: capture.target_css_width,
  }));
  return finalizeSupplementReport({
    base_observation: baseObservation,
    browser_identity: baseObservation.browser_identity,
    captures: Object.freeze(captures),
    chapter_switch: state.chapterSwitch,
    controller_id: SUPPLEMENT_CONTROLLER_ID,
    fixture_manifest_sha256: request.fixture_manifest_sha256,
    focus_aria: Object.freeze({ ...state.focusAria, captures: Object.freeze(state.focusAriaCaptures) }),
    novel_id: request.novel_id,
    old_draft_update: state.oldDraftUpdate,
    primary_document_id: request.primary_document_id,
    progress_lifecycle: state.progressLifecycle,
    recovery: Object.freeze({
      baseline_source_sha256: request.baseline_source_sha256,
      final_source_sha256: state.finalSourceDigest,
      status: "restored",
    }),
    request_fingerprint_sha256: request.request_fingerprint_sha256,
    route_evidence: baseObservation.route_evidence,
    schema_version: SUPPLEMENT_REPORT_SCHEMA,
    secondary_document_id: request.secondary_document_id,
    supplement_run_id: request.supplement_run_id,
    system_ime: Object.freeze(state.systemIme),
    target_scope_sha256: request.target_scope_sha256,
    textarea_fallback: state.textareaFallback,
  });
}

export function holdProjection(error) {
  const supplemental = error instanceof SupplementalObserverError;
  return Object.freeze({
    error_code: supplemental || error instanceof ObserverError ? error.code : "SUPPLEMENT_FAILED",
    recovery_status: supplemental ? error.recoveryStatus : "unknown",
    status: "hold",
  });
}
