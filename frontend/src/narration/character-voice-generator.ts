export const CHARACTER_VOICE_GENERATION_CONTRACT_VERSION = "character-voice-generation/1" as const;

export const CHARACTER_VOICE_GENERATION_ACTIVE_STATES = [
  "queued",
  "analyzing_character",
  "waiting_for_heavy_runtime",
  "generating_voice",
  "unloading_voice_generator",
  "validating_with_nano",
] as const;

export const CHARACTER_VOICE_GENERATION_READY_STATES = [
  "ready_applied",
  "ready_unapplied",
] as const;

export const CHARACTER_VOICE_GENERATION_FAILURE_STATES = [
  "failed_character_analysis",
  "failed_runtime_unavailable",
  "failed_memory_safety",
  "failed_generation",
  "failed_audio_validation",
  "failed_nano_validation",
  "failed_storage",
  "cancelled",
  "superseded",
] as const;

export type CharacterVoiceGenerationActiveState =
  typeof CHARACTER_VOICE_GENERATION_ACTIVE_STATES[number];
export type CharacterVoiceGenerationReadyState =
  typeof CHARACTER_VOICE_GENERATION_READY_STATES[number];
export type CharacterVoiceGenerationFailureState =
  typeof CHARACTER_VOICE_GENERATION_FAILURE_STATES[number];
export type CharacterVoiceGenerationState =
  | CharacterVoiceGenerationActiveState
  | CharacterVoiceGenerationReadyState
  | CharacterVoiceGenerationFailureState;

export interface CharacterVoiceGenerationWorkspaceSelection {
  readonly timelineId: string | null;
  readonly characterInstanceId: string | null;
}

/**
 * Narrow UI projection of `character-voice-generation/1`.
 * The public contracts adapter remains the only owner of wire parsing and
 * snake-case mapping; this module consumes only fields needed by the panel.
 */
export interface CharacterVoiceGenerationSnapshot {
  readonly contractVersion: typeof CHARACTER_VOICE_GENERATION_CONTRACT_VERSION;
  readonly commandId: string;
  readonly draftId: string | null;
  readonly characterId: string;
  readonly state: CharacterVoiceGenerationState;
  readonly progressPercent: number;
  readonly cancellable: boolean;
  readonly retryable: boolean;
  readonly terminal: boolean;
  readonly failureCode: string | null;
  readonly generatedVersionId: string | null;
  readonly selectionStillCurrent: boolean;
  readonly currentBindingVersion: number;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface StartCharacterVoiceGenerationCommand {
  readonly characterId: string;
  readonly workspaceSelection: CharacterVoiceGenerationWorkspaceSelection;
  readonly expectedBindingVersion: number;
}

export interface UseGeneratedCharacterVoiceCommand {
  readonly commandId: string;
  readonly expectedBindingVersion: number;
}

export type CharacterVoiceGeneratorBusyAction =
  | "load"
  | "start"
  | "refresh"
  | "cancel"
  | "retry"
  | "apply";

export type CharacterVoiceGeneratorPrimaryAction =
  | "start"
  | "cancel"
  | "retry"
  | "apply"
  | "reload"
  | null;

export interface CharacterVoiceGeneratorViewState {
  readonly visible: boolean;
  readonly valid: boolean;
  readonly phase: "hidden" | "loading" | "idle" | "invalid" | "load_error" | CharacterVoiceGenerationState;
  readonly tone: "neutral" | "progress" | "warning" | "danger" | "success";
  readonly statusLabel: string;
  readonly detail: string | null;
  readonly progressPercent: number | null;
  readonly primaryAction: CharacterVoiceGeneratorPrimaryAction;
  readonly primaryLabel: string | null;
  readonly primaryDisabled: boolean;
  readonly busy: boolean;
  readonly terminal: boolean;
}

export interface DeriveCharacterVoiceGeneratorStateInput {
  readonly capabilityEnabled?: boolean;
  readonly canConfigure?: boolean;
  readonly characterId: string;
  readonly expectedBindingVersion: number;
  readonly loadPhase?: "ready" | "loading" | "error";
  readonly command?: CharacterVoiceGenerationSnapshot | null;
  readonly busyAction?: CharacterVoiceGeneratorBusyAction | null;
  readonly loadError?: string | null;
}

export interface CharacterVoiceGeneratorReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
  useRef<T>(initial: T): { current: T };
}

