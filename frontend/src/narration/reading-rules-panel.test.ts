import { describe, expect, it, vi } from "vitest";

import { NarrationApiError } from "./api";
import {
  CAPABILITY_KEYS,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type FeatureCapability,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type NarrationCloudConsent,
  type NarrationSettingsResource,
} from "./contracts";
import {
  NARRATION_CLOUD_CONSENT_NOTICE_VERSION,
  NARRATION_CLOUD_DATA_SCOPE,
  buildReadingRulesPanelModel,
  buildReadingRulesSettingsRequest,
  classifyReadingRulesFailure,
  createReadingRulesPanel,
  isNarrationCloudConsentUsable,
  readingRulesDraftFromSettings,
  type ReadingRulesPanelApi,
  type ReadingRulesPanelProps,
  type ReadingRulesReactRuntime,
} from "./reading-rules-panel";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  readonly dependencies: readonly unknown[];
  cleanup?: () => void;
}


function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(
    root,
    (element) => element.type === "button" && textContent(element) === label,
  )[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}


function findInput(root: unknown, value: string): FakeElement {
  const input = findAll(
    root,
    (element) => element.type === "input" && element.props.value === value,
  )[0];
  if (!input) throw new Error(`input not found: ${value}`);
  return input;
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pendingEffects: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;

  const React: ReadingRulesReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
      return [
        states[index] as T,
        (next) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        },
      ];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
      pendingEffects.push({ index, effect, dependencies: [...dependencies] });
    },
  };

  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const pending = pendingEffects;
      pendingEffects = [];
      pending.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
    },
    unmount(): void {
      effects.forEach((effect) => effect?.cleanup?.());
    },
  };
}


async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";
const OTHER_NOVEL_ID = "223e4567-e89b-42d3-a456-426614174000";
const CONSENT_ID = "323e4567-e89b-42d3-a456-426614174000";


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
    visible: ["narration_product", "reading_settings", "cloud_assisted_analysis"].includes(key),
    actionable: false,
    reason_code: key === "cloud_assisted_analysis"
      ? "CLOUD_CONSENT_FLOW_NOT_READY"
      : "T2_GATE_REQUIRED",
    required_gate: "T2-GATE",
  };
}


function capabilities(...enabledKeys: readonly string[]): NarrationCapabilities {
  const enabled = new Set(enabledKeys);
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map((key) => feature(key, enabled)),
  };
}


function emptyConsent(): NarrationCloudConsent {
  return {
    consent_id: null,
    version: 0,
    state: "not_granted",
    purpose: "narration_speaker_analysis",
    data_scope: NARRATION_CLOUD_DATA_SCOPE,
    notice_version: null,
    provider_id: null,
    model_id: null,
    confirmed_at: null,
    revoked_at: null,
  };
}


function activeConsent(
  noticeVersion = NARRATION_CLOUD_CONSENT_NOTICE_VERSION,
): NarrationCloudConsent {
  return {
    consent_id: CONSENT_ID,
    version: 1,
    state: "active",
    purpose: "narration_speaker_analysis",
    data_scope: NARRATION_CLOUD_DATA_SCOPE,
    notice_version: noticeVersion,
    provider_id: null,
    model_id: null,
    confirmed_at: "2026-08-26T09:00:00Z",
    revoked_at: null,
  };
}


function revokedConsent(): NarrationCloudConsent {
  return {
    ...activeConsent(),
    version: 2,
    state: "revoked",
    revoked_at: "2026-08-26T09:05:00Z",
  };
}


function authorization(consent: NarrationCloudConsent = emptyConsent()): NarrationAuthorizationState {
  return {
    mode: "fixed_local_owner_workspace",
    can_read: true,
    can_configure: true,
    can_manage_voice_assets: true,
    can_confirm_voice_rights: true,
    cloud_consent: consent,
  };
}


function settings(input: {
  readonly novelId?: string;
  readonly version?: number;
  readonly policy?: "blockers_only" | "always_review";
  readonly analysisMode?: "local_rules_only" | "cloud_assisted";
} = {}): NarrationSettingsResource {
  const version = input.version ?? 3;
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: input.novelId ?? NOVEL_ID,
    settings_id: "423e4567-e89b-42d3-a456-426614174000",
    exists: true,
    version,
    values: {
      narrator: null,
      language: "zh-CN",
      output_format: "m4a_aac_lc",
      script_review_policy: input.policy ?? "blockers_only",
      analysis_mode: input.analysisMode ?? "local_rules_only",
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
    updated_at: "2026-08-26T09:00:00Z",
  };
}


function api(overrides: Partial<ReadingRulesPanelApi> = {}): ReadingRulesPanelApi {
  return {
    putSettings: async () => { throw new Error("unexpected putSettings"); },
    createCloudConsent: async () => { throw new Error("unexpected createCloudConsent"); },
    revokeCloudConsent: async () => { throw new Error("unexpected revokeCloudConsent"); },
    ...overrides,
  };
}


