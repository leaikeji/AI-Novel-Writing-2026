import { describe, expect, it, vi } from "vitest";

import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import { AssistantSelectionRegistry } from "./assistant-selection-registry";
import { AIEditTransactionManager } from "./assistant-transactions";
import type { EditableFieldAdapter, SelectionSnapshot } from "./assistant-fields";
import {
  SelectionEditRuntime,
  type SelectionEditGenerationClient,
} from "./selection-edit-runtime";
import type { CreativeGenerationRecord } from "./types";


const SELECTION_ID = "00000000-0000-4000-8000-000000000021";
const JOB_ID = "00000000-0000-4000-8000-000000000022";
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


async function harness(client?: SelectionEditGenerationClient) {
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
    id: "settings.idea",
    label: "创作思路",
    persistence: "explicit-save",
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
    persistenceBaseline: { kind: "entity", version: 7 },
    envelope: {
      agentId: "ai-novel-writer",
      novel: {
        id: "00000000-0000-4000-8000-000000000031",
        title: "潮声替我说晚安",
      },
      page: { section: "settings", view: "novel-settings" },
      entity: {
        type: "setting",
        id: "00000000-0000-4000-8000-000000000031",
        title: "小说设定",
      },
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
});
