import { apiRequest } from "../api";
import type {
  DocumentRecord,
  NovelMetadataRecord,
  NovelRecord,
  VolumeRecord,
  WorkspaceManifestItem,
  WorkspaceManifestPage,
} from "../types";


export const WORKSPACE_MANIFEST_PAGE_SIZE = 200;


export interface LoadNovelWorkspaceOptions {
  readonly signal?: AbortSignal;
  readonly onPage?: (
    novel: NovelRecord,
    page: WorkspaceManifestPage,
    pageNumber: number,
  ) => void;
}


function segment(value: string): string {
  return encodeURIComponent(value);
}


export function getNovelMetadata(
  novelId: string,
  signal?: AbortSignal,
): Promise<NovelMetadataRecord> {
  return apiRequest<NovelMetadataRecord>(`/novels/${segment(novelId)}`, { signal });
}


export function getWorkspaceManifestPage(
  novelId: string,
  cursor?: string | null,
  signal?: AbortSignal,
): Promise<WorkspaceManifestPage> {
  const query = new URLSearchParams({ limit: String(WORKSPACE_MANIFEST_PAGE_SIZE) });
  if (cursor) query.set("cursor", cursor);
  return apiRequest<WorkspaceManifestPage>(
    `/novels/${segment(novelId)}/workspace-manifest?${query.toString()}`,
    { signal },
  );
}


function navigationDocument(item: WorkspaceManifestItem): DocumentRecord {
  if (item.kind !== "document" || !item.document_type) {
    throw new Error("manifest document item is incomplete");
  }
  // Navigation records never contain a body. The selected-document endpoint
  // replaces this shell before the editor can use content or revision fields.
  return {
    id: item.id,
    novel_id: "",
    volume_id: item.parent_volume_id,
    kind: item.document_type,
    title: item.title,
    position: item.position,
    version: item.version,
    draft_version: item.draft_version ?? 1,
    base_revision_id: item.base_revision_id,
    content_markdown: "",
    content_hash: item.content_hash ?? "",
    visible_character_count: item.visible_character_count ?? 0,
    updated_at: item.updated_at,
    revisions: [],
  };
}


export function appendManifestPage(
  metadata: NovelMetadataRecord,
  current: NovelRecord | null,
  page: WorkspaceManifestPage,
): NovelRecord {
  if (page.novel.id !== metadata.id) throw new Error("manifest novel mismatch");
  const volumes = new Map<string, VolumeRecord>();
  for (const volume of current?.tree ?? []) {
    volumes.set(volume.id ?? "__ungrouped__", {
      ...volume,
      documents: [...volume.documents],
    });
  }
  for (const item of page.items) {
    if (item.kind === "volume") {
      const existing = volumes.get(item.id);
      volumes.set(item.id, {
        id: item.id,
        title: item.title,
        position: item.position,
        version: item.version,
        documents: existing?.documents ?? [],
      });
      continue;
    }
    const key = item.parent_volume_id ?? "__ungrouped__";
    const volume = volumes.get(key) ?? {
      id: item.parent_volume_id,
      title: item.parent_volume_id ? "" : "未分卷资料",
      position: item.parent_volume_id ? item.position : 2_147_483_647,
      version: 1,
      documents: [],
    };
    const document = { ...navigationDocument(item), novel_id: metadata.id };
    const existingIndex = volume.documents.findIndex((candidate) => candidate.id === item.id);
    if (existingIndex >= 0) volume.documents[existingIndex] = document;
    else volume.documents.push(document);
    volumes.set(key, volume);
  }
  return {
    ...metadata,
    story_ledger_version: page.novel.story_ledger_version,
    updated_at: page.novel.updated_at,
    tree: [...volumes.values()],
  };
}


export async function loadNovelWorkspace(
  novelId: string,
  options: LoadNovelWorkspaceOptions = {},
): Promise<NovelRecord> {
  const [metadata, firstPage] = await Promise.all([
    getNovelMetadata(novelId, options.signal),
    getWorkspaceManifestPage(novelId, null, options.signal),
  ]);
  let novel = appendManifestPage(metadata, null, firstPage);
  let pageNumber = 1;
  options.onPage?.(novel, firstPage, pageNumber);
  let cursor = firstPage.next_cursor;
  while (cursor) {
    const page = await getWorkspaceManifestPage(novelId, cursor, options.signal);
    novel = appendManifestPage(metadata, novel, page);
    pageNumber += 1;
    options.onPage?.(novel, page, pageNumber);
    cursor = page.next_cursor;
  }
  return novel;
}
