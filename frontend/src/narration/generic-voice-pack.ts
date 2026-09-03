import type { MediaAssetLink } from "./contracts";


export const GENERIC_VOICE_PACK_CONTRACT_VERSION = "generic-voice-pack/1" as const;
export const GENERIC_VOICE_GENERATION_COMMAND_CONTRACT_VERSION = "generic-voice-generation-command/1" as const;
export const GENERIC_VOICE_PACK_SLOT_COUNT = 24 as const;

export type GenericVoicePackState =
  | "missing"
  | "building"
  | "ready_to_activate"
  | "active"
  | "retired_for_new_use"
  | "rejected"
  | "failed"
  | "superseded";

export type GenericVoicePackSlotState =
  | "pending"
  | "generating"
  | "validated"
  | "reused"
  | "rejected"
  | "failed";

export type GenericVoicePackSlotCategory =
  | "child"
  | "youth"
  | "middle_age"
  | "older"
  | "neutral_group";

export interface GenericVoicePackSlotSnapshot {
  readonly slotId: string;
  readonly slotKey: string;
  readonly label: string;
  readonly category: GenericVoicePackSlotCategory;
  readonly state: GenericVoicePackSlotState;
  readonly previewAvailable: boolean;
  readonly previewAsset: MediaAssetLink | null;
  readonly voiceProfileId: string | null;
  readonly voiceVersionId: string | null;
  readonly failureCode: string | null;
}

/** Narrow UI projection of `generic-voice-pack/1`. */
export interface GenericVoicePackSnapshot {
  readonly contractVersion: typeof GENERIC_VOICE_PACK_CONTRACT_VERSION;
  readonly language: string;
  readonly packVersionId: string | null;
  readonly state: GenericVoicePackState;
  readonly preparedSlots: number;
  readonly totalSlots: typeof GENERIC_VOICE_PACK_SLOT_COUNT;
  readonly slots: readonly GenericVoicePackSlotSnapshot[];
  readonly failureCode: string | null;
  readonly updatedAt: string;
}

export type GenericVoiceGenerationCommandState =
  | "queued"
  | "building"
  | "ready"
  | "failed"
  | "cancelled"
  | "superseded";

/** Narrow UI projection of `generic-voice-generation-command/1`. */
export interface GenericVoiceGenerationCommandSnapshot {
  readonly contractVersion: typeof GENERIC_VOICE_GENERATION_COMMAND_CONTRACT_VERSION;
  readonly commandId: string;
  readonly packVersionId: string | null;
  readonly state: GenericVoiceGenerationCommandState;
  readonly progressCurrent: number;
  readonly progressTotal: typeof GENERIC_VOICE_PACK_SLOT_COUNT;
  readonly currentSlotKey: string | null;
  readonly cancellable: boolean;
  readonly retryable: boolean;
  readonly terminal: boolean;
  readonly failureCode: string | null;
  readonly updatedAt: string;
}

export interface GenericVoicePackLoadResult {
  readonly pack: GenericVoicePackSnapshot;
  readonly command: GenericVoiceGenerationCommandSnapshot | null;
}

export interface GenericVoicePackReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void];
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
  useRef<T>(initial: T): { current: T };
}

export type GenericVoicePackBusyAction =
  | "load"
  | "refresh"
  | "build"
  | "retry"
  | "cancel"
  | "regenerate"
  | "reject"
  | "preview";

export interface GenericVoicePackProps {
  /** `generic_voice_pool`; omission keeps the whole component fail closed. */
  readonly capabilityEnabled?: boolean;
  readonly canConfigure?: boolean;
  readonly initialPack?: GenericVoicePackSnapshot | null;
  readonly initialCommand?: GenericVoiceGenerationCommandSnapshot | null;
  readonly className?: string;
  readonly refreshIntervalMs?: number;
  readonly onLoadLatest?: (signal: AbortSignal) => Promise<GenericVoicePackLoadResult>;
  readonly onRefreshCommand: (
    commandId: string,
    signal: AbortSignal,
  ) => Promise<GenericVoicePackLoadResult>;
  readonly onBuild: () => Promise<GenericVoicePackLoadResult>;
  readonly onRetry: (commandId: string) => Promise<GenericVoicePackLoadResult>;
  readonly onCancel: (commandId: string) => Promise<GenericVoicePackLoadResult>;
  readonly onRegenerateSlot: (
    slotKey: string,
    expectedPackVersionId: string | null,
  ) => Promise<GenericVoicePackLoadResult>;
  readonly onRejectSlot: (
    slotKey: string,
    expectedPackVersionId: string,
  ) => Promise<GenericVoicePackLoadResult>;
  readonly onPreviewSlot?: (
    slotId: string,
    previewAsset: MediaAssetLink,
  ) => void | Promise<void>;
  readonly onChanged?: (result: GenericVoicePackLoadResult) => void;
}

