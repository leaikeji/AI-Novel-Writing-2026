import {
  correctStoryLedgerFact,
  loadStoryLedgerBatchImpactPreview,
  loadStoryLedgerFactDetail,
  loadStoryLedgerFactImpactPreview,
  loadStoryLedgerFacts,
  loadStoryLedgerFactSource,
  loadStoryLedgerSummary,
  revertStoryLedgerBatch,
} from "./api";
import type {
  IntelligenceBatchRevertCommandV1,
  IntelligenceBatchRevertResultV1,
  StoryFactCorrectionCommandV1,
  StoryFactCorrectionResultV1,
  StoryLedgerBatchImpactPreview,
  StoryLedgerFactDetail,
  StoryLedgerFactImpactPreview,
  StoryLedgerFactItem,
  StoryLedgerFactPage,
  StoryLedgerFilters,
  StoryLedgerReadScope,
  StoryLedgerSourceExcerpt,
  StoryLedgerSourceReference,
  StoryLedgerSummary,
  StoryLedgerTimelineContext,
} from "./contracts";
import {
  renderStoryLedgerBatchRevertDrawer,
  renderStoryFactCorrectionDrawer,
} from "./correction-drawers";
import { renderStoryLedgerFactDetail } from "./fact-detail";
import { renderStoryLedgerFactList } from "./fact-list";
import {
  describeStoryLedgerFilters,
  normalizeStoryLedgerFilters,
  renderStoryLedgerFilters,
} from "./filters";
import type { StoryLedgerElementNode, StoryLedgerReactRuntime } from "./runtime";
import { renderStoryLedgerSourceViewer } from "./source-viewer";
import {
  StoryLedgerRequestFence,
  isAbortLike,
  prepareStoryLedgerOperationAttempt,
  storyLedgerFilterIdentity,
  type StoryLedgerOperationAttempt,
} from "./state-model";
import { ensureStoryLedgerWorkspaceStyles } from "./styles";

type StateSetter<T> = (next: T | ((current: T) => T)) => void;

export interface StoryLedgerWorkspaceReactRuntime extends StoryLedgerReactRuntime {
  useState<T>(initial: T | (() => T)): [T, StateSetter<T>];
  useRef<T>(initial: T): { current: T };
  useEffect(
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ): void;
  useId?(): string;
}

export interface StoryLedgerWorkspaceApi {
  loadSummary(
    scope: StoryLedgerReadScope,
    filters: StoryLedgerFilters,
    signal?: AbortSignal,
  ): Promise<StoryLedgerSummary>;
  loadFacts(
    scope: StoryLedgerReadScope,
    page: StoryLedgerFilters & { readonly cursor?: string | null; readonly limit?: number },
    signal?: AbortSignal,
  ): Promise<StoryLedgerFactPage>;
  loadDetail(
    scope: StoryLedgerReadScope,
    factId: string,
    signal?: AbortSignal,
  ): Promise<StoryLedgerFactDetail>;
  loadSource(
    scope: StoryLedgerReadScope,
    factId: string,
    signal?: AbortSignal,
  ): Promise<StoryLedgerSourceExcerpt>;
  loadFactImpact(
    scope: StoryLedgerReadScope,
    factId: string,
    signal?: AbortSignal,
  ): Promise<StoryLedgerFactImpactPreview>;
  loadBatchImpact(
    scope: StoryLedgerReadScope,
    batchId: string,
    signal?: AbortSignal,
  ): Promise<StoryLedgerBatchImpactPreview>;
  correctFact(
    novelId: string,
    factId: string,
    command: StoryFactCorrectionCommandV1,
    signal?: AbortSignal,
  ): Promise<StoryFactCorrectionResultV1>;
  revertBatch(
    novelId: string,
    batchId: string,
    command: IntelligenceBatchRevertCommandV1,
    signal?: AbortSignal,
  ): Promise<IntelligenceBatchRevertResultV1>;
}

const DEFAULT_API: StoryLedgerWorkspaceApi = {
  loadSummary: loadStoryLedgerSummary,
  loadFacts: loadStoryLedgerFacts,
  loadDetail: loadStoryLedgerFactDetail,
  loadSource: loadStoryLedgerFactSource,
  loadFactImpact: loadStoryLedgerFactImpactPreview,
  loadBatchImpact: loadStoryLedgerBatchImpactPreview,
  correctFact: correctStoryLedgerFact,
  revertBatch: revertStoryLedgerBatch,
};

export interface StoryLedgerContextSelection {
  readonly factId: string;
  readonly factType: string;
  readonly timelineId: string | null;
  readonly dimension: string | null;
  readonly eventKind: string | null;
  readonly effectiveState: StoryLedgerFactItem["effective_state"];
  readonly health: StoryLedgerFactItem["health"];
  readonly source: StoryLedgerContextSourceMetadata | null;
}

export type StoryLedgerContextSourceMetadata = Readonly<Pick<
  StoryLedgerSourceReference,
  | "source_document_id"
  | "document_title"
  | "document_position"
  | "source_revision_id"
  | "revision_number"
  | "revision_is_current"
  | "binding_state"
  | "commit_batch_id"
  | "evidence_available"
>>;

/** Safe integration state: deliberately excludes fact/source body text and details. */
export interface StoryLedgerWorkspaceContext {
  readonly snapshotToken: string | null;
  readonly timeline: StoryLedgerTimelineContext | null;
  readonly filters: StoryLedgerFilters;
  readonly summary: StoryLedgerSummary | null;
  readonly selectedFactId: string | null;
  readonly selected: StoryLedgerContextSelection | null;
}

