import { ChangeSet, EditorState } from "@codemirror/state";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearEditorParagraphGutter,
  createEditorParagraphGutterButton,
  createEditorParagraphGutterExtension,
  editorParagraphGutterEffect,
  readEditorParagraphGutter,
  replaceEditorParagraphGutter,
  type EditorParagraphGutterEntry,
} from "./editor-paragraph-gutter";
import type { ParagraphGutterButtonModel } from "./paragraph-gutter";


function availableButton(
  paragraphOrdinal: number,
  sourceBlockKey = `paragraph-${paragraphOrdinal}`,
): ParagraphGutterButtonModel {
  return Object.freeze({
    paragraphOrdinal,
    sourceBlockKey,
    targetSegmentId: `segment-${paragraphOrdinal}`,
    availability: "available",
    disabled: false,
    ariaLabel: `从第 ${paragraphOrdinal + 1} 段朗读`,
    title: `播放第 ${paragraphOrdinal + 1} 段`,
  });
}


function disabledButton(
  paragraphOrdinal: number,
  sourceBlockKey = `paragraph-${paragraphOrdinal}`,
): ParagraphGutterButtonModel {
  return Object.freeze({
    paragraphOrdinal,
    sourceBlockKey,
    targetSegmentId: null,
    availability: "update_required",
    disabled: true,
    ariaLabel: `从第 ${paragraphOrdinal + 1} 段朗读`,
    title: "本段已变化，请更新朗读后再播放。",
  });
}


function entry(
  sourceStartUtf16: number,
  paragraphOrdinal: number,
  sourceBlockKey?: string,
): EditorParagraphGutterEntry {
  return Object.freeze({
    sourceStartUtf16,
    button: availableButton(paragraphOrdinal, sourceBlockKey),
  });
}


function createState(document = "甲段。\n\n乙段。") {
  return EditorState.create({
    doc: document,
    extensions: [
      createEditorParagraphGutterExtension({ onActivate: vi.fn() }),
    ],
  });
}


class FakeButton {
  type = "";
  className = "";
  textContent: string | null = null;
  disabled = false;
  title = "";
  readonly dataset: Record<string, string> = {};
  readonly attributes = new Map<string, string>();
  private readonly listeners = new Map<string, Set<EventListenerOrEventListenerObject>>();

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const listeners = this.listeners.get(type) ?? new Set<EventListenerOrEventListenerObject>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type: string, event: object): void {
    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") listener.call(this, event as Event);
      else listener.handleEvent(event as Event);
    }
  }
}


const hadDocument = "document" in globalThis;
const originalDocument = globalThis.document;


afterEach(() => {
  if (hadDocument) {
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: originalDocument,
      writable: true,
    });
  } else {
    Reflect.deleteProperty(globalThis, "document");
  }
});


function installFakeDocument(): FakeButton[] {
  const buttons: FakeButton[] = [];
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      createElement(tagName: string) {
        if (tagName !== "button") throw new Error(`unexpected element: ${tagName}`);
        const button = new FakeButton();
        buttons.push(button);
        return button;
      },
    } as unknown as Document,
    writable: true,
  });
  return buttons;
}


function fakeEvent(patch: Record<string, unknown> = {}) {
  return {
    key: "",
    isComposing: false,
    repeat: false,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    ...patch,
  };
}


