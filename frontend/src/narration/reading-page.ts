import type { QwenPawReactRuntime } from "../assistant-pane";
import {
  getNarrationOverview,
  listVoiceProfiles,
  listNarrationScopeOverrides,
  putNarrationPlaybackPreferences,
  putNarrationScopeOverride,
  putNarrationSettings,
  NarrationApiError,
} from "./api";
import type {
  FeatureCapability,
  NarrationOverviewResponse,
  NarrationScopeKind,
  NarrationScopeOverrideListResponse,
  NarrationScopeOverrideResource,
  NarrationScopeOverrideValues,
  NarrationSettingsResource,
  NarrationSettingsValues,
  NarrationCapabilities,
  NarratorVoiceSelection,
  PutNarrationScopeOverrideRequest,
  UpdateNarrationSettingsRequest,
  UpdateNarrationPlaybackPreferencesRequest,
  VoiceProfileListResponse,
  VoiceProfileResource,
  VoiceSourceType,
} from "./contracts";
import {
  createReadingPreferencesPanel,
} from "./reading-preferences-panel";
import {
  createScopeOverridesPanel as createCompactScopeOverridesPanel,
} from "./scope-overrides-panel";
import {
  voiceActivationEvidenceIsUsable,
  voiceSourceEvidenceIsUsable,
} from "./contracts";
import {
  canonicalReadingSection,
  capabilityFor,
  capabilityStatusText,
  createReadingOverview,
  isReadingSectionKey,
  READING_SECTIONS,
  type ReadingOverviewReactRuntime,
  type ReadingSectionKey,
} from "./reading-overview";


export const READING_WORKBENCH_SECTION = "reading" as const;
export const READING_PANEL_QUERY_KEY = "reading_panel" as const;


export type ReadingPageReactRuntime = Pick<
  QwenPawReactRuntime,
  "createElement" | "useState" | "useEffect" | "useRef"
>;


export interface ReadingPageApi {
  getOverview(novelId: string, signal?: AbortSignal): Promise<NarrationOverviewResponse>;
  listScopeOverrides(
    novelId: string,
    signal?: AbortSignal,
  ): Promise<NarrationScopeOverrideListResponse>;
  listVoiceProfiles?(
    novelId: string,
    signal?: AbortSignal,
  ): Promise<VoiceProfileListResponse>;
  putSettings(
    novelId: string,
    request: UpdateNarrationSettingsRequest,
    signal?: AbortSignal,
  ): Promise<NarrationSettingsResource>;
  putPlaybackPreferences?(
    novelId: string,
    request: UpdateNarrationPlaybackPreferencesRequest,
    signal?: AbortSignal,
  ): Promise<NarrationSettingsResource>;
  putScopeOverride(
    novelId: string,
    scopeKind: NarrationScopeKind,
    scopeId: string,
    request: PutNarrationScopeOverrideRequest,
    signal?: AbortSignal,
  ): Promise<NarrationScopeOverrideResource>;
}


export interface ReadingScopeTarget {
  readonly novelId: string;
  readonly scopeKind: NarrationScopeKind;
  readonly scopeId: string;
  readonly label: string;
}


export interface ReadingNarratorOption {
  readonly novelId: string | null;
  readonly profileId: string;
  readonly versionId: string;
  readonly label: string;
  readonly locked: true;
  readonly rightsActive: true;
}


export interface ReadingCharacterOption {
  readonly novelId: string;
  readonly characterId: string;
  readonly label: string;
}


type ExternalReadingSection = Exclude<ReadingSectionKey, "overview" | "narrator">;


export interface ReadingSectionRenderContext {
  readonly overview: NarrationOverviewResponse;
  readonly onRefresh: () => void;
  readonly onNavigate: (section: ReadingSectionKey) => void;
}


export interface ReadingPageProps {
  readonly novelId: string;
  readonly novelTitle?: string;
  readonly initialSection?: ReadingSectionKey;
  readonly scopeTargets?: readonly ReadingScopeTarget[];
  readonly narratorOptions?: readonly ReadingNarratorOption[];
  readonly characterOptions?: readonly ReadingCharacterOption[];
  readonly sectionContent?: Readonly<Partial<Record<ExternalReadingSection, unknown>>>;
  readonly renderSectionContent?: (
    section: ExternalReadingSection,
    context: ReadingSectionRenderContext,
  ) => unknown;
  readonly renderNarratorVoiceWorkspace?: (
    context: ReadingSectionRenderContext,
  ) => unknown;
  readonly onSectionChange?: (section: ReadingSectionKey) => void;
}