export interface StoryLedgerWorkspaceProps {
  readonly novelId: string;
  readonly timelineId?: string | null;
  readonly narrativeCutoff?: number | null;
  readonly snapshotToken?: string | null;
  readonly initialFactId?: string | null;
  readonly initialFilters?: StoryLedgerFilters;
  readonly pageSize?: number;
  readonly timelineOptions?: readonly {
    readonly id: string;
    readonly name: string;
  }[];
  readonly className?: string;
  readonly onTimelineChange?: (timelineId: string) => void;
  readonly onSnapshotChange?: (
    snapshotToken: string,
    storyLedgerVersion: number,
  ) => void;
  readonly onContextChange?: (context: StoryLedgerWorkspaceContext) => void;
}

interface SourceState {
  readonly fact: StoryLedgerFactItem;
  readonly source: StoryLedgerSourceExcerpt | null;
  readonly loading: boolean;
  readonly error: string | null;
}

interface CorrectionState {
  readonly fact: StoryLedgerFactDetail;
  readonly impact: StoryLedgerFactImpactPreview;
  readonly objectText: string;
  readonly reason: string;
  readonly saving: boolean;
  readonly error: string | null;
}

interface BatchState {
  readonly fact: StoryLedgerFactItem;
  readonly impact: StoryLedgerBatchImpactPreview;
  readonly reason: string;
  readonly saving: boolean;
  readonly error: string | null;
}

