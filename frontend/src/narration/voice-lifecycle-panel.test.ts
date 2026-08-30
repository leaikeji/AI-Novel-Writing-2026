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
  return value !== null && typeof value === "object"
    && "type" in value && "props" in value && "children" in value;
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
  const button = findAll(root, (element) => element.type === "button" && textContent(element) === label)[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}

function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left && left.length === right.length
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
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
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
const LOCAL_OBSERVED_AT = Date.parse("2032-01-02T03:04:05.000Z");

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
  const terminal = ["cancelled", "completed", "superseded"].includes(state);
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
      voiceVersionIds: [
        "40000000-0000-4000-8000-000000000001",
        "40000000-0000-4000-8000-000000000002",
      ],
      currentNarratorCount: 1,
      characterBindingCount: 2,
      anonymousSpeakerCount: 1,
      genericSlotCount: 1,
      historicalEditionCount: 3,
      renderCount: 8,
      exportCount: 1,
      currentReferenceCount: 5,
      historicalReferenceCount: 12,
      referenceCount: 17,
      assetCount: 5,
      totalBytes: 2_097_152,
      activeJobCount: 0,
      externalBackupStatus: "unmanaged",
      historicalAudioConsequence: "unavailable_private_voice_deleted",
      impactSummary: "将移除 2 个音色版本及 5 个媒体资产。",
    },
    eligibility: "referenced",
    referenceCount: 17,
    serverNow: "2026-08-29T10:00:00.000Z",
    executeAfter: state === "grace_pending" ? "2026-08-29T10:00:30.000Z" : null,
    impactExpiresAt: state === "requested" ? "2026-08-29T10:15:00.000Z" : null,
    assetCount: 5,
    totalBytes: 2_097_152,
    externalBackupStatus: "unmanaged",
    cancellable: state === "grace_pending" || state === "requested",
    retryable: state === "failed",
    terminal,
    confirmedAt: ["live_deleting", "live_deleted_backup_pending", "completed", "failed"]
      .includes(state) ? "2026-08-29T10:00:31.000Z" : null,
    cancelledAt: state === "cancelled" ? "2026-08-29T10:00:05.000Z" : null,
    completedAt: state === "completed" ? "2026-08-29T10:00:35.000Z" : null,
    supersededAt: state === "superseded" ? "2026-08-29T10:00:20.000Z" : null,
    jobDrainStartedAt: null,
    jobDrainDeadline: null,
    failureCode: state === "failed" ? "VOICE_DELETE_UNLINK_FAILED" : null,
    ...patch,
  };
}

function baseProps(overrides: Partial<VoiceLifecyclePanelProps> = {}): VoiceLifecyclePanelProps {
  return {
    capabilityEnabled: true,
    profile: profile("unreferenced"),
    nowEpochMs: LOCAL_OBSERVED_AT,
    serverNowObservedAtEpochMs: LOCAL_OBSERVED_AT,
    onCreateDeletionRequest: vi.fn(),
    onConfirmDeletion: vi.fn(),
    onCancelDeletion: vi.fn(),
    onRetryDeletion: vi.fn(),
    onReloadLifecycle: vi.fn(),
    ...overrides,
  };
}

