import type {
  CapabilityKey,
  CharacterVoiceBindingResource,
  FeatureCapability,
  NarrationAuthorizationState,
  NarrationCapabilities,
  VoiceProfileResource,
  VoiceProfileVersionResource,
  VoiceSourceType,
} from "./contracts";
import {
  voiceActivationEvidenceIsUsable,
  voiceSourceEvidenceIsUsable,
} from "./contracts";


export interface CharacterVoiceRosterReactRuntime {
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


export interface CharacterVoiceRosterCharacter {
  readonly characterId: string;
  readonly characterName: string;
  readonly roleType?: "main" | "supporting" | string | null;
}


export type CharacterVoiceSourceGroup = "official" | "private" | "unresolved";


export interface CharacterVoiceRosterRow {
  readonly characterId: string;
  readonly characterName: string;
  readonly roleLabel: string;
  readonly binding: CharacterVoiceBindingResource | null;
  readonly configured: boolean;
  readonly profile: VoiceProfileResource | null;
  readonly version: VoiceProfileVersionResource | null;
  readonly voiceName: string;
  readonly sourceGroup: CharacterVoiceSourceGroup;
  readonly sourceLabel: string | null;
  readonly sourceType: VoiceSourceType | null;
  readonly statusLabel: string | null;
  readonly previewAvailable: boolean;
}


export interface CharacterVoiceRosterProps {
  readonly novelId: string;
  readonly characters: readonly CharacterVoiceRosterCharacter[];
  readonly bindings: readonly CharacterVoiceBindingResource[];
  readonly profiles: readonly VoiceProfileResource[];
  readonly capabilities: NarrationCapabilities;
  readonly authorization: NarrationAuthorizationState;
  readonly className?: string;
  readonly onConfigureCharacter: (characterId: string) => void;
  readonly renderConfigurator?: (
    character: CharacterVoiceRosterCharacter,
    close: () => void,
  ) => unknown;
  readonly onPreviewVoice?: (
    character: CharacterVoiceRosterCharacter,
    profile: VoiceProfileResource,
    version: VoiceProfileVersionResource,
  ) => void | Promise<void>;
}


type PreviewPhase = "running" | "success" | "error";


interface PreviewState {
  readonly phase: PreviewPhase;
  readonly message: string;
}


interface FocusableElement {
  focus(options?: FocusOptions): void;
  closest?(selector: string): unknown;
  getClientRects?(): ArrayLike<unknown>;
}


interface DrawerElement extends FocusableElement {
  querySelectorAll(selector: string): ArrayLike<FocusableElement>;
}


interface ButtonEvent {
  readonly currentTarget: FocusableElement;
}


interface DrawerKeyboardEvent {
  readonly key: string;
  readonly shiftKey?: boolean;
  readonly isComposing?: boolean;
  readonly nativeEvent?: { readonly isComposing?: boolean };
  readonly target: unknown;
  preventDefault(): void;
  stopPropagation(): void;
}


const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "details > summary",
  "[tabindex]:not([tabindex='-1'])",
].join(",");


function visibleFocusables(drawer: DrawerElement | null): FocusableElement[] {
  return Array.from(drawer?.querySelectorAll(FOCUSABLE_SELECTOR) ?? []).filter((element) => (
    !element.closest?.('[hidden], [inert], [aria-hidden="true"]')
    // Closed details keep their children mounted to preserve unfinished edits.
    // Those children have no rendered rectangles and must not define Tab edges.
    && element.getClientRects?.().length !== 0
  ));
}


function capabilityByKey(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): FeatureCapability | undefined {
  return capabilities.items.find((item) => item.key === key);
}


function capabilityIsActionable(
  capabilities: NarrationCapabilities,
  key: CapabilityKey,
): boolean {
  const capability = capabilityByKey(capabilities, key);
  return capability?.state === "enabled"
    && capability.visible
    && capability.actionable;
}


function sourceGroup(version: VoiceProfileVersionResource | null): CharacterVoiceSourceGroup {
  if (version === null) return "unresolved";
  if (version.source_type === "preset"
    && voiceSourceEvidenceIsUsable(version)
    && voiceActivationEvidenceIsUsable(version)) return "official";
  if (version.source_type === "uploaded" || version.source_type === "generated") return "private";
  return "unresolved";
}


