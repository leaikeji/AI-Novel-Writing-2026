interface Window {
  QwenPaw: {
    host: {
      React: any;
      ReactDOM: any;
      antd: any;
      antdIcons: any;
      fetch: (path: string, init?: RequestInit) => Promise<Response>;
      getApiUrl: (path: string) => string;
      getApiToken: () => string | null;
    };
    route: {
      add: (
        pluginId: string,
        route: { id: string; path: string; component: unknown },
      ) => { dispose: () => void };
      wrap: (
        pluginId: string,
        targetId: string,
        wrapper: (inner: any) => any,
      ) => { dispose: () => void };
    };
  };
}
