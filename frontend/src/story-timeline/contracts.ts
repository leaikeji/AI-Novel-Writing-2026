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

export interface CharacterInstanceProfileV1 {
  readonly schema_version: "character-instance-profile/1";
  readonly public_identity: string | null;
  readonly true_identity: string | null;
  readonly cover_identity: string | null;
  readonly birth_year: number | null;
  readonly birth_information: string | null;
  readonly occupation: string | null;
  readonly personality: string | null;
  readonly goals: readonly string[];
  readonly flaws: readonly string[];
  readonly secrets: readonly string[];
  readonly growth_direction: string | null;
}

export interface CharacterInstanceProfileResource {
  readonly instance: CharacterInstanceRecord;
  readonly revision: null | {
    readonly id: string;
    readonly revision_number: number;
    readonly profile: CharacterInstanceProfileV1;
  };
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

export const EMPTY_INSTANCE_PROFILE: CharacterInstanceProfileV1 = {
  schema_version: "character-instance-profile/1",
  public_identity: null,
  true_identity: null,
  cover_identity: null,
  birth_year: null,
  birth_information: null,
  occupation: null,
  personality: null,
  goals: [],
  flaws: [],
  secrets: [],
  growth_direction: null,
};
