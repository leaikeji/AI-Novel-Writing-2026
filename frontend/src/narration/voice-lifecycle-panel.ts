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
  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void];
  useEffect(
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ): void;
}


export interface VoiceLifecyclePanelProps {
  /** Fail-closed feature gate. Omitting this prop renders no deletion UI. */
  readonly capabilityEnabled?: boolean;
  readonly profile: VoiceLifecycleProfile;
  readonly request?: VoiceDeletionRequestSnapshot | null;
  readonly busyAction?: VoiceLifecycleBusyAction | null;
  readonly errorMessage?: string | null;
  /** A server-aligned time can be supplied to avoid relying on the browser clock. */
  readonly nowEpochMs?: number;
  readonly className?: string;
  readonly onDiscardUnreferenced: (command: VoiceLifecycleProfileCommand) => void;
  readonly onRequestReferencedDeletion: (command: VoiceLifecycleProfileCommand) => void;
  readonly onConfirmDeletion: (command: VoiceLifecycleConfirmCommand) => void;
  readonly onCancelDeletion: (requestId: string) => void;
  readonly onRetryDeletion: (requestId: string) => void;
}


interface ConfirmationDraft {
  readonly scope: string;
  readonly value: string;
}


interface ValueChangeEvent {
  readonly target: { readonly value: string };
}


const SOURCE_LABELS: Readonly<Record<VoiceLifecycleProfile["sourceType"], string>> = {
  uploaded: "参考录音音色",
  generated: "描述生成音色",
};


const BUSY_LABELS: Readonly<Record<VoiceLifecycleBusyAction, string>> = {
  discard: "正在创建可撤销删除…",
  request: "正在冻结删除影响…",
  confirm: "正在确认删除…",
  cancel: "正在撤销删除…",
  retry: "正在重试删除…",
};


function classNames(...values: readonly (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}


function confirmationScope(
  profile: VoiceLifecycleProfile,
  request: VoiceDeletionRequestSnapshot | null,
): string {
  return `${profile.profileId}:${request?.requestId ?? "idle"}`;
}


function impactRows(
  impact: VoiceDeletionImpactSnapshot,
): readonly Readonly<{ label: string; value: string }>[] {
  return Object.freeze([
    { label: "音色版本", value: `${impact.voiceVersionCount}` },
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
    {
      className: "anw-voice-lifecycle__impact",
      "aria-labelledby": headingId,
    },
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
    const scope = confirmationScope(props.profile, request);
    const [confirmationDraft, setConfirmationDraft] = React.useState<ConfirmationDraft>({
      scope,
      value: "",
    });
    const [clockEpochMs, setClockEpochMs] = React.useState(() => Date.now());
    const confirmationText = confirmationDraft.scope === scope
      ? confirmationDraft.value
      : "";

    React.useEffect(() => {
      if (
        props.capabilityEnabled !== true
        || props.nowEpochMs !== undefined
        || request?.state !== "grace_pending"
      ) return;
      setClockEpochMs(Date.now());
      const interval = globalThis.setInterval(() => setClockEpochMs(Date.now()), 250);
      return () => globalThis.clearInterval(interval);
    }, [props.capabilityEnabled, props.nowEpochMs, request?.requestId, request?.state]);

    const view = deriveVoiceLifecycleState({
      capabilityEnabled: props.capabilityEnabled,
      profile: props.profile,
      request,
      nowEpochMs: props.nowEpochMs ?? clockEpochMs,
      confirmationText,
      busyAction: props.busyAction,
    });

    if (!view.visible) return null;

    const inputId = `anw-voice-lifecycle-confirm-${props.profile.profileId}`;
    const descriptionId = `${inputId}-description`;
    const impactHeadingId = (
      `anw-voice-lifecycle-impact-${request?.requestId ?? props.profile.profileId}`
    );
    const actions: unknown[] = [];

    if (view.canDiscardUnreferenced || view.phase === "idle-unreferenced") {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button is-danger",
          disabled: !view.canDiscardUnreferenced,
          onClick: () => props.onDiscardUnreferenced(
            voiceLifecycleProfileCommand(props.profile),
          ),
        },
        props.busyAction === "discard" ? BUSY_LABELS.discard : "删除音色",
      ));
    }

    if (view.canRequestReferencedDeletion || view.phase === "idle-referenced") {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button is-danger",
          disabled: !view.canRequestReferencedDeletion,
          onClick: () => props.onRequestReferencedDeletion(
            voiceLifecycleProfileCommand(props.profile),
          ),
        },
        props.busyAction === "request" ? BUSY_LABELS.request : "查看删除影响",
      ));
    }

    if (
      request
      && view.phase === "grace_pending"
      && view.undoRemainingSeconds !== null
      && view.undoRemainingSeconds > 0
    ) {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button",
          disabled: !view.canCancel,
          onClick: () => props.onCancelDeletion(request.requestId),
        },
        props.busyAction === "cancel" ? BUSY_LABELS.cancel : "撤销删除",
      ));
    }

    if (request && view.phase === "requested") {
      actions.push(
        h(
          "button",
          {
            type: "button",
            className: "anw-voice-lifecycle__button",
            disabled: !view.canCancel,
            onClick: () => props.onCancelDeletion(request.requestId),
          },
          props.busyAction === "cancel" ? BUSY_LABELS.cancel : "取消删除计划",
        ),
        h(
          "button",
          {
            type: "button",
            className: "anw-voice-lifecycle__button is-danger",
            disabled: !view.canConfirm,
            onClick: () => props.onConfirmDeletion(voiceLifecycleConfirmCommand(request)),
          },
          props.busyAction === "confirm" ? BUSY_LABELS.confirm : "确认删除音色",
        ),
      );
    }

    if (request && view.phase === "failed" && request.confirmedAt !== null) {
      actions.push(h(
        "button",
        {
          type: "button",
          className: "anw-voice-lifecycle__button is-danger",
          disabled: !view.canRetry,
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
      request && view.phase === "requested"
        ? h(
          "div",
          { className: "anw-voice-lifecycle__confirmation" },
          h("label", { htmlFor: inputId }, `输入音色名称“${props.profile.displayName}”以确认`),
          h(
            "p",
            { id: descriptionId },
            "名称必须完全一致。确认后将进入不可撤销的物理删除阶段。",
          ),
          h("input", {
            id: inputId,
            type: "text",
            value: confirmationText,
            autoComplete: "off",
            spellCheck: false,
            "aria-describedby": descriptionId,
            disabled: view.busy,
            onChange: (event: ValueChangeEvent) => setConfirmationDraft({
              scope,
              value: event.target.value,
            }),
          }),
        )
        : null,
      request ? createRequestNotice(React, request) : null,
      actions.length > 0
        ? h("div", { className: "anw-voice-lifecycle__actions" }, ...actions)
        : null,
    );
  };
}
