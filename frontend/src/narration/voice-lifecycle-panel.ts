import {
  deriveVoiceLifecycleState,
  externalBackupStatusMessage,
  formatVoiceLifecycleBytes,
  voiceLifecycleConfirmCommand,
  voiceLifecycleProfileCommand,
  type VoiceDeletionImpactSnapshot,
  type VoiceDeletionRequestSnapshot,
  type VoiceLifecycleBusyAction,
  type VoiceLifecycleConfirmCommand,
  type VoiceLifecycleProfile,
  type VoiceLifecycleProfileCommand,
} from "./voice-lifecycle-state";

export interface VoiceLifecycleReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
}

export interface VoiceLifecyclePanelProps {
  /** Fail-closed feature gate. Omitting this prop renders no deletion UI. */
  readonly capabilityEnabled?: boolean;
  readonly profile: VoiceLifecycleProfile;
  readonly request?: VoiceDeletionRequestSnapshot | null;
  readonly busyAction?: VoiceLifecycleBusyAction | null;
  readonly errorMessage?: string | null;
  /** Injectable browser time for tests. It is never treated as server wall time. */
  readonly nowEpochMs?: number;
  /** Browser time at which request.serverNow was observed. */
  readonly serverNowObservedAtEpochMs?: number;
  readonly className?: string;
  readonly onCreateDeletionRequest: (command: VoiceLifecycleProfileCommand) => void;
  readonly onConfirmDeletion: (command: VoiceLifecycleConfirmCommand) => void;
  readonly onCancelDeletion: (requestId: string) => void;
  readonly onRetryDeletion: (requestId: string) => void;
  /** Reloads the authoritative list after a superseded request releases its slot. */
  readonly onReloadLifecycle: () => void;
}

interface ClockSnapshot {
  readonly scope: string;
  readonly observedAtEpochMs: number;
  readonly nowEpochMs: number;
}

const SOURCE_LABELS: Readonly<Record<VoiceLifecycleProfile["sourceType"], string>> = {
  uploaded: "参考录音音色",
  generated: "生成音色",
};

const BUSY_LABELS: Readonly<Record<VoiceLifecycleBusyAction, string>> = {
  create: "正在创建删除计划…",
  confirm: "正在确认删除…",
  cancel: "正在撤销删除…",
  retry: "正在重试删除…",
};

