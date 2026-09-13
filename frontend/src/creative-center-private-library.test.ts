import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createReactHarness, findAll } from "./embedding/test-harness";
import type { LibraryQueryFilters, PrivateLibraryAssetDraft, PrivateLibraryAssetView } from "./private-library";
import type { NovelSummary } from "./types";
import { NOVEL_SURFACE_NAVIGATION_EVENT } from "./novel-surface-navigation";

const request = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...await original<typeof import("./api")>(), apiRequest: request }));
let page: typeof import("./creative-center");
let harness: ReturnType<typeof createReactHarness>;
const props = { onBack: vi.fn(), novels: [] as NovelSummary[], activeNovelId: "", onActiveNovelChange: vi.fn() };
const asset: PrivateLibraryAssetView = {
  id: "asset", title: "潮汐描写", asset_type: "vocabulary", version: 2, archived: false,
  scope_kind: "library", tags: [], binding_count: 0, updated_at: "2026-09-13", enabled: false,
  detail_loaded: false, entry_count: 2, summary: "摘要", current_version_id: "asset-v2",
};
const result = (items = [asset], next: number | null = null, offset = 0) => ({
  items, total: next === null ? items.length : 151, offset, limit: 50, has_more: next !== null, next_offset: next,
});
const defaultFilters: LibraryQueryFilters = { category: "vocabulary", query: "", scope: "all", enabled: "all", includeArchived: true };

