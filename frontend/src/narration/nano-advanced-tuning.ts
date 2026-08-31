const NANO_MAX_SEED = 9_223_372_036_854_775_807n;

export const NANO_ADVANCED_TUNING_DEFAULT_DRAFT = Object.freeze({
  seed: "1234",
  textTemperature: "1.0",
  textTopP: "1.0",
  textTopK: "50",
  audioTemperature: "0.8",
  audioTopP: "0.95",
  audioTopK: "25",
  audioRepetitionPenalty: "1.2",
});

export type NanoAdvancedTuningField = keyof typeof NANO_ADVANCED_TUNING_DEFAULT_DRAFT;
export type NanoAdvancedTuningTargetKind = "narrator" | "character";
export type NanoExperimentState =
  | "pending"
  | "running"
  | "ready_applied"
  | "ready_unapplied"
  | "failed";
export type NanoAdvancedTuningBusyAction = "create" | "apply" | "restore";

export interface NanoAdvancedTuningDraft {
  readonly seed: string;
  readonly textTemperature: string;
  readonly textTopP: string;
  readonly textTopK: string;
  readonly audioTemperature: string;
  readonly audioTopP: string;
  readonly audioTopK: string;
  readonly audioRepetitionPenalty: string;
}

/**
 * Camel-case adapter input for nano-decode-parameters/3.
 * Seed remains a canonical decimal string because the frozen int64 range is
 * wider than JavaScript's safe integer range. The shared API adapter owns the
 * final snake_case JSON mapping.
 */
export interface NanoAdvancedTuningParameters {
  readonly seed: string;
  readonly textTemperatureMilli: number;
  readonly textTopPMilli: number;
  readonly textTopK: number;
  readonly audioTemperatureMilli: number;
  readonly audioTopPMilli: number;
  readonly audioTopK: number;
  readonly audioRepetitionPenaltyMilli: number;
  readonly sampleMode: "full";
  readonly maxNewFrames: 375;
}

export interface NanoAdvancedTuningTarget {
  readonly kind: NanoAdvancedTuningTargetKind;
  readonly characterId: string | null;
  readonly expectedSettingsVersion: number;
  readonly expectedBindingVersion: number | null;
}

export interface NanoExperimentSnapshot {
  readonly commandId: string;
  readonly state: NanoExperimentState;
  readonly reusedVersion: boolean;
  readonly failureCode: string | null;
  readonly retryable: boolean;
}

export interface NanoAdvancedExperimentCommand extends NanoAdvancedTuningTarget {
  readonly basePresetId: string;
  readonly parameters: NanoAdvancedTuningParameters;
}

export interface NanoAdvancedApplyCommand extends NanoAdvancedTuningTarget {
  readonly commandId: string;
}

export interface NanoOfficialVoiceRestoreCommand extends NanoAdvancedTuningTarget {
  readonly basePresetId: string;
}

export interface NanoAdvancedTuningValidation {
  readonly valid: boolean;
  readonly parameters: NanoAdvancedTuningParameters | null;
  readonly fieldErrors: Readonly<Partial<Record<NanoAdvancedTuningField, string>>>;
}

export interface NanoAdvancedTuningViewState extends NanoAdvancedTuningValidation {
  readonly visible: boolean;
  readonly phase: "hidden" | "editing" | NanoExperimentState | "invalid";
  readonly tone: "neutral" | "warning" | "danger" | "success";
  readonly statusLabel: string;
  readonly canReset: boolean;
  readonly canCreate: boolean;
  readonly canApply: boolean;
  readonly canRestoreOfficial: boolean;
  readonly busy: boolean;
}

export interface NanoAdvancedTuningReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
}

export interface NanoAdvancedTuningPanelProps {
  /** Fail-closed capability gate. */
  readonly capabilityEnabled?: boolean;
  readonly basePresetId: string;
  readonly basePresetDisplayName: string;
  readonly target: NanoAdvancedTuningTarget;
  readonly experiment?: NanoExperimentSnapshot | null;
  readonly initialDraft?: NanoAdvancedTuningDraft;
  readonly busyAction?: NanoAdvancedTuningBusyAction | null;
  readonly errorMessage?: string | null;
  readonly className?: string;
  readonly onCreateExperiment: (command: NanoAdvancedExperimentCommand) => void;
  readonly onApplyExperiment: (command: NanoAdvancedApplyCommand) => void;
  readonly onRestoreOfficialVoice: (command: NanoOfficialVoiceRestoreCommand) => void;
}

