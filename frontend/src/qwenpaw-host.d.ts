interface QwenPawDisposable {
  dispose: () => void;
}

interface QwenPawAgentRef {
  id: string;
}

interface QwenPawSessionRef {
  id: string;
}

interface QwenPawSuggestionItem {
  label: string;
  value: string;
}

interface QwenPawRequestPayloadArgs {
  payload: Record<string, unknown>;
  sessionId?: string;
  selectedAgent?: string;
}

interface QwenPawToolRenderProps {
  result?: unknown;
  sessionId?: string;
  messageId?: string;
  data?: unknown;
}

interface Window {
  QwenPaw: {
    host: {
      React: any;
      ReactDOM: any;
      antd: any;
      antdIcons: any;
      useTheme: () => "light" | "dark";
      useLocale: () => "zh" | "en";
      useSelectedAgent: () => QwenPawAgentRef;
      useCurrentSession: () => QwenPawSessionRef | null;
      getSelectedAgentId: () => string | null;
      getCurrentSessionId: () => string | null;
      fetch: (path: string, init?: RequestInit) => Promise<Response>;
      getApiUrl: (path: string) => string;
      getApiToken: () => string | null;
    };
    route: {
      add: (
        pluginId: string,
        route: { id: string; path: string; component: unknown },
      ) => QwenPawDisposable;
      wrap: (
        pluginId: string,
        targetId: string,
        wrapper: (inner: any) => any,
      ) => QwenPawDisposable;
    };
    chat: {
      sender: {
        addSuggestion: (
          pluginId: string,
          suggestion: { id: string; items: QwenPawSuggestionItem[] },
        ) => QwenPawDisposable;
      };
      requestPayload: {
        add: (
          pluginId: string,
          transformer: (
            args: QwenPawRequestPayloadArgs,
          ) => Record<string, unknown> | undefined,
          options?: { id?: string; order?: number },
        ) => QwenPawDisposable;
      };
      toolRender: (
        pluginId: string,
        toolName: string,
        renderer: (props: QwenPawToolRenderProps) => unknown,
      ) => QwenPawDisposable;
      disposeAll: (pluginId: string) => void;
    };
  };
}

declare module "*.jpg" {
  const url: string;
  export default url;
}

declare module "*.png" {
  const url: string;
  export default url;
}