type ReadingPageLoadState =
  | { readonly phase: "loading" }
  | { readonly phase: "error"; readonly message: string }
  | {
      readonly phase: "ready";
      readonly overview: NarrationOverviewResponse;
      readonly overrides: readonly NarrationScopeOverrideResource[];
      readonly voiceProfiles: readonly VoiceProfileResource[];
      readonly voiceProfilesError: string | null;
    };


interface OperationState {
  readonly saving: boolean;
  readonly message: string | null;
  readonly kind: "success" | "error" | null;
}


const EMPTY_OPERATION: OperationState = {
  saving: false,
  message: null,
  kind: null,
};


const DEFAULT_API: ReadingPageApi = {
  getOverview: getNarrationOverview,
  listScopeOverrides: listNarrationScopeOverrides,
  listVoiceProfiles: (novelId, signal) => listVoiceProfiles({
    novelId,
    includeLibrary: true,
    signal,
  }),
  putSettings: putNarrationSettings,
  putPlaybackPreferences: putNarrationPlaybackPreferences,
  putScopeOverride: putNarrationScopeOverride,
};


function scopeTargetKey(target: Pick<ReadingScopeTarget, "scopeKind" | "scopeId">): string {
  return `${target.scopeKind}:${target.scopeId}`;
}


function narratorSelectionKey(selection: NarratorVoiceSelection): string {
  return `${selection.profile_id}:${selection.version_id}`;
}


export function readingSectionFromSearch(search: string): ReadingSectionKey {
  const value = new URLSearchParams(search).get(READING_PANEL_QUERY_KEY);
  return canonicalReadingSection(isReadingSectionKey(value) ? value : "overview");
}


export function readingSectionSearch(
  search: string,
  section: ReadingSectionKey,
): string {
  const query = new URLSearchParams(search);
  query.set("section", READING_WORKBENCH_SECTION);
  if (section === "overview") query.delete(READING_PANEL_QUERY_KEY);
  else query.set(READING_PANEL_QUERY_KEY, section);
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}


