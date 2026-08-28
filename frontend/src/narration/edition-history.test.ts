import { describe, expect, it } from "vitest";

import {
  EDITION_HISTORY_CONTRACT_VERSION,
  EditionHistoryContractError,
  LatestNarrationIntentCoordinator,
  createEditionSwitchIntent,
  parseDocumentEditionHistory,
} from "./edition-history";


const CURRENT = "10000000-0000-4000-8000-000000000001";
const HISTORY = "10000000-0000-4000-8000-000000000002";
const DOCUMENT = "20000000-0000-4000-8000-000000000001";
const SEGMENT = "30000000-0000-4000-8000-000000000001";


function item(editionId: string, current: boolean) {
  return {
    edition_id: editionId,
    request_id: current
      ? "40000000-0000-4000-8000-000000000001"
      : "40000000-0000-4000-8000-000000000002",
    source_revision_id: current
      ? "50000000-0000-4000-8000-000000000001"
      : "50000000-0000-4000-8000-000000000002",
    source_content_hash: current ? "a".repeat(64) : "b".repeat(64),
    edition_fingerprint: current ? "c".repeat(64) : "d".repeat(64),
    state: "ready",
    created_at: current ? "2026-08-27T12:00:00Z" : "2026-08-26T12:00:00Z",
    manifest_revision: current ? 3 : 1,
    manifest_etag: current ? `"${"e".repeat(64)}"` : `"${"f".repeat(64)}"`,
    ready_segment_count: 8,
    total_segment_count: 8,
    is_current: current,
    source_status: current ? "current" : "superseded",
    rights_available: true,
    playable: true,
    default_start_ready: true,
    resume_available: current,
    switch_allowed: true,
  };
}


function payload() {
  return {
    contract_version: EDITION_HISTORY_CONTRACT_VERSION,
    document_id: DOCUMENT,
    pointer_version: 7,
    current_edition_id: CURRENT,
    working_copy_content_hash: "a".repeat(64),
    working_copy_draft_version: 12,
    editions: [item(CURRENT, true), item(HISTORY, false)],
  };
}


function deferred<T>(): { readonly promise: Promise<T>; resolve(value: T): void } {
  let complete!: (value: T) => void;
  const promise = new Promise<T>((resolve) => { complete = resolve; });
  return { promise, resolve: (value: T) => complete(value) };
}


describe("Edition history contract", () => {
  it("parses a strict immutable history projection", () => {
    const history = parseDocumentEditionHistory(payload());

    expect(history.current_edition_id).toBe(CURRENT);
    expect(history.editions).toHaveLength(2);
    expect(history.editions[1].source_status).toBe("superseded");
    expect(Object.isFrozen(history)).toBe(true);
    expect(Object.isFrozen(history.editions)).toBe(true);
    expect(Object.isFrozen(history.editions[0])).toBe(true);
  });

  it("rejects unknown fields, pointer drift, unsafe rights, and false starts", () => {
    expect(() => parseDocumentEditionHistory({ ...payload(), token: "secret" })).toThrow(
      EditionHistoryContractError,
    );
    const pointerDrift = payload();
    pointerDrift.current_edition_id = HISTORY;
    expect(() => parseDocumentEditionHistory(pointerDrift)).toThrow(/unique current Edition/u);

    const rightsDrift = payload();
    rightsDrift.editions[1].rights_available = false;
    expect(() => parseDocumentEditionHistory(rightsDrift)).toThrow(/playable/u);

    const startDrift = payload();
    startDrift.editions[1].default_start_ready = false;
    startDrift.editions[1].resume_available = false;
    expect(() => parseDocumentEditionHistory(startDrift)).toThrow(/legal ready start/u);
  });
});


describe("Edition switch intent", () => {
  it("binds the target to the document pointer CAS version", () => {
    const history = parseDocumentEditionHistory(payload());

    expect(createEditionSwitchIntent(history, HISTORY, "immediate", SEGMENT)).toEqual({
      document_id: DOCUMENT,
      edition_id: HISTORY,
      expected_version: 7,
      switch_mode: "immediate",
      start_segment_id: SEGMENT,
    });
    expect(createEditionSwitchIntent(history, HISTORY, "next_playback")).toEqual({
      document_id: DOCUMENT,
      edition_id: HISTORY,
      expected_version: 7,
      switch_mode: "next_playback",
      start_segment_id: null,
    });
  });

  it("never switches unknown, current, or non-playable Editions", () => {
    const history = parseDocumentEditionHistory(payload());
    expect(() => createEditionSwitchIntent(history, CURRENT, "immediate")).toThrow(/already current/u);
    expect(() => createEditionSwitchIntent(
      history,
      "10000000-0000-4000-8000-000000000099",
      "immediate",
    )).toThrow(/outside this document/u);

    const blockedPayload = payload();
    blockedPayload.editions[1].playable = false;
    blockedPayload.editions[1].switch_allowed = false;
    const blocked = parseDocumentEditionHistory(blockedPayload);
    expect(() => createEditionSwitchIntent(blocked, HISTORY, "next_playback")).toThrow(/no legal/u);
  });
});


describe("Latest narration intent coordinator", () => {
  it("aborts and suppresses every superseded rapid intent", async () => {
    const coordinator = new LatestNarrationIntentCoordinator();
    const signals: AbortSignal[] = [];
    const firstDeferred = deferred<string>();
    const secondDeferred = deferred<string>();
    const first = coordinator.run((signal) => {
      signals.push(signal);
      return firstDeferred.promise;
    });
    const second = coordinator.run(() => secondDeferred.promise);

    expect(signals[0]?.aborted).toBe(true);
    secondDeferred.resolve("latest");
    firstDeferred.resolve("stale");

    await expect(second).resolves.toEqual({ accepted: true, sequence: 2, value: "latest" });
    await expect(first).resolves.toEqual({ accepted: false, sequence: 1, reason: "superseded" });
  });

  it("disposes one coordinator without leaking a late result", async () => {
    const coordinator = new LatestNarrationIntentCoordinator();
    const value = deferred<number>();
    const pending = coordinator.run(() => value.promise);
    coordinator.dispose();
    value.resolve(1);
    await expect(pending).resolves.toMatchObject({ accepted: false, reason: "disposed" });
    await expect(coordinator.run(async () => 2)).resolves.toMatchObject({
      accepted: false,
      reason: "disposed",
    });
  });
});
