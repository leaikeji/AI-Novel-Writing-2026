import type { CharacterCastPlanResource } from "./contracts";
import type { CharacterCastUiStatus } from "./character-voice-roster";
import { NarrationContractError } from "./contracts";
import type { TimelineIndexResource } from "../story-timeline/contracts";


export interface CharacterCastRunnerApi {
  getPlan(
    novelId: string,
    commandId: string,
    signal?: AbortSignal,
  ): Promise<CharacterCastPlanResource>;
  advancePlan(
    novelId: string,
    commandId: string,
    signal?: AbortSignal,
  ): Promise<CharacterCastPlanResource>;
}


export interface ContinueCharacterCastPlanOptions {
  readonly novelId: string;
  readonly initial: CharacterCastPlanResource;
  readonly api: CharacterCastRunnerApi;
  readonly signal: AbortSignal;
  readonly onUpdate: (plan: CharacterCastPlanResource) => void;
  readonly waitForPoll?: (signal: AbortSignal) => Promise<void>;
}


export function activeCharacterCastPlan(
  plans: readonly CharacterCastPlanResource[],
): CharacterCastPlanResource | null {
  return plans.find((plan) => plan.state === "reserved" || plan.state === "analyzing")
    ?? null;
}


export function characterCastUiStatus(
  plan: CharacterCastPlanResource | null,
): CharacterCastUiStatus | null {
  if (plan === null) return null;
  const common = {
    progressCurrent: plan.progress_current,
    progressTotal: plan.progress_total,
    retryable: plan.retryable,
  };
  if (plan.state === "reserved") {
    return { ...common, phase: "reserved", message: "已建立整书配音任务，正在准备人物资料。" };
  }
  if (plan.state === "analyzing") {
    return {
      ...common,
      phase: "analyzing",
      message: `正在逐一分析已保存的人物资料（${plan.progress_current}/${plan.progress_total}）。`,
    };
  }
  if (plan.state === "ready_applied") {
    return { ...common, phase: "applied", message: "整书智能配音已完成并应用。" };
  }
  if (plan.state === "ready_applied_with_warnings") {
    return {
      ...common,
      phase: "warning",
      message: `已完成可安全应用的配音；${plan.warnings.length} 项需手动处理。`,
    };
  }
  if (plan.state === "ready_unapplied") {
    return {
      ...common,
      phase: "unapplied",
      message: "人物资料或声音已变化，旧方案未覆盖新选择。再次点击可按最新状态规划。",
    };
  }
  return {
    ...common,
    phase: "failed",
    message: plan.state === "superseded"
      ? "该配音任务已失效，可按最新资料重新开始。"
      : plan.retryable
        ? "声音分析未完成，原声音未改变；可一键重试。"
        : "本次智能配音未产生可应用结果，原声音未改变。",
  };
}


export function primaryTimelineId(index: TimelineIndexResource, novelId: string): string {
  const active = index.items.filter((timeline) => (
    timeline.novel_id === novelId && timeline.lifecycle_state === "active"
  ));
  const selected = active.find((timeline) => timeline.is_primary)
    ?? active.find((timeline) => timeline.timeline_kind === "main")
    ?? active[0];
  if (selected === undefined) {
    throw new NarrationContractError(
      "character_cast_plan.timeline_id",
      "no active timeline",
    );
  }
  return selected.id;
}


export function waitForCharacterCastPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = globalThis.setTimeout(resolve, 1_200);
    signal.addEventListener("abort", () => {
      globalThis.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}


export async function continueCharacterCastPlan(
  options: ContinueCharacterCastPlanOptions,
): Promise<CharacterCastPlanResource> {
  const wait = options.waitForPoll ?? waitForCharacterCastPoll;
  let current = options.initial;
  while (!options.signal.aborted && !current.terminal) {
    const leaseIsActive = current.current_target_key !== null
      && current.lease_expires_at !== null
      && Date.parse(current.lease_expires_at) > Date.parse(current.server_now);
    if (leaseIsActive) {
      await wait(options.signal);
      if (options.signal.aborted) break;
      current = await options.api.getPlan(
        options.novelId,
        current.command_id,
        options.signal,
      );
    } else {
      current = await options.api.advancePlan(
        options.novelId,
        current.command_id,
        options.signal,
      );
    }
    if (!options.signal.aborted) options.onUpdate(current);
  }
  return current;
}
