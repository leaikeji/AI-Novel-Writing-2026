import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createCharacterWorkspaceDialog,
  type CharacterReactRuntime,
} from "./character-workspace";
import type {
  CharacterWorkspaceV2,
  IntelligenceBatchRevertImpactV1,
  ProjectedFactViewV2,
} from "./contracts";
import { characterWorkspace } from "./test-fixtures";
import {
  createReactHarness,
  findAll,
  findButton,
  type FakeElement,
  settle,
  textContent,
} from "./test-harness";

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function workspaceWithSource(): CharacterWorkspaceV2 {
  const workspace = characterWorkspace();
  const source = {
    document_id: "chapter-12",
    document_title: "第十二章",
    document_position: 12,
    revision_id: "chapter-revision-12",
    revision_is_current: true,
    source_content_hash: "a".repeat(64),
    source_coordinate: "unicode-codepoint-v1" as const,
    source_start: null,
    source_end: null,
    source_range_hash: null,
    source_excerpt: "开始主动承担风险",
    source_excerpt_truncated: false,
    binding_state: "bound",
    proposal_item_id: "proposal-1",
    commit_batch_id: "batch-1",
  };
  const fact: ProjectedFactViewV2 = {
    ...workspace.writing_state.recent_changes[0],
    source_document_id: source.document_id,
    source_revision_id: source.revision_id,
    source,
  };
  return {
    ...workspace,
    projected_state: { ...workspace.projected_state, current_facts: [fact] },
    writing_state: { ...workspace.writing_state, recent_changes: [fact] },
  };
}

function openGrowth(root: FakeElement): void {
  (findButton(root, "状态与经历").props.onClick as () => void)();
}

function clickWithCurrentTarget(root: FakeElement, label: string, trigger: HTMLElement): void {
  (findButton(root, label).props.onClick as (
    event: { readonly currentTarget: HTMLElement },
  ) => void)({ currentTarget: trigger });
}

function workspaceDialog(root: FakeElement): FakeElement {
  return findAll(root, (element) => (
    element.props.className === "anw-character-workspace-dialog"
  ))[0];
}

class FocusElement {
  readonly dataset: Record<string, string> = {};
  readonly attributes = new Map<string, string>();
  readonly id: string;
  disabled = false;
  isConnected = true;
  focusCount = 0;
  blurCount = 0;
  focusable: FocusElement[] = [];
  closeButton: FocusElement | null = null;
  owner: FocusDocument | null = null;

  constructor(id: string) {
    this.id = id;
  }

  focus(): void {
    this.focusCount += 1;
    if (this.owner) this.owner.activeElement = this;
  }

  blur(): void {
    this.blurCount += 1;
    if (this.owner?.activeElement === this) this.owner.activeElement = null;
  }

  querySelector<T>(): T | null {
    return this.closeButton && !this.closeButton.disabled
      ? this.closeButton as T
      : null;
  }

  querySelectorAll<T>(): T[] {
    return this.focusable.filter((element) => !element.disabled) as T[];
  }

  closest(): null {
    return null;
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }
}

class FocusDocument {
  activeElement: FocusElement | null = null;
  readonly nodes = new Map<string, FocusElement>();

  add(element: FocusElement): FocusElement {
    element.owner = this;
    this.nodes.set(element.id, element);
    return element;
  }

  getElementById(id: string): FocusElement | null {
    return this.nodes.get(id) ?? null;
  }
}

