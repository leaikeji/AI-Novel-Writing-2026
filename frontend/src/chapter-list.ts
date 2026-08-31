import type { DocumentVersionState } from "./types";


export type ChapterVersionTone = "draft" | "saved" | "checkpointed";

export interface ChapterVersionPresentation {
  readonly label: string;
  readonly description: string;
  readonly tone: ChapterVersionTone;
}


const VERSION_PRESENTATIONS: Record<DocumentVersionState, ChapterVersionPresentation> = {
  empty_draft: {
    label: "空白草稿",
    description: "章节已经创建，正文还没有内容。",
    tone: "draft",
  },
  saved_working_copy: {
    label: "工作稿已保存",
    description: "当前正文已保存到工作稿，但还没有建立对应检查点。",
    tone: "saved",
  },
  checkpointed: {
    label: "已建检查点",
    description: "当前正文与最近一次不可变检查点一致。",
    tone: "checkpointed",
  },
};


export function chapterVersionPresentation(
  state: DocumentVersionState | null | undefined,
): ChapterVersionPresentation {
  return state
    ? VERSION_PRESENTATIONS[state]
    : {
        label: "已保存",
        description: "正文已从服务端工作稿读取；当前后端尚未返回检查点状态。",
        tone: "saved",
      };
}


export function formatChapterUpdatedAt(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.month}-${values.day} ${values.hour}:${values.minute}`;
}