function sourceLabel(
  group: CharacterVoiceSourceGroup,
  type: VoiceSourceType | null,
): string {
  if (group === "official") return "官方音色";
  if (type === "generated") return "专属音色";
  if (type === "uploaded") return "私人录音";
  return "来源待恢复";
}


function roleLabel(roleType: CharacterVoiceRosterCharacter["roleType"]): string {
  if (roleType === "main") return "主角";
  if (roleType === "supporting") return "配角";
  return "人物";
}


function currentProfileVersion(
  profile: VoiceProfileResource | null,
  versionId: string | null,
): VoiceProfileVersionResource | null {
  if (profile === null || versionId === null) return null;
  return profile.versions.find((version) => version.version_id === versionId) ?? null;
}


export function buildCharacterVoiceRosterRows(
  novelId: string,
  characters: readonly CharacterVoiceRosterCharacter[],
  bindings: readonly CharacterVoiceBindingResource[],
  profiles: readonly VoiceProfileResource[],
): readonly CharacterVoiceRosterRow[] {
  const characterIds = new Set(characters.map((character) => character.characterId));
  const bindingByCharacter = new Map<string, CharacterVoiceBindingResource>();
  for (const binding of bindings) {
    if (binding.novel_id !== novelId || !characterIds.has(binding.character_id)) continue;
    if (!bindingByCharacter.has(binding.character_id)) {
      bindingByCharacter.set(binding.character_id, binding);
    }
  }
  const profileById = new Map(
    profiles
      .filter((profile) => profile.novel_id === null || profile.novel_id === novelId)
      .map((profile) => [profile.profile_id, profile] as const),
  );
  return characters.map((character) => {
    const binding = bindingByCharacter.get(character.characterId) ?? null;
    const configured = Boolean(
      binding
      && binding.binding_policy !== "unset"
      && binding.profile_id
      && binding.version_id,
    );
    const profile = configured && binding?.profile_id
      ? profileById.get(binding.profile_id) ?? null
      : null;
    const version = currentProfileVersion(profile, binding?.version_id ?? null);
    const group = configured ? sourceGroup(version) : "unresolved";
    return {
      characterId: character.characterId,
      characterName: character.characterName,
      roleLabel: roleLabel(character.roleType),
      binding,
      configured,
      profile,
      version,
      voiceName: configured ? profile?.name ?? "绑定音色不可用" : "尚未配置",
      sourceGroup: group,
      sourceLabel: configured
        ? sourceLabel(group, version?.source_type ?? null)
        : null,
      sourceType: version?.source_type ?? null,
      statusLabel: configured && version === null ? "需要处理" : null,
      previewAvailable: Boolean(
        version
        && (
          group === "official"
          || (version.source_type === "generated" && version.preview_asset)
        ),
      ),
    };
  });
}


function configurationIsActionable(
  props: Pick<CharacterVoiceRosterProps, "authorization" | "capabilities">,
): boolean {
  return props.authorization.can_read
    && props.authorization.can_configure
    && capabilityIsActionable(props.capabilities, "narration_product")
    && capabilityIsActionable(props.capabilities, "reading_settings");
}


function actionError(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "操作失败，请稍后重试。";
}


