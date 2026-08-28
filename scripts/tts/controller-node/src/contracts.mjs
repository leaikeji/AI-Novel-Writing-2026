import { createHash } from "node:crypto";


export const REQUEST_SCHEMA = "moss-tts-t4k-browser-observer-request/1.0";
export const REPORT_SCHEMA = "moss-tts-t4k-browser-observer-report/1.2";
export const CONTROLLER_ID = "ai-novel-world-2026-fixed-browser-controller/1.0";
export const EDGE_PATH = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge";
export const FIXED_ORIGIN = "http://127.0.0.1:18088";
export const FIXED_CAPTURES = Object.freeze([
  Object.freeze({ width: 1920, height: 1080, assistantMode: "collapsed" }),
  Object.freeze({ width: 1920, height: 1080, assistantMode: "expanded" }),
  Object.freeze({ width: 2560, height: 1440, assistantMode: "collapsed" }),
  Object.freeze({ width: 2560, height: 1440, assistantMode: "expanded" }),
]);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const VALIDATION_TOKEN = /^[A-Za-z0-9_-]{43,128}$/u;
const REQUEST_KEYS = Object.freeze([
  "document_id",
  "novel_id",
  "request_fingerprint_sha256",
  "run_fingerprint_sha256",
  "schema_version",
  "target_scope_sha256",
]);

export class ObserverError extends Error {
  constructor(code) {
    super(code);
    this.name = "ObserverError";
    this.code = code;
  }
}

export function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}

export function sha256Bytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

export function parseCanonicalRequest(raw) {
  if (!Buffer.isBuffer(raw) || raw.length < 2 || raw.length > 16 * 1024 || raw.at(-1) !== 0x0a) {
    throw new ObserverError("OBSERVER_REQUEST_INVALID");
  }
  let value;
  try {
    value = JSON.parse(raw.toString("utf8"));
  } catch {
    throw new ObserverError("OBSERVER_REQUEST_INVALID");
  }
  if (
    value === null
    || Array.isArray(value)
    || typeof value !== "object"
    || Object.keys(value).sort().join("\0") !== REQUEST_KEYS.join("\0")
    || `${canonicalJson(value)}\n` !== raw.toString("utf8")
    || value.schema_version !== REQUEST_SCHEMA
    || !UUID.test(value.novel_id)
    || !UUID.test(value.document_id)
    || !SHA256.test(value.request_fingerprint_sha256)
    || !SHA256.test(value.run_fingerprint_sha256)
    || !SHA256.test(value.target_scope_sha256)
  ) {
    throw new ObserverError("OBSERVER_REQUEST_INVALID");
  }
  return Object.freeze({ ...value });
}

/**
 * Parse the validation capability from the controller's fixed inherited FD 3.
 * The executable entrypoint is solely responsible for reading that descriptor;
 * the token is deliberately absent from argv, env, URLs, request JSON and reports.
 */
export function parseValidationTokenLine(raw) {
  if (!Buffer.isBuffer(raw) || raw.length < 44 || raw.length > 129 || raw.at(-1) !== 0x0a) {
    throw new ObserverError("OBSERVER_VALIDATION_CAPABILITY_INVALID");
  }
  const body = raw.subarray(0, -1);
  const asciiAllowed = [...body].every((byte) => (
    (byte >= 0x41 && byte <= 0x5a)
    || (byte >= 0x61 && byte <= 0x7a)
    || (byte >= 0x30 && byte <= 0x39)
    || byte === 0x5f
    || byte === 0x2d
  ));
  const token = body.toString("ascii");
  if (!asciiAllowed || !VALIDATION_TOKEN.test(token)) {
    throw new ObserverError("OBSERVER_VALIDATION_CAPABILITY_INVALID");
  }
  return token;
}

/** Return exactly one validation header while retaining unrelated request headers. */
export function loopbackValidationHeaders(headers, validationToken) {
  if (!VALIDATION_TOKEN.test(validationToken)) {
    throw new ObserverError("OBSERVER_VALIDATION_CAPABILITY_INVALID");
  }
  const projected = {};
  for (const [name, value] of Object.entries(headers ?? {})) {
    if (name.toLowerCase() === "x-ai-novel-tts-validation") continue;
    projected[name] = value;
  }
  projected["X-AI-Novel-TTS-Validation"] = validationToken;
  return projected;
}

export function fixedWorkbenchUrl(request) {
  const query = new URLSearchParams({
    novel_workbench: "1",
    novel_id: request.novel_id,
    document_id: request.document_id,
  });
  return `${FIXED_ORIGIN}/chat?${query.toString()}`;
}

export function finalRouteEvidence(rawUrl, request) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new ObserverError("OBSERVER_ROUTE_ESCAPED");
  }
  const queryKeys = [...url.searchParams.keys()].sort();
  const rootRoute = url.pathname === "/chat";
  const sessionRoute = /^\/chat\/[0-9A-Za-z_-]{1,128}$/u.test(url.pathname);
  if (
    url.origin !== FIXED_ORIGIN
    || url.username !== ""
    || url.password !== ""
    || url.hash !== ""
    || (!rootRoute && !sessionRoute)
    || queryKeys.join("\0") !== "document_id\0novel_id\0novel_workbench"
    || url.searchParams.get("novel_workbench") !== "1"
    || url.searchParams.get("novel_id") !== request.novel_id
    || url.searchParams.get("document_id") !== request.document_id
  ) throw new ObserverError("OBSERVER_ROUTE_ESCAPED");
  return Object.freeze({
    origin: FIXED_ORIGIN,
    path_fingerprint_sha256: sha256Bytes(Buffer.from(url.pathname, "utf8")),
    query_fingerprint_sha256: sha256Bytes(Buffer.from(canonicalJson({
      document_id: request.document_id,
      novel_id: request.novel_id,
      novel_workbench: "1",
    }), "utf8")),
    route_kind: rootRoute ? "chat_root" : "chat_session",
  });
}

export function pngDimensions(png) {
  if (
    !Buffer.isBuffer(png)
    || png.length < 33
    || !png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    || png.readUInt32BE(8) !== 13
    || png.subarray(12, 16).toString("ascii") !== "IHDR"
  ) throw new ObserverError("OBSERVER_SCREENSHOT_INVALID");
  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  if (width < 1 || height < 1) throw new ObserverError("OBSERVER_SCREENSHOT_INVALID");
  return Object.freeze({ width, height });
}

export function boundedDigestSummary(rows, maximum = 512) {
  if (!Array.isArray(rows)) throw new ObserverError("OBSERVER_SUMMARY_INVALID");
  const accepted = rows.slice(0, maximum).map((row) => ({
    kind: String(row.kind ?? "unknown").slice(0, 32),
    location_sha256: sha256Bytes(Buffer.from(String(row.location ?? ""), "utf8")),
    message_sha256: sha256Bytes(Buffer.from(String(row.message ?? ""), "utf8")),
  }));
  return Object.freeze({
    count: rows.length,
    dropped_count: Math.max(0, rows.length - accepted.length),
    rows: Object.freeze(accepted.map(Object.freeze)),
    summary_sha256: sha256Bytes(Buffer.from(canonicalJson(accepted), "utf8")),
  });
}