interface DraftState {
  readonly scope: string;
  readonly value: NanoAdvancedTuningDraft;
}

interface ValueChangeEvent {
  readonly target: { readonly value: string };
}

interface FieldDefinition {
  readonly key: NanoAdvancedTuningField;
  readonly label: string;
  readonly hint: string;
  readonly min: string;
  readonly max: string;
  readonly step: string;
  readonly inputMode: "decimal" | "numeric";
}

const FIELD_DEFINITIONS: readonly FieldDefinition[] = Object.freeze([
  { key: "seed", label: "随机种子", hint: "0 – 9223372036854775807", min: "0", max: "9223372036854775807", step: "1", inputMode: "numeric" },
  { key: "textTemperature", label: "文本温度", hint: "0.1 – 2.0", min: "0.1", max: "2", step: "0.001", inputMode: "decimal" },
  { key: "textTopP", label: "文本 Top-p", hint: "0.001 – 1.0", min: "0.001", max: "1", step: "0.001", inputMode: "decimal" },
  { key: "textTopK", label: "文本 Top-k", hint: "1 – 100", min: "1", max: "100", step: "1", inputMode: "numeric" },
  { key: "audioTemperature", label: "音频温度", hint: "0.1 – 2.0", min: "0.1", max: "2", step: "0.001", inputMode: "decimal" },
  { key: "audioTopP", label: "音频 Top-p", hint: "0.001 – 1.0", min: "0.001", max: "1", step: "0.001", inputMode: "decimal" },
  { key: "audioTopK", label: "音频 Top-k", hint: "1 – 100", min: "1", max: "100", step: "1", inputMode: "numeric" },
  { key: "audioRepetitionPenalty", label: "音频重复惩罚", hint: "1.0 – 2.0", min: "1", max: "2", step: "0.001", inputMode: "decimal" },
]);

function classNames(...values: readonly (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}

function validVersion(value: number | null): boolean {
  return value !== null && Number.isSafeInteger(value) && value >= 0;
}

function validTarget(target: NanoAdvancedTuningTarget): boolean {
  if (!validVersion(target.expectedSettingsVersion)) return false;
  if (target.kind === "narrator") {
    return target.characterId === null && target.expectedBindingVersion === null;
  }
  return target.kind === "character"
    && typeof target.characterId === "string"
    && target.characterId.trim().length > 0
    && validVersion(target.expectedBindingVersion);
}

function integerWithin(value: string, minimum: number, maximum: number): number | null {
  if (!/^(0|[1-9]\d*)$/.test(value)) return null;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) return null;
  return parsed;
}

export function nanoMilliFromDecimal(value: string): number | null {
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,3}))?$/.exec(value);
  if (!match) return null;
  const whole = Number(match[1]);
  if (!Number.isSafeInteger(whole)) return null;
  const fraction = (match[2] ?? "").padEnd(3, "0");
  const milli = whole * 1_000 + Number(fraction || "0");
  return Number.isSafeInteger(milli) ? milli : null;
}

