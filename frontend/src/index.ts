import {
  APP_ID,
  APP_PATH,
  APP_ROUTE_ID,
  CORE_CHAT_ROUTE_ID,
} from "./contracts";
import { registerAssistantRouteWrap } from "./assistant-route-wrap";
import { registerAssistantRequestPayload } from "./assistant-request-payload";
import { createAssistantContextRefCoordinator } from "./assistant-context-ref";
import { createAssistantContextRefHttpClient } from "./assistant-context-transport";
import { assistantContextRuntime } from "./assistant-context-runtime";
import {
  AssistantProposalCoordinator,
  registerAssistantToolCard,
} from "./assistant-tool-card";
import { AssistantSelectionRegistry } from "./assistant-selection-registry";
import { createAssistantSuggestionRegistry } from "./assistant-suggestions";
import { AssistantSelectionController } from "./assistant-selection-controller";
import { AIEditTransactionManager } from "./assistant-transactions";
import { NovelLibraryPage } from "./creative-center";
import { NovelWorkbench } from "./workbench-v2";
import { activeWorkbenchRouteSession } from "./workbench-route";
import { ensureNovelStyles } from "./styles";


const React = window.QwenPaw.host.React;
const { message } = window.QwenPaw.host.antd;


ensureNovelStyles();


window.QwenPaw.chat.disposeAll(APP_ID);
const assistantSelectionRegistry = new AssistantSelectionRegistry();
const assistantSuggestionRegistry = createAssistantSuggestionRegistry(
  APP_ID,
  window.QwenPaw.chat.sender,
);
const assistantSelectionController = new AssistantSelectionController({
  runtime: assistantContextRuntime,
  registry: assistantSelectionRegistry,
  suggestions: assistantSuggestionRegistry,
  copyCommand: async (command) => {
    if (!navigator.clipboard?.writeText) {
      throw new Error("clipboard unavailable");
    }
    await navigator.clipboard.writeText(command);
    message.success("助手命令已复制，请在右侧输入框粘贴并发送");
  },
});
const assistantEditTransactions = new AIEditTransactionManager();
const assistantProposalCoordinator = new AssistantProposalCoordinator({
  runtime: assistantContextRuntime,
  registry: assistantSelectionRegistry,
  transactions: assistantEditTransactions,
});
const assistantContextRefCoordinator = createAssistantContextRefCoordinator({
  runtime: assistantContextRuntime,
  getRouteSession: activeWorkbenchRouteSession,
  createRef: createAssistantContextRefHttpClient(),
  bindSelectionForSend: (input) => (
    assistantSelectionController.bindSelectionForSend(input)
  ),
});
registerAssistantRequestPayload({
  pluginId: APP_ID,
  requestPayload: window.QwenPaw.chat.requestPayload,
  getRequestContextPatch: (input) => assistantContextRefCoordinator.requestPatch(input),
  order: 20,
});
registerAssistantToolCard({
  pluginId: APP_ID,
  toolName: "novel_prepare_selection_edit",
  toolRender: window.QwenPaw.chat.toolRender,
  React,
  coordinator: assistantProposalCoordinator,
  copyText: (text) => navigator.clipboard.writeText(text),
  getCurrentSessionId: () => window.QwenPaw.host.getCurrentSessionId(),
  onCopyError: () => message.error("复制失败，请手动选择候选文本"),
});

window.QwenPaw.route.add(APP_ID, {
  id: APP_ROUTE_ID,
  path: APP_PATH,
  component: NovelLibraryPage,
});

registerAssistantRouteWrap({
  pluginId: APP_ID,
  targetRouteId: CORE_CHAT_ROUTE_ID,
  route: window.QwenPaw.route,
  React,
  Workbench: NovelWorkbench,
  contextRefCoordinator: assistantContextRefCoordinator,
  selectionController: assistantSelectionController,
});
