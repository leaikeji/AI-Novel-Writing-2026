import { describe, expect, it, vi } from "vitest";

import { createReactHarness, findAll, findButton, settle, textContent } from "../characters/test-harness";
import type {
  CharacterInstanceRecord,
  TimelineForkResult,
  TimelineIndexResource,
} from "./contracts";
import { createStoryTimelineWorkspace, type StoryTimelineWorkspaceProps } from "./timeline-workspace";

const { apiRequestMock } = vi.hoisted(() => ({ apiRequestMock: vi.fn() }));

vi.mock("../api", () => ({
  apiRequest: apiRequestMock,
  apiErrorMessage: (_reason: unknown, fallback: string) => fallback,
}));

vi.mock("./styles", () => ({ ensureStoryTimelineStyles: vi.fn() }));

const timelines = {
  single_timeline_mode: false,
  items: [
    {
      id: "timeline-main",
      novel_id: "novel-1",
      timeline_key: "main",
      name: "主线",
      timeline_kind: "main",
      is_primary: true,
      parent_timeline_id: null,
      fork_story_sequence: null,
      lifecycle_state: "active",
      position: 0,
      version: 2,
    },
    {
      id: "timeline-branch",
      novel_id: "novel-1",
      timeline_key: "branch",
      name: "雨夜分支",
      timeline_kind: "branch",
      is_primary: false,
      parent_timeline_id: "timeline-main",
      fork_story_sequence: 1,
      lifecycle_state: "active",
      position: 1,
      version: 1,
    },
  ],
} as const;

const singleTimeline: TimelineIndexResource = {
  single_timeline_mode: true,
  items: [timelines.items[0]],
};

const instances = [
  {
    id: "instance-main",
    novel_id: "novel-1",
    character_id: "character-root",
    origin_timeline_id: "timeline-main",
    derived_from_instance_id: null,
    continuity_kind: "native",
    display_label: "主线版本",
    current_revision_id: "profile-revision-1",
    lifecycle_state: "active",
    version: 4,
  },
] as const;

const forkResult: TimelineForkResult = {
  timeline: {
    id: "timeline-new-branch",
    novel_id: "novel-1",
    timeline_key: "branch-new",
    name: "雾夜分支",
    timeline_kind: "branch",
    is_primary: false,
    parent_timeline_id: "timeline-main",
    fork_story_sequence: 0,
    lifecycle_state: "active",
    position: 2,
    version: 1,
  },
  derived_instances: [],
  copied_fact_count: 0,
  story_ledger_version: 10,
};

const antd = {
  Alert: "alert",
  Button: "button",
  Card: "card",
  Empty: "empty",
  Input: "input",
  InputNumber: "input-number",
  Select: "select",
  Spin: "spin",
  Tag: "tag",
};

interface RenderOptions {
  readonly timelineResource?: TimelineIndexResource;
  readonly instanceRows?: readonly CharacterInstanceRecord[];
  readonly forkResponse?: TimelineForkResult;
  readonly forkError?: unknown;
  readonly timelineError?: unknown;
}

async function renderWorkspace(
  props: StoryTimelineWorkspaceProps,
  options: RenderOptions = {},
) {
  apiRequestMock.mockReset();
  apiRequestMock.mockImplementation((path: string) => {
    if (path === "/novels/novel-1/timelines") {
      return options.timelineError
        ? Promise.reject(options.timelineError)
        : Promise.resolve(options.timelineResource ?? timelines);
    }
    if (path === "/novels/novel-1/character-instances") {
      return Promise.resolve(options.instanceRows ?? instances);
    }
    if (path.includes("/fork")) {
      return options.forkError
        ? Promise.reject(options.forkError)
        : Promise.resolve(options.forkResponse ?? forkResult);
    }
    throw new Error(`unexpected request: ${path}`);
  });
  const harness = createReactHarness();
  const Component = createStoryTimelineWorkspace(harness.React, antd);
  let root = harness.render(Component, props);
  harness.commitEffects();
  await settle();
  root = harness.render(Component, props);
  return { Component, harness, root };
}

