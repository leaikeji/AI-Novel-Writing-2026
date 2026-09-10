/** Runs actual panel callbacks with deterministic hooks; not browser/layout evidence. */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { DocumentRecord, NovelRecord } from "../types";
import { ApiError } from "../api";

const transport = vi.hoisted(() => ({ request: vi.fn(), model: vi.fn() }));
vi.mock("../api", async (original) => ({
  ...await original<typeof import("../api")>(),
  apiRequest: transport.request, getGenerationModelStatus: transport.model,
  generationModelLabel: () => "合成测试模型", completedGenerationModelLabel: () => "合成测试模型",
}));

type Node = { type: unknown; props: Record<string, unknown>; children: unknown[] };
type Effect = { deps: unknown[]; cleanup?: () => void };
class Hooks {
  slots: unknown[] = [];
  cursor = 0;
  nodes: Node[] = [];
  pending: (() => void)[] = [];
  effects = new Map<number, Effect>();
  React = {
    Fragment: "Fragment",
    createElement: (type: unknown, props: Record<string, unknown> | null, ...children: unknown[]) => {
      const node = { type, props: props ?? {}, children }; this.nodes.push(node); return node;
    },
    useState: <T>(initial: T) => {
      const index = this.cursor++;
      if (!(index in this.slots)) this.slots[index] = initial;
      return [this.slots[index], (value: T | ((old: T) => T)) => {
        this.slots[index] = typeof value === "function"
          ? (value as (old: T) => T)(this.slots[index] as T) : value;
      }];
    },
    useRef: <T>(initial: T) => {
      const index = this.cursor++;
      if (!(index in this.slots)) this.slots[index] = { current: initial };
      return this.slots[index];
    },
    useMemo: <T>(factory: () => T, deps: unknown[]) => {
      const index = this.cursor++;
      const previous = this.slots[index] as { deps: unknown[]; value: T } | undefined;
      if (!previous || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
        this.slots[index] = { deps, value: factory() };
      }
      return (this.slots[index] as { value: T }).value;
    },
    useEffect: (run: () => (() => void) | void, deps: unknown[]) => {
      const index = this.cursor++;
      const previous = this.effects.get(index);
      if (!previous || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
        this.pending.push(() => {
          previous?.cleanup?.();
          this.effects.set(index, { deps, cleanup: run() || undefined });
        });
      }
    },
  };
  render(run: () => void) { this.cursor = 0; this.nodes = []; run(); this.pending.splice(0).forEach(run => run()); }
  dispose() { this.effects.forEach(effect => effect.cleanup?.()); }
}
const DOC = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const NOVEL = "33333333-3333-4333-8333-333333333333";
const JOB = "44444444-4444-4444-8444-444444444444";
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const flush = async () => { for (let i = 0; i < 12; i++) await new Promise(resolve => setTimeout(resolve, 0)); };

