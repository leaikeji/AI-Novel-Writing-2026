import { ApiError, apiRequest, NOVEL_RECYCLED_HTTP_EVENT } from "./api";
import { clearPurgedRecoveryDrafts } from "./recovery";
import type {
  NovelLifecycleAction,
  NovelLifecycleActionResult,
  NovelLifecycleNotice,
  RecycleBinNovelPage,
  RecycledNovelSummary,
  PurgeRecycledNovelResult,
} from "./types";


export const NOVEL_LIFECYCLE_CHANNEL = "ai-novel-world-2026:novel-lifecycle";
export const NOVEL_LIFECYCLE_LOCAL_EVENT = "ai-novel-world-2026:novel-lifecycle-local";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;


function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}


export function parseNovelLifecycleNotice(value: unknown): NovelLifecycleNotice | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.novel_id !== "string"
    || !UUID_PATTERN.test(record.novel_id)
    || typeof record.event_id !== "string"
    || !UUID_PATTERN.test(record.event_id)
    || (record.action !== "recycled" && record.action !== "restored")
    || !positiveInteger(record.version)
  ) return null;
  return Object.freeze({
    novel_id: record.novel_id.toLowerCase(),
    event_id: record.event_id.toLowerCase(),
    action: record.action,
    version: record.version,
  });
}


export function lifecycleNoticeFromResult(
  novelId: string,
  result: NovelLifecycleActionResult,
): NovelLifecycleNotice {
  const notice = parseNovelLifecycleNotice({
    novel_id: novelId,
    event_id: result.event_id,
    action: result.action,
    version: result.version,
  });
  if (!notice) throw new Error("小说生命周期响应无效，请刷新后重试。");
  return notice;
}


export function shouldApplyLifecycleNotice(
  notice: NovelLifecycleNotice,
  novelId: string,
  latestVersion: number,
): boolean {
  return notice.novel_id === novelId.toLowerCase() && notice.version > latestVersion;
}


export function publishNovelLifecycleNotice(notice: NovelLifecycleNotice): void {
  const parsed = parseNovelLifecycleNotice(notice);
  if (!parsed) return;
  window.dispatchEvent(new CustomEvent(NOVEL_LIFECYCLE_LOCAL_EVENT, { detail: parsed }));
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(NOVEL_LIFECYCLE_CHANNEL);
  try {
    channel.postMessage(parsed);
  } finally {
    channel.close();
  }
}


export function subscribeNovelLifecycleNotices(
  listener: (notice: NovelLifecycleNotice) => void,
): () => void {
  const seen = new Set<string>();
  const deliver = (value: unknown) => {
    const notice = parseNovelLifecycleNotice(value);
    if (!notice || seen.has(notice.event_id)) return;
    seen.add(notice.event_id);
    listener(notice);
  };
  const local = (event: Event) => deliver((event as CustomEvent).detail);
  window.addEventListener(NOVEL_LIFECYCLE_LOCAL_EVENT, local);
  const channel = typeof BroadcastChannel === "undefined"
    ? null
    : new BroadcastChannel(NOVEL_LIFECYCLE_CHANNEL);
  if (channel) channel.onmessage = (event) => deliver(event.data);
  return () => {
    window.removeEventListener(NOVEL_LIFECYCLE_LOCAL_EVENT, local);
    channel?.close();
  };
}


export function subscribeNovelRecycledHttp(
  listener: (detail: { novelId: string | null; requestPath: string }) => void,
): () => void {
  const receive = (event: Event) => {
    const detail = (event as CustomEvent).detail as Record<string, unknown> | undefined;
    listener({
      novelId: typeof detail?.novelId === "string" ? detail.novelId : null,
      requestPath: typeof detail?.requestPath === "string" ? detail.requestPath : "",
    });
  };
  window.addEventListener(NOVEL_RECYCLED_HTTP_EVENT, receive);
  return () => window.removeEventListener(NOVEL_RECYCLED_HTTP_EVENT, receive);
}


function lifecycleKey(action: NovelLifecycleAction): string {
  const random = globalThis.crypto?.randomUUID?.();
  if (!random) throw new Error("当前浏览器无法建立安全的操作标识，请刷新后重试。");
  return `novel-${action}:${random}`;
}


async function lifecycleAction(
  path: string,
  expectedVersion: number,
  idempotencyKey: string,
  request = apiRequest,
): Promise<NovelLifecycleActionResult> {
  const send = () => request<NovelLifecycleActionResult>(path, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      idempotency_key: idempotencyKey,
    }),
  });
  try {
    return await send();
  } catch (reason) {
    if (reason instanceof ApiError) throw reason;
    // The first response may have been lost after commit. One replay with the
    // same key retrieves the bounded receipt without another transition.
    return send();
  }
}


export function recycleNovel(
  novelId: string,
  expectedVersion: number,
  request = apiRequest,
): Promise<NovelLifecycleActionResult> {
  return lifecycleAction(
    `/novels/${encodeURIComponent(novelId)}/recycle`,
    expectedVersion,
    lifecycleKey("recycled"),
    request,
  );
}


