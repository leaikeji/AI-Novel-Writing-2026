import {
  Facet,
  RangeSet,
  StateEffect,
  StateField,
  type ChangeDesc,
  type EditorState,
  type Extension,
  type Text,
} from "@codemirror/state";
import {
  EditorView,
  GutterMarker,
  ViewPlugin,
  gutter,
  type ViewUpdate,
} from "@codemirror/view";

import type { ParagraphGutterButtonModel } from "./paragraph-gutter";


const GUTTER_CLASS = "anw-narration-paragraph-gutter";
const BUTTON_CLASS = "anw-chapter-paragraph-gutter-button";
const MARKER_CLASS = "anw-narration-paragraph-gutter-marker";
const AVAILABILITIES = new Set<ParagraphGutterButtonModel["availability"]>([
  "available",
  "editor_gutter_unavailable",
  "not_narratable",
  "update_required",
  "stale_scope",
]);


export interface EditorParagraphGutterEntry {
  readonly sourceStartUtf16: number;
  readonly button: ParagraphGutterButtonModel;
}


export type EditorParagraphGutterUpdatePayload =
  | readonly EditorParagraphGutterEntry[]
  | null;


export interface EditorParagraphGutterSnapshotEntry extends EditorParagraphGutterEntry {
  readonly lineNumber: number;
}


export interface CreateEditorParagraphGutterExtensionOptions {
  readonly onActivate: (paragraphOrdinal: number) => void;
}


export interface EditorParagraphGutterButtonHandle {
  readonly element: HTMLButtonElement;
  destroy(): void;
}


interface MaterializedEntry extends EditorParagraphGutterSnapshotEntry {
  readonly marker: ParagraphButtonMarker;
}


interface ParagraphGutterFieldState {
  readonly entries: readonly MaterializedEntry[];
  readonly markers: RangeSet<GutterMarker>;
}


type ParagraphActivationHandler = (paragraphOrdinal: number) => void;


const EMPTY_FIELD_STATE: ParagraphGutterFieldState = Object.freeze({
  entries: Object.freeze([]),
  markers: RangeSet.empty,
});


function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === "object" && value !== null;
}


function normalizeButton(value: unknown): ParagraphGutterButtonModel | null {
  if (!isRecord(value)) return null;
  try {
    const paragraphOrdinal = value.paragraphOrdinal;
    const sourceBlockKey = value.sourceBlockKey;
    const targetSegmentId = value.targetSegmentId;
    const availability = value.availability;
    const disabled = value.disabled;
    const ariaLabel = value.ariaLabel;
    const title = value.title;
    if (
      !Number.isSafeInteger(paragraphOrdinal)
      || (paragraphOrdinal as number) < 0
      || typeof sourceBlockKey !== "string"
      || !sourceBlockKey.trim()
      || !(
        targetSegmentId === null
        || (typeof targetSegmentId === "string" && Boolean(targetSegmentId.trim()))
      )
      || typeof availability !== "string"
      || !AVAILABILITIES.has(availability as ParagraphGutterButtonModel["availability"])
      || typeof disabled !== "boolean"
      || typeof ariaLabel !== "string"
      || !ariaLabel.trim()
      || typeof title !== "string"
      || !title.trim()
    ) return null;

    const available = availability === "available";
    if (available !== (!disabled && targetSegmentId !== null)) return null;
    if (!available && (!disabled || targetSegmentId !== null)) return null;

    return Object.freeze({
      paragraphOrdinal: paragraphOrdinal as number,
      sourceBlockKey,
      targetSegmentId: targetSegmentId as string | null,
      availability: availability as ParagraphGutterButtonModel["availability"],
      disabled,
      ariaLabel,
      title,
    });
  } catch {
    return null;
  }
}


function normalizePayloadShape(
  value: unknown,
): EditorParagraphGutterUpdatePayload {
  if (value === null) return null;
  if (!Array.isArray(value)) return null;
  const normalized: EditorParagraphGutterEntry[] = [];
  try {
    for (const candidate of value) {
      if (!isRecord(candidate)) return null;
      const sourceStartUtf16 = candidate.sourceStartUtf16;
      const button = normalizeButton(candidate.button);
      if (
        !Number.isSafeInteger(sourceStartUtf16)
        || (sourceStartUtf16 as number) < 0
        || !button
      ) return null;
      normalized.push(Object.freeze({
        sourceStartUtf16: sourceStartUtf16 as number,
        button,
      }));
    }
  } catch {
    return null;
  }
  return Object.freeze(normalized);
}


function mapPayload(
  value: EditorParagraphGutterUpdatePayload,
  mapping: ChangeDesc,
): EditorParagraphGutterUpdatePayload {
  const normalized = normalizePayloadShape(value);
  if (!normalized) return null;
  try {
    return Object.freeze(normalized.map((entry) => Object.freeze({
      sourceStartUtf16: mapping.mapPos(entry.sourceStartUtf16, 1),
      button: entry.button,
    })));
  } catch {
    return null;
  }
}


