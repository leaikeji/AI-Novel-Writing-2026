import {
  FIXED_CAPTURES,
  FIXED_ORIGIN,
  ObserverError,
  canonicalJson,
  sha256Bytes,
} from "./contracts.mjs";


export const SUPPLEMENT_REQUEST_SCHEMA =
  "moss-tts-t4-gate-browser-supplement-request/1.0";
export const SUPPLEMENT_REPORT_SCHEMA =
  "moss-tts-t4-gate-browser-supplement-report/1.0";
export const SUPPLEMENT_CONTROLLER_ID =
  "ai-novel-world-2026-host-browser-supplement/1.0";
export const SYSTEM_IME_CHECKPOINT_ID = "macos-system-chinese-ime/1";
export const TEXTAREA_FAULT_INJECTION_ID = "codemirror-root-append-throw/1";
export const SYSTEM_IME_OPERATOR_TIMEOUT_MS = 120_000;

export const SUPPLEMENT_SELECTORS = Object.freeze({
  assistant_root: ".anw-assistant-pane",
  assistant_toggle: ".anw-assistant-pane-toggle",
  chapter_button: ".anw-chapter-tree-chapter[data-document-id]",
  code_mirror_content:
    ".anw-chapter-editor-surface .cm-content[contenteditable=\"true\"]",
  code_mirror_root: ".anw-chapter-editor-surface .cm-editor",
  context_menu: ".anw-narration-paragraph-context-menu[role=\"menu\"]",
  context_menu_command:
    ".anw-narration-paragraph-context-menu[role=\"menu\"] button[role=\"menuitem\"]",
  editor_root: ".anw-chapter-editor-surface",
  live_region:
    ".anw-chapter-narration-player [role=\"status\"][aria-live=\"polite\"]",
  player:
    ".anw-chapter-narration-player[aria-label=\"章节智能朗读播放器\"]",
  rate: ".anw-chapter-narration-player select[aria-label=\"朗读倍速\"]",
  review_dialog: ".anw-script-review[role=\"dialog\"]",
  review_open: ".anw-chapter-narration-player button:text-is(\"复核脚本\")",
  textarea:
    ".anw-chapter-editor-surface textarea.anw-chapter-editor-textarea-fallback",
  timeline:
    ".anw-chapter-narration-player input[type=\"range\"][aria-label=\"按句段跳转章节朗读位置\"]",
  update_button:
    ".anw-chapter-narration-player button:text-is(\"更新朗读\")",
});

export const SUPPLEMENT_CAPTURES = FIXED_CAPTURES;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const REQUEST_KEYS = Object.freeze([
  "baseline_source_sha256",
  "fixture_manifest_sha256",
  "novel_id",
  "primary_document_id",
  "request_fingerprint_sha256",
  "schema_version",
  "secondary_document_id",
  "supplement_run_id",
  "target_scope_sha256",
]);

export class SupplementalObserverError extends ObserverError {
  constructor(code, recoveryStatus = "not_required") {
    super(code);
    this.name = "SupplementalObserverError";
    this.recoveryStatus = recoveryStatus;
  }
}

export function parseCanonicalSupplementRequest(raw) {
  if (!Buffer.isBuffer(raw) || raw.length < 2 || raw.length > 16 * 1024 || raw.at(-1) !== 0x0a) {
    throw new SupplementalObserverError("SUPPLEMENT_REQUEST_INVALID");
  }
  let value;
  try {
    value = JSON.parse(raw.toString("utf8"));
  } catch {
    throw new SupplementalObserverError("SUPPLEMENT_REQUEST_INVALID");
  }
  if (
    value === null
    || Array.isArray(value)
    || typeof value !== "object"
    || Object.keys(value).sort().join("\0") !== REQUEST_KEYS.join("\0")
    || `${canonicalJson(value)}\n` !== raw.toString("utf8")
    || value.schema_version !== SUPPLEMENT_REQUEST_SCHEMA
    || !UUID.test(value.supplement_run_id)
    || !UUID.test(value.novel_id)
    || !UUID.test(value.primary_document_id)
    || !UUID.test(value.secondary_document_id)
    || value.primary_document_id === value.secondary_document_id
    || !SHA256.test(value.baseline_source_sha256)
    || !SHA256.test(value.fixture_manifest_sha256)
    || !SHA256.test(value.request_fingerprint_sha256)
    || !SHA256.test(value.target_scope_sha256)
  ) throw new SupplementalObserverError("SUPPLEMENT_REQUEST_INVALID");
  return Object.freeze({ ...value });
}

export function baseRunFingerprint(request) {
  return sha256Bytes(Buffer.from(canonicalJson({
    fixture_manifest_sha256: request.fixture_manifest_sha256,
    supplement_run_id: request.supplement_run_id,
  }), "utf8"));
}

