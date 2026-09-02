import { describe, expect, it, vi } from "vitest";

import type {
  StoryLedgerBatchImpactPreview,
  StoryLedgerFactDetail,
  StoryLedgerFactImpactPreview,
  StoryLedgerFactItem,
  StoryLedgerFactPage,
  StoryLedgerSourceExcerpt,
  StoryLedgerSummary,
} from "./contracts";
import {
  createStoryLedgerWorkspace,
  type StoryLedgerWorkspaceApi,
  type StoryLedgerWorkspaceProps,
  type StoryLedgerWorkspaceReactRuntime,
} from "./workspace";

interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}

interface EffectRecord {
  readonly dependencies: readonly unknown[];
  readonly cleanup?: () => void;
}

function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((value, index) => Object.is(value, right[index])));
}

function createHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pendingEffects: Array<{
    readonly index: number;
    readonly effect: () => void | (() => void);
    readonly dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;

  const React: StoryLedgerWorkspaceReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function"
        ? (initial as () => T)()
        : initial;
      return [
        states[index] as T,
        (next) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        },
      ];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
      pendingEffects.push({ index, effect, dependencies: [...dependencies] });
    },
    useId(): string {
      return "workspace-test";
    },
  };

  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const pending = pendingEffects;
      pendingEffects = [];
      pending.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          ...(typeof cleanup === "function" ? { cleanup } : {}),
        };
      });
    },
  };
}

function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}

function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}

function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}

function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(
    root,
    (element) => element.type === "button" && textContent(element) === label,
  )[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}