export function scopeTargetsForNovel(
  novelId: string,
  targets: readonly ReadingScopeTarget[],
): readonly ReadingScopeTarget[] {
  const seen = new Set<string>();
  return targets.filter((target) => {
    const key = scopeTargetKey(target);
    if (target.novelId !== novelId || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


export function narratorOptionsForNovel(
  novelId: string,
  options: readonly ReadingNarratorOption[],
): readonly ReadingNarratorOption[] {
  const seen = new Set<string>();
  return options.filter((option) => {
    const key = narratorSelectionKey({
      profile_id: option.profileId,
      version_id: option.versionId,
    });
    if (
      option.locked !== true
      || option.rightsActive !== true
      || (option.novelId !== null && option.novelId !== novelId)
      || seen.has(key)
    ) return false;
    seen.add(key);
    return true;
  });
}


const NARRATOR_SOURCE_CAPABILITIES: Readonly<Record<VoiceSourceType, FeatureCapability["key"]>> = {
  preset: "preset_voice_source",
  uploaded: "reference_clone",
  generated: "voice_generator",
};


function narrationCapabilityActionable(
  capabilities: NarrationCapabilities,
  key: FeatureCapability["key"],
): boolean {
  const capability = capabilities.items.find((item) => item.key === key);
  if (!capability) throw new Error(`缺少朗读能力状态：${key}`);
  return capability.state === "enabled"
    && capability.visible
    && capability.actionable;
}


/**
 * Map only the current, production-eligible version of a scoped voice profile.
 * The server remains authoritative; this projection prevents stale or held
 * profiles from becoming selectable while the user is editing settings.
 */
export function narratorOptionsFromVoiceProfiles(
  novelId: string,
  profiles: readonly VoiceProfileResource[],
  capabilities: NarrationCapabilities,
): readonly ReadingNarratorOption[] {
  if (!narrationCapabilityActionable(capabilities, "narration_product")
    || !narrationCapabilityActionable(capabilities, "reading_settings")) return [];
  const options: ReadingNarratorOption[] = [];
  for (const profile of profiles) {
    if (profile.novel_id !== null && profile.novel_id !== novelId) continue;
    if (profile.status !== "active" || profile.current_version_id === null) continue;
    const version = profile.versions.find((item) => (
      item.version_id === profile.current_version_id
    ));
    if (!version
      || version.state !== "locked"
      || !voiceActivationEvidenceIsUsable(version)
      || version.rights.state !== "active"
      || !voiceSourceEvidenceIsUsable(version)) continue;
    if (!narrationCapabilityActionable(
      capabilities,
      NARRATOR_SOURCE_CAPABILITIES[version.source_type],
    )) continue;
    options.push({
      novelId: profile.novel_id,
      profileId: profile.profile_id,
      versionId: version.version_id,
      label: `${profile.name} · v${version.version_number}`,
      locked: true,
      rightsActive: true,
    });
  }
  return [...narratorOptionsForNovel(novelId, options)].sort((left, right) => (
    left.label.localeCompare(right.label, "zh-CN")
      || left.profileId.localeCompare(right.profileId)
      || left.versionId.localeCompare(right.versionId)
  ));
}


export function characterOptionsForNovel(
  novelId: string,
  options: readonly ReadingCharacterOption[],
): readonly ReadingCharacterOption[] {
  const seen = new Set<string>();
  return options.filter((option) => {
    if (option.novelId !== novelId || seen.has(option.characterId)) return false;
    seen.add(option.characterId);
    return true;
  });
}


export function buildNarrationSettingsReplacement(
  resource: NarrationSettingsResource,
  values: NarrationSettingsValues,
): UpdateNarrationSettingsRequest {
  return {
    expected_version: resource.version,
    values,
  };
}


export function emptyScopeOverrideValues(): NarrationScopeOverrideValues {
  return {
    narrator: null,
    language: null,
    text_rules: null,
    timing: null,
  };
}


export function scopeOverrideForTarget(
  target: ReadingScopeTarget,
  overrides: readonly NarrationScopeOverrideResource[],
): NarrationScopeOverrideResource | undefined {
  return overrides.find((override) => (
    override.novel_id === target.novelId
    && override.scope_kind === target.scopeKind
    && override.scope_id === target.scopeId
  ));
}


export function buildScopeOverrideReplacement(
  novelId: string,
  target: ReadingScopeTarget,
  current: NarrationScopeOverrideResource | undefined,
  enabled: boolean,
  overrides: NarrationScopeOverrideValues,
): PutNarrationScopeOverrideRequest {
  if (target.novelId !== novelId) {
    throw new Error("范围覆盖目标不属于当前作品");
  }
  if (current && (
    current.novel_id !== novelId
    || current.scope_kind !== target.scopeKind
    || current.scope_id !== target.scopeId
  )) {
    throw new Error("范围覆盖版本与目标不匹配");
  }
  return {
    expected_version: current?.version ?? 0,
    enabled,
    overrides: enabled ? overrides : emptyScopeOverrideValues(),
  };
}


export function replaceScopeOverride(
  novelId: string,
  target: ReadingScopeTarget,
  current: readonly NarrationScopeOverrideResource[],
  saved: NarrationScopeOverrideResource,
): readonly NarrationScopeOverrideResource[] {
  if (
    target.novelId !== novelId
    || saved.novel_id !== novelId
    || saved.scope_kind !== target.scopeKind
    || saved.scope_id !== target.scopeId
  ) {
    throw new Error("服务端返回了其他作品或范围的覆盖配置");
  }
  const key = scopeTargetKey(target);
  return [
    ...current.filter((item) => `${item.scope_kind}:${item.scope_id}` !== key),
    saved,
  ];
}


function mutationBlockReason(
  capability: FeatureCapability,
  canConfigure: boolean,
): string | null {
  if (!capability.actionable) return capabilityStatusText(capability);
  if (!canConfigure) return "当前作品授权不允许修改朗读配置（AUTHORIZATION_READ_ONLY）";
  return null;
}


function apiErrorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof NarrationApiError) {
    if (reason.detail.code === "VERSION_CONFLICT") {
      return "配置已在其他位置更新，请刷新后再保存（VERSION_CONFLICT）";
    }
    return `${reason.detail.message}（${reason.detail.code}）`;
  }
  return fallback;
}


export function createReadingPage(
  React: ReadingPageReactRuntime,
  api: ReadingPageApi = DEFAULT_API,
): (props: ReadingPageProps) => unknown {
  const h = React.createElement;
  const ReadingOverview = createReadingOverview(React as ReadingOverviewReactRuntime);
  const ReadingPreferencesPanel = createReadingPreferencesPanel(React);
  const ScopeOverridesPanel = createCompactScopeOverridesPanel(React);

  return function ReadingPage(props) {
    const [activeSection, setActiveSection] = React.useState<ReadingSectionKey>(
      canonicalReadingSection(props.initialSection),
    );
    const [reloadVersion, setReloadVersion] = React.useState(0);
    const [loadState, setLoadState] = React.useState<ReadingPageLoadState>({ phase: "loading" });
    const [operation, setOperation] = React.useState<OperationState>(EMPTY_OPERATION);
    const currentNovelRef = React.useRef(props.novelId);
    const mutationAbortRef = React.useRef<AbortController | null>(null);
    currentNovelRef.current = props.novelId;

    React.useEffect(() => {
      setActiveSection(canonicalReadingSection(props.initialSection));
    }, [props.novelId, props.initialSection]);

    React.useEffect(() => {
      const controller = new AbortController();
      setLoadState({ phase: "loading" });
      setOperation(EMPTY_OPERATION);
      const profilesRequest = api.listVoiceProfiles
        ? api.listVoiceProfiles(props.novelId, controller.signal)
          .then((response) => ({ response, error: null as string | null }))
          .catch((reason: unknown) => ({
            response: null,
            error: apiErrorMessage(reason, "无法核验旁白音色，已保持音色选项为空。"),
          }))
        : Promise.resolve({ response: null, error: null as string | null });
      void Promise.all([
        api.getOverview(props.novelId, controller.signal),
        api.listScopeOverrides(props.novelId, controller.signal),
        profilesRequest,
      ]).then(([overview, overrides, profilesResult]) => {
        if (controller.signal.aborted) return;
        if (overview.novel_id !== props.novelId || overrides.novel_id !== props.novelId) {
          setLoadState({ phase: "error", message: "服务端返回了其他作品的朗读配置，已阻止显示。" });
          return;
        }
        const voiceProfiles = profilesResult.response?.items ?? [];
        if (voiceProfiles.some((profile) => (
          profile.novel_id !== null && profile.novel_id !== props.novelId
        ))) {
          setLoadState({ phase: "error", message: "服务端返回了其他作品的旁白音色，已阻止显示。" });
          return;
        }
        setLoadState({
          phase: "ready",
          overview,
          overrides: overrides.items,
          voiceProfiles,
          voiceProfilesError: profilesResult.error,
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setLoadState({
          phase: "error",
          message: apiErrorMessage(reason, "无法加载朗读设置，请稍后重试。"),
        });
      });
      return () => controller.abort();
    }, [props.novelId, reloadVersion]);

    React.useEffect(() => () => {
      mutationAbortRef.current?.abort();
      mutationAbortRef.current = null;
    }, [props.novelId]);

    const reload = () => setReloadVersion((version) => version + 1);
    const navigate = (section: ReadingSectionKey) => {
      setActiveSection(section);
      props.onSectionChange?.(section);
    };

    if (loadState.phase === "loading") {
      return h(
        "main",
        {
          className: "anw-reading-page is-loading",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h(ReadingOverview, { state: { phase: "loading" } }),
      );
    }

    if (loadState.phase === "error") {
      return h(
        "main",
        {
          className: "anw-reading-page is-error",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h(ReadingOverview, {
          state: { phase: "error", message: loadState.message, onRetry: reload },
        }),
      );
    }

    if (loadState.overview.novel_id !== props.novelId) {
      return h(
        "main",
        {
          className: "anw-reading-page is-loading",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h(ReadingOverview, { state: { phase: "loading" } }),
      );
    }

    const overview = loadState.overview;
    const productCapability = capabilityFor(overview, "narration_product");
    if (!overview.authorization.can_read || !productCapability.visible) {
      return h(
        "main",
        {
          className: "anw-reading-page is-unavailable",
          role: "alert",
          "data-narration-reading-page": "v1",
          "data-novel-id": props.novelId,
        },
        h("h1", null, "朗读设置不可见"),
        h("p", null, !overview.authorization.can_read
          ? "当前作品授权不允许读取朗读配置。"
          : capabilityStatusText(productCapability)),
      );
    }

    const settingsCapability = capabilityFor(overview, "reading_settings");
    const configurationCapability = productCapability.actionable
      ? settingsCapability
      : productCapability;
    const chapterPlaybackReady = [
      "narration_synthesis",
      "product_player",
      "editor_production",
    ].every((key) => narrationCapabilityActionable(
      overview.capabilities,
      key as FeatureCapability["key"],
    ));
    const narratorOptions = narratorOptionsForNovel(props.novelId, [
      ...(props.narratorOptions ?? []),
      ...narratorOptionsFromVoiceProfiles(
        props.novelId,
        loadState.voiceProfiles,
        overview.capabilities,
      ),
    ]);
    const applySavedSettings = (saved: NarrationSettingsResource) => {
      if (saved.novel_id !== props.novelId) return;
      setLoadState((current) => current.phase === "ready"
        && current.overview.novel_id === props.novelId
        ? { ...current, overview: { ...current.overview, settings: saved } }
        : current);
    };
    const applySavedOverride = (saved: NarrationScopeOverrideResource) => {
      if (saved.novel_id !== props.novelId) return;
      setLoadState((current) => current.phase === "ready"
        && current.overview.novel_id === props.novelId
        ? {
          ...current,
          overrides: replaceScopeOverride(
            props.novelId,
            {
              novelId: saved.novel_id,
              scopeKind: saved.scope_kind,
              scopeId: saved.scope_id,
              label: saved.scope_id,
            },
            current.overrides,
            saved,
          ),
        }
        : current);
    };
    const saveSettings = (values: NarrationSettingsValues) => {
      if (mutationBlockReason(configurationCapability, overview.authorization.can_configure)) return;
      mutationAbortRef.current?.abort();
      const controller = new AbortController();
      mutationAbortRef.current = controller;
      setOperation({ saving: true, message: null, kind: null });
      void api.putSettings(
        props.novelId,
        buildNarrationSettingsReplacement(overview.settings, values),
        controller.signal,
      ).then((saved) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        if (saved.novel_id !== props.novelId) {
          throw new Error("settings scope mismatch");
        }
        setLoadState((current) => current.phase === "ready"
          && current.overview.novel_id === props.novelId
          ? { ...current, overview: { ...current.overview, settings: saved } }
          : current);
        setOperation({ saving: false, message: "作品旁白设置已保存。", kind: "success" });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        setOperation({
          saving: false,
          message: apiErrorMessage(reason, "保存作品旁白失败，请刷新后重试。"),
          kind: "error",
        });
      });
    };
    const saveScopeOverride = (
      target: ReadingScopeTarget,
      request: PutNarrationScopeOverrideRequest,
    ) => {
      if (mutationBlockReason(configurationCapability, overview.authorization.can_configure)) return;
      mutationAbortRef.current?.abort();
      const controller = new AbortController();
      mutationAbortRef.current = controller;
      setOperation({ saving: true, message: null, kind: null });
      void api.putScopeOverride(
        props.novelId,
        target.scopeKind,
        target.scopeId,
        request,
        controller.signal,
      ).then((saved) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        const nextOverrides = replaceScopeOverride(
          props.novelId,
          target,
          loadState.overrides,
          saved,
        );
        setLoadState((current) => current.phase === "ready"
          && current.overview.novel_id === props.novelId
          ? {
            ...current,
            overrides: nextOverrides,
          }
          : current);
        setOperation({ saving: false, message: "范围覆盖已保存。", kind: "success" });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (currentNovelRef.current !== props.novelId) return;
        setOperation({
          saving: false,
          message: apiErrorMessage(reason, "保存范围覆盖失败，请刷新后重试。"),
          kind: "error",
        });
      });
    };

    const externalContent = activeSection !== "overview" && activeSection !== "narrator"
      ? props.renderSectionContent?.(
        activeSection,
        { overview, onRefresh: reload, onNavigate: navigate },
      ) ?? props.sectionContent?.[activeSection]
      : undefined;
    const sectionBody = activeSection === "overview"
      ? h(ReadingOverview, {
        state: {
          phase: "ready",
          overview,
          onRetry: reload,
          onNavigate: navigate,
        },
      })
      : activeSection === "narrator"
        ? h(
          "div",
          { className: "anw-reading-narrator-stack" },
          loadState.voiceProfilesError
            ? h(
                "p",
                { className: "anw-reading-inline-error", role: "alert" },
                loadState.voiceProfilesError,
              )
            : null,
          h(ReadingPreferencesPanel, {
            novelId: props.novelId,
            settings: overview.settings,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            characterOptions: props.characterOptions ?? [],
            saveSettings: api.putSettings,
            savePlaybackPreferences: api.putPlaybackPreferences
              ?? putNarrationPlaybackPreferences,
            onSettingsSaved: applySavedSettings,
            onPlaybackPreferencesSaved: applySavedSettings,
            onRefresh: reload,
          }),
          props.renderNarratorVoiceWorkspace?.({
            overview,
            onRefresh: reload,
            onNavigate: navigate,
          }) ?? null,
          h(ScopeOverridesPanel, {
            novelId: props.novelId,
            settings: overview.settings,
            capabilities: overview.capabilities,
            authorization: overview.authorization,
            targets: props.scopeTargets ?? [],
            overrides: loadState.overrides,
            narratorOptions: narratorOptions.map((option) => ({
              novelId: option.novelId,
              profileId: option.profileId,
              versionId: option.versionId,
              label: option.label,
              usable: option.locked && option.rightsActive,
            })),
            characterOptions: props.characterOptions ?? [],
            saveOverride: api.putScopeOverride,
            onSaved: applySavedOverride,
            onRefresh: reload,
          }),
        )
        : externalContent ?? h(
          "section",
          {
            className: "anw-reading-integration-slot",
            role: "status",
            "data-reading-integration-slot": activeSection,
          },
          h("h2", null, READING_SECTIONS.find((item) => item.key === activeSection)?.label ?? "朗读设置"),
          h("p", null, "该局部模块将在 T2-GATE 汇合后接入；这里不会提供不可用的演示按钮。"),
        );

    return h(
      "main",
      {
        className: "anw-reading-page",
        "data-narration-reading-page": "v1",
        "data-novel-id": props.novelId,
        "data-active-section": activeSection,
      },
      h(
        "header",
        { className: "anw-reading-page-header" },
        h("div", null,
          h("p", { className: "anw-reading-eyebrow" }, props.novelTitle ?? "当前作品"),
          h("h1", null, "朗读"),
          h("p", null, chapterPlaybackReady
            ? "管理作品旁白、人物声音和朗读规则；章节播放与校听已在章节写作页开放。"
            : "管理作品旁白、人物声音和朗读规则；章节播放与校听将在对应产品能力通过门禁后开放。"),
        ),
        h(
          "span",
          {
            className: `anw-reading-product-state is-${productCapability.state}`,
            "data-reason-code": productCapability.reason_code ?? undefined,
          },
          productCapability.actionable ? "朗读设置可用" : capabilityStatusText(productCapability),
        ),
      ),
      h(
        "div",
        { className: "anw-reading-layout" },
        h(
          "nav",
          { className: "anw-reading-nav", "aria-label": "朗读设置" },
          ...READING_SECTIONS.map((section) => h(
            "button",
            {
              key: section.key,
              type: "button",
              className: activeSection === section.key ? "is-active" : "",
              "aria-current": activeSection === section.key ? "page" : undefined,
              "data-reading-section": section.key,
              onClick: () => navigate(section.key),
            },
            section.label,
          )),
        ),
        h(
          "div",
          { className: "anw-reading-content" },
          operation.message
            ? h(
              "div",
              {
                className: `anw-reading-operation is-${operation.kind ?? "idle"}`,
                role: operation.kind === "error" ? "alert" : "status",
                "aria-live": "polite",
              },
              h("span", null, operation.message),
              operation.kind === "error"
                ? h("button", { type: "button", onClick: reload }, "刷新最新配置")
                : null,
            )
            : null,
          sectionBody,
        ),
      ),
    );
  };
}
