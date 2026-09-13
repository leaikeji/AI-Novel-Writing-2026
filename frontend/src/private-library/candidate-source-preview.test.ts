import { describe, expect, it, vi } from "vitest";
import type { LibraryCheckHitRecord } from "../types";
import { createCandidateSourcePreview, type CandidateHitLocator } from "./candidate-source-preview";
import { createPrivateLibraryHarness, findAll, findByLabel, textContent } from "./test-harness";

describe("read-only candidate source location", () => {
  const text = "🌊\n" + "墙根的水仍未查清。\n".repeat(100) + "瓷砖微微错开。<script>原始笔记</script>";
  const start = text.indexOf("微微");
  const hit = { hit_id: "physical-shift", start_utf16: start, end_utf16: start + 2,
    matched_text: "微微" } as LibraryCheckHitRecord;

  function setup() {
    const harness = createPrivateLibraryHarness();
    const Preview = createCandidateSourcePreview(harness.React);
    let locate: CandidateHitLocator | null = null;
    const props = { text, bindLocator: (next: CandidateHitLocator | null) => { locate = next; } };
    const render = () => harness.render(Preview, props);
    const tree = render();
    (findByLabel(tree, "本次拟采用正文").props.ref as (node: object | null) => void)({});
    return { render, locate: (item: LibraryCheckHitRecord) => locate?.(item), getLocator: () => locate };
  }

  it("keeps the entire Unicode/plain text and scrolls the exact mark on every explicit location", () => {
    const view = setup();
    for (let repeat = 0; repeat < 2; repeat += 1) {
      view.locate(hit);
      const tree = view.render();
      const region = findByLabel(tree, "本次拟采用正文");
      expect(textContent(region)).toBe(text);
      expect(region.props.contentEditable).toBeUndefined();
      expect(region.props.dangerouslySetInnerHTML).toBeUndefined();
      const mark = findByLabel(tree, "当前命中：微微");
      expect(textContent(mark)).toBe("微微");
      const node = { focus: vi.fn(), scrollIntoView: vi.fn() };
      (mark.props.ref as (node: object | null) => void)(node);
      expect(node.focus).toHaveBeenCalledWith({ preventScroll: true });
      expect(node.scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    }
  });

  it.each([{ start_utf16: -1 }, { end_utf16: text.length + 1 }, { matched_text: "错词" }])(
    "does not mark stale or invalid offsets: %o", (changes) => {
      const view = setup(); view.locate({ ...hit, ...changes });
      const tree = view.render();
      expect(findAll(tree, (node) => node.type === "mark")).toHaveLength(0);
      expect(textContent(findByLabel(tree, "本次拟采用正文"))).toBe(text);
    },
  );

  it("disconnects the location callback when the preview unmounts", () => {
    const view = setup();
    (findByLabel(view.render(), "本次拟采用正文").props.ref as (node: null) => void)(null);
    expect(view.getLocator()).toBeNull();
  });
});
