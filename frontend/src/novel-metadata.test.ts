import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest } from "./api";
import { metadataDraft, metadataValidation, NovelMetadataEditor, saveNovelMetadata } from "./novel-metadata";
import type { NovelMetadataRecord } from "./types";

vi.mock("./api", async (original) => ({ ...await original<typeof import("./api")>(), apiRequest: vi.fn() }));
type Node = { type: unknown; props: Record<string, unknown>; children: unknown[] };
const novel = { id: "book", title: "危楼余火", author_name: "南窗", version: 3, cover_mode: "text" } as NovelMetadataRecord;
let states: unknown[], refs: Array<{ current: unknown }>, cursor: number, refCursor: number;
let tree: Node;
const changed = vi.fn();
function nodes(node: unknown): Node[] {
  if (!node || typeof node !== "object" || !("children" in node)) return [];
  const item = node as Node;
  return [item, ...item.children.flatMap(nodes)];
}
function render() { cursor = 0; refCursor = 0; tree = NovelMetadataEditor({ novel, onChanged: changed }) as Node; }
function button(label: string): Node { return nodes(tree).find(n => n.type === "Button" && n.children.includes(label))!; }
function modal(): Node { return nodes(tree).find(n => n.type === "Modal")!; }
function field(id: string): Node { return nodes(tree).find(n => n.props.id === id)!; }
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); render(); }

beforeEach(() => {
  vi.clearAllMocks(); states = []; refs = []; cursor = 0; refCursor = 0;
  vi.stubGlobal("window", { QwenPaw: { host: {
    React: {
      Fragment: "Fragment",
      createElement: (type: unknown, props: Record<string, unknown> | null, ...children: unknown[]) => ({ type, props: props || {}, children }),
      useState: (initial: unknown) => { const i = cursor++; if (!(i in states)) states[i] = initial; return [states[i], (next: unknown) => { states[i] = next; }]; },
      useRef: (initial: unknown) => { const i = refCursor++; return refs[i] ||= { current: initial }; },
      useEffect: () => undefined,
    },
    antd: { Button: "Button", Modal: "Modal", Input: "Input", Alert: "Alert" },
  } } });
  render(); (button("作品资料").props.onClick as () => void)(); render();
});

describe("book metadata", () => {
  it("validates blank and oversized fields", () => {
    expect(metadataValidation(metadataDraft(novel))).toBeNull();
    for (const title of ["  ", "字".repeat(241)]) expect(metadataValidation({ ...metadataDraft(novel), title })).not.toBeNull();
    for (const author_name of [" ", "字".repeat(121)]) expect(metadataValidation({ ...metadataDraft(novel), author_name })).not.toBeNull();
  });
  it("sends only the version and trimmed identity fields", async () => {
    vi.mocked(apiRequest).mockResolvedValue(novel);
    await saveNovelMetadata("book", { title: " 危楼余火 ", author_name: " 南窗 ", expected_version: 3 });
    expect(apiRequest).toHaveBeenCalledWith("/novels/book/metadata", { method: "PUT", body: JSON.stringify(metadataDraft(novel)) });
  });
  it("saves and refreshes the parent used by the title and text cover", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ ...novel, version: 4 });
    (modal().props.onOk as () => void)(); await settle();
    expect(changed).toHaveBeenCalledWith({ ...novel, version: 4 });
    expect(modal().props.open).toBe(false);
  });
  it("preserves edited input after network failure", async () => {
    (field("anw-novel-title").props.onChange as (e: { target: { value: string } }) => void)({ target: { value: "危楼余火新名" } }); render();
    vi.mocked(apiRequest).mockRejectedValue(new Error("网络断开"));
    (modal().props.onOk as () => void)(); await settle();
    expect(field("anw-novel-title").props.value).toBe("危楼余火新名");
    expect(changed).not.toHaveBeenCalled();
    expect(nodes(tree).find(n => n.type === "Alert")?.props.message).toBe("网络断开");
  });
  it("blocks silent conflict overwrites and explicitly loads latest", async () => {
    vi.mocked(apiRequest).mockRejectedValueOnce(new ApiError(409, "conflict", {}));
    (modal().props.onOk as () => void)(); await settle();
    expect(modal().props.okButtonProps).toEqual({ disabled: true });
    expect(field("anw-novel-title").props.value).toBe(novel.title);
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...novel, title: "另一处的新名", version: 4 });
    (button("载入最新资料").props.onClick as () => void)(); await settle();
    expect(field("anw-novel-title").props.value).toBe("另一处的新名");
    expect(modal().props.okButtonProps).toEqual({ disabled: false });
  });
  it("coalesces double clicks without sending duplicate writes", async () => {
    let finish: (value: NovelMetadataRecord) => void = () => undefined;
    vi.mocked(apiRequest).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const submit = modal().props.onOk as () => void;
    submit(); submit();
    expect(apiRequest).toHaveBeenCalledTimes(1);
    finish(novel); await settle();
  });
  it("cancels without saving", () => {
    (modal().props.onCancel as () => void)(); render();
    expect(modal().props.open).toBe(false);
    expect(apiRequest).not.toHaveBeenCalled();
  });
});
