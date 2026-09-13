import type {
  LexiconAction,
  LexiconEntry,
  LexiconPack,
  LibraryAssetSummary,
  LibraryQueryFilters,
  PrivateLibraryCategory,
} from "./contracts";


export const PRIVATE_LIBRARY_CATEGORIES = [
  "vocabulary",
  "writing_style",
  "plot",
  "idea",
] as const satisfies readonly PrivateLibraryCategory[];


export const PRIVATE_LIBRARY_CATEGORY_META: Readonly<Record<
  PrivateLibraryCategory,
  { readonly label: string; readonly singular: string; readonly empty: string }
>> = Object.freeze({
  vocabulary: {
    label: "用词库",
    singular: "词包",
    empty: "还没有词包，可先收藏一个常用词或建立词包。",
  },
  writing_style: {
    label: "文风库",
    singular: "文风",
    empty: "还没有文风资料，可保存自己的写作原则。",
  },
  plot: {
    label: "机制库",
    singular: "机制",
    empty: "还没有叙事机制，可保存可复用的情节结构。",
  },
  idea: {
    label: "灵感库",
    singular: "灵感",
    empty: "还没有灵感资料，可先记录一个想法。",
  },
});


export const LEXICON_ACTION_LABEL: Readonly<Record<LexiconAction, string>> = {
  recommend: "推荐",
  watch: "慎用",
  forbid: "禁用",
};


export type LibraryScopeFilter = "all" | "library" | "novel";
export type LibraryEnabledFilter = "all" | "enabled" | "disabled";


export interface PrivateLibraryAssetView extends LibraryAssetSummary {
  readonly enabled: boolean;
  readonly summary?: string;
  readonly lexicon?: LexiconPack;
}


export type PrivateLibraryFilters = LibraryQueryFilters;


function searchableText(asset: PrivateLibraryAssetView): string {
  const entries = asset.lexicon?.entries ?? [];
  return [
    asset.title,
    asset.summary ?? "",
    ...asset.tags,
    ...entries.flatMap((entry) => [
      entry.term,
      entry.note,
      entry.replacement_hint,
      ...entry.variants,
      ...entry.categories,
    ]),
  ].join("\n").toLocaleLowerCase("zh-CN");
}


export function filterPrivateLibraryAssets(
  assets: readonly PrivateLibraryAssetView[],
  filters: PrivateLibraryFilters,
): PrivateLibraryAssetView[] {
  const query = filters.query.trim().toLocaleLowerCase("zh-CN");
  return assets.filter((asset) => (
    asset.asset_type === filters.category
    && (filters.scope === "all" || asset.scope_kind === filters.scope)
    && (
      filters.enabled === "all"
      || asset.enabled === (filters.enabled === "enabled")
    )
    && (!query || searchableText(asset).includes(query))
  ));
}


export interface PrivateLibraryAssetDraft {
  readonly assetId?: string;
  readonly title: string;
  readonly assetType: PrivateLibraryCategory;
  readonly scopeKind: "library" | "novel";
  readonly scopeNovelId?: string;
  readonly enabled: boolean;
  readonly tags: readonly string[];
  readonly summary: string;
}


export interface LexiconEntryDraft {
  readonly entryId?: string;
  readonly term: string;
  readonly action: LexiconAction;
  readonly state: "active" | "inactive";
  readonly matchMode: "phrase" | "ascii_word";
  readonly categories: readonly string[];
  readonly note: string;
  readonly replacementHint: string;
}


export function assetDraftFromView(asset: PrivateLibraryAssetView): PrivateLibraryAssetDraft {
  return {
    assetId: asset.id,
    title: asset.title,
    assetType: asset.asset_type,
    scopeKind: asset.scope_kind,
    scopeNovelId: asset.scope_novel_id,
    enabled: asset.enabled,
    tags: asset.tags,
    summary: asset.summary ?? "",
  };
}


export function newAssetDraft(
  category: PrivateLibraryCategory,
  novelId?: string,
): PrivateLibraryAssetDraft {
  return {
    title: "",
    assetType: category,
    scopeKind: novelId ? "novel" : "library",
    scopeNovelId: novelId,
    enabled: true,
    tags: [],
    summary: "",
  };
}


export function entryDraftFromEntry(entry: LexiconEntry): LexiconEntryDraft {
  return {
    entryId: entry.entry_id,
    term: entry.term,
    action: entry.action,
    state: entry.state,
    matchMode: entry.match_mode,
    categories: entry.categories,
    note: entry.note,
    replacementHint: entry.replacement_hint,
  };
}


export function newEntryDraft(): LexiconEntryDraft {
  return {
    term: "",
    action: "recommend",
    state: "active",
    matchMode: "phrase",
    categories: [],
    note: "",
    replacementHint: "",
  };
}


export function splitTags(value: string): string[] {
  return [...new Set(value.split(/[，,]/u).map((item) => item.trim()).filter(Boolean))];
}
