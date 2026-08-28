import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { canonicalJson } from "../src/contracts.mjs";
import {
  SUPPLEMENT_CAPTURES,
  SUPPLEMENT_REQUEST_SCHEMA,
  SUPPLEMENT_REPORT_SCHEMA,
  SUPPLEMENT_SELECTORS,
  SupplementalObserverError,
  baseObserverRequest,
  baseRunFingerprint,
  chapterSelector,
  classifySupplementRequest,
  finalizeSupplementReport,
  parseCanonicalSupplementRequest,
  summarizeImeCheckpoint,
  supplementalWorkbenchUrl,
} from "../src/supplemental-contracts.mjs";
import {
  codeMirrorFallbackFaultInjection,
  holdProjection,
  recoverEditorHistory,
} from "../src/supplemental-observer.mjs";


const request = Object.freeze({
  baseline_source_sha256: "a".repeat(64),
  fixture_manifest_sha256: "b".repeat(64),
  novel_id: "11111111-1111-4111-8111-111111111111",
  primary_document_id: "22222222-2222-4222-8222-222222222222",
  request_fingerprint_sha256: "c".repeat(64),
  schema_version: SUPPLEMENT_REQUEST_SCHEMA,
  secondary_document_id: "33333333-3333-4333-8333-333333333333",
  supplement_run_id: "44444444-4444-4444-8444-444444444444",
  target_scope_sha256: "d".repeat(64),
});

test("supplement request is exact, canonical and cannot carry browser controls", () => {
  const raw = Buffer.from(`${canonicalJson(request)}\n`, "utf8");
  assert.deepEqual(parseCanonicalSupplementRequest(raw), request);
  for (const invalid of [
    Buffer.from(`${JSON.stringify(request, null, 2)}\n`),
    Buffer.from(`${canonicalJson({ ...request, viewport: { width: 800, height: 600 } })}\n`),
    Buffer.from(`${canonicalJson({ ...request, secondary_document_id: request.primary_document_id })}\n`),
    Buffer.from(`${canonicalJson({ ...request, validation_token: "x".repeat(43) })}\n`),
  ]) assert.throws(
    () => parseCanonicalSupplementRequest(invalid),
    (error) => error instanceof SupplementalObserverError
      && error.code === "SUPPLEMENT_REQUEST_INVALID",
  );
});

test("base observer adapter is primary-document scoped and deterministic", () => {
  const adapted = baseObserverRequest(request);
  assert.equal(adapted.document_id, request.primary_document_id);
  assert.equal(adapted.novel_id, request.novel_id);
  assert.equal(adapted.run_fingerprint_sha256, baseRunFingerprint(request));
  assert.match(adapted.run_fingerprint_sha256, /^[a-f0-9]{64}$/u);
  const url = new URL(supplementalWorkbenchUrl(request));
  assert.equal(url.origin, "http://127.0.0.1:18088");
  assert.equal(url.pathname, "/chat");
  assert.equal(url.searchParams.get("document_id"), request.primary_document_id);
  assert.equal(chapterSelector(request.secondary_document_id),
    `.anw-chapter-tree-chapter[data-document-id="${request.secondary_document_id}"]`);
});

test("desktop capture matrix and production selectors are fixed in code", () => {
  assert.deepEqual(SUPPLEMENT_CAPTURES, [
    { width: 1920, height: 1080, assistantMode: "collapsed" },
    { width: 1920, height: 1080, assistantMode: "expanded" },
    { width: 2560, height: 1440, assistantMode: "collapsed" },
    { width: 2560, height: 1440, assistantMode: "expanded" },
  ]);
  assert.equal(SUPPLEMENT_SELECTORS.textarea,
    ".anw-chapter-editor-surface textarea.anw-chapter-editor-textarea-fallback");
  assert.match(SUPPLEMENT_SELECTORS.player, /章节智能朗读播放器/u);
  assert.ok(!Object.values(SUPPLEMENT_SELECTORS).some((value) => /mobile|800|720/u.test(value)));
});

test("system IME accepts only trusted complete composition with Han delta", () => {
  const valid = summarizeImeCheckpoint({
    focus_preserved_during_composition: true,
    han_character_count_delta: 2,
    playback_seek_during_composition_count: 0,
    selection_preserved_or_expected: true,
    trusted_counts: { compositionstart: 1, compositionupdate: 3, compositionend: 1 },
    untrusted_event_count: 0,
  });
  assert.equal(valid.input_source_class, "system_chinese");
  assert.equal(valid.operator_confirmed, true);
  for (const invalid of [
    { ...valid, untrusted_event_count: 1 },
    { ...valid, han_character_count_delta: 0 },
    { ...valid, han_character_count_delta: 1 },
    { ...valid, trusted_counts: { compositionstart: 1, compositionupdate: 0, compositionend: 1 } },
    { ...valid, playback_seek_during_composition_count: 1 },
  ]) assert.throws(
    () => summarizeImeCheckpoint(invalid),
    (error) => error instanceof SupplementalObserverError
      && error.code === "SYSTEM_IME_OPERATOR_INPUT_REQUIRED"
      && error.recoveryStatus === "restored",
  );
});

