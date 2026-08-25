import type {
  AIApplyMeta,
  EditableFieldAdapter,
  SelectionRange,
  SelectionSnapshot,
} from "./assistant-fields";


export interface FormFieldApplyState {
  readonly value: string;
  readonly valueSha256: string;
  readonly selection: SelectionSnapshot | null;
  readonly dirty: boolean;
}


export interface FormFieldApplyReceipt {
  readonly fieldId: string;
  readonly meta: Readonly<AIApplyMeta>;
  readonly before: FormFieldApplyState;
  readonly after: FormFieldApplyState;
  readonly persistence: "explicit-save";
  readonly saveRequested: false;
}


export interface AssistantFormFieldAdapter extends EditableFieldAdapter {
  readonly persistence: "explicit-save";
  applyValue(nextValue: string, meta: AIApplyMeta): Promise<void>;
  applyValueWithReceipt(
    nextValue: string,
    meta: AIApplyMeta,
  ): Promise<FormFieldApplyReceipt>;
  getLastApplyReceipt(): FormFieldApplyReceipt | null;
  restoreSelection(range: SelectionRange): void;
}


export interface AssistantFormFieldAdapterOptions {
  id: string;
  label: string;
  getValue: () => string;
  getDirty: () => boolean;
  getSelection: () => SelectionSnapshot | null;
  hashValue: (value: string) => string | Promise<string>;
  applyDraftValue: (
    nextValue: string,
    meta: Readonly<AIApplyMeta>,
  ) => void | Promise<void>;
  markDirty: (meta: Readonly<AIApplyMeta>) => void | Promise<void>;
  restoreSelection: (range: SelectionRange) => void;
  focus: () => void;
  onApplied?: (receipt: FormFieldApplyReceipt) => void;
  dispose?: () => void;
}


export class FormFieldBaselineConflictError extends Error {
  readonly code = "baseline-conflict";

  constructor(
    readonly fieldId: string,
    readonly expectedSha256: string,
    readonly actualSha256: string,
  ) {
    super(`表单基线已变化，拒绝应用到字段 ${fieldId}`);
    this.name = "FormFieldBaselineConflictError";
  }
}


export class FormFieldControlledUpdateError extends Error {
  readonly code = "controlled-update-rejected";

  constructor(readonly fieldId: string) {
    super(`受控表单状态未接受应用值：${fieldId}`);
    this.name = "FormFieldControlledUpdateError";
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
  if (!id.trim()) throw new Error("assistant form field id must not be empty");
  if (!label.trim()) throw new Error("assistant form field label must not be empty");
}


export function createAssistantFormFieldAdapter(
  options: AssistantFormFieldAdapterOptions,
): AssistantFormFieldAdapter {
  validateIdentity(options.id, options.label);

  let disposed = false;
  let lastReceipt: FormFieldApplyReceipt | null = null;
  let applyQueue: Promise<void> = Promise.resolve();

  const assertActive = () => {
    if (disposed) throw new Error("Assistant form field adapter is disposed");
  };

  const apply = async (
    nextValue: string,
    rawMeta: AIApplyMeta,
  ): Promise<FormFieldApplyReceipt> => {
    assertActive();
    const meta = cloneMeta(rawMeta);
    const beforeValue = options.getValue();
    const beforeSelection = cloneSelection(options.getSelection());
    const beforeDirty = options.getDirty();
    const beforeSha256 = await options.hashValue(beforeValue);

    if (
      beforeSha256 !== meta.sourceValueSha256
      || options.getValue() !== beforeValue
    ) {
      const actualValue = options.getValue();
      const actualSha256 = actualValue === beforeValue
        ? beforeSha256
        : await options.hashValue(actualValue);
      throw new FormFieldBaselineConflictError(
        options.id,
        meta.sourceValueSha256,
        actualSha256,
      );
    }

    const afterSha256 = nextValue === beforeValue
      ? beforeSha256
      : await options.hashValue(nextValue);
    if (options.getValue() !== beforeValue) {
      const actualValue = options.getValue();
      throw new FormFieldBaselineConflictError(
        options.id,
        meta.sourceValueSha256,
        await options.hashValue(actualValue),
      );
    }

    assertActive();
    await options.applyDraftValue(nextValue, meta);
    const appliedValue = options.getValue();
    if (appliedValue !== nextValue) {
      throw new FormFieldControlledUpdateError(options.id);
    }

    // This is deliberately the only persistence-related callback exposed by
    // the form adapter. The existing page save button remains the sole owner
    // of server persistence.
    await options.markDirty(meta);
    const receipt: FormFieldApplyReceipt = {
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
      persistence: "explicit-save",
      saveRequested: false,
    };

    lastReceipt = receipt;
    options.onApplied?.(receipt);
    return receipt;
  };

  const enqueueApply = (
    nextValue: string,
    meta: AIApplyMeta,
  ): Promise<FormFieldApplyReceipt> => {
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
    persistence: "explicit-save",
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