export interface CharacterVoiceGeneratorProps {
  /** New generation/retry fail closed; durable commands remain readable and cancellable. */
  readonly capabilityEnabled?: boolean;
  readonly canConfigure?: boolean;
  readonly characterId: string;
  readonly characterName: string;
  readonly expectedBindingVersion: number;
  readonly workspaceSelection: CharacterVoiceGenerationWorkspaceSelection;
  readonly initialCommand?: CharacterVoiceGenerationSnapshot | null;
  readonly className?: string;
  readonly presentation?: "standalone" | "embedded";
  /** Set to zero only in deterministic unit tests; production defaults to 2 seconds. */
  readonly refreshIntervalMs?: number;
  readonly onLoadLatest?: (
    characterId: string,
    signal: AbortSignal,
  ) => Promise<CharacterVoiceGenerationSnapshot | null>;
  readonly onStartGeneration: (
    command: StartCharacterVoiceGenerationCommand,
  ) => Promise<CharacterVoiceGenerationSnapshot>;
  readonly onRefreshGeneration: (
    commandId: string,
    signal: AbortSignal,
  ) => Promise<CharacterVoiceGenerationSnapshot>;
  readonly onCancelGeneration: (
    commandId: string,
  ) => Promise<CharacterVoiceGenerationSnapshot>;
  readonly onRetryGeneration: (
    commandId: string,
  ) => Promise<CharacterVoiceGenerationSnapshot>;
  readonly onUseGeneratedVoice: (
    command: UseGeneratedCharacterVoiceCommand,
  ) => Promise<CharacterVoiceGenerationSnapshot>;
  readonly onCommandChanged?: (command: CharacterVoiceGenerationSnapshot) => void;
}

interface LocalGeneratorState {
  readonly scope: string;
  readonly loadPhase: "ready" | "loading" | "error";
  readonly command: CharacterVoiceGenerationSnapshot | null;
  readonly busyAction: CharacterVoiceGeneratorBusyAction | null;
  readonly errorMessage: string | null;
}

const ACTIVE_STATES = new Set<string>(CHARACTER_VOICE_GENERATION_ACTIVE_STATES);
const READY_STATES = new Set<string>(CHARACTER_VOICE_GENERATION_READY_STATES);
const FAILURE_STATES = new Set<string>(CHARACTER_VOICE_GENERATION_FAILURE_STATES);

const STATE_COPY: Readonly<Record<CharacterVoiceGenerationState, string>> = Object.freeze({
  queued: "专属音色任务已排队",
  analyzing_character: "正在分析已保存的人物卡",
  waiting_for_heavy_runtime: "正在等待声音生成资源",
  generating_voice: "正在生成专属音色",
  unloading_voice_generator: "声音已生成，正在释放重模型",
  validating_with_nano: "正在验证生成结果",
  ready_applied: "专属音色已生成并用于当前人物",
  ready_unapplied: "专属音色已生成，但没有覆盖你刚修改的声音",
  failed_character_analysis: "人物卡分析失败",
  failed_runtime_unavailable: "声音生成服务当前不可用",
  failed_memory_safety: "本次生成已因内存安全停止",
  failed_generation: "专属音色生成失败",
  failed_audio_validation: "生成音频未通过机器校验",
  failed_nano_validation: "生成结果未通过验证",
  failed_storage: "专属音色保存失败",
  cancelled: "专属音色生成已取消",
  superseded: "人物资料或声音绑定已变化，本次任务已失效",
});

function validVersion(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0;
}

function validTimestamp(value: string): boolean {
  return value.includes("T") && Number.isFinite(Date.parse(value));
}

function nonEmpty(value: string): boolean {
  return value.trim().length > 0;
}

function isActive(state: CharacterVoiceGenerationState): boolean {
  return ACTIVE_STATES.has(state);
}

function isReady(state: CharacterVoiceGenerationState): boolean {
  return READY_STATES.has(state);
}

function isFailure(state: CharacterVoiceGenerationState): boolean {
  return FAILURE_STATES.has(state);
}