export const editorParagraphGutterEffect = StateEffect.define<
  EditorParagraphGutterUpdatePayload
>({
  map: mapPayload,
});


export function replaceEditorParagraphGutter(
  entries: readonly EditorParagraphGutterEntry[],
): StateEffect<EditorParagraphGutterUpdatePayload> {
  return editorParagraphGutterEffect.of(normalizePayloadShape(entries));
}


export function clearEditorParagraphGutter(): StateEffect<EditorParagraphGutterUpdatePayload> {
  return editorParagraphGutterEffect.of(null);
}


function buttonModelsEqual(
  left: ParagraphGutterButtonModel,
  right: ParagraphGutterButtonModel,
): boolean {
  return left.paragraphOrdinal === right.paragraphOrdinal
    && left.sourceBlockKey === right.sourceBlockKey
    && left.targetSegmentId === right.targetSegmentId
    && left.availability === right.availability
    && left.disabled === right.disabled
    && left.ariaLabel === right.ariaLabel
    && left.title === right.title;
}


function isActivationKey(event: KeyboardEvent): boolean {
  return !event.isComposing
    && !event.repeat
    && (event.key === "Enter" || event.key === " ");
}


export function createEditorParagraphGutterButton(
  model: ParagraphGutterButtonModel,
  onActivate: ParagraphActivationHandler,
): EditorParagraphGutterButtonHandle {
  const button = document.createElement("button");
  button.type = "button";
  button.className = BUTTON_CLASS;
  button.textContent = "▶";
  button.disabled = model.disabled;
  button.title = model.title;
  button.dataset.paragraphOrdinal = String(model.paragraphOrdinal);
  button.dataset.availability = model.availability;
  button.setAttribute("aria-label", model.ariaLabel);

  let destroyed = false;
  const activate = () => {
    if (destroyed || button.disabled) return;
    onActivate(model.paragraphOrdinal);
  };
  const handlePointerDown = (event: PointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };
  const handleClick = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    activate();
  };
  const handleKeyDown = (event: KeyboardEvent) => {
    if (!isActivationKey(event)) return;
    event.preventDefault();
    event.stopPropagation();
    activate();
  };

  button.addEventListener("pointerdown", handlePointerDown);
  button.addEventListener("click", handleClick);
  button.addEventListener("keydown", handleKeyDown);

  return Object.freeze({
    element: button,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      button.removeEventListener("pointerdown", handlePointerDown);
      button.removeEventListener("click", handleClick);
      button.removeEventListener("keydown", handleKeyDown);
    },
  });
}


const buttonHandleByDom = new WeakMap<Node, EditorParagraphGutterButtonHandle>();


const paragraphActivationHandler = Facet.define<
  ParagraphActivationHandler,
  ParagraphActivationHandler | null
>({
  combine(values) {
    return values.length === 1 ? values[0] : null;
  },
});


class ParagraphButtonMarker extends GutterMarker {
  readonly elementClass = MARKER_CLASS;

  constructor(readonly model: ParagraphGutterButtonModel) {
    super();
  }

  eq(other: GutterMarker): boolean {
    return other instanceof ParagraphButtonMarker
      && buttonModelsEqual(this.model, other.model);
  }

  toDOM(view: EditorView): Node {
    const activationHandler = view.state.facet(paragraphActivationHandler);
    const renderModel = activationHandler
      ? this.model
      : Object.freeze({
          ...this.model,
          targetSegmentId: null,
          availability: "stale_scope" as const,
          disabled: true,
          title: "朗读操作已失效，请重新加载当前章节。",
        });
    const handle = createEditorParagraphGutterButton(
      renderModel,
      activationHandler ?? (() => undefined),
    );
    buttonHandleByDom.set(handle.element, handle);
    return handle.element;
  }

  destroy(dom: Node): void {
    const handle = buttonHandleByDom.get(dom);
    handle?.destroy();
    buttonHandleByDom.delete(dom);
  }
}


