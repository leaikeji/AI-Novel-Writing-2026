import { describe, expect, it, vi } from "vitest";

import { NarrationApiError } from "./api";
import {
  createCachePanel,
  formatExactBytes,
  isCacheCleanupActionable,
  type CachePanelApi,
  type CachePanelProps,
  type CachePanelReactRuntime,
} from "./cache-panel";
import {
  NARRATION_CACHE_SCHEMA_VERSION,
  NARRATION_CAPABILITY_SCHEMA_VERSION,
  NARRATION_SETTINGS_API_VERSION,
  type FeatureCapability,
  type NarrationApiErrorDetail,
  type NarrationAuthorizationState,
  type NarrationCacheCleanupPreview,
  type NarrationCacheCleanupResult,
  type NarrationCacheStatus,
  type NarrationCapabilities,
} from "./contracts";
import { T2_F_NARRATION_SETTINGS_PANEL_STYLES } from "./styles/t2-f";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  dependencies: readonly unknown[];
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
  const item = findAll(root, (element) => element.type === "button" && textContent(element) === label)[0];
  if (!item) throw new Error(`button not found: ${label}`);
  return item;
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

  const React: CachePanelReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
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
    beginRender(): void {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
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
}


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_NOVEL_ID = "22222222-2222-4222-8222-222222222222";
const FINGERPRINT = "a".repeat(64);
const OTHER_FINGERPRINT = "b".repeat(64);


function feature(key: FeatureCapability["key"], enabled = true): FeatureCapability {
  return {
    key,
    state: enabled ? "enabled" : "hold",
    visible: true,
    actionable: enabled,
    reason_code: enabled ? null : "T2_GATE_REQUIRED",
    required_gate: enabled ? null : "T2-GATE",
  };
}


function capabilities(cacheEnabled = true): NarrationCapabilities {
  return {
    schema_version: NARRATION_CAPABILITY_SCHEMA_VERSION,
    items: [
      feature("narration_product"),
      feature("reading_settings"),
      feature("cache_cleanup", cacheEnabled),
    ],
  };
}


const authorization: NarrationAuthorizationState = {
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


function status(
  changes: Partial<NarrationCacheStatus> = {},
): NarrationCacheStatus {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    schema_version: NARRATION_CACHE_SCHEMA_VERSION,
    novel_id: NOVEL_ID,
    snapshot_fingerprint: FINGERPRINT,
    source_asset_bytes: 100,
    locked_voice_bytes: 200,
    referenced_edition_bytes: 300,
    derived_cache_bytes: 4096,
    reclaimable_bytes: 2048,
    pending_job_count: 2,
    disk_free_bytes: 5 * 1024 ** 3,
    disk_total_bytes: 10 * 1024 ** 3,
    cleanup_capability: feature("cache_cleanup"),
    ...changes,
  };
}


function preview(
  changes: Partial<NarrationCacheCleanupPreview> = {},
): NarrationCacheCleanupPreview {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    snapshot_fingerprint: FINGERPRINT,
    cleanup_token: `v1.${"c".repeat(70)}`,
    expires_at: "2099-08-26T09:00:00Z",
    reclaimable_bytes: 2048,
    protected_asset_count: 3,
    candidate_asset_count: 2,
    ...changes,
  };
}


function result(
  changes: Partial<NarrationCacheCleanupResult> = {},
): NarrationCacheCleanupResult {
  return {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    novel_id: NOVEL_ID,
    deleted_asset_count: 2,
    reclaimed_bytes: 1536,
    source_asset_deleted_count: 0,
    locked_voice_deleted_count: 0,
    referenced_asset_deleted_count: 0,
    ...changes,
  };
}


function props(changes: Partial<CachePanelProps> = {}): CachePanelProps {
  return {
    novelId: NOVEL_ID,
    capabilities: capabilities(),
    authorization,
    ...changes,
  };
}


function apiError(code: NarrationApiErrorDetail["code"]): NarrationApiError {
  return new NarrationApiError(409, {
    contract_version: NARRATION_SETTINGS_API_VERSION,
    code,
    message: "fault",
    retryable: false,
    field: null,
    current_version: null,
    capability: "cache_cleanup",
  });
}


