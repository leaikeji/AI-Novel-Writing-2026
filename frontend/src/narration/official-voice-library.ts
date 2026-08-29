import {
  IDLE_OFFICIAL_VOICE_USE_STATE,
  OfficialVoiceUseConflictError,
  OfficialVoiceUseResponseError,
  canStartOfficialVoiceUse,
  classifyOfficialVoiceUseFailure,
  nextOfficialVoiceUseIdempotencyKey,
  reduceOfficialVoiceUseState,
  type OfficialVoiceUseAction,
  type OfficialVoiceUseState,
} from "./official-voice-use-state";
import type { OfficialPresetCatalogResponse } from "./contracts";


export const OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION = (
  "moss-tts-official-preset-catalog/2.0"
) as const;
export const OFFICIAL_VOICE_SELECTION_CONTRACT_VERSION = (
  "official-voice-selection/1.0"
) as const;


export const OFFICIAL_VOICE_PRESET_IDS = Object.freeze([
  "onnx.Junhao",
  "onnx.Zhiming",
  "onnx.Weiguo",
  "onnx.Xiaoyu",
  "onnx.Yuewen",
  "onnx.Lingyu",
  "onnx.Trump",
  "onnx.Ava",
  "onnx.Bella",
  "onnx.Adam",
  "onnx.Nathan",
  "onnx.Soyo",
  "onnx.Saki",
  "onnx.Mortis",
  "onnx.Umiri",
  "onnx.Mei",
  "onnx.Anon",
  "onnx.Arisa",
] as const);


export type OfficialVoicePresetId = typeof OFFICIAL_VOICE_PRESET_IDS[number];
export type OfficialVoiceLanguageScope = "zh-CN" | "en" | "ja-JP";
export type OfficialVoiceValidationTier =
  | "canonical_chapter_verified"
  | "pinned_catalog_unreviewed";


export interface OfficialVoiceProvenance {
  readonly schemaVersion: string;
  readonly repository: string;
  readonly revision: string;
  readonly manifestPath: string;
  readonly manifestSha256: string;
  readonly presetId: string;
  readonly manifestVoice: string;
  readonly promptCodesSha256: string;
  readonly promptFrameCount: number;
  readonly promptQuantizerCount: number;
  readonly modelFingerprintSha256: string;
  readonly provenanceFingerprintSha256: string;
}


export interface OfficialVoiceCatalogItem {
  readonly presetId: string;
  readonly displayName: string;
  readonly group: string;
  readonly language: string;
  readonly localUseStatus: "available";
  readonly commercialDistributionStatus: "not_evaluated";
  readonly validationTier: OfficialVoiceValidationTier;
  readonly languageScope: OfficialVoiceLanguageScope;
  readonly selectableNow: boolean;
  readonly previewableNow: boolean;
  readonly renderableExisting: boolean;
  readonly usageNotice: "private_local_writing_tool";
  readonly provenance: OfficialVoiceProvenance;
}


export interface OfficialVoiceCatalog {
  readonly schemaVersion: typeof OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION;
  readonly items: readonly OfficialVoiceCatalogItem[];
}


export type OfficialVoiceCatalogWireLike = OfficialPresetCatalogResponse;


export function officialVoiceCatalogFromWire(
  catalog: OfficialVoiceCatalogWireLike,
): OfficialVoiceCatalog {
  return Object.freeze({
    schemaVersion: catalog.schema_version,
    items: Object.freeze(catalog.items.map((item): OfficialVoiceCatalogItem => Object.freeze({
      presetId: item.preset_id,
      displayName: item.display_name,
      group: item.group,
      language: item.language,
      localUseStatus: item.local_use_status,
      commercialDistributionStatus: item.commercial_distribution_status,
      validationTier: item.validation_tier,
      languageScope: item.language_scope,
      selectableNow: item.selectable_now,
      previewableNow: item.previewable_now,
      renderableExisting: item.renderable_existing,
      usageNotice: item.usage_notice,
      provenance: Object.freeze({
        schemaVersion: item.provenance.schema_version,
        repository: item.provenance.repository,
        revision: item.provenance.revision,
        manifestPath: item.provenance.manifest_path,
        manifestSha256: item.provenance.manifest_sha256,
        presetId: item.provenance.preset_id,
        manifestVoice: item.provenance.manifest_voice,
        promptCodesSha256: item.provenance.prompt_codes_sha256,
        promptFrameCount: item.provenance.prompt_frame_count,
        promptQuantizerCount: item.provenance.prompt_quantizer_count,
        modelFingerprintSha256: item.provenance.model_fingerprint_sha256,
        provenanceFingerprintSha256: item.provenance.provenance_fingerprint_sha256,
      }),
    }))),
  });
}


