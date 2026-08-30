import { describe, expect, it, vi } from "vitest";

import { createReactHarness, findAll, findButton, settle, textContent } from "../characters/test-harness";
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

async function renderWorkspace(props: StoryTimelineWorkspaceProps) {
  apiRequestMock.mockImplementation((path: string) => {
    if (path === "/novels/novel-1/timelines") return Promise.resolve(timelines);
    if (path === "/novels/novel-1/character-instances") return Promise.resolve(instances);
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