export function characterVoiceGenerationSnapshotIsValid(
  command: CharacterVoiceGenerationSnapshot,
  characterId: string = command.characterId,
): boolean {
  if (
    command.contractVersion !== CHARACTER_VOICE_GENERATION_CONTRACT_VERSION
    || !nonEmpty(command.commandId)
    || (command.draftId !== null && !nonEmpty(command.draftId))
    || command.characterId !== characterId
    || !nonEmpty(command.characterId)
    || (!isActive(command.state) && !isReady(command.state) && !isFailure(command.state))
    || !Number.isSafeInteger(command.progressPercent)
    || command.progressPercent < 0
    || command.progressPercent > 100
    || !validVersion(command.currentBindingVersion)
    || typeof command.selectionStillCurrent !== "boolean"
    || !validTimestamp(command.createdAt)
    || !validTimestamp(command.updatedAt)
  ) return false;

  if (
    command.draftId === null
    && !["queued", "analyzing_character", "failed_character_analysis", "cancelled", "superseded"].includes(command.state)
  ) return false;

  if (command.terminal && (command.cancellable || command.retryable && !isFailure(command.state))) {
    return false;
  }
  if (isActive(command.state)) {
    return !command.terminal
      && !command.retryable
      && command.failureCode === null;
  }
  if (!command.terminal || command.cancellable) return false;
  if (isReady(command.state)) {
    return command.failureCode === null
      && !command.retryable
      && command.generatedVersionId !== null
      && nonEmpty(command.generatedVersionId)
      && command.progressPercent === 100;
  }
  if (command.state === "cancelled" || command.state === "superseded") {
    return command.failureCode === null
      || nonEmpty(command.failureCode);
  }
  return command.failureCode !== null && nonEmpty(command.failureCode);
}

function view(
  values: CharacterVoiceGeneratorViewState,
): CharacterVoiceGeneratorViewState {
  return Object.freeze(values);
}

function busyLabel(action: CharacterVoiceGeneratorBusyAction): string {
  if (action === "load" || action === "refresh") return "正在恢复任务进度…";
  if (action === "start") return "正在创建专属音色任务…";
  if (action === "cancel") return "正在取消…";
  if (action === "retry") return "正在重新开始…";
  return "正在使用专属音色…";
}

