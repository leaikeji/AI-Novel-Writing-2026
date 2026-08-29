import { apiRequest } from "../api";
import type {
  CharacterInstanceProfileResource,
  CharacterInstanceProfileV1,
  CharacterInstanceRecord,
  TimelineForkResult,
  TimelineIndexResource,
} from "./contracts";

const segment = (value: string): string => encodeURIComponent(value);

export function listStoryTimelines(
  novelId: string,
  signal?: AbortSignal,
): Promise<TimelineIndexResource> {
  return apiRequest(`/novels/${segment(novelId)}/timelines`, { signal });
}

export function listCharacterInstances(
  novelId: string,
  signal?: AbortSignal,
): Promise<CharacterInstanceRecord[]> {
  return apiRequest(`/novels/${segment(novelId)}/character-instances`, { signal });
}

export function forkStoryTimeline(
  novelId: string,
  timelineId: string,
  request: {
    readonly expected_story_ledger_version: number;
    readonly expected_source_timeline_version: number;
    readonly timeline_key: string;
    readonly name: string;
    readonly fork_story_sequence: number;
    readonly fork_anchor: Record<string, unknown>;
  },
  signal?: AbortSignal,
): Promise<TimelineForkResult> {
  return apiRequest(
    `/novels/${segment(novelId)}/timelines/${segment(timelineId)}/fork`,
    { method: "POST", body: JSON.stringify(request), signal },
  );
}

export function getCharacterInstanceProfile(
  novelId: string,
  instanceId: string,
  signal?: AbortSignal,
): Promise<CharacterInstanceProfileResource> {
  return apiRequest(
    `/novels/${segment(novelId)}/character-instances/${segment(instanceId)}/profile`,
    { signal },
  );
}

export function saveCharacterInstanceProfile(
  novelId: string,
  instanceId: string,
  request: {
    readonly expected_story_ledger_version: number;
    readonly expected_instance_version: number;
    readonly operation_key: string;
    readonly source_kind: "manual";
    readonly profile: CharacterInstanceProfileV1;
  },
  signal?: AbortSignal,
): Promise<CharacterInstanceProfileResource & { readonly story_ledger_version: number }> {
  return apiRequest(
    `/novels/${segment(novelId)}/character-instances/${segment(instanceId)}/profile`,
    { method: "PUT", body: JSON.stringify(request), signal },
  );
}