export function createStoryLedgerWorkspace(
  React: StoryLedgerWorkspaceReactRuntime,
  api: StoryLedgerWorkspaceApi = DEFAULT_API,
): (props: StoryLedgerWorkspaceProps) => StoryLedgerElementNode {
  const h = React.createElement;

  return function StoryLedgerWorkspace(
    props: StoryLedgerWorkspaceProps,
  ): StoryLedgerElementNode {
    const initialFactId = props.initialFactId?.trim() || null;
    const initialFiltersIdentity = storyLedgerFilterIdentity(props.initialFilters ?? {});
    const [filters, setFilters] = React.useState<StoryLedgerFilters>(() => (
      normalizeStoryLedgerFilters(props.initialFilters ?? {})
    ));
    const [summary, setSummary] = React.useState<StoryLedgerSummary | null>(null);
    const [page, setPage] = React.useState<StoryLedgerFactPage | null>(null);
    const [pageLoading, setPageLoading] = React.useState(true);
    const [pageLoadingMore, setPageLoadingMore] = React.useState(false);
    const [pageError, setPageError] = React.useState<string | null>(null);
    const [selectedFactId, setSelectedFactId] = React.useState<string | null>(initialFactId);
    const [detail, setDetail] = React.useState<StoryLedgerFactDetail | null>(null);
    const [detailLoading, setDetailLoading] = React.useState(false);
    const [detailError, setDetailError] = React.useState<string | null>(null);
    const [openMenuFactId, setOpenMenuFactId] = React.useState<string | null>(null);
    const [sourceState, setSourceState] = React.useState<SourceState | null>(null);
    const [correctionState, setCorrectionState] = React.useState<CorrectionState | null>(null);
    const [batchState, setBatchState] = React.useState<BatchState | null>(null);
    const [previewLoading, setPreviewLoading] = React.useState(false);
    const [liveStatus, setLiveStatus] = React.useState("正在读取故事账本…");
    const [refreshGeneration, setRefreshGeneration] = React.useState(0);
    const fenceRef = React.useRef<StoryLedgerRequestFence | null>(null);
    if (!fenceRef.current) fenceRef.current = new StoryLedgerRequestFence();
    const fence = fenceRef.current;
    const requestedSnapshotRef = React.useRef<string | null>(props.snapshotToken ?? null);
    const externalScopeRef = React.useRef("");
    const externalBaseScopeRef = React.useRef("");
    const initialFactIdRef = React.useRef<string | null>(initialFactId);
    const initialFiltersRef = React.useRef(initialFiltersIdentity);
    const selectedFactIdRef = React.useRef<string | null>(null);
    selectedFactIdRef.current = selectedFactId;
    const overlayTriggerRef = React.useRef<HTMLElement | null>(null);
    const detailTriggerRef = React.useRef<HTMLElement | null>(null);
    const correctionAttemptRef = React.useRef<StoryLedgerOperationAttempt | null>(null);
    const batchAttemptRef = React.useRef<StoryLedgerOperationAttempt | null>(null);
    const reactId = React.useId?.().replace(/[^A-Za-z0-9_-]/g, "");
    const idRef = React.useRef(
      `story-ledger-${safeId(props.novelId)}${reactId ? `-${reactId}` : ""}`,
    );
    const idPrefix = idRef.current;
    const filterIdentity = storyLedgerFilterIdentity(filters);
    const externalScopeIdentity = JSON.stringify([
      props.novelId,
      props.timelineId ?? null,
      props.narrativeCutoff ?? null,
      props.snapshotToken ?? null,
    ]);
    const externalBaseScopeIdentity = JSON.stringify([
      props.novelId,
      props.timelineId ?? null,
      props.narrativeCutoff ?? null,
    ]);
    const responseToken = page?.ledger_snapshot_token
      ?? summary?.ledger_snapshot_token
      ?? requestedSnapshotRef.current;
    const readScope = (token: string | null = responseToken): StoryLedgerReadScope => ({
      novelId: props.novelId,
      timelineId: props.timelineId ?? null,
      narrativeCutoff: props.narrativeCutoff ?? null,
      snapshotToken: token,
    });

    React.useEffect(() => {
      ensureStoryLedgerWorkspaceStyles();
      return () => fence.dispose();
    }, []);

    React.useEffect(() => {
      if (initialFiltersRef.current === initialFiltersIdentity) return;
      initialFiltersRef.current = initialFiltersIdentity;
      applyFilterChange(normalizeStoryLedgerFilters(props.initialFilters ?? {}));
    }, [initialFiltersIdentity]);

    React.useEffect(() => {
      if (initialFactIdRef.current === initialFactId) return;
      initialFactIdRef.current = initialFactId;
      if (selectedFactIdRef.current === initialFactId) return;
      fence.invalidate("detail");
      setSelectedFactId(initialFactId);
      setDetail(null);
      setDetailError(null);
      detailTriggerRef.current = null;
      closeTransientPanels(false);
      setLiveStatus(initialFactId
        ? "正在打开深链指定的事实…"
        : "已清除深链指定的事实。");
    }, [initialFactId]);

    React.useEffect(() => {
      const externalScopeChanged = externalScopeRef.current !== externalScopeIdentity;
      if (externalScopeChanged) {
        const incomingSnapshot = props.snapshotToken ?? null;
        const snapshotAlreadyObserved = externalScopeRef.current !== ""
          && externalBaseScopeRef.current === externalBaseScopeIdentity
          && incomingSnapshot !== null
          && requestedSnapshotRef.current === incomingSnapshot;
        externalScopeRef.current = externalScopeIdentity;
        externalBaseScopeRef.current = externalBaseScopeIdentity;
        if (snapshotAlreadyObserved) return;
        requestedSnapshotRef.current = incomingSnapshot;
        setSummary(null);
        setPage(null);
        setSelectedFactId(initialFactId);
        setDetail(null);
        setDetailError(null);
        detailTriggerRef.current = null;
        closeTransientPanels(false);
      }
      const requestToken = requestedSnapshotRef.current;
      const requestIdentity = scopeIdentity(
        props,
        filterIdentity,
        requestToken,
        refreshGeneration,
      );
      fence.setScope(requestIdentity);
      const lease = fence.begin("page", requestIdentity);
      setPageLoading(true);
      setPageLoadingMore(false);
      setPageError(null);
      setLiveStatus("正在读取账本总览和第一页事实…");
      const summaryScope = readScope(requestToken);
      void api.loadSummary(summaryScope, filters, lease.signal)
        .then(async (nextSummary) => {
          if (!lease.isCurrent() || !summaryMatchesRequest(nextSummary, props)) return null;
          const nextPage = await api.loadFacts(
            readScope(nextSummary.ledger_snapshot_token),
            { ...filters, limit: props.pageSize ?? 40 },
            lease.signal,
          );
          return { nextSummary, nextPage };
        })
        .then((result) => {
          if (!result || !lease.isCurrent()) return;
          if (!pageMatchesSummary(result.nextPage, result.nextSummary, props)) {
            throw new Error("账本快照或筛选指纹在首屏读取期间发生变化，请重新加载。");
          }
          requestedSnapshotRef.current = result.nextSummary.ledger_snapshot_token;
          setSummary(result.nextSummary);
          setPage(result.nextPage);
          setPageError(null);
          setLiveStatus(`已加载 ${result.nextPage.items.length} 条事实，共 ${result.nextSummary.total} 条。`);
          props.onSnapshotChange?.(
            result.nextSummary.ledger_snapshot_token,
            result.nextSummary.story_ledger_version,
          );
        })
        .catch((reason: unknown) => {
          if (!lease.isCurrent() || isAbortLike(reason)) return;
          setPageError(errorMessage(reason, "加载故事账本失败，请稍后重试。"));
          setLiveStatus("故事账本加载失败。" );
        })
        .finally(() => {
          if (lease.isCurrent()) setPageLoading(false);
        });
      return () => fence.invalidate("page");
    }, [
      props.novelId,
      props.timelineId,
      props.narrativeCutoff,
      props.snapshotToken,
      filterIdentity,
      refreshGeneration,
    ]);

    React.useEffect(() => {
      if (!selectedFactId || !page?.ledger_snapshot_token) return;
      const token = page.ledger_snapshot_token;
      const identity = `${props.novelId}:${props.timelineId ?? "none"}:${token}:${selectedFactId}`;
      const lease = fence.begin("detail", identity);
      setDetailLoading(true);
      setDetailError(null);
      void api.loadDetail(readScope(token), selectedFactId, lease.signal)
        .then((nextDetail) => {
          if (!lease.isCurrent()
            || selectedFactIdRef.current !== selectedFactId
            || !detailMatchesRequest(nextDetail, props, selectedFactId, token)) return;
          setDetail(nextDetail);
          setLiveStatus("事实详情已更新。" );
        })
        .catch((reason: unknown) => {
          if (!lease.isCurrent() || isAbortLike(reason)) return;
          setDetailError(errorMessage(reason, "加载事实详情失败。"));
          setLiveStatus("事实详情加载失败。" );
        })
        .finally(() => {
          if (lease.isCurrent()) setDetailLoading(false);
        });
      return () => fence.invalidate("detail");
    }, [selectedFactId, page?.ledger_snapshot_token, refreshGeneration]);

    React.useEffect(() => {
      const selected = selectedContext(detail?.item
        ?? page?.items.find((item) => item.id === selectedFactId)
        ?? null);
      props.onContextChange?.({
        snapshotToken: responseToken ?? null,
        timeline: summary?.timeline ?? page?.timeline ?? null,
        filters: normalizeStoryLedgerFilters(filters),
        summary,
        selectedFactId,
        selected,
      });
    }, [
      responseToken,
      summary,
      page,
      detail,
      selectedFactId,
      filterIdentity,
      props.onContextChange,
    ]);

    React.useEffect(() => {
      if (typeof document === "undefined") return;
      const openId = sourceState
        ? `${idPrefix}-source-dialog`
        : correctionState
          ? `${idPrefix}-correction-dialog`
          : batchState
            ? `${idPrefix}-batch-dialog`
            : null;
      if (openId) document.getElementById(openId)?.focus({ preventScroll: true });
    }, [Boolean(sourceState), Boolean(correctionState), Boolean(batchState)]);

    React.useEffect(() => {
      if (!selectedFactId || typeof document === "undefined") return;
      document.getElementById(`${idPrefix}-detail-title`)?.focus({ preventScroll: true });
    }, [selectedFactId]);

    function applyFilterChange(nextFilters: StoryLedgerFilters): void {
      const normalized = normalizeStoryLedgerFilters(nextFilters);
      const nextIdentity = storyLedgerFilterIdentity(normalized);
      fence.setScope(scopeIdentity(
        props,
        nextIdentity,
        requestedSnapshotRef.current,
        refreshGeneration,
      ));
      setFilters(normalized);
      setPage(null);
      setPageError(null);
      setOpenMenuFactId(null);
      closeTransientPanels(false);
      setLiveStatus(`正在应用筛选：${describeStoryLedgerFilters(normalized)}。`);
    }

    function refreshLatest(): void {
      requestedSnapshotRef.current = null;
      fence.setScope(scopeIdentity(
        props,
        filterIdentity,
        null,
        refreshGeneration + 1,
      ));
      setRefreshGeneration((value) => value + 1);
      setLiveStatus("正在刷新到最新账本快照…");
    }

    function selectFact(fact: StoryLedgerFactItem, trigger: HTMLElement): void {
      fence.invalidate("detail");
      detailTriggerRef.current = trigger;
      setSelectedFactId(fact.id);
      setDetail(detail?.item.id === fact.id ? detail : null);
      setDetailError(null);
      setOpenMenuFactId(null);
      setLiveStatus(`已选择 ${fact.subject || "未命名事实"}。`);
    }

    function closeDetail(): void {
      fence.invalidate("detail");
      setSelectedFactId(null);
      setDetail(null);
      setDetailError(null);
      setLiveStatus("已关闭事实详情。" );
      const trigger = detailTriggerRef.current;
      detailTriggerRef.current = null;
      trigger?.focus?.({ preventScroll: true });
    }

    function loadMore(): void {
      const cursor = page?.next_cursor;
      const token = page?.ledger_snapshot_token;
      if (!cursor || !token || pageLoadingMore) return;
      const identity = `${props.novelId}:${props.timelineId ?? "none"}:${filterIdentity}:${token}:${cursor}`;
      const lease = fence.begin("append", identity);
      const expectedFilterHash = page.filter_sha256;
      setPageLoadingMore(true);
      setPageError(null);
      setLiveStatus("正在加载更多事实…");
      void api.loadFacts(
        readScope(token),
        { ...filters, cursor, limit: props.pageSize ?? 40 },
        lease.signal,
      ).then((nextPage) => {
        if (!lease.isCurrent()) return;
        if (!pageMatchesAppend(nextPage, props, token, expectedFilterHash)) {
          setPageError("账本快照或筛选已经变化，未追加过期页面。请刷新后继续。");
          setLiveStatus("未追加过期页面。" );
          return;
        }
        setPage((current) => {
          if (!current
            || current.ledger_snapshot_token !== token
            || current.filter_sha256 !== expectedFilterHash) return current;
          const seen = new Set(current.items.map((item) => item.id));
          const appended = nextPage.items.filter((item) => !seen.has(item.id));
          return { ...nextPage, items: [...current.items, ...appended] };
        });
        setLiveStatus(`已追加 ${nextPage.items.length} 条事实。`);
      }).catch((reason: unknown) => {
        if (!lease.isCurrent() || isAbortLike(reason)) return;
        setPageError(errorMessage(reason, "加载更多事实失败。"));
        setLiveStatus("加载更多事实失败。" );
      }).finally(() => {
        if (lease.isCurrent()) setPageLoadingMore(false);
      });
    }

    function openSource(fact: StoryLedgerFactItem, trigger: HTMLElement): void {
      const token = page?.ledger_snapshot_token;
      if (!token) return;
      overlayTriggerRef.current = trigger;
      fence.invalidate("source");
      const identity = `${props.novelId}:${props.timelineId ?? "none"}:${token}:${fact.id}`;
      const lease = fence.begin("source", identity);
      setSourceState({ fact, source: null, loading: true, error: null });
      setLiveStatus("正在读取有界来源摘录…");
      void api.loadSource(readScope(token), fact.id, lease.signal)
        .then((source) => {
          if (!lease.isCurrent() || !sourceMatchesRequest(source, props, fact.id, token)) return;
          setSourceState({
            fact,
            source,
            loading: false,
            error: source.available
              ? null
              : source.unavailable_reason || "该事实没有可显示的安全来源摘录。",
          });
          setLiveStatus(source.available ? "来源摘录已打开。" : "该事实没有可用来源摘录。" );
        })
        .catch((reason: unknown) => {
          if (!lease.isCurrent() || isAbortLike(reason)) return;
          setSourceState({
            fact,
            source: null,
            loading: false,
            error: errorMessage(reason, "加载来源摘录失败。"),
          });
          setLiveStatus("来源摘录加载失败。" );
        });
    }

    function openCorrection(fact: StoryLedgerFactItem, trigger: HTMLElement): void {
      const token = page?.ledger_snapshot_token;
      if (!token || previewLoading) return;
      overlayTriggerRef.current = trigger;
      if (correctionAttemptRef.current?.targetId !== fact.id) {
        correctionAttemptRef.current = null;
      }
      const identity = `${props.novelId}:${props.timelineId ?? "none"}:${token}:correction:${fact.id}`;
      const lease = fence.begin("impact", identity);
      setPreviewLoading(true);
      setLiveStatus("正在读取修正影响预览…");
      void Promise.all([
        api.loadDetail(readScope(token), fact.id, lease.signal),
        api.loadFactImpact(readScope(token), fact.id, lease.signal),
      ]).then(([factDetail, impact]) => {
        if (!lease.isCurrent()
          || !detailMatchesRequest(factDetail, props, fact.id, token)
          || !factImpactMatchesRequest(impact, props, fact.id, token)) return;
        setCorrectionState({
          fact: factDetail,
          impact,
          objectText: factDetail.object_text,
          reason: "",
          saving: false,
          error: null,
        });
        setLiveStatus("修正影响预览已打开。" );
      }).catch((reason: unknown) => {
        if (!lease.isCurrent() || isAbortLike(reason)) return;
        setLiveStatus(errorMessage(reason, "读取修正影响预览失败。"));
      }).finally(() => {
        if (lease.isCurrent()) setPreviewLoading(false);
      });
    }

    function openBatchPreview(fact: StoryLedgerFactItem, trigger: HTMLElement): void {
      const token = page?.ledger_snapshot_token;
      const batchId = fact.source?.commit_batch_id;
      if (!token || !batchId || previewLoading) return;
      overlayTriggerRef.current = trigger;
      if (batchAttemptRef.current?.targetId !== batchId) batchAttemptRef.current = null;
      const identity = `${props.novelId}:${props.timelineId ?? "none"}:${token}:batch:${batchId}`;
      const lease = fence.begin("impact", identity);
      setPreviewLoading(true);
      setLiveStatus("正在读取同步批次影响预览…");
      void api.loadBatchImpact(readScope(token), batchId, lease.signal)
        .then((impact) => {
          if (!lease.isCurrent() || !batchImpactMatchesRequest(impact, props, batchId, token)) return;
          setBatchState({ fact, impact, reason: "", saving: false, error: null });
          setLiveStatus("同步批次影响预览已打开。" );
        })
        .catch((reason: unknown) => {
          if (!lease.isCurrent() || isAbortLike(reason)) return;
          setLiveStatus(errorMessage(reason, "读取同步批次影响预览失败。"));
        })
        .finally(() => {
          if (lease.isCurrent()) setPreviewLoading(false);
        });
    }

    function submitCorrection(): void {
      const current = correctionState;
      const token = page?.ledger_snapshot_token;
      if (!current || !token || current.saving) return;
      const replacement = { object_text: current.objectText } as const;
      const payload = {
        expected_story_ledger_version: current.fact.story_ledger_version,
        reason: current.reason,
        replacement,
      } as const;
      const attempt = prepareStoryLedgerOperationAttempt(
        correctionAttemptRef.current,
        "correction",
        current.fact.item.id,
        payload,
      );
      correctionAttemptRef.current = attempt;
      const lease = fence.begin(
        "mutation",
        `${props.novelId}:${token}:${current.fact.item.id}:${attempt.payloadIdentity}`,
      );
      setCorrectionState({ ...current, saving: true, error: null });
      setLiveStatus("正在创建替代事实…");
      void api.correctFact(props.novelId, current.fact.item.id, {
        schema_version: "story-fact-correction/1",
        operation_key: attempt.operationKey,
        expected_story_ledger_version: current.fact.story_ledger_version,
        reason: current.reason,
        replacement,
      }, lease.signal).then(() => {
        if (!lease.isCurrent()) return;
        correctionAttemptRef.current = null;
        setCorrectionState(null);
        restoreOverlayFocus();
        setLiveStatus("替代事实已创建，正在刷新账本。" );
        refreshLatest();
      }).catch((reason: unknown) => {
        if (!lease.isCurrent() || isAbortLike(reason)) return;
        setCorrectionState((state) => state ? {
          ...state,
          saving: false,
          error: errorMessage(reason, "修正事实失败；可使用同一内容重试。"),
        } : state);
        setLiveStatus("修正事实失败，草稿已保留。" );
      });
    }

    function submitBatchRevert(): void {
      const current = batchState;
      const token = page?.ledger_snapshot_token;
      if (!current || !token || current.saving) return;
      const payload = {
        expected_story_ledger_version: current.impact.story_ledger_version,
        reason: current.reason || null,
      } as const;
      const attempt = prepareStoryLedgerOperationAttempt(
        batchAttemptRef.current,
        "batch-revert",
        current.impact.batch_id,
        payload,
      );
      batchAttemptRef.current = attempt;
      const lease = fence.begin(
        "mutation",
        `${props.novelId}:${token}:${current.impact.batch_id}:${attempt.payloadIdentity}`,
      );
      setBatchState({ ...current, saving: true, error: null });
      setLiveStatus("正在撤销同步批次…");
      void api.revertBatch(props.novelId, current.impact.batch_id, {
        operation_key: attempt.operationKey,
        expected_story_ledger_version: current.impact.story_ledger_version,
        reason: current.reason || null,
      }, lease.signal).then(() => {
        if (!lease.isCurrent()) return;
        batchAttemptRef.current = null;
        setBatchState(null);
        restoreOverlayFocus();
        setLiveStatus("同步批次已撤销，正在刷新账本。" );
        refreshLatest();
      }).catch((reason: unknown) => {
        if (!lease.isCurrent() || isAbortLike(reason)) return;
        setBatchState((state) => state ? {
          ...state,
          saving: false,
          error: errorMessage(reason, "撤销同步批次失败；可使用同一内容重试。"),
        } : state);
        setLiveStatus("撤销同步批次失败，说明已保留。" );
      });
    }

    function closeSource(): void {
      fence.invalidate("source");
      setSourceState(null);
      setLiveStatus("已关闭来源证据。" );
      restoreOverlayFocus();
    }

    function closeCorrection(): void {
      if (correctionState?.saving) return;
      fence.invalidate("impact");
      correctionAttemptRef.current = null;
      setCorrectionState(null);
      setLiveStatus("已取消事实修正。" );
      restoreOverlayFocus();
    }

    function closeBatch(): void {
      if (batchState?.saving) return;
      fence.invalidate("impact");
      batchAttemptRef.current = null;
      setBatchState(null);
      setLiveStatus("已关闭同步批次预览。" );
      restoreOverlayFocus();
    }

    function closeTransientPanels(restoreFocus: boolean): void {
      fence.invalidateMany(["source", "impact", "mutation"]);
      setSourceState(null);
      setCorrectionState(null);
      setBatchState(null);
      setPreviewLoading(false);
      if (restoreFocus) restoreOverlayFocus();
      else overlayTriggerRef.current = null;
    }

    function restoreOverlayFocus(): void {
      const trigger = overlayTriggerRef.current;
      overlayTriggerRef.current = null;
      trigger?.focus?.({ preventScroll: true });
    }

    const selectedItem = detail?.item
      ?? page?.items.find((item) => item.id === selectedFactId)
      ?? null;
    const timeline = summary?.timeline ?? page?.timeline ?? null;
    const multipleTimelines = timeline?.mode === "multiple";
    const activeCount = summary?.by_effective_state.current ?? 0;
    const historicalCount = summary?.by_effective_state.historical ?? 0;
    const supersededCount = summary?.by_effective_state.superseded ?? 0;
    const invalidCount = summary?.by_effective_state.source_invalid ?? 0;
    const revertedCount = summary?.by_effective_state.batch_reverted ?? 0;
    const issueCount = (summary?.by_health.conflict ?? 0)
      + (summary?.by_health.ambiguous ?? 0);
    const listTitle = filters.reviewOnly ? "核对队列" : "事实列表";

    return h(
      "section",
      {
        className: `anw-story-ledger-workspace${props.className ? ` ${props.className}` : ""}`,
        "aria-label": "全书故事账本",
      },
      h(
        "header",
        { className: "anw-story-ledger-heading" },
        h(
          "div",
          null,
          h("h2", null, "故事账本"),
          h("p", null, "查看全书事实、来源证据与权威状态；修正会创建可审计的替代事实。"),
        ),
        h("button", { type: "button", disabled: pageLoading, onClick: refreshLatest }, "刷新账本"),
      ),
      renderTimelineContext(React, {
        timeline,
        timelineId: props.timelineId ?? null,
        timelineOptions: props.timelineOptions,
        onTimelineChange: props.onTimelineChange,
      }),
      renderSummary(React, {
        summary,
        loading: pageLoading && !summary,
        error: pageError && !summary ? pageError : null,
        activeCount,
        historicalCount,
        supersededCount,
        invalidCount,
        revertedCount,
        issueCount,
        reviewActive: filters.reviewOnly === true,
        onReviewToggle: () => applyFilterChange({ ...filters, reviewOnly: !filters.reviewOnly }),
      }),
      renderStoryLedgerFilters(React, {
        idPrefix: `${idPrefix}-filter`,
        filters,
        multipleTimelines,
        timelineOptions: props.timelineOptions,
        disabled: pageLoading && !page,
        onChange: applyFilterChange,
      }),
      h(
        "div",
        { className: "anw-story-ledger-main" },
        h(
          "section",
          { className: "anw-story-ledger-list-column", "aria-labelledby": `${idPrefix}-list-title` },
          h(
            "div",
            { className: "anw-story-ledger-list-heading" },
            h("h2", { id: `${idPrefix}-list-title` }, listTitle),
            h(
              "p",
              null,
              `${page?.items.length ?? 0}${summary ? ` / ${summary.total}` : ""} 条 · ${
                describeStoryLedgerFilters(filters)
              }`,
            ),
          ),
          previewLoading
            ? h("p", { role: "status" }, "正在读取动作影响预览…")
            : null,
          renderStoryLedgerFactList(React, {
            idPrefix,
            items: page?.items ?? [],
            selectedFactId,
            multipleTimelines,
            loading: pageLoading,
            loadingMore: pageLoadingMore,
            error: pageError,
            nextCursor: page?.next_cursor ?? null,
            openMenuFactId,
            onSelect: selectFact,
            onOpenSource: openSource,
            onCorrect: openCorrection,
            onPreviewBatchRevert: openBatchPreview,
            onMenuOpenChange: setOpenMenuFactId,
            onLoadMore: loadMore,
            onRetry: refreshLatest,
          }),
        ),
        h(
          "div",
          { className: `anw-story-ledger-detail-shell${selectedItem ? " is-open" : ""}` },
          renderStoryLedgerFactDetail(React, {
            idPrefix,
            selectedItem,
            detail,
            loading: detailLoading,
            error: detailError,
            multipleTimelines,
            onRetry: () => {
              if (!selectedFactId) return;
              fence.invalidate("detail");
              setDetail(null);
              setRefreshGeneration((value) => value + 1);
            },
            onClose: closeDetail,
            onOpenSource: openSource,
            onCorrect: openCorrection,
            onPreviewBatchRevert: openBatchPreview,
          }),
        ),
      ),
      h(
        "p",
        {
          className: "anw-story-ledger-live-status",
          role: "status",
          "aria-live": "polite",
          "aria-atomic": true,
        },
        liveStatus,
      ),
      sourceState
        ? h(
            "div",
            { className: "anw-story-ledger-modal-layer", onKeyDown: (event: { readonly key: string; preventDefault(): void }) => {
              if (event.key === "Escape") { event.preventDefault(); closeSource(); }
            } },
            renderStoryLedgerSourceViewer(React, {
              dialogId: `${idPrefix}-source-dialog`,
              titleId: `${idPrefix}-source-title`,
              source: sourceState.source,
              loading: sourceState.loading,
              error: sourceState.error,
              onClose: closeSource,
            }),
          )
        : null,
      correctionState
        ? h(
            "div",
            { className: "anw-story-ledger-modal-layer", onKeyDown: (event: { readonly key: string; preventDefault(): void }) => {
              if (event.key === "Escape" && !correctionState.saving) { event.preventDefault(); closeCorrection(); }
            } },
            renderStoryFactCorrectionDrawer(React, {
              dialogId: `${idPrefix}-correction-dialog`,
              titleId: `${idPrefix}-correction-title`,
              fact: {
                id: correctionState.fact.item.id,
                object_text: correctionState.fact.object_text,
                details: correctionState.fact.details,
              },
              objectText: correctionState.objectText,
              reason: correctionState.reason,
              saving: correctionState.saving,
              error: correctionState.error,
              impact: correctionState.impact,
              impactLoading: false,
              impactError: null,
              onObjectTextChange: (objectText) => setCorrectionState((state) => (
                state ? { ...state, objectText, error: null } : state
              )),
              onReasonChange: (reason) => setCorrectionState((state) => (
                state ? { ...state, reason, error: null } : state
              )),
              onSubmit: submitCorrection,
              onClose: closeCorrection,
            }),
          )
        : null,
      batchState
        ? h(
            "div",
            { className: "anw-story-ledger-modal-layer", onKeyDown: (event: { readonly key: string; preventDefault(): void }) => {
              if (event.key === "Escape" && !batchState.saving) { event.preventDefault(); closeBatch(); }
            } },
            renderStoryLedgerBatchRevertDrawer(React, {
              dialogId: `${idPrefix}-batch-dialog`,
              titleId: `${idPrefix}-batch-title`,
              impact: batchState.impact,
              reason: batchState.reason,
              saving: batchState.saving,
              error: batchState.error,
              onReasonChange: (reason) => setBatchState((state) => (
                state ? { ...state, reason, error: null } : state
              )),
              onSubmit: submitBatchRevert,
              onClose: closeBatch,
            }),
          )
        : null,
    );
  };
}

