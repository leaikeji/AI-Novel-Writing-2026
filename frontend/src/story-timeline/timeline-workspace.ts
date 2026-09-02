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
  type StoryTimelineContext,
  type StoryTimelineLedgerDeepLink,
  type StoryTimelineLedgerSnapshot,
  type StoryTimelineLedgerSnapshotSource,
  type StoryTimelineRecord,
} from "./contracts";
import { ensureStoryTimelineStyles } from "./styles";

interface TimelineAntdRuntime extends EmbeddingAntdRuntime {}

interface KeyboardEventLike {
  readonly key: string;
  preventDefault(): void;
}

interface TimelineWorkspaceError {
  readonly kind: "conflict" | "error";
  readonly title: string;
  readonly detail: string;
}

interface RefreshOptions {
  readonly preserveError?: boolean;
  readonly announce?: boolean;
}

export interface StoryTimelineWorkspaceProps {
  readonly novelId: string;
  /** Compatibility input; W3c should also pass the opaque shared snapshot. */
  readonly initialStoryLedgerVersion: number;
  readonly ledgerSnapshot?: StoryTimelineLedgerSnapshot;
  readonly refreshKey?: string | number;
  readonly currentTimelineId?: string | null;
  readonly characters: readonly CharacterRootSummary[];
  readonly refreshLedgerSnapshot?: (
    context: StoryTimelineContext,
    signal?: AbortSignal,
  ) => Promise<StoryTimelineLedgerSnapshot>;
  readonly onTimelineContextChange?: (context: StoryTimelineContext) => void;
  readonly onLedgerSnapshotChange?: (
    snapshot: StoryTimelineLedgerSnapshot,
    source: StoryTimelineLedgerSnapshotSource,
  ) => void;
  readonly onOpenLedger?: (target: StoryTimelineLedgerDeepLink) => void;
  readonly onOpenCharacterCard?: (target: StoryTimelineCharacterCardTarget) => void;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object"
    ? value as Record<string, unknown>
    : null;
}

function isAbortLike(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function conflictLedgerVersion(reason: unknown): number | null {
  const failure = record(reason);
  const detail = record(failure?.detail);
  if (failure?.status !== 409 && detail?.code !== "version_conflict") return null;
  const current = record(detail?.current);
  const value = current?.story_ledger_version;
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1
    ? value
    : null;
}

function isConflict(reason: unknown): boolean {
  const failure = record(reason);
  const detail = record(failure?.detail);
  return failure?.status === 409
    || detail?.code === "version_conflict"
    || detail?.type === "story_ledger_version_conflict";
}

function activeTimelines(
  timelines: readonly StoryTimelineRecord[],
): readonly StoryTimelineRecord[] {
  return timelines.filter((item) => item.lifecycle_state === "active");
}

function timelineContext(
  timelines: readonly StoryTimelineRecord[],
  timeline: StoryTimelineRecord | null,
): StoryTimelineContext {
  return {
    mode: timelines.length === 0 ? "none" : timelines.length === 1 ? "single" : "multiple",
    timelineId: timeline?.id ?? null,
    timelineName: timeline?.name ?? null,
  };
}

function preferredTimeline(
  timelines: readonly StoryTimelineRecord[],
  controlledId: string | null | undefined,
  currentId: string | null,
): StoryTimelineRecord | null {
  if (!timelines.length) return null;
  if (timelines.length === 1) return timelines[0] ?? null;
  return timelines.find((item) => item.id === controlledId)
    ?? timelines.find((item) => item.id === currentId)
    ?? timelines.find((item) => item.is_primary)
    ?? timelines[0]
    ?? null;
}

function timelineFromNavigationKey(
  timelines: readonly StoryTimelineRecord[],
  currentId: string,
  key: string,
): StoryTimelineRecord | null {
  const currentIndex = timelines.findIndex((item) => item.id === currentId);
  if (currentIndex < 0 || !timelines.length) return null;
  if (key === "Home") return timelines[0] ?? null;
  if (key === "End") return timelines[timelines.length - 1] ?? null;
  if (key === "ArrowRight" || key === "ArrowDown") {
    return timelines[(currentIndex + 1) % timelines.length] ?? null;
  }
  if (key === "ArrowLeft" || key === "ArrowUp") {
    return timelines[(currentIndex - 1 + timelines.length) % timelines.length] ?? null;
  }
  return null;
}

function safeDomSegment(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "_");
}

