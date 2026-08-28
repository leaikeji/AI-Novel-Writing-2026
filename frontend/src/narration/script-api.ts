import { ApiError, apiRequest } from "../api";
import {
  ScriptContractError,
  parseScriptApiErrorDetail,
  parseScriptReviewResource,
} from "./script-contracts";
import type {
  AnalyzeScriptRequest,
  ApproveScriptRequest,
  ReanalyzeSegmentsRequest,
  ScriptApiErrorDetail,
  ScriptReviewResource,
  SegmentReviewPatch,
} from "./script-contracts";


type ResponseParser<T> = (value: unknown) => T;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;


export interface ScriptReviewDocumentScope {
  readonly novel_id: string;
  readonly document_id: string;
  readonly revision_id: string;
  readonly source_content_hash: string;
}


export interface ScriptReviewScriptScope extends ScriptReviewDocumentScope {
  readonly script_id: string;
}


export interface ScriptReviewVersionScope extends ScriptReviewScriptScope {
  readonly script_version_id: string;
}


export class ScriptApiError extends Error {
  readonly status: number;
  readonly detail: ScriptApiErrorDetail;

  constructor(status: number, detail: ScriptApiErrorDetail) {
    super(detail.message);
    this.status = status;
    this.detail = detail;
  }
}


function pathId(value: string, field: string): string {
  if (!UUID_PATTERN.test(value)) {
    throw new ScriptContractError(field, "expected RFC-4122 UUID v1-v5");
  }
  return encodeURIComponent(value.toLowerCase());
}


function scopeHash(value: string, field: string): string {
  if (!SHA256_PATTERN.test(value)) {
    throw new ScriptContractError(field, "expected lowercase SHA-256");
  }
  return value;
}


function idempotencyHeaders(value: string): HeadersInit {
  if (!IDEMPOTENCY_KEY_PATTERN.test(value)) {
    throw new ScriptContractError("idempotency_key", "must be 8-128 safe characters");
  }
  return { "Idempotency-Key": value };
}


function jsonInit(
  method: "POST" | "PATCH",
  payload: object,
  idempotencyKey: string,
  signal?: AbortSignal,
): RequestInit {
  return {
    method,
    body: JSON.stringify(payload),
    headers: idempotencyHeaders(idempotencyKey),
    signal,
  };
}


function normalizeScriptError(reason: unknown): never {
  if (!(reason instanceof ApiError)) throw reason;
  try {
    throw new ScriptApiError(reason.status, parseScriptApiErrorDetail(reason.detail));
  } catch (error) {
    if (error instanceof ScriptApiError) throw error;
    throw reason;
  }
}


async function parsedRequest<T>(
  path: string,
  parser: ResponseParser<T>,
  init?: RequestInit,
): Promise<T> {
  try {
    return parser(await apiRequest<unknown>(path, init));
  } catch (reason) {
    normalizeScriptError(reason);
  }
}


function requireDocumentScope(
  resource: ScriptReviewResource,
  expected: ScriptReviewDocumentScope,
): ScriptReviewResource {
  const fields = {
    novel_id: pathId(expected.novel_id, "expected_scope.novel_id"),
    document_id: pathId(expected.document_id, "expected_scope.document_id"),
    revision_id: pathId(expected.revision_id, "expected_scope.revision_id"),
    source_content_hash: scopeHash(
      expected.source_content_hash,
      "expected_scope.source_content_hash",
    ),
  } as const;
  for (const [field, expectedValue] of Object.entries(fields)) {
    if (resource[field as keyof typeof fields] !== expectedValue) {
      throw new ScriptContractError(field, "response scope mismatch");
    }
  }
  return resource;
}


function requireScriptScope(
  resource: ScriptReviewResource,
  expected: ScriptReviewScriptScope,
): ScriptReviewResource {
  requireDocumentScope(resource, expected);
  if (resource.script_id !== pathId(expected.script_id, "expected_scope.script_id")) {
    throw new ScriptContractError("script_id", "response scope mismatch");
  }
  return resource;
}


function requireVersionScope(
  resource: ScriptReviewResource,
  expected: ScriptReviewVersionScope,
): ScriptReviewResource {
  requireScriptScope(resource, expected);
  if (
    resource.script_version_id
    !== pathId(expected.script_version_id, "expected_scope.script_version_id")
  ) {
    throw new ScriptContractError("script_version_id", "response scope mismatch");
  }
  return resource;
}


function requireSameRequestScope(
  actual: string,
  expected: string,
  field: string,
  validator: (value: string, field: string) => string,
): void {
  if (validator(actual, field) !== validator(expected, `expected_scope.${field}`)) {
    throw new ScriptContractError(field, "request and expected scope mismatch");
  }
}


