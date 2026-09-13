import { describe, expect, it, vi } from "vitest";
import { recoverExistingNarration } from "./recover-existing-narration";
import type { DocumentNarrationContext, NarrationEditionResource, NarrationWorkflowResource,
  FailedNarrationSegmentsProjection } from "./chapter-contracts";

function fixture() {
  const workflow: NarrationWorkflowResource = {
    contract_version: "narration-production-api/1", request_id: "new", intent: "create",
    request_version: 1, workflow_state: "review_required", source_revision_id: "rev",
    source_content_hash: "hash", settings_fingerprint: "settings", warning_count: 0,
    blocker_count: 1, script_version_id: "script", edition_id: null,
    current_manifest_revision: null, job_ids: [], replayed: false,
  };
  const previous: NarrationWorkflowResource = { ...workflow, request_id: "old",
    workflow_state: "failed", edition_id: "edition", current_manifest_revision: 1 };
  const edition: NarrationEditionResource = {
    contract_version: "narration-production-api/1", edition_id: "edition", request_id: "old",
    novel_id: "novel", document_id: "document", script_version_id: "script",
    settings_fingerprint: "settings", edition_fingerprint: "ef", state: "unavailable",
    segment_count: 1, pending_segment_count: 0, queued_segment_count: 0,
    rendering_segment_count: 0, ready_segment_count: 0, failed_segment_count: 1,
    current_manifest_revision: 1, job_ids: [],
  };
  const context: DocumentNarrationContext = {
    contract_version: "document-narration-context/1", novel_id: "novel", document_id: "document",
    pointer_version: 0, current_script_version_id: null, current_edition_id: null,
    active_edition_id: null, active_is_current: false, working_copy_draft_version: 3,
    working_copy_content_hash: "hash", source_snapshot: null, compatibility: "no_current_edition",
    source_notice_code: "NO_CURRENT_EDITION", editor_timeline_mode: "none",
    old_draft_subtitle_required: false, explicit_update_required: false, can_request_update: true,
    available_current_source_edition_ids: [], edition_history: {
      contract_version: "narration-edition-history/1", document_id: "document", pointer_version: 0,
      current_edition_id: null, working_copy_content_hash: "hash", working_copy_draft_version: 3,
      editions: [{ edition_id: "edition", request_id: "old", source_revision_id: "rev",
        source_content_hash: "hash", edition_fingerprint: "ef", state: "unavailable",
        created_at: "2026-09-13T00:00:00Z", manifest_revision: 1, manifest_etag: "etag",
        ready_segment_count: 0, total_segment_count: 1, is_current: false,
        source_status: "superseded", rights_available: true, playable: false,
        default_start_ready: false, resume_available: false, switch_allowed: false }],
    },
  };
  const failed: FailedNarrationSegmentsProjection = {
    contract_version: "narration-failed-segment-retry/1", edition_id: "edition", request_id: "old",
    request_version: 37, manifest_revision: 1, request_state: "failed", edition_state: "unavailable",
    items: [{ segment_id: "segment", ordinal: 0, failure_code: "TTS_PROVIDER_UNAVAILABLE",
      retryable: true, retry_reason_code: null, job_id: "job", fanout_segment_ids: ["segment"] }],
  };
  const resumed = { ...previous, workflow_state: "queued" as const };
  const deps = {
    getContext: vi.fn(async () => context), getEdition: vi.fn(async () => edition),
    getWorkflow: vi.fn().mockResolvedValueOnce(previous).mockResolvedValue(resumed),
    getFailed: vi.fn(async () => failed), retry: vi.fn<typeof import("./api").retryFailedNarrationSegments>(async () => ({
      contract_version: "narration-failed-segment-retry/1" as const, edition_id: "edition",
      request_id: "old", accepted_segment_ids: ["segment"], affected_segment_ids: ["segment"],
      commands: [], request_version: 38, request_state: "queued" as const,
      edition_state: "rendering" as const, replayed: false,
    })),
  };
  const controller = new AbortController();
  const options = { novelId: "novel", documentId: "document", workflow,
    idempotencyKey: "action:recover", signal: controller.signal, assertCurrent: vi.fn(), dependencies: deps };
  return { options, deps, context, edition, previous, failed, resumed, controller };
}

