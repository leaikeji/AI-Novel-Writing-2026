import { apiRequest } from "../api";
import type {
  IntelligenceBatchRevertCommandV1,
  IntelligenceBatchRevertResultV1,
  StoryFactCorrectionCommandV1,
  StoryFactCorrectionResultV1,
  StoryLedgerBatchImpactPreview,
  StoryLedgerFactDetail,
  StoryLedgerFactImpactPreview,
  StoryLedgerFactPage,
  StoryLedgerFilters,
  StoryLedgerPageQuery,
  StoryLedgerReadScope,
  StoryLedgerSourceExcerpt,
  StoryLedgerSummary,
} from "./contracts";

function ledgerQuery(
  scope: StoryLedgerReadScope,
  filters: StoryLedgerFilters = {},
): URLSearchParams {
  const query = new URLSearchParams();
  if (scope.timelineId) query.set("timeline_id", scope.timelineId);
  if (scope.narrativeCutoff !== null && scope.narrativeCutoff !== undefined) {
    query.set("narrative_cutoff", String(scope.narrativeCutoff));
  }
  if (scope.snapshotToken) query.set("snapshot_token", scope.snapshotToken);
  for (const factType of [...(filters.factTypes ?? [])].sort()) {
    if (factType) query.append("fact_type", factType);
  }
  if (filters.effectiveState) query.set("effective_state", filters.effectiveState);
  if (filters.health) query.set("health", filters.health);
  if (filters.dimension) query.set("dimension", filters.dimension);
  if (filters.sourceDocumentId) query.set("source_document_id", filters.sourceDocumentId);
  if (filters.commitBatchId) query.set("commit_batch_id", filters.commitBatchId);
  if (filters.factTimelineId) query.set("fact_timeline_id", filters.factTimelineId);
  if (filters.entityType) query.set("entity_type", filters.entityType);
  if (filters.entityId) query.set("entity_id", filters.entityId);
  if (filters.reviewOnly) query.set("review_only", "true");
  return query;
}

function withQuery(path: string, query: URLSearchParams): string {
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

function pathId(value: string): string {
  return encodeURIComponent(value);
}

export function loadStoryLedgerSummary(
  scope: StoryLedgerReadScope,
  filters: StoryLedgerFilters = {},
  signal?: AbortSignal,
): Promise<StoryLedgerSummary> {
  return apiRequest<StoryLedgerSummary>(withQuery(
    `/novels/${pathId(scope.novelId)}/story-ledger/summary`,
    ledgerQuery(scope, filters),
  ), { signal });
}

export function loadStoryLedgerFacts(
  scope: StoryLedgerReadScope,
  page: StoryLedgerPageQuery = {},
  signal?: AbortSignal,
): Promise<StoryLedgerFactPage> {
  const query = ledgerQuery(scope, page);
  if (page.cursor) query.set("cursor", page.cursor);
  if (page.limit !== undefined) query.set("limit", String(page.limit));
  return apiRequest<StoryLedgerFactPage>(withQuery(
    `/novels/${pathId(scope.novelId)}/story-ledger/facts`,
    query,
  ), { signal });
}

export function loadStoryLedgerFactDetail(
  scope: StoryLedgerReadScope,
  factId: string,
  signal?: AbortSignal,
): Promise<StoryLedgerFactDetail> {
  return apiRequest<StoryLedgerFactDetail>(withQuery(
    `/novels/${pathId(scope.novelId)}/story-ledger/facts/${pathId(factId)}`,
    ledgerQuery(scope),
  ), { signal });
}

export function loadStoryLedgerFactSource(
  scope: StoryLedgerReadScope,
  factId: string,
  signal?: AbortSignal,
): Promise<StoryLedgerSourceExcerpt> {
  return apiRequest<StoryLedgerSourceExcerpt>(withQuery(
    `/novels/${pathId(scope.novelId)}/story-ledger/facts/${pathId(factId)}/source`,
    ledgerQuery(scope),
  ), { signal });
}

export function loadStoryLedgerFactImpactPreview(
  scope: StoryLedgerReadScope,
  factId: string,
  signal?: AbortSignal,
): Promise<StoryLedgerFactImpactPreview> {
  return apiRequest<StoryLedgerFactImpactPreview>(withQuery(
    `/novels/${pathId(scope.novelId)}/story-ledger/facts/${pathId(factId)}/impact-preview`,
    ledgerQuery(scope),
  ), { signal });
}

export function loadStoryLedgerBatchImpactPreview(
  scope: StoryLedgerReadScope,
  batchId: string,
  signal?: AbortSignal,
): Promise<StoryLedgerBatchImpactPreview> {
  return apiRequest<StoryLedgerBatchImpactPreview>(withQuery(
    `/novels/${pathId(scope.novelId)}/story-ledger/batches/${pathId(batchId)}/impact-preview`,
    ledgerQuery(scope),
  ), { signal });
}

export function correctStoryLedgerFact(
  novelId: string,
  factId: string,
  command: StoryFactCorrectionCommandV1,
  signal?: AbortSignal,
): Promise<StoryFactCorrectionResultV1> {
  return apiRequest<StoryFactCorrectionResultV1>(
    `/novels/${pathId(novelId)}/story-ledger/facts/${pathId(factId)}/corrections`,
    { method: "POST", body: JSON.stringify(command), signal },
  );
}

export function revertStoryLedgerBatch(
  novelId: string,
  batchId: string,
  command: IntelligenceBatchRevertCommandV1,
  signal?: AbortSignal,
): Promise<IntelligenceBatchRevertResultV1> {
  return apiRequest<IntelligenceBatchRevertResultV1>(
    `/novels/${pathId(novelId)}/story-ledger/batches/${pathId(batchId)}/revert`,
    { method: "POST", body: JSON.stringify(command), signal },
  );
}
