import { undo, redo } from "@codemirror/commands";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PrototypeNarrationEditorBridge,
  TEXTAREA_SAFE_FALLBACK,
  codeMirrorNarrationEffect,
  codeMirrorNarrationRanges,
  createCodeMirrorPrototypeExtensions,
  createCodeMirrorPrototypeState,
  mountCodeMirrorPrototype,
  type NarrationEditorSelection,
  type NarrationSourceSegment,
} from "./editor-spike";


const EDITION_HASH = "edition-sha256";
const SAMPLE = "题记\n第一段。\n第二段“你好！”\n第三段结束。";


function segment(
  segmentId: string,
  sourceBlockKey: string,
  sourceText: string,
  text = SAMPLE,
): NarrationSourceSegment {
  const startUtf16 = text.indexOf(sourceText);
  if (startUtf16 < 0) throw new Error(`fixture segment not found: ${sourceText}`);
  return {
    segmentId,
    sourceBlockKey,
    sourceText,
    sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
  };
}


function sampleSegments(): NarrationSourceSegment[] {
  return [
    segment("seg-1", "block-1", "第一段。"),
    segment("seg-2", "block-2", "第二段“你好！”"),
    segment("seg-3", "block-3", "第三段结束。"),
  ];
}


function bridge(
  selection?: NarrationEditorSelection,
): PrototypeNarrationEditorBridge {
  return new PrototypeNarrationEditorBridge({
    text: SAMPLE,
    currentContentHash: EDITION_HASH,
    editionContentHash: EDITION_HASH,
    segments: sampleSegments(),
    selection,
  });
}


function mappedRange(target: PrototypeNarrationEditorBridge, segmentId: string) {
  const mapping = target.mappingFor(segmentId);
  if (mapping?.state !== "mapped") throw new Error(`${segmentId} is not mapped`);
  return mapping.currentRange;
}


function invalidReason(target: PrototypeNarrationEditorBridge, segmentId: string) {
  const mapping = target.mappingFor(segmentId);
  if (mapping?.state !== "invalidated") throw new Error(`${segmentId} is not invalidated`);
  return mapping.reason;
}


afterEach(() => {
  document.body.replaceChildren();
});


describe("NarrationEditorBridge UTF-16 contract", () => {
  it("uses JavaScript UTF-16 offsets for emoji and combining characters", () => {
    const text = "甲🙂e\u0301乙。";
    const sourceText = "🙂e\u0301";
    const startUtf16 = text.indexOf(sourceText);
    const target = new PrototypeNarrationEditorBridge({
      text,
      currentContentHash: EDITION_HASH,
      editionContentHash: EDITION_HASH,
      segments: [{
        segmentId: "unicode",
        sourceBlockKey: "unicode-block",
        sourceText,
        sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
      }],
    });

    expect(sourceText.length).toBe(4);
    expect(mappedRange(target, "unicode")).toEqual({ startUtf16: 1, endUtf16: 5 });
    expect(target.resolvePlaybackTarget({
      sourceBlockKey: "unicode-block",
      range: { startUtf16: 1, endUtf16: 5 },
    })).toBe("unicode");
  });

  it("fails closed when a source range splits an emoji surrogate pair", () => {
    const text = "甲🙂乙";
    expect(() => new PrototypeNarrationEditorBridge({
      text,
      currentContentHash: EDITION_HASH,
      editionContentHash: EDITION_HASH,
      segments: [{
        segmentId: "broken",
        sourceBlockKey: "block",
        sourceText: text.slice(2, 3),
        sourceRange: { startUtf16: 2, endUtf16: 3 },
      }],
    })).toThrow("must not split a UTF-16 surrogate pair");
  });
});


