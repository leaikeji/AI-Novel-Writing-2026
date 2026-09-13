import { describe, expect, it, vi } from "vitest";

import type { LibraryCheckHit } from "./contracts";
import type { PrivateLibraryAssetView } from "./model";
import { createPrivateLibraryWorkspace, type PrivateLibraryWorkspaceProps } from "./private-library-workspace";
import {
  TEST_ANTD,
  createPrivateLibraryHarness,
  findAll,
  findButton,
  findByLabel,
  textContent,
} from "./test-harness";


function assets(): PrivateLibraryAssetView[] {
  return [
    {
      id: "pack-1",
      asset_type: "vocabulary",
      title: "末日工程用词",
      version: 3,
      current_version_id: "pack-1-v3",
      archived: false,
      scope_kind: "novel",
      scope_novel_id: "novel-a",
      tags: ["工程", "动作"],
      binding_count: 1,
      updated_at: "2026-09-13T08:00:00Z",
      enabled: true,
      summary: "用于避难所建造场景",
      lexicon: {
        schema_version: "lexicon-pack/1",
        renderer_version: "lexicon-renderer/1",
        entries: [{
          entry_id: "entry-1",
          term: "排水坡度",
          action: "recommend",
          state: "active",
          match_mode: "phrase",
          case_sensitive: false,
          variants: [],
          categories: ["工程"],
          genres: [],
          eras: [],
          positions: ["body"],
          note: "具体工程动作",
          example: "",
          counterexample: "",
          replacement_hint: "",
          source_refs: [],
        }],
      },
    },
    {
      id: "pack-2",
      asset_type: "vocabulary",
      title: "套话禁用词",
      version: 1,
      current_version_id: "pack-2-v1",
      archived: false,
      scope_kind: "library",
      tags: [],
      binding_count: 0,
      updated_at: "2026-09-13T09:00:00Z",
      enabled: false,
    },
    {
      id: "style-1",
      asset_type: "writing_style",
      title: "短句动作风格",
      version: 1,
      current_version_id: "style-1-v1",
      archived: false,
      scope_kind: "library",
      tags: [],
      binding_count: 2,
      updated_at: "2026-09-13T10:00:00Z",
      enabled: true,
      summary: "动作段减少解释句",
    },
  ];
}


function props() {
  return {
    assets: assets(),
    activeNovel: { id: "novel-a", title: "危楼之下" },
    checkReport: {
      schema_version: "library-check/1" as const,
      id: "report-1",
      status: "complete" as const,
      text_sha256: "a".repeat(64),
      rules_sha256: "b".repeat(64),
      scanned_rule_count: 1,
      omitted_rule_count: 0,
      visible_character_count: 20,
      offset: 0,
      limit: 200,
      total_hits: 1,
      has_more: false,
      hits: [{
        hit_id: "hit-1",
        entry_id: "forbid-1",
        asset_id: "pack-1",
        asset_version_id: "pack-1-v3",
        action: "forbid" as const,
        matched_text: "不禁让人",
        start_utf16: 8,
        end_utf16: 12,
        reason: "本书已禁用",
        count: 1,
      }],
    },
    onRefresh: vi.fn(),
    onSaveAsset: vi.fn(),
    onSaveEntry: vi.fn(),
    onToggleEnabled: vi.fn(),
    onLocateHit: vi.fn(),
  };
}


