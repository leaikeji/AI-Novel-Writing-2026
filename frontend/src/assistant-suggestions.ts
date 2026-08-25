const SAFE_SUGGESTION_ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const MAX_SUGGESTION_ITEMS = 12;
const MAX_LABEL_CHARACTERS = 80;
const MAX_VALUE_CHARACTERS = 2_000;

interface SuggestionExtensionPoint {
  addSuggestion: (
    pluginId: string,
    suggestion: { id: string; items: QwenPawSuggestionItem[] },
  ) => QwenPawDisposable;
}

export interface AssistantSuggestionDefinition {
  id: string;
  items: ReadonlyArray<QwenPawSuggestionItem>;
}

export type AssistantSuggestionUpdate =
  | "registered"
  | "unchanged"
  | "removed";

export interface AssistantSuggestionRegistry {
  upsert(definition: AssistantSuggestionDefinition): AssistantSuggestionUpdate;
  remove(id: string): boolean;
  clear(): void;
  dispose(): void;
  registeredIds(): string[];
}

interface RegisteredSuggestion {
  signature: string;
  disposable: QwenPawDisposable;
}


function normalizeDefinition(
  definition: AssistantSuggestionDefinition,
): { id: string; items: QwenPawSuggestionItem[]; signature: string } {
  if (!SAFE_SUGGESTION_ID.test(definition.id)) {
    throw new Error("Invalid assistant suggestion id");
  }

  const seen = new Set<string>();
  const items: QwenPawSuggestionItem[] = [];
  for (const rawItem of definition.items) {
    if (typeof rawItem.label !== "string") continue;
    const label = rawItem.label.trim();
    const value = rawItem.value.trim();
    if (
      !label
      || !value
      || label.length > MAX_LABEL_CHARACTERS
      || value.length > MAX_VALUE_CHARACTERS
    ) {
      continue;
    }
    const key = JSON.stringify([label, value]);
    if (seen.has(key)) continue;
    seen.add(key);
    items.push({ label, value });
    if (items.length >= MAX_SUGGESTION_ITEMS) break;
  }

  return {
    id: definition.id,
    items,
    signature: JSON.stringify(items),
  };
}


export function createAssistantSuggestionRegistry(
  pluginId: string,
  sender: SuggestionExtensionPoint,
): AssistantSuggestionRegistry {
  const registered = new Map<string, RegisteredSuggestion>();
  let disposed = false;

  const assertActive = () => {
    if (disposed) throw new Error("Assistant suggestion registry is disposed");
  };

  const remove = (id: string): boolean => {
    const current = registered.get(id);
    if (!current) return false;
    registered.delete(id);
    current.disposable.dispose();
    return true;
  };

  const clear = () => {
    for (const id of [...registered.keys()]) remove(id);
  };

  return {
    upsert(definition) {
      assertActive();
      const normalized = normalizeDefinition(definition);
      if (normalized.items.length === 0) {
        remove(normalized.id);
        return "removed";
      }

      const current = registered.get(normalized.id);
      if (current?.signature === normalized.signature) return "unchanged";
      if (current) remove(normalized.id);

      const disposable = sender.addSuggestion(pluginId, {
        id: normalized.id,
        items: normalized.items,
      });
      registered.set(normalized.id, {
        signature: normalized.signature,
        disposable,
      });
      return "registered";
    },
    remove(id) {
      assertActive();
      return remove(id);
    },
    clear() {
      assertActive();
      clear();
    },
    dispose() {
      if (disposed) return;
      clear();
      disposed = true;
    },
    registeredIds() {
      return [...registered.keys()];
    },
  };
}
