import { apiErrorMessage } from "../api";
import type { EmbeddingAntdRuntime, EmbeddingReactRuntime, InputChangeEvent } from "../embedding/ui-runtime";
import {
  forkStoryTimeline,
  getCharacterInstanceProfile,
  listCharacterInstances,
  listStoryTimelines,
  saveCharacterInstanceProfile,
} from "./api";
import {
  EMPTY_INSTANCE_PROFILE,
  type CharacterInstanceProfileV1,
  type CharacterInstanceRecord,
  type CharacterRootSummary,
  type StoryTimelineRecord,
} from "./contracts";
import { ensureStoryTimelineStyles } from "./styles";

interface TimelineAntdRuntime extends EmbeddingAntdRuntime {}

export interface StoryTimelineWorkspaceProps {
  readonly novelId: string;
  readonly initialStoryLedgerVersion: number;
  readonly characters: readonly CharacterRootSummary[];
}

type EditableProfile = Omit<CharacterInstanceProfileV1, "schema_version">;

const editable = (profile: CharacterInstanceProfileV1): EditableProfile => ({
  public_identity: profile.public_identity,
  true_identity: profile.true_identity,
  cover_identity: profile.cover_identity,
  birth_year: profile.birth_year,
  birth_information: profile.birth_information,
  occupation: profile.occupation,
  personality: profile.personality,
  goals: [...profile.goals],
  flaws: [...profile.flaws],
  secrets: [...profile.secrets],
  growth_direction: profile.growth_direction,
});

const lines = (value: string): readonly string[] => value
  .split(/[,\n，]/)
  .map((item) => item.trim())
  .filter((item, index, all) => Boolean(item) && all.indexOf(item) === index);

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
    const [profile, setProfile] = React.useState<EditableProfile>(editable(EMPTY_INSTANCE_PROFILE));
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

    React.useEffect(() => {
      if (!selectedInstanceId) {
        setProfile(editable(EMPTY_INSTANCE_PROFILE));
        return;
      }
      const controller = new AbortController();
      setBusy(true);
      void getCharacterInstanceProfile(props.novelId, selectedInstanceId, controller.signal)
        .then((resource) => setProfile(editable(resource.revision?.profile ?? EMPTY_INSTANCE_PROFILE)))
        .catch((reason) => setError(apiErrorMessage(reason, "加载人物实例档案失败")))
        .finally(() => setBusy(false));
      return () => controller.abort();
    }, [props.novelId, selectedInstanceId]);

    const selectedTimeline = timelines.find((item) => item.id === selectedTimelineId)
      ?? timelines[0]
      ?? null;
    const visibleInstances = instances.filter(
      (item) => item.origin_timeline_id === selectedTimeline?.id && item.lifecycle_state === "active",
    );
    const selectedInstance = instances.find((item) => item.id === selectedInstanceId) ?? null;
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

    const saveProfile = async (): Promise<void> => {
      if (!selectedInstance) return;
      setBusy(true);
      setError(null);
      try {
        const result = await saveCharacterInstanceProfile(
          props.novelId,
          selectedInstance.id,
          {
            expected_story_ledger_version: ledgerVersion,
            expected_instance_version: selectedInstance.version,
            operation_key: `profile.web.${Date.now().toString(36)}`,
            source_kind: "manual",
            profile: { schema_version: "character-instance-profile/1", ...profile },
          },
        );
        setLedgerVersion(result.story_ledger_version);
        await refresh();
      } catch (reason) {
        setError(apiErrorMessage(reason, "保存人物实例档案失败"));
      } finally {
        setBusy(false);
      }
    };

    const textField = (key: keyof EditableProfile, label: string, multiline = false): unknown => h(
      "label",
      { key },
      label,
      h(multiline ? "textarea" : "input", {
        value: String(profile[key] ?? ""),
        onChange: (event: InputChangeEvent) => setProfile((current) => ({
          ...current,
          [key]: event.target.value || null,
        })),
      }),
    );

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
          showFork && selectedTimeline ? h("div", { className: "anw-profile-form" },
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
          h(Card, { title: "人物实例档案" },
            selectedInstance ? h("div", { className: "anw-profile-form" },
              textField("public_identity", "公开身份"),
              textField("true_identity", "真实身份"),
              textField("cover_identity", "掩护身份"),
              h("label", null, "出生年", h("input", {
                type: "number",
                value: profile.birth_year ?? "",
                onChange: (event: InputChangeEvent) => setProfile((current) => ({
                  ...current,
                  birth_year: event.target.value ? Number(event.target.value) : null,
                })),
              })),
              textField("birth_information", "出生信息"),
              textField("occupation", "初始职业"),
              textField("personality", "初始性格", true),
              textField("growth_direction", "成长方向", true),
              ...(["goals", "flaws", "secrets"] as const).map((key) => h("label", { key },
                key === "goals" ? "目标（逐行）" : key === "flaws" ? "缺陷（逐行）" : "秘密（逐行）",
                h("textarea", {
                  value: profile[key].join("\n"),
                  onChange: (event: InputChangeEvent) => setProfile((current) => ({ ...current, [key]: lines(event.target.value) })),
                }),
              )),
              h(Button, { type: "primary", onClick: () => void saveProfile() }, "保存为新 revision"),
              h("p", { className: "anw-timeline-muted" }, "故事中发生的年龄、身份、性格、位置与知识变化会进入 StoryFact，不覆盖这份初始档案。"),
            ) : h(Empty, { description: "选择一个人物实例查看档案" }),
          ),
        ) : null,
      ),
    );
  };
}