describe("story timeline context and ledger hand-off", () => {
  it("uses the only active timeline without rendering a persistent selector", async () => {
    const onTimelineContextChange = vi.fn();
    const onOpenLedger = vi.fn();
    const rendered = await renderWorkspace({
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [{ id: "character-root", name: "林舟" }],
      onTimelineContextChange,
      onOpenLedger,
    }, { timelineResource: singleTimeline });

    expect(findAll(rendered.root, (element) => element.props.role === "tablist")).toHaveLength(0);
    expect(textContent(rendered.root)).toContain("普通写作自动使用主线");
    expect(onTimelineContextChange).toHaveBeenLastCalledWith({
      mode: "single",
      timelineId: "timeline-main",
      timelineName: "主线",
    });

    (findButton(rendered.root, "查看本线账本").props.onClick as () => void)();
    expect(onOpenLedger).toHaveBeenCalledWith({
      section: "ledger",
      ledger_timeline: "timeline-main",
    });
  });

  it("exposes a complete roving tab contract and publishes explicit multi-line selection", async () => {
    const onTimelineContextChange = vi.fn();
    const props: StoryTimelineWorkspaceProps = {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      currentTimelineId: "timeline-main",
      characters: [{ id: "character-root", name: "林舟" }],
      onTimelineContextChange,
    };
    const rendered = await renderWorkspace(props);
    const tabs = findAll(rendered.root, (element) => element.props.role === "tab");

    expect(tabs).toHaveLength(2);
    expect(tabs[0]?.props["aria-selected"]).toBe(true);
    expect(tabs[0]?.props.tabIndex).toBe(0);
    expect(tabs[1]?.props["aria-selected"]).toBe(false);
    expect(tabs[1]?.props.tabIndex).toBe(-1);
    expect(tabs[0]?.props["aria-controls"]).toBe("anw-timeline-novel-1-panel-timeline-main");
    const panel = findAll(rendered.root, (element) => element.props.role === "tabpanel")[0];
    expect(panel?.props.id).toBe("anw-timeline-novel-1-panel-timeline-main");
    expect(panel?.props["aria-labelledby"]).toBe("anw-timeline-novel-1-tab-timeline-main");

    const preventDefault = vi.fn();
    (tabs[0]?.props.onKeyDown as (event: { key: string; preventDefault(): void }) => void)({
      key: "ArrowRight",
      preventDefault,
    });
    const moved = rendered.harness.render(rendered.Component, props);
    const movedTabs = findAll(moved, (element) => element.props.role === "tab");
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(movedTabs[0]?.props.tabIndex).toBe(-1);
    expect(movedTabs[1]?.props.tabIndex).toBe(0);
    expect(movedTabs[1]?.props["aria-selected"]).toBe(true);
    expect(onTimelineContextChange).toHaveBeenLastCalledWith({
      mode: "multiple",
      timelineId: "timeline-branch",
      timelineName: "雨夜分支",
    });

    (movedTabs[1]?.props.onKeyDown as (event: { key: string; preventDefault(): void }) => void)({
      key: "Home",
      preventDefault,
    });
    const home = rendered.harness.render(rendered.Component, props);
    const homeTabs = findAll(home, (element) => element.props.role === "tab");
    expect(homeTabs[0]?.props.tabIndex).toBe(0);
    (homeTabs[0]?.props.onKeyDown as (event: { key: string; preventDefault(): void }) => void)({
      key: "End",
      preventDefault,
    });
    const end = rendered.harness.render(rendered.Component, props);
    const endTabs = findAll(end, (element) => element.props.role === "tab");
    expect(endTabs[1]?.props.tabIndex).toBe(0);
  });

  it("deep-links the explicitly selected timeline into the frozen ledger filter", async () => {
    const onOpenLedger = vi.fn();
    const props: StoryTimelineWorkspaceProps = {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      currentTimelineId: "timeline-branch",
      characters: [],
      onOpenLedger,
    };
    const rendered = await renderWorkspace(props);

    (findButton(rendered.root, "查看本线账本").props.onClick as () => void)();

    expect(onOpenLedger).toHaveBeenCalledWith({
      section: "ledger",
      ledger_timeline: "timeline-branch",
    });
  });

  it("synchronizes CAS from refresh and later authoritative props, then reports mutation", async () => {
    const onLedgerSnapshotChange = vi.fn();
    const refreshLedgerSnapshot = vi.fn().mockResolvedValue({
      ledger_snapshot_token: "snapshot-8",
      story_ledger_version: 8,
    });
    const baseProps: StoryTimelineWorkspaceProps = {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      ledgerSnapshot: {
        ledger_snapshot_token: "snapshot-7",
        story_ledger_version: 7,
      },
      characters: [],
      refreshLedgerSnapshot,
      onLedgerSnapshotChange,
    };
    const rendered = await renderWorkspace(baseProps);

    expect(refreshLedgerSnapshot).toHaveBeenCalledOnce();
    expect(refreshLedgerSnapshot.mock.calls[0]?.[0]).toEqual({
      mode: "multiple",
      timelineId: "timeline-main",
      timelineName: "主线",
    });
    expect(onLedgerSnapshotChange).toHaveBeenCalledWith({
      ledger_snapshot_token: "snapshot-8",
      story_ledger_version: 8,
    }, "refresh");

    (findButton(rendered.root, "新建分支").props.onClick as () => void)();
    let root = rendered.harness.render(rendered.Component, baseProps);
    const nameInput = findAll(root, (element) => element.type === "input")[0];
    (nameInput?.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "雾夜分支" },
    });

    const nextProps: StoryTimelineWorkspaceProps = {
      ...baseProps,
      ledgerSnapshot: {
        ledger_snapshot_token: "snapshot-9",
        story_ledger_version: 9,
      },
    };
    root = rendered.harness.render(rendered.Component, nextProps);
    rendered.harness.commitEffects();
    root = rendered.harness.render(rendered.Component, nextProps);
    (findButton(root, "确认创建").props.onClick as () => void)();
    await settle();

    const forkCall = apiRequestMock.mock.calls.find((call) => String(call[0]).includes("/fork"));
    expect(JSON.parse(String((forkCall?.[1] as { body?: string })?.body))).toMatchObject({
      expected_story_ledger_version: 9,
      name: "雾夜分支",
    });
    expect(onLedgerSnapshotChange).toHaveBeenCalledWith({
      ledger_snapshot_token: null,
      story_ledger_version: 10,
    }, "mutation");
  });

  it("accepts a newer opaque snapshot from an ordinary refresh", async () => {
    const onLedgerSnapshotChange = vi.fn();
    const refreshLedgerSnapshot = vi.fn()
      .mockResolvedValueOnce({
        ledger_snapshot_token: "snapshot-8",
        story_ledger_version: 8,
      })
      .mockResolvedValueOnce({
        ledger_snapshot_token: "snapshot-12",
        story_ledger_version: 12,
      });
    const props: StoryTimelineWorkspaceProps = {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [],
      refreshLedgerSnapshot,
      onLedgerSnapshotChange,
    };
    const rendered = await renderWorkspace(props);

    (findButton(rendered.root, "刷新").props.onClick as () => void)();
    await settle();

    expect(refreshLedgerSnapshot).toHaveBeenCalledTimes(2);
    expect(onLedgerSnapshotChange).toHaveBeenLastCalledWith({
      ledger_snapshot_token: "snapshot-12",
      story_ledger_version: 12,
    }, "refresh");
  });

  it("keeps the fork draft on stale CAS, refreshes scope, and exposes a conflict state", async () => {
    const onLedgerSnapshotChange = vi.fn();
    const props: StoryTimelineWorkspaceProps = {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [],
      onLedgerSnapshotChange,
    };
    const rendered = await renderWorkspace(props, {
      forkError: {
        status: 409,
        detail: {
          code: "version_conflict",
          current: { story_ledger_version: 11 },
        },
      },
    });

    (findButton(rendered.root, "新建分支").props.onClick as () => void)();
    let root = rendered.harness.render(rendered.Component, props);
    const input = findAll(root, (element) => element.type === "input")[0];
    (input?.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "保留的分支名" },
    });
    root = rendered.harness.render(rendered.Component, props);
    (findButton(root, "确认创建").props.onClick as () => void)();
    await settle();
    root = rendered.harness.render(rendered.Component, props);

    expect((findAll(root, (element) => element.type === "input")[0]?.props.value)).toBe("保留的分支名");
    const alert = findAll(root, (element) => element.type === "alert")[0];
    expect(alert?.props.type).toBe("warning");
    expect(alert?.props.message).toBe("时间线或账本已更新");
    expect(onLedgerSnapshotChange).toHaveBeenCalledWith({
      ledger_snapshot_token: null,
      story_ledger_version: 11,
    }, "conflict");
    expect(apiRequestMock.mock.calls.filter((call) => call[0] === "/novels/novel-1/timelines").length).toBeGreaterThan(1);
  });

  it("renders a recoverable load error without inventing timeline operations", async () => {
    const rendered = await renderWorkspace({
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [],
    }, { timelineError: new Error("offline") });
    const alert = findAll(rendered.root, (element) => element.type === "alert")[0];

    expect(alert?.props.type).toBe("error");
    expect(alert?.props.message).toBe("时间线加载失败");
    expect(textContent(rendered.root)).not.toContain("合并时间线");
    expect(textContent(rendered.root)).not.toContain("版本映射");
  });
});