function classNames(...values: readonly (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}

function requestClockScope(request: VoiceDeletionRequestSnapshot | null): string {
  return request ? `${request.requestId}:${request.serverNow}` : "idle";
}

function impactRows(
  impact: VoiceDeletionImpactSnapshot,
): readonly Readonly<{ label: string; value: string }>[] {
  return Object.freeze([
    { label: "音色版本", value: `${impact.voiceVersionIds.length}` },
    { label: "当前旁白", value: `${impact.currentNarratorCount}` },
    { label: "人物绑定", value: `${impact.characterBindingCount}` },
    { label: "匿名说话人", value: `${impact.anonymousSpeakerCount}` },
    { label: "通用角色槽位", value: `${impact.genericSlotCount}` },
    { label: "历史朗读版本", value: `${impact.historicalEditionCount}` },
    { label: "已渲染音频", value: `${impact.renderCount}` },
    { label: "导出记录", value: `${impact.exportCount}` },
    {
      label: "项目管理文件",
      value: `${impact.assetCount} 个 · ${formatVoiceLifecycleBytes(impact.totalBytes)}`,
    },
    { label: "活动任务", value: `${impact.activeJobCount}` },
  ]);
}

function createImpactSummary(
  React: VoiceLifecycleReactRuntime,
  impact: VoiceDeletionImpactSnapshot,
  headingId: string,
): unknown {
  const h = React.createElement;
  const consequence = impact.historicalAudioConsequence === "unavailable_private_voice_deleted"
    ? "删除后，历史朗读会保留冻结的音色身份记录，但相关私人音色资源将不可用。"
    : "请核对以下冻结影响后再确认删除。";
  return h(
    "section",
    { className: "anw-voice-lifecycle__impact", "aria-labelledby": headingId },
    h("h4", { id: headingId }, "冻结的删除影响"),
    h(
      "dl",
      { className: "anw-voice-lifecycle__impact-grid" },
      ...impactRows(impact).map((row) => h(
        "div",
        { className: "anw-voice-lifecycle__impact-row", key: row.label },
        h("dt", null, row.label),
        h("dd", null, row.value),
      )),
    ),
    h("p", { className: "anw-voice-lifecycle__consequence" }, consequence),
  );
}

function createRequestNotice(
  React: VoiceLifecycleReactRuntime,
  request: VoiceDeletionRequestSnapshot,
): unknown {
  return React.createElement(
    "aside",
    {
      className: classNames(
        "anw-voice-lifecycle__backup",
        request.externalBackupStatus === "unmanaged" && "is-unmanaged",
      ),
      "data-backup-status": request.externalBackupStatus,
      "aria-label": "外部备份说明",
    },
    externalBackupStatusMessage(request.externalBackupStatus),
  );
}

export function createVoiceLifecyclePanel(
  React: VoiceLifecycleReactRuntime,
): (props: VoiceLifecyclePanelProps) => unknown {
  const h = React.createElement;

  return function VoiceLifecyclePanel(props: VoiceLifecyclePanelProps): unknown {
    const request = props.request ?? null;
    const clockScope = requestClockScope(request);
    const initialNow = props.nowEpochMs ?? Date.now();
    const [clock, setClock] = React.useState<ClockSnapshot>(() => ({
      scope: clockScope,
      observedAtEpochMs: props.serverNowObservedAtEpochMs ?? initialNow,
      nowEpochMs: initialNow,
    }));
    const currentClock = clock.scope === clockScope
      ? clock
      : {
        scope: clockScope,
        observedAtEpochMs: props.serverNowObservedAtEpochMs ?? initialNow,
        nowEpochMs: initialNow,
      };

    React.useEffect(() => {
      const now = props.nowEpochMs ?? Date.now();
      setClock({
        scope: clockScope,
        observedAtEpochMs: props.serverNowObservedAtEpochMs ?? now,
        nowEpochMs: now,
      });
      if (
        props.capabilityEnabled !== true
        || props.nowEpochMs !== undefined
        || request === null
        || !["grace_pending", "requested", "failed"].includes(request.state)
      ) return;
      const interval = globalThis.setInterval(() => {
        setClock((current) => ({ ...current, nowEpochMs: Date.now() }));
      }, 250);
      return () => globalThis.clearInterval(interval);
    }, [
      props.capabilityEnabled,
      props.nowEpochMs,
      props.serverNowObservedAtEpochMs,
      clockScope,
      request?.state,
    ]);

    React.useEffect(() => {
      if (props.capabilityEnabled === true && request?.state === "superseded") {
        props.onReloadLifecycle();
      }
    }, [props.capabilityEnabled, request?.requestId, request?.state]);

    const elapsedSinceServerNowMs = Math.max(
      0,
      (props.nowEpochMs ?? currentClock.nowEpochMs)
        - (props.serverNowObservedAtEpochMs ?? currentClock.observedAtEpochMs),
    );
    const view = deriveVoiceLifecycleState({
      capabilityEnabled: props.capabilityEnabled,
      profile: props.profile,
      request,
      elapsedSinceServerNowMs,
      busyAction: props.busyAction,
    });

    if (!view.visible) return null;

    const impactHeadingId = `anw-voice-lifecycle-impact-${request?.requestId ?? props.profile.profileId}`;
    const actions: unknown[] = [];

    if (view.canCreateDeletionRequest || view.phase === "idle-unreferenced" || view.phase === "idle-referenced") {
      const referenced = view.phase === "idle-referenced";
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button is-danger",
          disabled: !view.canCreateDeletionRequest,
          onClick: () => props.onCreateDeletionRequest(voiceLifecycleProfileCommand(props.profile)),
        },
        props.busyAction === "create"
          ? BUSY_LABELS.create
          : referenced ? "查看删除影响" : "删除音色",
      ));
    }

    if (request && view.canCancel) {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button",
          disabled: view.busy,
          onClick: () => props.onCancelDeletion(request.requestId),
        },
        props.busyAction === "cancel"
          ? BUSY_LABELS.cancel
          : view.phase === "requested" ? "取消删除计划" : "撤销删除",
      ));
    }

    if (request && view.phase === "requested") {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button is-danger",
          disabled: !view.canConfirm,
          onClick: () => props.onConfirmDeletion(voiceLifecycleConfirmCommand(request)),
        },
        props.busyAction === "confirm" ? BUSY_LABELS.confirm : "确认删除音色",
      ));
    }

    if (request && view.canRetry) {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button is-danger",
          disabled: view.busy,
          onClick: () => props.onRetryDeletion(request.requestId),
        },
        props.busyAction === "retry" ? BUSY_LABELS.retry : "重试删除",
      ));
    }

    return h(
      "section",
      {
        className: classNames("anw-voice-lifecycle", props.className),
        "data-phase": view.phase,
        "data-tone": view.tone,
        "aria-label": `私人音色“${props.profile.displayName}”删除管理`,
        "aria-busy": view.busy || undefined,
      },
      h(
        "header",
        { className: "anw-voice-lifecycle__header" },
        h(
          "div",
          null,
          h("p", { className: "anw-voice-lifecycle__eyebrow" }, "私人音色删除"),
          h("h3", null, props.profile.displayName),
        ),
        h("span", { className: "anw-voice-lifecycle__source" }, SOURCE_LABELS[props.profile.sourceType]),
      ),
      h(
        "p",
        {
          className: classNames("anw-voice-lifecycle__status", `is-${view.tone}`),
          role: "status",
          "aria-live": "polite",
        },
        props.busyAction ? BUSY_LABELS[props.busyAction] : view.statusLabel,
      ),
      props.errorMessage
        ? h("p", { className: "anw-voice-lifecycle__error", role: "alert" }, props.errorMessage)
        : null,
      request && view.phase === "grace_pending"
        ? h(
          "p",
          { className: "anw-voice-lifecycle__countdown" },
          view.undoRemainingSeconds !== null && view.undoRemainingSeconds > 0
            ? h("time", null, `剩余 ${view.undoRemainingSeconds} 秒可撤销`)
            : "撤销窗口已关闭",
        )
        : null,
      request && view.phase === "requested"
        ? createImpactSummary(React, request.impact, impactHeadingId)
        : null,
      request ? createRequestNotice(React, request) : null,
      actions.length > 0
        ? h("div", { className: "anw-voice-lifecycle__actions" }, ...actions)
        : null,
    );
  };
}
