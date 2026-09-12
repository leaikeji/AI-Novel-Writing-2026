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
import {
  OFFICIAL_PRESET_EVIDENCE,
  OFFICIAL_PRESET_IDS,
  type OfficialPresetCatalogResponse,
  type OfficialPresetId,
  type OfficialPresetLanguage,
  type OfficialVoicePreviewAudioResponse,
} from "./contracts";
import {
  DEFAULT_ALIYUN_TTS_MODEL_ID,
  DEFAULT_TTS_PROVIDER_ID,
  type AliyunTTSModelId,
  type TTSProviderId,
} from "./tts-provider";


export const OFFICIAL_VOICE_CATALOG_SCHEMA_VERSION = (
  "qwen-tts-preset-catalog/2"
) as const;
export const OFFICIAL_VOICE_SELECTION_CONTRACT_VERSION = (
  "official-voice-selection/1.0"
) as const;


export const OFFICIAL_VOICE_PRESET_IDS = OFFICIAL_PRESET_IDS;


export type OfficialVoicePresetId = OfficialPresetId;
export type OfficialVoiceLanguageScope = OfficialPresetLanguage;
export type OfficialVoiceValidationTier =
  | "canonical_chapter_verified"
  | "pinned_catalog_unreviewed";


export interface OfficialVoiceProvenance {
  readonly schemaVersion: string;
  readonly catalogId: string;
  readonly presetId: string;
  readonly localModelId: string;
  readonly localModelRevision: string;
  readonly providerVoiceIds: Readonly<Record<string, string>>;
  readonly modelFingerprintSha256: string;
  readonly provenanceFingerprintSha256: string;
}


export interface OfficialVoiceCatalogItem {
  readonly presetId: string;
  readonly displayName: string;
  readonly officialSpeaker: string;
  readonly nativeLanguage: OfficialVoiceLanguageScope;
  readonly dialect: string | null;
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
      officialSpeaker: item.official_speaker,
      nativeLanguage: item.native_language,
      dialect: item.dialect,
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
        catalogId: item.provenance.catalog_id,
        presetId: item.provenance.preset_id,
        localModelId: item.provenance.local_model_id,
        localModelRevision: item.provenance.local_model_revision,
        providerVoiceIds: Object.freeze({ ...item.provenance.provider_voice_ids }),
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
  /** Embedded mode omits the duplicate library title inside a configurator disclosure. */
  readonly presentation?: "standalone" | "embedded";
  readonly providerSelection?: OfficialVoiceProviderSelection;
  readonly headerAction?: unknown;
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
  ) => void | OfficialVoicePreviewAudioResponse["cache_status"]
    | Promise<void | OfficialVoicePreviewAudioResponse["cache_status"]>;
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
  readonly providerAvailable: boolean;
  readonly providerAvailabilityLabel: string;
}


export interface OfficialVoiceProviderSelection {
  readonly providerId: TTSProviderId;
  readonly aliyunModelId: AliyunTTSModelId;
}


export interface OfficialVoiceLibraryGroupModel {
  readonly languageScope: OfficialVoiceLanguageScope;
  readonly label: string;
  readonly items: readonly OfficialVoiceLibraryItemModel[];
}


export type OfficialVoiceLanguageFilter = "all" | OfficialVoiceLanguageScope;


export type OfficialVoiceLibraryModel =
  | {
    readonly status: "ready";
    readonly groups: readonly OfficialVoiceLibraryGroupModel[];
    readonly itemCount: number;
    readonly message: string;
  }
  | {
    readonly status: "empty" | "invalid";
    readonly groups: readonly OfficialVoiceLibraryGroupModel[];
    readonly itemCount: 0;
    readonly message: string;
  };


