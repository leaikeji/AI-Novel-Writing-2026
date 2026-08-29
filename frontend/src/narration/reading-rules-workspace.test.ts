import { describe, expect, it, vi } from "vitest";

import {
  CAPABILITY_KEYS,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  NARRATION_SETTINGS_SCHEMA_VERSION,
  type FeatureCapability,
  type NarrationAuthorizationState,
  type NarrationCapabilities,
  type NarrationSettingsResource,
} from "./contracts";
import {
  createReadingRulesWorkspace,
  normalizeReadingRulesWorkspaceSection,
  type ReadingRulesWorkspaceProps,
  type ReadingRulesWorkspaceReactRuntime,
} from "./reading-rules-workspace";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
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
  if (Array.isArray(root)) return root.flatMap((item) => findAll(item, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((item) => findAll(item, predicate)),
  ];
}


function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<{ dependencies: readonly unknown[]; cleanup?: () => void } | undefined> = [];
  let pending: Array<{ index: number; effect: () => void | (() => void); dependencies: readonly unknown[] }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const React: ReadingRulesWorkspaceReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      return [states[index] as T, (next) => {
        states[index] = typeof next === "function"
          ? (next as (current: T) => T)(states[index] as T)
          : next;
      }];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      const current = effects[index]?.dependencies;
      if (!current || current.length !== dependencies.length || current.some((item, itemIndex) => !Object.is(item, dependencies[itemIndex]))) {
        pending.push({ index, effect, dependencies: [...dependencies] });
      }
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pending = [];
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const items = pending;
      pending = [];
      items.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
    },
  };
}


const NOVEL_ID = "123e4567-e89b-42d3-a456-426614174000";


function feature(key: typeof CAPABILITY_KEYS[number]): FeatureCapability {
  return {
    key,
    state: "enabled",
    visible: true,
    actionable: true,
    reason_code: null,
    required_gate: null,
  };
}


function capabilities(): NarrationCapabilities {
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: CAPABILITY_KEYS.map(feature),
  };
}


function authorization(): NarrationAuthorizationState {
  return {
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
  };
}


function settings(novelId = NOVEL_ID): NarrationSettingsResource {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_SETTINGS_SCHEMA_VERSION,
    novel_id: novelId,
    settings_id: "223e4567-e89b-42d3-a456-426614174000",
    exists: true,
    version: 3,
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
      timing: { sentence_gap_ms: 220, paragraph_gap_ms: 480, section_gap_ms: 850 },
      casting: {
        anonymous_reuse_scope: "scene",
        same_scene_voice_deduplication: true,
        unknown_speaker_action: "block",
      },
      playback: { playback_rate: 1, volume: 1 },
    },
    updated_at: "2026-08-29T10:00:00Z",
  };
}


function props(input: Partial<ReadingRulesWorkspaceProps> = {}): ReadingRulesWorkspaceProps {
  return {
    novelId: NOVEL_ID,
    settings: settings(),
    capabilities: capabilities(),
    authorization: authorization(),
    pronunciationScopeOptions: [],
    ...input,
  };
}


describe("reading rules workspace", () => {
  it("normalizes legacy subsection intent", () => {
    expect(normalizeReadingRulesWorkspaceSection("pronunciation")).toBe("pronunciation");
    expect(normalizeReadingRulesWorkspaceSection("unknown")).toBe("recognition");
  });

  it("combines recognition and pronunciation in one keyboard-reachable workspace", () => {
    const harness = createReactHarness();
    const Workspace = createReadingRulesWorkspace(harness.React);
    let tree = harness.render(Workspace, props({ initialSection: "pronunciation" }));
    harness.commitEffects();
    tree = harness.render(Workspace, props({ initialSection: "pronunciation" }));
    const nav = findAll(tree, (item) => item.type === "nav")[0]!;
    const buttons = findAll(nav, (item) => item.type === "button");
    expect(buttons).toHaveLength(2);
    expect(buttons.map((item) => [textContent(item), item.props["aria-current"]])).toEqual([
      ["识别与复核", undefined],
      ["发音命中", "page"],
    ]);
    const sections = findAll(tree, (item) => item.props["data-rules-section"] !== undefined);
    expect(sections.map((item) => item.props["data-rules-section"])).toEqual([
      "recognition",
      "pronunciation",
    ]);
    const pronunciationComponent = findAll(
      sections[1],
      (item) => typeof item.type === "function",
    )[0]!;
    expect(pronunciationComponent.props.timing).toEqual(settings().values.timing);
  });

  it("changes the in-page current section without hiding either authoring surface", () => {
    const onSectionChange = vi.fn();
    const harness = createReactHarness();
    const Workspace = createReadingRulesWorkspace(harness.React);
    const workspaceProps = props({ onSectionChange });
    let tree = harness.render(Workspace, workspaceProps);
    harness.commitEffects();
    tree = harness.render(Workspace, workspaceProps);
    const pronunciation = findAll(tree, (item) => item.type === "button" && textContent(item) === "发音命中")[0]!;
    (pronunciation.props.onClick as () => void)();
    tree = harness.render(Workspace, workspaceProps);
    expect(tree.props["data-active-rules-section"]).toBe("pronunciation");
    expect(onSectionChange).toHaveBeenCalledWith("pronunciation");
    expect(findAll(tree, (item) => item.props["data-rules-section"] !== undefined)).toHaveLength(2);
  });

  it("fails closed when settings belong to another novel", () => {
    const harness = createReactHarness();
    const Workspace = createReadingRulesWorkspace(harness.React);
    const tree = harness.render(Workspace, props({
      settings: settings("323e4567-e89b-42d3-a456-426614174000"),
    }));
    expect(textContent(tree)).toContain("已拒绝组合显示");
    expect(findAll(tree, (item) => item.props.role === "alert")).toHaveLength(1);
  });
});
