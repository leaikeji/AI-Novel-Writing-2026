import { describe, expect, it, vi } from "vitest";

import {
  IDLE_OFFICIAL_VOICE_USE_STATE,
  OfficialVoiceUseConflictError,
  OfficialVoiceUseResponseError,
  canStartOfficialVoiceUse,
  classifyOfficialVoiceUseFailure,
  createOfficialVoiceUseIdempotencyKey,
  nextOfficialVoiceUseIdempotencyKey,
  reduceOfficialVoiceUseState,
} from "./official-voice-use-state";


const PRESET_A = "onnx.Junhao";
const PRESET_B = "onnx.Ava";
const KEY_A = "official-voice-selection-key-a";
const KEY_B = "official-voice-selection-key-b";


function applying() {
  return reduceOfficialVoiceUseState(IDLE_OFFICIAL_VOICE_USE_STATE, {
    type: "start",
    presetId: PRESET_A,
    requestId: 1,
    idempotencyKey: KEY_A,
    message: "正在使用音色…",
  });
}


describe("official voice use state", () => {
  it("implements the frozen idle -> applying -> applied path", () => {
    const pending = applying();
    expect(pending).toMatchObject({
      phase: "applying",
      presetId: PRESET_A,
      requestId: 1,
      idempotencyKey: KEY_A,
      failure: null,
    });
    expect(canStartOfficialVoiceUse(pending)).toBe(false);

    const applied = reduceOfficialVoiceUseState(pending, {
      type: "succeed",
      presetId: PRESET_A,
      requestId: 1,
      message: "已设为旁白。",
    });
    expect(applied).toMatchObject({ phase: "applied", message: "已设为旁白。" });
    expect(canStartOfficialVoiceUse(applied)).toBe(true);
    expect(Object.isFrozen(applied)).toBe(true);
  });

  it("ignores duplicate starts and stale completions", () => {
    const pending = applying();
    expect(reduceOfficialVoiceUseState(pending, {
      type: "start",
      presetId: PRESET_B,
      requestId: 2,
      idempotencyKey: KEY_B,
      message: "不应覆盖",
    })).toBe(pending);
    expect(reduceOfficialVoiceUseState(pending, {
      type: "succeed",
      presetId: PRESET_B,
      requestId: 1,
      message: "过期响应",
    })).toBe(pending);
    expect(reduceOfficialVoiceUseState(pending, {
      type: "succeed",
      presetId: PRESET_A,
      requestId: 2,
      message: "过期响应",
    })).toBe(pending);
  });

  it("separates conflict from retryable errors and requires reset after conflict", () => {
    const conflict = reduceOfficialVoiceUseState(applying(), {
      type: "fail",
      presetId: PRESET_A,
      requestId: 1,
      failure: classifyOfficialVoiceUseFailure({
        status: 409,
        detail: { code: "VERSION_CONFLICT", retryable: true },
      }),
    });
    expect(conflict).toMatchObject({
      phase: "conflict",
      failure: { kind: "conflict", retryable: false },
    });
    expect(canStartOfficialVoiceUse(conflict)).toBe(false);

    const ignored = reduceOfficialVoiceUseState(conflict, {
      type: "start",
      presetId: PRESET_A,
      requestId: 2,
      idempotencyKey: KEY_B,
      message: "不能用旧版本直接重试",
    });
    expect(ignored).toBe(conflict);

    const reset = reduceOfficialVoiceUseState(conflict, {
      type: "reset",
      requestId: 2,
    });
    expect(reset).toMatchObject({ phase: "idle", requestId: 2, presetId: null });
  });

  it("reuses the same idempotency key only for a retryable same-intent error", () => {
    const failed = reduceOfficialVoiceUseState(applying(), {
      type: "fail",
      presetId: PRESET_A,
      requestId: 1,
      failure: classifyOfficialVoiceUseFailure(new TypeError("connection reset")),
    });
    expect(failed).toMatchObject({
      phase: "error",
      failure: { retryable: true },
    });
    const createKey = vi.fn(() => KEY_B);
    expect(nextOfficialVoiceUseIdempotencyKey(failed, PRESET_A, createKey)).toBe(KEY_A);
    expect(createKey).not.toHaveBeenCalled();
    expect(nextOfficialVoiceUseIdempotencyKey(failed, PRESET_B, createKey)).toBe(KEY_B);
    expect(createKey).toHaveBeenCalledTimes(1);
  });

  it("classifies structural API failures without importing the public API DTO", () => {
    expect(classifyOfficialVoiceUseFailure({
      status: 422,
      detail: { code: "REQUEST_VALIDATION_FAILED", retryable: false },
    })).toMatchObject({
      kind: "error",
      code: "REQUEST_VALIDATION_FAILED",
      retryable: false,
    });
    expect(classifyOfficialVoiceUseFailure(
      new OfficialVoiceUseResponseError("mismatch"),
    )).toMatchObject({
      kind: "error",
      code: "RESPONSE_CONTRACT_VIOLATION",
      retryable: false,
    });
    expect(classifyOfficialVoiceUseFailure(
      new OfficialVoiceUseConflictError(),
    )).toMatchObject({
      kind: "conflict",
      code: "SELECTION_NOT_CURRENT",
      retryable: false,
    });
  });

  it("creates an API-safe idempotency key", () => {
    expect(createOfficialVoiceUseIdempotencyKey()).toMatch(
      /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/u,
    );
  });
});