export function createCharacterVoiceRoster(
  React: CharacterVoiceRosterReactRuntime,
): (props: CharacterVoiceRosterProps) => unknown {
  const h = React.createElement;

  return function CharacterVoiceRoster(props: CharacterVoiceRosterProps): unknown {
    const rows = buildCharacterVoiceRosterRows(
      props.novelId,
      props.characters,
      props.bindings,
      props.profiles,
    );
    const [previewStates, setPreviewStates] = React.useState<Readonly<Record<string, PreviewState>>>({});
    const [drawerOpen, setDrawerOpen] = React.useState(false);
    const [selectedCharacterId, setSelectedCharacterId] = React.useState<string | null>(null);
    const mountedRef = React.useRef(true);
    const drawerRef = React.useRef<DrawerElement | null>(null);
    const openerRef = React.useRef<FocusableElement | null>(null);
    React.useEffect(() => {
      mountedRef.current = true;
      return () => { mountedRef.current = false; };
    }, []);
    const unconfigured = rows.filter((row) => !row.configured);
    const configureEnabled = configurationIsActionable(props);
    const statusId = `anw-character-voice-roster-${props.novelId}-status`;
    const selectedCharacter = selectedCharacterId === null
      ? null
      : props.characters.find((item) => item.characterId === selectedCharacterId) ?? null;

    React.useEffect(() => {
      if (!drawerOpen) return;
      queueMicrotask(() => {
        const first = visibleFocusables(drawerRef.current)[0];
        first?.focus({ preventScroll: true });
      });
    }, [drawerOpen, selectedCharacterId]);

    const updatePreview = (characterId: string, state: PreviewState) => {
      if (!mountedRef.current) return;
      setPreviewStates((current) => ({ ...current, [characterId]: state }));
    };

    const closeDrawer = (): void => {
      if (!drawerOpen) return;
      setDrawerOpen(false);
      queueMicrotask(() => openerRef.current?.focus({ preventScroll: true }));
    };

    const openDrawer = (
      character: CharacterVoiceRosterCharacter,
      trigger: FocusableElement,
    ): void => {
      if (!configureEnabled) return;
      openerRef.current = trigger;
      setSelectedCharacterId(character.characterId);
      props.onConfigureCharacter(character.characterId);
      if (props.renderConfigurator) setDrawerOpen(true);
    };

    const trapDrawerFocus = (event: DrawerKeyboardEvent): void => {
      if (!drawerOpen) return;
      if (event.isComposing || event.nativeEvent?.isComposing) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeDrawer();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = visibleFocusables(drawerRef.current);
      if (focusables.length === 0) {
        event.preventDefault();
        drawerRef.current?.focus();
        return;
      }
      const currentIndex = focusables.indexOf(event.target as FocusableElement);
      const nextIndex = event.shiftKey
        ? currentIndex <= 0 ? focusables.length - 1 : currentIndex - 1
        : currentIndex < 0 || currentIndex === focusables.length - 1 ? 0 : currentIndex + 1;
      if (
        currentIndex < 0
        || (event.shiftKey && currentIndex === 0)
        || (!event.shiftKey && currentIndex === focusables.length - 1)
      ) {
        event.preventDefault();
        focusables[nextIndex]?.focus();
      }
    };

    const runPreview = async (
      character: CharacterVoiceRosterCharacter,
      profile: VoiceProfileResource,
      version: VoiceProfileVersionResource,
    ) => {
      if (!props.onPreviewVoice) return;
      updatePreview(character.characterId, {
        phase: "running",
        message: "正在准备试听…",
      });
      try {
        await props.onPreviewVoice(character, profile, version);
        updatePreview(character.characterId, {
          phase: "success",
          message: "试听已开始，不会更改当前声音。",
        });
      } catch (reason: unknown) {
        updatePreview(character.characterId, {
          phase: "error",
          message: actionError(reason),
        });
      }
    };

    const rootClassName = ["anw-character-voice-roster", props.className ?? ""]
      .filter(Boolean)
      .join(" ");
    if (!props.authorization.can_read) {
      return h(
        "section",
        { className: rootClassName, role: "status" },
        h("h2", null, "人物配音"),
        h("p", { className: "anw-character-voice-roster__empty" }, "当前身份无权查看人物配音。"),
      );
    }
    return h(
      "section",
      {
        className: rootClassName,
        "aria-labelledby": `${statusId}-heading`,
        "aria-describedby": statusId,
      },
      h("header", { className: "anw-character-voice-roster__header" },
        h("div", null,
          h("h2", { id: `${statusId}-heading` }, "人物配音"),
          h("p", null, `${rows.length} 位人物 · ${unconfigured.length} 位待配置`),
        ),
      ),
      h("p", {
        id: statusId,
        className: "anw-character-voice-roster__status",
        role: "status",
        "aria-live": "polite",
      }, configureEnabled ? "为每位人物选择 Qwen 官方音色或已授权的私人音色。" : "当前人物声音设置为只读。"),
      rows.length === 0
        ? h("p", { className: "anw-character-voice-roster__empty", role: "status" },
          "当前作品还没有可配置声音的人物。请先在人物卡中新建人物。",
        )
        : h("ul", { className: "anw-character-voice-roster__list" },
          ...rows.map((row) => {
            const previewState = previewStates[row.characterId];
            const character = props.characters.find((item) => item.characterId === row.characterId)
              ?? { characterId: row.characterId, characterName: row.characterName };
            const previewEnabled = Boolean(
              row.profile
              && row.version
              && row.previewAvailable
              && props.onPreviewVoice
              && previewState?.phase !== "running",
            );
            return h("li", {
              key: row.characterId,
              className: `anw-character-voice-roster__card is-${row.configured ? "configured" : "unconfigured"}`,
              "data-character-id": row.characterId,
            },
            h("div", { className: "anw-character-voice-roster__identity" },
              h("strong", null, row.characterName),
              h("span", { className: "anw-character-voice-roster__role" }, row.roleLabel),
            ),
            h("div", { className: "anw-character-voice-roster__binding" },
              h("strong", null, row.voiceName),
              row.sourceLabel === null
                ? null
                : h("span", { className: `anw-character-voice-roster__source is-${row.sourceGroup}` },
                  row.sourceLabel,
                ),
              row.statusLabel === null
                ? null
                : h("span", { className: "anw-character-voice-roster__coverage is-missing" },
                  row.statusLabel,
                ),
            ),
            previewState
              ? h("p", {
                className: `anw-character-voice-roster__result is-${previewState.phase}`,
                role: previewState.phase === "error" ? "alert" : "status",
              }, previewState.message)
              : null,
            h("div", { className: "anw-character-voice-roster__actions" },
              props.onPreviewVoice
                ? h("button", {
                  type: "button",
                  disabled: !previewEnabled,
                  title: previewEnabled ? "试听当前声音" : "当前声音暂无可试听音频",
                  onClick: () => {
                    if (row.profile && row.version && previewEnabled) {
                      void runPreview(character, row.profile, row.version);
                    }
                  },
                }, previewState?.phase === "running" ? "准备中…" : "试听")
                : null,
              h("button", {
                type: "button",
                disabled: !configureEnabled,
                title: configureEnabled ? undefined : "当前人物声音设置为只读。",
                "aria-haspopup": props.renderConfigurator ? "dialog" : undefined,
                onClick: (event: ButtonEvent) => openDrawer(character, event.currentTarget),
              }, "更换"),
            ));
          }),
        ),
      props.renderConfigurator && selectedCharacter
        ? h("div", {
          className: "anw-character-voice-drawer-layer",
          hidden: !drawerOpen,
          inert: !drawerOpen ? true : undefined,
          "aria-hidden": !drawerOpen ? true : undefined,
        },
        h("button", {
          type: "button",
          className: "anw-character-voice-drawer__backdrop",
          tabIndex: -1,
          "aria-label": "关闭人物声音设置",
          onClick: closeDrawer,
        }),
        h("section", {
          ref: (element: DrawerElement | null) => { drawerRef.current = element; },
          className: "anw-character-voice-drawer",
          role: "dialog",
          "aria-modal": true,
          "aria-labelledby": `${statusId}-drawer-heading`,
          tabIndex: -1,
          onKeyDown: trapDrawerFocus,
        },
        h("header", { className: "anw-character-voice-drawer__header" },
          h("div", null,
            h("p", null, "人物声音"),
            h("h2", { id: `${statusId}-drawer-heading` }, selectedCharacter.characterName),
          ),
          h("button", {
            type: "button",
            className: "anw-character-voice-drawer__close",
            onClick: closeDrawer,
            "aria-label": "关闭人物声音设置",
          }, "关闭"),
        ),
        h("div", { className: "anw-character-voice-drawer__body" },
          props.renderConfigurator(selectedCharacter, closeDrawer),
        )),
        )
        : null,
    );
  };
}
