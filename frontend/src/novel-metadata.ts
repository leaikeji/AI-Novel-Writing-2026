import { ApiError, apiErrorMessage, apiRequest } from "./api";
import type { NovelMetadataRecord } from "./types";

export interface MetadataDraft {
  title: string;
  author_name: string;
  expected_version: number;
}

export function metadataDraft(novel: NovelMetadataRecord): MetadataDraft {
  return { title: novel.title, author_name: novel.author_name, expected_version: novel.version };
}

export function metadataValidation(draft: MetadataDraft): string | null {
  if (!draft.title.trim() || draft.title.trim().length > 240) return "请输入1—240字符的书名。";
  if (!draft.author_name.trim() || draft.author_name.trim().length > 120) return "请输入1—120字符的作者笔名。";
  return null;
}

export function saveNovelMetadata(novelId: string, draft: MetadataDraft): Promise<NovelMetadataRecord> {
  return apiRequest<NovelMetadataRecord>(`/novels/${encodeURIComponent(novelId)}/metadata`, {
    method: "PUT", body: JSON.stringify({ ...draft, title: draft.title.trim(), author_name: draft.author_name.trim() }),
  });
}

export function NovelMetadataEditor(props: {
  novel: NovelMetadataRecord;
  onChanged: (novel: NovelMetadataRecord) => void;
}) {
  const { React, antd } = window.QwenPaw.host;
  const h = React.createElement;
  const { Button, Modal, Input, Alert } = antd;
  const [draft, setDraft] = React.useState(null as MetadataDraft | null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [conflict, setConflict] = React.useState(false);
  const pending = React.useRef(false);
  const activeId = React.useRef(props.novel.id);
  activeId.current = props.novel.id;
  React.useEffect(() => { setDraft(null); setError(""); setConflict(false); }, [props.novel.id]);
  const open = () => { setDraft(metadataDraft(props.novel)); setError(""); setConflict(false); };
  const save = async () => {
    if (!draft || pending.current || conflict) return;
    const invalid = metadataValidation(draft);
    if (invalid) { setError(invalid); return; }
    const id = props.novel.id;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const updated = await saveNovelMetadata(id, draft);
      if (activeId.current === id) { props.onChanged(updated); setDraft(null); }
    } catch (failure) {
      if (activeId.current === id) {
        const isConflict = failure instanceof ApiError && failure.status === 409;
        setConflict(isConflict);
        setError(isConflict ? "作品已在其他位置更新。你的输入仍保留；载入最新资料会替换当前输入，请核对后重新修改。" : apiErrorMessage(failure, "保存失败，输入已保留，请核对网络后重试。"));
      }
    } finally { pending.current = false; setBusy(false); }
  };
  const refresh = async () => {
    if (pending.current) return;
    pending.current = true; setBusy(true);
    const id = props.novel.id;
    try {
      const latest = await apiRequest<NovelMetadataRecord>(`/novels/${encodeURIComponent(id)}`);
      if (activeId.current === id) {
        props.onChanged(latest); setDraft(metadataDraft(latest)); setConflict(false); setError("");
      }
    } catch (failure) { setError(apiErrorMessage(failure, "读取失败，输入已保留。")); }
    finally { pending.current = false; setBusy(false); }
  };
  return h(React.Fragment, null,
    h(Button, { size: "small", onClick: open }, "作品资料"),
    h(Modal, {
      title: "作品资料", open: draft !== null, width: 480, centered: true,
      confirmLoading: busy, okText: "保存", cancelText: "取消",
      onOk: () => void save(), onCancel: () => { if (!busy) setDraft(null); },
      closable: !busy, maskClosable: false, keyboard: !busy,
      cancelButtonProps: { disabled: busy }, okButtonProps: { disabled: conflict },
    }, draft ? h("div", { className: "mb-form-stack" },
      h("label", { htmlFor: "anw-novel-title" }, "书名"),
      h(Input, { id: "anw-novel-title", autoFocus: true, maxLength: 240, value: draft.title, disabled: busy,
        onChange: (event: { target: { value: string } }) => setDraft({ ...draft, title: event.target.value }) }),
      h("label", { htmlFor: "anw-novel-author" }, "作者笔名"),
      h(Input, { id: "anw-novel-author", maxLength: 120, value: draft.author_name, disabled: busy,
        onChange: (event: { target: { value: string } }) => setDraft({ ...draft, author_name: event.target.value }) }),
      h("small", null, "修改不影响正文与大纲。文字封面会同步更新；已有图片封面不会自动重绘。"),
      error ? h(Alert, { type: "error", message: error, showIcon: true, role: "alert" }) : null,
      conflict ? h(Button, { onClick: () => void refresh(), disabled: busy }, "载入最新资料") : null,
    ) : null),
  );
}