export type OfficialVoiceSelectionTarget =
  | {
    readonly kind: "narrator";
    readonly targetLanguage: string;
    readonly expectedSettingsVersion: number;
  }
  | {
    readonly kind: "character";
    readonly characterId: string;
    readonly characterName?: string;
    readonly targetLanguage: string;
    readonly expectedSettingsVersion: number;
    readonly expectedBindingVersion: number;
  };


export type OfficialVoiceSelectionRequest =
  | {
    readonly presetId: string;
    readonly targetKind: "narrator";
    readonly expectedSettingsVersion: number;
  }
  | {
    readonly presetId: string;
    readonly targetKind: "character";
    readonly characterId: string;
    readonly expectedSettingsVersion: number;
    readonly expectedBindingVersion: number;
  };


export interface OfficialVoiceSelectionResult {
  readonly replayed: boolean;
  readonly selectionStillCurrent: boolean;
  readonly presetId: string;
  readonly targetKind: "narrator" | "character";
  readonly characterId: string | null;
  readonly settingsVersion: number;
  readonly bindingVersion: number | null;
  readonly languageMismatch: boolean;
}


export interface OfficialVoiceLibraryReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ): void;
}


export interface OfficialVoiceLibraryProps {
  readonly novelId: string;
  readonly catalog: OfficialVoiceCatalog | null;
  readonly target: OfficialVoiceSelectionTarget;
  readonly activePresetId?: string | null;
  readonly loading?: boolean;
  readonly loadError?: string | null;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly createIdempotencyKey?: () => string;
  readonly onUse: (
    novelId: string,
    request: OfficialVoiceSelectionRequest,
    idempotencyKey: string,
    signal: AbortSignal,
  ) => Promise<OfficialVoiceSelectionResult>;
  readonly onPreview?: (
    novelId: string,
    item: OfficialVoiceCatalogItem,
    signal: AbortSignal,
  ) => void | Promise<void>;
  readonly onApplied?: (
    result: OfficialVoiceSelectionResult,
    item: OfficialVoiceCatalogItem,
  ) => void;
  readonly onConflictRefresh?: () => void | Promise<void>;
}


export interface OfficialVoiceLibraryItemModel {
  readonly item: OfficialVoiceCatalogItem;
  readonly languageLabel: string;
  readonly validationLabel: string;
  readonly languageMismatch: boolean;
  readonly languageNotice: string | null;
  readonly availabilityLabel: string;
}


export interface OfficialVoiceLibraryGroupModel {
  readonly languageScope: OfficialVoiceLanguageScope;
  readonly label: string;
  readonly items: readonly OfficialVoiceLibraryItemModel[];
}


export type OfficialVoiceLibraryModel =
  | {
    readonly status: "ready";
    readonly groups: readonly OfficialVoiceLibraryGroupModel[];
    readonly itemCount: 18;
    readonly message: string;
  }
  | {
    readonly status: "empty" | "invalid";
    readonly groups: readonly OfficialVoiceLibraryGroupModel[];
    readonly itemCount: 0;
    readonly message: string;
  };


interface PreviewState {
  readonly phase: "idle" | "loading" | "ready" | "error";
  readonly presetId: string | null;
  readonly message: string;
}


