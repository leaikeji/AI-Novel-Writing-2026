import { describe, expect, it, vi } from "vitest";

import { createAssistantSuggestionRegistry } from "./assistant-suggestions";


describe("assistant suggestions", () => {
  it("registers normalized unique items and deduplicates identical updates", () => {
    const disposers: Array<ReturnType<typeof vi.fn>> = [];
    const addSuggestion = vi.fn(() => {
      const dispose = vi.fn();
      disposers.push(dispose);
      return { dispose };
    });
    const registry = createAssistantSuggestionRegistry(
      "ai-novel-world-2026",
      { addSuggestion },
    );
    const definition = {
      id: "selection-actions",
      items: [
        { label: " 润色 ", value: " 请润色选区 " },
        { label: "润色", value: "请润色选区" },
      ],
    };

    expect(registry.upsert(definition)).toBe("registered");
    expect(registry.upsert(definition)).toBe("unchanged");
    expect(addSuggestion).toHaveBeenCalledTimes(1);
    expect(addSuggestion).toHaveBeenCalledWith(
      "ai-novel-world-2026",
      {
        id: "selection-actions",
        items: [{ label: "润色", value: "请润色选区" }],
      },
    );
    expect(disposers[0]).not.toHaveBeenCalled();
  });

  it("disposes the old registration when a definition changes", () => {
    const disposeFirst = vi.fn();
    const disposeSecond = vi.fn();
    const addSuggestion = vi.fn()
      .mockReturnValueOnce({ dispose: disposeFirst })
      .mockReturnValueOnce({ dispose: disposeSecond });
    const registry = createAssistantSuggestionRegistry("plugin", { addSuggestion });

    registry.upsert({
      id: "selection-actions",
      items: [{ label: "润色", value: "润色" }],
    });
    expect(registry.upsert({
      id: "selection-actions",
      items: [{ label: "扩写", value: "扩写" }],
    })).toBe("registered");

    expect(disposeFirst).toHaveBeenCalledOnce();
    expect(disposeSecond).not.toHaveBeenCalled();
    expect(registry.registeredIds()).toEqual(["selection-actions"]);
  });

  it("supports explicit removal, clear and idempotent final disposal", () => {
    const disposers: Array<ReturnType<typeof vi.fn>> = [];
    const addSuggestion = vi.fn(() => {
      const dispose = vi.fn();
      disposers.push(dispose);
      return { dispose };
    });
    const registry = createAssistantSuggestionRegistry("plugin", { addSuggestion });
    registry.upsert({ id: "one", items: [{ label: "一", value: "一" }] });
    registry.upsert({ id: "two", items: [{ label: "二", value: "二" }] });

    expect(registry.remove("one")).toBe(true);
    expect(registry.remove("missing")).toBe(false);
    registry.dispose();
    registry.dispose();

    expect(disposers[0]).toHaveBeenCalledOnce();
    expect(disposers[1]).toHaveBeenCalledOnce();
    expect(registry.registeredIds()).toEqual([]);
    expect(() => registry.upsert({
      id: "late",
      items: [{ label: "迟到", value: "迟到" }],
    })).toThrow("disposed");
  });

  it("removes an existing registration when no valid items remain", () => {
    const dispose = vi.fn();
    const registry = createAssistantSuggestionRegistry("plugin", {
      addSuggestion: vi.fn(() => ({ dispose })),
    });
    registry.upsert({ id: "selection", items: [{ label: "润色", value: "润色" }] });

    expect(registry.upsert({
      id: "selection",
      items: [{ label: "", value: "" }],
    })).toBe("removed");
    expect(dispose).toHaveBeenCalledOnce();
  });
});
