import assert from "node:assert/strict";
import { userInfo } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  EDGE_PATH,
  FIXED_CAPTURES,
  FIXED_ORIGIN,
  ObserverError,
  REQUEST_SCHEMA,
  REPORT_SCHEMA,
  boundedDigestSummary,
  canonicalJson,
  finalRouteEvidence,
  fixedWorkbenchUrl,
  parseCanonicalRequest,
  parseValidationTokenLine,
  pngDimensions,
  loopbackValidationHeaders,
} from "../src/contracts.mjs";
import { loadFixedChromium } from "../src/runtime-identity.mjs";


const request = Object.freeze({
  document_id: "22222222-2222-4222-8222-222222222222",
  novel_id: "11111111-1111-4111-8111-111111111111",
  request_fingerprint_sha256: "a".repeat(64),
  run_fingerprint_sha256: "b".repeat(64),
  schema_version: REQUEST_SCHEMA,
  target_scope_sha256: "c".repeat(64),
});

test("final route permits only the fixed root or one canonical session path", () => {
  assert.equal(finalRouteEvidence(fixedWorkbenchUrl(request), request).route_kind, "chat_root");
  const session = new URL(fixedWorkbenchUrl(request));
  session.pathname = "/chat/session_123";
  assert.equal(finalRouteEvidence(session.href, request).route_kind, "chat_session");
  session.searchParams.set("extra", "forbidden");
  assert.throws(() => finalRouteEvidence(session.href, request), ObserverError);
  const wrongDocument = new URL(fixedWorkbenchUrl(request));
  wrongDocument.searchParams.set("document_id", "33333333-3333-4333-8333-333333333333");
  assert.throws(() => finalRouteEvidence(wrongDocument.href, request), ObserverError);
});

test("accepts only one byte-canonical fixed request", () => {
  const raw = Buffer.from(`${canonicalJson(request)}\n`, "utf8");
  assert.deepEqual(parseCanonicalRequest(raw), request);
  assert.throws(
    () => parseCanonicalRequest(Buffer.from(`${JSON.stringify(request, null, 2)}\n`)),
    (error) => error instanceof ObserverError && error.code === "OBSERVER_REQUEST_INVALID",
  );
  assert.throws(
    () => parseCanonicalRequest(Buffer.from(`${canonicalJson({ ...request, url: "https://example.com" })}\n`)),
    (error) => error instanceof ObserverError && error.code === "OBSERVER_REQUEST_INVALID",
  );
  assert.throws(
    () => parseCanonicalRequest(Buffer.from(`${canonicalJson({ ...request, validation_token: "A".repeat(43) })}\n`)),
    (error) => error instanceof ObserverError && error.code === "OBSERVER_REQUEST_INVALID",
  );
});

test("route, browser, selectors and four captures are not caller selectable", () => {
  const url = fixedWorkbenchUrl(request);
  assert.equal(new URL(url).origin, FIXED_ORIGIN);
  assert.equal(new URL(url).pathname, "/chat");
  assert.equal(new URL(url).searchParams.get("novel_id"), request.novel_id);
  assert.equal(new URL(url).searchParams.get("document_id"), request.document_id);
  assert.equal(EDGE_PATH, "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge");
  assert.deepEqual(FIXED_CAPTURES, [
    { width: 1920, height: 1080, assistantMode: "collapsed" },
    { width: 1920, height: 1080, assistantMode: "expanded" },
    { width: 2560, height: 1440, assistantMode: "collapsed" },
    { width: 2560, height: 1440, assistantMode: "expanded" },
  ]);
});

test("PNG dimensions come from a real IHDR shape", () => {
  const png = Buffer.alloc(33);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
  png.writeUInt32BE(13, 8);
  png.write("IHDR", 12, "ascii");
  png.writeUInt32BE(1920, 16);
  png.writeUInt32BE(1080, 20);
  assert.deepEqual(pngDimensions(png), { width: 1920, height: 1080 });
  assert.throws(() => pngDimensions(Buffer.from("not png")), ObserverError);
});

test("console and page errors retain no raw message or location", () => {
  const summary = boundedDigestSummary([
    { kind: "error", location: "http://127.0.0.1/private?id=secret", message: "secret body" },
  ]);
  const serialized = canonicalJson(summary);
  assert.equal(summary.count, 1);
  assert.equal(summary.rows[0].message_sha256.length, 64);
  assert.equal(summary.rows[0].location_sha256.length, 64);
  assert.doesNotMatch(serialized, /secret|private/u);
});

test("only the fixed Node and receipt-bound dependency tree become observer authority", () => {
  const expectedNode = path.join(
    userInfo().homedir,
    "Library",
    "Application Support",
    "AI小说世界2026",
    "controller-runtime",
    "node-v24.19.0-darwin-arm64",
    "bin",
    "node",
  );
  if (process.execPath === expectedNode) {
    assert.ok(loadFixedChromium());
    return;
  }
  assert.throws(() => loadFixedChromium(), (error) => (
    error instanceof ObserverError
    && error.code === "OBSERVER_RUNTIME_IDENTITY_INVALID"
  ));
});

test("report schema is 1.2 and validation capability accepts only one fixed line", () => {
  assert.equal(REPORT_SCHEMA, "moss-tts-t4k-browser-observer-report/1.2");
  const token = "A".repeat(43);
  assert.equal(parseValidationTokenLine(Buffer.from(`${token}\n`, "ascii")), token);
  for (const invalid of [
    Buffer.from(token, "ascii"),
    Buffer.from(`${"A".repeat(42)}\n`, "ascii"),
    Buffer.from(`${"A".repeat(129)}\n`, "ascii"),
    Buffer.from(`${"A".repeat(42)}!\n`, "ascii"),
    Buffer.from(`${token}\nextra\n`, "ascii"),
    Buffer.concat([Buffer.from("A".repeat(42), "ascii"), Buffer.from([0xc1, 0x0a])]),
  ]) assert.throws(() => parseValidationTokenLine(invalid), ObserverError);
});

test("loopback projection strips duplicate case variants and retains no token metadata", () => {
  const token = "v".repeat(43);
  const projected = loopbackValidationHeaders({
    Accept: "application/json",
    "x-ai-novel-tts-validation": "caller-controlled",
    "X-AI-NOVEL-TTS-VALIDATION": "duplicate",
  }, token);
  const validationNames = Object.keys(projected).filter(
    (name) => name.toLowerCase() === "x-ai-novel-tts-validation",
  );
  assert.deepEqual(validationNames, ["X-AI-Novel-TTS-Validation"]);
  assert.equal(projected["X-AI-Novel-TTS-Validation"], token);
  assert.equal(projected.Accept, "application/json");
});