test("network classifier separates derivative progress, draft and synthesis writes", () => {
  const root = "http://127.0.0.1:18088/api/ai-novel-world-2026";
  assert.equal(classifySupplementRequest(
    "PUT", `${root}/narration-editions/${request.supplement_run_id}/playback-progress?profile_id=desktop.default`,
  ).kind, "progress_write");
  assert.equal(classifySupplementRequest(
    "PATCH", `${root}/documents/${request.primary_document_id}/draft`,
  ).kind, "draft_write");
  const update = classifySupplementRequest(
    "POST", `${root}/documents/${request.primary_document_id}/narration-requests`,
    JSON.stringify({ intent: "update" }),
  );
  assert.equal(update.kind, "tts_creation_write");
  assert.equal(update.intent, "update");
  assert.match(update.scope_sha256, /^[a-f0-9]{64}$/u);
  assert.equal(classifySupplementRequest("GET", `${root}/narration-overview`).kind, "other");
  assert.equal(classifySupplementRequest(
    "GET", `${root}/media-assets/${request.supplement_run_id}/content`,
  ).kind, "media_read");
});

test("fallback injection restores appendChild before the one deliberate throw", () => {
  const source = codeMirrorFallbackFaultInjection.toString();
  assert.match(source, /state\.count === 0/u);
  assert.match(source, /cm-announced/u);
  assert.match(source, /cm-scroller/u);
  assert.match(source, /Node\.prototype\.appendChild = nativeAppendChild/u);
  assert.match(source, /T4_GATE_CODEMIRROR_ROOT_APPEND_THROW/u);
  assert.doesNotMatch(source, /FALLBACK_STATE_KEY/u);
});

test("report hash covers the independent v1 envelope and HOLD is fail closed", () => {
  const report = finalizeSupplementReport({
    controller_id: "test",
    schema_version: SUPPLEMENT_REPORT_SCHEMA,
    supplement_run_id: request.supplement_run_id,
  });
  assert.match(report.report_sha256, /^[a-f0-9]{64}$/u);
  const changed = finalizeSupplementReport({
    controller_id: "changed",
    schema_version: SUPPLEMENT_REPORT_SCHEMA,
    supplement_run_id: request.supplement_run_id,
  });
  assert.notEqual(changed.report_sha256, report.report_sha256);
  assert.deepEqual(
    holdProjection(new SupplementalObserverError("SYSTEM_IME_OPERATOR_INPUT_REQUIRED", "restored")),
    {
      error_code: "SYSTEM_IME_OPERATOR_INPUT_REQUIRED",
      recovery_status: "restored",
      status: "hold",
    },
  );
});

test("entrypoint reads the capability only from inherited FD 3", () => {
  const source = readFileSync(
    new URL("../bin/observe-supplement.mjs", import.meta.url),
    "utf8",
  );
  assert.match(source, /readSync\(3,/u);
  assert.doesNotMatch(source, /process\.env/u);
  assert.doesNotMatch(source, /validationToken.*argv|argv.*validationToken/u);
  assert.match(source, /process\.argv\.length !== 2/u);
});

test("layout IME writes remain observable and final recovery is read from the page", () => {
  const source = readFileSync(
    new URL("../src/supplemental-observer.mjs", import.meta.url),
    "utf8",
  );
  const collection = source.slice(source.indexOf("export async function collectSupplementalObservation"));
  assert.doesNotMatch(collection, /tracker\.dispose\(\)/u);
  assert.match(collection, /state\.finalSourceDigest = await editorDigest\(page\)/u);
  assert.match(collection, /final_source_sha256: state\.finalSourceDigest/u);
  assert.doesNotMatch(
    collection,
    /final_source_sha256: request\.baseline_source_sha256/u,
  );
});

test("IME recovery walks editor history and stops at the exact baseline", async () => {
  let remainingTransactions = 24;
  let undoCount = 0;
  assert.equal(await recoverEditorHistory({
    isBaseline: async () => remainingTransactions === 0,
    pressUndo: async () => {
      undoCount += 1;
      remainingTransactions -= 1;
    },
  }), true);
  assert.equal(undoCount, 24);
});

test("IME recovery remains bounded when the baseline is unreachable", async () => {
  let undoCount = 0;
  assert.equal(await recoverEditorHistory({
    isBaseline: async () => false,
    pressUndo: async () => { undoCount += 1; },
  }), false);
  assert.equal(undoCount, 128);
});

test("an unmounted chapter editor fails with a stable recovery classification", () => {
  const source = readFileSync(
    new URL("../src/supplemental-observer.mjs", import.meta.url),
    "utf8",
  );
  assert.match(source, /SUPPLEMENT_CHAPTER_SWITCH_EDITOR_UNAVAILABLE/u);
  assert.match(
    source,
    /SUPPLEMENT_CHAPTER_SWITCH_EDITOR_UNAVAILABLE"[\s\S]{0,120}"not_required"/u,
  );
});

test("player projection treats chapter-switch unmount as an absent projection", () => {
  const source = readFileSync(
    new URL("../src/supplemental-observer.mjs", import.meta.url),
    "utf8",
  );
  const projection = source.slice(
    source.indexOf("async function playerProjection"),
    source.indexOf("async function progressApi"),
  );
  assert.match(projection, /inputValue\(\{ timeout: 1_000 \}\)/u);
  assert.match(projection, /catch \{\s*return null;\s*\}/u);
});
