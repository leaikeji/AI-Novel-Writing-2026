export const VOICE_PREPARATION_CONTRACT_VERSION = "narration-voice-preparation/1" as const;

export const VOICE_PREPARATION_STATES = [
  "reserved",
  "preparing",
  "ready",
  "ready_with_warnings",
  "failed",
  "cancelled",
  "superseded",
] as const;

export type VoicePreparationState = typeof VOICE_PREPARATION_STATES[number];

export type VoicePreparationTargetState =
  | "pending"
  | "preserved"
  | "queued"
  | "generating"
  | "ready_applied"
  | "ready_unapplied"
  | "fallback_official"
  | "failed"
  | "cancelled";

export interface VoicePreparationTargetSummary {
  readonly characterId: string;
  readonly characterName: string;
  readonly state: VoicePreparationTargetState;
}

/**
 * Narrow UI projection of `narration-voice-preparation/1`.
 * Wire parsing and snake-case mapping remain owned by the shared contracts adapter.
 */
export interface VoicePreparationSnapshot {
  readonly contractVersion: typeof VOICE_PREPARATION_CONTRACT_VERSION;
  readonly commandId: string;
  readonly state: VoicePreparationState;
  readonly serverNow: string;
  readonly progressCurrent: number;
  readonly progressTotal: number;
  readonly preflightRequestId: string | null;
  readonly preflightScriptVersionId: string | null;
  readonly chapterReady: boolean;
  readonly backgroundRemaining: number;
  readonly continuationState: string | null;
  readonly narrationRequestId: string | null;
  readonly currentTarget: VoicePreparationTargetSummary | null;
  readonly preserved: readonly VoicePreparationTargetSummary[];
  readonly generated: readonly VoicePreparationTargetSummary[];
  readonly fallback: readonly VoicePreparationTargetSummary[];
  readonly failed: readonly VoicePreparationTargetSummary[];
  readonly cancellable: boolean;
  readonly retryable: boolean;
  readonly terminal: boolean;
  readonly failureCode: string | null;
  readonly updatedAt: string;
}

export type VoicePreparationBusyAction = "load" | "refresh" | "start" | "retry" | "cancel";
export type VoicePreparationPrimaryAction = "start" | "retry" | "cancel" | "reload" | null;

export interface VoicePreparationViewState {
  readonly visible: boolean;
  readonly valid: boolean;
  readonly phase: "hidden" | "idle" | "loading" | "load_error" | "invalid" | VoicePreparationState;
  readonly tone: "neutral" | "progress" | "success" | "warning" | "danger";
  readonly statusLabel: string;
  readonly detail: string | null;
  readonly progressLabel: string | null;
  readonly progressValue: number | null;
  readonly progressMaximum: number | null;
  readonly primaryAction: VoicePreparationPrimaryAction;
  readonly primaryLabel: string | null;
  readonly primaryDisabled: boolean;
  readonly busy: boolean;
  readonly terminal: boolean;
}

export interface DeriveVoicePreparationStateInput {
  readonly capabilityEnabled?: boolean;
  readonly canConfigure?: boolean;
  readonly loadPhase?: "ready" | "loading" | "error";
  readonly command?: VoicePreparationSnapshot | null;
  readonly busyAction?: VoicePreparationBusyAction | null;
  readonly loadError?: string | null;
}

export interface VoicePreparationReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
  useRef<T>(initial: T): { current: T };
}

export interface VoicePreparationProps {
  /** New commands and retries fail closed; durable commands remain readable and cancellable. */
  readonly capabilityEnabled?: boolean;
  readonly canConfigure?: boolean;
  readonly initialCommand?: VoicePreparationSnapshot | null;
  readonly className?: string;
  readonly presentation?: "card" | "player-inline";
  readonly refreshIntervalMs?: number;
  readonly onLoadLatest?: (signal: AbortSignal) => Promise<VoicePreparationSnapshot | null>;
  readonly onStart?: () => Promise<VoicePreparationSnapshot>;
  readonly onRefresh: (
    commandId: string,
    signal: AbortSignal,
  ) => Promise<VoicePreparationSnapshot>;
  readonly onRetry: (commandId: string) => Promise<VoicePreparationSnapshot>;
  readonly onCancel: (commandId: string) => Promise<VoicePreparationSnapshot>;
  readonly onCommandChanged?: (command: VoicePreparationSnapshot) => void;
}

