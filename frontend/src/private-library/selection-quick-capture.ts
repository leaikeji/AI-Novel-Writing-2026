import type { LexiconAction, PrivateLibraryCategory } from "./contracts";
import {
  LEXICON_ACTION_LABEL,
  PRIVATE_LIBRARY_CATEGORIES,
  PRIVATE_LIBRARY_CATEGORY_META,
} from "./model";
import type {
  InputChangeEvent,
  PrivateLibraryAntdRuntime,
  PrivateLibraryReactRuntime,
} from "./ui-runtime";


export interface SelectionCaptureTarget {
  readonly assetId: string;
  readonly title: string;
  readonly category: PrivateLibraryCategory;
  readonly scopeKind: "library" | "novel";
  readonly scopeNovelId?: string;
}


export interface SelectionCaptureInput {
  readonly selectedText: string;
  readonly category: PrivateLibraryCategory;
  readonly targetAssetId?: string;
  readonly action: LexiconAction;
  readonly destination: "collect" | "use_current_novel";
  readonly novelId?: string;
}


export interface SelectionQuickCaptureProps {
  readonly selectedText: string;
  readonly activeNovel?: { readonly id: string; readonly title: string } | null;
  readonly targets: readonly SelectionCaptureTarget[];
  readonly disabled?: boolean;
  readonly onCancel: () => void;
  readonly onSave: (input: SelectionCaptureInput) => void | Promise<void>;
}


export function createSelectionQuickCapture(
  React: PrivateLibraryReactRuntime,
  antd: Pick<PrivateLibraryAntdRuntime, "Alert" | "Button" | "Card" | "Input" | "Select">,
): (props: SelectionQuickCaptureProps) => unknown {
  const h = React.createElement;
  const { Alert, Button, Card, Input, Select } = antd;

  return function SelectionQuickCapture(props: SelectionQuickCaptureProps): unknown {
    const [category, setCategory] = React.useState<PrivateLibraryCategory>("vocabulary");
    const [action, setAction] = React.useState<LexiconAction>("recommend");
    const [destination, setDestination] = React.useState<SelectionCaptureInput["destination"]>("collect");
    const [targetAssetId, setTargetAssetId] = React.useState<string | undefined>(undefined);
    const [saving, setSaving] = React.useState(false);
    const [saveError, setSaveError] = React.useState<string | null>(null);

    const targets = props.targets.filter((target) => (
      target.category === category
      && (destination === "collect"
        ? target.scopeKind === "library"
        : target.scopeKind === "library"
          || (target.scopeKind === "novel" && target.scopeNovelId === props.activeNovel?.id))
    ));
    const validTargetId = targets.some((target) => target.assetId === targetAssetId)
      ? targetAssetId
      : undefined;
    const lexiconTooLong = category === "vocabulary"
      && [...props.selectedText.trim()].length > 80;
    const canSave = Boolean(props.selectedText.trim()) && !lexiconTooLong && (
      destination !== "use_current_novel" || Boolean(props.activeNovel)
    );

    const save = () => {
      if (!canSave || saving) return;
      setSaving(true);
      setSaveError(null);
      void Promise.resolve(props.onSave({
        selectedText: props.selectedText,
        category,
        targetAssetId: validTargetId,
        action,
        destination,
        novelId: destination === "use_current_novel" ? props.activeNovel?.id : undefined,
      })).then(() => {
        setSaving(false);
      }).catch((error: unknown) => {
        setSaving(false);
        setSaveError(error instanceof Error ? error.message : "保存失败，选中文本仍保留在面板中。");
      });
    };

    return h(
      Card,
      { className: "anw-private-library-capture", title: "添加到私有库" },
      h("label", null,
        h("span", null, "选中文本"),
        h(Input.TextArea, {
          value: props.selectedText,
          readOnly: true,
          rows: 4,
          "aria-label": "要收藏的选中文本",
        }),
      ),
      h("label", null,
        h("span", null, "资料分类"),
        h(Select, {
          value: category,
          options: PRIVATE_LIBRARY_CATEGORIES.map((value) => ({ value, label: PRIVATE_LIBRARY_CATEGORY_META[value].label })),
          "aria-label": "选中文本资料分类",
          onChange: (value: PrivateLibraryCategory) => {
            setCategory(value);
            setTargetAssetId(undefined);
          },
        }),
      ),
      category === "vocabulary"
        ? h("label", null,
            h("span", null, "使用方式"),
            h(Select, {
              value: action,
              options: Object.entries(LEXICON_ACTION_LABEL).map(([value, label]) => ({ value, label })),
              "aria-label": "选中文本使用方式",
              onChange: (value: LexiconAction) => setAction(value),
            }),
          )
        : null,
      h("label", null,
        h("span", null, "保存动作"),
        h(Select, {
          value: destination,
          options: [
            { value: "collect", label: "仅收藏到通用库" },
            ...(props.activeNovel ? [{ value: "use_current_novel", label: `保存并用于《${props.activeNovel.title}》` }] : []),
          ],
          "aria-label": "选中文本保存动作",
          onChange: (value: SelectionCaptureInput["destination"]) => {
            setDestination(value);
            setTargetAssetId(undefined);
          },
        }),
      ),
      h("label", null,
        h("span", null, "目标资料（可选）"),
        h(Select, {
          value: validTargetId,
          allowClear: true,
          placeholder: "不选择则保存到默认收集处",
          options: targets.map((target) => ({ value: target.assetId, label: target.title })),
          "aria-label": "选中文本目标资料",
          onChange: (value: string | undefined) => setTargetAssetId(value),
        }),
      ),
      h("p", { className: "anw-private-library-capture__destination", role: "status" },
        destination === "use_current_novel" && props.activeNovel
          ? `将保存到《${props.activeNovel.title}》的本书专用资料，并立即用于本书。`
          : "将收藏到通用库，不会自动用于任何作品。",
      ),
      saveError ? h(Alert, { type: "error", showIcon: true, message: saveError }) : null,
      !props.selectedText.trim() ? h(Alert, { type: "warning", message: "选中文本已失效，请重新选择。" }) : null,
      lexiconTooLong ? h(Alert, {
        type: "warning",
        message: "用词条目最多 80 个字符；请缩小选区，或改存为文风、机制或灵感。",
      }) : null,
      h("div", { className: "anw-private-library-capture__actions" },
        h(Button, { disabled: saving, onClick: props.onCancel }, "取消"),
        h(Button, {
          type: "primary",
          loading: saving,
          disabled: props.disabled === true || !canSave,
          onClick: save,
        }, destination === "use_current_novel" ? "保存并用于本书" : "收藏"),
      ),
    );
  };
}
