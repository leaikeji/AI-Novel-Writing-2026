import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  appendManifestPage,
  getWorkspaceManifestPage,
  loadNovelWorkspace,
} from "./api";
import type { NovelMetadataRecord, WorkspaceManifestPage } from "../types";


const metadata: NovelMetadataRecord = {
  id: "novel-1",
  title: "长篇",
  author_name: "",
  description: "",
  writing_type: "long",
  audience: "",
  genre: "",
  subgenre: "",
  idea: "",
  template_key: null,
  template_name: "",
  template_data: {},
  cover_mode: "system",
  cover_image_data: "",
  cover_asset_id: null,
  outline_target_chapters: 2500,
  highlight: "",
  background: "",
  main_plot: "",
  story_ledger_version: 1,
  visible_character_count: 5_000_000,
  version: 1,
  created_at: null,
  updated_at: null,
};


const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();


function page(items: WorkspaceManifestPage["items"]): WorkspaceManifestPage {
  return {
    schema_version: "novel-workspace-manifest/1",
    novel: {
      id: metadata.id,
      title: metadata.title,
      description: "",
      story_ledger_version: 1,
      visible_character_count: 5_000_000,
      updated_at: null,
    },
    items,
    next_cursor: null,
    manifest_etag: "etag",
  };
}


describe("workspace manifest navigation", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("window", { QwenPaw: { host: { fetch: fetchMock } } });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("requests a bounded page and forwards abort", async () => {
    const signal = new AbortController().signal;
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => page([]),
    } as Response);
    await getWorkspaceManifestPage("novel 1", "cursor/value", signal);
    expect(fetchMock).toHaveBeenCalledWith(
      "/ai-novel-world-2026/novels/novel%201/workspace-manifest?limit=200&cursor=cursor%2Fvalue",
      expect.objectContaining({ signal }),
    );
  });

  it("builds navigation shells without server-provided bodies", () => {
    const novel = appendManifestPage(metadata, null, page([
      {
        kind: "volume",
        id: "volume-1",
        parent_volume_id: null,
        document_type: null,
        title: "第一卷",
        position: 1000,
        status: null,
        version: 1,
        draft_version: null,
        base_revision_id: null,
        content_hash: null,
        visible_character_count: null,
        updated_at: null,
      },
      {
        kind: "document",
        id: "chapter-1",
        parent_volume_id: "volume-1",
        document_type: "chapter",
        title: "开端",
        position: 1000,
        status: "draft",
        version: 1,
        draft_version: 2,
        base_revision_id: "revision-1",
        content_hash: "hash",
        visible_character_count: 2000,
        updated_at: null,
      },
    ]));
    expect(novel.tree[0].documents[0]).toMatchObject({
      id: "chapter-1",
      content_markdown: "",
      revisions: [],
      visible_character_count: 2000,
    });
  });

  it("streams bounded pages into one navigation tree", async () => {
    const first = page([{
      kind: "volume",
      id: "volume-1",
      parent_volume_id: null,
      document_type: null,
      title: "第一卷",
      position: 1000,
      status: null,
      version: 1,
      draft_version: null,
      base_revision_id: null,
      content_hash: null,
      visible_character_count: null,
      updated_at: null,
    }]);
    first.next_cursor = "next-page";
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify(metadata)))
      .mockResolvedValueOnce(new Response(JSON.stringify(first)))
      .mockResolvedValueOnce(new Response(JSON.stringify(page([{
        kind: "document",
        id: "chapter-1",
        parent_volume_id: "volume-1",
        document_type: "chapter",
        title: "开端",
        position: 1000,
        status: "draft",
        version: 1,
        draft_version: 1,
        base_revision_id: null,
        content_hash: "hash",
        visible_character_count: 2000,
        updated_at: null,
      }]))));
    const observedPageSizes: number[] = [];
    const novel = await loadNovelWorkspace("novel-1", {
      onPage: (current) => observedPageSizes.push(
        current.tree.flatMap((volume) => volume.documents).length,
      ),
    });
    expect(observedPageSizes).toEqual([0, 1]);
    expect(novel.tree[0].documents[0].content_markdown).toBe("");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
