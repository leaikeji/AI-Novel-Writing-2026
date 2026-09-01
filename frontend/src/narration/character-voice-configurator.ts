export interface CharacterVoiceConfiguratorReactRuntime {
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


export interface CharacterVoiceConfiguratorCurrentVoice {
  readonly phase: "loading" | "unbound" | "resolved" | "unresolved" | "error";
  readonly name: string | null;
  readonly sourceLabel: string | null;
  readonly languageLabel: string | null;
  readonly message?: string | null;
}


export interface CharacterVoiceConfiguratorMatchResult {
  readonly voiceName: string;
  readonly presetId: string;
  readonly selectionStillCurrent: boolean;
}


export interface CharacterVoiceConfiguratorProps {
  readonly scopeId: string;
  readonly characterId: string;
  readonly characterName: string;
  readonly currentVoice: CharacterVoiceConfiguratorCurrentVoice;
  readonly canConfigure: boolean;
  readonly matchEnabled: boolean;
  readonly matchDisabledReason?: string | null;
  readonly onMatchOfficialVoice?: (
    signal: AbortSignal,
  ) => Promise<CharacterVoiceConfiguratorMatchResult>;
  readonly onUseMatchedOfficialVoice?: (
    presetId: string,
    signal: AbortSignal,
  ) => Promise<CharacterVoiceConfiguratorMatchResult>;
  readonly generatorContent?: unknown;
  readonly officialVoiceContent?: unknown;
  readonly advancedContent?: unknown;
  readonly officialVoicesOpenByDefault?: boolean;
  readonly className?: string;
  readonly onChanged?: () => void;
}


type MatchPhase = "idle" | "running" | "success" | "error";


interface MatchState {
  readonly scopeId: string;
  readonly phase: MatchPhase;
  readonly message: string;
  readonly presetId: string | null;
  readonly needsApply: boolean;
}


function initialMatchState(scopeId: string): MatchState {
  return Object.freeze({
    scopeId,
    phase: "idle",
    message: "",
    presetId: null,
    needsApply: false,
  });
}


function actionError(reason: unknown): string {
  return reason instanceof Error && reason.message.trim()
    ? reason.message
    : "操作失败，请稍后重试。";
}


function safeDomToken(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/gu, "-").replace(/-+/gu, "-") || "character";
}


function currentVoiceCopy(
  current: CharacterVoiceConfiguratorCurrentVoice,
): { readonly badge: string; readonly message: string; readonly tone: string } {
  if (current.phase === "loading") {
    return { badge: "读取中", message: current.message ?? "正在读取当前声音…", tone: "is-muted" };
  }
  if (current.phase === "unbound") {
    return { badge: "跟随规则", message: current.message ?? "尚未单独绑定声音。", tone: "is-muted" };
  }
  if (current.phase === "resolved") {
    const metadata = [current.sourceLabel, current.languageLabel].filter(Boolean).join(" · ");
    return {
      badge: "正在使用",
      message: [current.name, metadata].filter(Boolean).join(" · "),
      tone: "",
    };
  }
  return {
    badge: current.phase === "error" ? "读取失败" : "需要恢复",
    message: current.message ?? (
      current.phase === "error"
        ? "当前声音暂时无法读取，请刷新后重试。"
        : "已保存的声音暂时不可用，可重新选择。"
    ),
    tone: "is-error",
  };
}


/**
 * The only character-voice composition shell used by both the character card
 * and the global roster drawer. Network adapters remain outside this module;
 * request cancellation and stale-scope protection live here once.
 */
