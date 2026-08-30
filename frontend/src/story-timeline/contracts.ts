export interface StoryTimelineRecord {
  readonly id: string;
  readonly novel_id: string;
  readonly timeline_key: string;
  readonly name: string;
  readonly timeline_kind: "main" | "branch" | "merge";
  readonly is_primary: boolean;
  readonly parent_timeline_id: string | null;
  readonly fork_story_sequence: number | null;
  readonly lifecycle_state: "active" | "archived";
  readonly position: number;
  readonly version: number;
}

export interface TimelineIndexResource {
  readonly single_timeline_mode: boolean;
  readonly items: readonly StoryTimelineRecord[];
}

export interface CharacterInstanceRecord {
  readonly id: string;
  readonly novel_id: string;
  readonly character_id: string;
  readonly origin_timeline_id: string;
  readonly derived_from_instance_id: string | null;
  readonly continuity_kind: "native" | "derived" | "traveler";
  readonly display_label: string;
  readonly current_revision_id: string | null;
  readonly lifecycle_state: "active" | "archived";
  readonly version: number;
}

export interface TimelineForkResult {
  readonly timeline: StoryTimelineRecord;
  readonly derived_instances: readonly CharacterInstanceRecord[];
  readonly copied_fact_count: 0;
  readonly story_ledger_version: number;
}

export interface CharacterRootSummary {
  readonly id: string;
  readonly name: string;
}

/**
 * Minimal hand-off from the timeline workspace to the single formal character
 * workspace. The receiver must use all three stable IDs and must not resolve an
 * instance by display name or by the most recently used timeline.
 */
export interface StoryTimelineCharacterCardTarget {
  readonly characterId: string;
  readonly timelineId: string;
  readonly instanceId: string;
}