const IDLE_PREVIEW_STATE: PreviewState = Object.freeze({
  phase: "idle",
  presetId: null,
  message: "",
});


const LANGUAGE_ORDER: readonly OfficialVoiceLanguageScope[] = ["zh-CN", "en", "ja-JP"];
const LANGUAGE_LABELS: Readonly<Record<OfficialVoiceLanguageScope, string>> = Object.freeze({
  "zh-CN": "中文",
  en: "English",
  "ja-JP": "日本語",
});
const LANGUAGE_COUNTS: Readonly<Record<OfficialVoiceLanguageScope, number>> = Object.freeze({
  "zh-CN": 6,
  en: 5,
  "ja-JP": 7,
});
const VERIFIED_PRESET_IDS = new Set(["onnx.Junhao", "onnx.Zhiming", "onnx.Xiaoyu"]);
const EXPECTED_LANGUAGE_BY_PRESET: Readonly<Record<OfficialVoicePresetId, OfficialVoiceLanguageScope>> = (
  Object.freeze(Object.fromEntries(OFFICIAL_VOICE_PRESET_IDS.map((presetId, index) => [
    presetId,
    index < 6 ? "zh-CN" : index < 11 ? "en" : "ja-JP",
  ])) as Record<OfficialVoicePresetId, OfficialVoiceLanguageScope>)
);


export function officialVoiceLanguageMatches(
  sourceLanguage: string,
  targetLanguage: string,
): boolean {
  const source = sourceLanguage.trim().split("-", 1)[0]?.toLocaleLowerCase("en-US") ?? "";
  const target = targetLanguage.trim().split("-", 1)[0]?.toLocaleLowerCase("en-US") ?? "";
  return source !== "" && target !== "" && source === target;
}


function validationLabel(tier: OfficialVoiceValidationTier): string {
  return tier === "canonical_chapter_verified"
    ? "已通过章节技术验证"
    : "固定目录 · 未专项听检";
}


function availabilityLabel(item: OfficialVoiceCatalogItem): string {
  if (item.selectableNow) return "本机可直接使用";
  if (item.renderableExisting) return "暂停新选择 · 已有绑定可朗读";
  return "当前不可新用";
}


function catalogIntegrityIssue(catalog: OfficialVoiceCatalog): string | null {
  if (catalog.schemaVersion !== OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION) {
    return "官方音色目录版本不兼容，已停止展示可操作卡片。";
  }
  if (catalog.items.length !== OFFICIAL_VOICE_PRESET_IDS.length) {
    return "官方音色目录不完整，已停止展示可操作卡片。";
  }
  const seen = new Set<string>();
  for (let index = 0; index < catalog.items.length; index += 1) {
    const item = catalog.items[index];
    const expectedPresetId = OFFICIAL_VOICE_PRESET_IDS[index];
    if (
      item === undefined
      || item.presetId !== expectedPresetId
      || seen.has(item.presetId)
      || item.displayName.trim() === ""
      || item.group.trim() === ""
      || item.language !== item.languageScope
      || item.languageScope !== EXPECTED_LANGUAGE_BY_PRESET[expectedPresetId]
      || item.localUseStatus !== "available"
      || item.commercialDistributionStatus !== "not_evaluated"
      || item.usageNotice !== "private_local_writing_tool"
      || typeof item.selectableNow !== "boolean"
      || typeof item.previewableNow !== "boolean"
      || typeof item.renderableExisting !== "boolean"
      || item.provenance?.presetId !== item.presetId
      || item.provenance.repository.trim() === ""
      || item.provenance.revision.trim() === ""
      || item.provenance.manifestPath.trim() === ""
      || item.provenance.provenanceFingerprintSha256.trim() === ""
    ) return "官方音色目录身份或顺序校验失败，已停止展示可操作卡片。";
    const expectedTier = VERIFIED_PRESET_IDS.has(item.presetId)
      ? "canonical_chapter_verified"
      : "pinned_catalog_unreviewed";
    if (item.validationTier !== expectedTier) {
      return "官方音色目录验证等级与已知证据不一致，已停止展示可操作卡片。";
    }
    seen.add(item.presetId);
  }
  return null;
}


