import { describe, expect, it, vi } from "vitest";

import {
  createVoiceLifecyclePanel,
  type VoiceLifecyclePanelProps,
  type VoiceLifecycleReactRuntime,
} from "./voice-lifecycle-panel";
import {
  PRIVATE_VOICE_DELETION_CONTRACT_VERSION,
  PRIVATE_VOICE_DELETION_IMPACT_VERSION,
  type PrivateVoiceDeletionRequestState,
  type VoiceDeletionRequestSnapshot,
  type VoiceLifecycleProfile,
} from "./voice-lifecycle-state";
import {
  VOICE_LIFECYCLE_STYLE_ID,
  VOICE_LIFECYCLE_STYLES,
} from "./styles/voice-lifecycle";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  readonly dependencies: readonly unknown[];
  readonly cleanup?: () => void;
}


function isElement(value: unknown): value is FakeElement {
  return value !== null
    && typeof value === "object"
    && "type" in value
    && "props" in value
    && "children" in value;
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


function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(root, (element) => (
    element.type === "button" && textContent(element) === label
  ))[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createHarness() {
  const states: unknown[] = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pending: Array<{
    readonly index: number;
    readonly effect: () => void | (() => void);
    readonly dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let effectIndex = 0;
  const React: VoiceLifecycleReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)) {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
      return [states[index] as T, (next: T | ((current: T) => T)) => {
        states[index] = typeof next === "function"
          ? (next as (current: T) => T)(states[index] as T)
          : next;
      }];
    },
    useEffect(effect, dependencies) {
      const index = effectIndex++;
      if (!sameDependencies(effects[index]?.dependencies, dependencies)) {
        pending.push({ index, effect, dependencies: [...dependencies] });
      }
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): unknown {
      stateIndex = 0;
      effectIndex = 0;
      pending = [];
      const tree = Component(props);
      const scheduled = pending;
      pending = [];
      for (const item of scheduled) {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      }
      return tree;
    },
  };
}


const PROFILE_ID = "10000000-0000-4000-8000-000000000001";
const NOVEL_ID = "20000000-0000-4000-8000-000000000001";
const REQUEST_ID = "30000000-0000-4000-8000-000000000001";
const NOW = Date.parse("2026-08-29T10:00:00.000Z");


function profile(eligibility: VoiceLifecycleProfile["eligibility"]): VoiceLifecycleProfile {
  return {
    profileId: PROFILE_ID,
    displayName: "林晚的雨夜声线",
    expectedProfileVersion: 4,
    sourceType: "generated",
    eligibility,
  };
}


function request(
  state: PrivateVoiceDeletionRequestState,
  patch: Partial<VoiceDeletionRequestSnapshot> = {},
): VoiceDeletionRequestSnapshot {
  return {
    contractVersion: PRIVATE_VOICE_DELETION_CONTRACT_VERSION,
    requestId: REQUEST_ID,
    profileId: PROFILE_ID,
    novelId: NOVEL_ID,
    command: state === "grace_pending"
      ? "discard_unreferenced_private_voice"
      : "true_delete_private_voice",
    state,
    expectedProfileVersion: 4,
    impactDigest: "a".repeat(64),
    impact: {
      schemaVersion: PRIVATE_VOICE_DELETION_IMPACT_VERSION,
      profileId: PROFILE_ID,
      novelId: NOVEL_ID,
      profileVersion: 4,
      voiceVersionCount: 2,
      currentNarratorCount: 1,
      characterBindingCount: 2,
      anonymousSpeakerCount: 1,
      genericSlotCount: 1,
      historicalEditionCount: 3,
      renderCount: 8,
      exportCount: 1,
      assetCount: 5,
      totalBytes: 2_097_152,
      activeJobCount: 0,
      externalBackupStatus: "unmanaged",
      historicalAudioConsequence: "unavailable_private_voice_deleted",
    },
    executeAfter: state === "grace_pending" ? "2026-08-29T10:00:30.000Z" : null,
    impactExpiresAt: "2026-08-29T10:15:00.000Z",
    assetCount: 5,
    totalBytes: 2_097_152,
    externalBackupStatus: "unmanaged",
    confirmedAt: ["live_deleting", "live_deleted_backup_pending", "completed", "failed"]
      .includes(state) ? "2026-08-29T10:00:31.000Z" : null,
    cancelledAt: state === "cancelled" ? "2026-08-29T10:00:05.000Z" : null,
    completedAt: state === "completed" ? "2026-08-29T10:00:35.000Z" : null,
    failureCode: state === "failed" ? "VOICE_DELETE_IO_FAILED" : null,
    ...patch,
  };
}


function baseProps(
  overrides: Partial<VoiceLifecyclePanelProps> = {},
): VoiceLifecyclePanelProps {
  return {
    capabilityEnabled: true,
    profile: profile("unreferenced"),
    nowEpochMs: NOW,
    onDiscardUnreferenced: vi.fn(),
    onRequestReferencedDeletion: vi.fn(),
    onConfirmDeletion: vi.fn(),
    onCancelDeletion: vi.fn(),
    onRetryDeletion: vi.fn(),
    ...overrides,
  };
}