describe("actual ChapterWorkflowPanel method integration", () => {
  let hooks: Hooks;
  let Panel: typeof import("../chapter-workflow").ChapterWorkflowPanel;
  let confirms: Record<string, unknown>[];
  let errors: Mock<(message: string) => void>;
  let changed: Mock<(document: DocumentRecord, status: string) => void>;
  let prepare: Mock<() => Promise<DocumentRecord | null>>;
  let bodyState: Mock<(active: boolean, stage: string) => void>;
  let activeDoc: string;
  let bodyReply: (path: string, init: RequestInit) => Promise<unknown>;
  let recoveryReply: unknown;
  let catalogGate: boolean;
  const doc = (id: string) => ({ id, novel_id: NOVEL, kind: "chapter", title: "合成章节", visible_character_count: 0, draft_version: 1 } as DocumentRecord);
  function render(id = activeDoc) {
    activeDoc = id;
    hooks.render(() => Panel({ novel: { id: NOVEL, tree: [] } as unknown as NovelRecord,
      document: doc(id), chapterNumber: 1, onPrepareGeneration: prepare,
      onDocumentChanged: changed, onError: errors, onStatus: vi.fn(), onBodyGenerationStateChange: bodyState }));
  }
  async function confirm() {
    const picker = hooks.nodes.find(node => node.props.className === "anw-modal anw-asset-modal")!;
    await ((picker.props.footer as Node[])[0].props.onClick as () => Promise<void>)();
    return [...confirms].reverse().find(item => item.className === "anw-modal anw-generation-confirm")!;
  }
  beforeEach(async () => {
    vi.resetModules(); hooks = new Hooks(); confirms = []; errors = vi.fn(); changed = vi.fn();
    activeDoc = DOC; prepare = vi.fn(async () => doc(DOC)); recoveryReply = null; catalogGate = true;
    bodyState = vi.fn();
    const values = new Map<string, string>();
    vi.stubGlobal("sessionStorage", { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v); } });
    const Modal = { confirm: (value: Record<string, unknown>) => { confirms.push(value); }, error: vi.fn() };
    vi.stubGlobal("window", { QwenPaw: { host: { React: hooks.React, ReactDOM: {}, antd: {
      Modal, Input: { TextArea: "TextArea" }, Button: "Button", Card: "Card", Checkbox: "Checkbox",
      Empty: "Empty", Spin: "Spin", Tag: "Tag", Tabs: "Tabs", Alert: "Alert",
    }, antdIcons: {} } } });
    transport.model.mockReset().mockResolvedValue({}); transport.request.mockReset();
    bodyReply = async (path, init) => {
      const action = JSON.parse(String(init.body)).writing_action.action_id;
      return { id: JOB, document_id: path.split("/")[2], state: "ready", candidate: { id: JOB, base_draft_version: 1 },
        writing_method: { schema_version: "writing-method-status/1", action_id: action, dispatch_id: JOB,
          state: "dispatched", method_input_hash: "a".repeat(64), job_ref: `chapter:${JOB}`,
          selected_ids: ["suspense-writing"], omitted_ids: [], auxiliary_calls: 0, semantic_enabled: false } };
    };
    transport.request.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.startsWith("/writing-skills?")) {
        const query = new URLSearchParams(path.split("?")[1]);
        return { schema_version: "writing-skill-catalog/1", agent_id: "ai-novel-writer", catalog_version: "a".repeat(64),
          chapter_body_available: catalogGate, catalog_available: true, semantic_available: false,
          scope: { owner_id: DOC, workspace_id: NOVEL, kind: "novel", scope_id: NOVEL,
            document_id: query.get("document_id"), tab_id: query.get("tab_id"), agent_id: "ai-novel-writer" },
          capabilities: [{ skill_id: "suspense-writing", display_name: "悬疑", version: "1.0.0" }] };
      }
      if (path.endsWith("/chapter-brief")) return { document_id: path.split("/")[2], version: 1, target_word_count: 1000,
        expectation_text: "", outline_text: "合成测试大纲", forbidden_text: "", role_constraints: { required: [], allowed: [], context_only: [], forbidden: [] } };
      if (path.endsWith("/generation-jobs/body")) return bodyReply(path, init!);
      if (path.includes("/writing-method-actions/")) return recoveryReply;
      if (path.endsWith("/adopt")) return { document: doc(DOC), candidate: { id: JOB, visible_character_count: 1000 } };
      throw new Error(`Unexpected request ${path}`);
    });
    ({ ChapterWorkflowPanel: Panel } = await import("../chapter-workflow"));
    render(); await flush(); render();
  });
  afterEach(() => { hooks.dispose(); vi.unstubAllGlobals(); });
  const bodyCalls = () => transport.request.mock.calls.filter(([path]) => String(path).endsWith("/generation-jobs/body"));

  it("coalesces double confirmation and reaches the existing adoption path with a stable action", async () => {
    const prompt = await confirm();
    (prompt.onOk as () => void)(); (prompt.onOk as () => void)(); await flush();
    expect(errors.mock.calls).toEqual([]);
    expect(bodyCalls()).toHaveLength(1);
    expect(JSON.parse(String(bodyCalls()[0][1].body)).writing_action.action_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(changed).toHaveBeenCalledTimes(1);
    expect(errors).not.toHaveBeenCalled();
    render();
    expect(hooks.nodes.some(node => node.children.includes("查询原任务"))).toBe(false);
  });
  it("automatically selects methods without adding controls or fields to chapter content", async () => {
    expect(hooks.nodes.some(node => node.props["aria-label"] === "本次写作方法")).toBe(false);
    const prompt = await confirm(); (prompt.onOk as () => void)(); await flush();
    const body = JSON.parse(String(bodyCalls()[0][1].body));
    expect(body).not.toHaveProperty("method_mode");
    expect(body.writing_action.preferences).toEqual({ mode: "auto", semantic_mode: "off" });
    render(OTHER); await flush(); render();
    expect(hooks.nodes.some(node => node.props["aria-label"] === "本次写作方法")).toBe(false);
  });
  it("links automatic length rewrites to the prior action while keeping the method choice", async () => {
    const original = bodyReply;
    let attempt = 0;
    bodyReply = async (path, init) => {
      const value = await original(path, init) as Record<string, unknown>;
      attempt += 1;
      if (attempt === 1) throw new ApiError(422, "too short", {
        type: "chapter_length_out_of_range", direction: "below_target",
        validation_state: "below_target", retryable: true,
        writing_method: value.writing_method,
        job: { ...value, state: "failed", candidate: null },
      });
      return value;
    };
    const prompt = await confirm(); (prompt.onOk as () => void)(); await flush();
    expect(errors).not.toHaveBeenCalled();
    expect(bodyCalls()).toHaveLength(2);
    const first = JSON.parse(String(bodyCalls()[0][1].body)).writing_action;
    const second = JSON.parse(String(bodyCalls()[1][1].body)).writing_action;
    expect(first).not.toHaveProperty("retry_of_action_id");
    expect(second.retry_of_action_id).toBe(first.action_id);
    expect(second.action_id).not.toBe(first.action_id);
    expect(second.preferences).toEqual(first.preferences);
    expect(changed).toHaveBeenCalledTimes(1);
  });
  it("preserves the server's closed branch without exposing method configuration", async () => {
    catalogGate = false; render(OTHER); await flush(); render();
    expect(hooks.nodes.some(node => node.props["aria-label"] === "本次写作方法")).toBe(false);
    expect(bodyCalls()).toHaveLength(0);
  });
  it("rejects an old confirmation after switching chapters, including returning to the same chapter", async () => {
    const prompt = await confirm(); render(OTHER); await flush(); render(DOC); await flush();
    (prompt.onOk as () => void)(); await flush();
    expect(prepare).not.toHaveBeenCalled(); expect(bodyCalls()).toHaveLength(0);
  });
  it("stops before reading or saving a brief when scope changes during draft preparation", async () => {
    const saved = deferred<DocumentRecord>(); prepare.mockReturnValue(saved.promise);
    const prompt = await confirm(); (prompt.onOk as () => void)(); await flush();
    render(OTHER); await flush(); saved.resolve(doc(DOC)); await flush();
    expect(bodyState).toHaveBeenLastCalledWith(false, "");
    expect(transport.request.mock.calls.filter(([path]) => String(path).endsWith("/chapter-brief"))).toHaveLength(0);
    expect(bodyCalls()).toHaveLength(0); expect(changed).not.toHaveBeenCalled();
  });
  it("does not adopt a late body response after switching chapters", async () => {
    const pending = deferred<unknown>(); const original = bodyReply;
    bodyReply = async (path, init) => { const output = await original(path, init); await pending.promise; return output; };
    const prompt = await confirm(); (prompt.onOk as () => void)(); await flush();
    expect(bodyCalls()).toHaveLength(1); render(OTHER); await flush(); pending.resolve(null); await flush();
    expect(transport.request.mock.calls.filter(([path]) => String(path).endsWith("/adopt"))).toHaveLength(0);
    expect(changed).not.toHaveBeenCalled(); expect(errors).not.toHaveBeenCalled();
  });
  it("refuses a saved working copy belonging to a different chapter", async () => {
    prepare.mockResolvedValue(doc(OTHER));
    const prompt = await confirm(); (prompt.onOk as () => void)(); await flush();
    expect(errors).toHaveBeenCalledWith(expect.stringContaining("保存结果与当前章节不一致"));
    expect(bodyCalls()).toHaveLength(0);
  });
  it("does not open a stale confirmation when the model read finishes after a switch", async () => {
    const model = deferred<unknown>(); transport.model.mockReturnValue(model.promise);
    const confirming = confirm(); await flush(); render(OTHER); await flush();
    model.resolve({}); await confirming; await flush();
    expect(confirms).toHaveLength(0); expect(errors).not.toHaveBeenCalled(); expect(bodyCalls()).toHaveLength(0);
  });
  it("queries a lost result through the panel without generating again or adopting it", async () => {
    const original = bodyReply;
    bodyReply = async (path, init) => { recoveryReply = await original(path, init); throw new Error("测试响应丢失"); };
    const prompt = await confirm(); (prompt.onOk as () => void)(); await flush(); render();
    const query = hooks.nodes.find(node => node.children.includes("查询原任务"))!;
    expect(query).toBeDefined();
    await (query.props.onClick as () => Promise<void>)(); await flush();
    expect(bodyCalls()).toHaveLength(1);
    expect(transport.request.mock.calls.filter(([path]) => String(path).includes("/writing-method-actions/"))).toHaveLength(1);
    expect(transport.request.mock.calls.filter(([path]) => String(path).endsWith("/adopt"))).toHaveLength(0);
    expect(changed).not.toHaveBeenCalled();
  });
});