export function filterOfficialVoiceLibraryGroups(
  groups: readonly OfficialVoiceLibraryGroupModel[],
  query: string,
  languageFilter: OfficialVoiceLanguageFilter,
): readonly OfficialVoiceLibraryGroupModel[] {
  const normalizedQuery = query.trim().toLocaleLowerCase("en-US");
  return groups
    .filter((group) => (
      languageFilter === "all" || group.languageScope === languageFilter
    ))
    .map((group) => Object.freeze({
      ...group,
      items: Object.freeze(group.items.filter(({ item, languageLabel }) => (
        normalizedQuery === ""
        || [
          item.displayName,
          item.presetId,
          item.officialSpeaker,
          item.group,
          languageLabel,
        ]
          .some((value) => value.toLocaleLowerCase("en-US").includes(normalizedQuery))
      ))),
    }))
    .filter((group) => group.items.length > 0);
}


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


const LANGUAGE_ORDER: readonly OfficialVoiceLanguageScope[] = ["zh-CN"];
const MANDARIN_LANGUAGE_LABEL = "普通话";
const EVIDENCE_BY_PRESET = new Map(
  OFFICIAL_PRESET_EVIDENCE.map((evidence) => [evidence.presetId, evidence] as const),
);


export function officialVoiceLanguageFilterForTarget(
  _targetLanguage: string,
): OfficialVoiceLanguageScope {
  return "zh-CN";
}


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


export function officialVoiceProviderMappingKey(
  selection: OfficialVoiceProviderSelection,
): string {
  return selection.providerId === "local_qwen3_tts"
    ? "local_qwen3_tts"
    : `aliyun_qwen_audio_tts:${selection.aliyunModelId}`;
}


export function officialVoiceIsAvailableForProvider(
  item: OfficialVoiceCatalogItem,
  selection: OfficialVoiceProviderSelection,
): boolean {
  const voiceId = item.provenance.providerVoiceIds[officialVoiceProviderMappingKey(selection)];
  return typeof voiceId === "string" && voiceId.trim() !== "";
}