describe("CodeMirror paragraph gutter state", () => {
  it("places one independent marker on each paragraph start line", () => {
    let state = createState();
    state = state.update({
      effects: replaceEditorParagraphGutter([
        entry(0, 0),
        entry(5, 1),
      ]),
    }).state;

    expect(readEditorParagraphGutter(state)).toEqual([
      {
        sourceStartUtf16: 0,
        lineNumber: 1,
        button: availableButton(0),
      },
      {
        sourceStartUtf16: 5,
        lineNumber: 3,
        button: availableButton(1),
      },
    ]);
  });

  it("maps paragraph positions through UTF-16 document transactions", () => {
    let state = createState();
    state = state.update({
      effects: replaceEditorParagraphGutter([entry(0, 0), entry(5, 1)]),
    }).state;
    state = state.update({ changes: { from: 0, insert: "标题\n" } }).state;

    expect(readEditorParagraphGutter(state).map((item) => ({
      ordinal: item.button.paragraphOrdinal,
      start: item.sourceStartUtf16,
      line: item.lineNumber,
    }))).toEqual([
      { ordinal: 0, start: 3, line: 2 },
      { ordinal: 1, start: 8, line: 4 },
    ]);
  });

  it("maps a dispatchable effect when CodeMirror rebases it", () => {
    const effect = replaceEditorParagraphGutter([entry(5, 1)]);
    const mapping = ChangeSet.of({ from: 0, insert: "序\n" }, 8);
    const mapped = effect.map(mapping);

    expect(mapped?.is(editorParagraphGutterEffect)).toBe(true);
    expect(mapped?.value).toEqual([entry(7, 1)]);
  });

  it("replaces and clears the full marker set atomically", () => {
    let state = createState();
    state = state.update({
      effects: replaceEditorParagraphGutter([entry(0, 0), entry(5, 1)]),
    }).state;
    state = state.update({
      effects: replaceEditorParagraphGutter([{ sourceStartUtf16: 5, button: disabledButton(1) }]),
    }).state;
    expect(readEditorParagraphGutter(state)).toEqual([{
      sourceStartUtf16: 5,
      lineNumber: 3,
      button: disabledButton(1),
    }]);

    state = state.update({ effects: clearEditorParagraphGutter() }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);
    state = state.update({ effects: clearEditorParagraphGutter() }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);
  });

  it.each([
    {
      name: "out-of-bounds source start",
      payload: [entry(99, 0)],
    },
    {
      name: "duplicate paragraph ordinal",
      payload: [entry(0, 0, "first"), entry(5, 0, "second")],
    },
    {
      name: "duplicate source block",
      payload: [entry(0, 0, "same"), entry(5, 1, "same")],
    },
    {
      name: "duplicate source line",
      payload: [entry(0, 0), entry(2, 1)],
    },
  ])("fails the complete update closed for $name", ({ payload }) => {
    let state = createState();
    state = state.update({ effects: replaceEditorParagraphGutter([entry(0, 0)]) }).state;
    state = state.update({ effects: replaceEditorParagraphGutter(payload) }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);
  });

  it("fails malformed and internally inconsistent runtime payloads closed", () => {
    let state = createState();
    state = state.update({ effects: replaceEditorParagraphGutter([entry(0, 0)]) }).state;
    const inconsistent = {
      sourceStartUtf16: 0,
      button: {
        ...availableButton(0),
        disabled: true,
      },
    };
    state = state.update({
      effects: editorParagraphGutterEffect.of([
        inconsistent as unknown as EditorParagraphGutterEntry,
      ]),
    }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);

    state = state.update({
      effects: editorParagraphGutterEffect.of(
        { unexpected: true } as unknown as readonly EditorParagraphGutterEntry[],
      ),
    }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);
  });

  it("fails a UTF-16 offset that splits a surrogate pair closed", () => {
    let state = createState("甲🙂乙");
    state = state.update({
      effects: replaceEditorParagraphGutter([entry(2, 0)]),
    }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);
  });

  it("clears mapped markers when an edit collapses two paragraph starts", () => {
    let state = createState();
    state = state.update({
      effects: replaceEditorParagraphGutter([entry(0, 0), entry(5, 1)]),
    }).state;
    state = state.update({ changes: { from: 0, to: 5 } }).state;
    expect(readEditorParagraphGutter(state)).toEqual([]);
  });

  it("does not turn ordinary editor selection, text updates, or clearing into playback", () => {
    const onActivate = vi.fn();
    let state = EditorState.create({
      doc: "甲段。",
      extensions: [createEditorParagraphGutterExtension({ onActivate })],
    });
    state = state.update({ effects: replaceEditorParagraphGutter([entry(0, 0)]) }).state;
    state = state.update({ selection: { anchor: 2 } }).state;
    state = state.update({ changes: { from: 2, insert: "新" } }).state;
    state = state.update({ effects: clearEditorParagraphGutter() }).state;

    expect(onActivate).not.toHaveBeenCalled();
    expect(readEditorParagraphGutter(state)).toEqual([]);
  });

  it("rejects an extension without a real activation callback", () => {
    expect(() => createEditorParagraphGutterExtension({
      onActivate: null as unknown as (paragraphOrdinal: number) => void,
    })).toThrow("onActivate must be a function");
  });
});