interface SummaryRenderProps {
  readonly summary: StoryLedgerSummary | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly activeCount: number;
  readonly historicalCount: number;
  readonly supersededCount: number;
  readonly invalidCount: number;
  readonly revertedCount: number;
  readonly issueCount: number;
  readonly reviewActive: boolean;
  readonly onReviewToggle: () => void;
}

function renderSummary(
  React: StoryLedgerReactRuntime,
  props: SummaryRenderProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  return h(
    "section",
    { className: "anw-story-ledger-summary", "aria-labelledby": "story-ledger-summary-title" },
    h(
      "div",
      { className: "anw-story-ledger-summary-header" },
      h(
        "div",
        null,
        h("h2", { id: "story-ledger-summary-title" }, "账本总览"),
        props.summary
          ? h(
              "p",
              { className: "anw-story-ledger-snapshot" },
              `诊断版本 ${props.summary.story_ledger_version} · snapshot ${shortToken(
                props.summary.ledger_snapshot_token,
              )}`,
            )
          : null,
      ),
      h(
        "button",
        {
          type: "button",
          className: `anw-story-ledger-review-button${props.reviewActive ? " is-active" : ""}`,
          "aria-pressed": props.reviewActive,
          disabled: !props.summary,
          onClick: props.onReviewToggle,
        },
        `核对队列（${props.summary?.review_required ?? 0}）`,
      ),
    ),
    props.loading ? h("p", { role: "status" }, "正在读取账本总览…") : null,
    props.error ? h("p", { role: "alert" }, props.error) : null,
    props.summary
      ? h(
          "ul",
          { className: "anw-story-ledger-summary-grid", "aria-label": "账本数量概览" },
          summaryMetric(React, "当前有效", props.activeCount),
          summaryMetric(React, "历史变化", props.historicalCount),
          summaryMetric(React, "已被替代", props.supersededCount),
          summaryMetric(React, "冲突／不确定", props.issueCount),
          summaryMetric(React, "来源失效", props.invalidCount),
          summaryMetric(React, "已撤销同步", props.revertedCount),
          summaryMetric(React, "全部事实", props.summary.total),
          summaryMetric(React, "待核对", props.summary.review_required),
        )
      : null,
  );
}

