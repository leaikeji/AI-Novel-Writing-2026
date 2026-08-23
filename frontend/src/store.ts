import { createStore } from "zustand/vanilla";

interface WorkbenchState {
  novelId: string | null;
  documentId: string | null;
  select: (novelId: string | null, documentId: string | null) => void;
}

export const workbenchStore = createStore<WorkbenchState>((set) => ({
  novelId: null,
  documentId: null,
  select: (novelId, documentId) => set({ novelId, documentId }),
}));

export function useWorkbenchState(): WorkbenchState {
  const React = window.QwenPaw.host.React;
  return React.useSyncExternalStore(
    workbenchStore.subscribe,
    workbenchStore.getState,
    workbenchStore.getInitialState,
  );
}