describe("cache panel helpers", () => {
  it("formats exact bytes and combines global, nested and authorization gates", () => {
    expect(formatExactBytes(0)).toBe("0 B");
    expect(formatExactBytes(2048)).toBe("2,048 B（2.00 KiB）");
    expect(isCacheCleanupActionable(capabilities(), authorization, status())).toBe(true);
    expect(isCacheCleanupActionable(capabilities(false), authorization, status())).toBe(false);
    expect(isCacheCleanupActionable(
      capabilities(),
      authorization,
      status({ cleanup_capability: feature("cache_cleanup", false) }),
    )).toBe(false);
    expect(isCacheCleanupActionable(
      capabilities(),
      { ...authorization, can_configure: false },
      status(),
    )).toBe(false);
  });
});


describe("cache panel", () => {
  it("requires preview and explicit confirmation before exact-snapshot execution", async () => {
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn().mockResolvedValue(status()),
      previewNarrationCacheCleanup: vi.fn().mockResolvedValue(preview()),
      executeNarrationCacheCleanup: vi.fn().mockResolvedValue(result()),
    };
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    const panelProps = props();

    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    let tree = Panel(panelProps);
    harness.commitEffects();
    expect(textContent(tree)).toContain("源资产（不可清理）100 B");
    expect(textContent(tree)).toContain("当前可回收2,048 B（2.00 KiB）");

    (findButton(tree, "预览可清理项").props.onClick as () => void)();
    expect(api.executeNarrationCacheCleanup).not.toHaveBeenCalled();
    await settle();
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    const executeBeforeConfirm = findButton(tree, "确认清理派生缓存");
    expect(executeBeforeConfirm.props.disabled).toBe(true);
    expect(textContent(tree)).toContain("此时尚未删除任何资产");
    const checkbox = findAll(tree, (element) => element.type === "input" && element.props.type === "checkbox")[0];
    if (!checkbox) throw new Error("confirmation checkbox missing");
    (checkbox.props.onChange as (event: { target: { checked: boolean } }) => void)({
      target: { checked: true },
    });
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    const execute = findButton(tree, "确认清理派生缓存");
    expect(execute.props.disabled).toBe(false);
    (execute.props.onClick as () => void)();
    await settle();

    expect(api.previewNarrationCacheCleanup).toHaveBeenCalledWith(
      NOVEL_ID,
      { snapshot_fingerprint: FINGERPRINT },
      expect.any(AbortSignal),
    );
    expect(api.executeNarrationCacheCleanup).toHaveBeenCalledWith(
      NOVEL_ID,
      {
        snapshot_fingerprint: FINGERPRINT,
        cleanup_token: preview().cleanup_token,
        confirmed: true,
      },
      expect.any(AbortSignal),
    );
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    expect(textContent(tree)).toContain("实际回收 1,536 B（1.50 KiB）");
    expect(textContent(tree)).toContain("源资产 0 个、锁定音色 0 个");
  });

  it("is status-only under HOLD even if reclaimable bytes exist", async () => {
    const heldStatus = status({ cleanup_capability: feature("cache_cleanup", false) });
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn().mockResolvedValue(heldStatus),
      previewNarrationCacheCleanup: vi.fn(),
      executeNarrationCacheCleanup: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    const panelProps = props({ capabilities: capabilities(false) });
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    const tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("T2_GATE_REQUIRED");
    expect(findButton(tree, "预览可清理项").props.disabled).toBe(true);
    expect(api.previewNarrationCacheCleanup).not.toHaveBeenCalled();
    expect(api.executeNarrationCacheCleanup).not.toHaveBeenCalled();
  });

  it("rejects a mismatched preview and never exposes an execute confirmation", async () => {
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn().mockResolvedValue(status()),
      previewNarrationCacheCleanup: vi.fn().mockResolvedValue(preview({
        snapshot_fingerprint: OTHER_FINGERPRINT,
      })),
      executeNarrationCacheCleanup: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    const panelProps = props();
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    let tree = Panel(panelProps);
    harness.commitEffects();
    (findButton(tree, "预览可清理项").props.onClick as () => void)();
    await settle();
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("预览与当前快照不一致");
    expect(findAll(tree, (element) => textContent(element) === "确认清理派生缓存")).toHaveLength(0);
    expect(api.executeNarrationCacheCleanup).not.toHaveBeenCalled();
  });

  it("clears preview on execute conflict and reports no fabricated reclaimed bytes", async () => {
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn().mockResolvedValue(status()),
      previewNarrationCacheCleanup: vi.fn().mockResolvedValue(preview()),
      executeNarrationCacheCleanup: vi.fn().mockRejectedValue(apiError("VERSION_CONFLICT")),
    };
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    const panelProps = props();
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    let tree = Panel(panelProps);
    harness.commitEffects();
    (findButton(tree, "预览可清理项").props.onClick as () => void)();
    await settle();
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    const checkbox = findAll(tree, (element) => element.type === "input" && element.props.type === "checkbox")[0];
    if (!checkbox) throw new Error("confirmation checkbox missing");
    (checkbox.props.onChange as (event: { target: { checked: boolean } }) => void)({ target: { checked: true } });
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();
    (findButton(tree, "确认清理派生缓存").props.onClick as () => void)();
    await settle();
    harness.beginRender();
    tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("缓存快照已变化");
    expect(textContent(tree)).not.toContain("清理完成");
    expect(textContent(tree)).not.toContain("实际回收");
    expect(findAll(tree, (element) => element.type === "input" && element.props.type === "checkbox")).toHaveLength(0);
  });

  it("shows a definite disk-insufficient state when free bytes are zero", async () => {
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn().mockResolvedValue(status({ disk_free_bytes: 0 })),
      previewNarrationCacheCleanup: vi.fn(),
      executeNarrationCacheCleanup: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    const panelProps = props();
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    const tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("媒体盘可用空间为 0");
    expect(findAll(tree, (element) => element.props.role === "alert").length).toBeGreaterThan(0);
  });

  it("warns below the fixed 1 GiB guard while preserving existing playback", async () => {
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn().mockResolvedValue(status({
        disk_free_bytes: 512 * 1024 ** 2,
      })),
      previewNarrationCacheCleanup: vi.fn(),
      executeNarrationCacheCleanup: vi.fn(),
    };
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    const panelProps = props();
    harness.beginRender();
    Panel(panelProps);
    harness.commitEffects();
    await settle();
    harness.beginRender();
    const tree = Panel(panelProps);
    harness.commitEffects();

    expect(textContent(tree)).toContain("低于 1 GiB 安全余量");
    expect(textContent(tree)).toContain("已有音频仍可播放");
    expect(findAll(tree, (element) => element.props.role === "alert")).toHaveLength(1);
  });

  it("aborts stale scope loads and restores host focus on destroy", async () => {
    let resolveFirst: ((value: NarrationCacheStatus) => void) | undefined;
    const first = new Promise<NarrationCacheStatus>((resolve) => { resolveFirst = resolve; });
    const signals: AbortSignal[] = [];
    const api: CachePanelApi = {
      getNarrationCacheStatus: vi.fn((novelId, signal) => {
        if (signal) signals.push(signal);
        return novelId === NOVEL_ID
          ? first
          : Promise.resolve(status({ novel_id: OTHER_NOVEL_ID }));
      }),
      previewNarrationCacheCleanup: vi.fn(),
      executeNarrationCacheCleanup: vi.fn(),
    };
    const onReturnFocus = vi.fn();
    const harness = createReactHarness();
    const Panel = createCachePanel(harness.React, api);
    harness.beginRender();
    Panel(props({ onReturnFocus }));
    harness.commitEffects();
    harness.beginRender();
    Panel(props({ novelId: OTHER_NOVEL_ID, onReturnFocus }));
    harness.commitEffects();
    expect(signals[0]?.aborted).toBe(true);
    resolveFirst?.(status());
    await settle();
    harness.beginRender();
    const tree = Panel(props({ novelId: OTHER_NOVEL_ID, onReturnFocus }));
    harness.commitEffects();
    expect((tree as FakeElement).props["data-cache-panel-phase"]).toBe("ready");
    harness.unmount();
    expect(onReturnFocus).toHaveBeenCalledTimes(1);
    expect(T2_F_NARRATION_SETTINGS_PANEL_STYLES).toContain(".anw-cache-panel");
  });
});
