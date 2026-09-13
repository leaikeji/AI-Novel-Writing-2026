import { describe, expect, it, vi } from "vitest";

import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import { AssistantSelectionRegistry } from "./assistant-selection-registry";
import { AIEditTransactionManager } from "./assistant-transactions";
import type { EditableFieldAdapter, SelectionSnapshot } from "./assistant-fields";
import {
  createSelectionEditReviewHost,
  SelectionEditRuntime,
  type SelectionEditGenerationClient,
  type SelectionEditRuntimeOptions,
} from "./selection-edit-runtime";
import type { QwenPawReactRuntime } from "./assistant-pane";
import type { CreativeGenerationRecord, LibraryCheckReportRecord } from "./types";


const SELECTION_ID = "00000000-0000-4000-8000-000000000021";
const JOB_ID = "00000000-0000-4000-8000-000000000022";
const RETRY_JOB_ID = "00000000-0000-4000-8000-000000000025";
const REVIEW_ID = "00000000-0000-4000-8000-000000000023";
const TRANSACTION_ID = "00000000-0000-4000-8000-000000000024";


async function sha256(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}


function readyJob(
  inputSnapshot: Record<string, unknown>,
  overrides: Partial<CreativeGenerationRecord> = {},
): CreativeGenerationRecord {
  return {
    id: JOB_ID,
    scope_type: "novel",
    scope_id: "00000000-0000-4000-8000-000000000031",
    novel_id: "00000000-0000-4000-8000-000000000031",
    document_id: null,
    kind: "selection_edit",
    state: "ready",
    input_hash: "a".repeat(64),
    input_snapshot: inputSnapshot,
    execution_agent_id: "ai-novel-writer",
    requested_provider_id: "minimax-cn",
    requested_model_id: "MiniMax-M3",
    generation_contract_version: "selection-edit-v2",
    actual_provider_id: "minimax-cn",
    actual_model_id: "MiniMax-M3",
    provider_profile: "minimax-cn",
    output_json: {
      schema_version: 2,
      selection_id: SELECTION_ID,
      operation: "polish",
      replacement_text: "新句",
      short_summary: "表达更凝练。",
      replacement_character_count: 2,
      warnings: [],
      diff_segments: [{
        segment_id: "change-1",
        kind: "replace",
        original_text: "旧句",
        replacement_text: "新句",
      }],
    },
    output_text: "新句",
    target_character_count: null,
    output_visible_character_count: 2,
    attempt: 1,
    failure_message: null,
    created_at: "2026-08-25T08:00:00.000Z",
    completed_at: "2026-08-25T08:00:01.000Z",
    ...overrides,
  };
}


