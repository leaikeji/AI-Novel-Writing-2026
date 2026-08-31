import { chapterDisplayTitle, volumeDisplayTitle } from "./presenters";
import { DocumentRecord, NovelRecord, VolumeRecord } from "./types";


export interface ChapterTreeChapter {
  document: DocumentRecord;
  chapterNumber: number;
  displayTitle: string;
}


export interface ChapterTreeVolume {
  key: string;
  volume: VolumeRecord;
  volumeNumber: number | null;
  displayTitle: string;
  chapters: ChapterTreeChapter[];
}


export function canonicalVolumeRecords(novel: NovelRecord): VolumeRecord[] {
  const byPosition = (left: VolumeRecord, right: VolumeRecord) => left.position - right.position;
  return [
    ...novel.tree.filter((volume) => volume.id !== null).sort(byPosition),
    ...novel.tree.filter((volume) => volume.id === null).sort(byPosition),
  ];
}


export function canonicalChapterDocuments(novel: NovelRecord): DocumentRecord[] {
  return canonicalVolumeRecords(novel).flatMap((volume) => (
    [...volume.documents]
      .filter((document) => document.kind === "chapter")
      .sort((left, right) => left.position - right.position)
  ));
}


export function chapterOrdinalFor(novel: NovelRecord, documentId: string): number | undefined {
  const index = canonicalChapterDocuments(novel)
    .findIndex((document) => document.id === documentId);
  return index < 0 ? undefined : index + 1;
}


export function nextChapterOrdinalForVolume(
  novel: NovelRecord,
  volumeId: string,
): number | undefined {
  let chaptersBeforeTarget = 0;
  for (const volume of canonicalVolumeRecords(novel)) {
    if (volume.id === null) break;
    const chapterCount = volume.documents.filter((document) => document.kind === "chapter").length;
    if (volume.id === volumeId) return chaptersBeforeTarget + chapterCount + 1;
    chaptersBeforeTarget += chapterCount;
  }
  return undefined;
}


export function buildChapterTreeVolumes(novel: NovelRecord, query = ""): ChapterTreeVolume[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  let chapterNumber = 0;
  let volumeNumber = 0;
  return canonicalVolumeRecords(novel)
    .map((volume: VolumeRecord) => {
      if (volume.id !== null) volumeNumber += 1;
      const chapters = [...volume.documents]
        .sort((left: DocumentRecord, right: DocumentRecord) => left.position - right.position)
        .filter((item: DocumentRecord) => item.kind === "chapter")
        .map((item: DocumentRecord) => {
          chapterNumber += 1;
          return {
            document: item,
            chapterNumber,
            displayTitle: chapterDisplayTitle(chapterNumber, item.title),
          };
        });
      return {
        key: volume.id ?? "unassigned",
        volume,
        volumeNumber: volume.id === null ? null : volumeNumber,
        displayTitle: volume.id === null
          ? "未分卷"
          : volumeDisplayTitle(volumeNumber, volume.title),
        chapters,
      };
    })
    .filter((item: ChapterTreeVolume) => item.chapters.length > 0)
    .map((item: ChapterTreeVolume) => {
      if (!normalizedQuery) return item;
      const volumeMatches = item.displayTitle.toLocaleLowerCase().includes(normalizedQuery)
        || item.volume.title.toLocaleLowerCase().includes(normalizedQuery);
      return {
        ...item,
        chapters: volumeMatches
          ? item.chapters
          : item.chapters.filter((chapter: ChapterTreeChapter) => (
              chapter.displayTitle.toLocaleLowerCase().includes(normalizedQuery)
              || chapter.document.title.toLocaleLowerCase().includes(normalizedQuery)
            )),
      };
    })
    .filter((item: ChapterTreeVolume) => item.chapters.length > 0);
}