describe("voice lifecycle panel v2", () => {
  it("renders nothing when the readiness capability is omitted", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({ capabilityEnabled: undefined });
    expect(harness.render(Panel, props)).toBeNull();
    expect(props.onCreateDeletionRequest).not.toHaveBeenCalled();
  });

  it("uses the same create command with zero popup for unreferenced voices", () => {
    const unreferencedHarness = createHarness();
    const UnreferencedPanel = createVoiceLifecyclePanel(unreferencedHarness.React);
    const unreferencedProps = baseProps();
    const unreferencedTree = unreferencedHarness.render(UnreferencedPanel, unreferencedProps);
    (findButton(unreferencedTree, "删除音色").props.onClick as () => void)();
    expect(unreferencedProps.onCreateDeletionRequest).toHaveBeenCalledWith({
      profileId: PROFILE_ID,
      expectedProfileVersion: 4,
    });
    expect(findAll(unreferencedTree, (element) => element.type === "input")).toHaveLength(0);

    const referencedHarness = createHarness();
    const ReferencedPanel = createVoiceLifecyclePanel(referencedHarness.React);
    const referencedProps = baseProps({ profile: profile("referenced") });
    const referencedTree = referencedHarness.render(ReferencedPanel, referencedProps);
    (findButton(referencedTree, "查看删除影响").props.onClick as () => void)();
    expect(referencedProps.onCreateDeletionRequest).toHaveBeenCalledWith({
      profileId: PROFILE_ID,
      expectedProfileVersion: 4,
    });
  });

  it("uses local elapsed time against server_now for the undo countdown", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({ request: request("grace_pending") });
    let tree = harness.render(Panel, props);
    expect(textContent(tree)).toContain("剩余 30 秒可撤销");
    (findButton(tree, "撤销删除").props.onClick as () => void)();
    expect(props.onCancelDeletion).toHaveBeenCalledWith(REQUEST_ID);

    tree = harness.render(Panel, { ...props, nowEpochMs: LOCAL_OBSERVED_AT + 30_000 });
    expect(textContent(tree)).toContain("撤销窗口已关闭");
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);
  });

  it("shows one frozen summary confirmation without requiring a name input", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({
      profile: profile("referenced"),
      request: request("requested"),
    });
    const tree = harness.render(Panel, props);
    expect(textContent(tree)).toContain("冻结的删除影响");
    expect(textContent(tree)).toContain("人物绑定2");
    expect(textContent(tree)).toContain("历史朗读版本3");
    expect(textContent(tree)).toContain("5 个 · 2.0 MiB");
    expect(findAll(tree, (element) => element.type === "input")).toHaveLength(0);
    const confirm = findButton(tree, "确认删除音色");
    expect(confirm.props.disabled).toBe(false);
    (confirm.props.onClick as () => void)();
    expect(props.onConfirmDeletion).toHaveBeenCalledWith({
      requestId: REQUEST_ID,
      expectedProfileVersion: 4,
      impactDigest: "a".repeat(64),
    });
  });

  it("shows both safe pre-fence actions while jobs drain, but only retry after fencing", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const waitingProps = baseProps({
      profile: profile("referenced"),
      request: request("failed", {
        failureCode: "VOICE_DELETE_WAITING_FOR_JOBS",
        confirmedAt: null,
        cancellable: true,
        retryable: true,
        jobDrainStartedAt: "2026-08-29T10:00:00.000Z",
        jobDrainDeadline: "2026-08-29T10:01:00.000Z",
      }),
    });
    let tree = harness.render(Panel, waitingProps);
    expect(textContent(tree)).toContain("任务排空窗口剩余 60 秒");
    (findButton(tree, "撤销删除").props.onClick as () => void)();
    (findButton(tree, "重试删除").props.onClick as () => void)();
    expect(waitingProps.onCancelDeletion).toHaveBeenCalledWith(REQUEST_ID);
    expect(waitingProps.onRetryDeletion).toHaveBeenCalledWith(REQUEST_ID);

    const fencedProps = baseProps({
      profile: profile("referenced"),
      request: request("failed", { cancellable: false, retryable: true }),
    });
    tree = harness.render(Panel, fencedProps);
    expect(findAll(tree, (element) => textContent(element) === "撤销删除")).toHaveLength(0);
    (findButton(tree, "重试删除").props.onClick as () => void)();
    expect(fencedProps.onRetryDeletion).toHaveBeenCalledWith(REQUEST_ID);
  });

  it("presents superseded as terminal and asks for a fresh impact", () => {
    const harness = createHarness();
    const Panel = createVoiceLifecyclePanel(harness.React);
    const props = baseProps({
      profile: { ...profile("referenced"), expectedProfileVersion: 5 },
      request: request("superseded", { failureCode: "VOICE_DELETE_PROFILE_CHANGED" }),
    });
    const tree = harness.render(Panel, props);
    expect(textContent(tree)).toContain("删除计划因音色或影响发生变化而失效");
    expect(findAll(tree, (element) => element.type === "button")).toHaveLength(0);
    expect(props.onReloadLifecycle).toHaveBeenCalledOnce();
  });
});

describe("voice lifecycle styles", () => {
  it("keeps controls touch-safe and removes obsolete name-confirmation styles", () => {
    expect(VOICE_LIFECYCLE_STYLE_ID).toBe("anw-voice-lifecycle-styles");
    expect(VOICE_LIFECYCLE_STYLES).toContain("min-height: 44px");
    expect(VOICE_LIFECYCLE_STYLES).toContain("@media (max-width: 720px)");
    expect(VOICE_LIFECYCLE_STYLES).toContain("@media (max-width: 390px)");
    expect(VOICE_LIFECYCLE_STYLES).toContain("@media (forced-colors: active)");
    expect(VOICE_LIFECYCLE_STYLES).not.toContain("confirmation input");
    expect(VOICE_LIFECYCLE_STYLES).not.toContain("min-width: 390px");
  });
});