interface LocalVoicePreparationState {
  readonly loadPhase: "ready" | "loading" | "error";
  readonly command: VoicePreparationSnapshot | null;
  readonly busyAction: VoicePreparationBusyAction | null;
  readonly errorMessage: string | null;
}

const STATE_SET = new Set<string>(VOICE_PREPARATION_STATES);
const ACTIVE_STATES = new Set<VoicePreparationState>(["reserved", "preparing"]);
const TERMINAL_STATES = new Set<VoicePreparationState>([
  "ready",
  "ready_with_warnings",
  "failed",
  "cancelled",
  "superseded",
]);

function nonEmpty(value: string): boolean {
  return value.trim().length > 0;
}

function validTimestamp(value: string): boolean {
  return value.includes("T") && Number.isFinite(Date.parse(value));
}

function validCount(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0;
}

function targetIsValid(target: VoicePreparationTargetSummary): boolean {
  return nonEmpty(target.characterId)
    && nonEmpty(target.characterName)
    && [
      "pending",
      "preserved",
      "queued",
      "generating",
      "ready_applied",
      "ready_unapplied",
      "fallback_official",
      "failed",
      "cancelled",
    ].includes(target.state);
}

export function voicePreparationSnapshotIsValid(command: VoicePreparationSnapshot): boolean {
  if (
    command.contractVersion !== VOICE_PREPARATION_CONTRACT_VERSION
    || !nonEmpty(command.commandId)
    || !STATE_SET.has(command.state)
    || !validTimestamp(command.serverNow)
    || !validTimestamp(command.updatedAt)
    || !validCount(command.progressCurrent)
    || !validCount(command.progressTotal)
    || command.progressCurrent > command.progressTotal
    || !validCount(command.backgroundRemaining)
    || (command.preflightRequestId !== null && !nonEmpty(command.preflightRequestId))
    || (command.preflightScriptVersionId !== null && !nonEmpty(command.preflightScriptVersionId))
    || (command.continuationState !== null && !nonEmpty(command.continuationState))
    || (command.narrationRequestId !== null && !nonEmpty(command.narrationRequestId))
    || (command.currentTarget !== null && !targetIsValid(command.currentTarget))
    || ![...command.preserved, ...command.generated, ...command.fallback, ...command.failed]
      .every(targetIsValid)
  ) return false;

  if (ACTIVE_STATES.has(command.state)) {
    return !command.terminal && !command.retryable && command.failureCode === null;
  }
  if (!TERMINAL_STATES.has(command.state) || !command.terminal || command.cancellable) return false;
  if (command.state === "ready" || command.state === "ready_with_warnings") {
    return command.failureCode === null && !command.retryable;
  }
  if (command.state === "failed") {
    return command.failureCode !== null && nonEmpty(command.failureCode);
  }
  return command.failureCode === null || nonEmpty(command.failureCode);
}

function freezeView(values: VoicePreparationViewState): VoicePreparationViewState {
  return Object.freeze(values);
}

function busyLabel(action: VoicePreparationBusyAction): string {
  if (action === "load" || action === "refresh") return "正在恢复人物声音准备进度…";
  if (action === "start") return "正在创建人物声音准备任务…";
  if (action === "retry") return "正在重新开始人物声音准备…";
  return "正在取消后续人物声音准备…";
}

function completionDetail(command: VoicePreparationSnapshot): string {
  const parts: string[] = [];
  if (command.generated.length > 0) parts.push(`${command.generated.length} 个专属音色`);
  if (command.fallback.length > 0) parts.push(`${command.fallback.length} 个官方兜底`);
  if (command.preserved.length > 0) parts.push(`${command.preserved.length} 个现有音色保留`);
  if (command.failed.length > 0) parts.push(`${command.failed.length} 个人物未完成`);
  return parts.length > 0 ? parts.join("、") : "人物声音准备已完成";
}

