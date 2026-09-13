import type { LibraryAssetPage, LibraryAssetSummary, LibraryQueryFilters } from "./contracts";

export const LIBRARY_PAGE_LIMIT = 50;

/** The entire server filter is retained for every page; no loaded-only search. */
export function buildLibraryQuery(
  filters: LibraryQueryFilters,
  novelId: string | null | undefined,
  offset = 0,
): string {
  if (!Number.isSafeInteger(offset) || offset < 0) throw new Error("无效的资料分页位置");
  if (!novelId && (filters.scope === "novel" || filters.enabled !== "all")) {
    throw new Error("请先选择作品再按本书范围或启用状态筛选");
  }
  const params = new URLSearchParams({
    asset_type: filters.category,
    query: filters.query.trim(),
    scope_filter: filters.scope,
    enabled_filter: filters.enabled,
    include_archived: String(filters.includeArchived ?? false),
    projection: "summary",
    offset: String(offset),
    limit: String(LIBRARY_PAGE_LIMIT),
  });
  if (novelId) params.set("novel_id", novelId);
  return params.toString();
}

export interface LibraryRequestTicket {
  readonly generation: number;
  readonly queryKey: string;
  readonly offset: number;
}

/** Each stream (list, details, history) gets its own gate. */
export function createLibraryRequestGate() {
  let generation = 0;
  let active: LibraryRequestTicket | null = null;
  return {
    begin(queryKey: string, offset = 0): LibraryRequestTicket {
      active = { generation: ++generation, queryKey, offset };
      return active;
    },
    isCurrent(ticket: LibraryRequestTicket): boolean {
      return ticket === active;
    },
    invalidate(): void {
      generation += 1;
      active = null;
    },
  };
}

export function mergeLibraryPage<T extends LibraryAssetSummary>(
  previousItems: readonly T[],
  page: LibraryAssetPage<T>,
  append: boolean,
): { items: T[]; total: number; hasMore: boolean; nextOffset: number | null } {
  if (
    !Number.isSafeInteger(page.offset) || page.offset < 0
    || !Number.isSafeInteger(page.total) || page.total < 0
    || (page.has_more && (
      page.next_offset === null || !Number.isSafeInteger(page.next_offset)
      || page.next_offset <= page.offset
    ))
    || (!page.has_more && page.next_offset !== null)
  ) throw new Error("资料分页响应无效，请刷新后重试");
  const itemsById = new Map((append ? previousItems : []).map((item) => [item.id, item]));
  for (const item of page.items) itemsById.set(item.id, item);
  return {
    items: [...itemsById.values()],
    total: page.total,
    hasMore: page.has_more,
    // A duplicate caused by a concurrent edit does not change the server offset.
    nextOffset: page.next_offset,
  };
}