export function createCharacterVoiceConfigurator(
  React: CharacterVoiceConfiguratorReactRuntime,
): (props: CharacterVoiceConfiguratorProps) => unknown {
  const h = React.createElement;

  return function CharacterVoiceConfigurator(
    props: CharacterVoiceConfiguratorProps,
  ): unknown {
    const [matchState, setMatchState] = React.useState<MatchState>(() => (
      initialMatchState(props.scopeId)
    ));
    const [officialActivated, setOfficialActivated] = React.useState(
      props.officialVoicesOpenByDefault === true,
    );
    const [advancedActivated, setAdvancedActivated] = React.useState(false);
    const state = matchState.scopeId === props.scopeId
      ? matchState
      : initialMatchState(props.scopeId);
    const stateRef = React.useRef(state);
    stateRef.current = state;
    const requestRef = React.useRef<{
      readonly sequence: number;
      readonly scopeId: string;
      readonly controller: AbortController;
    } | null>(null);
    const sequenceRef = React.useRef(0);
    const prefix = `anw-character-voice-configurator-${safeDomToken(props.characterId)}`;
    const current = currentVoiceCopy(props.currentVoice);

    React.useEffect(() => {
      requestRef.current?.controller.abort();
      requestRef.current = null;
      sequenceRef.current += 1;
      const reset = initialMatchState(props.scopeId);
      stateRef.current = reset;
      setMatchState(reset);
      setOfficialActivated(props.officialVoicesOpenByDefault === true);
      setAdvancedActivated(false);
    }, [props.scopeId]);

    React.useEffect(() => () => {
      requestRef.current?.controller.abort();
      requestRef.current = null;
      sequenceRef.current += 1;
    }, []);

    const ownsRequest = (
      request: NonNullable<typeof requestRef.current>,
    ): boolean => !request.controller.signal.aborted
      && requestRef.current?.sequence === request.sequence
      && requestRef.current.scopeId === props.scopeId;

    const runMatch = (presetId: string | null = null): void => {
      const applyExisting = presetId !== null;
      const handler = applyExisting
        ? props.onUseMatchedOfficialVoice
        : props.onMatchOfficialVoice;
      if (
        handler === undefined
        || !props.canConfigure
        || !props.matchEnabled
        || stateRef.current.phase === "running"
      ) return;
      requestRef.current?.controller.abort();
      const request = {
        sequence: sequenceRef.current + 1,
        scopeId: props.scopeId,
        controller: new AbortController(),
      };
      sequenceRef.current = request.sequence;
      requestRef.current = request;
      const running: MatchState = Object.freeze({
        scopeId: props.scopeId,
        phase: "running",
        message: applyExisting ? "正在使用已匹配的官方音色…" : "正在分析已保存的人物卡…",
        presetId,
        needsApply: applyExisting,
      });
      stateRef.current = running;
      setMatchState(running);
      const resultPromise = applyExisting
        ? props.onUseMatchedOfficialVoice?.(presetId, request.controller.signal)
        : props.onMatchOfficialVoice?.(request.controller.signal);
      void resultPromise?.then((result) => {
        if (!ownsRequest(request)) return;
        const success: MatchState = Object.freeze({
          scopeId: props.scopeId,
          phase: "success",
          message: result.selectionStillCurrent
            ? `已使用 ${result.voiceName}。`
            : `已匹配 ${result.voiceName}，但没有覆盖你刚修改的声音。`,
          presetId: result.presetId,
          needsApply: !result.selectionStillCurrent,
        });
        stateRef.current = success;
        setMatchState(success);
        requestRef.current = null;
        props.onChanged?.();
      }).catch((reason: unknown) => {
        if (!ownsRequest(request)) return;
        const failed: MatchState = Object.freeze({
          scopeId: props.scopeId,
          phase: "error",
          message: actionError(reason),
          presetId,
          needsApply: applyExisting,
        });
        stateRef.current = failed;
        setMatchState(failed);
        requestRef.current = null;
      });
    };

    const matchActionAvailable = props.canConfigure
      && props.matchEnabled
      && props.onMatchOfficialVoice !== undefined;
    const statusMessage = state.phase === "idle"
      ? props.matchDisabledReason ?? ""
      : state.message;

    return h(
      "section",
      {
        className: ["anw-character-voice-configurator", props.className ?? ""]
          .filter(Boolean)
          .join(" "),
        "aria-label": `${props.characterName}的声音配置`,
        "data-character-id": props.characterId,
      },
      h(
        "section",
        { className: "anw-character-current-voice", "aria-labelledby": `${prefix}-current` },
        h("header", null,
          h("h3", { id: `${prefix}-current` }, "当前声音"),
          h("span", {
            className: ["anw-character-current-voice__badge", current.tone].filter(Boolean).join(" "),
          }, current.badge),
        ),
        h("p", {
          className: [
            "anw-character-current-voice__status",
            current.tone === "is-error" ? "is-error" : "",
          ].filter(Boolean).join(" "),
          role: current.tone === "is-error" ? "alert" : undefined,
        }, current.message),
      ),
      h(
        "section",
        { className: "anw-character-voice-configurator__match", "aria-labelledby": `${prefix}-match` },
        h("div", null,
          h("h3", { id: `${prefix}-match` }, "智能匹配官方音色"),
          h("p", null, "只分析已保存的人物卡，成功后直接使用。"),
        ),
        h("button", {
          type: "button",
          disabled: !matchActionAvailable || state.phase === "running",
          "aria-describedby": `${prefix}-match-status`,
          onClick: () => runMatch(),
        }, state.phase === "running" && !state.needsApply
          ? "匹配中…"
          : state.phase === "error" && !state.needsApply
            ? "重试智能匹配"
            : "立即智能匹配"),
        h("p", {
          id: `${prefix}-match-status`,
          className: [
            "anw-character-voice-configurator__match-status",
            state.phase === "error" ? "is-error" : "",
          ].filter(Boolean).join(" "),
          role: state.phase === "error" ? "alert" : "status",
          "aria-live": "polite",
        }, statusMessage),
        state.needsApply && state.presetId !== null && props.onUseMatchedOfficialVoice
          ? h("button", {
            type: "button",
            className: "anw-character-voice-configurator__secondary",
            disabled: state.phase === "running",
            onClick: () => runMatch(state.presetId),
          }, state.phase === "running" ? "使用中…" : "使用此音色")
          : null,
      ),
      props.generatorContent === undefined
        ? null
        : props.generatorContent,
      props.officialVoiceContent === undefined
        ? null
        : h(
          "details",
          {
            className: "anw-character-voice-configurator__disclosure",
            open: props.officialVoicesOpenByDefault === true,
            onToggle: (event: { readonly currentTarget: { readonly open: boolean } }) => {
              if (event.currentTarget.open) setOfficialActivated(true);
            },
          },
          h("summary", null,
            h("span", null,
              h("strong", null, "浏览全部官方音色"),
              h("small", null, "选中即使用，试听不会更改绑定。"),
            ),
          ),
          officialActivated
            ? h("div", { className: "anw-character-voice-configurator__disclosure-body" },
              props.officialVoiceContent,
            )
            : null,
        ),
      props.advancedContent === undefined
        ? null
        : h(
          "details",
          {
            className: "anw-character-voice-configurator__disclosure",
            onToggle: (event: { readonly currentTarget: { readonly open: boolean } }) => {
              if (event.currentTarget.open) setAdvancedActivated(true);
            },
          },
          h("summary", null,
            h("span", null,
              h("strong", null, "私人音色与高级调音"),
              h("small", null, "仅在需要时展开。"),
            ),
          ),
          advancedActivated
            ? h("div", { className: "anw-character-voice-configurator__disclosure-body" },
              props.advancedContent,
            )
            : null,
        ),
    );
  };
}