async function harness(
  client?: SelectionEditGenerationClient,
  options: {
    document?: boolean;
    runtime?: Partial<SelectionEditRuntimeOptions>;
  } = {},
) {
  let value = "旧句留在这里。";
  const applyValue = vi.fn(async (nextValue: string) => { value = nextValue; });
  const selection: SelectionSnapshot = {
    startUtf16: 0,
    endUtf16: 2,
    direction: "forward",
    text: "旧句",
    before: "",
    after: "留在这里。",
  };
  const adapter: EditableFieldAdapter = {
    id: options.document ? "chapter.body" : "settings.idea",
    label: options.document ? "正文" : "创作思路",
    persistence: options.document ? "autosave" : "explicit-save",
    undoPolicy: "ai-transaction",
    getValue: () => value,
    applyValue,
    getSelection: () => selection,
    focus: vi.fn(),
    getDirty: () => true,
    dispose: () => undefined,
  };
  const contextRuntime = new NovelAssistantContextRuntime();
  contextRuntime.setHostBinding("ai-novel-writer", "visible-chat-session");
  const scope = contextRuntime.mountScope({
    id: "modal:settings",
    kind: "modal",
    persistenceBaseline: options.document
      ? { kind: "draft", version: 7 }
      : { kind: "entity", version: 7 },
    envelope: {
      agentId: "ai-novel-writer",
      novel: {
        id: "00000000-0000-4000-8000-000000000031",
        title: "潮声替我说晚安",
      },
      page: options.document
        ? { section: "chapters", view: "chapter-editor" }
        : { section: "settings", view: "novel-settings" },
      entity: {
        type: options.document ? "document" : "setting",
        id: options.document
          ? "00000000-0000-4000-8000-000000000032"
          : "00000000-0000-4000-8000-000000000031",
        title: options.document ? "第一章 潮声" : "小说设定",
      },
      ...(options.document ? {
        document: {
          id: "00000000-0000-4000-8000-000000000032",
          kind: "chapter",
          title: "第一章 潮声",
          draftVersion: 7,
          savedContentHash: "a".repeat(64),
          dirty: false,
        },
      } : {}),
    },
  });
  scope.registerField(adapter);
  scope.setFocusedField(adapter.id);
  const initial = contextRuntime.getEditableFieldContext(adapter.id)!;
  const registry = new AssistantSelectionRegistry({
    idProvider: () => SELECTION_ID,
    sha256,
  });
  const record = await registry.create({
    agentId: initial.agentId,
    novelId: initial.novelId,
    documentId: initial.documentId,
    fieldId: initial.fieldId,
    contextRevision: initial.contextRevision + 1,
    fieldValue: value,
    startUtf16: selection.startUtf16,
    endUtf16: selection.endUtf16,
    direction: selection.direction,
  });
  contextRuntime.setActiveSelection({
    id: record.selectionId,
    fieldId: record.fieldId,
    text: record.text,
    startUtf16: record.startUtf16,
    endUtf16: record.endUtf16,
    direction: record.direction,
    before: selection.before,
    after: selection.after,
    sourceValueSha256: record.sourceValueSha256,
    contextRevision: record.contextRevision,
    createdAt: new Date(record.createdAtMs).toISOString(),
    expiresAt: new Date(record.expiresAtMs).toISOString(),
  });
  const generationClient = client ?? {
    start: vi.fn(async (payload) => readyJob(payload.input_snapshot)),
  };
  const transactions = new AIEditTransactionManager({
    uuid: () => TRANSACTION_ID,
    sha256,
  });
  const fallback = vi.fn();
  const runtime = new SelectionEditRuntime({
    contextRuntime,
    registry,
    transactions,
    generationClient,
    uuid: () => REVIEW_ID,
    sha256,
    onAssistantFallback: fallback,
    ...options.runtime,
  });
  return {
    runtime,
    record,
    registry,
    scope,
    adapter,
    applyValue,
    generationClient,
    fallback,
    getValue: () => value,
    setValue: (next: string) => { value = next; },
  };
}