function summaryMetric(
  React: StoryLedgerReactRuntime,
  label: string,
  value: number,
): StoryLedgerElementNode {
  const h = React.createElement;
  return h("li", null, h("span", null, label), h("strong", null, value));
}

interface TimelineRenderProps {
  readonly timeline: StoryLedgerTimelineContext | null;
  readonly timelineId: string | null;
  readonly timelineOptions?: readonly { readonly id: string; readonly name: string }[];
  readonly onTimelineChange?: (timelineId: string) => void;
}

function renderTimelineContext(
  React: StoryLedgerReactRuntime,
  props: TimelineRenderProps,
): StoryLedgerElementNode {
  const h = React.createElement;
  if (!props.timeline) {
    return h("div", { className: "anw-story-ledger-timeline-context", role: "status" }, "正在确认账本时间线…");
  }
  if (props.timeline.mode !== "multiple") {
    return h(
      "div",
      { className: "anw-story-ledger-timeline-context" },
      h("strong", null, "当前时间线："),
      props.timeline.timeline_name || "主线（单时间线）",
    );
  }
  if (props.timelineOptions?.length && props.onTimelineChange) {
    return h(
      "label",
      { className: "anw-story-ledger-timeline-context" },
      h("strong", null, "当前时间线"),
      h(
        "select",
        {
          value: props.timelineId ?? props.timeline.timeline_id ?? "",
          onChange: (event: { readonly target: { readonly value: string } }) => {
            if (event.target.value) props.onTimelineChange?.(event.target.value);
          },
        },
        ...props.timelineOptions.map((timeline) => h(
          "option",
          { key: timeline.id, value: timeline.id },
          timeline.name,
        )),
      ),
    );
  }
  return h(
    "div",
    { className: "anw-story-ledger-timeline-context" },
    h("strong", null, "当前时间线："),
    `${props.timeline.timeline_name || "未命名时间线"}（${
      props.timeline.timeline_id || "未绑定 ID"
    }）`,
  );
}