describe("one-click existing audio recovery", () => {
  it("retries the original failed batch exactly once using projection CAS", async () => {
    const f = fixture();
    expect(await recoverExistingNarration(f.options)).toEqual(f.resumed);
    expect(f.deps.retry).toHaveBeenCalledExactlyOnceWith("edition", {
      segment_ids: ["segment"], expected_request_version: 37, expected_manifest_revision: 1,
    }, "action:recover:0", f.controller.signal);
  });
  it("splits 135 failures into 100/35 with fresh CAS, never retries the same IDs", async () => {
    const f = fixture();
    const items = Array.from({ length: 135 }, (_, n) => ({ ...f.failed.items[0], segment_id: `s${n}` }));
    f.deps.getFailed.mockResolvedValueOnce({ ...f.failed, items })
      .mockResolvedValueOnce({ ...f.failed, request_version: 38, request_state: "rendering", items: items.slice(100) });
    await recoverExistingNarration(f.options);
    expect(f.deps.retry).toHaveBeenCalledTimes(2);
    expect(f.deps.retry.mock.calls.map((call) => call[1].segment_ids.length)).toEqual([100, 35]);
    expect(f.deps.retry.mock.calls[1][1].expected_request_version).toBe(38);
    expect(f.deps.retry.mock.calls[1][2]).toBe("action:recover:1");
  });
  it.each(["queued", "rendering", "partial_ready", "ready"] as const)("resumes %s without retry", async (state) => {
    const f = fixture();
    f.deps.getWorkflow.mockReset().mockResolvedValue({ ...f.previous, workflow_state: state });
    expect((await recoverExistingNarration(f.options)).request_id).toBe("old");
    expect(f.deps.retry).not.toHaveBeenCalled();
  });
  it("leaves a normal non-review workflow untouched", async () => {
    const f = fixture();
    const active = { ...f.options.workflow, workflow_state: "analyzing" as const };
    expect(await recoverExistingNarration({ ...f.options, workflow: active })).toBe(active);
    expect(f.deps.getContext).not.toHaveBeenCalled();
  });
  it.each(["empty", "source", "settings"])("does not reuse %s history", async (kind) => {
    const f = fixture();
    if (kind === "empty") f.deps.getContext.mockResolvedValue({ ...f.context,
      edition_history: { ...f.context.edition_history, editions: [] } });
    if (kind === "source") f.deps.getContext.mockResolvedValue({ ...f.context,
      edition_history: { ...f.context.edition_history, editions: f.context.edition_history.editions.map(x => ({ ...x, source_content_hash: "oldhash" })) } });
    if (kind === "settings") f.deps.getEdition.mockResolvedValue({ ...f.edition, settings_fingerprint: "oldsettings" });
    expect(await recoverExistingNarration(f.options)).toBe(f.options.workflow);
    expect(f.deps.retry).not.toHaveBeenCalled();
  });
  it.each(["scope", "changed-source", "edition-scope", "request-scope", "rights", "not-retryable", "projection-scope"])("fails closed on %s", async (kind) => {
    const f = fixture();
    if (kind === "scope") f.deps.getContext.mockResolvedValue({ ...f.context, novel_id: "other" });
    if (kind === "changed-source") f.deps.getContext.mockResolvedValue({ ...f.context, working_copy_content_hash: "changed" });
    if (kind === "edition-scope") f.deps.getEdition.mockResolvedValue({ ...f.edition, document_id: "other" });
    if (kind === "request-scope") f.deps.getWorkflow.mockReset().mockResolvedValue({ ...f.previous, settings_fingerprint: "other" });
    if (kind === "rights") f.deps.getContext.mockResolvedValue({ ...f.context,
      edition_history: { ...f.context.edition_history, editions: f.context.edition_history.editions.map(x => ({ ...x, rights_available: false })) } });
    if (kind === "not-retryable") f.deps.getFailed.mockResolvedValue({ ...f.failed, items: f.failed.items.map(x => ({ ...x, retryable: false })) });
    if (kind === "projection-scope") f.deps.getFailed.mockResolvedValue({ ...f.failed, request_id: "other" });
    await expect(recoverExistingNarration(f.options)).rejects.toThrow();
    expect(f.deps.retry).not.toHaveBeenCalled();
  });
  it("propagates CAS/network failure without falling back to approval", async () => {
    const f = fixture();
    f.deps.retry.mockRejectedValue(new Error("VERSION_CONFLICT"));
    await expect(recoverExistingNarration(f.options)).rejects.toThrow("VERSION_CONFLICT");
    expect(f.deps.retry).toHaveBeenCalledTimes(1);
  });
  it.each(["abort", "switch"])("does not write after %s during projection read", async (kind) => {
    const f = fixture();
    f.deps.getFailed.mockImplementation(async () => {
      if (kind === "abort") f.controller.abort();
      else f.options.assertCurrent.mockImplementation(() => { throw new Error("stale"); });
      return f.failed;
    });
    await expect(recoverExistingNarration(f.options)).rejects.toThrow();
    expect(f.deps.retry).not.toHaveBeenCalled();
  });
});