function props(input: Partial<ReadingRulesPanelProps> = {}): ReadingRulesPanelProps {
  return {
    novelId: NOVEL_ID,
    settings: settings(),
    capabilities: capabilities("narration_product", "reading_settings"),
    authorization: authorization(),
    ...input,
  };
}


describe("reading rules model", () => {
  it("requires the product and settings gates before draft controls become editable", () => {
    const resource = settings();
    const saved = readingRulesDraftFromSettings(resource);
    const model = buildReadingRulesPanelModel({
      draft: { ...saved, scriptReviewPolicy: "always_review" },
      saved,
      capabilities: capabilities("reading_settings"),
      authorization: authorization(),
      consent: emptyConsent(),
      busy: false,
      consentConfirmed: false,
    });
    expect(model.canRead).toBe(true);
    expect(model.canEditSettings).toBe(false);
    expect(model.canSave).toBe(false);
    expect(model.productReason).toBe("T2_GATE_REQUIRED");
  });

  it("treats only the current frozen notice as usable cloud consent", () => {
    expect(isNarrationCloudConsentUsable(activeConsent())).toBe(true);
    expect(isNarrationCloudConsentUsable(activeConsent("narration-cloud-consent/0"))).toBe(false);
    expect(isNarrationCloudConsentUsable(revokedConsent())).toBe(false);
  });

  it("builds a complete replacement request without dropping unrelated settings", () => {
    const resource = settings();
    const request = buildReadingRulesSettingsRequest(resource, {
      scriptReviewPolicy: "always_review",
      analysisMode: "local_rules_only",
    });
    expect(request.expected_version).toBe(3);
    expect(request.values).toEqual({
      ...resource.values,
      script_review_policy: "always_review",
      analysis_mode: "local_rules_only",
    });
  });

  it("classifies conflict, cancellation and network failures without private input", () => {
    const conflict = classifyReadingRulesFailure(new NarrationApiError(409, {
      contract_version: NARRATION_SETTINGS_API_VERSION,
      code: "VERSION_CONFLICT",
      message: "server detail",
      retryable: false,
      field: null,
      current_version: 4,
      capability: null,
    }));
    expect(conflict.refreshRequired).toBe(true);
    expect(conflict.message).not.toContain("server detail");
    expect(classifyReadingRulesFailure({ name: "AbortError" }).code).toBe("CANCELLED");
    expect(classifyReadingRulesFailure(new TypeError("offline")).code).toBe("NETWORK_ERROR");
  });
});


