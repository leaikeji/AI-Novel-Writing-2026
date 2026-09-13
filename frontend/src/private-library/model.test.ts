import { describe, expect, it } from "vitest";

import {
  PRIVATE_LIBRARY_CATEGORIES,
  filterPrivateLibraryAssets,
  splitTags,
  type PrivateLibraryAssetView,
} from "./model";


function asset(
  id: string,
  patch: Partial<PrivateLibraryAssetView> = {},
): PrivateLibraryAssetView {
  return {
    id,
    asset_type: "vocabulary",
    title: id,
    version: 1,
    current_version_id: `${id}-v1`,
    archived: false,
    scope_kind: "library",
    tags: [],
    binding_count: 0,
    updated_at: "2026-09-13T08:00:00Z",
    enabled: true,
    ...patch,
  };
}


describe("private library view model", () => {
  it("keeps the four author-facing categories in the planned order", () => {
    expect(PRIVATE_LIBRARY_CATEGORIES).toEqual([
      "vocabulary",
      "writing_style",
      "plot",
      "idea",
    ]);
  });

  it("searches pack titles, tags, entries and filters scope plus enabled state", () => {
    const assets = [
      asset("engineering", {
        title: "末日工程用词",
        scope_kind: "novel",
        scope_novel_id: "novel-a",
        tags: ["工程"],
        lexicon: {
          schema_version: "lexicon-pack/1",
          renderer_version: "lexicon-renderer/1",
          entries: [{
            entry_id: "entry-1",
            term: "排水坡度",
            action: "recommend",
            state: "active",
            match_mode: "phrase",
            case_sensitive: false,
            variants: [],
            categories: ["动作"],
            genres: [],
            eras: [],
            positions: ["body"],
            note: "用于工事描写",
            example: "",
            counterexample: "",
            replacement_hint: "",
            source_refs: [],
          }],
        },
      }),
      asset("disabled", { title: "旧词包", enabled: false }),
      asset("idea", { asset_type: "idea", title: "地铁灵感" }),
    ];
    expect(filterPrivateLibraryAssets(assets, {
      category: "vocabulary",
      query: "排水坡度",
      scope: "novel",
      enabled: "enabled",
    }).map((item) => item.id)).toEqual(["engineering"]);
    expect(filterPrivateLibraryAssets(assets, {
      category: "vocabulary",
      query: "旧",
      scope: "all",
      enabled: "disabled",
    }).map((item) => item.id)).toEqual(["disabled"]);
  });

  it("normalizes comma-separated tags without silently keeping duplicates", () => {
    expect(splitTags("动作, 环境，动作，  工程  ")).toEqual(["动作", "环境", "工程"]);
  });
});
