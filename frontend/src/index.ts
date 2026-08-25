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
import {
  SelectionEditRuntime,
  createSelectionEditReviewHost,
} from "./selection-edit-runtime";
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
const assistantEditTransactions = new AIEditTransactionManager();
let assistantSelectionController: AssistantSelectionController;
const selectionEditRuntime = new SelectionEditRuntime({
  contextRuntime: assistantContextRuntime,
  registry: assistantSelectionRegistry,
  transactions: assistantEditTransactions,
  copyText: (text) => navigator.clipboard.writeText(text),
  confirmExit: (prompt) => window.confirm(prompt),
  onAssistantFallback: (selectionId, operation) => {
    if (!assistantSelectionController.prepareAssistantFallback(selectionId, operation)) {
      message.error("选区已失效，请重新框选后再发送到助手");
      return;
    }
    message.info("已准备助手命令，请在右侧输入框中明确发送");
  },
});
assistantSelectionController = new AssistantSelectionController({
  runtime: assistantContextRuntime,
  registry: assistantSelectionRegistry,
  suggestions: assistantSuggestionRegistry,
  onStartEditorTask: (request) => selectionEditRuntime.start(request),
});
const SelectionEditReviewHost = createSelectionEditReviewHost(
  React,
  selectionEditRuntime,
);
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
  openReview: (candidate) => selectionEditRuntime.openBridgeCandidate(candidate),
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
  selectionEditReviewHost: SelectionEditReviewHost,
});