async function settle(rounds = 12): Promise<void> {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const timeline = {
  mode: "multiple",
  timeline_id: "timeline-branch",
  timeline_name: "雨夜分支",
  narrative_cutoff: 18,
} as const;

function fact(id = "fact-1", overrides: Partial<StoryLedgerFactItem> = {}): StoryLedgerFactItem {
  return {
    id,
    fact_type: "character_state",
    subject: id === "fact-1" ? "林舟" : "闻川",
    predicate: "location",
    object_preview: id === "fact-1" ? "林舟位于北塔" : "闻川位于旧港",
    object_truncated: false,
    timeline_id: "timeline-branch",
    dimension: "location",
    event_kind: null,
    story_sequence: id === "fact-1" ? 8 : 9,
    created_at: "2026-09-01T00:00:00Z",
    effective_state: "current",
    effective_reason_codes: ["active_and_selected"],
    included_in_current_projection: true,
    health: "ok",
    health_reason_codes: [],
    entities: [],
    source: {
      source_document_id: "chapter-8",
      document_title: "第八章",
      document_position: 8,
      source_revision_id: "revision-8",
      revision_number: 2,
      revision_is_current: true,
      source_content_hash: "hash",
      source_start: 1,
      source_end: 4,
      binding_state: "current",
      commit_batch_id: "batch-8",
      evidence_available: true,
    },
    ...overrides,
  };
}

function summary(
  token = "snapshot-1",
  filterHash = "filter-all",
  overrides: Partial<StoryLedgerSummary> = {},
): StoryLedgerSummary {
  return {
    schema_version: "story-ledger-summary/1",
    novel_id: "novel-1",
    ledger_snapshot_token: token,
    story_ledger_version: token === "snapshot-1" ? 19 : 20,
    timeline,
    filter_sha256: filterHash,
    total: 2,
    by_fact_type: { character_state: 2 },
    by_effective_state: {
      current: 1,
      historical: 0,
      superseded: 0,
      source_invalid: 1,
      batch_reverted: 0,
    },
    by_health: { ok: 1, conflict: 1, ambiguous: 0 },
    review_required: 1,
    ...overrides,
  };
}

function page(
  items: readonly StoryLedgerFactItem[] = [fact("fact-1"), fact("fact-2")],
  token = "snapshot-1",
  filterHash = "filter-all",
  nextCursor: string | null = null,
): StoryLedgerFactPage {
  return {
    schema_version: "story-ledger-page/1",
    novel_id: "novel-1",
    ledger_snapshot_token: token,
    story_ledger_version: token === "snapshot-1" ? 19 : 20,
    timeline,
    filter_sha256: filterHash,
    items,
    next_cursor: nextCursor,
  };
}

function detail(id = "fact-1", token = "snapshot-1"): StoryLedgerFactDetail {
  const item = fact(id);
  return {
    schema_version: "story-ledger-fact-detail/1",
    novel_id: "novel-1",
    ledger_snapshot_token: token,
    story_ledger_version: token === "snapshot-1" ? 19 : 20,
    timeline,
    item,
    object_text: `${item.subject}的完整事实内容`,
    details: { private_body: "不能进入 assistant context" },
    story_time: null,
    visibility: null,
    lifecycle_status: "active",
    schema_version_of_fact: "story-fact/3",
    event_fingerprint: null,
    event_links: [],
    bindings: [],
  };
}

function source(id = "fact-1", token = "snapshot-1"): StoryLedgerSourceExcerpt {
  return {
    schema_version: "story-ledger-source/1",
    novel_id: "novel-1",
    fact_id: id,
    ledger_snapshot_token: token,
    story_ledger_version: 19,
    timeline,
    available: true,
    unavailable_reason: null,
    document_id: "chapter-8",
    document_title: "第八章",
    document_position: 8,
    revision_id: "revision-8",
    revision_number: 2,
    revision_is_current: true,
    source_content_hash: "hash",
    source_range_hash: "range",
    source_start: 1,
    source_end: 4,
    excerpt: "绝不能进入 context 的来源摘录",
    excerpt_start: 0,
    excerpt_end: 12,
    highlight_start: 1,
    highlight_end: 4,
    truncated_before: false,
    truncated_after: false,
  };
}

function factImpact(id = "fact-1", token = "snapshot-1"): StoryLedgerFactImpactPreview {
  return {
    schema_version: "story-ledger-fact-impact-preview/1",
    novel_id: "novel-1",
    fact_id: id,
    preview_snapshot_token: token,
    story_ledger_version: 19,
    timeline,
    currently_in_projection: true,
    current_projection_fact_count: 2,
    related_event_link_count: 1,
    embedding_rebuild_required: true,
    commit_batch_ids: ["batch-8"],
    batch_fact_count: 2,
    batch_relationship_count: 1,
    correction_supported: true,
    correction_block_reason: null,
  };
}

function batchImpact(token = "snapshot-1"): StoryLedgerBatchImpactPreview {
  return {
    schema_version: "story-ledger-batch-impact-preview/1",
    novel_id: "novel-1",
    batch_id: "batch-8",
    preview_snapshot_token: token,
    story_ledger_version: 19,
    timeline,
    state: "committed",
    already_reverted: false,
    batch_fact_count: 2,
    batch_relationship_count: 1,
    facts: [{ id: "fact-1", disposition: "supersede" }],
    relationships: [{ id: "relationship-1", disposition: "preserve_root_reproject_visibility" }],
  };
}

function createApi(overrides: Partial<StoryLedgerWorkspaceApi> = {}): StoryLedgerWorkspaceApi {
  return {
    loadSummary: vi.fn().mockResolvedValue(summary()),
    loadFacts: vi.fn().mockResolvedValue(page()),
    loadDetail: vi.fn().mockImplementation((_scope, id) => Promise.resolve(detail(id))),
    loadSource: vi.fn().mockImplementation((_scope, id) => Promise.resolve(source(id))),
    loadFactImpact: vi.fn().mockImplementation((_scope, id) => Promise.resolve(factImpact(id))),
    loadBatchImpact: vi.fn().mockResolvedValue(batchImpact()),
    correctFact: vi.fn().mockResolvedValue({ replayed: false, story_ledger_version: 20, fact: {} }),
    revertBatch: vi.fn().mockResolvedValue({ replayed: false, story_ledger_version: 20, batch_id: "batch-8" }),
    ...overrides,
  };
}

const baseProps: StoryLedgerWorkspaceProps = {
  novelId: "novel-1",
  timelineId: "timeline-branch",
  timelineOptions: [
    { id: "timeline-main", name: "主线" },
    { id: "timeline-branch", name: "雨夜分支" },
  ],
};

async function loadWorkspace(
  api: StoryLedgerWorkspaceApi,
  props: StoryLedgerWorkspaceProps = baseProps,
) {
  const harness = createHarness();
  const Component = createStoryLedgerWorkspace(harness.React, api);
  let root = harness.render(Component, props);
  harness.commitEffects();
  await settle();
  root = harness.render(Component, props);
  harness.commitEffects();
  await settle();
  root = harness.render(Component, props);
  return { harness, Component, root, props };
}

describe("whole-book story ledger workspace", () => {
  it("loads summary then a server page on one snapshot and exposes only safe context metadata", async () => {
    const onContextChange = vi.fn();
    const onSnapshotChange = vi.fn();
    const onTimelineChange = vi.fn();
    const props = { ...baseProps, onContextChange, onSnapshotChange, onTimelineChange };
    const api = createApi();
    const rendered = await loadWorkspace(api, props);

    expect(api.loadSummary).toHaveBeenCalledWith(
      expect.objectContaining({ novelId: "novel-1", timelineId: "timeline-branch" }),
      {},
      expect.any(AbortSignal),
    );
    expect(api.loadFacts).toHaveBeenCalledWith(
      expect.objectContaining({ snapshotToken: "snapshot-1" }),
      expect.objectContaining({ limit: 40 }),
      expect.any(AbortSignal),
    );
    expect(onSnapshotChange).toHaveBeenCalledWith("snapshot-1", 19);
    expect(textContent(rendered.root)).toContain("账本总览");
    expect(textContent(rendered.root)).toContain("当前有效1");
    expect(textContent(rendered.root)).toContain("核对队列（1）");
    expect(textContent(rendered.root)).toContain("雨夜分支");

    (findButton(rendered.root, "查看").props.onClick as (event: unknown) => void)({
      currentTarget: { focus: vi.fn() },
    });
    let root = rendered.harness.render(rendered.Component, props);
    rendered.harness.commitEffects();
    await settle();
    root = rendered.harness.render(rendered.Component, props);
    rendered.harness.commitEffects();
    const context = onContextChange.mock.calls[
      onContextChange.mock.calls.length - 1
    ]?.[0] as unknown;
    const serialized = JSON.stringify(context);
    expect(serialized).toContain("fact-1");
    expect(serialized).toContain("chapter-8");
    expect(serialized).not.toContain("完整事实内容");
    expect(serialized).not.toContain("private_body");
    expect(serialized).not.toContain("来源摘录");
    expect(serialized).not.toContain("object_preview");

    const timelineSelect = findAll(
      root,
      (element) => element.type === "select" && element.props.value === "timeline-branch",
    )[0];
    (timelineSelect.props.onChange as (event: unknown) => void)({
      target: { value: "timeline-main" },
    });
    expect(onTimelineChange).toHaveBeenCalledWith("timeline-main");
  });

  it("does not refetch when the owner echoes the snapshot just observed by the workspace", async () => {
    const onSnapshotChange = vi.fn();
    const api = createApi();
    const props = { ...baseProps, onSnapshotChange };
    const rendered = await loadWorkspace(api, props);

    expect(onSnapshotChange).toHaveBeenCalledWith("snapshot-1", 19);
    expect(api.loadSummary).toHaveBeenCalledTimes(1);
    expect(api.loadFacts).toHaveBeenCalledTimes(1);

    rendered.harness.render(rendered.Component, {
      ...props,
      snapshotToken: "snapshot-1",
    });
    rendered.harness.commitEffects();
    await settle();

    expect(api.loadSummary).toHaveBeenCalledTimes(1);
    expect(api.loadFacts).toHaveBeenCalledTimes(1);
  });

  it("aborts an append immediately when combined filters change and never mixes the old page", async () => {
    const append = deferred<StoryLedgerFactPage>();
    const loadFacts = vi.fn().mockImplementation((_scope, query) => {
      if (query.cursor) return append.promise;
      if (query.reviewOnly) {
        return Promise.resolve(page([
          fact("fact-review", { health: "conflict", subject: "待核对事实" }),
        ], "snapshot-1", "filter-review"));
      }
      return Promise.resolve(page([fact("fact-1")], "snapshot-1", "filter-all", "cursor-1"));
    });
    const loadSummary = vi.fn().mockImplementation((_scope, filters) => Promise.resolve(
      filters.reviewOnly
        ? summary("snapshot-1", "filter-review", { total: 1, review_required: 1 })
        : summary("snapshot-1", "filter-all"),
    ));
    const api = createApi({ loadFacts, loadSummary });
    const rendered = await loadWorkspace(api);

    (findButton(rendered.root, "加载更多事实").props.onClick as () => void)();
    const appendSignal = loadFacts.mock.calls[
      loadFacts.mock.calls.length - 1
    ]?.[2] as AbortSignal;
    expect(appendSignal.aborted).toBe(false);
    (findButton(rendered.root, "核对队列（1）").props.onClick as () => void)();
    expect(appendSignal.aborted).toBe(true);

    let root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();
    append.resolve(page([fact("fact-stale", { subject: "迟到旧页" })], "snapshot-1", "filter-all"));
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);

    expect(textContent(root)).toContain("待核对事实");
    expect(textContent(root)).not.toContain("迟到旧页");
    expect(loadSummary).toHaveBeenLastCalledWith(
      expect.anything(),
      expect.objectContaining({ reviewOnly: true }),
      expect.any(AbortSignal),
    );
  });

  it("rejects an append whose response token changes instead of merging snapshots", async () => {
    const loadFacts = vi.fn().mockImplementation((_scope, query) => (
      query.cursor
        ? Promise.resolve(page([fact("fact-new", { subject: "新快照事实" })], "snapshot-2", "filter-all"))
        : Promise.resolve(page([fact("fact-1")], "snapshot-1", "filter-all", "cursor-1"))
    ));
    const rendered = await loadWorkspace(createApi({ loadFacts }));

    (findButton(rendered.root, "加载更多事实").props.onClick as () => void)();
    await settle();
    const root = rendered.harness.render(rendered.Component, baseProps);

    expect(textContent(root)).toContain("林舟位于北塔");
    expect(textContent(root)).not.toContain("新快照事实");
    expect(textContent(root)).toContain("未追加过期页面");
  });

  it("isolates detail selections and ignores a late detail for the previous fact", async () => {
    const first = deferred<StoryLedgerFactDetail>();
    const second = deferred<StoryLedgerFactDetail>();
    const loadDetail = vi.fn().mockImplementation((_scope, id) => (
      id === "fact-1" ? first.promise : second.promise
    ));
    const api = createApi({ loadDetail });
    const rendered = await loadWorkspace(api);
    const viewButtons = findAll(
      rendered.root,
      (element) => element.type === "button" && textContent(element) === "查看",
    );

    (viewButtons[0].props.onClick as (event: unknown) => void)({
      currentTarget: { focus: vi.fn() },
    });
    let root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();
    const firstSignal = loadDetail.mock.calls[0][2] as AbortSignal;
    (findAll(root, (element) => element.type === "button" && textContent(element) === "查看")[1]
      .props.onClick as (event: unknown) => void)({
        currentTarget: { focus: vi.fn() },
      });
    expect(firstSignal.aborted).toBe(true);
    root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();

    second.resolve(detail("fact-2"));
    first.resolve(detail("fact-1"));
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);
    expect(textContent(root)).toContain("闻川的完整事实内容");
    expect(textContent(root)).not.toContain("林舟的完整事实内容");
  });

  it("keeps the active detail request when the owner echoes the selected fact into the deep link", async () => {
    const pendingDetail = deferred<StoryLedgerFactDetail>();
    const loadDetail = vi.fn().mockReturnValue(pendingDetail.promise);
    const onContextChange = vi.fn();
    const props = { ...baseProps, onContextChange };
    const rendered = await loadWorkspace(createApi({ loadDetail }), props);

    (findButton(rendered.root, "查看").props.onClick as (event: unknown) => void)({
      currentTarget: { focus: vi.fn() },
    });

    let root = rendered.harness.render(rendered.Component, props);
    rendered.harness.commitEffects();
    expect(onContextChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ selectedFactId: "fact-1" }),
    );
    const detailSignal = loadDetail.mock.calls[0][2] as AbortSignal;
    expect(detailSignal.aborted).toBe(false);

    const echoedProps = { ...props, initialFactId: "fact-1" };
    root = rendered.harness.render(rendered.Component, echoedProps);
    rendered.harness.commitEffects();
    expect(detailSignal.aborted).toBe(false);

    pendingDetail.resolve(detail("fact-1"));
    await settle();
    root = rendered.harness.render(rendered.Component, echoedProps);
    rendered.harness.commitEffects();
    expect(textContent(root)).toContain("林舟的完整事实内容");
  });

  it("opens a fact supplied by a validated ledger deep link", async () => {
    const loadDetail = vi.fn().mockImplementation((_scope, id) => Promise.resolve(detail(id)));
    const props = { ...baseProps, initialFactId: "fact-2" };
    const rendered = await loadWorkspace(createApi({ loadDetail }), props);

    expect(loadDetail).toHaveBeenCalledWith(
      expect.objectContaining({ snapshotToken: "snapshot-1" }),
      "fact-2",
      expect.any(AbortSignal),
    );
    expect(textContent(rendered.root)).toContain("闻川的完整事实内容");
  });

  it("aborts late source and both preview kinds on a filter scope change", async () => {
    const sourceRequest = deferred<StoryLedgerSourceExcerpt>();
    const correctionDetail = deferred<StoryLedgerFactDetail>();
    const correctionImpact = deferred<StoryLedgerFactImpactPreview>();
    const batchRequest = deferred<StoryLedgerBatchImpactPreview>();
    const loadSource = vi.fn().mockReturnValue(sourceRequest.promise);
    const loadDetail = vi.fn().mockReturnValue(correctionDetail.promise);
    const loadFactImpact = vi.fn().mockReturnValue(correctionImpact.promise);
    const loadBatchImpact = vi.fn().mockReturnValue(batchRequest.promise);
    const api = createApi({ loadSource, loadDetail, loadFactImpact, loadBatchImpact });
    const rendered = await loadWorkspace(api);

    let root = rendered.root;
    (findButton(root, "更多").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, baseProps);
    (findButton(root, "查看来源").props.onClick as (event: unknown) => void)({ currentTarget: {} });
    const sourceSignal = loadSource.mock.calls[0][2] as AbortSignal;
    (findButton(root, "核对队列（1）").props.onClick as () => void)();
    expect(sourceSignal.aborted).toBe(true);
    sourceRequest.resolve(source());
    root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);
    expect(textContent(root)).not.toContain("绝不能进入 context 的来源摘录");

    (findButton(root, "更多").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, baseProps);
    (findButton(root, "修正事实").props.onClick as (event: unknown) => void)({ currentTarget: {} });
    const correctionDetailSignal = loadDetail.mock.calls[
      loadDetail.mock.calls.length - 1
    ]?.[2] as AbortSignal;
    const correctionImpactSignal = loadFactImpact.mock.calls[
      loadFactImpact.mock.calls.length - 1
    ]?.[2] as AbortSignal;
    (findButton(root, "核对队列（1）").props.onClick as () => void)();
    expect(correctionDetailSignal.aborted).toBe(true);
    expect(correctionImpactSignal.aborted).toBe(true);
    correctionDetail.resolve(detail());
    correctionImpact.resolve(factImpact());
    root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);
    expect(textContent(root)).not.toContain("创建替代事实");

    (findButton(root, "更多").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, baseProps);
    (findButton(root, "预览撤销第 8 章同步").props.onClick as (event: unknown) => void)({ currentTarget: {} });
    const batchSignal = loadBatchImpact.mock.calls[0][2] as AbortSignal;
    (findButton(root, "核对队列（1）").props.onClick as () => void)();
    expect(batchSignal.aborted).toBe(true);
    batchRequest.resolve(batchImpact());
    root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);
    expect(textContent(root)).not.toContain("确认撤销同步");
  });

  it("fences a mutation late response while preserving server-safe operation semantics", async () => {
    const mutation = deferred<{ replayed: boolean; story_ledger_version: number; fact: {} }>();
    const correctFact = vi.fn().mockReturnValue(mutation.promise);
    const loadSummary = vi.fn().mockImplementation((_scope, filters) => Promise.resolve(
      filters.reviewOnly
        ? summary("snapshot-1", "filter-review", { total: 1 })
        : summary(),
    ));
    const loadFacts = vi.fn().mockImplementation((_scope, query) => Promise.resolve(
      query.reviewOnly
        ? page([fact("fact-review", { subject: "筛选后事实", health: "conflict" })], "snapshot-1", "filter-review")
        : page(),
    ));
    const api = createApi({ correctFact, loadSummary, loadFacts });
    const rendered = await loadWorkspace(api);
    let root = rendered.root;

    (findButton(root, "更多").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, baseProps);
    (findButton(root, "修正事实").props.onClick as (event: unknown) => void)({
      currentTarget: { focus: vi.fn() },
    });
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);
    const textareas = findAll(root, (element) => element.type === "textarea");
    (textareas[0].props.onChange as (event: unknown) => void)({ target: { value: "替代后的事实" } });
    (textareas[1].props.onChange as (event: unknown) => void)({ target: { value: "原文证据明确" } });
    root = rendered.harness.render(rendered.Component, baseProps);
    (findButton(root, "创建替代事实").props.onClick as () => void)();
    const mutationSignal = correctFact.mock.calls[0][3] as AbortSignal;
    const command = correctFact.mock.calls[0][2] as { operation_key: string };
    expect(command.operation_key).toMatch(/^story-ledger-correction:/);
    expect(mutationSignal.aborted).toBe(false);

    (findButton(root, "核对队列（1）").props.onClick as () => void)();
    expect(mutationSignal.aborted).toBe(true);
    root = rendered.harness.render(rendered.Component, baseProps);
    rendered.harness.commitEffects();
    mutation.resolve({ replayed: false, story_ledger_version: 20, fact: {} });
    await settle();
    root = rendered.harness.render(rendered.Component, baseProps);

    expect(textContent(root)).toContain("筛选后事实");
    expect(textContent(root)).not.toContain("替代后的事实");
    expect(loadSummary).toHaveBeenCalledTimes(2);
  });

  it("renders a recoverable workspace error and live status", async () => {
    const api = createApi({
      loadSummary: vi.fn().mockRejectedValue(new Error("服务端暂不可用")),
    });
    const rendered = await loadWorkspace(api);

    expect(textContent(rendered.root)).toContain("服务端暂不可用");
    expect(findAll(rendered.root, (element) => element.props.role === "alert").length)
      .toBeGreaterThan(0);
    expect(findAll(rendered.root, (element) => (
      element.props.role === "status" && element.props["aria-live"] === "polite"
    ))).toHaveLength(1);
    expect(findButton(rendered.root, "重新加载")).toBeTruthy();
  });
});