export function createOfficialVoiceLibraryModel(
  catalog: OfficialVoiceCatalog | null,
  targetLanguage: string,
): OfficialVoiceLibraryModel {
  if (catalog === null || catalog.items.length === 0) {
    return Object.freeze({
      status: "empty",
      groups: Object.freeze([]),
      itemCount: 0,
      message: "当前没有可显示的官方音色。请刷新目录后重试。",
    });
  }
  const issue = catalogIntegrityIssue(catalog);
  if (issue !== null) {
    return Object.freeze({
      status: "invalid",
      groups: Object.freeze([]),
      itemCount: 0,
      message: issue,
    });
  }
  const groups = LANGUAGE_ORDER.map((languageScope): OfficialVoiceLibraryGroupModel => {
    const items = catalog.items
      .filter((item) => item.languageScope === languageScope)
      .map((item): OfficialVoiceLibraryItemModel => {
        const mismatch = !officialVoiceLanguageMatches(item.languageScope, targetLanguage);
        return Object.freeze({
          item,
          languageLabel: LANGUAGE_LABELS[item.languageScope],
          validationLabel: validationLabel(item.validationTier),
          languageMismatch: mismatch,
          languageNotice: mismatch
            ? item.languageScope === "zh-CN"
              ? `当前朗读语言为 ${targetLanguage || "未设置"}；${LANGUAGE_LABELS[item.languageScope]}音色仍可直接使用。`
              : `跨语言 · 本项目未专项听检。当前朗读语言为 ${targetLanguage || "未设置"}；${LANGUAGE_LABELS[item.languageScope]}音色仍可直接使用。`
            : item.languageScope === "zh-CN"
              ? null
              : "跨语言 · 本项目未专项听检；这不会阻止直接使用。",
          availabilityLabel: availabilityLabel(item),
        });
      });
    return Object.freeze({
      languageScope,
      label: `${LANGUAGE_LABELS[languageScope]}（${LANGUAGE_COUNTS[languageScope]}）`,
      items: Object.freeze(items),
    });
  });
  return Object.freeze({
    status: "ready",
    groups: Object.freeze(groups),
    itemCount: 18,
    message: "18 个固定官方音色已加载；试听可选，使用不需要额外确认。",
  });
}


export function createOfficialVoiceSelectionRequest(
  presetId: string,
  target: OfficialVoiceSelectionTarget,
): OfficialVoiceSelectionRequest {
  if (target.kind === "narrator") {
    return Object.freeze({
      presetId,
      targetKind: "narrator",
      expectedSettingsVersion: target.expectedSettingsVersion,
    });
  }
  return Object.freeze({
    presetId,
    targetKind: "character",
    characterId: target.characterId,
    expectedSettingsVersion: target.expectedSettingsVersion,
    expectedBindingVersion: target.expectedBindingVersion,
  });
}


function targetIdentity(novelId: string, target: OfficialVoiceSelectionTarget): string {
  return target.kind === "narrator"
    ? [novelId, target.kind, target.targetLanguage, target.expectedSettingsVersion].join(":")
    : [
      novelId,
      target.kind,
      target.characterId,
      target.targetLanguage,
      target.expectedSettingsVersion,
      target.expectedBindingVersion,
    ].join(":");
}


function targetIsReady(novelId: string, target: OfficialVoiceSelectionTarget): boolean {
  if (
    novelId.trim() === ""
    || target.targetLanguage.trim() === ""
    || !Number.isSafeInteger(target.expectedSettingsVersion)
    || target.expectedSettingsVersion < 0
  ) return false;
  return target.kind === "narrator" || (
    target.characterId.trim() !== ""
    && Number.isSafeInteger(target.expectedBindingVersion)
    && target.expectedBindingVersion >= 0
  );
}