describe("story timeline character hand-off", () => {
  it("renders a read-only instance summary without issuing profile reads or writes", async () => {
    const rendered = await renderWorkspace({
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [{ id: "character-root", name: "林舟" }],
    });
    const instanceButton = findAll(
      rendered.root,
      (element) => element.type === "button" && textContent(element).includes("主线版本"),
    )[0];

    (instanceButton.props.onClick as () => void)();
    const root = rendered.harness.render(rendered.Component, {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [{ id: "character-root", name: "林舟" }],
    });

    expect(textContent(root)).toContain("林舟");
    expect(textContent(root)).toContain("已有正式档案");
    expect(textContent(root)).not.toContain("保存为新 revision");
    expect(findAll(root, (element) => element.type === "input" || element.type === "textarea")).toHaveLength(0);
    expect(apiRequestMock.mock.calls.some((call) => String(call[0]).includes("/profile"))).toBe(false);
    expect(apiRequestMock.mock.calls.some((call) => (
      (call[1] as { readonly method?: string } | undefined)?.method === "PUT"
    ))).toBe(false);
  });

  it("hands stable root, timeline and instance IDs to the formal character card", async () => {
    const onOpenCharacterCard = vi.fn();
    const props: StoryTimelineWorkspaceProps = {
      novelId: "novel-1",
      initialStoryLedgerVersion: 7,
      characters: [{ id: "character-root", name: "林舟" }],
      onOpenCharacterCard,
    };
    const rendered = await renderWorkspace(props);
    const instanceButton = findAll(
      rendered.root,
      (element) => element.type === "button" && textContent(element).includes("主线版本"),
    )[0];

    (instanceButton.props.onClick as () => void)();
    const root = rendered.harness.render(rendered.Component, props);
    const openButton = findButton(root, "打开正式人物卡");
    expect(openButton.props.disabled).toBe(false);
    (openButton.props.onClick as () => void)();

    expect(onOpenCharacterCard).toHaveBeenCalledWith({
      characterId: "character-root",
      timelineId: "timeline-main",
      instanceId: "instance-main",
    });
  });
});
