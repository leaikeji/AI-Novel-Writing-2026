import { describe, expect, it, vi } from "vitest";

import {
  CAPABILITY_KEYS,
  NARRATION_CACHE_SCHEMA_VERSION,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type FeatureCapability,
  type NarrationOverviewResponse,
} from "./contracts";
import {
  buildReadingStatusModel,
  createReadingStatus,
  formatNarrationBytes,
  type ReadingStatusReactRuntime,
} from "./reading-status";
import { T2_G_NARRATION_READING_RULES_STYLES } from "./styles/t2-g";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


const React: ReadingStatusReactRuntime = {
  createElement(type, props, ...children): FakeElement {
    return { type, props: props ?? {}, children };
  },
};


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";
const OTHER_NOVEL_ID = "223e4567-e89b-42d3-a456-426614174000";
const ZERO_SHA = "0".repeat(64);


function feature(
  key: typeof CAPABILITY_KEYS[number],
  enabled: ReadonlySet<string>,
): FeatureCapability {
  if (enabled.has(key)) {
    return {
      key,
      state: "enabled",
      visible: true,
      actionable: true,
      reason_code: null,
      required_gate: null,
    };
  }
  return {
    key,
    state: "hold",
    visible: [
      "narration_product",
      "reading_settings",
      "cache_cleanup",
    ].includes(key),
    actionable: false,
    reason_code: key === "generic_voice_pool"
      ? "GENERIC_VOICE_ASSETS_UNAVAILABLE"
      : "T2_GATE_REQUIRED",
    required_gate: "T2-GATE",
  };
}


function overviewFixture(
  enabledKeys: readonly string[] = [],
): NarrationOverviewResponse {
  const enabled = new Set(enabledKeys);
  const cleanup = feature("cache_cleanup", enabled);
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    capabilities: {
      schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
      items: CAPABILITY_KEYS.map((key) => feature(key, enabled)),
    },
    authorization: {
      mode: "fixed_local_owner_workspace",
      can_read: true,
      can_configure: true,
      can_manage_voice_assets: true,
      can_confirm_voice_rights: true,
      cloud_consent: {
        consent_id: null,
        version: 0,
        state: "not_granted",
        purpose: "narration_speaker_analysis",
        data_scope: "uncertain_segments_with_minimal_context",
        notice_version: null,
        provider_id: null,
        model_id: null,
        confirmed_at: null,
        revoked_at: null,
      },
    },
    runtime: {
      technical_enabled: false,
      lifecycle_status: "disabled",
      sidecar_reachable: false,
      model_ready: false,
      product_visible: false,
      protocol_version: "moss-tts-sidecar/1.1",
      model_fingerprint_sha256: null,
      reason_code: "TTS_RUNTIME_DISABLED",
    },
    settings: {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
      novel_id: NOVEL_ID,
      settings_id: null,
      exists: false,
      version: 0,
      values: {
        narrator: null,
        language: "zh-CN",
        output_format: "m4a_aac_lc",
        script_review_policy: "blockers_only",
        analysis_mode: "local_rules_only",
        text_rules: {
          read_chapter_title: true,
          read_author_notes: false,
          read_section_breaks: false,
          first_person_mode: "narrator",
          first_person_character_id: null,
          inner_monologue_mode: "character",
        },
        timing: {
          sentence_gap_ms: 220,
          paragraph_gap_ms: 480,
          section_gap_ms: 850,
        },
        casting: {
          anonymous_reuse_scope: "scene",
          same_scene_voice_deduplication: true,
          unknown_speaker_action: "block",
        },
        playback: { playback_rate: 1, volume: 1 },
      },
      updated_at: null,
    },
    coverage: {
      character_count: 3,
      configured_character_count: 1,
      locked_character_voice_count: 1,
      generic_required_slot_count: 24,
      generic_ready_slot_count: 0,
      pending_review_script_count: 2,
      blocker_count: 1,
      warning_count: 2,
      generated_chapter_count: 4,
      failed_job_count: 1,
    },
    voice_sources: [
      {
        source_type: "preset",
        capability: "preset_voice_source",
        available: false,
        reason_code: "T2_GATE_REQUIRED",
        accepted_mime_types: [],
        maximum_bytes: null,
      },
      {
        source_type: "uploaded",
        capability: "reference_clone",
        available: false,
        reason_code: "T2_GATE_REQUIRED",
        accepted_mime_types: ["audio/wav", "audio/flac"],
        maximum_bytes: 16 * 1024 * 1024,
      },
      {
        source_type: "generated",
        capability: "voice_generator",
        available: false,
        reason_code: "T2_GATE_REQUIRED",
        accepted_mime_types: [],
        maximum_bytes: null,
      },
    ],
    cache: {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      schema_version: NARRATION_CACHE_SCHEMA_VERSION,
      novel_id: NOVEL_ID,
      snapshot_fingerprint: ZERO_SHA,
      source_asset_bytes: 1024,
      locked_voice_bytes: 2048,
      referenced_edition_bytes: 4096,
      derived_cache_bytes: 8192,
      reclaimable_bytes: 3072,
      pending_job_count: 2,
      disk_free_bytes: 5 * 1024 ** 3,
      disk_total_bytes: 10 * 1024 ** 3,
      cleanup_capability: cleanup,
    },
  };
}


