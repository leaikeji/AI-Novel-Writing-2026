import type { ChapterTreeChapter, ChapterTreeVolume } from "../chapter-tree";


export const CHAPTER_TREE_ROW_HEIGHT = 42;
export const CHAPTER_TREE_OVERSCAN_ROWS = 8;


export type ChapterTreeVirtualRow =
  | Readonly<{
      kind: "volume";
      key: string;
      volume: ChapterTreeVolume;
    }>
  | Readonly<{
      kind: "chapter";
      key: string;
      volumeKey: string;
      chapter: ChapterTreeChapter;
    }>;


export interface ChapterTreeVirtualWindow {
  readonly rows: ReadonlyArray<Readonly<{
    row: ChapterTreeVirtualRow;
    index: number;
    top: number;
  }>>;
  readonly totalHeight: number;
}


export interface FixedVirtualWindow<T> {
  readonly rows: ReadonlyArray<Readonly<{
    row: T;
    index: number;
    top: number;
  }>>;
  readonly totalHeight: number;
}


export function virtualizeFixedRows<T>(
  rows: ReadonlyArray<T>,
  scrollTop: number,
  viewportHeight: number,
  rowHeight: number,
  overscanRows: number,
): FixedVirtualWindow<T> {
  const totalHeight = rows.length * rowHeight;
  if (!rows.length || viewportHeight <= 0) return { rows: [], totalHeight };
  const maximumScrollTop = Math.max(0, totalHeight - viewportHeight);
  const boundedScrollTop = Math.min(Math.max(0, scrollTop), maximumScrollTop);
  const firstVisible = Math.floor(boundedScrollTop / rowHeight);
  const visibleCount = Math.max(1, Math.ceil(viewportHeight / rowHeight));
  const start = Math.max(0, firstVisible - overscanRows);
  const end = Math.min(rows.length, firstVisible + visibleCount + overscanRows);
  return {
    totalHeight,
    rows: rows.slice(start, end).map((row, offset) => {
      const index = start + offset;
      return { row, index, top: index * rowHeight };
    }),
  };
}


export function fixedVirtualScrollTarget(
  key: string,
  scrollTop: number,
  viewportHeight: number,
  totalHeight: number,
): number | null {
  const maximum = Math.max(0, totalHeight - viewportHeight);
  const page = Math.max(1, viewportHeight);
  if (key === "Home") return 0;
  if (key === "End") return maximum;
  if (key === "PageUp") return Math.max(0, scrollTop - page);
  if (key === "PageDown") return Math.min(maximum, scrollTop + page);
  return null;
}


export function flattenChapterTreeRows(
  volumes: ReadonlyArray<ChapterTreeVolume>,
  expandedVolumeKeys: ReadonlySet<string>,
  forceExpanded = false,
): ChapterTreeVirtualRow[] {
  const rows: ChapterTreeVirtualRow[] = [];
  for (const volume of volumes) {
    rows.push({ kind: "volume", key: `volume:${volume.key}`, volume });
    if (!forceExpanded && !expandedVolumeKeys.has(volume.key)) continue;
    for (const chapter of volume.chapters) {
      rows.push({
        kind: "chapter",
        key: `chapter:${chapter.document.id}`,
        volumeKey: volume.key,
        chapter,
      });
    }
  }
  return rows;
}


export function virtualizeChapterTreeRows(
  rows: ReadonlyArray<ChapterTreeVirtualRow>,
  scrollTop: number,
  viewportHeight: number,
  rowHeight = CHAPTER_TREE_ROW_HEIGHT,
  overscanRows = CHAPTER_TREE_OVERSCAN_ROWS,
): ChapterTreeVirtualWindow {
  return virtualizeFixedRows(
    rows,
    scrollTop,
    viewportHeight,
    rowHeight,
    overscanRows,
  );
}