describe("paragraph gutter button DOM contract", () => {
  it("renders the accessible independent play control and preserves pointer selection", () => {
    const buttons = installFakeDocument();
    const onActivate = vi.fn();
    const handle = createEditorParagraphGutterButton(availableButton(2), onActivate);
    const button = buttons[0];

    expect(handle.element).toBe(button);
    expect(button.type).toBe("button");
    expect(button.className).toBe("anw-chapter-paragraph-gutter-button");
    expect(button.textContent).toBe("▶");
    expect(button.disabled).toBe(false);
    expect(button.title).toBe("播放第 3 段");
    expect(button.dataset).toEqual({
      availability: "available",
      paragraphOrdinal: "2",
    });
    expect(button.attributes.get("aria-label")).toBe("从第 3 段朗读");

    const pointerDown = fakeEvent();
    button.dispatch("pointerdown", pointerDown);
    expect(pointerDown.preventDefault).toHaveBeenCalledOnce();
    expect(pointerDown.stopPropagation).toHaveBeenCalledOnce();
    expect(onActivate).not.toHaveBeenCalled();
  });

  it("activates only click, Enter, and Space with the paragraph ordinal", () => {
    const buttons = installFakeDocument();
    const onActivate = vi.fn();
    createEditorParagraphGutterButton(availableButton(4), onActivate);
    const button = buttons[0];

    button.dispatch("keydown", fakeEvent({ key: "ArrowDown" }));
    button.dispatch("keydown", fakeEvent({ key: "Enter", repeat: true }));
    button.dispatch("keydown", fakeEvent({ key: " ", isComposing: true }));
    expect(onActivate).not.toHaveBeenCalled();

    const click = fakeEvent();
    button.dispatch("click", click);
    const enter = fakeEvent({ key: "Enter" });
    button.dispatch("keydown", enter);
    const space = fakeEvent({ key: " " });
    button.dispatch("keydown", space);

    expect(onActivate).toHaveBeenCalledTimes(3);
    expect(onActivate.mock.calls).toEqual([[4], [4], [4]]);
    expect(click.preventDefault).toHaveBeenCalledOnce();
    expect(enter.preventDefault).toHaveBeenCalledOnce();
    expect(space.preventDefault).toHaveBeenCalledOnce();
  });

  it("keeps disabled controls inert and destroys listeners idempotently", () => {
    const buttons = installFakeDocument();
    const onActivate = vi.fn();
    const handle = createEditorParagraphGutterButton(disabledButton(1), onActivate);
    const button = buttons[0];
    expect(button.disabled).toBe(true);

    button.dispatch("click", fakeEvent());
    button.dispatch("keydown", fakeEvent({ key: "Enter" }));
    expect(onActivate).not.toHaveBeenCalled();

    handle.destroy();
    handle.destroy();
    button.disabled = false;
    button.dispatch("click", fakeEvent());
    button.dispatch("keydown", fakeEvent({ key: " " }));
    button.dispatch("pointerdown", fakeEvent());
    expect(onActivate).not.toHaveBeenCalled();
  });
});