function providerAvailabilityLabel(
  item: OfficialVoiceCatalogItem,
  selection: OfficialVoiceProviderSelection,
): string {
  if (selection.providerId === "local_qwen3_tts") return "本地可用";
  return officialVoiceIsAvailableForProvider(item, selection)
    ? "当前云端模型有映射（未实测）"
    : "仅本地可用";
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
    const expectedEvidence = EVIDENCE_BY_PRESET.get(expectedPresetId);
    if (
      item === undefined
      || expectedEvidence === undefined
      || item.presetId !== expectedPresetId
      || seen.has(item.presetId)
      || item.displayName.trim() === ""
      || item.group.trim() === ""
      || item.language !== item.languageScope
      || item.languageScope !== "zh-CN"
      || item.officialSpeaker !== expectedEvidence.localVoiceId
      || item.nativeLanguage !== expectedEvidence.nativeLanguage
      || item.localUseStatus !== "available"
      || item.commercialDistributionStatus !== "not_evaluated"
      || item.usageNotice !== "private_local_writing_tool"
      || typeof item.selectableNow !== "boolean"
      || typeof item.previewableNow !== "boolean"
      || typeof item.renderableExisting !== "boolean"
      || item.provenance?.presetId !== item.presetId
      || item.provenance.catalogId !== "qwen-provider-voice-map/1"
      || item.provenance.localModelId.trim() === ""
      || item.provenance.localModelRevision.trim() === ""
      || item.provenance.provenanceFingerprintSha256.trim() === ""
    ) return "官方音色目录身份或顺序校验失败，已停止展示可操作卡片。";
    const expectedTier = expectedEvidence.validationTier;
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
  providerSelection: OfficialVoiceProviderSelection = {
    providerId: DEFAULT_TTS_PROVIDER_ID,
    aliyunModelId: DEFAULT_ALIYUN_TTS_MODEL_ID,
  },
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
          languageLabel: MANDARIN_LANGUAGE_LABEL,
          validationLabel: validationLabel(item.validationTier),
          languageMismatch: mismatch,
          languageNotice: mismatch
            ? `当前朗读语言为 ${targetLanguage || "未设置"}；新选择固定使用普通话。`
            : null,
          availabilityLabel: availabilityLabel(item),
          providerAvailable: officialVoiceIsAvailableForProvider(item, providerSelection),
          providerAvailabilityLabel: providerAvailabilityLabel(item, providerSelection),
        });
      });
    return Object.freeze({
      languageScope,
      label: `${MANDARIN_LANGUAGE_LABEL}（${items.length}）`,
      items: Object.freeze(items),
    });
  });
  const itemCount = groups.reduce((count, group) => count + group.items.length, 0);
  return Object.freeze({
    status: "ready",
    groups: Object.freeze(groups),
    itemCount,
    message: "Qwen 普通话官方音色已加载；外语与方言不会作为新选择展示。",
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


function targetContextLabel(target: OfficialVoiceSelectionTarget): string {
  if (target.kind === "narrator") return "作品旁白";
  return target.characterName?.trim()
    ? `人物${target.characterName.trim()}`
    : "当前人物";
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


export function assertOfficialVoiceSelectionIdentity(
  result: OfficialVoiceSelectionResult,
  expectedPresetId: string,
  target: OfficialVoiceSelectionTarget,
): void {
  const expectedCharacterId = target.kind === "character" ? target.characterId : null;
  if (
    !isRecord(result)
    || typeof result.replayed !== "boolean"
    || typeof result.selectionStillCurrent !== "boolean"
    || result.presetId !== expectedPresetId
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
}


export function assertOfficialVoiceSelectionResult(
  result: OfficialVoiceSelectionResult,
  expectedPresetId: string,
  target: OfficialVoiceSelectionTarget,
): void {
  assertOfficialVoiceSelectionIdentity(result, expectedPresetId, target);
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
    const [searchQuery, setSearchQuery] = React.useState("");
    const [languageFilter, setLanguageFilter] = React.useState<OfficialVoiceLanguageFilter>(() => (
      officialVoiceLanguageFilterForTarget(props.target.targetLanguage)
    ));
    const useStateRef = React.useRef(useState);
    useStateRef.current = useState;
    const previewStateRef = React.useRef(previewState);
    previewStateRef.current = previewState;
    const useRequestSequenceRef = React.useRef(0);
    const previewSequenceRef = React.useRef(0);
    const useAbortRef = React.useRef<AbortController | null>(null);
    const previewAbortRef = React.useRef<AbortController | null>(null);
    const scopeIdentity = targetIdentity(props.novelId, props.target);
    const providerSelection = props.providerSelection ?? {
      providerId: DEFAULT_TTS_PROVIDER_ID,
      aliyunModelId: DEFAULT_ALIYUN_TTS_MODEL_ID,
    };
    const model = createOfficialVoiceLibraryModel(
      props.catalog,
      props.target.targetLanguage,
      providerSelection,
    );
    const filteredGroups = model.status === "ready"
      ? filterOfficialVoiceLibraryGroups(model.groups, searchQuery, languageFilter)
      : [];
    const filteredCount = filteredGroups.reduce(
      (total, group) => total + group.items.length,
      0,
    );
    const targetReady = targetIsReady(props.novelId, props.target);
    const prefix = `anw-official-voice-${safeDomToken(props.novelId)}-${
      props.target.kind === "character" ? safeDomToken(props.target.characterId) : "narrator"
    }`;

    const commitUse = (next: OfficialVoiceUseState): OfficialVoiceUseState => {
      useStateRef.current = next;
      setUseState(next);
      return next;
    };

    const transition = (action: OfficialVoiceUseAction): OfficialVoiceUseState => {
      const next = reduceOfficialVoiceUseState(useStateRef.current, action);
      return commitUse(next);
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
      setSearchQuery("");
      setLanguageFilter(officialVoiceLanguageFilterForTarget(props.target.targetLanguage));
    }, [scopeIdentity]);

    React.useEffect(() => () => {
      useAbortRef.current?.abort();
      previewAbortRef.current?.abort();
      useRequestSequenceRef.current += 1;
      previewSequenceRef.current += 1;
    }, []);

    const applyVoice = (item: OfficialVoiceCatalogItem) => {
      const current = useStateRef.current;
      const currentlyBoundPresetId = current.phase === "applied"
        ? current.presetId
        : props.activePresetId ?? null;
      const alreadyApplied = currentlyBoundPresetId === item.presetId;
      if (
        props.disabled === true
        || !targetReady
        || !item.selectableNow
        || !officialVoiceIsAvailableForProvider(item, providerSelection)
        || alreadyApplied
        || !canStartOfficialVoiceUse(current)
      ) return;
      let idempotencyKey: string;
      let controller: AbortController;
      let requestId: number;
      try {
        idempotencyKey = nextOfficialVoiceUseIdempotencyKey(
          current,
          item.presetId,
          props.createIdempotencyKey,
        );
        requestId = Math.max(
          useRequestSequenceRef.current + 1,
          current.requestId + 1,
        );
        useRequestSequenceRef.current = requestId;
        controller = new AbortController();
      } catch (reason: unknown) {
        const failure = classifyOfficialVoiceUseFailure(reason);
        requestId = Math.max(
          useRequestSequenceRef.current + 1,
          current.requestId + 1,
        );
        useRequestSequenceRef.current = requestId;
        commitUse(Object.freeze({
          phase: failure.kind,
          presetId: item.presetId,
          requestId,
          idempotencyKey: "official-voice-selection-init-failed",
          message: failure.message,
          failure,
        }));
        return;
      }
      useAbortRef.current?.abort();
      useAbortRef.current = controller;
      previewAbortRef.current?.abort();
      previewSequenceRef.current += 1;
      commitPreview(IDLE_PREVIEW_STATE);
      const request = createOfficialVoiceSelectionRequest(item.presetId, props.target);
      const started = transition({
        type: "start",
        presetId: item.presetId,
        requestId,
        idempotencyKey,
        message: `正在${targetActionLabel(props.target)}：${item.displayName}…`,
      });
      if (started.phase !== "applying" || started.requestId !== requestId) {
        const failure = classifyOfficialVoiceUseFailure(
          new OfficialVoiceUseResponseError("official voice selection did not start"),
        );
        commitUse(Object.freeze({
          phase: failure.kind,
          presetId: item.presetId,
          requestId,
          idempotencyKey,
          message: failure.message,
          failure,
        }));
        return;
      }
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
          assertOfficialVoiceSelectionResult(result, item.presetId, props.target);
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
        .then((cacheStatus) => {
          if (controller.signal.aborted || sequence !== previewSequenceRef.current) return;
          commitPreview(Object.freeze({
            phase: "ready",
            presetId: item.presetId,
            message: cacheStatus === "hit"
              ? `${item.displayName} 已直接播放缓存试听。`
              : cacheStatus === "miss"
                ? `${item.displayName} 试听已生成并播放，后续将直接复用。`
                : `${item.displayName} 本地试听已开始。`,
          }));
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted || sequence !== previewSequenceRef.current || isAbortLike(reason)) return;
          commitPreview(Object.freeze({
            phase: "error",
            presetId: item.presetId,
            message: `${item.displayName} 本地试听失败；未更改当前绑定。`,
          }));
        });
    };

    const liveMessage = useState.phase === "applying"
      || useState.phase === "error"
      || useState.phase === "conflict"
      ? useState.message
      : useState.phase === "applied"
        ? useState.message
        : "";
    const currentPresetId = useState.phase === "applied"
      ? useState.presetId
      : props.activePresetId ?? null;
    const useTemporarilyBlocked = useState.phase === "applying"
      || useState.phase === "conflict";

    const renderItem = (itemModel: OfficialVoiceLibraryItemModel): unknown => {
      const item = itemModel.item;
      const isCurrent = currentPresetId === item.presetId;
      const nonRetryableSameItem = useState.phase === "error"
        && useState.presetId === item.presetId
        && !useState.failure.retryable;
      const previewing = previewState.phase === "loading"
        && previewState.presetId === item.presetId;
      const previewPhase = previewState.presetId === item.presetId
        ? previewState.phase
        : "idle";
      const warningId = `${prefix}-${safeDomToken(item.presetId)}-language-note`;
      const unavailableId = `${prefix}-${safeDomToken(item.presetId)}-availability`;
      const headingId = `${prefix}-${safeDomToken(item.presetId)}-heading`;
      const selectionDisabled = props.disabled === true
        || !targetReady
        || !item.selectableNow
        || !itemModel.providerAvailable
        || nonRetryableSameItem;
      const selectionAriaDisabled = selectionDisabled || useTemporarilyBlocked;
      const previewDisabled = props.disabled === true
        || !item.previewableNow
        || props.onPreview === undefined;
      const describedBy = [
        itemModel.languageNotice === null ? null : warningId,
        item.selectableNow && itemModel.providerAvailable ? null : unavailableId,
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
            "data-provider-available": String(itemModel.providerAvailable),
            "data-preview-phase": previewPhase,
            "aria-busy": previewing ? true : undefined,
            "aria-labelledby": headingId,
          },
          h(
            "label",
            {
              className: [
                "anw-official-voice-card__selection",
                selectionAriaDisabled ? "is-disabled" : "",
              ].filter(Boolean).join(" "),
            },
            h("input", {
              className: "anw-official-voice-card__radio",
              type: "radio",
              name: `${prefix}-selection`,
              value: item.presetId,
              checked: isCurrent,
              disabled: selectionDisabled,
              "aria-disabled": selectionAriaDisabled ? true : undefined,
              "aria-describedby": describedBy,
              "aria-label": `${isCurrent ? "当前使用" : "选择使用"}：${targetContextLabel(props.target)} · ${item.displayName}`,
              onChange: () => applyVoice(item),
            }),
            h("span", { className: "anw-official-voice-card__heading" },
              h("span", null,
                h("strong", { id: headingId }, item.displayName),
                h(
                  "span",
                  { className: "anw-official-voice-library__filter-status" },
                  itemModel.languageLabel,
                ),
              ),
              h(
                "span",
                {
                  id: unavailableId,
                  className: itemModel.providerAvailable
                    ? "anw-official-voice-library__filter-status"
                    : "anw-official-voice-card__provider is-local-only",
                },
                itemModel.providerAvailabilityLabel,
              ),
              isCurrent
                ? h("span", { className: "anw-official-voice-card__current" }, "当前使用")
                : null,
            ),
          ),
          h(
            "button",
            {
              type: "button",
              className: "anw-official-voice-card__preview",
              disabled: previewDisabled,
              "aria-disabled": previewDisabled ? true : undefined,
              "aria-label": `${item.previewableNow ? "本地试听" : "本地试听暂不可用"}${item.displayName}`,
              onClick: () => previewVoice(item),
            },
            previewing
              ? "准备试听…"
              : item.previewableNow && props.onPreview !== undefined
                ? previewPhase === "ready" ? "再次试听" : "试听"
                : "本地试听暂不可用",
          ),
          h(
            "details",
            { className: "anw-official-voice-card__details" },
            h("summary", null, "详情"),
            h("dl", null,
              h(
                "div",
                null,
                h("dt", null, "使用状态"),
                h("dd", null, itemModel.availabilityLabel),
              ),
              h(
                "div",
                null,
                h("dt", null, "技术验证"),
                h("dd", null, itemModel.validationLabel),
              ),
              itemModel.languageNotice === null
                ? null
                : h(
                  "div",
                  { className: "anw-official-voice-card__language-note" },
                  h("dt", null, "语言提示"),
                  h("dd", { id: warningId }, itemModel.languageNotice),
                ),
              h("div", null, h("dt", null, "Preset ID"), h("dd", null, item.presetId)),
              h("div", null, h("dt", null, "官方 speaker"), h("dd", null, item.officialSpeaker)),
              h("div", null, h("dt", null, "朗读语言"), h("dd", null, "普通话（固定）")),
              h("div", null, h("dt", null, "本地模型"), h("dd", null, item.provenance.localModelId)),
              h("div", null, h("dt", null, "模型 revision"), h("dd", null, item.provenance.localModelRevision)),
              h("div", null, h("dt", null, "映射目录"), h("dd", null, item.provenance.catalogId)),
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
          previewPhase === "idle"
            ? null
            : h(
              "span",
              {
                className: [
                  "anw-official-voice-card__preview-status",
                  previewPhase === "error" ? "is-error" : "",
                ].filter(Boolean).join(" "),
                role: "status",
                "aria-live": "polite",
              },
              previewState.message,
            ),
        ),
      );
    };

    const content = props.loading === true
      ? h("p", { className: "anw-official-voice-library__empty", role: "status" }, "正在加载官方音色…")
      : props.loadError
        ? h("p", { className: "anw-official-voice-library__empty is-error", role: "status" }, props.loadError)
        : model.status !== "ready"
          ? h("p", { className: "anw-official-voice-library__empty", role: "status" }, model.message)
          : filteredCount === 0
            ? h(
              "p",
              { className: "anw-official-voice-library__empty", role: "status" },
              "没有匹配的官方音色；可清空搜索或切换语言。",
            )
            : filteredGroups.map((group) => {
            return h(
              "ul",
              {
                key: group.languageScope,
                id: `${prefix}-${safeDomToken(group.languageScope)}-panel`,
                className: "anw-official-voice-library__grid",
                "aria-label": group.label,
              },
              ...group.items.map(renderItem),
            );
          });

    return h(
      "section",
      {
        className: ["anw-official-voice-library", props.className ?? ""].filter(Boolean).join(" "),
        role: "region",
        "aria-labelledby": props.presentation === "embedded" ? undefined : `${prefix}-heading`,
        "aria-label": props.presentation === "embedded" ? "官方音色" : undefined,
        "aria-describedby": props.presentation === "embedded"
          ? `${prefix}-live-status`
          : `${prefix}-summary ${prefix}-live-status`,
        "aria-busy": props.loading === true || useState.phase === "applying",
        "data-catalog-status": props.loading === true
          ? "loading"
          : props.loadError
            ? "error"
            : model.status,
        "data-official-voice-count": model.itemCount,
        "data-official-voice-use-phase": useState.phase,
      },
      props.presentation === "embedded"
        ? props.headerAction ?? null
        : h("header", { className: "anw-official-voice-library__header" },
          h("div", null,
            h("h2", { id: `${prefix}-heading` }, "选择旁白音色"),
            h(
              "p",
              { id: `${prefix}-summary` },
              "选中即保存，试听不更换声音。已有音频保持不变。",
            ),
          ),
          h("div", { className: "anw-official-voice-library__header-actions" },
            props.headerAction ?? null,
            h("span", { className: "anw-official-voice-library__count" }, `${model.itemCount} 项`),
          ),
        ),
      targetReady
        ? null
        : h(
          "p",
          { className: "anw-official-voice-library__scope-error", role: "status" },
          "当前作品或人物设置尚未就绪，暂不能更改音色。",
        ),
      model.status === "ready"
        ? h(
          "div",
          { className: "anw-official-voice-library__filters", role: "search" },
          h(
            "label",
            null,
            h("span", null, "搜索音色"),
            h("input", {
              type: "search",
              value: searchQuery,
              placeholder: "名称或音色特点",
              onChange: (event: { target: { value: string } }) => {
                setSearchQuery(event.target.value);
              },
            }),
          ),
          h("span", {
            className: "anw-official-voice-library__language-fixed",
            role: "note",
          }, "普通话 · 本地试听，首次生成后复用"),
          searchQuery.trim() === ""
            ? null
            : h(
              "span",
              { className: "anw-official-voice-library__filter-count", "aria-hidden": true },
              `当前显示 ${filteredCount} 项`,
            ),
          h(
            "span",
            {
              className: "anw-official-voice-library__filter-status",
              role: "status",
              "aria-live": "polite",
              "aria-atomic": true,
            },
            `当前显示 ${filteredCount} 项`,
          ),
        )
        : null,
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
      (useState.phase === "conflict" || props.loadError) && props.onConflictRefresh !== undefined
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