export function deriveCharacterVoiceGeneratorState(
  input: DeriveCharacterVoiceGeneratorStateInput,
): CharacterVoiceGeneratorViewState {
  const generationAvailable = input.capabilityEnabled === true;
  if (!generationAvailable && (input.command ?? null) === null) {
    return view({
      visible: false,
      valid: true,
      phase: "hidden",
      tone: "neutral",
      statusLabel: "人物专属音色生成未开放",
      detail: null,
      progressPercent: null,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: false,
      terminal: false,
    });
  }
  const busy = input.busyAction ?? null;
  if (!nonEmpty(input.characterId) || !validVersion(input.expectedBindingVersion)) {
    return view({
      visible: true,
      valid: false,
      phase: "invalid",
      tone: "danger",
      statusLabel: "人物声音状态无效，已阻止生成",
      detail: "请重新打开人物卡后再试。",
      progressPercent: null,
      primaryAction: "reload",
      primaryLabel: "重新加载",
      primaryDisabled: busy !== null,
      busy: busy !== null,
      terminal: false,
    });
  }
  if (busy !== null) {
    return view({
      visible: true,
      valid: true,
      phase: input.command?.state ?? (input.loadPhase === "error" ? "load_error" : "loading"),
      tone: "progress",
      statusLabel: busyLabel(busy),
      detail: null,
      progressPercent: input.command?.progressPercent ?? null,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: true,
      terminal: input.command?.terminal ?? false,
    });
  }
  if (input.loadPhase === "loading") {
    return view({
      visible: true,
      valid: true,
      phase: "loading",
      tone: "progress",
      statusLabel: "正在恢复专属音色任务…",
      detail: null,
      progressPercent: null,
      primaryAction: null,
      primaryLabel: null,
      primaryDisabled: true,
      busy: true,
      terminal: false,
    });
  }
  if (input.loadPhase === "error") {
    return view({
      visible: true,
      valid: true,
      phase: "load_error",
      tone: "danger",
      statusLabel: input.loadError?.trim() || "无法恢复专属音色任务",
      detail: "原人物声音未改变。",
      progressPercent: null,
      primaryAction: "reload",
      primaryLabel: "重新加载",
      primaryDisabled: false,
      busy: false,
      terminal: false,
    });
  }
  const command = input.command ?? null;
  if (command === null) {
    const configurable = generationAvailable && input.canConfigure !== false;
    return view({
      visible: true,
      valid: true,
      phase: "idle",
      tone: "neutral",
      statusLabel: configurable
        ? "根据已保存的人物卡生成一条专属新音色，并在成功后直接使用。"
        : "当前人物声音为只读。",
      detail: "原声音会保持到生成和 Nano 验证全部完成。",
      progressPercent: null,
      primaryAction: configurable ? "start" : null,
      primaryLabel: configurable ? "生成专属音色并使用" : null,
      primaryDisabled: !configurable,
      busy: false,
      terminal: false,
    });
  }
  if (!characterVoiceGenerationSnapshotIsValid(command, input.characterId)) {
    return view({
      visible: true,
      valid: false,
      phase: "invalid",
      tone: "danger",
      statusLabel: "服务端返回的专属音色状态不完整，已停止操作",
      detail: "原人物声音未改变。",
      progressPercent: null,
      primaryAction: "reload",
      primaryLabel: "重新加载",
      primaryDisabled: false,
      busy: false,
      terminal: false,
    });
  }
  if (isActive(command.state)) {
    return view({
      visible: true,
      valid: true,
      phase: command.state,
      tone: "progress",
      statusLabel: STATE_COPY[command.state],
      detail: command.cancellable ? "此阶段可以取消；取消不会改变原人物声音。" : "原人物声音会保持到全部验证成功。",
      progressPercent: command.progressPercent,
      primaryAction: command.cancellable ? "cancel" : null,
      primaryLabel: command.cancellable ? "取消生成" : null,
      primaryDisabled: false,
      busy: false,
      terminal: false,
    });
  }
  if (command.state === "ready_applied") {
    if (!command.selectionStillCurrent) {
      return view({
        visible: true,
        valid: true,
        phase: command.state,
        tone: "warning",
        statusLabel: "专属音色曾成功使用，但当前人物声音后来发生了变化",
        detail: "生成结果仍保留；点击后按当前人物声音版本重新应用。",
        progressPercent: 100,
        primaryAction: input.canConfigure === false ? null : "apply",
        primaryLabel: input.canConfigure === false ? null : "再次使用此音色",
        primaryDisabled: input.canConfigure === false,
        busy: false,
        terminal: true,
      });
    }
    return view({
      visible: true,
      valid: true,
      phase: command.state,
      tone: "success",
      statusLabel: STATE_COPY[command.state],
      detail: "后续新朗读版本将使用这条专属音色；既有 Edition 不变。",
      progressPercent: 100,
      primaryAction: !generationAvailable || input.canConfigure === false
        ? null
        : "start",
      primaryLabel: !generationAvailable || input.canConfigure === false ? null : "重新生成专属音色",
      primaryDisabled: !generationAvailable || input.canConfigure === false,
      busy: false,
      terminal: true,
    });
  }
  if (command.state === "ready_unapplied") {
    return view({
      visible: true,
      valid: true,
      phase: command.state,
      tone: "warning",
      statusLabel: STATE_COPY[command.state],
      detail: "生成结果已保留。点击使用时会按当前人物声音版本再次执行 CAS。",
      progressPercent: 100,
      primaryAction: input.canConfigure === false ? null : "apply",
      primaryLabel: input.canConfigure === false ? null : "使用此音色",
      primaryDisabled: input.canConfigure === false,
      busy: false,
      terminal: true,
    });
  }
  const retryable = command.retryable
    && generationAvailable
    && input.canConfigure !== false;
  return view({
    visible: true,
    valid: true,
    phase: command.state,
    tone: command.state === "cancelled" || command.state === "superseded" ? "warning" : "danger",
    statusLabel: STATE_COPY[command.state],
    detail: command.failureCode ? `失败代码：${command.failureCode}。原人物声音未改变。` : "原人物声音未改变。",
    progressPercent: command.progressPercent,
    primaryAction: !generationAvailable || input.canConfigure === false
      ? null
      : retryable
        ? "retry"
        : "start",
    primaryLabel: !generationAvailable || input.canConfigure === false
      ? null
      : retryable
        ? "一键重试"
        : "重新生成",
    primaryDisabled: !generationAvailable || input.canConfigure === false,
    busy: false,
    terminal: true,
  });
}

