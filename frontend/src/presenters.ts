const REVISION_SOURCE_LABELS: Record<string, string> = {
  ai_candidate_adopt: "采用 AI 候选",
  initial: "初始版本",
  manual: "手动版本",
  manual_checkpoint: "手动保存",
  manual_restore: "历史恢复",
  pre_restore_checkpoint: "恢复前保护版本",
};


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
