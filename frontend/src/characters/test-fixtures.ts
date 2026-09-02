import type { CharacterWorkspaceV2 } from "./contracts";
import type { StoryLedgerFactImpactPreview } from "../story-ledger";

export function storyFactImpact(
  overrides: Partial<StoryLedgerFactImpactPreview> = {},
): StoryLedgerFactImpactPreview {
  return {
    schema_version: "story-ledger-fact-impact-preview/1",
    novel_id: "novel-1",
    fact_id: "fact-1",
    preview_snapshot_token: "ledger-snapshot-19",
    story_ledger_version: 19,
    timeline: {
      mode: "single",
      timeline_id: "timeline-main",
      timeline_name: "主时间线",
      narrative_cutoff: 12,
    },
    currently_in_projection: true,
    current_projection_fact_count: 1,
    related_event_link_count: 0,
    embedding_rebuild_required: true,
    commit_batch_ids: [],
    batch_fact_count: 0,
    batch_relationship_count: 0,
    correction_supported: true,
    correction_block_reason: null,
    ...overrides,
  };
}

export function characterWorkspace(
  overrides: Partial<CharacterWorkspaceV2> = {},
): CharacterWorkspaceV2 {
  const primaryTimeline = {
    id: "timeline-main",
    name: "主时间线",
    timeline_kind: "main",
    is_primary: true,
    parent_timeline_id: null,
    fork_story_sequence: null,
  } as const;
  const mainInstance = {
    id: "instance-main",
    character_id: "character-1",
    origin_timeline_id: primaryTimeline.id,
    continuity_kind: "default",
    display_label: "主线版本",
    derived_from_instance_id: null,
    lifecycle_state: "active",
    version: 7,
    current_revision_id: "instance-revision-7",
    profile: {
      schema_version: "character-instance-profile/2",
      public_identity: "书店店员",
      true_identity: "守门人",
      goals: ["寻找失踪的姐姐"],
    },
    profile_schema_version: 2,
  } as const;
  return {
    schema_version: "character-workspace/2",
    novel_id: "novel-1",
    character_catalog_version: 11,
    story_ledger_version: 19,
    timeline_mode: "single",
    character: {
      id: "character-1",
      novel_id: "novel-1",
      name: "林舟",
      role_type: "main",
      description: "沉静而敏锐。",
      details: {},
      lifecycle_state: "active",
      position: 1,
      version: 4,
      current_revision_id: "character-revision-4",
    },
    selected_timeline: primaryTimeline,
    selected_instance: mainInstance,
    timelines: [primaryTimeline],
    instances: [mainInstance],
    aliases: [
      {
        id: "alias-1",
        alias: "小舟",
        alias_kind: "nickname",
        timeline_id: null,
        character_instance_id: null,
        identity_layer: "public",
        valid_from_sequence: null,
        valid_to_sequence: null,
        lifecycle_state: "active",
      },
    ],
    relationships: [],
    chapter_references: [],
    voice_binding: {
      binding_id: "binding-1",
      binding_policy: "fixed",
      profile_id: "voice-profile-1",
      voice_version_id: "voice-version-1",
      language: "zh-CN",
      version: 3,
    },
    projected_state: {
      timeline_id: primaryTimeline.id,
      narrative_cutoff: 12,
      current_facts: [
        {
          id: "fact-1",
          fact_type: "character_state",
          timeline_id: primaryTimeline.id,
          character_id: "character-1",
          character_instance_id: "instance-main",
          relationship_id: null,
          dimension: "勇气",
          event_kind: "changed",
          predicate: "勇气变化",
          object_text: "开始主动承担风险",
          details: {},
          story_sequence: 12,
          source_revision_id: "chapter-revision-12",
          source_document_id: "chapter-12",
          story_time: null,
          created_at: "2026-08-31T12:00:00Z",
          effective_state: "current",
          health: "ok",
          source: null,
        },
      ],
      conflicts: [],
      ambiguous_fact_ids: [],
    },
    writing_state: {
      as_of: {
        timeline_id: primaryTimeline.id,
        narrative_cutoff: 12,
        story_time: null,
      },
      slots: [
        {
          key: "goal",
          label: "当前目标",
          mode: "multiple",
          values: [
            {
              fact_id: "fact-1",
              object_text: "开始主动承担风险",
              story_sequence: 12,
              story_time: null,
              source: null,
            },
          ],
          health: "ok",
        },
      ],
      recent_changes: [
        {
          id: "fact-1",
          fact_type: "character_state",
          timeline_id: primaryTimeline.id,
          character_id: "character-1",
          character_instance_id: "instance-main",
          relationship_id: null,
          dimension: "勇气",
          event_kind: "changed",
          predicate: "勇气变化",
          object_text: "开始主动承担风险",
          details: {},
          story_sequence: 12,
          source_revision_id: "chapter-revision-12",
          source_document_id: "chapter-12",
          story_time: null,
          created_at: "2026-08-31T12:00:00Z",
          effective_state: "current",
          health: "ok",
          source: null,
        },
      ],
      risk_summary: {
        conflict_count: 0,
        ambiguous_count: 0,
        invalid_source_count: 0,
      },
      history_summary: {
        total: 1,
        current: 1,
        historical: 0,
        superseded: 0,
        source_invalid: 0,
        batch_reverted: 0,
      },
    },
    ...overrides,
  };
}

export function multiTimelineWorkspace(): CharacterWorkspaceV2 {
  const base = characterWorkspace();
  const branch = {
    id: "timeline-branch",
    name: "雨夜分支",
    timeline_kind: "branch",
    is_primary: false,
    parent_timeline_id: base.selected_timeline.id,
    fork_story_sequence: 8,
  } as const;
  const branchInstance = {
    ...base.selected_instance,
    id: "instance-branch",
    origin_timeline_id: branch.id,
    continuity_kind: "derived",
    display_label: "雨夜后的林舟",
    derived_from_instance_id: base.selected_instance.id,
    version: 1,
    current_revision_id: "instance-branch-revision-1",
  } as const;
  return characterWorkspace({
    timeline_mode: "multiple",
    selected_timeline: branch,
    selected_instance: branchInstance,
    timelines: [base.selected_timeline, branch],
    instances: [base.selected_instance, branchInstance],
  });
}
