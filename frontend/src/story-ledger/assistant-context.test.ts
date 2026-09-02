import { describe, expect, it } from "vitest";

import type {
  StoryLedgerFactDetail,
  StoryLedgerSourceExcerpt,
  StoryLedgerSummary,
} from "./contracts";
import {
  buildStoryLedgerAssistantContext,
  buildStoryLedgerAssistantContextFromWorkspace,
  STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS,
  validateStoryLedgerAssistantContext,
} from "./assistant-context";

const timeline = {
  mode: "single",
  timeline_id: "timeline-1",
  timeline_name: "主线",
  narrative_cutoff: 8,
} as const;

const item = {
  id: "fact-1",
  fact_type: "character_state",
  subject: "林舟",
  predicate: "位置",
  object_preview: "灯塔",
  object_truncated: false,
  timeline_id: "timeline-1",
  dimension: "location",
  event_kind: "state",
  story_sequence: 8,
  created_at: "2026-09-02T00:00:00Z",
  effective_state: "current",
  effective_reason_codes: ["projection_current"],
  included_in_current_projection: true,
  health: "ok",
  health_reason_codes: [],
  entities: [{
    entity_type: "character",
    entity_id: "character-1",
    label: "林舟",
    lifecycle_state: "active",
    reference_missing: false,
  }],
  source: {
    source_document_id: "document-1",
    document_title: "第一章",
    document_position: 1,
    source_revision_id: "revision-1",
    revision_number: 2,
    revision_is_current: true,
    source_content_hash: "a".repeat(64),
    source_start: 4,
    source_end: 6,
    binding_state: "current",
    commit_batch_id: null,
    evidence_available: true,
  },
} as const;

const summary: StoryLedgerSummary = {
  schema_version: "story-ledger-summary/1",
  novel_id: "novel-1",
  ledger_snapshot_token: "snapshot-1",
  story_ledger_version: 9,
  timeline,
  filter_sha256: "b".repeat(64),
  total: 1,
  by_fact_type: { character_state: 1 },
  by_effective_state: { current: 1 },
  by_health: { ok: 1 },
  review_required: 0,
};

const detail: StoryLedgerFactDetail = {
  schema_version: "story-ledger-fact-detail/1",
  novel_id: "novel-1",
  ledger_snapshot_token: "snapshot-1",
  story_ledger_version: 9,
  timeline,
  item,
  object_text: "灯塔",
  details: { private_note: "不得进入上下文" },
  story_time: null,
  visibility: { hidden: true },
  lifecycle_status: "active",
  schema_version_of_fact: "story-fact/2",
  event_fingerprint: null,
  event_links: [],
  bindings: [],
};

const source: StoryLedgerSourceExcerpt = {
  schema_version: "story-ledger-source/1",
  novel_id: "novel-1",
  fact_id: "fact-1",
  ledger_snapshot_token: "snapshot-1",
  story_ledger_version: 9,
  timeline,
  available: true,
  unavailable_reason: null,
  document_id: "document-1",
  document_title: "第一章",
  document_position: 1,
  revision_id: "revision-1",
  revision_number: 2,
  revision_is_current: true,
  source_content_hash: "a".repeat(64),
  source_range_hash: "c".repeat(64),
  source_start: 4,
  source_end: 6,
  excerpt: "绝不能进入 assistant context 的完整来源摘录",
  excerpt_start: 0,
  excerpt_end: 20,
  highlight_start: 4,
  highlight_end: 6,
  truncated_before: false,
  truncated_after: true,
};

