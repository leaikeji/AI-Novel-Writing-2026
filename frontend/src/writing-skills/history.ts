import { apiRequest } from "../api";
import type { QwenPawReactRuntime } from "../assistant-pane";
import { writingPageTabId } from "./chapter";
import { isWritingActionId, WRITING_METHOD_STATES } from "./contracts";
import { methodDetailLines, parseMethodDetails, type MethodDetails } from "./details";

export interface ChapterMethodHistory {
  readonly record_status: "legacy_unrecorded" | "evidence_unavailable" | "recorded";
  readonly phase: string | null;
  readonly method_input_hash: string | null;
  readonly details: MethodDetails | null;
}
export function parseChapterMethodHistory(value: unknown, documentId: string, jobId: string): ChapterMethodHistory | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  if (data.schema_version !== "chapter-method-history/1" || data.document_id !== documentId || data.job_id !== jobId
    || !isWritingActionId(documentId) || !isWritingActionId(jobId)) return null;
  if (data.record_status === "legacy_unrecorded" || data.record_status === "evidence_unavailable") {
    if (data.details !== null || data.phase !== null || data.method_input_hash !== null) return null;
    return { record_status: data.record_status, details: null, phase: null, method_input_hash: null };
  }
  const details = parseMethodDetails(data.details);
  if (data.record_status !== "recorded" || !details || typeof data.method_input_hash !== "string"
    || !/^[a-f0-9]{64}$/.test(data.method_input_hash) || !WRITING_METHOD_STATES.some(state => state === data.phase)) return null;
  return { record_status: "recorded", details, phase: data.phase as string, method_input_hash: data.method_input_hash };
}
export function historyLines(value: ChapterMethodHistory): readonly string[] {
  if (value.record_status === "legacy_unrecorded") return ["旧任务未记录写作方法（legacy_unrecorded），不能据生成成功推定 Skill 已装载。"];
  if (value.record_status === "evidence_unavailable") return ["原任务有方法引用，但证据缺失或不一致；未使用当前版本补写历史。"];
  return [value.phase === "dispatched" ? "原请求已确认派发；不代表模型遵循或写作效果已验证。"
    : `原记录阶段：${value.phase}；下列为冻结方法，不代表生成成功。`,
  ...methodDetailLines(value.details!), `方法摘要：${value.method_input_hash}`];
}
/** Explicit, lazy job-history GET. Never installs a live action/recovery ticket. */
export function createChapterMethodHistory(React: Pick<QwenPawReactRuntime, "createElement" | "useState" | "useEffect">) {
  const h = React.createElement;
  return function ChapterMethodHistoryNotice({ documentId, jobId }: { documentId: string; jobId: string }) {
    const [open, setOpen] = React.useState(false);
    const key = `${documentId}:${jobId}`;
    const [stored, setStored] = React.useState(null as { key: string; value: ChapterMethodHistory } | null);
    const value = stored?.key === key ? stored.value : null;
    const [error, setError] = React.useState("");
    React.useEffect(() => {
      if (!open || value) return;
      let active = true;
      setError("");
      void Promise.resolve().then(() => {
        const query = new URLSearchParams({ tab_id: writingPageTabId() });
        return apiRequest<unknown>(`/documents/${documentId}/generation-jobs/${jobId}/writing-method?${query}`);
      }).then(raw => {
        if (!active) return;
        const parsed = parseChapterMethodHistory(raw, documentId, jobId);
        if (!parsed) throw new Error("history scope mismatch");
        setStored({ key, value: parsed });
      }).catch(() => { if (active) setError("方法证据暂时无法确认；此查询不会重新生成。"); });
      return () => { active = false; };
    }, [open, documentId, jobId]);
    return h("details", { className: "anw-writing-method-history",
      style: { minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere" },
      onToggle: (event: { currentTarget: { open: boolean } }) => setOpen(event.currentTarget.open),
    }, h("summary", { style: { cursor: "pointer" } }, "查看本任务写作方法证据"),
    h("div", { role: "status", style: { maxHeight: "16rem", overflowY: "auto" }, tabIndex: 0 },
      ...(value ? historyLines(value).map((line, index) => h("p", { key: index }, line))
        : [h("p", null, error || (open ? "正在读取原任务记录…" : "展开后只读查询，不调用模型。"))])));
  };
}