export function deriveVoicePreparationState(
  input: DeriveVoicePreparationStateInput,
): VoicePreparationViewState {
  const command = input.command ?? null;
  const capabilityEnabled = input.capabilityEnabled === true;
  const configurable = capabilityEnabled && input.canConfigure !== false;
  const busyAction = input.busyAction ?? null;

  if (!capabilityEnabled && command === null && input.loadPhase !== "loading") {
    return freezeView({
      visible: false,
      valid: true,
      phase: "hidden",
      tone: "neutral",
      statusLabel: "人物声音自动准备未开放",
      detail: null,
      progressLabel: null,
      progressValue: null,
      progressMaximum: null,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: false,
      terminal: false,
    });
  }
  if (busyAction !== null) {
    return freezeView({
      visible: true,
      valid: true,
      phase: command?.state ?? "loading",
      tone: "progress",
      statusLabel: busyLabel(busyAction),
      detail: null,
      progressLabel: command ? `${command.progressCurrent}/${command.progressTotal}` : null,
      progressValue: command?.progressCurrent ?? null,
      progressMaximum: command?.progressTotal ?? null,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: true,
      terminal: command?.terminal ?? false,
    });
  }
  if (input.loadPhase === "loading") {
    return freezeView({
      visible: true,
      valid: true,
      phase: "loading",
      tone: "progress",
      statusLabel: "正在恢复人物声音准备进度…",
      detail: null,
      progressLabel: null,
      progressValue: null,
      progressMaximum: null,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: true,
      terminal: false,
    });
  }
  if (input.loadPhase === "error") {
    return freezeView({
      visible: true,
      valid: true,
      phase: "load_error",
      tone: "danger",
      statusLabel: input.loadError?.trim() || "无法恢复人物声音准备进度",
      detail: "已完成的声音不会丢失，也不会重复创建。",
      progressLabel: null,
      progressValue: null,
      progressMaximum: null,
      primaryAction: "reload",
      primaryLabel: "重新加载",
      primaryDisabled: false,
      busy: false,
      terminal: false,
    });
  }
  if (command === null) {
    return freezeView({
      visible: true,
      valid: true,
      phase: "idle",
      tone: "neutral",
      statusLabel: configurable
        ? "为尚未配置的人物准备专属音色。"
        : "当前人物声音只能查看。",
      detail: "已有私人、上传或专属音色会保持不变。",
      progressLabel: null,
      progressValue: null,
      progressMaximum: null,
      primaryAction: configurable ? "start" : null,
      primaryLabel: configurable ? "准备专属音色" : null,
      primaryDisabled: !configurable,
      busy: false,
      terminal: false,
    });
  }
  if (!voicePreparationSnapshotIsValid(command)) {
    return freezeView({
      visible: true,
      valid: false,
      phase: "invalid",
      tone: "danger",
      statusLabel: "服务端返回的人物声音准备状态不完整，已停止操作",
      detail: "现有人物声音和朗读任务均未改变。",
      progressLabel: null,
      progressValue: null,
      progressMaximum: null,
      primaryAction: "reload",
      primaryLabel: "重新加载",
      primaryDisabled: false,
      busy: false,
      terminal: false,
    });
  }
  if (ACTIVE_STATES.has(command.state)) {
    const current = command.currentTarget?.characterName;
    const status = command.chapterReady
      ? "本章声音已就绪"
      : `正在准备人物声音 ${command.progressCurrent}/${command.progressTotal}`;
    const detail = command.chapterReady && command.backgroundRemaining > 0
      ? `另有 ${command.backgroundRemaining} 个人物在后台准备。`
      : current ? `当前：${current}` : "完成后会自动继续朗读。";
    return freezeView({
      visible: true,
      valid: true,
      phase: command.state,
      tone: "progress",
      statusLabel: status,
      detail,
      progressLabel: `${command.progressCurrent}/${command.progressTotal}`,
      progressValue: command.progressCurrent,
      progressMaximum: command.progressTotal,
      primaryAction: command.cancellable ? "cancel" : null,
      primaryLabel: command.cancellable ? "取消后续准备" : null,
      primaryDisabled: false,
      busy: false,
      terminal: false,
    });
  }
  if (command.state === "ready" || command.state === "ready_with_warnings") {
    return freezeView({
      visible: true,
      valid: true,
      phase: command.state,
      tone: command.state === "ready" ? "success" : "warning",
      statusLabel: command.chapterReady ? "人物声音准备完成，朗读已继续" : "人物声音准备完成",
      detail: completionDetail(command),
      progressLabel: `${command.progressCurrent}/${command.progressTotal}`,
      progressValue: command.progressCurrent,
      progressMaximum: command.progressTotal,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: false,
      terminal: true,
    });
  }
  const retryable = command.retryable && configurable;
  const superseded = command.state === "superseded";
  const cancelled = command.state === "cancelled";
  return freezeView({
    visible: true,
    valid: true,
    phase: command.state,
    tone: superseded || cancelled ? "warning" : "danger",
    statusLabel: superseded
      ? "人物资料、章节或声音设置已变化"
      : cancelled ? "已停止后续人物声音准备" : "人物声音准备未完成",
    detail: superseded
      ? "已完成的有效声音仍会保留；请按最新内容重新开始。"
      : command.failureCode ? `失败代码：${command.failureCode}` : "现有人物声音保持不变。",
    progressLabel: `${command.progressCurrent}/${command.progressTotal}`,
    progressValue: command.progressCurrent,
    progressMaximum: command.progressTotal,
    primaryAction: retryable ? "retry" : configurable && (superseded || cancelled) ? "start" : null,
    primaryLabel: retryable ? "一键重试" : configurable && (superseded || cancelled) ? "重新准备" : null,
    primaryDisabled: !retryable && !(configurable && (superseded || cancelled)),
    busy: false,
    terminal: true,
  });
}

