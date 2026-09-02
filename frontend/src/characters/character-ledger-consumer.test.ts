import { describe, expect, it, vi } from "vitest";

import { renderCharacterFactHistory } from "./character-fact-history";
import { renderCharacterStatePanel } from "./character-state-panel";
import { createCharacterWorkspaceDialog } from "./character-workspace";
import type {
  CharacterBatchRevertImpact,
  CharacterFactHistoryPageV2,
  CharacterWorkspaceV2,
  ProjectedFactViewV2,
  StoryFactCorrectionCommandV1,
} from "./contracts";
import { characterWorkspace, storyFactImpact } from "./test-fixtures";
import { createReactHarness, findAll, findButton, settle, textContent } from "./test-harness";

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function factWithSource(
  id: string,
  objectText: string,
  batchId = "batch-1",
  dimension = "goal",
): ProjectedFactViewV2 {
  const base = characterWorkspace().projected_state.current_facts[0];
  return {
    ...base,
    id,
    object_text: objectText,
    dimension,
    source_document_id: `chapter-${batchId}`,
    source_revision_id: `revision-${batchId}`,
    source: {
      document_id: `chapter-${batchId}`,
      document_title: `章节 ${batchId}`,
      document_position: 12,
      revision_id: `revision-${batchId}`,
      revision_is_current: true,
      source_content_hash: "a".repeat(64),
      source_coordinate: "unicode-codepoint-v1",
      source_start: null,
      source_end: null,
      source_range_hash: null,
      source_excerpt: objectText,
      source_excerpt_truncated: false,
      binding_state: "bound",
      proposal_item_id: `proposal-${batchId}`,
      commit_batch_id: batchId,
    },
  };
}

function workspaceWithFacts(facts: readonly ProjectedFactViewV2[]): CharacterWorkspaceV2 {
  const workspace = characterWorkspace();
  return {
    ...workspace,
    projected_state: { ...workspace.projected_state, current_facts: facts },
    writing_state: {
      ...workspace.writing_state,
      recent_changes: facts.slice(0, 5),
      history_summary: {
        ...workspace.writing_state.history_summary,
        total: facts.length,
        current: facts.length,
      },
    },
  };
}

function batchImpact(
  workspace: CharacterWorkspaceV2,
  batchId: string,
  factIds: readonly string[],
): CharacterBatchRevertImpact {
  return {
    schema_version: "story-ledger-batch-impact-preview/1",
    novel_id: workspace.novel_id,
    batch_id: batchId,
    preview_snapshot_token: `ledger-snapshot-${workspace.story_ledger_version}`,
    story_ledger_version: workspace.story_ledger_version,
    timeline: {
      mode: workspace.timeline_mode,
      timeline_id: workspace.selected_timeline.id,
      timeline_name: workspace.selected_timeline.name,
      narrative_cutoff: workspace.projected_state.narrative_cutoff,
    },
    state: "ready",
    already_reverted: false,
    batch_fact_count: factIds.length,
    batch_relationship_count: 0,
    facts: factIds.map((id) => ({ id, disposition: "supersede" })),
    relationships: [],
  };
}

function historyPage(
  items: readonly ProjectedFactViewV2[],
  nextCursor: string | null = null,
): CharacterFactHistoryPageV2 {
  return {
    schema_version: "character-fact-history/1",
    items,
    next_cursor: nextCursor,
    total_summary: {
      total: items.length,
      current: items.length,
      historical: 0,
      superseded: 0,
      source_invalid: 0,
      batch_reverted: 0,
    },
  };
}

function openGrowth(root: unknown): void {
  (findButton(root, "状态与经历").props.onClick as () => void)();
}

function click(
  root: unknown,
  label: string,
  trigger: HTMLElement = {} as HTMLElement,
): void {
  (findButton(root, label).props.onClick as (
    event: { readonly currentTarget: HTMLElement },
  ) => void)({ currentTarget: trigger });
}

