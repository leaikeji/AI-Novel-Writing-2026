import { apiErrorMessage } from "../api";
import type { EmbeddingAntdRuntime, EmbeddingReactRuntime, InputChangeEvent } from "../embedding/ui-runtime";
import {
  forkStoryTimeline,
  listCharacterInstances,
  listStoryTimelines,
} from "./api";
import {
  type CharacterInstanceRecord,
  type CharacterRootSummary,
  type StoryTimelineCharacterCardTarget,
  type StoryTimelineRecord,
} from "./contracts";
import { ensureStoryTimelineStyles } from "./styles";

interface TimelineAntdRuntime extends EmbeddingAntdRuntime {}

export interface StoryTimelineWorkspaceProps {
  readonly novelId: string;
  readonly initialStoryLedgerVersion: number;
  readonly characters: readonly CharacterRootSummary[];
  readonly onOpenCharacterCard?: (target: StoryTimelineCharacterCardTarget) => void;
}

export function createStoryTimelineWorkspace(
  React: EmbeddingReactRuntime,
  antd: TimelineAntdRuntime,
): (props: StoryTimelineWorkspaceProps) => unknown {
  const h = React.createElement;
  const { Alert, Button, Card, Empty, Spin, Tag } = antd;

  return function StoryTimelineWorkspace(props: StoryTimelineWorkspaceProps): unknown {
    const [timelines, setTimelines] = React.useState<readonly StoryTimelineRecord[]>([]);
    const [instances, setInstances] = React.useState<readonly CharacterInstanceRecord[]>([]);
    const [ledgerVersion, setLedgerVersion] = React.useState(props.initialStoryLedgerVersion);
    const [selectedTimelineId, setSelectedTimelineId] = React.useState<string | null>(null);
    const [selectedInstanceId, setSelectedInstanceId] = React.useState<string | null>(null);
    const [branchName, setBranchName] = React.useState("");
    const [showFork, setShowFork] = React.useState(false);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);

    const refresh = async (signal?: AbortSignal): Promise<void> => {
      const [timelineResource, instanceRows] = await Promise.all([
        listStoryTimelines(props.novelId, signal),
        listCharacterInstances(props.novelId, signal),
      ]);
      setTimelines(timelineResource.items);
      setInstances(instanceRows);
      setSelectedTimelineId((current) => current
        && timelineResource.items.some((item) => item.id === current)
        ? current
        : timelineResource.items[0]?.id ?? null);
    };

    React.useEffect(() => {
      ensureStoryTimelineStyles();
      const controller = new AbortController();
      setBusy(true);
      void refresh(controller.signal)
        .catch((reason) => setError(apiErrorMessage(reason, "加载时间线失败")))
        .finally(() => setBusy(false));
      return () => controller.abort();
    }, [props.novelId]);

    const selectedTimeline = timelines.find((item) => item.id === selectedTimelineId)
      ?? timelines[0]
      ?? null;
    const visibleInstances = instances.filter(
      (item) => item.origin_timeline_id === selectedTimeline?.id && item.lifecycle_state === "active",
    );
    const selectedInstance = visibleInstances.find((item) => item.id === selectedInstanceId) ?? null;
    const characterNames = new Map(props.characters.map((item) => [item.id, item.name]));
    const advanced = timelines.filter((item) => item.lifecycle_state === "active").length > 1;

    const fork = async (): Promise<void> => {
      if (!selectedTimeline || !branchName.trim()) return;
      setBusy(true);
      setError(null);
      try {
        const result = await forkStoryTimeline(props.novelId, selectedTimeline.id, {
          expected_story_ledger_version: ledgerVersion,
          expected_source_timeline_version: selectedTimeline.version,
          timeline_key: `branch-${Date.now().toString(36)}`,
          name: branchName.trim(),
          fork_story_sequence: 0,
          fork_anchor: { source: "author_workspace" },
        });
        setLedgerVersion(result.story_ledger_version);
        setBranchName("");
        setShowFork(false);
        await refresh();
        setSelectedTimelineId(result.timeline.id);
      } catch (reason) {
        setError(apiErrorMessage(reason, "创建时间线分支失败"));
      } finally {
        setBusy(false);
      }
    };

    return h(
      Spin,
      { spinning: busy },
      h("section", { className: "anw-timeline-workspace", "aria-label": "时间线与人物实例" },
        error ? h(Alert, { type: "error", showIcon: true, message: error }) : null,
        h(Card, null,
          h("div", { className: "anw-timeline-header" },
            h("div", null,
              h("h3", null, "时间线"),
              h(Tag, { color: advanced ? "blue" : "green" }, advanced ? "多时间线模式" : "单时间线默认"),
              h("p", { className: "anw-timeline-muted" }, advanced
                ? "章节、关系与状态写入必须明确时间线和人物实例。"
                : "普通写作自动使用主线，无需增加任何步骤。"),
            ),
            h(Button, { onClick: () => setShowFork(true) }, advanced ? "新建分支" : "创建第二条时间线"),
          ),
          showFork && selectedTimeline ? h("div", { className: "anw-timeline-fork-form" },
            h("label", null, "从当前时间线分叉", h("strong", null, selectedTimeline.name)),
            h("label", null, "新时间线名称", h("input", {
              value: branchName,
              maxLength: 240,
              autoFocus: true,
              onChange: (event: InputChangeEvent) => setBranchName(event.target.value),
            })),
            h("div", null,
              h(Button, { type: "primary", disabled: !branchName.trim(), onClick: () => void fork() }, "确认创建"),
              h(Button, { onClick: () => setShowFork(false) }, "取消"),
            ),
          ) : null,
          advanced ? h("div", { className: "anw-timeline-list", role: "tablist", "aria-label": "时间线切换" },
            ...timelines.filter((item) => item.lifecycle_state === "active").map((item) => h(
              "button",
              {
                key: item.id,
                type: "button",
                role: "tab",
                "aria-current": String(item.id === selectedTimeline?.id),
                onClick: () => { setSelectedTimelineId(item.id); setSelectedInstanceId(null); },
              },
              item.name,
            )),
          ) : null,
        ),
        advanced ? h("div", { className: "anw-timeline-grid" },
          h(Card, { title: "本线人物实例" },
            visibleInstances.length ? h("div", { className: "anw-instance-list" },
              ...visibleInstances.map((item) => h("button", {
                key: item.id,
                type: "button",
                "aria-current": String(item.id === selectedInstanceId),
                onClick: () => setSelectedInstanceId(item.id),
              },
              h("strong", null, item.display_label || characterNames.get(item.character_id) || "未命名人物"),
              h("div", { className: "anw-timeline-muted" }, item.continuity_kind === "derived" ? "分支派生实例" : item.continuity_kind === "traveler" ? "穿越者实例" : "本线原生实例"),
              )),
            ) : h(Empty, { description: "当前时间线没有人物实例" }),
          ),
          h(Card, { title: "本线人物摘要" },
            selectedInstance ? h("div", { className: "anw-instance-summary" },
              h("dl", null,
                h("div", null, h("dt", null, "人物"), h("dd", null, characterNames.get(selectedInstance.character_id) || "未命名人物")),
                h("div", null, h("dt", null, "本线标识"), h("dd", null, selectedInstance.display_label || "未设置区分标签")),
                h("div", null, h("dt", null, "连续性"), h("dd", null, selectedInstance.continuity_kind === "derived" ? "分支派生" : selectedInstance.continuity_kind === "traveler" ? "穿越者" : "本线原生")),
                h("div", null, h("dt", null, "档案状态"), h("dd", null, selectedInstance.current_revision_id ? "已有正式档案" : "尚未建立正式档案")),
              ),
              h(Button, {
                type: "primary",
                disabled: !props.onOpenCharacterCard,
                onClick: () => props.onOpenCharacterCard?.({
                  characterId: selectedInstance.character_id,
                  timelineId: selectedTimeline!.id,
                  instanceId: selectedInstance.id,
                }),
              }, "打开正式人物卡"),
              h("p", { className: "anw-timeline-muted" }, "身份、出生资料、目标、秘密与成长方向统一在正式人物卡中维护。"),
            ) : h(Empty, { description: "选择一个人物实例查看摘要" }),
          ),
        ) : null,
      ),
    );
  };
}
