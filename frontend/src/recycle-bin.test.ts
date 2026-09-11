import { describe, expect, it, vi } from "vitest";

import {
  formatRecycleStatistic,
  lifecycleNoticeFromResult,
  listRecycledNovels,
  parseNovelLifecycleNotice,
  purgeRecycledNovel,
  recycleNovel,
  restoreWarningMessage,
} from "./recycle-bin";


const NOVEL_ID = "11111111-1111-4111-8111-111111111111";
const EVENT_ID = "22222222-2222-4222-8222-222222222222";


describe("recycle bin client contract", () => {
  it("parses only bounded lifecycle notices", () => {
    expect(parseNovelLifecycleNotice({
      novel_id: NOVEL_ID,
      event_id: EVENT_ID,
      action: "recycled",
      version: 7,
      content: "must not cross tabs",
    })).toEqual({
      novel_id: NOVEL_ID,
      event_id: EVENT_ID,
      action: "recycled",
      version: 7,
    });
    expect(parseNovelLifecycleNotice({
      novel_id: NOVEL_ID,
      event_id: EVENT_ID,
      action: "purged",
      version: 7,
    })).toBeNull();
  });

  it("retries a lost transport response with the same idempotency key", async () => {
    const response = {
      event_id: EVENT_ID,
      action: "recycled" as const,
      version: 8,
      recycled_at: "2026-09-10T12:00:00+00:00",
      warning_codes: [],
      replayed: true,
    };
    const request = vi.fn()
      .mockRejectedValueOnce(new TypeError("connection lost"))
      .mockResolvedValueOnce(response);
    await expect(recycleNovel(NOVEL_ID, 7, request)).resolves.toEqual(response);
    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls[0][0]).toBe(`/novels/${NOVEL_ID}/recycle`);
    expect(request.mock.calls[0][1].body).toBe(request.mock.calls[1][1].body);
  });

  it("builds stable pagination and capability-oriented warnings", async () => {
    const request = vi.fn().mockResolvedValue({ items: [], next_cursor: null, total_count: 0 });
    await listRecycledNovels("next+/=", 25, request);
    expect(request.mock.calls[0][0]).toBe("/recycle-bin/novels?limit=25&cursor=next%2B%2F%3D");
    expect(formatRecycleStatistic(null, " 字")).toBe("暂不可用");
    expect(restoreWarningMessage(["missing_derived_audio", "retired_embedding_index"]))
      .toContain("朗读音频");
    expect(restoreWarningMessage(["missing_derived_audio", "retired_embedding_index"]))
      .toContain("语义检索索引");
  });

  it("rejects malformed lifecycle responses before broadcast", () => {
    expect(() => lifecycleNoticeFromResult(NOVEL_ID, {
      event_id: "bad",
      action: "restored",
      version: 9,
      recycled_at: null,
      warning_codes: [],
      replayed: false,
    })).toThrow("生命周期响应无效");
  });

  it("sends only the exact version and typed purge phrase", async () => {
    const response = {
      deleted: true as const,
      media_cleanup_pending: false,
      deleted_media_count: 0,
      deleted_document_ids: [EVENT_ID],
    };
    const request = vi.fn().mockResolvedValue(response);
    await expect(purgeRecycledNovel(NOVEL_ID, 9, "确认删除", request)).resolves.toEqual(response);
    expect(request).toHaveBeenCalledWith(`/recycle-bin/novels/${NOVEL_ID}/purge`, {
      method: "POST",
      body: JSON.stringify({ expected_version: 9, confirmation_text: "确认删除" }),
    });
  });
});