describe("character story-ledger consumer", () => {
  it("bounds multi-value state by default and reports missing dimensions neutrally", () => {
    const workspace = characterWorkspace();
    const values = Array.from({ length: 5 }, (_, index) => ({
      fact_id: `goal-${index + 1}`,
      object_text: index === 0 ? `追查${"很长的线索".repeat(30)}` : `目标 ${index + 1}`,
      story_sequence: index + 1,
      story_time: null,
      source: null,
    }));
    const scoped = {
      ...workspace,
      writing_state: {
        ...workspace.writing_state,
        slots: [{
          ...workspace.writing_state.slots[0],
          values,
        }],
      },
    };
    const harness = createReactHarness();
    const root = renderCharacterStatePanel(harness.React, {
      currentStateTitleId: "current",
      recentChangesTitleId: "recent",
      workspace: scoped,
      historyOpen: false,
      onToggleHistory: vi.fn(),
    });

    const visibleValues = findAll(root, (element) => (
      element.type === "ul" && element.props.className === "anw-character-state-values"
    ))[0];
    const remaining = findAll(root, (element) => (
      element.type === "details" && element.props.className === "anw-character-state-more-values"
    ))[0];
    expect(findAll(visibleValues, (element) => element.type === "li")).toHaveLength(3);
    expect(findAll(remaining, (element) => element.type === "li")).toHaveLength(2);
    expect(textContent(remaining)).toContain("共 5 条，查看全部");
    expect(textContent(root)).toContain("查看完整内容");
    expect(textContent(root)).toContain("已记录 1/8，7 项尚无事实");
    expect(textContent(root)).toContain("缺失维度仍需按写作需要补充");
    expect(textContent(root)).not.toContain("没有待核对项");
  });

  it("uses labeled list items and a keyboard-closing action menu instead of fake table roles", () => {
    const fact = factWithSource("fact-menu", "前往灯塔");
    const batchSibling = { ...fact, id: "fact-menu-sibling", object_text: "确认灯塔信号" };
    const onCorrectFact = vi.fn();
    const harness = createReactHarness();
    const root = renderCharacterFactHistory(harness.React, {
      titleId: "history",
      page: historyPage([fact, batchSibling]),
      loading: false,
      loadingMore: false,
      batchPreviewing: false,
      error: null,
      effectiveState: "all",
      health: "all",
      dimension: "",
      sourceDocumentId: "",
      dimensionOptions: ["goal"],
      sourceOptions: [{ id: fact.source!.document_id, label: fact.source!.document_title }],
      onEffectiveStateChange: vi.fn(),
      onHealthChange: vi.fn(),
      onDimensionChange: vi.fn(),
      onSourceDocumentChange: vi.fn(),
      onLoadMore: vi.fn(),
      onOpenSource: vi.fn(),
      onCorrectFact,
      onPreviewBatchRevert: vi.fn(),
    });

    expect(findAll(root, (element) => element.props.role === "table" || element.props.role === "row"))
      .toHaveLength(0);
    expect(findAll(root, (element) => element.type === "ul" && element.props["aria-label"] === "人物事实历史"))
      .toHaveLength(1);
    expect(findAll(root, (element) => element.type === "li" && element.props.className === "anw-character-fact-card"))
      .toHaveLength(2);
    expect(findAll(root, (element) => element.props.className === "anw-character-fact-card-label").map(textContent))
      .toEqual([
        "状态", "维度", "事实", "序位", "来源",
        "状态", "维度", "事实", "序位", "来源",
      ]);
    expect(findAll(root, (element) => element.props.role === "menuitem").map(textContent))
      .toEqual(["修正", "修正"]);
    expect(findAll(root, (element) => element.type === "button" && textContent(element) === "预览批次撤销"))
      .toHaveLength(1);
    expect(textContent(root)).toContain("共 2 条事实");
    expect(findButton(root, "查看").props["aria-label"]).toContain("来源");

    const menu = findAll(root, (element) => element.type === "details" && element.props.className === "anw-character-action-menu")[0];
    const summaryFocus = vi.fn();
    const preventDefault = vi.fn();
    const stopPropagation = vi.fn();
    const disclosure = {
      open: true,
      querySelector: () => ({ focus: summaryFocus }),
    };
    (menu.props.onKeyDown as (event: unknown) => void)({
      key: "Escape",
      currentTarget: disclosure,
      preventDefault,
      stopPropagation,
    });
    expect(disclosure.open).toBe(false);
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(stopPropagation).toHaveBeenCalledOnce();
    expect(summaryFocus).toHaveBeenCalledOnce();

    const summaryTrigger = {} as HTMLElement;
    const actionDisclosure = {
      open: true,
      querySelector: () => summaryTrigger,
    };
    const menuTrigger = {
      closest: () => actionDisclosure,
    } as unknown as HTMLElement;
    (findButton(root, "修正").props.onClick as (
      event: { currentTarget: HTMLElement },
    ) => void)({ currentTarget: menuTrigger });
    expect(actionDisclosure.open).toBe(false);
    expect(onCorrectFact).toHaveBeenCalledWith(fact, summaryTrigger);
  });

  it("sends dimension and source filters to the server-side history callback", async () => {
    const fact = factWithSource("fact-filter", "前往码头", "batch-filter", "location");
    const workspace = workspaceWithFacts([fact]);
    const onLoadFacts = vi.fn().mockResolvedValue(historyPage([fact]));
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const props = { workspace, onLoadFacts };
    let root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    (findButton(root, "查看全部事实（1）").props.onClick as () => void)();
    root = harness.render(Component, props);
    harness.commitEffects();
    await settle();
    root = harness.render(Component, props);

    const history = findAll(root, (element) => element.props.className === "anw-character-fact-history")[0];
    const selects = findAll(history, (element) => element.type === "select");
    (selects[2].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "location" } });
    (selects[3].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: fact.source!.document_id } });
    root = harness.render(Component, props);
    harness.commitEffects();
    await settle();

    expect(onLoadFacts).toHaveBeenLastCalledWith(
      expect.objectContaining({
        dimension: "location",
        source_document_id: fact.source!.document_id,
      }),
      expect.any(AbortSignal),
    );
  });

  it("loads and renders the real fact impact before enabling correction", async () => {
    const workspace = characterWorkspace();
    const pending = deferred<ReturnType<typeof storyFactImpact>>();
    const onLoadFactImpact = vi.fn(() => pending.promise);
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    const props = { workspace, onLoadFactImpact, onCorrectFact: vi.fn() };
    let root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    click(root, "修正");
    root = harness.render(Component, props);

    let drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    expect(onLoadFactImpact).toHaveBeenCalledWith("fact-1", expect.any(AbortSignal));
    expect(textContent(drawer)).toContain("正在读取当前账本快照的实际影响");
    expect(findButton(drawer, "创建替代事实").props.disabled).toBe(true);

    pending.resolve(storyFactImpact({
      related_event_link_count: 3,
      batch_fact_count: 4,
      batch_relationship_count: 2,
      embedding_rebuild_required: false,
    }));
    await settle();
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    expect(textContent(drawer)).toContain("3 条事件链接");
    expect(textContent(drawer)).toContain("4 条批次事实、2 条关系记录");
    expect(textContent(drawer)).toContain("无需重建语义索引");
    expect(textContent(drawer)).not.toContain("受影响上下文");
  });

  it("reuses a correction operation key after failure and rotates it when payload changes", async () => {
    const workspace = characterWorkspace();
    const onCorrectFact = vi.fn().mockRejectedValue(new Error("网络未确认结果"));
    const props = {
      workspace,
      onCorrectFact,
      onLoadFactImpact: vi.fn().mockResolvedValue(storyFactImpact()),
    };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    click(root, "修正");
    await settle();
    root = harness.render(Component, props);
    let drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    let textareas = findAll(drawer, (element) => element.type === "textarea");
    (textareas[0].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "新的目标" } });
    (textareas[1].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "章节证据" } });
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];

    (findButton(drawer, "创建替代事实").props.onClick as () => void)();
    await settle();
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    (findButton(drawer, "创建替代事实").props.onClick as () => void)();
    await settle();

    const firstKey = onCorrectFact.mock.calls[0][1].operation_key;
    const retryKey = onCorrectFact.mock.calls[1][1].operation_key;
    expect(retryKey).toBe(firstKey);

    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    textareas = findAll(drawer, (element) => element.type === "textarea");
    (textareas[1].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "更新后的章节证据" } });
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    (findButton(drawer, "创建替代事实").props.onClick as () => void)();
    await settle();

    expect(onCorrectFact.mock.calls[2][1].operation_key).not.toBe(firstKey);
  });

  it("reuses a batch-revert key after failure and rotates it when the reason changes", async () => {
    const fact = factWithSource("fact-batch", "批次事实");
    const workspace = workspaceWithFacts([fact]);
    const impact = batchImpact(workspace, "batch-1", [fact.id]);
    const onRevertBatch = vi.fn().mockRejectedValue(new Error("网络未确认结果"));
    const props = {
      workspace,
      onLoadFacts: vi.fn().mockResolvedValue(historyPage([fact])),
      onPreviewBatchRevert: vi.fn().mockResolvedValue(impact),
      onRevertBatch,
    };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    (findButton(root, "查看全部事实（1）").props.onClick as () => void)();
    root = harness.render(Component, props);
    harness.commitEffects();
    await settle();
    root = harness.render(Component, props);
    click(root, "预览批次撤销");
    await settle();
    root = harness.render(Component, props);
    let drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-batch-revert-dialog")[0];

    (findButton(drawer, "确认撤销同步").props.onClick as () => void)();
    await settle();
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-batch-revert-dialog")[0];
    (findButton(drawer, "确认撤销同步").props.onClick as () => void)();
    await settle();

    const firstKey = onRevertBatch.mock.calls[0][1].operation_key;
    expect(onRevertBatch.mock.calls[1][1].operation_key).toBe(firstKey);

    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-batch-revert-dialog")[0];
    const reason = findAll(drawer, (element) => element.type === "textarea")[0];
    (reason.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "作者确认撤销" } });
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-batch-revert-dialog")[0];
    (findButton(drawer, "确认撤销同步").props.onClick as () => void)();
    await settle();

    expect(onRevertBatch.mock.calls[2][1].operation_key).not.toBe(firstKey);
  });

  it("does not append a late load-more page after filters start a fresh first page", async () => {
    const firstFact = factWithSource("fact-first", "首页事实");
    const lateFact = factWithSource("fact-late", "过期追加事实");
    const filteredFact = { ...factWithSource("fact-filtered", "冲突新页"), health: "conflict" as const };
    const workspace = workspaceWithFacts([firstFact]);
    const more = deferred<CharacterFactHistoryPageV2>();
    const onLoadFacts = vi.fn()
      .mockResolvedValueOnce(historyPage([firstFact], "cursor-1"))
      .mockImplementationOnce(() => more.promise)
      .mockResolvedValueOnce(historyPage([filteredFact]));
    const props = { workspace, onLoadFacts };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    (findButton(root, "查看全部事实（1）").props.onClick as () => void)();
    root = harness.render(Component, props);
    harness.commitEffects();
    await settle();
    root = harness.render(Component, props);
    (findButton(root, "加载更多").props.onClick as () => void)();

    root = harness.render(Component, props);
    const history = findAll(root, (element) => element.props.className === "anw-character-fact-history")[0];
    const health = findAll(history, (element) => element.type === "select")[1];
    (health.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "conflict" } });
    root = harness.render(Component, props);
    harness.commitEffects();
    await settle();
    root = harness.render(Component, props);
    expect(textContent(root)).toContain("冲突新页");

    more.resolve(historyPage([lateFact]));
    await settle();
    root = harness.render(Component, props);
    expect(textContent(root)).toContain("冲突新页");
    expect(textContent(root)).not.toContain("过期追加事实");
    expect((onLoadFacts.mock.calls[1][1] as AbortSignal).aborted).toBe(true);
  });

  it("keeps only the latest batch preview when earlier responses arrive late", async () => {
    const firstFact = factWithSource("fact-batch-1", "批次一", "batch-1");
    const secondFact = factWithSource("fact-batch-2", "批次二", "batch-2");
    const workspace = workspaceWithFacts([firstFact, secondFact]);
    const first = deferred<CharacterBatchRevertImpact>();
    const second = deferred<CharacterBatchRevertImpact>();
    const onPreviewBatchRevert = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const props = {
      workspace,
      onLoadFacts: vi.fn().mockResolvedValue(historyPage([firstFact, secondFact])),
      onPreviewBatchRevert,
      onRevertBatch: vi.fn(),
    };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    (findButton(root, "查看全部事实（2）").props.onClick as () => void)();
    root = harness.render(Component, props);
    harness.commitEffects();
    await settle();
    root = harness.render(Component, props);
    const actions = findAll(root, (element) => element.type === "button" && textContent(element) === "预览批次撤销");
    (actions[0].props.onClick as (event: { currentTarget: HTMLElement }) => void)({ currentTarget: {} as HTMLElement });
    (actions[1].props.onClick as (event: { currentTarget: HTMLElement }) => void)({ currentTarget: {} as HTMLElement });

    second.resolve(batchImpact(workspace, "batch-2", ["second-1", "second-2"]));
    await settle();
    root = harness.render(Component, props);
    expect(textContent(root)).toContain("2 条批次事实将标记为已撤销同步");

    first.resolve(batchImpact(workspace, "batch-1", ["first"]));
    await settle();
    root = harness.render(Component, props);
    expect(textContent(root)).toContain("2 条批次事实将标记为已撤销同步");
    expect((onPreviewBatchRevert.mock.calls[0][1] as AbortSignal).aborted).toBe(true);
  });

  it("preserves unsaved character drafts and dirty footer actions after a ledger mutation", async () => {
    const workspace = characterWorkspace();
    const props = {
      workspace,
      onLoadFactImpact: vi.fn().mockResolvedValue(storyFactImpact()),
      onCorrectFact: vi.fn().mockResolvedValue({ ...workspace, story_ledger_version: 20 }),
      onSave: vi.fn(),
    };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, props);
    const name = findAll(root, (element) => String(element.props.id).endsWith("field-character-name"))[0];
    (name.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "林舟的未保存名字" } });
    root = harness.render(Component, props);
    openGrowth(root);
    root = harness.render(Component, props);
    click(root, "修正");
    await settle();
    root = harness.render(Component, props);
    let drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    const correctionFields = findAll(drawer, (element) => element.type === "textarea");
    (correctionFields[0].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "新事实" } });
    (correctionFields[1].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "章节证据" } });
    root = harness.render(Component, props);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    (findButton(drawer, "创建替代事实").props.onClick as () => void)();
    await settle();
    root = harness.render(Component, props);

    const footer = findAll(root, (element) => element.props.className === "anw-character-workspace-footer")[0];
    expect(findAll(footer, (element) => element.type === "button").map(textContent))
      .toEqual(["撤销修改", "保存人物卡"]);
    (findButton(root, "基础资料").props.onClick as () => void)();
    root = harness.render(Component, props);
    expect(findAll(root, (element) => String(element.props.id).endsWith("field-character-name"))[0].props.value)
      .toBe("林舟的未保存名字");
  });

  it("ignores a late correction mutation after an external ledger snapshot replaces the scope", async () => {
    const workspace = characterWorkspace();
    const mutation = deferred<CharacterWorkspaceV2>();
    let mutationSignal: AbortSignal | undefined;
    const onCorrectFact = vi.fn((
      _factId: string,
      _command: StoryFactCorrectionCommandV1,
      signal?: AbortSignal,
    ) => {
      mutationSignal = signal;
      return mutation.promise;
    });
    const baseProps = {
      workspace,
      onCorrectFact,
      onLoadFactImpact: vi.fn().mockResolvedValue(storyFactImpact()),
    };
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, baseProps);
    openGrowth(root);
    root = harness.render(Component, baseProps);
    click(root, "修正");
    await settle();
    root = harness.render(Component, baseProps);
    let drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    const textareas = findAll(drawer, (element) => element.type === "textarea");
    (textareas[0].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "迟到替代值" } });
    (textareas[1].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "有证据" } });
    root = harness.render(Component, baseProps);
    drawer = findAll(root, (element) => element.props.className === "anw-character-drawer anw-character-correction")[0];
    (findButton(drawer, "创建替代事实").props.onClick as () => void)();

    const external = {
      ...workspace,
      story_ledger_version: 21,
      character: { ...workspace.character, name: "外部已刷新人物" },
    };
    const externalProps = { ...baseProps, workspace: external };
    root = harness.render(Component, externalProps);
    harness.commitEffects();
    root = harness.render(Component, externalProps);
    harness.commitEffects();

    mutation.resolve({
      ...workspace,
      story_ledger_version: 20,
      character: { ...workspace.character, name: "迟到响应人物" },
    });
    await settle();
    root = harness.render(Component, externalProps);
    expect(textContent(root)).toContain("外部已刷新人物");
    expect(textContent(root)).not.toContain("迟到响应人物");
    expect(mutationSignal?.aborted).toBe(true);
  });
});