describe("SelectionEditRuntime", () => {
  it("keeps the controlled source field mounted while the local review surface is active", () => {
    const state = {
      phase: "applied",
      identity: {
        reviewSessionId: REVIEW_ID,
        selectionId: SELECTION_ID,
        operation: "polish",
        baseText: "旧句",
        target: {
          fieldId: "settings.idea",
          fieldLabel: "创作思路",
          mode: "multiline",
        },
      },
      focusRequest: {
        sequence: 1,
        target: { kind: "source-field", fieldId: "settings.idea" },
        reason: "apply-succeeded",
      },
      message: "AI 修改已应用。",
      canUndo: true,
      undoPending: false,
    } as const;
    const createElement = vi.fn((type: unknown, props: unknown, ...children: unknown[]) => ({
      type,
      props,
      children,
    }));
    const React = {
      createElement,
      useState: (initial: () => unknown) => [initial(), vi.fn()],
      useEffect: vi.fn(),
    } as unknown as QwenPawReactRuntime;
    const runtime = {
      getState: () => state,
      subscribe: vi.fn(() => vi.fn()),
      getRetrievalStatus: () => ({ summary: null, novelId: undefined }),
      subscribeRetrievalStatus: vi.fn(() => vi.fn()),
      getWritingMethodStatus: () => ({ status: null }),
      subscribeWritingMethodStatus: vi.fn(() => vi.fn()),
      handleSurfaceAction: vi.fn(),
      focusSource: vi.fn(),
    } as unknown as SelectionEditRuntime;
    const Host = createSelectionEditReviewHost(React, runtime);

    const rendered = Host({ fieldIds: "settings.idea", children: "SOURCE_FIELD" }) as {
      children: unknown[];
    };

    expect(rendered.children[0]).toBe("SOURCE_FIELD");
    expect(rendered.children[1]).toMatchObject({
      props: expect.objectContaining({ state }),
    });
  });

  it("creates one audited editor job, opens V2 review, applies once and supports one-step undo", async () => {
    const values = await harness();

    const started = await values.runtime.start({
      record: values.record,
      fieldLabel: "创作思路",
      operation: "polish",
    });

    expect(started).toEqual({ jobId: JOB_ID });
    expect(values.runtime.getState().phase).toBe("reviewing");
    expect(values.registry.get(SELECTION_ID)?.delivery).toEqual({
      kind: "editor-task",
      jobId: JOB_ID,
    });
    expect(values.generationClient.start).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "selection_edit",
        force_new: false,
        target_character_count: null,
        input_snapshot: expect.objectContaining({
          selection_id: SELECTION_ID,
          operation: "polish",
          target: expect.objectContaining({
            field_id: "settings.idea",
            persistence: "explicit-save",
          }),
          base: expect.objectContaining({
            persistence_version_kind: "entity",
            persistence_version: 7,
          }),
        }),
      }),
      expect.any(AbortSignal),
    );

    values.runtime.handleSurfaceAction({ type: "accept-all" });
    await vi.waitFor(() => expect(values.runtime.getState().phase).toBe("applied"));
    expect(values.getValue()).toBe("新句留在这里。");
    expect(values.applyValue).toHaveBeenCalledTimes(1);

    values.runtime.handleSurfaceAction({ type: "undo" });
    await vi.waitFor(() => expect(values.runtime.getState().phase).toBe("discarded"));
    expect(values.getValue()).toBe("旧句留在这里。");
    expect(values.applyValue).toHaveBeenCalledTimes(2);
  });

  it("checks a chapter selection candidate and keeps it unapplied until forbidden hits are explicitly kept", async () => {
    const documentId = "00000000-0000-4000-8000-000000000032";
    const checkSelectionResult = vi.fn(async () => ({
      schema_version: "library-check/1" as const,
      id: "00000000-0000-4000-8000-000000000041",
      version: 1,
      status: "complete" as const,
      text_sha256: "a".repeat(64),
      rules_sha256: "b".repeat(64),
      hits: [{
        hit_id: "00000000-0000-4000-8000-000000000042",
        entry_id: "entry_forbid",
        asset_id: "00000000-0000-4000-8000-000000000043",
        asset_version_id: "00000000-0000-4000-8000-000000000044",
        action: "forbid" as const,
        matched_text: "新句",
        start_utf16: 0,
        end_utf16: 2,
        reason: "本书禁用",
        count: 1,
      }],
      unresolved_forbid_hit_ids: ["00000000-0000-4000-8000-000000000042"],
      scanned_rule_count: 1,
      omitted_rule_count: 0,
      visible_character_count: 2,
      offset: 0,
      limit: 200,
      total_hits: 1,
      has_more: false,
    }));
    const client: SelectionEditGenerationClient = {
      start: vi.fn(async (payload) => readyJob(payload.input_snapshot, {
        scope_type: "document",
        scope_id: documentId,
        document_id: documentId,
      })),
    };
    const values = await harness(client, {
      document: true,
      runtime: {
        checkSelectionResult,
        reviewLibraryCheck: async () => null,
      },
    });

    await values.runtime.start({
      record: values.record,
      fieldLabel: "正文",
      operation: "polish",
    });
    expect(checkSelectionResult).not.toHaveBeenCalled();
    values.runtime.handleSurfaceAction({ type: "accept-all" });
    await vi.waitFor(() => expect(values.runtime.getState().phase).toBe("conflict"));
    expect(checkSelectionResult).toHaveBeenCalledOnce();
    expect(checkSelectionResult).toHaveBeenLastCalledWith(expect.objectContaining({
      acceptedSegmentIds: expect.any(Array),
    }));
    expect(values.applyValue).not.toHaveBeenCalled();
    expect(values.getValue()).toBe("旧句留在这里。");
  });

  it("passes the exact approved full-body report and diff choices through the controlled transaction", async () => {
    const report: LibraryCheckReportRecord = {
      schema_version: "library-check/1", id: RETRY_JOB_ID, version: 4, status: "complete",
      text_sha256: await sha256("新句留在这里。"), rules_sha256: "b".repeat(64),
      hits: [], unresolved_forbid_hit_ids: [], scanned_rule_count: 0, omitted_rule_count: 0,
      visible_character_count: 7, offset: 0, limit: 200, total_hits: 0, has_more: false,
    };
    const values = await harness({ start: vi.fn(async (payload) => readyJob(payload.input_snapshot, {
      scope_type: "document", scope_id: "00000000-0000-4000-8000-000000000032",
      document_id: "00000000-0000-4000-8000-000000000032",
    })) }, { document: true, runtime: { checkSelectionResult: async () => report } });
    await values.runtime.start({ record: values.record, fieldLabel: "正文", operation: "polish" });
    values.runtime.handleSurfaceAction({ type: "accept-all" });
    await vi.waitFor(() => expect(values.runtime.getState().phase).toBe("applied"));
    expect(values.applyValue).toHaveBeenCalledWith("新句留在这里。", expect.objectContaining({
      transactionId: REVIEW_ID,
      libraryApplication: expect.objectContaining({
        application_id: REVIEW_ID, job_id: JOB_ID, attempt: 1,
        base_draft_version: 7, base_content_hash: await sha256("旧句留在这里。"),
        replacement_sha256: await sha256("新句"), accepted_segment_ids: ["change-1"],
        library_check_report_id: report.id, library_check_version: 4,
      }),
    }));
  });

  it.each(["missing", "failed"])("keeps a generated body candidate when check is %s without starting another model job", async (kind) => {
    const client = { start: vi.fn(async (payload: Parameters<SelectionEditGenerationClient["start"]>[0]) => readyJob(payload.input_snapshot, {
      scope_type: "document", scope_id: "00000000-0000-4000-8000-000000000032",
      document_id: "00000000-0000-4000-8000-000000000032",
    })) };
    const values = await harness(client, { document: true, runtime: {
      ...(kind === "failed" ? { checkSelectionResult: async () => { throw new Error("无法连接检查服务"); } } : {}),
    } });
    await values.runtime.start({ record: values.record, fieldLabel: "正文", operation: "polish" });
    expect(values.runtime.getState().phase).toBe("reviewing");
    values.runtime.handleSurfaceAction({ type: "accept-all" });
    await vi.waitFor(() => expect(values.runtime.getState().phase).toBe("conflict"));
    expect(values.applyValue).not.toHaveBeenCalled();
    expect(client.start).toHaveBeenCalledOnce();
  });

  it("publishes only the frozen retrieval summary for the active selection task", async () => {
    const summary = {
      schema_version: "retrieval-summary/1",
      outcome: "degraded",
      mode: "lexical_only",
      reason_code: "provider_unavailable",
      hit_count: 2,
      index_state: "ready",
    } as const;
    const client: SelectionEditGenerationClient = {
      start: vi.fn(async (payload) => readyJob(payload.input_snapshot, {
        retrieval_summary: { ...summary, query: "must-not-render" },
      } as unknown as Partial<CreativeGenerationRecord>)),
    };
    const values = await harness(client);
    const listener = vi.fn();
    values.runtime.subscribeRetrievalStatus(listener);

    await values.runtime.start({
      record: values.record,
      fieldLabel: "创作思路",
      operation: "polish",
    });

    expect(values.runtime.getRetrievalStatus()).toEqual({
      summary,
      novelId: "00000000-0000-4000-8000-000000000031",
    });
    expect(listener).toHaveBeenLastCalledWith(values.runtime.getRetrievalStatus());
  });

  it("fails closed when the field changes while the model is running", async () => {
    let resolveJob!: (job: CreativeGenerationRecord) => void;
    let inputSnapshot: Record<string, unknown> = {};
    const client: SelectionEditGenerationClient = {
      start: vi.fn(async (payload) => {
        inputSnapshot = payload.input_snapshot;
        return new Promise<CreativeGenerationRecord>((resolve) => { resolveJob = resolve; });
      }),
    };
    const values = await harness(client);
    const started = values.runtime.start({
      record: values.record,
      fieldLabel: "创作思路",
      operation: "polish",
    });
    await vi.waitFor(() => expect(client.start).toHaveBeenCalledTimes(1));
    values.setValue("作者继续输入，旧句留在这里。");
    values.scope.notifyFieldChanged("settings.idea");
    resolveJob(readyJob(inputSnapshot));
    await started;

    expect(values.runtime.getState()).toMatchObject({
      phase: "conflict",
      message: expect.stringContaining("已经变化"),
    });
    expect(values.applyValue).not.toHaveBeenCalled();
    expect(values.getValue()).toBe("作者继续输入，旧句留在这里。");
  });

  it("rejects requested/actual model drift and exposes chat only on explicit fallback", async () => {
    const client: SelectionEditGenerationClient = {
      start: vi.fn(async (payload) => readyJob(payload.input_snapshot, {
        actual_model_id: "unexpected-model",
      })),
    };
    const values = await harness(client);
    await values.runtime.start({
      record: values.record,
      fieldLabel: "创作思路",
      operation: "polish",
    });

    expect(values.runtime.getState()).toMatchObject({
      phase: "failed",
      message: expect.stringContaining("不一致"),
    });
    expect(values.fallback).not.toHaveBeenCalled();
    values.runtime.handleSurfaceAction({ type: "send-to-assistant" });
    expect(values.fallback).toHaveBeenCalledWith(SELECTION_ID, "polish");
    expect(values.applyValue).not.toHaveBeenCalled();
  });

  it("creates a new audited attempt only after an explicit retry", async () => {
    let callCount = 0;
    const client: SelectionEditGenerationClient = {
      start: vi.fn(async (payload) => {
        callCount += 1;
        return readyJob(payload.input_snapshot, callCount === 1
          ? {
            state: "failed",
            failure_message: "模型暂时不可用",
            output_json: {},
            output_text: "",
            completed_at: null,
          }
          : { id: RETRY_JOB_ID, attempt: 2 });
      }),
    };
    const values = await harness(client);
    await values.runtime.start({
      record: values.record,
      fieldLabel: "创作思路",
      operation: "polish",
    });
    expect(values.runtime.getState()).toMatchObject({ phase: "failed", retryable: true });
    expect(values.registry.get(SELECTION_ID)?.jobId).toBe(JOB_ID);

    values.runtime.handleSurfaceAction({ type: "retry" });
    await vi.waitFor(() => expect(values.runtime.getState().phase).toBe("reviewing"));

    expect(client.start).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ force_new: true }),
      expect.any(AbortSignal),
    );
    expect(values.registry.get(SELECTION_ID)?.delivery).toEqual({
      kind: "editor-task",
      jobId: RETRY_JOB_ID,
    });
  });
});
