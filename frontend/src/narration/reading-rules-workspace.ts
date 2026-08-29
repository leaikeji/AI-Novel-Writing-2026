import type {
  NarrationAuthorizationState,
  NarrationCapabilities,
  NarrationCloudConsent,
  NarrationSettingsResource,
  PronunciationProfileResource,
} from "./contracts";
import {
  createPronunciationPanel,
  type PronunciationHitPreview,
  type PronunciationPanelApi,
  type PronunciationPanelReactRuntime,
  type PronunciationScopeOption,
} from "./pronunciation-panel";
import {
  createReadingRulesPanel,
  type ReadingRulesPanelApi,
  type ReadingRulesReactRuntime,
} from "./reading-rules-panel";


export type ReadingRulesWorkspaceSection = "recognition" | "pronunciation";


export type ReadingRulesWorkspaceReactRuntime = ReadingRulesReactRuntime
  & PronunciationPanelReactRuntime;


export interface ReadingRulesWorkspaceDependencies {
  readonly readingRulesApi?: ReadingRulesPanelApi;
  readonly pronunciationApi?: PronunciationPanelApi;
}


export interface ReadingRulesWorkspaceProps {
  readonly novelId: string;
  readonly settings: NarrationSettingsResource;
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly pronunciationScopeOptions: readonly PronunciationScopeOption[];
  readonly initialSection?: ReadingRulesWorkspaceSection;
  readonly initialPreviewText?: string;
  readonly onSettingsSaved?: (settings: NarrationSettingsResource) => void;
  readonly onConsentChanged?: (consent: NarrationCloudConsent) => void;
  readonly onPronunciationSaved?: (profile: PronunciationProfileResource) => void;
  readonly onPreviewHits?: (preview: PronunciationHitPreview) => void;
  readonly onOpenReadingPreferences?: () => void;
  readonly onRefresh?: () => void;
  readonly onSectionChange?: (section: ReadingRulesWorkspaceSection) => void;
  readonly createIdempotencyKey?: () => string;
  readonly onReturnFocus?: () => void;
  readonly className?: string;
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
}


export function normalizeReadingRulesWorkspaceSection(
  value: string | null | undefined,
): ReadingRulesWorkspaceSection {
  return value === "pronunciation" ? "pronunciation" : "recognition";
}


export function createReadingRulesWorkspace(
  React: ReadingRulesWorkspaceReactRuntime,
  dependencies: ReadingRulesWorkspaceDependencies = {},
): (props: ReadingRulesWorkspaceProps) => unknown {
  const h = React.createElement;
  const ReadingRulesPanel = dependencies.readingRulesApi
    ? createReadingRulesPanel(React, dependencies.readingRulesApi)
    : createReadingRulesPanel(React);
  const PronunciationPanel = dependencies.pronunciationApi
    ? createPronunciationPanel(React, dependencies.pronunciationApi)
    : createPronunciationPanel(React);

  return function ReadingRulesWorkspace(props: ReadingRulesWorkspaceProps): unknown {
    const [activeSection, setActiveSection] = React.useState<ReadingRulesWorkspaceSection>(
      normalizeReadingRulesWorkspaceSection(props.initialSection),
    );
    const recognitionRef = React.useRef<FocusableElement | null>(null);
    const pronunciationRef = React.useRef<FocusableElement | null>(null);
    const prefix = `anw-reading-rules-workspace-${props.novelId}`;

    React.useEffect(() => {
      setActiveSection(normalizeReadingRulesWorkspaceSection(props.initialSection));
    }, [props.novelId, props.initialSection]);

    const activate = (section: ReadingRulesWorkspaceSection): void => {
      setActiveSection(section);
      props.onSectionChange?.(section);
      queueMicrotask(() => {
        const target = section === "recognition" ? recognitionRef.current : pronunciationRef.current;
        target?.focus({ preventScroll: false });
      });
    };

    if (props.settings.novel_id !== props.novelId) {
      return h("section", {
        className: "anw-reading-rules-workspace",
        role: "region",
        "aria-labelledby": `${prefix}-heading`,
      },
      h("h2", { id: `${prefix}-heading` }, "识别、发音与停顿"),
      h("p", { role: "alert" }, "朗读规则与当前作品不一致，已拒绝组合显示。"),
      );
    }

    return h("section", {
      className: ["anw-reading-rules-workspace", props.className ?? ""].filter(Boolean).join(" "),
      role: "region",
      "aria-labelledby": `${prefix}-heading`,
      "data-active-rules-section": activeSection,
    },
    h("header", null,
      h("p", { className: "anw-reading-rules-workspace__eyebrow" }, "作品级朗读规则"),
      h("h2", { id: `${prefix}-heading` }, "识别、发音与停顿"),
      h("p", null, "先决定脚本如何识别人声与复核，再用同一工作区检查发音规则命中。"),
    ),
    h("nav", { "aria-label": "识别、发音与停顿分区" },
      h("button", {
        type: "button",
        "aria-current": activeSection === "recognition" ? "page" : undefined,
        "aria-controls": `${prefix}-recognition`,
        onClick: () => activate("recognition"),
      }, "识别与复核"),
      h("button", {
        type: "button",
        "aria-current": activeSection === "pronunciation" ? "page" : undefined,
        "aria-controls": `${prefix}-pronunciation`,
        onClick: () => activate("pronunciation"),
      }, "发音命中"),
    ),
    h("div", {
      id: `${prefix}-recognition`,
      ref: recognitionRef,
      tabIndex: -1,
      className: "anw-reading-rules-workspace__section",
      "data-rules-section": "recognition",
    },
    h(ReadingRulesPanel, {
      novelId: props.novelId,
      settings: props.settings,
      capabilities: props.capabilities,
      authorization: props.authorization,
      onSettingsSaved: props.onSettingsSaved,
      onConsentChanged: props.onConsentChanged,
      onRefresh: props.onRefresh,
      createIdempotencyKey: props.createIdempotencyKey,
    }),
    ),
    h("div", {
      id: `${prefix}-pronunciation`,
      ref: pronunciationRef,
      tabIndex: -1,
      className: "anw-reading-rules-workspace__section",
      "data-rules-section": "pronunciation",
    },
    h(PronunciationPanel, {
      novelId: props.novelId,
      capabilities: props.capabilities,
      authorization: props.authorization,
      scopeOptions: props.pronunciationScopeOptions,
      timing: props.settings.values.timing,
      initialPreviewText: props.initialPreviewText,
      onOpenReadingSettings: props.onOpenReadingPreferences,
      onSaved: props.onPronunciationSaved,
      onPreviewHits: props.onPreviewHits,
      onReturnFocus: props.onReturnFocus,
    }),
    ),
    );
  };
}
