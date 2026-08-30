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
  buildReadingOverviewModel,
  capabilityStatusText,
  createReadingOverview,
  formatNarrationBytes,
  type ReadingOverviewReactRuntime,
} from "./reading-overview";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


function isFakeElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


const React: ReadingOverviewReactRuntime = {
  createElement(type, props, ...children): FakeElement {
    return {
      type,
      props: (props ?? {}) as Record<string, unknown>,
      children,
    };
  },
};


function findAll(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): readonly FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isFakeElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isFakeElement(root)) return "";
  return root.children.map(textContent).join("");
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";
const ZERO_SHA = "0".repeat(64);


function capability(key: typeof CAPABILITY_KEYS[number]): FeatureCapability {
  const definitions: Readonly<Partial<Record<typeof CAPABILITY_KEYS[number], FeatureCapability>>> = {
    narration_product: {
      key,
      state: "hold",
      visible: true,
      actionable: false,
      reason_code: "T2_GATE_REQUIRED",
      required_gate: "T2-GATE",
    },
    reading_settings: {
      key,
      state: "hold",
      visible: true,
      actionable: false,
      reason_code: "T2_GATE_REQUIRED",
      required_gate: "T2-GATE",
    },
    generic_voice_pool: {
      key,
      state: "unavailable",
      visible: true,
      actionable: false,
      reason_code: "GENERIC_VOICE_ASSETS_UNAVAILABLE",
      required_gate: "T2-E",
    },
    cache_cleanup: {
      key,
      state: "hold",
      visible: true,
      actionable: false,
      reason_code: "T2_GATE_REQUIRED",
      required_gate: "T2-GATE",
    },
    voice_generator: {
      key,
      state: "unavailable",
      visible: false,
      actionable: false,
      reason_code: "VOICE_GENERATOR_NO_GO",
      required_gate: "T5-GATE",
    },
  };
  return definitions[key] ?? {
    key,
    state: "hold",
    visible: false,
    actionable: false,
    reason_code: "T4_GATE_REQUIRED",
    required_gate: "T4-GATE",
  };
}


function overviewFixture(): NarrationOverviewResponse {
  const cleanup = capability("cache_cleanup");
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    capabilities: {
      schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
      items: CAPABILITY_KEYS.map(capability),
    },
    authorization: {
      mode: "fixed_local_owner_workspace",
      can_read: true,
      can_configure: true,
      can_manage_voice_assets: false,
      can_confirm_voice_rights: false,
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
      protocol_version: "1.1",
      model_fingerprint_sha256: null,
      reason_code: "T2_GATE_REQUIRED",
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
          sentence_gap_ms: 250,
          paragraph_gap_ms: 650,
          section_gap_ms: 1_000,
        },
        casting: {
          anonymous_reuse_scope: "scene",
          same_scene_voice_deduplication: true,
          unknown_speaker_action: "block",
        },
        playback: { playback_rate: 1, volume: 0.8 },
      },
      updated_at: null,
    },
    coverage: {
      character_count: 4,
      configured_character_count: 0,
      locked_character_voice_count: 0,
      generic_required_slot_count: 24,
      generic_ready_slot_count: 0,
      pending_review_script_count: 0,
      blocker_count: 0,
      warning_count: 0,
      generated_chapter_count: 0,
      failed_job_count: 0,
    },
    voice_sources: [
      {
        source_type: "preset",
        capability: "preset_voice_source",
        available: false,
        reason_code: "T4_GATE_REQUIRED",
        accepted_mime_types: [],
        maximum_bytes: null,
      },
      {
        source_type: "uploaded",
        capability: "reference_clone",
        available: false,
        reason_code: "T4_GATE_REQUIRED",
        accepted_mime_types: ["audio/wav", "audio/flac"],
        maximum_bytes: 16 * 1024 * 1024,
      },
      {
        source_type: "generated",
        capability: "voice_generator",
        available: false,
        reason_code: "VOICE_GENERATOR_NO_GO",
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
      referenced_edition_bytes: 0,
      derived_cache_bytes: 4096,
      reclaimable_bytes: 2048,
      pending_job_count: 0,
      disk_free_bytes: 5 * 1024 ** 3,
      disk_total_bytes: 10 * 1024 ** 3,
      cleanup_capability: cleanup,
    },
  };
}


