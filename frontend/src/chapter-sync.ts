import type { DocumentRecord, IntelligenceProposalRecord } from "./types";


export function resolveSyncProgressDocument(
  current: DocumentRecord,
  preparedOverride?: unknown,
): DocumentRecord {
  if (
    typeof preparedOverride === "object"
    && preparedOverride !== null
    && typeof (preparedOverride as Partial<DocumentRecord>).id === "string"
    && typeof (preparedOverride as Partial<DocumentRecord>).draft_version === "number"
  ) {
    return preparedOverride as DocumentRecord;
  }
  return current;
}


export function reusableSyncProgressRevisionId(
  document: DocumentRecord,
): string | null {
  if (!document.base_revision_id || !document.content_hash) return null;
  const baseRevision = (document.revisions || []).find(
    (revision) => revision.id === document.base_revision_id,
  );
  if (!baseRevision || baseRevision.content_hash !== document.content_hash) return null;
  return baseRevision.id;
}


const REUSABLE_SYNC_PROPOSAL_STATES = new Set([
  "ready",
  "partially_accepted",
  "accepted",
  "rejected",
]);

export function reusableSyncProgressProposal(
  proposals: readonly IntelligenceProposalRecord[],
  revisionId: string,
): IntelligenceProposalRecord | null {
  return proposals.find((proposal) => (
    proposal.source_current
    && proposal.chapter_revision_id === revisionId
    && REUSABLE_SYNC_PROPOSAL_STATES.has(proposal.state)
  )) ?? null;
}
