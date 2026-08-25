import type {
  AIApplyMeta,
  EditableFieldAdapter,
  SelectionRange,
  SelectionSnapshot,
} from "./assistant-fields";


export interface BodyFieldApplyState {
  readonly value: string;
  readonly valueSha256: string;
  readonly selection: SelectionSnapshot | null;
  readonly dirty: boolean;
}


export interface BodyFieldApplyReceipt {
  readonly fieldId: string;
  readonly meta: Readonly<AIApplyMeta>;
  readonly before: BodyFieldApplyState;
  readonly after: BodyFieldApplyState;
  readonly persistence: "autosave";
  readonly autosaveRequested: true;
}


export interface AssistantBodyFieldAdapter extends EditableFieldAdapter {
  readonly persistence: "autosave";
  applyValue(nextValue: string, meta: AIApplyMeta): Promise<void>;
  applyValueWithReceipt(
    nextValue: string,
    meta: AIApplyMeta,
  ): Promise<BodyFieldApplyReceipt>;
  getLastApplyReceipt(): BodyFieldApplyReceipt | null;
  restoreSelection(range: SelectionRange): void;
}


export interface AssistantBodyFieldAdapterOptions {
  id: string;
  label: string;
  getValue: () => string;
  getDirty: () => boolean;
  getSelection: () => SelectionSnapshot | null;
  hashValue: (value: string) => string | Promise<string>;
  applyEditorContent: (
    nextValue: string,
    meta: Readonly<AIApplyMeta>,
  ) => void | Promise<void>;
  scheduleAutosave: (
    nextValue: string,
    meta: Readonly<AIApplyMeta>,
  ) => void | Promise<void>;
  restoreSelection: (range: SelectionRange) => void;
  focus: () => void;
  onApplied?: (receipt: BodyFieldApplyReceipt) => void;
  dispose?: () => void;
}


export class BodyFieldBaselineConflictError extends Error {
  readonly code = "baseline-conflict";

  constructor(
    readonly fieldId: string,
    readonly expectedSha256: string,
    readonly actualSha256: string,
  ) {
    super(`正文基线已变化，拒绝应用到字段 ${fieldId}`);
    this.name = "BodyFieldBaselineConflictError";
  }
}


export class BodyFieldControlledUpdateError extends Error {
  readonly code = "controlled-update-rejected";

  constructor(readonly fieldId: string) {
    super(`受控正文状态未接受应用值：${fieldId}`);
    this.name = "BodyFieldControlledUpdateError";
  }
}


function cloneSelection(
  selection: SelectionSnapshot | null,
): SelectionSnapshot | null {
  return selection ? { ...selection } : null;
}


function cloneRange(range: SelectionRange): SelectionRange {
  return { ...range };
}


function cloneMeta(meta: AIApplyMeta): Readonly<AIApplyMeta> {
  return { ...meta };
}


function validateIdentity(id: string, label: string): void {
  if (!id.trim()) throw new Error("assistant body field id must not be empty");
  if (!label.trim()) throw new Error("assistant body field label must not be empty");
}


export function createAssistantBodyFieldAdapter(
  options: AssistantBodyFieldAdapterOptions,
): AssistantBodyFieldAdapter {
  validateIdentity(options.id, options.label);

  let disposed = false;
  let lastReceipt: BodyFieldApplyReceipt | null = null;
  let applyQueue: Promise<void> = Promise.resolve();

  const assertActive = () => {
    if (disposed) throw new Error("Assistant body field adapter is disposed");
  };

  const apply = async (
    nextValue: string,
    rawMeta: AIApplyMeta,
  ): Promise<BodyFieldApplyReceipt> => {
    assertActive();
    const meta = cloneMeta(rawMeta);
    const beforeValue = options.getValue();
    const beforeSelection = cloneSelection(options.getSelection());
    const beforeDirty = options.getDirty();
    const beforeSha256 = await options.hashValue(beforeValue);

    // Hashing may be asynchronous. Re-check the getter so typing during that
    // window cannot turn a valid proposal into a stale overwrite.
    if (
      beforeSha256 !== meta.sourceValueSha256
      || options.getValue() !== beforeValue
    ) {
      const actualValue = options.getValue();
      const actualSha256 = actualValue === beforeValue
        ? beforeSha256
        : await options.hashValue(actualValue);
      throw new BodyFieldBaselineConflictError(
        options.id,
        meta.sourceValueSha256,
        actualSha256,
      );
    }

    // Compute the receipt hash before mutating controlled state. This keeps
    // the apply-to-autosave handoff free of an extra asynchronous hash gap.
    const afterSha256 = nextValue === beforeValue
      ? beforeSha256
      : await options.hashValue(nextValue);
    if (options.getValue() !== beforeValue) {
      const actualValue = options.getValue();
      throw new BodyFieldBaselineConflictError(
        options.id,
        meta.sourceValueSha256,
        await options.hashValue(actualValue),
      );
    }

    assertActive();
    await options.applyEditorContent(nextValue, meta);

    // A React setter alone is not a sufficient write path for this adapter.
    // The callback must update the page's controlled getter/ref as one action.
    const appliedValue = options.getValue();
    if (appliedValue !== nextValue) {
      throw new BodyFieldControlledUpdateError(options.id);
    }

    const receipt: BodyFieldApplyReceipt = {
      fieldId: options.id,
      meta,
      before: {
        value: beforeValue,
        valueSha256: beforeSha256,
        selection: beforeSelection,
        dirty: beforeDirty,
      },
      after: {
        value: appliedValue,
        valueSha256: afterSha256,
        selection: cloneSelection(options.getSelection()),
        dirty: options.getDirty(),
      },
      persistence: "autosave",
      autosaveRequested: true,
    };

    // Keep the receipt before requesting persistence. If scheduling fails, the
    // local controlled edit still has enough evidence for a later undo.
    lastReceipt = receipt;
    await options.scheduleAutosave(appliedValue, meta);
    options.onApplied?.(receipt);
    return receipt;
  };

  const enqueueApply = (
    nextValue: string,
    meta: AIApplyMeta,
  ): Promise<BodyFieldApplyReceipt> => {
    const result = applyQueue.then(
      () => apply(nextValue, meta),
      () => apply(nextValue, meta),
    );
    applyQueue = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  };

  return {
    id: options.id,
    label: options.label,
    persistence: "autosave",
    undoPolicy: "ai-transaction",
    getValue() {
      assertActive();
      return options.getValue();
    },
    async applyValue(nextValue, meta) {
      await enqueueApply(nextValue, meta);
    },
    applyValueWithReceipt(nextValue, meta) {
      return enqueueApply(nextValue, meta);
    },
    getLastApplyReceipt() {
      return lastReceipt;
    },
    getSelection() {
      assertActive();
      return cloneSelection(options.getSelection());
    },
    restoreSelection(range) {
      assertActive();
      options.restoreSelection(cloneRange(range));
    },
    focus() {
      assertActive();
      options.focus();
    },
    getDirty() {
      assertActive();
      return options.getDirty();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      options.dispose?.();
    },
  };
}