interface LocalGenericVoicePackState {
  readonly loadPhase: "ready" | "loading" | "error";
  readonly pack: GenericVoicePackSnapshot | null;
  readonly command: GenericVoiceGenerationCommandSnapshot | null;
  readonly busyAction: GenericVoicePackBusyAction | null;
  readonly busySlotKey: string | null;
  readonly errorMessage: string | null;
}

const PACK_STATES = new Set<GenericVoicePackState>([
  "missing",
  "building",
  "ready_to_activate",
  "active",
  "retired_for_new_use",
  "rejected",
  "failed",
  "superseded",
]);
const SLOT_STATES = new Set<GenericVoicePackSlotState>([
  "pending",
  "generating",
  "validated",
  "reused",
  "rejected",
  "failed",
]);
const COMMAND_STATES = new Set<GenericVoiceGenerationCommandState>([
  "queued",
  "building",
  "ready",
  "failed",
  "cancelled",
  "superseded",
]);

const CATEGORY_LABELS: Readonly<Record<GenericVoicePackSlotCategory, string>> = Object.freeze({
  child: "小孩",
  youth: "青年",
  middle_age: "中年",
  older: "老年",
  neutral_group: "中性与群体",
});

const SLOT_STATE_LABELS: Readonly<Record<GenericVoicePackSlotState, string>> = Object.freeze({
  pending: "待准备",
  generating: "正在生成",
  validated: "已验证",
  reused: "已复用",
  rejected: "已拒绝",
  failed: "生成失败",
});

const SLOT_DISPLAY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  crowd_female: "未具名女性对白（单声线）",
  crowd_male: "未具名男性对白（单声线）",
});

export function genericVoicePackSlotDisplayLabel(
  slot: Pick<GenericVoicePackSlotSnapshot, "slotKey" | "label">,
): string {
  return SLOT_DISPLAY_LABELS[slot.slotKey] ?? slot.label;
}

function nonEmpty(value: string): boolean {
  return value.trim().length > 0;
}

function validTimestamp(value: string): boolean {
  return value.includes("T") && Number.isFinite(Date.parse(value));
}

function validProgress(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0 && value <= GENERIC_VOICE_PACK_SLOT_COUNT;
}

function slotIsValid(slot: GenericVoicePackSlotSnapshot): boolean {
  const hasCompleteIdentity = slot.voiceProfileId !== null && slot.voiceVersionId !== null;
  const hasPreviewAsset = slot.previewAsset !== null;
  const validPublication = slot.state === "validated" || slot.state === "reused";
  return nonEmpty(slot.slotKey)
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(slot.slotId)
    && nonEmpty(slot.label)
    && slot.category in CATEGORY_LABELS
    && SLOT_STATES.has(slot.state)
    && ((slot.voiceProfileId === null) === (slot.voiceVersionId === null))
    && slot.previewAvailable === hasPreviewAsset
    && slot.previewAvailable === validPublication
    && (!hasPreviewAsset || hasCompleteIdentity)
    && (!validPublication || (hasCompleteIdentity && hasPreviewAsset))
    && (slot.failureCode === null || nonEmpty(slot.failureCode));
}

