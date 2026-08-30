import { createNarrationIdempotencyKey } from "./idempotency-key";


export type OfficialVoiceUsePhase =
  | "idle"
  | "applying"
  | "applied"
  | "conflict"
  | "error";


export type OfficialVoiceUseFailureKind = "conflict" | "error";


export interface OfficialVoiceUseFailure {
  readonly kind: OfficialVoiceUseFailureKind;
  readonly code: string | null;
  readonly message: string;
  readonly retryable: boolean;
}


interface OfficialVoiceUseStateBase {
  readonly phase: OfficialVoiceUsePhase;
  readonly requestId: number;
  readonly message: string;
}


export interface IdleOfficialVoiceUseState extends OfficialVoiceUseStateBase {
  readonly phase: "idle";
  readonly presetId: null;
  readonly idempotencyKey: null;
  readonly failure: null;
}


export interface ApplyingOfficialVoiceUseState extends OfficialVoiceUseStateBase {
  readonly phase: "applying";
  readonly presetId: string;
  readonly idempotencyKey: string;
  readonly failure: null;
}


export interface AppliedOfficialVoiceUseState extends OfficialVoiceUseStateBase {
  readonly phase: "applied";
  readonly presetId: string;
  readonly idempotencyKey: string;
  readonly failure: null;
}


export interface FailedOfficialVoiceUseState extends OfficialVoiceUseStateBase {
  readonly phase: "conflict" | "error";
  readonly presetId: string;
  readonly idempotencyKey: string;
  readonly failure: OfficialVoiceUseFailure;
}


export type OfficialVoiceUseState =
  | IdleOfficialVoiceUseState
  | ApplyingOfficialVoiceUseState
  | AppliedOfficialVoiceUseState
  | FailedOfficialVoiceUseState;


export type OfficialVoiceUseAction =
  | {
    readonly type: "start";
    readonly presetId: string;
    readonly requestId: number;
    readonly idempotencyKey: string;
    readonly message: string;
  }
  | {
    readonly type: "succeed";
    readonly presetId: string;
    readonly requestId: number;
    readonly message: string;
  }
  | {
    readonly type: "fail";
    readonly presetId: string;
    readonly requestId: number;
    readonly failure: OfficialVoiceUseFailure;
  }
  | {
    readonly type: "reset";
    readonly requestId: number;
    readonly message?: string;
  };


const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/u;
const CONFLICT_CODES = new Set([
  "IDEMPOTENCY_CONFLICT",
  "STALE_INPUT",
  "VERSION_CONFLICT",
  "VOICE_BINDING_VERSION_CONFLICT",
]);


export const IDLE_OFFICIAL_VOICE_USE_STATE: IdleOfficialVoiceUseState = Object.freeze({
  phase: "idle",
  presetId: null,
  requestId: 0,
  idempotencyKey: null,
  message: "选择一个官方音色即可直接使用，试听不是前置步骤。",
  failure: null,
});


export class OfficialVoiceUseResponseError extends Error {}


export class OfficialVoiceUseConflictError extends Error {
  readonly status = 409;
  readonly code: string;

  constructor(code = "SELECTION_NOT_CURRENT") {
    super("official voice selection is no longer current");
    this.code = code;
  }
}


function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return value !== null && typeof value === "object";
}


function errorCode(reason: unknown): string | null {
  if (!isRecord(reason)) return null;
  const direct = reason.code;
  if (typeof direct === "string" && direct.trim()) return direct;
  const detail = reason.detail;
  if (!isRecord(detail)) return null;
  return typeof detail.code === "string" && detail.code.trim() ? detail.code : null;
}


function errorStatus(reason: unknown): number | null {
  if (!isRecord(reason)) return null;
  return typeof reason.status === "number" && Number.isInteger(reason.status)
    ? reason.status
    : null;
}


function declaredRetryable(reason: unknown): boolean | null {
  if (!isRecord(reason)) return null;
  if (typeof reason.retryable === "boolean") return reason.retryable;
  const detail = reason.detail;
  if (!isRecord(detail)) return null;
  return typeof detail.retryable === "boolean" ? detail.retryable : null;
}