export function baseObserverRequest(request) {
  return Object.freeze({
    document_id: request.primary_document_id,
    novel_id: request.novel_id,
    request_fingerprint_sha256: request.request_fingerprint_sha256,
    run_fingerprint_sha256: baseRunFingerprint(request),
    target_scope_sha256: request.target_scope_sha256,
  });
}

export function supplementalWorkbenchUrl(request, documentId = request.primary_document_id) {
  if (!UUID.test(documentId)) {
    throw new SupplementalObserverError("SUPPLEMENT_ROUTE_INVALID");
  }
  const query = new URLSearchParams({
    novel_workbench: "1",
    novel_id: request.novel_id,
    document_id: documentId,
  });
  return `${FIXED_ORIGIN}/chat?${query.toString()}`;
}

export function chapterSelector(documentId) {
  if (!UUID.test(documentId)) {
    throw new SupplementalObserverError("SUPPLEMENT_ROUTE_INVALID");
  }
  return `.anw-chapter-tree-chapter[data-document-id="${documentId}"]`;
}

export function summarizeImeCheckpoint(value) {
  const counts = value?.trusted_counts;
  const valid = (
    value !== null
    && typeof value === "object"
    && counts !== null
    && typeof counts === "object"
    && Number.isSafeInteger(counts.compositionstart)
    && counts.compositionstart >= 1
    && Number.isSafeInteger(counts.compositionupdate)
    && counts.compositionupdate >= 1
    && Number.isSafeInteger(counts.compositionend)
    && counts.compositionend >= 1
    && Number.isSafeInteger(value.untrusted_event_count)
    && value.untrusted_event_count === 0
    && Number.isSafeInteger(value.han_character_count_delta)
    && value.han_character_count_delta >= 2
    && value.focus_preserved_during_composition === true
    && value.selection_preserved_or_expected === true
    && Number.isSafeInteger(value.playback_seek_during_composition_count)
    && value.playback_seek_during_composition_count === 0
  );
  if (!valid) {
    throw new SupplementalObserverError("SYSTEM_IME_OPERATOR_INPUT_REQUIRED", "restored");
  }
  return Object.freeze({
    focus_preserved_during_composition: true,
    han_character_count_delta: value.han_character_count_delta,
    input_source_class: "system_chinese",
    operator_confirmed: true,
    playback_seek_during_composition_count: 0,
    selection_preserved_or_expected: true,
    trusted_counts: Object.freeze({
      compositionend: counts.compositionend,
      compositionstart: counts.compositionstart,
      compositionupdate: counts.compositionupdate,
    }),
    untrusted_event_count: 0,
  });
}

export function classifySupplementRequest(method, rawUrl, postData = null) {
  const normalizedMethod = String(method).toUpperCase();
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return Object.freeze({ kind: "other", scope_sha256: sha256Bytes(Buffer.from("invalid", "utf8")) });
  }
  const scope = `${normalizedMethod} ${url.pathname}?${[...url.searchParams.entries()].sort().map(
    ([key, value]) => `${key}=${value}`,
  ).join("&")}`;
  let kind = "other";
  if (normalizedMethod === "PUT" && /\/narration-editions\/[0-9a-f-]{36}\/playback-progress$/iu.test(url.pathname)) {
    kind = "progress_write";
  } else if (
    ["GET", "HEAD"].includes(normalizedMethod)
    && /\/media-assets\/[0-9a-f-]{36}\/content$/iu.test(url.pathname)
  ) {
    kind = "media_read";
  } else if (
    normalizedMethod === "PATCH"
    && /\/documents\/[0-9a-f-]{36}\/draft$/iu.test(url.pathname)
  ) {
    kind = "draft_write";
  } else if (
    !["GET", "HEAD", "OPTIONS"].includes(normalizedMethod)
    && /(?:narration-requests|voice)/u.test(url.pathname)
  ) {
    kind = "tts_creation_write";
  }
  let intent = null;
  if (kind === "tts_creation_write" && typeof postData === "string" && postData.length <= 64 * 1024) {
    try {
      const body = JSON.parse(postData);
      if (body?.intent === "create" || body?.intent === "update") intent = body.intent;
    } catch {
      // A malformed body remains a write, never a trusted intent.
    }
  }
  return Object.freeze({
    intent,
    kind,
    resource_id_sha256: (() => {
      const match = url.pathname.match(/\/(?:narration-editions|documents)\/([0-9a-f-]{36})(?:\/|$)/iu);
      return match ? sha256Bytes(Buffer.from(match[1].toLowerCase(), "utf8")) : null;
    })(),
    scope_sha256: sha256Bytes(Buffer.from(scope, "utf8")),
  });
}

export function finalizeSupplementReport(report) {
  const unsigned = Object.freeze({ ...report });
  return Object.freeze({
    ...unsigned,
    report_sha256: sha256Bytes(Buffer.from(canonicalJson(unsigned), "utf8")),
  });
}
