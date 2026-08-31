import type { StoryFactRecord } from "./types";


export type FactViewState = "current" | "stale" | "empty";


export interface FactView {
  facts: StoryFactRecord[];
  state: FactViewState;
}


const FACT_TYPE_LABELS: Record<string, string> = {
  character_state: "人物状态",
  clue: "线索",
  fact: "故事事实",
  foreshadow: "伏笔",
  foreshadow_new: "新增伏笔",
  foreshadow_progress: "伏笔推进",
  foreshadow_resolved: "伏笔回收",
  relationship: "人物关系",
  setting: "故事设定",
  storyline_event: "剧情事件",
};


const FACT_STATUS_LABELS: Record<string, string> = {
  active: "当前有效",
  detached: "已解除关联",
  source_archived: "来源已归档",
  source_restored: "已随版本恢复",
  source_superseded: "基于旧稿",
};


const REVISION_SOURCE_LABELS: Record<string, string> = {
  ai_candidate_adopt: "采用 AI 候选",
  initial: "初始版本",
  manual: "手动版本",
  manual_checkpoint: "手动保存",
  manual_restore: "历史恢复",
  pre_restore_checkpoint: "恢复前保护版本",
};


export function factTypeLabel(value: string): string {
  return FACT_TYPE_LABELS[value] ?? "其他资料";
}


export function factStatusLabel(value: string): string {
  return FACT_STATUS_LABELS[value] ?? "状态未知";
}


export function revisionSourceLabel(value: string): string {
  return REVISION_SOURCE_LABELS[value] ?? "版本记录";
}


export function chapterTitleName(title: string): string {
  return title
    .trim()
    .replace(
      /^第\s*(?:\d+|[零〇一二三四五六七八九十百千万两]+)\s*章(?=$|[\s:：·—-])(?:[\s:：·—-]+)?/,
      "",
    )
    .trim();
}


export function chapterDisplayTitle(chapterNumber: number, title: string): string {
  const cleanTitle = chapterTitleName(title);
  return `第${chapterNumber}章${cleanTitle ? ` ${cleanTitle}` : ""}`;
}


export function chapterTitleForStorage(chapterNumber: number, title: string): string {
  void chapterNumber;
  return chapterTitleName(title);
}


export function volumeTitleName(title: string): string {
  return title
    .trim()
    .replace(
      /^第\s*(?:\d+|[零〇一二三四五六七八九十百千万两]+)\s*卷(?=$|[\s:：·—-])(?:[\s:：·—-]+)?/,
      "",
    )
    .trim();
}


export function volumeDisplayTitle(volumeNumber: number, title: string): string {
  const cleanTitle = volumeTitleName(title);
  return `第${volumeNumber}卷${cleanTitle ? ` ${cleanTitle}` : ""}`;
}


export function volumeTitleForStorage(volumeNumber: number, title: string): string {
  void volumeNumber;
  return volumeTitleName(title);
}


export function isClueFactType(value: string): boolean {
  return value === "clue"
    || value === "fact"
    || value === "storyline_event"
    || value.startsWith("foreshadow");
}


export function selectFactView(
  facts: StoryFactRecord[],
  matches: (fact: StoryFactRecord) => boolean,
): FactView {
  const relevant = facts.filter(matches);
  const current = relevant.filter(
    (fact) => fact.status === "active" || fact.status === "source_restored",
  );
  if (current.length) return { facts: current, state: "current" };

  const stale = relevant.filter((fact) => fact.status === "source_superseded");
  if (stale.length) return { facts: stale, state: "stale" };

  return { facts: [], state: "empty" };
}