describe("story ledger assistant context", () => {
  it("emits only the frozen whitelist and excludes source/detail payloads", () => {
    const context = buildStoryLedgerAssistantContext({
      novel: { id: "novel-1", title: "潮声" },
      snapshotToken: "snapshot-1",
      timeline,
      filters: { factTypes: ["character_state"], health: "ok" },
      summary,
      selectedDetail: detail,
      selectedSource: source,
    });
    const serialized = JSON.stringify(context);

    expect(validateStoryLedgerAssistantContext(context)).toBe(true);
    expect(context.schema_version).toBe("story-ledger-assistant-context/1");
    expect(context.selected_fact?.source?.range_hash).toBe("c".repeat(64));
    expect(serialized).not.toContain("source_excerpt");
    expect(serialized).not.toContain(source.excerpt);
    expect(serialized).not.toContain("private_note");
    expect(serialized).not.toContain("visibility");
    expect([...serialized].length).toBeLessThanOrEqual(
      STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS,
    );
  });

  it("bounds an oversized selected fact by Unicode code points", () => {
    const context = buildStoryLedgerAssistantContext({
      novel: { id: "novel-1", title: "潮声" },
      snapshotToken: "snapshot-1",
      timeline,
      filters: {},
      summary,
      selectedDetail: { ...detail, object_text: "😀".repeat(20_000) },
    });
    expect(context.selected_fact?.object_text_truncated).toBe(true);
    expect(context.budget.truncated).toBe(true);
    expect(context.budget.used_code_points).toBe([...JSON.stringify(context)].length);
    expect(context.budget.used_code_points).toBeLessThanOrEqual(6_000);
  });

  it("rejects an added excerpt field even when the object is otherwise valid", () => {
    const context = buildStoryLedgerAssistantContext({
      novel: { id: "novel-1", title: "潮声" },
      snapshotToken: "snapshot-1",
      timeline,
      filters: {},
      summary,
    });
    expect(validateStoryLedgerAssistantContext({ ...context, source_excerpt: "泄漏" }))
      .toBe(false);
  });

  it("builds the runtime envelope from body-free workspace metadata only", () => {
    const context = buildStoryLedgerAssistantContextFromWorkspace({
      novel: { id: "novel-1", title: "潮声" },
      context: {
        snapshotToken: "snapshot-1",
        timeline,
        filters: { factTypes: ["character_state"], reviewOnly: true },
        summary,
        selectedFactId: "fact-1",
        selected: {
          factId: "fact-1",
          factType: "character_state",
          timelineId: "timeline-1",
          dimension: "location",
          eventKind: "state",
          effectiveState: "current",
          health: "ok",
          source: {
            source_document_id: "document-1",
            document_title: "第一章",
            document_position: 1,
            source_revision_id: "revision-1",
            revision_number: 2,
            revision_is_current: true,
            binding_state: "current",
            commit_batch_id: null,
            evidence_available: true,
          },
        },
      },
    });
    const serialized = JSON.stringify(context);

    expect(context?.selected_fact).toMatchObject({
      id: "fact-1",
      fact_type: "character_state",
      object_text: "",
      predicate: "",
      source: {
        document_id: "document-1",
        revision_id: "revision-1",
        source_start: null,
        source_end: null,
      },
    });
    expect(context?.selected_fact_id).toBe("fact-1");
    expect(serialized).not.toContain("完整事实内容");
    expect(serialized).not.toContain("source_excerpt");
    expect(validateStoryLedgerAssistantContext(context)).toBe(true);
  });

  it("does not publish a workspace envelope across mismatched snapshots", () => {
    expect(buildStoryLedgerAssistantContextFromWorkspace({
      novel: { id: "novel-1", title: "潮声" },
      context: {
        snapshotToken: "snapshot-stale",
        timeline,
        filters: {},
        summary,
        selectedFactId: null,
        selected: null,
      },
    })).toBeNull();
  });

  it("publishes only the selected id while deep-linked detail metadata is loading", () => {
    const context = buildStoryLedgerAssistantContextFromWorkspace({
      novel: { id: "novel-1", title: "潮声" },
      context: {
        snapshotToken: "snapshot-1",
        timeline,
        filters: {},
        summary,
        selectedFactId: "fact-loading",
        selected: null,
      },
    });

    expect(context?.selected_fact_id).toBe("fact-loading");
    expect(context?.selected_fact).toBeNull();
    expect(validateStoryLedgerAssistantContext(context)).toBe(true);
  });
});
