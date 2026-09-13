import { describe, expect, it } from "vitest";
import type { LibraryAssetPage, LibraryAssetSummary, LibraryQueryFilters } from "./contracts";
import { buildLibraryQuery, createLibraryRequestGate, mergeLibraryPage } from "./library-query";

const filters: LibraryQueryFilters = {
  category: "vocabulary", query: "  潮声%_  ", scope: "novel", enabled: "disabled",
  includeArchived: true,
};
function item(id: string): LibraryAssetSummary {
  return {
    id, asset_type: "vocabulary", title: id, version: 1, current_version_id: `${id}-v1`,
    archived: false, scope_kind: "library", tags: [], binding_count: 0,
    updated_at: "2026-09-13T08:00:00Z", detail_loaded: false,
  };
}
function page(patch: Partial<LibraryAssetPage> = {}): LibraryAssetPage {
  return { items: [item("a"), item("b")], offset: 0, limit: 2, total: 5,
    has_more: true, next_offset: 2, ...patch };
}

describe("private library server query and request generations", () => {
  it("keeps the full query key when loading later pages and requests summaries", () => {
    const first = new URLSearchParams(buildLibraryQuery(filters, "novel-a"));
    const later = new URLSearchParams(buildLibraryQuery(filters, "novel-a", 100));
    expect(first.get("query")).toBe("潮声%_");
    expect(first.get("projection")).toBe("summary");
    expect(first.get("scope_filter")).toBe("novel");
    expect(first.get("enabled_filter")).toBe("disabled");
    expect(first.get("include_archived")).toBe("true");
    later.set("offset", "0");
    expect(later.toString()).toBe(first.toString());
  });
  it("does not fabricate a novel context for enabled filters", () => {
    expect(() => buildLibraryQuery(filters, undefined)).toThrow("先选择作品");
    const query = new URLSearchParams(buildLibraryQuery({ ...filters, scope: "all", enabled: "all" }, null));
    expect(query.has("novel_id")).toBe(false);
    expect(() => buildLibraryQuery(filters, "a", -1)).toThrow();
  });
  it("rejects late results after book, filter, refresh or selection changes", () => {
    const gate = createLibraryRequestGate();
    const oldBook = gate.begin(buildLibraryQuery(filters, "old"));
    const newBook = gate.begin(buildLibraryQuery(filters, "new"));
    expect(gate.isCurrent(oldBook)).toBe(false);
    expect(gate.isCurrent(newBook)).toBe(true);
    const changedFilter = gate.begin(buildLibraryQuery({ ...filters, query: "铁锈" }, "new"));
    expect(gate.isCurrent(newBook)).toBe(false);
    gate.invalidate();
    expect(gate.isCurrent(changedFilter)).toBe(false);
  });
  it("uses server next offset, not deduplicated array length", () => {
    const first = mergeLibraryPage([], page(), false);
    const second = mergeLibraryPage(first.items, page({
      items: [item("b"), item("c")], offset: 2, next_offset: 4,
    }), true);
    expect(second.items.map((asset) => asset.id)).toEqual(["a", "b", "c"]);
    expect(second.nextOffset).toBe(4);
    expect(second.total).toBe(5);
    const last = mergeLibraryPage(second.items, page({
      items: [item("d")], offset: 4, has_more: false, next_offset: null,
    }), true);
    expect(last.hasMore).toBe(false);
  });
  it("resets old pages on mutation refresh and preserves previous data on a bad response", () => {
    const previous = [item("old")];
    expect(mergeLibraryPage(previous, page(), false).items.map((asset) => asset.id)).toEqual(["a", "b"]);
    expect(() => mergeLibraryPage(previous, page({ next_offset: 0 }), true)).toThrow("分页响应无效");
    expect(previous.map((asset) => asset.id)).toEqual(["old"]);
  });
});