describe("reading rules surface", () => {
  it("disables all settings fields when the global product gate is held", () => {
    const harness = createReactHarness();
    const Panel = createReadingRulesPanel(harness.React, api());
    let tree = harness.render(Panel, props({
      capabilities: capabilities("reading_settings", "cloud_assisted_analysis"),
    }));
    harness.commitEffects();
    tree = harness.render(Panel, props({
      capabilities: capabilities("reading_settings", "cloud_assisted_analysis"),
    }));
    const fieldsets = findAll(tree, (element) => element.type === "fieldset");
    expect(fieldsets).toHaveLength(2);
    expect(fieldsets.every((element) => element.props.disabled === true)).toBe(true);
    expect(findButton(tree, "保存识别与复核规则").props.disabled).toBe(true);
    expect(textContent(tree)).toContain("当前只读：T2_GATE_REQUIRED");
  });

  it("saves one full CAS replacement and applies only the same novel response", async () => {
    const saved = settings();
    const response = settings({ version: 4, policy: "always_review" });
    const putSettings = vi.fn(async () => response);
    const onSettingsSaved = vi.fn();
    const harness = createReactHarness();
    const Panel = createReadingRulesPanel(harness.React, api({ putSettings }));
    const panelProps = props({ settings: saved, onSettingsSaved });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    (findInput(tree, "always_review").props.onChange as (event: unknown) => void)({
      target: { value: "always_review", checked: true },
    });
    tree = harness.render(Panel, panelProps);
    const save = findButton(tree, "保存识别与复核规则");
    expect(save.props.disabled).toBe(false);
    (save.props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);

    expect(putSettings).toHaveBeenCalledWith(
      NOVEL_ID,
      {
        expected_version: 3,
        values: { ...saved.values, script_review_policy: "always_review" },
      },
      expect.any(AbortSignal),
    );
    expect(onSettingsSaved).toHaveBeenCalledWith(response);
    expect(textContent(tree)).toContain("已保存");
  });

  it("reuses one idempotency key across a network retry and verifies the receipt", async () => {
    const createCloudConsent = vi.fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(activeConsent());
    const createIdempotencyKey = vi.fn(() => "cloud:test-key-0001");
    const onConsentChanged = vi.fn();
    const harness = createReactHarness();
    const Panel = createReadingRulesPanel(harness.React, api({ createCloudConsent }));
    const panelProps = props({
      capabilities: capabilities(
        "narration_product",
        "reading_settings",
        "cloud_assisted_analysis",
      ),
      createIdempotencyKey,
      onConsentChanged,
    });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const checkbox = findAll(
      tree,
      (element) => element.type === "input" && element.props.type === "checkbox",
    )[0];
    (checkbox.props.onChange as (event: unknown) => void)({ target: { checked: true, value: "" } });
    tree = harness.render(Panel, panelProps);
    (findButton(tree, "确认作品级授权").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);
    expect(textContent(tree)).toContain("连接失败");
    (findButton(tree, "确认作品级授权").props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);

    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(createCloudConsent).toHaveBeenCalledTimes(2);
    expect(createCloudConsent.mock.calls.map((call) => call[2])).toEqual([
      "cloud:test-key-0001",
      "cloud:test-key-0001",
    ]);
    expect(createCloudConsent.mock.calls[0][1]).toEqual({
      notice_version: NARRATION_CLOUD_CONSENT_NOTICE_VERSION,
      data_scope: NARRATION_CLOUD_DATA_SCOPE,
      provider_id: null,
      model_id: null,
      confirmed: true,
    });
    expect(onConsentChanged).toHaveBeenCalledWith(activeConsent());
    expect(textContent(tree)).toContain("授权已记录");
  });

  it("allows explicit withdrawal while cloud capability is held and prepares local mode", async () => {
    const revokeCloudConsent = vi.fn(async () => revokedConsent());
    const harness = createReactHarness();
    const Panel = createReadingRulesPanel(harness.React, api({ revokeCloudConsent }));
    const panelProps = props({
      settings: settings({ analysisMode: "cloud_assisted" }),
      authorization: authorization(activeConsent()),
      capabilities: capabilities("narration_product", "reading_settings"),
    });
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    const revoke = findButton(tree, "撤销云端授权");
    expect(revoke.props.disabled).toBe(false);
    (revoke.props.onClick as () => void)();
    await settle();
    tree = harness.render(Panel, panelProps);

    expect(revokeCloudConsent).toHaveBeenCalledWith(
      NOVEL_ID,
      { consent_id: CONSENT_ID, expected_version: 1 },
      expect.any(AbortSignal),
    );
    expect(findInput(tree, "local_rules_only").props.checked).toBe(true);
    expect(findButton(tree, "保存识别与复核规则").props.disabled).toBe(false);
    expect(textContent(tree)).toContain("后续分析不会外发");
  });

  it("fails closed for stale notice and mixed-novel settings", () => {
    const staleHarness = createReactHarness();
    const StalePanel = createReadingRulesPanel(staleHarness.React, api());
    const staleProps = props({
      settings: settings({ analysisMode: "cloud_assisted" }),
      authorization: authorization(activeConsent("narration-cloud-consent/0")),
      capabilities: capabilities(
        "narration_product",
        "reading_settings",
        "cloud_assisted_analysis",
      ),
    });
    let stale = staleHarness.render(StalePanel, staleProps);
    staleHarness.commitEffects();
    stale = staleHarness.render(StalePanel, staleProps);
    expect(findInput(stale, "local_rules_only").props.checked).toBe(true);
    expect(textContent(stale)).toContain("授权记录需重新确认");
    expect(textContent(stale)).toContain("已准备切回本地模式");

    const driftHarness = createReactHarness();
    const DriftPanel = createReadingRulesPanel(driftHarness.React, api());
    const drifted = driftHarness.render(DriftPanel, props({
      settings: settings({ novelId: OTHER_NOVEL_ID }),
    }));
    expect(textContent(drifted)).toContain("已拒绝显示");
    expect(findAll(drifted, (element) => element.props.role === "alert")).toHaveLength(1);
  });

  it("aborts an in-flight write on unmount", () => {
    let observedSignal: AbortSignal | undefined;
    const putSettings = vi.fn((_novelId, _payload, signal?: AbortSignal) => {
      observedSignal = signal;
      return new Promise<NarrationSettingsResource>(() => undefined);
    });
    const harness = createReactHarness();
    const Panel = createReadingRulesPanel(harness.React, api({ putSettings }));
    const panelProps = props();
    let tree = harness.render(Panel, panelProps);
    harness.commitEffects();
    tree = harness.render(Panel, panelProps);
    (findInput(tree, "always_review").props.onChange as (event: unknown) => void)({
      target: { value: "always_review", checked: true },
    });
    tree = harness.render(Panel, panelProps);
    (findButton(tree, "保存识别与复核规则").props.onClick as () => void)();
    expect(observedSignal?.aborted).toBe(false);
    harness.unmount();
    expect(observedSignal?.aborted).toBe(true);
  });
});