describe("transaction mapping and conservative invalidation", () => {
  it("maps every untouched range after a plain edit before the narration blocks", () => {
    const target = bridge();
    const before = mappedRange(target, "seg-1");
    const report = target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "旧" }],
    });

    expect(report.invalidated).toEqual({});
    expect(mappedRange(target, "seg-1")).toEqual({
      startUtf16: before.startUtf16 + 1,
      endUtf16: before.endUtf16 + 1,
    });
    expect(report.text).toBe(`旧${SAMPLE}`);
  });

  it("invalidates a segment for an edit inside it without discarding untouched blocks", () => {
    const target = bridge();
    const range = mappedRange(target, "seg-2");
    const targetOffset = range.startUtf16 + 2;
    const report = target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: targetOffset, endUtf16: targetOffset, insertedText: "新" }],
    });

    expect(report.invalidated).toEqual({ "seg-2": "transaction_intersection" });
    expect(invalidReason(target, "seg-2")).toBe("transaction_intersection");
    expect(target.mappingFor("seg-1")?.state).toBe("mapped");
    expect(target.mappingFor("seg-3")?.state).toBe("mapped");
  });

  it("keeps an earlier segment mapped when a plain edit occurs after it", () => {
    const target = bridge();
    const secondBefore = mappedRange(target, "seg-2");
    const third = mappedRange(target, "seg-3");
    target.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: third.startUtf16 + 2,
        endUtf16: third.startUtf16 + 2,
        insertedText: "新",
      }],
    });

    expect(mappedRange(target, "seg-2")).toEqual(secondBefore);
    expect(invalidReason(target, "seg-3")).toBe("transaction_intersection");
  });

  it.each([
    ["at the segment start", "startUtf16"],
    ["at the segment end", "endUtf16"],
  ] as const)("invalidates the touched block and adjacent blocks for an edit %s", (_name, boundary) => {
    const target = bridge();
    const range = mappedRange(target, "seg-2");
    const offset = range[boundary];
    target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: offset, endUtf16: offset, insertedText: "边" }],
    });

    expect(invalidReason(target, "seg-1")).toBe("boundary_adjacent");
    expect(invalidReason(target, "seg-2")).toBe("transaction_intersection");
    expect(invalidReason(target, "seg-3")).toBe("boundary_adjacent");
  });

  it("invalidates adjacent source blocks for paragraph splitting", () => {
    const target = bridge();
    const range = mappedRange(target, "seg-2");
    target.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: range.startUtf16 + 3,
        endUtf16: range.startUtf16 + 3,
        insertedText: "\n",
      }],
    });

    expect(invalidReason(target, "seg-1")).toBe("boundary_adjacent");
    expect(invalidReason(target, "seg-2")).toBe("transaction_intersection");
    expect(invalidReason(target, "seg-3")).toBe("boundary_adjacent");
  });

  it("invalidates both sides and their neighbour for paragraph merging", () => {
    const target = bridge();
    const first = mappedRange(target, "seg-1");
    target.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: first.endUtf16,
        endUtf16: first.endUtf16 + 1,
        insertedText: "",
      }],
    });

    expect(target.mappingFor("seg-1")?.state).toBe("invalidated");
    expect(target.mappingFor("seg-2")?.state).toBe("invalidated");
    expect(target.mappingFor("seg-3")?.state).toBe("invalidated");
  });

  it("invalidates adjacent blocks when quote or punctuation boundaries change", () => {
    const target = bridge();
    const range = mappedRange(target, "seg-2");
    target.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: range.startUtf16 + 3,
        endUtf16: range.startUtf16 + 3,
        insertedText: "！",
      }],
    });

    expect(target.mappingFor("seg-1")?.state).toBe("invalidated");
    expect(target.mappingFor("seg-2")?.state).toBe("invalidated");
    expect(target.mappingFor("seg-3")?.state).toBe("invalidated");
  });

  it("does not guess a mapping back into existence after an undo transaction", () => {
    const target = bridge();
    const second = mappedRange(target, "seg-2");
    const insertedAt = second.startUtf16 + 2;
    target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: insertedAt, endUtf16: insertedAt, insertedText: "新" }],
    });
    target.applyTransaction({
      origin: "undo",
      changes: [{ startUtf16: insertedAt, endUtf16: insertedAt + 1, insertedText: "" }],
    });

    expect(target.readSnapshot().text).toBe(SAMPLE);
    expect(invalidReason(target, "seg-2")).toBe("transaction_intersection");
    expect(target.readSnapshot().exactEditionText).toBe(false);
  });

  it("requires source text and local anchors to remain valid after mapping", () => {
    const text = "xx第一段。";
    const startUtf16 = text.indexOf("第一段。");
    const target = new PrototypeNarrationEditorBridge({
      text,
      currentContentHash: EDITION_HASH,
      editionContentHash: EDITION_HASH,
      segments: [{
        segmentId: "anchored",
        sourceBlockKey: "block",
        sourceText: "第一段。",
        sourceRange: { startUtf16, endUtf16: text.length },
        prefixAnchor: "xx",
      }],
    });
    target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 1, insertedText: "y" }],
    });

    expect(invalidReason(target, "anchored")).toBe("anchor_mismatch");
  });

  it("maps a 1,500-block long chapter without weakening correctness checks", () => {
    const paragraphs = Array.from(
      { length: 1_500 },
      (_, index) => `第${index + 1}段🙂内容。`,
    );
    const text = `题记\n${paragraphs.join("\n")}`;
    let cursor = "题记\n".length;
    const segments = paragraphs.map((sourceText, index): NarrationSourceSegment => {
      const startUtf16 = cursor;
      cursor += sourceText.length + (index + 1 < paragraphs.length ? 1 : 0);
      return {
        segmentId: `long-${index}`,
        sourceBlockKey: `long-block-${index}`,
        sourceText,
        sourceRange: { startUtf16, endUtf16: startUtf16 + sourceText.length },
      };
    });
    const target = new PrototypeNarrationEditorBridge({
      text,
      currentContentHash: EDITION_HASH,
      editionContentHash: EDITION_HASH,
      segments,
    });

    const startedAt = performance.now();
    const report = target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "旧" }],
    });
    const elapsedMs = performance.now() - startedAt;

    expect(report.mappedSegmentIds).toHaveLength(1_500);
    expect(mappedRange(target, "long-1499").startUtf16).toBe(
      segments[1_499].sourceRange.startUtf16 + 1,
    );
    expect(elapsedMs).toBeLessThan(2_000);
  });
});


