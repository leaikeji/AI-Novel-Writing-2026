import { describe, expect, it, vi } from "vitest";

import {
  activeCharacterCastPlan,
  characterCastUiStatus,
  continueCharacterCastPlan,
  primaryTimelineId,
} from "./character-cast-runner";
import type { CharacterCastPlanResource } from "./contracts";


const NOVEL_ID = "10000000-0000-4000-8000-000000000001";
const COMMAND_ID = "10000000-0000-4000-8000-000000000002";
const TIMELINE_ID = "10000000-0000-4000-8000-000000000003";
const ITEM_ID = "10000000-0000-4000-8000-000000000004";
const NOW = "2026-09-01T00:00:00Z";


function plan(
  changes: Partial<CharacterCastPlanResource> = {},
): CharacterCastPlanResource {
  const state = changes.state ?? "reserved";
  const terminal = [
    "ready_applied",
    "ready_applied_with_warnings",
    "ready_unapplied",
    "failed",
    "superseded",
  ].includes(state);
  return {
    contract_version: "character-cast-plan/1",
    command_id: COMMAND_ID,
    novel_id: NOVEL_ID,
    timeline_id: TIMELINE_ID,
    mode: "fill_and_deduplicate",
    state,
    server_now: NOW,
    progress_current: terminal ? 1 : 0,
    progress_total: 1,
    terminal,
    retryable: state === "failed",
    current_target_key: null,
    lease_expires_at: null,
    assignments: [],
    preserved: [],
    warnings: [],
    items: [{
      item_id: ITEM_ID,
      target: {
        target_key: "narrator",
        target_kind: "narrator",
        character_id: null,
        character_name: null,
        role_type: null,
      },
      state: terminal ? "blocked" : "pending",
      attempt: 0,
      workspace_digest: "a".repeat(64),
      lease_expires_at: null,
      brief: null,
      selected_preset_id: null,
      score_milli: null,
      profile_id: null,
      version_id: null,
      voice_action_command_id: null,
      warning_code: null,
      failure_code: null,
    }],
    failure_code: state === "failed" ? "CAST_PLAN_ALL_TARGETS_FAILED" : null,
    created_at: NOW,
    updated_at: NOW,
    completed_at: terminal ? NOW : null,
    ...changes,
  };
}


describe("character cast command runner", () => {
  it("advances exactly one server target at a time until the command is terminal", async () => {
    const intermediate = plan({ state: "analyzing" });
    const completed = plan({ state: "ready_applied" });
    const advancePlan = vi.fn()
      .mockResolvedValueOnce(intermediate)
      .mockResolvedValueOnce(completed);
    const onUpdate = vi.fn();

    const result = await continueCharacterCastPlan({
      novelId: NOVEL_ID,
      initial: plan(),
      api: { getPlan: vi.fn(), advancePlan },
      signal: new AbortController().signal,
      onUpdate,
    });

    expect(result).toBe(completed);
    expect(advancePlan.mock.calls).toEqual([
      [NOVEL_ID, COMMAND_ID, expect.any(AbortSignal)],
      [NOVEL_ID, COMMAND_ID, expect.any(AbortSignal)],
    ]);
    expect(onUpdate.mock.calls.map(([value]) => value)).toEqual([
      intermediate,
      completed,
    ]);
  });

  it("polls an existing lease after refresh instead of starting a second analysis", async () => {
    const leased = plan({
      state: "analyzing",
      current_target_key: "narrator",
      lease_expires_at: "2026-09-01T00:15:00Z",
      items: [{
        ...plan().items[0]!,
        state: "analyzing",
        attempt: 1,
        lease_expires_at: "2026-09-01T00:15:00Z",
      }],
    });
    const released = plan({ state: "analyzing" });
    const completed = plan({ state: "ready_applied" });
    const waitForPoll = vi.fn(async () => undefined);
    const getPlan = vi.fn(async () => released);
    const advancePlan = vi.fn(async () => completed);

    await continueCharacterCastPlan({
      novelId: NOVEL_ID,
      initial: leased,
      api: { getPlan, advancePlan },
      signal: new AbortController().signal,
      onUpdate: vi.fn(),
      waitForPoll,
    });

    expect(waitForPoll).toHaveBeenCalledTimes(1);
    expect(getPlan).toHaveBeenCalledTimes(1);
    expect(advancePlan).toHaveBeenCalledTimes(1);
    expect(getPlan.mock.invocationCallOrder[0]).toBeLessThan(
      advancePlan.mock.invocationCallOrder[0]!,
    );
  });

  it("stops after abort while waiting on another browser's lease", async () => {
    const controller = new AbortController();
    const getPlan = vi.fn();
    const advancePlan = vi.fn();
    const leased = plan({
      state: "analyzing",
      current_target_key: "narrator",
      lease_expires_at: "2026-09-01T00:15:00Z",
    });

    const result = await continueCharacterCastPlan({
      novelId: NOVEL_ID,
      initial: leased,
      api: { getPlan, advancePlan },
      signal: controller.signal,
      onUpdate: vi.fn(),
      waitForPoll: async () => { controller.abort(); },
    });

    expect(result).toBe(leased);
    expect(getPlan).not.toHaveBeenCalled();
    expect(advancePlan).not.toHaveBeenCalled();
  });

  it("restores the active command and projects terminal recovery guidance", () => {
    const completed = plan({ state: "ready_applied" });
    const analyzing = plan({ state: "analyzing" });
    expect(activeCharacterCastPlan([completed, analyzing])).toBe(analyzing);
    expect(characterCastUiStatus(plan({ state: "ready_unapplied" })))
      .toMatchObject({ phase: "unapplied" });
    expect(characterCastUiStatus(plan({ state: "failed", retryable: true })))
      .toMatchObject({
        phase: "failed",
        retryable: true,
        message: "声音分析未完成，原声音未改变；可一键重试。",
      });
  });

  it("derives the primary active timeline only from the requested novel", () => {
    expect(primaryTimelineId({
      single_timeline_mode: false,
      items: [
        {
          id: "20000000-0000-4000-8000-000000000001",
          novel_id: "20000000-0000-4000-8000-000000000002",
          timeline_key: "foreign",
          name: "其他作品",
          timeline_kind: "main",
          is_primary: true,
          parent_timeline_id: null,
          fork_story_sequence: null,
          lifecycle_state: "active",
          position: 0,
          version: 1,
        },
        {
          id: TIMELINE_ID,
          novel_id: NOVEL_ID,
          timeline_key: "main",
          name: "主时间线",
          timeline_kind: "main",
          is_primary: true,
          parent_timeline_id: null,
          fork_story_sequence: null,
          lifecycle_state: "active",
          position: 0,
          version: 1,
        },
      ],
    }, NOVEL_ID)).toBe(TIMELINE_ID);
    expect(() => primaryTimelineId({ single_timeline_mode: true, items: [] }, NOVEL_ID))
      .toThrow(/no active timeline/);
  });
});
