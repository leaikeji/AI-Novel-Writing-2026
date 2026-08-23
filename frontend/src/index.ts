import {
  APP_ID,
  APP_PATH,
  APP_ROUTE_ID,
  CORE_CHAT_ROUTE_ID,
} from "./contracts";
import { NovelLibraryPage, NovelWorkbench } from "./workbench";
import { activeWorkbenchRoute } from "./workbench-route";


const React = window.QwenPaw.host.React;


function isNovelWorkbenchChat(): boolean {
  return activeWorkbenchRoute() !== null;
}


function wrapNativeChat(Inner: any) {
  return function NativeChatWithNovelWorkbench() {
    if (!isNovelWorkbenchChat()) {
      return React.createElement(Inner);
    }

    return React.createElement(
      "div",
      {
        "data-ai-novel-workbench": "active",
        style: {
          display: "grid",
          gridTemplateColumns: "minmax(620px, 62%) minmax(420px, 38%)",
          height: "100%",
          minHeight: 0,
          overflow: "hidden",
          background: "var(--ant-color-bg-container, transparent)",
        },
      },
      React.createElement(
        "section",
        { style: { minWidth: 0, minHeight: 0, overflow: "hidden" } },
        React.createElement(NovelWorkbench),
      ),
      React.createElement(
        "section",
        {
          "aria-label": "QwenPaw 原生 AI 助手",
          style: {
            minWidth: 0,
            minHeight: 0,
            overflow: "hidden",
            borderLeft: "1px solid var(--ant-color-border-secondary, #303030)",
          },
        },
        React.createElement(Inner),
      ),
    );
  };
}


window.QwenPaw.route.add(APP_ID, {
  id: APP_ROUTE_ID,
  path: APP_PATH,
  component: NovelLibraryPage,
});

window.QwenPaw.route.wrap(APP_ID, CORE_CHAT_ROUTE_ID, wrapNativeChat);