describe("reading status model", () => {
  it("formats bounded byte values without accepting unsafe input", () => {
    expect(formatNarrationBytes(0)).toBe("0 B");
    expect(formatNarrationBytes(1024)).toBe("1.00 KiB");
    expect(formatNarrationBytes(5 * 1024 ** 3)).toBe("5.00 GiB");
    expect(formatNarrationBytes(-1)).toBe("不可用");
    expect(formatNarrationBytes(Number.MAX_SAFE_INTEGER + 1)).toBe("不可用");
  });

  it("reports current product holds, runtime, cache and failed jobs from server evidence", () => {
    const model = buildReadingStatusModel(overviewFixture());
    expect(model.runtimeReady).toBe(false);
    expect(model.runtimeLabel).toBe("本地 TTS 未启用");
    expect(model.diskPercentFree).toBe(50);
    expect(model.characterCoverageLabel).toBe("1/3");
    expect(model.issues.map((issue) => issue.code)).toEqual([
      "T2_GATE_REQUIRED",
      "TTS_RUNTIME_DISABLED",
      "T2_GATE_REQUIRED",
      "NARRATION_JOBS_FAILED",
    ]);
  });

  it("accepts a fully evidenced ready projection and flags revoked cloud mode", () => {
    const base = overviewFixture([
      "narration_product",
      "reading_settings",
      "cache_cleanup",
    ]);
    const ready: NarrationOverviewResponse = {
      ...base,
      runtime: {
        ...base.runtime,
        technical_enabled: true,
        lifecycle_status: "ready",
        sidecar_reachable: true,
        model_ready: true,
        product_visible: true,
        model_fingerprint_sha256: "a".repeat(64),
        reason_code: null,
      },
      coverage: { ...base.coverage, failed_job_count: 0 },
    };
    expect(buildReadingStatusModel(ready).issues).toEqual([]);

    const revokedCloud: NarrationOverviewResponse = {
      ...ready,
      settings: {
        ...ready.settings,
        values: { ...ready.settings.values, analysis_mode: "cloud_assisted" },
      },
    };
    expect(buildReadingStatusModel(revokedCloud).issues.map((issue) => issue.code))
      .toContain("CLOUD_CONSENT_REQUIRED");
  });

  it("rejects an aggregate containing another novel's child resource", () => {
    const source = overviewFixture();
    const drifted: NarrationOverviewResponse = {
      ...source,
      cache: { ...source.cache, novel_id: OTHER_NOVEL_ID },
    };
    expect(() => buildReadingStatusModel(drifted)).toThrow(/scope mismatch/);
  });
});


describe("reading status surface", () => {
  const Status = createReadingStatus(React);

  it("renders named regions and routes actionable issues to their section", () => {
    const onOpenSection = vi.fn();
    const tree = Status({ overview: overviewFixture(), onOpenSection }) as FakeElement;
    expect(tree.props["aria-labelledby"]).toBe("anw-reading-status-title");
    expect(tree.props["data-runtime-ready"]).toBe("false");
    expect(textContent(tree)).toContain("状态只反映真实后端证据");
    expect(textContent(tree)).not.toContain("通用音色");
    const buttons = findAll(tree, (element) => element.type === "button");
    expect(buttons.length).toBeGreaterThan(0);
    (buttons[0].props.onClick as () => void)();
    expect(onOpenSection).toHaveBeenCalledWith(expect.any(String));
  });

  it("fails closed instead of rendering mixed-novel status", () => {
    const source = overviewFixture();
    const drifted: NarrationOverviewResponse = {
      ...source,
      settings: { ...source.settings, novel_id: OTHER_NOVEL_ID },
    };
    const tree = Status({ overview: drifted }) as FakeElement;
    expect(findAll(tree, (element) => element.props.role === "alert")).toHaveLength(1);
    expect(textContent(tree)).toContain("已拒绝显示");
  });

  it("keeps styles scoped, responsive and keyboard-visible", () => {
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain(".anw-reading-rules-panel");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain(".anw-reading-status");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain(":focus-visible");
    expect(T2_G_NARRATION_READING_RULES_STYLES).toContain("@media (max-width: 560px)");
    expect(T2_G_NARRATION_READING_RULES_STYLES).not.toMatch(/(^|\n)\s*(button|input|section)\s*\{/);
  });
});
