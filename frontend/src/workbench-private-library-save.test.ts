/** Actual Workbench callbacks with deterministic hooks and I/O; not product acceptance. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AIApplyMeta } from "./assistant-fields";
import type { DocumentRecord, NovelRecord, SelectionLibraryApplication } from "./types";
import type { RecoveryDraft, RecoveryDraftIdentity } from "./recovery";
import type { CreateChapterEditorSurfaceOptions } from "./narration/chapter-editor-surface";

const io = vi.hoisted(() => ({
  request: vi.fn(), model: vi.fn(), loadNovel: vi.fn(), loadRecovery: vi.fn(),
  saveRecovery: vi.fn(), replaceRecovery: vi.fn(), clearRecovery: vi.fn(),
  surface: vi.fn(), bodyScope: vi.fn(), gate: vi.fn(), confirm: vi.fn(),
}));
vi.mock("./api", async (original) => ({
  ...await original<typeof import("./api")>(), apiRequest: io.request, getGenerationModelStatus: io.model,
}));
vi.mock("./recovery", async (original) => ({
  ...await original<typeof import("./recovery")>(), loadRecoveryDraft: io.loadRecovery,
  saveRecoveryDraft: io.saveRecovery, replaceRecoveryDraftIfCurrent: io.replaceRecovery,
  clearRecoveryDraftIfCurrent: io.clearRecovery,
}));
vi.mock("./novel-navigation/api", () => ({ loadNovelWorkspace: io.loadNovel }));
vi.mock("./workbench-studio", () => ({ StudioProjectView: "studio-project" }));
vi.mock("./chapter-workflow", async (original) => ({
  ...await original<typeof import("./chapter-workflow")>(),
  ChapterWorkflowPanel: "chapter-workflow", mountChapterBodyAssistantScope: io.bodyScope,
}));
vi.mock("./assistant-context-runtime", () => ({ assistantContextRuntime: { getStatus: () => ({ scopeKind: "document" }) } }));
vi.mock("./narration/chapter-editor-surface", () => ({ createChapterEditorSurface: io.surface }));
vi.mock("./narration/chapter-capability-gate", async (original) => ({
  ...await original<typeof import("./narration/chapter-capability-gate")>(), loadChapterNarrationCapabilityGate: io.gate,
}));
vi.mock("./recycle-bin", async (original) => ({
  ...await original<typeof import("./recycle-bin")>(),
  subscribeNovelLifecycleNotices: () => () => undefined,
  subscribeNovelRecycledHttp: () => () => undefined,
}));
vi.mock("./workbench-route", async (original) => ({
  ...await original<typeof import("./workbench-route")>(),
  activeWorkbenchRoute: () => null, replaceWorkbenchHistoryUrl: vi.fn(), rememberWorkbenchLocation: vi.fn(),
}));

type Node = { type: unknown; props: Record<string, unknown>; children: unknown[] };
type Effect = { deps: readonly unknown[]; cleanup?: () => void };
function sameDeps(left: readonly unknown[] | undefined, right: readonly unknown[]): boolean {
  return Boolean(left && left.length === right.length && right.every((value, index) => Object.is(value, left[index])));
}
class Hooks {
  private slots: unknown[] = [];
  private cursor = 0;
  private effects = new Map<number, Effect>();
  private pending: (() => void)[] = [];
  nodes: Node[] = [];
  dirty = false;
  readonly parent = { scrollTo: vi.fn(), querySelector: vi.fn(() => null) };
  private memo<T>(factory: () => T, deps: readonly unknown[]): T {
    const index = this.cursor++;
    const previous = this.slots[index] as { deps: readonly unknown[]; value: T } | undefined;
    if (!sameDeps(previous?.deps, deps)) this.slots[index] = { deps, value: factory() };
    return (this.slots[index] as { value: T }).value;
  }
  private effect(run: () => void | (() => void), deps: readonly unknown[]): void {
    const index = this.cursor++;
    const previous = this.effects.get(index);
    if (!sameDeps(previous?.deps, deps)) this.pending.push(() => {
      previous?.cleanup?.();
      this.effects.set(index, { deps, cleanup: run() || undefined });
    });
  }
  React = {
    Fragment: "fragment",
    createElement: (type: unknown, props: Record<string, unknown> | null, ...children: unknown[]): Node => {
      const node = { type, props: props ?? {}, children }; this.nodes.push(node); return node;
    },
    useState: <T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] => {
      const index = this.cursor++;
      if (!(index in this.slots)) this.slots[index] = {
        value: typeof initial === "function" ? (initial as () => T)() : initial,
        set: (next: T | ((current: T) => T)) => {
          const slot = this.slots[index] as { value: T };
          const value = typeof next === "function" ? (next as (current: T) => T)(slot.value) : next;
          if (!Object.is(slot.value, value)) { slot.value = value; this.dirty = true; }
        },
      };
      const slot = this.slots[index] as { value: T; set: (next: T | ((current: T) => T)) => void };
      return [slot.value, slot.set];
    },
    useRef: <T>(initial: T): { current: T } => {
      const index = this.cursor++;
      if (!(index in this.slots)) this.slots[index] = { current: initial };
      return this.slots[index] as { current: T };
    },
    useMemo: <T>(factory: () => T, deps: readonly unknown[]) => this.memo(factory, deps),
    useCallback: <T>(callback: T, deps: readonly unknown[]) => this.memo(() => callback, deps),
    useEffect: (run: () => void | (() => void), deps: readonly unknown[]) => this.effect(run, deps),
    useLayoutEffect: (run: () => void | (() => void), deps: readonly unknown[]) => this.effect(run, deps),
  };
  render(run: () => unknown): void {
    this.cursor = 0; this.nodes = []; this.dirty = false; this.pending = [];
    run();
    for (const node of this.nodes) {
      if (node.props.className === "anw-chapter-editor-surface") {
        const ref = node.props.ref as { current: unknown }; ref.current = this.parent;
      }
    }
    this.pending.splice(0).forEach((effect) => effect());
  }
  dispose(): void { this.effects.forEach((effect) => effect.cleanup?.()); }
}

const NOVEL = "33333333-3333-4333-8333-333333333333";
const DOC_A = "11111111-1111-4111-8111-111111111111";
const DOC_B = "22222222-2222-4222-8222-222222222222";
const BODY_A = "潮声越过堤岸。";
const BODY_B = "林舟撑开锈蚀的铁门。";
const AI_TEXT = "潮水拍上木阶。";
// Distinct deterministic hash fixtures; cryptographic hashing is outside this I/O test.
const hashes = new Map<string, string>();
const sha = (value: string): string => {
  if (!hashes.has(value)) hashes.set(value, (hashes.size + 1).toString(16).padStart(64, "0"));
  return hashes.get(value)!;
};
function documentRecord(id: string, text = id === DOC_A ? BODY_A : BODY_B, version = 1): DocumentRecord {
  return { id, novel_id: NOVEL, volume_id: null, kind: "chapter", title: id === DOC_A ? "旧堤" : "铁门",
    position: id === DOC_A ? 0 : 1, version: 1, draft_version: version, base_revision_id: null,
    content_markdown: text, content_hash: sha(text), visible_character_count: text.length, updated_at: null, revisions: [] };
}
function novelRecord(): NovelRecord {
  return { id: NOVEL, title: "潮线以北", author_name: "作者", description: "旧港守堤人的故事", writing_type: "novel",
    audience: "adult", genre: "悬疑", subgenre: "", idea: "", template_key: null, template_name: "", template_data: {},
    cover_mode: "text", cover_image_data: "", cover_asset_id: null, outline_target_chapters: 0,
    highlight: "", background: "", main_plot: "", story_ledger_version: 1, version: 1, created_at: null, updated_at: null,
    tree: [{ id: null, title: "未分卷", position: 0, version: 1, documents: [documentRecord(DOC_A), documentRecord(DOC_B)] }] };
}
function application(): SelectionLibraryApplication {
  return { schema_version: "selection-library-application/1", application_id: "44444444-4444-4444-8444-444444444444",
    job_id: "55555555-5555-4555-8555-555555555555", attempt: 1, base_draft_version: 1, base_content_hash: sha(BODY_A),
    replacement_sha256: sha(AI_TEXT), library_check_report_id: "66666666-6666-4666-8666-666666666666", library_check_version: 1 };
}
function pendingDraft(text = AI_TEXT): RecoveryDraft {
  return { documentId: DOC_A, draftVersion: 1, contentMarkdown: text, baseContentHash: sha(BODY_A), updatedAt: 1,
    draftId: "persisted-recovery", pendingLibrarySave: { contentMarkdown: AI_TEXT, application: application() } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function nodeText(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(nodeText).join("");
  if (!value || typeof value !== "object") return "";
  return ((value as Node).children ?? []).map(nodeText).join("");
}
type BodyOptions = Parameters<typeof import("./chapter-workflow").mountChapterBodyAssistantScope>[0];
type Patch = { expected_draft_version: number; content_markdown: string; library_application?: SelectionLibraryApplication };

describe("Workbench controlled selection save and recovery entry", () => {
  let hooks: Hooks;
  let Workbench: typeof import("./workbench-v2").NovelWorkbench;
  let recovery: typeof import("./recovery");
  let ApiError: typeof import("./api").ApiError;
  let local: Map<string, RecoveryDraft>;
  let server: Map<string, DocumentRecord>;
  let surfaceOptions: CreateChapterEditorSurfaceOptions | undefined;
  let surfaceValue: string;
  let surfaceEditable: boolean;
  let bodyOptions: BodyOptions | undefined;
  let patchReply: ((id: string, patch: Patch) => Promise<DocumentRecord>) | undefined;
  const calls = () => io.request.mock.calls.filter(([, init]) => init?.method === "PATCH") as [string, RequestInit][];
  const bodyOf = (call: [string, RequestInit]): Patch => JSON.parse(String(call[1].body)) as Patch;
  function render() { hooks.render(() => Workbench()); }
  async function settle() {
    for (let index = 0; index < 24; index += 1) { await Promise.resolve(); if (hooks.dirty) render(); }
  }
  function button(label: string): Node {
    const node = hooks.nodes.find((candidate) => candidate.type === "button" && nodeText(candidate) === label);
    if (!node) throw new Error(`button missing: ${label}; ${hooks.nodes.filter((item) => item.type === "button").map(nodeText).join(" | ")}`);
    return node;
  }
  function click(label: string): unknown { return (button(label).props.onClick as () => unknown)(); }
  function workflowProps(): Record<string, unknown> {
    const node = hooks.nodes.find((candidate) => candidate.type === "chapter-workflow");
    if (!node) throw new Error("chapter workflow missing");
    return node.props;
  }
  function manual(text: string): void {
    if (!surfaceOptions) throw new Error("editor surface missing");
    if (!surfaceEditable) return;
    surfaceValue = text;
    surfaceOptions.onDocChanged({ lease: surfaceOptions.lease, nextValue: text, origin: "input", composing: false });
  }
  async function applyAI(text = AI_TEXT, app = application()): Promise<void> {
    if (!bodyOptions) throw new Error("body adapter missing");
    const meta: AIApplyMeta = { transactionId: app.application_id, agentId: "ai-novel-writer",
      operation: "replace-selection", sourceValueSha256: app.base_content_hash, appliedAt: "2026-09-13T08:00:00Z",
      libraryApplication: app };
    await bodyOptions.applyEditorContent(text, meta);
    await bodyOptions.scheduleAutosave(text, meta);
    await settle();
  }
  async function undoTo(text: string): Promise<void> {
    if (!bodyOptions) throw new Error("body adapter missing");
    const meta: AIApplyMeta = { transactionId: "undo-operation", agentId: "ai-novel-writer",
      operation: "undo", sourceValueSha256: sha(bodyOptions.getValue()), appliedAt: "2026-09-13T08:00:01Z" };
    await bodyOptions.applyEditorContent(text, meta);
    await bodyOptions.scheduleAutosave(text, meta);
    await settle();
  }
  function accepted(id: string, patch: Patch): DocumentRecord {
    const result = documentRecord(id, patch.content_markdown, patch.expected_draft_version + 1);
    if (patch.library_application) result.library_application = {
      kind: "application", application_id: patch.library_application.application_id,
      report_id: patch.library_application.library_check_report_id,
      input_sha256: patch.library_application.base_content_hash, output_sha256: result.content_hash,
      request_sha256: "a".repeat(64), draft_version: result.draft_version, at: "2026-09-13T08:00:00Z", replayed: false,
    };
    server.set(id, result);
    return result;
  }
  async function projectSwitch(id: string): Promise<void> {
    click("返回列表"); render(); await settle();
    const studio = hooks.nodes.find((node) => node.type === "studio-project");
    if (!studio) throw new Error("project view missing");
    (studio.props.onSelectDocument as (id: string) => void)(id);
    await settle();
  }

  beforeEach(async () => {
    vi.resetModules(); vi.useFakeTimers();
    for (const mock of Object.values(io)) mock.mockReset();
    hooks = new Hooks(); local = new Map(); server = new Map([[DOC_A, documentRecord(DOC_A)], [DOC_B, documentRecord(DOC_B)]]);
    surfaceOptions = undefined; surfaceValue = ""; surfaceEditable = true; bodyOptions = undefined; patchReply = undefined;
    const input = Object.assign("input", { TextArea: "textarea" });
    const components = new Proxy({ Input: input, Modal: { confirm: io.confirm }, Button: "button", Alert: "alert" }, {
      get: (target, key) => key in target ? target[key as keyof typeof target] : String(key),
    });
    const windowDocument = { visibilityState: "visible", addEventListener: vi.fn(), removeEventListener: vi.fn(),
      querySelector: vi.fn(() => null), activeElement: null, createElement: vi.fn(() => ({ click: vi.fn(), remove: vi.fn() })) };
    vi.stubGlobal("window", { QwenPaw: { host: { React: hooks.React, ReactDOM: {}, antd: components, antdIcons: components } },
      document: windowDocument, location: { search: `?novel_id=${NOVEL}&document_id=${DOC_A}`, href: `http://localhost/chat?novel_id=${NOVEL}&document_id=${DOC_A}` },
      history: { replaceState: vi.fn() }, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      setInterval, clearInterval, requestAnimationFrame: (callback: () => void) => { callback(); return 1; }, scrollTo: vi.fn(),
    });
    vi.stubGlobal("document", windowDocument);
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
    const storage = new Map<string, string>();
    vi.stubGlobal("sessionStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) });
    io.confirm.mockReturnValue({ destroy: vi.fn() });
    io.model.mockResolvedValue({ agent_id: "ai-novel-writer", provider_id: "provider", model_id: "model", policy: "follow-agent-effective" });
    io.loadNovel.mockImplementation(async (_id: string, options?: { onPage?: (value: NovelRecord) => void }) => {
      const novel = novelRecord(); options?.onPage?.(novel); return novel;
    });
    io.gate.mockRejectedValue(new Error("本次代码用例不进入朗读运行态"));
    recovery = await import("./recovery"); ({ ApiError } = await import("./api"));
    io.loadRecovery.mockImplementation(async (id: string) => structuredClone(local.get(id)));
    io.saveRecovery.mockImplementation(async (draft: RecoveryDraft) => { local.set(draft.documentId, structuredClone(draft)); });
    io.replaceRecovery.mockImplementation(async (expected: RecoveryDraftIdentity, next: RecoveryDraft) => {
      const current = local.get(expected.documentId);
      if (!current || !recovery.isCurrentRecoveryDraft(current, expected)) return false;
      local.set(next.documentId, structuredClone(next)); return true;
    });
    io.clearRecovery.mockImplementation(async (expected: RecoveryDraftIdentity) => {
      const current = local.get(expected.documentId);
      if (!current || !recovery.isCurrentRecoveryDraft(current, expected)) return false;
      local.delete(expected.documentId); return true;
    });
    io.request.mockImplementation(async (path: string, init?: RequestInit) => {
      const id = path.split("/")[2]!;
      if (path.endsWith("/draft") && init?.method === "PATCH") {
        const patch = JSON.parse(String(init.body)) as Patch;
        return patchReply ? patchReply(id, patch) : accepted(id, patch);
      }
      if (path.startsWith("/documents/")) return structuredClone(server.get(id));
      if (path === `/novels/${NOVEL}`) return novelRecord();
      throw new Error(`Unexpected HTTP ${init?.method ?? "GET"} ${path}`);
    });
    io.surface.mockImplementation((options: CreateChapterEditorSurfaceOptions) => {
      surfaceOptions = options; surfaceValue = options.initialValue; surfaceEditable = true;
      return {
        kind: "codemirror6", bridge: { lease: options.lease },
        assistantControl: { focus: vi.fn(), setSelectionRange: vi.fn() },
        readValue: () => surfaceValue,
        setValue: (value: string, origin: string) => {
          surfaceValue = value;
          if (origin !== "external") options.onDocChanged({ lease: options.lease, nextValue: value, origin: "ai-apply", composing: false });
          return true;
        },
        setEditable: (editable: boolean) => { surfaceEditable = editable; },
        setParagraphGutter: () => true, focus: vi.fn(), dispose: vi.fn(),
      };
    });
    io.bodyScope.mockImplementation((options: BodyOptions) => {
      bodyOptions = options;
      return { notifyFieldChanged: vi.fn(), setFocusedField: vi.fn(), dispose: vi.fn() };
    });
    ({ NovelWorkbench: Workbench } = await import("./workbench-v2"));
  });
  afterEach(() => { hooks.dispose(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("drives actual editor and autosave callbacks without running narration", async () => {
    render(); await settle();
    expect(surfaceOptions?.lease.documentId).toBe(DOC_A);
    manual(`${BODY_A}林舟收紧绳结。`); await settle();
    await vi.advanceTimersByTimeAsync(600); await settle();
    expect(calls()).toHaveLength(1);
    expect(bodyOf(calls()[0]!)).toEqual({ expected_draft_version: 1, content_markdown: `${BODY_A}林舟收紧绳结。` });
    expect(server.get(DOC_A)?.content_markdown).toBe(`${BODY_A}林舟收紧绳结。`);
  });

  it.each(["controlled AI", "manual"])("does not send a prior chapter's 600ms %s timer into the new chapter", async (kind) => {
    render(); await settle();
    if (kind === "controlled AI") await applyAI();
    else { manual(`${BODY_A}林舟收紧绳结。`); await settle(); }
    await projectSwitch(DOC_B);
    await vi.advanceTimersByTimeAsync(700); await settle();
    expect(surfaceOptions?.lease.documentId).toBe(DOC_B);
    expect(surfaceValue).toBe(BODY_B);
    expect(calls().filter(([path]) => path.includes(DOC_B))).toEqual([]);
    expect(local.get(DOC_A)?.contentMarkdown).toContain(kind === "controlled AI" ? AI_TEXT : BODY_A);
    if (kind === "controlled AI") expect(local.get(DOC_A)?.pendingLibrarySave?.application).toEqual(application());
  });

  it("ignores an acknowledged AI save whose IndexedDB CAS resolves after a chapter switch", async () => {
    const casDone = deferred<boolean>();
    const originalCas = io.replaceRecovery.getMockImplementation()!;
    io.replaceRecovery.mockImplementationOnce(async (expected: RecoveryDraftIdentity, next: RecoveryDraft) => {
      expect(await originalCas(expected, next)).toBe(true);
      return casDone.promise;
    });
    render(); await settle(); await applyAI();
    await vi.advanceTimersByTimeAsync(600); await settle();
    expect(io.replaceRecovery).toHaveBeenCalledOnce();
    await projectSwitch(DOC_B);
    casDone.resolve(true); await settle();
    expect(surfaceOptions?.lease.documentId).toBe(DOC_B);
    expect((workflowProps().document as DocumentRecord).id).toBe(DOC_B);
    expect(surfaceValue).toBe(BODY_B);
    expect(calls().filter(([path]) => path.includes(DOC_B))).toEqual([]);
    expect(server.get(DOC_A)?.content_markdown).toBe(AI_TEXT);
  });

  it("does not replace later typing when an earlier recovery CAS response arrives late", async () => {
    const casDone = deferred<boolean>();
    const originalCas = io.replaceRecovery.getMockImplementation()!;
    io.replaceRecovery.mockImplementationOnce(async (expected: RecoveryDraftIdentity, next: RecoveryDraft) => {
      expect(await originalCas(expected, next)).toBe(true);
      return casDone.promise;
    });
    render(); await settle(); await applyAI();
    await vi.advanceTimersByTimeAsync(600); await settle();
    expect(io.replaceRecovery).toHaveBeenCalledOnce();
    const continued = `${AI_TEXT}他把湿透的信封塞进内袋。`;
    manual(continued); await settle();
    const newest = structuredClone(local.get(DOC_A));
    casDone.resolve(true); await settle();
    expect(bodyOptions?.getValue()).toBe(continued);
    expect(surfaceValue).toBe(continued);
    expect(local.get(DOC_A)).toEqual(newest);
    expect(local.get(DOC_A)?.pendingLibrarySave?.contentMarkdown).toBe(AI_TEXT);
    await vi.advanceTimersByTimeAsync(700); await settle();
    expect(calls()).toHaveLength(1);
    expect(button("重新检查并保存")).toBeDefined();
  });

  it("coalesces B and C waiters behind a controlled A save without re-posting stale B after C", async () => {
    const first = deferred<DocumentRecord>();
    patchReply = async (id, patch) => patch.library_application ? first.promise : accepted(id, patch);
    render(); await settle(); await applyAI();
    await vi.advanceTimersByTimeAsync(600); await settle();
    expect(calls()).toHaveLength(1);
    const draftB = `${AI_TEXT}他收好缆绳。`;
    const draftC = `${draftB}远处传来三声钟响。`;
    manual(draftB); await settle();
    await vi.advanceTimersByTimeAsync(600); await settle();
    const queuedB = (workflowProps().onPrepareGeneration as () => Promise<DocumentRecord | null>)();
    manual(draftC); await settle();
    await vi.advanceTimersByTimeAsync(600); await settle();
    const queuedC = (workflowProps().onPrepareGeneration as () => Promise<DocumentRecord | null>)();
    expect(calls()).toHaveLength(1);
    first.resolve(accepted(DOC_A, bodyOf(calls()[0]!)));
    await settle(); await queuedB; await queuedC;
    await vi.advanceTimersByTimeAsync(150); await settle();
    expect(calls().map(bodyOf).map((patch) => patch.content_markdown)).toEqual([AI_TEXT, draftC]);
    expect(bodyOf(calls()[0]!).library_application).toEqual(application());
    expect(bodyOf(calls()[1]!).library_application).toBeUndefined();
    expect(server.get(DOC_A)?.content_markdown).toBe(draftC);
    expect(surfaceValue).toBe(draftC);
  });

  it("keeps discovered controlled recovery inactive and read-only until the author explicitly restores it", async () => {
    const retained = pendingDraft(`${AI_TEXT}他没有回头看那盏灯。`);
    local.set(DOC_A, retained);
    render(); await settle();
    expect(surfaceEditable).toBe(false);
    expect(surfaceValue).toBe(BODY_A);
    manual("不应替换原恢复记录的输入");
    // A queued editor event also cannot bypass the Workbench-level recovery guard.
    surfaceOptions?.onDocChanged({ lease: surfaceOptions.lease, nextValue: "迟到的编辑事件", origin: "input", composing: false });
    const prepared = await (workflowProps().onPrepareGeneration as () => Promise<DocumentRecord | null>)();
    expect(prepared).toBeNull();
    await expect(applyAI()).rejects.toThrow("恢复稿");
    await vi.advanceTimersByTimeAsync(700); await settle();
    expect(calls()).toEqual([]);
    expect(io.saveRecovery).not.toHaveBeenCalled();
    expect(local.get(DOC_A)).toEqual(retained);
    const preview = hooks.nodes.find((node) => node.props["aria-label"] === "保留的本地恢复全文");
    expect(preview?.props.value).toBe(retained.contentMarkdown);
    click("恢复本地稿"); await settle();
    expect(calls().map(bodyOf).map((patch) => patch.content_markdown)).toEqual([AI_TEXT, retained.contentMarkdown]);
    expect(bodyOf(calls()[0]!).library_application).toEqual(application());
    expect(bodyOf(calls()[1]!).library_application).toBeUndefined();
    expect(server.get(DOC_A)?.content_markdown).toBe(retained.contentMarkdown);
    expect(surfaceEditable).toBe(true);
  });

  it("blocks input while recovery discovery is pending, without changing the persisted local record", async () => {
    const read = deferred<RecoveryDraft | undefined>();
    const retained = pendingDraft(); local.set(DOC_A, retained);
    io.loadRecovery.mockReturnValueOnce(read.promise);
    render(); await settle();
    expect(surfaceEditable).toBe(false);
    expect(await (workflowProps().onPrepareGeneration as () => Promise<DocumentRecord | null>)()).toBeNull();
    expect(io.saveRecovery).not.toHaveBeenCalled();
    read.resolve(structuredClone(retained)); await settle();
    expect(surfaceEditable).toBe(false);
    expect(local.get(DOC_A)).toEqual(retained);
    expect(calls()).toEqual([]);
  });

  it("keeps a conflicting local draft when loading the server and converts it only after explicit comparison and confirmation", async () => {
    render(); await settle(); await applyAI();
    const continued = `${AI_TEXT}他听见栈桥下有人咳嗽。`;
    manual(continued); await settle();
    const newer = documentRecord(DOC_A, "码头上只剩半截旧缆绳。", 3);
    server.set(DOC_A, newer);
    patchReply = async () => { throw new ApiError(409, "正文版本冲突", { type: "draft_conflict", current: newer }); };
    await vi.advanceTimersByTimeAsync(600); await settle();
    const retained = structuredClone(local.get(DOC_A));
    click("载入服务器版"); await settle();
    expect(surfaceValue).toBe(newer.content_markdown);
    expect(surfaceEditable).toBe(false);
    expect(local.get(DOC_A)).toEqual(retained);
    expect(await (workflowProps().onPrepareGeneration as () => Promise<DocumentRecord | null>)()).toBeNull();
    click("将本地稿按手写保存");
    const modal = io.confirm.mock.lastCall?.[0] as Record<string, unknown>;
    expect(modal.title).toBe("转为作者手写稿并保存？");
    const localPreview = hooks.nodes.find((node) => node.props["aria-label"] === "转为手写的本地全文");
    const serverPreview = hooks.nodes.find((node) => node.props["aria-label"] === "转为手写前的服务器全文");
    expect(localPreview?.props.value).toBe(continued);
    expect(serverPreview?.props.value).toBe(newer.content_markdown);
    expect(calls()).toHaveLength(1);
    patchReply = undefined;
    await (modal.onOk as () => Promise<void>)(); await settle();
    expect(bodyOf(calls()[1]!)).toEqual({ expected_draft_version: 3, content_markdown: continued });
    expect(server.get(DOC_A)?.content_markdown).toBe(continued);
    expect(surfaceEditable).toBe(true);
    expect(local.has(DOC_A)).toBe(false);
  });

  it("does not convert a retained draft against a server version changed after opening confirmation", async () => {
    const retained = pendingDraft(); local.set(DOC_A, retained);
    render(); await settle();
    click("将本地稿按手写保存");
    const modal = io.confirm.mock.lastCall?.[0] as Record<string, unknown>;
    server.set(DOC_A, documentRecord(DOC_A, "新一班船提前入港。", 2));
    await expect((modal.onOk as () => Promise<void>)()).rejects.toThrow("服务器已有新稿");
    await settle();
    expect(calls()).toEqual([]);
    expect(local.get(DOC_A)).toEqual(retained);
    expect(surfaceEditable).toBe(false);
  });

  it("stays read-only when recovery discovery fails instead of treating the missing result as an empty store", async () => {
    const retained = pendingDraft(); local.set(DOC_A, retained);
    io.loadRecovery.mockRejectedValueOnce(new Error("本地恢复记录读取失败"));
    render(); await settle();
    expect(surfaceEditable).toBe(false);
    expect(await (workflowProps().onPrepareGeneration as () => Promise<DocumentRecord | null>)()).toBeNull();
    await expect(applyAI()).rejects.toThrow("恢复稿");
    expect(io.saveRecovery).not.toHaveBeenCalled();
    expect(local.get(DOC_A)).toEqual(retained);
    expect(calls()).toEqual([]);
    expect(hooks.nodes.some((node) => node.type === "alert" && node.props.message === "本地恢复记录读取失败")).toBe(true);
  });

  it.each(["before request", "during request"])("keeps undo ordinary and preserves only an in-flight controlled application: %s", async (phase) => {
    const first = deferred<DocumentRecord>();
    patchReply = async (id, patch) => patch.library_application ? first.promise : accepted(id, patch);
    render(); await settle(); await applyAI();
    if (phase === "during request") {
      await vi.advanceTimersByTimeAsync(600); await settle();
      expect(calls()).toHaveLength(1);
    }
    await undoTo(BODY_A);
    expect(bodyOptions?.getValue()).toBe(BODY_A);
    expect(local.get(DOC_A)?.contentMarkdown).toBe(BODY_A);
    if (phase === "during request") {
      expect(local.get(DOC_A)?.pendingLibrarySave?.application.application_id).toBe(application().application_id);
      first.resolve(accepted(DOC_A, bodyOf(calls()[0]!))); await settle();
      expect(calls().map(bodyOf).map((patch) => [patch.content_markdown, Boolean(patch.library_application)]))
        .toEqual([[AI_TEXT, true], [BODY_A, false]]);
    } else {
      expect(local.get(DOC_A)?.pendingLibrarySave).toBeUndefined();
      await vi.advanceTimersByTimeAsync(700); await settle();
      expect(calls()).toEqual([]);
    }
    expect(server.get(DOC_A)?.content_markdown).toBe(BODY_A);
  });

  it("does not retain chapter B's undone application merely because chapter A still has a request in flight", async () => {
    const first = deferred<DocumentRecord>();
    patchReply = async (id, patch) => id === DOC_A ? first.promise : accepted(id, patch);
    render(); await settle(); await applyAI();
    await vi.advanceTimersByTimeAsync(600); await settle();
    expect(calls()).toHaveLength(1);
    await projectSwitch(DOC_B);
    const nextText = "林舟将铁门推开一道缝。";
    const nextApplication = { ...application(), application_id: "77777777-7777-4777-8777-777777777777",
      job_id: "88888888-8888-4888-8888-888888888888", base_content_hash: sha(BODY_B), replacement_sha256: sha(nextText) };
    await applyAI(nextText, nextApplication);
    await undoTo(BODY_B);
    expect(local.get(DOC_B)?.pendingLibrarySave).toBeUndefined();
    expect(bodyOptions?.getValue()).toBe(BODY_B);
    first.resolve(accepted(DOC_A, bodyOf(calls()[0]!))); await settle();
    await vi.advanceTimersByTimeAsync(700); await settle();
    expect(calls().filter(([path]) => path.includes(DOC_B))).toEqual([]);
    expect(server.get(DOC_B)?.content_markdown).toBe(BODY_B);
  });

  it("does not retry the old controlled PATCH after a rule-report CAS finishes in another chapter", async () => {
    const casDone = deferred<boolean>();
    const originalCas = io.replaceRecovery.getMockImplementation()!;
    io.replaceRecovery.mockImplementationOnce(async (expected: RecoveryDraftIdentity, next: RecoveryDraft) => {
      expect(await originalCas(expected, next)).toBe(true);
      return casDone.promise;
    });
    const originalRequest = io.request.getMockImplementation()!;
    io.request.mockImplementation((path: string, init?: RequestInit) => {
      if (path === `/novels/${NOVEL}/library-checks`) return Promise.resolve({
        schema_version: "library-check/1", id: "99999999-9999-4999-8999-999999999999", version: 1, status: "complete",
        text_sha256: sha(AI_TEXT), rules_sha256: "c".repeat(64), hits: [], unresolved_forbid_hit_ids: [],
        scanned_rule_count: 1, omitted_rule_count: 0, visible_character_count: AI_TEXT.length,
        offset: 0, limit: 200, total_hits: 0, has_more: false,
      });
      return originalRequest(path, init);
    });
    patchReply = async () => { throw new ApiError(409, "当前规则已经变化", { type: "library_check_required" }); };
    render(); await settle(); await applyAI();
    await vi.advanceTimersByTimeAsync(600); await settle();
    expect(io.replaceRecovery).toHaveBeenCalledOnce();
    await projectSwitch(DOC_B);
    casDone.resolve(true); await settle();
    expect(calls()).toHaveLength(1);
    expect(surfaceValue).toBe(BODY_B);
    expect((workflowProps().document as DocumentRecord).id).toBe(DOC_B);
  });
});