export function restoreNovel(
  novelId: string,
  expectedVersion: number,
  request = apiRequest,
): Promise<NovelLifecycleActionResult> {
  return lifecycleAction(
    `/recycle-bin/novels/${encodeURIComponent(novelId)}/restore`,
    expectedVersion,
    lifecycleKey("restored"),
    request,
  );
}


export function listRecycledNovels(
  cursor?: string | null,
  limit = 20,
  request = apiRequest,
): Promise<RecycleBinNovelPage> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor) query.set("cursor", cursor);
  return request<RecycleBinNovelPage>(`/recycle-bin/novels?${query.toString()}`);
}


export function purgeRecycledNovel(
  novelId: string,
  expectedVersion: number,
  confirmationText: string,
  request = apiRequest,
): Promise<PurgeRecycledNovelResult> {
  return request<PurgeRecycledNovelResult>(
    `/recycle-bin/novels/${encodeURIComponent(novelId)}/purge`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: expectedVersion,
        confirmation_text: confirmationText,
      }),
    },
  );
}


export function formatRecycleStatistic(value: number | null, suffix: string): string {
  return value === null ? "暂不可用" : `${value.toLocaleString("zh-CN")}${suffix}`;
}


export function restoreWarningMessage(codes: readonly string[]): string {
  if (!codes.length) return "作品已恢复，可以从创作中心重新打开。";
  const messages = new Set<string>();
  for (const code of codes) {
    if (code.includes("audio") || code.includes("media")) {
      messages.add("部分朗读音频需要在作品内重新生成后才能播放。");
    } else if (code.includes("embedding") || code.includes("index")) {
      messages.add("语义检索索引需要按现有授权流程重新建立。");
    } else if (code.includes("attachment")) {
      messages.add("部分原始附件缺失，正文已恢复，依赖附件的能力暂不可用。");
    } else {
      messages.add("部分派生能力暂不可用，可在作品内查看具体状态。");
    }
  }
  return `作品已恢复。${[...messages].join("")}`;
}


export interface RecycleBinPageProps {
  readonly onBack: () => void;
  readonly onRestored: (novelId: string, message: string) => void | Promise<void>;
}


