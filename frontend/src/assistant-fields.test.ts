import { describe, expect, it, vi } from "vitest";

import {
  EditableFieldRegistry,
  type EditableFieldAdapter,
} from "./assistant-fields";


function adapter(id: string): EditableFieldAdapter {
  return {
    id,
    label: id,
    persistence: "explicit-save",
    undoPolicy: "ai-transaction",
    getValue: () => "",
    applyValue: () => undefined,
    getSelection: () => null,
    focus: () => undefined,
    getDirty: () => false,
    dispose: vi.fn(),
  };
}


describe("EditableFieldRegistry", () => {
  it("owns field lifecycle and clears focus with disposal", () => {
    const registry = new EditableFieldRegistry();
    const title = adapter("chapter.title");
    const registration = registry.register(title);
    registry.setFocused(title.id);

    expect(registry.getFocused()).toBe(title);
    expect(registry.snapshot()).toEqual({
      focusedFieldId: title.id,
      fieldIds: [title.id],
    });

    registration.dispose();
    registration.dispose();

    expect(registry.get(title.id)).toBeUndefined();
    expect(registry.getFocused()).toBeUndefined();
    expect(title.dispose).toHaveBeenCalledTimes(1);
  });

  it("rejects duplicate ids and disposes every remaining field on clear", () => {
    const registry = new EditableFieldRegistry();
    const first = adapter("chapter.body");
    const second = adapter("chapter.outline");
    registry.register(first);
    registry.register(second);

    expect(() => registry.register(adapter(first.id))).toThrow(
      "editable field already registered",
    );

    registry.clear();

    expect(first.dispose).toHaveBeenCalledTimes(1);
    expect(second.dispose).toHaveBeenCalledTimes(1);
    expect(registry.snapshot()).toEqual({ fieldIds: [] });
  });
});