function selectedContext(item: StoryLedgerFactItem | null): StoryLedgerContextSelection | null {
  if (!item) return null;
  const source = item.source ? {
    source_document_id: item.source.source_document_id,
    document_title: item.source.document_title,
    document_position: item.source.document_position,
    source_revision_id: item.source.source_revision_id,
    revision_number: item.source.revision_number,
    revision_is_current: item.source.revision_is_current,
    binding_state: item.source.binding_state,
    commit_batch_id: item.source.commit_batch_id,
    evidence_available: item.source.evidence_available,
  } : null;
  return {
    factId: item.id,
    factType: item.fact_type,
    timelineId: item.timeline_id,
    dimension: item.dimension,
    eventKind: item.event_kind,
    effectiveState: item.effective_state,
    health: item.health,
    source,
  };
}

function scopeIdentity(
  props: StoryLedgerWorkspaceProps,
  filterIdentity: string,
  snapshotToken: string | null,
  generation: number,
): string {
  return JSON.stringify([
    props.novelId,
    props.timelineId ?? null,
    props.narrativeCutoff ?? null,
    snapshotToken,
    filterIdentity,
    generation,
  ]);
}

function summaryMatchesRequest(
  summary: StoryLedgerSummary,
  props: StoryLedgerWorkspaceProps,
): boolean {
  return summary.novel_id === props.novelId
    && timelineMatches(summary.timeline, props.timelineId ?? null);
}