function actionError(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "操作失败，请稍后重试。";
}

function classNames(...values: readonly (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}

export function createVoicePreparation(
  React: VoicePreparationReactRuntime,
): (props: VoicePreparationProps) => unknown {
  const h = React.createElement;

  return function VoicePreparation(props: VoicePreparationProps): unknown {
    const [local, setLocal] = React.useState<LocalVoicePreparationState>(() => ({
      loadPhase: props.onLoadLatest ? "loading" : "ready",
      command: props.initialCommand ?? null,
      busyAction: props.onLoadLatest ? "load" : null,
      errorMessage: null,
    }));
    const mountedRef = React.useRef(true);
    const actionLockRef = React.useRef(false);

    React.useEffect(() => {
      mountedRef.current = true;
      return () => { mountedRef.current = false; };
    }, []);

    const publish = (command: VoicePreparationSnapshot): void => {
      if (!mountedRef.current) return;
      setLocal({ loadPhase: "ready", command, busyAction: null, errorMessage: null });
      props.onCommandChanged?.(command);
    };

    const loadLatest = (busyAction: "load" | "refresh" = "load"): (() => void) | undefined => {
      if (!props.onLoadLatest || actionLockRef.current) return undefined;
      actionLockRef.current = true;
      const controller = new AbortController();
      setLocal((current) => ({ ...current, loadPhase: "loading", busyAction, errorMessage: null }));
      void props.onLoadLatest(controller.signal).then((command) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setLocal({ loadPhase: "ready", command, busyAction: null, errorMessage: null });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setLocal((current) => ({
          ...current,
          loadPhase: "error",
          busyAction: null,
          errorMessage: actionError(reason),
        }));
      }).finally(() => { actionLockRef.current = false; });
      return () => controller.abort();
    };

    React.useEffect(() => loadLatest("load"), [props.capabilityEnabled]);

    React.useEffect(() => {
      const command = local.command;
      const interval = props.refreshIntervalMs ?? 2_000;
      if (
        interval <= 0
        || local.busyAction !== null
        || command === null
        || command.terminal
      ) return;
      const controller = new AbortController();
      const timer = globalThis.setTimeout(() => {
        if (!mountedRef.current || actionLockRef.current) return;
        actionLockRef.current = true;
        setLocal((current) => ({ ...current, busyAction: "refresh", errorMessage: null }));
        void props.onRefresh(command.commandId, controller.signal).then(publish).catch((reason: unknown) => {
          if (controller.signal.aborted || !mountedRef.current) return;
          setLocal((current) => ({
            ...current,
            loadPhase: "error",
            busyAction: null,
            errorMessage: actionError(reason),
          }));
        }).finally(() => { actionLockRef.current = false; });
      }, interval);
      return () => {
        controller.abort();
        globalThis.clearTimeout(timer);
      };
    }, [
      props.refreshIntervalMs,
      local.busyAction,
      local.command?.commandId,
      local.command?.state,
      local.command?.updatedAt,
      local.command?.terminal,
    ]);

    const derived = deriveVoicePreparationState({
      capabilityEnabled: props.capabilityEnabled,
      canConfigure: props.canConfigure,
      loadPhase: local.loadPhase,
      command: local.command,
      busyAction: local.busyAction,
      loadError: local.errorMessage,
    });
    if (!derived.visible) return null;

    const invoke = (action: Exclude<VoicePreparationPrimaryAction, null>): void => {
      if (actionLockRef.current) return;
      const command = local.command;
      if (action === "reload") {
        loadLatest("load");
        return;
      }
      const task = action === "start" && props.onStart
        ? props.onStart
        : action === "retry" && command
          ? () => props.onRetry(command.commandId)
          : action === "cancel" && command
            ? () => props.onCancel(command.commandId)
            : null;
      if (!task) return;
      actionLockRef.current = true;
      setLocal((current) => ({ ...current, busyAction: action, errorMessage: null }));
      let request: Promise<VoicePreparationSnapshot>;
      try {
        request = task();
      } catch (reason: unknown) {
        actionLockRef.current = false;
        if (mountedRef.current) {
          setLocal((current) => ({ ...current, busyAction: null, errorMessage: actionError(reason) }));
        }
        return;
      }
      void request.then(publish).catch((reason: unknown) => {
        if (!mountedRef.current) return;
        setLocal((current) => ({
          ...current,
          busyAction: null,
          errorMessage: actionError(reason),
        }));
      }).finally(() => { actionLockRef.current = false; });
    };

    const command = local.command;
    const technical = command ? h(
      "details",
      { className: "anw-voice-preparation__details" },
      h("summary", null, "任务详情"),
      h(
        "dl",
        null,
        h("div", null, h("dt", null, "任务"), h("dd", null, command.commandId)),
        command.preflightScriptVersionId
          ? h("div", null, h("dt", null, "朗读稿"), h("dd", null, command.preflightScriptVersionId))
          : null,
        command.narrationRequestId
          ? h("div", null, h("dt", null, "朗读任务"), h("dd", null, command.narrationRequestId))
          : null,
        command.failureCode
          ? h("div", null, h("dt", null, "失败代码"), h("dd", null, command.failureCode))
          : null,
      ),
    ) : null;

    return h(
      "section",
      {
        className: classNames(
          "anw-voice-preparation",
          `is-${derived.tone}`,
          props.presentation === "player-inline" && "is-player-inline",
          props.className,
        ),
        "data-phase": derived.phase,
        "aria-busy": derived.busy,
        "aria-live": "polite",
      },
      h(
        "div",
        { className: "anw-voice-preparation__copy" },
        h("strong", null, derived.statusLabel),
        derived.detail ? h("p", null, derived.detail) : null,
      ),
      derived.progressValue !== null && derived.progressMaximum !== null
        ? h(
          "div",
          { className: "anw-voice-preparation__progress" },
          h("progress", {
            value: derived.progressValue,
            max: Math.max(1, derived.progressMaximum),
            "aria-label": "人物声音准备进度",
          }),
          h("span", null, derived.progressLabel),
        )
        : null,
      local.errorMessage && local.loadPhase !== "error"
        ? h("p", { className: "anw-voice-preparation__error", role: "alert" }, local.errorMessage)
        : null,
      derived.primaryAction && derived.primaryLabel
        ? h(
          "button",
          {
            type: "button",
            className: classNames(
              "anw-voice-preparation__action",
              derived.primaryAction === "cancel" && "is-secondary",
            ),
            disabled: derived.primaryDisabled
              || (derived.primaryAction === "reload" && !props.onLoadLatest),
            onClick: () => invoke(derived.primaryAction as Exclude<VoicePreparationPrimaryAction, null>),
          },
          derived.primaryLabel,
        )
        : null,
      props.presentation === "player-inline" ? null : technical,
    );
  };
}