function render() {
  const tree = harness.render(page.PrivateLibraryV2, props);
  const workspace = findAll(tree, (node) => typeof node.props.onFiltersChange === "function")[0]!;
  harness.commitEffects();
  return workspace.props;
}
async function settlePage() {
  await vi.runOnlyPendingTimersAsync();
  render();
  await Promise.resolve(); await Promise.resolve();
  return render();
}
beforeEach(async () => {
  vi.resetModules(); vi.useFakeTimers(); request.mockReset();
  props.novels = []; props.activeNovelId = "";
  harness = createReactHarness();
  const input = Object.assign("input", { TextArea: "textarea" });
  const components = new Proxy({ Input: input }, { get: (target, key) => key === "Input" ? target.Input : String(key) });
  vi.stubGlobal("window", { QwenPaw: { host: {
    React: { ...harness.React, useCallback: <T>(callback: T) => callback },
    ReactDOM: {}, antd: components, antdIcons: components,
  } } });
  request.mockImplementation(async (path: string) => {
    if (path === "/private-library/presets" || path.includes("/versions")) return { items: [] };
    if (path.includes("/assets?")) return result();
    return { ...asset, detail_loaded: true, content: "长篇说明。".repeat(150) };
  });
  page = await import("./creative-center");
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("private library real page wiring", () => {
  it("notifies the route wrapper when entering and leaving private library without losing host history state", () => {
    const location = { origin: "http://localhost", pathname: "/chat/current-session", search: "?novel_center=1" };
    const hostState = { session: "current-session" };
    const history = { state: hostState, replaceState: vi.fn((_state: unknown, _unused: string, target: string) => {
      location.search = new URL(target, location.origin).search;
    }) };
    const notifiedQueries: string[] = [];
    const dispatchEvent = vi.fn((event: Event) => {
      expect(event.type).toBe(NOVEL_SURFACE_NAVIGATION_EVENT);
      notifiedQueries.push(location.search);
      return true;
    });
    Object.assign(window, { location, history, dispatchEvent });
    const center = harness.render(page.NovelLibraryPage, {});
    const enter = findAll(center, (node) => node.props.label === "私有库")[0]!;
    (enter.props.onClick as () => void)();
    expect(history.replaceState).toHaveBeenLastCalledWith(hostState, "", "/chat/current-session?novel_center=1&view=private-library");
    const library = harness.render(page.NovelLibraryPage, {});
    (library.props.onBack as () => void)();
    expect(history.replaceState).toHaveBeenLastCalledWith(hostState, "", "/chat/current-session?novel_center=1");
    expect(notifiedQueries).toEqual(["?novel_center=1&view=private-library", "?novel_center=1"]);
  });

  it("uses server projection/filter/offset and preserves full detail text when editing", async () => {
    render();
    const state = await settlePage();
    expect(state.total).toBe(1);
    const listCall = request.mock.calls.find(([path]) => String(path).includes("/assets?"))!;
    expect(String(listCall[0])).toContain("projection=summary");
    expect(String(listCall[0])).toContain("asset_type=vocabulary");
    expect((state.selectedAsset as PrivateLibraryAssetView).summary).toHaveLength(750);
    await (state.onSaveAsset as (draft: PrivateLibraryAssetDraft) => Promise<void>)({
      assetId: asset.id, assetType: "vocabulary", title: asset.title,
      summary: (state.selectedAsset as PrivateLibraryAssetView).summary!, tags: [],
      scopeKind: "library", enabled: false,
    });
    const saved = request.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(saved[1].body).content).toHaveLength(750);
  });

  it("discards a late response from a previous query and keeps errors distinct from an empty library", async () => {
    let resolveOld: (value: ReturnType<typeof result>) => void = () => undefined;
    request.mockImplementation((path: string) => {
      if (path.includes("/presets")) return Promise.resolve({ items: [] });
      if (path.includes("query=" + encodeURIComponent("沉井"))) return Promise.reject(new Error("连接中断"));
      return new Promise((resolve) => { resolveOld = resolve; });
    });
    render(); await vi.runOnlyPendingTimersAsync();
    const initial = render();
    (initial.onFiltersChange as (filters: LibraryQueryFilters) => void)({ ...defaultFilters, query: "沉井" });
    render(); await vi.runOnlyPendingTimersAsync();
    resolveOld(result([{ ...asset, title: "迟到资料" }]));
    await Promise.resolve();
    const state = render();
    expect(state.assets).toEqual([]);
    expect(String(state.loadError)).toContain("连接中断");
    expect((state.filters as LibraryQueryFilters).query).toBe("沉井");
  });

  it("continues at the server offset even after deduplication and resets it on mutation", async () => {
    request.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path.includes("/presets") || path.includes("/versions")) return { items: [] };
      if (init?.method === "PUT") return {};
      if (path.includes("offset=50")) return result([asset], 100, 50);
      if (path.includes("/assets?")) return result([asset], 50);
      return { ...asset, detail_loaded: true, content: "完整资料" };
    });
    render(); let state = await settlePage();
    (state.onLoadMore as () => void)();
    await Promise.resolve(); await Promise.resolve(); state = render();
    expect(state.assets).toHaveLength(1);
    (state.onLoadMore as () => void)();
    expect(request.mock.calls.some(([path]) => String(path).includes("offset=100"))).toBe(true);
    await Promise.resolve(); await Promise.resolve(); state = render();
    await (state.onSaveAsset as (draft: PrivateLibraryAssetDraft) => Promise<void>)({
      assetId: asset.id, assetType: "vocabulary", title: asset.title,
      summary: "修改后的完整资料", tags: [], scopeKind: "library", enabled: false,
    });
    const lists = request.mock.calls.filter(([path]) => String(path).includes("/assets?"));
    expect(String(lists[lists.length - 1]?.[0])).toContain("offset=0");
    state = render();
    expect(state.assets).toHaveLength(1);
  });

  it("shows a toggle failure without an unhandled rejected promise", async () => {
    props.novels = [{ id: "novel-a", title: "潮汐尽头" } as NovelSummary]; props.activeNovelId = "novel-a";
    const baseline = request.getMockImplementation()!;
    request.mockImplementation((path: string, init?: RequestInit) => path.endsWith("/enabled")
      ? Promise.reject(new Error("绑定版本已变化，请刷新后重试")) : baseline(path, init));
    render(); const state = await settlePage();
    await expect((state.onToggleEnabled as (asset: PrivateLibraryAssetView, enabled: boolean) => Promise<void>)(asset, true)).resolves.toBeUndefined();
    const failed = render();
    expect(String(failed.loadError)).toContain("绑定版本已变化");
    expect((failed.assets as PrivateLibraryAssetView[])[0].enabled).toBe(false);
  });
});