function pageMatchesSummary(
  page: StoryLedgerFactPage,
  summary: StoryLedgerSummary,
  props: StoryLedgerWorkspaceProps,
): boolean {
  return page.novel_id === props.novelId
    && page.ledger_snapshot_token === summary.ledger_snapshot_token
    && page.story_ledger_version === summary.story_ledger_version
    && page.filter_sha256 === summary.filter_sha256
    && timelineMatches(page.timeline, props.timelineId ?? null);
}

function pageMatchesAppend(
  page: StoryLedgerFactPage,
  props: StoryLedgerWorkspaceProps,
  snapshotToken: string,
  filterHash: string,
): boolean {
  return page.novel_id === props.novelId
    && page.ledger_snapshot_token === snapshotToken
    && page.filter_sha256 === filterHash
    && timelineMatches(page.timeline, props.timelineId ?? null);
}

function detailMatchesRequest(
  detail: StoryLedgerFactDetail,
  props: StoryLedgerWorkspaceProps,
  factId: string,
  snapshotToken: string,
): boolean {
  return detail.novel_id === props.novelId
    && detail.item.id === factId
    && detail.ledger_snapshot_token === snapshotToken
    && timelineMatches(detail.timeline, props.timelineId ?? null);
}

function sourceMatchesRequest(
  source: StoryLedgerSourceExcerpt,
  props: StoryLedgerWorkspaceProps,
  factId: string,
  snapshotToken: string,
): boolean {
  return source.novel_id === props.novelId
    && source.fact_id === factId
    && source.ledger_snapshot_token === snapshotToken
    && timelineMatches(source.timeline, props.timelineId ?? null);
}

function factImpactMatchesRequest(
  impact: StoryLedgerFactImpactPreview,
  props: StoryLedgerWorkspaceProps,
  factId: string,
  snapshotToken: string,
): boolean {
  return impact.novel_id === props.novelId
    && impact.fact_id === factId
    && impact.preview_snapshot_token === snapshotToken
    && timelineMatches(impact.timeline, props.timelineId ?? null);
}

function batchImpactMatchesRequest(
  impact: StoryLedgerBatchImpactPreview,
  props: StoryLedgerWorkspaceProps,
  batchId: string,
  snapshotToken: string,
): boolean {
  return impact.novel_id === props.novelId
    && impact.batch_id === batchId
    && impact.preview_snapshot_token === snapshotToken
    && timelineMatches(impact.timeline, props.timelineId ?? null);
}

function timelineMatches(
  timeline: StoryLedgerTimelineContext,
  requestedTimelineId: string | null,
): boolean {
  return !requestedTimelineId || timeline.timeline_id === requestedTimelineId;
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message.trim() ? reason.message : fallback;
}

function shortToken(token: string): string {
  return token.length <= 16 ? token : `${token.slice(0, 8)}…${token.slice(-6)}`;
}

function safeId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "-");
}