function actionError(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "操作失败，请稍后重试。";
}

function classNames(...values: readonly (string | null | undefined | false)[]): string {
  return values.filter(Boolean).join(" ");
}

export function createCharacterVoiceGenerator(
  React: CharacterVoiceGeneratorReactRuntime,
): (props: CharacterVoiceGeneratorProps) => unknown {
  const h = React.createElement;

  return function CharacterVoiceGenerator(props: CharacterVoiceGeneratorProps): unknown {
    const scope = `${props.characterId}:${props.expectedBindingVersion}`;
    const [local, setLocal] = React.useState<LocalGeneratorState>(() => ({
      scope,
      loadPhase: props.onLoadLatest ? "loading" : "ready",
      command: props.initialCommand ?? null,
      busyAction: props.onLoadLatest ? "load" : null,
      errorMessage: null,
    }));
    const mountedRef = React.useRef(true);
    React.useEffect(() => {
      mountedRef.current = true;
      return () => { mountedRef.current = false; };
    }, []);

    const scoped = local.scope === scope
      ? local
      : {
        scope,
        loadPhase: props.onLoadLatest ? "loading" as const : "ready" as const,
        command: props.initialCommand ?? null,
        busyAction: props.onLoadLatest ? "load" as const : null,
        errorMessage: null,
      };

    const publish = (command: CharacterVoiceGenerationSnapshot) => {
      if (!mountedRef.current) return;
      setLocal({ scope, loadPhase: "ready", command, busyAction: null, errorMessage: null });
      props.onCommandChanged?.(command);
    };

    React.useEffect(() => {
      if (!props.onLoadLatest) return;
      const controller = new AbortController();
      setLocal((current) => ({
        scope,
        loadPhase: "loading",
        command: current.scope === scope ? current.command : props.initialCommand ?? null,
        busyAction: "load",
        errorMessage: null,
      }));
      void props.onLoadLatest(props.characterId, controller.signal).then((command) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setLocal({ scope, loadPhase: "ready", command, busyAction: null, errorMessage: null });
        if (command) props.onCommandChanged?.(command);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setLocal({
          scope,
          loadPhase: "error",
          command: null,
          busyAction: null,
          errorMessage: actionError(reason),
        });
      });
      return () => controller.abort();
    }, [props.capabilityEnabled, props.characterId, scope]);

    React.useEffect(() => {
      const command = scoped.command;
      const interval = props.refreshIntervalMs ?? 2_000;
      if (
        interval <= 0
        || scoped.busyAction !== null
        || command === null
        || command.terminal
      ) return;
      const controller = new AbortController();
      const timer = globalThis.setTimeout(() => {
        if (!mountedRef.current) return;
        setLocal((current) => current.scope === scope
          ? { ...current, busyAction: "refresh", errorMessage: null }
          : current);
        void props.onRefreshGeneration(command.commandId, controller.signal).then(publish).catch((reason: unknown) => {
          if (controller.signal.aborted || !mountedRef.current) return;
          setLocal({
            scope,
            loadPhase: "error",
            command,
            busyAction: null,
            errorMessage: actionError(reason),
          });
        });
      }, interval);
      return () => {
        controller.abort();
        globalThis.clearTimeout(timer);
      };
    }, [
      props.capabilityEnabled,
      props.refreshIntervalMs,
      scope,
      scoped.busyAction,
      scoped.command?.commandId,
      scoped.command?.state,
      scoped.command?.updatedAt,
      scoped.command?.terminal,
    ]);

    const derived = deriveCharacterVoiceGeneratorState({
      capabilityEnabled: props.capabilityEnabled,
      canConfigure: props.canConfigure,
      characterId: props.characterId,
      expectedBindingVersion: props.expectedBindingVersion,
      loadPhase: scoped.loadPhase,
      command: scoped.command,
      busyAction: scoped.busyAction,
      loadError: scoped.errorMessage,
    });
    if (!derived.visible) return null;

    const run = async (action: Exclude<CharacterVoiceGeneratorPrimaryAction, null>) => {
      if (scoped.busyAction !== null) return;
      const command = scoped.command;
      const busyAction: CharacterVoiceGeneratorBusyAction = action === "reload"
        ? "load"
        : action;
      setLocal({ ...scoped, busyAction, errorMessage: null });
      try {
        let next: CharacterVoiceGenerationSnapshot | null;
        if (action === "reload") {
          next = props.onLoadLatest
            ? await props.onLoadLatest(props.characterId, new AbortController().signal)
            : command;
        } else if (action === "start") {
          next = await props.onStartGeneration({
            characterId: props.characterId,
            workspaceSelection: props.workspaceSelection,
            expectedBindingVersion: command?.currentBindingVersion
              ?? props.expectedBindingVersion,
          });
        } else if (action === "cancel" && command) {
          next = await props.onCancelGeneration(command.commandId);
        } else if (action === "retry" && command) {
          next = await props.onRetryGeneration(command.commandId);
        } else if (action === "apply" && command) {
          next = await props.onUseGeneratedVoice({
            commandId: command.commandId,
            expectedBindingVersion: command.currentBindingVersion,
          });
        } else {
          next = command;
        }
        if (!mountedRef.current) return;
        if (next) publish(next);
        else setLocal({ scope, loadPhase: "ready", command: null, busyAction: null, errorMessage: null });
      } catch (reason: unknown) {
        if (!mountedRef.current) return;
        setLocal({
          ...scoped,
          loadPhase: action === "reload" ? "error" : scoped.loadPhase,
          busyAction: null,
          errorMessage: actionError(reason),
        });
      }
    };

    const rootClassName = classNames(
      "anw-character-voice-generator",
      `is-${derived.tone}`,
      props.className,
    );
    const statusId = `anw-character-voice-generator-${props.characterId}-status`;
    const primaryLabel = derived.primaryAction === "start" && derived.phase === "idle"
      ? `为${props.characterName}生成并使用专属音色`
      : derived.primaryLabel;
    return h(
      "section",
      {
        className: rootClassName,
        "aria-labelledby": `${statusId}-heading`,
        "aria-describedby": statusId,
        "data-generation-state": derived.phase,
      },
      props.presentation === "embedded"
        ? h("div", { className: "anw-character-voice-generator__heading" },
          h("h3", { id: `${statusId}-heading` }, "生成专属音色"),
          derived.terminal
            ? h("span", { className: "anw-character-voice-generator__terminal" }, "本次任务已结束")
            : null,
        )
        : h("div", { className: "anw-character-voice-generator__heading" },
          h("div", null,
            h("p", { className: "anw-character-voice-generator__eyebrow" }, "生成专属音色"),
            h("h3", { id: `${statusId}-heading` }, `为${props.characterName}创建独特声音`),
          ),
          derived.terminal
            ? h("span", { className: "anw-character-voice-generator__terminal" }, "本次任务已结束")
            : null,
        ),
      h("p", {
        id: statusId,
        className: "anw-character-voice-generator__status",
        role: derived.tone === "danger" ? "alert" : "status",
        "aria-live": "polite",
      }, derived.statusLabel),
      derived.progressPercent !== null
        ? h("div", { className: "anw-character-voice-generator__progress" },
          h("progress", {
            max: 100,
            value: derived.progressPercent,
            "aria-label": "专属音色生成进度",
          }),
          h("span", null, `${derived.progressPercent}%`),
        )
        : null,
      derived.detail
        ? h("p", { className: "anw-character-voice-generator__detail" }, derived.detail)
        : null,
      scoped.errorMessage && scoped.loadPhase !== "error"
        ? h("p", { className: "anw-character-voice-generator__error", role: "alert" }, scoped.errorMessage)
        : null,
      derived.primaryAction && primaryLabel
        ? h("button", {
          type: "button",
          className: classNames(
            "anw-character-voice-generator__primary",
            derived.primaryAction === "cancel" && "is-cancel",
          ),
          disabled: derived.primaryDisabled,
          onClick: () => { void run(derived.primaryAction as Exclude<CharacterVoiceGeneratorPrimaryAction, null>); },
        }, primaryLabel)
        : null,
    );
  };
}
