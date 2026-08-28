export interface WorkbenchDocumentSurfaceLease {
  readonly documentId: string;
  readonly generation: number;
}


export function canReuseActiveDocumentLoad(input: Readonly<{
  requestedDocumentId: string;
  activeDocumentId: string | null;
  activeGeneration: number;
  surfaceLease: WorkbenchDocumentSurfaceLease | null;
}>): boolean {
  return input.requestedDocumentId.length > 0
    && input.activeDocumentId === input.requestedDocumentId
    && input.surfaceLease?.documentId === input.requestedDocumentId
    && input.surfaceLease.generation === input.activeGeneration;
}
