export interface PrivateLibraryAssistantNovel {
  readonly id: string;
  readonly title: string;
}


type Listener = () => void;


let selectedNovel: PrivateLibraryAssistantNovel | null = null;
const listeners = new Set<Listener>();


/**
 * Publish only the currently selected private-library novel. The backend still
 * verifies this identifier before an assistant context ref can be created.
 */
export function publishPrivateLibraryAssistantNovel(
  novel: PrivateLibraryAssistantNovel | null,
): void {
  const next = novel && novel.id.trim()
    ? { id: novel.id, title: novel.title }
    : null;
  if (selectedNovel?.id === next?.id && selectedNovel?.title === next?.title) return;
  selectedNovel = next;
  for (const listener of listeners) listener();
}


export function currentPrivateLibraryAssistantNovel(): PrivateLibraryAssistantNovel | null {
  return selectedNovel;
}


export function subscribePrivateLibraryAssistantNovel(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
