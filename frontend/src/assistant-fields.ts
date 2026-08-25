export type EditableFieldPersistence = "autosave" | "explicit-save";
export type EditableFieldSelectionDirection = "forward" | "backward" | "none";


export interface SelectionRange {
  startUtf16: number;
  endUtf16: number;
  direction: EditableFieldSelectionDirection;
}


export interface SelectionSnapshot extends SelectionRange {
  text: string;
  before: string;
  after: string;
}


export interface AIApplyMeta {
  transactionId: string;
  agentId: string;
  sessionId?: string;
  selectionId?: string;
  operation: string;
  sourceValueSha256: string;
  appliedAt: string;
}


export interface EditableFieldAdapter {
  readonly id: string;
  readonly label: string;
  readonly persistence: EditableFieldPersistence;
  readonly undoPolicy: "ai-transaction";
  getValue(): string;
  applyValue(nextValue: string, meta: AIApplyMeta): void | Promise<void>;
  getSelection(): SelectionSnapshot | null;
  restoreSelection?(range: SelectionRange): void;
  focus(): void;
  getDirty(): boolean;
  dispose(): void;
}


export interface EditableFieldRegistrySnapshot {
  focusedFieldId?: string;
  fieldIds: string[];
}


export interface EditableFieldRegistration {
  dispose(): void;
}


export class EditableFieldRegistry {
  private readonly fields = new Map<string, EditableFieldAdapter>();
  private focusedFieldId: string | undefined;

  register(adapter: EditableFieldAdapter): EditableFieldRegistration {
    if (!adapter.id.trim()) {
      throw new Error("editable field id must not be empty");
    }
    if (this.fields.has(adapter.id)) {
      throw new Error(`editable field already registered: ${adapter.id}`);
    }
    this.fields.set(adapter.id, adapter);
    let active = true;
    return {
      dispose: () => {
        if (!active) return;
        active = false;
        if (this.fields.get(adapter.id) !== adapter) return;
        this.fields.delete(adapter.id);
        if (this.focusedFieldId === adapter.id) {
          this.focusedFieldId = undefined;
        }
        adapter.dispose();
      },
    };
  }

  get(fieldId: string): EditableFieldAdapter | undefined {
    return this.fields.get(fieldId);
  }

  list(): EditableFieldAdapter[] {
    return [...this.fields.values()];
  }

  setFocused(fieldId: string | undefined): void {
    if (fieldId !== undefined && !this.fields.has(fieldId)) {
      throw new Error(`editable field is not registered: ${fieldId}`);
    }
    this.focusedFieldId = fieldId;
  }

  getFocused(): EditableFieldAdapter | undefined {
    return this.focusedFieldId === undefined
      ? undefined
      : this.fields.get(this.focusedFieldId);
  }

  snapshot(): EditableFieldRegistrySnapshot {
    return {
      focusedFieldId: this.focusedFieldId,
      fieldIds: [...this.fields.keys()],
    };
  }

  clear(): void {
    const registrations = [...this.fields.values()];
    this.fields.clear();
    this.focusedFieldId = undefined;
    for (const adapter of registrations) {
      adapter.dispose();
    }
  }
}