describe("voice lifecycle panel", () => {
  it("renders nothing and exposes no real deletion action when capability is omitted", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({ capabilityEnabled: undefined });
    const tree = harness.render(Panel, props);
    expect(tree).toBeNull();
    expect(props.onDiscardUnreferenced).not.toHaveBeenCalled();
    expect(props.onRequestReferencedDeletion).not.toHaveBeenCalled();
    expect(props.onConfirmDeletion).not.toHaveBeenCalled();
  });

  it("separates one-click unreferenced deletion from referenced impact creation", () => {
    const unreferencedHarness = createHarness();
    const UnreferencedPanel = createVoiceLifecyclePanel(unreferencedHarness.React);
    const unreferencedProps = baseProps();
    const unreferencedTree = unreferencedHarness.render(UnreferencedPanel, unreferencedProps);
    (findButton(unreferencedTree, "删除音色").props.onClick as () => void)();
    expect(unreferencedProps.onDiscardUnreferenced).toHaveBeenCalledWith({
      profileId: PROFILE_ID,
      expectedProfileVersion: 4,
    });
    expect(findAll(unreferencedTree, (element) => element.type === "input")).toHaveLength(0);

    const referencedHarness = createHarness();
    const ReferencedPanel = createVoiceLifecyclePanel(referencedHarness.React);
    const referencedProps = baseProps({ profile: profile("referenced") });
    const referencedTree = referencedHarness.render(ReferencedPanel, referencedProps);
    (findButton(referencedTree, "查看删除影响").props.onClick as () => void)();
    expect(referencedProps.onRequestReferencedDeletion).toHaveBeenCalledWith({
      profileId: PROFILE_ID,
      expectedProfileVersion: 4,
    });
    expect(textContent(referencedTree)).toContain("必须先查看冻结的影响摘要");
  });

  it("shows the server-based 30-second undo countdown and removes cancel at expiry", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({
      profile: profile("unreferenced"),
      request: request("grace_pending"),
    });
    let tree = harness.render(Panel, props);
    expect(textContent(tree)).toContain("剩余 30 秒可撤销");
    (findButton(tree, "撤销删除").props.onClick as () => void)();
    expect(props.onCancelDeletion).toHaveBeenCalledWith(REQUEST_ID);

    tree = harness.render(Panel, { ...props, nowEpochMs: NOW + 30_000 });
    expect(textContent(tree)).toContain("撤销窗口已关闭");
    expect(findAll(tree, (element) => (
      element.type === "button" && textContent(element).includes("撤销")
    ))).toHaveLength(0);
  });

  it("requires an exact name before sending the frozen impact CAS confirmation", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({
      profile: profile("referenced"),
      request: request("requested"),
    });
    let tree = harness.render(Panel, props);
    expect(textContent(tree)).toContain("冻结的删除影响");
    expect(textContent(tree)).toContain("人物绑定2");
    expect(textContent(tree)).toContain("历史朗读版本3");
    expect(textContent(tree)).toContain("5 个 · 2.0 MiB");
    expect(textContent(tree)).toContain("外部备份不受本项目管理");
    expect(findButton(tree, "确认删除音色").props.disabled).toBe(true);

    const input = findAll(tree, (element) => element.type === "input")[0];
    if (!input) throw new Error("missing name confirmation input");
    (input.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "林晚的雨夜声线" },
    });
    tree = harness.render(Panel, props);
    const confirm = findButton(tree, "确认删除音色");
    expect(confirm.props.disabled).toBe(false);
    (confirm.props.onClick as () => void)();
    expect(props.onConfirmDeletion).toHaveBeenCalledWith({
      requestId: REQUEST_ID,
      expectedProfileVersion: 4,
      impactDigest: "a".repeat(64),
    });
    (findButton(tree, "取消删除计划").props.onClick as () => void)();
    expect(props.onCancelDeletion).toHaveBeenCalledWith(REQUEST_ID);
  });

  it("never offers cancel after physical deletion starts and exposes only valid retry", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const callbacks = baseProps({
      profile: profile("referenced"),
      request: request("live_deleting"),
    });
    let tree = harness.render(Panel, callbacks);
    expect(textContent(tree)).toContain("此阶段不能撤销");
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);

    tree = harness.render(Panel, { ...callbacks, request: request("failed") });
    (findButton(tree, "重试删除").props.onClick as () => void)();
    expect(callbacks.onRetryDeletion).toHaveBeenCalledWith(REQUEST_ID);

    tree = harness.render(Panel, {
      ...callbacks,
      request: request("failed", { confirmedAt: null }),
    });
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);
  });

  it("reports completed project-managed deletion without claiming external permanence", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const tree = harness.render(Panel, baseProps({
      profile: { ...profile("referenced"), expectedProfileVersion: 5 },
      request: request("completed"),
    }));
    expect(textContent(tree)).toContain("项目管理的在线音色数据已删除");
    expect(textContent(tree)).toContain("Time Machine");
    expect(textContent(tree)).not.toContain("永久删除");
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);
  });
});


describe("voice lifecycle styles", () => {
  it("keeps controls touch-safe and supplies narrow-screen and forced-color layouts", () => {
    expect(VOICE_LIFECYCLE_STYLE_ID).toBe("anw-voice-lifecycle-styles");
    expect(VOICE_LIFECYCLE_STYLES).toContain("min-height: 44px");
    expect(VOICE_LIFECYCLE_STYLES).toContain("@media (max-width: 720px)");
    expect(VOICE_LIFECYCLE_STYLES).toContain("@media (max-width: 390px)");
    expect(VOICE_LIFECYCLE_STYLES).toContain("@media (forced-colors: active)");
    expect(VOICE_LIFECYCLE_STYLES).not.toContain("min-width: 390px");
  });
});
