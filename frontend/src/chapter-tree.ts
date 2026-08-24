import { chapterDisplayTitle } from "./presenters";
import { DocumentRecord, NovelRecord, VolumeRecord } from "./types";


export interface ChapterTreeChapter {
  document: DocumentRecord;
  displayTitle: string;
}


export interface ChapterTreeVolume {
  key: string;
  volume: VolumeRecord;
  chapters: ChapterTreeChapter[];
}


export function buildChapterTreeVolumes(novel: NovelRecord, query = ""): ChapterTreeVolume[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  let chapterNumber = 0;
  return [...novel.tree]
    .sort((left: VolumeRecord, right: VolumeRecord) => left.position - right.position)
    .map((volume: VolumeRecord) => {
      const chapters = [...volume.documents]
        .sort((left: DocumentRecord, right: DocumentRecord) => left.position - right.position)
        .filter((item: DocumentRecord) => item.kind === "chapter")
        .map((item: DocumentRecord) => {
          chapterNumber += 1;
          return {
            document: item,
            displayTitle: chapterDisplayTitle(chapterNumber, item.title),
          };
        });
      return {
        key: volume.id ?? "unassigned",
        volume,
        chapters,
      };
    })
    .filter((item: ChapterTreeVolume) => item.chapters.length > 0)
    .map((item: ChapterTreeVolume) => {
      if (!normalizedQuery) return item;
      const volumeMatches = item.volume.title.toLocaleLowerCase().includes(normalizedQuery);
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