function isAbortLike(reason: unknown): boolean {
  return isRecord(reason) && reason.name === "AbortError";
}


export function classifyOfficialVoiceUseFailure(
  reason: unknown,
): OfficialVoiceUseFailure {
  const code = errorCode(reason);
  const status = errorStatus(reason);
  if (status === 409 || (code !== null && CONFLICT_CODES.has(code))) {
    return Object.freeze({
      kind: "conflict",
      code,
      message: "音色设置已在其他位置更新。请刷新当前设置后重试，现有声音没有被覆盖。",
      retryable: false,
    });
  }
  if (isAbortLike(reason)) {
    return Object.freeze({
      kind: "error",
      code,
      message: "本次使用已取消，现有声音没有改变。",
      retryable: false,
    });
  }
  if (reason instanceof OfficialVoiceUseResponseError) {
    return Object.freeze({
      kind: "error",
      code: "RESPONSE_CONTRACT_VIOLATION",
      message: "服务端返回的音色结果与本次选择不一致，已停止更新。",
      retryable: false,
    });
  }
  const retryable = declaredRetryable(reason) ?? (
    status === null || status >= 500 || reason instanceof TypeError
  );
  return Object.freeze({
    kind: "error",
    code,
    message: retryable
      ? "使用音色的响应未完成，现有声音保持不变。可直接重试。"
      : "暂时无法使用这个音色，现有声音保持不变。请刷新后再试。",
    retryable,
  });
}


export function canStartOfficialVoiceUse(state: OfficialVoiceUseState): boolean {
  return state.phase !== "applying" && state.phase !== "conflict";
}


function ownsCompletion(
  state: OfficialVoiceUseState,
  action: Extract<OfficialVoiceUseAction, { readonly type: "succeed" | "fail" }>,
): state is ApplyingOfficialVoiceUseState {
  return state.phase === "applying"
    && state.requestId === action.requestId
    && state.presetId === action.presetId;
}


export function reduceOfficialVoiceUseState(
  state: OfficialVoiceUseState,
  action: OfficialVoiceUseAction,
): OfficialVoiceUseState {
  if (action.type === "reset") {
    return Object.freeze({
      ...IDLE_OFFICIAL_VOICE_USE_STATE,
      requestId: action.requestId,
      message: action.message ?? IDLE_OFFICIAL_VOICE_USE_STATE.message,
    });
  }
  if (action.type === "start") {
    if (
      !canStartOfficialVoiceUse(state)
      || !action.presetId.trim()
      || !Number.isSafeInteger(action.requestId)
      || action.requestId <= state.requestId
      || !IDEMPOTENCY_KEY_PATTERN.test(action.idempotencyKey)
    ) return state;
    return Object.freeze({
      phase: "applying",
      presetId: action.presetId,
      requestId: action.requestId,
      idempotencyKey: action.idempotencyKey,
      message: action.message,
      failure: null,
    });
  }
  if (!ownsCompletion(state, action)) return state;
  if (action.type === "succeed") {
    return Object.freeze({
      phase: "applied",
      presetId: state.presetId,
      requestId: state.requestId,
      idempotencyKey: state.idempotencyKey,
      message: action.message,
      failure: null,
    });
  }
  return Object.freeze({
    phase: action.failure.kind,
    presetId: state.presetId,
    requestId: state.requestId,
    idempotencyKey: state.idempotencyKey,
    message: action.failure.message,
    failure: action.failure,
  });
}


export function nextOfficialVoiceUseIdempotencyKey(
  state: OfficialVoiceUseState,
  presetId: string,
  createKey: () => string = createOfficialVoiceUseIdempotencyKey,
): string {
  if (
    state.phase === "error"
    && state.presetId === presetId
    && state.failure.retryable
  ) return state.idempotencyKey;
  const created = createKey();
  if (!IDEMPOTENCY_KEY_PATTERN.test(created)) {
    throw new Error("official voice idempotency key must contain 8-128 safe characters");
  }
  return created;
}


export function createOfficialVoiceUseIdempotencyKey(): string {
  return createNarrationIdempotencyKey("official-voice-selection");
}