function targetActionLabel(target: OfficialVoiceSelectionTarget): string {
  if (target.kind === "narrator") return "设为旁白";
  return target.characterName?.trim()
    ? `用于${target.characterName.trim()}`
    : "用于此人物";
}


function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return value !== null && typeof value === "object";
}


function successMessage(
  item: OfficialVoiceCatalogItem,
  target: OfficialVoiceSelectionTarget,
): string {
  return target.kind === "narrator"
    ? `${item.displayName}已设为旁白。`
    : `${item.displayName}已用于${target.characterName?.trim() || "此人物"}。`;
}


function assertSelectionResult(
  result: OfficialVoiceSelectionResult,
  item: OfficialVoiceCatalogItem,
  target: OfficialVoiceSelectionTarget,
): void {
  const expectedCharacterId = target.kind === "character" ? target.characterId : null;
  if (
    !isRecord(result)
    || typeof result.replayed !== "boolean"
    || typeof result.selectionStillCurrent !== "boolean"
    || result.presetId !== item.presetId
    || result.targetKind !== target.kind
    || result.characterId !== expectedCharacterId
    || !Number.isSafeInteger(result.settingsVersion)
    || result.settingsVersion < 1
    || typeof result.languageMismatch !== "boolean"
    || (target.kind === "character" && (
      !Number.isSafeInteger(result.bindingVersion)
      || (result.bindingVersion ?? 0) < 1
    ))
    || (target.kind === "narrator" && result.bindingVersion !== null)
  ) {
    throw new OfficialVoiceUseResponseError("official voice selection result changed identity");
  }
  if (!result.selectionStillCurrent) {
    throw new OfficialVoiceUseConflictError();
  }
}


function safeDomToken(value: string): string {
  const token = value.replace(/[^A-Za-z0-9_-]/gu, "-").replace(/-+/gu, "-");
  return token || "scope";
}


function isAbortLike(reason: unknown): boolean {
  return reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError";
}