export function genericVoicePackSnapshotIsValid(pack: GenericVoicePackSnapshot): boolean {
  if (
    pack.contractVersion !== GENERIC_VOICE_PACK_CONTRACT_VERSION
    || pack.language !== "zh-CN"
    || !PACK_STATES.has(pack.state)
    || !validProgress(pack.preparedSlots)
    || pack.totalSlots !== GENERIC_VOICE_PACK_SLOT_COUNT
    || !validTimestamp(pack.updatedAt)
    || (pack.packVersionId !== null && !nonEmpty(pack.packVersionId))
    || (pack.failureCode !== null && !nonEmpty(pack.failureCode))
    || !pack.slots.every(slotIsValid)
  ) return false;
  const keys = new Set(pack.slots.map((slot) => slot.slotKey));
  if (keys.size !== pack.slots.length || pack.slots.length > GENERIC_VOICE_PACK_SLOT_COUNT) return false;
  const prepared = pack.slots.filter((slot) => slot.state === "validated" || slot.state === "reused").length;
  if (pack.preparedSlots !== prepared) return false;
  if (pack.state === "missing") {
    return pack.packVersionId === null && pack.slots.length === 0 && pack.preparedSlots === 0;
  }
  if (pack.packVersionId === null) return false;
  if (["ready_to_activate", "active", "retired_for_new_use"].includes(pack.state)) {
    return pack.preparedSlots === GENERIC_VOICE_PACK_SLOT_COUNT
      && pack.slots.length === GENERIC_VOICE_PACK_SLOT_COUNT;
  }
  return true;
}

export function genericVoiceGenerationCommandIsValid(
  command: GenericVoiceGenerationCommandSnapshot,
): boolean {
  if (
    command.contractVersion !== GENERIC_VOICE_GENERATION_COMMAND_CONTRACT_VERSION
    || !nonEmpty(command.commandId)
    || !COMMAND_STATES.has(command.state)
    || !validProgress(command.progressCurrent)
    || command.progressTotal !== GENERIC_VOICE_PACK_SLOT_COUNT
    || (command.packVersionId !== null && !nonEmpty(command.packVersionId))
    || (command.currentSlotKey !== null && !nonEmpty(command.currentSlotKey))
    || (command.failureCode !== null && !nonEmpty(command.failureCode))
    || !validTimestamp(command.updatedAt)
  ) return false;
  if (command.state === "queued" || command.state === "building") {
    return !command.terminal && !command.retryable && command.failureCode === null;
  }
  if (!command.terminal || command.cancellable) return false;
  if (command.state === "ready") {
    return !command.retryable && command.failureCode === null;
  }
  if (command.state === "failed") {
    return command.failureCode !== null && nonEmpty(command.failureCode);
  }
  return command.failureCode === null || nonEmpty(command.failureCode);
}

export function genericVoicePackStatusLabel(pack: GenericVoicePackSnapshot): string {
  if (pack.state === "missing") return "尚未开始准备";
  if (pack.state === "building") return "正在后台准备";
  if (pack.state === "ready_to_activate") return "正在完成启用";
  if (pack.state === "active") return "已可用于中文通用角色";
  if (pack.state === "retired_for_new_use") return "已停止用于新的朗读";
  if (pack.state === "rejected") return "当前候选已拒绝";
  if (pack.state === "superseded") return "已有更新的音色包候选";
  return "准备未完成";
}

function actionError(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "操作失败，请稍后重试。";
}