export function createRecycleBinPage(React: any, antd: any, icons: any) {
  const h = React.createElement;
  const { Alert, Button, Empty, Input, Modal, Space, Spin, Typography } = antd;
  const { ArrowLeftOutlined, BookOutlined, ReloadOutlined } = icons;
  return function RecycleBinPage(props: RecycleBinPageProps) {
    const [items, setItems] = React.useState([] as RecycledNovelSummary[]);
    const [nextCursor, setNextCursor] = React.useState(null as string | null);
    const [totalCount, setTotalCount] = React.useState(0);
    const [loading, setLoading] = React.useState(true);
    const [loadingMore, setLoadingMore] = React.useState(false);
    const [restoringId, setRestoringId] = React.useState("");
    const [purgingId, setPurgingId] = React.useState("");
    const [error, setError] = React.useState("");

    const load = React.useCallback(async (cursor?: string | null) => {
      cursor ? setLoadingMore(true) : setLoading(true);
      try {
        const page = await listRecycledNovels(cursor);
        setItems((current: RecycledNovelSummary[]) => cursor
          ? [...current, ...page.items.filter((item) => !current.some((known) => known.id === item.id))]
          : page.items);
        setNextCursor(page.next_cursor);
        setTotalCount(page.total_count);
        setError("");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "加载回收站失败");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    }, []);

    React.useEffect(() => { void load(null); }, [load]);

    const confirmRestore = (item: RecycledNovelSummary) => {
      Modal.confirm({
        className: "anw-modal mb-confirm-modal",
        title: `恢复《${item.title}》`,
        content: "恢复后作品会重新出现在创作中心；本地未同步稿仍由作者确认后恢复。",
        okText: "确认恢复",
        cancelText: "取消",
        async onOk() {
          setRestoringId(item.id);
          try {
            const result = await restoreNovel(item.id, item.version);
            const notice = lifecycleNoticeFromResult(item.id, result);
            publishNovelLifecycleNotice(notice);
            await props.onRestored(item.id, restoreWarningMessage(result.warning_codes));
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : "恢复作品失败");
            throw reason;
          } finally {
            setRestoringId("");
          }
        },
      });
    };

    const confirmPurge = (item: RecycledNovelSummary) => {
      let confirmationText = "";
      let dialog: any;
      const purgeContent = (failure = "") => h(
        Space,
        { direction: "vertical", size: 12, style: { width: "100%" } },
        h(Typography.Text, { type: "danger" }, "正文、历史版本、人物、索引和朗读媒体将被永久销毁。此操作不可恢复。"),
        h(Typography.Text, null, "作品已经经过移入回收站这一步；逐字确认后将立即执行单书永久删除。"),
        failure ? h(Alert, { type: "error", showIcon: true, message: failure }) : null,
        h("label", { htmlFor: `purge-confirm-${item.id}` }, "请逐字输入“确认删除”"),
        h(Input, {
          id: `purge-confirm-${item.id}`,
          autoComplete: "off",
          placeholder: "确认删除",
          defaultValue: confirmationText,
          onChange: updateConfirmation,
        }),
      );
      const updateConfirmation = (event: { target?: { value?: unknown } }) => {
        confirmationText = typeof event.target?.value === "string" ? event.target.value : "";
        dialog?.update({ okButtonProps: { danger: true, disabled: confirmationText !== "确认删除" } });
      };
      dialog = Modal.confirm({
        className: "anw-modal mb-confirm-modal mb-purge-modal",
        title: `彻底删除《${item.title}》`,
        content: purgeContent(),
        okText: "彻底删除",
        cancelText: "取消",
        okButtonProps: { danger: true, disabled: true },
        async onOk() {
          if (confirmationText !== "确认删除") return Promise.reject(new Error("请输入“确认删除”"));
          setPurgingId(item.id);
          let result: PurgeRecycledNovelResult;
          try {
            result = await purgeRecycledNovel(item.id, item.version, confirmationText);
          } catch (reason) {
            const message = reason instanceof Error ? reason.message : "彻底删除失败";
            setError(message);
            dialog?.update({
              content: purgeContent(message),
              okButtonProps: { danger: true, disabled: confirmationText !== "确认删除" },
            });
            setPurgingId("");
            throw reason;
          }
          let cleared = 0;
          let localCleanupFailed = false;
          try {
            cleared = await clearPurgedRecoveryDrafts(result.deleted_document_ids);
          } catch {
            localCleanupFailed = true;
          }
          setItems((current: RecycledNovelSummary[]) => current.filter((entry) => entry.id !== item.id));
          setTotalCount((current: number) => Math.max(0, current - 1));
          setPurgingId("");
          Modal.success({
            title: "作品已彻底删除",
            content: localCleanupFailed
              ? "服务端内容已删除，但本浏览器恢复稿清理失败；请清除该站点的本地数据。"
              : result.media_cleanup_pending
                ? `数据库内容已删除，本浏览器清理 ${cleared} 条恢复稿；媒体清理仍在受控重试。`
                : `数据库与媒体已删除，本浏览器清理 ${cleared} 条恢复稿。`,
          });
        },
      });
    };

    return h(
      "main",
      { className: "anw-app mb-center-page mb-recycle-page" },
      h(
        "div",
        { className: "mb-center-inner" },
        h(
          "header",
          { className: "mb-recycle-header" },
          h(Button, { icon: h(ArrowLeftOutlined), onClick: props.onBack }, "返回创作中心"),
          h("div", null, h("h1", null, "回收站"), h("p", null, `共 ${totalCount} 本作品`)),
          h(Button, { icon: h(ReloadOutlined), onClick: () => void load(null), disabled: loading }, "刷新"),
        ),
        h(Alert, {
          type: "info",
          showIcon: true,
          message: "作品不会自动清理；单本彻底删除需要在回收站内逐字输入“确认删除”，完成后不可恢复。",
        }),
        error ? h(Alert, {
          type: "error",
          showIcon: true,
          closable: true,
          message: error,
          onClose: () => setError(""),
        }) : null,
        loading
          ? h("div", { className: "mb-center-loading" }, h(Spin), "正在载入回收站…")
          : items.length
            ? h(
                "section",
                { className: "mb-recycle-list", "aria-label": "回收站作品" },
                ...items.map((item: RecycledNovelSummary) => h(
                  "article",
                  { key: item.id, className: "mb-recycle-card" },
                  h("div", { className: "mb-recycle-cover", "aria-hidden": "true" }, h(BookOutlined)),
                  h(
                    "div",
                    { className: "mb-recycle-meta" },
                    h("h2", null, item.title),
                    h("p", null, `移入时间：${new Date(item.recycled_at).toLocaleString("zh-CN")}`),
                    h(
                      "ul",
                      null,
                      h("li", null, formatRecycleStatistic(item.chapter_count, " 章")),
                      h("li", null, formatRecycleStatistic(item.visible_character_count, " 字")),
                      h("li", null, formatRecycleStatistic(item.media_bytes, " 字节媒体")),
                    ),
                  ),
                  h(
                    "div",
                    { className: "mb-recycle-actions" },
                    h(Button, {
                      className: "mb-recycle-restore",
                      loading: restoringId === item.id,
                      disabled: Boolean(restoringId || purgingId),
                      onClick: () => confirmRestore(item),
                    }, "恢复"),
                    h(Button, {
                      danger: true,
                      loading: purgingId === item.id,
                      disabled: Boolean(restoringId || purgingId),
                      onClick: () => confirmPurge(item),
                    }, "彻底删除"),
                  ),
                )),
                nextCursor ? h(Button, {
                  className: "mb-recycle-more",
                  loading: loadingMore,
                  onClick: () => void load(nextCursor),
                }, "加载更多") : null,
              )
            : h(Empty, { description: "回收站为空" }),
      ),
    );
  };
}