export async function analyzeNarrationScript(
  documentId: string,
  payload: AnalyzeScriptRequest,
  expectedScope: ScriptReviewDocumentScope,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  requireSameRequestScope(documentId, expectedScope.document_id, "document_id", pathId);
  requireSameRequestScope(
    payload.source_revision_id,
    expectedScope.revision_id,
    "revision_id",
    pathId,
  );
  requireSameRequestScope(
    payload.source_content_hash,
    expectedScope.source_content_hash,
    "source_content_hash",
    scopeHash,
  );
  const resource = await parsedRequest(
    `/documents/${pathId(documentId, "document_id")}/narration-scripts/analyze`,
    parseScriptReviewResource,
    jsonInit("POST", payload, idempotencyKey, signal),
  );
  return requireDocumentScope(resource, expectedScope);
}


export async function getNarrationScript(
  scriptId: string,
  expectedScope: ScriptReviewScriptScope,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  requireSameRequestScope(scriptId, expectedScope.script_id, "script_id", pathId);
  const resource = await parsedRequest(
    `/narration-scripts/${pathId(scriptId, "script_id")}`,
    parseScriptReviewResource,
    { signal },
  );
  return requireScriptScope(resource, expectedScope);
}


export async function getNarrationScriptVersion(
  versionId: string,
  expectedScope: ScriptReviewVersionScope,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  requireSameRequestScope(
    versionId,
    expectedScope.script_version_id,
    "script_version_id",
    pathId,
  );
  const resource = await parsedRequest(
    `/narration-script-versions/${pathId(versionId, "script_version_id")}`,
    parseScriptReviewResource,
    { signal },
  );
  return requireVersionScope(resource, expectedScope);
}


export async function getNarrationScriptVersionForEdition(
  versionId: string,
  expectedScope: ScriptReviewDocumentScope,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  const normalizedVersion = pathId(versionId, "script_version_id");
  const resource = await parsedRequest(
    `/narration-script-versions/${normalizedVersion}`,
    parseScriptReviewResource,
    { signal },
  );
  requireDocumentScope(resource, expectedScope);
  if (resource.script_version_id !== normalizedVersion) {
    throw new ScriptContractError("script_version_id", "response scope mismatch");
  }
  return resource;
}


export async function patchNarrationScriptSegment(
  versionId: string,
  segmentId: string,
  payload: SegmentReviewPatch,
  expectedScope: ScriptReviewVersionScope,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  const normalizedVersion = pathId(versionId, "script_version_id");
  requireSameRequestScope(
    versionId,
    expectedScope.script_version_id,
    "script_version_id",
    pathId,
  );
  const resource = await parsedRequest(
    `/narration-script-versions/${pathId(versionId, "script_version_id")}/segments/${pathId(segmentId, "segment_id")}`,
    parseScriptReviewResource,
    jsonInit("PATCH", payload, idempotencyKey, signal),
  );
  requireScriptScope(resource, expectedScope);
  if (
    resource.script_version_id === normalizedVersion
    || resource.version_number <= payload.expected_version_number
  ) {
    throw new ScriptContractError("script_version_id", "response is not a new child version");
  }
  return resource;
}


export async function approveNarrationScriptVersion(
  versionId: string,
  payload: ApproveScriptRequest,
  expectedScope: ScriptReviewVersionScope,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  requireSameRequestScope(
    versionId,
    expectedScope.script_version_id,
    "script_version_id",
    pathId,
  );
  requireSameRequestScope(
    payload.source_revision_id,
    expectedScope.revision_id,
    "revision_id",
    pathId,
  );
  const resource = await parsedRequest(
    `/narration-script-versions/${pathId(versionId, "script_version_id")}/approve`,
    parseScriptReviewResource,
    jsonInit("POST", payload, idempotencyKey, signal),
  );
  requireVersionScope(resource, expectedScope);
  if (
    resource.version_number !== payload.expected_version_number
    || resource.immutable_hash !== payload.expected_immutable_hash
    || resource.state !== "approved"
    || resource.approval?.request_id !== payload.request_id.toLowerCase()
  ) {
    throw new ScriptContractError("approval", "response does not match approval guards");
  }
  return resource;
}


export async function reanalyzeNarrationScriptSegments(
  versionId: string,
  payload: ReanalyzeSegmentsRequest,
  expectedScope: ScriptReviewVersionScope,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<ScriptReviewResource> {
  const normalizedVersion = pathId(versionId, "script_version_id");
  requireSameRequestScope(
    versionId,
    expectedScope.script_version_id,
    "script_version_id",
    pathId,
  );
  const resource = await parsedRequest(
    `/narration-script-versions/${pathId(versionId, "script_version_id")}/reanalyze-segments`,
    parseScriptReviewResource,
    jsonInit("POST", payload, idempotencyKey, signal),
  );
  requireScriptScope(resource, expectedScope);
  if (
    resource.script_version_id === normalizedVersion
    || resource.version_number <= payload.expected_version_number
  ) {
    throw new ScriptContractError("script_version_id", "response is not a new child version");
  }
  return resource;
}