function installFocusDocument(): FocusDocument {
  const focusDocument = new FocusDocument();
  vi.stubGlobal("HTMLElement", FocusElement);
  vi.stubGlobal("document", focusDocument);
  return focusDocument;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("character workspace nested drawer focus", () => {
  it("keeps drawer and title ids unique when the same character is mounted twice", () => {
    const workspace = characterWorkspace();
    const firstHarness = createReactHarness();
    const secondHarness = createReactHarness();
    const First = createCharacterWorkspaceDialog({
      ...firstHarness.React,
      useId: () => ":workspace-a:",
    });
    const Second = createCharacterWorkspaceDialog({
      ...secondHarness.React,
      useId: () => ":workspace-b:",
    });

    let firstRoot = firstHarness.render(First, { workspace });
    let secondRoot = secondHarness.render(Second, { workspace });
    openGrowth(firstRoot);
    openGrowth(secondRoot);
    firstRoot = firstHarness.render(First, { workspace });
    secondRoot = secondHarness.render(Second, { workspace });
    clickWithCurrentTarget(firstRoot, "修正", {} as HTMLElement);
    clickWithCurrentTarget(secondRoot, "修正", {} as HTMLElement);
    firstRoot = firstHarness.render(First, { workspace });
    secondRoot = secondHarness.render(Second, { workspace });

    const firstDrawer = findAll(firstRoot, (element) => (
      element.props.className === "anw-character-drawer anw-character-correction"
    ))[0];
    const secondDrawer = findAll(secondRoot, (element) => (
      element.props.className === "anw-character-drawer anw-character-correction"
    ))[0];
    expect(firstDrawer.props.id).not.toBe(secondDrawer.props.id);
    expect(firstDrawer.props["aria-labelledby"]).not.toBe(
      secondDrawer.props["aria-labelledby"],
    );
    expect(findAll(firstDrawer, (element) => element.type === "h3")[0].props.id)
      .toBe(firstDrawer.props["aria-labelledby"]);
    expect(findAll(secondDrawer, (element) => element.type === "h3")[0].props.id)
      .toBe(secondDrawer.props["aria-labelledby"]);
  });

  it("uses currentTarget, derives a unique correction title, traps Tab, and restores focus", async () => {
    const workspace = characterWorkspace();
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace });
    harness.commitEffects();
    openGrowth(root);
    root = harness.render(Component, { workspace });

    const focusDocument = installFocusDocument();
    const parentDialog = focusDocument.add(new FocusElement("character-workspace-character-1-dialog"));
    const drawerNode = focusDocument.add(new FocusElement("character-workspace-character-1-correction-dialog"));
    const closeNode = focusDocument.add(new FocusElement("correction-close"));
    const fieldNode = focusDocument.add(new FocusElement("correction-field"));
    const trigger = focusDocument.add(new FocusElement("correction-trigger"));
    const decoy = focusDocument.add(new FocusElement("active-element-decoy"));
    drawerNode.closeButton = closeNode;
    drawerNode.focusable = [closeNode, fieldNode];
    parentDialog.focusable = [trigger];
    decoy.focus();

    clickWithCurrentTarget(root, "修正", trigger as unknown as HTMLElement);
    root = harness.render(Component, { workspace });
    harness.commitEffects();
    await settle();

    const drawer = findAll(root, (element) => (
      element.props.id === "character-workspace-character-1-correction-dialog"
    ))[0];
    const heading = findAll(drawer, (element) => element.type === "h3")[0];
    expect(drawer.props["aria-labelledby"]).toBe("character-workspace-character-1-correction-title");
    expect(heading.props.id).toBe(drawer.props["aria-labelledby"]);
    expect(focusDocument.activeElement).toBe(closeNode);

    for (const className of [
      "anw-character-workspace-summary",
      "anw-character-workspace-tabs",
      "anw-character-workspace-body",
      "anw-character-workspace-footer",
    ]) {
      const region = findAll(root, (element) => element.props.className === className)[0];
      expect(region.props.inert).toBe("");
      expect(region.props["aria-hidden"]).toBe(true);
    }

    fieldNode.focus();
    const preventForward = vi.fn();
    (workspaceDialog(root).props.onKeyDown as (event: unknown) => void)({
      key: "Tab",
      preventDefault: preventForward,
    });
    expect(preventForward).toHaveBeenCalledOnce();
    expect(focusDocument.activeElement).toBe(closeNode);

    const preventBackward = vi.fn();
    (workspaceDialog(root).props.onKeyDown as (event: unknown) => void)({
      key: "Tab",
      shiftKey: true,
      preventDefault: preventBackward,
    });
    expect(preventBackward).toHaveBeenCalledOnce();
    expect(focusDocument.activeElement).toBe(fieldNode);

    (findButton(drawer, "×").props.onClick as () => void)();
    root = harness.render(Component, { workspace });
    harness.commitEffects();
    await settle();
    expect(findAll(root, (element) => element.props.id === drawer.props.id)).toHaveLength(0);
    expect(focusDocument.activeElement).toBe(trigger);
    expect(decoy.focusCount).toBe(1);
  });

  it("falls back to the recent-changes heading after its trigger is unmounted", async () => {
    const workspace = characterWorkspace();
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace });
    harness.commitEffects();
    openGrowth(root);
    root = harness.render(Component, { workspace });

    const focusDocument = installFocusDocument();
    const drawerNode = focusDocument.add(new FocusElement("character-workspace-character-1-correction-dialog"));
    const closeNode = focusDocument.add(new FocusElement("correction-close"));
    const fallback = focusDocument.add(new FocusElement("character-workspace-character-1-recent-changes-title"));
    const trigger = focusDocument.add(new FocusElement("removed-trigger"));
    drawerNode.closeButton = closeNode;
    trigger.isConnected = false;

    clickWithCurrentTarget(root, "修正", trigger as unknown as HTMLElement);
    root = harness.render(Component, { workspace });
    harness.commitEffects();
    await settle();
    const drawer = findAll(root, (element) => element.props.id === drawerNode.id)[0];
    (findButton(drawer, "×").props.onClick as () => void)();
    root = harness.render(Component, { workspace });
    harness.commitEffects();
    await settle();

    expect(focusDocument.activeElement).toBe(fallback);
  });

  it("allows Escape while a source is loading and drops late or superseded responses", async () => {
    const workspace = workspaceWithSource();
    const first = deferred<{
      id: string;
      document_id: string;
      revision_number: number;
      content_hash: string;
      content_markdown: string;
      content_text: string;
    }>();
    const secondRevision = {
      id: "revision-new",
      document_id: "chapter-12",
      revision_number: 2,
      content_hash: "a".repeat(64),
      content_markdown: "新版本",
      content_text: "新版本",
    };
    const onLoadSource = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce(secondRevision);
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace, onLoadSource });
    openGrowth(root);
    root = harness.render(Component, { workspace, onLoadSource });
    const trigger = {} as HTMLElement;

    clickWithCurrentTarget(root, "查看来源", trigger);
    root = harness.render(Component, { workspace, onLoadSource });
    let sourceDrawer = findAll(root, (element) => (
      element.props.id === "character-workspace-character-1-source-dialog"
    ))[0];
    expect(sourceDrawer.props["aria-labelledby"]).toBe("character-workspace-character-1-source-title");
    expect(sourceDrawer.props["aria-busy"]).toBe(true);
    expect(findButton(sourceDrawer, "×").props.disabled).not.toBe(true);

    const preventClose = vi.fn();
    (workspaceDialog(root).props.onKeyDown as (event: unknown) => void)({
      key: "Escape",
      preventDefault: preventClose,
    });
    expect(preventClose).toHaveBeenCalledOnce();
    root = harness.render(Component, { workspace, onLoadSource });
    expect(findAll(root, (element) => element.props.id === sourceDrawer.props.id)).toHaveLength(0);

    clickWithCurrentTarget(root, "查看来源", trigger);
    await settle();
    root = harness.render(Component, { workspace, onLoadSource });
    sourceDrawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-source-dialog")[0];
    expect(textContent(sourceDrawer)).toContain("revision 2");

    first.resolve({
      id: "revision-old",
      document_id: "chapter-12",
      revision_number: 1,
      content_hash: "a".repeat(64),
      content_markdown: "旧版本",
      content_text: "旧版本",
    });
    await settle();
    root = harness.render(Component, { workspace, onLoadSource });
    sourceDrawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-source-dialog")[0];
    expect(textContent(sourceDrawer)).toContain("revision 2");
    expect(textContent(sourceDrawer)).not.toContain("revision 1");
  });

  it("disables correction close paths and exposes busy semantics while saving", async () => {
    const workspace = characterWorkspace();
    const save = deferred<CharacterWorkspaceV2>();
    const onCorrectFact = vi.fn(() => save.promise);
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace, onCorrectFact });
    openGrowth(root);
    root = harness.render(Component, { workspace, onCorrectFact });
    clickWithCurrentTarget(root, "修正", {} as HTMLElement);
    root = harness.render(Component, { workspace, onCorrectFact });
    let drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-correction-dialog")[0];
    const textareas = findAll(drawer, (element) => element.type === "textarea");
    (textareas[0].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "新的事实" } });
    (textareas[1].props.onChange as (event: { target: { value: string } }) => void)({ target: { value: "有明确章节证据" } });
    root = harness.render(Component, { workspace, onCorrectFact });
    drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-correction-dialog")[0];
    (findButton(drawer, "创建替代事实").props.onClick as () => void)();
    root = harness.render(Component, { workspace, onCorrectFact });
    drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-correction-dialog")[0];

    expect(drawer.props["aria-busy"]).toBe(true);
    expect(findButton(drawer, "×").props.disabled).toBe(true);
    expect(findButton(drawer, "取消").props.disabled).toBe(true);
    expect(textContent(drawer)).toContain("完成前无法关闭");
    const preventClose = vi.fn();
    (workspaceDialog(root).props.onKeyDown as (event: unknown) => void)({ key: "Escape", preventDefault: preventClose });
    root = harness.render(Component, { workspace, onCorrectFact });
    expect(preventClose).toHaveBeenCalledOnce();
    expect(findAll(root, (element) => element.props.id === drawer.props.id)).toHaveLength(1);

    save.resolve({ ...workspace, story_ledger_version: 20 });
    await settle();
  });

  it("derives the batch title and disables all batch close paths while saving", async () => {
    const workspace = workspaceWithSource();
    const impact: IntelligenceBatchRevertImpactV1 = {
      batch_id: "batch-1",
      state: "ready",
      already_reverted: false,
      facts: [{ id: "fact-1", disposition: "supersede" }],
      relationships: [],
    };
    const save = deferred<CharacterWorkspaceV2>();
    const onLoadFacts = vi.fn().mockResolvedValue({
      schema_version: "character-fact-history/1" as const,
      items: workspace.projected_state.current_facts,
      next_cursor: null,
      total_summary: workspace.writing_state.history_summary,
    });
    const onPreviewBatchRevert = vi.fn().mockResolvedValue(impact);
    const onRevertBatch = vi.fn(() => save.promise);
    const harness = createReactHarness();
    const Component = createCharacterWorkspaceDialog(harness.React);
    let root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    harness.commitEffects();
    openGrowth(root);
    root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    (findButton(root, "查看全部事实（1）").props.onClick as () => void)();
    root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    harness.commitEffects();
    await settle();
    root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    clickWithCurrentTarget(root, "撤销同步", {} as HTMLElement);
    await settle();
    root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    let drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-batch-revert-dialog")[0];
    const heading = findAll(drawer, (element) => element.type === "h3")[0];
    expect(drawer.props["aria-labelledby"]).toBe("character-workspace-character-1-batch-revert-title");
    expect(heading.props.id).toBe(drawer.props["aria-labelledby"]);
    (findButton(drawer, "确认撤销同步").props.onClick as () => void)();
    root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    drawer = findAll(root, (element) => element.props.id === "character-workspace-character-1-batch-revert-dialog")[0];

    expect(drawer.props["aria-busy"]).toBe(true);
    expect(findButton(drawer, "×").props.disabled).toBe(true);
    expect(findButton(drawer, "取消").props.disabled).toBe(true);
    expect(textContent(drawer)).toContain("完成前无法关闭");
    const preventClose = vi.fn();
    (workspaceDialog(root).props.onKeyDown as (event: unknown) => void)({ key: "Escape", preventDefault: preventClose });
    root = harness.render(Component, { workspace, onLoadFacts, onPreviewBatchRevert, onRevertBatch });
    expect(preventClose).toHaveBeenCalledOnce();
    expect(findAll(root, (element) => element.props.id === drawer.props.id)).toHaveLength(1);

    save.resolve({ ...workspace, story_ledger_version: 20 });
    await settle();
  });

  it.each([
    ["pointer", true],
    ["keyboard", false],
  ] as const)("preserves the whole-card %s focus restoration contract", async (modality, shouldBlur) => {
    const focusDocument = installFocusDocument();
    const style = focusDocument.add(new FocusElement("anw-character-workspace-styles"));
    const opener = focusDocument.add(new FocusElement(`opener-${modality}`));
    const dialog = focusDocument.add(new FocusElement("character-workspace-character-1-dialog"));
    opener.dataset.characterOpenModality = modality;
    opener.focus();
    const cleanups: Array<() => void> = [];
    const React: CharacterReactRuntime = {
      createElement(type, props, ...children): FakeElement {
        return { type, props: props ?? {}, children };
      },
      useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
        return [typeof initial === "function" ? (initial as () => T)() : initial, () => undefined];
      },
      useRef<T>(initial: T): { current: T } {
        return { current: initial };
      },
      useEffect(effect): void {
        const cleanup = effect();
        if (typeof cleanup === "function") cleanups.push(cleanup);
      },
    };
    const Component = createCharacterWorkspaceDialog(React);
    Component({ workspace: characterWorkspace() });
    await settle();
    expect(focusDocument.activeElement).toBe(dialog);

    cleanups.reverse().forEach((cleanup) => cleanup());
    expect(opener.focusCount).toBe(2);
    expect(opener.blurCount).toBe(shouldBlur ? 1 : 0);
    expect(opener.dataset.characterOpenModality).toBeUndefined();
    expect(style.id).toBe("anw-character-workspace-styles");
  });
});