function materializePayload(
  document: Text,
  value: unknown,
): ParagraphGutterFieldState {
  const normalized = normalizePayloadShape(value);
  if (!normalized || normalized.length === 0) return EMPTY_FIELD_STATE;

  const documentText = document.toString();
  const ordinals = new Set<number>();
  const sourceBlockKeys = new Set<string>();
  const sourceStarts = new Set<number>();
  const lineNumbers = new Set<number>();
  const materialized: MaterializedEntry[] = [];
  try {
    for (const entry of normalized) {
      if (entry.sourceStartUtf16 > document.length) return EMPTY_FIELD_STATE;
      if (
        entry.sourceStartUtf16 > 0
        && entry.sourceStartUtf16 < documentText.length
        && documentText.charCodeAt(entry.sourceStartUtf16 - 1) >= 0xd800
        && documentText.charCodeAt(entry.sourceStartUtf16 - 1) <= 0xdbff
        && documentText.charCodeAt(entry.sourceStartUtf16) >= 0xdc00
        && documentText.charCodeAt(entry.sourceStartUtf16) <= 0xdfff
      ) return EMPTY_FIELD_STATE;
      const { paragraphOrdinal, sourceBlockKey } = entry.button;
      const lineNumber = document.lineAt(entry.sourceStartUtf16).number;
      if (
        ordinals.has(paragraphOrdinal)
        || sourceBlockKeys.has(sourceBlockKey)
        || sourceStarts.has(entry.sourceStartUtf16)
        || lineNumbers.has(lineNumber)
      ) return EMPTY_FIELD_STATE;
      ordinals.add(paragraphOrdinal);
      sourceBlockKeys.add(sourceBlockKey);
      sourceStarts.add(entry.sourceStartUtf16);
      lineNumbers.add(lineNumber);
      materialized.push(Object.freeze({
        ...entry,
        lineNumber,
        marker: new ParagraphButtonMarker(entry.button),
      }));
    }
  } catch {
    return EMPTY_FIELD_STATE;
  }

  materialized.sort((left, right) => (
    left.sourceStartUtf16 - right.sourceStartUtf16
    || left.button.paragraphOrdinal - right.button.paragraphOrdinal
  ));
  const frozenEntries = Object.freeze(materialized);
  return Object.freeze({
    entries: frozenEntries,
    markers: RangeSet.of(
      frozenEntries.map((entry) => entry.marker.range(entry.sourceStartUtf16)),
      true,
    ),
  });
}


function mapCurrentEntries(
  entries: readonly MaterializedEntry[],
  mapping: ChangeDesc,
): readonly EditorParagraphGutterEntry[] {
  try {
    return Object.freeze(entries.map((entry) => Object.freeze({
      sourceStartUtf16: mapping.mapPos(entry.sourceStartUtf16, 1),
      button: entry.button,
    })));
  } catch {
    return Object.freeze([]);
  }
}


const paragraphGutterField = StateField.define<ParagraphGutterFieldState>({
  create: () => EMPTY_FIELD_STATE,
  update(current, transaction) {
    let next = transaction.docChanged
      ? materializePayload(
          transaction.state.doc,
          mapCurrentEntries(current.entries, transaction.changes),
        )
      : current;
    for (const effect of transaction.effects) {
      if (!effect.is(editorParagraphGutterEffect)) continue;
      next = materializePayload(transaction.state.doc, effect.value);
    }
    return next;
  },
});


class AccessibleParagraphGutterPlugin {
  private readonly previousAriaHidden = new Map<HTMLElement, string | null>();

  constructor(view: EditorView) {
    this.sync(view);
  }

  update(update: ViewUpdate): void {
    this.sync(update.view);
  }

  destroy(): void {
    for (const [element, previousValue] of this.previousAriaHidden) {
      if (previousValue === null) element.removeAttribute("aria-hidden");
      else element.setAttribute("aria-hidden", previousValue);
    }
    this.previousAriaHidden.clear();
  }

  private sync(view: EditorView): void {
    const active = new Set<HTMLElement>();
    for (const gutterElement of view.scrollDOM.querySelectorAll<HTMLElement>(".cm-gutters")) {
      if (!gutterElement.querySelector(`.${GUTTER_CLASS}`)) continue;
      active.add(gutterElement);
      if (!this.previousAriaHidden.has(gutterElement)) {
        this.previousAriaHidden.set(gutterElement, gutterElement.getAttribute("aria-hidden"));
      }
      gutterElement.removeAttribute("aria-hidden");
    }
    for (const [element, previousValue] of this.previousAriaHidden) {
      if (active.has(element)) continue;
      if (previousValue === null) element.removeAttribute("aria-hidden");
      else element.setAttribute("aria-hidden", previousValue);
      this.previousAriaHidden.delete(element);
    }
  }
}


const accessibleParagraphGutter = ViewPlugin.fromClass(AccessibleParagraphGutterPlugin);


export function createEditorParagraphGutterExtension(
  options: CreateEditorParagraphGutterExtensionOptions,
): Extension {
  if (typeof options.onActivate !== "function") {
    throw new TypeError("onActivate must be a function");
  }
  return [
    paragraphGutterField,
    paragraphActivationHandler.of(options.onActivate),
    gutter({
      class: GUTTER_CLASS,
      markers: (view) => view.state.field(paragraphGutterField).markers,
    }),
    accessibleParagraphGutter,
  ];
}


export function readEditorParagraphGutter(
  state: EditorState,
): readonly EditorParagraphGutterSnapshotEntry[] {
  const field = state.field(paragraphGutterField, false);
  if (!field) return Object.freeze([]);
  return Object.freeze(field.entries.map((entry) => Object.freeze({
    sourceStartUtf16: entry.sourceStartUtf16,
    lineNumber: entry.lineNumber,
    button: entry.button,
  })));
}