describe("reading overview model", () => {
  it("reports only verified server state and keeps the T2 gate explicit", () => {
    const model = buildReadingOverviewModel(overviewFixture());

    expect(model.configurationEmpty).toBe(true);
    expect(model.mutationAllowed).toBe(false);
    expect(model.mutationBlockReason).toContain("T2_GATE_REQUIRED");
    expect(model.runtimeLabel).toBe("未启用");
    expect(model.narratorLabel).toBe("未配置");
    expect(model.characterCoverageLabel).toBe("0 / 4");
  });

  it("formats storage totals without claiming cache cleanup is available", () => {
    expect(formatNarrationBytes(0)).toBe("0 B");
    expect(formatNarrationBytes(1536)).toBe("1.5 KiB");
    expect(buildReadingOverviewModel(overviewFixture()).cacheLabel)
      .toBe("4.0 KiB 派生缓存 · 2.0 KiB 可回收");
    expect(capabilityStatusText(capability("cache_cleanup"))).toContain("T2_GATE_REQUIRED");
  });
});


describe("reading overview surface", () => {
  const Overview = createReadingOverview(React);

  it("renders distinct loading and recoverable error states", () => {
    const loading = Overview({ state: { phase: "loading" } }) as FakeElement;
    const retry = vi.fn();
    const error = Overview({
      state: { phase: "error", message: "暂时无法读取", onRetry: retry },
    }) as FakeElement;

    expect(loading.props["data-reading-state"]).toBe("loading");
    expect(loading.props["aria-busy"]).toBe(true);
    expect(error.props.role).toBe("alert");
    expect(error.props["data-reading-state"]).toBe("error");
    const retryButton = findAll(error, (element) => element.type === "button")[0];
    (retryButton.props.onClick as () => void)();
    expect(retry).toHaveBeenCalledOnce();
  });

  it("renders the empty gated state and disables every mutation shortcut", () => {
    const onNavigate = vi.fn();
    const tree = Overview({
      state: { phase: "ready", overview: overviewFixture(), onNavigate },
    }) as FakeElement;

    expect(tree.props["data-reading-state"]).toBe("gated");
    expect(findAll(tree, (element) => element.props["data-reading-empty"] === "true"))
      .toHaveLength(1);
    const buttons = findAll(tree, (element) => element.type === "button");
    expect(buttons).toHaveLength(3);
    expect(buttons.every((button) => button.props.disabled === true)).toBe(true);
    expect(textContent(tree)).toContain("等待声音设置阶段门禁通过（T2_GATE_REQUIRED）");
    expect(textContent(tree)).toContain("18 个官方音色");
    expect(textContent(tree)).not.toContain("有明确授权且已锁定");
    expect(textContent(tree)).not.toContain("文字生成音色");
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("enables configuration navigation only when both product gates are actionable", () => {
    const base = overviewFixture();
    const enabledKeys = new Set(["narration_product", "reading_settings"]);
    const enabled = {
      ...base,
      capabilities: {
        ...base.capabilities,
        items: base.capabilities.items.map((item): FeatureCapability => enabledKeys.has(item.key)
          ? {
            key: item.key,
            state: "enabled",
            visible: true,
            actionable: true,
            reason_code: null,
            required_gate: null,
          }
          : item),
      },
    } satisfies NarrationOverviewResponse;
    const onNavigate = vi.fn();
    const tree = Overview({ state: { phase: "ready", overview: enabled, onNavigate } }) as FakeElement;
    const configure = findAll(tree, (element) => element.type === "button"
      && textContent(element) === "配置旁白")[0];

    expect(tree.props["data-reading-state"]).toBe("empty");
    expect(configure.props.disabled).toBe(false);
    (configure.props.onClick as () => void)();
    expect(onNavigate).toHaveBeenCalledWith("narrator");
  });
});
