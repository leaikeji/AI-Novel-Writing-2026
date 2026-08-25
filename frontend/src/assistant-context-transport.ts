import { apiRequest } from "./api";
import type {
  CreateAssistantContextRefInput,
  CreatedAssistantContextRef,
} from "./assistant-context-ref";


type AssistantApiRequest = (path: string, init?: RequestInit) => Promise<unknown>;


export interface AssistantContextRefHttpClientOptions {
  request?: AssistantApiRequest;
}


interface AssistantContextRefResponse {
  contextRef: string;
  expiresAt: string;
  contextRevision: number;
  payloadCharacters: number;
}


const CONTEXT_REF_PATTERN = /^[A-Za-z0-9_-]{43}$/;


function parseCreatedRef(value: unknown): CreatedAssistantContextRef {
  if (!value || typeof value !== "object") {
    throw new Error("invalid assistant context ref response");
  }
  const candidate = value as Partial<AssistantContextRefResponse>;
  if (typeof candidate.contextRef !== "string"
    || !CONTEXT_REF_PATTERN.test(candidate.contextRef)
    || typeof candidate.expiresAt !== "string"
    || !Number.isFinite(Date.parse(candidate.expiresAt))
    || !Number.isSafeInteger(candidate.contextRevision)
    || (candidate.contextRevision ?? -1) < 0
    || !Number.isSafeInteger(candidate.payloadCharacters)
    || (candidate.payloadCharacters ?? -1) < 0) {
    throw new Error("invalid assistant context ref response");
  }
  return {
    contextRef: candidate.contextRef,
    expiresAt: candidate.expiresAt,
    contextRevision: candidate.contextRevision,
    payloadCharacters: candidate.payloadCharacters,
  } as CreatedAssistantContextRef;
}


/** Create the narrow PawApp HTTP adapter used by the async ref coordinator. */
export function createAssistantContextRefHttpClient(
  options: AssistantContextRefHttpClientOptions = {},
): (
  input: CreateAssistantContextRefInput,
  signal: AbortSignal,
) => Promise<CreatedAssistantContextRef> {
  const request: AssistantApiRequest = options.request
    ?? ((path, init) => apiRequest<unknown>(path, init));
  return async (input, signal) => {
    const response = await request("/assistant-contexts", {
      method: "POST",
      signal,
      body: JSON.stringify({
        ownerToken: input.binding.ownerToken,
        tabInstance: input.binding.tabInstance,
        agentId: input.binding.agentId,
        novelId: input.binding.novelId,
        ...(input.binding.documentId
          ? { documentId: input.binding.documentId }
          : {}),
        ...(input.binding.sessionId
          ? { sessionId: input.binding.sessionId }
          : {}),
        snapshot: input.snapshot,
      }),
    });
    return parseCreatedRef(response);
  };
}