describe("follow, selection, composition and playback intent", () => {
  it("does not move selection or follow another segment during composition", () => {
    const selection = { startUtf16: 6, endUtf16: 8, direction: "forward" as const };
    const target = bridge(selection);
    expect(target.markCurrentSegment("seg-1")).toEqual({ applied: true, segmentId: "seg-1" });
    target.beginComposition();

    expect(target.markCurrentSegment("seg-2")).toEqual({ applied: false, reason: "composition" });
    expect(target.scrollCurrentSegmentIntoView()).toEqual({ applied: false, reason: "composition" });
    const second = mappedRange(target, "seg-2");
    target.applyTransaction({
      origin: "composition",
      changes: [{
        startUtf16: second.startUtf16 + 2,
        endUtf16: second.startUtf16 + 2,
        insertedText: "啊",
      }],
      selectionAfter: { startUtf16: second.startUtf16 + 3, endUtf16: second.startUtf16 + 3, direction: "none" },
    });

    expect(target.readSnapshot()).toMatchObject({
      composing: true,
      currentSegmentId: "seg-1",
      selection: { startUtf16: second.startUtf16 + 3, endUtf16: second.startUtf16 + 3 },
    });
    target.endComposition();
    expect(target.scrollCurrentSegmentIntoView()).toEqual({ applied: true, segmentId: "seg-1" });
  });

  it("pauses auto-follow after manual scrolling and resumes only explicitly", () => {
    const target = bridge();
    target.markCurrentSegment("seg-2");
    target.noteManualScroll();
    expect(target.scrollCurrentSegmentIntoView()).toEqual({ applied: false, reason: "manual_scroll" });
    expect(target.lastRequestedScrollSegment()).toBeNull();

    target.resumeAutoFollow();
    expect(target.scrollCurrentSegmentIntoView()).toEqual({ applied: true, segmentId: "seg-2" });
    expect(target.lastRequestedScrollSegment()).toBe("seg-2");
  });

  it("keeps ordinary editor clicks as caret-only and emits only explicit seek intents", () => {
    const target = bridge();
    const listener = vi.fn();
    target.registerPlaybackIntent(listener);

    expect(target.requestPlayback("editor-click", { segmentId: "seg-2" })).toEqual({
      accepted: false,
      reason: "editor_click_moves_caret_only",
    });
    expect(listener).not.toHaveBeenCalled();

    expect(target.requestPlayback("gutter", { sourceBlockKey: "block-2" })).toMatchObject({
      accepted: true,
      intent: { source: "gutter", segmentId: "seg-2" },
    });
    const third = mappedRange(target, "seg-3");
    expect(target.requestPlayback("command", { positionUtf16: third.startUtf16 + 1 })).toMatchObject({
      accepted: true,
      intent: { source: "command", segmentId: "seg-3" },
    });
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("allows an explicitly labelled immutable old-edition row after current mapping is lost", () => {
    const target = bridge();
    const second = mappedRange(target, "seg-2");
    target.applyTransaction({
      origin: "input",
      changes: [{
        startUtf16: second.startUtf16 + 1,
        endUtf16: second.startUtf16 + 1,
        insertedText: "改",
      }],
    });

    expect(target.requestPlayback("gutter", { sourceBlockKey: "block-2" })).toEqual({
      accepted: false,
      reason: "unmapped_target",
    });
    expect(target.requestPlayback("readonly-segment", { segmentId: "seg-2" })).toMatchObject({
      accepted: true,
      intent: { source: "readonly-segment", segmentId: "seg-2" },
    });
  });
});


describe("page reload safety and textarea degradation", () => {
  it("does not guess an active-session mapping after a diverged page reload", () => {
    const target = bridge();
    target.applyTransaction({
      origin: "input",
      changes: [{ startUtf16: 0, endUtf16: 0, insertedText: "旧" }],
    });
    expect(target.mappingFor("seg-1")?.state).toBe("mapped");

    target.resetAfterPageReload({ currentText: `旧${SAMPLE}`, currentContentHash: "working-copy-sha256" });
    expect(target.readSnapshot().exactEditionText).toBe(false);
    expect(invalidReason(target, "seg-1")).toBe("reload_diverged");
    expect(invalidReason(target, "seg-2")).toBe("reload_diverged");
    expect(target.resolvePlaybackTarget({ sourceBlockKey: "block-1" })).toBeNull();
  });

  it("can rebind immutable source ranges only after the exact edition hash returns", () => {
    const target = bridge();
    target.resetAfterPageReload({ currentText: `旧${SAMPLE}`, currentContentHash: "working-copy-sha256" });
    target.resetAfterPageReload({ currentText: SAMPLE, currentContentHash: EDITION_HASH });

    expect(target.readSnapshot().exactEditionText).toBe(true);
    expect(target.mappingFor("seg-1")?.state).toBe("mapped");
  });

  it("freezes textarea as a non-overlay fallback", () => {
    expect(TEXTAREA_SAFE_FALLBACK).toEqual({
      editableDecoration: false,
      editableGutterSeek: false,
      ordinaryClickSeeks: false,
      allowedSeekSurfaces: ["readonly-segment", "paragraph-list", "explicit-command"],
      divergedCopyPresentation: ["player-subtitle", "immutable-edition-drawer"],
      requiredRecoveryAction: "update-narration",
    });
  });
});


describe("CodeMirror 6 public API prototype", () => {
  it("maps a public Decoration through a UTF-16 transaction without moving selection", () => {
    let state = createCodeMirrorPrototypeState("甲🙂乙", {
      startUtf16: 3,
      endUtf16: 4,
      direction: "forward",
    });
    const selectionBefore = state.selection.main;
    state = state.update({ effects: codeMirrorNarrationEffect({ startUtf16: 1, endUtf16: 3 }) }).state;
    expect(codeMirrorNarrationRanges(state)).toEqual([{ startUtf16: 1, endUtf16: 3 }]);
    expect(state.selection.main).toEqual(selectionBefore);

    state = state.update({ changes: { from: 0, insert: "序" } }).state;
    expect(state.doc.toString()).toBe("序甲🙂乙");
    expect(codeMirrorNarrationRanges(state)).toEqual([{ startUtf16: 2, endUtf16: 4 }]);

    state = state.update({ effects: codeMirrorNarrationEffect(null) }).state;
    expect(codeMirrorNarrationRanges(state)).toEqual([]);
  });

  it("keeps public history undo/redo and gutter extensions runnable in jsdom", () => {
    const parent = document.createElement("div");
    document.body.append(parent);
    const onDocumentChange = vi.fn();
    const state = EditorState.create({
      doc: "第一段。\n第二段。",
      extensions: createCodeMirrorPrototypeExtensions(undefined, onDocumentChange),
    });
    const view = new EditorView({ state, parent });
    try {
      view.dispatch({ changes: { from: 0, to: 3, insert: "首段" }, userEvent: "input.type" });
      expect(view.state.doc.toString()).toBe("首段。\n第二段。");
      expect(onDocumentChange).toHaveBeenLastCalledWith({
        text: "首段。\n第二段。",
        composing: false,
        transactionCount: 1,
      });
      expect(undo(view)).toBe(true);
      expect(view.state.doc.toString()).toBe("第一段。\n第二段。");
      expect(redo(view)).toBe(true);
      expect(view.state.doc.toString()).toBe("首段。\n第二段。");
      expect(onDocumentChange).toHaveBeenCalledTimes(3);
      expect(parent.querySelector(".cm-lineNumbers")).not.toBeNull();
      expect(parent.querySelectorAll(".cm-gutterElement").length).toBeGreaterThan(0);
    } finally {
      view.destroy();
    }
  });

  it("mounts one self-contained browser handle with highlight and history controls", () => {
    const parent = document.createElement("div");
    document.body.append(parent);
    const onDocumentChange = vi.fn();
    const handle = mountCodeMirrorPrototype(parent, "甲🙂乙", { onDocumentChange });
    try {
      handle.highlight({ startUtf16: 1, endUtf16: 3 });
      expect(codeMirrorNarrationRanges(handle.view.state)).toEqual([{ startUtf16: 1, endUtf16: 3 }]);
      handle.view.dispatch({ changes: { from: 3, to: 4, insert: "丁" }, userEvent: "input.type" });
      expect(handle.view.state.doc.toString()).toBe("甲🙂丁");
      expect(handle.undo()).toBe(true);
      expect(handle.view.state.doc.toString()).toBe("甲🙂乙");
      expect(handle.redo()).toBe(true);
      expect(handle.view.state.doc.toString()).toBe("甲🙂丁");
      expect(onDocumentChange).toHaveBeenCalledTimes(3);
    } finally {
      handle.destroy();
    }
  });
});


describe("Monaco public API risk probe", () => {
  it("runs model UTF-16 ranges, decoration, edit and undo without claiming worker/CSP support", async () => {
    const monaco = await import("monaco-editor/editor/editor.api.js");
    const model = monaco.editor.createModel("甲🙂乙", "markdown");
    try {
      expect(model.getPositionAt(3)).toEqual({ lineNumber: 1, column: 4 });
      const decorationIds = model.deltaDecorations([], [{
        range: new monaco.Range(1, 2, 1, 4),
        options: { inlineClassName: "anw-narration-current-segment", glyphMarginClassName: "anw-narration-gutter" },
      }]);
      expect(decorationIds).toHaveLength(1);

      model.pushStackElement();
      model.pushEditOperations([], [{
        range: new monaco.Range(1, 4, 1, 5),
        text: "丁",
      }], () => null);
      expect(model.getValue()).toBe("甲🙂丁");
      await model.undo();
      expect(model.getValue()).toBe("甲🙂乙");
    } finally {
      model.dispose();
    }
  });
});


describe("single Blob-compatible module prototype", () => {
  it("bundles the bridge and CodeMirror public API into one import-free ES module", async () => {
    const prototypeRoot = process.cwd();
    const entry = resolve(prototypeRoot, "editor/editor-spike.ts");
    const script = String.raw`
      import { build } from "vite";
      import { JSDOM } from "jsdom";
      const entry = process.argv[1];
      const result = await build({
        configFile: false,
        logLevel: "silent",
        build: {
          write: false,
          minify: false,
          target: "esnext",
          lib: { entry, formats: ["es"], fileName: () => "editor-spike.js" },
          rollupOptions: { output: { inlineDynamicImports: true } },
        },
      });
      const outputs = Array.isArray(result) ? result : [result];
      const chunks = outputs.flatMap((output) => output.output).filter((item) => item.type === "chunk");
      if (chunks.length !== 1) throw new Error("expected exactly one ES chunk");
      const chunk = chunks[0];
      if (chunk.imports.length || chunk.dynamicImports.length) throw new Error("bundle is not import-free");
      if (!chunk.code.includes("PrototypeNarrationEditorBridge")) throw new Error("bridge export missing");
      if (chunk.code.includes("module.exports")) throw new Error("CommonJS output is not allowed");

      const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://127.0.0.1/" });
      for (const key of ["window", "document", "navigator", "Node", "HTMLElement", "MutationObserver", "DOMRect"]) {
        Object.defineProperty(globalThis, key, { configurable: true, value: dom.window[key] });
      }
      globalThis.requestAnimationFrame = (callback) => setTimeout(() => callback(Date.now()), 0);
      globalThis.cancelAnimationFrame = (handle) => clearTimeout(handle);
      const moduleUrl = "data:text/javascript;base64," + Buffer.from(chunk.code).toString("base64");
      const loaded = await import(moduleUrl);
      if (typeof loaded.PrototypeNarrationEditorBridge !== "function") throw new Error("bundle did not execute");
      dom.window.close();
      process.stdout.write(JSON.stringify({
        chunkCount: chunks.length,
        imports: chunk.imports.length,
        dynamicImports: chunk.dynamicImports.length,
        rawBytes: Buffer.byteLength(chunk.code),
        executed: true,
      }));
    `;
    const output = execFileSync(process.execPath, ["--input-type=module", "-e", script, entry], {
      cwd: prototypeRoot,
      encoding: "utf8",
      env: process.env,
    });
    const result = JSON.parse(output) as {
      chunkCount: number;
      imports: number;
      dynamicImports: number;
      rawBytes: number;
      executed: boolean;
    };

    expect(result).toMatchObject({
      chunkCount: 1,
      imports: 0,
      dynamicImports: 0,
      executed: true,
    });
    expect(result.rawBytes).toBeGreaterThan(0);
  });
});
