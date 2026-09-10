import type { StoryLedgerAssistantContextV1 } from "./assistant-context";

/** Static legacy wire example for validator tests; never imported by product code. */
const LEGACY_LEDGER_CONTEXT: StoryLedgerAssistantContextV1 = {
  "schema_version": "story-ledger-assistant-context/1",
  "novel": {
    "id": "novel-1",
    "title": "潮声替我说晚安"
  },
  "ledger_snapshot_token": "ledger-snapshot/1:novel-1:9",
  "timeline": {
    "id": "timeline-1",
    "name": "主线"
  },
  "filters": {
    "fact_types": [
      "character_state"
    ],
    "effective_state": null,
    "health": null,
    "dimension": null,
    "source_document_id": null,
    "commit_batch_id": null,
    "fact_timeline_id": null,
    "entity_type": null,
    "entity_id": null,
    "review_only": true
  },
  "summary": {
    "total": 2,
    "review_required": 1,
    "by_fact_type": {
      "character_state": 2
    },
    "by_effective_state": {
      "current": 1,
      "superseded": 1
    },
    "by_health": {
      "conflict": 1,
      "ok": 1
    }
  },
  "selected_fact_id": "fact-1",
  "selected_fact": {
    "id": "fact-1",
    "fact_type": "character_state",
    "entity_labels": [
      "林舟"
    ],
    "predicate": "位置",
    "object_text": "灯塔",
    "object_text_truncated": false,
    "effective_state": "current",
    "health": "ok",
    "effective_reason_codes": [
      "projection_current"
    ],
    "health_reason_codes": [],
    "source": {
      "document_id": "document-1",
      "document_title": "第一章",
      "revision_id": "revision-1",
      "revision_is_current": true,
      "coordinate_version": "unicode-codepoint-v1",
      "source_start": 4,
      "source_end": 6,
      "range_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    }
  },
  "budget": {
    "max_code_points": 6000,
    "used_code_points": 1224,
    "truncated": false
  }
};

export function legacyLedgerContextFixture(): StoryLedgerAssistantContextV1 {
  return structuredClone(LEGACY_LEDGER_CONTEXT);
}

/** Keep negative fixtures otherwise valid so schema failures are not budget failures. */
export function accountLegacyLedgerFixtureBudget<T extends Pick<StoryLedgerAssistantContextV1, "budget">>(value: T): T {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const used = [...JSON.stringify(value)].length;
    if (used === value.budget.used_code_points) break;
    value.budget.used_code_points = used;
  }
  return value;
}