function classNames(...values: readonly (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}

function groupSlots(
  slots: readonly GenericVoicePackSlotSnapshot[],
): readonly Readonly<{
  category: GenericVoicePackSlotCategory;
  label: string;
  slots: readonly GenericVoicePackSlotSnapshot[];
}>[] {
  const categories = Object.keys(CATEGORY_LABELS) as GenericVoicePackSlotCategory[];
  return categories.map((category) => ({
    category,
    label: CATEGORY_LABELS[category],
    slots: slots.filter((slot) => slot.category === category),
  })).filter((group) => group.slots.length > 0);
}

export function createGenericVoicePack(
  React: GenericVoicePackReactRuntime,
): (props: GenericVoicePackProps) => unknown {
  const h = React.createElement;

  return function GenericVoicePack(props: GenericVoicePackProps): unknown {
    const [local, setLocal] = React.useState<LocalGenericVoicePackState>(() => ({
      loadPhase: props.onLoadLatest ? "loading" : "ready",
      pack: props.initialPack ?? null,
      command: props.initialCommand ?? null,
      busyAction: props.onLoadLatest ? "load" : null,
      busySlotKey: null,
      errorMessage: null,
    }));
    const mountedRef = React.useRef(true);
    const actionLockRef = React.useRef(false);

    React.useEffect(() => {
      mountedRef.current = true;
      return () => { mountedRef.current = false; };
    }, []);

    const publish = (result: GenericVoicePackLoadResult): void => {
      if (!mountedRef.current) return;
      setLocal({
        loadPhase: "ready",
        pack: result.pack,
        command: result.command,
        busyAction: null,
        busySlotKey: null,
        errorMessage: null,
      });
      props.onChanged?.(result);
    };

    const fail = (reason: unknown): void => {
      if (!mountedRef.current) return;
      setLocal((current) => ({
        ...current,
        loadPhase: current.pack === null ? "error" : "ready",
        busyAction: null,
        busySlotKey: null,
        errorMessage: actionError(reason),
      }));
    };

    const loadLatest = (): (() => void) | undefined => {
      if (!props.onLoadLatest || actionLockRef.current) return undefined;
      actionLockRef.current = true;
      const controller = new AbortController();
      setLocal((current) => ({
        ...current,
        loadPhase: "loading",
        busyAction: "load",
        errorMessage: null,
      }));
      void props.onLoadLatest(controller.signal).then((result) => {
        if (!controller.signal.aborted) publish(result);
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) fail(reason);
      }).finally(() => { actionLockRef.current = false; });
      return () => controller.abort();
    };

    React.useEffect(loadLatest, [props.capabilityEnabled]);

    React.useEffect(() => {
      const command = local.command;
      const interval = props.refreshIntervalMs ?? 3_000;
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
        void props.onRefreshCommand(command.commandId, controller.signal).then(publish).catch((reason: unknown) => {
          if (!controller.signal.aborted) fail(reason);
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

    if (props.capabilityEnabled !== true && local.pack === null && local.loadPhase !== "loading") return null;

    const packValid = local.pack !== null && genericVoicePackSnapshotIsValid(local.pack);
    const commandValid = local.command === null || genericVoiceGenerationCommandIsValid(local.command);
    const invalid = (local.pack !== null && !packValid) || !commandValid;
    const configurable = props.capabilityEnabled === true && props.canConfigure !== false;
    const busy = local.busyAction !== null;
    const pack = packValid ? local.pack : null;
    const command = commandValid ? local.command : null;

    const invoke = (
      action: GenericVoicePackBusyAction,
      task: () => Promise<GenericVoicePackLoadResult> | void | Promise<void>,
      slotKey: string | null = null,
    ): void => {
      if (actionLockRef.current) return;
      actionLockRef.current = true;
      setLocal((current) => ({
        ...current,
        busyAction: action,
        busySlotKey: slotKey,
        errorMessage: null,
      }));
      let request: Promise<GenericVoicePackLoadResult | void>;
      try {
        request = Promise.resolve(task());
      } catch (reason: unknown) {
        actionLockRef.current = false;
        fail(reason);
        return;
      }
      void request.then((result) => {
        if (result) publish(result);
        else if (mountedRef.current) {
          setLocal((current) => ({ ...current, busyAction: null, busySlotKey: null }));
        }
      }).catch(fail).finally(() => { actionLockRef.current = false; });
    };

    const headingStatus = local.loadPhase === "loading"
      ? "正在恢复…"
      : pack ? `已准备 ${pack.preparedSlots}/${GENERIC_VOICE_PACK_SLOT_COUNT}` : "状态不可用";
    const status = invalid
      ? "音色包状态不完整，已停止操作"
      : local.loadPhase === "error"
        ? local.errorMessage || "无法恢复通用音色包"
        : pack ? genericVoicePackStatusLabel(pack) : "正在加载通用音色包…";

    let primary: unknown = null;
    if (!busy && configurable && pack) {
      const canResume = [
        "missing",
        "failed",
        "rejected",
        "superseded",
        "retired_for_new_use",
      ].includes(pack.state) || (
        pack.state === "building"
        && (command === null || command.state === "cancelled" || command.state === "superseded")
      );
      if (command?.state === "failed" && command.retryable) {
        primary = h(
          "button",
          {
            type: "button",
            className: "anw-generic-voice-pack__primary",
            onClick: () => invoke("retry", () => props.onRetry(command.commandId)),
          },
          "重试",
        );
      } else if (canResume) {
        primary = h(
          "button",
          {
            type: "button",
            className: "anw-generic-voice-pack__primary",
            onClick: () => invoke("build", props.onBuild),
          },
          pack.state === "missing" ? "开始准备" : "继续准备",
        );
      } else if (command && !command.terminal && command.cancellable) {
        primary = h(
          "button",
          {
            type: "button",
            className: "anw-generic-voice-pack__secondary",
            onClick: () => invoke("cancel", () => props.onCancel(command.commandId)),
          },
          "停止后续准备",
        );
      }
    }

    const slotGroups = pack ? groupSlots(pack.slots) : [];
    const packVersionId = pack?.packVersionId ?? null;
    return h(
      "details",
      {
        className: classNames("anw-generic-voice-pack", props.className),
        "data-state": pack?.state ?? local.loadPhase,
      },
      h(
        "summary",
        { className: "anw-generic-voice-pack__summary" },
        h(
          "span",
          null,
          h("strong", null, "中文通用角色音色"),
          h("small", null, status),
        ),
        h("span", { className: "anw-generic-voice-pack__count" }, headingStatus),
      ),
      h(
        "div",
        { className: "anw-generic-voice-pack__body", "aria-busy": busy },
        pack
          ? h(
            "div",
            { className: "anw-generic-voice-pack__progress", "aria-live": "polite" },
            h("progress", {
              value: pack.preparedSlots,
              max: GENERIC_VOICE_PACK_SLOT_COUNT,
              "aria-label": "中文通用角色音色准备进度",
            }),
            h("span", null, `${pack.preparedSlots}/${GENERIC_VOICE_PACK_SLOT_COUNT}`),
          )
          : null,
        busy
          ? h("p", { className: "anw-generic-voice-pack__notice", "aria-live": "polite" },
            local.busyAction === "load" || local.busyAction === "refresh"
              ? "正在恢复最新进度…"
              : local.busyAction === "preview" ? "正在加载试听…" : "正在提交操作…")
          : null,
        local.errorMessage
          ? h("p", { className: "anw-generic-voice-pack__error", role: "alert" }, local.errorMessage)
          : null,
        invalid || local.loadPhase === "error"
          ? h("button", {
            type: "button",
            className: "anw-generic-voice-pack__secondary",
            disabled: busy || !props.onLoadLatest,
            onClick: () => loadLatest(),
          }, "重新加载")
          : primary,
        ...slotGroups.map((group) => h(
          "section",
          { className: "anw-generic-voice-pack__group", key: group.category },
          h("h4", null, group.label),
          h(
            "ul",
            null,
            ...group.slots.map((slot) => {
              const slotBusy = busy && local.busySlotKey === slot.slotKey;
              return h(
                "li",
                { key: slot.slotKey, "data-slot-state": slot.state },
                h(
                  "span",
                  { className: "anw-generic-voice-pack__slot-copy" },
                  h("strong", null, genericVoicePackSlotDisplayLabel(slot)),
                  h("small", null, SLOT_STATE_LABELS[slot.state]),
                ),
                h(
                  "div",
                  { className: "anw-generic-voice-pack__slot-actions" },
                  slot.previewAvailable
                    && slot.previewAsset !== null
                    && props.onPreviewSlot
                    ? h("button", {
                      type: "button",
                      disabled: busy,
                      onClick: () => invoke(
                        "preview",
                        () => props.onPreviewSlot?.(
                          slot.slotId,
                          slot.previewAsset as MediaAssetLink,
                        ),
                        slot.slotKey,
                      ),
                    }, slotBusy && local.busyAction === "preview" ? "加载中…" : "试听")
                    : null,
                  configurable
                    ? h("button", {
                      type: "button",
                      disabled: busy,
                      onClick: () => invoke(
                        "regenerate",
                        () => props.onRegenerateSlot(slot.slotKey, packVersionId),
                        slot.slotKey,
                      ),
                    }, slotBusy && local.busyAction === "regenerate" ? "提交中…" : "重新生成")
                    : null,
                  configurable && packVersionId !== null && slot.state !== "rejected"
                    ? h("button", {
                      type: "button",
                      className: "is-danger",
                      disabled: busy,
                      onClick: () => invoke(
                        "reject",
                        () => props.onRejectSlot(slot.slotKey, packVersionId),
                        slot.slotKey,
                      ),
                    }, slotBusy && local.busyAction === "reject" ? "提交中…" : "拒绝此候选")
                    : null,
                ),
                slot.failureCode
                  ? h("code", { className: "anw-generic-voice-pack__slot-failure" }, slot.failureCode)
                  : null,
              );
            }),
          ),
        )),
        pack?.failureCode
          ? h(
            "details",
            { className: "anw-generic-voice-pack__technical" },
            h("summary", null, "技术详情"),
            h("code", null, pack.failureCode),
          )
          : null,
      ),
    );
  };
}