function makeBranchKey(timelineId: string): string {
  return `branch-${safeDomSegment(timelineId)}-${Date.now().toString(36)}`;
}

export function createStoryTimelineWorkspace(
  React: EmbeddingReactRuntime,
  antd: TimelineAntdRuntime,
): (props: StoryTimelineWorkspaceProps) => unknown {
  const h = React.createElement;
  const { Alert, Button, Card, Empty, Spin, Tag } = antd;

  return function StoryTimelineWorkspace(props: StoryTimelineWorkspaceProps): unknown {
    const incomingSnapshot = props.ledgerSnapshot ?? {
      ledger_snapshot_token: null,
      story_ledger_version: props.initialStoryLedgerVersion,
    };
    const [timelines, setTimelines] = React.useState<readonly StoryTimelineRecord[]>([]);
    const [instances, setInstances] = React.useState<readonly CharacterInstanceRecord[]>([]);
    const [ledgerSnapshot, setLedgerSnapshot] = React.useState<StoryTimelineLedgerSnapshot>(
      incomingSnapshot,
    );
    const [selectedTimelineId, setSelectedTimelineId] = React.useState<string | null>(null);
    const [selectedInstanceId, setSelectedInstanceId] = React.useState<string | null>(null);
    const [branchName, setBranchName] = React.useState("");
    const [branchKey, setBranchKey] = React.useState<string | null>(null);
    const [showFork, setShowFork] = React.useState(false);
    const [refreshing, setRefreshing] = React.useState(false);
    const [mutating, setMutating] = React.useState(false);
    const [error, setError] = React.useState<TimelineWorkspaceError | null>(null);
    const [statusMessage, setStatusMessage] = React.useState("");
    const refreshGenerationRef = React.useRef(0);
    const refreshControllerRef = React.useRef<AbortController | null>(null);
    const mutationGenerationRef = React.useRef(0);
    const mutationControllerRef = React.useRef<AbortController | null>(null);
    const snapshotRef = React.useRef<StoryTimelineLedgerSnapshot>(incomingSnapshot);
    const snapshotNovelRef = React.useRef(props.novelId);
    const publishedContextRef = React.useRef("");

    const active = activeTimelines(timelines);
    const selectedTimeline = active.find((item) => item.id === selectedTimelineId)
      ?? (active.length === 1 ? active[0] ?? null : null);
    const visibleInstances = instances.filter(
      (item) => item.origin_timeline_id === selectedTimeline?.id && item.lifecycle_state === "active",
    );
    const selectedInstance = visibleInstances.find((item) => item.id === selectedInstanceId) ?? null;
    const characterNames = new Map(props.characters.map((item) => [item.id, item.name]));
    const advanced = active.length > 1;
    const busy = refreshing || mutating;
    const baseId = `anw-timeline-${safeDomSegment(props.novelId)}`;

    const publishContext = (
      rows: readonly StoryTimelineRecord[],
      selected: StoryTimelineRecord | null,
    ): void => {
      const context = timelineContext(rows, selected);
      const key = `${context.mode}:${context.timelineId ?? ""}:${context.timelineName ?? ""}`;
      if (publishedContextRef.current === key) return;
      publishedContextRef.current = key;
      props.onTimelineContextChange?.(context);
    };

    const observeSnapshot = (
      snapshot: StoryTimelineLedgerSnapshot,
      source: StoryTimelineLedgerSnapshotSource,
    ): void => {
      if (snapshotNovelRef.current !== props.novelId) {
        snapshotNovelRef.current = props.novelId;
        snapshotRef.current = snapshot;
      } else if (snapshot.story_ledger_version < snapshotRef.current.story_ledger_version) {
        return;
      } else if (
        snapshot.story_ledger_version === snapshotRef.current.story_ledger_version
        && snapshot.ledger_snapshot_token === snapshotRef.current.ledger_snapshot_token
      ) {
        return;
      } else if (
        snapshot.story_ledger_version === snapshotRef.current.story_ledger_version
        && snapshot.ledger_snapshot_token === null
        && snapshotRef.current.ledger_snapshot_token !== null
      ) {
        return;
      } else {
        snapshotRef.current = snapshot;
      }
      setLedgerSnapshot(snapshotRef.current);
      props.onLedgerSnapshotChange?.(snapshotRef.current, source);
    };

    const activateTimeline = (
      timeline: StoryTimelineRecord,
      focus: boolean,
    ): void => {
      setSelectedTimelineId(timeline.id);
      setSelectedInstanceId(null);
      publishContext(active, timeline);
      if (focus && typeof document !== "undefined") {
        const moveFocus = (): void => {
          document.getElementById(`${baseId}-tab-${safeDomSegment(timeline.id)}`)?.focus();
        };
        if (typeof queueMicrotask === "function") queueMicrotask(moveFocus);
        else moveFocus();
      }
    };

    const refresh = async (options: RefreshOptions = {}): Promise<void> => {
      const generation = ++refreshGenerationRef.current;
      refreshControllerRef.current?.abort();
      const controller = new AbortController();
      refreshControllerRef.current = controller;
      if (!options.preserveError) setError(null);
      setRefreshing(true);
      try {
        const [timelineResource, instanceRows] = await Promise.all([
          listStoryTimelines(props.novelId, controller.signal),
          listCharacterInstances(props.novelId, controller.signal),
        ]);
        if (generation !== refreshGenerationRef.current || controller.signal.aborted) return;
        const nextActive = activeTimelines(timelineResource.items);
        const nextTimeline = preferredTimeline(
          nextActive,
          props.currentTimelineId,
          selectedTimelineId,
        );
        setTimelines(timelineResource.items);
        setInstances(instanceRows);
        setSelectedTimelineId(nextTimeline?.id ?? null);
        setSelectedInstanceId((current) => current
          && instanceRows.some((item) => (
            item.id === current
            && item.origin_timeline_id === nextTimeline?.id
            && item.lifecycle_state === "active"
          ))
          ? current
          : null);
        const nextContext = timelineContext(nextActive, nextTimeline);
        publishContext(nextActive, nextTimeline);
        if (props.refreshLedgerSnapshot && nextContext.timelineId) {
          const refreshedSnapshot = await props.refreshLedgerSnapshot(
            nextContext,
            controller.signal,
          );
          if (generation !== refreshGenerationRef.current || controller.signal.aborted) return;
          observeSnapshot(refreshedSnapshot, "refresh");
        }
        if (options.announce) setStatusMessage("时间线与账本快照已刷新");
      } catch (reason) {
        if (generation !== refreshGenerationRef.current || isAbortLike(reason)) return;
        setError({
          kind: "error",
          title: "时间线加载失败",
          detail: apiErrorMessage(reason, "加载时间线失败"),
        });
      } finally {
        if (generation === refreshGenerationRef.current) setRefreshing(false);
      }
    };

    const openFork = (): void => {
      if (!selectedTimeline) return;
      setBranchKey((current) => current ?? makeBranchKey(selectedTimeline.id));
      setShowFork(true);
      setError(null);
    };

    const cancelFork = (): void => {
      mutationControllerRef.current?.abort();
      mutationGenerationRef.current += 1;
      setShowFork(false);
      setBranchName("");
      setBranchKey(null);
      setError(null);
    };

    const fork = async (): Promise<void> => {
      const trimmedName = branchName.trim();
      if (!selectedTimeline || !trimmedName) return;
      const stableBranchKey = branchKey ?? makeBranchKey(selectedTimeline.id);
      if (!branchKey) setBranchKey(stableBranchKey);
      const generation = ++mutationGenerationRef.current;
      mutationControllerRef.current?.abort();
      const controller = new AbortController();
      mutationControllerRef.current = controller;
      setMutating(true);
      setError(null);
      setStatusMessage("");
      try {
        const result = await forkStoryTimeline(props.novelId, selectedTimeline.id, {
          expected_story_ledger_version: ledgerSnapshot.story_ledger_version,
          expected_source_timeline_version: selectedTimeline.version,
          timeline_key: stableBranchKey,
          name: trimmedName,
          fork_story_sequence: 0,
          fork_anchor: { source: "author_workspace" },
        }, controller.signal);
        if (generation !== mutationGenerationRef.current || controller.signal.aborted) return;
        observeSnapshot({
          ledger_snapshot_token: null,
          story_ledger_version: result.story_ledger_version,
        }, "mutation");
        setBranchName("");
        setBranchKey(null);
        setShowFork(false);
        await refresh();
        if (generation !== mutationGenerationRef.current || controller.signal.aborted) return;
        setTimelines((current) => current.some((item) => item.id === result.timeline.id)
          ? current
          : [...current, result.timeline].sort((left, right) => (
            left.position - right.position || left.id.localeCompare(right.id)
          )));
        setInstances((current) => {
          const known = new Set(current.map((item) => item.id));
          return [
            ...current,
            ...result.derived_instances.filter((item) => !known.has(item.id)),
          ];
        });
        setSelectedTimelineId(result.timeline.id);
        publishContext(
          activeTimelines([...timelines, result.timeline]),
          result.timeline,
        );
        setStatusMessage(`已创建时间线分支“${result.timeline.name}”`);
      } catch (reason) {
        if (generation !== mutationGenerationRef.current || isAbortLike(reason)) return;
        if (isConflict(reason)) {
          const currentVersion = conflictLedgerVersion(reason);
          if (currentVersion !== null) {
            observeSnapshot({
              ledger_snapshot_token: null,
              story_ledger_version: currentVersion,
            }, "conflict");
          }
          setError({
            kind: "conflict",
            title: "时间线或账本已更新",
            detail: "已刷新时间线范围。你输入的分支名已保留，请核对后重试。",
          });
          await refresh({ preserveError: true });
        } else {
          setError({
            kind: "error",
            title: "创建时间线分支失败",
            detail: apiErrorMessage(reason, "创建时间线分支失败"),
          });
        }
      } finally {
        if (generation === mutationGenerationRef.current) setMutating(false);
      }
    };

    React.useEffect(() => {
      ensureStoryTimelineStyles();
    }, []);

    React.useEffect(() => {
      if (snapshotNovelRef.current !== props.novelId) {
        snapshotNovelRef.current = props.novelId;
        snapshotRef.current = incomingSnapshot;
        setLedgerSnapshot(incomingSnapshot);
        publishedContextRef.current = "";
        setSelectedTimelineId(null);
        setSelectedInstanceId(null);
        setBranchName("");
        setBranchKey(null);
        setShowFork(false);
      } else if (
        incomingSnapshot.story_ledger_version > snapshotRef.current.story_ledger_version
        || (
          incomingSnapshot.story_ledger_version === snapshotRef.current.story_ledger_version
          && incomingSnapshot.ledger_snapshot_token !== null
          && incomingSnapshot.ledger_snapshot_token !== snapshotRef.current.ledger_snapshot_token
        )
      ) {
        snapshotRef.current = incomingSnapshot;
        setLedgerSnapshot(incomingSnapshot);
      }
    }, [
      props.novelId,
      incomingSnapshot.story_ledger_version,
      incomingSnapshot.ledger_snapshot_token,
    ]);

    React.useEffect(() => {
      void refresh();
      return () => {
        refreshGenerationRef.current += 1;
        refreshControllerRef.current?.abort();
      };
    }, [props.novelId, props.refreshKey]);

    React.useEffect(() => () => {
      mutationGenerationRef.current += 1;
      mutationControllerRef.current?.abort();
    }, [props.novelId]);

    React.useEffect(() => {
      if (!props.currentTimelineId || !active.length) return;
      const controlled = active.find((item) => item.id === props.currentTimelineId);
      if (controlled && controlled.id !== selectedTimelineId) {
        activateTimeline(controlled, false);
      }
    }, [props.currentTimelineId, timelines]);

    const onTimelineKeyDown = (
      timeline: StoryTimelineRecord,
      event: KeyboardEventLike,
    ): void => {
      const next = timelineFromNavigationKey(active, timeline.id, event.key);
      if (!next) return;
      event.preventDefault();
      activateTimeline(next, true);
    };

    const openLedger = (): void => {
      if (!selectedTimeline) return;
      props.onOpenLedger?.({
        section: "ledger",
        ledger_timeline: selectedTimeline.id,
      });
    };

    const selectedTabId = selectedTimeline
      ? `${baseId}-tab-${safeDomSegment(selectedTimeline.id)}`
      : null;
    const selectedPanelId = selectedTimeline
      ? `${baseId}-panel-${safeDomSegment(selectedTimeline.id)}`
      : null;

    return h(
      Spin,
      { spinning: busy },
      h("section", { className: "anw-timeline-workspace", "aria-label": "时间线与人物实例" },
        error ? h(Alert, {
          type: error.kind === "conflict" ? "warning" : "error",
          showIcon: true,
          message: error.title,
          description: error.detail,
        }) : null,
        statusMessage ? h("p", {
          className: "anw-timeline-status",
          role: "status",
          "aria-live": "polite",
        }, statusMessage) : null,
        h(Card, null,
          h("div", { className: "anw-timeline-header" },
            h("div", null,
              h("h3", null, "时间线"),
              h(Tag, { color: advanced ? "blue" : "green" }, advanced ? "多时间线模式" : "单时间线默认"),
              h("p", { className: "anw-timeline-muted" }, advanced
                ? "章节、关系与状态读取使用当前明确选中的时间线。"
                : "普通写作自动使用主线，无需增加任何步骤。"),
            ),
            h("div", { className: "anw-timeline-header-actions" },
              h(Button, {
                disabled: !selectedTimeline || !props.onOpenLedger,
                onClick: openLedger,
              }, "查看本线账本"),
              h(Button, { onClick: () => void refresh({ announce: true }) }, "刷新"),
              h(Button, {
                disabled: !selectedTimeline,
                onClick: openFork,
              }, advanced ? "新建分支" : "创建第二条时间线"),
            ),
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
              h(Button, {
                type: "primary",
                disabled: !branchName.trim() || busy,
                onClick: () => void fork(),
              }, "确认创建"),
              h(Button, { disabled: busy, onClick: cancelFork }, "取消"),
            ),
          ) : null,
          advanced ? h("div", {
            className: "anw-timeline-list",
            role: "tablist",
            "aria-label": "时间线切换",
            "aria-orientation": "horizontal",
          },
          ...active.map((item) => {
            const tabId = `${baseId}-tab-${safeDomSegment(item.id)}`;
            const panelId = `${baseId}-panel-${safeDomSegment(item.id)}`;
            const selected = item.id === selectedTimeline?.id;
            return h(
              "button",
              {
                key: item.id,
                id: tabId,
                type: "button",
                role: "tab",
                "aria-selected": selected,
                "aria-controls": panelId,
                tabIndex: selected ? 0 : -1,
                onClick: () => activateTimeline(item, false),
                onKeyDown: (event: KeyboardEventLike) => onTimelineKeyDown(item, event),
              },
              item.name,
            );
          })) : null,
        ),
        advanced && selectedTimeline ? h("div", {
          id: selectedPanelId,
          className: "anw-timeline-grid",
          role: "tabpanel",
          "aria-labelledby": selectedTabId,
          tabIndex: 0,
        },
        h(Card, { title: "本线人物实例" },
          visibleInstances.length ? h("div", { className: "anw-instance-list" },
            ...visibleInstances.map((item) => h("button", {
              key: item.id,
              type: "button",
              "aria-pressed": item.id === selectedInstanceId,
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
                timelineId: selectedTimeline.id,
                instanceId: selectedInstance.id,
              }),
            }, "打开正式人物卡"),
            h("p", { className: "anw-timeline-muted" }, "身份、出生资料、目标、秘密与成长方向统一在正式人物卡中维护。"),
          ) : h(Empty, { description: "选择一个人物实例查看摘要" }),
        )) : null,
      ),
    );
  };
}