export function nanoDecimalFromMilli(value: number): string {
  if (!Number.isSafeInteger(value) || value < 0) throw new RangeError("milli value is invalid");
  const whole = Math.floor(value / 1_000);
  const fraction = String(value % 1_000).padStart(3, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : `${whole}.0`;
}

function validSeed(value: string): boolean {
  if (!/^(0|[1-9]\d*)$/.test(value)) return false;
  try {
    return BigInt(value) <= NANO_MAX_SEED;
  } catch {
    return false;
  }
}

export function validateNanoAdvancedTuningDraft(
  draft: NanoAdvancedTuningDraft,
): NanoAdvancedTuningValidation {
  const errors: Partial<Record<NanoAdvancedTuningField, string>> = {};
  if (!validSeed(draft.seed)) errors.seed = "请输入 0 到 9223372036854775807 的整数。";

  const textTemperatureMilli = nanoMilliFromDecimal(draft.textTemperature);
  if (textTemperatureMilli === null || textTemperatureMilli < 100 || textTemperatureMilli > 2_000) {
    errors.textTemperature = "请输入 0.1 到 2.0，最多三位小数。";
  }
  const textTopPMilli = nanoMilliFromDecimal(draft.textTopP);
  if (textTopPMilli === null || textTopPMilli < 1 || textTopPMilli > 1_000) {
    errors.textTopP = "请输入 0.001 到 1.0，最多三位小数。";
  }
  const textTopK = integerWithin(draft.textTopK, 1, 100);
  if (textTopK === null) errors.textTopK = "请输入 1 到 100 的整数。";

  const audioTemperatureMilli = nanoMilliFromDecimal(draft.audioTemperature);
  if (audioTemperatureMilli === null || audioTemperatureMilli < 100 || audioTemperatureMilli > 2_000) {
    errors.audioTemperature = "请输入 0.1 到 2.0，最多三位小数。";
  }
  const audioTopPMilli = nanoMilliFromDecimal(draft.audioTopP);
  if (audioTopPMilli === null || audioTopPMilli < 1 || audioTopPMilli > 1_000) {
    errors.audioTopP = "请输入 0.001 到 1.0，最多三位小数。";
  }
  const audioTopK = integerWithin(draft.audioTopK, 1, 100);
  if (audioTopK === null) errors.audioTopK = "请输入 1 到 100 的整数。";

  const audioRepetitionPenaltyMilli = nanoMilliFromDecimal(draft.audioRepetitionPenalty);
  if (
    audioRepetitionPenaltyMilli === null
    || audioRepetitionPenaltyMilli < 1_000
    || audioRepetitionPenaltyMilli > 2_000
  ) {
    errors.audioRepetitionPenalty = "请输入 1.0 到 2.0，最多三位小数。";
  }

  if (Object.keys(errors).length > 0) {
    return Object.freeze({ valid: false, parameters: null, fieldErrors: Object.freeze(errors) });
  }
  return Object.freeze({
    valid: true,
    parameters: Object.freeze({
      seed: draft.seed,
      textTemperatureMilli: textTemperatureMilli as number,
      textTopPMilli: textTopPMilli as number,
      textTopK: textTopK as number,
      audioTemperatureMilli: audioTemperatureMilli as number,
      audioTopPMilli: audioTopPMilli as number,
      audioTopK: audioTopK as number,
      audioRepetitionPenaltyMilli: audioRepetitionPenaltyMilli as number,
      sampleMode: "full",
      maxNewFrames: 375,
    }),
    fieldErrors: Object.freeze({}),
  });
}

export function nanoAdvancedDraftFromParameters(
  parameters: NanoAdvancedTuningParameters,
): NanoAdvancedTuningDraft {
  return Object.freeze({
    seed: parameters.seed,
    textTemperature: nanoDecimalFromMilli(parameters.textTemperatureMilli),
    textTopP: nanoDecimalFromMilli(parameters.textTopPMilli),
    textTopK: String(parameters.textTopK),
    audioTemperature: nanoDecimalFromMilli(parameters.audioTemperatureMilli),
    audioTopP: nanoDecimalFromMilli(parameters.audioTopPMilli),
    audioTopK: String(parameters.audioTopK),
    audioRepetitionPenalty: nanoDecimalFromMilli(parameters.audioRepetitionPenaltyMilli),
  });
}

function validExperiment(experiment: NanoExperimentSnapshot | null): boolean {
  return experiment === null || (
    typeof experiment.commandId === "string"
    && experiment.commandId.trim().length > 0
    && ["pending", "running", "ready_applied", "ready_unapplied", "failed"]
      .includes(experiment.state)
    && typeof experiment.reusedVersion === "boolean"
    && typeof experiment.retryable === "boolean"
    && (experiment.failureCode === null || (
      typeof experiment.failureCode === "string" && experiment.failureCode.trim().length > 0
    ))
    && (experiment.state === "failed" || experiment.failureCode === null)
    && (experiment.state !== "failed" || experiment.failureCode !== null)
    && (experiment.state === "failed" || !experiment.retryable)
  );
}

function statusForExperiment(
  experiment: NanoExperimentSnapshot | null,
): Readonly<{ label: string; tone: NanoAdvancedTuningViewState["tone"] }> {
  if (experiment === null) {
    return { label: "修改参数后只需点击一次；后台真实验证成功后会自动尝试使用。", tone: "neutral" };
  }
  if (experiment.state === "pending") {
    return { label: "高级调音已排队，原音色绑定保持不变。", tone: "warning" };
  }
  if (experiment.state === "running") {
    return { label: "正在执行 Nano 真实合成与机器验证，原音色绑定保持不变。", tone: "warning" };
  }
  if (experiment.state === "ready_applied") {
    return {
      label: experiment.reusedVersion
        ? "已复用相同参数的机器验证音色并自动使用。"
        : "高级调音已通过真实验证并自动使用。",
      tone: "success",
    };
  }
  if (experiment.state === "ready_unapplied") {
    return { label: "调音已通过真实验证，但你在期间修改了音色，因此没有覆盖新选择。", tone: "warning" };
  }
  return {
    label: experiment.failureCode
      ? `高级调音失败（${experiment.failureCode}）；原音色绑定未改变。`
      : "高级调音失败；原音色绑定未改变。",
    tone: "danger",
  };
}

export function deriveNanoAdvancedTuningState(input: {
  readonly capabilityEnabled?: boolean;
  readonly basePresetId: string;
  readonly target: NanoAdvancedTuningTarget;
  readonly draft: NanoAdvancedTuningDraft;
  readonly experiment?: NanoExperimentSnapshot | null;
  readonly busyAction?: NanoAdvancedTuningBusyAction | null;
}): NanoAdvancedTuningViewState {
  const validation = validateNanoAdvancedTuningDraft(input.draft);
  const experiment = input.experiment ?? null;
  const busy = input.busyAction !== null && input.busyAction !== undefined;
  if (input.capabilityEnabled !== true) {
    return Object.freeze({
      ...validation,
      visible: false,
      phase: "hidden",
      tone: "neutral",
      statusLabel: "",
      canReset: false,
      canCreate: false,
      canApply: false,
      canRestoreOfficial: false,
      busy,
    });
  }
  if (!input.basePresetId.trim() || !validTarget(input.target) || !validExperiment(experiment)) {
    return Object.freeze({
      ...validation,
      valid: false,
      visible: true,
      phase: "invalid",
      tone: "danger",
      statusLabel: "高级调音的基础音色、绑定版本或实验状态无效，已停止操作。",
      canReset: !busy,
      canCreate: false,
      canApply: false,
      canRestoreOfficial: false,
      busy,
    });
  }
  const status = statusForExperiment(experiment);
  const inProgress = experiment?.state === "pending" || experiment?.state === "running";
  return Object.freeze({
    ...validation,
    visible: true,
    phase: experiment?.state ?? "editing",
    tone: status.tone,
    statusLabel: status.label,
    canReset: !busy,
    canCreate: validation.valid && !inProgress && !busy,
    canApply: experiment?.state === "ready_unapplied" && !busy,
    canRestoreOfficial: !busy,
    busy,
  });
}

export function nanoAdvancedExperimentCommand(
  basePresetId: string,
  target: NanoAdvancedTuningTarget,
  parameters: NanoAdvancedTuningParameters,
): NanoAdvancedExperimentCommand {
  return Object.freeze({ basePresetId, ...target, parameters });
}

export function nanoAdvancedApplyCommand(
  commandId: string,
  target: NanoAdvancedTuningTarget,
): NanoAdvancedApplyCommand {
  return Object.freeze({ commandId, ...target });
}

export function nanoOfficialVoiceRestoreCommand(
  basePresetId: string,
  target: NanoAdvancedTuningTarget,
): NanoOfficialVoiceRestoreCommand {
  return Object.freeze({ basePresetId, ...target });
}

function draftScope(props: NanoAdvancedTuningPanelProps): string {
  return [
    props.basePresetId,
    props.target.kind,
    props.target.characterId ?? "narrator",
  ].join(":");
}

export function createNanoAdvancedTuningPanel(
  React: NanoAdvancedTuningReactRuntime,
): (props: NanoAdvancedTuningPanelProps) => unknown {
  const h = React.createElement;
  return function NanoAdvancedTuningPanel(props: NanoAdvancedTuningPanelProps): unknown {
    const scope = draftScope(props);
    const initialDraft = props.initialDraft ?? NANO_ADVANCED_TUNING_DEFAULT_DRAFT;
    const [draftState, setDraftState] = React.useState<DraftState>(() => ({
      scope,
      value: Object.freeze({ ...initialDraft }),
    }));
    const draft = draftState.scope === scope
      ? draftState.value
      : Object.freeze({ ...initialDraft });

    React.useEffect(() => {
      setDraftState({ scope, value: Object.freeze({ ...initialDraft }) });
    }, [scope, ...Object.values(initialDraft)]);

    const view = deriveNanoAdvancedTuningState({
      capabilityEnabled: props.capabilityEnabled,
      basePresetId: props.basePresetId,
      target: props.target,
      draft,
      experiment: props.experiment,
      busyAction: props.busyAction,
    });
    if (!view.visible) return null;

    const updateField = (field: NanoAdvancedTuningField, value: string): void => {
      setDraftState({ scope, value: Object.freeze({ ...draft, [field]: value }) });
    };
    const reset = (): void => {
      setDraftState({ scope, value: NANO_ADVANCED_TUNING_DEFAULT_DRAFT });
    };
    const create = (): void => {
      if (!view.canCreate || view.parameters === null) return;
      props.onCreateExperiment(nanoAdvancedExperimentCommand(
        props.basePresetId,
        props.target,
        view.parameters,
      ));
    };
    const apply = (): void => {
      if (!view.canApply || !props.experiment) return;
      props.onApplyExperiment(nanoAdvancedApplyCommand(props.experiment.commandId, props.target));
    };

    return h(
      "section",
      {
        className: classNames("anw-nano-tuning", props.className),
        "data-phase": view.phase,
        "data-tone": view.tone,
        "aria-label": "MOSS-TTS-Nano 高级调音",
        "aria-busy": view.busy || undefined,
      },
      h(
        "header",
        { className: "anw-nano-tuning__header" },
        h("div", null,
          h("p", { className: "anw-nano-tuning__eyebrow" }, "Nano 高级调音"),
          h("h3", null, props.basePresetDisplayName),
        ),
        h("span", { className: "anw-nano-tuning__fixed" }, "full · 375 帧"),
      ),
      h("p", { className: "anw-nano-tuning__description" },
        "这些是模型真实采样参数。生成会先在后台验证，失败不会改动当前音色。",
      ),
      h(
        "div",
        { className: "anw-nano-tuning__grid" },
        ...FIELD_DEFINITIONS.map((field) => {
          const inputId = `anw-nano-tuning-${field.key}`;
          const error = view.fieldErrors[field.key];
          const describedBy = `${inputId}-hint${error ? ` ${inputId}-error` : ""}`;
          return h(
            "div",
            { className: "anw-nano-tuning__field", key: field.key },
            h("label", { htmlFor: inputId }, field.label),
            h("span", { id: `${inputId}-hint`, className: "anw-nano-tuning__hint" }, field.hint),
            h("input", {
              id: inputId,
              type: field.key === "seed" ? "text" : "number",
              inputMode: field.inputMode,
              min: field.min,
              max: field.max,
              step: field.step,
              maxLength: field.key === "seed" ? 19 : undefined,
              value: draft[field.key],
              disabled: view.busy,
              "aria-invalid": Boolean(error),
              "aria-describedby": describedBy,
              onChange: (event: ValueChangeEvent) => updateField(field.key, event.target.value),
            }),
            error
              ? h("span", { id: `${inputId}-error`, className: "anw-nano-tuning__field-error", role: "alert" }, error)
              : null,
          );
        }),
      ),
      h(
        "p",
        {
          className: classNames("anw-nano-tuning__status", `is-${view.tone}`),
          role: "status",
          "aria-live": "polite",
        },
        props.busyAction === "create"
          ? "正在创建高级调音…"
          : props.busyAction === "apply"
          ? "正在使用已验证音色…"
          : props.busyAction === "restore"
          ? "正在恢复官方音色…"
          : view.statusLabel,
      ),
      props.errorMessage
        ? h("p", { className: "anw-nano-tuning__error", role: "alert" }, props.errorMessage)
        : null,
      h(
        "div",
        { className: "anw-nano-tuning__actions" },
        h("button", {
          type: "button",
          className: "anw-nano-tuning__button",
          disabled: !view.canReset,
          onClick: reset,
        }, "重置参数"),
        h("button", {
          type: "button",
          className: "anw-nano-tuning__button",
          disabled: !view.canRestoreOfficial,
          onClick: () => props.onRestoreOfficialVoice(
            nanoOfficialVoiceRestoreCommand(props.basePresetId, props.target),
          ),
        }, "恢复官方音色"),
        h("button", {
          type: "button",
          className: "anw-nano-tuning__button is-primary",
          disabled: !view.canCreate,
          onClick: create,
        }, props.experiment?.state === "failed" ? "重新创建并使用" : "创建并使用"),
        view.canApply
          ? h("button", {
            type: "button",
            className: "anw-nano-tuning__button is-primary",
            onClick: apply,
          }, "使用此音色")
          : null,
      ),
    );
  };
}