describe("private library desktop workspace", () => {
  it("renders four keyboard tabs, pack and entry lists, status and check location", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = props();
    let tree = harness.render(Workspace, input);
    const tabs = findAll(tree, (element) => element.props.role === "tab");
    expect(tabs).toHaveLength(4);
    expect(tabs.map(textContent)).toEqual([
      "用词库",
      "文风库",
      "机制库",
      "灵感库",
    ]);
    expect(textContent(tree)).toContain("排水坡度");
    expect(textContent(tree)).toContain("本书专用");
    expect(textContent(tree)).toContain("已启用");

    const secondFocus = vi.fn();
    const firstRef = tabs[0]?.props.ref as (node: { focus(): void }) => void;
    const secondRef = tabs[1]?.props.ref as (node: { focus(): void }) => void;
    firstRef({ focus: vi.fn() });
    secondRef({ focus: secondFocus });
    const preventDefault = vi.fn();
    (tabs[0]?.props.onKeyDown as (event: { key: string; preventDefault(): void }) => void)({
      key: "ArrowRight",
      preventDefault,
    });
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(secondFocus).toHaveBeenCalledOnce();
    tree = harness.render(Workspace, input);
    expect(findAll(tree, (element) => element.props.role === "tab")[1]?.props["aria-selected"]).toBe(true);

    (findAll(tree, (element) => element.props.role === "tab")[0]?.props.onClick as () => void)();
    tree = harness.render(Workspace, input);
    (findButton(tree, "定位原句").props.onClick as () => void)();
    expect(input.onLocateHit).toHaveBeenCalledWith(expect.objectContaining({
      hit_id: "hit-1",
      start_utf16: 8,
      end_utf16: 12,
    } satisfies Partial<LibraryCheckHit>));
  });

  it("preserves search and filters across a failed refresh and retries through props", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = props();
    let tree = harness.render(Workspace, input);
    (findByLabel(tree, "搜索私有库").props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "套话" },
    });
    tree = harness.render(Workspace, input);
    (findByLabel(tree, "筛选启用状态").props.onChange as (value: string) => void)("disabled");
    tree = harness.render(Workspace, { ...input, loadError: "网络暂时不可用" });
    expect(findByLabel(tree, "搜索私有库").props.value).toBe("套话");
    expect(findByLabel(tree, "筛选启用状态").props.value).toBe("disabled");
    expect(textContent(tree)).toContain("套话禁用词");
    const errorAlert = findAll(tree, (element) => element.type === "alert" && element.props.type === "error")[0]!;
    const retry = errorAlert.props.action as ReturnType<typeof findButton>;
    (retry.props.onClick as () => void)();
    expect(input.onRefresh).toHaveBeenCalledOnce();
  });

  it("offers bounded pagination without replacing the already loaded list", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const onLoadMore = vi.fn();
    const tree = harness.render(Workspace, {
      ...props(),
      hasMore: true,
      onLoadMore,
    });
    expect(textContent(tree)).toContain("末日工程用词");
    (findButton(tree, "继续加载").props.onClick as () => void)();
    expect(onLoadMore).toHaveBeenCalledOnce();
  });

  it("refreshes current filters without resending maintenance or resetting author inputs", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = props();
    let tree = harness.render(Workspace, input);
    (findByLabel(tree, "搜索私有库").props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "工程" },
    });
    tree = harness.render(Workspace, input);
    expect(findButton(tree, "刷新资料").props.disabled).toBe(false);
    (findButton(tree, "刷新资料").props.onClick as () => void)();
    expect(input.onRefresh).toHaveBeenCalledOnce();
    expect(input.onSaveAsset).not.toHaveBeenCalled();
    tree = harness.render(Workspace, input);
    expect(findByLabel(tree, "搜索私有库").props.value).toBe("工程");
  });

  it.each([{ loading: true }, { disabled: true }])("disables refresh during blocked operations: %o", (state) => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const tree = harness.render(Workspace, { ...props(), ...state });
    expect(findButton(tree, "刷新资料").props.disabled).toBe(true);
  });

  it("protects an open editor from refresh and enables refresh after closing it", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = props();
    let tree = harness.render(Workspace, input);
    (findButton(tree, "编辑资料").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, input);
    expect(findButton(tree, "刷新资料").props.disabled).toBe(true);
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    (drawer.props.onClose as () => void)();
    tree = harness.render(Workspace, input);
    expect(findButton(tree, "刷新资料").props.disabled).toBe(false);
    expect(input.onRefresh).not.toHaveBeenCalled();
  });

  it("opens the creation drawer, focuses its first field and returns focus on close", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = props();
    let tree = harness.render(Workspace, input);
    const triggerFocus = vi.fn();
    (findButton(tree, "新建词包").props.onClick as (event: { currentTarget: { focus(): void } }) => void)({
      currentTarget: { focus: triggerFocus },
    });
    tree = harness.render(Workspace, input);
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    expect(drawer.props.open).toBe(true);
    expect(drawer.props.width).toBe(520);
    const nameInput = findByLabel(tree, "资料名称");
    const inputFocus = vi.fn();
    (nameInput.props.ref as (node: { focus(): void }) => void)({ focus: inputFocus });
    (drawer.props.afterOpenChange as (open: boolean) => void)(true);
    expect(inputFocus).toHaveBeenCalledOnce();
    (drawer.props.onClose as () => void)();
    expect(triggerFocus).not.toHaveBeenCalled();
    (drawer.props.afterOpenChange as (open: boolean) => void)(false);
    (drawer.props.afterOpenChange as (open: boolean) => void)(false);
    expect(triggerFocus).toHaveBeenCalledOnce();
  });

  it("emits only the edited asset draft and toggles through injected callbacks", async () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = props();
    let tree = harness.render(Workspace, input);
    (findButton(tree, "编辑资料").props.onClick as (event: { currentTarget: { focus(): void } }) => void)({
      currentTarget: { focus: vi.fn() },
    });
    tree = harness.render(Workspace, input);
    (findByLabel(tree, "资料名称").props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "地下工事用词" },
    });
    tree = harness.render(Workspace, input);
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    const footer = drawer.props.footer;
    (findButton(footer, "保存").props.onClick as () => void)();
    expect(input.onSaveAsset).toHaveBeenCalledWith(expect.objectContaining({
      assetId: "pack-1",
      title: "地下工事用词",
      scopeKind: "novel",
      scopeNovelId: "novel-a",
    }));
    await Promise.resolve();

    tree = harness.render(Workspace, input);
    (findByLabel(tree, "末日工程用词启用状态").props.onChange as (checked: boolean) => void)(false);
    expect(input.onToggleEnabled).toHaveBeenCalledWith(
      expect.objectContaining({ id: "pack-1" }),
      false,
    );
  });

  it("uses controlled server filters without filtering summary-only matches again", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const onFiltersChange = vi.fn();
    const filtered = { category: "vocabulary" as const, query: "疏水阀", scope: "all" as const, enabled: "all" as const };
    const tree = harness.render(Workspace, {
      ...props(),
      assets: [{ ...assets()[0]!, lexicon: undefined, detail_loaded: false, entry_count: 312 }],
      filters: filtered, onFiltersChange, total: 101, hasMore: true, onLoadMore: vi.fn(),
    });
    expect(textContent(tree)).toContain("末日工程用词");
    expect(textContent(tree)).toContain("312 个词项");
    expect(textContent(tree)).toContain("当前筛选共 101 项 · 已加载 1 项");
    expect(findAll(tree, (element) => element.props.role === "tab").map(textContent)).toEqual(["用词库", "文风库", "机制库", "灵感库"]);
    (findByLabel(tree, "搜索私有库").props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "泵站" } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...filtered, query: "泵站" });
    (findByLabel(tree, "包含已归档资料").props.onChange as (event: { target: { checked: boolean } }) => void)({ target: { checked: true } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...filtered, includeArchived: true });
  });

  it("keeps pagination available when loaded items have no local match", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const onLoadMore = vi.fn();
    const tree = harness.render(Workspace, { ...props(), assets: [assets()[2]!], hasMore: true, onLoadMore });
    (findButton(tree, "继续加载").props.onClick as () => void)();
    expect(onLoadMore).toHaveBeenCalledOnce();
    expect(findAll(tree, (element) => element.type === "empty")).toHaveLength(0);
  });

  it("does not portray a failed initial query as an empty library", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const tree = harness.render(Workspace, { ...props(), assets: [], total: 0, loadError: "读取超时" });
    expect(findAll(tree, (element) => element.type === "empty")).toHaveLength(0);
    expect(textContent(tree)).not.toContain("当前筛选共 0 项");
    expect(textContent(tree)).toContain("资料列表尚未加载");
  });

  it("disables summary editing until the selected full detail is loaded", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), assets: [{ ...assets()[0]!, lexicon: undefined, detail_loaded: false }], selectedAssetId: "pack-1" };
    let tree = harness.render(Workspace, { ...input, detailLoading: true });
    expect(findButton(tree, "编辑资料").props.disabled).toBe(true);
    expect(textContent(tree)).not.toContain("这个词包还没有词项");
    expect(findAll(tree, (element) => element.type === "button" && textContent(element) === "添加词项")).toHaveLength(0);
    tree = harness.render(Workspace, { ...input, detailError: "详情读取失败" });
    expect(findButton(tree, "编辑资料").props.disabled).toBe(true);
    tree = harness.render(Workspace, { ...input, selectedAsset: { ...assets()[2]!, detail_loaded: true } });
    expect(findButton(tree, "编辑资料").props.disabled).toBe(true);
    tree = harness.render(Workspace, { ...input, selectedAsset: { ...assets()[0]!, detail_loaded: true } });
    expect(findButton(tree, "编辑资料").props.disabled).toBe(false);
    expect(textContent(tree)).toContain("排水坡度");
  });

  it.each([
    [false, false, false], [false, true, false], [true, true, false], [true, false, true],
  ])("archive state %s and enabled %s gives disabled %s", (archived, enabled, disabled) => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), assets: [{ ...assets()[0]!, archived, enabled }] };
    const tree = harness.render(Workspace, input);
    const toggle = findByLabel(tree, "末日工程用词启用状态");
    expect(toggle.props.disabled).toBe(disabled);
    (toggle.props.onChange as (checked: boolean) => void)(!enabled);
    if (disabled) expect(input.onToggleEnabled).not.toHaveBeenCalled();
    else expect(input.onToggleEnabled).toHaveBeenCalledWith(input.assets[0], !enabled);
  });

  it("does not offer novel filters or enable actions without an active novel", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), activeNovel: null };
    const tree = harness.render(Workspace, input);
    const toggle = findByLabel(tree, "末日工程用词启用状态");
    expect(toggle.props.disabled).toBe(true);
    (toggle.props.onChange as (checked: boolean) => void)(false);
    expect(input.onToggleEnabled).not.toHaveBeenCalled();
    expect(findByLabel(tree, "筛选启用状态").props.disabled).toBe(true);
    expect(findByLabel(tree, "筛选保存范围").props.options).toEqual([
      { value: "all", label: "全部范围" }, { value: "library", label: "通用库" },
    ]);
  });

  it.each(["novel", "category", "query", "selected_asset", "asset_version"])(
    "preserves an open draft and blocks its save after %s changes",
    (change) => {
      const harness = createPrivateLibraryHarness();
      const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
      const input: PrivateLibraryWorkspaceProps = {
        ...props(), selectedAssetId: "pack-1",
        filters: { category: "vocabulary", query: "", scope: "all", enabled: "all" },
      };
      let tree = harness.render(Workspace, input);
      (findButton(tree, "新建词包").props.onClick as (event: object) => void)({});
      tree = harness.render(Workspace, input);
      (findByLabel(tree, "资料名称").props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "泵房维修措辞" } });
      tree = harness.render(Workspace, input);
      const originalDrawer = findAll(tree, (element) => element.type === "drawer")[0]!;
      const originalSave = findButton(originalDrawer.props.footer, "保存");
      const newSave = vi.fn();
      const changed: PrivateLibraryWorkspaceProps = {
        ...input, onSaveAsset: newSave,
        ...(change === "novel" ? { activeNovel: { id: "novel-b", title: "山海旧站" } } : {}),
        ...(change === "category" ? { filters: { ...input.filters!, category: "idea" } } : {}),
        ...(change === "query" ? { filters: { ...input.filters!, query: "维修" } } : {}),
        ...(change === "selected_asset" ? { selectedAssetId: "pack-2" } : {}),
        ...(change === "asset_version" ? { selectedAsset: { ...assets()[0]!, current_version_id: "pack-1-v4" } } : {}),
      };
      tree = harness.render(Workspace, changed);
      const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
      expect(drawer.props.open).toBe(true);
      expect(findByLabel(tree, "资料名称").props.value).toBe("泵房维修措辞");
      expect(findButton(drawer.props.footer, "保存").props.disabled).toBe(true);
      expect(findAll(tree, (element) => element.type === "alert").some((alert) => alert.props.message === "当前上下文已切换，原表单暂停保存")).toBe(true);
      (findButton(drawer.props.footer, "保存").props.onClick as () => void)();
      (originalSave.props.onClick as () => void)();
      expect(newSave).not.toHaveBeenCalled();
      expect(input.onSaveAsset).not.toHaveBeenCalled();
      const scopeSelect = findByLabel(tree, "资料保存范围");
      expect(scopeSelect.props.options).toContainEqual({ value: "novel", label: "本书专用：危楼之下" });
    },
  );

  it("allows retained input to be saved only after returning to its original context", async () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), selectedAssetId: "pack-1" };
    let tree = harness.render(Workspace, input);
    (findButton(tree, "编辑资料").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, { ...input, activeNovel: { id: "novel-b", title: "山海旧站" } });
    expect(findByLabel(tree, "资料名称").props.value).toBe("末日工程用词");
    tree = harness.render(Workspace, input);
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    expect(findButton(drawer.props.footer, "保存").props.disabled).toBe(false);
    (findButton(drawer.props.footer, "保存").props.onClick as () => void)();
    await Promise.resolve();
    expect(input.onSaveAsset).toHaveBeenCalledWith(expect.objectContaining({ assetId: "pack-1", scopeNovelId: "novel-a" }));
  });

  it("retains an entry editor's asset identity when another asset is selected", () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), selectedAssetId: "pack-1" };
    let tree = harness.render(Workspace, input);
    (findButton(tree, "添加词项").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, input);
    (findByLabel(tree, "词或短语").props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "阀座" } });
    tree = harness.render(Workspace, { ...input, selectedAssetId: "pack-2" });
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    expect(findByLabel(tree, "词或短语").props.value).toBe("阀座");
    (findButton(drawer.props.footer, "保存").props.onClick as () => void)();
    expect(input.onSaveEntry).not.toHaveBeenCalled();
  });

  it("blocks form replacement while saving and retains input when a late success arrives in another context", async () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => { finish = resolve; });
    const onSaveAsset = vi.fn(() => pending);
    const input = { ...props(), selectedAssetId: "pack-1", onSaveAsset };
    let tree = harness.render(Workspace, input);
    (findButton(tree, "编辑资料").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, input);
    let drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    (findButton(drawer.props.footer, "保存").props.onClick as () => void)();
    const newSave = vi.fn();
    const changed = { ...input, activeNovel: { id: "novel-b", title: "山海旧站" }, onSaveAsset: newSave };
    tree = harness.render(Workspace, changed);
    drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    expect(drawer.props.closable).toBe(false);
    (drawer.props.onClose as () => void)();
    (findButton(tree, "新建词包").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, changed);
    expect(findByLabel(tree, "资料名称").props.value).toBe("末日工程用词");
    finish();
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
    tree = harness.render(Workspace, changed);
    drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    expect(drawer.props.open).toBe(true);
    expect(findByLabel(tree, "资料名称").props.value).toBe("末日工程用词");
    expect(findButton(drawer.props.footer, "保存").props.disabled).toBe(true);
    expect(newSave).not.toHaveBeenCalled();
    expect(onSaveAsset).toHaveBeenCalledOnce();
    (drawer.props.onClose as () => void)();
    tree = harness.render(Workspace, changed);
    (findButton(tree, "新建词包").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, changed);
    expect(findByLabel(tree, "资料名称").props.value).toBe("");
    expect(findByLabel(tree, "资料保存范围").props.options).toContainEqual({ value: "novel", label: "本书专用：山海旧站" });
  });

  it("turns synchronous callback failures into a recoverable form error", async () => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), onSaveAsset: vi.fn(() => { throw new Error("原资料已变化"); }) };
    let tree = harness.render(Workspace, input);
    (findButton(tree, "编辑资料").props.onClick as (event: object) => void)({});
    tree = harness.render(Workspace, input);
    let drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    (findButton(drawer.props.footer, "保存").props.onClick as () => void)();
    for (let index = 0; index < 4; index += 1) await Promise.resolve();
    tree = harness.render(Workspace, input);
    drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    expect(drawer.props.open).toBe(true);
    expect(drawer.props.closable).toBe(true);
    expect(findAll(tree, (element) => element.type === "alert").some((alert) => alert.props.message === "原资料已变化")).toBe(true);
  });

  it.each(["asset", "entry"])("closes the %s editor after its successful save advances the same asset version", async (kind) => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => { finish = resolve; });
    const save = vi.fn(() => pending);
    const input = { ...props(), selectedAssetId: "pack-1", onSaveAsset: save, onSaveEntry: save };
    let tree = harness.render(Workspace, input);
    const focus = vi.fn();
    (findButton(tree, kind === "asset" ? "编辑资料" : "添加词项").props.onClick as (event: object) => void)({ currentTarget: { focus } });
    tree = harness.render(Workspace, input);
    if (kind === "entry") {
      (findByLabel(tree, "词或短语").props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "阀座" } });
      tree = harness.render(Workspace, input);
    }
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    (findButton(drawer.props.footer, "保存").props.onClick as () => void)();
    const updated = { ...input, selectedAsset: { ...assets()[0]!, version: 4, current_version_id: "pack-1-v4" } };
    harness.render(Workspace, updated);
    finish();
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
    tree = harness.render(Workspace, updated);
    expect(findAll(tree, (element) => element.type === "drawer" && element.props.open === true)).toHaveLength(0);
    expect(save).toHaveBeenCalledOnce();
    expect(focus).not.toHaveBeenCalled();
    const currentFocus = vi.fn();
    const currentTrigger = findButton(tree, kind === "asset" ? "编辑资料" : "添加词项");
    (currentTrigger.props.ref as (node: { focus(): void }) => void)({ focus: currentFocus });
    const closedDrawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    (closedDrawer.props.afterOpenChange as (open: boolean) => void)(false);
    expect(currentFocus).toHaveBeenCalledOnce();
    expect(focus).not.toHaveBeenCalled();
  });

  it.each(["new_editor", "other_novel"])("does not steal focus after a delayed close callback and %s", (change) => {
    const harness = createPrivateLibraryHarness();
    const Workspace = createPrivateLibraryWorkspace(harness.React, TEST_ANTD);
    const input = { ...props(), selectedAssetId: "pack-1" };
    let tree = harness.render(Workspace, input);
    const focus = vi.fn();
    (findButton(tree, "编辑资料").props.onClick as (event: object) => void)({ currentTarget: { focus } });
    tree = harness.render(Workspace, input);
    const drawer = findAll(tree, (element) => element.type === "drawer")[0]!;
    (drawer.props.onClose as () => void)();
    tree = harness.render(Workspace, change === "other_novel" ? { ...input, activeNovel: { id: "novel-b", title: "山海旧站" } } : input);
    if (change === "new_editor") (findButton(tree, "新建词包").props.onClick as (event: object) => void)({});
    (drawer.props.afterOpenChange as (open: boolean) => void)(false);
    expect(focus).not.toHaveBeenCalled();
  });
});