export function createOfficialVoiceLibrary(
  React: OfficialVoiceLibraryReactRuntime,
): (props: OfficialVoiceLibraryProps) => unknown {
  const h = React.createElement;

  return function OfficialVoiceLibrary(props: OfficialVoiceLibraryProps): unknown {
    const [useState, setUseState] = React.useState<OfficialVoiceUseState>(
      IDLE_OFFICIAL_VOICE_USE_STATE,
    );
    const [previewState, setPreviewState] = React.useState<PreviewState>(IDLE_PREVIEW_STATE);
    const useStateRef = React.useRef(useState);
    useStateRef.current = useState;
    const previewStateRef = React.useRef(previewState);
    previewStateRef.current = previewState;
    const useRequestSequenceRef = React.useRef(0);
    const previewSequenceRef = React.useRef(0);
    const useAbortRef = React.useRef<AbortController | null>(null);
    const previewAbortRef = React.useRef<AbortController | null>(null);
    const scopeIdentity = targetIdentity(props.novelId, props.target);
    const model = createOfficialVoiceLibraryModel(props.catalog, props.target.targetLanguage);
    const targetReady = targetIsReady(props.novelId, props.target);
    const prefix = `anw-official-voice-${safeDomToken(props.novelId)}-${
      props.target.kind === "character" ? safeDomToken(props.target.characterId) : "narrator"
    }`;

    const transition = (action: OfficialVoiceUseAction): OfficialVoiceUseState => {
      const next = reduceOfficialVoiceUseState(useStateRef.current, action);
      useStateRef.current = next;
      setUseState(next);
      return next;
    };

    const commitPreview = (next: PreviewState): void => {
      previewStateRef.current = next;
      setPreviewState(next);
    };

    React.useEffect(() => {
      useAbortRef.current?.abort();
      previewAbortRef.current?.abort();
      const requestId = ++useRequestSequenceRef.current;
      previewSequenceRef.current += 1;
      transition({ type: "reset", requestId });
      commitPreview(IDLE_PREVIEW_STATE);
    }, [scopeIdentity]);

    React.useEffect(() => () => {
      useAbortRef.current?.abort();
      previewAbortRef.current?.abort();
      useRequestSequenceRef.current += 1;
      previewSequenceRef.current += 1;
    }, []);

    const applyVoice = (item: OfficialVoiceCatalogItem) => {
      const current = useStateRef.current;
      const alreadyApplied = current.phase === "applied" && current.presetId === item.presetId;
      if (
        props.disabled === true
        || !targetReady
        || !item.selectableNow
        || alreadyApplied
        || !canStartOfficialVoiceUse(current)
      ) return;
      const idempotencyKey = nextOfficialVoiceUseIdempotencyKey(
        current,
        item.presetId,
        props.createIdempotencyKey,
      );
      const requestId = ++useRequestSequenceRef.current;
      const controller = new AbortController();
      useAbortRef.current?.abort();
      useAbortRef.current = controller;
      const request = createOfficialVoiceSelectionRequest(item.presetId, props.target);
      const started = transition({
        type: "start",
        presetId: item.presetId,
        requestId,
        idempotencyKey,
        message: `正在${targetActionLabel(props.target)}：${item.displayName}…`,
      });
      if (started.phase !== "applying" || started.requestId !== requestId) return;
      void (async () => {
        let result: OfficialVoiceSelectionResult;
        try {
          result = await props.onUse(
            props.novelId,
            request,
            idempotencyKey,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          assertSelectionResult(result, item, props.target);
        } catch (reason: unknown) {
          if (controller.signal.aborted || isAbortLike(reason)) return;
          transition({
            type: "fail",
            presetId: item.presetId,
            requestId,
            failure: classifyOfficialVoiceUseFailure(reason),
          });
          return;
        }
        transition({
          type: "succeed",
          presetId: item.presetId,
          requestId,
          message: successMessage(item, props.target),
        });
        try {
          props.onApplied?.(result, item);
        } catch {
          // A consumer refresh callback cannot change the already committed server result.
        }
      })();
    };

    const previewVoice = (item: OfficialVoiceCatalogItem) => {
      const previewHandler = props.onPreview;
      if (
        props.disabled === true
        || !item.previewableNow
        || previewHandler === undefined
        || previewStateRef.current.phase === "loading"
      ) return;
      const sequence = ++previewSequenceRef.current;
      const controller = new AbortController();
      previewAbortRef.current?.abort();
      previewAbortRef.current = controller;
      commitPreview(Object.freeze({
        phase: "loading",
        presetId: item.presetId,
        message: `正在加载 ${item.displayName} 试听…`,
      }));
      void Promise.resolve()
        .then(() => previewHandler(props.novelId, item, controller.signal))
        .then(() => {
          if (controller.signal.aborted || sequence !== previewSequenceRef.current) return;
          commitPreview(Object.freeze({
            phase: "ready",
            presetId: item.presetId,
            message: `${item.displayName} 试听已开始；仍可直接使用，无需确认。`,
          }));
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted || sequence !== previewSequenceRef.current || isAbortLike(reason)) return;
          commitPreview(Object.freeze({
            phase: "error",
            presetId: item.presetId,
            message: `${item.displayName} 试听失败；这不影响直接使用。`,
          }));
        });
    };

    const liveMessage = useState.phase === "idle" && previewState.message
      ? previewState.message
      : useState.message;
    const currentPresetId = useState.phase === "applied"
      ? useState.presetId
      : props.activePresetId ?? null;
    const globalUseBlocked = props.disabled === true
      || !targetReady
      || useState.phase === "applying"
      || useState.phase === "conflict";

    const renderItem = (itemModel: OfficialVoiceLibraryItemModel): unknown => {
      const item = itemModel.item;
      const isCurrent = currentPresetId === item.presetId;
      const isApplying = useState.phase === "applying" && useState.presetId === item.presetId;
      const retrying = useState.phase === "error"
        && useState.presetId === item.presetId
        && useState.failure.retryable;
      const nonRetryableSameItem = useState.phase === "error"
        && useState.presetId === item.presetId
        && !useState.failure.retryable;
      const previewing = previewState.phase === "loading"
        && previewState.presetId === item.presetId;
      const warningId = `${prefix}-${safeDomToken(item.presetId)}-language-note`;
      const unavailableId = `${prefix}-${safeDomToken(item.presetId)}-availability`;
      const useDisabled = globalUseBlocked
        || !item.selectableNow
        || isCurrent
        || nonRetryableSameItem;
      const previewDisabled = props.disabled === true
        || !item.previewableNow
        || props.onPreview === undefined
        || previewState.phase === "loading";
      const describedBy = [
        itemModel.languageNotice === null ? null : warningId,
        item.selectableNow ? null : unavailableId,
      ].filter(Boolean).join(" ") || undefined;
      return h(
        "li",
        { key: item.presetId, className: "anw-official-voice-library__item" },
        h(
          "article",
          {
            className: [
              "anw-official-voice-card",
              isCurrent ? "is-current" : "",
              item.selectableNow ? "" : "is-unavailable",
            ].filter(Boolean).join(" "),
            "data-official-preset-id": item.presetId,
            "data-language-scope": item.languageScope,
            "data-validation-tier": item.validationTier,
            "data-selectable-now": String(item.selectableNow),
            "data-previewable-now": String(item.previewableNow),
            "data-renderable-existing": String(item.renderableExisting),
          },
          h("div", { className: "anw-official-voice-card__heading" },
            h("div", null,
              h("h4", null, item.displayName),
              h("p", { className: "anw-official-voice-card__group" }, item.group),
            ),
            isCurrent
              ? h("span", { className: "anw-official-voice-card__current" }, "当前使用")
              : null,
          ),
          h("div", { className: "anw-official-voice-card__badges" },
            h("span", { className: "anw-official-voice-card__badge" }, itemModel.languageLabel),
            h(
              "span",
              {
                className: [
                  "anw-official-voice-card__badge",
                  item.validationTier === "canonical_chapter_verified" ? "is-verified" : "is-unreviewed",
                ].join(" "),
              },
              itemModel.validationLabel,
            ),
            h(
              "span",
              {
                id: unavailableId,
                className: [
                  "anw-official-voice-card__badge",
                  item.selectableNow ? "is-available" : "is-unavailable",
                ].join(" "),
              },
              itemModel.availabilityLabel,
            ),
          ),
          itemModel.languageNotice === null
            ? null
            : h(
              "p",
              {
                id: warningId,
                className: "anw-official-voice-card__language-note",
                role: "note",
              },
              itemModel.languageNotice,
            ),
          h("div", { className: "anw-official-voice-card__actions" },
            h(
              "button",
              {
                type: "button",
                className: "anw-official-voice-card__preview",
                disabled: previewDisabled,
                "aria-disabled": previewDisabled ? true : undefined,
                "aria-label": `${item.previewableNow ? "试听" : "试听暂不可用"}${item.displayName}`,
                onClick: () => previewVoice(item),
              },
              previewing
                ? "加载试听…"
                : item.previewableNow && props.onPreview !== undefined
                  ? "试听"
                  : "试听暂不可用",
            ),
            h(
              "button",
              {
                type: "button",
                className: "anw-official-voice-card__use",
                disabled: useDisabled,
                "aria-disabled": useDisabled ? true : undefined,
                "aria-pressed": isCurrent,
                "aria-describedby": describedBy,
                onClick: () => applyVoice(item),
              },
              isApplying
                ? "正在使用…"
                : isCurrent
                  ? "当前使用"
                  : retrying
                    ? "重试使用"
                    : targetActionLabel(props.target),
            ),
          ),
          h(
            "details",
            { className: "anw-official-voice-card__details" },
            h("summary", null, "模型详情"),
            h("dl", null,
              h("div", null, h("dt", null, "Preset ID"), h("dd", null, item.presetId)),
              h("div", null, h("dt", null, "来源语言"), h("dd", null, item.language)),
              h("div", null, h("dt", null, "固定来源"), h("dd", null, item.provenance.repository)),
              h("div", null, h("dt", null, "模型 revision"), h("dd", null, item.provenance.revision)),
              h("div", null, h("dt", null, "Manifest"), h("dd", null, item.provenance.manifestPath)),
              h(
                "div",
                null,
                h("dt", null, "目录证据"),
                h("dd", null, item.provenance.provenanceFingerprintSha256),
              ),
              h("div", null,
                h("dt", null, "本地用途"),
                h("dd", null, "个人本机写作朗读可用"),
              ),
              h("div", null,
                h("dt", null, "商业发布/再分发"),
                h("dd", null, "未评估"),
              ),
              h("div", null,
                h("dt", null, "已有版本渲染"),
                h("dd", null, item.renderableExisting ? "可用" : "当前不可用"),
              ),
            ),
          ),
        ),
      );
    };

    const content = props.loading === true
      ? h("p", { className: "anw-official-voice-library__empty", role: "status" }, "正在加载 18 个官方音色…")
      : props.loadError
        ? h("p", { className: "anw-official-voice-library__empty is-error", role: "status" }, props.loadError)
        : model.status !== "ready"
          ? h("p", { className: "anw-official-voice-library__empty", role: "status" }, model.message)
          : model.groups.map((group) => {
            const groupId = `${prefix}-${safeDomToken(group.languageScope)}-heading`;
            return h(
              "section",
              {
                key: group.languageScope,
                className: "anw-official-voice-library__group",
                "aria-labelledby": groupId,
              },
              h("h3", { id: groupId }, group.label),
              h(
                "ul",
                { className: "anw-official-voice-library__grid" },
                ...group.items.map(renderItem),
              ),
            );
          });

    return h(
      "section",
      {
        className: ["anw-official-voice-library", props.className ?? ""].filter(Boolean).join(" "),
        role: "region",
        "aria-labelledby": `${prefix}-heading`,
        "aria-describedby": `${prefix}-summary ${prefix}-live-status`,
        "aria-busy": props.loading === true || useState.phase === "applying",
        "data-catalog-status": props.loading === true
          ? "loading"
          : props.loadError
            ? "error"
            : model.status,
        "data-official-voice-count": model.itemCount,
        "data-official-voice-use-phase": useState.phase,
      },
      h("header", { className: "anw-official-voice-library__header" },
        h("div", null,
          h("p", { className: "anw-official-voice-library__eyebrow" }, "MOSS-TTS-Nano · 官方固定音色"),
          h("h2", { id: `${prefix}-heading` }, "官方音色库"),
          h(
            "p",
            { id: `${prefix}-summary` },
            "固定收录 18 个官方音色；当前可用项可在个人本机项目中直接选择，试听可选，不需要语言、版权或质量确认。",
          ),
        ),
        h("span", { className: "anw-official-voice-library__count" }, "18 项"),
      ),
      targetReady
        ? null
        : h(
          "p",
          { className: "anw-official-voice-library__scope-error", role: "status" },
          "当前作品或人物设置尚未就绪，暂不能更改音色。",
        ),
      h(
        "p",
        {
          id: `${prefix}-live-status`,
          className: [
            "anw-official-voice-library__live-status",
            useState.phase === "error" || useState.phase === "conflict" ? "is-error" : "",
          ].filter(Boolean).join(" "),
          role: "status",
          "aria-live": "polite",
          "aria-atomic": true,
        },
        liveMessage,
      ),
      useState.phase === "conflict" && props.onConflictRefresh !== undefined
        ? h(
          "button",
          {
            type: "button",
            className: "anw-official-voice-library__refresh",
            onClick: () => { void props.onConflictRefresh?.(); },
          },
          "刷新当前设置",
        )
        : null,
      ...(Array.isArray(content) ? content : [content]),
    );
  };
}
