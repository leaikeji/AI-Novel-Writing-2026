export type AssistantRequestContextPatch = Readonly<Record<string, unknown>>;

export interface AssistantRequestSnapshotInput {
  sessionId?: string;
  selectedAgent?: string;
}

export type AssistantRequestContextGetter = (
  input: AssistantRequestSnapshotInput,
) => AssistantRequestContextPatch | null | undefined;

type RequestPayloadTransformer = (
  args: QwenPawRequestPayloadArgs,
) => Record<string, unknown> | undefined;

interface RequestPayloadExtensionPoint {
  add: (
    pluginId: string,
    transformer: RequestPayloadTransformer,
    options?: { id?: string; order?: number },
  ) => QwenPawDisposable;
}

export interface AssistantRequestPayloadRegistrationOptions {
  pluginId: string;
  requestPayload: RequestPayloadExtensionPoint;
  getRequestContextPatch: AssistantRequestContextGetter;
  id?: string;
  order?: number;
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}


function hasEnumerableEntries(value: Readonly<Record<string, unknown>>): boolean {
  return Object.keys(value).length > 0;
}


/**
 * 构造发送时转换器。getter 只在每次发送时调用，避免在输入过程中复制正文。
 *
 * 这里不决定最终采用内联上下文还是 context_ref：调用方返回的 patch 可以是
 * 任意经过阶段 0B 门禁批准的 request_context 字段。若宿主已经提供了非对象形态的
 * request_context，则安全跳过注入，绝不覆盖宿主载荷。
 */
export function createAssistantRequestPayloadTransformer(
  getRequestContextPatch: AssistantRequestContextGetter,
): RequestPayloadTransformer {
  return (args) => {
    let patch: AssistantRequestContextPatch | null | undefined;
    try {
      patch = getRequestContextPatch({
        sessionId: args.sessionId,
        selectedAgent: args.selectedAgent,
      });
    } catch {
      // 页面上下文是增强信息；采集失败不能阻断宿主原生消息发送。
      return undefined;
    }

    if (!patch || !isRecord(patch) || !hasEnumerableEntries(patch)) {
      return undefined;
    }

    const existingRequestContext = args.payload.request_context;
    if (
      existingRequestContext !== undefined
      && !isRecord(existingRequestContext)
    ) {
      return undefined;
    }

    return {
      ...args.payload,
      request_context: {
        ...(existingRequestContext ?? {}),
        ...patch,
      },
    };
  };
}


export function registerAssistantRequestPayload(
  options: AssistantRequestPayloadRegistrationOptions,
): QwenPawDisposable {
  const transformer = createAssistantRequestPayloadTransformer(
    options.getRequestContextPatch,
  );
  return options.requestPayload.add(
    options.pluginId,
    transformer,
    {
      id: options.id ?? `${options.pluginId}.assistant-context`,
      order: options.order,
    },
  );
}
