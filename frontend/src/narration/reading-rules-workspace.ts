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
      h("h2", { id: `${prefix}-heading` }, "朗读规则"),
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
      h("h2", { id: `${prefix}-heading` }, "朗读规则"),
      h("p", null, "决定如何识别说话人、何时请你确认，以及特殊词语怎么读。"),
    ),
    h("nav", { "aria-label": "朗读规则分区" },
      h("button", {
        type: "button",
        id: `${prefix}-recognition-control`,
        className: activeSection === "recognition" ? "is-active" : undefined,
        "aria-current": activeSection === "recognition" ? "page" : undefined,
        "aria-controls": `${prefix}-recognition`,
        onClick: () => activate("recognition"),
      }, "识别与复核"),
      h("button", {
        type: "button",
        id: `${prefix}-pronunciation-control`,
        className: activeSection === "pronunciation" ? "is-active" : undefined,
        "aria-current": activeSection === "pronunciation" ? "page" : undefined,
        "aria-controls": `${prefix}-pronunciation`,
        onClick: () => activate("pronunciation"),
      }, "发音词典"),
    ),
    h("div", {
      id: `${prefix}-recognition`,
      ref: recognitionRef,
      tabIndex: -1,
      className: "anw-reading-rules-workspace__section",
      hidden: activeSection !== "recognition",
      role: "region",
      "aria-labelledby": `${prefix}-recognition-control`,
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
      hidden: activeSection !== "pronunciation",
      role: "region",
      "aria-labelledby": `${prefix}-pronunciation-control`,
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
